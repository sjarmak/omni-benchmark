"""Freeze aggregate-only dual-scorer gold conformance for all of dev-A."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .autoresearch_config import AutoresearchError, _write_exclusive
from .content_policy import ContentPolicy
from .custody import CustodyError, load_dev_a_records
from .dev_a_baseline_scoring import (
    RELEASE_PATH,
    SELECTION_ROOT,
    UNSCORABLE_GOLD_FAILURES,
    DevABaselineScoringError,
    _committed_dev_a_inputs,
    _digest,
    _json,
    _private_file,
    _workspace,
)
from .scoring import OFFICIAL_SOFT_EX_VERSION, SENSITIVITY_SCORER_VERSION
from .sealed_scoring import (
    PostgreSQLIsolationProvider,
    ScoringMode,
    SealedQueryCase,
    score_query,
    validate_query_case,
)

QUESTION_COUNT = 154
SCHEMA_VERSION = 1
_RECEIPT_FIELDS = frozenset(
    {
        "dev_a_ids_sha256",
        "freeze_a_commit",
        "kind",
        "official",
        "question_count",
        "release_sha256",
        "schema_version",
        "sensitivity",
    }
)
_MODE_FIELDS = frozenset(
    {
        "failure_categories",
        "scoreable_questions",
        "scorer_identity",
        "scorer_version",
        "unscorable_questions",
    }
)


class DevAGoldConformanceError(RuntimeError):
    """Sanitized failure at the aggregate gold-conformance boundary."""


@dataclass(frozen=True)
class DevAGoldConformancePlan:
    """Exact dev-A gold cases, with all protected inputs hidden from repr."""

    dev_a_ids_sha256: str
    freeze_a_commit: str
    question_count: int
    release_sha256: str
    cases: tuple[SealedQueryCase, ...] = field(repr=False)


@dataclass(frozen=True)
class ModeGoldConformance:
    """Aggregate eligibility for one frozen scorer mode."""

    failure_categories: Mapping[str, int]
    scoreable_questions: int
    scorer_identity: str
    scorer_version: str
    unscorable_questions: int

    def as_dict(self) -> dict[str, object]:
        return {
            "failure_categories": dict(sorted(self.failure_categories.items())),
            "scoreable_questions": self.scoreable_questions,
            "scorer_identity": self.scorer_identity,
            "scorer_version": self.scorer_version,
            "unscorable_questions": self.unscorable_questions,
        }


@dataclass(frozen=True)
class DevAGoldConformanceResult:
    """Aggregate-only result; no question identity or outcome survives."""

    official: ModeGoldConformance
    sensitivity: ModeGoldConformance


def prepare_dev_a_gold_conformance_plan(
    workspace: Path,
    *,
    freeze_a_commit: str,
    expected_release_sha256: str,
    environment: Mapping[str, str] | None = None,
) -> DevAGoldConformancePlan:
    """Load exactly the released dev-A gold without reading candidate artifacts."""
    root = _workspace(workspace)
    release_sha256 = _digest(expected_release_sha256, "release SHA-256")
    policy = ContentPolicy.from_environment(
        os.environ if environment is None else environment
    )
    try:
        dev_a_ids, dev_a_ids_sha256, public_records = _committed_dev_a_inputs(
            root, freeze_a_commit, policy
        )
        release = _private_file(root, RELEASE_PATH, "dev-A release")
    except DevABaselineScoringError as error:
        raise DevAGoldConformanceError(str(error)) from error
    if len(dev_a_ids) != QUESTION_COUNT:
        raise DevAGoldConformanceError("dev-A membership must contain exactly 154 IDs")
    if hashlib.sha256(release).hexdigest() != release_sha256:
        raise DevAGoldConformanceError(
            "dev-A release does not match the expected release SHA-256"
        )
    try:
        labels = load_dev_a_records(root / RELEASE_PATH, dev_a_ids)
    except CustodyError as error:
        raise DevAGoldConformanceError(str(error)) from error
    if frozenset(labels) != dev_a_ids:
        raise DevAGoldConformanceError(
            "dev-A release does not exactly match committed dev-A membership"
        )
    cases = tuple(
        _case(public_records[instance_id], labels[instance_id])
        for instance_id in sorted(dev_a_ids)
    )
    try:
        for case in cases:
            validate_query_case(case)
    except (TypeError, ValueError) as error:
        raise DevAGoldConformanceError("invalid gold-conformance input") from error
    return DevAGoldConformancePlan(
        dev_a_ids_sha256=dev_a_ids_sha256,
        freeze_a_commit=freeze_a_commit,
        question_count=len(cases),
        release_sha256=release_sha256,
        cases=cases,
    )


def score_dev_a_gold_conformance(
    plan: DevAGoldConformancePlan,
    provider: PostgreSQLIsolationProvider,
) -> DevAGoldConformanceResult:
    """Execute gold only and retain aggregate closed-category counts."""
    if (
        not isinstance(plan, DevAGoldConformancePlan)
        or plan.question_count != QUESTION_COUNT
    ):
        raise DevAGoldConformanceError("gold-conformance plan is invalid")
    summaries: dict[ScoringMode, ModeGoldConformance] = {}
    for mode in (ScoringMode.OFFICIAL, ScoringMode.SENSITIVITY):
        failures: Counter[str] = Counter()
        scoreable = 0
        for case in plan.cases:
            result = score_query(case, mode, provider)
            identity, version = _scorer_identity(mode)
            if (result.scorer_identity, result.scorer_version) != (identity, version):
                raise DevAGoldConformanceError("frozen scorer identity is invalid")
            if result.outcome in {"correct", "wrong_answer"}:
                scoreable += 1
                continue
            if (
                result.outcome is None
                and result.failure_origin == "benchmark_infrastructure"
                and result.failure_class in UNSCORABLE_GOLD_FAILURES
            ):
                assert result.failure_class is not None
                failures[result.failure_class.value] += 1
                continue
            raise DevAGoldConformanceError(
                "infrastructure failure blocks gold-conformance publication"
            )
        summaries[mode] = ModeGoldConformance(
            failure_categories=dict(failures),
            scoreable_questions=scoreable,
            scorer_identity=identity,
            scorer_version=version,
            unscorable_questions=sum(failures.values()),
        )
    return DevAGoldConformanceResult(
        official=summaries[ScoringMode.OFFICIAL],
        sensitivity=summaries[ScoringMode.SENSITIVITY],
    )


def publish_dev_a_gold_conformance(
    workspace: Path,
    *,
    destination: Path,
    plan: DevAGoldConformancePlan,
    result: DevAGoldConformanceResult,
) -> dict[str, Any]:
    """Write one immutable aggregate receipt and return safe counts plus its hash."""
    root = _workspace(workspace)
    selected = _destination(destination)
    _validate_result(plan, result)
    payload = {
        "dev_a_ids_sha256": plan.dev_a_ids_sha256,
        "freeze_a_commit": plan.freeze_a_commit,
        "kind": "dev-a-gold-conformance",
        "official": result.official.as_dict(),
        "question_count": plan.question_count,
        "release_sha256": plan.release_sha256,
        "schema_version": SCHEMA_VERSION,
        "sensitivity": result.sensitivity.as_dict(),
    }
    content = _canonical(payload)
    try:
        stored = _write_exclusive(root / selected, content, workspace=root)
    except AutoresearchError as error:
        raise DevAGoldConformanceError(str(error)) from error
    digest = hashlib.sha256(content).hexdigest()
    return {
        "official_scoreable_questions": result.official.scoreable_questions,
        "path": stored.relative_to(root).as_posix(),
        "question_count": plan.question_count,
        "receipt_sha256": digest,
        "sensitivity_scoreable_questions": result.sensitivity.scoreable_questions,
    }


def load_dev_a_gold_conformance_receipt(
    workspace: Path,
    path: Path,
    *,
    expected_sha256: str,
    freeze_a_commit: str,
    release_sha256: str,
    dev_a_ids_sha256: str,
) -> tuple[int, int]:
    """Authenticate one aggregate receipt for use before candidate execution."""
    root = _workspace(workspace)
    selected = _destination(path)
    expected = _digest(expected_sha256, "gold-conformance receipt SHA-256")
    try:
        content = _private_file(root, selected, "gold-conformance receipt")
        value = _json(content, "gold-conformance receipt")
    except DevABaselineScoringError as error:
        raise DevAGoldConformanceError(str(error)) from error
    if hashlib.sha256(content).hexdigest() != expected:
        raise DevAGoldConformanceError("gold-conformance receipt hash does not match")
    if _canonical(value) != content:
        raise DevAGoldConformanceError("gold-conformance receipt is not canonical")
    if (
        not isinstance(value, Mapping)
        or set(value) != _RECEIPT_FIELDS
        or value.get("kind") != "dev-a-gold-conformance"
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("freeze_a_commit") != freeze_a_commit
        or value.get("release_sha256") != release_sha256
        or value.get("dev_a_ids_sha256") != dev_a_ids_sha256
        or value.get("question_count") != QUESTION_COUNT
    ):
        raise DevAGoldConformanceError("gold-conformance receipt identity is invalid")
    official = _mode_receipt(value.get("official"), ScoringMode.OFFICIAL)
    sensitivity = _mode_receipt(value.get("sensitivity"), ScoringMode.SENSITIVITY)
    return official, sensitivity


def _case(
    public_record: Mapping[str, Any], private_record: Mapping[str, Any]
) -> SealedQueryCase:
    return SealedQueryCase(
        database=str(public_record["selected_database"]),
        candidate_sql="SELECT 1",
        gold_sql=private_record["sol_sql"],
        preprocess_sql=public_record["preprocess_sql"],
        cleanup_sql=public_record["clean_up_sqls"],
        conditions=public_record["conditions"],
    )


def _validate_result(
    plan: DevAGoldConformancePlan, result: DevAGoldConformanceResult
) -> None:
    if not isinstance(result, DevAGoldConformanceResult):
        raise DevAGoldConformanceError("gold-conformance result is invalid")
    for summary in (result.official, result.sensitivity):
        if (
            summary.scoreable_questions < 1
            or summary.unscorable_questions < 0
            or summary.scoreable_questions + summary.unscorable_questions
            != plan.question_count
            or summary.unscorable_questions != sum(summary.failure_categories.values())
            or not set(summary.failure_categories).issubset(
                failure.value for failure in UNSCORABLE_GOLD_FAILURES
            )
        ):
            raise DevAGoldConformanceError("gold-conformance counts are invalid")


def _mode_receipt(value: object, mode: ScoringMode) -> int:
    identity, version = _scorer_identity(mode)
    if not isinstance(value, Mapping) or set(value) != _MODE_FIELDS:
        raise DevAGoldConformanceError("gold-conformance mode receipt is invalid")
    failures = value.get("failure_categories")
    scoreable = value.get("scoreable_questions")
    unscorable = value.get("unscorable_questions")
    if (
        not isinstance(failures, Mapping)
        or any(
            not isinstance(key, str) or type(count) is not int or count < 1
            for key, count in failures.items()
        )
        or not set(failures).issubset(
            failure.value for failure in UNSCORABLE_GOLD_FAILURES
        )
        or type(scoreable) is not int
        or scoreable < 1
        or type(unscorable) is not int
        or unscorable < 0
        or scoreable + unscorable != QUESTION_COUNT
        or sum(failures.values()) != unscorable
        or value.get("scorer_identity") != identity
        or value.get("scorer_version") != version
    ):
        raise DevAGoldConformanceError("gold-conformance mode receipt is invalid")
    return scoreable


def _scorer_identity(mode: ScoringMode) -> tuple[str, str]:
    return (
        ("official_soft_ex", OFFICIAL_SOFT_EX_VERSION)
        if mode is ScoringMode.OFFICIAL
        else ("sensitivity", SENSITIVITY_SCORER_VERSION)
    )


def _destination(value: Path) -> Path:
    selected = Path(value)
    if (
        selected.is_absolute()
        or selected.parent != SELECTION_ROOT
        or not selected.name.startswith("dev-a-gold-conformance-")
        or not selected.name.endswith(".json")
    ):
        raise DevAGoldConformanceError(
            "gold-conformance destination must be a confined state path"
        )
    return selected


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

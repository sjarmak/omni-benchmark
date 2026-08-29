"""Score the immutable public baseline against the authorized dev-A release."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifact_store import MAX_ARTIFACT_BYTES, ArtifactStore, ArtifactStoreError
from .content_policy import ContentPolicy
from .custody import CustodyError, load_dev_a_records
from .direct_question_loader import (
    DirectQuestionLoadError,
    _committed,
    _ids,
    _public_records,
    _validate_config_paths,
)
from .omni_result_adapter import (
    OmniResultContractError,
    decode_result_artifact_rows,
    reject_forbidden_keys,
)
from .scoring import OFFICIAL_SOFT_EX_VERSION, SENSITIVITY_SCORER_VERSION
from .sealed_scoring import (
    FailureClass,
    PostgreSQLIsolationProvider,
    ScoringMode,
    SealedQueryCase,
    SealedScoringResult,
    score_precomputed_result,
    score_query,
    system_no_answer,
    validate_query_case,
)

SELECTION_PATH = Path(
    "experiments/autoresearch/state/public-direct-baseline-freeze-v1.json"
)
SELECTION_ROOT = Path("experiments/autoresearch/state")
RELEASE_PATH = Path("data/private/dev-a/labels.jsonl")
DEV_A_IDS_PATH = Path("data/manifests/dev_a_ids.txt")
CONFIG_PATH = Path("config/autoresearch.json")
PUBLIC_MANIFEST_PATH = Path("data/manifests/eligible_questions.jsonl")
RAW_ROOT = Path("experiments/autoresearch/raw")
SCORE_SCHEMA_VERSION = "dev-a-frozen-baseline-score-v2"
RECEIPT_SCHEMA_VERSION = "dev-a-frozen-baseline-score-receipt-v2"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
PATH_COMPONENT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
SELECTION_FIELDS = frozenset(
    {
        "continuation_manifest_sha256",
        "continuation_run_id",
        "counts",
        "entries",
        "exclusion_manifest_sha256",
        "kind",
        "original_run_id",
        "schema_version",
        "source_commit",
        "source_schedule_sha256",
    }
)
ENTRY_FIELDS = frozenset(
    {
        "condition",
        "database",
        "disposition",
        "generation_sha256",
        "instance_id",
        "original_action",
        "repetition",
        "run_manifest_sha256",
        "selected_attempt_id",
        "trial_key",
    }
)
C4_SELECTION_FIELDS = frozenset(
    {
        "artifact_file_count",
        "artifact_inventory_sha256",
        "counts",
        "deployment_sha256",
        "eligible_manifest_sha256",
        "entries",
        "execution_plan_sha256",
        "kind",
        "output_root",
        "run_id",
        "schema_version",
        "source_commit",
        "source_schedule_sha256",
        "train_ids_sha256",
    }
)
C4_ENTRY_FIELDS = frozenset(
    {
        "attempt_id",
        "condition",
        "database",
        "generation_sha256",
        "instance_id",
        "repetition",
        "run_manifest_sha256",
    }
)
RUN_REQUIRED_FIELDS = frozenset(
    {
        "condition",
        "generation_sha256",
        "git_commit",
        "repetition",
        "schema_version",
        "scope",
    }
)
UNSCORABLE_GOLD_FAILURES = frozenset(
    {
        FailureClass.GOLD_QUERY_MISSING,
        FailureClass.GOLD_TIMEOUT,
        FailureClass.GOLD_STATEMENT_ERROR,
        FailureClass.GOLD_NO_RESULT,
        FailureClass.GOLD_RESULT_OVERFLOW,
    }
)


class DevABaselineScoringError(RuntimeError):
    """Sanitized failure at the dev-A scoring custody boundary."""


@dataclass(frozen=True)
class PreparedDevAAttempt:
    """One hash-bound frozen attempt; SQL is absent from representations."""

    attempt_id: str
    condition: str
    generation_sha256: str
    generation_record_sha256: str
    question_key: str
    case: SealedQueryCase = field(repr=False)
    candidate_rows: tuple[tuple[Any, ...], ...] | None = field(default=None, repr=False)
    no_answer_failure: FailureClass | None = None


@dataclass(frozen=True)
class DevABaselinePlan:
    """Fully validated scorer inputs, including private SQL hidden from repr."""

    selection_sha256: str
    release_sha256: str
    dev_a_ids_sha256: str
    freeze_a_commit: str
    released_question_count: int
    selected_question_count: int
    unrepresented_question_count: int
    attempts: tuple[PreparedDevAAttempt, ...] = field(repr=False)


@dataclass(frozen=True)
class ModeAttemptScore:
    """One mode's scored result or frozen gold-unscorable disposition."""

    result: SealedScoringResult | None = None
    unscorable_failure: FailureClass | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.unscorable_failure is None):
            raise ValueError("exactly one score disposition must be set")
        if (
            self.unscorable_failure is not None
            and self.unscorable_failure not in UNSCORABLE_GOLD_FAILURES
        ):
            raise ValueError("unscorable failure is outside the frozen rule")

    @property
    def status(self) -> str:
        return "scored" if self.result is not None else "unscorable"


@dataclass(frozen=True)
class DevAAttemptResult:
    """Permitted SQL-free results for one frozen attempt."""

    attempt: PreparedDevAAttempt
    official: ModeAttemptScore
    sensitivity: ModeAttemptScore


@dataclass(frozen=True)
class DevABaselineResults:
    """Complete paired result set, unavailable when infrastructure failed."""

    attempts: tuple[DevAAttemptResult, ...]

    def scoreable_question_count(self, mode: ScoringMode) -> int:
        """Count unique represented questions eligible under one frozen scorer."""
        if not isinstance(mode, ScoringMode):
            raise DevABaselineScoringError("scoring mode is invalid")
        return len(
            {
                item.attempt.question_key
                for item in self.attempts
                if _mode_score(item, mode).result is not None
            }
        )


@dataclass(frozen=True)
class _SelectionEntry:
    condition: str
    database: str
    generation_sha256: str
    instance_id: str
    repetition: int
    run_manifest_sha256: str
    run_id: str
    selected_attempt_id: str
    trial_key: str


def prepare_dev_a_baseline_plan(
    workspace: Path,
    *,
    artifact_workspace: Path | None = None,
    freeze_a_commit: str,
    selection_path: Path = SELECTION_PATH,
    expected_selection_sha256: str,
    expected_release_sha256: str,
    environment: Mapping[str, str] | None = None,
) -> DevABaselinePlan:
    """Validate public artifacts separately from the dev-A custody workspace."""
    root = _workspace(workspace)
    artifact_root = (
        root if artifact_workspace is None else _workspace(artifact_workspace)
    )
    selection_digest = _digest(expected_selection_sha256, "selection SHA-256")
    release_digest = _digest(expected_release_sha256, "release SHA-256")
    policy = ContentPolicy.from_environment(
        os.environ if environment is None else environment
    )

    selected_path = _confined_selection_path(selection_path)
    selection_bytes = _private_file(artifact_root, selected_path, "selection manifest")
    if hashlib.sha256(selection_bytes).hexdigest() != selection_digest:
        raise DevABaselineScoringError(
            "selection manifest does not match the expected selection SHA-256"
        )
    selection, entries, required_conditions = _selection(selection_bytes, policy)
    dev_a_ids, dev_a_ids_sha256, public_records = _committed_dev_a_inputs(
        root, freeze_a_commit, policy
    )
    selected_entries = tuple(
        entry for entry in entries if entry.instance_id in dev_a_ids
    )
    selected_ids = frozenset(entry.instance_id for entry in selected_entries)
    _validate_selected_schedule(
        selected_entries, selected_ids, required_conditions=required_conditions
    )

    prepared_public = tuple(
        _prepare_public_attempt(
            artifact_root,
            selection=selection,
            entry=entry,
            public_record=public_records[entry.instance_id],
            policy=policy,
        )
        for entry in selected_entries
    )

    release_bytes = _private_file(root, RELEASE_PATH, "dev-A release")
    if hashlib.sha256(release_bytes).hexdigest() != release_digest:
        raise DevABaselineScoringError(
            "dev-A release does not match the expected release SHA-256"
        )
    try:
        labels = load_dev_a_records(root / RELEASE_PATH, dev_a_ids)
    except CustodyError as error:
        raise DevABaselineScoringError(str(error)) from error
    if frozenset(labels) != dev_a_ids:
        raise DevABaselineScoringError(
            "dev-A release does not exactly match committed dev-A membership"
        )

    attempts = tuple(
        _attach_gold(attempt, public_records[attempt.instance_id], labels)
        for attempt in prepared_public
    )
    for attempt in attempts:
        try:
            validate_query_case(attempt.case)
        except (TypeError, ValueError) as error:
            raise DevABaselineScoringError("invalid scoring input") from error
    return DevABaselinePlan(
        selection_sha256=selection_digest,
        release_sha256=release_digest,
        dev_a_ids_sha256=dev_a_ids_sha256,
        freeze_a_commit=freeze_a_commit,
        released_question_count=len(dev_a_ids),
        selected_question_count=len(selected_ids),
        unrepresented_question_count=len(dev_a_ids - selected_ids),
        attempts=attempts,
    )


def score_dev_a_baseline_plan(
    plan: DevABaselinePlan,
    provider: PostgreSQLIsolationProvider,
    *,
    expected_scoreable_question_counts: tuple[int, int] | None = None,
) -> DevABaselineResults:
    """Freeze gold eligibility for both modes, then score eligible candidates."""
    if not isinstance(plan, DevABaselinePlan):
        raise DevABaselineScoringError("scoring plan is invalid")
    try:
        for attempt in plan.attempts:
            validate_query_case(attempt.case)
    except (TypeError, ValueError) as error:
        raise DevABaselineScoringError("invalid scoring input") from error

    eligibility = _freeze_gold_conformance(plan, provider)
    if expected_scoreable_question_counts is not None:
        if (
            not isinstance(expected_scoreable_question_counts, tuple)
            or len(expected_scoreable_question_counts) != 2
            or any(
                type(value) is not int or value < 1
                for value in expected_scoreable_question_counts
            )
        ):
            raise DevABaselineScoringError("authorized denominator is invalid")
        observed = tuple(
            sum(
                failure is None
                for (question_key, selected_mode), failure in eligibility.items()
                if selected_mode is mode
            )
            for mode in (ScoringMode.OFFICIAL, ScoringMode.SENSITIVITY)
        )
        if observed != expected_scoreable_question_counts:
            raise DevABaselineScoringError(
                "scoreable questions do not match the authorized denominator"
            )
    scored: list[DevAAttemptResult] = []
    for attempt in plan.attempts:
        official = _score_eligible_attempt(
            attempt,
            ScoringMode.OFFICIAL,
            eligibility[(attempt.question_key, ScoringMode.OFFICIAL)],
            provider,
        )
        sensitivity = _score_eligible_attempt(
            attempt,
            ScoringMode.SENSITIVITY,
            eligibility[(attempt.question_key, ScoringMode.SENSITIVITY)],
            provider,
        )
        scored.append(
            DevAAttemptResult(
                attempt=attempt,
                official=official,
                sensitivity=sensitivity,
            )
        )
    return DevABaselineResults(attempts=tuple(scored))


def require_scoreable_question_counts(
    results: DevABaselineResults,
    *,
    official: int,
    sensitivity: int,
) -> None:
    """Bind publication to the exact human-authorized coverage denominators."""
    if type(official) is not int or official < 1:
        raise DevABaselineScoringError("authorized denominator is invalid")
    if type(sensitivity) is not int or sensitivity < 1:
        raise DevABaselineScoringError("authorized denominator is invalid")
    observed = (
        results.scoreable_question_count(ScoringMode.OFFICIAL),
        results.scoreable_question_count(ScoringMode.SENSITIVITY),
    )
    if observed != (official, sensitivity):
        raise DevABaselineScoringError(
            "scoreable questions do not match the authorized denominator"
        )


def _freeze_gold_conformance(
    plan: DevABaselinePlan,
    provider: PostgreSQLIsolationProvider,
) -> dict[tuple[str, ScoringMode], FailureClass | None]:
    representatives: dict[str, PreparedDevAAttempt] = {}
    for attempt in plan.attempts:
        prior = representatives.setdefault(attempt.question_key, attempt)
        if not _same_question_case(prior.case, attempt.case):
            raise DevABaselineScoringError(
                "represented question has inconsistent scoring inputs"
            )

    eligibility: dict[tuple[str, ScoringMode], FailureClass | None] = {}
    for question_key, attempt in representatives.items():
        conformance_case = SealedQueryCase(
            database=attempt.case.database,
            candidate_sql="SELECT 1",
            gold_sql=attempt.case.gold_sql,
            preprocess_sql=attempt.case.preprocess_sql,
            cleanup_sql=attempt.case.cleanup_sql,
            conditions=attempt.case.conditions,
        )
        for mode in (ScoringMode.OFFICIAL, ScoringMode.SENSITIVITY):
            result = score_query(conformance_case, mode, provider)
            _require_scorer_identity(result, mode)
            if (
                result.outcome is None
                and result.failure_origin == "benchmark_infrastructure"
                and result.failure_class in UNSCORABLE_GOLD_FAILURES
            ):
                eligibility[(question_key, mode)] = result.failure_class
            elif result.outcome in {"correct", "wrong_answer"}:
                eligibility[(question_key, mode)] = None
            else:
                raise DevABaselineScoringError(
                    "infrastructure failure blocks dev-A score publication"
                )
    return eligibility


def _score_eligible_attempt(
    attempt: PreparedDevAAttempt,
    mode: ScoringMode,
    unscorable_failure: FailureClass | None,
    provider: PostgreSQLIsolationProvider,
) -> ModeAttemptScore:
    if unscorable_failure is not None:
        return ModeAttemptScore(unscorable_failure=unscorable_failure)
    if attempt.candidate_rows is not None:
        result = score_precomputed_result(
            attempt.case, attempt.candidate_rows, mode, provider
        )
    elif attempt.no_answer_failure is None:
        result = score_query(attempt.case, mode, provider)
    else:
        result = system_no_answer(mode, failure_class=attempt.no_answer_failure)
    _require_publishable(result, mode)
    return ModeAttemptScore(result=result)


def _same_question_case(left: SealedQueryCase, right: SealedQueryCase) -> bool:
    return (
        left.database == right.database
        and left.gold_sql == right.gold_sql
        and left.preprocess_sql == right.preprocess_sql
        and left.cleanup_sql == right.cleanup_sql
        and left.conditions == right.conditions
    )


def publish_dev_a_baseline_results(
    workspace: Path,
    *,
    output_root: Path,
    plan: DevABaselinePlan,
    results: DevABaselineResults,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Publish two SQL-free immutable score artifacts and a safe receipt."""
    root = _workspace(workspace)
    _validate_result_alignment(plan, results)
    official_payload = _score_payload(plan, results, ScoringMode.OFFICIAL)
    sensitivity_payload = _score_payload(plan, results, ScoringMode.SENSITIVITY)
    try:
        store = ArtifactStore(
            root,
            Path(output_root),
            environment=environment,
            require_new_root=True,
        )
        official = store.write_json(Path("official.score.json"), official_payload)
        sensitivity = store.write_json(
            Path("sensitivity.score.json"), sensitivity_payload
        )
        receipt = _receipt(
            root,
            Path(output_root),
            plan,
            results,
            official_sha256=official.sha256,
            sensitivity_sha256=sensitivity.sha256,
        )
        stored_receipt = store.write_json(Path("receipt.json"), receipt)
    except ArtifactStoreError as error:
        raise DevABaselineScoringError(str(error)) from error
    return receipt | {"receipt_sha256": stored_receipt.sha256}


def _committed_dev_a_inputs(
    workspace: Path,
    freeze_a_commit: str,
    policy: ContentPolicy,
) -> tuple[frozenset[str], str, dict[str, dict[str, Any]]]:
    if (
        not isinstance(freeze_a_commit, str)
        or COMMIT_PATTERN.fullmatch(freeze_a_commit) is None
    ):
        raise DevABaselineScoringError(
            "Freeze-A commit must be the full canonical hash"
        )
    try:
        canonical = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", f"{freeze_a_commit}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise DevABaselineScoringError("cannot verify Freeze-A commit") from error
    if canonical != freeze_a_commit:
        raise DevABaselineScoringError(
            "Freeze-A commit must be the full canonical hash"
        )
    try:
        config = _committed(workspace, freeze_a_commit, CONFIG_PATH)
        _validate_config_paths(config.content, policy)
        committed_ids = _committed(workspace, freeze_a_commit, DEV_A_IDS_PATH)
        dev_a_ids = _ids(committed_ids.content, "dev-a")
        public_manifest = _committed(workspace, freeze_a_commit, PUBLIC_MANIFEST_PATH)
        public_records = _public_records(public_manifest.content, policy)
    except DirectQuestionLoadError as error:
        raise DevABaselineScoringError(str(error)) from error
    current_ids = _workspace_file(workspace, DEV_A_IDS_PATH, "dev-A ID manifest")
    if current_ids != committed_ids.content:
        raise DevABaselineScoringError(
            "dev-A ID manifest does not match the Freeze-A commit"
        )
    if not dev_a_ids.issubset(public_records):
        raise DevABaselineScoringError(
            "committed dev-A IDs are absent from the public manifest"
        )
    return dev_a_ids, hashlib.sha256(current_ids).hexdigest(), public_records


def _selection(
    content: bytes, policy: ContentPolicy
) -> tuple[Mapping[str, Any], tuple[_SelectionEntry, ...], tuple[str, ...]]:
    value = _json(content, "selection manifest")
    if isinstance(value, Mapping) and value.get("kind") in {
        "public-c4-baseline-freeze",
        "e02-dev-a-c4-freeze",
    }:
        return _c4_selection(value, policy)
    if not isinstance(value, Mapping) or set(value) != SELECTION_FIELDS:
        raise DevABaselineScoringError("selection manifest must use the exact schema")
    reject_forbidden_keys(value)
    if policy.sanitize_json(value) != value:
        raise DevABaselineScoringError("selection manifest contains sensitive content")
    if value["schema_version"] != 1 or value["kind"] != "public-direct-baseline-freeze":
        raise DevABaselineScoringError("selection manifest identity is invalid")
    source_commit = value["source_commit"]
    if (
        not isinstance(source_commit, str)
        or COMMIT_PATTERN.fullmatch(source_commit) is None
    ):
        raise DevABaselineScoringError("selection source commit is invalid")
    for digest_field in (
        "continuation_manifest_sha256",
        "exclusion_manifest_sha256",
        "source_schedule_sha256",
    ):
        _digest(value[digest_field], f"selection {digest_field}")
    original_run_id = _path_component(value["original_run_id"], "original run ID")
    continuation_run_id = _path_component(
        value["continuation_run_id"], "continuation run ID"
    )
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise DevABaselineScoringError("selection entries must be a non-empty array")
    entries = tuple(
        _selection_entry(item, original_run_id, continuation_run_id)
        for item in raw_entries
    )
    if len({entry.trial_key for entry in entries}) != len(entries):
        raise DevABaselineScoringError("selection has duplicate trial keys")
    if len({entry.selected_attempt_id for entry in entries}) != len(entries):
        raise DevABaselineScoringError("selection has duplicate selected attempts")
    counts = value["counts"]
    dispositions = Counter(item["disposition"] for item in raw_entries)
    if (
        not isinstance(counts, Mapping)
        or set(counts) != {"continuation", "preserved", "total"}
        or counts["continuation"] != dispositions["continuation"]
        or counts["preserved"] != dispositions["preserved"]
        or counts["total"] != len(entries)
    ):
        raise DevABaselineScoringError("selection counts do not match entries")
    return value, entries, ("C1", "C2", "C3")


def _c4_selection(
    value: Mapping[str, Any], policy: ContentPolicy
) -> tuple[Mapping[str, Any], tuple[_SelectionEntry, ...], tuple[str, ...]]:
    if set(value) != C4_SELECTION_FIELDS:
        raise DevABaselineScoringError(
            "C4 selection manifest must use the exact schema"
        )
    reject_forbidden_keys(value)
    if policy.sanitize_json(value) != value:
        raise DevABaselineScoringError(
            "C4 selection manifest contains sensitive content"
        )
    if value["schema_version"] != 1:
        raise DevABaselineScoringError("C4 selection manifest identity is invalid")
    source_commit = value["source_commit"]
    if (
        not isinstance(source_commit, str)
        or COMMIT_PATTERN.fullmatch(source_commit) is None
    ):
        raise DevABaselineScoringError("C4 selection source commit is invalid")
    for field_name in (
        "artifact_inventory_sha256",
        "deployment_sha256",
        "eligible_manifest_sha256",
        "execution_plan_sha256",
        "source_schedule_sha256",
        "train_ids_sha256",
    ):
        _digest(value[field_name], f"C4 selection {field_name}")
    run_id = _path_component(value["run_id"], "C4 selection run ID")
    if value["output_root"] != (RAW_ROOT / run_id).as_posix():
        raise DevABaselineScoringError("C4 selection output root is invalid")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise DevABaselineScoringError("C4 selection entries must be a non-empty array")
    entries = tuple(_c4_selection_entry(item, run_id) for item in raw_entries)
    if len({entry.trial_key for entry in entries}) != len(entries):
        raise DevABaselineScoringError("C4 selection has duplicate trial keys")
    if len({entry.selected_attempt_id for entry in entries}) != len(entries):
        raise DevABaselineScoringError("C4 selection has duplicate attempts")
    counts = value["counts"]
    if (
        not isinstance(counts, Mapping)
        or set(counts) != {"answered", "attempts", "databases", "errored", "refused"}
        or any(type(item) is not int or item < 0 for item in counts.values())
        or counts["attempts"] != len(entries)
        or counts["databases"] != len({entry.database for entry in entries})
        or counts["answered"] + counts["errored"] + counts["refused"] != len(entries)
        or type(value["artifact_file_count"]) is not int
        or value["artifact_file_count"] < 2 * len(entries)
    ):
        raise DevABaselineScoringError("C4 selection counts do not match entries")
    return value, entries, ("C4",)


def _c4_selection_entry(value: object, run_id: str) -> _SelectionEntry:
    if not isinstance(value, Mapping) or set(value) != C4_ENTRY_FIELDS:
        raise DevABaselineScoringError("C4 selection entry must use the exact schema")
    if value["condition"] != "C4" or value["repetition"] != 1:
        raise DevABaselineScoringError("C4 selection attempt identity is invalid")
    instance_id = _path_component(value["instance_id"], "C4 selection instance ID")
    database = _path_component(value["database"], "C4 selection database")
    trial_key = f"{instance_id}:C4:1"
    attempt_id = f"{run_id}:{trial_key}"
    if value["attempt_id"] != attempt_id:
        raise DevABaselineScoringError("C4 selection attempt identity is invalid")
    return _SelectionEntry(
        condition="C4",
        database=database,
        generation_sha256=_digest(value["generation_sha256"], "generation SHA-256"),
        instance_id=instance_id,
        repetition=1,
        run_manifest_sha256=_digest(
            value["run_manifest_sha256"], "run manifest SHA-256"
        ),
        run_id=run_id,
        selected_attempt_id=attempt_id,
        trial_key=trial_key,
    )


def _selection_entry(
    value: object, original_run_id: str, continuation_run_id: str
) -> _SelectionEntry:
    if not isinstance(value, Mapping) or set(value) != ENTRY_FIELDS:
        raise DevABaselineScoringError("selection entry must use the exact schema")
    condition = value["condition"]
    if condition not in {"C1", "C2", "C3"}:
        raise DevABaselineScoringError("selection condition is invalid")
    repetition = value["repetition"]
    if type(repetition) is not int or repetition != 1:
        raise DevABaselineScoringError("selection repetition is invalid")
    instance_id = _path_component(value["instance_id"], "selection instance ID")
    database = _path_component(value["database"], "selection database")
    trial_key = f"{instance_id}:{condition}:{repetition}"
    if value["trial_key"] != trial_key:
        raise DevABaselineScoringError("selection trial key is invalid")
    disposition = value["disposition"]
    action = value["original_action"]
    if (disposition, action) not in {
        ("preserved", "preserve"),
        ("continuation", "never_attempted"),
        ("continuation", "rerun_infrastructure"),
    }:
        raise DevABaselineScoringError("selection disposition is invalid")
    run_id = original_run_id if disposition == "preserved" else continuation_run_id
    selected_attempt_id = value["selected_attempt_id"]
    if selected_attempt_id != f"{run_id}:{trial_key}":
        raise DevABaselineScoringError("selection attempt identity is invalid")
    return _SelectionEntry(
        condition=condition,
        database=database,
        generation_sha256=_digest(value["generation_sha256"], "generation SHA-256"),
        instance_id=instance_id,
        repetition=repetition,
        run_manifest_sha256=_digest(
            value["run_manifest_sha256"], "run manifest SHA-256"
        ),
        run_id=run_id,
        selected_attempt_id=selected_attempt_id,
        trial_key=trial_key,
    )


def _validate_selected_schedule(
    entries: Sequence[_SelectionEntry],
    selected_ids: frozenset[str],
    *,
    required_conditions: tuple[str, ...],
) -> None:
    by_id: Counter[str] = Counter(entry.instance_id for entry in entries)
    if any(
        by_id[instance_id] != len(required_conditions) for instance_id in selected_ids
    ):
        raise DevABaselineScoringError(
            "represented dev-A questions must have every frozen condition"
        )
    expected = {
        (instance_id, condition)
        for instance_id in selected_ids
        for condition in required_conditions
    }
    observed = {(entry.instance_id, entry.condition) for entry in entries}
    if observed != expected:
        raise DevABaselineScoringError("selected dev-A schedule is incomplete")


@dataclass(frozen=True)
class _PublicAttempt:
    attempt_id: str
    condition: str
    generation_sha256: str
    generation_record_sha256: str
    instance_id: str
    generated_sql: str | tuple[()] = field(repr=False)
    candidate_rows: tuple[tuple[Any, ...], ...] | None = field(repr=False)
    no_answer_failure: FailureClass | None


def _prepare_public_attempt(
    workspace: Path,
    *,
    selection: Mapping[str, Any],
    entry: _SelectionEntry,
    public_record: Mapping[str, Any],
    policy: ContentPolicy,
) -> _PublicAttempt:
    if public_record["selected_database"] != entry.database:
        raise DevABaselineScoringError(
            "selection database does not match the committed public question"
        )
    root = (
        RAW_ROOT
        / entry.run_id
        / entry.database
        / entry.condition.lower()
        / f"{entry.instance_id}-r{entry.repetition}"
    )
    generation = _private_file(
        workspace, root / "generation.jsonl", "frozen generation artifact"
    )
    if hashlib.sha256(generation).hexdigest() != entry.generation_sha256:
        raise DevABaselineScoringError(
            "frozen generation does not match the selection manifest"
        )
    lines = generation.splitlines(keepends=True)
    if len(lines) != 1 or not lines[0].endswith(b"\n"):
        raise DevABaselineScoringError(
            "frozen generation must contain one canonical record"
        )
    record = _json(lines[0], "frozen generation record")
    if not isinstance(record, Mapping):
        raise DevABaselineScoringError("frozen generation record must be an object")
    reject_forbidden_keys(record)
    if policy.sanitize_json(record) != record:
        raise DevABaselineScoringError("frozen generation contains sensitive content")
    expected = {
        "attempt_id": entry.selected_attempt_id,
        "condition": entry.condition,
        "instance_id": entry.instance_id,
        "partition": "train",
        "question": public_record["query"],
        "repetition": entry.repetition,
        "run_id": entry.run_id,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise DevABaselineScoringError(
            "frozen generation identity does not match selection"
        )
    outcome = record.get("generation_outcome")
    if outcome not in {"answered", "errored", "refused"}:
        raise DevABaselineScoringError("frozen generation outcome is invalid")
    candidate, candidate_rows, failure = _candidate_input(
        workspace,
        root=root,
        condition=entry.condition,
        outcome=outcome,
        record=record,
    )

    run = _private_file(workspace, root / "run.json", "run manifest")
    if hashlib.sha256(run).hexdigest() != entry.run_manifest_sha256:
        raise DevABaselineScoringError(
            "run manifest does not match the selection manifest"
        )
    manifest = _json(run, "run manifest")
    if not isinstance(manifest, Mapping) or not RUN_REQUIRED_FIELDS.issubset(manifest):
        raise DevABaselineScoringError("run manifest is invalid")
    reject_forbidden_keys(manifest)
    expected_manifest = {
        "condition": entry.condition,
        "generation_sha256": entry.generation_sha256,
        "git_commit": selection["source_commit"],
        "repetition": entry.repetition,
        "scope": "train",
    }
    if any(manifest.get(key) != value for key, value in expected_manifest.items()):
        raise DevABaselineScoringError("run manifest identity does not match selection")
    if type(manifest.get("schema_version")) is not int:
        raise DevABaselineScoringError("run manifest schema version is invalid")
    return _PublicAttempt(
        attempt_id=entry.selected_attempt_id,
        condition=entry.condition,
        generation_sha256=entry.generation_sha256,
        generation_record_sha256=hashlib.sha256(lines[0]).hexdigest(),
        instance_id=entry.instance_id,
        generated_sql=candidate,
        candidate_rows=candidate_rows,
        no_answer_failure=failure,
    )


def _candidate_input(
    workspace: Path,
    *,
    root: Path,
    condition: str,
    outcome: str,
    record: Mapping[str, Any],
) -> tuple[str | tuple[()], tuple[tuple[Any, ...], ...] | None, FailureClass | None]:
    if condition == "C4":
        return _c4_candidate_input(workspace, root=root, outcome=outcome, record=record)
    generated_sql = record.get("generated_sql")
    if generated_sql is None or (
        isinstance(generated_sql, str) and not generated_sql.strip()
    ):
        failure = (
            FailureClass.AGENT_REFUSAL
            if outcome == "refused"
            else FailureClass.NO_QUERY
        )
        return (), None, failure
    if not isinstance(generated_sql, str):
        raise DevABaselineScoringError("generated SQL has an invalid type")
    return generated_sql, None, None


def _c4_candidate_input(
    workspace: Path,
    *,
    root: Path,
    outcome: str,
    record: Mapping[str, Any],
) -> tuple[tuple[()], tuple[tuple[Any, ...], ...] | None, FailureClass | None]:
    if record.get("generated_sql") is not None:
        raise DevABaselineScoringError("C4 generation must not contain direct SQL")
    if outcome != "answered":
        if (
            outcome != "errored"
            or record.get("failure_origin") != "evaluated_system"
            or record.get("terminal_failure_class") != "omni_job_terminal_failure"
        ):
            raise DevABaselineScoringError(
                "C4 terminal generation is not an evaluated-system outcome"
            )
        return (), None, FailureClass.CANDIDATE_EXECUTION_ERROR
    expected_path = root / "answer.result.json"
    expected_relative = expected_path.as_posix()
    digest = record.get("result_artifact_sha256")
    if (
        not isinstance(record.get("generated_query"), str)
        or not record["generated_query"].strip()
        or record.get("failure_origin") is not None
        or record.get("harness_failure") is not None
        or record.get("query_unavailable_reason") is not None
        or record.get("terminal_failure_class") is not None
        or record.get("actual_result_status") != "complete"
        or record.get("execution_status") != "complete"
        or record.get("result_artifact_schema_version") != 1
        or record.get("result_artifact_path") != expected_relative
        or record.get("actual_result_hash") != digest
    ):
        raise DevABaselineScoringError("C4 result artifact binding is invalid")
    expected_digest = _digest(digest, "C4 result artifact SHA-256")
    content = _private_file(workspace, expected_path, "C4 result artifact")
    if hashlib.sha256(content).hexdigest() != expected_digest:
        raise DevABaselineScoringError("C4 result artifact does not match its binding")
    artifact = _json(content, "C4 result artifact")
    try:
        rows = decode_result_artifact_rows(artifact)
    except OmniResultContractError as error:
        raise DevABaselineScoringError("C4 result artifact is invalid") from error
    return (), rows, None


def _attach_gold(
    attempt: _PublicAttempt,
    public_record: Mapping[str, Any],
    labels: Mapping[str, Mapping[str, Any]],
) -> PreparedDevAAttempt:
    private_record = labels[attempt.instance_id]
    if attempt.candidate_rows is not None and (
        public_record["preprocess_sql"] or public_record["clean_up_sqls"]
    ):
        raise DevABaselineScoringError(
            "precomputed C4 result requires a stateless public scoring case"
        )
    return PreparedDevAAttempt(
        attempt_id=attempt.attempt_id,
        condition=attempt.condition,
        generation_sha256=attempt.generation_sha256,
        generation_record_sha256=attempt.generation_record_sha256,
        question_key=hashlib.sha256(attempt.instance_id.encode("utf-8")).hexdigest(),
        case=SealedQueryCase(
            database=str(public_record["selected_database"]),
            candidate_sql=attempt.generated_sql,
            gold_sql=private_record["sol_sql"],
            preprocess_sql=public_record["preprocess_sql"],
            cleanup_sql=public_record["clean_up_sqls"],
            conditions=public_record["conditions"],
        ),
        candidate_rows=attempt.candidate_rows,
        no_answer_failure=attempt.no_answer_failure,
    )


def _require_publishable(result: SealedScoringResult, mode: ScoringMode) -> None:
    _require_scorer_identity(result, mode)
    if result.outcome is None or result.failure_origin == "benchmark_infrastructure":
        raise DevABaselineScoringError(
            "infrastructure failure blocks dev-A score publication"
        )


def _require_scorer_identity(result: SealedScoringResult, mode: ScoringMode) -> None:
    expected = (
        ("official_soft_ex", OFFICIAL_SOFT_EX_VERSION)
        if mode is ScoringMode.OFFICIAL
        else ("sensitivity", SENSITIVITY_SCORER_VERSION)
    )
    if (result.scorer_identity, result.scorer_version) != expected:
        raise DevABaselineScoringError("frozen scorer identity is invalid")


def _mode_score(item: DevAAttemptResult, mode: ScoringMode) -> ModeAttemptScore:
    return item.official if mode is ScoringMode.OFFICIAL else item.sensitivity


def _validate_result_alignment(
    plan: DevABaselinePlan, results: DevABaselineResults
) -> None:
    if not isinstance(results, DevABaselineResults):
        raise DevABaselineScoringError("scoring results are invalid")
    if len(results.attempts) != len(plan.attempts) or any(
        item.attempt is not expected
        for item, expected in zip(results.attempts, plan.attempts, strict=True)
    ):
        raise DevABaselineScoringError("scoring results do not match the plan")
    eligibility: dict[tuple[str, ScoringMode], FailureClass | None] = {}
    for item in results.attempts:
        for mode in (ScoringMode.OFFICIAL, ScoringMode.SENSITIVITY):
            score = _mode_score(item, mode)
            if score.result is not None:
                _require_publishable(score.result, mode)
            elif score.unscorable_failure not in UNSCORABLE_GOLD_FAILURES:
                raise DevABaselineScoringError("scoring results are invalid")
            key = (item.attempt.question_key, mode)
            disposition = score.unscorable_failure
            prior = eligibility.setdefault(key, disposition)
            if prior != disposition:
                raise DevABaselineScoringError(
                    "question eligibility is inconsistent across attempts"
                )


def _score_payload(
    plan: DevABaselinePlan,
    results: DevABaselineResults,
    mode: ScoringMode,
) -> dict[str, Any]:
    selected = [_mode_score(item, mode) for item in results.attempts]
    scorer_identity, scorer_version = (
        ("official_soft_ex", OFFICIAL_SOFT_EX_VERSION)
        if mode is ScoringMode.OFFICIAL
        else ("sensitivity", SENSITIVITY_SCORER_VERSION)
    )
    attempts = []
    for item, score in zip(results.attempts, selected, strict=True):
        record: dict[str, str] = {
            "attempt_id": item.attempt.attempt_id,
            "generation_record_sha256": item.attempt.generation_record_sha256,
            "generation_sha256": item.attempt.generation_sha256,
            "status": score.status,
        }
        if score.result is not None:
            assert score.result.outcome is not None
            record["outcome"] = score.result.outcome
            if (
                score.result.outcome == "refused_or_error"
                and score.result.failure_class is not None
            ):
                record["failure_category"] = score.result.failure_class.value
        else:
            assert score.unscorable_failure is not None
            record["failure_category"] = score.unscorable_failure.value
        attempts.append(record)
    return {
        "attempts": attempts,
        "dev_a_ids_sha256": plan.dev_a_ids_sha256,
        "release_sha256": plan.release_sha256,
        "schema_version": SCORE_SCHEMA_VERSION,
        "scorer": {
            "identity": scorer_identity,
            "version": scorer_version,
        },
        "selection_sha256": plan.selection_sha256,
    }


def _receipt(
    workspace: Path,
    output_root: Path,
    plan: DevABaselinePlan,
    results: DevABaselineResults,
    *,
    official_sha256: str,
    sensitivity_sha256: str,
) -> dict[str, Any]:
    def aggregate(mode: ScoringMode) -> dict[str, Any]:
        conditions = tuple(
            sorted({item.attempt.condition for item in results.attempts})
        )
        by_condition: dict[str, Counter[str]] = {
            condition: Counter() for condition in conditions
        }
        overall: Counter[str] = Counter()
        scoreable_questions: set[str] = set()
        unscorable_questions: set[str] = set()
        for item in results.attempts:
            disposition = _mode_score(item, mode)
            if disposition.result is None:
                by_condition[item.attempt.condition]["unscorable"] += 1
                overall["unscorable"] += 1
                unscorable_questions.add(item.attempt.question_key)
                continue
            scoreable_questions.add(item.attempt.question_key)
            assert disposition.result.outcome is not None
            by_condition[item.attempt.condition][disposition.result.outcome] += 1
            overall[disposition.result.outcome] += 1
        payload: dict[str, Any] = {
            "correct": overall["correct"],
            "refused_or_error": overall["refused_or_error"],
            "scheduled_attempts": len(results.attempts),
            "scoreable_attempts": len(results.attempts) - overall["unscorable"],
            "scoreable_questions": len(scoreable_questions),
            "unscorable_attempts": overall["unscorable"],
            "unscorable_questions": len(unscorable_questions),
            "wrong_answer": overall["wrong_answer"],
            "by_condition": {},
        }
        for condition, counts in by_condition.items():
            payload["by_condition"][condition] = {
                "correct": counts["correct"],
                "refused_or_error": counts["refused_or_error"],
                "scheduled_attempts": sum(counts.values()),
                "scoreable_attempts": sum(counts.values()) - counts["unscorable"],
                "unscorable_attempts": counts["unscorable"],
                "wrong_answer": counts["wrong_answer"],
            }
        return payload

    return {
        "artifacts": {
            "official": {
                "path": (output_root / "official.score.json").as_posix(),
                "sha256": official_sha256,
            },
            "sensitivity": {
                "path": (output_root / "sensitivity.score.json").as_posix(),
                "sha256": sensitivity_sha256,
            },
        },
        "coverage": {
            "attempts": len(plan.attempts),
            "released_questions": plan.released_question_count,
            "selected_questions": plan.selected_question_count,
            "unrepresented_questions": plan.unrepresented_question_count,
        },
        "dev_a_ids_sha256": plan.dev_a_ids_sha256,
        "official": aggregate(ScoringMode.OFFICIAL),
        "release_sha256": plan.release_sha256,
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "selection_sha256": plan.selection_sha256,
        "sensitivity": aggregate(ScoringMode.SENSITIVITY),
    }


def _workspace(value: Path) -> Path:
    try:
        root = Path(value).resolve(strict=True)
    except OSError as error:
        raise DevABaselineScoringError("workspace is unavailable") from error
    try:
        git_root = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise DevABaselineScoringError("workspace must be a git repository") from error
    if Path(git_root).resolve() != root:
        raise DevABaselineScoringError("workspace must be the git repository root")
    return root


def _confined_selection_path(value: Path) -> Path:
    selected = Path(value)
    if (
        selected.is_absolute()
        or selected.parent != SELECTION_ROOT
        or not selected.name.endswith(".json")
        or PATH_COMPONENT_PATTERN.fullmatch(selected.name) is None
    ):
        raise DevABaselineScoringError(
            "selection path must be a confined autoresearch state freeze"
        )
    return selected


def _private_file(workspace: Path, relative: Path, description: str) -> bytes:
    path = workspace / relative
    descriptor: int | None = None
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size < 1
            or metadata.st_size > MAX_ARTIFACT_BYTES
        ):
            raise DevABaselineScoringError(f"{description} is not a private file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise DevABaselineScoringError(f"{description} changed while opening")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise DevABaselineScoringError(f"{description} is too large")
            chunks.append(chunk)
        content = b"".join(chunks)
    except DevABaselineScoringError:
        raise
    except OSError as error:
        raise DevABaselineScoringError(f"cannot read {description}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not content:
        raise DevABaselineScoringError(f"{description} is empty")
    return content


def _workspace_file(workspace: Path, relative: Path, description: str) -> bytes:
    try:
        resolved = (workspace / relative).resolve(strict=True)
        resolved.relative_to(workspace)
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise DevABaselineScoringError(f"{description} is invalid")
        return resolved.read_bytes()
    except DevABaselineScoringError:
        raise
    except (OSError, ValueError) as error:
        raise DevABaselineScoringError(f"cannot read {description}") from error


def _digest(value: object, description: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise DevABaselineScoringError(f"{description} must be a SHA-256 digest")
    return value


def _path_component(value: object, description: str) -> str:
    if not isinstance(value, str) or PATH_COMPONENT_PATTERN.fullmatch(value) is None:
        raise DevABaselineScoringError(f"{description} is invalid")
    return value


def _json(content: bytes, description: str) -> Any:
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DevABaselineScoringError(
            f"{description} must contain valid JSON"
        ) from error

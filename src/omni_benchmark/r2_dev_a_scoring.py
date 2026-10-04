"""R2 transport adapter for the unchanged frozen dev-A scorers."""

from __future__ import annotations

import hashlib
import json
import copy
import os
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError
from .autoresearch_metrics import ValidatedGenerationOutputs
from .dev_a_baseline_scoring import (
    RELEASE_PATH,
    DevABaselinePlan,
    DevABaselineResults,
    _PublicAttempt,
    _attach_gold,
    _c4_candidate_input,
    _committed_dev_a_inputs,
    _private_file,
    _validate_result_alignment,
)
from .content_policy import ContentPolicy
from .custody import CustodyError, load_dev_a_records
from .measure_review_catalog import canonical_catalog_bytes
from .protected_fields import ProtectedFieldError, reject_protected_fields
from .r2_execution import (
    FINALIZATION_KIND,
    SERIES_ID,
    MAX_GENERATION_BYTES,
    MAX_MANIFEST_BYTES,
    R2ExecutionError,
    R2ExecutionPlan,
    _reconciled_attempt,
)
from .hkb_io import HKBFileSafetyError, read_regular_file
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION
from .scoring import OFFICIAL_SOFT_EX_VERSION, SENSITIVITY_SCORER_VERSION
from .sealed_scoring import FailureClass, ScoringMode

SCORE_SCHEMA_VERSION = "r2-score-artifact-v2"
RECEIPT_SCHEMA_VERSION = "r2-dev-a-score-receipt-v1"
_CONDITIONS = (CONTROL_CONDITION, TREATMENT_CONDITION)


class R2DevAScoringError(RuntimeError):
    """Sanitized failure at the R2 dev-A scoring boundary."""


@dataclass(frozen=True)
class R2DevAScoringPlan:
    """Validated R2 generation bindings plus the existing scorer plan."""

    baseline: DevABaselinePlan = field(repr=False)
    finalization_sha256: str
    generations: Mapping[str, ValidatedGenerationOutputs]


def prepare_r2_dev_a_scoring_plan(
    workspace: Path,
    *,
    artifact_workspace: Path,
    execution_plan: R2ExecutionPlan,
    finalization_root: Path,
    expected_finalization_sha256: str,
    freeze_a_commit: str,
    expected_release_sha256: str,
    expected_pair_count: int = 136,
    environment: Mapping[str, str] | None = None,
) -> R2DevAScoringPlan:
    """Validate complete public R2 evidence before opening the dev-A release."""
    root = Path(workspace).resolve(strict=True)
    artifacts = Path(artifact_workspace).resolve(strict=True)
    if not isinstance(execution_plan, R2ExecutionPlan):
        raise R2DevAScoringError("R2 execution plan is invalid")
    if type(expected_pair_count) is not int or expected_pair_count < 1:
        raise R2DevAScoringError("R2 expected pair count is invalid")
    if len(execution_plan.attempts) != expected_pair_count * 2:
        raise R2DevAScoringError("R2 execution plan is incomplete")
    policy = ContentPolicy.from_environment(
        os.environ if environment is None else environment
    )
    try:
        generations, records = _validate_finalization(
            artifacts,
            execution_plan,
            finalization_root,
            expected_finalization_sha256,
            expected_pair_count,
        )
        dev_a_ids, dev_a_ids_sha256, public_records = _committed_dev_a_inputs(
            root, freeze_a_commit, policy
        )
        selected_ids = {attempt.instance_id for attempt in execution_plan.attempts}
        if not selected_ids.issubset(dev_a_ids):
            raise R2DevAScoringError("R2 schedule is outside dev-A membership")
        coordinates = Counter(
            (attempt.instance_id, attempt.condition)
            for attempt in execution_plan.attempts
        )
        if coordinates != Counter(
            (instance_id, condition)
            for instance_id in selected_ids
            for condition in _CONDITIONS
        ):
            raise R2DevAScoringError("R2 paired scoring frame is incomplete")
        public_attempts = tuple(
            _prepare_public_r2_attempt(
                artifacts,
                attempt,
                records[attempt.attempt_id],
                public_records[attempt.instance_id],
            )
            for attempt in execution_plan.attempts
        )

        release_bytes = _private_file(root, RELEASE_PATH, "dev-A release")
        if hashlib.sha256(release_bytes).hexdigest() != expected_release_sha256:
            raise R2DevAScoringError("dev-A release does not match its expected hash")
        labels = load_dev_a_records(root / RELEASE_PATH, dev_a_ids)
        if frozenset(labels) != dev_a_ids:
            raise R2DevAScoringError("dev-A release does not match membership")
        prepared = tuple(
            _attach_gold(item, public_records[item.instance_id], labels)
            for item in public_attempts
        )
    except (
        CustodyError,
        HKBFileSafetyError,
        OSError,
        ProtectedFieldError,
        R2ExecutionError,
        ValueError,
    ) as error:
        if isinstance(error, R2DevAScoringError):
            raise
        raise R2DevAScoringError(str(error)) from error
    baseline = DevABaselinePlan(
        selection_sha256=expected_finalization_sha256,
        release_sha256=expected_release_sha256,
        dev_a_ids_sha256=dev_a_ids_sha256,
        freeze_a_commit=freeze_a_commit,
        released_question_count=len(dev_a_ids),
        selected_question_count=len(selected_ids),
        unrepresented_question_count=len(dev_a_ids - selected_ids),
        attempts=prepared,
        scheduled_question_count=len(selected_ids),
    )
    return R2DevAScoringPlan(
        baseline=baseline,
        finalization_sha256=expected_finalization_sha256,
        generations=generations,
    )


def _validate_finalization(
    workspace: Path,
    plan: R2ExecutionPlan,
    destination: Path,
    expected_sha256: str,
    expected_pair_count: int,
) -> tuple[dict[str, ValidatedGenerationOutputs], dict[str, Mapping[str, Any]]]:
    root = workspace / destination
    manifest_path = root / "finalization.json"
    manifest_bytes = read_regular_file(manifest_path, maximum_bytes=MAX_MANIFEST_BYTES)
    if hashlib.sha256(manifest_bytes).hexdigest() != expected_sha256:
        raise R2DevAScoringError("R2 finalization does not match its expected hash")
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise R2DevAScoringError("R2 finalization manifest is invalid") from error
    if not isinstance(manifest, Mapping) or manifest_bytes != canonical_catalog_bytes(
        manifest
    ):
        raise R2DevAScoringError("R2 finalization manifest is not canonical")
    reject_protected_fields(manifest)
    stored_internal = manifest.get("manifest_sha256")
    unhashed = copy.deepcopy(dict(manifest))
    unhashed.pop("manifest_sha256", None)
    if stored_internal != hashlib.sha256(canonical_catalog_bytes(unhashed)).hexdigest():
        raise R2DevAScoringError("R2 finalization manifest hash is invalid")
    expected_top = {
        "bundle_manifest_sha256": plan.bundle_manifest_sha256,
        "bundle_set_sha256": plan.bundle_set_sha256,
        "execution_plan_sha256": plan.sha256,
        "information_boundary": {
            "correctness_used": False,
            "hidden_annotations_used": False,
            "result_values_emitted": False,
            "sealed_test_used": False,
        },
        "kind": FINALIZATION_KIND,
        "schedule_sha256": plan.schedule_sha256,
        "schema_version": 1,
        "series_id": SERIES_ID,
        "system_commit": plan.system_commit,
    }
    if any(manifest.get(key) != value for key, value in expected_top.items()):
        raise R2DevAScoringError("R2 finalization identity is invalid")
    if set(manifest) != set(expected_top) | {"conditions", "manifest_sha256"}:
        raise R2DevAScoringError("R2 finalization shape is invalid")
    file_names = {
        CONTROL_CONDITION: "r2-c5b.generation.jsonl",
        TREATMENT_CONDITION: "r2-m1.generation.jsonl",
    }
    generations = {}
    records = {}
    conditions = manifest.get("conditions")
    if not isinstance(conditions, Mapping) or set(conditions) != set(_CONDITIONS):
        raise R2DevAScoringError("R2 finalization arm coverage is invalid")
    for condition in _CONDITIONS:
        selected_attempts = tuple(
            attempt for attempt in plan.attempts if attempt.condition == condition
        )
        if len(selected_attempts) != expected_pair_count:
            raise R2DevAScoringError("R2 finalization arm is incomplete")
        rebuilt = b"".join(
            _reconciled_attempt(workspace, plan, attempt)
            for attempt in selected_attempts
        )
        generation_path = root / file_names[condition]
        generation_bytes = read_regular_file(
            generation_path, maximum_bytes=MAX_GENERATION_BYTES
        )
        if generation_bytes != rebuilt:
            raise R2DevAScoringError("R2 finalized arm differs from attempt evidence")
        digest = hashlib.sha256(generation_bytes).hexdigest()
        run_ids = {attempt.run_id for attempt in selected_attempts}
        expected_condition = {
            "generation_file": file_names[condition],
            "generation_sha256": digest,
            "ordered_attempt_ids": [item.attempt_id for item in selected_attempts],
            "record_count": expected_pair_count,
            "run_id": next(iter(run_ids)) if len(run_ids) == 1 else None,
        }
        if conditions[condition] != expected_condition:
            raise R2DevAScoringError("R2 finalization arm binding is invalid")
        raw_lines = generation_bytes.splitlines(keepends=True)
        for raw, attempt in zip(raw_lines, selected_attempts, strict=True):
            record = json.loads(raw)
            if not isinstance(record, Mapping):
                raise R2DevAScoringError("R2 generation record is invalid")
            records[attempt.attempt_id] = record
        generations[condition] = ValidatedGenerationOutputs(
            path=generation_path,
            sha256=digest,
            question_count=expected_pair_count,
            scope="dev-a",
            condition=condition,
            run_id=expected_condition["run_id"],
            repetition=1,
            run_manifest_path=manifest_path,
            run_manifest_sha256=expected_sha256,
        )
    return generations, records


def _prepare_public_r2_attempt(
    workspace: Path,
    attempt: Any,
    record: Mapping[str, Any],
    public_record: Mapping[str, Any],
) -> _PublicAttempt:
    if public_record["selected_database"] != attempt.database:
        raise R2DevAScoringError("R2 database does not match the public question")
    outcome = record.get("generation_outcome")
    if outcome == "answered":
        candidate, rows, failure = _c4_candidate_input(
            workspace,
            root=attempt.output_root,
            outcome=outcome,
            record=record,
            recovery_entry=None,
            recovery_workspace=None,
            source_generation_sha256=hashlib.sha256(
                canonical_catalog_bytes(record)
            ).hexdigest(),
        )
    else:
        candidate = ()
        rows = None
        failure = (
            FailureClass.AGENT_REFUSAL
            if outcome == "refused"
            else FailureClass.CANDIDATE_EXECUTION_ERROR
        )
    raw = canonical_catalog_bytes(record)
    return _PublicAttempt(
        attempt_id=attempt.attempt_id,
        condition=attempt.condition,
        generation_sha256=hashlib.sha256(raw).hexdigest(),
        generation_record_sha256=hashlib.sha256(raw).hexdigest(),
        instance_id=attempt.instance_id,
        generated_sql=candidate,
        candidate_rows=rows,
        no_answer_failure=failure,
    )


def publish_r2_dev_a_results(
    workspace: Path,
    *,
    artifact_workspace: Path,
    output_root: Path,
    plan: R2DevAScoringPlan,
    results: DevABaselineResults,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Publish four immutable SQL-free arm score artifacts and one receipt."""
    root = Path(workspace).resolve(strict=True)
    artifact_root = Path(artifact_workspace).resolve(strict=True)
    if not isinstance(plan, R2DevAScoringPlan):
        raise R2DevAScoringError("R2 scoring plan is invalid")
    _validate_result_alignment(plan.baseline, results)
    bindings = _generation_bindings(artifact_root, plan, results)
    try:
        store = ArtifactStore(
            root,
            Path(output_root),
            environment=environment,
            require_new_root=True,
        )
        stored: dict[str, dict[str, Any]] = {
            "official": {},
            "sensitivity": {},
        }
        for mode, label in (
            (ScoringMode.OFFICIAL, "official"),
            (ScoringMode.SENSITIVITY, "sensitivity"),
        ):
            for condition in _CONDITIONS:
                payload = _score_payload(plan, results, bindings, condition, mode)
                name = f"{condition.lower()}.{label}.score.json"
                artifact = store.write_json(Path(name), payload)
                stored[label][condition] = {
                    "path": store.relative_path(artifact).as_posix(),
                    "sha256": artifact.sha256,
                }
        receipt = _receipt(plan, results, stored)
        receipt_artifact = store.write_json(Path("receipt.json"), receipt)
    except (ArtifactStoreError, ValueError) as error:
        raise R2DevAScoringError(str(error)) from error
    return receipt | {"receipt_sha256": receipt_artifact.sha256}


def _generation_bindings(
    artifact_workspace: Path,
    plan: R2DevAScoringPlan,
    results: DevABaselineResults,
) -> dict[str, tuple[ValidatedGenerationOutputs, tuple[str, ...]]]:
    if set(plan.generations) != set(_CONDITIONS):
        raise R2DevAScoringError("R2 generation arm coverage is invalid")
    result_by_condition = {
        condition: tuple(
            item for item in results.attempts if item.attempt.condition == condition
        )
        for condition in _CONDITIONS
    }
    bindings = {}
    for condition in _CONDITIONS:
        generation = plan.generations[condition]
        if (
            not isinstance(generation, ValidatedGenerationOutputs)
            or generation.condition != condition
            or generation.scope != "dev-a"
            or generation.repetition != 1
        ):
            raise R2DevAScoringError("R2 generation binding is invalid")
        path = generation.path.resolve(strict=True)
        try:
            relative = path.relative_to(artifact_workspace)
        except ValueError as error:
            raise R2DevAScoringError(
                "R2 generation must be inside the artifact workspace"
            ) from error
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != generation.sha256:
            raise R2DevAScoringError("R2 generation changed after validation")
        raw_lines = content.splitlines(keepends=True)
        selected = result_by_condition[condition]
        if len(raw_lines) != generation.question_count or len(raw_lines) != len(
            selected
        ):
            raise R2DevAScoringError("R2 score arm is incomplete")
        attempt_ids = []
        for raw, item in zip(raw_lines, selected, strict=True):
            try:
                record = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise R2DevAScoringError("R2 generation record is invalid") from error
            if (
                not isinstance(record, Mapping)
                or record.get("attempt_id") != item.attempt.attempt_id
                or hashlib.sha256(raw).hexdigest()
                != item.attempt.generation_record_sha256
            ):
                raise R2DevAScoringError("R2 generation record binding is invalid")
            attempt_ids.append(item.attempt.attempt_id)
        bindings[condition] = (generation, tuple(attempt_ids), relative.as_posix())
    return bindings


def _score_payload(
    plan: R2DevAScoringPlan,
    results: DevABaselineResults,
    bindings: Mapping[str, tuple[Any, ...]],
    condition: str,
    mode: ScoringMode,
) -> dict[str, Any]:
    identity, version = (
        ("official_soft_ex", OFFICIAL_SOFT_EX_VERSION)
        if mode is ScoringMode.OFFICIAL
        else ("sensitivity", SENSITIVITY_SCORER_VERSION)
    )
    attempts = []
    for item in results.attempts:
        if item.attempt.condition != condition:
            continue
        score = item.official if mode is ScoringMode.OFFICIAL else item.sensitivity
        record = {
            "attempt_id": item.attempt.attempt_id,
            "generation_record_sha256": item.attempt.generation_record_sha256,
            "status": score.status,
        }
        if score.result is not None:
            if score.result.outcome is None:
                raise R2DevAScoringError("R2 scored attempt has no outcome")
            record["outcome"] = score.result.outcome
            if (
                score.result.outcome == "refused_or_error"
                and score.result.failure_class is not None
            ):
                record["failure_category"] = score.result.failure_class.value
        else:
            if score.unscorable_failure is None:
                raise R2DevAScoringError("R2 unscorable attempt has no category")
            record["failure_category"] = score.unscorable_failure.value
        attempts.append(record)
    generation = bindings[condition][0]
    relative_path = bindings[condition][2]
    return {
        "attempts": attempts,
        "generation": {"path": relative_path, "sha256": generation.sha256},
        "schema_version": SCORE_SCHEMA_VERSION,
        "scorer": {"identity": identity, "version": version},
    }


def _receipt(
    plan: R2DevAScoringPlan,
    results: DevABaselineResults,
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "artifacts": artifacts,
        "coverage": {
            "released_questions": plan.baseline.released_question_count,
            "scheduled_attempts": len(results.attempts),
            "scheduled_questions": plan.baseline.scheduled_question_count,
        },
        "dev_a_ids_sha256": plan.baseline.dev_a_ids_sha256,
        "finalization_sha256": plan.finalization_sha256,
        "freeze_a_commit": plan.baseline.freeze_a_commit,
        "release_sha256": plan.baseline.release_sha256,
        "schema_version": RECEIPT_SCHEMA_VERSION,
    }

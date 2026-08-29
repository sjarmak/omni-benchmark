"""Production custody boundary for loading and scoring a complete sealed batch."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifact_store import ALLOWED_RAW_ROOTS, ArtifactStore, ArtifactStoreError
from .autoresearch_metrics import ValidatedGenerationOutputs
from .custody import (
    CustodyError,
    _canonical_record,
    _private_instance_id,
    _validate_private_record,
)
from .dev_a_baseline_scoring import (
    DevABaselinePlan,
    DevABaselineScoringError,
    PreparedDevAAttempt,
    _private_file,
    score_dev_a_baseline_plan,
)
from .freeze_b import (
    CONDITIONS,
    REPETITIONS,
    FreezeBError,
    FreezeBManifest,
    SealedRunManifest,
)
from .sealed_execution_plan import SealedExecutionPlan
from .sealed_generation_staging import (
    SealedGenerationStagingError,
    _canonical_bytes,
    _read_private_file,
    _validated_freeze,
    _validated_generation_record,
    _validated_plan,
    prepare_sealed_attempt,
)
from .sealed_results import SealedScoredAttempt, aggregate_sealed_results
from .sealed_scoring import (
    FailureClass,
    PostgreSQLIsolationProvider,
    ScoringMode,
    SealedQueryCase,
    validate_query_case,
)

GENERATION_FILENAME = "generation.jsonl"
RUN_MANIFEST_FILENAME = "run.json"


class SealedEvaluationError(RuntimeError):
    """Sanitized failure at the final sealed evaluator boundary."""


@dataclass(frozen=True)
class SealedFrozenAttempt:
    """One validated frozen generation; candidate content stays out of repr."""

    attempt_id: str
    condition: str
    database: str
    repetition: int
    generation_sha256: str
    generation_record_sha256: str
    run_manifest_sha256: str
    generation_outcome: str
    terminal_failure_class: str | None
    instance_id: str = field(repr=False)
    candidate_sql: str | tuple[()] = field(repr=False)
    candidate_rows: tuple[tuple[Any, ...], ...] | None = field(default=None, repr=False)
    no_answer_failure: FailureClass | None = None


@dataclass(frozen=True)
class SealedValidatedCohort:
    """One exact condition/repetition generation and run-manifest binding."""

    condition: str
    repetition: int
    generation: ValidatedGenerationOutputs
    run_manifest: SealedRunManifest


@dataclass(frozen=True)
class SealedOutputBatch:
    """All no-gold inputs proven complete before private custody is opened."""

    freeze_b_sha256: str
    plan_sha256: str
    schedule_sha256: str
    test_ids_sha256: str
    cohorts: tuple[SealedValidatedCohort, ...]
    attempts: tuple[SealedFrozenAttempt, ...] = field(repr=False)


@dataclass(frozen=True)
class SealedEvaluationPlan:
    """Exact frozen attempts with sealed labels attached inside custody."""

    freeze_b_sha256: str
    plan_sha256: str
    release_sha256: str
    test_ids_sha256: str
    batch: SealedOutputBatch = field(repr=False)
    attempts: tuple[PreparedDevAAttempt, ...] = field(repr=False)


def load_sealed_output_batch(
    workspace: Path,
    *,
    output_root: Path,
    plan: SealedExecutionPlan,
    freeze_b: FreezeBManifest,
    questions: Mapping[str, str],
) -> SealedOutputBatch:
    """Authenticate all twelve cohorts without opening any private label source."""
    root = _workspace(workspace)
    try:
        validated_plan = _validated_plan(plan)
        validated_freeze = _validated_freeze(freeze_b)
    except SealedGenerationStagingError as error:
        raise SealedEvaluationError("sealed plan or Freeze B is invalid") from error
    if (
        validated_plan.freeze_b_sha256 != validated_freeze.sha256()
        or validated_plan.system_commit != validated_freeze.system_commit
        or validated_plan.schedule_sha256 != validated_freeze.schedule_sha256
    ):
        raise SealedEvaluationError("sealed plan does not match Freeze B")
    question_map = _questions(questions, validated_plan)
    selected_root = _output_root(root, output_root)
    cohorts: list[SealedValidatedCohort] = []
    attempts_by_id: dict[str, SealedFrozenAttempt] = {}
    for condition in CONDITIONS:
        for repetition in range(1, REPETITIONS + 1):
            cohort, attempts = _load_cohort(
                root,
                selected_root,
                validated_plan,
                validated_freeze,
                question_map,
                condition,
                repetition,
            )
            cohorts.append(cohort)
            for attempt in attempts:
                if attempt.attempt_id in attempts_by_id:
                    raise SealedEvaluationError(
                        "sealed cohorts contain a duplicate attempt"
                    )
                attempts_by_id[attempt.attempt_id] = attempt
    expected_ids = tuple(item.attempt_id for item in validated_plan.attempts)
    if set(attempts_by_id) != set(expected_ids) or len(attempts_by_id) != 1_212:
        raise SealedEvaluationError("sealed cohort attempt set is incomplete")
    return SealedOutputBatch(
        freeze_b_sha256=validated_freeze.sha256(),
        plan_sha256=validated_plan.sha256,
        schedule_sha256=validated_plan.schedule_sha256,
        test_ids_sha256=validated_plan.test_ids_sha256,
        cohorts=tuple(cohorts),
        attempts=tuple(attempts_by_id[attempt_id] for attempt_id in expected_ids),
    )


def prepare_sealed_evaluation_plan(
    workspace: Path,
    *,
    batch: SealedOutputBatch,
    release_path: Path,
    expected_release_sha256: str,
    public_records: Mapping[str, Mapping[str, Any]],
) -> SealedEvaluationPlan:
    """Open exactly 101 test labels only after complete output preflight."""
    root = _workspace(workspace)
    validated_batch = _validated_batch(batch)
    release_digest = _digest(expected_release_sha256, "test release SHA-256")
    selected = Path(release_path)
    if (
        selected.is_absolute()
        or not selected.is_relative_to(Path("data/private"))
        or ".." in selected.parts
    ):
        raise SealedEvaluationError("test release must use the private custody root")
    expected_ids = frozenset(
        attempt.instance_id for attempt in validated_batch.attempts
    )
    if len(expected_ids) != 101:
        raise SealedEvaluationError("sealed test membership must contain 101 IDs")
    public = _validated_public_records(public_records, validated_batch, expected_ids)
    try:
        release_content = _private_file(root, selected, "sealed test release")
    except DevABaselineScoringError as error:
        raise SealedEvaluationError("sealed test release is unavailable") from error
    if hashlib.sha256(release_content).hexdigest() != release_digest:
        raise SealedEvaluationError("sealed test release hash does not match")
    labels = _exact_release_records(release_content, expected_ids)
    if frozenset(labels) != expected_ids:
        raise SealedEvaluationError(
            "sealed test release must contain exactly 101 records"
        )
    attempts = tuple(
        _attach_gold(attempt, public[attempt.instance_id], labels[attempt.instance_id])
        for attempt in validated_batch.attempts
    )
    try:
        for attempt in attempts:
            validate_query_case(attempt.case)
    except (TypeError, ValueError) as error:
        raise SealedEvaluationError("sealed scoring input is invalid") from error
    return SealedEvaluationPlan(
        freeze_b_sha256=validated_batch.freeze_b_sha256,
        plan_sha256=validated_batch.plan_sha256,
        release_sha256=release_digest,
        test_ids_sha256=validated_batch.test_ids_sha256,
        batch=validated_batch,
        attempts=attempts,
    )


def score_sealed_evaluation(
    plan: SealedEvaluationPlan, provider: PostgreSQLIsolationProvider
) -> tuple[SealedScoredAttempt, ...]:
    """Freeze gold eligibility, then score every eligible candidate once."""
    if not isinstance(plan, SealedEvaluationPlan) or len(plan.attempts) != 1_212:
        raise SealedEvaluationError("sealed evaluation plan is invalid")
    dev_plan = DevABaselinePlan(
        selection_sha256=plan.plan_sha256,
        release_sha256=plan.release_sha256,
        dev_a_ids_sha256=plan.test_ids_sha256,
        freeze_a_commit="0" * 40,
        released_question_count=101,
        selected_question_count=101,
        unrepresented_question_count=0,
        attempts=plan.attempts,
    )
    try:
        scored = score_dev_a_baseline_plan(dev_plan, provider)
    except DevABaselineScoringError as error:
        raise SealedEvaluationError(
            "sealed infrastructure failure blocks score publication"
        ) from error
    if len(scored.attempts) != len(plan.batch.attempts):
        raise SealedEvaluationError("sealed score result is incomplete")
    return tuple(
        SealedScoredAttempt(
            attempt_id=frozen.attempt_id,
            condition=frozen.condition,
            repetition=frozen.repetition,
            generation_sha256=frozen.generation_sha256,
            generation_record_sha256=frozen.generation_record_sha256,
            question_key=prepared.question_key,
            generation_outcome=frozen.generation_outcome,
            terminal_failure_class=frozen.terminal_failure_class,
            official=result.official,
            sensitivity=result.sensitivity,
        )
        for frozen, prepared, result in zip(
            plan.batch.attempts, plan.attempts, scored.attempts, strict=True
        )
    )


def publish_sealed_evaluation(
    workspace: Path,
    *,
    output_root: Path,
    plan: SealedEvaluationPlan,
    results: Sequence[SealedScoredAttempt],
) -> dict[str, str]:
    """Atomically publish 24 private score files and two safe aggregates."""
    root = _workspace(workspace)
    if not isinstance(plan, SealedEvaluationPlan):
        raise SealedEvaluationError("sealed evaluation plan is invalid")
    scored = _validated_results(plan, results)
    reports = {
        mode: aggregate_sealed_results(scored, mode)
        for mode in (ScoringMode.OFFICIAL, ScoringMode.SENSITIVITY)
    }
    selected = _relative_raw_root(output_root)
    destination = root / selected
    if os.path.lexists(destination):
        raise SealedEvaluationError("sealed score output already exists")
    temporary = selected.parent / f".{selected.name}.tmp-{secrets.token_hex(8)}"
    temporary_path = root / temporary
    try:
        ArtifactStore(root, selected.parent)
        store = ArtifactStore(root, temporary, require_new_root=True)
        score_artifacts: dict[ScoringMode, list[dict[str, str]]] = {
            ScoringMode.OFFICIAL: [],
            ScoringMode.SENSITIVITY: [],
        }
        aggregate_artifacts: dict[ScoringMode, Any] = {}
        for mode in (ScoringMode.OFFICIAL, ScoringMode.SENSITIVITY):
            for cohort in plan.batch.cohorts:
                cohort_results = tuple(
                    item
                    for item in scored
                    if (item.condition, item.repetition)
                    == (cohort.condition, cohort.repetition)
                )
                artifact = store.write_json(
                    Path(mode.value)
                    / f"{cohort.condition.lower()}-r{cohort.repetition}.score.json",
                    _score_payload(plan, cohort, cohort_results, mode),
                )
                score_artifacts[mode].append(
                    {
                        "path": store.root_relative_path(artifact).as_posix(),
                        "sha256": artifact.sha256,
                    }
                )
            aggregate_artifacts[mode] = store.write_json(
                Path(mode.value) / "aggregate.json",
                {
                    "freeze_b_sha256": plan.freeze_b_sha256,
                    "kind": "sealed-aggregate-result",
                    "plan_sha256": plan.plan_sha256,
                    "release_sha256": plan.release_sha256,
                    "report": reports[mode],
                    "schema_version": 1,
                    "score_artifact_sha256s": [
                        item["sha256"] for item in score_artifacts[mode]
                    ],
                    "test_ids_sha256": plan.test_ids_sha256,
                },
            )
        receipt = store.write_json(
            Path("receipt.json"),
            {
                "aggregates": {
                    mode.value: {
                        "path": store.root_relative_path(
                            aggregate_artifacts[mode]
                        ).as_posix(),
                        "sha256": aggregate_artifacts[mode].sha256,
                    }
                    for mode in (ScoringMode.OFFICIAL, ScoringMode.SENSITIVITY)
                },
                "attempt_count": 1_212,
                "cohort_count": 12,
                "freeze_b_sha256": plan.freeze_b_sha256,
                "kind": "sealed-evaluation-receipt",
                "plan_sha256": plan.plan_sha256,
                "question_count": 101,
                "release_sha256": plan.release_sha256,
                "schema_version": 1,
                "score_artifacts": {
                    mode.value: score_artifacts[mode]
                    for mode in (ScoringMode.OFFICIAL, ScoringMode.SENSITIVITY)
                },
                "test_ids_sha256": plan.test_ids_sha256,
            },
        )
        _rename_noreplace(temporary_path, destination)
    except (ArtifactStoreError, OSError) as error:
        _cleanup_temporary(temporary_path)
        raise SealedEvaluationError(
            "sealed score publication failed atomically"
        ) from error
    return {
        "official_aggregate_sha256": aggregate_artifacts[ScoringMode.OFFICIAL].sha256,
        "output_root": selected.as_posix(),
        "receipt_sha256": receipt.sha256,
        "sensitivity_aggregate_sha256": aggregate_artifacts[
            ScoringMode.SENSITIVITY
        ].sha256,
    }


def _validated_results(
    plan: SealedEvaluationPlan, value: object
) -> tuple[SealedScoredAttempt, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SealedEvaluationError("sealed score results are invalid")
    results = tuple(value)
    if len(results) != 1_212 or any(
        not isinstance(result, SealedScoredAttempt) for result in results
    ):
        raise SealedEvaluationError("sealed score results are incomplete")
    for frozen, result in zip(plan.batch.attempts, results, strict=True):
        assert isinstance(result, SealedScoredAttempt)
        if (
            result.attempt_id != frozen.attempt_id
            or result.condition != frozen.condition
            or result.repetition != frozen.repetition
            or result.generation_sha256 != frozen.generation_sha256
            or result.generation_record_sha256 != frozen.generation_record_sha256
        ):
            raise SealedEvaluationError("sealed score results do not match the plan")
    return results  # type: ignore[return-value]


def _exact_release_records(
    content: bytes, expected_ids: frozenset[str]
) -> dict[str, dict[str, Any]]:
    lines = content.splitlines(keepends=True)
    if len(lines) != 101 or any(not line.endswith(b"\n") for line in lines):
        raise SealedEvaluationError(
            "sealed test release must contain exactly 101 records"
        )
    records: dict[str, dict[str, Any]] = {}
    try:
        for line_number, raw_line in enumerate(lines, start=1):
            decoded = json.loads(raw_line)
            instance_id = _private_instance_id(decoded, line_number)
            if instance_id not in expected_ids or instance_id in records:
                raise SealedEvaluationError(
                    "sealed test release membership or schema is invalid"
                )
            record = _validate_private_record(decoded, line_number)
            if _canonical_record(record) != raw_line:
                raise SealedEvaluationError("sealed test release is not canonical")
            records[instance_id] = record
    except SealedEvaluationError:
        raise
    except (CustodyError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SealedEvaluationError(
            "sealed test release membership or schema is invalid"
        ) from error
    return records


def _score_payload(
    plan: SealedEvaluationPlan,
    cohort: SealedValidatedCohort,
    results: Sequence[SealedScoredAttempt],
    mode: ScoringMode,
) -> dict[str, Any]:
    if len(results) != 101:
        raise SealedEvaluationError("sealed score cohort is incomplete")
    attempts = []
    for item in results:
        disposition = (
            item.official if mode is ScoringMode.OFFICIAL else item.sensitivity
        )
        record: dict[str, str] = {
            "attempt_id": item.attempt_id,
            "generation_record_sha256": item.generation_record_sha256,
            "status": disposition.status,
        }
        if disposition.result is None:
            assert disposition.unscorable_failure is not None
            record["failure_category"] = disposition.unscorable_failure.value
        else:
            assert disposition.result.outcome is not None
            record["outcome"] = disposition.result.outcome
            if disposition.result.failure_class is not None:
                record["failure_category"] = disposition.result.failure_class.value
        attempts.append(record)
    return {
        "attempts": attempts,
        "freeze_b_sha256": plan.freeze_b_sha256,
        "generation": {
            "sha256": cohort.generation.sha256,
            "run_manifest_sha256": cohort.run_manifest.sha256(),
        },
        "kind": "sealed-score-artifact",
        "plan_sha256": plan.plan_sha256,
        "release_sha256": plan.release_sha256,
        "schema_version": 1,
        "scorer": {
            "identity": mode.value,
            "version": _scorer_version(mode),
        },
        "test_ids_sha256": plan.test_ids_sha256,
    }


def _scorer_version(mode: ScoringMode) -> str:
    from .scoring import OFFICIAL_SOFT_EX_VERSION, SENSITIVITY_SCORER_VERSION

    return (
        OFFICIAL_SOFT_EX_VERSION
        if mode is ScoringMode.OFFICIAL
        else SENSITIVITY_SCORER_VERSION
    )


def _relative_raw_root(value: Path) -> Path:
    selected = Path(value)
    if (
        selected.is_absolute()
        or not selected.parts
        or ".." in selected.parts
        or not any(selected.is_relative_to(root) for root in ALLOWED_RAW_ROOTS)
    ):
        raise SealedEvaluationError("sealed score output root is invalid")
    return selected


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically publish a directory without replacing a raced destination."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError as error:
        raise OSError("renameat2 is required for atomic sealed publication") from error
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    ):
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), destination)


def _cleanup_temporary(path: Path) -> None:
    if not os.path.lexists(path):
        return
    try:
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_dir() and not child.is_symlink():
                child.rmdir()
            else:
                child.unlink()
        path.rmdir()
    except OSError:
        pass


def _validated_batch(value: object) -> SealedOutputBatch:
    if not isinstance(value, SealedOutputBatch):
        raise SealedEvaluationError("complete sealed output preflight is required")
    if (
        len(value.cohorts) != 12
        or len(value.attempts) != 1_212
        or len({attempt.attempt_id for attempt in value.attempts}) != 1_212
        or {(cohort.condition, cohort.repetition) for cohort in value.cohorts}
        != {
            (condition, repetition)
            for condition in CONDITIONS
            for repetition in range(1, REPETITIONS + 1)
        }
    ):
        raise SealedEvaluationError("complete sealed output preflight is required")
    for digest in (
        value.freeze_b_sha256,
        value.plan_sha256,
        value.schedule_sha256,
        value.test_ids_sha256,
    ):
        _digest(digest, "sealed preflight SHA-256")
    return value


def _validated_public_records(
    value: object,
    batch: SealedOutputBatch,
    expected_ids: frozenset[str],
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Mapping) or not expected_ids.issubset(value):
        raise SealedEvaluationError("frozen public test records are incomplete")
    result: dict[str, Mapping[str, Any]] = {}
    planned_database = {
        attempt.instance_id: attempt.database for attempt in batch.attempts
    }
    for instance_id in expected_ids:
        record = value[instance_id]
        if not isinstance(record, Mapping):
            raise SealedEvaluationError("frozen public test record is invalid")
        required = {
            "selected_database",
            "preprocess_sql",
            "clean_up_sqls",
            "conditions",
        }
        if not required.issubset(record):
            raise SealedEvaluationError("frozen public test record is invalid")
        database = record["selected_database"]
        if not isinstance(database, str) or not database:
            raise SealedEvaluationError("frozen public test database is invalid")
        if database != planned_database[instance_id]:
            raise SealedEvaluationError("frozen public test database is invalid")
        result[instance_id] = record
    if len(planned_database) != 101:
        raise SealedEvaluationError("frozen public test records are incomplete")
    return result


def _attach_gold(
    frozen: SealedFrozenAttempt,
    public_record: Mapping[str, Any],
    private_record: Mapping[str, Any],
) -> PreparedDevAAttempt:
    if frozen.candidate_rows is not None and (
        public_record["preprocess_sql"] or public_record["clean_up_sqls"]
    ):
        raise SealedEvaluationError(
            "precomputed C4 result requires a stateless public scoring case"
        )
    return PreparedDevAAttempt(
        attempt_id=frozen.attempt_id,
        condition=frozen.condition,
        generation_sha256=frozen.generation_sha256,
        generation_record_sha256=frozen.generation_record_sha256,
        # The key never enters aggregate output. Keeping the literal frozen
        # instance ID here preserves preregistered ascending-ID bootstrap order.
        question_key=frozen.instance_id,
        case=SealedQueryCase(
            database=str(public_record["selected_database"]),
            candidate_sql=frozen.candidate_sql,
            gold_sql=private_record["sol_sql"],
            preprocess_sql=public_record["preprocess_sql"],
            cleanup_sql=public_record["clean_up_sqls"],
            conditions=public_record["conditions"],
        ),
        candidate_rows=frozen.candidate_rows,
        no_answer_failure=frozen.no_answer_failure,
    )


def _digest(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SealedEvaluationError(f"{description} must be a lowercase SHA-256")
    return value


def _load_cohort(
    workspace: Path,
    output_root: Path,
    plan: SealedExecutionPlan,
    freeze_b: FreezeBManifest,
    questions: Mapping[str, str],
    condition: str,
    repetition: int,
) -> tuple[SealedValidatedCohort, tuple[SealedFrozenAttempt, ...]]:
    directory = output_root / f"{condition.lower()}-r{repetition}"
    generation_path = directory / GENERATION_FILENAME
    manifest_path = directory / RUN_MANIFEST_FILENAME
    try:
        metadata = directory.stat(follow_symlinks=False)
        if (
            directory.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
            or set(directory.iterdir()) != {generation_path, manifest_path}
        ):
            raise SealedEvaluationError("sealed cohort directory is invalid")
        generation_content = _read_private_file(generation_path)
        manifest_content = _read_private_file(manifest_path)
    except SealedEvaluationError:
        raise
    except (OSError, SealedGenerationStagingError) as error:
        raise SealedEvaluationError("sealed cohort is missing or invalid") from error
    try:
        manifest_value = json.loads(manifest_content)
        manifest = SealedRunManifest.from_dict(manifest_value, freeze_b=freeze_b)
    except (UnicodeDecodeError, json.JSONDecodeError, FreezeBError, TypeError) as error:
        raise SealedEvaluationError("sealed cohort run manifest is invalid") from error
    if (
        manifest.canonical_bytes() != manifest_content
        or (manifest.condition, manifest.repetition) != (condition, repetition)
        or hashlib.sha256(generation_content).hexdigest() != manifest.generation_sha256
    ):
        raise SealedEvaluationError("sealed cohort binding is invalid")
    planned = tuple(
        item
        for item in plan.attempts
        if (item.condition, item.repetition) == (condition, repetition)
    )
    lines = generation_content.splitlines(keepends=True)
    if (
        len(planned) != 101
        or len(lines) != 101
        or any(not line.endswith(b"\n") for line in lines)
    ):
        raise SealedEvaluationError("sealed cohort must contain exactly 101 records")
    attempts = tuple(
        _generation_attempt(
            workspace,
            plan,
            freeze_b,
            questions,
            expected,
            line,
            manifest,
        )
        for expected, line in zip(planned, lines, strict=True)
    )
    generation = ValidatedGenerationOutputs(
        path=generation_path,
        sha256=manifest.generation_sha256,
        question_count=101,
        scope="test",
        condition=condition,
        run_id=f"sealed-{condition.lower()}-r{repetition}",
        repetition=repetition,
        run_manifest_path=manifest_path,
        run_manifest_sha256=manifest.sha256(),
    )
    return (
        SealedValidatedCohort(
            condition=condition,
            repetition=repetition,
            generation=generation,
            run_manifest=manifest,
        ),
        attempts,
    )


def _generation_attempt(
    workspace: Path,
    plan: SealedExecutionPlan,
    freeze_b: FreezeBManifest,
    questions: Mapping[str, str],
    expected: Any,
    raw_line: bytes,
    manifest: SealedRunManifest,
) -> SealedFrozenAttempt:
    try:
        supplied = json.loads(raw_line)
        prepared = prepare_sealed_attempt(
            plan=plan,
            freeze_b=freeze_b,
            attempt_id=expected.attempt_id,
            question=questions[expected.instance_id],
        )
        record = _validated_generation_record(prepared, supplied)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        SealedGenerationStagingError,
        TypeError,
        ValueError,
    ) as error:
        raise SealedEvaluationError(
            "sealed cohort generation record is invalid"
        ) from error
    if _canonical_bytes(record) != raw_line:
        raise SealedEvaluationError("sealed cohort generation record is not canonical")
    outcome = str(record["generation_outcome"])
    terminal = record.get("terminal_failure_class")
    candidate_sql: str | tuple[()] = ()
    candidate_rows = None
    no_answer = None
    if expected.condition == "C4":
        if outcome == "answered":
            candidate_rows = _c4_result_rows(workspace, record)
        elif (
            outcome != "errored"
            or record.get("failure_origin") != "evaluated_system"
            or terminal != "omni_job_terminal_failure"
        ):
            raise SealedEvaluationError("sealed C4 terminal outcome is invalid")
        else:
            no_answer = FailureClass.CANDIDATE_EXECUTION_ERROR
    elif outcome == "answered":
        candidate = record.get("generated_sql")
        if not isinstance(candidate, str) or not candidate.strip():
            raise SealedEvaluationError("sealed direct candidate SQL is invalid")
        candidate_sql = candidate
    else:
        no_answer = (
            FailureClass.AGENT_REFUSAL
            if outcome == "refused"
            else FailureClass.NO_QUERY
        )
    return SealedFrozenAttempt(
        attempt_id=expected.attempt_id,
        condition=expected.condition,
        database=expected.database,
        repetition=expected.repetition,
        generation_sha256=manifest.generation_sha256,
        generation_record_sha256=hashlib.sha256(raw_line).hexdigest(),
        run_manifest_sha256=manifest.sha256(),
        generation_outcome=outcome,
        terminal_failure_class=terminal if isinstance(terminal, str) else None,
        instance_id=expected.instance_id,
        candidate_sql=candidate_sql,
        candidate_rows=candidate_rows,
        no_answer_failure=no_answer,
    )


def _c4_result_rows(
    workspace: Path, record: Mapping[str, Any]
) -> tuple[tuple[Any, ...], ...]:
    # Imported lazily so the no-gold cohort preflight remains independent of
    # scorer/provider construction. The artifact itself is generation output.
    from .dev_a_baseline_scoring import DevABaselineScoringError, _json, _private_file
    from .omni_result_adapter import (
        OmniResultContractError,
        decode_result_artifact_rows,
    )

    relative = record.get("result_artifact_path")
    digest = record.get("result_artifact_sha256")
    if (
        not isinstance(relative, str)
        or not isinstance(digest, str)
        or record.get("actual_result_hash") != digest
        or record.get("actual_result_status") != "complete"
        or record.get("execution_status") != "complete"
        or record.get("result_artifact_schema_version") != 1
    ):
        raise SealedEvaluationError("sealed C4 result artifact binding is invalid")
    selected = Path(relative)
    if (
        selected.is_absolute()
        or not selected.parts
        or ".." in selected.parts
        or not any(selected.is_relative_to(root) for root in ALLOWED_RAW_ROOTS)
    ):
        raise SealedEvaluationError("sealed C4 result artifact path is invalid")
    try:
        content = _private_file(workspace, selected, "sealed C4 result artifact")
        if hashlib.sha256(content).hexdigest() != digest:
            raise SealedEvaluationError("sealed C4 result artifact hash is invalid")
        value = _json(content, "sealed C4 result artifact")
        return decode_result_artifact_rows(value)
    except SealedEvaluationError:
        raise
    except (DevABaselineScoringError, OmniResultContractError) as error:
        raise SealedEvaluationError("sealed C4 result artifact is invalid") from error


def _questions(value: object, plan: SealedExecutionPlan) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not isinstance(question, str) or not question
        for key, question in value.items()
    ):
        raise SealedEvaluationError("sealed public question map is invalid")
    result = dict(value)
    expected = {attempt.instance_id for attempt in plan.attempts}
    if set(result) != expected:
        raise SealedEvaluationError(
            "sealed public question set does not match the plan"
        )
    return result


def _output_root(workspace: Path, value: Path) -> Path:
    selected = Path(value)
    if (
        selected.is_absolute()
        or not selected.parts
        or ".." in selected.parts
        or not any(selected.is_relative_to(root) for root in ALLOWED_RAW_ROOTS)
    ):
        raise SealedEvaluationError("sealed cohort output root is invalid")
    candidate = workspace / selected
    try:
        if candidate.resolve(strict=False) != candidate:
            raise SealedEvaluationError("sealed cohort output root contains a symlink")
    except OSError as error:
        raise SealedEvaluationError(
            "sealed cohort output root is unavailable"
        ) from error
    return candidate


def _workspace(value: Path) -> Path:
    absolute = Path(value).absolute()
    try:
        resolved = Path(value).resolve(strict=True)
    except OSError as error:
        raise SealedEvaluationError("workspace is unavailable") from error
    if absolute != resolved or resolved.is_symlink() or not resolved.is_dir():
        raise SealedEvaluationError("workspace must be a non-symlink directory")
    return resolved

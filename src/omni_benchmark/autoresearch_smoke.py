"""Cross-condition telemetry smoke validation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .autoresearch_artifacts import MAX_RUN_ARTIFACT_BYTES, _resolve_raw_run_path
from .autoresearch_config import (
    AutoresearchConfig,
    AutoresearchError,
    _read_confined_private_jsonl,
)
from .autoresearch_provenance import validate_manifest_binding
from .autoresearch_runs import (
    _public_question_texts,
    _scope_definition,
    _validate_run_identity,
    _validate_run_record,
)

SMOKE_CONDITIONS = frozenset({"C1", "C2", "C3", "C4"})
SMOKE_SCOPES = frozenset({"train", "dev-a"})


@dataclass(frozen=True)
class TelemetrySmokeBundle:
    """One condition's generation artifact and exact bound run manifest."""

    condition: str
    generation_path: Path
    run_manifest_path: Path
    expected_run_manifest_sha256: str


@dataclass(frozen=True)
class _ValidatedSmokeAttempt:
    condition: str
    instance_id: str
    run_id: str
    repetition: int
    trace_captured: bool
    generation_sha256: str
    run_manifest_sha256: str


def validate_telemetry_smoke(
    config: AutoresearchConfig,
    bundles: Sequence[TelemetrySmokeBundle],
    *,
    scope: str = "train",
) -> dict[str, object]:
    """Validate one hash-bound public telemetry attempt for each condition."""
    if scope not in SMOKE_SCOPES:
        raise AutoresearchError("telemetry smoke scope must be train or dev-a")
    _validate_bundle_set(bundles)
    expected_partition, _, permitted_ids = _scope_definition(config, scope)
    public_questions = _public_question_texts(config)
    attempts = [
        _validate_smoke_bundle(
            config,
            bundle,
            scope=scope,
            expected_partition=expected_partition,
            permitted_ids=permitted_ids,
            public_questions=public_questions,
        )
        for bundle in bundles
    ]
    if not _has_matched_identity(attempts):
        raise AutoresearchError(
            "telemetry smoke must use the same question, run, and repetition"
        )
    return {
        "conditions": sorted(SMOKE_CONDITIONS),
        "generation_sha256_by_condition": {
            attempt.condition: attempt.generation_sha256 for attempt in attempts
        },
        "question_count": len(bundles),
        "run_manifest_sha256_by_condition": {
            attempt.condition: attempt.run_manifest_sha256 for attempt in attempts
        },
        "scope": scope,
        "trace_capture_by_condition": {
            attempt.condition: attempt.trace_captured for attempt in attempts
        },
    }


def _validate_smoke_bundle(
    config: AutoresearchConfig,
    bundle: TelemetrySmokeBundle,
    *,
    scope: str,
    expected_partition: str,
    permitted_ids: frozenset[str],
    public_questions: dict[str, str],
) -> _ValidatedSmokeAttempt:
    records, generation_sha256 = _read_smoke_generation(config, bundle)
    record = records[0]
    instance_id, _, _, _, _ = _validate_run_record(
        record,
        config,
        expected_partition,
        scored=False,
        public_questions=public_questions,
    )
    if instance_id not in permitted_ids:
        raise AutoresearchError(f"telemetry smoke question must belong to {scope}")
    condition, run_id, repetition = _validate_run_identity(
        records, f"{bundle.condition} telemetry smoke generation"
    )
    if condition != bundle.condition:
        raise AutoresearchError(
            "telemetry smoke declared condition does not match generation"
        )
    manifest = validate_manifest_binding(
        workspace=config.workspace,
        records=records,
        generation_sha256=generation_sha256,
        condition=condition,
        scope=scope,
        repetition=repetition,
        manifest_path=bundle.run_manifest_path,
        expected_manifest_sha256=bundle.expected_run_manifest_sha256,
        required=True,
    )
    if manifest is None:  # pragma: no cover - required=True makes this unreachable
        raise AutoresearchError("telemetry smoke run manifest is required")
    return _ValidatedSmokeAttempt(
        condition=condition,
        instance_id=instance_id,
        run_id=run_id,
        repetition=repetition,
        trace_captured=record["trace_captured"],
        generation_sha256=generation_sha256,
        run_manifest_sha256=manifest.sha256,
    )


def _read_smoke_generation(
    config: AutoresearchConfig, bundle: TelemetrySmokeBundle
) -> tuple[list[dict[str, object]], str]:
    description = f"{bundle.condition} telemetry smoke generation"
    generation_path = _resolve_raw_run_path(config, bundle.generation_path, description)
    records, generation_sha256 = _read_confined_private_jsonl(
        config.workspace,
        generation_path,
        description,
        maximum_bytes=MAX_RUN_ARTIFACT_BYTES,
    )
    if len(records) != 1:
        raise AutoresearchError(
            "each telemetry smoke generation must contain exactly one attempt"
        )
    return records, generation_sha256


def _has_matched_identity(attempts: Sequence[_ValidatedSmokeAttempt]) -> bool:
    identities = (
        {attempt.instance_id for attempt in attempts},
        {attempt.run_id for attempt in attempts},
        {attempt.repetition for attempt in attempts},
    )
    return all(len(values) == 1 for values in identities)


def _validate_bundle_set(bundles: Sequence[TelemetrySmokeBundle]) -> None:
    if len(bundles) != len(SMOKE_CONDITIONS):
        raise AutoresearchError(
            "telemetry smoke requires four individually bound condition bundles"
        )
    conditions = [bundle.condition for bundle in bundles]
    if len(set(conditions)) != len(conditions):
        raise AutoresearchError("telemetry smoke contains a duplicate condition bundle")
    if set(conditions) != SMOKE_CONDITIONS:
        raise AutoresearchError("telemetry smoke must cover C1, C2, C3, and C4")

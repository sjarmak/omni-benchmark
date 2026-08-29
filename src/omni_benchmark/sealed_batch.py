"""Generate-then-score gate for the final sealed evaluation batch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any

from .freeze_b import (
    CONDITIONS,
    REPETITIONS,
    FreezeBError,
    FreezeBManifest,
    SealedRunManifest,
    schedule_sha256,
)
from .sealed_scoring import (
    PostgreSQLIsolationProvider,
    ScoringMode,
    SealedQueryCase,
    SealedScoringResult,
    score_query_both,
    validate_query_case,
)

FINAL_GENERATION_TRIALS = 1_212
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class FrozenGenerationAttempt:
    """One already-generated attempt crossing into the sealed evaluator."""

    attempt_id: str
    condition: str
    repetition: int
    generation_sha256: str
    run_manifest_sha256: str
    generation_record_sha256: str
    candidate_sql: str | Sequence[str] = field(repr=False)


@dataclass(frozen=True)
class SealedGoldRecord:
    """Evaluator-only label fields, intentionally absent from repr."""

    attempt_id: str
    database: str
    gold_sql: str | Sequence[str] = field(repr=False)
    preprocess_sql: str | Sequence[str] = field(default=(), repr=False)
    cleanup_sql: str | Sequence[str] = field(default=(), repr=False)
    conditions: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class SealedBatchResult:
    """SQL-free results emitted only after the complete batch is validated."""

    attempt_ids: tuple[str, ...]
    official: tuple[SealedScoringResult, ...]
    sensitivity: tuple[SealedScoringResult, ...]

    def scores(self, mode: ScoringMode) -> tuple[SealedScoringResult, ...]:
        if mode is ScoringMode.OFFICIAL:
            return self.official
        if mode is ScoringMode.SENSITIVITY:
            return self.sensitivity
        raise ValueError("unsupported scoring mode")

    def score_records(self, mode: ScoringMode) -> tuple[dict[str, str], ...]:
        return tuple(
            result.as_score_record(attempt_id)
            for attempt_id, result in zip(
                self.attempt_ids, self.scores(mode), strict=True
            )
        )


def score_completed_generation(
    *,
    freeze_b: FreezeBManifest,
    run_manifests: Sequence[SealedRunManifest],
    generations: Sequence[FrozenGenerationAttempt],
    gold_records: Sequence[SealedGoldRecord],
    expected_attempt_ids: Sequence[str],
    provider: PostgreSQLIsolationProvider,
) -> SealedBatchResult:
    """Validate frozen provenance and full presence before touching hidden labels."""
    validated_freeze = _validated_freeze(freeze_b)
    expected = _expected_ids(expected_attempt_ids)
    if schedule_sha256(expected) != validated_freeze.schedule_sha256:
        raise ValueError("attempt schedule does not match Freeze B")
    manifests = _validated_run_manifests(run_manifests, validated_freeze)
    generation_by_id = _unique_by_id(generations, "generation")
    if set(generation_by_id) != set(expected):
        raise ValueError("generation attempt set does not match frozen schedule")
    _validate_generations(generation_by_id, manifests)
    gold_by_id = _unique_by_id(gold_records, "gold")
    if set(gold_by_id) != set(expected):
        raise ValueError("gold attempt set does not match frozen schedule")
    cases = tuple(
        _query_case(generation_by_id[attempt_id], gold_by_id[attempt_id])
        for attempt_id in expected
    )
    for case in cases:
        validate_query_case(case)
    paired_results = tuple(score_query_both(case, provider) for case in cases)
    return SealedBatchResult(
        attempt_ids=expected,
        official=tuple(result[0] for result in paired_results),
        sensitivity=tuple(result[1] for result in paired_results),
    )


def _expected_ids(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) != FINAL_GENERATION_TRIALS:
        raise ValueError("frozen schedule must contain exactly 1,212 attempts")
    if any(not isinstance(value, str) or not value for value in result):
        raise ValueError("expected attempt IDs must be non-empty strings")
    if len(set(result)) != len(result):
        raise ValueError("frozen schedule has duplicate attempt IDs")
    return result


def _unique_by_id(
    records: Sequence[FrozenGenerationAttempt] | Sequence[SealedGoldRecord],
    description: str,
) -> dict[str, FrozenGenerationAttempt] | dict[str, SealedGoldRecord]:
    result = {record.attempt_id: record for record in records}
    if len(result) != len(records):
        raise ValueError(f"duplicate {description} attempt ID")
    if any(not isinstance(attempt_id, str) or not attempt_id for attempt_id in result):
        raise ValueError(f"{description} attempt IDs must be non-empty strings")
    return result


def _validated_freeze(freeze_b: FreezeBManifest) -> FreezeBManifest:
    if not isinstance(freeze_b, FreezeBManifest):
        raise ValueError("scoring requires a validated Freeze B manifest")
    try:
        return FreezeBManifest.from_dict(freeze_b.as_dict())
    except FreezeBError as error:
        raise ValueError(f"invalid Freeze B manifest: {error}") from error


def _validated_run_manifests(
    run_manifests: Sequence[SealedRunManifest],
    freeze_b: FreezeBManifest,
) -> dict[tuple[str, int], SealedRunManifest]:
    expected_keys = {
        (condition, repetition)
        for condition in CONDITIONS
        for repetition in range(1, REPETITIONS + 1)
    }
    result: dict[tuple[str, int], SealedRunManifest] = {}
    for supplied in run_manifests:
        if not isinstance(supplied, SealedRunManifest):
            raise ValueError("sealed run manifests contain an invalid record")
        try:
            manifest = SealedRunManifest.from_dict(
                supplied.as_dict(), freeze_b=freeze_b
            )
        except FreezeBError as error:
            raise ValueError(
                f"sealed run manifest does not match Freeze B: {error}"
            ) from error
        key = (manifest.condition, manifest.repetition)
        if key in result:
            raise ValueError("duplicate sealed run manifest")
        result[key] = manifest
    if set(result) != expected_keys:
        raise ValueError("sealed run manifest set must contain C1-C4 repetitions 1-3")
    return result


def _validate_generations(
    generation_by_id: Mapping[str, FrozenGenerationAttempt],
    manifests: Mapping[tuple[str, int], SealedRunManifest],
) -> None:
    counts = {key: 0 for key in manifests}
    for attempt_id, generation in generation_by_id.items():
        condition, repetition = _attempt_coordinates(attempt_id)
        if generation.condition != condition or generation.repetition != repetition:
            raise ValueError(
                "generation condition/repetition does not match attempt ID"
            )
        key = (condition, repetition)
        manifest = manifests.get(key)
        if manifest is None:
            raise ValueError("generation has no matching sealed run manifest")
        if generation.generation_sha256 != manifest.generation_sha256:
            raise ValueError("generation sha256 does not match sealed run manifest")
        if generation.run_manifest_sha256 != manifest.sha256():
            raise ValueError("generation run_manifest_sha256 does not match")
        _digest(generation.generation_record_sha256, "generation_record_sha256")
        counts[key] += 1
    if any(count != 101 for count in counts.values()):
        raise ValueError("each sealed run manifest must bind exactly 101 generations")


def _attempt_coordinates(attempt_id: str) -> tuple[str, int]:
    try:
        _, condition, repetition_text = attempt_id.rsplit(":", 2)
        repetition = int(repetition_text)
    except (ValueError, TypeError) as error:
        raise ValueError("generation attempt ID has invalid coordinates") from error
    if condition not in CONDITIONS or repetition not in range(1, REPETITIONS + 1):
        raise ValueError("generation attempt ID has invalid coordinates")
    return condition, repetition


def _digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{description} must be a lowercase SHA-256")
    return value


def _query_case(
    generation: FrozenGenerationAttempt, gold: SealedGoldRecord
) -> SealedQueryCase:
    return SealedQueryCase(
        database=gold.database,
        candidate_sql=generation.candidate_sql,
        gold_sql=gold.gold_sql,
        preprocess_sql=gold.preprocess_sql,
        cleanup_sql=gold.cleanup_sql,
        conditions=gold.conditions,
    )

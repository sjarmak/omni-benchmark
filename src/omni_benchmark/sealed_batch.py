"""Generate-then-score gate for the final sealed evaluation batch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .sealed_scoring import (
    PostgreSQLIsolationProvider,
    ScoringMode,
    SealedQueryCase,
    SealedScoringResult,
    score_query_both,
    validate_query_case,
)

FINAL_GENERATION_TRIALS = 1_212


@dataclass(frozen=True)
class FrozenGenerationAttempt:
    """One already-generated attempt crossing into the sealed evaluator."""

    attempt_id: str
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
    generations: Sequence[FrozenGenerationAttempt],
    gold_records: Sequence[SealedGoldRecord],
    expected_attempt_ids: Sequence[str],
    provider: PostgreSQLIsolationProvider,
) -> SealedBatchResult:
    """Validate full schedule presence before executing any hidden label."""
    expected = _expected_ids(expected_attempt_ids)
    generation_by_id = _unique_by_id(generations, "generation")
    gold_by_id = _unique_by_id(gold_records, "gold")
    if set(generation_by_id) != set(expected):
        raise ValueError("generation attempt set does not match frozen schedule")
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

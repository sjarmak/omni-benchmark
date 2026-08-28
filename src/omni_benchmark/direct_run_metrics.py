"""Pure aggregation for validated direct-comparator run observations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .autoresearch_config import _sha256_bytes
from .autoresearch_metrics import ValidatedRun, median_iqr
from .autoresearch_provenance import ValidatedManifestBinding


@dataclass(frozen=True)
class DirectRunObservation:
    instance_id: str
    outcome: str
    generation_outcome: str
    latency: float
    cost: float | None
    total_tokens: int | None
    tool_calls: int | None
    database_queries: int | None
    category: str | None
    terminal_failure: str | None


@dataclass(frozen=True)
class DirectRunMetrics:
    correct_ids: frozenset[str]
    wrong_ids: frozenset[str]
    refused_or_error_ids: frozenset[str]
    refused_ids: frozenset[str]
    errored_ids: frozenset[str]
    mean_latency: float
    median_latency: float
    iqr_latency: float
    total_cost: float | None
    total_tokens: int | None
    median_tokens: float | None
    iqr_tokens: float | None
    total_tool_calls: int | None
    total_database_queries: int | None
    categories: tuple[tuple[str, int], ...]
    terminal_failures: tuple[tuple[str, int], ...]


def aggregate_run_metrics(
    observations: tuple[DirectRunObservation, ...],
) -> DirectRunMetrics:
    latencies = [value.latency for value in observations]
    token_counts = [value.total_tokens for value in observations]
    total_tokens = _optional_sum(token_counts)
    median_tokens, iqr_tokens = (
        (None, None) if total_tokens is None else median_iqr(token_counts)  # type: ignore[arg-type]
    )
    median_latency, iqr_latency = median_iqr(latencies)
    return DirectRunMetrics(
        correct_ids=_ids_for_outcome(observations, "correct"),
        wrong_ids=_ids_for_outcome(observations, "wrong_answer"),
        refused_or_error_ids=_ids_for_outcome(observations, "refused_or_error"),
        refused_ids=_ids_for_generation_outcome(observations, "refused"),
        errored_ids=_ids_for_generation_outcome(observations, "errored"),
        mean_latency=sum(latencies) / len(latencies),
        median_latency=median_latency,
        iqr_latency=iqr_latency,
        total_cost=_optional_sum([value.cost for value in observations]),
        total_tokens=total_tokens,
        median_tokens=median_tokens,
        iqr_tokens=iqr_tokens,
        total_tool_calls=_optional_sum([value.tool_calls for value in observations]),
        total_database_queries=_optional_sum(
            [value.database_queries for value in observations]
        ),
        categories=_counter_pairs(value.category for value in observations),
        terminal_failures=_counter_pairs(
            value.terminal_failure for value in observations
        ),
    )


def combined_run_sha(
    generation_sha256: str,
    score_sha256: str | None,
    manifest: ValidatedManifestBinding | None,
) -> str:
    combined = generation_sha256
    if score_sha256 is not None:
        combined = _sha256_bytes(f"{combined}:{score_sha256}".encode())
    if manifest is not None:
        combined = _sha256_bytes(f"{combined}:{manifest.sha256}".encode())
    return combined


def make_validated_run(
    *,
    run_path: Path,
    combined_sha256: str,
    generation_sha256: str,
    score_path: Path | None,
    score_sha256: str | None,
    question_count: int,
    scope: str,
    condition: str,
    run_id: str,
    repetition: int,
    metrics: DirectRunMetrics,
    manifest: ValidatedManifestBinding | None,
) -> ValidatedRun:
    return ValidatedRun(
        path=run_path,
        sha256=combined_sha256,
        generation_sha256=generation_sha256,
        score_path=score_path,
        score_sha256=score_sha256,
        question_count=question_count,
        scope=scope,
        condition=condition,
        run_id=run_id,
        repetition=repetition,
        correct_ids=metrics.correct_ids,
        wrong_answer_ids=metrics.wrong_ids,
        refused_or_error_ids=metrics.refused_or_error_ids,
        refused_ids=metrics.refused_ids,
        errored_ids=metrics.errored_ids,
        refusal_observable=condition != "C4",
        mean_latency_ms=metrics.mean_latency,
        median_latency_ms=metrics.median_latency,
        iqr_latency_ms=metrics.iqr_latency,
        total_cost_usd=metrics.total_cost,
        total_tokens=metrics.total_tokens,
        median_tokens=metrics.median_tokens,
        iqr_tokens=metrics.iqr_tokens,
        total_tool_calls=metrics.total_tool_calls,
        total_database_queries=metrics.total_database_queries,
        failure_categories=metrics.categories,
        terminal_failure_classes=metrics.terminal_failures,
        run_manifest_path=None if manifest is None else manifest.path,
        run_manifest_sha256=None if manifest is None else manifest.sha256,
    )


def _ids_for_outcome(
    observations: tuple[DirectRunObservation, ...], outcome: str
) -> frozenset[str]:
    return frozenset(
        value.instance_id for value in observations if value.outcome == outcome
    )


def _ids_for_generation_outcome(
    observations: tuple[DirectRunObservation, ...], generation_outcome: str
) -> frozenset[str]:
    return frozenset(
        value.instance_id
        for value in observations
        if value.generation_outcome == generation_outcome
    )


def _optional_sum(values: list[int | float | None]) -> int | float | None:
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _counter_pairs(values: Iterable[str | None]) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(Counter(value for value in values if value is not None).items())
    )

"""Immutable summaries and derived metrics for validated run artifacts."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from pathlib import Path

from .autoresearch_config import _display_path


def median_iqr(values: list[float | int]) -> tuple[float, float]:
    """Return median and inclusive interquartile range."""
    median = float(statistics.median(values))
    if len(values) < 2:
        return median, 0.0
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return median, float(quartiles[2] - quartiles[0])


def _per_attempt(total: int | None, attempts: int) -> float | None:
    return None if total is None else total / attempts


def _per_correct(total: int | None, correct: int) -> float | None:
    return None if total is None or correct == 0 else total / correct


@dataclass(frozen=True)
class ValidatedRun:
    """Mechanically validated full-training result summary."""

    path: Path
    sha256: str
    generation_sha256: str
    score_path: Path | None
    score_sha256: str | None
    question_count: int
    scope: str
    condition: str
    run_id: str
    repetition: int
    correct_ids: frozenset[str]
    wrong_answer_ids: frozenset[str]
    refused_or_error_ids: frozenset[str]
    refused_ids: frozenset[str]
    errored_ids: frozenset[str]
    refusal_observable: bool
    mean_latency_ms: float
    median_latency_ms: float
    iqr_latency_ms: float
    total_cost_usd: float | None
    total_tokens: int | None
    median_tokens: float | None
    iqr_tokens: float | None
    total_tool_calls: int | None
    total_database_queries: int | None
    failure_categories: tuple[tuple[str, int], ...]
    terminal_failure_classes: tuple[tuple[str, int], ...]
    run_manifest_path: Path | None = None
    run_manifest_sha256: str | None = None

    @property
    def accuracy(self) -> float:
        return len(self.correct_ids) / self.question_count

    @property
    def wrong_answer_rate(self) -> float:
        return len(self.wrong_answer_ids) / self.question_count

    @property
    def refused_or_error_rate(self) -> float:
        return len(self.refused_or_error_ids) / self.question_count

    @property
    def refusal_rate(self) -> float | None:
        if not self.refusal_observable:
            return None
        return len(self.refused_ids) / self.question_count

    @property
    def error_rate(self) -> float:
        return len(self.errored_ids) / self.question_count

    @property
    def tokens_per_correct(self) -> float | None:
        return _per_correct(self.total_tokens, len(self.correct_ids))

    @property
    def tool_calls_per_attempt(self) -> float | None:
        return _per_attempt(self.total_tool_calls, self.question_count)

    @property
    def tool_calls_per_correct(self) -> float | None:
        return _per_correct(self.total_tool_calls, len(self.correct_ids))

    @property
    def database_queries_per_attempt(self) -> float | None:
        return _per_attempt(self.total_database_queries, self.question_count)

    @property
    def database_queries_per_correct(self) -> float | None:
        return _per_correct(self.total_database_queries, len(self.correct_ids))

    def as_manifest(self, workspace: Path) -> dict[str, object]:
        return {
            "accuracy": self.accuracy,
            "correct_count": len(self.correct_ids),
            "condition": self.condition,
            "failure_categories": dict(self.failure_categories),
            "terminal_failure_classes": dict(self.terminal_failure_classes),
            "database_queries_per_attempt": self.database_queries_per_attempt,
            "database_queries_per_correct": self.database_queries_per_correct,
            "iqr_latency_ms": self.iqr_latency_ms,
            "iqr_tokens": self.iqr_tokens,
            "mean_latency_ms": self.mean_latency_ms,
            "median_latency_ms": self.median_latency_ms,
            "median_tokens": self.median_tokens,
            "path": _display_path(self.path, workspace),
            "question_count": self.question_count,
            "refused_count": (
                len(self.refused_ids) if self.refusal_observable else None
            ),
            "refusal_observable": self.refusal_observable,
            "refusal_rate": self.refusal_rate,
            "refused_or_error_count": len(self.refused_or_error_ids),
            "refused_or_error_rate": self.refused_or_error_rate,
            "errored_count": len(self.errored_ids),
            "error_rate": self.error_rate,
            "repetition": self.repetition,
            "run_id": self.run_id,
            "run_manifest_path": (
                None
                if self.run_manifest_path is None
                else _display_path(self.run_manifest_path, workspace)
            ),
            "run_manifest_sha256": self.run_manifest_sha256,
            "generation_sha256": self.generation_sha256,
            "score_path": (
                None
                if self.score_path is None
                else _display_path(self.score_path, workspace)
            ),
            "score_sha256": self.score_sha256,
            "sha256": self.sha256,
            "scope": self.scope,
            "total_cost_usd": self.total_cost_usd,
            "total_database_queries": self.total_database_queries,
            "total_tokens": self.total_tokens,
            "total_tool_calls": self.total_tool_calls,
            "tokens_per_correct": self.tokens_per_correct,
            "tool_calls_per_attempt": self.tool_calls_per_attempt,
            "tool_calls_per_correct": self.tool_calls_per_correct,
            "wrong_answer_rate": self.wrong_answer_rate,
        }


@dataclass(frozen=True)
class ValidatedBaselineOutputs:
    """Public-only generated outputs frozen before hidden labels are released."""

    path: Path
    sha256: str
    question_count: int
    run_manifest_path: Path | None = None
    run_manifest_sha256: str | None = None

    def as_manifest(self, workspace: Path) -> dict[str, object]:
        return {
            "path": _display_path(self.path, workspace),
            "question_count": self.question_count,
            "run_manifest_path": (
                None
                if self.run_manifest_path is None
                else _display_path(self.run_manifest_path, workspace)
            ),
            "run_manifest_sha256": self.run_manifest_sha256,
            "scored": False,
            "sha256": self.sha256,
            "scope": "train",
        }


@dataclass(frozen=True)
class ValidatedGenerationOutputs:
    """Immutable unscored generation summary for train or dev-A."""

    path: Path
    sha256: str
    question_count: int
    scope: str
    condition: str
    run_id: str
    repetition: int
    run_manifest_path: Path | None = None
    run_manifest_sha256: str | None = None

    def as_manifest(self, workspace: Path) -> dict[str, object]:
        return {
            "condition": self.condition,
            "path": _display_path(self.path, workspace),
            "question_count": self.question_count,
            "repetition": self.repetition,
            "run_id": self.run_id,
            "run_manifest_path": (
                None
                if self.run_manifest_path is None
                else _display_path(self.run_manifest_path, workspace)
            ),
            "run_manifest_sha256": self.run_manifest_sha256,
            "scored": False,
            "sha256": self.sha256,
            "scope": self.scope,
        }

"""Pure experiment-delta and Pareto calculations."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .autoresearch_config import AutoresearchError, _require_string
from .autoresearch_metrics import ValidatedRun


def guard_intervention_text(text: str, train_ids: Iterable[str]) -> None:
    """Reject exact benchmark IDs in implementation descriptions or patches."""
    _require_string(text, "intervention")
    for instance_id in train_ids:
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(instance_id)}(?![A-Za-z0-9_])"
        if re.search(pattern, text) is not None:
            raise AutoresearchError(
                "intervention contains an exact benchmark instance ID"
            )


def outcome_for(run: ValidatedRun, instance_id: str) -> str:
    """Return the three-state outcome for one validated attempt."""
    if instance_id in run.correct_ids:
        return "correct"
    if instance_id in run.wrong_answer_ids:
        return "wrong_answer"
    return "refused_or_error"


def _optional_delta(left: int | None, right: int | None) -> int | None:
    return None if left is None or right is None else right - left


def _optional_rate_delta(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else right - left


def _outcome_transitions(before: ValidatedRun, after: ValidatedRun) -> dict[str, int]:
    transitions: dict[str, int] = {}
    instance_ids = (
        before.correct_ids | before.wrong_answer_ids | before.refused_or_error_ids
    )
    for instance_id in sorted(instance_ids):
        transition = (
            f"{outcome_for(before, instance_id)}->{outcome_for(after, instance_id)}"
        )
        transitions[transition] = transitions.get(transition, 0) + 1
    return transitions


def _generation_outcome_for(run: ValidatedRun, instance_id: str) -> str:
    if instance_id in run.refused_ids:
        return "refused"
    if instance_id in run.errored_ids:
        return "errored"
    return "answered"


def _generation_outcome_transitions(
    before: ValidatedRun, after: ValidatedRun
) -> dict[str, int]:
    transitions: dict[str, int] = {}
    instance_ids = (
        before.correct_ids | before.wrong_answer_ids | before.refused_or_error_ids
    )
    for instance_id in sorted(instance_ids):
        transition = (
            f"{_generation_outcome_for(before, instance_id)}"
            f"->{_generation_outcome_for(after, instance_id)}"
        )
        transitions[transition] = transitions.get(transition, 0) + 1
    return transitions


def run_deltas(before: ValidatedRun, after: ValidatedRun) -> dict[str, object]:
    """Calculate all preregistered question and telemetry deltas."""
    before_categories = dict(before.failure_categories)
    after_categories = dict(after.failure_categories)
    category_names = before_categories.keys() | after_categories.keys()
    before_terminal = dict(before.terminal_failure_classes)
    after_terminal = dict(after.terminal_failure_classes)
    terminal_names = before_terminal.keys() | after_terminal.keys()
    cost_delta = (
        None
        if before.total_cost_usd is None or after.total_cost_usd is None
        else after.total_cost_usd - before.total_cost_usd
    )
    return {
        "accuracy_delta": after.accuracy - before.accuracy,
        "after_accuracy": after.accuracy,
        "before_accuracy": before.accuracy,
        "failure_category_changes": {
            name: after_categories.get(name, 0) - before_categories.get(name, 0)
            for name in sorted(category_names)
        },
        "fixed_questions": sorted(after.correct_ids - before.correct_ids),
        "generation_outcome_transitions": _generation_outcome_transitions(
            before, after
        ),
        "mean_latency_delta_ms": after.mean_latency_ms - before.mean_latency_ms,
        "outcome_transitions": _outcome_transitions(before, after),
        "refused_or_error_rate_delta": (
            after.refused_or_error_rate - before.refused_or_error_rate
        ),
        "refusal_rate_delta": _optional_rate_delta(
            before.refusal_rate, after.refusal_rate
        ),
        "error_rate_delta": after.error_rate - before.error_rate,
        "regressed_questions": sorted(before.correct_ids - after.correct_ids),
        "terminal_failure_class_changes": {
            name: after_terminal.get(name, 0) - before_terminal.get(name, 0)
            for name in sorted(terminal_names)
        },
        "total_cost_delta_usd": cost_delta,
        "total_database_query_delta": _optional_delta(
            before.total_database_queries, after.total_database_queries
        ),
        "total_token_delta": _optional_delta(before.total_tokens, after.total_tokens),
        "total_tool_call_delta": _optional_delta(
            before.total_tool_calls, after.total_tool_calls
        ),
        "wrong_answer_rate_delta": after.wrong_answer_rate - before.wrong_answer_rate,
    }


def dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Return whether one candidate strictly Pareto-dominates another."""
    maximize = ("accuracy", "stability", "generality")
    minimize = (
        "wrong_answer_rate",
        "refused_or_error_rate",
        "regression_count",
        "cost",
        "latency",
        "complexity",
        "special_case_count",
    )
    dimensions = (*maximize, *minimize)
    if any(left[key] is None or right[key] is None for key in dimensions):
        return False
    no_worse = all(left[key] >= right[key] for key in maximize) and all(
        left[key] <= right[key] for key in minimize
    )
    strictly_better = any(left[key] > right[key] for key in maximize) or any(
        left[key] < right[key] for key in minimize
    )
    return no_worse and strictly_better


def pareto_frontier(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return kept candidates not dominated within their own condition."""
    candidates = [
        event
        for event in events
        if event.get("event") == "decision" and event.get("decision") == "KEEP"
    ]
    return [
        candidate
        for candidate in candidates
        if not any(
            other is not candidate
            and other.get("condition") == candidate.get("condition")
            and dominates(other["candidate_vector"], candidate["candidate_vector"])
            for other in candidates
        )
    ]

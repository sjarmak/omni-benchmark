"""Typed product contract and aggregate oracle for measure-selection traces."""

from __future__ import annotations

import copy
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .protected_fields import ProtectedFieldError, reject_protected_fields


class MeasureSelectionTraceError(ValueError):
    """Raised when a measure-selection trace cannot support a scored claim."""


MEASURE_POLICIES = frozenset({"allow_inline", "prefer_measures", "require_measures"})
QUERY_PATHS = frozenset({"semantic_query", "templated_sql", "physical_sql", "no_query"})
METRIC_PATHS = frozenset(
    {"governed_measure", "mixed", "inline", "not_applicable", "unknown"}
)
RETRIEVAL_STATUSES = frozenset(
    {"not_applicable", "not_attempted", "no_candidates", "candidates_found", "failed"}
)
DECISIONS = frozenset({"selected", "rejected"})
SELECTED_REASON_CODES = frozenset(
    {
        "exact_semantic_match",
        "user_named_measure",
        "policy_required_best_match",
        "composed_metric_dependency",
    }
)
REJECTED_REASON_CODES = frozenset(
    {
        "lower_ranked_exact_match",
        "ambiguous_match",
        "semantic_mismatch",
        "grain_mismatch",
        "filter_mismatch",
        "aggregation_mismatch",
        "unavailable_in_topic",
        "access_denied",
        "unsupported_query_shape",
    }
)
FALLBACK_REASON_CODES = frozenset(
    {
        "no_measure_candidate",
        "candidate_ambiguous",
        "candidate_grain_mismatch",
        "candidate_filter_mismatch",
        "candidate_aggregation_mismatch",
        "candidate_unavailable_in_topic",
        "candidate_access_denied",
        "unsupported_query_shape",
        "retrieval_failed",
        "inline_allowed_by_policy",
        "partial_measure_coverage",
        "user_requested_sql",
        "no_query",
        "unknown",
    }
)

_TRACE_KEYS = frozenset(
    {
        "attempt_id",
        "fallback_reason_code",
        "inline_equivalent_measure_ids",
        "measure_decisions",
        "measure_policy",
        "metric_path",
        "query_path",
        "retrieval_status",
        "schema_version",
    }
)
_DECISION_KEYS = frozenset({"decision", "detail", "measure_id", "reason_code"})
_DECISION_REQUIRED_KEYS = frozenset({"decision", "measure_id", "reason_code"})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


def validate_measure_selection_trace(value: object) -> dict[str, Any]:
    """Validate one proposed product trace using closed scored vocabularies."""
    trace = _mapping(value, "measure-selection trace")
    _reject_protected(trace)
    if set(trace) != _TRACE_KEYS:
        raise MeasureSelectionTraceError("measure-selection trace fields are invalid")
    if trace["schema_version"] != 1 or isinstance(trace["schema_version"], bool):
        raise MeasureSelectionTraceError("schema_version must be 1")

    _identifier(trace["attempt_id"], "attempt_id")
    _enum(trace["measure_policy"], MEASURE_POLICIES, "measure_policy")
    query_path = _enum(trace["query_path"], QUERY_PATHS, "query_path")
    metric_path = _enum(trace["metric_path"], METRIC_PATHS, "metric_path")
    retrieval_status = _enum(
        trace["retrieval_status"], RETRIEVAL_STATUSES, "retrieval_status"
    )

    fallback = trace["fallback_reason_code"]
    if fallback is not None:
        _enum(fallback, FALLBACK_REASON_CODES, "fallback_reason_code")

    inline_ids = _identifier_list(
        trace["inline_equivalent_measure_ids"],
        "inline_equivalent_measure_ids",
    )
    raw_decisions = _sequence(trace["measure_decisions"], "measure_decisions")
    decisions: list[Mapping[str, Any]] = []
    decision_ids: set[str] = set()
    selected_ids: set[str] = set()
    for index, raw_decision in enumerate(raw_decisions):
        decision = _mapping(raw_decision, f"measure_decisions[{index}]")
        if not _DECISION_REQUIRED_KEYS.issubset(decision) or not set(decision).issubset(
            _DECISION_KEYS
        ):
            raise MeasureSelectionTraceError(
                f"measure_decisions[{index}] fields are invalid"
            )
        measure_id = _identifier(
            decision["measure_id"], f"measure_decisions[{index}].measure_id"
        )
        if measure_id in decision_ids:
            raise MeasureSelectionTraceError("measure decision IDs must be unique")
        decision_ids.add(measure_id)
        disposition = _enum(
            decision["decision"], DECISIONS, f"measure_decisions[{index}].decision"
        )
        allowed_reasons = (
            SELECTED_REASON_CODES
            if disposition == "selected"
            else REJECTED_REASON_CODES
        )
        _enum(
            decision["reason_code"],
            allowed_reasons,
            f"measure_decisions[{index}].reason_code",
        )
        if "detail" in decision:
            detail = decision["detail"]
            if not isinstance(detail, str) or not detail.strip() or len(detail) > 2048:
                raise MeasureSelectionTraceError(
                    f"measure_decisions[{index}].detail is invalid"
                )
        if disposition == "selected":
            selected_ids.add(measure_id)
        decisions.append(decision)

    if retrieval_status == "candidates_found" and not decisions:
        raise MeasureSelectionTraceError(
            "candidates_found retrieval requires measure decisions"
        )
    if retrieval_status != "candidates_found" and decisions:
        raise MeasureSelectionTraceError(
            "measure decisions require candidates_found retrieval"
        )

    if metric_path == "governed_measure":
        if not selected_ids or inline_ids or fallback is not None:
            raise MeasureSelectionTraceError("governed_measure trace is inconsistent")
    elif metric_path == "mixed":
        if not selected_ids or not inline_ids or fallback is None:
            raise MeasureSelectionTraceError("mixed trace is inconsistent")
    elif metric_path == "inline":
        if selected_ids or fallback is None:
            raise MeasureSelectionTraceError("inline trace is inconsistent")
    elif metric_path == "not_applicable":
        if (
            retrieval_status != "not_applicable"
            or decisions
            or inline_ids
            or fallback is not None
        ):
            raise MeasureSelectionTraceError("not_applicable trace is inconsistent")
    elif fallback is None:
        raise MeasureSelectionTraceError(
            "unknown metric path requires a fallback reason"
        )

    if query_path == "no_query" and metric_path != "unknown":
        raise MeasureSelectionTraceError("no_query requires an unknown metric path")
    if query_path != "no_query" and fallback == "no_query":
        raise MeasureSelectionTraceError("no_query fallback requires no_query path")
    return copy.deepcopy(dict(trace))


def build_measure_selection_acceptance_report(
    traces: Sequence[Mapping[str, object]],
    opportunities: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    """Build an aggregate-only acceptance report against frozen opportunities."""
    if isinstance(traces, (str, bytes)):
        raise MeasureSelectionTraceError("traces must be a sequence")
    validated = [validate_measure_selection_trace(trace) for trace in traces]
    by_attempt: dict[str, dict[str, Any]] = {}
    for trace in validated:
        attempt_id = trace["attempt_id"]
        if attempt_id in by_attempt:
            raise MeasureSelectionTraceError("trace attempt IDs must be unique")
        by_attempt[attempt_id] = trace
    if set(opportunities) != set(by_attempt):
        raise MeasureSelectionTraceError("trace and opportunity IDs must match exactly")

    normalized_opportunities: dict[str, frozenset[str]] = {}
    for attempt_id, raw_measure_ids in opportunities.items():
        _identifier(attempt_id, "opportunity attempt ID")
        measure_ids = _identifier_list(raw_measure_ids, f"opportunities[{attempt_id}]")
        normalized_opportunities[attempt_id] = frozenset(measure_ids)

    opportunity_count = 0
    retrieved_count = 0
    selected_count = 0
    governed_count = 0
    inline_count = 0
    policy_violation_count = 0
    decision_reason_counts: dict[str, Counter[str]] = {
        "rejected": Counter(),
        "selected": Counter(),
    }
    fallback_reason_counts: Counter[str] = Counter()
    query_path_counts: Counter[str] = Counter()
    metric_path_counts: Counter[str] = Counter()
    retrieval_status_counts: Counter[str] = Counter()

    for attempt_id, trace in by_attempt.items():
        expected_ids = normalized_opportunities[attempt_id]
        query_path_counts[trace["query_path"]] += 1
        metric_path_counts[trace["metric_path"]] += 1
        retrieval_status_counts[trace["retrieval_status"]] += 1
        if trace["fallback_reason_code"] is not None:
            fallback_reason_counts[trace["fallback_reason_code"]] += 1
        selected_ids = {
            decision["measure_id"]
            for decision in trace["measure_decisions"]
            if decision["decision"] == "selected"
        }
        for decision in trace["measure_decisions"]:
            decision_reason_counts[decision["decision"]][decision["reason_code"]] += 1

        if not expected_ids:
            continue
        opportunity_count += 1
        retrieved_count += trace["retrieval_status"] == "candidates_found"
        mapped_selected = bool(expected_ids.intersection(selected_ids))
        selected_count += mapped_selected
        governed_count += trace["metric_path"] == "governed_measure" and mapped_selected
        inline_count += trace["metric_path"] in {"inline", "mixed"}
        policy_violation_count += (
            trace["measure_policy"] == "require_measures"
            and trace["metric_path"] != "governed_measure"
        )

    return {
        "decision_reason_counts": {
            decision: dict(sorted(counts.items()))
            for decision, counts in decision_reason_counts.items()
        },
        "fallback_reason_counts": dict(sorted(fallback_reason_counts.items())),
        "information_boundary": {
            "emits_attempt_ids": False,
            "free_form_detail_scored": False,
            "hidden_annotations_used": False,
            "question_text_used": False,
            "result_values_used": False,
            "sealed_test_used": False,
        },
        "kind": "measure-selection-acceptance-report",
        "metric_path_counts": dict(sorted(metric_path_counts.items())),
        "query_path_counts": dict(sorted(query_path_counts.items())),
        "retrieval_status_counts": dict(sorted(retrieval_status_counts.items())),
        "schema_version": 1,
        "summary": {
            "attempt_count": len(validated),
            "governed_measure_opportunity_count": governed_count,
            "governed_measure_opportunity_rate": _rate(
                governed_count, opportunity_count
            ),
            "inline_fallback_opportunity_count": inline_count,
            "mapped_measure_selected_count": selected_count,
            "mapped_measure_selected_rate": _rate(selected_count, opportunity_count),
            "opportunity_count": opportunity_count,
            "policy_violation_count": policy_violation_count,
            "retrieved_opportunity_count": retrieved_count,
            "retrieved_opportunity_rate": _rate(retrieved_count, opportunity_count),
        },
    }


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MeasureSelectionTraceError(f"{label} must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MeasureSelectionTraceError(f"{label} must be an array")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise MeasureSelectionTraceError(f"{label} is invalid")
    return value


def _identifier_list(value: object, label: str) -> tuple[str, ...]:
    items = _sequence(value, label)
    result = tuple(_identifier(item, f"{label} item") for item in items)
    if len(result) != len(set(result)):
        raise MeasureSelectionTraceError(f"{label} must contain unique IDs")
    return result


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise MeasureSelectionTraceError(f"{label} is not an allowed enum value")
    return value


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _reject_protected(value: object) -> None:
    try:
        reject_protected_fields(value)
    except ProtectedFieldError as error:
        raise MeasureSelectionTraceError(
            "measure-selection trace contains a protected field"
        ) from error

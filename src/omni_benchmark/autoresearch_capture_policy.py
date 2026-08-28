"""Validation policy for captured attempt outcomes and telemetry."""

from __future__ import annotations

from typing import Any, Mapping

from .autoresearch_artifacts import _count, _validate_trace_reference
from .autoresearch_config import AutoresearchError


def validate_capture_telemetry(record: Mapping[str, Any]) -> None:
    """Validate outcome, failure ownership, and telemetry availability together."""
    _validate_outcome(record)
    _validate_failure(record)
    _validate_sources(record)
    _validate_unavailable_counts(record)
    _validate_tool_breakdown(record)
    _validate_trace_reference(record)


def _validate_outcome(record: Mapping[str, Any]) -> None:
    generation_outcome = record["generation_outcome"]
    if generation_outcome not in {"answered", "refused", "errored"}:
        raise AutoresearchError(
            "generation_outcome must be answered, refused, or errored"
        )
    scored_outcome = record.get("outcome")
    if (
        scored_outcome in {"correct", "wrong_answer"}
        and generation_outcome != "answered"
    ):
        raise AutoresearchError(
            "answered scored outcomes require generation_outcome answered"
        )
    if scored_outcome == "refused_or_error" and generation_outcome == "answered":
        raise AutoresearchError(
            "refused_or_error requires generation_outcome refused or errored"
        )


def _validate_failure(record: Mapping[str, Any]) -> None:
    generation_outcome = record["generation_outcome"]
    failure_origin = record["failure_origin"]
    if failure_origin not in {
        None,
        "benchmark_infrastructure",
        "evaluated_system",
    }:
        raise AutoresearchError(
            "failure_origin must be benchmark_infrastructure, evaluated_system, or null"
        )
    failure_class = record["terminal_failure_class"]
    if generation_outcome == "answered" and any(
        value is not None
        for value in (failure_origin, failure_class, record["harness_failure"])
    ):
        raise AutoresearchError(
            "answered attempts cannot declare a terminal evaluated-system failure"
        )
    if generation_outcome in {"refused", "errored"} and (
        failure_origin not in {"benchmark_infrastructure", "evaluated_system"}
        or failure_class is None
    ):
        raise AutoresearchError(
            "refused or errored attempts require failure_origin and a terminal failure class"
        )
    if failure_origin == "benchmark_infrastructure" and generation_outcome != "errored":
        raise AutoresearchError(
            "benchmark infrastructure failures must be errored attempts"
        )


def _validate_sources(record: Mapping[str, Any]) -> None:
    for source_field, value_field in (
        ("token_source", "token_usage"),
        ("cost_source", "cost_usd"),
    ):
        source = record[source_field]
        if source not in {"provider_reported", "derived", "unavailable"}:
            raise AutoresearchError(
                f"{source_field} must be provider_reported, derived, or unavailable"
            )
        if (record[value_field] is None) != (source == "unavailable"):
            raise AutoresearchError(
                f"{source_field} must disclose whether {value_field} is available"
            )


def _validate_unavailable_counts(record: Mapping[str, Any]) -> None:
    supported_fields = {
        "tool_call_count",
        "database_query_count",
        "retry_count",
        "validation_attempt_count",
        "model_provider",
        "model_name",
        "model_version",
    }
    unavailable = record["telemetry_unavailable"]
    if (
        not isinstance(unavailable, list)
        or len(set(unavailable)) != len(unavailable)
        or any(field not in supported_fields for field in unavailable)
    ):
        raise AutoresearchError(
            "telemetry_unavailable must contain unique supported telemetry fields"
        )
    null_fields = {
        field
        for field in supported_fields
        if (
            record[field] is None
            if field in record
            else record["model"][field.removeprefix("model_")] is None
        )
    }
    if set(unavailable) != null_fields:
        raise AutoresearchError(
            "telemetry_unavailable must exactly identify unavailable counts"
        )


def _validate_tool_breakdown(record: Mapping[str, Any]) -> None:
    breakdown = record["tool_calls_by_name"]
    if not isinstance(breakdown, list):
        raise AutoresearchError("tool_calls_by_name must be an array")
    names: set[str] = set()
    total = 0
    for item in breakdown:
        if not isinstance(item, dict) or set(item) != {"name", "count"}:
            raise AutoresearchError(
                "tool_calls_by_name entries must contain name and count"
            )
        name = item["name"]
        count = item["count"]
        if not isinstance(name, str) or not name or name in names:
            raise AutoresearchError("tool_calls_by_name names must be unique strings")
        try:
            validated_count = _count(count, "tool_calls_by_name count", nullable=False)
        except AutoresearchError as error:
            raise AutoresearchError(
                "tool_calls_by_name counts must be non-negative integers"
            ) from error
        names.add(name)
        total += validated_count  # type: ignore[operator]
    observed_total = record["tool_call_count"]
    if observed_total is None and breakdown:
        raise AutoresearchError(
            "tool_calls_by_name must be empty when tool_call_count is unavailable"
        )
    if observed_total is not None and total != observed_total:
        raise AutoresearchError("tool_calls_by_name must sum to tool_call_count")

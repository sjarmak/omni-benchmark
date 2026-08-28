"""Validate direct-SQL trace structure, lifecycle, and telemetry."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .autoresearch_artifacts import TRACE_EVENT_FIELDS, TRACE_SCHEMA_VERSION
from .content_policy import ContentPolicy
from .direct_action_protocol import DIRECT_TOOL_NAMES
from .direct_capture_contract import (
    DirectCondition,
    DirectModelTurnProvenance,
    DirectProbeResult,
)
from .direct_sql_result import DirectResultError, validate_json_value
from .omni_result_adapter import reject_forbidden_keys

_SHA256 = re.compile(r"[0-9a-f]{64}")
_TRACE_EVENT_TYPES = frozenset(
    {
        "direct_capture_failure",
        "direct_final_sql_execution",
        "direct_model_turn",
        "direct_refusal",
        "direct_tool_dispatch",
    }
)
_CAPTURE_FAILURES = frozenset(
    {"invalid_model_action", "unauthorized_tool", "turn_limit_exhausted"}
)
_MODEL_FAILURES = frozenset(
    {
        "model_auth_error",
        "model_budget_error",
        "model_identity_mismatch",
        "model_infrastructure_error",
        "model_protocol_error",
        "model_quota_error",
        "model_rate_limit_error",
        "model_setup_error",
        "model_structured_output_error",
        "model_timeout_error",
        "model_tool_surface_error",
        "model_transport_error",
    }
)
_PRE_QUERY_FAILURES = frozenset(
    {"database_identity_mismatch", "database_infrastructure_error"}
)


def validate_direct_trace(
    content: bytes, probe: DirectProbeResult, policy: ContentPolicy
) -> None:
    """Validate one complete trace against the captured probe summary."""
    events = _parse_trace(content, policy, probe)
    _reconcile_model_turn_provenance(events, probe, policy)
    _validate_trace_lifecycle(events, probe)
    _reconcile_trace_counts(events, probe)
    _reconcile_trace_tokens(events, probe)
    _reconcile_tool_breakdown(events, probe)
    _validate_terminal_event(events[-1], probe)


def _reconcile_model_turn_provenance(
    events: list[dict[str, Any]],
    probe: DirectProbeResult,
    policy: ContentPolicy,
) -> None:
    try:
        records = tuple(
            DirectModelTurnProvenance.from_dict(record.as_dict())
            for record in probe.model_turn_provenance
            if isinstance(record, DirectModelTurnProvenance)
        )
    except ValueError as error:
        raise ValueError("captured model turn provenance is invalid") from error
    if len(records) != len(probe.model_turn_provenance):
        raise ValueError("captured model turn provenance is invalid")
    model_events = [
        event for event in events if event["event_type"] == "direct_model_turn"
    ]
    if len(model_events) != len(records):
        raise ValueError("trace model turn provenance is incomplete")
    for event, record in zip(model_events, records, strict=True):
        identity = probe.binding.model
        if (
            record.trace_seq != event["seq"]
            or record.provider != probe.provider
            or record.requested_model != probe.model
            or record.model_identity_sha256 != identity.sha256()
            or record.binary_sha256 != identity.executable_sha256
            or record.cli_version != identity.executable_version
            or (
                record.availability == "observed"
                and set(record.realized_models) != {probe.model}
            )
            or event["metadata_sha256"] != record.sha256()
            or policy.sanitize_json(record.as_dict()) != record.as_dict()
        ):
            raise ValueError("trace model turn provenance does not match capture")


def _parse_trace(
    content: bytes, policy: ContentPolicy, probe: DirectProbeResult
) -> list[dict[str, Any]]:
    try:
        values = [json.loads(line) for line in content.splitlines()]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("trace artifact is not valid JSONL") from error
    if not values or any(not isinstance(value, dict) for value in values):
        raise ValueError("trace artifact must contain event objects")
    events = [dict(value) for value in values]
    for seq, event in enumerate(events):
        _validate_trace_event(event, seq, policy, probe)
    return events


def _validate_trace_event(
    event: dict[str, Any],
    seq: int,
    policy: ContentPolicy,
    probe: DirectProbeResult,
) -> None:
    reject_forbidden_keys(event)
    try:
        validate_json_value(event)
    except DirectResultError as error:
        raise ValueError("trace event must contain finite JSON") from error
    if (
        set(event) != TRACE_EVENT_FIELDS
        or event["schema_version"] != TRACE_SCHEMA_VERSION
    ):
        raise ValueError("trace event does not use trace-event-v2")
    if event["seq"] != seq or type(event["seq"]) is not int:
        raise ValueError("trace event sequence is invalid")
    if (event["provider"], event["model"]) != (probe.provider, probe.model):
        raise ValueError("trace model identity does not match captured probe")
    if policy.sanitize_json(event) != event:
        raise ValueError("trace artifact contains sensitive content")
    _validate_trace_scalars(event)
    _validate_trace_capability(event, probe.condition)


def _validate_trace_capability(
    event: Mapping[str, Any], condition: DirectCondition
) -> None:
    event_type = event["event_type"]
    if event_type not in _TRACE_EVENT_TYPES:
        raise ValueError("trace event type is outside the direct harness contract")
    if event["component"] != "direct-sql-harness":
        raise ValueError("trace component is outside the direct harness contract")
    if event["validation_attempt_delta"] != 0:
        raise ValueError("direct trace cannot claim validation attempts")
    tool_name = event["tool_name"]
    tool_delta = event["tool_call_delta"]
    database_delta = event["database_query_delta"]
    if event_type == "direct_tool_dispatch":
        if tool_name not in DIRECT_TOOL_NAMES[condition] or tool_delta != 1:
            raise ValueError("trace tool capability violates the condition contract")
        _validate_tool_dispatch_event(event, database_delta)
        return
    if event_type == "direct_final_sql_execution":
        if tool_name != "execute_sql" or tool_delta != 0:
            raise ValueError("trace final SQL event violates the harness contract")
        _validate_final_sql_event(event, database_delta)
        return
    if tool_name is not None or tool_delta != 0:
        raise ValueError("trace non-tool event contains forged tool telemetry")
    if not _zero_or_unavailable(database_delta):
        raise ValueError("trace non-SQL event contains database-query telemetry")
    _validate_non_sql_event(event)


def _validate_tool_dispatch_event(
    event: Mapping[str, Any], database_delta: Any
) -> None:
    _validate_success_or_error(event, "trace tool event")
    if event["tool_name"] != "execute_sql" and not _zero_or_unavailable(database_delta):
        raise ValueError("trace non-SQL tool contains database-query telemetry")
    if event["tool_name"] == "execute_sql" and event["status"] == "SUCCESS":
        if not _positive_count(database_delta):
            raise ValueError("successful SQL tool event lacks a database query")
    if event["tool_name"] == "execute_sql" and event["status"] == "ERROR":
        _validate_failed_sql_delta(event, database_delta)
    _validate_non_model_usage(event)


def _validate_final_sql_event(event: Mapping[str, Any], database_delta: Any) -> None:
    status, failure = event["status"], event["failure_class"]
    if status == "COMPLETE":
        if failure is not None or not _positive_count(database_delta):
            raise ValueError("completed SQL trace event is inconsistent")
    elif status != "ERROR" or not _failure_text(failure):
        raise ValueError("failed SQL trace event is inconsistent")
    if status == "ERROR":
        _validate_failed_sql_delta(event, database_delta)
    _validate_non_model_usage(event)


def _validate_non_sql_event(event: Mapping[str, Any]) -> None:
    event_type, status, failure = (
        event["event_type"],
        event["status"],
        event["failure_class"],
    )
    if event_type == "direct_model_turn":
        if not (
            (status == "SUCCESS" and failure is None)
            or (status == "ERROR" and failure in _MODEL_FAILURES)
        ):
            raise ValueError("trace model event status is inconsistent")
        _validate_model_usage(event)
        return
    if event_type == "direct_capture_failure":
        if status != "ERROR" or failure not in _CAPTURE_FAILURES:
            raise ValueError("trace capture failure class is invalid")
    elif status != "DENIED" or failure != "agent_refusal":
        raise ValueError("trace terminal event status is inconsistent")
    _validate_non_model_usage(event)


def _validate_success_or_error(event: Mapping[str, Any], description: str) -> None:
    status, failure = event["status"], event["failure_class"]
    if not (
        (status == "SUCCESS" and failure is None)
        or (status == "ERROR" and _failure_text(failure))
    ):
        raise ValueError(f"{description} status is inconsistent")


def _validate_non_model_usage(event: Mapping[str, Any]) -> None:
    if any(
        not _zero_or_unavailable(event[field])
        for field in ("input_tokens", "output_tokens", "retry_delta")
    ):
        raise ValueError("trace non-model event contains model-usage telemetry")


def _validate_model_usage(event: Mapping[str, Any]) -> None:
    input_tokens = event["input_tokens"]
    output_tokens = event["output_tokens"]
    if (input_tokens is None) != (output_tokens is None):
        raise ValueError("trace model token telemetry must be paired")
    for value in (input_tokens, output_tokens, event["retry_delta"]):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("trace model usage telemetry is invalid")


def _zero_or_unavailable(value: Any) -> bool:
    return value is None or (type(value) is int and value == 0)


def _positive_count(value: Any) -> bool:
    return type(value) is int and value > 0


def _failure_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def _validate_failed_sql_delta(event: Mapping[str, Any], value: Any) -> None:
    failure = event["failure_class"]
    if failure == "sql_not_admitted":
        if value != 0:
            raise ValueError("rejected SQL cannot claim a database query")
        return
    if failure in _PRE_QUERY_FAILURES:
        if value is None or (type(value) is int and value >= 0):
            return
    if not _positive_count(value):
        raise ValueError("failed SQL execution lacks a database query")


def _validate_trace_lifecycle(
    events: list[dict[str, Any]], probe: DirectProbeResult
) -> None:
    model_turn_count = sum(
        event["event_type"] == "direct_model_turn" for event in events
    )
    if model_turn_count > probe.maximum_turns:
        raise ValueError("trace exceeds captured maximum_turns")
    expecting_model = True
    for index, event in enumerate(events):
        event_type = event["event_type"]
        if event["failure_class"] == "turn_limit_exhausted":
            if not _is_turn_limit_terminal(event, index, events, probe):
                raise ValueError("trace turn-limit terminal is out of sequence")
            expecting_model = False
            continue
        if expecting_model:
            if event_type != "direct_model_turn":
                raise ValueError("trace lifecycle must begin each turn with the model")
            expecting_model = False
        elif event_type == "direct_model_turn":
            raise ValueError("trace lifecycle is missing a structured model action")
        elif event_type == "direct_tool_dispatch":
            expecting_model = True
        elif index != len(events) - 1:
            raise ValueError("trace lifecycle contains events after a terminal event")
        if event_type == "direct_model_turn" and event["status"] == "ERROR":
            if index != len(events) - 1:
                raise ValueError(
                    "trace lifecycle contains events after a terminal event"
                )
    _validate_outcome_terminal(events[-1], probe)


def _is_turn_limit_terminal(
    event: Mapping[str, Any],
    index: int,
    events: list[dict[str, Any]],
    probe: DirectProbeResult,
) -> bool:
    return (
        index > 0
        and index == len(events) - 1
        and events[index - 1]["event_type"] == "direct_tool_dispatch"
        and event["event_type"] == "direct_capture_failure"
        and event["status"] == "ERROR"
        and event["failure_class"] == "turn_limit_exhausted"
        and probe.generation_outcome == "errored"
        and probe.failure_class == "turn_limit_exhausted"
        and sum(item["event_type"] == "direct_model_turn" for item in events)
        == probe.maximum_turns
    )


def _validate_outcome_terminal(
    terminal: Mapping[str, Any], probe: DirectProbeResult
) -> None:
    expected = {
        "answered": ("direct_final_sql_execution", "COMPLETE"),
        "refused": ("direct_refusal", "DENIED"),
    }
    if probe.generation_outcome in expected:
        event_type, status = expected[probe.generation_outcome]
        if (terminal["event_type"], terminal["status"]) != (event_type, status):
            raise ValueError("trace lifecycle terminal does not match outcome")
        return
    if terminal["status"] != "ERROR" or terminal["event_type"] not in {
        "direct_capture_failure",
        "direct_final_sql_execution",
        "direct_model_turn",
        "direct_tool_dispatch",
    }:
        raise ValueError("trace lifecycle terminal does not match errored outcome")


def _validate_trace_scalars(event: Mapping[str, Any]) -> None:
    for field in ("component", "event_type", "status"):
        if not isinstance(event[field], str) or not event[field]:
            raise ValueError("trace event text fields are invalid")
    for field in ("elapsed_ms", "duration_ms"):
        value = event[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("trace event duration fields are invalid")
    digest = event["metadata_sha256"]
    if digest is not None and (
        not isinstance(digest, str) or _SHA256.fullmatch(digest) is None
    ):
        raise ValueError("trace event metadata digest is invalid")


def _reconcile_trace_counts(
    events: list[dict[str, Any]], probe: DirectProbeResult
) -> None:
    for field, expected in (
        ("tool_call_delta", probe.tool_call_count),
        ("database_query_delta", probe.database_query_count),
        ("validation_attempt_delta", probe.validation_attempt_count),
        ("retry_delta", probe.retry_count),
    ):
        values = [event[field] for event in events]
        if expected is None:
            if any(
                value is not None and (type(value) is not int or value < 0)
                for value in values
            ) or all(value is not None for value in values):
                raise ValueError(
                    "trace telemetry does not preserve partial count observability"
                )
            continue
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("trace telemetry count is invalid")
        if sum(values) != expected:
            raise ValueError("trace telemetry does not match captured totals")


def _reconcile_trace_tokens(
    events: list[dict[str, Any]], probe: DirectProbeResult
) -> None:
    pairs = [(event["input_tokens"], event["output_tokens"]) for event in events]
    if probe.token_usage is None:
        valid = all(
            (first is None and second is None)
            or (
                type(first) is int
                and first >= 0
                and type(second) is int
                and second >= 0
            )
            for first, second in pairs
        )
        if not valid or all(first is not None for first, _ in pairs):
            raise ValueError(
                "trace telemetry does not preserve partial token observability"
            )
        return
    if any(type(value) is not int or value < 0 for pair in pairs for value in pair):
        raise ValueError("trace token telemetry is invalid")
    input_tokens = sum(pair[0] for pair in pairs)
    output_tokens = sum(pair[1] for pair in pairs)
    expected = probe.token_usage
    if expected != {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }:
        raise ValueError("trace telemetry does not match captured token totals")


def _reconcile_tool_breakdown(
    events: list[dict[str, Any]], probe: DirectProbeResult
) -> None:
    observed: Counter[str] = Counter()
    for event in events:
        delta = event["tool_call_delta"]
        if isinstance(delta, int) and delta:
            name = event["tool_name"]
            if not isinstance(name, str) or not name:
                raise ValueError("trace tool call is missing its name")
            observed[name] += delta
    if tuple(sorted(observed.items())) != probe.tool_calls_by_name:
        raise ValueError(
            "trace telemetry tool breakdown does not match captured totals"
        )


def _validate_terminal_event(
    event: Mapping[str, Any], probe: DirectProbeResult
) -> None:
    expected_statuses = {
        "answered": {"COMPLETE"},
        "refused": {"DENIED"},
        "errored": {"ERROR", "FAILED", "CONTRACT_ERROR", "ADAPTER_ERROR"},
    }
    if str(event["status"]).upper() not in expected_statuses[probe.generation_outcome]:
        raise ValueError("trace terminal status does not match attempt outcome")
    expected_failure = (
        None if probe.generation_outcome == "answered" else probe.failure_class
    )
    if event["failure_class"] != expected_failure:
        raise ValueError("trace terminal failure does not match captured probe")

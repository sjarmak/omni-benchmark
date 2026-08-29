"""Validation of per-attempt trace and result artifacts."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .autoresearch_config import (
    AutoresearchConfig,
    AutoresearchError,
    _read_confined_private_bytes,
    _read_confined_private_jsonl,
    _sha256_bytes,
    _unresolved_inside,
)
from .content_policy import ContentPolicy

TRACE_EVENT_FIELDS = {
    "schema_version",
    "seq",
    "timestamp",
    "elapsed_ms",
    "component",
    "event_type",
    "status",
    "duration_ms",
    "provider",
    "model",
    "tool_call_delta",
    "tool_name",
    "input_tokens",
    "output_tokens",
    "database_query_delta",
    "validation_attempt_delta",
    "retry_delta",
    "failure_class",
    "metadata_sha256",
}
TRACE_SCHEMA_VERSION = "trace-event-v2"
TRACE_SUCCESS_TERMINAL_STATES = frozenset({"COMPLETE", "OK", "SUCCEEDED", "SUCCESS"})
TRACE_FAILURE_TERMINAL_STATES = frozenset(
    {
        "ADAPTER_ERROR",
        "CANCELLED",
        "CONTRACT_ERROR",
        "DENIED",
        "ERROR",
        "FAILED",
        "POLL_EXHAUSTED",
    }
)
TRACE_ROOTS = (
    Path("runs"),
    Path("experiments/runs"),
    Path("experiments/autoresearch/raw"),
)
RESULT_ARTIFACT_FIELDS = frozenset({"columns", "rows", "schema_version", "truncated"})
MAX_RESULT_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_RUN_ARTIFACT_BYTES = 256 * 1024 * 1024


def _number(value: Any, name: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        suffix = " or null" if nullable else ""
        raise AutoresearchError(f"{name} must be a non-negative number{suffix}")
    if not math.isfinite(value):
        raise AutoresearchError(f"{name} must be finite")
    return float(value)


def _count(value: Any, name: str, *, nullable: bool = True) -> int | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        suffix = " or null" if nullable else ""
        raise AutoresearchError(f"{name} must be a non-negative integer{suffix}")
    return value


def _validate_observer_retry_telemetry(record: Mapping[str, Any]) -> None:
    fields = {"observer_retry_count", "observer_retry_wait_ms"}
    present = fields & record.keys()
    if present and present != fields:
        raise AutoresearchError("observer retry telemetry must be complete")
    if not present:
        return
    count = _count(
        record["observer_retry_count"], "observer_retry_count", nullable=False
    )
    wait_ms = _number(record["observer_retry_wait_ms"], "observer_retry_wait_ms")
    if (count == 0) != (wait_ms == 0):
        raise AutoresearchError("observer retry telemetry is inconsistent")


def _validate_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise AutoresearchError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AutoresearchError(f"{field} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise AutoresearchError(f"{field} must include a timezone")
    return parsed


def _validate_trace_reference(record: Mapping[str, Any]) -> None:
    captured = record["trace_captured"]
    truncated = record["trace_truncated"]
    if not isinstance(captured, bool) or not isinstance(truncated, bool):
        raise AutoresearchError("trace capture flags must be booleans")
    trace_path = record["trace_path"]
    trace_sha256 = record["trace_sha256"]
    trace_version = record["trace_schema_version"]
    reason = record["trace_degraded_reason"]
    if captured:
        if not isinstance(trace_path, str) or not trace_path:
            raise AutoresearchError("trace_path must be present when trace is captured")
        candidate = Path(trace_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise AutoresearchError("trace_path must be a confined relative path")
        if (
            not isinstance(trace_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", trace_sha256) is None
        ):
            raise AutoresearchError("trace_sha256 must be a SHA-256 hex digest")
        if trace_version != TRACE_SCHEMA_VERSION:
            raise AutoresearchError(
                f"trace_schema_version must be {TRACE_SCHEMA_VERSION}"
            )
        if reason is not None and (not isinstance(reason, str) or not reason):
            raise AutoresearchError("trace_degraded_reason must be a string or null")
        if truncated and reason is None:
            raise AutoresearchError(
                "trace_degraded_reason is required when a trace is truncated"
            )
        if not truncated and reason is not None:
            raise AutoresearchError(
                "complete traces must not declare a trace_degraded_reason"
            )
        return
    if any(value is not None for value in (trace_path, trace_sha256, trace_version)):
        raise AutoresearchError("uncaptured traces cannot have path, hash, or version")
    if not isinstance(reason, str) or not reason:
        raise AutoresearchError(
            "trace_degraded_reason is required when trace capture is unavailable"
        )


def _verify_trace_artifact(
    config: AutoresearchConfig,
    record: Mapping[str, Any],
    content_policy: ContentPolicy,
) -> None:
    if not record["trace_captured"]:
        return
    relative_path = Path(record["trace_path"])
    if not any(relative_path.is_relative_to(root) for root in TRACE_ROOTS):
        raise AutoresearchError("trace_path must use an ignored raw-run root")
    trace_path = _unresolved_inside(config.workspace, relative_path, "trace artifact")
    events, sha256 = _read_confined_private_jsonl(
        config.workspace,
        trace_path,
        "trace artifact",
        maximum_bytes=MAX_RUN_ARTIFACT_BYTES,
    )
    if sha256 != record["trace_sha256"]:
        raise AutoresearchError("trace artifact does not match trace_sha256")
    for expected_seq, event in enumerate(events):
        if set(event) != TRACE_EVENT_FIELDS:
            raise AutoresearchError("trace event has an invalid schema")
        if event["schema_version"] != record["trace_schema_version"]:
            raise AutoresearchError("trace event schema version does not match attempt")
        if type(event["seq"]) is not int or event["seq"] != expected_seq:
            raise AutoresearchError(
                "trace event sequence must be contiguous and ordered"
            )
        _validate_timestamp(event["timestamp"], "trace event timestamp")
        for field in ("component", "event_type", "status"):
            value = event[field]
            if not isinstance(value, str) or not value:
                raise AutoresearchError(
                    f"trace event {field} must be a non-empty string"
                )
            if not content_policy.diagnostic_is_safe(value):
                raise AutoresearchError("trace event contains sensitive content")
        _number(event["elapsed_ms"], "trace event elapsed_ms")
        _number(event["duration_ms"], "trace event duration_ms", nullable=True)
        for field in ("input_tokens", "output_tokens"):
            _count(event[field], f"trace event {field}")
        for field in (
            "database_query_delta",
            "tool_call_delta",
            "validation_attempt_delta",
            "retry_delta",
        ):
            _count(event[field], f"trace event {field}")
        for field in ("provider", "model", "tool_name", "failure_class"):
            value = event[field]
            if value is not None and (not isinstance(value, str) or not value):
                raise AutoresearchError(
                    f"trace event {field} must be a non-empty string or null"
                )
            if value is not None and not content_policy.identifier_is_safe(value):
                raise AutoresearchError("trace event contains sensitive content")
        metadata_hash = event["metadata_sha256"]
        if metadata_hash is not None and (
            not isinstance(metadata_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", metadata_hash) is None
        ):
            raise AutoresearchError(
                "trace event metadata_sha256 must be a SHA-256 digest or null"
            )
    if not record["trace_truncated"]:
        _reconcile_trace_totals(record, events)


def _reconcile_trace_totals(
    record: Mapping[str, Any], events: list[dict[str, Any]]
) -> None:
    usage = record["token_usage"]
    if usage is None:
        if any(
            event["input_tokens"] is not None or event["output_tokens"] is not None
            for event in events
        ):
            raise AutoresearchError(
                "complete trace token totals must remain unavailable when the envelope is unavailable"
            )
    else:
        if any(
            event["input_tokens"] is None or event["output_tokens"] is None
            for event in events
        ):
            raise AutoresearchError(
                "complete trace token totals cannot reconcile unavailable events"
            )
        input_tokens = sum(event["input_tokens"] for event in events)
        output_tokens = sum(event["output_tokens"] for event in events)
        if (
            input_tokens != usage["input_tokens"]
            or output_tokens != usage["output_tokens"]
        ):
            raise AutoresearchError("complete trace token totals do not match envelope")
    for envelope_field, event_field in (
        ("tool_call_count", "tool_call_delta"),
        ("database_query_count", "database_query_delta"),
        ("retry_count", "retry_delta"),
        ("validation_attempt_count", "validation_attempt_delta"),
    ):
        envelope_value = record[envelope_field]
        if envelope_value is None:
            if any(event[event_field] is not None for event in events):
                raise AutoresearchError(
                    f"complete trace {event_field} must remain unavailable when the envelope is unavailable"
                )
            continue
        if any(event[event_field] is None for event in events):
            raise AutoresearchError(
                f"complete trace {event_field} cannot reconcile unavailable events"
            )
        if sum(event[event_field] for event in events) != envelope_value:
            raise AutoresearchError(
                f"complete trace {event_field} total does not match envelope"
            )
    final_event = events[-1] if events else None
    final_failure_class = None if final_event is None else final_event["failure_class"]
    final_status = "" if final_event is None else final_event["status"].upper()
    if (
        final_status in TRACE_SUCCESS_TERMINAL_STATES
        and final_failure_class is not None
    ) or (
        final_status in TRACE_FAILURE_TERMINAL_STATES and final_failure_class is None
    ):
        raise AutoresearchError(
            "complete trace terminal status and failure_class are inconsistent"
        )
    trace_terminal_failure = (
        final_status in TRACE_FAILURE_TERMINAL_STATES or final_failure_class is not None
    )
    envelope_terminal_failure = record["generation_outcome"] in {
        "refused",
        "errored",
    }
    if trace_terminal_failure != envelope_terminal_failure:
        raise AutoresearchError(
            "complete trace terminal failure state does not match generation outcome"
        )
    if (
        trace_terminal_failure
        and final_failure_class != record["terminal_failure_class"]
    ):
        raise AutoresearchError(
            "complete trace failure_class must match terminal_failure_class"
        )


def _resolve_raw_run_path(
    config: AutoresearchConfig, path: Path, description: str
) -> Path:
    unresolved = _unresolved_inside(config.workspace, path, description)
    relative = unresolved.relative_to(config.workspace)
    if not any(relative.is_relative_to(root) for root in TRACE_ROOTS):
        raise AutoresearchError(f"{description} must use an ignored raw-run root")
    return unresolved


def _validate_safe_record_content(
    record: Mapping[str, Any], content_policy: ContentPolicy
) -> None:
    if content_policy.sanitize_json(dict(record)) != dict(record):
        raise AutoresearchError("run artifact contains sensitive content")
    diagnostic_fields = (
        "actual_result_status",
        "compiler_failure_class",
        "compiler_status",
        "execution_failure_class",
        "execution_status",
        "failure_category",
        "harness_failure",
        "terminal_failure_class",
        "trace_degraded_reason",
        "query_unavailable_reason",
        "validation_failure_class",
        "validation_status",
    )
    if any(
        isinstance(record.get(field), str)
        and not content_policy.diagnostic_is_safe(record[field])
        for field in diagnostic_fields
    ):
        raise AutoresearchError("run artifact contains sensitive content")
    identifier_values = [
        value
        for field in (
            "semantic_objects",
            "public_hkb_nodes",
            "semantic_objects_available",
            "semantic_objects_retrieved",
        )
        for value in (record.get(field) or [])
    ]
    identifier_values.extend(
        value for value in record["model"].values() if value is not None
    )
    if any(not content_policy.identifier_is_safe(value) for value in identifier_values):
        raise AutoresearchError("run artifact contains sensitive content")


def _validate_string_array(record: Mapping[str, Any], field: str) -> None:
    value = record.get(field)
    if value is not None and (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise AutoresearchError(f"{field} must be an array of non-empty strings")


def _validate_diagnostic_trace(record: Mapping[str, Any]) -> None:
    result_hash = record.get("actual_result_hash")
    if result_hash is not None and (
        not isinstance(result_hash, str)
        or re.fullmatch(r"[0-9a-f]{64}", result_hash) is None
    ):
        raise AutoresearchError("actual_result_hash must be a SHA-256 hex digest")
    status = record.get("actual_result_status")
    if status is not None and (not isinstance(status, str) or not status):
        raise AutoresearchError("actual_result_status must be a non-empty string")
    question = record.get("question")
    if question is not None and (not isinstance(question, str) or not question):
        raise AutoresearchError("question must be a non-empty string")
    for field in (
        "public_hkb_nodes",
        "semantic_objects_available",
        "semantic_objects_retrieved",
        "prior_experiment_ids",
        "prior_experiments",
    ):
        _validate_string_array(record, field)
    for field in (
        "compiler_status",
        "compiler_failure_class",
        "validation_status",
        "validation_failure_class",
        "execution_status",
        "execution_failure_class",
    ):
        value = record.get(field)
        if value is not None and (not isinstance(value, str) or not value):
            raise AutoresearchError(f"{field} must be a non-empty string or null")


def _has_opaque_result_binding(record: Mapping[str, Any]) -> bool:
    reason = record.get("query_unavailable_reason")
    return (
        isinstance(reason, str)
        and bool(reason)
        and record.get("actual_result_hash") is not None
        and isinstance(record.get("result_artifact_path"), str)
        and type(record.get("result_artifact_schema_version")) is int
        and record["result_artifact_schema_version"] == 1
        and record.get("result_artifact_sha256") is not None
    )


def _verify_result_artifact(
    config: AutoresearchConfig,
    record: Mapping[str, Any],
    content_policy: ContentPolicy,
) -> None:
    fields = (
        "result_artifact_path",
        "result_artifact_schema_version",
        "result_artifact_sha256",
    )
    values = [record.get(field) for field in fields]
    if all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise AutoresearchError("result artifact binding must be complete")
    path_value = record["result_artifact_path"]
    if not isinstance(path_value, str) or not path_value:
        raise AutoresearchError("result artifact path must be a non-empty string")
    relative_path = Path(path_value)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise AutoresearchError("result artifact path must be confined and relative")
    if not any(relative_path.is_relative_to(root) for root in TRACE_ROOTS):
        raise AutoresearchError("result artifact must use an ignored raw-run root")
    digest = record["result_artifact_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise AutoresearchError("result artifact SHA-256 is invalid")
    if (
        type(record["result_artifact_schema_version"]) is not int
        or record["result_artifact_schema_version"] != 1
    ):
        raise AutoresearchError("result artifact schema version is unsupported")
    result_path = _unresolved_inside(config.workspace, relative_path, "result artifact")
    content = _read_confined_private_bytes(
        config.workspace,
        result_path,
        "result artifact",
        maximum_bytes=MAX_RESULT_ARTIFACT_BYTES,
    )
    if _sha256_bytes(content) != digest:
        raise AutoresearchError("result artifact does not match its SHA-256")
    if record.get("actual_result_hash") != digest:
        raise AutoresearchError("actual result hash must bind the result artifact")
    try:
        result = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AutoresearchError("result artifact must be valid JSON") from error
    _validate_result_value(result, content_policy, config.forbidden_fields)


def _validate_result_value(
    value: Any,
    content_policy: ContentPolicy,
    forbidden_fields: frozenset[str],
) -> None:
    if not isinstance(value, dict) or set(value) != RESULT_ARTIFACT_FIELDS:
        raise AutoresearchError("result artifact has an invalid schema")
    columns = value["columns"]
    rows = value["rows"]
    if not isinstance(columns, list) or any(
        not isinstance(column, str) or not column for column in columns
    ):
        raise AutoresearchError("result artifact columns are invalid")
    if any(column in forbidden_fields for column in columns):
        raise AutoresearchError("result artifact contains a forbidden column")
    if any(content_policy.field_name_is_sensitive(column) for column in columns):
        raise AutoresearchError("result artifact contains a sensitive column")
    if not isinstance(rows, list) or any(
        not isinstance(row, list) or len(row) != len(columns) for row in rows
    ):
        raise AutoresearchError("result artifact rows do not match its columns")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or not isinstance(value["truncated"], bool)
    ):
        raise AutoresearchError("result artifact metadata is invalid")
    if content_policy.sanitize_json(value) != value:
        raise AutoresearchError("result artifact contains sensitive content")

"""Write immutable C1-C3 generation artifacts and provenance manifests."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from .autoresearch_artifacts import TRACE_EVENT_FIELDS, TRACE_SCHEMA_VERSION
from .autoresearch_config import _canonical_bytes
from .content_policy import ContentPolicy
from .direct_sql_capture import DirectCondition, DirectProbeResult, _TOOL_NAMES
from .direct_sql_result import DirectResultError, validate_json_value
from .omni_result_adapter import reject_forbidden_keys
from .run_manifest import RunManifest
from .sql_admission import query_sql_is_admissible

_RESULT_FIELDS = frozenset({"columns", "rows", "schema_version", "truncated"})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
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


@dataclass(frozen=True)
class DirectAttemptArtifacts:
    """Hash-bound artifacts emitted by one direct-SQL invocation."""

    generation: StoredArtifact
    run_manifest: StoredArtifact


@dataclass(frozen=True)
class DirectAttemptSpec:
    """Immutable run identity and provenance for one C1-C3 attempt."""

    condition: DirectCondition
    scope: str
    instance_id: str
    question: str
    run_id: str
    repetition: int
    controllable_seed: int | None
    provider: str
    model: str
    model_version: str | None
    git_commit: str
    harness_config_sha256: str
    prompt_sha256: str
    instructions_sha256: str
    semantic_model_ref: str
    semantic_model_sha256: str | None
    model_config_id: str
    budget_id: str
    software_versions: Mapping[str, str]
    cli_versions: Mapping[str, str]


def write_direct_attempt(
    *,
    workspace: Path,
    store: ArtifactStore,
    spec: DirectAttemptSpec,
    probe: DirectProbeResult,
) -> DirectAttemptArtifacts:
    """Write generation.jsonl, then bind it with the exact run manifest."""
    _validate_root_binding(workspace, store, probe)
    _validate_probe_binding(spec, probe)
    policy = ContentPolicy.from_environment(os.environ)
    _validate_generated_sql(probe, policy)
    _validate_trace_artifact(workspace, probe, policy)
    _validate_result_artifact(workspace, probe, policy)
    _validate_receipt(workspace, store, spec, probe, policy)
    record = _attempt_record(workspace, spec, probe)
    reject_forbidden_keys(record)
    if policy.sanitize_json(record) != record:
        raise ValueError("attempt record contains sensitive content")
    try:
        validate_json_value(record)
    except DirectResultError as error:
        raise ValueError("attempt record must contain finite JSON") from error
    _validate_attempt_measurements(probe)
    prospective_digest = hashlib.sha256(_canonical_bytes(record)).hexdigest()
    manifest = _run_manifest(spec, probe, prospective_digest)
    generation = store.write_jsonl(Path("generation.jsonl"), [record])
    run_manifest = store.write_json(Path("run.json"), manifest.as_dict())
    return DirectAttemptArtifacts(generation=generation, run_manifest=run_manifest)


def _validate_probe_binding(spec: DirectAttemptSpec, probe: DirectProbeResult) -> None:
    if spec.condition != probe.condition:
        raise ValueError("attempt condition does not match captured probe")
    expected_attempt = (
        f"{spec.run_id}:{spec.instance_id}:{spec.condition}:{spec.repetition}"
    )
    if probe.attempt_id != expected_attempt:
        raise ValueError("attempt identity does not match captured probe")
    if type(probe.maximum_turns) is not int or probe.maximum_turns < 1:
        raise ValueError("captured maximum_turns is invalid")
    if (spec.provider, spec.model) != (probe.provider, probe.model):
        raise ValueError("attempt model identity does not match captured probe")
    question_sha256 = hashlib.sha256(spec.question.encode("utf-8")).hexdigest()
    if probe.question_sha256 != question_sha256:
        raise ValueError("attempt question does not match captured probe")
    if probe.generation_outcome not in {"answered", "refused", "errored"}:
        raise ValueError("attempt has an invalid generation outcome")
    answered = probe.generation_outcome == "answered"
    if answered and (probe.generated_sql is None or probe.result_artifact is None):
        raise ValueError("answered attempts require SQL and a typed result artifact")
    if not answered and probe.result_artifact is not None:
        raise ValueError("failed attempts cannot bind a result artifact")
    if answered != (probe.failure_class is None):
        raise ValueError("attempt outcome and terminal failure class are inconsistent")
    _validate_semantic_provenance(probe)
    _validate_sources(probe)


def _validate_root_binding(
    workspace: Path, store: ArtifactStore, probe: DirectProbeResult
) -> None:
    try:
        store.require_workspace(workspace)
        store.relative_path(probe.receipt)
        store.relative_path(probe.trace)
        if probe.result_artifact is not None:
            store.relative_path(probe.result_artifact)
    except ArtifactStoreError as error:
        raise ValueError(
            "attempt artifacts do not share the destination root"
        ) from error


def _validate_receipt(
    workspace: Path,
    store: ArtifactStore,
    spec: DirectAttemptSpec,
    probe: DirectProbeResult,
    policy: ContentPolicy,
) -> None:
    if store.root_relative_path(probe.receipt) != Path("capture.receipt.json"):
        raise ValueError("capture receipt path is invalid")
    content = _read_stored_artifact(workspace, probe.receipt, "capture receipt")
    try:
        actual = json.loads(content)
        validate_json_value(actual)
    except (UnicodeError, json.JSONDecodeError, DirectResultError) as error:
        raise ValueError("capture receipt is not strict JSON") from error
    result = probe.result_artifact
    expected = {
        "artifact_root_identity": store.root_identity,
        "attempt_id": f"{spec.run_id}:{spec.instance_id}:{spec.condition}:{spec.repetition}",
        "condition": probe.condition,
        "generated_sql_sha256": hashlib.sha256(probe.generated_sql.encode()).hexdigest()
        if probe.generated_sql is not None
        else None,
        "maximum_turns": probe.maximum_turns,
        "model": probe.model,
        "provider": probe.provider,
        "question_sha256": probe.question_sha256,
        "result_path": store.relative_path(result).as_posix() if result else None,
        "result_sha256": result.sha256 if result else None,
        "schema_version": 1,
        "trace_path": store.relative_path(probe.trace).as_posix(),
        "trace_sha256": probe.trace.sha256,
    }
    if actual != expected or policy.sanitize_json(actual) != actual:
        raise ValueError("capture receipt does not match the exact attempt artifacts")


def _validate_generated_sql(probe: DirectProbeResult, policy: ContentPolicy) -> None:
    sql = probe.generated_sql
    if sql is not None and (
        not policy.query_is_safe(sql) or not query_sql_is_admissible(sql)
    ):
        raise ValueError("captured SQL does not pass publisher SQL admission")


def _validate_semantic_provenance(probe: DirectProbeResult) -> None:
    values = probe.semantic_objects
    if tuple(sorted(set(values))) != values or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise ValueError("captured semantic object provenance is invalid")
    if probe.condition != "C3" and values:
        raise ValueError(f"{probe.condition} cannot publish semantic objects")
    tools = dict(probe.tool_calls_by_name)
    if values and tools.get("search_semantic_model", 0) < 1:
        raise ValueError("semantic objects lack semantic-model tool provenance")


def _validate_sources(probe: DirectProbeResult) -> None:
    for source, value, field in (
        (probe.token_source, probe.token_usage, "token"),
        (probe.cost_source, probe.cost_usd, "cost"),
    ):
        if source not in {"provider_reported", "derived", "unavailable"}:
            raise ValueError(f"attempt {field} source is invalid")
        if (value is None) != (source == "unavailable"):
            raise ValueError(f"attempt {field} source and value disagree")


def _validate_attempt_measurements(probe: DirectProbeResult) -> None:
    values = (
        (probe.latency_ms,)
        if probe.cost_usd is None
        else (
            probe.latency_ms,
            probe.cost_usd,
        )
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        raise ValueError("attempt latency and available cost must be non-negative")


def _validate_trace_artifact(
    workspace: Path, probe: DirectProbeResult, policy: ContentPolicy
) -> None:
    content = _read_stored_artifact(workspace, probe.trace, "trace")
    events = _parse_trace(content, policy, probe)
    _validate_trace_lifecycle(events, probe)
    _reconcile_trace_counts(events, probe)
    _reconcile_trace_tokens(events, probe)
    _reconcile_tool_breakdown(events, probe)
    _validate_terminal_event(events[-1], probe)


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
        if tool_name not in _TOOL_NAMES[condition] or tool_delta != 1:
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
            or (status == "ERROR" and failure == "model_transport_error")
        ):
            raise ValueError("trace model event status is inconsistent")
        if status == "ERROR":
            _validate_non_model_usage(event)
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
    if failure == "database_infrastructure_error":
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
        else:
            if index != len(events) - 1:
                raise ValueError(
                    "trace lifecycle contains events after a terminal event"
                )
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
            if any(value is not None for value in values):
                raise ValueError("trace telemetry does not preserve unavailable counts")
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
        if any(first is not None or second is not None for first, second in pairs):
            raise ValueError("trace telemetry does not preserve unavailable tokens")
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


def _validate_result_artifact(
    workspace: Path, probe: DirectProbeResult, policy: ContentPolicy
) -> None:
    if probe.result_artifact is None:
        return
    content = _read_stored_artifact(workspace, probe.result_artifact, "result artifact")
    try:
        value = json.loads(content)
        validate_json_value(value)
    except (UnicodeError, json.JSONDecodeError, DirectResultError) as error:
        raise ValueError("result artifact is not valid JSON") from error
    reject_forbidden_keys(value)
    if policy.sanitize_json(value) != value:
        raise ValueError("result artifact contains sensitive content")
    _validate_typed_result(value, policy)


def _validate_typed_result(value: Any, policy: ContentPolicy) -> None:
    if not isinstance(value, dict) or set(value) != _RESULT_FIELDS:
        raise ValueError("result artifact does not use the exact typed schema")
    columns, rows = value["columns"], value["rows"]
    if not isinstance(columns, list) or any(
        not isinstance(column, str) or not column for column in columns
    ):
        raise ValueError("result artifact columns are invalid")
    if len(set(columns)) != len(columns):
        raise ValueError("result artifact columns must be unique")
    for column in columns:
        reject_forbidden_keys({column: None})
    if any(policy.field_name_is_sensitive(column) for column in columns):
        raise ValueError("result artifact columns contain sensitive names")
    if not isinstance(rows, list) or any(
        not isinstance(row, list) or len(row) != len(columns) for row in rows
    ):
        raise ValueError("result artifact rows do not match columns")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("result artifact metadata is invalid")
    if value["truncated"] is not False:
        raise ValueError("result artifact metadata is invalid")


def _read_stored_artifact(
    workspace: Path, artifact: StoredArtifact, description: str
) -> bytes:
    path = artifact.path
    try:
        resolved_workspace = workspace.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_workspace)
        metadata = path.lstat()
        content = path.read_bytes()
    except (OSError, ValueError) as error:
        raise ValueError(f"{description} is outside the private workspace") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise ValueError(f"{description} is not a private regular file")
    digest = hashlib.sha256(content).hexdigest()
    if (
        not content
        or len(content) > _MAX_ARTIFACT_BYTES
        or len(content) != artifact.size_bytes
        or digest != artifact.sha256
    ):
        raise ValueError(f"{description} metadata does not match stored bytes")
    return content


def _attempt_record(
    workspace: Path, spec: DirectAttemptSpec, probe: DirectProbeResult
) -> dict[str, object]:
    record = {
        **_identity_fields(spec, probe),
        **_telemetry_fields(spec, probe),
        **_trace_fields(workspace, probe),
    }
    if probe.generated_sql is not None:
        record |= {
            "generated_query": None,
            "generated_sql": probe.generated_sql,
            "query_unavailable_reason": None,
        }
    if probe.result_artifact is not None:
        record |= _result_fields(workspace, probe.result_artifact)
    return record


def _identity_fields(
    spec: DirectAttemptSpec, probe: DirectProbeResult
) -> dict[str, object]:
    failure = probe.failure_class
    return {
        "attempt_id": (
            f"{spec.run_id}:{spec.instance_id}:{spec.condition}:{spec.repetition}"
        ),
        "condition": spec.condition,
        "failure_origin": None if failure is None else "evaluated_system",
        "finished_at": probe.finished_at,
        "generation_outcome": probe.generation_outcome,
        "harness_failure": failure,
        "instance_id": spec.instance_id,
        "latency_ms": probe.latency_ms,
        "model": {
            "name": spec.model,
            "provider": spec.provider,
            "version": spec.model_version,
        },
        "partition": spec.scope,
        "question": spec.question,
        "repetition": spec.repetition,
        "run_id": spec.run_id,
        "semantic_objects": list(probe.semantic_objects),
        "started_at": probe.started_at,
        "terminal_failure_class": failure,
    }


def _telemetry_fields(
    spec: DirectAttemptSpec, probe: DirectProbeResult
) -> dict[str, object]:
    unavailable = [] if probe.retry_count is not None else ["retry_count"]
    if probe.database_query_count is None:
        unavailable.append("database_query_count")
    if spec.model_version is None:
        unavailable.append("model_version")
    return {
        "cost_source": probe.cost_source,
        "cost_usd": probe.cost_usd,
        "database_query_count": probe.database_query_count,
        "retry_count": probe.retry_count,
        "telemetry_unavailable": sorted(unavailable),
        "token_source": probe.token_source,
        "token_usage": probe.token_usage,
        "tool_call_count": probe.tool_call_count,
        "tool_calls_by_name": [
            {"count": count, "name": name} for name, count in probe.tool_calls_by_name
        ],
        "validation_attempt_count": probe.validation_attempt_count,
    }


def _trace_fields(workspace: Path, probe: DirectProbeResult) -> dict[str, object]:
    return {
        "trace_captured": True,
        "trace_degraded_reason": None,
        "trace_path": probe.trace.path.relative_to(workspace).as_posix(),
        "trace_schema_version": "trace-event-v2",
        "trace_sha256": probe.trace.sha256,
        "trace_truncated": False,
    }


def _result_fields(workspace: Path, result: StoredArtifact) -> dict[str, object]:
    return {
        "actual_result_hash": result.sha256,
        "actual_result_status": "complete",
        "execution_status": "complete",
        "result_artifact_path": result.path.relative_to(workspace).as_posix(),
        "result_artifact_schema_version": 1,
        "result_artifact_sha256": result.sha256,
    }


def _run_manifest(
    spec: DirectAttemptSpec, probe: DirectProbeResult, generation_sha256: str
) -> RunManifest:
    return RunManifest.from_dict(
        {
            "budget_id": spec.budget_id,
            "cli_versions": dict(spec.cli_versions),
            "condition": spec.condition,
            "controllable_seed": spec.controllable_seed,
            "finished_at": probe.finished_at,
            "generation_sha256": generation_sha256,
            "git_commit": spec.git_commit,
            "harness_config_sha256": spec.harness_config_sha256,
            "instructions_sha256": spec.instructions_sha256,
            "model": spec.model,
            "model_config_id": spec.model_config_id,
            "prompt_sha256": spec.prompt_sha256,
            "provider": spec.provider,
            "repetition": spec.repetition,
            "schema_version": 2,
            "scope": spec.scope,
            "semantic_model_ref": spec.semantic_model_ref,
            "semantic_model_sha256": spec.semantic_model_sha256,
            "software_versions": dict(spec.software_versions),
            "started_at": probe.started_at,
        }
    )

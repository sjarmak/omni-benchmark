"""Strict wire contract shared by the restricted Claude transport."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .direct_capture_contract import (
    DirectModelFailure,
    DirectModelFailureCategory,
    DirectModelTurn,
    DirectModelUsage,
)
from .direct_runtime_binding import DirectBudgetIdentity, DirectModelIdentity
from .omni_result_adapter import reject_forbidden_keys

ClaudeFailureCategory = DirectModelFailureCategory
REFUSAL_REASONS = ("cannot_answer_safely", "insufficient_information")
_TERMINAL_USAGE_FIELDS = frozenset(
    {
        "cacheCreationInputTokens",
        "cacheReadInputTokens",
        "canonicalModel",
        "contextWindow",
        "costUSD",
        "inputTokens",
        "maxOutputTokens",
        "outputTokens",
        "provider",
        "webSearchRequests",
    }
)
_RETRY_FIELDS = frozenset(
    {
        "attempt",
        "error",
        "error_status",
        "max_retries",
        "retry_delay_ms",
        "session_id",
        "subtype",
        "type",
        "uuid",
    }
)
_RETRY_ERRORS = frozenset(
    {
        "account_on_hold",
        "authentication_failed",
        "billing_error",
        "invalid_request",
        "max_output_tokens",
        "model_not_found",
        "oauth_org_not_allowed",
        "overloaded",
        "rate_limit",
        "server_error",
        "unknown",
    }
)


class ClaudeDirectTransportError(DirectModelFailure):
    """A classified provider/setup failure with any observable partial usage."""


@dataclass(frozen=True)
class ClaudeUsage(DirectModelUsage):
    """Input includes fresh, cache-read, and cache-creation input tokens."""

    input_tokens: int
    output_tokens: int
    message_count: int
    models: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaudeTerminalTelemetry:
    """Validated cumulative terminal telemetry from one pinned CLI result."""

    cost_usd: float
    models: tuple[str, ...]
    usage: ClaudeUsage
    web_search_requests: int


@dataclass(frozen=True)
class ClaudeProcessResult:
    """Literal process boundary result; no provider semantics are inferred here."""

    duration_seconds: float
    returncode: int
    stderr: str
    stdout: str


@dataclass(frozen=True)
class ClaudeTurnProvenance:
    """Provider evidence bound to one immutable turn result."""

    binary_path: str
    binary_sha256: str
    cli_version: str
    cost_source: str
    duration_seconds: float
    model_identity: DirectModelIdentity
    partial_usage: ClaudeUsage
    provider: str
    realized_models: tuple[str, ...]
    request_sha256: str
    requested_model: str
    result_subtype: str
    session_id: str
    stream_sha256: str
    token_source: str


@dataclass(frozen=True)
class ClaudeDirectModelTurn(DirectModelTurn):
    """Direct harness turn with provider provenance retained for audit."""

    provenance: ClaudeTurnProvenance | None = None


@dataclass(frozen=True)
class ClaudeDirectConfig:
    """All pre-run resources required by one stateless Claude invocation."""

    budget_id: str
    claude_config_dir: Path
    effort: str
    maximum_cost_usd: float
    maximum_turns: int
    model: str
    runtime_home: Path
    temp_directory: Path
    timeout_seconds: float
    working_directory: Path


def direct_model_identity(
    *,
    provider: str,
    model: str,
    adapter: str,
    adapter_version: str,
    executable_sha256: str,
    executable_version: str,
    system_prompt: str,
    transport_config: Mapping[str, Any],
) -> DirectModelIdentity:
    """Derive the exact immutable identity for a restricted Claude transport."""
    try:
        value = {
            "adapter": adapter,
            "adapter_version": adapter_version,
            "executable_sha256": executable_sha256,
            "executable_version": executable_version,
            "model": model,
            "provider": provider,
            "system_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
            "transport_config_sha256": hashlib.sha256(
                strict_json(transport_config, "transport config").encode()
            ).hexdigest(),
        }
        return DirectModelIdentity.from_dict(value, environment={})
    except Exception:
        raise ClaudeDirectTransportError(
            "model_identity", "Claude model identity is invalid"
        ) from None


def direct_budget_identity(
    *,
    budget_id: str,
    maximum_turns: int,
    per_turn_timeout_seconds: float,
    per_turn_max_cost_usd: float,
) -> DirectBudgetIdentity:
    """Derive the exact immutable budget contract for the capture harness."""
    try:
        return DirectBudgetIdentity.from_dict(
            {
                "budget_id": budget_id,
                "maximum_turns": maximum_turns,
                "per_turn_max_cost_usd": per_turn_max_cost_usd,
                "per_turn_timeout_seconds": per_turn_timeout_seconds,
            },
            environment={},
        )
    except Exception:
        raise ClaudeDirectTransportError(
            "setup", "Claude budget identity is invalid"
        ) from None


def terminal_telemetry(
    result: Mapping[str, Any], model: str, *, required: bool
) -> ClaudeTerminalTelemetry | None:
    model_usage = result.get("modelUsage")
    total_cost_value = result.get("total_cost_usd")
    if model_usage is None and total_cost_value is None and not required:
        return None
    if model_usage == {} and not required:
        return _empty_terminal_telemetry(total_cost_value)
    observed_model, usage = _terminal_model_usage(model_usage)
    _validate_terminal_identity(observed_model, usage)
    parsed_usage, web_search_requests, cost = _parse_terminal_usage(
        observed_model, usage
    )
    total_cost = _nonnegative_finite(total_cost_value, "total cost")
    if not math.isclose(total_cost, cost, rel_tol=1e-9, abs_tol=1e-12):
        raise ClaudeDirectTransportError(
            "protocol", "terminal cost does not reconcile with model telemetry"
        )
    return ClaudeTerminalTelemetry(
        cost_usd=total_cost,
        models=(observed_model,),
        usage=parsed_usage,
        web_search_requests=web_search_requests,
    )


def _empty_terminal_telemetry(total_cost_value: object) -> ClaudeTerminalTelemetry:
    total_cost = _nonnegative_finite(total_cost_value, "total cost")
    if total_cost != 0:
        raise ClaudeDirectTransportError(
            "protocol", "empty terminal model telemetry has nonzero cost"
        )
    return ClaudeTerminalTelemetry(
        cost_usd=0.0,
        models=(),
        usage=ClaudeUsage(input_tokens=0, output_tokens=0, message_count=0),
        web_search_requests=0,
    )


def _terminal_model_usage(
    model_usage: object,
) -> tuple[str, Mapping[str, Any]]:
    if not isinstance(model_usage, Mapping) or len(model_usage) != 1:
        raise ClaudeDirectTransportError(
            "protocol", "terminal model telemetry is missing"
        )
    observed_model = next(iter(model_usage))
    if not isinstance(observed_model, str) or not observed_model:
        raise ClaudeDirectTransportError(
            "protocol", "terminal model identity is invalid"
        )
    usage = model_usage[observed_model]
    if not isinstance(usage, Mapping):
        raise ClaudeDirectTransportError("protocol", "terminal telemetry is malformed")
    return observed_model, usage


def _validate_terminal_identity(observed_model: str, usage: Mapping[str, Any]) -> None:
    if not _TERMINAL_USAGE_FIELDS.issubset(usage):
        raise ClaudeDirectTransportError("protocol", "terminal telemetry is incomplete")
    if usage["canonicalModel"] != observed_model or usage["provider"] != "firstParty":
        raise ClaudeDirectTransportError(
            "model_identity", "terminal model/provider identity is inconsistent"
        )
    _positive_int(usage["contextWindow"], "terminal context window")
    _positive_int(usage["maxOutputTokens"], "terminal output limit")
    if "costBasis" in usage and usage["costBasis"] not in {
        "list",
        "managed",
        "unknown",
    }:
        raise ClaudeDirectTransportError("protocol", "terminal cost basis is invalid")


def _parse_terminal_usage(
    observed_model: str, usage: Mapping[str, Any]
) -> tuple[ClaudeUsage, int, float]:
    web_search_requests = _nonnegative_int(
        usage["webSearchRequests"], "terminal web search telemetry"
    )
    fresh = _nonnegative_int(usage["inputTokens"], "terminal telemetry")
    cache_read = _nonnegative_int(usage["cacheReadInputTokens"], "terminal telemetry")
    cache_create = _nonnegative_int(
        usage["cacheCreationInputTokens"], "terminal telemetry"
    )
    output = _nonnegative_int(usage["outputTokens"], "terminal telemetry")
    cost = _nonnegative_finite(usage["costUSD"], "terminal telemetry cost")
    return (
        ClaudeUsage(
            input_tokens=fresh + cache_read + cache_create,
            output_tokens=output,
            message_count=1,
            models=(observed_model,),
        ),
        web_search_requests,
        cost,
    )


def partial_usage_from_events(events: Sequence[Mapping[str, Any]]) -> ClaudeUsage:
    messages: dict[tuple[str, str | None, str], tuple[int, int, int, int, str]] = {}
    for event in events:
        parsed = _partial_usage_message(event)
        if parsed is None:
            continue
        key, value = parsed
        if key in messages and messages[key] != value:
            raise ClaudeDirectTransportError(
                "protocol", "Claude stream contains conflicting duplicate messages"
            )
        messages[key] = value
    return ClaudeUsage(
        input_tokens=sum(
            fresh + read + create for fresh, read, create, _, _ in messages.values()
        ),
        output_tokens=sum(output for _, _, _, output, _ in messages.values()),
        message_count=len(messages),
        models=tuple(sorted({model for *_, model in messages.values()})),
    )


def _partial_usage_message(
    event: Mapping[str, Any],
) -> tuple[tuple[str, str | None, str], tuple[int, int, int, int, str]] | None:
    if event.get("type") != "assistant":
        return None
    message = event.get("message")
    if not isinstance(message, Mapping) or not isinstance(
        message.get("usage"), Mapping
    ):
        return None
    identity = (
        event.get("session_id"),
        event.get("parent_tool_use_id"),
        message.get("id"),
    )
    model = message.get("model")
    session, parent, message_id = identity
    if (
        not isinstance(session, str)
        or not session
        or (parent is not None and not isinstance(parent, str))
        or not isinstance(message_id, str)
        or not message_id
        or not isinstance(model, str)
        or not model
    ):
        raise ClaudeDirectTransportError(
            "protocol", "usage-bearing assistant event lacks provider identity"
        )
    usage = message["usage"]
    value = (
        _nonnegative_int(usage.get("input_tokens"), "partial telemetry"),
        _nonnegative_int(usage.get("cache_read_input_tokens"), "partial telemetry"),
        _nonnegative_int(usage.get("cache_creation_input_tokens"), "partial telemetry"),
        _nonnegative_int(usage.get("output_tokens"), "partial telemetry"),
        model,
    )
    return (session, parent, message_id), value


def retry_count_from_events(events: Sequence[Mapping[str, Any]]) -> int:
    retries: dict[tuple[str, str], tuple[Any, ...]] = {}
    for event in events:
        if event.get("type") != "system" or event.get("subtype") != "api_retry":
            continue
        key, value = _retry_record(event)
        if key in retries and retries[key] != value:
            raise ClaudeDirectTransportError(
                "protocol", "Claude stream contains conflicting duplicate retry events"
            )
        retries[key] = value
    return len(retries)


def _retry_record(event: Mapping[str, Any]) -> tuple[tuple[str, str], tuple[Any, ...]]:
    if not _RETRY_FIELDS.issubset(event):
        raise ClaudeDirectTransportError(
            "protocol", "api retry telemetry is incomplete"
        )
    session = event["session_id"]
    retry_uuid = event["uuid"]
    if (
        not isinstance(session, str)
        or not session
        or not isinstance(retry_uuid, str)
        or not retry_uuid
    ):
        raise ClaudeDirectTransportError("protocol", "api retry identity is invalid")
    attempt = _positive_int(event["attempt"], "api retry attempt")
    maximum = _positive_int(event["max_retries"], "api retry maximum")
    delay = _nonnegative_int(event["retry_delay_ms"], "api retry delay")
    status = event["error_status"]
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ClaudeDirectTransportError("protocol", "api retry status is invalid")
    error = event["error"]
    if error not in _RETRY_ERRORS or attempt > maximum:
        raise ClaudeDirectTransportError("protocol", "api retry telemetry is invalid")
    return (session, retry_uuid), (attempt, maximum, delay, status, error)


def best_effort_telemetry(raw: str) -> tuple[ClaudeUsage | None, int | None]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            events.append(value)
    try:
        partial = partial_usage_from_events(events) if events else None
    except ClaudeDirectTransportError:
        partial = None
    try:
        retries = retry_count_from_events(events) if events else 0
    except ClaudeDirectTransportError:
        retries = None
    return partial, retries


def validate_process_result(process: Any) -> None:
    """Validate the literal process-runner boundary before parsing its stream."""
    if not isinstance(process, ClaudeProcessResult):
        raise ClaudeDirectTransportError(
            "infrastructure", "Claude runner returned the wrong result type"
        )
    if (
        isinstance(process.returncode, bool)
        or not isinstance(process.returncode, int)
        or not isinstance(process.stdout, str)
        or not isinstance(process.stderr, str)
        or isinstance(process.duration_seconds, bool)
        or not isinstance(process.duration_seconds, (int, float))
        or not math.isfinite(process.duration_seconds)
        or process.duration_seconds < 0
    ):
        raise ClaudeDirectTransportError(
            "infrastructure", "Claude runner result is malformed"
        )


def parse_events(raw: str) -> tuple[dict[str, Any], ...]:
    """Parse a complete strict-JSON Claude stream or fail closed."""
    if not raw.strip():
        raise ClaudeDirectTransportError("protocol", "Claude stream is empty")
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            event = None
        if event is None:
            raise ClaudeDirectTransportError(
                "protocol", "Claude stream contains malformed JSON"
            )
        if not isinstance(event, dict):
            raise ClaudeDirectTransportError(
                "protocol", "Claude stream event must be an object"
            )
        events.append(event)
    if not events:
        raise ClaudeDirectTransportError("protocol", "Claude stream is empty")
    return tuple(events)


def try_parse_events(raw: str) -> tuple[dict[str, Any], ...] | None:
    """Return a complete event stream, or ``None`` for literal failure parsing."""
    try:
        return parse_events(raw)
    except ClaudeDirectTransportError:
        return None


def object_events(raw: str) -> tuple[dict[str, Any], ...]:
    """Retain valid object events from a failed process for terminal telemetry."""
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(event, dict):
            events.append(event)
    return tuple(events)


def one_event(
    events: Sequence[Mapping[str, Any]],
    event_type: str,
    *,
    subtype: str | None = None,
) -> Mapping[str, Any]:
    """Select exactly one event by type and optional subtype."""
    matches = [
        event
        for event in events
        if event.get("type") == event_type
        and (subtype is None or event.get("subtype") == subtype)
    ]
    if len(matches) != 1:
        raise ClaudeDirectTransportError(
            "protocol", f"Claude stream requires exactly one {event_type} event"
        )
    return matches[0]


def validate_session(
    events: Sequence[Mapping[str, Any]],
    init: Mapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    """Require one non-empty session identity throughout the stream."""
    session = init.get("session_id")
    if not isinstance(session, str) or not session:
        raise ClaudeDirectTransportError(
            "protocol", "Claude session identity is missing"
        )
    observed = {
        event["session_id"]
        for event in events
        if isinstance(event.get("session_id"), str) and event.get("session_id")
    }
    if observed != {session} or result.get("session_id") != session:
        raise ClaudeDirectTransportError(
            "protocol", "Claude stream contains inconsistent session identity"
        )


def validate_surface(init: Mapping[str, Any]) -> None:
    """Reject any provider-exposed ambient tool or MCP surface."""
    if init.get("tools") != [] or init.get("mcp_servers") != []:
        raise ClaudeDirectTransportError(
            "tool_surface", "Claude init exposed an ambient tool surface"
        )


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ClaudeDirectTransportError(
            "protocol", f"{label} must contain non-negative integer telemetry"
        )
    return value


def _positive_int(value: Any, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise ClaudeDirectTransportError("protocol", f"{label} must be positive")
    return result


def _nonnegative_finite(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ClaudeDirectTransportError("protocol", f"{label} is not finite")
    number = float(value)
    if number < 0:
        raise ClaudeDirectTransportError("protocol", f"{label} must be non-negative")
    return number


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def normalize_tool_specs(
    tool_specs: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for tool in tool_specs:
        if not isinstance(tool, Mapping) or set(tool) != {
            "description",
            "input_schema",
            "name",
        }:
            raise ClaudeDirectTransportError("protocol", "tool spec is not exact")
        name = tool["name"]
        description = tool["description"]
        schema = tool["input_schema"]
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(description, str)
            or not description
        ):
            raise ClaudeDirectTransportError(
                "protocol", "tool spec identity is invalid"
            )
        names.add(name)
        normalized.append(
            {
                "description": description,
                "input_schema": _normalize_input_schema(schema),
                "name": name,
            }
        )
    if not normalized:
        raise ClaudeDirectTransportError("protocol", "at least one tool is required")
    strict_json(normalized, "tool specs")
    return tuple(normalized)


def _normalize_input_schema(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "additionalProperties",
        "properties",
        "required",
        "type",
    }:
        raise ClaudeDirectTransportError("protocol", "tool input schema is not exact")
    properties = value["properties"]
    required = value["required"]
    if (
        value["type"] != "object"
        or value["additionalProperties"] is not False
        or not isinstance(properties, Mapping)
        or not isinstance(required, list)
        or set(required) != set(properties)
        or len(required) != len(properties)
    ):
        raise ClaudeDirectTransportError("protocol", "tool input schema is invalid")
    for name, schema in properties.items():
        if (
            not isinstance(name, str)
            or not isinstance(schema, Mapping)
            or dict(schema) != {"type": "string"}
        ):
            raise ClaudeDirectTransportError(
                "protocol", "tool arguments must be required strings"
            )
    return {
        "additionalProperties": False,
        "properties": {name: {"type": "string"} for name in properties},
        "required": list(required),
        "type": "object",
    }


def strict_json(value: Any, label: str) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        encoded = None
    if encoded is None:
        raise ClaudeDirectTransportError(
            "protocol", f"{label} must use finite strict JSON"
        )
    return encoded


def action_schema(tool_specs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tool_variants = [
        {
            "additionalProperties": False,
            "properties": {
                "arguments": dict(tool["input_schema"]),
                "name": {"const": tool["name"]},
                "type": {"const": "tool"},
            },
            "required": ["type", "name", "arguments"],
            "type": "object",
        }
        for tool in tool_specs
    ]
    answer = {
        "additionalProperties": False,
        "properties": {
            "sql": {"minLength": 1, "type": "string"},
            "type": {"const": "answer"},
        },
        "required": ["type", "sql"],
        "type": "object",
    }
    refusal = {
        "additionalProperties": False,
        "properties": {
            "reason": {"enum": list(REFUSAL_REASONS)},
            "type": {"const": "refuse"},
        },
        "required": ["type", "reason"],
        "type": "object",
    }
    return {
        "additionalProperties": False,
        "oneOf": [*tool_variants, answer, refusal],
        "properties": {
            "arguments": {"type": "object"},
            "name": {"type": "string"},
            "reason": {"type": "string"},
            "sql": {"type": "string"},
            "type": {"type": "string"},
        },
        "type": "object",
    }


def validate_action(action: Any, tool_specs: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(action, Mapping):
        raise ClaudeDirectTransportError("protocol", "structured action is missing")
    try:
        reject_forbidden_keys(action)
        strict_json(action, "structured action")
    except ClaudeDirectTransportError:
        raise
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise ClaudeDirectTransportError(
            "protocol", "structured action contains forbidden fields"
        )
    action_type = action.get("type")
    if action_type == "answer":
        valid = (
            set(action) == {"sql", "type"}
            and isinstance(action.get("sql"), str)
            and bool(action["sql"].strip())
        )
    elif action_type == "refuse":
        valid = (
            set(action) == {"reason", "type"}
            and action.get("reason") in REFUSAL_REASONS
        )
    elif action_type == "tool":
        valid = _valid_tool_action(action, tool_specs)
    else:
        valid = False
    if not valid:
        raise ClaudeDirectTransportError(
            "protocol", "structured action does not match the offered contract"
        )


def _valid_tool_action(
    action: Mapping[str, Any], tool_specs: Sequence[Mapping[str, Any]]
) -> bool:
    if set(action) != {"arguments", "name", "type"}:
        return False
    name = action.get("name")
    arguments = action.get("arguments")
    matching = [tool for tool in tool_specs if tool["name"] == name]
    if len(matching) != 1 or not isinstance(arguments, Mapping):
        return False
    expected = matching[0]["input_schema"]["required"]
    return set(arguments) == set(expected) and all(
        isinstance(arguments[key], str) and bool(arguments[key].strip())
        for key in expected
    )

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .claude_direct_contract import (
    ClaudeDirectConfig,
    ClaudeDirectModelTurn,
    ClaudeProcessResult,
    ClaudeTerminalTelemetry,
    ClaudeDirectTransportError,
    ClaudeFailureCategory,
    ClaudeTurnProvenance,
    ClaudeUsage,
    action_schema,
    best_effort_telemetry,
    direct_budget_identity,
    direct_model_identity,
    normalize_tool_specs,
    object_events,
    one_event,
    parse_events,
    partial_usage_from_events,
    retry_count_from_events,
    strict_json,
    terminal_telemetry,
    try_parse_events,
    validate_action,
    validate_process_result,
    validate_session,
    validate_surface,
)
from .claude_resource_identity import (
    ClaudeResourceIdentity,
    ClaudeResourceIdentityError,
    PinnedClaudeResources,
    current_claude_resource_identity,
    pin_claude_resources,
    validate_private_directory,
)
from .claude_process_runtime import (
    ClaudeProcessRunner,
    claude_environment,
    proc_fd_path,
    run_claude_process,
)
from .direct_runtime_binding import DirectBudgetIdentity, DirectModelIdentity
from .omni_result_adapter import reject_forbidden_keys

PINNED_CLAUDE_BINARY = Path("/home/ds/.local/share/claude/versions/2.1.250")
PINNED_CLAUDE_BINARY_SHA256 = (
    "2be252a00ac56e704d7fbf7e5e9ef1243584093334a861945238a0c27e84bdac"
)
PINNED_CLAUDE_VERSION = "2.1.250"
PROVIDER_ID = "anthropic_claude_code_oauth"
ADAPTER_ID = "claude-code-restricted-mcp"
ADAPTER_VERSION = "1.0.0"

_EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})
_AUTH_PATTERN = re.compile(
    r"(?i)(authentication\s+(?:failed|error)|invalid\s+(?:auth|oauth)|"
    r"oauth\s+token\s+(?:expired|invalid)|api\s*key\s+(?:invalid|missing)|"
    r"unauthorized|(?:http\s+|status\s*=?\s*)(?:401|403)\b)"
)
_RATE_LIMIT_PATTERN = re.compile(r"(?i)(?:http\s+|status\s*=?\s*)429\b")
_QUOTA_PATTERN = re.compile(
    r"(?i)(monthly\s+usage\s+limit|rate\s+limit\s+(?:exceeded|reached)|"
    r"quota\s+(?:exceeded|exhausted)|usage\s+limit\s+reached|"
    r"hit\s+your\s+session\s+limit)"
)
_SYSTEM_PROMPT = """You are a direct analytical SQL agent in a controlled evaluation.
Return exactly one JSON action matching the supplied schema. The harness owns every
tool: request a listed tool action when information or execution is needed. Do not
claim access to files, shell, networks, credentials, hidden annotations, or tools that
are not listed. Return an answer action only for Query-only analytical SQL. Refuse when
the available public information is insufficient to answer safely."""
_TRANSPORT_POLICY = {
    "disable_slash_commands": True,
    "include_partial_messages": True,
    "mcp_servers": {},
    "no_chrome": True,
    "no_session_persistence": True,
    "output_format": "stream-json",
    "permission_mode": "dontAsk",
    "restricted": True,
    "safe_mode": True,
    "setting_sources": [],
    "strict_mcp_config": True,
    "tools": [],
}


@dataclass(frozen=True)
class _ProcessEvidence:
    result: Mapping[str, Any]
    partial: ClaudeUsage
    retry_count: int
    terminal: ClaudeTerminalTelemetry | None


class ClaudeDirectTransport:
    """Use Claude Code only as a structured model transport, never as an agent shell."""

    def __init__(
        self,
        config: ClaudeDirectConfig,
        *,
        runner: ClaudeProcessRunner | None = None,
    ) -> None:
        self._config = _validate_config(config)
        self._runner = run_claude_process if runner is None else runner
        self._resource_identity = _resource_identity(self._config)
        self._model_identity = _derive_model_identity(
            self._config, PINNED_CLAUDE_BINARY_SHA256
        )
        self._budget_identity = direct_budget_identity(
            budget_id=self._config.budget_id,
            maximum_turns=self._config.maximum_turns,
            per_turn_max_cost_usd=float(self._config.maximum_cost_usd),
            per_turn_timeout_seconds=float(self._config.timeout_seconds),
        )

    @property
    def runtime_identity(self) -> DirectModelIdentity:
        """Return the exact model, executable, prompt, and transport identity."""
        return self._model_identity

    @property
    def budget_identity(self) -> DirectBudgetIdentity:
        """Return the exact pre-run turn, timeout, and cost ceilings."""
        return self._budget_identity

    @property
    def execution_authority(self) -> str:
        """Fingerprint all mutable state capable of changing an invocation."""
        return _execution_authority(
            self._config,
            self._runner,
            _resource_identity(self._config),
        )

    def next_turn(
        self,
        messages: tuple[Mapping[str, Any], ...],
        tool_specs: tuple[Mapping[str, Any], ...],
    ) -> ClaudeDirectModelTurn:
        resources = _pin_resources(self._config)
        failure: ClaudeDirectTransportError | None = None
        outcome: (
            tuple[ClaudeProcessResult, str, tuple[Mapping[str, Any], ...]] | None
        ) = None
        try:
            outcome = _invoke_pinned_turn(self, resources, messages, tool_specs)
        except ClaudeDirectTransportError as error:
            failure = error
        finally:
            failure = _close_resources(resources, failure)
        if failure is not None:
            raise failure from None
        if outcome is None:
            raise ClaudeDirectTransportError(
                "infrastructure", "Claude invocation produced no outcome"
            )
        process, request, normalized_tools = outcome
        return _parse_process_result(
            process=process,
            config=self._config,
            request=request,
            tool_specs=normalized_tools,
            binary_sha256=resources.binary_sha256,
            model_identity=self._model_identity,
        )


def _invoke_pinned_turn(
    transport: ClaudeDirectTransport,
    resources: PinnedClaudeResources,
    messages: tuple[Mapping[str, Any], ...],
    tool_specs: tuple[Mapping[str, Any], ...],
) -> tuple[ClaudeProcessResult, str, tuple[Mapping[str, Any], ...]]:
    if not resources.source_matches(transport._resource_identity):
        raise ClaudeDirectTransportError(
            "setup", "Claude execution resources changed before invocation"
        )
    _reconcile_model_identity(
        transport._model_identity, transport._config, resources.binary_sha256
    )
    normalized_tools = normalize_tool_specs(tool_specs)
    request = _request_json(messages, normalized_tools)
    command = _command(
        transport._config, action_schema(normalized_tools), resources.binary_fd
    )
    process = _invoke_with_resource_reconciliation(
        transport._runner, transport._config, resources, command, request
    )
    return process, request, normalized_tools


def _invoke_with_resource_reconciliation(
    runner: ClaudeProcessRunner,
    config: ClaudeDirectConfig,
    resources: PinnedClaudeResources,
    command: tuple[str, ...],
    request: str,
) -> ClaudeProcessResult:
    failure: ClaudeDirectTransportError | None = None
    process: ClaudeProcessResult | None = None
    try:
        process = _invoke_runner(runner, config, resources, command, request)
    except ClaudeDirectTransportError as error:
        failure = error
    try:
        resources.verify_unchanged()
    except ClaudeResourceIdentityError as error:
        if failure is None and process is not None:
            partial, retries = best_effort_telemetry(process.stdout)
            failure = ClaudeDirectTransportError(
                "infrastructure",
                "Claude process completed before resource reconciliation",
                partial_usage=partial,
                retry_count=retries,
            )
        resource_error = ClaudeDirectTransportError("setup", str(error))
        failure = _resource_failure(resource_error, failure)
    if failure is not None:
        raise failure from None
    if process is None:
        raise ClaudeDirectTransportError(
            "infrastructure", "Claude process runner returned no result"
        )
    return process


def _resource_failure(
    resource_error: ClaudeDirectTransportError,
    prior: ClaudeDirectTransportError | None,
) -> ClaudeDirectTransportError:
    return ClaudeDirectTransportError(
        "setup",
        str(resource_error),
        partial_usage=None if prior is None else prior.partial_usage,
        retry_count=None if prior is None else prior.retry_count,
        terminal_cost_usd=None if prior is None else prior.terminal_cost_usd,
        terminal_usage=None if prior is None else prior.terminal_usage,
    )


def _close_resources(
    resources: PinnedClaudeResources,
    prior: ClaudeDirectTransportError | None,
) -> ClaudeDirectTransportError | None:
    try:
        resources.close()
    except ClaudeResourceIdentityError:
        cleanup = ClaudeDirectTransportError(
            "setup", "Claude execution snapshot cleanup failed"
        )
        return _resource_failure(cleanup, prior)
    return prior


def _invoke_runner(
    runner: ClaudeProcessRunner,
    config: ClaudeDirectConfig,
    resources: PinnedClaudeResources,
    command: tuple[str, ...],
    request: str,
) -> ClaudeProcessResult:
    try:
        process = runner(
            command,
            stdin=request,
            cwd=Path(proc_fd_path(resources.work_fd)),
            env=claude_environment(resources),
            pass_fds=resources.pass_fds,
            timeout_seconds=config.timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        partial, retries = best_effort_telemetry(_as_text(error.output))
        failure = ClaudeDirectTransportError(
            "timeout",
            "Claude transport exceeded its fixed timeout",
            partial_usage=partial,
            retry_count=retries,
        )
    except Exception:
        failure = ClaudeDirectTransportError(
            "infrastructure", "Claude process runner failed"
        )
    else:
        failure = None
    if failure is not None:
        raise failure
    if process is None:
        raise ClaudeDirectTransportError(
            "infrastructure", "Claude process runner returned no result"
        )
    return process


def _validate_config(config: ClaudeDirectConfig) -> ClaudeDirectConfig:
    if type(config) is not ClaudeDirectConfig:
        raise ClaudeDirectTransportError("setup", "Claude config has the wrong type")
    if not _exact_model(config.model):
        raise ClaudeDirectTransportError(
            "setup", "model must be a full pinned Claude model identifier"
        )
    if config.effort not in _EFFORT_LEVELS:
        raise ClaudeDirectTransportError("setup", "effort level is invalid")
    _positive_finite(config.timeout_seconds, "timeout")
    _positive_finite(config.maximum_cost_usd, "maximum cost")
    if not isinstance(config.budget_id, str) or not config.budget_id:
        raise ClaudeDirectTransportError("setup", "budget ID is invalid")
    if type(config.maximum_turns) is not int or config.maximum_turns <= 0:
        raise ClaudeDirectTransportError("setup", "maximum turns is invalid")
    for path, label in (
        (config.claude_config_dir, "Claude config directory"),
        (config.runtime_home, "runtime home"),
        (config.temp_directory, "temporary directory"),
        (config.working_directory, "working directory"),
    ):
        if not isinstance(path, Path):
            raise ClaudeDirectTransportError("setup", f"{label} must be a Path")
        try:
            validate_private_directory(path, label)
        except ClaudeResourceIdentityError as error:
            raise ClaudeDirectTransportError("setup", str(error)) from None
    return config


def _derive_model_identity(
    config: ClaudeDirectConfig, executable_sha256: str
) -> DirectModelIdentity:
    transport_config = {
        "effort": config.effort,
        "maximum_cost_usd": float(config.maximum_cost_usd),
        "policy": _TRANSPORT_POLICY,
    }
    return direct_model_identity(
        provider=PROVIDER_ID,
        model=config.model,
        adapter=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        executable_sha256=executable_sha256,
        executable_version=PINNED_CLAUDE_VERSION,
        system_prompt=_SYSTEM_PROMPT,
        transport_config=transport_config,
    )


def _execution_authority(
    config: ClaudeDirectConfig,
    runner: ClaudeProcessRunner,
    resource_identity: ClaudeResourceIdentity,
) -> str:
    payload = {
        "budget_id": config.budget_id,
        "claude_config_dir": str(config.claude_config_dir),
        "effort": config.effort,
        "maximum_cost_usd": config.maximum_cost_usd,
        "maximum_turns": config.maximum_turns,
        "model": config.model,
        "runner": _callable_identity(runner),
        "resource_identity_sha256": resource_identity.sha256(),
        "runtime_home": str(config.runtime_home),
        "temp_directory": str(config.temp_directory),
        "timeout_seconds": config.timeout_seconds,
        "working_directory": str(config.working_directory),
    }
    return hashlib.sha256(
        strict_json(payload, "execution authority").encode()
    ).hexdigest()


def _callable_identity(value: object) -> str:
    function = getattr(value, "__func__", value)
    owner = getattr(value, "__self__", None)
    return f"{id(owner)}:{id(function)}"


def _reconcile_model_identity(
    expected: DirectModelIdentity,
    config: ClaudeDirectConfig,
    executable_sha256: str,
) -> None:
    if type(expected) is not DirectModelIdentity or expected != _derive_model_identity(
        config, executable_sha256
    ):
        raise ClaudeDirectTransportError(
            "model_identity", "Claude model identity changed before invocation"
        )


def _exact_model(model: Any) -> bool:
    return (
        isinstance(model, str)
        and model.startswith("claude-")
        and bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]*", model))
        and any(character.isdigit() for character in model)
    )


def _positive_finite(value: Any, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ClaudeDirectTransportError(
            "setup", f"{label} must be a positive finite number"
        )


def _pin_resources(config: ClaudeDirectConfig) -> PinnedClaudeResources:
    try:
        return pin_claude_resources(
            binary_path=PINNED_CLAUDE_BINARY,
            expected_binary_sha256=PINNED_CLAUDE_BINARY_SHA256,
            config_directory=config.claude_config_dir,
            runtime_home=config.runtime_home,
            temp_directory=config.temp_directory,
            working_directory=config.working_directory,
        )
    except ClaudeResourceIdentityError as error:
        failure_message = str(error)
    raise ClaudeDirectTransportError("setup", failure_message)


def _resource_identity(config: ClaudeDirectConfig) -> ClaudeResourceIdentity:
    try:
        return current_claude_resource_identity(
            config_directory=config.claude_config_dir,
            runtime_home=config.runtime_home,
            temp_directory=config.temp_directory,
            working_directory=config.working_directory,
        )
    except ClaudeResourceIdentityError as error:
        failure_message = str(error)
    raise ClaudeDirectTransportError("setup", failure_message)


def _request_json(
    messages: Sequence[Mapping[str, Any]], tool_specs: Sequence[Mapping[str, Any]]
) -> str:
    if not messages or any(not isinstance(message, Mapping) for message in messages):
        raise ClaudeDirectTransportError("protocol", "messages must be non-empty")
    payload = {
        "messages": [dict(message) for message in messages],
        "tool_specs": tool_specs,
    }
    try:
        reject_forbidden_keys(payload)
    except Exception:
        invalid = True
    else:
        invalid = False
    if invalid:
        raise ClaudeDirectTransportError(
            "protocol", "messages contain forbidden hidden fields"
        )
    return strict_json(payload, "request")


def _command(
    config: ClaudeDirectConfig, schema: Mapping[str, Any], binary_fd: int
) -> tuple[str, ...]:
    return (
        proc_fd_path(binary_fd),
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--json-schema",
        strict_json(schema, "action schema"),
        "--system-prompt",
        _SYSTEM_PROMPT,
        "--model",
        config.model,
        "--effort",
        config.effort,
        "--max-budget-usd",
        f"{config.maximum_cost_usd:g}",
        "--permission-mode",
        "dontAsk",
        "--restricted",
        "--safe-mode",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--no-chrome",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
        "--tools",
        "",
    )


def _parse_process_result(
    *,
    process: ClaudeProcessResult,
    config: ClaudeDirectConfig,
    request: str,
    tool_specs: Sequence[Mapping[str, Any]],
    binary_sha256: str,
    model_identity: DirectModelIdentity,
) -> ClaudeDirectModelTurn:
    validate_process_result(process)
    events = _events_from_process(process)
    evidence = _result_evidence(events, config)
    realized_models = _validate_result_context(
        events, evidence, config, binary_sha256, model_identity
    )
    action = _validated_action(evidence, config, process.returncode, tool_specs)
    return _model_turn(
        action=action,
        process=process,
        config=config,
        request=request,
        evidence=evidence,
        binary_sha256=binary_sha256,
        model_identity=model_identity,
        realized_models=realized_models,
    )


def _events_from_process(
    process: ClaudeProcessResult,
) -> tuple[dict[str, Any], ...]:
    events = try_parse_events(process.stdout)
    if events is None and process.returncode != 0:
        events = object_events(process.stdout)
    terminal_count = (
        0 if events is None else sum(event.get("type") == "result" for event in events)
    )
    if events is None or (process.returncode != 0 and terminal_count == 0):
        if process.returncode == 0:
            return parse_events(process.stdout)  # pragma: no cover - always raises
        category = _classify_literal_failure(process.stdout, process.stderr)
        partial, retries = best_effort_telemetry(process.stdout)
        raise ClaudeDirectTransportError(
            category,
            f"Claude process exited with status {process.returncode}",
            partial_usage=partial,
            retry_count=retries,
        )
    return events


def _capture_protocol_failure(
    operation: Callable[[], Any], default: Any
) -> tuple[Any, ClaudeDirectTransportError | None]:
    try:
        return operation(), None
    except ClaudeDirectTransportError as error:
        return default, error


def _result_evidence(
    events: Sequence[Mapping[str, Any]], config: ClaudeDirectConfig
) -> _ProcessEvidence:
    result, result_failure = _capture_protocol_failure(
        lambda: one_event(events, "result"), {}
    )
    partial, partial_failure = _capture_protocol_failure(
        lambda: partial_usage_from_events(events), None
    )
    retry_count, retry_failure = _capture_protocol_failure(
        lambda: retry_count_from_events(events), None
    )
    successful = result.get("is_error") is False and result.get("subtype") == "success"
    if result_failure is None:
        terminal, terminal_failure = _capture_protocol_failure(
            lambda: terminal_telemetry(result, config.model, required=successful), None
        )
        if terminal is not None and terminal.web_search_requests > 0:
            terminal_failure = ClaudeDirectTransportError(
                "tool_surface", "Claude used an unavailable web search surface"
            )
    else:
        terminal, terminal_failure = None, None
    for failure in (result_failure, partial_failure, terminal_failure, retry_failure):
        if failure is not None:
            raise _preserve_telemetry(failure, partial, retry_count, terminal)
    assert partial is not None and retry_count is not None
    return _ProcessEvidence(result, partial, retry_count, terminal)


def _validate_result_context(
    events: Sequence[Mapping[str, Any]],
    evidence: _ProcessEvidence,
    config: ClaudeDirectConfig,
    binary_sha256: str,
    model_identity: DirectModelIdentity,
) -> tuple[str, ...]:
    try:
        init = one_event(events, "system", subtype="init")
        validate_session(events, init, evidence.result)
        validate_surface(init)
        realized_models = _realized_models(
            init, evidence.terminal, evidence.partial, config.model
        )
        _reconcile_model_identity(model_identity, config, binary_sha256)
    except ClaudeDirectTransportError as error:
        raise _preserve_telemetry(
            error, evidence.partial, evidence.retry_count, evidence.terminal
        ) from None
    return realized_models


def _validated_action(
    evidence: _ProcessEvidence,
    config: ClaudeDirectConfig,
    returncode: int,
    tool_specs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    category = _provider_failure_category(evidence.result, returncode)
    if category is not None:
        raise ClaudeDirectTransportError(
            category,
            _failure_message(category),
            partial_usage=evidence.partial,
            retry_count=evidence.retry_count,
            terminal_cost_usd=(
                None if evidence.terminal is None else evidence.terminal.cost_usd
            ),
            terminal_usage=(
                None if evidence.terminal is None else evidence.terminal.usage
            ),
        )
    terminal = evidence.terminal
    if terminal is None:
        raise ClaudeDirectTransportError("protocol", "terminal telemetry is missing")
    if terminal.cost_usd > config.maximum_cost_usd:
        raise _preserve_telemetry(
            ClaudeDirectTransportError("protocol", "terminal cost exceeded fixed cap"),
            evidence.partial,
            evidence.retry_count,
            terminal,
        )
    action = evidence.result.get("structured_output")
    try:
        validate_action(action, tool_specs)
    except ClaudeDirectTransportError as error:
        raise _preserve_telemetry(
            error, evidence.partial, evidence.retry_count, terminal
        ) from None
    return dict(action)


def _model_turn(
    *,
    action: dict[str, Any],
    process: ClaudeProcessResult,
    config: ClaudeDirectConfig,
    request: str,
    evidence: _ProcessEvidence,
    binary_sha256: str,
    model_identity: DirectModelIdentity,
    realized_models: tuple[str, ...],
) -> ClaudeDirectModelTurn:
    terminal = evidence.terminal
    if terminal is None:  # already rejected by _validated_action
        raise ClaudeDirectTransportError("protocol", "terminal telemetry is missing")
    stream_sha256 = hashlib.sha256(process.stdout.encode()).hexdigest()
    provenance = ClaudeTurnProvenance(
        binary_path=str(PINNED_CLAUDE_BINARY),
        binary_sha256=binary_sha256,
        cli_version=PINNED_CLAUDE_VERSION,
        cost_source="claude_result_total_cost_usd",
        duration_seconds=process.duration_seconds,
        model_identity=model_identity,
        partial_usage=evidence.partial,
        provider=PROVIDER_ID,
        realized_models=realized_models,
        request_sha256=hashlib.sha256(request.encode()).hexdigest(),
        requested_model=config.model,
        result_subtype=evidence.result["subtype"],
        session_id=evidence.result["session_id"],
        stream_sha256=stream_sha256,
        token_source="claude_result_model_usage",
    )
    return ClaudeDirectModelTurn(
        action=action,
        model_identity=model_identity,
        cost_usd=terminal.cost_usd,
        input_tokens=terminal.usage.input_tokens,
        output_tokens=terminal.usage.output_tokens,
        provenance=provenance,
        retry_count=evidence.retry_count,
    )


def _provider_failure_category(
    result: Mapping[str, Any], returncode: int
) -> ClaudeFailureCategory | None:
    subtype = result.get("subtype")
    status = result.get("api_error_status")
    if status in {401, 403}:
        return "auth"
    if status == 429:
        return "rate_limit"
    if subtype == "error_max_budget_usd":
        return "budget"
    if subtype == "error_max_structured_output_retries":
        return "structured_output"
    if result.get("is_error") is False and subtype == "success" and returncode == 0:
        return None
    return "infrastructure"


def _failure_message(category: ClaudeFailureCategory) -> str:
    return {
        "auth": "Claude provider rejected OAuth",
        "budget": "Claude process exhausted its fixed budget",
        "rate_limit": "Claude provider returned rate limit status 429",
        "structured_output": "Claude exhausted structured-output retries",
    }.get(category, "Claude provider returned a terminal error")


def _preserve_telemetry(
    error: ClaudeDirectTransportError,
    partial: ClaudeUsage | None,
    retry_count: int | None,
    terminal: ClaudeTerminalTelemetry | None,
) -> ClaudeDirectTransportError:
    return ClaudeDirectTransportError(
        error.category,
        str(error),
        partial_usage=partial,
        retry_count=retry_count,
        terminal_cost_usd=None if terminal is None else terminal.cost_usd,
        terminal_usage=None if terminal is None else terminal.usage,
    )


def _realized_models(
    init: Mapping[str, Any],
    terminal: ClaudeTerminalTelemetry | None,
    partial: ClaudeUsage,
    expected: str,
) -> tuple[str, ...]:
    models = () if terminal is None else terminal.models
    if init.get("model") != expected or (models and models != (expected,)):
        raise ClaudeDirectTransportError(
            "model_identity", "realized Claude model does not match the pinned model"
        )
    if partial.models and partial.models != (expected,):
        raise ClaudeDirectTransportError(
            "model_identity", "partial Claude model does not match the pinned model"
        )
    return models or (expected,)


def _classify_literal_failure(stdout: str, stderr: str) -> ClaudeFailureCategory:
    literal = "\n".join((*_literal_lines(stdout), stderr))
    if _AUTH_PATTERN.search(literal):
        return "auth"
    if _RATE_LIMIT_PATTERN.search(literal):
        return "rate_limit"
    if _QUOTA_PATTERN.search(literal):
        return "quota"
    return "infrastructure"


def _literal_lines(raw: str) -> tuple[str, ...]:
    literal: list[str] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            literal.append(line)
            continue
        if not isinstance(value, dict):
            literal.append(line)
    return tuple(literal)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _as_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""

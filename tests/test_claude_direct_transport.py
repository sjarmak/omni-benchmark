from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.claude_direct_transport import (
    PINNED_CLAUDE_BINARY,
    PINNED_CLAUDE_BINARY_SHA256,
    ClaudeDirectConfig,
    ClaudeDirectTransport,
    ClaudeDirectTransportError,
    ClaudeProcessResult,
)
from omni_benchmark.direct_capture_contract import DirectModelFailure


MODEL = "claude-sonnet-4-6"


def _tool_specs() -> tuple[dict[str, Any], ...]:
    return (
        {
            "description": "Inspect schema.",
            "input_schema": {
                "additionalProperties": False,
                "properties": {},
                "required": [],
                "type": "object",
            },
            "name": "inspect_schema",
        },
        {
            "description": "Run query-only SQL.",
            "input_schema": {
                "additionalProperties": False,
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
                "type": "object",
            },
            "name": "execute_sql",
        },
    )


def _messages() -> tuple[dict[str, Any], ...]:
    return ({"role": "user", "content": "How many sites are there?"},)


def _model_usage(
    model: str = MODEL, cost: float = 0.02, **changes: Any
) -> dict[str, Any]:
    usage = {
        "cacheCreationInputTokens": 1,
        "cacheReadInputTokens": 2,
        "canonicalModel": model,
        "contextWindow": 200_000,
        "costBasis": "managed",
        "costUSD": cost,
        "futureAdditiveField": {"observed": True},
        "inputTokens": 7,
        "maxOutputTokens": 64_000,
        "outputTokens": 5,
        "provider": "firstParty",
        "webSearchRequests": 0,
    }
    return {model: {**usage, **changes}}


def _init_event(model: str = MODEL) -> dict[str, Any]:
    return {
        "mcp_servers": [],
        "model": model,
        "session_id": "session-1",
        "subtype": "init",
        "tools": ["StructuredOutput"],
        "type": "system",
    }


def _assistant_event(
    *,
    session_id: str = "session-1",
    message_id: str = "msg-1",
    parent_tool_use_id: str | None = None,
    input_tokens: int = 7,
    cache_read_input_tokens: int = 2,
    cache_creation_input_tokens: int = 1,
    output_tokens: int = 5,
    model: str = MODEL,
) -> dict[str, Any]:
    return {
        "message": {
            "content": [{"text": "partial", "type": "text"}],
            "id": message_id,
            "model": model,
            "usage": {
                "cache_creation_input_tokens": cache_creation_input_tokens,
                "cache_read_input_tokens": cache_read_input_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        },
        "parent_tool_use_id": parent_tool_use_id,
        "session_id": session_id,
        "type": "assistant",
    }


def _success_stream(
    *,
    action: dict[str, Any] | None = None,
    model: str = MODEL,
    init_tools: list[str] | None = None,
    mcp_servers: list[dict[str, str]] | None = None,
    model_usage: dict[str, Any] | None = None,
    total_cost_usd: float = 0.02,
    extra_events: tuple[dict[str, Any], ...] = (),
) -> str:
    action = action or {"sql": "SELECT COUNT(*) FROM site", "type": "answer"}
    model_usage = model_usage or _model_usage(model, total_cost_usd)
    events = (
        {
            **_init_event(model),
            "mcp_servers": [] if mcp_servers is None else mcp_servers,
            "tools": ["StructuredOutput"] if init_tools is None else init_tools,
        },
        *extra_events,
        {
            "is_error": False,
            "modelUsage": model_usage,
            "result": json.dumps(action),
            "session_id": "session-1",
            "structured_output": {"action": action},
            "subtype": "success",
            "total_cost_usd": total_cost_usd,
            "type": "result",
        },
    )
    return "\n".join(json.dumps(event) for event in events)


def _retry_event(
    *,
    attempt: int = 1,
    uuid: str = "retry-1",
    error_status: int | None = 529,
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "error": "overloaded" if error_status == 529 else "rate_limit",
        "error_status": error_status,
        "max_retries": 10,
        "retry_delay_ms": 500,
        "session_id": "session-1",
        "subtype": "api_retry",
        "type": "system",
        "uuid": uuid,
    }


def _error_stream(
    subtype: str,
    *,
    status: int | None = None,
    extra_events: tuple[dict[str, Any], ...] = (),
) -> str:
    result = {
        "errors": ["sanitized provider failure"],
        "is_error": True,
        "modelUsage": {} if status is not None else _model_usage(),
        "result": "sanitized provider failure",
        "session_id": "session-1",
        "subtype": subtype,
        "total_cost_usd": 0.0 if status is not None else 0.02,
        "type": "result",
    }
    if status is not None:
        result["api_error_status"] = status
    events = (
        _init_event(),
        *extra_events,
        result,
    )
    return "\n".join(json.dumps(event) for event in events)


class _RecordingRunner:
    def __init__(self, result: ClaudeProcessResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        command: tuple[str, ...],
        *,
        stdin: str,
        cwd: Path,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout_seconds: float,
    ) -> ClaudeProcessResult:
        self.calls.append(
            {
                "command": command,
                "cwd": cwd,
                "env": env,
                "pass_fds": pass_fds,
                "stdin": stdin,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.result


def _config(tmp_path: Path, **overrides: Any) -> ClaudeDirectConfig:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    directories = {}
    for name in ("config", "home", "tmp", "work"):
        path = tmp_path / name
        path.mkdir(mode=0o700)
        directories[name] = path
    values = {
        "budget_id": "direct-sql-production-v1",
        "claude_config_dir": directories["config"],
        "effort": "high",
        "maximum_cost_usd": 1.0,
        "maximum_turns": 12,
        "model": MODEL,
        "runtime_home": directories["home"],
        "temp_directory": directories["tmp"],
        "timeout_seconds": 90.0,
        "working_directory": directories["work"],
    }
    values.update(overrides)
    return ClaudeDirectConfig(**values)


def _transport(
    tmp_path: Path,
    stdout: str | None = None,
    *,
    stderr: str = "",
    returncode: int = 0,
    runner: Any | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> tuple[ClaudeDirectTransport, _RecordingRunner | Any]:
    if runner is None:
        runner = _RecordingRunner(
            ClaudeProcessResult(
                duration_seconds=1.25,
                returncode=returncode,
                stderr=stderr,
                stdout=_success_stream() if stdout is None else stdout,
            )
        )
    transport = ClaudeDirectTransport(
        _config(tmp_path, **(config_overrides or {})), runner=runner
    )
    return transport, runner


def _value_after(command: tuple[str, ...], flag: str) -> str:
    return command[command.index(flag) + 1]


def test_pinned_binary_matches_reviewed_claude_code_release() -> None:
    assert PINNED_CLAUDE_BINARY == Path("/home/ds/.local/share/claude/versions/2.1.250")
    assert (
        PINNED_CLAUDE_BINARY_SHA256
        == "2be252a00ac56e704d7fbf7e5e9ef1243584093334a861945238a0c27e84bdac"
    )


def test_execution_authority_changes_with_config_or_runner_state(
    tmp_path: Path,
) -> None:
    transport, _ = _transport(tmp_path / "first")
    original = transport.execution_authority

    object.__setattr__(
        transport,
        "_config",
        replace(transport._config, timeout_seconds=9876.0),
    )
    assert transport.execution_authority != original

    after_config = transport.execution_authority
    object.__setattr__(transport, "_runner", object())
    assert transport.execution_authority != after_config


def test_command_has_no_ambient_tools_fallback_or_session_state(tmp_path: Path) -> None:
    transport, runner = _transport(tmp_path)

    transport.next_turn(_messages(), _tool_specs())

    call = runner.calls[0]
    command = call["command"]
    assert command[0].startswith("/proc/self/fd/")
    assert int(command[0].rsplit("/", 1)[1]) in call["pass_fds"]
    assert command[1] == "--print"
    for flag in (
        "--disable-slash-commands",
        "--include-partial-messages",
        "--no-chrome",
        "--no-session-persistence",
        "--restricted",
        "--safe-mode",
        "--strict-mcp-config",
        "--verbose",
    ):
        assert flag in command
    assert _value_after(command, "--tools") == ""
    assert _value_after(command, "--setting-sources") == ""
    assert json.loads(_value_after(command, "--mcp-config")) == {"mcpServers": {}}
    assert _value_after(command, "--model") == MODEL
    assert _value_after(command, "--effort") == "high"
    assert _value_after(command, "--output-format") == "stream-json"
    assert _value_after(command, "--permission-mode") == "dontAsk"
    assert _value_after(command, "--max-budget-usd") == "1"
    assert not {
        "--agent",
        "--agents",
        "--continue",
        "--fallback-model",
        "--fork-session",
        "--plugin-dir",
        "--plugin-url",
        "--resume",
        "--session-id",
    }.intersection(command)
    assert "How many sites are there?" not in command
    assert json.loads(call["stdin"])["messages"] == list(_messages())


def test_json_schema_is_limited_to_harness_action_and_offered_tools(
    tmp_path: Path,
) -> None:
    transport, runner = _transport(tmp_path)

    transport.next_turn(_messages(), _tool_specs())

    schema = json.loads(_value_after(runner.calls[0]["command"], "--json-schema"))
    assert schema["additionalProperties"] is False
    assert set(schema) == {
        "additionalProperties",
        "properties",
        "required",
        "type",
    }
    assert schema["required"] == ["action"]
    variants = schema["properties"]["action"]["oneOf"]
    tool_variants = [item for item in variants if "name" in item["properties"]]
    assert [item["properties"]["name"]["const"] for item in tool_variants] == [
        "inspect_schema",
        "execute_sql",
    ]
    assert {item["properties"]["type"]["const"] for item in variants} == {
        "answer",
        "refuse",
        "tool",
    }


def test_environment_is_constructed_from_explicit_private_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "must-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    monkeypatch.setenv("MCP_CONFIG", "must-not-leak")
    transport, runner = _transport(tmp_path)

    transport.next_turn(_messages(), _tool_specs())

    env = runner.calls[0]["env"]
    assert {
        key: value
        for key, value in env.items()
        if key not in {"CLAUDE_CONFIG_DIR", "HOME", "TMPDIR"}
    } == {
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "TERM": "dumb",
    }
    assert all(
        env[name].startswith("/proc/self/fd/")
        for name in ("CLAUDE_CONFIG_DIR", "HOME", "TMPDIR")
    )
    assert not set(env).intersection(
        {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "AWS_SECRET_ACCESS_KEY"}
    )


def test_success_uses_terminal_model_usage_and_cost_not_partial_events(
    tmp_path: Path,
) -> None:
    duplicate = _assistant_event(input_tokens=999, output_tokens=999)
    transport, _ = _transport(
        tmp_path,
        _success_stream(extra_events=(duplicate, duplicate)),
    )

    turn = transport.next_turn(_messages(), _tool_specs())

    assert turn.action == {"sql": "SELECT COUNT(*) FROM site", "type": "answer"}
    assert turn.input_tokens == 10
    assert turn.output_tokens == 5
    assert turn.cost_usd == pytest.approx(0.02)
    assert turn.retry_count == 0
    assert turn.provenance.token_source == "claude_result_model_usage"
    assert turn.provenance.cost_source == "claude_result_total_cost_usd"
    assert turn.provenance.partial_usage.input_tokens == 1002
    assert turn.provenance.partial_usage.output_tokens == 999


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("canonicalModel", "claude-opus-4-6"),
        ("provider", "bedrock"),
        ("contextWindow", 0),
        ("maxOutputTokens", True),
        ("webSearchRequests", -1),
    ],
)
def test_additive_usage_still_validates_model_provider_and_counts(
    tmp_path: Path, field: str, value: Any
) -> None:
    stream = json.loads(_success_stream().splitlines()[-1])
    stream["modelUsage"][MODEL][field] = value
    stdout = "\n".join((*_success_stream().splitlines()[:-1], json.dumps(stream)))
    transport, _ = _transport(tmp_path, stdout)

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category in {"model_identity", "protocol"}


def test_api_retry_events_are_deduplicated_and_exposed(tmp_path: Path) -> None:
    first = _retry_event()
    second = _retry_event(attempt=2, uuid="retry-2")
    transport, _ = _transport(
        tmp_path,
        _success_stream(extra_events=(first, first, second)),
    )

    turn = transport.next_turn(_messages(), _tool_specs())
    assert turn.retry_count == 2
    changed = {**first, "retry_delay_ms": 900}
    transport, _ = _transport(
        tmp_path / "conflict",
        _success_stream(extra_events=(first, changed)),
    )
    with pytest.raises(ClaudeDirectTransportError, match="retry") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert (exc.value.category, exc.value.terminal_cost_usd) == ("protocol", 0.02)


def test_repeated_partial_assistant_event_is_deduplicated_by_provider_identity(
    tmp_path: Path,
) -> None:
    event = _assistant_event(input_tokens=3, cache_read_input_tokens=4, output_tokens=2)
    transport, _ = _transport(
        tmp_path,
        _success_stream(extra_events=(event, event)),
    )

    turn = transport.next_turn(_messages(), _tool_specs())

    assert turn.provenance.partial_usage.input_tokens == 3 + 4 + 1
    assert turn.provenance.partial_usage.output_tokens == 2
    assert turn.provenance.partial_usage.message_count == 1


def test_conflicting_duplicate_provider_message_is_protocol_failure(
    tmp_path: Path,
) -> None:
    first = _assistant_event(input_tokens=3)
    changed = _assistant_event(input_tokens=4)
    transport, _ = _transport(
        tmp_path,
        _success_stream(extra_events=(first, changed)),
    )

    with pytest.raises(
        ClaudeDirectTransportError, match="conflicting duplicate"
    ) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "protocol"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("inputTokens", -1),
        ("outputTokens", True),
        ("cacheReadInputTokens", 1.5),
        ("cacheCreationInputTokens", -1),
        ("costUSD", -0.01),
        ("costUSD", math.inf),
    ],
)
def test_non_finite_or_negative_terminal_telemetry_is_rejected(
    tmp_path: Path, field: str, value: Any
) -> None:
    usage = _model_usage()
    usage[MODEL][field] = value
    transport, _ = _transport(tmp_path, _success_stream(model_usage=usage))

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "protocol"


@pytest.mark.parametrize("cost", [-0.01, math.nan, math.inf])
def test_non_finite_or_negative_total_cost_is_rejected(
    tmp_path: Path, cost: float
) -> None:
    transport, _ = _transport(tmp_path, _success_stream(total_cost_usd=cost))

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "protocol"


def test_terminal_cost_must_reconcile_with_model_usage(tmp_path: Path) -> None:
    transport, _ = _transport(
        tmp_path, _success_stream(model_usage=_model_usage(), total_cost_usd=0.03)
    )

    with pytest.raises(ClaudeDirectTransportError, match="cost") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "protocol"


def test_intrinsic_structured_output_surface_is_accepted(tmp_path: Path) -> None:
    transport, _ = _transport(
        tmp_path,
        _success_stream(init_tools=["StructuredOutput"]),
    )

    turn = transport.next_turn(_messages(), _tool_specs())

    assert turn.action == {"sql": "SELECT COUNT(*) FROM site", "type": "answer"}


@pytest.mark.parametrize(
    ("stdout", "match", "category"),
    [
        (_success_stream(model="claude-unexpected-9"), "model", "model_identity"),
        (_success_stream(init_tools=[]), "tool surface", "tool_surface"),
        (_success_stream(init_tools=["Bash"]), "tool surface", "tool_surface"),
        (
            _success_stream(init_tools=["StructuredOutput", "StructuredOutput"]),
            "tool surface",
            "tool_surface",
        ),
        (
            _success_stream(init_tools=["StructuredOutput", "Bash"]),
            "tool surface",
            "tool_surface",
        ),
        (
            _success_stream(init_tools=["Bash", "StructuredOutput"]),
            "tool surface",
            "tool_surface",
        ),
        (
            _success_stream(mcp_servers=[{"name": "ambient", "status": "connected"}]),
            "tool surface",
            "tool_surface",
        ),
    ],
)
def test_wrong_model_or_ambient_surface_fails_with_terminal_telemetry(
    tmp_path: Path, stdout: str, match: str, category: str
) -> None:
    transport, _ = _transport(tmp_path, stdout)

    with pytest.raises(ClaudeDirectTransportError, match=match) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert (exc.value.category, exc.value.terminal_cost_usd) == (category, 0.02)


@pytest.mark.parametrize(
    "action",
    [
        {"sql": "SELECT 1", "type": "answer", "unexpected": True},
        {"name": "Bash", "arguments": {}, "type": "tool"},
        {"name": "StructuredOutput", "arguments": {}, "type": "tool"},
        {"name": "execute_sql", "arguments": {}, "type": "tool"},
        {"reason": "maybe", "type": "refuse"},
    ],
)
def test_structured_action_is_revalidated_against_offered_tools(
    tmp_path: Path, action: dict[str, Any]
) -> None:
    transport, _ = _transport(tmp_path, _success_stream(action=action))

    with pytest.raises(ClaudeDirectTransportError, match="structured action") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "protocol"
    assert exc.value.terminal_usage is not None


@pytest.mark.parametrize(
    ("stdout", "stderr", "returncode", "expected"),
    [
        (json.dumps(_init_event()), "HTTP 403 Forbidden", 1, "auth"),
        (json.dumps(_init_event()), "HTTP 429 Too Many Requests", 1, "rate_limit"),
        ("You've hit your session limit · resets 1:10pm", "", 1, "quota"),
        ("", "native process exited unexpectedly", 23, "infrastructure"),
    ],
)
def test_cli_failures_are_classified_without_scanning_agent_content(
    tmp_path: Path,
    stdout: str,
    stderr: str,
    returncode: int,
    expected: str,
) -> None:
    transport, _ = _transport(tmp_path, stdout, stderr=stderr, returncode=returncode)

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == expected


@pytest.mark.parametrize(
    ("subtype", "status", "expected"),
    [
        ("success", 401, "auth"),
        ("success", 403, "auth"),
        ("success", 429, "rate_limit"),
        ("error_max_budget_usd", None, "budget"),
        ("error_max_structured_output_retries", None, "structured_output"),
    ],
)
def test_nonzero_structured_terminal_failure_is_classified_before_fallback(
    tmp_path: Path, subtype: str, status: int | None, expected: str
) -> None:
    retry = _retry_event(error_status=429) if status == 429 else _retry_event()
    assistant = _assistant_event(input_tokens=3, output_tokens=2)
    transport, _ = _transport(
        tmp_path,
        "native warning\n"
        + _error_stream(subtype, status=status, extra_events=(assistant, retry, retry)),
        stderr="untrusted provider detail",
        returncode=1,
    )

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert isinstance(exc.value, DirectModelFailure)
    assert exc.value.category == expected
    assert exc.value.partial_usage.input_tokens == 6
    expected = (0, 0.0) if status is not None else (10, 0.02)
    assert (
        exc.value.terminal_usage.input_tokens,
        exc.value.terminal_cost_usd,
    ) == expected
    assert exc.value.accounted_usage is exc.value.terminal_usage
    assert exc.value.token_source == "provider_reported"
    assert exc.value.token_observation == "terminal"
    assert exc.value.cost_source == "provider_reported"
    assert exc.value.retry_count == 1


def test_structured_oauth_failure_ignores_synthetic_partial_model(
    tmp_path: Path,
) -> None:
    assistant = _assistant_event(model="<synthetic>", input_tokens=0, output_tokens=0)
    events = [
        _init_event(),
        assistant,
        {
            "is_error": True,
            "modelUsage": {},
            "result": (
                "Failed to authenticate: OAuth session expired and could not be "
                "refreshed"
            ),
            "session_id": "session-1",
            "subtype": "success",
            "total_cost_usd": 0.0,
            "type": "result",
        },
    ]
    transport, _ = _transport(
        tmp_path,
        "\n".join(json.dumps(event) for event in events),
        returncode=0,
    )

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "auth"
    assert "OAuth session expired" not in str(exc.value)
    assert exc.value.partial_usage.models == ("<synthetic>",)
    assert exc.value.terminal_usage is not None
    assert exc.value.terminal_usage.input_tokens == 0


def test_successful_synthetic_partial_model_remains_invalid(tmp_path: Path) -> None:
    transport, _ = _transport(
        tmp_path,
        _success_stream(extra_events=(_assistant_event(model="<synthetic>"),)),
    )

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "model_identity"


def test_structured_output_failure_is_not_reclassified_from_result_text(
    tmp_path: Path,
) -> None:
    events = [
        json.loads(line)
        for line in _error_stream("error_max_structured_output_retries").splitlines()
    ]
    events[-1]["result"] = "model wrote: OAuth session expired"
    transport, _ = _transport(
        tmp_path,
        "\n".join(json.dumps(event) for event in events),
        returncode=1,
    )

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "structured_output"


def test_provider_error_still_requires_pinned_init_model(tmp_path: Path) -> None:
    events = [json.loads(line) for line in _error_stream("success").splitlines()]
    events[0]["model"] = "claude-unexpected-9"
    transport, _ = _transport(
        tmp_path,
        "\n".join(json.dumps(event) for event in events),
        returncode=1,
    )

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "model_identity"


@pytest.mark.parametrize("is_error", [None, 0, 1, "false"])
def test_success_requires_is_error_to_be_exactly_false(
    tmp_path: Path, is_error: Any
) -> None:
    events = [json.loads(line) for line in _success_stream().splitlines()]
    if is_error is None:
        events[-1].pop("is_error")
    else:
        events[-1]["is_error"] = is_error
    transport, _ = _transport(
        tmp_path, "\n".join(json.dumps(event) for event in events)
    )

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "infrastructure"

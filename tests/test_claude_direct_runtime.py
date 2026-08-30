from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

import omni_benchmark.claude_direct_transport as claude_transport
from omni_benchmark.claude_direct_transport import (
    ClaudeDirectTransport,
    ClaudeDirectTransportError,
    ClaudeProcessResult,
)
from tests.test_claude_direct_transport import (
    MODEL,
    _RecordingRunner,
    _assistant_event,
    _config,
    _messages,
    _retry_event,
    _success_stream,
    _tool_specs,
    _transport,
)


class _SecretFailingRunner:
    def __call__(self, *args: Any, **kwargs: Any) -> ClaudeProcessResult:
        raise RuntimeError("credential=do-not-retain")


def test_runner_failure_does_not_retain_secret_in_exception_graph(
    tmp_path: Path,
) -> None:
    transport, _ = _transport(tmp_path, runner=_SecretFailingRunner())

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    failure = exc.value
    assert failure.category == "infrastructure"
    assert "do-not-retain" not in str(failure.args) + repr(failure)
    assert failure.__cause__ is None
    assert failure.__context__ is None


class _TimeoutRunner:
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
        event = _assistant_event(
            input_tokens=11,
            cache_read_input_tokens=7,
            cache_creation_input_tokens=3,
            output_tokens=5,
        )
        retry = _retry_event()
        raise subprocess.TimeoutExpired(
            command,
            timeout_seconds,
            output=(
                f"{json.dumps(event)}\n{json.dumps(event)}\n"
                f"{json.dumps(retry)}\n{json.dumps(_retry_event(attempt=2))}\n"
            ),
            stderr="",
        )


class _ResourceDriftRunner:
    def __init__(self, target: Path, failure: Exception) -> None:
        self._failure = failure
        self._target = target
        self.snapshot_root: Path | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> ClaudeProcessResult:
        self.snapshot_root = Path(kwargs["env"]["HOME"]).resolve().parent
        self._target.write_text("changed during invocation", encoding="utf-8")
        raise self._failure


def test_timeout_keeps_usage_despite_retry_conflict(tmp_path: Path) -> None:
    transport, _ = _transport(tmp_path, runner=_TimeoutRunner())

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "timeout"
    assert exc.value.partial_usage.input_tokens == 21
    assert exc.value.retry_count is None


def test_resource_drift_takes_precedence_over_runner_exception(tmp_path: Path) -> None:
    config = _config(tmp_path)
    target = config.runtime_home / "state.json"
    target.write_text("reviewed", encoding="utf-8")
    runner = _ResourceDriftRunner(target, RuntimeError("provider failed"))
    transport = ClaudeDirectTransport(config, runner=runner)

    with pytest.raises(ClaudeDirectTransportError, match="during invocation") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "setup"
    assert exc.value.partial_usage is None
    assert runner.snapshot_root is not None
    assert not runner.snapshot_root.exists()


def test_resource_drift_takes_precedence_and_preserves_timeout_usage(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    target = config.working_directory / "state.json"
    target.write_text("reviewed", encoding="utf-8")
    event = _assistant_event(input_tokens=13, output_tokens=5)
    failure = subprocess.TimeoutExpired(
        ("claude",), config.timeout_seconds, output=json.dumps(event), stderr=""
    )
    runner = _ResourceDriftRunner(target, failure)
    transport = ClaudeDirectTransport(config, runner=runner)

    with pytest.raises(ClaudeDirectTransportError, match="during invocation") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "setup"
    assert exc.value.partial_usage.input_tokens == 16
    assert exc.value.partial_usage.output_tokens == 5
    assert runner.snapshot_root is not None
    assert not runner.snapshot_root.exists()


def test_shape_failures_keep_unambiguous_telemetry(tmp_path: Path) -> None:
    session_events = [json.loads(line) for line in _success_stream().splitlines()]
    session_events[-1]["session_id"] = "other-session"
    duplicate_events = [json.loads(line) for line in _success_stream().splitlines()]
    duplicate_events.append(duplicate_events[-1])
    cases = ((session_events, 0, 0.02), (duplicate_events, 1, None))
    for index, (events, returncode, expected_cost) in enumerate(cases):
        stdout = "\n".join(json.dumps(event) for event in events)
        transport, _ = _transport(
            tmp_path / str(index),
            stdout,
            stderr="HTTP 401 Unauthorized",
            returncode=returncode,
        )
        with pytest.raises(ClaudeDirectTransportError) as exc:
            transport.next_turn(_messages(), _tool_specs())
        assert (exc.value.category, exc.value.terminal_cost_usd) == (
            "protocol",
            expected_cost,
        )


def test_runtime_directories_must_be_private_real_directories(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(mode=0o755)
    config = _config(tmp_path / "other", claude_config_dir=config_dir)

    with pytest.raises(ClaudeDirectTransportError, match="private") as exc:
        ClaudeDirectTransport(
            config, runner=_RecordingRunner(ClaudeProcessResult(0, 0, "", ""))
        )

    assert exc.value.category == "setup"


def test_provider_provenance_is_immutable_and_content_bound(tmp_path: Path) -> None:
    transport, _ = _transport(tmp_path)

    turn = transport.next_turn(_messages(), _tool_specs())

    provenance = turn.provenance
    assert provenance.provider == "anthropic_claude_code_oauth"
    assert provenance.requested_model == MODEL
    assert provenance.realized_models == (MODEL,)
    assert provenance.binary_sha256 == claude_transport.PINNED_CLAUDE_BINARY_SHA256
    assert provenance.cli_version == "2.1.250"
    assert len(provenance.stream_sha256) == 64
    assert len(provenance.request_sha256) == 64
    with pytest.raises(FrozenInstanceError):
        provenance.provider = "changed"  # type: ignore[misc]


def test_messages_and_tool_specs_must_be_finite_strict_json(tmp_path: Path) -> None:
    transport, runner = _transport(tmp_path)

    with pytest.raises(ClaudeDirectTransportError, match="strict JSON") as exc:
        transport.next_turn(({"role": "user", "content": float("nan")},), _tool_specs())

    assert exc.value.category == "protocol"
    assert runner.calls == []


def test_config_rejects_unpinned_or_unbounded_execution(tmp_path: Path) -> None:
    with pytest.raises(ClaudeDirectTransportError, match="timeout"):
        ClaudeDirectTransport(
            _config(tmp_path / "timeout", timeout_seconds=math.inf),
            runner=_RecordingRunner(ClaudeProcessResult(0, 0, "", "")),
        )
    with pytest.raises(ClaudeDirectTransportError, match="cost"):
        ClaudeDirectTransport(
            _config(tmp_path / "cost", maximum_cost_usd=0),
            runner=_RecordingRunner(ClaudeProcessResult(0, 0, "", "")),
        )
    with pytest.raises(ClaudeDirectTransportError, match="model"):
        ClaudeDirectTransport(
            _config(tmp_path / "model", model="sonnet"),
            runner=_RecordingRunner(ClaudeProcessResult(0, 0, "", "")),
        )


def test_no_live_process_is_used_by_fixture_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("fixture tests must not launch Claude")

    monkeypatch.setattr(subprocess, "run", fail)
    assert os.path.isfile(claude_transport.PINNED_CLAUDE_BINARY)

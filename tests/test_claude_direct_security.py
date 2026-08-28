from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

import omni_benchmark.claude_resource_identity as resource_identity
import omni_benchmark.claude_direct_transport as claude_transport
from omni_benchmark.claude_direct_transport import (
    ClaudeDirectTransport,
    ClaudeDirectTransportError,
    ClaudeProcessResult,
)
from omni_benchmark.direct_runtime_binding import DirectModelIdentity
from tests.test_claude_direct_transport import (
    _RecordingRunner,
    _assistant_event,
    _config,
    _messages,
    _model_usage,
    _success_stream,
    _tool_specs,
    _transport,
)


def test_positive_web_search_is_tool_surface_failure_with_telemetry(
    tmp_path: Path,
) -> None:
    usage = _model_usage(webSearchRequests=1)
    transport, _ = _transport(tmp_path, _success_stream(model_usage=usage))

    with pytest.raises(ClaudeDirectTransportError, match="web search") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "tool_surface"
    assert exc.value.terminal_cost_usd == pytest.approx(0.02)
    assert exc.value.terminal_usage is not None


def test_transport_exposes_exact_frozen_model_identity_and_turn_reconciles_it(
    tmp_path: Path,
) -> None:
    transport, _ = _transport(tmp_path)

    turn = transport.next_turn(_messages(), _tool_specs())

    identity = transport.runtime_identity
    assert type(identity) is DirectModelIdentity
    assert identity.provider == "anthropic_claude_code_oauth"
    assert identity.model == "claude-sonnet-4-6"
    assert identity.adapter == "claude-code-restricted-mcp"
    assert identity.adapter_version == "1.0.0"
    assert identity.executable_version == "2.1.250"
    assert identity.executable_sha256 == claude_transport.PINNED_CLAUDE_BINARY_SHA256
    assert turn.model_identity == identity
    assert turn.provenance.model_identity == identity
    assert transport.budget_identity.budget_id == "direct-sql-production-v1"
    assert transport.budget_identity.maximum_turns == 12
    with pytest.raises(FrozenInstanceError):
        identity.model = "changed"  # type: ignore[misc]


def test_transport_config_changes_produce_distinct_model_identities(
    tmp_path: Path,
) -> None:
    first, _ = _transport(tmp_path / "first")
    second, _ = _transport(tmp_path / "second", config_overrides={"effort": "medium"})

    assert first.runtime_identity.transport_config_sha256 != (
        second.runtime_identity.transport_config_sha256
    )
    assert first.runtime_identity.system_prompt_sha256 == (
        second.runtime_identity.system_prompt_sha256
    )


def test_resource_pinning_failure_does_not_retain_raw_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, runner = _transport(tmp_path)

    def fail_open(_: Path) -> int:
        raise OSError("credential=must-not-survive")

    monkeypatch.setattr(resource_identity, "open_claude_binary", fail_open)

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    failure = exc.value
    assert failure.category == "setup"
    assert "must-not-survive" not in str(failure.args) + repr(failure)
    assert failure.__cause__ is None
    assert failure.__context__ is None
    assert runner.calls == []


def test_stale_model_identity_is_rejected_before_provider_invocation(
    tmp_path: Path,
) -> None:
    transport, runner = _transport(tmp_path)
    forged = transport.runtime_identity.as_dict()
    forged["transport_config_sha256"] = "f" * 64
    object.__setattr__(
        transport,
        "_model_identity",
        DirectModelIdentity.from_dict(forged, environment={}),
    )

    with pytest.raises(ClaudeDirectTransportError, match="model identity") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "model_identity"
    assert runner.calls == []


def test_invalid_binary_hash_refuses_before_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _RecordingRunner(ClaudeProcessResult(0.0, 0, "", _success_stream()))
    monkeypatch.setattr(
        resource_identity, "claude_binary_sha256", lambda descriptor: "0" * 64
    )
    transport = ClaudeDirectTransport(_config(tmp_path), runner=runner)

    with pytest.raises(ClaudeDirectTransportError, match="binary SHA") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "setup"
    assert runner.calls == []


def test_private_directories_are_revalidated_before_every_turn(tmp_path: Path) -> None:
    transport, runner = _transport(tmp_path)
    (tmp_path / "home").chmod(0o755)

    with pytest.raises(ClaudeDirectTransportError, match="private") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "setup"
    assert runner.calls == []


def test_config_content_mutation_changes_authority_and_refuses_before_runner(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config_file = config.claude_config_dir / "oauth.json"
    config_file.write_text('{"profile":"reviewed"}', encoding="utf-8")
    runner = _RecordingRunner(ClaudeProcessResult(1.0, 0, "", _success_stream()))
    transport = ClaudeDirectTransport(config, runner=runner)
    reviewed_authority = transport.execution_authority
    assert len(reviewed_authority) == 64
    assert "reviewed" not in reviewed_authority

    config_file.write_text('{"profile":"substituted"}', encoding="utf-8")

    assert transport.execution_authority != reviewed_authority
    with pytest.raises(ClaudeDirectTransportError, match="resources changed") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "setup"
    assert runner.calls == []


def test_added_working_directory_content_changes_authority_and_refuses_before_runner(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    runner = _RecordingRunner(ClaudeProcessResult(1.0, 0, "", _success_stream()))
    transport = ClaudeDirectTransport(config, runner=runner)
    reviewed_authority = transport.execution_authority

    (config.working_directory / "CLAUDE.md").write_text(
        "Substituted ambient instruction.", encoding="utf-8"
    )

    assert transport.execution_authority != reviewed_authority
    with pytest.raises(ClaudeDirectTransportError, match="resources changed") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "setup"
    assert runner.calls == []


def test_same_path_directory_replacement_changes_authority_and_refuses_before_runner(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    runner = _RecordingRunner(ClaudeProcessResult(1.0, 0, "", _success_stream()))
    transport = ClaudeDirectTransport(config, runner=runner)
    reviewed_authority = transport.execution_authority
    reviewed_directory = config.runtime_home.with_name("reviewed-home")
    config.runtime_home.rename(reviewed_directory)
    config.runtime_home.mkdir(mode=0o700)

    assert transport.execution_authority != reviewed_authority
    with pytest.raises(ClaudeDirectTransportError, match="resources changed") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "setup"
    assert runner.calls == []


class _SwapResourcesRunner(_RecordingRunner):
    def __init__(
        self,
        result: ClaudeProcessResult,
        *,
        binary_path: Path,
        config_path: Path,
    ) -> None:
        super().__init__(result)
        self._binary_path = binary_path
        self._config_path = config_path
        self.pinned_binary = b""
        self.pinned_config_inode = 0
        self.reviewed_config_inode = 0

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
        replaced_binary = self._binary_path.with_suffix(".reviewed")
        self._binary_path.rename(replaced_binary)
        self._binary_path.write_bytes(b"replacement")
        self._binary_path.chmod(0o700)
        replaced_config = self._config_path.with_suffix(".reviewed")
        self._config_path.rename(replaced_config)
        self._config_path.mkdir(mode=0o700)
        self.pinned_binary = Path(command[0]).read_bytes()
        self.pinned_config_inode = Path(env["CLAUDE_CONFIG_DIR"]).stat().st_ino
        self.reviewed_config_inode = replaced_config.stat().st_ino
        return super().__call__(
            command,
            stdin=stdin,
            cwd=cwd,
            env=env,
            pass_fds=pass_fds,
            timeout_seconds=timeout_seconds,
        )


class _ReplaceContainedFileRunner(_RecordingRunner):
    def __init__(
        self,
        result: ClaudeProcessResult,
        *,
        pinned_root: str,
        target: Path,
        replacement_content: str,
    ) -> None:
        super().__init__(result)
        self._pinned_root = pinned_root
        self._replacement_content = replacement_content
        self._target = target
        self.observed_content = ""
        self.snapshot_file_mode = 0
        self.snapshot_root_mode = 0
        self.snapshot_root: Path | None = None

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
        replacement = self._target.with_suffix(".replacement")
        replacement.write_text(self._replacement_content, encoding="utf-8")
        replacement.replace(self._target)
        pinned_roots = {
            "config": Path(env["CLAUDE_CONFIG_DIR"]),
            "home": Path(env["HOME"]),
            "work": cwd,
        }
        pinned_target = pinned_roots[self._pinned_root] / self._target.name
        self.observed_content = pinned_target.read_text(encoding="utf-8")
        self.snapshot_root = pinned_target.parent.resolve()
        self.snapshot_file_mode = pinned_target.stat().st_mode & 0o777
        self.snapshot_root_mode = pinned_target.parent.stat().st_mode & 0o777
        return super().__call__(
            command,
            stdin=stdin,
            cwd=cwd,
            env=env,
            pass_fds=pass_fds,
            timeout_seconds=timeout_seconds,
        )


class _WriteTemporaryFileRunner(_RecordingRunner):
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
        (Path(env["TMPDIR"]) / "provider-runtime.tmp").write_text(
            "mutable runtime state", encoding="utf-8"
        )
        return super().__call__(
            command,
            stdin=stdin,
            cwd=cwd,
            env=env,
            pass_fds=pass_fds,
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.parametrize(
    ("directory_attribute", "pinned_root"),
    [
        ("claude_config_dir", "config"),
        ("runtime_home", "home"),
        ("working_directory", "work"),
    ],
)
def test_contained_input_replacement_during_runner_is_rejected_after_runner(
    tmp_path: Path, directory_attribute: str, pinned_root: str
) -> None:
    config = _config(tmp_path)
    input_file = getattr(config, directory_attribute) / "input.json"
    input_file.write_text('{"profile":"reviewed"}', encoding="utf-8")
    secret = "credential=must-not-survive"
    runner = _ReplaceContainedFileRunner(
        ClaudeProcessResult(
            1.0, 0, "", _success_stream(extra_events=(_assistant_event(),))
        ),
        pinned_root=pinned_root,
        target=input_file,
        replacement_content=secret,
    )
    transport = ClaudeDirectTransport(config, runner=runner)

    with pytest.raises(ClaudeDirectTransportError, match="during invocation") as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert runner.observed_content == '{"profile":"reviewed"}'
    assert runner.snapshot_file_mode == 0o400
    assert runner.snapshot_root_mode == 0o500
    assert runner.snapshot_root is not None
    assert not runner.snapshot_root.exists()
    assert len(runner.calls) == 1
    assert exc.value.category == "setup"
    assert exc.value.partial_usage.input_tokens == 10
    assert secret not in str(exc.value.args) + repr(exc.value)
    assert exc.value.__cause__ is None


class _SwapRestoreContainedFileRunner(_RecordingRunner):
    def __init__(self, result: ClaudeProcessResult, *, target: Path) -> None:
        super().__init__(result)
        self._target = target
        self.observed_content = ""

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
        reviewed = self._target.with_suffix(".reviewed")
        self._target.rename(reviewed)
        self._target.write_text("substituted", encoding="utf-8")
        self.observed_content = (
            Path(env["CLAUDE_CONFIG_DIR"]) / self._target.name
        ).read_text(encoding="utf-8")
        self._target.unlink()
        reviewed.rename(self._target)
        return super().__call__(
            command,
            stdin=stdin,
            cwd=cwd,
            env=env,
            pass_fds=pass_fds,
            timeout_seconds=timeout_seconds,
        )


def test_transient_original_swap_cannot_change_provider_visible_bytes(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    input_file = config.claude_config_dir / "input.json"
    input_file.write_text("reviewed", encoding="utf-8")
    runner = _SwapRestoreContainedFileRunner(
        ClaudeProcessResult(1.0, 0, "", _success_stream()), target=input_file
    )
    transport = ClaudeDirectTransport(config, runner=runner)

    turn = transport.next_turn(_messages(), _tool_specs())

    assert runner.observed_content == "reviewed"
    assert turn.action["type"] == "answer"


def test_temporary_directory_content_remains_mutable_during_runner(
    tmp_path: Path,
) -> None:
    runner = _WriteTemporaryFileRunner(
        ClaudeProcessResult(1.0, 0, "", _success_stream())
    )
    transport = ClaudeDirectTransport(_config(tmp_path), runner=runner)

    turn = transport.next_turn(_messages(), _tool_specs())

    assert turn.action["type"] == "answer"
    assert len(runner.calls) == 1


def test_binary_and_directories_are_fd_pinned_across_verification_to_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed_binary = tmp_path / "claude-reviewed"
    reviewed_bytes = b"reviewed executable fixture"
    reviewed_binary.write_bytes(reviewed_bytes)
    reviewed_binary.chmod(0o700)
    reviewed_hash = hashlib.sha256(reviewed_bytes).hexdigest()
    monkeypatch.setattr(claude_transport, "PINNED_CLAUDE_BINARY", reviewed_binary)
    monkeypatch.setattr(claude_transport, "PINNED_CLAUDE_BINARY_SHA256", reviewed_hash)
    config = _config(tmp_path / "runtime")
    runner = _SwapResourcesRunner(
        ClaudeProcessResult(1.0, 0, "", _success_stream()),
        binary_path=reviewed_binary,
        config_path=config.claude_config_dir,
    )
    transport = ClaudeDirectTransport(config, runner=runner)

    turn = transport.next_turn(_messages(), _tool_specs())

    assert runner.pinned_binary == reviewed_bytes
    assert runner.pinned_config_inode != runner.reviewed_config_inode
    assert turn.provenance.binary_sha256 == reviewed_hash

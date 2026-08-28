from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.direct_probe_cli as direct_probe_cli
from omni_benchmark.direct_probe_cli import (
    DirectProbeCliError,
    direct_probe_main,
    load_committed_direct_runtime_spec,
    private_runtime_directories,
)


def _git(workspace: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(workspace), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _runtime_payload() -> dict[str, object]:
    return {
        "adapter": "claude-code-restricted-mcp",
        "adapter_version": "1.0.0",
        "budget_id": "direct-sql-public-baseline-v1",
        "effort": "high",
        "harness_retry_ceiling": 0,
        "input_token_ceiling": None,
        "maximum_cost_usd_per_turn": 1.0,
        "maximum_turns": 12,
        "model": "claude-opus-5",
        "output_token_ceiling": None,
        "provider": "anthropic_claude_code_oauth",
        "schema_version": 1,
        "timeout_seconds_per_turn": 120.0,
        "token_ceiling_unavailable_reason": (
            "claude_code_2.1.250_exposes_no_supported_token_limit"
        ),
    }


def _runtime_repo(
    tmp_path: Path, payload: dict[str, object] | None = None
) -> tuple[Path, str]:
    workspace = tmp_path / "repo"
    config = workspace / "config/conditions/direct-runtime-v1.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(payload or _runtime_payload(), sort_keys=True) + "\n")
    (workspace / ".gitignore").write_text("runs/\n")
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "runtime")
    return workspace, _git(workspace, "rev-parse", "HEAD")


def _arguments(workspace: Path, commit: str) -> list[str]:
    return [
        "--workspace",
        str(workspace),
        "--system-commit",
        commit,
        "--instance-id",
        "archeology_scan_10",
        "--condition",
        "C2",
        "--output-root",
        "runs/direct/canary-c2",
        "--run-id",
        "public-canary-v1",
        "--claude-config-dir",
        str(workspace / "oauth"),
    ]


def test_loads_one_committed_runtime_policy_for_all_direct_conditions(
    tmp_path: Path,
) -> None:
    workspace, commit = _runtime_repo(tmp_path)

    spec = load_committed_direct_runtime_spec(workspace, commit)

    assert spec.model == "claude-opus-5"
    assert spec.maximum_turns == 12
    assert spec.timeout_seconds_per_turn == 120.0
    assert spec.harness_retry_ceiling == 0
    assert spec.input_token_ceiling is None
    assert spec.output_token_ceiling is None


def test_runtime_policy_rejects_unknown_fields(tmp_path: Path) -> None:
    payload = _runtime_payload()
    payload["condition"] = "C1"
    workspace, commit = _runtime_repo(tmp_path, payload)

    with pytest.raises(DirectProbeCliError, match="exact schema"):
        load_committed_direct_runtime_spec(workspace, commit)


def test_cli_requires_explicit_authenticated_acknowledgement(
    tmp_path: Path,
) -> None:
    workspace, commit = _runtime_repo(tmp_path)
    (workspace / "oauth").mkdir(mode=0o700)
    called = False

    def run_attempt(_: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {"status": "unexpected"}

    with pytest.raises(DirectProbeCliError, match="explicit acknowledgement"):
        direct_probe_main(
            _arguments(workspace, commit),
            environment={},
            attempt_runner=run_attempt,
        )

    assert called is False


def test_cli_loads_committed_policy_and_emits_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, commit = _runtime_repo(tmp_path)
    oauth = workspace / "oauth"
    oauth.mkdir(mode=0o700)
    observed: list[object] = []

    def run_attempt(plan: object) -> dict[str, object]:
        observed.append(plan)
        return {"condition": "C2", "status": "refused"}

    result = direct_probe_main(
        [*_arguments(workspace, commit), "--execute-authenticated-smoke"],
        environment={},
        attempt_runner=run_attempt,
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "condition": "C2",
        "status": "refused",
    }
    plan = observed[0]
    assert plan.runtime.model == "claude-opus-5"
    assert plan.arguments.condition == "C2"


def test_runtime_directories_are_private_empty_and_ephemeral(tmp_path: Path) -> None:
    with private_runtime_directories(parent=tmp_path) as directories:
        paths = tuple(directories)
        assert len(paths) == 3
        assert len(set(paths)) == 3
        for path in paths:
            assert path.parent.parent == tmp_path
            assert not tuple(path.iterdir())
            assert path.stat().st_mode & 0o777 == 0o700
        (paths[0] / "provider-state.json").write_text("{}")

    assert all(not path.exists() for path in paths)


def test_cli_rejects_non_private_oauth_directory(tmp_path: Path) -> None:
    workspace, commit = _runtime_repo(tmp_path)
    oauth = workspace / "oauth"
    oauth.mkdir(mode=0o755)

    with pytest.raises(DirectProbeCliError, match="private"):
        direct_probe_main(
            [*_arguments(workspace, commit), "--execute-authenticated-smoke"],
            environment=dict(os.environ),
            attempt_runner=lambda _: {},
        )


def test_default_runner_wires_preparation_capture_and_publication(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, commit = _runtime_repo(tmp_path)
    oauth = workspace / "oauth"
    oauth.mkdir(mode=0o700)
    observed: dict[str, object] = {}
    prepared = SimpleNamespace(binding=object())
    probe = SimpleNamespace(
        generation_outcome="refused",
        failure_class="agent_refusal",
    )

    def prepare(**kwargs: object) -> object:
        observed["prepare"] = kwargs
        return prepared

    class Capture:
        def __init__(self, *, prepared: object) -> None:
            observed["prepared"] = prepared

        def capture(self) -> object:
            return probe

    def write_attempt(**kwargs: object) -> object:
        observed["write"] = kwargs
        root = workspace / "runs/direct/canary-c2"
        return SimpleNamespace(
            generation=SimpleNamespace(
                path=root / "generation.jsonl",
                sha256="a" * 64,
                size_bytes=10,
            ),
            run_manifest=SimpleNamespace(
                path=root / "run.json",
                sha256="b" * 64,
                size_bytes=20,
            ),
        )

    monkeypatch.setattr(direct_probe_cli, "prepare_committed_direct_attempt", prepare)
    monkeypatch.setattr(direct_probe_cli, "DirectSqlCapture", Capture)
    monkeypatch.setattr(
        direct_probe_cli,
        "DirectAttemptSpec",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(direct_probe_cli, "write_direct_attempt", write_attempt)
    monkeypatch.setattr(
        direct_probe_cli,
        "_semantic_identity",
        lambda _: ("public-hkb:" + "c" * 64, "c" * 64),
    )

    result = direct_probe_main(
        [*_arguments(workspace, commit), "--execute-authenticated-smoke"],
        environment={
            "PGHOST": "public-neon.example",
            "PGDATABASE": "neondb",
            "PGUSER": "reader",
            "PGPASSWORD": "secret",
            "UNRELATED": "not-forwarded-to-postgres",
        },
    )

    assert result == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["generation_outcome"] == "refused"
    assert receipt["failure_class"] == "agent_refusal"
    prepare_kwargs = observed["prepare"]
    assert prepare_kwargs["condition"] == "C2"
    assert prepare_kwargs["database_environment"] == {
        "PGHOST": "public-neon.example",
        "PGDATABASE": "neondb",
        "PGUSER": "reader",
        "PGPASSWORD": "secret",
    }
    assert observed["prepared"] is prepared
    assert observed["write"]["probe"] is probe


def test_runtime_directory_cleanup_failure_is_not_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_cleanup(_: Path) -> None:
        raise OSError("cleanup failed")

    monkeypatch.setattr(direct_probe_cli.shutil, "rmtree", fail_cleanup)

    with pytest.raises(DirectProbeCliError, match="could not be removed"):
        with private_runtime_directories(parent=tmp_path):
            pass

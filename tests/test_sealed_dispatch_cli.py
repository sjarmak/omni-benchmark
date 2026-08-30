from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.sealed_dispatch_cli as cli_module
from omni_benchmark.freeze_b import FreezeBManifest
from omni_benchmark.sealed_dispatch import (
    SealedDispatchError,
    SealedDispatchPolicy,
    load_sealed_dispatch_policy,
)
from tests.test_sealed_generation_staging import _plan


POLICY_VALUE = {
    "cli_versions_by_condition": {
        condition: {"synthetic": "1.0.0"} for condition in ("C1", "C2", "C3", "C4")
    },
    "cost_ceiling_usd": "121.200000",
    "maximum_concurrency": 4,
    "maximum_wall_clock_seconds": 43_200,
    "reservation_usd_by_condition": {
        "C1": "0.100000",
        "C2": "0.100000",
        "C3": "0.100000",
        "C4": "0.100000",
    },
    "software_versions": {"omni-benchmark": "0.1.0", "python": "3.11.15"},
}


def _git_workspace(tmp_path: Path) -> tuple[Path, str, Path, FreezeBManifest]:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    policy_path = Path("config/sealed-dispatch-v1.json")
    destination = workspace / policy_path
    destination.parent.mkdir(parents=True)
    content = (
        json.dumps(POLICY_VALUE, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    destination.write_bytes(content)
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "synthetic@example.invalid"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Synthetic Test"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "policy"], cwd=workspace, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _, original = _plan()
    value = original.as_dict()
    value["system_commit"] = commit
    value["scorer"]["source_commit"] = commit
    value["frozen_files"][policy_path.as_posix()] = hashlib.sha256(content).hexdigest()
    freeze = FreezeBManifest.from_dict(value)
    return workspace, commit, policy_path, freeze


def test_dispatch_policy_loads_only_canonical_frozen_git_object(tmp_path: Path) -> None:
    workspace, commit, policy_path, freeze = _git_workspace(tmp_path)

    policy = load_sealed_dispatch_policy(
        workspace,
        system_commit=commit,
        policy_path=policy_path,
        freeze_b=freeze,
    )
    (workspace / policy_path).write_text("{}\n", encoding="utf-8")
    repeated = load_sealed_dispatch_policy(
        workspace,
        system_commit=commit,
        policy_path=policy_path,
        freeze_b=freeze,
    )

    assert policy == repeated
    assert policy == SealedDispatchPolicy.from_dict(POLICY_VALUE)
    assert len(policy.sha256) == 64


def test_dispatch_policy_rejects_unfrozen_or_noncanonical_object(
    tmp_path: Path,
) -> None:
    workspace, commit, policy_path, freeze = _git_workspace(tmp_path)
    value = freeze.as_dict()
    del value["frozen_files"][policy_path.as_posix()]
    missing = FreezeBManifest.from_dict(value)

    with pytest.raises(SealedDispatchError, match="frozen"):
        load_sealed_dispatch_policy(
            workspace,
            system_commit=commit,
            policy_path=policy_path,
            freeze_b=missing,
        )

    (workspace / policy_path).write_text(
        json.dumps(POLICY_VALUE, indent=2) + "\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "noncanonical"], cwd=workspace, check=True)
    changed_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    value = freeze.as_dict()
    value["system_commit"] = changed_commit
    value["scorer"]["source_commit"] = changed_commit
    value["frozen_files"][policy_path.as_posix()] = hashlib.sha256(
        (workspace / policy_path).read_bytes()
    ).hexdigest()
    noncanonical = FreezeBManifest.from_dict(value)

    with pytest.raises(SealedDispatchError, match="canonical"):
        load_sealed_dispatch_policy(
            workspace,
            system_commit=changed_commit,
            policy_path=policy_path,
            freeze_b=noncanonical,
        )


@dataclass(frozen=True)
class _FakePreflight:
    def public_summary(self) -> dict[str, object]:
        return {
            "attempt_count": 1_212,
            "live_execution": "not_started",
            "pending_count": 1_212,
        }


@dataclass(frozen=True)
class _FakeReport:
    def public_summary(self) -> dict[str, object]:
        return {"attempt_count": 1_212, "remaining_count": 0}


def _argv(tmp_path: Path, *, execute: bool = False) -> list[str]:
    values = [
        "--workspace",
        str(tmp_path),
        "--control-commit",
        "f" * 40,
        "--system-commit",
        "e" * 40,
        "--freeze-b",
        "experiments/freeze-b.json",
        "--schedule",
        "data/final-schedule.jsonl",
        "--public-manifest",
        "data/manifests/eligible_questions.jsonl",
        "--test-ids",
        "data/manifests/sealed_mvp_ids.txt",
        "--policy",
        "config/sealed-dispatch-v1.json",
        "--receipt",
        "/tmp/sealed-approval.json",
        "--output-root",
        "runs/sealed-final-v1",
        "--run-id",
        "sealed-final-v1",
    ]
    if execute:
        values.append("--execute-sealed-generation")
    return values


def test_cli_requires_and_forwards_the_selected_test_id_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, freeze = _plan()
    policy = SealedDispatchPolicy.from_dict(POLICY_VALUE)
    selected: list[Path] = []
    monkeypatch.setattr(
        cli_module,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )

    def load_plan(*args, **kwargs):  # type: ignore[no-untyped-def]
        selected.append(kwargs["test_ids_path"])
        return plan

    monkeypatch.setattr(cli_module, "load_sealed_execution_plan", load_plan)
    monkeypatch.setattr(cli_module, "load_sealed_public_questions", lambda *a, **k: {})
    monkeypatch.setattr(
        cli_module, "load_sealed_dispatch_policy", lambda *a, **k: policy
    )
    monkeypatch.setattr(
        cli_module,
        "preflight_sealed_dispatch",
        lambda **kwargs: _FakePreflight(),
    )

    assert cli_module.dispatch_main(_argv(tmp_path)) == 0
    assert selected == [Path("data/manifests/sealed_mvp_ids.txt")]

    missing = _argv(tmp_path)
    index = missing.index("--test-ids")
    del missing[index : index + 2]
    with pytest.raises(SystemExit):
        cli_module.dispatch_main(missing)


def test_cli_defaults_to_dry_preflight_without_constructing_adapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan, freeze = _plan()
    policy = SealedDispatchPolicy.from_dict(POLICY_VALUE)
    calls: list[str] = []
    monkeypatch.setattr(
        cli_module,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )
    monkeypatch.setattr(cli_module, "load_sealed_execution_plan", lambda *a, **k: plan)
    monkeypatch.setattr(cli_module, "load_sealed_public_questions", lambda *a, **k: {})
    monkeypatch.setattr(
        cli_module, "load_sealed_dispatch_policy", lambda *a, **k: policy
    )
    monkeypatch.setattr(
        cli_module,
        "preflight_sealed_dispatch",
        lambda **kwargs: calls.append("preflight") or _FakePreflight(),
    )

    status = cli_module.dispatch_main(
        _argv(tmp_path),
        adapter_factories_builder=lambda _value: calls.append("factory"),
    )

    assert status == 0
    assert calls == ["preflight"]
    assert json.loads(capsys.readouterr().out)["live_execution"] == "not_started"


def test_cli_requires_explicit_execute_and_available_factory_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan, freeze = _plan()
    policy = SealedDispatchPolicy.from_dict(POLICY_VALUE)
    monkeypatch.setattr(
        cli_module,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )
    monkeypatch.setattr(cli_module, "load_sealed_execution_plan", lambda *a, **k: plan)
    monkeypatch.setattr(cli_module, "load_sealed_public_questions", lambda *a, **k: {})
    monkeypatch.setattr(
        cli_module, "load_sealed_dispatch_policy", lambda *a, **k: policy
    )
    monkeypatch.setattr(
        cli_module, "preflight_sealed_dispatch", lambda **kwargs: _FakePreflight()
    )

    with pytest.raises(SealedDispatchError, match="adapters are unavailable"):
        cli_module.dispatch_main(_argv(tmp_path, execute=True))

    calls: list[str] = []
    monkeypatch.setattr(
        cli_module,
        "execute_sealed_dispatch",
        lambda preflight, adapter_factories_builder: (
            calls.append("execute") or _FakeReport()
        ),
    )
    status = cli_module.dispatch_main(
        _argv(tmp_path, execute=True),
        adapter_factories_builder=lambda _value: {"C1": object()},
    )

    assert status == 0
    assert calls == ["execute"]
    assert json.loads(capsys.readouterr().out)["remaining_count"] == 0


def test_cli_wires_default_production_builder_only_on_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan, freeze = _plan()
    policy = SealedDispatchPolicy.from_dict(POLICY_VALUE)
    preflight = _FakePreflight()
    events: list[object] = []
    monkeypatch.setattr(
        cli_module,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )
    monkeypatch.setattr(cli_module, "load_sealed_execution_plan", lambda *a, **k: plan)
    monkeypatch.setattr(cli_module, "load_sealed_public_questions", lambda *a, **k: {})
    monkeypatch.setattr(
        cli_module, "load_sealed_dispatch_policy", lambda *a, **k: policy
    )
    monkeypatch.setattr(
        cli_module, "preflight_sealed_dispatch", lambda **kwargs: preflight
    )
    monkeypatch.setattr(
        cli_module,
        "_production_config",
        lambda arguments: events.append("config") or "production-config",
    )
    monkeypatch.setattr(
        cli_module,
        "build_sealed_production_adapter_factories",
        lambda config, value: events.append((config, value)) or {"C1": object()},
    )

    def execute(value, *, adapter_factories_builder):  # type: ignore[no-untyped-def]
        events.append("execute")
        adapter_factories_builder(value)
        return _FakeReport()

    monkeypatch.setattr(cli_module, "execute_sealed_dispatch", execute)

    status = cli_module.dispatch_main(_argv(tmp_path, execute=True))

    assert status == 0
    assert events == [
        "config",
        "execute",
        ("production-config", preflight),
    ]
    assert json.loads(capsys.readouterr().out)["remaining_count"] == 0

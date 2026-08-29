from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.baseline_continuation_cli as continuation_cli
from omni_benchmark.baseline_batch import (
    BaselineBatchError,
    ImmutableAttemptRepository,
    apply_committed_direct_baseline_exclusions,
    direct_only_baseline_schedule,
    load_committed_baseline_schedule,
)
from omni_benchmark.baseline_continuation_cli import baseline_continuation_main
from omni_benchmark.baseline_continuation import (
    continuation_schedule,
    load_continuation_manifest,
)
from tests.test_baseline_batch import _commit_exclusion_manifest, _schedule_repo
from tests.test_baseline_continuation import _write_attempt


def _prepared_cli_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, str, Path, list[str]]:
    workspace, _ = _schedule_repo(tmp_path)
    commit = _commit_exclusion_manifest(workspace)
    run_id = "original-run"
    source = apply_committed_direct_baseline_exclusions(
        workspace,
        commit,
        direct_only_baseline_schedule(
            load_committed_baseline_schedule(workspace, commit, run_id=run_id)
        ),
    )
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/original-run")
    )
    _write_attempt(
        repository,
        source.attempts[0],
        outcome="answered",
        failure_class=None,
        failure_origin=None,
        started_at="2026-08-28T18:00:00Z",
        finished_at="2026-08-28T18:00:01Z",
        manifest_commit=commit,
    )
    _write_attempt(
        repository,
        source.attempts[1],
        outcome="errored",
        failure_class="model_setup_error",
        failure_origin="evaluated_system",
        started_at="2026-08-28T18:20:44Z",
        finished_at="2026-08-28T18:20:46.5Z",
        manifest_commit=commit,
    )
    manifest = tmp_path / "continuation.json"
    monkeypatch.setattr(continuation_cli, "AUTHORIZED_SYSTEM_COMMIT", commit)
    monkeypatch.setattr(continuation_cli, "AUTHORIZED_ORIGINAL_RUN_ID", run_id)
    monkeypatch.setattr(
        continuation_cli,
        "AUTHORIZED_ORIGINAL_OUTPUT_ROOT",
        Path("experiments/autoresearch/raw/original-run"),
    )
    monkeypatch.setattr(
        continuation_cli, "AUTHORIZED_CONTINUATION_RUN_ID", "continuation-run"
    )
    monkeypatch.setattr(
        continuation_cli,
        "AUTHORIZED_CONTINUATION_OUTPUT_ROOT",
        Path("experiments/autoresearch/raw/continuation-run"),
    )
    monkeypatch.setattr(
        continuation_cli, "AUTHORIZED_AUTHORIZATION_ID", "authorized-incident"
    )
    monkeypatch.setattr(
        continuation_cli, "AUTHORIZED_INCIDENT_START", "2026-08-28T18:20:46Z"
    )
    monkeypatch.setattr(
        continuation_cli, "AUTHORIZED_INCIDENT_END", "2026-08-28T18:26:20Z"
    )
    monkeypatch.setattr(continuation_cli, "AUTHORIZED_INVALIDATED_ATTEMPTS", 1)
    prepare = [
        "prepare",
        "--source-workspace",
        str(workspace),
        "--system-commit",
        commit,
        "--original-run-id",
        run_id,
        "--original-output-root",
        "experiments/autoresearch/raw/original-run",
        "--continuation-run-id",
        "continuation-run",
        "--manifest-output",
        str(manifest),
        "--authorization-id",
        "authorized-incident",
        "--incident-finished-start",
        "2026-08-28T18:20:46Z",
        "--incident-finished-end",
        "2026-08-28T18:26:20Z",
        "--expected-invalidated-attempts",
        "1",
    ]
    return workspace, commit, manifest, prepare


def _execution_arguments(
    workspace: Path, commit: str, manifest: Path, digest: str, command: str
) -> list[str]:
    return [
        command,
        "--source-workspace",
        str(workspace),
        "--system-commit",
        commit,
        "--original-run-id",
        "original-run",
        "--original-output-root",
        "experiments/autoresearch/raw/original-run",
        "--execution-workspace",
        str(workspace),
        "--continuation-output-root",
        "experiments/autoresearch/raw/continuation-run",
        "--manifest",
        str(manifest),
        "--manifest-sha256",
        digest,
    ]


def _planning_arguments(tmp_path: Path) -> list[str]:
    return [
        "--freeze-a-commit",
        "d" * 40,
        "--claude-config-dir",
        str(tmp_path / "profile-1"),
        "--claude-config-dir",
        str(tmp_path / "profile-2"),
        "--claude-config-dir",
        str(tmp_path / "profile-3"),
        "--database-environment-dir",
        str(tmp_path / "database-envs"),
        "--observed-condition-cost",
        "C1=1.0",
        "--observed-condition-cost",
        "C2=1.1",
        "--observed-condition-cost",
        "C3=1.2",
        "--cost-ceiling-usd",
        "2000",
        "--attempt-cost-ceiling-usd",
        "12",
    ]


def test_prepare_plan_and_reconcile_cover_the_committed_continuation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, commit, manifest, prepare = _prepared_cli_case(tmp_path, monkeypatch)

    assert baseline_continuation_main(prepare) == 0
    prepared = json.loads(capsys.readouterr().out)
    assert prepared["counts"] == {
        "never_attempted": 628,
        "preserved": 1,
        "rerun_infrastructure": 1,
        "source_schedule": 630,
    }
    digest = prepared["continuation_manifest_sha256"]
    monkeypatch.setattr(continuation_cli, "AUTHORIZED_MANIFEST_SHA256", digest)

    plan_arguments = _execution_arguments(
        workspace, commit, manifest, digest, "plan"
    ) + _planning_arguments(tmp_path)
    assert baseline_continuation_main(plan_arguments) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["execution_plan"]["attempt_count"] == 629
    assert plan["reconciliation_before_run"]["preserved_attempts"] == 1
    assert plan["live_execution"] == "not_started_pending_profile_validation"

    reconcile_arguments = _execution_arguments(
        workspace, commit, manifest, digest, "reconcile"
    )
    assert baseline_continuation_main(reconcile_arguments) == 0
    reconciliation = json.loads(capsys.readouterr().out)["reconciliation"]
    assert reconciliation["reconciled_trial_count"] == 1
    assert reconciliation["missing_continuation_attempts"] == 629


def test_execute_uses_the_verified_plan_and_reports_final_reconciliation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, commit, manifest, prepare = _prepared_cli_case(tmp_path, monkeypatch)
    baseline_continuation_main(prepare)
    digest = json.loads(capsys.readouterr().out)["continuation_manifest_sha256"]
    monkeypatch.setattr(continuation_cli, "AUTHORIZED_MANIFEST_SHA256", digest)
    reports = iter(
        (
            SimpleNamespace(as_dict=lambda: {"complete": False}),
            SimpleNamespace(as_dict=lambda: {"complete": True}),
        )
    )
    monkeypatch.setattr(
        continuation_cli,
        "reconcile_continuation",
        lambda *args, **kwargs: next(reports),
    )
    monkeypatch.setattr(
        continuation_cli,
        "DatabaseEnvironmentDirectory",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        continuation_cli,
        "LiveBaselineDispatcher",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    batch_report = SimpleNamespace(as_dict=lambda: {"status": "complete"})
    monkeypatch.setattr(
        continuation_cli, "run_baseline_batch", lambda *args, **kwargs: batch_report
    )
    execute_arguments = _execution_arguments(
        workspace, commit, manifest, digest, "execute"
    ) + _planning_arguments(tmp_path)

    assert baseline_continuation_main(execute_arguments) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["live_execution"] == {"status": "complete"}
    assert output["reconciliation_after_run"] == {"complete": True}
    assert len(output["execution_plan_sha256"]) == 64


def test_freeze_cli_writes_exact_complete_authorized_selection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, commit, manifest_path, prepare = _prepared_cli_case(
        tmp_path, monkeypatch
    )
    baseline_continuation_main(prepare)
    digest = json.loads(capsys.readouterr().out)["continuation_manifest_sha256"]
    monkeypatch.setattr(continuation_cli, "AUTHORIZED_MANIFEST_SHA256", digest)
    source = apply_committed_direct_baseline_exclusions(
        workspace,
        commit,
        direct_only_baseline_schedule(
            load_committed_baseline_schedule(workspace, commit, run_id="original-run")
        ),
    )
    manifest = load_continuation_manifest(manifest_path, expected_sha256=digest)
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/continuation-run")
    )
    for attempt in continuation_schedule(source, manifest).attempts:
        _write_attempt(
            repository,
            attempt,
            outcome="answered",
            failure_class=None,
            failure_origin=None,
            started_at="2026-08-28T19:00:00Z",
            finished_at="2026-08-28T19:00:01Z",
            manifest_commit=commit,
        )
    freeze_relative = Path(
        "experiments/autoresearch/state/public-direct-baseline-freeze-v1.json"
    )
    freeze_path = workspace / freeze_relative
    arguments = _execution_arguments(
        workspace, commit, manifest_path, digest, "freeze"
    ) + ["--freeze-output", str(freeze_relative)]

    assert baseline_continuation_main(arguments) == 0

    output = json.loads(capsys.readouterr().out)
    frozen = json.loads(freeze_path.read_bytes())
    assert (
        output["baseline_freeze_sha256"]
        == hashlib.sha256(freeze_path.read_bytes()).hexdigest()
    )
    assert output["counts"] == {"continuation": 629, "preserved": 1, "total": 630}
    assert len(frozen["entries"]) == 630
    assert freeze_path.stat().st_mode & 0o777 == 0o600


def test_freeze_cli_rejects_a_replacement_output_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, commit, manifest, prepare = _prepared_cli_case(tmp_path, monkeypatch)
    baseline_continuation_main(prepare)
    digest = json.loads(capsys.readouterr().out)["continuation_manifest_sha256"]
    monkeypatch.setattr(continuation_cli, "AUTHORIZED_MANIFEST_SHA256", digest)

    with pytest.raises(BaselineBatchError, match="freeze output"):
        baseline_continuation_main(
            _execution_arguments(workspace, commit, manifest, digest, "freeze")
            + ["--freeze-output", "experiments/autoresearch/state/replacement.json"]
        )


def test_plan_rejects_a_non_exact_execution_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, commit, manifest, prepare = _prepared_cli_case(tmp_path, monkeypatch)
    baseline_continuation_main(prepare)
    digest = json.loads(capsys.readouterr().out)["continuation_manifest_sha256"]
    monkeypatch.setattr(continuation_cli, "AUTHORIZED_MANIFEST_SHA256", digest)
    (workspace / "change.txt").write_text("new commit\n")
    subprocess.run(("git", "-C", str(workspace), "add", "change.txt"), check=True)
    subprocess.run(
        ("git", "-C", str(workspace), "commit", "-qm", "change head"), check=True
    )

    with pytest.raises(BaselineBatchError, match="exact clean system commit"):
        baseline_continuation_main(
            _execution_arguments(workspace, commit, manifest, digest, "reconcile")
        )


def test_prepare_rejects_a_caller_selected_incident_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, prepare = _prepared_cli_case(tmp_path, monkeypatch)
    end_index = prepare.index("--incident-finished-end") + 1
    prepare[end_index] = "2026-08-28T18:27:20Z"

    with pytest.raises(BaselineBatchError, match="outside the authorized"):
        baseline_continuation_main(prepare)

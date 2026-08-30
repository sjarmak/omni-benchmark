from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

import omni_benchmark.c4_baseline_freeze as freeze_module
from omni_benchmark.baseline_batch import BaselineAttempt, BaselineSchedule
from omni_benchmark.c4_baseline_freeze import (
    C4BaselineFreezeError,
    c4_baseline_freeze_main,
    freeze_c4_baseline_selection,
)
from omni_benchmark.run_manifest import RunManifest


COMMIT = "a" * 40
DIGEST = "b" * 64
TEST_RUN_ID = "public-c4-baseline-freeze-test"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "experiments/autoresearch/raw").mkdir(parents=True)
    (workspace / "experiments/autoresearch/state").mkdir(parents=True)
    (workspace / ".gitignore").write_text("experiments/autoresearch/\n")
    return workspace


def _schedule(
    run_id: str = TEST_RUN_ID, *, attempts: int = 2, databases: int = 2
) -> BaselineSchedule:
    selected = tuple(
        BaselineAttempt(
            condition="C4",
            database=f"database_{index % databases}",
            instance_id=f"question_{index}",
            repetition=1,
            run_id=run_id,
        )
        for index in range(attempts)
    )
    return BaselineSchedule(
        attempts=selected,
        eligible_manifest_sha256="c" * 64,
        source_commit=COMMIT,
        train_ids_sha256="d" * 64,
        scheduled_attempts=selected,
        scorer_conformance_manifest_sha256="1" * 64,
    )


def _production_frame(run_id: str = TEST_RUN_ID) -> BaselineSchedule:
    scheduled = tuple(
        BaselineAttempt(
            condition="C4",
            database=(
                "database_00"
                if index < 9
                else "database_01"
                if index < 18
                else f"database_{2 + ((index - 18) % 16):02d}"
            ),
            instance_id=f"question_{index:03d}",
            repetition=1,
            run_id=run_id,
        )
        for index in range(154)
    )
    return BaselineSchedule(
        attempts=scheduled[18:],
        eligible_manifest_sha256="c" * 64,
        source_commit=COMMIT,
        train_ids_sha256="d" * 64,
        scheduled_attempts=scheduled,
        scorer_conformance_manifest_sha256="1" * 64,
    )


def _write_attempt(
    workspace: Path,
    output_root: Path,
    attempt: BaselineAttempt,
    *,
    outcome: str = "answered",
    failure: str | None = None,
) -> None:
    root = (
        workspace / output_root / attempt.database / "c4" / f"{attempt.instance_id}-r1"
    )
    root.mkdir(parents=True, mode=0o700)
    current = workspace / output_root
    while current != root:
        current.chmod(0o700)
        relative = root.relative_to(current)
        current = current / relative.parts[0]
    root.chmod(0o700)
    record = {
        "attempt_id": attempt.attempt_id,
        "condition": "C4",
        "cost_usd": None,
        "cost_unavailable_reason": "omni_job_api_does_not_expose_cost",
        "database_query_count": 1,
        "generation_outcome": outcome,
        "instance_id": attempt.instance_id,
        "latency_ms": 10.0,
        "partition": "train",
        "repetition": 1,
        "retry_count": None,
        "run_id": attempt.run_id,
        "terminal_failure_class": failure,
        "token_usage": None,
        "tool_call_count": 1,
        "validation_attempt_count": 0,
    }
    generation = _canonical(record)
    manifest = RunManifest.from_dict(
        {
            "budget_id": "public-c4-v4",
            "cli_versions": {"omni": "1.1.2"},
            "condition": "C4",
            "controllable_seed": None,
            "finished_at": "2026-08-29T09:00:01Z",
            "generation_sha256": hashlib.sha256(generation).hexdigest(),
            "git_commit": COMMIT,
            "harness_config_sha256": DIGEST,
            "instructions_sha256": DIGEST,
            "model": "omni",
            "model_config_id": "public-c4",
            "prompt_sha256": DIGEST,
            "provider": "omni",
            "repetition": 1,
            "schema_version": 2,
            "scope": "train",
            "semantic_model_ref": f"public:{attempt.database}",
            "semantic_model_sha256": DIGEST,
            "software_versions": {"omni-benchmark": "0.1.0"},
            "started_at": "2026-08-29T09:00:00Z",
        },
        environment={},
    )
    files = {
        "attempt.trace.jsonl": _canonical({"event": "public-trace"}),
        "generation.jsonl": generation,
        "run.json": manifest.canonical_bytes(),
    }
    for name, content in files.items():
        path = root / name
        path.write_bytes(content)
        path.chmod(0o600)


def _freeze(workspace: Path, schedule: BaselineSchedule):
    output_root = Path(f"experiments/autoresearch/raw/{schedule.attempts[0].run_id}")
    destination = Path(
        f"experiments/autoresearch/state/{schedule.attempts[0].run_id}-freeze.json"
    )
    return freeze_c4_baseline_selection(
        workspace,
        schedule=schedule,
        output_root=output_root,
        destination=destination,
        expected_execution_plan_sha256="e" * 64,
        expected_deployment_sha256="f" * 64,
    )


def test_complete_c4_schedule_freezes_canonical_hash_bound_selection(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule()
    output_root = Path(f"experiments/autoresearch/raw/{TEST_RUN_ID}")
    _write_attempt(workspace, output_root, schedule.attempts[0])
    _write_attempt(
        workspace,
        output_root,
        schedule.attempts[1],
        outcome="refused",
        failure="agent_refusal",
    )

    receipt = _freeze(workspace, schedule)
    path = workspace / receipt["path"]
    content = path.read_bytes()
    manifest = json.loads(content)

    assert receipt == {
        "artifact_file_count": 6,
        "attempt_count": 2,
        "database_count": 2,
        "path": f"experiments/autoresearch/state/{TEST_RUN_ID}-freeze.json",
        "run_id": TEST_RUN_ID,
        "scheduled_attempt_count": 2,
        "selection_sha256": hashlib.sha256(content).hexdigest(),
        "source_schedule_sha256": schedule.sha256,
        "unscorable_attempt_count": 0,
    }
    assert manifest["kind"] == "public-c4-baseline-freeze"
    assert manifest["counts"] == {
        "answerable_attempts": 2,
        "answered": 1,
        "attempts": 2,
        "databases": 2,
        "errored": 0,
        "refused": 1,
        "scheduled_attempts": 2,
        "scheduled_databases": 2,
        "unscorable_attempts": 0,
    }
    assert [entry["attempt_id"] for entry in manifest["entries"]] == [
        attempt.attempt_id for attempt in schedule.attempts
    ]
    assert all(entry["condition"] == "C4" for entry in manifest["entries"])
    assert manifest["execution_plan_sha256"] == "e" * 64
    assert manifest["deployment_sha256"] == "f" * 64
    assert manifest["scorer_conformance_manifest_sha256"] == "1" * 64
    assert manifest["scheduled_entries"] == [
        {
            "attempt_id": attempt.attempt_id,
            "condition": "C4",
            "database": attempt.database,
            "instance_id": attempt.instance_id,
            "repetition": 1,
        }
        for attempt in schedule.scheduled_attempts
    ]
    assert content == _canonical(manifest)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_freeze_refuses_incomplete_schedule_without_writing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule()
    _write_attempt(
        workspace,
        Path(f"experiments/autoresearch/raw/{TEST_RUN_ID}"),
        schedule.attempts[0],
    )

    with pytest.raises(C4BaselineFreezeError, match="incomplete"):
        _freeze(workspace, schedule)

    assert not (
        workspace / f"experiments/autoresearch/state/{TEST_RUN_ID}-freeze.json"
    ).exists()


def test_freeze_inventories_preserved_scheduled_attempt_diagnostic(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule()
    output_root = Path(f"experiments/autoresearch/raw/{TEST_RUN_ID}")
    for attempt in schedule.attempts:
        _write_attempt(workspace, output_root, attempt)
    diagnostic = (
        workspace / output_root / "database_0/c4/.failed-question_0-r1-0123456789abcdef"
    )
    diagnostic.mkdir(mode=0o700)
    failure = diagnostic / "failure.json"
    failure.write_text('{"attempt_id":"diagnostic"}\n')
    failure.chmod(0o600)

    receipt = _freeze(workspace, schedule)

    assert receipt["artifact_file_count"] == 7


def test_freeze_refuses_unexpected_or_symlinked_artifact_tree(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule()
    output_root = Path(f"experiments/autoresearch/raw/{TEST_RUN_ID}")
    for attempt in schedule.attempts:
        _write_attempt(workspace, output_root, attempt)
    unexpected = (
        workspace
        / output_root
        / "database_0/c4/.failed-not-scheduled-r1-0123456789abcdef"
    )
    unexpected.mkdir(mode=0o700)
    failure = unexpected / "failure.json"
    failure.write_text("{}\n")
    failure.chmod(0o600)

    with pytest.raises(C4BaselineFreezeError, match="unexpected"):
        _freeze(workspace, schedule)

    unexpected.rename(workspace / "removed")
    os.symlink(
        "generation.jsonl",
        workspace / output_root / "database_0/c4/question_0-r1/copied-generation.jsonl",
    )
    with pytest.raises(C4BaselineFreezeError, match="unexpected|regular"):
        _freeze(workspace, schedule)


def test_freeze_refuses_quarantined_run_and_overwrite(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    quarantined = _schedule("public-c4-baseline-v3")
    with pytest.raises(C4BaselineFreezeError, match="quarantined"):
        _freeze(workspace, quarantined)

    schedule = _schedule()
    output_root = Path(f"experiments/autoresearch/raw/{TEST_RUN_ID}")
    for attempt in schedule.attempts:
        _write_attempt(workspace, output_root, attempt)
    _freeze(workspace, schedule)
    with pytest.raises(C4BaselineFreezeError, match="already exists"):
        _freeze(workspace, schedule)


def test_freeze_refuses_score_or_other_extra_artifact(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule()
    output_root = Path(f"experiments/autoresearch/raw/{TEST_RUN_ID}")
    for attempt in schedule.attempts:
        _write_attempt(workspace, output_root, attempt)
    score = workspace / output_root / "database_0/c4/question_0-r1/official.score.json"
    score.write_text('{"correctness":true}\n')
    score.chmod(0o600)

    with pytest.raises(C4BaselineFreezeError, match="unexpected file"):
        _freeze(workspace, schedule)


def test_cli_requires_exact_committed_154_scheduled_136_answerable_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    schedule = _production_frame()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        freeze_module,
        "load_committed_baseline_schedule",
        lambda *args, **kwargs: schedule,
    )
    monkeypatch.setattr(
        freeze_module, "c4_dev_a_experiment_schedule", lambda *args, **kwargs: schedule
    )

    def fake_freeze(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {"attempt_count": 136, "selection_sha256": "9" * 64}

    monkeypatch.setattr(freeze_module, "freeze_c4_baseline_selection", fake_freeze)
    arguments = [
        "--workspace",
        str(workspace),
        "--system-commit",
        COMMIT,
        "--run-id",
        TEST_RUN_ID,
        "--output-root",
        f"experiments/autoresearch/raw/{TEST_RUN_ID}",
        "--destination",
        f"experiments/autoresearch/state/{TEST_RUN_ID}-freeze.json",
        "--expected-schedule-sha256",
        schedule.sha256,
        "--expected-execution-plan-sha256",
        "e" * 64,
        "--expected-deployment-sha256",
        "f" * 64,
    ]

    assert c4_baseline_freeze_main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {
        "attempt_count": 136,
        "selection_sha256": "9" * 64,
    }
    assert captured["schedule"] is schedule

    arguments[arguments.index(schedule.sha256)] = "0" * 64
    with pytest.raises(C4BaselineFreezeError, match="schedule identity"):
        c4_baseline_freeze_main(arguments)


def test_cli_freezes_exact_154_scheduled_136_answerable_e02_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    schedule = _production_frame("e02-dev-a-v1")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        freeze_module,
        "load_committed_baseline_schedule",
        lambda *args, **kwargs: schedule,
    )
    monkeypatch.setattr(
        freeze_module, "c4_dev_a_experiment_schedule", lambda *args: schedule
    )

    def fake_freeze(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {"attempt_count": 136, "selection_sha256": "9" * 64}

    monkeypatch.setattr(freeze_module, "freeze_c4_baseline_selection", fake_freeze)
    arguments = [
        "--workspace",
        str(workspace),
        "--system-commit",
        COMMIT,
        "--run-id",
        "e02-dev-a-v1",
        "--schedule-kind",
        "e02-dev-a",
        "--output-root",
        "experiments/autoresearch/raw/e02-dev-a-v1",
        "--destination",
        "experiments/autoresearch/state/e02-dev-a-v1-freeze.json",
        "--expected-schedule-sha256",
        schedule.sha256,
        "--expected-execution-plan-sha256",
        "e" * 64,
        "--expected-deployment-sha256",
        "f" * 64,
    ]

    assert c4_baseline_freeze_main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["attempt_count"] == 136
    assert captured["selection_kind"] == "e02-dev-a-c4-freeze"


def test_freeze_binds_all_scheduled_ids_without_executing_fixed_exclusions(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    schedule = _production_frame()
    output_root = Path(f"experiments/autoresearch/raw/{TEST_RUN_ID}")
    for attempt in schedule.attempts:
        _write_attempt(workspace, output_root, attempt)

    receipt = _freeze(workspace, schedule)
    manifest = json.loads((workspace / receipt["path"]).read_bytes())

    assert receipt["attempt_count"] == 136
    assert receipt["scheduled_attempt_count"] == 154
    assert receipt["unscorable_attempt_count"] == 18
    assert manifest["counts"] == {
        "answerable_attempts": 136,
        "answered": 136,
        "attempts": 136,
        "databases": 16,
        "errored": 0,
        "refused": 0,
        "scheduled_attempts": 154,
        "scheduled_databases": 18,
        "unscorable_attempts": 18,
    }
    assert len(manifest["scheduled_entries"]) == 154
    assert len(manifest["entries"]) == 136
    assert {item["instance_id"] for item in manifest["scheduled_entries"]} - {
        item["instance_id"] for item in manifest["entries"]
    } == {f"question_{index:03d}" for index in range(18)}

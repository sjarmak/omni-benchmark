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
    run_id: str = "public-c4-baseline-v4", *, attempts: int = 2, databases: int = 2
) -> BaselineSchedule:
    return BaselineSchedule(
        attempts=tuple(
            BaselineAttempt(
                condition="C4",
                database=f"database_{index % databases}",
                instance_id=f"question_{index}",
                repetition=1,
                run_id=run_id,
            )
            for index in range(attempts)
        ),
        eligible_manifest_sha256="c" * 64,
        source_commit=COMMIT,
        train_ids_sha256="d" * 64,
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
    output_root = Path("experiments/autoresearch/raw/public-c4-baseline-v4")
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
        "path": "experiments/autoresearch/state/public-c4-baseline-v4-freeze.json",
        "run_id": "public-c4-baseline-v4",
        "selection_sha256": hashlib.sha256(content).hexdigest(),
        "source_schedule_sha256": schedule.sha256,
    }
    assert manifest["kind"] == "public-c4-baseline-freeze"
    assert manifest["counts"] == {
        "answered": 1,
        "attempts": 2,
        "databases": 2,
        "errored": 0,
        "refused": 1,
    }
    assert [entry["attempt_id"] for entry in manifest["entries"]] == [
        attempt.attempt_id for attempt in schedule.attempts
    ]
    assert all(entry["condition"] == "C4" for entry in manifest["entries"])
    assert manifest["execution_plan_sha256"] == "e" * 64
    assert manifest["deployment_sha256"] == "f" * 64
    assert content == _canonical(manifest)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_freeze_refuses_incomplete_schedule_without_writing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule()
    _write_attempt(
        workspace,
        Path("experiments/autoresearch/raw/public-c4-baseline-v4"),
        schedule.attempts[0],
    )

    with pytest.raises(C4BaselineFreezeError, match="incomplete"):
        _freeze(workspace, schedule)

    assert not (
        workspace / "experiments/autoresearch/state/public-c4-baseline-v4-freeze.json"
    ).exists()


def test_freeze_refuses_unexpected_or_symlinked_artifact_tree(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule()
    output_root = Path("experiments/autoresearch/raw/public-c4-baseline-v4")
    for attempt in schedule.attempts:
        _write_attempt(workspace, output_root, attempt)
    unexpected = workspace / output_root / "database_0/c4/.failed-question_0-r1-x"
    unexpected.mkdir()
    (unexpected / "failure.json").write_text("{}\n")

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
    output_root = Path("experiments/autoresearch/raw/public-c4-baseline-v4")
    for attempt in schedule.attempts:
        _write_attempt(workspace, output_root, attempt)
    _freeze(workspace, schedule)
    with pytest.raises(C4BaselineFreezeError, match="already exists"):
        _freeze(workspace, schedule)


def test_freeze_refuses_score_or_other_extra_artifact(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule()
    output_root = Path("experiments/autoresearch/raw/public-c4-baseline-v4")
    for attempt in schedule.attempts:
        _write_attempt(workspace, output_root, attempt)
    score = workspace / output_root / "database_0/c4/question_0-r1/official.score.json"
    score.write_text('{"correctness":true}\n')
    score.chmod(0o600)

    with pytest.raises(C4BaselineFreezeError, match="unexpected file"):
        _freeze(workspace, schedule)


def test_cli_requires_exact_committed_129_attempt_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    schedule = _schedule(attempts=129, databases=10)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        freeze_module,
        "load_committed_baseline_schedule",
        lambda *args, **kwargs: schedule,
    )
    monkeypatch.setattr(
        freeze_module, "c4_public_baseline_schedule", lambda *args, **kwargs: schedule
    )

    def fake_freeze(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {"attempt_count": 129, "selection_sha256": "9" * 64}

    monkeypatch.setattr(freeze_module, "freeze_c4_baseline_selection", fake_freeze)
    arguments = [
        "--workspace",
        str(workspace),
        "--system-commit",
        COMMIT,
        "--run-id",
        "public-c4-baseline-v4",
        "--output-root",
        "experiments/autoresearch/raw/public-c4-baseline-v4",
        "--destination",
        "experiments/autoresearch/state/public-c4-baseline-v4-freeze.json",
        "--expected-schedule-sha256",
        schedule.sha256,
        "--expected-execution-plan-sha256",
        "e" * 64,
        "--expected-deployment-sha256",
        "f" * 64,
    ]

    assert c4_baseline_freeze_main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {
        "attempt_count": 129,
        "selection_sha256": "9" * 64,
    }
    assert captured["schedule"] is schedule

    arguments[arguments.index(schedule.sha256)] = "0" * 64
    with pytest.raises(C4BaselineFreezeError, match="schedule identity"):
        c4_baseline_freeze_main(arguments)

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from omni_benchmark.freeze_b import FreezeBManifest
from omni_benchmark.freeze_b_record import (
    FreezeBRecordError,
    record_freeze_b,
    record_main,
)


RECORDED_AT = "2026-08-29T06:00:00Z"


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _schedule() -> list[dict[str, object]]:
    return [
        {
            "attempt_id": f"sealed:q-{question:03d}:{condition}:{repetition}",
            "condition": condition,
            "instance_id": f"q-{question:03d}",
            "repetition": repetition,
        }
        for question in range(1, 102)
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    ]


def _condition(condition: str) -> dict[str, object]:
    semantic_path = {
        "C1": None,
        "C2": None,
        "C3": "models/c3-export.json",
        "C4": "models/c4-export.json",
    }[condition]
    return {
        "budget_id": "sealed-default-v1",
        "condition": condition,
        "harness_config_path": f"config/conditions/{condition.lower()}.json",
        "instructions_path": "config/final-instructions.txt",
        "model": "managed-standard",
        "model_config_id": "frozen-final-v1",
        "prompt_path": "config/final-prompt.txt",
        "provider": "aws-bedrock",
        "runtime_policy_path": "config/final-runtime-policy.json",
        "semantic_model_path": semantic_path,
        "semantic_model_ref": "none" if semantic_path is None else semantic_path,
    }


def _spec(paths: list[str], freeze_a_commit: str) -> dict[str, object]:
    return {
        "conditions": [_condition(condition) for condition in ("C1", "C2", "C3", "C4")],
        "database": {
            "libpq_version": "18.6",
            "postgresql_version": "18.6",
            "snapshot_manifest_path": "data/database-snapshot.json",
        },
        "freeze_a_commit": freeze_a_commit,
        "frozen_files": paths,
        "kind": "freeze-b-input",
        "schedule": {
            "algorithm": "committed_block_interleaved_v1",
            "path": "data/final-schedule.jsonl",
            "seed": "human-approved-seed-v1",
        },
        "schema_version": 1,
    }


def _repository(tmp_path: Path) -> tuple[Path, str, bytes]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Freeze Test")
    _git(repo, "config", "user.email", "freeze@example.invalid")
    (repo / "bootstrap.txt").write_text("freeze-a\n", encoding="utf-8")
    _git(repo, "add", "bootstrap.txt")
    _git(repo, "commit", "-qm", "freeze a")
    freeze_a_commit = _git(repo, "rev-parse", "HEAD")

    files = {
        "config/conditions/c1.json": b'{"condition":"C1"}\n',
        "config/conditions/c2.json": b'{"condition":"C2"}\n',
        "config/conditions/c3.json": b'{"condition":"C3"}\n',
        "config/conditions/c4.json": b'{"condition":"C4"}\n',
        "config/final-instructions.txt": b"Answer with governed SQL.\n",
        "config/final-prompt.txt": b"Final benchmark prompt.\n",
        "config/final-runtime-policy.json": b'{"retries":0}\n',
        "data/database-snapshot.json": b'{"snapshot":"public-v1"}\n',
        "models/c3-export.json": b'{"model":"c3"}\n',
        "models/c4-export.json": b'{"model":"c4"}\n',
    }
    project = Path(__file__).parents[1]
    for relative in (
        "src/omni_benchmark/autoresearch_config.py",
        "src/omni_benchmark/content_policy.py",
        "src/omni_benchmark/freeze_b.py",
        "src/omni_benchmark/freeze_b_record.py",
        "src/omni_benchmark/scoring.py",
    ):
        files[relative] = (project / relative).read_bytes()
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    schedule_bytes = b"".join(
        json.dumps(record, separators=(",", ":"), sort_keys=True).encode() + b"\n"
        for record in _schedule()
    )
    schedule_path = repo / "data/final-schedule.jsonl"
    schedule_path.write_bytes(schedule_bytes)
    frozen_paths = sorted(
        [*files, "data/final-schedule.jsonl", "config/freeze-b-input.json"]
    )
    spec_path = repo / "config/freeze-b-input.json"
    spec_path.write_text(
        json.dumps(_spec(frozen_paths, freeze_a_commit), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "system freeze inputs")
    return repo, _git(repo, "rev-parse", "HEAD"), files["config/conditions/c1.json"]


def test_record_uses_exact_commit_and_writes_canonical_mode_0600(
    tmp_path: Path,
) -> None:
    repo, commit, committed_c1 = _repository(tmp_path)
    (repo / "config/conditions/c1.json").write_text(
        '{"condition":"substituted"}\n', encoding="utf-8"
    )
    destination = repo / "experiments/freeze-b.json"
    destination.parent.mkdir()

    result = record_freeze_b(
        repo,
        system_commit=commit,
        input_spec_path=Path("config/freeze-b-input.json"),
        recorded_at=RECORDED_AT,
        destination=Path("experiments/freeze-b.json"),
    )

    manifest = FreezeBManifest.from_dict(json.loads(destination.read_text()))
    assert result.manifest == manifest
    assert result.schedule_attempt_count == 1_212
    assert result.frozen_file_count == 17
    assert (
        dict(manifest.frozen_files)["config/conditions/c1.json"]
        == hashlib.sha256(committed_c1).hexdigest()
    )
    assert manifest.system_commit == commit
    assert destination.read_bytes() == manifest.canonical_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


def test_record_refuses_overwrite_and_abbreviated_or_non_head_commit(
    tmp_path: Path,
) -> None:
    repo, commit, _ = _repository(tmp_path)
    destination = repo / "experiments/freeze-b.json"
    destination.parent.mkdir()
    destination.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FreezeBRecordError, match="already exists"):
        record_freeze_b(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/freeze-b.json"),
        )
    with pytest.raises(FreezeBRecordError, match="full lowercase commit"):
        record_freeze_b(
            repo,
            system_commit=commit[:12],
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/new-freeze-b.json"),
        )
    with pytest.raises(FreezeBRecordError, match="current HEAD"):
        record_freeze_b(
            repo,
            system_commit=_git(repo, "rev-parse", "HEAD^"),
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/new-freeze-b.json"),
        )


@pytest.mark.parametrize("case", ["missing", "unsafe", "symlink"])
def test_record_rejects_non_committed_or_unsafe_frozen_file(
    tmp_path: Path, case: str
) -> None:
    repo, _, _ = _repository(tmp_path)
    spec_path = repo / "config/freeze-b-input.json"
    spec = json.loads(spec_path.read_text())
    if case == "missing":
        spec["frozen_files"].append("config/not-committed.json")
    elif case == "unsafe":
        spec["frozen_files"].append("../outside.json")
    else:
        target = repo / "config/target.json"
        target.write_text("{}\n", encoding="utf-8")
        link = repo / "config/link.json"
        link.symlink_to(target.name)
        spec["frozen_files"].append("config/link.json")
        _git(repo, "add", "config/target.json", "config/link.json")
    spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    _git(repo, "add", "config/freeze-b-input.json")
    _git(repo, "commit", "-qm", f"invalid {case} input")
    commit = _git(repo, "rev-parse", "HEAD")
    destination = repo / "experiments/freeze-b.json"
    destination.parent.mkdir()

    with pytest.raises(FreezeBRecordError, match="committed regular file|path"):
        record_freeze_b(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/freeze-b.json"),
        )


@pytest.mark.parametrize("case", ["missing_attempt", "duplicate", "wrong_identity"])
def test_record_rejects_an_incomplete_or_inconsistent_schedule(
    tmp_path: Path, case: str
) -> None:
    repo, _, _ = _repository(tmp_path)
    records = _schedule()
    if case == "missing_attempt":
        records.pop()
    elif case == "duplicate":
        records[-1] = records[0]
    else:
        records[-1]["instance_id"] = "q-100"
    schedule_path = repo / "data/final-schedule.jsonl"
    schedule_path.write_bytes(
        b"".join(
            json.dumps(record, separators=(",", ":"), sort_keys=True).encode() + b"\n"
            for record in records
        )
    )
    _git(repo, "add", "data/final-schedule.jsonl")
    _git(repo, "commit", "-qm", f"invalid {case} schedule")
    commit = _git(repo, "rev-parse", "HEAD")
    destination = repo / "experiments/freeze-b.json"
    destination.parent.mkdir()

    with pytest.raises(FreezeBRecordError, match="schedule"):
        record_freeze_b(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/freeze-b.json"),
        )


@pytest.mark.parametrize(
    "case",
    [
        "extra_field",
        "boolean_version",
        "missing_reference",
        "missing_input_spec",
        "wrong_algorithm",
        "missing_schedule",
        "missing_snapshot",
    ],
)
def test_record_rejects_noncanonical_or_incomplete_input_spec(
    tmp_path: Path, case: str
) -> None:
    repo, _, _ = _repository(tmp_path)
    spec_path = repo / "config/freeze-b-input.json"
    spec = json.loads(spec_path.read_text())
    if case == "extra_field":
        spec["unexpected"] = True
        message = "exact schema"
    elif case == "boolean_version":
        spec["schema_version"] = True
        message = "schema_version"
    elif case == "missing_reference":
        spec["frozen_files"].remove("models/c3-export.json")
        message = "condition provenance"
    elif case == "missing_input_spec":
        spec["frozen_files"].remove("config/freeze-b-input.json")
        message = "input spec path"
    elif case == "wrong_algorithm":
        spec["schedule"]["algorithm"] = "unregistered"
        message = "schedule algorithm"
    elif case == "missing_schedule":
        spec["frozen_files"].remove("data/final-schedule.jsonl")
        message = "schedule path"
    else:
        spec["frozen_files"].remove("data/database-snapshot.json")
        message = "database snapshot"
    spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")
    _git(repo, "add", "config/freeze-b-input.json")
    _git(repo, "commit", "-qm", f"invalid {case} spec")
    commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(FreezeBRecordError, match=message):
        record_freeze_b(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/freeze-b.json"),
        )


def test_record_rejects_symlinked_destination_parent(tmp_path: Path) -> None:
    repo, commit, _ = _repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "experiments").symlink_to(outside, target_is_directory=True)

    with pytest.raises(FreezeBRecordError, match="artifact parent"):
        record_freeze_b(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/freeze-b.json"),
        )

    assert not (outside / "freeze-b.json").exists()


def test_record_ignores_git_environment_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit, _ = _repository(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _git(unrelated, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(unrelated / ".git"))

    result = record_freeze_b(
        repo,
        system_commit=commit,
        input_spec_path=Path("config/freeze-b-input.json"),
        recorded_at=RECORDED_AT,
        destination=Path("experiments/freeze-b.json"),
    )

    assert result.manifest.system_commit == commit


def test_record_rejects_runtime_source_not_bound_to_system_commit(
    tmp_path: Path,
) -> None:
    repo, _, _ = _repository(tmp_path)
    source = repo / "src/omni_benchmark/scoring.py"
    source.write_text("# substituted scorer source\n", encoding="utf-8")
    _git(repo, "add", "src/omni_benchmark/scoring.py")
    _git(repo, "commit", "-qm", "substitute scorer source")
    commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(FreezeBRecordError, match="runtime source"):
        record_freeze_b(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/freeze-b.json"),
        )


def test_record_rejects_workspace_reached_through_symlink(tmp_path: Path) -> None:
    repo, commit, _ = _repository(tmp_path)
    linked = tmp_path / "linked-repo"
    linked.symlink_to(repo, target_is_directory=True)

    with pytest.raises(FreezeBRecordError, match="non-symlink"):
        record_freeze_b(
            linked,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            recorded_at=RECORDED_AT,
            destination=Path("experiments/freeze-b.json"),
        )


def test_cli_prints_only_public_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, commit, _ = _repository(tmp_path)
    (repo / "experiments").mkdir()

    status = record_main(
        [
            "--workspace",
            str(repo),
            "--system-commit",
            commit,
            "--input-spec",
            "config/freeze-b-input.json",
            "--recorded-at",
            RECORDED_AT,
            "--destination",
            "experiments/freeze-b.json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert status == 0
    assert set(output) == {
        "freeze_b_sha256",
        "frozen_file_count",
        "schedule_attempt_count",
        "system_commit",
    }
    assert "seed" not in json.dumps(output)


def test_script_entrypoint_records_the_same_public_summary(tmp_path: Path) -> None:
    repo, commit, _ = _repository(tmp_path)
    project = Path(__file__).parents[1]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(project / "sealed_tools/record_freeze_b.py"),
            "--workspace",
            str(repo),
            "--system-commit",
            commit,
            "--input-spec",
            "config/freeze-b-input.json",
            "--recorded-at",
            RECORDED_AT,
            "--destination",
            "experiments/freeze-b.json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    output = json.loads(completed.stdout)
    assert output["schedule_attempt_count"] == 1_212
    assert output["frozen_file_count"] == 17
    assert output["system_commit"] == commit
    assert completed.stderr == ""

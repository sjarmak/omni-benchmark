from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

from omni_benchmark.freeze_b import CONDITIONS, REPETITIONS, schedule_sha256
from omni_benchmark.freeze_b_schedule import (
    MIN_REPETITION_BLOCK_GAP,
    FreezeBScheduleError,
    generate_freeze_b_schedule,
    schedule_main,
)


SEED = "human-supplied-schedule-seed-v1"


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _test_ids(count: int = 101) -> bytes:
    return "".join(f"q-{index:03d}\n" for index in range(1, count + 1)).encode()


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Schedule Test")
    _git(repo, "config", "user.email", "schedule@example.invalid")
    project = Path(__file__).parents[1]
    files = {
        "data/manifests/test_ids.txt": _test_ids(),
        **{
            relative: (project / relative).read_bytes()
            for relative in (
                "src/omni_benchmark/autoresearch_config.py",
                "src/omni_benchmark/content_policy.py",
                "src/omni_benchmark/freeze_b.py",
                "src/omni_benchmark/freeze_b_record.py",
                "src/omni_benchmark/freeze_b_schedule.py",
                "src/omni_benchmark/scoring.py",
            )
        },
    }
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "committed sealed schedule inputs")
    return repo, _git(repo, "rev-parse", "HEAD")


def _records(path: Path) -> list[dict[str, object]]:
    content = path.read_bytes()
    assert content.endswith(b"\n")
    return [json.loads(line) for line in content.splitlines()]


def test_schedule_is_complete_canonical_separated_and_commit_derived(
    tmp_path: Path,
) -> None:
    repo, commit = _repository(tmp_path)
    committed_ids_sha256 = hashlib.sha256(_test_ids()).hexdigest()
    (repo / "data/manifests/test_ids.txt").write_bytes(_test_ids(100))

    result = generate_freeze_b_schedule(
        repo,
        system_commit=commit,
        seed=SEED,
        destination=Path("experiments/final-schedule.jsonl"),
    )

    records = _records(result.path)
    assert len(records) == 1_212
    assert result.attempt_count == 1_212
    assert result.question_count == 101
    assert result.test_ids_sha256 == committed_ids_sha256
    assert result.schedule_sha256 == schedule_sha256(
        tuple(str(record["attempt_id"]) for record in records)
    )
    assert result.file_sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()
    assert stat.S_IMODE(result.path.stat().st_mode) == 0o600
    assert Counter(str(record["condition"]) for record in records) == {
        condition: 303 for condition in CONDITIONS
    }
    assert Counter(int(record["repetition"]) for record in records) == {
        repetition: 404 for repetition in range(1, REPETITIONS + 1)
    }
    combinations = Counter(
        (
            str(record["instance_id"]),
            str(record["condition"]),
            int(record["repetition"]),
        )
        for record in records
    )
    assert len(combinations) == 1_212
    assert set(combinations.values()) == {1}
    assert len({str(record["attempt_id"]) for record in records}) == 1_212
    for raw_line, record in zip(
        result.path.read_bytes().splitlines(keepends=True), records, strict=True
    ):
        assert (
            raw_line
            == (
                json.dumps(
                    record, ensure_ascii=False, separators=(",", ":"), sort_keys=True
                )
                + "\n"
            ).encode()
        )

    blocks = [records[index : index + len(CONDITIONS)] for index in range(0, 1_212, 4)]
    positions: dict[str, list[int]] = defaultdict(list)
    for position, block in enumerate(blocks):
        identities = {
            (str(record["instance_id"]), int(record["repetition"])) for record in block
        }
        assert len(identities) == 1
        assert {str(record["condition"]) for record in block} == set(CONDITIONS)
        instance_id, _ = identities.pop()
        positions[instance_id].append(position)
    assert (
        min(
            right - left
            for question_positions in positions.values()
            for left, right in zip(question_positions, question_positions[1:])
        )
        >= MIN_REPETITION_BLOCK_GAP
    )


def test_same_seed_is_reproducible_and_different_seed_changes_order(
    tmp_path: Path,
) -> None:
    repo, commit = _repository(tmp_path)

    first = generate_freeze_b_schedule(
        repo,
        system_commit=commit,
        seed=SEED,
        destination=Path("experiments/first.jsonl"),
    )
    second = generate_freeze_b_schedule(
        repo,
        system_commit=commit,
        seed=SEED,
        destination=Path("experiments/second.jsonl"),
    )
    different = generate_freeze_b_schedule(
        repo,
        system_commit=commit,
        seed="another-human-seed-v1",
        destination=Path("experiments/different.jsonl"),
    )

    assert first.path.read_bytes() == second.path.read_bytes()
    assert first.schedule_sha256 == second.schedule_sha256
    assert different.path.read_bytes() != first.path.read_bytes()
    assert different.schedule_sha256 != first.schedule_sha256


def test_schedule_refuses_overwrite_abbreviation_and_stale_commit(
    tmp_path: Path,
) -> None:
    repo, commit = _repository(tmp_path)
    destination = repo / "experiments/final.jsonl"
    destination.parent.mkdir()
    destination.write_text("existing\n", encoding="utf-8")

    with pytest.raises(FreezeBScheduleError, match="already exists"):
        generate_freeze_b_schedule(
            repo,
            system_commit=commit,
            seed=SEED,
            destination=Path("experiments/final.jsonl"),
        )
    with pytest.raises(FreezeBScheduleError, match="full lowercase commit"):
        generate_freeze_b_schedule(
            repo,
            system_commit=commit[:12],
            seed=SEED,
            destination=Path("experiments/abbreviated.jsonl"),
        )
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-qm", "later")
    with pytest.raises(FreezeBScheduleError, match="current HEAD"):
        generate_freeze_b_schedule(
            repo,
            system_commit=commit,
            seed=SEED,
            destination=Path("experiments/stale.jsonl"),
        )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (_test_ids(100), "exactly 101"),
        (_test_ids(100) + b"q-100\n", "duplicate"),
        (_test_ids(100) + b"not allowed\n", "invalid"),
        (_test_ids()[:-1], "newline-terminated"),
        (b"q-002\nq-001\n" + _test_ids()[12:], "sorted"),
        (_test_ids().replace(b"\n", b"\r\n"), "invalid"),
    ],
)
def test_schedule_rejects_noncanonical_committed_test_ids(
    tmp_path: Path, content: bytes, message: str
) -> None:
    repo, _ = _repository(tmp_path)
    (repo / "data/manifests/test_ids.txt").write_bytes(content)
    _git(repo, "add", "data/manifests/test_ids.txt")
    _git(repo, "commit", "-qm", "invalid test identity manifest")
    commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(FreezeBScheduleError, match=message):
        generate_freeze_b_schedule(
            repo,
            system_commit=commit,
            seed=SEED,
            destination=Path("experiments/final.jsonl"),
        )


def test_schedule_rejects_git_symlink_for_test_ids(tmp_path: Path) -> None:
    repo, _ = _repository(tmp_path)
    ids = repo / "data/manifests/test_ids.txt"
    ids.unlink()
    (repo / "data/manifests/other.txt").write_bytes(_test_ids())
    ids.symlink_to("other.txt")
    _git(repo, "add", "data/manifests/test_ids.txt", "data/manifests/other.txt")
    _git(repo, "commit", "-qm", "symlink test identities")
    commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(FreezeBScheduleError, match="committed regular file"):
        generate_freeze_b_schedule(
            repo,
            system_commit=commit,
            seed=SEED,
            destination=Path("experiments/final.jsonl"),
        )


def test_schedule_rejects_bad_seed_unsafe_destination_and_symlink_parent(
    tmp_path: Path,
) -> None:
    repo, commit = _repository(tmp_path)

    with pytest.raises(FreezeBScheduleError, match="seed"):
        generate_freeze_b_schedule(
            repo,
            system_commit=commit,
            seed="",
            destination=Path("experiments/empty-seed.jsonl"),
        )
    with pytest.raises(FreezeBScheduleError, match="destination"):
        generate_freeze_b_schedule(
            repo,
            system_commit=commit,
            seed=SEED,
            destination=Path("../outside.jsonl"),
        )
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "experiments").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FreezeBScheduleError, match="artifact parent"):
        generate_freeze_b_schedule(
            repo,
            system_commit=commit,
            seed=SEED,
            destination=Path("experiments/final.jsonl"),
        )
    assert not (outside / "final.jsonl").exists()


def test_schedule_ignores_git_environment_and_binds_runtime_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, commit = _repository(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _git(unrelated, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(unrelated / ".git"))

    result = generate_freeze_b_schedule(
        repo,
        system_commit=commit,
        seed=SEED,
        destination=Path("experiments/final.jsonl"),
    )
    assert result.system_commit == commit
    monkeypatch.delenv("GIT_DIR")

    (repo / "src/omni_benchmark/freeze_b_schedule.py").write_text(
        "# substituted schedule generator\n", encoding="utf-8"
    )
    _git(repo, "add", "src/omni_benchmark/freeze_b_schedule.py")
    _git(repo, "commit", "-qm", "substitute schedule generator")
    new_commit = _git(repo, "rev-parse", "HEAD")
    with pytest.raises(FreezeBScheduleError, match="runtime source"):
        generate_freeze_b_schedule(
            repo,
            system_commit=new_commit,
            seed=SEED,
            destination=Path("experiments/after-substitution.jsonl"),
        )


def test_schedule_rejects_workspace_reached_through_symlink(tmp_path: Path) -> None:
    repo, commit = _repository(tmp_path)
    linked = tmp_path / "linked-repo"
    linked.symlink_to(repo, target_is_directory=True)

    with pytest.raises(FreezeBScheduleError, match="non-symlink"):
        generate_freeze_b_schedule(
            linked,
            system_commit=commit,
            seed=SEED,
            destination=Path("experiments/final.jsonl"),
        )


def test_cli_prints_hashes_and_counts_without_seed_or_identities(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, commit = _repository(tmp_path)

    status = schedule_main(
        [
            "--workspace",
            str(repo),
            "--system-commit",
            commit,
            "--seed",
            SEED,
            "--destination",
            "experiments/final.jsonl",
        ]
    )

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert status == 0
    assert set(output) == {
        "attempt_count",
        "question_count",
        "schedule_file_sha256",
        "schedule_sha256",
        "system_commit",
        "test_ids_sha256",
    }
    assert SEED not in output_text
    assert "q-001" not in output_text


def test_script_entrypoint_generates_the_same_public_summary(tmp_path: Path) -> None:
    repo, commit = _repository(tmp_path)
    project = Path(__file__).parents[1]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(project / "sealed_tools/generate_freeze_b_schedule.py"),
            "--workspace",
            str(repo),
            "--system-commit",
            commit,
            "--seed",
            SEED,
            "--destination",
            "experiments/final.jsonl",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    output = json.loads(completed.stdout)
    assert output["attempt_count"] == 1_212
    assert output["question_count"] == 101
    assert output["system_commit"] == commit
    assert SEED not in completed.stdout
    assert completed.stderr == ""

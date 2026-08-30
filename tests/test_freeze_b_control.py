from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from omni_benchmark.freeze_b import FreezeBManifest, schedule_sha256
from omni_benchmark.freeze_b_control import (
    FreezeBControlError,
    control_main,
    load_freeze_b_control,
)
from omni_benchmark.scoring import scorer_metadata
from omni_benchmark.sealed_generation_control import load_archived_freeze_b_control


SHA_A = "a" * 64
SHA_B = "b" * 64


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _condition(condition: str) -> dict[str, object]:
    return {
        "budget_id": "sealed-default-v1",
        "condition": condition,
        "harness_config_sha256": SHA_A,
        "instructions_sha256": SHA_B,
        "model": "managed-standard",
        "model_config_id": "frozen-final-v1",
        "prompt_sha256": SHA_A,
        "provider": "aws-bedrock",
        "runtime_policy_sha256": SHA_B,
        "semantic_model_ref": "none" if condition == "C1" else "export:final-v1",
        "semantic_model_sha256": None if condition == "C1" else SHA_A,
    }


def _manifest(system_commit: str, *, freeze_a_commit: str) -> FreezeBManifest:
    attempt_ids = tuple(
        f"sealed:q-{question:03d}:{condition}:{repetition}"
        for question in range(1, 102)
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    )
    return FreezeBManifest.from_dict(
        {
            "conditions": [
                _condition(condition) for condition in ("C1", "C2", "C3", "C4")
            ],
            "database": {
                "libpq_version": "18.6",
                "postgresql_version": "18.6",
                "snapshot_manifest_sha256": SHA_A,
            },
            "expected_test_outputs": 1_212,
            "freeze_a_commit": freeze_a_commit,
            "frozen_files": {"config/freeze-b-input.json": SHA_A},
            "kind": "freeze-b-manifest",
            "question_count": 101,
            "recorded_at": "2026-08-29T06:20:00Z",
            "repetitions": 3,
            "schedule": {
                "algorithm": "committed_block_interleaved_v1",
                "seed": "human-supplied-final-seed",
                "sha256": schedule_sha256(attempt_ids),
            },
            "schema_version": 1,
            "scorer": {
                "metadata": scorer_metadata(),
                "source_commit": system_commit,
            },
            "system_commit": system_commit,
        }
    )


def _system_repository(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Freeze Control Test")
    _git(repo, "config", "user.email", "control@example.invalid")
    (repo / "freeze-a.txt").write_text("freeze a\n", encoding="utf-8")
    _git(repo, "add", "freeze-a.txt")
    _git(repo, "commit", "-qm", "freeze a")
    freeze_a_commit = _git(repo, "rev-parse", "HEAD")

    project = Path(__file__).parents[1]
    for relative in (
        "src/omni_benchmark/autoresearch_config.py",
        "src/omni_benchmark/content_policy.py",
        "src/omni_benchmark/freeze_b.py",
        "src/omni_benchmark/freeze_b_control.py",
        "src/omni_benchmark/freeze_b_record.py",
        "src/omni_benchmark/freeze_b_schedule.py",
        "src/omni_benchmark/scoring.py",
    ):
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((project / relative).read_bytes())
    (repo / "system.txt").write_text("frozen system\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "frozen system")
    return repo, _git(repo, "rev-parse", "HEAD"), freeze_a_commit


def _add_control_commit(
    repo: Path,
    system_commit: str,
    freeze_a_commit: str,
    *,
    content: bytes | None = None,
    executable: bool = False,
) -> tuple[str, FreezeBManifest]:
    manifest = _manifest(system_commit, freeze_a_commit=freeze_a_commit)
    path = repo / "experiments/freeze-b.json"
    path.parent.mkdir()
    path.write_bytes(manifest.canonical_bytes() if content is None else content)
    if executable:
        path.chmod(0o755)
    _git(repo, "add", "experiments/freeze-b.json")
    _git(repo, "commit", "-qm", "record Freeze B")
    return _git(repo, "rev-parse", "HEAD"), manifest


def test_control_loads_exact_direct_child_despite_dirty_substitution(
    tmp_path: Path,
) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    control_commit, manifest = _add_control_commit(repo, system_commit, freeze_a_commit)
    (repo / "experiments/freeze-b.json").write_text("substituted\n", encoding="utf-8")

    result = load_freeze_b_control(
        repo,
        control_commit=control_commit,
        system_commit=system_commit,
        manifest_path=Path("experiments/freeze-b.json"),
    )

    assert result.manifest == manifest
    assert result.control_commit == control_commit
    assert result.system_commit == system_commit
    assert result.freeze_b_sha256 == manifest.sha256()
    assert result.frozen_file_count == 1


def test_archived_control_loads_after_head_moves_without_rebinding_commit(
    tmp_path: Path,
) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    control_commit, manifest = _add_control_commit(repo, system_commit, freeze_a_commit)
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-qm", "later scorer system")

    result = load_archived_freeze_b_control(
        repo,
        control_commit=control_commit,
        system_commit=system_commit,
        manifest_path=Path("experiments/freeze-b.json"),
    )

    assert result.manifest == manifest
    assert result.control_commit == control_commit
    assert result.system_commit == system_commit


def test_control_rejects_abbreviated_stale_or_wrong_system_commit(
    tmp_path: Path,
) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    control_commit, _ = _add_control_commit(repo, system_commit, freeze_a_commit)

    with pytest.raises(FreezeBControlError, match="full lowercase"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit[:12],
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )
    with pytest.raises(FreezeBControlError, match="full lowercase"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit[:12],
            manifest_path=Path("experiments/freeze-b.json"),
        )
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-qm", "later")
    with pytest.raises(FreezeBControlError, match="current HEAD"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )


def test_control_rejects_non_direct_parent_or_extra_change(tmp_path: Path) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    (repo / "intermediate.txt").write_text("intermediate\n", encoding="utf-8")
    _git(repo, "add", "intermediate.txt")
    _git(repo, "commit", "-qm", "intermediate")
    control_commit, _ = _add_control_commit(repo, system_commit, freeze_a_commit)

    with pytest.raises(FreezeBControlError, match="direct child"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )

    second = tmp_path / "extra"
    repo, system_commit, freeze_a_commit = _system_repository(second)
    manifest = _manifest(system_commit, freeze_a_commit=freeze_a_commit)
    (repo / "experiments").mkdir()
    (repo / "experiments/freeze-b.json").write_bytes(manifest.canonical_bytes())
    (repo / "extra.txt").write_text("extra\n", encoding="utf-8")
    _git(repo, "add", "experiments/freeze-b.json", "extra.txt")
    _git(repo, "commit", "-qm", "freeze plus extra")
    with pytest.raises(FreezeBControlError, match="only the Freeze B manifest"):
        load_freeze_b_control(
            repo,
            control_commit=_git(repo, "rev-parse", "HEAD"),
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )


def test_control_rejects_merge_commit_even_when_tree_adds_only_manifest(
    tmp_path: Path,
) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    _git(repo, "checkout", "-qb", "freeze-side")
    manifest = _manifest(system_commit, freeze_a_commit=freeze_a_commit)
    (repo / "experiments").mkdir()
    (repo / "experiments/freeze-b.json").write_bytes(manifest.canonical_bytes())
    _git(repo, "add", "experiments/freeze-b.json")
    _git(repo, "commit", "-qm", "side freeze record")
    _git(repo, "checkout", "-qb", "control", system_commit)
    _git(repo, "commit", "--allow-empty", "-qm", "empty control parent")
    _git(repo, "merge", "--no-ff", "-qm", "merge freeze record", "freeze-side")
    control_commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(FreezeBControlError, match="not a merge"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )


def test_control_rejects_modified_manifest_and_unsafe_manifest_path(
    tmp_path: Path,
) -> None:
    repo, _, freeze_a_commit = _system_repository(tmp_path)
    existing = repo / "experiments/freeze-b.json"
    existing.parent.mkdir()
    existing.write_text("placeholder\n", encoding="utf-8")
    _git(repo, "add", "experiments/freeze-b.json")
    _git(repo, "commit", "-qm", "reserve manifest path")
    system_commit = _git(repo, "rev-parse", "HEAD")
    existing.write_bytes(
        _manifest(system_commit, freeze_a_commit=freeze_a_commit).canonical_bytes()
    )
    _git(repo, "add", "experiments/freeze-b.json")
    _git(repo, "commit", "-qm", "modify reserved manifest")
    control_commit = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(FreezeBControlError, match="add only"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )
    with pytest.raises(FreezeBControlError, match="manifest path"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("../freeze-b.json"),
        )


@pytest.mark.parametrize("case", ["noncanonical", "executable", "oversized", "symlink"])
def test_control_rejects_unsafe_or_noncanonical_manifest(
    tmp_path: Path, case: str
) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    manifest = _manifest(system_commit, freeze_a_commit=freeze_a_commit)
    path = repo / "experiments/freeze-b.json"
    path.parent.mkdir()
    if case == "noncanonical":
        path.write_text(json.dumps(manifest.as_dict(), indent=2) + "\n")
    elif case == "oversized":
        path.write_bytes(b"{" + b" " * (1024 * 1024 + 1) + b"}")
    elif case == "symlink":
        path.symlink_to("missing.json")
    else:
        path.write_bytes(manifest.canonical_bytes())
        path.chmod(0o755)
    _git(repo, "add", "experiments/freeze-b.json")
    _git(repo, "commit", "-qm", f"invalid {case} Freeze B")

    message = {
        "noncanonical": "canonical",
        "executable": "non-executable regular Git blob",
        "oversized": "byte limit",
        "symlink": "non-executable regular Git blob",
    }[case]
    with pytest.raises(FreezeBControlError, match=message):
        load_freeze_b_control(
            repo,
            control_commit=_git(repo, "rev-parse", "HEAD"),
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )


def test_control_rejects_manifest_bound_to_another_system(tmp_path: Path) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    other_commit = freeze_a_commit
    manifest = _manifest(other_commit, freeze_a_commit=freeze_a_commit)
    control_commit, _ = _add_control_commit(
        repo,
        system_commit,
        freeze_a_commit,
        content=manifest.canonical_bytes(),
    )

    with pytest.raises(FreezeBControlError, match="recorded system commit"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )


def test_control_rejects_unresolvable_full_system_commit(tmp_path: Path) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    control_commit, _ = _add_control_commit(repo, system_commit, freeze_a_commit)

    with pytest.raises(FreezeBControlError, match="system commit is unavailable"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit="0" * 40,
            manifest_path=Path("experiments/freeze-b.json"),
        )


def test_control_rejects_runtime_source_drift(tmp_path: Path) -> None:
    repo, _, freeze_a_commit = _system_repository(tmp_path)
    source = repo / "src/omni_benchmark/freeze_b_control.py"
    source.write_text("# substituted control loader\n", encoding="utf-8")
    _git(repo, "add", "src/omni_benchmark/freeze_b_control.py")
    _git(repo, "commit", "-qm", "substitute control loader")
    system_commit = _git(repo, "rev-parse", "HEAD")
    control_commit, _ = _add_control_commit(repo, system_commit, freeze_a_commit)

    with pytest.raises(FreezeBControlError, match="runtime source"):
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )


def test_control_ignores_git_environment_and_rejects_symlink_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    control_commit, _ = _add_control_commit(repo, system_commit, freeze_a_commit)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _git(unrelated, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(unrelated / ".git"))
    assert (
        load_freeze_b_control(
            repo,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        ).control_commit
        == control_commit
    )
    linked = tmp_path / "linked"
    linked.symlink_to(repo, target_is_directory=True)
    with pytest.raises(FreezeBControlError, match="non-symlink"):
        load_freeze_b_control(
            linked,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=Path("experiments/freeze-b.json"),
        )


def test_control_cli_prints_only_hashes_and_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    control_commit, _ = _add_control_commit(repo, system_commit, freeze_a_commit)

    status = control_main(
        [
            "--workspace",
            str(repo),
            "--control-commit",
            control_commit,
            "--system-commit",
            system_commit,
            "--manifest",
            "experiments/freeze-b.json",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert status == 0
    assert set(output) == {
        "control_commit",
        "freeze_b_sha256",
        "frozen_file_count",
        "system_commit",
    }


def test_control_script_entrypoint_loads_the_same_record(tmp_path: Path) -> None:
    repo, system_commit, freeze_a_commit = _system_repository(tmp_path)
    control_commit, _ = _add_control_commit(repo, system_commit, freeze_a_commit)
    project = Path(__file__).parents[1]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(project / "sealed_tools/validate_freeze_b_control.py"),
            "--workspace",
            str(repo),
            "--control-commit",
            control_commit,
            "--system-commit",
            system_commit,
            "--manifest",
            "experiments/freeze-b.json",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    output = json.loads(completed.stdout)
    assert output["control_commit"] == control_commit
    assert output["system_commit"] == system_commit
    assert completed.stderr == ""

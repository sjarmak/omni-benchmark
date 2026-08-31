"""The guard must fail exactly when the per-attempt preflight would fail."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "guard_runtime_commit.py"
)
_SPEC = importlib.util.spec_from_file_location("guard_runtime_commit", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
guard = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(guard)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", "-C", str(root), *arguments), check=True, capture_output=True
    )


@pytest.fixture()
def repository(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "test")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("value = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "--quiet", "-m", "initial")
    return tmp_path


def test_pinned_workspace_passes(repository: Path) -> None:
    guard.assert_pinned(repository, guard.head_commit(repository))


def test_moved_head_fails(repository: Path) -> None:
    pinned = guard.head_commit(repository)
    (repository / "notes.md").write_text("evidence\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "--quiet", "-m", "record evidence")
    with pytest.raises(guard.GuardError, match="HEAD is"):
        guard.assert_pinned(repository, pinned)


def test_dirty_runtime_path_fails(repository: Path) -> None:
    pinned = guard.head_commit(repository)
    (repository / "src" / "module.py").write_text("value = 2\n")
    with pytest.raises(guard.GuardError, match="runtime paths are dirty"):
        guard.assert_pinned(repository, pinned)


def test_untracked_runtime_file_fails(repository: Path) -> None:
    """Preflight uses --untracked-files=all, so a new file is a violation too."""
    pinned = guard.head_commit(repository)
    (repository / "src" / "extra.py").write_text("value = 3\n")
    with pytest.raises(guard.GuardError, match="runtime paths are dirty"):
        guard.assert_pinned(repository, pinned)


def test_non_runtime_change_is_permitted(repository: Path) -> None:
    """Docs and evidence outside the runtime paths do not fail preflight."""
    pinned = guard.head_commit(repository)
    (repository / "docs.md").write_text("prose\n")
    guard.assert_pinned(repository, pinned)


def test_runtime_paths_match_the_preflight_contract() -> None:
    from omni_benchmark.omni_probe_preflight import RUNTIME_PATHS

    assert guard.RUNTIME_PATHS == RUNTIME_PATHS

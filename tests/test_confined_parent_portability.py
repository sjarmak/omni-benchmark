from __future__ import annotations

import os
from pathlib import Path

import pytest

from omni_benchmark import autoresearch_config
from omni_benchmark.autoresearch_config import AutoresearchError


@pytest.mark.parametrize("symlinked_root", [False, True])
def test_directory_descriptor_resolves_real_path(
    tmp_path: Path, symlinked_root: bool
) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    root = tmp_path / "alias"
    root.symlink_to(directory, target_is_directory=True)
    opened = root if symlinked_root else directory
    descriptor = os.open(opened, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert autoresearch_config._directory_descriptor_path(
            descriptor
        ) == directory.resolve(strict=True)
    finally:
        os.close(descriptor)


def test_confined_parent_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(AutoresearchError, match="inside workspace"):
        autoresearch_config._open_confined_parent(
            workspace, workspace / "escape" / "artifact.json"
        )
    assert not (outside / "artifact.json").exists()


def test_confined_write_through_symlinked_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(workspace, target_is_directory=True)
    destination = autoresearch_config._write_exclusive(
        Path("nested/artifact.json"), b"{}", workspace=alias
    )
    assert destination == workspace.resolve() / "nested" / "artifact.json"
    assert destination.read_bytes() == b"{}"
    assert destination.stat().st_mode & 0o777 == 0o600


def test_directory_descriptor_rejects_unsupported_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autoresearch_config.sys, "platform", "unsupported")
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(AutoresearchError, match="inside workspace"):
            autoresearch_config._directory_descriptor_path(descriptor)
    finally:
        os.close(descriptor)


def test_linux_descriptor_resolution_uses_proc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(autoresearch_config.sys, "platform", "linux")
    calls: list[tuple[Path, bool]] = []

    def resolve(path: Path, strict: bool = False) -> Path:
        calls.append((path, strict))
        return tmp_path

    monkeypatch.setattr(Path, "resolve", resolve)
    assert autoresearch_config._directory_descriptor_path(42) == tmp_path
    assert calls == [(Path("/proc/self/fd/42"), True)]

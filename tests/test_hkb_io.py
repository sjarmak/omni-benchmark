from __future__ import annotations

import os
from pathlib import Path

import pytest

from omni_benchmark.hkb_io import (
    HKBFileSafetyError,
    publish_flat_files,
    publish_nested_files,
    read_relative_regular_file,
)


@pytest.mark.parametrize(
    "relative",
    ["/absolute/file.jsonl", "alpha//file.jsonl", "alpha/./file.jsonl"],
)
def test_relative_reader_rejects_paths_before_normalization(
    tmp_path: Path, relative: str
) -> None:
    with pytest.raises(HKBFileSafetyError, match="unsafe relative HKB path"):
        read_relative_regular_file(tmp_path, relative, maximum_bytes=10)


@pytest.mark.parametrize("name", ["../escape.jsonl", "/absolute.jsonl", "a/b.jsonl"])
def test_flat_publisher_accepts_only_one_safe_path_component(
    tmp_path: Path, name: str
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (tmp_path / "escape.jsonl").write_text("outside")

    with pytest.raises(HKBFileSafetyError, match="flat output name must be one safe"):
        publish_flat_files(staging, tmp_path / "output", (name,))


def test_nested_publisher_preflights_every_child_before_replacing_files(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    destination = tmp_path / "output"
    paths = ("alpha/source.json", "beta/source.json")
    for directory in ("alpha", "beta"):
        (staging / directory).mkdir(parents=True)
        (staging / directory / "source.json").write_text(f"new-{directory}")
        (destination / directory).mkdir(parents=True)
        (destination / directory / "source.json").write_text(f"old-{directory}")
    (destination / "beta" / "unexpected.txt").write_text("reject")

    with pytest.raises(HKBFileSafetyError, match="unexpected.txt"):
        publish_nested_files(staging, destination, paths)

    assert (destination / "alpha" / "source.json").read_text() == "old-alpha"
    assert (destination / "beta" / "source.json").read_text() == "old-beta"


def test_relative_reader_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    database_root = tmp_path / "alpha"
    database_root.mkdir()
    os.mkfifo(database_root / "source.json")

    with pytest.raises(HKBFileSafetyError, match="regular non-symlink"):
        read_relative_regular_file(
            tmp_path,
            "alpha/source.json",
            maximum_bytes=10,
        )

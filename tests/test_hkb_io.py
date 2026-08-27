from __future__ import annotations

from pathlib import Path

import pytest

from omni_benchmark.hkb_io import (
    HKBFileSafetyError,
    publish_flat_files,
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

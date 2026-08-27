from __future__ import annotations

import json
from pathlib import Path

from omni_benchmark.split import development_split_main, prepare_main, split_main

from .helpers import official_shape_records, write_jsonl


def test_prepare_and_split_cli_flow(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.jsonl"
    output = tmp_path / "manifests"
    write_jsonl(source, official_shape_records())

    assert (
        prepare_main(
            [
                "--input",
                str(source),
                "--output-dir",
                str(output),
                "--source-commit",
                "a418e108",
            ]
        )
        == 0
    )
    assert (
        split_main(
            [
                "--manifest-dir",
                str(output),
                "--train-size",
                "231",
                "--test-size",
                "101",
            ]
        )
        == 0
    )

    output_lines = capsys.readouterr().out.splitlines()
    assert json.loads(output_lines[0])["counts"]["eligible"] == 332
    split_output = json.loads(output_lines[1])
    assert split_output["counts"] == {"test": 101, "train": 231}
    assert split_output["algorithm"]["seed"] == "omni-livesqlbench-large-v1-split-v1"

    assert (
        development_split_main(
            [
                "--manifest-dir",
                str(output),
                "--dev-a-size",
                "154",
                "--dev-b-size",
                "77",
            ]
        )
        == 0
    )
    development_output = json.loads(capsys.readouterr().out)
    assert development_output["counts"] == {
        "development": 231,
        "dev_a": 154,
        "dev_b": 77,
    }
    assert development_output["algorithm"]["seed"] == (
        "omni-livesqlbench-large-v1-development-split-v1"
    )

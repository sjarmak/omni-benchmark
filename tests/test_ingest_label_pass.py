"""The labeling-pass ingest refuses a pass that does not cover its cohort."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SHA = "c" * 64
ATTEMPTS = [f"run-1:alpha_Q{index}:C4:1" for index in (1, 2)]


def _module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "ingest_label_pass", "scripts/ingest_label_pass.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "dev_a_ids.txt").write_text("alpha_Q1\nalpha_Q2\n", encoding="utf-8")
    (manifests / "test_ids.txt").write_text("z_T9\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "batch": 0,
                    "attempts": [
                        {"attempt_id": attempt, "generation_record_sha256": SHA}
                        for attempt in ATTEMPTS
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    labels = tmp_path / "labels"
    labels.mkdir()
    batches = tmp_path / "batches"
    batches.mkdir()
    return {
        "manifests": manifests,
        "manifest": manifest,
        "labels": labels,
        "in": batches,
    }


def _write(batches: Path, records: list[dict[str, str]]) -> None:
    (batches / "batch-000.json").write_text(json.dumps(records), encoding="utf-8")


def _record(attempt: str, category: str = "relationship_join") -> dict[str, str]:
    return {
        "attempt_id": attempt,
        "generation_record_sha256": SHA,
        "category": category,
        "rationale": f"the generated query joined the wrong path for {attempt}",
    }


def _run(module: Any, workspace: dict[str, Path], **overrides: str) -> int:
    argv = [
        "--input-dir",
        str(workspace["in"]),
        "--manifest",
        str(workspace["manifest"]),
        "--pass-id",
        overrides.get("pass_id", "dev-a-pass-1"),
        "--labeler",
        overrides.get("labeler", "model:claude"),
        "--labels-dir",
        str(workspace["labels"]),
        "--manifests-dir",
        str(workspace["manifests"]),
        "--created-at",
        "2026-09-02T12:00:00.000Z",
    ]
    return int(module.main(argv))


def test_a_complete_pass_is_appended_once(
    workspace: dict[str, Path], capsys: Any
) -> None:
    module = _module()
    _write(
        workspace["in"],
        [_record(ATTEMPTS[0]), _record(ATTEMPTS[1], "metric_aggregation_grain")],
    )
    assert _run(module, workspace) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["labels"] == 2
    assert summary["categories"] == {
        "relationship_join": 1,
        "metric_aggregation_grain": 1,
    }
    lines = (workspace["labels"] / "dev-a-pass-1.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["category"] == "relationship_join"
    assert _run(module, workspace) == 2


def test_a_missing_attempt_blocks_the_whole_pass(workspace: dict[str, Path]) -> None:
    module = _module()
    _write(workspace["in"], [_record(ATTEMPTS[0])])
    assert _run(module, workspace) == 2
    assert not (workspace["labels"] / "dev-a-pass-1.jsonl").exists()


def test_a_duplicate_label_blocks_the_whole_pass(workspace: dict[str, Path]) -> None:
    module = _module()
    _write(
        workspace["in"],
        [
            _record(ATTEMPTS[0]),
            _record(ATTEMPTS[1]),
            _record(ATTEMPTS[1], "direct_reasoning"),
        ],
    )
    assert _run(module, workspace) == 2
    assert not (workspace["labels"] / "dev-a-pass-1.jsonl").exists()


def test_an_unknown_category_blocks_the_whole_pass(workspace: dict[str, Path]) -> None:
    module = _module()
    _write(
        workspace["in"],
        [_record(ATTEMPTS[0], "not_a_category"), _record(ATTEMPTS[1])],
    )
    assert _run(module, workspace) == 2
    assert not (workspace["labels"] / "dev-a-pass-1.jsonl").exists()


def test_a_label_outside_dev_a_blocks_the_whole_pass(
    workspace: dict[str, Path],
) -> None:
    module = _module()
    (workspace["manifests"] / "dev_a_ids.txt").write_text(
        "alpha_Q1\n", encoding="utf-8"
    )
    _write(workspace["in"], [_record(ATTEMPTS[0]), _record(ATTEMPTS[1])])
    assert _run(module, workspace) == 2
    assert not (workspace["labels"] / "dev-a-pass-1.jsonl").exists()

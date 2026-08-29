from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.gold_free_scoring import (
    GoldFreeScoringError,
    run_self_consistency_exercise,
)
from omni_benchmark.gold_free_scoring_cli import main


def _canonical(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text(
        "experiments/autoresearch/raw/\n", encoding="utf-8"
    )
    manifests = workspace / "data/manifests"
    manifests.mkdir(parents=True)
    (manifests / "dev_a_ids.txt").write_text("q-1\n", encoding="utf-8")
    (manifests / "eligible_questions.jsonl").write_bytes(
        _canonical(
            {
                "conditions": {"decimal": 2, "order": True},
                "instance_id": "q-1",
            }
        )
    )
    return workspace


def _attempt(
    root: Path,
    *,
    run_id: str,
    rows: list[list[object]],
    instance_id: str = "q-1",
) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    result = root / "answer.result.json"
    result.write_bytes(
        _canonical(
            {
                "columns": ["value"],
                "rows": rows,
                "schema_version": 1,
                "truncated": False,
            }
        )
    )
    result_sha256 = hashlib.sha256(result.read_bytes()).hexdigest()
    generation = root / "generation.jsonl"
    generation.write_bytes(
        _canonical(
            {
                "actual_result_hash": result_sha256,
                "actual_result_status": "complete",
                "attempt_id": f"{run_id}:{instance_id}:C2:1",
                "condition": "C2",
                "generation_outcome": "answered",
                "instance_id": instance_id,
                "partition": "dev-a",
                "repetition": 1,
                "run_id": run_id,
            }
        )
    )
    return generation, result


def test_real_result_representations_agree_under_both_frozen_scorers(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    left = _attempt(
        tmp_path / "left",
        run_id="left-run",
        rows=[[{"type": "decimal", "value": "97.12142028092653806402"}]],
    )
    right = _attempt(
        tmp_path / "right",
        run_id="right-run",
        rows=[[97.12142028092654]],
    )

    receipt = run_self_consistency_exercise(
        workspace,
        left_generation=left[0],
        left_result=left[1],
        right_generation=right[0],
        right_result=right[1],
        output_root=Path("experiments/autoresearch/raw/gold-free-v1"),
    )

    assert receipt.official_agreement is True
    assert receipt.sensitivity_agreement is True
    assert receipt.instance_id == "q-1"
    assert receipt.condition == "C2"
    assert receipt.left_result_sha256 != receipt.right_result_sha256
    assert receipt.official_score.correct_count == 1
    assert receipt.sensitivity_score.correct_count == 1
    evidence = json.loads(receipt.evidence.path.read_text(encoding="utf-8"))
    assert evidence["oracle"] == "result_set_self_consistency_not_correctness"
    assert (
        evidence["inputs"]["left"]["generation_sha256"]
        == hashlib.sha256(left[0].read_bytes()).hexdigest()
    )


def test_disagreement_is_preserved_without_claiming_benchmark_correctness(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    left = _attempt(tmp_path / "left", run_id="left-run", rows=[[1]])
    right = _attempt(tmp_path / "right", run_id="right-run", rows=[[2]])

    receipt = run_self_consistency_exercise(
        workspace,
        left_generation=left[0],
        left_result=left[1],
        right_generation=right[0],
        right_result=right[1],
        output_root=Path("experiments/autoresearch/raw/gold-free-v1"),
    )

    assert receipt.official_agreement is False
    assert receipt.sensitivity_agreement is False
    assert receipt.official_score.wrong_answer_count == 1
    assert receipt.sensitivity_score.wrong_answer_count == 1


def test_result_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    left = _attempt(tmp_path / "left", run_id="left-run", rows=[[1]])
    right = _attempt(tmp_path / "right", run_id="right-run", rows=[[1]])
    left[1].write_bytes(_canonical({"tampered": True}))

    with pytest.raises(GoldFreeScoringError, match="result hash"):
        run_self_consistency_exercise(
            workspace,
            left_generation=left[0],
            left_result=left[1],
            right_generation=right[0],
            right_result=right[1],
            output_root=Path("experiments/autoresearch/raw/gold-free-v1"),
        )


def test_non_dev_a_instance_is_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    left = _attempt(
        tmp_path / "left", run_id="left-run", rows=[[1]], instance_id="q-test"
    )
    right = _attempt(
        tmp_path / "right", run_id="right-run", rows=[[1]], instance_id="q-test"
    )

    with pytest.raises(GoldFreeScoringError, match="dev-A"):
        run_self_consistency_exercise(
            workspace,
            left_generation=left[0],
            left_result=left[1],
            right_generation=right[0],
            right_result=right[1],
            output_root=Path("experiments/autoresearch/raw/gold-free-v1"),
        )


def test_cli_emits_hash_bound_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    left = _attempt(tmp_path / "left", run_id="left-run", rows=[[1]])
    right = _attempt(tmp_path / "right", run_id="right-run", rows=[[1]])

    exit_code = main(
        [
            "--workspace",
            str(workspace),
            "--left-generation",
            str(left[0]),
            "--left-result",
            str(left[1]),
            "--right-generation",
            str(right[0]),
            "--right-result",
            str(right[1]),
            "--output-root",
            "experiments/autoresearch/raw/gold-free-v1",
        ]
    )

    receipt = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert receipt["oracle"] == "result_set_self_consistency_not_correctness"
    assert receipt["official_agreement"] is True
    assert receipt["sensitivity_agreement"] is True

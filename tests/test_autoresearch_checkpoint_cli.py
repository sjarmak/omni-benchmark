from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_benchmark.autoresearch import main

from tests.test_autoresearch_checkpoints import (
    configured_workspace as _configured_workspace,
    unscored_record,
    write_dev_b_receipt,
    write_full_run,
    write_json,
    write_jsonl,
)


@pytest.fixture
def configured_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Reuse the checkpoint fixture setup without coupling test collection."""
    return _configured_workspace.__wrapped__(tmp_path)


def test_cli_runs_public_view_baseline_proposal_decision_checkpoint_and_stop(
    configured_workspace: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, config_path = configured_workspace
    before = write_full_run(workspace, "before", ("correct", "wrong_answer"))
    after = write_full_run(workspace, "after", ("correct", "correct"))
    baseline = workspace / "runs" / "baseline-all.jsonl"
    write_jsonl(
        baseline,
        [
            unscored_record("train_1"),
            unscored_record("train_2"),
            unscored_record("dev_b_1"),
        ],
    )
    dev_b_receipt = write_dev_b_receipt(workspace, after, "checkpoint-cli")
    taxonomy = workspace / "analysis" / "taxonomy.json"
    write_json(
        taxonomy,
        {
            "categories": [
                {"name": "join path", "count": 0, "primary_source": "semantic model"}
            ]
        },
    )
    common = [
        "--workspace",
        str(workspace),
        "--config",
        str(config_path),
        "--freeze-a-commit",
        "a" * 40,
    ]

    assert main([*common, "public-dev-a"]) == 0
    assert (
        main([*common, "baseline", "--run", str(baseline), "--git-commit", "a" * 40])
        == 0
    )
    assert (
        main(
            [
                *common,
                "propose",
                "--experiment-id",
                "exp-cli",
                "--parent",
                "baseline",
                "--hypothesis",
                "A reusable dependency rule is missing.",
                "--intervention",
                "Materialize every declared dependency edge.",
                "--affected-class",
                "dependency",
                "--mechanism",
                "Mechanical graph traversal.",
                "--predicted-direction",
                "Increase correctness.",
                "--regression-risk",
                "Cycles may be rejected.",
                "--subsystem",
                "transformer",
                "--generality-rationale",
                "Applies to every database.",
                "--condition",
                "C4",
                "--content-provenance",
                "Public schema and HKB.",
                "--intervention-provenance",
                "Transformer source diff.",
                "--tuning-actor",
                "human_agent_collaboration",
                "--tuning-effort",
                "one mechanism and one dev-A run",
                "--optimization-surface",
                "structural",
                "--candidate-generation-method",
                "Deterministic transformer edit.",
                "--generality-scope",
                "cross_database_general",
                "--evaluation-id",
                "train_1",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                *common,
                "regression-add",
                "--instance-id",
                "train_2",
                "--capability",
                "dependency compilation",
                "--rationale",
                "Representative of a reusable capability.",
                "--source-experiment",
                "exp-cli",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                *common,
                "decide",
                "--experiment-id",
                "exp-cli",
                "--decision",
                "KEEP",
                "--before-run",
                str(before),
                "--after-run",
                str(after),
                "--git-commit",
                "b" * 40,
                "--rationale",
                "Reusable gain with no regression.",
                "--complexity-impact",
                "One deterministic transformation rule.",
                "--production-relevance",
                "Applies to semantic-model compilation.",
                "--complexity-score",
                "1",
                "--special-case-count",
                "0",
                "--stability-rate",
                "1",
                "--unexpected-observations",
                "None.",
                "--follow-up-hypothesis",
                "Test deeper graphs.",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                *common,
                "checkpoint",
                "--name",
                "checkpoint-cli",
                "--run",
                str(after),
                "--dev-b-receipt",
                str(dev_b_receipt.receipt),
                "--dev-b-signature",
                str(dev_b_receipt.signature),
                "--guardian-public-key",
                str(dev_b_receipt.public_key),
                "--taxonomy",
                str(taxonomy),
                "--git-commit",
                "b" * 40,
            ]
        )
        == 0
    )
    assert (
        main(
            [
                *common,
                "stop",
                "--reason",
                "planned experiment budget reached",
                "--rationale",
                "The preregistered stopping rule fired.",
                "--git-commit",
                "c" * 40,
            ]
        )
        == 0
    )
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [value["status"] for value in outputs] == [
        "created",
        "created",
        "proposed",
        "added",
        "KEEP",
        "created",
        "stopped",
    ]

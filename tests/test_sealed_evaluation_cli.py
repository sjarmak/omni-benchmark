"""Dry-default command boundary for final sealed scoring."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.sealed_evaluation_cli as cli
from omni_benchmark.sealed_evaluation import SealedEvaluationError


def _arguments(tmp_path: Path) -> list[str]:
    return [
        "--workspace",
        str(tmp_path),
        "--control-commit",
        "f" * 40,
        "--system-commit",
        "e" * 40,
        "--freeze-b",
        "experiments/freeze-b.json",
        "--schedule",
        "data/final-schedule.jsonl",
        "--public-manifest",
        "data/manifests/eligible_questions.jsonl",
        "--cohort-root",
        "runs/sealed-cohorts",
    ]


def test_dry_default_stops_after_complete_public_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = SimpleNamespace(freeze_b_sha256="a" * 64)
    freeze = SimpleNamespace(sha256=lambda: "a" * 64)
    batch = SimpleNamespace(
        attempts=(None,) * 1_212,
        cohorts=(None,) * 12,
        freeze_b_sha256="a" * 64,
        plan_sha256="b" * 64,
        schedule_sha256="c" * 64,
    )
    monkeypatch.setattr(cli, "_require_exact_control_checkout", lambda *_: None)
    monkeypatch.setattr(cli, "load_sealed_execution_plan", lambda *a, **k: plan)
    monkeypatch.setattr(
        cli,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )
    monkeypatch.setattr(cli, "load_sealed_public_questions", lambda *a, **k: {})
    monkeypatch.setattr(cli, "load_sealed_output_batch", lambda *a, **k: batch)
    monkeypatch.setattr(
        cli,
        "prepare_sealed_evaluation_plan",
        lambda *a, **k: pytest.fail("dry preflight opened private release"),
    )

    assert cli.sealed_evaluation_main(_arguments(tmp_path), environment={}) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "validated_not_scored"
    assert summary["attempt_count"] == 1_212


def test_execution_requires_all_private_arguments(tmp_path: Path) -> None:
    with pytest.raises(SealedEvaluationError, match="release"):
        cli._execution_arguments(
            cli._parser().parse_args(
                _arguments(tmp_path) + ["--execute-sealed-scoring"]
            )
        )

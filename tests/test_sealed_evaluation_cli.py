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
        "--generation-control-commit",
        "d" * 40,
        "--generation-system-commit",
        "c" * 40,
        "--generation-freeze-b",
        "experiments/freeze-b-generation.json",
        "--schedule",
        "data/final-schedule.jsonl",
        "--public-manifest",
        "data/manifests/eligible_questions.jsonl",
        "--test-ids",
        "data/manifests/sealed_mvp_ids.txt",
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
        generation_freeze_b_sha256="d" * 64,
        plan_sha256="b" * 64,
        schedule_sha256="c" * 64,
    )
    monkeypatch.setattr(cli, "_require_exact_control_checkout", lambda *_: None)
    calls = {}

    def load_plan(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["plan"] = kwargs
        return plan

    monkeypatch.setattr(cli, "load_sealed_execution_plan", load_plan)
    monkeypatch.setattr(
        cli,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )
    generation_control = SimpleNamespace(manifest=freeze)
    monkeypatch.setattr(
        cli,
        "load_archived_freeze_b_control",
        lambda *a, **k: generation_control,
    )
    monkeypatch.setattr(cli, "load_sealed_public_questions", lambda *a, **k: {})

    def load_batch(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["batch"] = kwargs
        return batch

    monkeypatch.setattr(cli, "load_sealed_output_batch", load_batch)
    monkeypatch.setattr(
        cli,
        "prepare_sealed_evaluation_plan",
        lambda *a, **k: pytest.fail("dry preflight opened private release"),
    )

    assert cli.sealed_evaluation_main(_arguments(tmp_path), environment={}) == 0

    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "validated_not_scored"
    assert summary["attempt_count"] == 1_212
    assert calls["plan"]["test_ids_path"] == Path("data/manifests/sealed_mvp_ids.txt")
    assert calls["batch"]["generation_control"] is generation_control


def test_execution_requires_all_private_arguments(tmp_path: Path) -> None:
    with pytest.raises(SealedEvaluationError, match="release"):
        cli._execution_arguments(
            cli._parser().parse_args(
                _arguments(tmp_path) + ["--execute-sealed-scoring"]
            )
        )


def test_execution_threads_validated_batch_through_scoring_and_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    freeze = SimpleNamespace(sha256=lambda: "a" * 64)
    generation_control = SimpleNamespace(manifest=freeze)
    plan = SimpleNamespace(freeze_b_sha256="a" * 64)
    batch = SimpleNamespace(
        attempts=(),
        cohorts=(),
        freeze_b_sha256="a" * 64,
        generation_freeze_b_sha256="d" * 64,
        plan_sha256="b" * 64,
        schedule_sha256="c" * 64,
    )
    scoring_plan = SimpleNamespace(attempts=())
    provider = object()
    calls = {}
    monkeypatch.setattr(cli, "_require_exact_control_checkout", lambda *_: None)
    monkeypatch.setattr(cli, "load_sealed_execution_plan", lambda *a, **k: plan)
    monkeypatch.setattr(
        cli,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )
    monkeypatch.setattr(
        cli, "load_archived_freeze_b_control", lambda *a, **k: generation_control
    )
    monkeypatch.setattr(cli, "load_sealed_public_questions", lambda *a, **k: {})
    monkeypatch.setattr(cli, "load_sealed_output_batch", lambda *a, **k: batch)
    monkeypatch.setattr(cli, "_committed_public_records", lambda *a, **k: {})
    monkeypatch.setattr(
        cli, "prepare_sealed_evaluation_plan", lambda *a, **k: scoring_plan
    )
    monkeypatch.setattr(cli, "_required_dsn", lambda *a, **k: "postgresql://dsn")
    monkeypatch.setattr(cli, "_require_pinned_postgres", lambda *a, **k: None)
    monkeypatch.setattr(
        cli, "PsycopgTemplateIsolationProvider", lambda *a, **k: provider
    )
    monkeypatch.setattr(cli, "score_sealed_evaluation", lambda *a, **k: ())

    def publish(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.update(kwargs)
        return {"receipt_sha256": "f" * 64}

    monkeypatch.setattr(cli, "publish_sealed_evaluation", publish)

    status = cli.sealed_evaluation_main(
        _arguments(tmp_path)
        + [
            "--release",
            "data/private/test/labels.jsonl",
            "--expected-release-sha256",
            "e" * 64,
            "--output-root",
            "runs/sealed-score",
            "--execute-sealed-scoring",
        ],
        environment={},
    )

    assert status == 0
    assert calls["plan"] is scoring_plan
    assert calls["results"] == ()
    assert json.loads(capsys.readouterr().out) == {"receipt_sha256": "f" * 64}

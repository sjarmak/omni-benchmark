"""Dry-default C5 deployment boundary."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.baseline_batch import (
    c4_dev_a_experiment_schedule,
    load_committed_baseline_schedule,
)
from omni_benchmark.c5_experiment_cli import (
    C5ExperimentError,
    _c5_deployment_identity,
    c5_experiment_main,
)


ROOT = Path(__file__).resolve().parents[1]


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _arguments() -> list[str]:
    return [
        "--workspace",
        str(ROOT),
        "--system-commit",
        _head(),
        "--run-id",
        "c5-dev-a-deployment-v1",
        "--output-root",
        "experiments/deployments/c5-dev-a-v1",
    ]


def test_dry_c5_plan_is_exact_public_and_provider_inert(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = c5_experiment_main(_arguments())

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["condition"] == "C5"
    assert output["candidate_database_count"] == 18
    assert output["deployment_database_count"] == 16
    assert output["schedule_attempt_count"] == 136
    assert output["live_execution"] == "not_started"
    assert output["file_count"] > 1000
    assert output["relationship_count"] > 500
    assert len(output["execution_plan_sha256"]) == 64
    assert output["deployment_set_sha256"] != output["candidate_set_sha256"]


def test_c5_uses_condition_specific_remote_identity() -> None:
    model, branch = _c5_deployment_identity("sample_large")

    assert model == "livesqlbench-sample_large-c5-tuned-v1"
    assert branch == model
    assert "public-baseline" not in model


def test_live_c5_deployment_carries_only_the_scheduled_committed_plans() -> None:
    observed: dict[str, object] = {}

    def deploy(argv: list[str], **kwargs: object) -> int:
        plans, diagnostics = kwargs["bundle_loader"](ROOT, _head())
        full = load_committed_baseline_schedule(
            ROOT, _head(), run_id="c5-dev-a-deployment-v1"
        )
        schedule = c4_dev_a_experiment_schedule(ROOT, _head(), full)
        assert set(plans) == {attempt.database for attempt in schedule.attempts}
        assert diagnostics == {}
        observed["argv"] = argv
        observed["identity"] = kwargs["identity_factory"]("sample_large")
        return 0

    result = c5_experiment_main(
        [*_arguments(), "--execute-live-deployment", "--profile", "fixture"],
        deployment_runner=deploy,
    )

    assert result == 0
    assert "--execute-live-deployment" in observed["argv"]
    assert observed["identity"] == (
        "livesqlbench-sample_large-c5-tuned-v1",
        "livesqlbench-sample_large-c5-tuned-v1",
    )


def test_live_c5_deployment_requires_a_profile_before_product_access() -> None:
    def forbidden(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("deployment must not start without a profile")

    with pytest.raises(C5ExperimentError, match="Omni profile"):
        c5_experiment_main(
            [*_arguments(), "--execute-live-deployment"],
            deployment_runner=forbidden,
        )


def test_c5_output_root_stays_inside_the_deployment_tree() -> None:
    arguments = _arguments()
    arguments[-1] = "experiments/runs/c5-dev-a-v1"

    with pytest.raises(C5ExperimentError, match="not confined"):
        c5_experiment_main(arguments)

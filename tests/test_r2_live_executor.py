"""The post-receipt executor pins each attempt to its verified deployment."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.r2_live_executor as live
from omni_benchmark.r2_dispatch import R2DeploymentTarget, R2DispatchPolicy
from omni_benchmark.r2_execution import (
    R2AttemptArtifacts,
    R2ExecutionPlan,
    R2PlannedAttempt,
)
from omni_benchmark.r2_paired_schedule import CONTROL_CONDITION


SHA = "a" * 64
COMMIT = "b" * 40


def _attempt() -> R2PlannedAttempt:
    return R2PlannedAttempt(
        attempt_id="r2attempt-1",
        attempt_position=1,
        condition=CONTROL_CONDITION,
        database="sample_large",
        deployment_identity="livesqlbench-sample_large-r2-c5b-v1",
        deployment_run_id="r2-c5b-deployment-v1",
        instance_id="sample-1",
        output_root=Path("runs/r2/sample/001-r2attempt-1"),
        pair_id="r2pair-sample-1",
        pair_position=1,
        repetition=1,
        run_id="r2-c5b-v1",
        semantic_model_sha256=SHA,
        within_pair_position=1,
    )


def _plan() -> R2ExecutionPlan:
    attempt = _attempt()
    treatment = replace(
        attempt,
        attempt_id="r2attempt-2",
        attempt_position=2,
        condition="R2-M1",
        deployment_identity="livesqlbench-sample_large-r2-m1-v1",
        deployment_run_id="r2-m1-deployment-v1",
        output_root=Path("runs/r2/sample/002-r2attempt-2"),
        run_id="r2-m1-v1",
        within_pair_position=2,
    )
    return R2ExecutionPlan(
        attempts=(attempt, treatment),
        balanced_ai_settings_sha256=SHA,
        budget_policy_sha256=SHA,
        bundle_manifest_sha256=SHA,
        bundle_set_sha256=SHA,
        harness_config_sha256=SHA,
        instructions_sha256=SHA,
        output_root=Path("runs/r2"),
        projected_arm_cost_usd={"R2-C5B": "1", "R2-M1": "1"},
        projected_total_cost_usd="2",
        prompt_sha256=SHA,
        schedule_sha256=SHA,
        system_commit=COMMIT,
    )


def _target() -> R2DeploymentTarget:
    attempt = _attempt()
    return R2DeploymentTarget(
        branch_id="branch-generated-id",
        branch_name=attempt.deployment_identity,
        model_id="model-generated-id",
        model_name=attempt.deployment_identity,
        semantic_model_sha256=attempt.semantic_model_sha256,
    )


def test_executor_overrides_only_target_ids_and_calls_the_receipt_gated_leaf(
    tmp_path: Path,
) -> None:
    artifact = R2AttemptArtifacts(
        generation_path=tmp_path / "generation.jsonl",
        generation_sha256=SHA,
        manifest_path=tmp_path / "run.json",
        manifest_sha256=SHA,
    )
    observed: dict[str, object] = {}

    def execute(**kwargs: object):  # type: ignore[no-untyped-def]
        observed.update(kwargs)
        return artifact, SimpleNamespace()

    executor = live.R2LiveExecutor(
        workspace=tmp_path,
        plan=_plan(),
        policy=R2DispatchPolicy.create(
            budget_id="r2-budget-v1",
            freeze_a_commit="c" * 40,
            maximum_wall_clock_seconds=100,
        ),
        environment={
            "OMNI_API_TOKEN": "secret-token",
            "OMNI_BASE_URL": "https://example.omniapp.co",
            "OMNI_MODEL_ID": "wrong-model",
            "UNRELATED_SECRET": "must-not-be-copied",
        },
        attempt_runner=execute,
    )

    result = executor.execute(_attempt(), _target())

    assert result is artifact
    environment = observed["environment"]
    assert environment["OMNI_MODEL_ID"] == "model-generated-id"
    assert environment["OMNI_BRANCH_ID"] == "branch-generated-id"
    assert environment["OMNI_API_TOKEN"] == "secret-token"
    assert "UNRELATED_SECRET" not in environment
    arguments = observed["probe_arguments"]
    assert isinstance(arguments, argparse.Namespace)
    assert arguments.instance_id == "sample-1"
    assert arguments.output_root == _attempt().output_root
    assert arguments.execute_authenticated_smoke is True
    assert observed["deployment_target"] == _target()


def test_executor_rejects_target_or_attempt_substitution_before_leaf(
    tmp_path: Path,
) -> None:
    executor = live.R2LiveExecutor(
        workspace=tmp_path,
        plan=_plan(),
        policy=R2DispatchPolicy.create(
            budget_id="r2-budget-v1",
            freeze_a_commit="c" * 40,
            maximum_wall_clock_seconds=100,
        ),
        environment={
            "OMNI_PROFILE": "fixture",
            "OMNI_BASE_URL": "https://example.omniapp.co",
        },
        attempt_runner=lambda **_: pytest.fail("leaf must not run"),
    )
    changed = replace(_target(), branch_name="wrong")
    with pytest.raises(live.R2LiveExecutorError, match="deployment"):
        executor.execute(_attempt(), changed)

    unknown = replace(_attempt(), attempt_id="unknown")
    with pytest.raises(live.R2LiveExecutorError, match="attempt"):
        executor.execute(unknown, _target())


def test_environment_requires_exactly_one_operator_owned_auth_mode(
    tmp_path: Path,
) -> None:
    common = {
        "workspace": tmp_path,
        "plan": _plan(),
        "policy": R2DispatchPolicy.create(
            budget_id="r2-budget-v1",
            freeze_a_commit="c" * 40,
            maximum_wall_clock_seconds=100,
        ),
        "attempt_runner": lambda **_: pytest.fail("leaf must not run"),
    }
    with pytest.raises(live.R2LiveExecutorError, match="exactly one"):
        live.R2LiveExecutor(
            **common,
            environment={"OMNI_BASE_URL": "https://example.omniapp.co"},
        )
    with pytest.raises(live.R2LiveExecutorError, match="exactly one"):
        live.R2LiveExecutor(
            **common,
            environment={
                "OMNI_API_TOKEN": "token",
                "OMNI_PROFILE": "profile",
                "OMNI_BASE_URL": "https://example.omniapp.co",
            },
        )


def test_live_environment_is_validated_and_minimized_before_consumption() -> None:
    prepared = live.prepare_r2_live_environment(
        {
            "HOME": "/must-not-reach-token-mode",
            "OMNI_API_TOKEN": "secret-token",
            "OMNI_BASE_URL": "https://example.omniapp.co",
            "PATH": "/usr/bin",
            "UNRELATED_SECRET": "secret",
        }
    )

    assert prepared == {
        "OMNI_API_TOKEN": "secret-token",
        "OMNI_BASE_URL": "https://example.omniapp.co",
        "PATH": "/usr/bin",
    }


def test_executor_rejects_missing_base_url_and_invalid_leaf_result(
    tmp_path: Path,
) -> None:
    common = {
        "workspace": tmp_path,
        "plan": _plan(),
        "policy": R2DispatchPolicy.create(
            budget_id="r2-budget-v1",
            freeze_a_commit="c" * 40,
            maximum_wall_clock_seconds=100,
        ),
    }
    with pytest.raises(live.R2LiveExecutorError, match="base URL"):
        live.R2LiveExecutor(
            **common,
            environment={"OMNI_PROFILE": "fixture"},
        )
    executor = live.R2LiveExecutor(
        **common,
        environment={
            "OMNI_PROFILE": "fixture",
            "OMNI_BASE_URL": "https://example.omniapp.co",
        },
        attempt_runner=lambda **_: ("wrong", object()),
    )
    with pytest.raises(live.R2LiveExecutorError, match="invalid result"):
        executor.execute(_attempt(), _target())


def test_executor_sanitizes_leaf_exception(tmp_path: Path) -> None:
    executor = live.R2LiveExecutor(
        workspace=tmp_path,
        plan=_plan(),
        policy=R2DispatchPolicy.create(
            budget_id="r2-budget-v1",
            freeze_a_commit="c" * 40,
            maximum_wall_clock_seconds=100,
        ),
        environment={
            "OMNI_PROFILE": "fixture",
            "OMNI_BASE_URL": "https://example.omniapp.co",
        },
        attempt_runner=lambda **_: (_ for _ in ()).throw(RuntimeError("Bearer secret")),
    )
    with pytest.raises(live.R2LiveExecutorError, match="r2attempt-1") as captured:
        executor.execute(_attempt(), _target())
    assert "Bearer secret" not in str(captured.value)

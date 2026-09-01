"""Dry-default deployment leaf for one exact committed R2 semantic arm."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from .omni_semantic_deploy_cli import (
    ClientFactory,
    OmniDeploymentCliError,
    deployment_main,
)
from .r2_execution import R2ExecutionError, load_committed_r2_execution_plan
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION
from .r2_runtime_adapter import (
    R2RuntimeAdapterError,
    load_committed_r2_semantic_plans,
    prepare_r2_deployment_adapter,
)


DeploymentRunner = Callable[..., int]


def r2_deployment_main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    deployment_runner: DeploymentRunner = deployment_main,
) -> int:
    """Print an exact arm plan or explicitly delegate its public deployment."""
    arguments = _parser().parse_args(argv)
    plan = _load_execution_plan(arguments)
    semantic_plans = load_committed_r2_semantic_plans(
        arguments.workspace,
        plan=plan,
        condition=arguments.condition,
    )
    prepared = prepare_r2_deployment_adapter(
        plan,
        condition=arguments.condition,
        semantic_plans=semantic_plans,
    )
    workspace = arguments.workspace.resolve(strict=True)
    destination = workspace / prepared.output_root
    if destination.exists() or destination.is_symlink():
        raise R2RuntimeAdapterError("R2 deployment output root must be absent")
    if not arguments.execute_live_deployment:
        print(_json(prepared.public_dict()))
        return 0
    if not isinstance(arguments.profile, str) or not arguments.profile.strip():
        raise R2RuntimeAdapterError("live R2 deployment requires an Omni profile")
    try:
        return deployment_runner(
            [
                "--workspace",
                str(workspace),
                "--output-root",
                str(destination),
                "--run-id",
                prepared.deployment_run_id,
                "--profile",
                arguments.profile,
                "--max-workers",
                str(arguments.max_workers),
                "--minimum-request-interval-seconds",
                str(arguments.minimum_request_interval_seconds),
                "--execute-live-deployment",
            ],
            client_factory=client_factory,
            commit_observer=lambda _workspace: prepared.system_commit,
            bundle_loader=lambda _workspace, _commit: (
                dict(prepared.semantic_plans),
                {},
            ),
            identity_factory=prepared.remote_identity,
        )
    except OmniDeploymentCliError as error:
        raise R2RuntimeAdapterError(str(error)) from error


def r2_deployment_entrypoint() -> int:
    """Run the deployment leaf without leaking unexpected exception details."""
    try:
        return r2_deployment_main()
    except (R2ExecutionError, R2RuntimeAdapterError) as error:
        print(f"R2 deployment preparation failed: {error}", file=sys.stderr)
    except Exception:
        print("R2 deployment preparation failed: internal error", file=sys.stderr)
    return 1


def _load_execution_plan(arguments: argparse.Namespace):  # type: ignore[no-untyped-def]
    return load_committed_r2_execution_plan(
        arguments.workspace,
        system_commit=arguments.system_commit,
        output_root=arguments.output_root,
        arm_run_ids={
            CONTROL_CONDITION: arguments.control_run_id,
            TREATMENT_CONDITION: arguments.treatment_run_id,
        },
        deployment_run_ids={
            CONTROL_CONDITION: arguments.control_deployment_run_id,
            TREATMENT_CONDITION: arguments.treatment_deployment_run_id,
        },
        projected_attempt_cost_usd={
            CONTROL_CONDITION: arguments.control_projected_attempt_cost_usd,
            TREATMENT_CONDITION: arguments.treatment_projected_attempt_cost_usd,
        },
        budget_policy_sha256=arguments.budget_policy_sha256,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--control-run-id", required=True)
    parser.add_argument("--treatment-run-id", required=True)
    parser.add_argument("--control-deployment-run-id", required=True)
    parser.add_argument("--treatment-deployment-run-id", required=True)
    parser.add_argument("--control-projected-attempt-cost-usd", required=True)
    parser.add_argument("--treatment-projected-attempt-cost-usd", required=True)
    parser.add_argument("--budget-policy-sha256", required=True)
    parser.add_argument(
        "--condition",
        required=True,
        choices=(CONTROL_CONDITION, TREATMENT_CONDITION),
    )
    parser.add_argument("--profile")
    parser.add_argument("--max-workers", type=int, choices=range(1, 9), default=1)
    parser.add_argument("--minimum-request-interval-seconds", type=float, default=1.25)
    parser.add_argument("--execute-live-deployment", action="store_true")
    return parser


def _json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

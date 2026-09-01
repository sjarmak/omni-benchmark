"""Dry-preflight or receipt-gated execution of the complete paired R2 series."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .r2_dispatch import (
    R2DispatchError,
    R2DispatchPolicy,
    authorize_r2_dispatch,
    execute_r2_dispatch,
    prepare_r2_dispatch_inputs,
)
from .r2_execution import R2ExecutionError, load_committed_r2_execution_plan
from .r2_live_executor import (
    R2LiveExecutor,
    R2LiveExecutorError,
    prepare_r2_live_environment,
)
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION


class R2DispatchCliError(RuntimeError):
    """Raised before the paired dispatcher can cross its action boundary."""


def r2_dispatch_main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Print the complete preflight or execute only through the receipt gate."""
    arguments = _parser().parse_args(argv)
    plan = _load_execution_plan(arguments)
    policy = R2DispatchPolicy.create(
        budget_id=arguments.budget_id,
        freeze_a_commit=arguments.freeze_a_commit,
        maximum_wall_clock_seconds=arguments.maximum_wall_clock_seconds,
    )
    inputs = prepare_r2_dispatch_inputs(
        workspace=arguments.workspace,
        plan=plan,
        policy=policy,
        deployment_roots={
            CONTROL_CONDITION: arguments.control_deployment_root,
            TREATMENT_CONDITION: arguments.treatment_deployment_root,
        },
    )
    if not arguments.execute_live_series:
        print(_json(inputs.public_summary()))
        return 0
    if arguments.human_approval_receipt is None:
        raise R2DispatchCliError("live R2 series requires an action receipt")
    preflight = authorize_r2_dispatch(
        inputs,
        receipt_path=arguments.human_approval_receipt,
    )
    process_environment = prepare_r2_live_environment(
        os.environ if environment is None else environment
    )
    report = execute_r2_dispatch(
        preflight,
        executor_builder=lambda approved: R2LiveExecutor(
            workspace=approved.inputs.workspace,
            plan=approved.inputs.plan,
            policy=approved.inputs.policy,
            environment=process_environment,
        ),
    )
    print(_json(report.public_summary()))
    return 0


def r2_dispatch_entrypoint() -> int:
    """Keep credentials and provider details out of unexpected CLI failures."""
    try:
        return r2_dispatch_main()
    except (
        R2DispatchCliError,
        R2DispatchError,
        R2ExecutionError,
        R2LiveExecutorError,
    ) as error:
        print(f"R2 dispatch failed: {error}", file=sys.stderr)
    except Exception:
        print("R2 dispatch failed: internal error", file=sys.stderr)
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
    _add_common_arguments(parser)
    parser.add_argument("--human-approval-receipt", type=Path)
    parser.add_argument("--execute-live-series", action="store_true")
    return parser


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--control-run-id", required=True)
    parser.add_argument("--treatment-run-id", required=True)
    parser.add_argument("--control-deployment-run-id", required=True)
    parser.add_argument("--treatment-deployment-run-id", required=True)
    parser.add_argument("--control-deployment-root", type=Path, required=True)
    parser.add_argument("--treatment-deployment-root", type=Path, required=True)
    parser.add_argument("--control-projected-attempt-cost-usd", required=True)
    parser.add_argument("--treatment-projected-attempt-cost-usd", required=True)
    parser.add_argument("--budget-policy-sha256", required=True)
    parser.add_argument("--budget-id", required=True)
    parser.add_argument("--freeze-a-commit", required=True)
    parser.add_argument("--maximum-wall-clock-seconds", type=int, required=True)


def _json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

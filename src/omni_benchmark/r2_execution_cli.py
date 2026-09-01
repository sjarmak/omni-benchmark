"""Print or finalize the Git-bound offline R2 execution contract."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from .r2_execution import (
    R2ExecutionError,
    finalize_r2_generations,
    load_committed_r2_execution_plan,
)
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION


def r2_execution_main(argv: Sequence[str] | None = None) -> int:
    """Resolve one exact committed plan or finalize its complete raw attempts."""
    arguments = _parser().parse_args(argv)
    if arguments.dry_run_plan and arguments.finalization_destination is not None:
        raise R2ExecutionError("finalization destination is only valid with finalize")
    if arguments.finalize and arguments.finalization_destination is None:
        raise R2ExecutionError("finalize requires a destination")
    plan = load_committed_r2_execution_plan(
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
    if arguments.dry_run_plan:
        print(_json(plan.public_dict()))
        return 0
    assert arguments.finalization_destination is not None
    finalized = finalize_r2_generations(
        arguments.workspace,
        plan=plan,
        destination=arguments.finalization_destination,
    )
    workspace = arguments.workspace.resolve(strict=True)
    counts = Counter(item.condition for item in plan.attempts)
    print(
        _json(
            {
                "control": {
                    "path": finalized.control_path.relative_to(workspace).as_posix(),
                    "record_count": counts[CONTROL_CONDITION],
                    "sha256": finalized.control_sha256,
                },
                "execution_plan_sha256": plan.sha256,
                "manifest": {
                    "path": finalized.manifest_path.relative_to(workspace).as_posix(),
                    "sha256": finalized.manifest_sha256,
                },
                "schema_version": 1,
                "treatment": {
                    "path": finalized.treatment_path.relative_to(workspace).as_posix(),
                    "record_count": counts[TREATMENT_CONDITION],
                    "sha256": finalized.treatment_sha256,
                },
            }
        )
    )
    return 0


def r2_execution_entrypoint() -> int:
    """Run the offline command without leaking unexpected exception details."""
    try:
        return r2_execution_main()
    except R2ExecutionError as error:
        print(f"R2 execution preparation failed: {error}", file=sys.stderr)
    except Exception:
        print("R2 execution preparation failed: internal error", file=sys.stderr)
    return 1


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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run-plan", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    parser.add_argument("--finalization-destination", type=Path)
    return parser


def _json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

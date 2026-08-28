"""Print the public baseline schedule and uniform cost scenario without execution."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from .baseline_batch import (
    BASELINE_CONDITIONS,
    BaselineBatchError,
    BatchBudget,
    ImmutableAttemptRepository,
    apply_committed_direct_baseline_exclusions,
    direct_only_baseline_schedule,
    load_committed_baseline_schedule,
    project_baseline_cost,
    run_baseline_batch,
)
from .baseline_batch_live import (
    DatabaseEnvironmentDirectory,
    LiveBaselineDispatcher,
    build_execution_plan,
    direct_concurrency_canary_schedule,
    project_condition_cost_scenario,
    verify_deployment_gate,
)
from .c1_retrieval_sensitivity import (
    load_committed_c1_retrieval_sensitivity_schedule,
    validate_c1_retrieval_sensitivity_invocation,
)

_CHILD_ENVIRONMENT_KEYS = frozenset(
    {
        "HOME",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_PROXY",
        "OMNI_API_TOKEN",
        "OMNI_BASE_URL",
        "OMNI_CONFIG_PATH",
        "OMNI_PROFILE",
        "PATH",
        "PYTHONDONTWRITEBYTECODE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        "XDG_CONFIG_HOME",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observed-attempt-cost-usd", required=True)
    parser.add_argument("--cost-ceiling-usd", required=True)
    parser.add_argument("--c1-retrieval-sensitivity", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run-execution-plan", action="store_true")
    mode.add_argument("--execute-live-baseline", action="store_true")
    mode.add_argument("--execute-live-direct-baseline", action="store_true")
    mode.add_argument("--execute-live-direct-concurrency-canary", action="store_true")
    parser.add_argument("--freeze-a-commit")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--claude-config-dir", type=Path, action="append")
    parser.add_argument("--observed-condition-cost", action="append")
    parser.add_argument("--deployment-root", type=Path)
    parser.add_argument("--deployment-run-id")
    parser.add_argument("--database-environment-dir", type=Path)
    parser.add_argument("--attempt-cost-ceiling-usd", type=float)
    parser.add_argument("--maximum-concurrency", type=int, default=4)
    parser.add_argument("--subprocess-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--remaining-wall-clock-seconds", type=float)
    return parser


def baseline_batch_main(argv: Sequence[str] | None = None) -> int:
    """Project, dry-run, or explicitly dispatch the committed public baseline."""
    arguments = _parser().parse_args(argv)
    if arguments.c1_retrieval_sensitivity:
        validate_c1_retrieval_sensitivity_invocation(
            run_id=arguments.run_id,
            output_root=arguments.output_root,
            cost_ceiling_usd=arguments.cost_ceiling_usd,
            execute_live=arguments.execute_live_direct_baseline,
            remaining_wall_clock_seconds=arguments.remaining_wall_clock_seconds,
            attempt_cost_ceiling_usd=arguments.attempt_cost_ceiling_usd,
        )
    schedule = (
        load_committed_c1_retrieval_sensitivity_schedule(
            arguments.workspace,
            arguments.system_commit,
            run_id=arguments.run_id,
        )
        if arguments.c1_retrieval_sensitivity
        else load_committed_baseline_schedule(
            arguments.workspace,
            arguments.system_commit,
            run_id=arguments.run_id,
        )
    )
    if arguments.execute_live_direct_concurrency_canary:
        schedule = direct_concurrency_canary_schedule(schedule)
    elif (
        arguments.execute_live_direct_baseline
        and not arguments.c1_retrieval_sensitivity
    ):
        schedule = apply_committed_direct_baseline_exclusions(
            arguments.workspace,
            arguments.system_commit,
            direct_only_baseline_schedule(schedule),
        )
    projection = project_baseline_cost(
        schedule,
        observed_attempt_cost_usd=arguments.observed_attempt_cost_usd,
        cost_ceiling_usd=arguments.cost_ceiling_usd,
    )
    if arguments.c1_retrieval_sensitivity and not (
        arguments.dry_run_execution_plan or arguments.execute_live_direct_baseline
    ):
        raise BaselineBatchError(
            "C1 retrieval sensitivity requires planning or live direct execution"
        )
    if (
        arguments.dry_run_execution_plan
        or arguments.execute_live_baseline
        or arguments.execute_live_direct_baseline
        or arguments.execute_live_direct_concurrency_canary
    ):
        required = {
            "freeze A commit": arguments.freeze_a_commit,
            "output root": arguments.output_root,
            "Claude config directory": arguments.claude_config_dir,
            "condition cost observations": arguments.observed_condition_cost,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise BaselineBatchError(
                f"execution planning requires {', '.join(missing)}"
            )
        plan = build_execution_plan(
            schedule,
            workspace=arguments.workspace.resolve(strict=True),
            output_root=arguments.output_root,
            claude_config_directories=tuple(arguments.claude_config_dir),
            freeze_a_commit=arguments.freeze_a_commit,
        )
        scenario = _successful_canary_scenario(
            schedule, arguments.observed_condition_cost
        )
        if arguments.execute_live_baseline:
            return _execute_live(
                arguments,
                schedule,
                plan,
                scenario.as_dict(),
                require_deployment=True,
            )
        if (
            arguments.execute_live_direct_baseline
            or arguments.execute_live_direct_concurrency_canary
        ):
            return _execute_live(
                arguments,
                schedule,
                plan,
                scenario.as_dict(),
                require_deployment=False,
            )
        print(
            json.dumps(
                {
                    "execution_plan": plan.public_dict(),
                    "live_execution": "not_started",
                    "schedule_identity": schedule.public_identity(),
                    "successful_canary_cost_scenario": scenario.as_dict(),
                },
                allow_nan=False,
                sort_keys=True,
            )
        )
        return 0
    output = {
        **projection.as_dict(),
        "conditions": list(BASELINE_CONDITIONS),
        "database_count": len({attempt.database for attempt in schedule.attempts}),
        "eligible_manifest_sha256": schedule.eligible_manifest_sha256,
        "live_execution": "disabled_pending_d045_replay",
        "projection_basis": (
            "one_observed_failed_C1_attempt_applied_uniformly_for_capacity_planning"
        ),
        "run_id": arguments.run_id,
        "schedule_sha256": schedule.sha256,
        "source_commit": schedule.source_commit,
        "train_ids_sha256": schedule.train_ids_sha256,
    }
    print(json.dumps(output, allow_nan=False, sort_keys=True))
    return 0


def _condition_costs(values: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        condition, separator, cost = value.partition("=")
        if not separator or condition not in BASELINE_CONDITIONS or condition in result:
            raise BaselineBatchError(
                "condition costs must be unique CONDITION=USD values"
            )
        result[condition] = cost
    return result


def _successful_canary_scenario(schedule, values: Sequence[str]):
    return project_condition_cost_scenario(
        schedule,
        observed_condition_cost_usd=_condition_costs(values),
    )


def _execute_live(
    arguments,
    schedule,
    plan,
    scenario: Mapping[str, object],
    *,
    require_deployment: bool,
) -> int:
    required = {
        "database environment directory": arguments.database_environment_dir,
        "attempt cost ceiling": arguments.attempt_cost_ceiling_usd,
    }
    if require_deployment:
        required = {
            **required,
            "deployment root": arguments.deployment_root,
            "deployment run ID": arguments.deployment_run_id,
        }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise BaselineBatchError(f"live baseline requires {', '.join(missing)}")
    databases = {attempt.database for attempt in schedule.attempts}
    targets = (
        verify_deployment_gate(
            arguments.deployment_root, arguments.deployment_run_id, databases
        )
        if require_deployment
        else None
    )
    workspace = arguments.workspace.resolve(strict=True)
    dispatcher = LiveBaselineDispatcher(
        plan,
        database_environments=DatabaseEnvironmentDirectory(
            workspace, arguments.database_environment_dir
        ),
        common_environment=_child_environment(os.environ),
        timeout_seconds=arguments.subprocess_timeout_seconds,
        deployment_targets=targets,
    )
    report = run_baseline_batch(
        schedule,
        repository=ImmutableAttemptRepository(workspace, arguments.output_root),
        executor=dispatcher,
        maximum_concurrency=arguments.maximum_concurrency,
        budget=BatchBudget(
            cost_ceiling_usd=float(arguments.cost_ceiling_usd),
            attempt_cost_ceiling_usd=arguments.attempt_cost_ceiling_usd,
            unobservable_cost_reservation_conditions=(
                frozenset({"C4"}) if require_deployment else frozenset()
            ),
        ),
    )
    print(
        json.dumps(
            {
                "execution_plan_sha256": plan.sha256,
                "live_execution": report.as_dict(),
                "schedule_identity": schedule.public_identity(),
                "successful_canary_cost_scenario": dict(scenario),
            },
            allow_nan=False,
            sort_keys=True,
        )
    )
    return 0


def _child_environment(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in environment.items()
        if key in _CHILD_ENVIRONMENT_KEYS
    }

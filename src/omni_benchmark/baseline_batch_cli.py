"""Print the public baseline schedule and uniform cost scenario without execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from .baseline_batch import (
    BASELINE_CONDITIONS,
    BaselineBatchError,
    BatchBudget,
    BatchStopPolicy,
    ImmutableAttemptRepository,
    apply_committed_direct_baseline_exclusions,
    c4_dev_a_experiment_schedule,
    direct_only_baseline_schedule,
    load_committed_baseline_schedule,
    project_baseline_cost,
    run_baseline_batch,
)
from .baseline_batch_live import (
    DatabaseEnvironmentDirectory,
    DeploymentTarget,
    LiveBaselineDispatcher,
    build_execution_plan,
    c4_concurrency_canary_schedule,
    direct_concurrency_canary_schedule,
    project_condition_cost_scenario,
    verify_deployment_gate,
    verify_derived_deployment_gate,
)
from .c4_production_approval import (
    C4ProductionApprovalError,
    consume_c4_production_approval,
    validate_c4_production_approval,
)
from .claude_lease_preflight import (
    ClaudeLeasePreflightError,
    verify_lease_window,
)
from .c1_retrieval_sensitivity import (
    load_committed_c1_retrieval_sensitivity_schedule,
    validate_c1_retrieval_sensitivity_invocation,
)
from .omni_cli import OmniCliError, OmniCliSettings

_C4_ARM_SPEC_PATH = Path("config/conditions/c4-public-baseline-arm-v1.json")

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
    mode.add_argument("--dry-run-c4-baseline", action="store_true")
    mode.add_argument("--dry-run-e02-dev-a-experiment", action="store_true")
    mode.add_argument("--dry-run-c5-dev-a-experiment", action="store_true")
    mode.add_argument("--execute-live-baseline", action="store_true")
    mode.add_argument("--execute-live-direct-baseline", action="store_true")
    mode.add_argument("--execute-live-direct-concurrency-canary", action="store_true")
    mode.add_argument("--execute-live-c4-baseline", action="store_true")
    mode.add_argument("--execute-live-c4-concurrency-canary", action="store_true")
    mode.add_argument("--execute-live-e02-dev-a-experiment", action="store_true")
    mode.add_argument("--execute-live-c5-dev-a-experiment", action="store_true")
    parser.add_argument("--freeze-a-commit")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--claude-config-dir", type=Path, action="append")
    parser.add_argument("--observed-condition-cost", action="append")
    parser.add_argument("--deployment-root", type=Path)
    parser.add_argument("--deployment-run-id")
    parser.add_argument("--database-environment-dir", type=Path)
    parser.add_argument("--attempt-cost-ceiling-usd", type=float)
    parser.add_argument("--maximum-concurrency", type=int, default=4)
    parser.add_argument("--subprocess-timeout-seconds", type=float, default=900.0)
    parser.add_argument("--identity-stable-until")
    parser.add_argument("--maximum-wall-clock-seconds", type=float)
    parser.add_argument("--remaining-wall-clock-seconds", type=float)
    parser.add_argument("--human-approval-receipt", type=Path)
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
    e02_mode = (
        arguments.dry_run_e02_dev_a_experiment
        or arguments.execute_live_e02_dev_a_experiment
    )
    c5_mode = (
        arguments.dry_run_c5_dev_a_experiment
        or arguments.execute_live_c5_dev_a_experiment
    )
    experiment_mode = e02_mode or c5_mode
    c4_mode = (
        arguments.dry_run_c4_baseline
        or arguments.execute_live_c4_baseline
        or arguments.execute_live_c4_concurrency_canary
        or experiment_mode
    )
    if c4_mode:
        schedule = c4_dev_a_experiment_schedule(
            arguments.workspace, arguments.system_commit, schedule
        )
        if arguments.execute_live_c4_concurrency_canary:
            schedule = c4_concurrency_canary_schedule(schedule)
    elif arguments.execute_live_direct_concurrency_canary:
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
        or arguments.dry_run_c4_baseline
        or arguments.execute_live_baseline
        or arguments.execute_live_direct_baseline
        or arguments.execute_live_direct_concurrency_canary
        or arguments.execute_live_c4_baseline
        or arguments.execute_live_c4_concurrency_canary
        or experiment_mode
    ):
        required = {
            "freeze A commit": arguments.freeze_a_commit,
            "output root": arguments.output_root,
            "condition cost observations": arguments.observed_condition_cost,
        }
        if any(attempt.condition != "C4" for attempt in schedule.attempts):
            required["Claude config directory"] = arguments.claude_config_dir
        if c4_mode:
            required["maximum wall-clock seconds"] = (
                arguments.maximum_wall_clock_seconds
            )
            if arguments.maximum_concurrency > 5:
                raise BaselineBatchError(
                    "C4 concurrency cannot exceed Omni's limit of 5"
                )
        if experiment_mode:
            required["deployment root"] = arguments.deployment_root
            required["deployment run ID"] = arguments.deployment_run_id
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise BaselineBatchError(
                f"execution planning requires {', '.join(missing)}"
            )
        if c4_mode:
            BatchStopPolicy(arguments.maximum_wall_clock_seconds)
        plan = build_execution_plan(
            schedule,
            workspace=arguments.workspace.resolve(strict=True),
            output_root=arguments.output_root,
            claude_config_directories=tuple(arguments.claude_config_dir or ()),
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
                derived_deployment=False,
                require_human_approval=False,
                telemetry_only_c4=False,
                expected_deployment_source_commit=None,
            )
        if (
            arguments.execute_live_e02_dev_a_experiment
            or arguments.execute_live_c5_dev_a_experiment
        ):
            return _execute_live(
                arguments,
                schedule,
                plan,
                scenario.as_dict(),
                require_deployment=True,
                derived_deployment=False,
                require_human_approval=True,
                telemetry_only_c4=True,
                expected_deployment_source_commit=arguments.system_commit,
            )
        if (
            arguments.execute_live_c4_baseline
            or arguments.execute_live_c4_concurrency_canary
        ):
            return _execute_live(
                arguments,
                schedule,
                plan,
                scenario.as_dict(),
                require_deployment=True,
                derived_deployment=True,
                require_human_approval=arguments.execute_live_c4_baseline,
                telemetry_only_c4=True,
                expected_deployment_source_commit=None,
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
                derived_deployment=False,
                require_human_approval=False,
                telemetry_only_c4=False,
                expected_deployment_source_commit=None,
            )
        deployment_targets = None
        if arguments.dry_run_c4_baseline:
            deployment_targets = verify_derived_deployment_gate(
                arguments.workspace,
                arguments.system_commit,
                _C4_ARM_SPEC_PATH,
                {attempt.database for attempt in schedule.attempts},
            )
        elif arguments.dry_run_e02_dev_a_experiment or (
            arguments.dry_run_c5_dev_a_experiment
        ):
            deployment_targets = verify_deployment_gate(
                arguments.deployment_root,
                arguments.deployment_run_id,
                {attempt.database for attempt in schedule.attempts},
                expected_source_commit=arguments.system_commit,
            )
        print(
            json.dumps(
                {
                    "execution_plan": plan.public_dict(),
                    "cost_projection": projection.as_dict(),
                    "cost_role": (
                        "telemetry_only_not_an_operational_stop"
                        if c4_mode
                        else "operational_budget"
                    ),
                    "deployment_target_count": (
                        None if deployment_targets is None else len(deployment_targets)
                    ),
                    "live_execution": "not_started",
                    "operational_stop": (
                        None
                        if not c4_mode
                        else {
                            "maximum_wall_clock_seconds": arguments.maximum_wall_clock_seconds,
                            "policy": "finish_started_database_condition_blocks",
                        }
                    ),
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


_LIVE_MODE_FLAGS = (
    "execute_live_baseline",
    "execute_live_direct_baseline",
    "execute_live_direct_concurrency_canary",
    "execute_live_c4_baseline",
    "execute_live_c4_concurrency_canary",
    "execute_live_e02_dev_a_experiment",
    "execute_live_c5_dev_a_experiment",
)


def _semantic_candidate_kind(arguments) -> str:
    """Name the committed semantic candidate this live arm must read back."""
    if getattr(arguments, "execute_live_e02_dev_a_experiment", False):
        return "e02"
    if getattr(arguments, "execute_live_c5_dev_a_experiment", False):
        return "c5"
    return "baseline"


def _identity_stable_until(value: str | None) -> float | None:
    """Read the operator's rotation boundary as epoch seconds."""
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise BaselineBatchError(
            "identity stable-until must be an ISO 8601 timestamp"
        ) from error
    if moment.tzinfo is None:
        raise BaselineBatchError(
            "identity stable-until must carry a UTC offset; a naive timestamp "
            "silently means a different instant on a differently configured host"
        )
    return moment.timestamp()


def _verify_lease_window(arguments, plan) -> None:
    """Refuse a live launch whose leased identities can change mid-attempt."""
    if not any(getattr(arguments, flag, False) for flag in _LIVE_MODE_FLAGS):
        return
    directories = tuple(plan.claude_config_directories)
    if not directories:
        return
    try:
        verify_lease_window(
            directories,
            attempt_seconds=arguments.subprocess_timeout_seconds,
            identity_stable_until=_identity_stable_until(
                arguments.identity_stable_until
            ),
        )
    except ClaudeLeasePreflightError as error:
        raise BaselineBatchError(f"lease preflight failed: {error}") from error


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


def _deployment_targets_sha256(
    targets: Mapping[str, DeploymentTarget],
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                database: {
                    "branch_id": target.branch_id,
                    "model_id": target.model_id,
                    "semantic_model_sha256": target.semantic_model_sha256,
                }
                for database, target in sorted(targets.items())
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _execute_live(
    arguments,
    schedule,
    plan,
    scenario: Mapping[str, object],
    *,
    require_deployment: bool,
    derived_deployment: bool,
    require_human_approval: bool,
    telemetry_only_c4: bool,
    expected_deployment_source_commit: str | None,
) -> int:
    required = {"attempt cost ceiling": arguments.attempt_cost_ceiling_usd}
    if any(attempt.condition != "C4" for attempt in schedule.attempts):
        required["database environment directory"] = arguments.database_environment_dir
    if require_deployment and not derived_deployment:
        required = {
            **required,
            "deployment root": arguments.deployment_root,
            "deployment run ID": arguments.deployment_run_id,
        }
    if require_human_approval:
        required["human approval receipt"] = arguments.human_approval_receipt
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise BaselineBatchError(f"live baseline requires {', '.join(missing)}")
    databases = {attempt.database for attempt in schedule.attempts}
    if derived_deployment:
        targets = verify_derived_deployment_gate(
            arguments.workspace,
            arguments.system_commit,
            _C4_ARM_SPEC_PATH,
            databases,
        )
    elif require_deployment:
        targets = verify_deployment_gate(
            arguments.deployment_root,
            arguments.deployment_run_id,
            databases,
            expected_source_commit=expected_deployment_source_commit,
        )
    else:
        targets = None
    workspace = arguments.workspace.resolve(strict=True)
    common_environment = _child_environment(os.environ)
    if derived_deployment or telemetry_only_c4:
        # Every deployed-semantics arm reaches Omni through the child process, so a
        # missing provider setting has to fail here rather than after a one-time
        # approval receipt is already spent.
        common_environment = _validated_c4_child_environment(common_environment)
    budget = BatchBudget(
        cost_ceiling_usd=float(arguments.cost_ceiling_usd),
        attempt_cost_ceiling_usd=arguments.attempt_cost_ceiling_usd,
        unobservable_cost_reservation_conditions=(
            frozenset({"C4"})
            if require_deployment and not derived_deployment and not telemetry_only_c4
            else frozenset()
        ),
        telemetry_only_conditions=(
            frozenset({"C4"}) if telemetry_only_c4 else frozenset()
        ),
    )
    if require_human_approval:
        assert targets is not None
        binding = {
            "condition": "C4",
            "deployment_sha256": _deployment_targets_sha256(targets),
            "execution_plan_sha256": plan.sha256,
            "output_root": arguments.output_root.as_posix(),
            "run_id": arguments.run_id,
            "schedule_sha256": schedule.sha256,
            "system_commit": arguments.system_commit,
        }
        try:
            approval = validate_c4_production_approval(
                workspace,
                arguments.human_approval_receipt,
                binding,
            )
            consume_c4_production_approval(
                workspace,
                Path("experiments/approvals/c4-production"),
                approval,
            )
        except C4ProductionApprovalError as error:
            raise BaselineBatchError(str(error)) from error
    database_environments = (
        None
        if arguments.database_environment_dir is None
        else DatabaseEnvironmentDirectory(workspace, arguments.database_environment_dir)
    )
    _verify_lease_window(arguments, plan)
    dispatcher = LiveBaselineDispatcher(
        plan,
        database_environments=database_environments,
        common_environment=common_environment,
        timeout_seconds=arguments.subprocess_timeout_seconds,
        deployment_targets=targets,
        c4_budget=budget if targets is not None else None,
        semantic_candidate_kind=_semantic_candidate_kind(arguments),
    )
    report = run_baseline_batch(
        schedule,
        repository=ImmutableAttemptRepository(workspace, arguments.output_root),
        executor=dispatcher,
        maximum_concurrency=arguments.maximum_concurrency,
        budget=budget,
        stop_policy=(
            BatchStopPolicy(arguments.maximum_wall_clock_seconds)
            if all(attempt.condition == "C4" for attempt in schedule.attempts)
            else None
        ),
    )
    print(
        json.dumps(
            {
                "cost_role": (
                    "telemetry_only_not_an_operational_stop"
                    if telemetry_only_c4
                    else "operational_budget"
                ),
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


def _validated_c4_child_environment(
    environment: Mapping[str, str],
) -> dict[str, str]:
    child = _child_environment(environment)
    try:
        OmniCliSettings.from_environment({**child, "OMNI_MODEL_ID": "preflight"})
    except OmniCliError as error:
        raise BaselineBatchError(str(error)) from error
    return child

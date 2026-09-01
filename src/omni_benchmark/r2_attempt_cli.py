"""Dry plan or run one exact R2 attempt through the production Omni capture."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from . import omni_probe_cli as omni_probe
from .omni_capture import OmniJobCapture, OmniJobClient, OmniProbeResult
from .omni_cli import OmniCliClient, OmniCliSettings
from .omni_credit_cost import capture_with_cost
from .omni_probe_preflight import CliVersionObserver, observe_omni_cli_version
from .omni_semantic_deployment import (
    OmniSemanticDeploymentError,
    verified_semantic_deployment_sha256,
)
from .r2_execution import (
    R2AttemptArtifacts,
    R2ExecutionError,
    R2ExecutionPlan,
    load_committed_r2_execution_plan,
    write_r2_attempt_artifacts,
)
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION
from .r2_runtime_adapter import (
    R2RuntimeAdapterError,
    load_committed_r2_semantic_plans,
    prepare_r2_attempt_adapter,
    prepare_r2_attempt_dry_plan,
    r2_generation_record,
    validate_r2_probe_plan,
)


ClientFactory = Callable[[OmniCliSettings], OmniJobClient]


def r2_attempt_main(
    argv: Sequence[str] | None = None,
) -> int:
    """Print one credential-free attempt plan; live dispatch remains closed."""
    arguments = _parser().parse_args(argv)
    plan = _load_execution_plan(arguments)
    dry = prepare_r2_attempt_dry_plan(plan, arguments.attempt_id)
    print(_json(dry.public_dict()))
    return 0


def execute_r2_attempt(
    *,
    plan: R2ExecutionPlan,
    attempt_id: str,
    deployment_target: object,
    probe_arguments: argparse.Namespace,
    environment: dict[str, str],
    client_factory: ClientFactory | None,
    sleep: Callable[[float], None] | None,
    cli_version_observer: CliVersionObserver | None,
) -> tuple[R2AttemptArtifacts, OmniProbeResult]:
    """Capture and publish one attempt after local and deployment preflight."""
    attempt = plan.attempt(attempt_id)
    probe_plan = omni_probe._prepare_probe(
        probe_arguments,
        environment,
        observe_omni_cli_version
        if cli_version_observer is None
        else cli_version_observer,
    )
    validate_r2_probe_plan(plan, attempt_id=attempt_id, probe_plan=probe_plan)
    prepared_target = prepare_r2_attempt_adapter(
        plan,
        attempt_id=attempt_id,
        deployment_target=deployment_target,
    )
    if (
        getattr(probe_plan.settings, "model_id", None) != prepared_target.model_id
        or getattr(probe_plan.settings, "branch_id", None) != prepared_target.branch_id
    ):
        raise R2RuntimeAdapterError(
            "R2 probe target does not match the verified deployment"
        )
    semantic_plan = load_committed_r2_semantic_plans(
        probe_plan.workspace,
        plan=plan,
        condition=attempt.condition,
    )[attempt.database]
    factory = client_factory or (
        lambda settings: OmniCliClient(settings, environment=probe_plan.environment)
    )
    client = factory(probe_plan.settings)
    omni_probe._verify_authentication(client)
    try:
        observed_semantic_sha256 = verified_semantic_deployment_sha256(
            semantic_plan,
            client.read_semantic_model(),
        )
    except (KeyError, OmniSemanticDeploymentError, ValueError) as error:
        raise R2RuntimeAdapterError(
            "R2 semantic model drifted after verified deployment"
        ) from error
    if observed_semantic_sha256 != attempt.semantic_model_sha256:
        raise R2RuntimeAdapterError(
            "R2 semantic model drifted after verified deployment"
        )
    options: dict[str, Any] = {
        "maximum_status_checks": probe_plan.specs.condition.maximum_status_checks,
        "poll_schedule_seconds": probe_plan.specs.condition.poll_schedule_seconds,
    }
    if sleep is not None:
        options["sleep"] = sleep
    result = capture_with_cost(
        client=client,
        environment=probe_plan.environment,
        capture=lambda: OmniJobCapture(client, probe_plan.store, **options).probe(
            probe_plan.question
        ),
    )
    record = r2_generation_record(
        workspace=probe_plan.workspace,
        plan=plan,
        attempt_id=attempt_id,
        probe=result,
        probe_plan=probe_plan,
    )
    artifacts = write_r2_attempt_artifacts(
        probe_plan.workspace,
        plan=plan,
        attempt_id=attempt_id,
        record=record,
    )
    return artifacts, result


def r2_attempt_entrypoint() -> int:
    """Run the attempt leaf without leaking unexpected exception details."""
    try:
        return r2_attempt_main()
    except (
        R2ExecutionError,
        R2RuntimeAdapterError,
        omni_probe.OmniProbeCliError,
    ) as error:
        print(f"R2 attempt preparation failed: {error}", file=sys.stderr)
    except Exception:
        print("R2 attempt preparation failed: internal error", file=sys.stderr)
    return 1


def _load_execution_plan(arguments: argparse.Namespace) -> R2ExecutionPlan:
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
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--dry-run-attempt", action="store_true", required=True)
    return parser


def _json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

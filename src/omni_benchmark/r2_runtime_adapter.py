"""Exact adapters between the frozen R2 contract and existing Omni primitives.

This module has no series loop and performs no action on import.  Its pure plans
bind one arm or one attempt to the Git-authenticated R2 execution plan; the
caller remains responsible for the separately approved live-action boundary.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from . import omni_attempt, r2_execution
from .artifact_store import StoredArtifact
from .omni_attempt import C4AttemptSpec
from .omni_capture import OmniProbeResult
from .omni_credit_cost import COST_UNAVAILABLE_JOB_API
from .omni_result_adapter import reject_forbidden_keys
from .omni_semantic_deployment import (
    OmniSemanticDeploymentError,
    OmniSemanticDeploymentPlan,
    build_semantic_deployment_plan,
    semantic_deployment_sha256,
)
from .r2_execution import (
    R2AttemptArtifacts,
    R2ExecutionPlan,
    R2PlannedAttempt,
)
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION


class R2RuntimeAdapterError(ValueError):
    """Raised before an R2 runtime identity can drift from its frozen plan."""


_CONDITIONS = (CONTROL_CONDITION, TREATMENT_CONDITION)
_CONDITION_DIRECTORIES = {
    CONTROL_CONDITION: "r2-c5b",
    TREATMENT_CONDITION: "r2-m1",
}
_DEPLOYMENT_ROOT = Path("experiments/deployments")


@dataclass(frozen=True, slots=True)
class R2DeploymentAdapterPlan:
    """One complete arm deployment selected from the exact R2 plan."""

    condition: str
    deployment_run_id: str
    execution_plan_sha256: str
    output_root: Path
    remote_identities: Mapping[str, str]
    semantic_model_sha256s: Mapping[str, str]
    semantic_plans: Mapping[str, OmniSemanticDeploymentPlan]
    system_commit: str

    def remote_identity(self, database: str) -> tuple[str, str]:
        try:
            identity = self.remote_identities[database]
        except KeyError as error:
            raise R2RuntimeAdapterError(
                "database is absent from the R2 deployment plan"
            ) from error
        return identity, identity

    def public_dict(self) -> dict[str, object]:
        return {
            "condition": self.condition,
            "databases": [
                {
                    "database": database,
                    "deployment_identity": self.remote_identities[database],
                    "semantic_model_sha256": self.semantic_model_sha256s[database],
                }
                for database in sorted(self.remote_identities)
            ],
            "deployment_run_id": self.deployment_run_id,
            "execution_plan_sha256": self.execution_plan_sha256,
            "live_execution": "not_started",
            "output_root": self.output_root.as_posix(),
            "schema_version": 1,
            "series_id": r2_execution.SERIES_ID,
            "system_commit": self.system_commit,
        }


@dataclass(frozen=True, slots=True)
class R2AttemptDryPlan:
    """Credential-free identity for one member of the frozen paired schedule."""

    attempt: R2PlannedAttempt
    execution_plan_sha256: str
    system_commit: str

    def public_dict(self) -> dict[str, object]:
        return {
            **self.attempt.public_dict(),
            "execution_plan_sha256": self.execution_plan_sha256,
            "live_execution": "not_started",
            "schema_version": 1,
            "series_id": r2_execution.SERIES_ID,
            "system_commit": self.system_commit,
        }


@dataclass(frozen=True, slots=True)
class R2AttemptAdapterPlan:
    """One attempt bound to a complete verified deployment target."""

    attempt: R2PlannedAttempt
    branch_id: str
    branch_name: str
    execution_plan_sha256: str
    model_id: str
    model_name: str
    system_commit: str

    def public_dict(self) -> dict[str, object]:
        return {
            **self.attempt.public_dict(),
            "branch_id": self.branch_id,
            "branch_name": self.branch_name,
            "execution_plan_sha256": self.execution_plan_sha256,
            "live_execution": "not_started",
            "model_id": self.model_id,
            "model_name": self.model_name,
            "schema_version": 1,
            "series_id": r2_execution.SERIES_ID,
            "system_commit": self.system_commit,
        }


def prepare_r2_deployment_adapter(
    plan: R2ExecutionPlan,
    *,
    condition: str,
    semantic_plans: Mapping[str, OmniSemanticDeploymentPlan],
) -> R2DeploymentAdapterPlan:
    """Bind one exact arm to authenticated semantic plans without product access."""
    _require_execution_plan(plan)
    selected_condition = _condition(condition)
    attempts = tuple(
        attempt for attempt in plan.attempts if attempt.condition == selected_condition
    )
    if not attempts:
        raise R2RuntimeAdapterError("R2 deployment condition has no attempts")
    databases = tuple(sorted({attempt.database for attempt in attempts}))
    if set(semantic_plans) != set(databases):
        raise R2RuntimeAdapterError(
            "R2 semantic plan coverage does not match the scheduled arm"
        )
    deployment_run_ids = {attempt.deployment_run_id for attempt in attempts}
    if len(deployment_run_ids) != 1:
        raise R2RuntimeAdapterError("R2 deployment run identity is inconsistent")
    deployment_run_id = next(iter(deployment_run_ids))
    identities: dict[str, str] = {}
    digests: dict[str, str] = {}
    plans: dict[str, OmniSemanticDeploymentPlan] = {}
    for database in databases:
        database_attempts = tuple(
            attempt for attempt in attempts if attempt.database == database
        )
        database_identities = {
            attempt.deployment_identity for attempt in database_attempts
        }
        database_digests = {
            attempt.semantic_model_sha256 for attempt in database_attempts
        }
        if len(database_identities) != 1:
            raise R2RuntimeAdapterError("R2 deployment identity is inconsistent")
        if len(database_digests) != 1:
            raise R2RuntimeAdapterError("R2 semantic identity is inconsistent")
        semantic_plan = semantic_plans[database]
        observed_database = getattr(semantic_plan, "database", database)
        if observed_database != database:
            raise R2RuntimeAdapterError(
                "R2 semantic plan database does not match the schedule"
            )
        try:
            observed_digest = semantic_deployment_sha256(semantic_plan)
        except OmniSemanticDeploymentError as error:
            raise R2RuntimeAdapterError("R2 semantic plan is invalid") from error
        expected_digest = next(iter(database_digests))
        if observed_digest != expected_digest:
            raise R2RuntimeAdapterError(
                "R2 semantic plan does not match the execution plan"
            )
        identities[database] = next(iter(database_identities))
        digests[database] = expected_digest
        plans[database] = semantic_plan
    return R2DeploymentAdapterPlan(
        condition=selected_condition,
        deployment_run_id=deployment_run_id,
        execution_plan_sha256=plan.sha256,
        output_root=_DEPLOYMENT_ROOT / deployment_run_id,
        remote_identities=MappingProxyType(identities),
        semantic_model_sha256s=MappingProxyType(digests),
        semantic_plans=MappingProxyType(plans),
        system_commit=plan.system_commit,
    )


def prepare_r2_attempt_dry_plan(
    plan: R2ExecutionPlan, attempt_id: str
) -> R2AttemptDryPlan:
    """Select one attempt without reading deployments, credentials, or questions."""
    _require_execution_plan(plan)
    attempt = plan.attempt(attempt_id)
    return R2AttemptDryPlan(
        attempt=attempt,
        execution_plan_sha256=plan.sha256,
        system_commit=plan.system_commit,
    )


def prepare_r2_attempt_adapter(
    plan: R2ExecutionPlan,
    *,
    attempt_id: str,
    deployment_target: object,
) -> R2AttemptAdapterPlan:
    """Require the selected attempt's exact model, branch, and semantic digest."""
    dry = prepare_r2_attempt_dry_plan(plan, attempt_id)
    attempt = dry.attempt
    branch_id = getattr(deployment_target, "branch_id", None)
    branch_name = getattr(deployment_target, "branch_name", branch_id)
    model_id = getattr(deployment_target, "model_id", None)
    model_name = getattr(deployment_target, "model_name", model_id)
    semantic_model_sha256 = getattr(deployment_target, "semantic_model_sha256", None)
    if (
        not isinstance(branch_id, str)
        or not branch_id
        or not isinstance(model_id, str)
        or not model_id
        or branch_name != attempt.deployment_identity
        or model_name != attempt.deployment_identity
    ):
        raise R2RuntimeAdapterError(
            "verified deployment identity does not match the R2 attempt"
        )
    if semantic_model_sha256 != attempt.semantic_model_sha256:
        raise R2RuntimeAdapterError(
            "verified deployment semantic model does not match the R2 attempt"
        )
    return R2AttemptAdapterPlan(
        attempt=attempt,
        branch_id=branch_id,
        branch_name=branch_name,
        execution_plan_sha256=dry.execution_plan_sha256,
        model_id=model_id,
        model_name=model_name,
        system_commit=dry.system_commit,
    )


def load_committed_r2_semantic_plans(
    workspace: Path,
    *,
    plan: R2ExecutionPlan,
    condition: str,
) -> dict[str, OmniSemanticDeploymentPlan]:
    """Build one arm's semantic plans from the same immutable Git tree as R2."""
    _require_execution_plan(plan)
    selected_condition = _condition(condition)
    root = r2_execution._git_root(workspace)
    commit = r2_execution._canonical_git_commit(root, plan.system_commit)
    if commit != plan.system_commit:
        raise R2RuntimeAdapterError("R2 system commit does not match execution plan")
    archive = r2_execution._committed_archive(root, commit)
    databases = tuple(
        sorted(
            {
                attempt.database
                for attempt in plan.attempts
                if attempt.condition == selected_condition
            }
        )
    )
    try:
        with tempfile.TemporaryDirectory(prefix="omni-r2-runtime-") as directory:
            snapshot = Path(directory) / "snapshot"
            snapshot.mkdir(mode=0o700)
            r2_execution._extract_committed_archive(archive, snapshot)
            bundle_root = (
                snapshot
                / r2_execution._BUNDLE_ROOT
                / _CONDITION_DIRECTORIES[selected_condition]
            )
            plans = {
                database: build_semantic_deployment_plan(bundle_root / database)
                for database in databases
            }
            prepare_r2_deployment_adapter(
                plan, condition=selected_condition, semantic_plans=plans
            )
            return plans
    except (
        OSError,
        OmniSemanticDeploymentError,
        r2_execution.R2ExecutionError,
    ) as error:
        raise R2RuntimeAdapterError(
            "committed R2 semantic plans are unavailable"
        ) from error


def validate_r2_probe_plan(
    plan: R2ExecutionPlan,
    *,
    attempt_id: str,
    probe_plan: object,
) -> None:
    """Bind the existing C4 probe scaffold to R2 before product construction."""
    attempt = plan.attempt(attempt_id)
    arguments = getattr(probe_plan, "arguments", None)
    specs = getattr(probe_plan, "specs", None)
    if arguments is None or specs is None:
        raise R2RuntimeAdapterError("R2 probe plan is invalid")
    expected_arguments = {
        "instance_id": attempt.instance_id,
        "output_root": attempt.output_root,
        "repetition": attempt.repetition,
        "run_id": attempt.run_id,
        "system_commit": plan.system_commit,
    }
    if any(
        getattr(arguments, key, None) != value
        for key, value in expected_arguments.items()
    ):
        raise R2RuntimeAdapterError("R2 probe identity does not match execution plan")
    expected_hashes = {
        "condition_sha256": plan.harness_config_sha256,
        "instructions_sha256": plan.instructions_sha256,
        "prompt_sha256": plan.prompt_sha256,
    }
    if any(
        getattr(specs, key, None) != value for key, value in expected_hashes.items()
    ):
        raise R2RuntimeAdapterError(
            "R2 probe specification does not match execution plan"
        )


def r2_generation_record(
    *,
    workspace: Path,
    plan: R2ExecutionPlan,
    attempt_id: str,
    probe: OmniProbeResult,
    probe_plan: object,
) -> dict[str, Any]:
    """Convert captured C4 telemetry to the exact scheduled R2 record identity."""
    attempt = plan.attempt(attempt_id)
    arguments = probe_plan.arguments
    condition = probe_plan.specs.condition
    spec = C4AttemptSpec(
        instance_id=attempt.instance_id,
        question=probe_plan.question,
        run_id=attempt.run_id,
        repetition=attempt.repetition,
        provider=condition.provider,
        model=condition.managed_llm_identity,
        model_version=None,
        git_commit=plan.system_commit,
        harness_config_sha256=plan.harness_config_sha256,
        prompt_sha256=plan.prompt_sha256,
        instructions_sha256=plan.instructions_sha256,
        semantic_model_ref=probe_plan.semantic_model_ref,
        semantic_model_sha256=attempt.semantic_model_sha256,
        model_config_id=condition.model_config_id,
        budget_id=arguments.budget_id,
        software_versions=probe_plan.software_versions,
        cli_versions=probe_plan.cli_versions,
        cost_reservation_usd=0.0,
        budget_policy_sha256=plan.budget_policy_sha256,
        cost_unavailable_reason=COST_UNAVAILABLE_JOB_API,
    )
    record = omni_attempt._attempt_record(
        workspace=workspace,
        spec=spec,
        probe=probe,
    )
    record.update(
        {
            "attempt_id": attempt.attempt_id,
            "condition": attempt.condition,
            "database": attempt.database,
            "instance_id": attempt.instance_id,
            "partition": "dev-a",
            "repetition": attempt.repetition,
            "run_id": attempt.run_id,
        }
    )
    reject_forbidden_keys(record)
    return record


def r2_attempt_receipt(
    *,
    workspace: Path,
    plan: R2ExecutionPlan,
    attempt_id: str,
    artifacts: R2AttemptArtifacts,
    probe: OmniProbeResult,
) -> dict[str, object]:
    """Emit only identity and sidecar hashes, never question/query/result values."""
    attempt = plan.attempt(attempt_id)
    return {
        "attempt_id": attempt.attempt_id,
        "condition": attempt.condition,
        "database": attempt.database,
        "execution_plan_sha256": plan.sha256,
        "failure_class": probe.failure_class,
        "generation": _path_digest(
            workspace, artifacts.generation_path, artifacts.generation_sha256
        ),
        "job_id_sha256": (
            None
            if probe.job_id is None
            else hashlib.sha256(probe.job_id.encode()).hexdigest()
        ),
        "response_shape": _artifact_receipt(workspace, probe.response_shape),
        "run_manifest": _path_digest(
            workspace, artifacts.manifest_path, artifacts.manifest_sha256
        ),
        "terminal_state": probe.terminal_state,
        "trace": _artifact_receipt(workspace, probe.trace),
    }


def _require_execution_plan(plan: object) -> R2ExecutionPlan:
    if not isinstance(plan, R2ExecutionPlan):
        raise R2RuntimeAdapterError("R2 runtime requires an execution plan")
    return plan


def _condition(value: object) -> str:
    if value not in _CONDITIONS:
        raise R2RuntimeAdapterError("R2 runtime condition is invalid")
    return str(value)


def _path_digest(workspace: Path, path: Path, digest: str) -> dict[str, str]:
    try:
        relative = path.relative_to(workspace)
    except ValueError as error:
        raise R2RuntimeAdapterError(
            "R2 receipt artifact is outside the workspace"
        ) from error
    return {"path": relative.as_posix(), "sha256": digest}


def _artifact_receipt(workspace: Path, artifact: StoredArtifact) -> dict[str, object]:
    return {
        **_path_digest(workspace, artifact.path, artifact.sha256),
        "size_bytes": artifact.size_bytes,
    }

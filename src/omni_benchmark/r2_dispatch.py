"""Receipt-gated sequential orchestration for the paired R2 dev-A series."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from .baseline_batch_live import (
    BaselineBatchError,
    DeploymentTarget,
    verify_deployment_gate,
)
from .measure_opportunity_map import (
    MeasureOpportunityMapError,
    validate_agent_adjudicated_measure_opportunity_map,
)
from .omni_probe_preflight import OmniProbePreflightError, git_output
from .omni_probe_preflight import verify_system_commit as verify_probe_system_commit
from .r2_execution import (
    R2AttemptArtifacts,
    R2ExecutionError,
    R2ExecutionPlan,
    R2FinalizedGenerations,
    R2PlannedAttempt,
    finalize_r2_generations,
)
from . import r2_execution
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION
from .r2_production_approval import (
    DecisionLoader,
    R2ProductionApproval,
    R2ProductionApprovalError,
    consume_r2_production_approval,
    r2_control_subprocess_environment,
    validate_r2_production_approval,
)


SERIES_ID = r2_execution.SERIES_ID
CLEANUP_BEAD_ID = "omni-benchmark-ei0.10.16"
OPPORTUNITY_MAP_PATH = Path(
    "experiments/r2-public-evidence-measures/measure-opportunity-map-v1.json"
)
OPPORTUNITY_WORKBOOK_PATH = Path(
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-review-workbook-v1-agent-adjudicated.csv"
)
OPPORTUNITY_SOURCE_WORKBOOK_PATH = Path(
    "experiments/r2-public-evidence-measures/measure-opportunity-review-workbook-v1.csv"
)
OPPORTUNITY_INSTRUCTIONS_PATH = Path(
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-agent-adjudication-instructions-v1.md"
)
OPPORTUNITY_PROSPECTIVE_PROPOSAL_PATH = Path(
    "docs/protocol-amendment-opportunity-agent-adjudication-proposal.md"
)
OPPORTUNITY_PROSPECTIVE_APPROVAL_PATH = Path(
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-agent-adjudication-amendment-approval-v1.json"
)
OPPORTUNITY_CORRECTIVE_PROPOSAL_PATH = Path(
    "docs/protocol-amendment-observed-opportunity-adjudication-proposal.md"
)
OPPORTUNITY_CORRECTIVE_APPROVAL_PATH = Path(
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-observed-adjudication-amendment-approval-v1.json"
)
OPPORTUNITY_PROVENANCE_PATH = Path(
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-agent-adjudication-provenance-v1.json"
)
OPPORTUNITY_OUTPUT_ADOPTION_PATH = Path(
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-agent-adjudication-output-adoption-v1.json"
)
ACCEPTED_CATALOG_PATH = Path(
    "experiments/r2-public-evidence-measures/public-evidence-measure-catalog-v1.json"
)
PUBLIC_MANIFEST_PATH = Path("data/manifests/eligible_questions.jsonl")
DEV_A_IDS_PATH = Path("data/manifests/dev_a_ids.txt")
APPROVAL_CONSUMPTION_ROOT = Path("experiments/approvals/r2-paired-series")

_CONDITIONS = (CONTROL_CONDITION, TREATMENT_CONDITION)
_AUTHORITY_KEY = secrets.token_bytes(32)
_COMMIT = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,119}")
_MAX_OPPORTUNITY_BYTES = 16 * 1024 * 1024


class R2DispatchError(RuntimeError):
    """Raised when paired R2 execution cannot cross its exact action gate."""


@dataclass(frozen=True, slots=True)
class R2DispatchPolicy:
    """Receipt-bound runtime declarations that are not encoded in the schedule."""

    budget_id: str
    freeze_a_commit: str
    maximum_wall_clock_seconds: int
    maximum_concurrency: int = 1

    @classmethod
    def create(
        cls,
        *,
        budget_id: str,
        freeze_a_commit: str,
        maximum_wall_clock_seconds: int,
    ) -> R2DispatchPolicy:
        return _validated_policy(
            cls(
                budget_id=budget_id,
                freeze_a_commit=freeze_a_commit,
                maximum_wall_clock_seconds=maximum_wall_clock_seconds,
            )
        )


@dataclass(frozen=True, slots=True)
class R2OpportunityGate:
    """Hash-bound, question-text-free identity of the frozen analysis map."""

    artifact_sha256: str
    external_sha256: str
    opportunity_question_count: int
    eligible_question_count: int = 136


@dataclass(frozen=True, slots=True)
class R2DeploymentTarget:
    """Verified product IDs plus the isolated names the deployment claimed."""

    branch_id: str
    branch_name: str
    model_id: str
    model_name: str
    semantic_model_sha256: str


@dataclass(frozen=True, slots=True)
class R2DeploymentGate:
    """Complete verified target maps and their canonical per-arm digests."""

    targets_by_condition: Mapping[str, Mapping[str, R2DeploymentTarget]]
    sha256_by_condition: Mapping[str, str]

    @classmethod
    def create(
        cls,
        targets_by_condition: Mapping[str, Mapping[str, object]],
        sha256_by_condition: Mapping[str, str],
    ) -> R2DeploymentGate:
        if (
            not isinstance(targets_by_condition, Mapping)
            or set(targets_by_condition) != set(_CONDITIONS)
            or not isinstance(sha256_by_condition, Mapping)
            or set(sha256_by_condition) != set(_CONDITIONS)
        ):
            raise R2DispatchError("R2 deployment gate must cover both conditions")
        targets: dict[str, Mapping[str, R2DeploymentTarget]] = {}
        for condition in _CONDITIONS:
            raw = targets_by_condition[condition]
            if not isinstance(raw, Mapping) or not raw:
                raise R2DispatchError("R2 deployment gate is empty")
            converted = {
                database: _deployment_target(target)
                for database, target in raw.items()
                if isinstance(database, str) and database
            }
            if len(converted) != len(raw):
                raise R2DispatchError("R2 deployment target identity is invalid")
            targets[condition] = MappingProxyType(converted)
        digests = {
            condition: _digest(
                sha256_by_condition[condition], "R2 deployment gate SHA-256"
            )
            for condition in _CONDITIONS
        }
        return cls(
            targets_by_condition=MappingProxyType(targets),
            sha256_by_condition=MappingProxyType(digests),
        )


@dataclass(frozen=True, slots=True)
class R2CleanupGate:
    """Public Beads state for the human-owned full-source cleanup gate."""

    bead_id: str
    closed_at: str | None
    confirmed: bool


@dataclass(frozen=True, slots=True)
class R2DispatchInputs:
    """Provider-inert, receipt-ready identity for the complete paired action."""

    workspace: Path
    plan: R2ExecutionPlan
    policy: R2DispatchPolicy
    opportunity: R2OpportunityGate
    deployments: R2DeploymentGate
    cleanup: R2CleanupGate
    finalization_root: Path
    runtime_sources_sha256: str
    observed: tuple[tuple[str, str], ...]
    binding: Mapping[str, object]
    _authorization: str = field(repr=False)

    def public_summary(self) -> dict[str, object]:
        return {
            **dict(self.binding),
            "live_execution": "not_started",
            "pending_count": len(self.plan.attempts) - len(self.observed),
            "reconciled_count": len(self.observed),
        }


@dataclass(frozen=True, slots=True)
class R2DispatchPreflight:
    """Receipt-authenticated process-local capability for one dispatch invocation."""

    inputs: R2DispatchInputs
    approval: R2ProductionApproval = field(repr=False)
    _authorization: str = field(repr=False)

    def public_summary(self) -> dict[str, object]:
        return self.inputs.public_summary()


@dataclass(frozen=True, slots=True)
class R2DispatchReport:
    """Question-free completion counts and finalization identity."""

    attempt_count: int
    completed_this_run: int
    reconciled_count: int
    remaining_count: int
    finalization_manifest_path: Path | None
    finalization_manifest_sha256: str | None

    def public_summary(self) -> dict[str, object]:
        return {
            "attempt_count": self.attempt_count,
            "completed_this_run": self.completed_this_run,
            "finalization_manifest_path": (
                None
                if self.finalization_manifest_path is None
                else self.finalization_manifest_path.as_posix()
            ),
            "finalization_manifest_sha256": self.finalization_manifest_sha256,
            "reconciled_count": self.reconciled_count,
            "remaining_count": self.remaining_count,
        }


class R2AttemptExecutor(Protocol):
    """Evaluated-system adapter constructed only after receipt consumption."""

    def execute(
        self, attempt: R2PlannedAttempt, target: R2DeploymentTarget
    ) -> R2AttemptArtifacts: ...


OpportunityLoader = Callable[[Path, R2ExecutionPlan], R2OpportunityGate]
DeploymentLoader = Callable[
    [Path, R2ExecutionPlan, Mapping[str, Path]], R2DeploymentGate
]
CleanupLoader = Callable[[Path, str], R2CleanupGate]
RuntimeVerifier = Callable[[Path, str], str]
ApprovalValidator = Callable[..., R2ProductionApproval]
ApprovalConsumer = Callable[[Path, Path, R2ProductionApproval], Path]
ExecutorBuilder = Callable[[R2DispatchPreflight], R2AttemptExecutor]
Finalizer = Callable[..., R2FinalizedGenerations]


def prepare_r2_dispatch_inputs(
    *,
    workspace: Path,
    plan: R2ExecutionPlan,
    policy: R2DispatchPolicy,
    deployment_roots: Mapping[str, Path],
    opportunity_loader: OpportunityLoader = None,  # type: ignore[assignment]
    deployment_loader: DeploymentLoader = None,  # type: ignore[assignment]
    cleanup_loader: CleanupLoader = None,  # type: ignore[assignment]
    runtime_verifier: RuntimeVerifier = None,  # type: ignore[assignment]
) -> R2DispatchInputs:
    """Reconcile every non-receipt prerequisite without constructing a client."""
    root = _workspace(workspace)
    selected_plan = _validated_plan(plan)
    selected_policy = _validated_policy(policy)
    load_opportunity = (
        load_committed_r2_opportunity_gate
        if opportunity_loader is None
        else opportunity_loader
    )
    load_deployments = (
        load_r2_deployment_gate if deployment_loader is None else deployment_loader
    )
    load_cleanup = load_r2_cleanup_gate if cleanup_loader is None else cleanup_loader
    verify_runtime = (
        verify_r2_runtime_sources if runtime_verifier is None else runtime_verifier
    )
    try:
        runtime_sha256 = verify_runtime(root, selected_plan.system_commit)
    except R2DispatchError:
        raise
    except Exception as error:
        raise R2DispatchError("R2 runtime verification failed") from error
    if _DIGEST.fullmatch(runtime_sha256) is None:
        raise R2DispatchError("R2 runtime verification failed")
    try:
        opportunity = load_opportunity(root, selected_plan)
    except R2DispatchError:
        raise
    except Exception as error:
        raise R2DispatchError("R2 opportunity map gate failed") from error
    _validated_opportunity(opportunity)
    if opportunity.opportunity_question_count == 0:
        raise R2DispatchError("R2 opportunity map is empty")
    try:
        cleanup = load_cleanup(root, CLEANUP_BEAD_ID)
    except R2DispatchError:
        raise
    except Exception as error:
        raise R2DispatchError("R2 source cleanup gate failed") from error
    _validated_cleanup(cleanup)
    if not cleanup.confirmed:
        raise R2DispatchError("R2 source cleanup is not confirmed")
    try:
        deployments = load_deployments(root, selected_plan, deployment_roots)
    except R2DispatchError:
        raise
    except Exception as error:
        raise R2DispatchError("R2 deployment gate failed") from error
    _validate_deployments(selected_plan, deployments)
    finalization_root = _finalization_root(selected_plan.output_root)
    finalization_path = root / finalization_root
    if finalization_path.exists() or finalization_path.is_symlink():
        raise R2DispatchError("R2 finalization root already exists")
    observed = _reconcile_dispatch_state(root, selected_plan)
    provisional = R2DispatchInputs(
        workspace=root,
        plan=selected_plan,
        policy=selected_policy,
        opportunity=opportunity,
        deployments=deployments,
        cleanup=cleanup,
        finalization_root=finalization_root,
        runtime_sources_sha256=runtime_sha256,
        observed=observed,
        binding=MappingProxyType({}),
        _authorization="",
    )
    binding = _dispatch_binding(provisional)
    value = R2DispatchInputs(
        workspace=root,
        plan=selected_plan,
        policy=selected_policy,
        opportunity=opportunity,
        deployments=deployments,
        cleanup=cleanup,
        finalization_root=finalization_root,
        runtime_sources_sha256=runtime_sha256,
        observed=observed,
        binding=MappingProxyType(binding),
        _authorization="",
    )
    object.__setattr__(value, "_authorization", _inputs_authorization(value))
    return value


def authorize_r2_dispatch(
    inputs: R2DispatchInputs,
    *,
    receipt_path: Path,
    now: datetime | None = None,
    decision_loader: DecisionLoader | None = None,
    approval_validator: ApprovalValidator = validate_r2_production_approval,
) -> R2DispatchPreflight:
    """Validate one exact action receipt without constructing an executor."""
    value = _validated_inputs(inputs)
    try:
        approval = approval_validator(
            value.workspace,
            receipt_path,
            value.binding,
            now=now,
            decision_loader=decision_loader,
        )
    except R2ProductionApprovalError as error:
        raise R2DispatchError("R2 action receipt is invalid") from error
    if dict(getattr(approval, "binding", {})) != dict(value.binding):
        raise R2DispatchError("R2 action receipt is invalid")
    preflight = R2DispatchPreflight(
        inputs=value,
        approval=approval,
        _authorization="",
    )
    object.__setattr__(preflight, "_authorization", _preflight_authorization(preflight))
    return preflight


def execute_r2_dispatch(
    preflight: R2DispatchPreflight,
    *,
    executor_builder: ExecutorBuilder,
    approval_consumer: ApprovalConsumer = consume_r2_production_approval,
    finalizer: Finalizer = finalize_r2_generations,
    monotonic: Callable[[], float] = time.monotonic,
) -> R2DispatchReport:
    """Consume approval, construct one executor, and run only pending positions."""
    value = _validated_preflight(preflight)
    inputs = value.inputs
    try:
        current = _reconcile_dispatch_state(inputs.workspace, inputs.plan)
    except R2DispatchError as error:
        raise R2DispatchError("R2 attempt state changed after preflight") from error
    if current != inputs.observed:
        raise R2DispatchError("R2 attempt state changed after preflight")
    finalization_path = inputs.workspace / inputs.finalization_root
    if finalization_path.exists() or finalization_path.is_symlink():
        raise R2DispatchError("R2 attempt state changed after preflight")
    try:
        approval_consumer(
            inputs.workspace,
            APPROVAL_CONSUMPTION_ROOT,
            value.approval,
        )
    except R2ProductionApprovalError as error:
        raise R2DispatchError("R2 action receipt consumption failed") from error
    try:
        executor = executor_builder(value)
    except Exception as error:
        raise R2DispatchError("R2 executor construction failed") from error
    if not callable(getattr(executor, "execute", None)):
        raise R2DispatchError("R2 executor is invalid")
    observed_ids = {attempt_id for attempt_id, _digest_value in current}
    pending = tuple(
        attempt
        for attempt in inputs.plan.attempts
        if attempt.attempt_id not in observed_ids
    )
    started = monotonic()
    completed = 0
    for attempt in pending:
        if monotonic() - started >= inputs.policy.maximum_wall_clock_seconds:
            break
        target = inputs.deployments.targets_by_condition[attempt.condition][
            attempt.database
        ]
        try:
            artifacts = executor.execute(attempt, target)
        except Exception as error:
            raise R2DispatchError(
                f"R2 attempt infrastructure failure: {attempt.attempt_id}"
            ) from error
        if not isinstance(artifacts, R2AttemptArtifacts):
            raise R2DispatchError(
                f"R2 executor returned an invalid result: {attempt.attempt_id}"
            )
        try:
            r2_execution._reconciled_attempt(inputs.workspace, inputs.plan, attempt)
        except R2ExecutionError as error:
            raise R2DispatchError(
                f"R2 attempt publication failed: {attempt.attempt_id}"
            ) from error
        completed += 1
    reconciled = _reconcile_dispatch_state(inputs.workspace, inputs.plan)
    remaining = len(inputs.plan.attempts) - len(reconciled)
    finalization: R2FinalizedGenerations | None = None
    if remaining == 0:
        try:
            finalization = finalizer(
                inputs.workspace,
                plan=inputs.plan,
                destination=inputs.finalization_root,
            )
        except Exception as error:
            raise R2DispatchError("R2 arm finalization failed") from error
    manifest_path = None if finalization is None else finalization.manifest_path
    manifest_sha256 = None if finalization is None else finalization.manifest_sha256
    if manifest_sha256 is not None and _DIGEST.fullmatch(manifest_sha256) is None:
        raise R2DispatchError("R2 arm finalization returned an invalid manifest")
    return R2DispatchReport(
        attempt_count=len(inputs.plan.attempts),
        completed_this_run=completed,
        reconciled_count=len(reconciled),
        remaining_count=remaining,
        finalization_manifest_path=manifest_path,
        finalization_manifest_sha256=manifest_sha256,
    )


def load_committed_r2_opportunity_gate(
    workspace: Path, plan: R2ExecutionPlan
) -> R2OpportunityGate:
    """Regenerate the final opportunity map only from the plan's Git tree."""
    root = r2_execution._git_root(workspace)
    commit = r2_execution._canonical_git_commit(root, plan.system_commit)
    if commit != plan.system_commit:
        raise R2DispatchError("R2 opportunity map commit does not match the plan")
    archive = r2_execution._committed_archive(root, commit)
    try:
        with tempfile.TemporaryDirectory(prefix="omni-r2-opportunity-") as directory:
            snapshot = Path(directory) / "snapshot"
            snapshot.mkdir(mode=0o700)
            r2_execution._extract_committed_archive(archive, snapshot)
            content = r2_execution._snapshot_file(
                snapshot, OPPORTUNITY_MAP_PATH, _MAX_OPPORTUNITY_BYTES
            )
            catalog = r2_execution._snapshot_file(
                snapshot, ACCEPTED_CATALOG_PATH, _MAX_OPPORTUNITY_BYTES
            )
            manifest = r2_execution._snapshot_file(
                snapshot, PUBLIC_MANIFEST_PATH, r2_execution.MAX_GENERATION_BYTES
            )
            dev_a_ids = r2_execution._snapshot_file(
                snapshot, DEV_A_IDS_PATH, r2_execution.MAX_MANIFEST_BYTES
            )
            source_workbook = r2_execution._snapshot_file(
                snapshot, OPPORTUNITY_SOURCE_WORKBOOK_PATH, _MAX_OPPORTUNITY_BYTES
            )
            adjudicated_workbook = r2_execution._snapshot_file(
                snapshot, OPPORTUNITY_WORKBOOK_PATH, _MAX_OPPORTUNITY_BYTES
            )
            instructions = r2_execution._snapshot_file(
                snapshot, OPPORTUNITY_INSTRUCTIONS_PATH, _MAX_OPPORTUNITY_BYTES
            )
            prospective_proposal = r2_execution._snapshot_file(
                snapshot,
                OPPORTUNITY_PROSPECTIVE_PROPOSAL_PATH,
                _MAX_OPPORTUNITY_BYTES,
            )
            prospective_approval = r2_execution._snapshot_file(
                snapshot,
                OPPORTUNITY_PROSPECTIVE_APPROVAL_PATH,
                _MAX_OPPORTUNITY_BYTES,
            )
            corrective_proposal = r2_execution._snapshot_file(
                snapshot,
                OPPORTUNITY_CORRECTIVE_PROPOSAL_PATH,
                _MAX_OPPORTUNITY_BYTES,
            )
            corrective_approval = r2_execution._snapshot_file(
                snapshot,
                OPPORTUNITY_CORRECTIVE_APPROVAL_PATH,
                _MAX_OPPORTUNITY_BYTES,
            )
            provenance = r2_execution._snapshot_file(
                snapshot, OPPORTUNITY_PROVENANCE_PATH, _MAX_OPPORTUNITY_BYTES
            )
            output_adoption = r2_execution._snapshot_file(
                snapshot,
                OPPORTUNITY_OUTPUT_ADOPTION_PATH,
                _MAX_OPPORTUNITY_BYTES,
            )
            value = validate_agent_adjudicated_measure_opportunity_map(
                content,
                catalog,
                manifest,
                dev_a_ids,
                source_workbook,
                adjudicated_workbook,
                instructions,
                prospective_proposal,
                prospective_approval,
                corrective_proposal,
                corrective_approval,
                provenance,
                output_adoption,
            )
    except (
        OSError,
        R2ExecutionError,
        MeasureOpportunityMapError,
    ) as error:
        raise R2DispatchError(
            "committed R2 opportunity map does not reproduce"
        ) from error
    try:
        summary = value["summary"]
        artifact_sha256 = value["manifest"]["artifact_sha256"]
        eligible = summary["eligible_question_count"]
        opportunity_count = summary["opportunity_question_count"]
    except (KeyError, TypeError) as error:
        raise R2DispatchError("committed R2 opportunity map is invalid") from error
    gate = R2OpportunityGate(
        artifact_sha256=artifact_sha256,
        external_sha256=hashlib.sha256(content).hexdigest(),
        opportunity_question_count=opportunity_count,
        eligible_question_count=eligible,
    )
    return _validated_opportunity(gate)


def load_r2_deployment_gate(
    workspace: Path,
    plan: R2ExecutionPlan,
    roots: Mapping[str, Path],
) -> R2DeploymentGate:
    """Authenticate both complete deployment sets and their isolated names."""
    if not isinstance(roots, Mapping) or set(roots) != set(_CONDITIONS):
        raise R2DispatchError("R2 deployment roots must cover both conditions")
    targets_by_condition: dict[str, dict[str, R2DeploymentTarget]] = {}
    sha256_by_condition: dict[str, str] = {}
    for condition in _CONDITIONS:
        attempts = tuple(item for item in plan.attempts if item.condition == condition)
        databases = {item.database for item in attempts}
        run_ids = {item.deployment_run_id for item in attempts}
        if len(run_ids) != 1:
            raise R2DispatchError("R2 deployment run identity is inconsistent")
        run_id = next(iter(run_ids))
        root = _deployment_root(workspace, roots[condition])
        try:
            verified = verify_deployment_gate(
                root,
                run_id,
                databases,
                expected_source_commit=plan.system_commit,
            )
        except BaselineBatchError as error:
            raise R2DispatchError("R2 deployment records are not verified") from error
        targets: dict[str, R2DeploymentTarget] = {}
        records = []
        for database in sorted(databases):
            value = _private_json(root / f"{run_id}.{database}.json")
            target = verified[database]
            selected = R2DeploymentTarget(
                branch_id=target.branch_id,
                branch_name=_text(value.get("branch_name"), "deployment branch name"),
                model_id=target.model_id,
                model_name=_text(value.get("model_name"), "deployment model name"),
                semantic_model_sha256=target.semantic_model_sha256,
            )
            targets[database] = selected
            records.append(_target_record(database, selected))
        targets_by_condition[condition] = targets
        sha256_by_condition[condition] = hashlib.sha256(
            _canonical_json(records)
        ).hexdigest()
    return R2DeploymentGate.create(targets_by_condition, sha256_by_condition)


def load_r2_cleanup_gate(workspace: Path, bead_id: str) -> R2CleanupGate:
    """Read only the human task status; never touch the released source."""
    if bead_id != CLEANUP_BEAD_ID:
        raise R2DispatchError("R2 source cleanup bead identity is invalid")
    try:
        completed = subprocess.run(
            ("bd", "-C", str(workspace), "show", bead_id, "--json"),
            capture_output=True,
            check=False,
            env=r2_control_subprocess_environment(),
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise R2DispatchError("R2 source cleanup decision is unavailable") from error
    if completed.returncode != 0 or len(completed.stdout) > 1_048_576:
        raise R2DispatchError("R2 source cleanup decision is unavailable")
    try:
        response = json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise R2DispatchError("R2 source cleanup decision is unavailable") from error
    if not isinstance(response, list) or len(response) != 1:
        raise R2DispatchError("R2 source cleanup decision is invalid")
    issue = response[0]
    if (
        not isinstance(issue, Mapping)
        or issue.get("id") != bead_id
        or issue.get("issue_type") != "task"
        or not isinstance(issue.get("labels"), list)
        or "human" not in issue["labels"]
    ):
        raise R2DispatchError("R2 source cleanup decision is invalid")
    confirmed = issue.get("status") == "closed"
    closed_at = issue.get("closed_at") if confirmed else None
    return R2CleanupGate(
        bead_id=bead_id,
        closed_at=closed_at if isinstance(closed_at, str) else None,
        confirmed=confirmed and isinstance(closed_at, str),
    )


def verify_r2_runtime_sources(workspace: Path, system_commit: str) -> str:
    """Require exact HEAD/runtime cleanliness, then bind the committed runtime tree."""
    try:
        verify_probe_system_commit(workspace, system_commit)
        content = git_output(
            workspace,
            "ls-tree",
            "-r",
            "--full-tree",
            system_commit,
            "--",
            "src",
            "scripts",
            "pyproject.toml",
            "uv.lock",
        )
    except OmniProbePreflightError as error:
        raise R2DispatchError("R2 runtime does not match the system commit") from error
    if not content:
        raise R2DispatchError("R2 runtime tree is empty")
    return hashlib.sha256(content).hexdigest()


def _dispatch_binding(inputs: R2DispatchInputs) -> dict[str, object]:
    plan = inputs.plan
    return {
        "attempt_count": len(plan.attempts),
        "balanced_ai_settings_sha256": plan.balanced_ai_settings_sha256,
        "budget_id": inputs.policy.budget_id,
        "budget_policy_sha256": plan.budget_policy_sha256,
        "bundle_set_sha256": plan.bundle_set_sha256,
        "conditions": list(_CONDITIONS),
        "deployment_run_ids": _arm_identity(plan, "deployment_run_id"),
        "deployment_sha256": dict(inputs.deployments.sha256_by_condition),
        "execution_plan_sha256": plan.sha256,
        "finalization_root": inputs.finalization_root.as_posix(),
        "freeze_a_commit": inputs.policy.freeze_a_commit,
        "maximum_concurrency": inputs.policy.maximum_concurrency,
        "maximum_wall_clock_seconds": inputs.policy.maximum_wall_clock_seconds,
        "opportunity_map_artifact_sha256": inputs.opportunity.artifact_sha256,
        "opportunity_map_sha256": inputs.opportunity.external_sha256,
        "output_root": plan.output_root.as_posix(),
        "projected_arm_cost_usd": dict(plan.projected_arm_cost_usd),
        "projected_total_cost_usd": plan.projected_total_cost_usd,
        "reconciled_attempts_sha256": hashlib.sha256(
            _canonical_json([list(item) for item in inputs.observed])
        ).hexdigest(),
        "reconciled_count": len(inputs.observed),
        "run_ids": _arm_identity(plan, "run_id"),
        "runtime_sources_sha256": inputs.runtime_sources_sha256,
        "schedule_sha256": plan.schedule_sha256,
        "series_id": SERIES_ID,
        "source_cleanup_bead_id": inputs.cleanup.bead_id,
        "source_cleanup_closed_at": inputs.cleanup.closed_at,
        "system_commit": plan.system_commit,
    }


def _validated_plan(plan: object) -> R2ExecutionPlan:
    if not isinstance(plan, R2ExecutionPlan) or not plan.attempts:
        raise R2DispatchError("R2 dispatch requires an execution plan")
    attempts = plan.attempts
    if (
        tuple(item.attempt_position for item in attempts)
        != tuple(range(1, len(attempts) + 1))
        or len({item.attempt_id for item in attempts}) != len(attempts)
        or {item.condition for item in attempts} != set(_CONDITIONS)
        or any(
            not item.output_root.is_relative_to(plan.output_root) for item in attempts
        )
    ):
        raise R2DispatchError("R2 execution plan ordering is invalid")
    _digest(plan.sha256, "R2 execution plan SHA-256")
    return plan


def _validated_policy(policy: object) -> R2DispatchPolicy:
    if (
        not isinstance(policy, R2DispatchPolicy)
        or _IDENTIFIER.fullmatch(policy.budget_id) is None
        or _COMMIT.fullmatch(policy.freeze_a_commit) is None
        or type(policy.maximum_wall_clock_seconds) is not int
        or not 1 <= policy.maximum_wall_clock_seconds <= 172_800
        or policy.maximum_concurrency != 1
    ):
        raise R2DispatchError("R2 dispatch policy is invalid")
    return policy


def _validated_opportunity(gate: object) -> R2OpportunityGate:
    if (
        not isinstance(gate, R2OpportunityGate)
        or _DIGEST.fullmatch(gate.artifact_sha256) is None
        or _DIGEST.fullmatch(gate.external_sha256) is None
        or type(gate.eligible_question_count) is not int
        or gate.eligible_question_count != 136
        or type(gate.opportunity_question_count) is not int
        or not 0 <= gate.opportunity_question_count <= gate.eligible_question_count
    ):
        raise R2DispatchError("R2 opportunity map gate is invalid")
    return gate


def _validated_cleanup(gate: object) -> R2CleanupGate:
    if (
        not isinstance(gate, R2CleanupGate)
        or gate.bead_id != CLEANUP_BEAD_ID
        or type(gate.confirmed) is not bool
        or (gate.confirmed and not isinstance(gate.closed_at, str))
        or (not gate.confirmed and gate.closed_at is not None)
    ):
        raise R2DispatchError("R2 source cleanup gate is invalid")
    return gate


def _validate_deployments(plan: R2ExecutionPlan, gate: object) -> R2DeploymentGate:
    if not isinstance(gate, R2DeploymentGate):
        raise R2DispatchError("R2 deployment gate is invalid")
    expected_by_condition = {
        condition: {
            attempt.database
            for attempt in plan.attempts
            if attempt.condition == condition
        }
        for condition in _CONDITIONS
    }
    for condition in _CONDITIONS:
        targets = gate.targets_by_condition.get(condition)
        if (
            not isinstance(targets, Mapping)
            or set(targets) != expected_by_condition[condition]
        ):
            raise R2DispatchError("R2 deployment coverage is invalid")
        for attempt in (item for item in plan.attempts if item.condition == condition):
            target = targets[attempt.database]
            if (
                target.model_name != attempt.deployment_identity
                or target.branch_name != attempt.deployment_identity
                or target.semantic_model_sha256 != attempt.semantic_model_sha256
            ):
                raise R2DispatchError("R2 deployment identity does not match the plan")
    return gate


def _reconcile_dispatch_state(
    workspace: Path, plan: R2ExecutionPlan
) -> tuple[tuple[str, str], ...]:
    root = workspace / plan.output_root
    if root.is_symlink():
        raise R2DispatchError("R2 output root is unsafe")
    if not root.exists():
        return ()
    if not root.is_dir():
        raise R2DispatchError("R2 output root is unsafe")
    observed = []
    for attempt in plan.attempts:
        destination = workspace / attempt.output_root
        if destination.is_symlink():
            raise R2DispatchError("R2 attempt state is unsafe")
        if not destination.exists():
            continue
        try:
            content = r2_execution._reconciled_attempt(workspace, plan, attempt)
        except R2ExecutionError as error:
            raise R2DispatchError("R2 attempt state is invalid") from error
        observed.append((attempt.attempt_id, hashlib.sha256(content).hexdigest()))
    allowed_directories = {root}
    for attempt in plan.attempts:
        destination = workspace / attempt.output_root
        current = destination
        while current != root:
            allowed_directories.add(current)
            current = current.parent
    for path in root.rglob("*"):
        if path.is_symlink():
            raise R2DispatchError("R2 output tree contains a symlink")
        if path.is_dir():
            if path not in allowed_directories:
                raise R2DispatchError("R2 output tree contains an unknown directory")
            continue
        attempt_root = next(
            (
                workspace / attempt.output_root
                for attempt in plan.attempts
                if path.is_relative_to(workspace / attempt.output_root)
            ),
            None,
        )
        if (
            attempt_root is None
            or path.parent != attempt_root
            or path.name
            not in {
                "answer.result.json",
                "attempt.trace.jsonl",
                "generation.jsonl",
                "response-shape.json",
                "run.json",
            }
        ):
            raise R2DispatchError("R2 output tree contains an unknown artifact")
    return tuple(observed)


def _validated_inputs(inputs: object) -> R2DispatchInputs:
    if not isinstance(inputs, R2DispatchInputs) or not hmac.compare_digest(
        inputs._authorization, _inputs_authorization(inputs)
    ):
        raise R2DispatchError("R2 dispatch inputs are invalid")
    return inputs


def _validated_preflight(preflight: object) -> R2DispatchPreflight:
    if not isinstance(preflight, R2DispatchPreflight):
        raise R2DispatchError("R2 dispatch preflight is invalid")
    _validated_inputs(preflight.inputs)
    if not hmac.compare_digest(
        preflight._authorization, _preflight_authorization(preflight)
    ):
        raise R2DispatchError("R2 dispatch preflight is invalid")
    return preflight


def _inputs_authorization(inputs: R2DispatchInputs) -> str:
    value = {
        "binding": dict(inputs.binding),
        "observed": [list(item) for item in inputs.observed],
        "workspace": str(inputs.workspace),
    }
    return hmac.new(_AUTHORITY_KEY, _canonical_json(value), hashlib.sha256).hexdigest()


def _preflight_authorization(preflight: R2DispatchPreflight) -> str:
    value = {
        "approval_approved_at": preflight.approval.approved_at.isoformat(),
        "approval_binding": dict(preflight.approval.binding),
        "decision_bead_id": preflight.approval.decision_bead_id,
        "approval_expires_at": preflight.approval.expires_at.isoformat(),
        "inputs_authorization": preflight.inputs._authorization,
        "nonce": preflight.approval.nonce,
        "receipt_sha256": preflight.approval.receipt_sha256,
    }
    return hmac.new(_AUTHORITY_KEY, _canonical_json(value), hashlib.sha256).hexdigest()


def _arm_identity(plan: R2ExecutionPlan, field_name: str) -> dict[str, str]:
    result = {}
    for condition in _CONDITIONS:
        values = {
            str(getattr(attempt, field_name))
            for attempt in plan.attempts
            if attempt.condition == condition
        }
        if len(values) != 1:
            raise R2DispatchError(f"R2 {field_name} is inconsistent")
        result[condition] = next(iter(values))
    return result


def _finalization_root(output_root: Path) -> Path:
    candidate = Path(output_root.as_posix() + "-finalized")
    try:
        return r2_execution._raw_root(candidate)
    except R2ExecutionError as error:
        raise R2DispatchError("R2 finalization root is invalid") from error


def _deployment_target(value: object) -> R2DeploymentTarget:
    if isinstance(value, R2DeploymentTarget):
        selected = value
    elif isinstance(value, DeploymentTarget):
        selected = R2DeploymentTarget(
            branch_id=value.branch_id,
            branch_name=value.branch_id,
            model_id=value.model_id,
            model_name=value.model_id,
            semantic_model_sha256=value.semantic_model_sha256,
        )
    else:
        try:
            selected = R2DeploymentTarget(
                branch_id=value.branch_id,
                branch_name=value.branch_name,
                model_id=value.model_id,
                model_name=value.model_name,
                semantic_model_sha256=value.semantic_model_sha256,
            )
        except (AttributeError, TypeError) as error:
            raise R2DispatchError("R2 deployment target is invalid") from error
    if (
        any(
            not isinstance(item, str) or not item
            for item in (
                selected.branch_id,
                selected.branch_name,
                selected.model_id,
                selected.model_name,
            )
        )
        or _DIGEST.fullmatch(selected.semantic_model_sha256) is None
    ):
        raise R2DispatchError("R2 deployment target is invalid")
    return selected


def _target_record(database: str, target: R2DeploymentTarget) -> dict[str, str]:
    return {
        "branch_id": target.branch_id,
        "branch_name": target.branch_name,
        "database": database,
        "model_id": target.model_id,
        "model_name": target.model_name,
        "semantic_model_sha256": target.semantic_model_sha256,
    }


def _private_json(path: Path) -> Mapping[str, Any]:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
            ):
                raise OSError("deployment record is not private")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                content = stream.read(1_048_577)
        finally:
            os.close(descriptor)
        if not content or len(content) > 1_048_576:
            raise OSError("deployment record size is invalid")
        value = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise R2DispatchError("R2 deployment record is unavailable") from error
    if not isinstance(value, Mapping):
        raise R2DispatchError("R2 deployment record is invalid")
    if _canonical_json(value) != content:
        raise R2DispatchError("R2 deployment record is invalid")
    return value


def _deployment_root(workspace: Path, value: object) -> Path:
    if not isinstance(value, Path):
        raise R2DispatchError("R2 deployment root is invalid")
    relative = Path(value)
    allowed = Path("experiments/deployments")
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.is_relative_to(allowed)
        or relative == allowed
    ):
        raise R2DispatchError("R2 deployment root is not confined")
    candidate = workspace / relative
    try:
        if candidate.resolve(strict=False) != candidate:
            raise R2DispatchError("R2 deployment root is unsafe")
    except OSError as error:
        raise R2DispatchError("R2 deployment root is unavailable") from error
    return candidate


def _workspace(path: Path) -> Path:
    try:
        return Path(path).resolve(strict=True)
    except OSError as error:
        raise R2DispatchError("R2 workspace is unavailable") from error


def _digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise R2DispatchError(f"{description} is invalid")
    return value


def _text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise R2DispatchError(f"{description} is invalid")
    return value


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

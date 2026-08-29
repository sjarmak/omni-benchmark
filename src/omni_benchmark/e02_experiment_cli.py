"""Dry-default, receipt-gated deployment of the exact E02 candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .baseline_batch import (
    BaselineBatchError,
    c4_dev_a_experiment_schedule,
    load_committed_baseline_schedule,
)
from .c4_production_approval import (
    C4ProductionApprovalError,
    consume_c4_production_approval,
    validate_c4_production_approval,
)
from .e02_candidate import (
    E02CandidateError,
    E02CommittedCandidate,
    load_committed_e02_candidate,
)
from .omni_semantic_deploy_cli import (
    ClientFactory,
    OmniDeploymentCliError,
    deployment_main,
)
from .omni_semantic_deployment import semantic_deployment_sha256
from .omni_result_adapter import reject_forbidden_keys

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")
_DEPLOYMENT_ROOT = Path("experiments/deployments")
_STATE_ROOT = Path("experiments/autoresearch/state")
_MAX_BASELINE_FREEZE_BYTES = 16 * 1024 * 1024


class E02ExperimentError(ValueError):
    """Raised before an E02 deployment can cross an unauthorized boundary."""


@dataclass(frozen=True, slots=True)
class E02DeploymentPlan:
    """Exact public identity for one E02 deployment and later dev-A run."""

    candidate: E02CommittedCandidate
    baseline_selection_sha256: str
    execution_plan_sha256: str
    file_count: int
    output_root: Path
    run_id: str
    schedule_sha256: str
    schedule_attempt_count: int

    @property
    def approval_binding(self) -> dict[str, str]:
        return {
            "condition": "C4",
            "deployment_sha256": self.candidate.candidate_set_sha256,
            "execution_plan_sha256": self.execution_plan_sha256,
            "output_root": self.output_root.as_posix(),
            "run_id": self.run_id,
            "schedule_sha256": self.schedule_sha256,
            "system_commit": self.candidate.source_commit,
        }

    def public_dict(self) -> dict[str, object]:
        return {
            "approval_binding": self.approval_binding,
            "candidate_set_sha256": self.candidate.candidate_set_sha256,
            "baseline_selection_sha256": self.baseline_selection_sha256,
            "database_count": len(self.candidate.plans),
            "execution_plan_sha256": self.execution_plan_sha256,
            "file_count": self.file_count,
            "live_execution": "not_started",
            "relationship_count": self.candidate.relationship_count,
            "schedule_attempt_count": self.schedule_attempt_count,
            "schedule_sha256": self.schedule_sha256,
            "schema_version": 1,
            "system_commit": self.candidate.source_commit,
        }


def prepare_e02_deployment_plan(
    workspace: Path,
    *,
    system_commit: str,
    run_id: str,
    output_root: Path,
    expected_candidate_set_sha256: str,
    baseline_freeze: Path,
    expected_baseline_selection_sha256: str,
    baseline_validator: Callable[[Path, Path, str], str],
) -> E02DeploymentPlan:
    """Resolve all exact public inputs without constructing a product client."""
    selected_run_id = _identifier(run_id, "run ID")
    selected_output = _output_root(output_root)
    expected_candidate = _digest(
        expected_candidate_set_sha256, "expected candidate set SHA-256"
    )
    baseline_selection_sha256 = baseline_validator(
        workspace,
        baseline_freeze,
        expected_baseline_selection_sha256,
    )
    try:
        candidate = load_committed_e02_candidate(workspace, system_commit)
        full = load_committed_baseline_schedule(
            workspace, system_commit, run_id=selected_run_id
        )
        schedule = c4_dev_a_experiment_schedule(workspace, system_commit, full)
    except (E02CandidateError, BaselineBatchError) as error:
        raise E02ExperimentError("E02 public inputs are invalid") from error
    if candidate.candidate_set_sha256 != expected_candidate:
        raise E02ExperimentError("E02 candidate set does not match expectation")
    database_plans = {
        database: {
            "manifest_sha256": plan.manifest_sha256,
            "semantic_deployment_sha256": semantic_deployment_sha256(plan),
        }
        for database, plan in sorted(candidate.plans.items())
    }
    file_count = sum(len(plan.files) for plan in candidate.plans.values())
    identity = {
        "baseline_selection_sha256": baseline_selection_sha256,
        "candidate_set_sha256": candidate.candidate_set_sha256,
        "databases": database_plans,
        "file_count": file_count,
        "kind": "e02-dev-a-deployment-plan",
        "output_root": selected_output.as_posix(),
        "relationship_count": candidate.relationship_count,
        "run_id": selected_run_id,
        "schedule_sha256": schedule.sha256,
        "schema_version": 1,
        "system_commit": candidate.source_commit,
    }
    return E02DeploymentPlan(
        candidate=candidate,
        baseline_selection_sha256=baseline_selection_sha256,
        execution_plan_sha256=hashlib.sha256(_canonical(identity)).hexdigest(),
        file_count=file_count,
        output_root=selected_output,
        run_id=selected_run_id,
        schedule_sha256=schedule.sha256,
        schedule_attempt_count=len(schedule.attempts),
    )


def e02_experiment_main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    approval_validator: Callable[..., object] = validate_c4_production_approval,
    approval_consumer: Callable[..., Path] = consume_c4_production_approval,
    deployment_runner: Callable[..., int] = deployment_main,
    baseline_validator: Callable[[Path, Path, str], str] | None = None,
) -> int:
    """Print the exact dry plan or deploy only after one current receipt."""
    arguments = _parser().parse_args(argv)
    workspace = arguments.workspace.resolve(strict=True)
    selected_baseline_validator = (
        validate_c4_baseline_freeze
        if baseline_validator is None
        else baseline_validator
    )
    plan = prepare_e02_deployment_plan(
        workspace,
        system_commit=arguments.system_commit,
        run_id=arguments.run_id,
        output_root=arguments.output_root,
        expected_candidate_set_sha256=arguments.expected_candidate_set_sha256,
        baseline_freeze=arguments.baseline_freeze,
        expected_baseline_selection_sha256=(
            arguments.expected_baseline_selection_sha256
        ),
        baseline_validator=selected_baseline_validator,
    )
    destination = workspace / plan.output_root
    if destination.exists() or destination.is_symlink():
        raise E02ExperimentError("E02 deployment output root must be absent")
    if not arguments.execute_live_deployment:
        print(json.dumps(plan.public_dict(), separators=(",", ":"), sort_keys=True))
        return 0
    if arguments.human_approval_receipt is None:
        raise E02ExperimentError("live E02 requires a human approval receipt")
    if not isinstance(arguments.profile, str) or not arguments.profile.strip():
        raise E02ExperimentError("live E02 requires an Omni profile")
    try:
        approval = approval_validator(
            workspace,
            arguments.human_approval_receipt,
            plan.approval_binding,
        )
        approval_consumer(
            workspace,
            Path("experiments/approvals/e02-deployment"),
            approval,
        )
        return deployment_runner(
            [
                "--workspace",
                str(workspace),
                "--output-root",
                str(destination),
                "--run-id",
                plan.run_id,
                "--profile",
                arguments.profile,
                "--max-workers",
                str(arguments.max_workers),
                "--minimum-request-interval-seconds",
                str(arguments.minimum_request_interval_seconds),
                "--execute-live-deployment",
            ],
            client_factory=client_factory,
            commit_observer=lambda _workspace: plan.candidate.source_commit,
            bundle_loader=lambda _workspace, _commit: (dict(plan.candidate.plans), {}),
            identity_factory=_e02_deployment_identity,
        )
    except (C4ProductionApprovalError, OmniDeploymentCliError) as error:
        raise E02ExperimentError(str(error)) from error


def e02_experiment_entrypoint() -> int:
    """Run the command without leaking an unexpected exception or receipt."""
    try:
        return e02_experiment_main()
    except E02ExperimentError as error:
        print(f"E02 experiment preparation failed: {error}", file=sys.stderr)
    except Exception:
        print("E02 experiment preparation failed: internal error", file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--expected-candidate-set-sha256", required=True)
    parser.add_argument("--baseline-freeze", type=Path, required=True)
    parser.add_argument("--expected-baseline-selection-sha256", required=True)
    parser.add_argument("--human-approval-receipt", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--max-workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--minimum-request-interval-seconds", type=float, default=0.0)
    parser.add_argument("--execute-live-deployment", action="store_true")
    return parser


def _identifier(value: object, description: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise E02ExperimentError(f"E02 {description} is invalid")
    return value


def validate_c4_baseline_freeze(
    workspace: Path, path: Path, expected_sha256: str
) -> str:
    """Require the exact completed public C4 baseline before E02 preparation."""
    expected = _digest(expected_sha256, "expected baseline selection SHA-256")
    selected = Path(path)
    if (
        selected.is_absolute()
        or selected.parent != _STATE_ROOT
        or not selected.name.endswith("-freeze.json")
    ):
        raise E02ExperimentError("C4 baseline freeze path is not confined")
    target = Path(workspace).resolve(strict=True) / selected
    descriptor: int | None = None
    try:
        metadata = target.lstat()
        if (
            target.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or metadata.st_size < 1
            or metadata.st_size > _MAX_BASELINE_FREEZE_BYTES
        ):
            raise E02ExperimentError("C4 baseline freeze is not a private file")
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_uid != metadata.st_uid
            or opened.st_mode != metadata.st_mode
            or opened.st_nlink != metadata.st_nlink
            or opened.st_size != metadata.st_size
        ):
            raise E02ExperimentError("C4 baseline freeze changed while opening")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size > _MAX_BASELINE_FREEZE_BYTES:
                raise E02ExperimentError("C4 baseline freeze is too large")
    except E02ExperimentError:
        raise
    except OSError as error:
        raise E02ExperimentError("C4 baseline freeze is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    content = b"".join(chunks)
    observed = hashlib.sha256(content).hexdigest()
    if observed != expected:
        raise E02ExperimentError("C4 baseline freeze hash does not match")
    try:
        value = json.loads(content, object_pairs_hook=_strict_json_object)
        reject_forbidden_keys(value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise E02ExperimentError("C4 baseline freeze is invalid") from error
    if (
        not isinstance(value, Mapping)
        or value.get("kind") != "public-c4-baseline-freeze"
        or value.get("schema_version") != 1
        or not isinstance(value.get("entries"), list)
        or len(value["entries"]) != 129
        or not isinstance(value.get("counts"), Mapping)
        or value["counts"].get("attempts") != 129
        or value["counts"].get("databases") != 10
    ):
        raise E02ExperimentError("C4 baseline freeze identity is invalid")
    return observed


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field {key}")
        result[key] = value
    return result


def _e02_deployment_identity(database: str) -> tuple[str, str]:
    selected = _identifier(database, "database")
    identity = f"livesqlbench-{selected}-e02-relationships-v1"
    return identity, identity


def _digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise E02ExperimentError(f"{description} is invalid")
    return value


def _output_root(value: Path) -> Path:
    selected = Path(value)
    if (
        selected.is_absolute()
        or ".." in selected.parts
        or selected.parent != _DEPLOYMENT_ROOT
        or _IDENTIFIER.fullmatch(selected.name) is None
    ):
        raise E02ExperimentError("E02 deployment output root is not confined")
    return selected


def _canonical(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()

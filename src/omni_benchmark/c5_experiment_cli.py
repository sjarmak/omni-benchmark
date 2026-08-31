"""Dry-default deployment of the exact committed C5 tuned candidate.

Deployment carries only the public schema and the public HKB onto isolated
`livesqlbench-*` branches, so it runs under Tier 1 autonomy: no questions, no
gold, no evaluated answers. Everything that touches an evaluated answer stays in
the receipt-gated generation path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .baseline_batch import (
    BaselineBatchError,
    c4_dev_a_experiment_schedule,
    load_committed_baseline_schedule,
)
from .e02_candidate import (
    E02CandidateError,
    E02CommittedCandidate,
    load_committed_c5_candidate,
)
from .omni_semantic_deploy_cli import (
    ClientFactory,
    OmniDeploymentCliError,
    deployment_main,
)
from .omni_semantic_deployment import semantic_deployment_sha256

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")
_DEPLOYMENT_ROOT = Path("experiments/deployments")


class C5ExperimentError(ValueError):
    """Raised before a C5 deployment can cross an unauthorized boundary."""


@dataclass(frozen=True, slots=True)
class C5DeploymentPlan:
    """Exact public identity for one C5 deployment and later dev-A run."""

    candidate: E02CommittedCandidate
    deployment_databases: tuple[str, ...]
    deployment_set_sha256: str
    execution_plan_sha256: str
    file_count: int
    output_root: Path
    run_id: str
    schedule_sha256: str
    schedule_attempt_count: int

    def public_dict(self) -> dict[str, object]:
        return {
            "candidate_database_count": len(self.candidate.plans),
            "candidate_set_sha256": self.candidate.candidate_set_sha256,
            "condition": "C5",
            "deployment_database_count": len(self.deployment_databases),
            "deployment_set_sha256": self.deployment_set_sha256,
            "execution_plan_sha256": self.execution_plan_sha256,
            "file_count": self.file_count,
            "live_execution": "not_started",
            "output_root": self.output_root.as_posix(),
            "relationship_count": self.candidate.relationship_count,
            "run_id": self.run_id,
            "schedule_attempt_count": self.schedule_attempt_count,
            "schedule_sha256": self.schedule_sha256,
            "schema_version": 1,
            "system_commit": self.candidate.source_commit,
        }


def prepare_c5_deployment_plan(
    workspace: Path,
    *,
    system_commit: str,
    run_id: str,
    output_root: Path,
) -> C5DeploymentPlan:
    """Resolve all exact public inputs without constructing a product client."""
    selected_run_id = _identifier(run_id, "run ID")
    selected_output = _output_root(output_root)
    try:
        candidate = load_committed_c5_candidate(workspace, system_commit)
        full = load_committed_baseline_schedule(
            workspace, system_commit, run_id=selected_run_id
        )
        schedule = c4_dev_a_experiment_schedule(workspace, system_commit, full)
    except (E02CandidateError, BaselineBatchError) as error:
        raise C5ExperimentError("C5 public inputs are invalid") from error
    deployment_databases = tuple(
        sorted({attempt.database for attempt in schedule.attempts})
    )
    if any(database not in candidate.plans for database in deployment_databases):
        raise C5ExperimentError("C5 candidate does not cover the execution schedule")
    database_plans = {
        database: {
            "manifest_sha256": candidate.plans[database].manifest_sha256,
            "semantic_deployment_sha256": semantic_deployment_sha256(
                candidate.plans[database]
            ),
        }
        for database in deployment_databases
    }
    deployment_set_sha256 = hashlib.sha256(
        _canonical(
            {
                "candidate_set_sha256": candidate.candidate_set_sha256,
                "databases": database_plans,
                "kind": "c5-dev-a-selected-deployment-set",
                "schema_version": 1,
            }
        )
    ).hexdigest()
    file_count = sum(
        len(candidate.plans[database].files) for database in deployment_databases
    )
    identity = {
        "candidate_set_sha256": candidate.candidate_set_sha256,
        "databases": database_plans,
        "deployment_set_sha256": deployment_set_sha256,
        "file_count": file_count,
        "kind": "c5-dev-a-deployment-plan",
        "output_root": selected_output.as_posix(),
        "relationship_count": candidate.relationship_count,
        "run_id": selected_run_id,
        "schedule_sha256": schedule.sha256,
        "schema_version": 1,
        "system_commit": candidate.source_commit,
    }
    return C5DeploymentPlan(
        candidate=candidate,
        deployment_databases=deployment_databases,
        deployment_set_sha256=deployment_set_sha256,
        execution_plan_sha256=hashlib.sha256(_canonical(identity)).hexdigest(),
        file_count=file_count,
        output_root=selected_output,
        run_id=selected_run_id,
        schedule_sha256=schedule.sha256,
        schedule_attempt_count=len(schedule.attempts),
    )


def c5_experiment_main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    deployment_runner: Callable[..., int] = deployment_main,
) -> int:
    """Print the exact dry plan, or deploy the committed C5 bundles."""
    arguments = _parser().parse_args(argv)
    workspace = arguments.workspace.resolve(strict=True)
    plan = prepare_c5_deployment_plan(
        workspace,
        system_commit=arguments.system_commit,
        run_id=arguments.run_id,
        output_root=arguments.output_root,
    )
    destination = workspace / plan.output_root
    if destination.exists() or destination.is_symlink():
        raise C5ExperimentError("C5 deployment output root must be absent")
    if not arguments.execute_live_deployment:
        print(json.dumps(plan.public_dict(), separators=(",", ":"), sort_keys=True))
        return 0
    if not isinstance(arguments.profile, str) or not arguments.profile.strip():
        raise C5ExperimentError("live C5 deployment requires an Omni profile")
    try:
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
            bundle_loader=lambda _workspace, _commit: (
                {
                    database: plan.candidate.plans[database]
                    for database in plan.deployment_databases
                },
                {},
            ),
            identity_factory=_c5_deployment_identity,
        )
    except OmniDeploymentCliError as error:
        raise C5ExperimentError(str(error)) from error


def c5_experiment_entrypoint() -> int:
    """Run the command without leaking an unexpected exception."""
    try:
        return c5_experiment_main()
    except C5ExperimentError as error:
        print(f"C5 experiment preparation failed: {error}", file=sys.stderr)
    except Exception:
        print("C5 experiment preparation failed: internal error", file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--profile")
    parser.add_argument("--max-workers", type=int, choices=range(1, 9), default=1)
    parser.add_argument("--minimum-request-interval-seconds", type=float, default=1.25)
    parser.add_argument("--execute-live-deployment", action="store_true")
    return parser


def _c5_deployment_identity(database: str) -> tuple[str, str]:
    selected = _identifier(database, "database")
    identity = f"livesqlbench-{selected}-c5-tuned-v1"
    return identity, identity


def _identifier(value: object, description: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise C5ExperimentError(f"C5 {description} is invalid")
    return value


def _output_root(value: Path) -> Path:
    selected = Path(value)
    if (
        selected.is_absolute()
        or ".." in selected.parts
        or selected.parent != _DEPLOYMENT_ROOT
        or _IDENTIFIER.fullmatch(selected.name) is None
    ):
        raise C5ExperimentError("C5 deployment output root is not confined")
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

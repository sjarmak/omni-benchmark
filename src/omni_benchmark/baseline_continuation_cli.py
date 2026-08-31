"""Prepare, verify, or execute an authorized direct-baseline continuation."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from .baseline_batch import (
    BaselineBatchError,
    BatchBudget,
    ImmutableAttemptRepository,
    apply_committed_direct_baseline_exclusions,
    direct_only_baseline_schedule,
    load_committed_baseline_schedule,
    run_baseline_batch,
)
from .baseline_batch_cli import _child_environment
from .baseline_batch_live import (
    DatabaseEnvironmentDirectory,
    LiveBaselineDispatcher,
    build_execution_plan,
    project_condition_cost_scenario,
)
from .baseline_continuation import (
    ContinuationAuthorization,
    build_baseline_freeze_manifest,
    build_continuation_manifest,
    continuation_schedule,
    load_continuation_manifest,
    reconcile_continuation,
    write_baseline_freeze_manifest,
    write_continuation_manifest,
)
from .claude_lease_preflight import ClaudeLeasePreflightError, verify_lease_window
from .omni_probe_preflight import OmniProbePreflightError, verify_system_commit

AUTHORIZED_SYSTEM_COMMIT = "5be315e44bea7ee1a39500380dcbc4c05976dd3e"
AUTHORIZED_ORIGINAL_RUN_ID = "public-baseline-v1-direct-16db"
AUTHORIZED_ORIGINAL_OUTPUT_ROOT = Path(
    "experiments/autoresearch/raw/public-baseline-v1-direct-16db"
)
AUTHORIZED_CONTINUATION_RUN_ID = "public-baseline-v1-direct-16db-continuation-1"
AUTHORIZED_CONTINUATION_OUTPUT_ROOT = Path(
    "experiments/autoresearch/raw/public-baseline-v1-direct-16db-continuation-1"
)
AUTHORIZED_AUTHORIZATION_ID = "omni-benchmark-6tm-oauth-rotation-20260828"
AUTHORIZED_INCIDENT_START = "2026-08-28T18:20:46Z"
AUTHORIZED_INCIDENT_END = "2026-08-28T18:26:20Z"
AUTHORIZED_INVALIDATED_ATTEMPTS = 95
AUTHORIZED_MANIFEST_SHA256 = (
    "751a2a7081958d3d35d051ca47d9f62481d3df082048c7644b125bc093179717"
)
AUTHORIZED_FREEZE_OUTPUT = Path(
    "experiments/autoresearch/state/public-direct-baseline-freeze-v1.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    _source_arguments(prepare)
    prepare.add_argument("--continuation-run-id", required=True)
    prepare.add_argument("--manifest-output", type=Path, required=True)
    prepare.add_argument("--authorization-id", required=True)
    prepare.add_argument("--incident-finished-start", required=True)
    prepare.add_argument("--incident-finished-end", required=True)
    prepare.add_argument("--expected-invalidated-attempts", type=int, required=True)

    for name in ("plan", "execute", "reconcile", "freeze"):
        action = subparsers.add_parser(name)
        _source_arguments(action)
        action.add_argument("--execution-workspace", type=Path, required=True)
        action.add_argument("--continuation-output-root", type=Path, required=True)
        action.add_argument("--manifest", type=Path, required=True)
        action.add_argument("--manifest-sha256", required=True)
        if name == "freeze":
            action.add_argument("--freeze-output", type=Path, required=True)
        if name in {"plan", "execute"}:
            _execution_arguments(action)
    return parser


def _source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--original-run-id", required=True)
    parser.add_argument("--original-output-root", type=Path, required=True)


def _execution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--freeze-a-commit", required=True)
    parser.add_argument(
        "--claude-config-dir", type=Path, action="append", required=True
    )
    parser.add_argument("--database-environment-dir", type=Path, required=True)
    parser.add_argument("--observed-condition-cost", action="append", required=True)
    parser.add_argument("--cost-ceiling-usd", type=float, required=True)
    parser.add_argument("--attempt-cost-ceiling-usd", type=float, required=True)
    parser.add_argument("--maximum-concurrency", type=int, default=3)
    parser.add_argument("--subprocess-timeout-seconds", type=float, default=900.0)


def baseline_continuation_main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    _require_authorized_source(arguments)
    source_workspace = arguments.source_workspace.resolve(strict=True)
    source = _load_source_schedule(
        source_workspace,
        arguments.system_commit,
        arguments.original_run_id,
    )
    source_repository = ImmutableAttemptRepository(
        source_workspace, arguments.original_output_root
    )
    if arguments.command == "prepare":
        return _prepare(arguments, source, source_repository)
    _require_authorized_execution(arguments)
    execution_workspace = arguments.execution_workspace.resolve(strict=True)
    try:
        verify_system_commit(execution_workspace, arguments.system_commit)
    except OmniProbePreflightError as error:
        raise BaselineBatchError(
            "execution workspace is not the exact clean system commit"
        ) from error
    manifest = load_continuation_manifest(
        arguments.manifest, expected_sha256=arguments.manifest_sha256
    )
    continuation_repository = ImmutableAttemptRepository(
        execution_workspace, arguments.continuation_output_root
    )
    before = reconcile_continuation(
        source,
        manifest,
        source_repository=source_repository,
        continuation_repository=continuation_repository,
    )
    schedule = continuation_schedule(source, manifest)
    if arguments.command == "reconcile":
        _print(
            {
                "continuation_manifest_sha256": manifest.sha256,
                "reconciliation": before.as_dict(),
                "schedule_identity": schedule.public_identity(),
            }
        )
        return 0
    if arguments.command == "freeze":
        frozen = build_baseline_freeze_manifest(
            source,
            manifest,
            source_repository=source_repository,
            continuation_repository=continuation_repository,
        )
        destination = source_workspace / arguments.freeze_output
        digest = write_baseline_freeze_manifest(
            source_workspace,
            destination,
            frozen,
        )
        _print(
            {
                "baseline_freeze_path": str(arguments.freeze_output),
                "baseline_freeze_sha256": digest,
                "counts": dict(frozen.counts),
            }
        )
        return 0
    plan = build_execution_plan(
        schedule,
        workspace=execution_workspace,
        output_root=arguments.continuation_output_root,
        claude_config_directories=tuple(arguments.claude_config_dir),
        freeze_a_commit=arguments.freeze_a_commit,
    )
    scenario = project_condition_cost_scenario(
        schedule,
        observed_condition_cost_usd=_condition_costs(arguments.observed_condition_cost),
    )
    if arguments.command == "plan":
        _print(
            {
                "continuation_manifest_sha256": manifest.sha256,
                "execution_plan": plan.public_dict(),
                "live_execution": "not_started_pending_profile_validation",
                "reconciliation_before_run": before.as_dict(),
                "successful_canary_cost_scenario": scenario.as_dict(),
            }
        )
        return 0
    return _execute(
        arguments,
        source,
        manifest,
        source_repository,
        continuation_repository,
        schedule,
        plan,
        scenario.as_dict(),
    )


def _prepare(arguments, source, repository) -> int:
    authorization = ContinuationAuthorization(
        authorization_id=arguments.authorization_id,
        expected_invalidated_attempts=arguments.expected_invalidated_attempts,
        finished_at_start=arguments.incident_finished_start,
        finished_at_end=arguments.incident_finished_end,
        terminal_failure_class="model_setup_error",
    )
    manifest = build_continuation_manifest(
        source,
        repository=repository,
        continuation_run_id=arguments.continuation_run_id,
        authorization=authorization,
    )
    digest = write_continuation_manifest(arguments.manifest_output, manifest)
    _print(
        {
            "continuation_manifest_sha256": digest,
            "counts": dict(manifest.counts),
            "manifest_path": str(arguments.manifest_output),
            "source_schedule_sha256": manifest.source_schedule_sha256,
        }
    )
    return 0


def _require_authorized_source(arguments) -> None:
    expected = {
        "system_commit": AUTHORIZED_SYSTEM_COMMIT,
        "original_run_id": AUTHORIZED_ORIGINAL_RUN_ID,
        "original_output_root": AUTHORIZED_ORIGINAL_OUTPUT_ROOT,
    }
    if any(getattr(arguments, field) != value for field, value in expected.items()):
        raise BaselineBatchError(
            "continuation source does not match the authorized OAuth incident"
        )
    if arguments.command == "prepare":
        prepare_expected = {
            "authorization_id": AUTHORIZED_AUTHORIZATION_ID,
            "continuation_run_id": AUTHORIZED_CONTINUATION_RUN_ID,
            "expected_invalidated_attempts": AUTHORIZED_INVALIDATED_ATTEMPTS,
            "incident_finished_end": AUTHORIZED_INCIDENT_END,
            "incident_finished_start": AUTHORIZED_INCIDENT_START,
        }
        if any(
            getattr(arguments, field) != value
            for field, value in prepare_expected.items()
        ):
            raise BaselineBatchError(
                "continuation request is outside the authorized OAuth incident"
            )


def _require_authorized_execution(arguments) -> None:
    if (
        arguments.continuation_output_root != AUTHORIZED_CONTINUATION_OUTPUT_ROOT
        or arguments.manifest_sha256 != AUTHORIZED_MANIFEST_SHA256
    ):
        raise BaselineBatchError(
            "continuation execution does not match the authorized immutable plan"
        )
    if (
        arguments.command == "freeze"
        and arguments.freeze_output != AUTHORIZED_FREEZE_OUTPUT
    ):
        raise BaselineBatchError("continuation freeze output is not authorized")


def _execute(
    arguments,
    source,
    manifest,
    source_repository,
    continuation_repository,
    schedule,
    plan,
    scenario: Mapping[str, object],
) -> int:
    execution_workspace = arguments.execution_workspace.resolve(strict=True)
    try:
        verify_lease_window(
            tuple(plan.claude_config_directories),
            attempt_seconds=arguments.subprocess_timeout_seconds,
        )
    except ClaudeLeasePreflightError as error:
        raise BaselineBatchError(f"lease preflight failed: {error}") from error
    dispatcher = LiveBaselineDispatcher(
        plan,
        database_environments=DatabaseEnvironmentDirectory(
            execution_workspace, arguments.database_environment_dir
        ),
        common_environment=_child_environment(os.environ),
        timeout_seconds=arguments.subprocess_timeout_seconds,
    )
    report = run_baseline_batch(
        schedule,
        repository=continuation_repository,
        executor=dispatcher,
        maximum_concurrency=arguments.maximum_concurrency,
        budget=BatchBudget(
            cost_ceiling_usd=arguments.cost_ceiling_usd,
            attempt_cost_ceiling_usd=arguments.attempt_cost_ceiling_usd,
        ),
    )
    after = reconcile_continuation(
        source,
        manifest,
        source_repository=source_repository,
        continuation_repository=continuation_repository,
    )
    _print(
        {
            "continuation_manifest_sha256": manifest.sha256,
            "execution_plan_sha256": plan.sha256,
            "live_execution": report.as_dict(),
            "reconciliation_after_run": after.as_dict(),
            "successful_canary_cost_scenario": dict(scenario),
        }
    )
    return 0


def _load_source_schedule(workspace: Path, commit: str, run_id: str):
    full = load_committed_baseline_schedule(workspace, commit, run_id=run_id)
    return apply_committed_direct_baseline_exclusions(
        workspace, commit, direct_only_baseline_schedule(full)
    )


def _condition_costs(values: Sequence[str]) -> dict[str, str]:
    costs: dict[str, str] = {}
    for value in values:
        condition, separator, cost = value.partition("=")
        if not separator or condition not in {"C1", "C2", "C3"} or condition in costs:
            raise BaselineBatchError(
                "condition costs must be unique C1-C3 CONDITION=USD values"
            )
        costs[condition] = cost
    if set(costs) != {"C1", "C2", "C3"}:
        raise BaselineBatchError("continuation requires C1-C3 cost observations")
    return costs


def _print(value: object) -> None:
    print(json.dumps(value, allow_nan=False, sort_keys=True))

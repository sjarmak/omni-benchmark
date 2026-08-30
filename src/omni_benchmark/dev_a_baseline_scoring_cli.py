"""Command line boundary for frozen-baseline dev-A scoring."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import psycopg

from .dev_a_baseline_scoring import (
    RAW_ROOT,
    SELECTION_PATH,
    SELECTION_ROOT,
    DevABaselineScoringError,
    prepare_dev_a_baseline_plan,
    publish_dev_a_baseline_results,
    require_scoreable_question_counts,
    score_dev_a_baseline_plan,
)
from .dev_a_gold_conformance import (
    DevAGoldConformanceError,
    load_dev_a_gold_conformance_receipt,
)
from .postgres_isolation import PsycopgTemplateIsolationProvider

ADMIN_DSN_ENV = "OMNI_BENCHMARK_SCORER_ADMIN_DSN"
EXECUTION_DSN_ENV = "OMNI_BENCHMARK_SCORER_EXECUTION_DSN"
PINNED_POSTGRES_SERVER_VERSION_NUM = "180006"


def dev_a_baseline_scoring_entrypoint() -> int:
    """Run the CLI with a no-traceback custody boundary."""
    try:
        return dev_a_baseline_scoring_main()
    except DevABaselineScoringError as error:
        print(f"dev-A baseline scoring failed: {error}", file=sys.stderr)
    except Exception:
        print("dev-A baseline scoring failed: internal scorer error", file=sys.stderr)
    return 1


def dev_a_baseline_scoring_main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Score and publish one exact, already-frozen dev-A baseline selection."""
    arguments = _parser().parse_args(argv)
    process_environment = dict(os.environ if environment is None else environment)
    admin_dsn = _required_dsn(process_environment, ADMIN_DSN_ENV)
    execution_dsn = _required_dsn(process_environment, EXECUTION_DSN_ENV)
    output_root = _output_root(arguments.output_root)
    workspace = arguments.workspace.resolve(strict=True)
    if (workspace / output_root).exists() or (workspace / output_root).is_symlink():
        raise DevABaselineScoringError("output root must not already exist")

    plan = prepare_dev_a_baseline_plan(
        workspace,
        artifact_workspace=arguments.artifact_workspace,
        freeze_a_commit=arguments.freeze_a_commit,
        selection_path=_selection_path(arguments.selection),
        expected_selection_sha256=arguments.expected_selection_sha256,
        expected_release_sha256=arguments.expected_release_sha256,
        c4_recovery_workspace=arguments.c4_recovery_workspace,
        c4_recovery_manifest_path=arguments.c4_recovery_manifest,
        expected_c4_recovery_sha256=arguments.expected_c4_recovery_sha256,
        environment=process_environment,
    )
    expected_counts = _expected_counts(arguments, workspace, plan)
    _require_pinned_postgres(admin_dsn)
    templates = {
        attempt.case.database: attempt.case.database for attempt in plan.attempts
    }
    try:
        provider = PsycopgTemplateIsolationProvider(
            admin_dsn,
            execution_dsn,
            templates,
        )
    except ValueError as error:
        raise DevABaselineScoringError(
            "PostgreSQL scorer configuration is invalid"
        ) from error
    results = score_dev_a_baseline_plan(
        plan,
        provider,
        expected_scoreable_question_counts=expected_counts,
    )
    require_scoreable_question_counts(
        results,
        official=expected_counts[0],
        sensitivity=expected_counts[1],
    )
    receipt = publish_dev_a_baseline_results(
        workspace,
        output_root=output_root,
        plan=plan,
        results=results,
        environment=process_environment,
    )
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score the exact frozen public baseline on authorized dev-A"
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--artifact-workspace",
        type=Path,
        help=(
            "git worktree containing the frozen selection and generation artifacts; "
            "defaults to --workspace"
        ),
    )
    parser.add_argument("--freeze-a-commit", required=True)
    parser.add_argument("--selection", type=Path, default=SELECTION_PATH)
    parser.add_argument("--expected-selection-sha256", required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    parser.add_argument("--c4-recovery-workspace", type=Path)
    parser.add_argument("--c4-recovery-manifest", type=Path)
    parser.add_argument("--expected-c4-recovery-sha256")
    parser.add_argument("--expected-official-scoreable-questions", type=int)
    parser.add_argument("--expected-sensitivity-scoreable-questions", type=int)
    parser.add_argument("--gold-conformance-receipt", type=Path)
    parser.add_argument("--expected-gold-conformance-sha256")
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def _expected_counts(arguments, workspace: Path, plan) -> tuple[int, int]:
    direct = (
        arguments.expected_official_scoreable_questions,
        arguments.expected_sensitivity_scoreable_questions,
    )
    if arguments.gold_conformance_receipt is None:
        if arguments.expected_gold_conformance_sha256 is not None or any(
            value is None for value in direct
        ):
            raise DevABaselineScoringError(
                "exact scoreable denominators or a conformance receipt are required"
            )
        return direct
    if any(value is not None for value in direct) or (
        arguments.expected_gold_conformance_sha256 is None
    ):
        raise DevABaselineScoringError(
            "gold-conformance receipt arguments are mutually exclusive with denominators"
        )
    try:
        return load_dev_a_gold_conformance_receipt(
            workspace,
            arguments.gold_conformance_receipt,
            expected_sha256=arguments.expected_gold_conformance_sha256,
            freeze_a_commit=plan.freeze_a_commit,
            release_sha256=plan.release_sha256,
            dev_a_ids_sha256=plan.dev_a_ids_sha256,
        )
    except DevAGoldConformanceError as error:
        raise DevABaselineScoringError(str(error)) from error


def _required_dsn(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DevABaselineScoringError(f"{name} must be set in the process environment")
    return value


def _output_root(value: Path) -> Path:
    selected = Path(value)
    if (
        selected.is_absolute()
        or not selected.parts
        or ".." in selected.parts
        or not selected.is_relative_to(RAW_ROOT)
    ):
        raise DevABaselineScoringError(
            "output root must be a confined autoresearch raw path"
        )
    return selected


def _selection_path(value: Path) -> Path:
    selected = Path(value)
    if (
        selected.is_absolute()
        or selected.parent != SELECTION_ROOT
        or not selected.name.endswith(".json")
    ):
        raise DevABaselineScoringError(
            "selection path must be a confined autoresearch state path"
        )
    return selected


def _require_pinned_postgres(admin_dsn: str) -> None:
    try:
        with psycopg.connect(admin_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('server_version_num')")
                row = cursor.fetchone()
    except Exception as error:
        raise DevABaselineScoringError(
            "cannot verify the PostgreSQL scorer runtime"
        ) from error
    if row != (PINNED_POSTGRES_SERVER_VERSION_NUM,):
        raise DevABaselineScoringError(
            "PostgreSQL scorer does not match the pinned server version"
        )

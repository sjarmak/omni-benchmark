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
    DevABaselineScoringError,
    prepare_dev_a_baseline_plan,
    publish_dev_a_baseline_results,
    require_scoreable_question_counts,
    score_dev_a_baseline_plan,
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
        freeze_a_commit=arguments.freeze_a_commit,
        expected_selection_sha256=arguments.expected_selection_sha256,
        expected_release_sha256=arguments.expected_release_sha256,
        environment=process_environment,
    )
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
    results = score_dev_a_baseline_plan(plan, provider)
    require_scoreable_question_counts(
        results,
        official=arguments.expected_official_scoreable_questions,
        sensitivity=arguments.expected_sensitivity_scoreable_questions,
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
    parser.add_argument("--freeze-a-commit", required=True)
    parser.add_argument("--expected-selection-sha256", required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    parser.add_argument(
        "--expected-official-scoreable-questions", type=int, required=True
    )
    parser.add_argument(
        "--expected-sensitivity-scoreable-questions", type=int, required=True
    )
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


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

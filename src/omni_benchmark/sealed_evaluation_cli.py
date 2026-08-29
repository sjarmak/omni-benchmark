"""Dry-default operator boundary for final sealed score publication."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .content_policy import ContentPolicy
from .dev_a_baseline_scoring import DevABaselineScoringError
from .dev_a_baseline_scoring_cli import (
    ADMIN_DSN_ENV,
    EXECUTION_DSN_ENV,
    _require_pinned_postgres,
    _required_dsn,
)
from .direct_question_loader import DirectQuestionLoadError, _committed, _public_records
from .freeze_b_control import load_freeze_b_control
from .postgres_isolation import PsycopgTemplateIsolationProvider
from .sealed_evaluation import (
    SealedEvaluationError,
    load_sealed_output_batch,
    prepare_sealed_evaluation_plan,
    publish_sealed_evaluation,
    score_sealed_evaluation,
)
from .sealed_execution_plan import (
    load_sealed_execution_plan,
    load_sealed_public_questions,
)


def sealed_evaluation_entrypoint() -> int:
    """Run with a sanitized no-traceback custody boundary."""
    try:
        return sealed_evaluation_main()
    except SealedEvaluationError as error:
        print(f"sealed evaluation failed: {error}", file=sys.stderr)
    except Exception:
        print("sealed evaluation failed: internal scorer error", file=sys.stderr)
    return 1


def sealed_evaluation_main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Preflight publicly by default; score only with explicit acknowledgement."""
    arguments = _parser().parse_args(argv)
    process_environment = dict(os.environ if environment is None else environment)
    workspace = arguments.workspace.resolve(strict=True)
    _require_exact_control_checkout(workspace, arguments.control_commit)
    plan = load_sealed_execution_plan(
        workspace,
        control_commit=arguments.control_commit,
        system_commit=arguments.system_commit,
        freeze_b_path=arguments.freeze_b,
        schedule_path=arguments.schedule,
        public_manifest_path=arguments.public_manifest,
    )
    control = load_freeze_b_control(
        workspace,
        control_commit=arguments.control_commit,
        system_commit=arguments.system_commit,
        manifest_path=arguments.freeze_b,
    )
    questions = load_sealed_public_questions(
        workspace,
        plan=plan,
        freeze_b=control.manifest,
        public_manifest_path=arguments.public_manifest,
    )
    batch = load_sealed_output_batch(
        workspace,
        output_root=arguments.cohort_root,
        plan=plan,
        freeze_b=control.manifest,
        questions=questions,
    )
    if not arguments.execute_sealed_scoring:
        print(
            json.dumps(
                {
                    "attempt_count": len(batch.attempts),
                    "cohort_count": len(batch.cohorts),
                    "freeze_b_sha256": batch.freeze_b_sha256,
                    "plan_sha256": batch.plan_sha256,
                    "schedule_sha256": batch.schedule_sha256,
                    "status": "validated_not_scored",
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0

    release_path, release_sha256, output_root = _execution_arguments(arguments)
    public_records = _committed_public_records(
        workspace,
        arguments.system_commit,
        arguments.public_manifest,
        process_environment,
    )
    scoring_plan = prepare_sealed_evaluation_plan(
        workspace,
        batch=batch,
        release_path=release_path,
        expected_release_sha256=release_sha256,
        public_records=public_records,
    )
    try:
        admin_dsn = _required_dsn(process_environment, ADMIN_DSN_ENV)
        execution_dsn = _required_dsn(process_environment, EXECUTION_DSN_ENV)
        _require_pinned_postgres(admin_dsn)
        provider = PsycopgTemplateIsolationProvider(
            admin_dsn,
            execution_dsn,
            {
                attempt.case.database: attempt.case.database
                for attempt in scoring_plan.attempts
            },
        )
    except (DevABaselineScoringError, ValueError) as error:
        raise SealedEvaluationError(
            "PostgreSQL scorer configuration is invalid"
        ) from error
    results = score_sealed_evaluation(scoring_plan, provider)
    summary = publish_sealed_evaluation(
        workspace,
        output_root=output_root,
        plan=scoring_plan,
        results=results,
    )
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


def _execution_arguments(arguments: Any) -> tuple[Path, str, Path]:
    if (
        arguments.release is None
        or arguments.expected_release_sha256 is None
        or arguments.output_root is None
    ):
        raise SealedEvaluationError(
            "sealed execution requires release path, release SHA-256, and output root"
        )
    return arguments.release, arguments.expected_release_sha256, arguments.output_root


def _committed_public_records(
    workspace: Path,
    system_commit: str,
    path: Path,
    environment: Mapping[str, str],
) -> dict[str, dict[str, Any]]:
    try:
        committed = _committed(workspace, system_commit, path)
        return _public_records(
            committed.content, ContentPolicy.from_environment(environment)
        )
    except DirectQuestionLoadError as error:
        raise SealedEvaluationError("frozen public manifest is invalid") from error


def _require_exact_control_checkout(workspace: Path, control_commit: str) -> None:
    try:
        head = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        raise SealedEvaluationError("cannot verify sealed control checkout") from error
    if head != control_commit or status:
        raise SealedEvaluationError(
            "sealed scoring requires the exact clean Freeze-B control checkout"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--control-commit", required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--freeze-b", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--public-manifest", type=Path, required=True)
    parser.add_argument("--cohort-root", type=Path, required=True)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--expected-release-sha256")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--execute-sealed-scoring", action="store_true")
    return parser

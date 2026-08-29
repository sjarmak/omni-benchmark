"""Explicit custody command for aggregate-only complete dev-A conformance."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .dev_a_baseline_scoring import DevABaselineScoringError
from .dev_a_baseline_scoring_cli import (
    ADMIN_DSN_ENV,
    EXECUTION_DSN_ENV,
    _require_pinned_postgres,
    _required_dsn,
)
from .dev_a_gold_conformance import (
    DevAGoldConformanceError,
    prepare_dev_a_gold_conformance_plan,
    publish_dev_a_gold_conformance,
    score_dev_a_gold_conformance,
)
from .postgres_isolation import PsycopgTemplateIsolationProvider


def dev_a_gold_conformance_entrypoint() -> int:
    """Run without exposing protected input or an unexpected traceback."""
    try:
        return dev_a_gold_conformance_main()
    except DevAGoldConformanceError as error:
        print(f"dev-A gold conformance failed: {error}", file=sys.stderr)
    except Exception:
        print("dev-A gold conformance failed: internal scorer error", file=sys.stderr)
    return 1


def dev_a_gold_conformance_main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Execute one explicit gold-only sweep and publish aggregate counts."""
    arguments = _parser().parse_args(argv)
    if not arguments.execute_gold_conformance:
        raise DevAGoldConformanceError(
            "gold conformance requires explicit execution acknowledgement"
        )
    process_environment = dict(os.environ if environment is None else environment)
    try:
        admin_dsn = _required_dsn(process_environment, ADMIN_DSN_ENV)
        execution_dsn = _required_dsn(process_environment, EXECUTION_DSN_ENV)
    except DevABaselineScoringError as error:
        raise DevAGoldConformanceError(str(error)) from error
    workspace = arguments.workspace.resolve(strict=True)
    try:
        _require_pinned_postgres(admin_dsn)
    except DevABaselineScoringError as error:
        raise DevAGoldConformanceError(
            "PostgreSQL scorer configuration is invalid"
        ) from error
    plan = prepare_dev_a_gold_conformance_plan(
        workspace,
        freeze_a_commit=arguments.freeze_a_commit,
        expected_release_sha256=arguments.expected_release_sha256,
        environment=process_environment,
    )
    try:
        templates = {case.database: case.database for case in plan.cases}
        provider = PsycopgTemplateIsolationProvider(
            admin_dsn,
            execution_dsn,
            templates,
        )
    except (DevABaselineScoringError, ValueError) as error:
        raise DevAGoldConformanceError(
            "PostgreSQL scorer configuration is invalid"
        ) from error
    result = score_dev_a_gold_conformance(plan, provider)
    receipt = publish_dev_a_gold_conformance(
        workspace,
        destination=arguments.destination,
        plan=plan,
        result=result,
    )
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--freeze-a-commit", required=True)
    parser.add_argument("--expected-release-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--execute-gold-conformance", action="store_true")
    return parser

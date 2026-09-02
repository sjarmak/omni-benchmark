#!/usr/bin/env python3
"""Reconcile the telemetry database against the frozen analysis artifacts.

Connects with ``--dsn`` or ``OMNI_BENCHMARK_TELEMETRY_DSN``, recomputes every
aggregate the database can reproduce, and prints one line per check with the
expected value, the observed value, and its status. Exits non-zero when any
check fails. ``--report PATH`` writes the same checks as JSON; the report is
never overwritten and never contains the connection string.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

from omni_benchmark.telemetry_db.reconcile import (
    GROUPS,
    ReconcileError,
    load_frozen_artifacts,
    reconcile,
    render_table,
    write_report,
)

DSN_ENV = "OMNI_BENCHMARK_TELEMETRY_DSN"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn", default=None, help=f"libpq connection string (default: ${DSN_ENV})"
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--report", type=Path, default=None, help="write JSON report")
    parser.add_argument(
        "--group",
        action="append",
        choices=GROUPS,
        default=None,
        help="run only this group (repeatable; default: every group)",
    )
    parser.add_argument(
        "--failures-only",
        action="store_true",
        help="print only checks that did not match",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dsn = args.dsn or os.environ.get(DSN_ENV)
    if not dsn:
        raise SystemExit(f"no connection string: pass --dsn or set {DSN_ENV}")
    try:
        artifacts = load_frozen_artifacts(args.repo_root.resolve())
        with psycopg.connect(dsn) as conn:
            result = reconcile(conn, artifacts, tuple(args.group or GROUPS))
        if args.report is not None:
            write_report(args.report, result)
    except ReconcileError as error:
        raise SystemExit(f"reconciliation aborted: {error}") from error
    shown = result.failures if args.failures_only else result.checks
    print(render_table(shown))
    summary = result.summary()
    loads = ", ".join(str(run["load_id"]) for run in result.load_runs) or "none"
    print(
        f"\n{summary['checks']} checks, {summary['matches']} matched, "
        f"{summary['failures']} failed; loads: {loads}"
    )
    if args.report is not None:
        print(f"report: {args.report}")
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main())

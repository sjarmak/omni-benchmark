#!/usr/bin/env python3
"""Load every public telemetry source into the benchmark telemetry database.

Without ``--dry-run`` the loader connects with ``--dsn`` or
``OMNI_BENCHMARK_TELEMETRY_DSN``, applies the schema, and upserts every source
inside one transaction. ``--dry-run`` reads every source and prints what would
be written without opening a connection.

The recorded ``system_commit`` is HEAD, and only when the runtime tree (the
paths a live run binds to plus the loader's own configuration) matches it.
``--allow-dirty-tree`` loads anyway and records ``system_commit`` as NULL.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg

from omni_benchmark.omni_probe_preflight import RUNTIME_PATHS
from omni_benchmark.telemetry_db.loader import LoadPlan, Sources, collect, load_all

DSN_ENV = "OMNI_BENCHMARK_TELEMETRY_DSN"
VERIFIED_PATHS = (*RUNTIME_PATHS, "config/telemetry_db")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--load-id", required=True, help="identifier recorded in load_run"
    )
    parser.add_argument(
        "--dsn", default=None, help=f"libpq connection string (default: ${DSN_ENV})"
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--system-commit",
        default=None,
        help="commit the load is expected to run at; must equal HEAD",
    )
    parser.add_argument(
        "--allow-dirty-tree",
        action="store_true",
        help="load from a modified runtime tree and record system_commit NULL",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="read sources; do not connect"
    )
    parser.add_argument("--skip-sealed", action="store_true")
    parser.add_argument("--skip-dev-a", action="store_true")
    return parser.parse_args(argv)


def plan_summary(plan: LoadPlan) -> dict[str, object]:
    return {
        "row_counts": plan.row_counts,
        "dropped": {source: dict(reasons) for source, reasons in plan.dropped.items()},
        "custody": dict(plan.custody),
        "arms": plan.notes.get("dev-a", {}).get("arms", {}),
        "manifests_hashed": len(plan.manifests),
    }


def _git(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"git {arguments[0]} failed in {repo_root}: {completed.stderr.strip()}"
        )
    return completed.stdout


def dirty_runtime_paths(repo_root: Path) -> tuple[str, ...]:
    """Tracked or untracked changes under the paths a load must be bound to."""
    status = _git(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *VERIFIED_PATHS,
    )
    return tuple(line[3:] for line in status.splitlines() if line)


def resolve_system_commit(
    repo_root: Path, explicit: str | None, *, allow_dirty_tree: bool
) -> str | None:
    """HEAD when the runtime tree matches it; None under ``allow_dirty_tree``."""
    dirty = dirty_runtime_paths(repo_root)
    if dirty and not allow_dirty_tree:
        raise SystemExit(
            "runtime tree differs from HEAD; commit or pass --allow-dirty-tree: "
            + ", ".join(dirty)
        )
    head = _git(repo_root, "rev-parse", "HEAD").strip()
    if explicit is not None and explicit != head:
        raise SystemExit(f"--system-commit {explicit} is not HEAD {head}")
    if dirty:
        print(f"warning: recording system_commit NULL; dirty: {dirty}", file=sys.stderr)
        return None
    return head


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sources = Sources(
        repo_root=args.repo_root.resolve(),
        include_dev_a=not args.skip_dev_a,
        include_sealed=not args.skip_sealed,
    )
    if args.dry_run:
        print(json.dumps(plan_summary(collect(sources)), indent=2, sort_keys=True))
        return 0
    dsn = args.dsn or os.environ.get(DSN_ENV)
    if not dsn:
        raise SystemExit(f"no connection string: pass --dsn or set {DSN_ENV}")
    system_commit = resolve_system_commit(
        sources.repo_root, args.system_commit, allow_dirty_tree=args.allow_dirty_tree
    )
    with psycopg.connect(dsn) as conn:
        result = load_all(sources, conn, args.load_id, system_commit)
    summary = plan_summary(result.plan)
    summary["load_id"] = result.load_id
    summary["system_commit"] = system_commit
    summary["upserted"] = dict(result.row_counts)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

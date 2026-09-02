#!/usr/bin/env python3
"""Write labeling prompts for a dev-A failure cohort, in deterministic batches.

Reads public telemetry only: the cohort is scored dev-A attempts, and every
column that reaches a prompt is on the allowlist in
``omni_benchmark.telemetry_db.label_context``. Split membership is verified
against ``--manifests-dir`` before any prompt is written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg

from omni_benchmark.telemetry_db.custody import CustodyViolation, load_split_ids
from omni_benchmark.telemetry_db.label_context import (
    Cohort,
    LabelContextError,
    context_rows,
    render_batch_prompt,
)

DEFAULT_MANIFESTS_DIR = Path("data/manifests")
DEFAULT_DSN_ENV = "OMNI_BENCHMARK_TELEMETRY_DSN"
FAILED_OUTCOMES = ("wrong_answer", "refused_or_error")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--manifests-dir", type=Path, default=DEFAULT_MANIFESTS_DIR)
    parser.add_argument("--dsn-env", default=DEFAULT_DSN_ENV)
    parser.add_argument("--arm", action="append", dest="arms", default=None)
    parser.add_argument("--outcome", action="append", dest="outcomes", default=None)
    parser.add_argument("--batch-size", type=int, default=14)
    parser.add_argument("--limit", type=int, default=None)
    return parser


def _sort_key(row: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(row["arm"]),
        str(row["terminal_failure_class"] or ""),
        str(row["attempt_id"]),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.batch_size < 1:
        print("batch size must be positive", file=sys.stderr)
        return 2
    dsn = os.environ.get(arguments.dsn_env)
    if not dsn:
        print(f"{arguments.dsn_env} is not set", file=sys.stderr)
        return 2
    cohort = Cohort(
        arms=tuple(arguments.arms or ("C1", "C2", "C3", "C4", "C5", "E02")),
        outcomes=tuple(arguments.outcomes or FAILED_OUTCOMES),
        limit=arguments.limit,
    )
    try:
        split = load_split_ids(arguments.manifests_dir)
        with psycopg.connect(dsn) as conn:
            rows = context_rows(conn, cohort, split)
    except (CustodyViolation, LabelContextError) as error:
        print(f"cohort rejected: {error}", file=sys.stderr)
        return 2
    if not rows:
        print("cohort selected no attempts", file=sys.stderr)
        return 1
    rows.sort(key=_sort_key)
    out_dir = arguments.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    batches = [
        rows[start : start + arguments.batch_size]
        for start in range(0, len(rows), arguments.batch_size)
    ]
    manifest = []
    for index, batch in enumerate(batches):
        path = out_dir / f"batch-{index:03d}.txt"
        path.write_text(render_batch_prompt(batch), encoding="utf-8")
        manifest.append(
            {
                "batch": index,
                "path": str(path),
                "attempts": [
                    {
                        "attempt_id": row["attempt_id"],
                        "generation_record_sha256": row["generation_record_sha256"],
                        "arm": row["arm"],
                    }
                    for row in batch
                ],
            }
        )
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "attempts": len(rows),
                "batches": len(batches),
                "manifest": str(manifest_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

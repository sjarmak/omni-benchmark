#!/usr/bin/env python3
"""Append one failure-taxonomy label to the git-tracked label ledger.

The attempt must belong to the dev-A split: the split ID files under
``--manifests-dir`` are read before anything is written, and a label for any
other instance is refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from omni_benchmark.telemetry_db.custody import CustodyViolation, load_split_ids
from omni_benchmark.telemetry_db.labels import LabelError, append_label
from omni_benchmark.telemetry_db.taxonomy import TAXONOMY_V1, TAXONOMY_VERSION


DEFAULT_LABELS_DIR = Path("experiments/labels")
DEFAULT_MANIFESTS_DIR = Path("data/manifests")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Categories for " + TAXONOMY_VERSION + ": " + ", ".join(TAXONOMY_V1),
    )
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS_DIR)
    parser.add_argument(
        "--manifests-dir",
        type=Path,
        default=DEFAULT_MANIFESTS_DIR,
        help="directory holding dev_a_ids.txt and test_ids.txt",
    )
    parser.add_argument("--pass-id", required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--generation-record-sha256", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--labeler", required=True, help="human:<name> or model:<name>")
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--taxonomy-version", default=TAXONOMY_VERSION)
    parser.add_argument(
        "--created-at",
        default=None,
        help="ISO-8601 UTC timestamp; defaults to the current time",
    )
    return parser


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    record_fields = {
        "attempt_id": arguments.attempt_id,
        "generation_record_sha256": arguments.generation_record_sha256,
        "taxonomy_version": arguments.taxonomy_version,
        "category": arguments.category,
        "labeler": arguments.labeler,
        "rationale": arguments.rationale,
        "created_at": arguments.created_at or _utc_now(),
    }
    try:
        split = load_split_ids(arguments.manifests_dir)
        record = append_label(
            arguments.labels_dir, arguments.pass_id, record_fields, split=split
        )
    except (LabelError, CustodyViolation) as error:
        print(f"label rejected: {error}", file=sys.stderr)
        return 2
    print(json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

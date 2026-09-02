#!/usr/bin/env python3
"""Append a completed labeling pass to the git-tracked label ledger.

Reads the per-batch label files a labeling pass produced, checks them against
the cohort manifest that pass was built from, and appends every record through
the same dev-A custody guard the single-label CLI uses. The pass is written in
one shot: if any record is invalid or any attempt is missing or duplicated,
nothing is written.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from omni_benchmark.telemetry_db.custody import (
    CustodyViolation,
    assert_dev_a_instance,
    load_split_ids,
)
from omni_benchmark.telemetry_db.labels import (
    LabelError,
    append_label,
    build_label_record,
    instance_of_label,
)
from omni_benchmark.telemetry_db.taxonomy import TAXONOMY_VERSION

DEFAULT_LABELS_DIR = Path("experiments/labels")
DEFAULT_MANIFESTS_DIR = Path("data/manifests")
RECORD_KEYS = frozenset(
    {"attempt_id", "generation_record_sha256", "category", "rationale"}
)


class IngestError(ValueError):
    """Raised when the pass does not cover its cohort exactly."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pass-id", required=True)
    parser.add_argument("--labeler", required=True, help="human:<name> or model:<name>")
    parser.add_argument("--labels-dir", type=Path, default=DEFAULT_LABELS_DIR)
    parser.add_argument("--manifests-dir", type=Path, default=DEFAULT_MANIFESTS_DIR)
    parser.add_argument("--taxonomy-version", default=TAXONOMY_VERSION)
    parser.add_argument("--created-at", default=None)
    return parser


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def read_pass_records(input_dir: Path) -> list[dict[str, str]]:
    """Read every batch file in ``input_dir`` as a flat list of label records."""
    paths = sorted(input_dir.glob("*.json"))
    if not paths:
        raise IngestError(f"no label files under {input_dir}")
    records: list[dict[str, str]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise IngestError(f"{path}: not valid JSON: {error}") from error
        if not isinstance(payload, list):
            raise IngestError(f"{path}: expected a JSON array of label records")
        for index, item in enumerate(payload):
            if not isinstance(item, dict) or set(item) != RECORD_KEYS:
                raise IngestError(
                    f"{path}[{index}]: each record needs exactly "
                    f"{', '.join(sorted(RECORD_KEYS))}"
                )
            records.append(item)
    return records


def check_coverage(
    records: Sequence[dict[str, str]], manifest: Sequence[dict[str, object]]
) -> None:
    """Every cohort attempt must be labeled exactly once, and nothing else."""
    expected = {
        (attempt["attempt_id"], attempt["generation_record_sha256"])
        for entry in manifest
        for attempt in entry["attempts"]  # type: ignore[index,union-attr]
    }
    seen: set[tuple[str, str]] = set()
    duplicates: list[tuple[str, str]] = []
    for record in records:
        key = (record["attempt_id"], record["generation_record_sha256"])
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if duplicates:
        raise IngestError(f"{len(duplicates)} attempts labeled more than once")
    missing = sorted(attempt for attempt, _ in expected - seen)
    unexpected = sorted(attempt for attempt, _ in seen - expected)
    if missing or unexpected:
        raise IngestError(
            f"{len(missing)} cohort attempts unlabeled, "
            f"{len(unexpected)} labels outside the cohort; "
            f"first missing: {missing[:3]}; first unexpected: {unexpected[:3]}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    ledger = arguments.labels_dir / f"{arguments.pass_id}.jsonl"
    if ledger.exists():
        print(f"{ledger} already exists; a pass is written once", file=sys.stderr)
        return 2
    created_at = arguments.created_at or _utc_now()
    try:
        manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
        records = read_pass_records(arguments.input_dir)
        check_coverage(records, manifest)
        split = load_split_ids(arguments.manifests_dir)
        fields = [
            {
                "attempt_id": record["attempt_id"],
                "generation_record_sha256": record["generation_record_sha256"],
                "taxonomy_version": arguments.taxonomy_version,
                "category": record["category"],
                "labeler": arguments.labeler,
                "rationale": record["rationale"],
                "created_at": created_at,
            }
            for record in records
        ]
        for entry in fields:
            record = build_label_record(entry, arguments.pass_id)
            assert_dev_a_instance(
                instance_of_label(record), split, f"label {record.label_id}"
            )
    except (IngestError, LabelError, CustodyViolation, OSError) as error:
        print(f"pass rejected: {error}", file=sys.stderr)
        return 2
    counts: dict[str, int] = {}
    try:
        for entry in fields:
            written = append_label(
                arguments.labels_dir, arguments.pass_id, entry, split=split
            )
            counts[written.category] = counts.get(written.category, 0) + 1
    except (LabelError, CustodyViolation) as error:
        print(f"pass partially written then rejected: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"labels": len(fields), "ledger": str(ledger), "categories": counts},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

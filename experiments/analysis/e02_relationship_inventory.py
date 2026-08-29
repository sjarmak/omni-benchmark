"""Aggregate the public-only E02 relationship candidate inventory."""

from __future__ import annotations

import argparse
import json
import stat
from collections import Counter
from pathlib import Path
from typing import Any

from omni_benchmark.semantic_relationships import plan_relationship_contracts


MAX_SCHEMA_BYTES = 64 * 1024 * 1024


def _records(path: Path) -> list[dict[str, Any]]:
    metadata = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > MAX_SCHEMA_BYTES
    ):
        raise ValueError(f"unsafe or oversized public schema artifact: {path}")
    content = path.read_bytes()
    if len(content) != metadata.st_size:
        raise ValueError(f"public schema artifact changed while reading: {path}")
    records = [json.loads(line) for line in content.splitlines()]
    if not records or any(not isinstance(record, dict) for record in records):
        raise ValueError("public schema JSONL must contain objects")
    return records


def _schema_paths(workspace: Path) -> list[Path]:
    paths = [
        workspace
        / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl"
    ]
    baseline = workspace / "semantic_models/public_baseline"
    for root in sorted(path for path in baseline.iterdir() if path.is_dir()):
        paths.append(root / "schema_ir" / f"{root.name}.schema.jsonl")
    return paths


def inventory(workspace: Path) -> dict[str, Any]:
    plans = [
        plan_relationship_contracts(_records(path))
        for path in _schema_paths(workspace.resolve(strict=True))
    ]
    relationships = [
        relationship for plan in plans for relationship in plan["relationships"]
    ]
    deferred = [item for plan in plans for item in plan["deferred"]]
    reasons = Counter(reason for item in deferred for reason in item["reasons"])
    return {
        "database_count": len(plans),
        "deferred_by_reason": dict(sorted(reasons.items())),
        "deferred_count": len(deferred),
        "exactly_one_count": sum(
            relationship["source_match"] == "exactly_one"
            for relationship in relationships
        ),
        "foreign_key_count": len(relationships) + len(deferred),
        "multi_column_count": sum(
            len(relationship["source_column_stable_ids"]) > 1
            for relationship in relationships
        ),
        "relationship_count": len(relationships),
        "schema_version": 1,
        "zero_or_one_count": sum(
            relationship["source_match"] == "zero_or_one"
            for relationship in relationships
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(inventory(arguments.workspace), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

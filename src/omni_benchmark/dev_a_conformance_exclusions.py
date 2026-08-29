"""Public-only derivation of fixed dev-A scorer-conformance exclusions."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DEV_A_IDS_PATH = Path("data/manifests/dev_a_ids.txt")
ELIGIBLE_MANIFEST_PATH = Path("data/manifests/eligible_questions.jsonl")
OFFICIAL_LOADER_PATH = Path(
    "data/raw/livesqlbench-large-v1/init-databases_postgresql_large_v1.sh"
)
TARGET_DATABASES = {
    "mental_healths_large": 34,
    "organ_transplant_large": 37,
}


class DevAConformanceExclusionError(ValueError):
    """Raised when the public inputs no longer reproduce the fixed frame."""


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def build_dev_a_conformance_exclusions(workspace: Path) -> dict[str, Any]:
    """Derive the authorized exclusion identity from committed public fields."""

    ids_content = (workspace / DEV_A_IDS_PATH).read_bytes()
    manifest_content = (workspace / ELIGIBLE_MANIFEST_PATH).read_bytes()
    dev_a_ids = ids_content.decode("utf-8").splitlines()
    if len(dev_a_ids) != 154 or len(set(dev_a_ids)) != 154:
        raise DevAConformanceExclusionError(
            "dev-A membership must contain 154 unique IDs"
        )

    dev_a_membership = set(dev_a_ids)
    selected: dict[str, list[str]] = {database: [] for database in TARGET_DATABASES}
    seen: set[str] = set()
    for line_number, line in enumerate(manifest_content.splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise DevAConformanceExclusionError(
                f"eligible manifest line {line_number} is invalid JSON"
            ) from error
        if not isinstance(record, dict):
            raise DevAConformanceExclusionError(
                f"eligible manifest line {line_number} is not an object"
            )
        instance_id = record.get("instance_id")
        database = record.get("selected_database")
        if instance_id not in dev_a_membership:
            continue
        if not isinstance(instance_id, str) or instance_id in seen:
            raise DevAConformanceExclusionError(
                "eligible manifest dev-A identities must be unique strings"
            )
        seen.add(instance_id)
        if database in selected:
            selected[database].append(instance_id)

    if seen != dev_a_membership:
        raise DevAConformanceExclusionError(
            "eligible manifest does not cover the exact dev-A membership"
        )
    counts = {
        database: len(instance_ids) for database, instance_ids in selected.items()
    }
    if counts != {"mental_healths_large": 9, "organ_transplant_large": 9}:
        raise DevAConformanceExclusionError(
            "public dev-A database counts no longer match the authorized frame"
        )

    excluded_ids = sorted(
        instance_id
        for instance_ids in selected.values()
        for instance_id in instance_ids
    )
    return {
        "counts": {
            "answerable_questions": 136,
            "scheduled_questions": 154,
            "unscorable_questions": 18,
        },
        "databases": [
            {
                "database": database,
                "official_loader_omitted_tables": omitted_tables,
                "unscorable_questions": counts[database],
            }
            for database, omitted_tables in TARGET_DATABASES.items()
        ],
        "disposition": "scheduled_but_unscorable",
        "failure_class": "gold_statement_error",
        "human_decision": {
            "bead_id": "omni-benchmark-1u8",
            "response": "A",
        },
        "instance_ids": excluded_ids,
        "kind": "dev-a-scorer-conformance-exclusions",
        "official_loader": {
            "path": OFFICIAL_LOADER_PATH.as_posix(),
            "semantics": "exact_case_sensitive_filename_match_on_linux",
        },
        "schema_version": 1,
        "scope": "c4-promotion-and-dev-a-reporting",
        "scorers": ["official_soft_ex", "corrected_multiset_sensitivity"],
        "sources": {
            "dev_a_ids_path": DEV_A_IDS_PATH.as_posix(),
            "dev_a_ids_sha256": _sha256(ids_content),
            "eligible_manifest_path": ELIGIBLE_MANIFEST_PATH.as_posix(),
            "eligible_manifest_sha256": _sha256(manifest_content),
        },
    }

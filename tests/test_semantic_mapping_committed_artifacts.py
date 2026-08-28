from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from omni_benchmark.semantic_mapping_publication import build_mapping_artifacts


REPOSITORY_ROOT = Path(__file__).parents[1]
SPEC_PATH = REPOSITORY_ROOT / "config" / "archeology_scan_public_mapping.json"
HKB_PATH = (
    REPOSITORY_ROOT
    / "semantic_models"
    / "public_ir"
    / "archeology_scan_large.hkb.jsonl"
)
SCHEMA_ROOT = REPOSITORY_ROOT / "semantic_models" / "public_schema_ir"
MAPPING_ROOT = REPOSITORY_ROOT / "semantic_models" / "public_mapping"
PROTECTED_KEYS = frozenset({"external_knowledge", "gold_sql", "sol_sql", "test_cases"})


def _records(content: bytes) -> list[dict[str, Any]]:
    return [json.loads(line) for line in content.splitlines()]


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def test_committed_mapping_regenerates_exactly_from_public_inputs() -> None:
    manifest_bytes = (SCHEMA_ROOT / "manifest.json").read_bytes()
    expected, manifest = build_mapping_artifacts(
        SPEC_PATH.read_bytes(),
        HKB_PATH.read_bytes(),
        (SCHEMA_ROOT / "archeology_scan_large.schema.jsonl").read_bytes(),
        manifest_bytes,
    )
    committed = (MAPPING_ROOT / manifest["output"]["file"]).read_bytes()

    assert committed == expected
    assert hashlib.sha256(committed).hexdigest() == (
        "a54234cf768619bd15260a87ff3cd55765d006eaa4bd20bc05fd427ed24eeae6"
    )
    assert json.loads((MAPPING_ROOT / "manifest.json").read_bytes()) == manifest


def test_committed_mapping_preserves_classification_and_provenance() -> None:
    manifest = json.loads((MAPPING_ROOT / "manifest.json").read_bytes())
    records = _records((MAPPING_ROOT / manifest["output"]["file"]).read_bytes())
    indexed = {int(item["hkb_stable_id"].rsplit(":", 1)[1]): item for item in records}

    assert manifest["counts"] == {
        "dispositions": {
            "compile": 14,
            "context_only": 10,
            "defer_cross_grain": 20,
            "unsupported": 10,
        },
        "hkb_nodes": 54,
    }
    assert indexed[16]["dependency_audit"]["missing_references"] == [
        "archeology_scan_large:hkb:29"
    ]
    assert indexed[42]["dependency_audit"]["missing_references"] == [
        "archeology_scan_large:hkb:12"
    ]
    assert indexed[52]["dependency_audit"]["redundant_references"] == [
        "archeology_scan_large:hkb:26"
    ]
    assert all(
        item["provenance"]["intervention"] == "human_general_modeling_inference"
        and item["provenance"]["transformation_class"] == "interpretive"
        for item in records
    )
    assert PROTECTED_KEYS.isdisjoint(_keys(records))

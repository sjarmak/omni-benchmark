from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from omni_benchmark.hkb_inventory import load_hkb_source_inventory
from omni_benchmark.semantic_bundle_publication import build_bundle_artifacts
from omni_benchmark.semantic_mapping_publication import build_mapping_artifacts


ROOT = Path(__file__).resolve().parents[1]
HKB_INVENTORY = ROOT / "config/public_hkb_sources.json"
BASELINE_ROOT = ROOT / "semantic_models/public_baseline"
PROTECTED_KEYS = frozenset(
    {
        "expected_result",
        "external_knowledge",
        "gold_result",
        "gold_sql",
        "oracle_hint",
        "oracle_sql",
        "sol_sql",
        "test_case",
        "test_cases",
        "test_correctness",
    }
)


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def _databases() -> list[str]:
    inventory = load_hkb_source_inventory(HKB_INVENTORY)
    return sorted(
        item.database
        for item in inventory.files
        if item.database != "archeology_scan_large"
    )


def test_committed_semantic_fanout_is_complete_and_public_only() -> None:
    for database in _databases():
        root = BASELINE_ROOT / database
        mapping_manifest = json.loads((root / "mapping/manifest.json").read_bytes())
        bundle_manifest = json.loads((root / "bundle/manifest.json").read_bytes())
        mapping_bytes = (root / "mapping" / f"{database}.mapping.jsonl").read_bytes()
        mapping_records = [json.loads(line) for line in mapping_bytes.splitlines()]
        hkb_records = (
            (ROOT / "semantic_models/public_ir" / f"{database}.hkb.jsonl")
            .read_bytes()
            .splitlines()
        )

        assert mapping_manifest["database"] == database
        assert (
            mapping_manifest["output"]["sha256"]
            == hashlib.sha256(mapping_bytes).hexdigest()
        )
        assert mapping_manifest["validation"] == {
            "all_hkb_nodes_classified_once": True,
            "all_schema_bindings_resolve": True,
            "hidden_annotations_used": False,
            "public_inputs_only": True,
            "status": "passed",
        }
        assert (
            sum(mapping_manifest["counts"]["dispositions"].values())
            == (mapping_manifest["counts"]["hkb_nodes"])
        )
        assert len(mapping_records) == len(hkb_records)
        assert all(
            record["provenance"]["intervention"]
            == "agent_assisted_public_modeling_inference"
            for record in mapping_records
        )
        assert bundle_manifest["database"] == database
        assert bundle_manifest["validation"] == {
            "all_compile_mappings_materialized": True,
            "hidden_annotations_used": False,
            "joins_generated": False,
            "public_inputs_only": True,
            "status": "passed",
        }
        assert PROTECTED_KEYS.isdisjoint(
            _keys({"mapping": mapping_manifest, "bundle": bundle_manifest})
        )
        expected_files = {item["file"] for item in bundle_manifest["files"]}
        assert {path.name for path in (root / "bundle").iterdir()} == {
            *expected_files,
            "manifest.json",
        }
        for item in bundle_manifest["files"]:
            content = (root / "bundle" / item["file"]).read_bytes()
            assert item["sha256"] == hashlib.sha256(content).hexdigest()
            assert item["size_bytes"] == len(content)


def test_committed_semantic_fanout_regenerates_exactly() -> None:
    for database in _databases():
        root = BASELINE_ROOT / database
        hkb = ROOT / "semantic_models/public_ir" / f"{database}.hkb.jsonl"
        schema = root / "schema_ir" / f"{database}.schema.jsonl"
        schema_manifest = root / "schema_ir/manifest.json"
        mapping_spec = root / "mapping.spec.json"
        mapping = root / "mapping" / f"{database}.mapping.jsonl"
        mapping_manifest = root / "mapping/manifest.json"
        bundle_spec = root / "bundle.spec.json"

        regenerated_mapping, regenerated_mapping_manifest = build_mapping_artifacts(
            mapping_spec.read_bytes(),
            hkb.read_bytes(),
            schema.read_bytes(),
            schema_manifest.read_bytes(),
        )
        assert mapping.read_bytes() == regenerated_mapping
        assert json.loads(mapping_manifest.read_bytes()) == regenerated_mapping_manifest

        regenerated_files, regenerated_bundle_manifest = build_bundle_artifacts(
            bundle_spec.read_bytes(),
            hkb.read_bytes(),
            schema.read_bytes(),
            mapping.read_bytes(),
            mapping_manifest.read_bytes(),
        )
        assert json.loads((root / "bundle/manifest.json").read_bytes()) == (
            regenerated_bundle_manifest
        )
        for name, expected in regenerated_files.items():
            assert (root / "bundle" / name).read_bytes() == expected

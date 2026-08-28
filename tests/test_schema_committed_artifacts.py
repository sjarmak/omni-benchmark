from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.hkb_inventory import load_hkb_source_inventory
from omni_benchmark.schema_ir import generate_public_schema_ir
from omni_benchmark.schema_source_inventory import load_schema_source_inventory


REPOSITORY_ROOT = Path(__file__).parents[1]
SCHEMA_INVENTORY_PATH = REPOSITORY_ROOT / "config" / "public_schema_sources.json"
HKB_INVENTORY_PATH = REPOSITORY_ROOT / "config" / "public_hkb_sources.json"
CANARY_SCHEMA_IR_ROOT = REPOSITORY_ROOT / "semantic_models" / "public_schema_ir"
FANOUT_SCHEMA_IR_ROOT = REPOSITORY_ROOT / "semantic_models" / "public_baseline"


def test_committed_inventory_pins_schema_metadata_for_every_hkb_database() -> None:
    schema_inventory = load_schema_source_inventory(SCHEMA_INVENTORY_PATH)
    hkb_inventory = load_hkb_source_inventory(HKB_INVENTORY_PATH)
    expected_databases = {item.database for item in hkb_inventory.files}

    assert schema_inventory.dataset == hkb_inventory.dataset
    assert schema_inventory.revision == hkb_inventory.revision
    assert len(schema_inventory.files) == 36
    assert {item.database for item in schema_inventory.files} == expected_databases
    assert sum(item.size for item in schema_inventory.files) == 6_003_364
    assert schema_inventory.inventory_sha256 == (
        "2b833d1524695ac811bbeac2a78b00815767b793511a74f35ed913b521796c3a"
    )
    assert (
        schema_inventory.inventory_sha256
        == hashlib.sha256(SCHEMA_INVENTORY_PATH.read_bytes()).hexdigest()
    )


def test_committed_inventory_matches_the_eligible_population_databases() -> None:
    inventory = load_schema_source_inventory(SCHEMA_INVENTORY_PATH)
    eligible_path = REPOSITORY_ROOT / "data" / "manifests" / "eligible_questions.jsonl"
    eligible_databases = {
        json.loads(line)["selected_database"]
        for line in eligible_path.read_text(encoding="utf-8").splitlines()
    }

    assert {item.database for item in inventory.files} == eligible_databases


def test_committed_canary_schema_ir_is_hash_bound_and_row_free() -> None:
    manifest_path = CANARY_SCHEMA_IR_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    ir_path = CANARY_SCHEMA_IR_ROOT / manifest["output"]["file"]
    ir_bytes = ir_path.read_bytes()
    records = [json.loads(line) for line in ir_bytes.splitlines()]

    assert manifest["database"] == "archeology_scan_large"
    assert manifest["counts"] == {
        "columns": 959,
        "foreign_keys": 77,
        "primary_keys": 51,
        "structured_columns": 12,
        "structured_leaves": 92,
        "tables": 51,
    }
    assert manifest["output"]["sha256"] == hashlib.sha256(ir_bytes).hexdigest()
    assert manifest["output"]["sha256"] == (
        "e2044dc11b055e08046153de8c9cec9d121f037391d5b757c8cd071dd607162f"
    )
    assert manifest["source"]["companion_hkb_ir"]["sha256"] == (
        "c6b20ec0e101f080712255645554cea2685deca7929a8c6d4c3391aeecf92d37"
    )
    assert manifest["source"]["companion_hkb_ir"]["manifest_sha256"] == (
        "e6fa23fa6fcc821104c3854271e1cb6e8cfba7a841a16c9613d7e8a3c497e35d"
    )
    assert len(records) == 1_179
    assert {record["record_kind"] for record in records} == {
        "column",
        "foreign_key",
        "structured_leaf",
        "table",
    }
    assert all(
        not {"sol_sql", "gold_sql", "external_knowledge", "test_cases"}.intersection(
            record
        )
        for record in records
    )
    assert b"First 3 rows:" not in ir_bytes


def test_committed_fanout_schema_ir_is_complete_hash_bound_and_row_free() -> None:
    hkb_inventory = load_hkb_source_inventory(HKB_INVENTORY_PATH)
    expected_databases = {
        item.database
        for item in hkb_inventory.files
        if item.database != "archeology_scan_large"
    }
    observed_databases = {
        path.parent.parent.name
        for path in FANOUT_SCHEMA_IR_ROOT.glob("*/schema_ir/manifest.json")
    }

    assert observed_databases == expected_databases
    for database in sorted(expected_databases):
        root = FANOUT_SCHEMA_IR_ROOT / database / "schema_ir"
        manifest_bytes = (root / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        output = root / f"{database}.schema.jsonl"
        output_bytes = output.read_bytes()

        assert {path.name for path in root.iterdir()} == {
            f"{database}.schema.jsonl",
            "manifest.json",
        }
        assert manifest["database"] == database
        assert manifest["output"] == {
            "file": output.name,
            "sha256": hashlib.sha256(output_bytes).hexdigest(),
        }
        assert manifest["validation"] == {
            "all_ddl_columns_have_meanings": True,
            "all_key_references_resolve": True,
            "all_meanings_resolve_to_ddl_columns": True,
            "sample_rows_emitted": 0,
            "stable_ids_unique": True,
            "status": "passed",
        }
        assert b"First 3 rows:" not in output_bytes
        assert b'"gold_sql"' not in output_bytes
        assert b'"external_knowledge"' not in output_bytes


@pytest.mark.skipif(
    not (REPOSITORY_ROOT / "data/raw/livesqlbench-large-v1/schema").exists(),
    reason="requires fetched pinned public schema sources",
)
def test_committed_fanout_schema_ir_regenerates_exactly(tmp_path: Path) -> None:
    hkb_inventory = load_hkb_source_inventory(HKB_INVENTORY_PATH)
    databases = sorted(
        item.database
        for item in hkb_inventory.files
        if item.database != "archeology_scan_large"
    )

    for database in databases:
        generated_root = tmp_path / database
        manifest = generate_public_schema_ir(
            REPOSITORY_ROOT / "data/raw/livesqlbench-large-v1/schema",
            SCHEMA_INVENTORY_PATH,
            generated_root,
            database=database,
            companion_hkb_ir=(
                REPOSITORY_ROOT
                / "semantic_models"
                / "public_ir"
                / f"{database}.hkb.jsonl"
            ),
        )
        committed_root = FANOUT_SCHEMA_IR_ROOT / database / "schema_ir"
        assert (generated_root / "manifest.json").read_bytes() == (
            committed_root / "manifest.json"
        ).read_bytes()
        assert (generated_root / manifest["output"]["file"]).read_bytes() == (
            committed_root / manifest["output"]["file"]
        ).read_bytes()

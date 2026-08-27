from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from omni_benchmark.hkb_inventory import load_hkb_source_inventory


REPOSITORY_ROOT = Path(__file__).parents[1]
INVENTORY_PATH = REPOSITORY_ROOT / "config" / "public_hkb_sources.json"
IR_ROOT = REPOSITORY_ROOT / "semantic_models" / "public_ir"


def test_committed_inventory_pins_all_public_hkb_files() -> None:
    inventory = load_hkb_source_inventory(INVENTORY_PATH)
    public_databases = {
        json.loads(line)["selected_database"]
        for line in (
            REPOSITORY_ROOT / "data" / "manifests" / "eligible_questions.jsonl"
        )
        .read_text(encoding="utf-8")
        .splitlines()
    }

    assert inventory.dataset == "birdsql/livesqlbench-large-v1"
    assert inventory.revision == "a418e108d5cbb4cf9b783a928eff5e924ad2460d"
    assert len(inventory.files) == 18
    assert {item.database for item in inventory.files} == public_databases
    assert sum(item.size for item in inventory.files) == 429_459


def test_committed_public_ir_is_hash_bound_and_complete() -> None:
    manifest_path = IR_ROOT / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inventory_sha256 = hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest()

    assert manifest["source"]["inventory_sha256"] == inventory_sha256
    assert manifest["counts"] == {
        "calculation_knowledge": 430,
        "databases": 18,
        "dependency_edges": 945,
        "domain_knowledge": 462,
        "entries": 1090,
        "entries_with_dependencies": 560,
        "maximum_dependency_depth": 6,
        "no_dependency_empty_list": 21,
        "no_dependency_sentinel_minus_one": 509,
        "value_illustration": 198,
    }
    observed_types: Counter[str] = Counter()
    observed_entries = 0
    for database, metadata in manifest["databases"].items():
        ir_path = IR_ROOT / metadata["ir_file"]
        assert hashlib.sha256(ir_path.read_bytes()).hexdigest() == metadata["ir_sha256"]
        records = [json.loads(line) for line in ir_path.read_text().splitlines()]
        assert all(record["database"] == database for record in records)
        assert all(
            record["stable_id"].startswith(f"{database}:hkb:") for record in records
        )
        assert all(
            set(record["provenance"])
            == {
                "content",
                "intervention",
                "source",
                "transformation_class",
            }
            for record in records
        )
        assert all(
            not {"sol_sql", "external_knowledge", "test_cases"}.intersection(record)
            for record in records
        )
        observed_types.update(record["source_type"] for record in records)
        observed_entries += len(records)
    assert observed_entries == 1090
    assert observed_types == {
        "calculation_knowledge": 430,
        "domain_knowledge": 462,
        "value_illustration": 198,
    }

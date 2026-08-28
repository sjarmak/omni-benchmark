from __future__ import annotations

import hashlib
import json
from pathlib import Path

from omni_benchmark.hkb_inventory import load_hkb_source_inventory
from omni_benchmark.schema_source_inventory import load_schema_source_inventory


REPOSITORY_ROOT = Path(__file__).parents[1]
SCHEMA_INVENTORY_PATH = REPOSITORY_ROOT / "config" / "public_schema_sources.json"
HKB_INVENTORY_PATH = REPOSITORY_ROOT / "config" / "public_hkb_sources.json"


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

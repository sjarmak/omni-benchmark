from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.database_inventory import (
    InventoryError,
    fingerprint_dump_directory,
    load_database_inventory,
    parse_restore_order,
    verify_database_dump,
    verify_restore_order,
)


INVENTORY = Path("config/databases/livesqlbench-large-v1.json")


def test_public_inventory_is_complete_and_secret_free() -> None:
    inventory = load_database_inventory(INVENTORY)

    assert inventory.canary == "archeology_scan_large"
    assert len(inventory.databases) == 18
    assert len({database.name for database in inventory.databases}) == 18
    assert all(len(database.dump_sha256) == 64 for database in inventory.databases)
    assert all(database.dump_file_count > 0 for database in inventory.databases)
    assert all(database.dump_size_bytes > 0 for database in inventory.databases)
    assert all(
        database.managed_mirror.provider == "neon" for database in inventory.databases
    )
    assert all(
        database.managed_mirror.organization_id == "org-steep-term-23543236"
        for database in inventory.databases
    )
    assert (
        len({database.managed_mirror.project_id for database in inventory.databases})
        == 18
    )
    assert (
        len({database.managed_mirror.branch_id for database in inventory.databases})
        == 18
    )
    assert all(
        database.managed_mirror.runtime_role == "omni_benchmark_reader"
        for database in inventory.databases
    )
    assert all(
        database.verification.external_parity for database in inventory.databases
    )
    assert all(
        database.verification.readonly_role_verified for database in inventory.databases
    )
    assert all(
        database.verification.table_count > 0 for database in inventory.databases
    )
    assert all(database.verification.row_count > 0 for database in inventory.databases)
    assert all(
        database.verification.postgres_server_version_num == "180006"
        for database in inventory.databases
    )
    assert len({database.omni_connection.id for database in inventory.databases}) == 18
    assert all(
        database.omni_connection.name == f"LiveSQLBench {database.name}"
        for database in inventory.databases
    )
    records = {database.name: database for database in inventory.databases}
    assert records["organ_transplant_large"].dump_sha256 == (
        "e8fbf464d52b3faa9441856b66077868cfddffe26202cac204ef82b23c42b837"
    )
    assert records["labor_certification_applications_large"].scorer_omitted_tables == (
        "training_program_worker_link",
    )
    assert len(records["mental_healths_large"].scorer_omitted_tables) == 34
    assert len(records["organ_transplant_large"].scorer_omitted_tables) == 37
    assert records["mental_healths_large"].scorer_continues_after_sql_error is True
    assert records["organ_transplant_large"].scorer_continues_after_sql_error is True
    assert (
        records[
            "labor_certification_applications_large"
        ].scorer_continues_after_sql_error
        is False
    )
    assert all(
        not database.scorer_omitted_tables
        for name, database in records.items()
        if name
        not in {
            "labor_certification_applications_large",
            "mental_healths_large",
            "organ_transplant_large",
        }
    )
    serialized = INVENTORY.read_text(encoding="utf-8").lower()
    assert "postgresql" + "://" not in serialized
    assert "password" not in serialized
    assert "token" not in serialized


def test_inventory_rejects_connection_urls(tmp_path: Path) -> None:
    path = tmp_path / "inventory.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "benchmark": "fixture",
                "canary": "fixture_db",
                "postgres_major": 18,
                "sources": {"dump_url": "postgresql" + "://example.invalid/db"},
                "databases": [{"name": "fixture_db", "alias": "fixture"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(InventoryError, match="connection URL"):
        load_database_inventory(path)


@pytest.mark.parametrize(
    ("object_name", "unexpected_key"),
    [
        ("managed_mirror", "endpoint"),
        ("managed_mirror", "password"),
        ("verification", "note"),
        ("omni_connection", "host"),
    ],
)
def test_inventory_rejects_unexpected_external_metadata(
    tmp_path: Path, object_name: str, unexpected_key: str
) -> None:
    raw = json.loads(INVENTORY.read_text(encoding="utf-8"))
    raw["databases"][0][object_name][unexpected_key] = "must-not-be-retained"
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(InventoryError, match=f"unexpected {object_name} keys"):
        load_database_inventory(path)


def test_inventory_rejects_invalid_format_version(tmp_path: Path) -> None:
    raw = json.loads(INVENTORY.read_text(encoding="utf-8"))
    raw["format_version"] = "2"
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(InventoryError, match="format_version"):
        load_database_inventory(path)


@pytest.mark.parametrize(
    ("object_name", "field"),
    [
        ("managed_mirror", "project_id"),
        ("managed_mirror", "branch_id"),
        ("omni_connection", "id"),
    ],
)
def test_inventory_rejects_duplicate_external_ids(
    tmp_path: Path, object_name: str, field: str
) -> None:
    raw = json.loads(INVENTORY.read_text(encoding="utf-8"))
    raw["databases"][1][object_name][field] = raw["databases"][0][object_name][field]
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(InventoryError, match="external IDs must be unique"):
        load_database_inventory(path)


def test_inventory_rejects_connection_without_passed_gates(tmp_path: Path) -> None:
    raw = json.loads(INVENTORY.read_text(encoding="utf-8"))
    raw["databases"][0]["verification"]["external_parity"] = False
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(InventoryError, match="requires passed verification gates"):
        load_database_inventory(path)


def test_format_one_bootstrap_inventory_allows_absent_external_metadata(
    tmp_path: Path,
) -> None:
    raw = json.loads(INVENTORY.read_text(encoding="utf-8"))
    raw["format_version"] = 1
    raw.pop("sources")
    raw.pop("canary_verification")
    for database in raw["databases"]:
        database.pop("managed_mirror")
        database.pop("verification")
        database.pop("omni_connection")
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    inventory = load_database_inventory(path)

    assert all(database.managed_mirror is None for database in inventory.databases)
    assert all(database.verification is None for database in inventory.databases)
    assert all(database.omni_connection is None for database in inventory.databases)


@pytest.mark.parametrize(
    ("container", "field", "value", "message"),
    [
        (
            "sources",
            "public_dump_url",
            "https://ep-example.us-east-2.aws.neon" + ".tech/db",
            "managed database endpoint",
        ),
        (
            "canary_verification",
            "postgres_image",
            "ep-example.us-east-2.aws.neon" + ".tech",
            "managed database endpoint",
        ),
        (
            "sources",
            "public_dump_url",
            "https://user:secret@example.invalid/public.zip",
            "embedded credentials",
        ),
        (
            "sources",
            "public_dump_url",
            "https://synthetic-token@example.invalid/public.zip",
            "embedded credentials",
        ),
        (
            "sources",
            "public_dump_url",
            "https://:synthetic-pass@example.invalid/public.zip",
            "embedded credentials",
        ),
        (
            "canary_verification",
            "postgres_image",
            "ep" + "-synthetic-endpoint",
            "managed database endpoint",
        ),
    ],
)
def test_inventory_rejects_endpoint_or_credentials_in_allowed_string_fields(
    tmp_path: Path, container: str, field: str, value: str, message: str
) -> None:
    raw = json.loads(INVENTORY.read_text(encoding="utf-8"))
    raw[container][field] = value
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(InventoryError, match=message):
        load_database_inventory(path)


def test_inventory_rejects_bare_endpoint_id_in_managed_metadata(
    tmp_path: Path,
) -> None:
    raw = json.loads(INVENTORY.read_text(encoding="utf-8"))
    raw["databases"][0]["managed_mirror"]["project_id"] = "ep" + "-synthetic-endpoint"
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(InventoryError, match="managed database endpoint"):
        load_database_inventory(path)


def test_dump_fingerprint_is_path_independent_and_detects_changes(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for root in (first, second):
        (root / "a.sql").write_bytes(b"CREATE TABLE a (id integer);\n")
        (root / "b.sql").write_bytes(b"INSERT INTO a VALUES (1);\n")

    expected_file_hash = hashlib.sha256((first / "a.sql").read_bytes()).hexdigest()
    first_result = fingerprint_dump_directory(first)
    second_result = fingerprint_dump_directory(second)

    assert first_result == second_result
    assert first_result.files[0].sha256 == expected_file_hash
    (second / "b.sql").write_bytes(b"INSERT INTO a VALUES (2);\n")
    assert fingerprint_dump_directory(second).sha256 != first_result.sha256


def test_dump_verification_rejects_content_not_pinned_for_database(
    tmp_path: Path,
) -> None:
    inventory = load_database_inventory(INVENTORY)
    dump = tmp_path / "dump"
    dump.mkdir()
    (dump / "table.sql").write_text("SELECT 1;\n", encoding="utf-8")

    with pytest.raises(InventoryError, match="does not match pinned inventory"):
        verify_database_dump(inventory.databases[0], dump)


def test_restore_order_parser_reads_pinned_upstream_mapping() -> None:
    source = """
declare -A DATABASE_MAPPING=(
    ["archeology_scan_large_template"]="sites scans ArtifactConditionAssessments"
    ["robot_fault_prediction_large_template"]="robot_record joint_condition"
)
"""

    assert parse_restore_order(source) == {
        "archeology_scan_large": (
            "sites",
            "scans",
            "ArtifactConditionAssessments",
        ),
        "robot_fault_prediction_large": ("robot_record", "joint_condition"),
    }


def test_restore_order_parser_rejects_duplicate_database() -> None:
    source = """
    ["fixture_template"]="first"
    ["fixture_template"]="second"
"""

    with pytest.raises(InventoryError, match="duplicate restore order"):
        parse_restore_order(source)


def test_restore_order_must_match_pinned_canonical_file(tmp_path: Path) -> None:
    inventory = load_database_inventory(INVENTORY)
    canonical = Path("config/databases/restore-order-large-v1.json")
    assert len(verify_restore_order(inventory, canonical)) == 18

    changed = tmp_path / "changed.json"
    changed.write_bytes(canonical.read_bytes() + b"\n")
    with pytest.raises(InventoryError, match="restore-order SHA-256"):
        verify_restore_order(inventory, changed)

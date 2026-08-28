from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.schema_inspection import (
    SchemaInspectionError,
    inspect_public_schema_sources,
)


DATASET = "birdsql/livesqlbench-large-v1"
REVISION = "a418e108d5cbb4cf9b783a928eff5e924ad2460d"


def _git_blob_oid(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _source(database: str, kind: str, content: bytes) -> dict[str, object]:
    suffix = {
        "column_meanings": "column_meaning_base.json",
        "schema": "schema.txt",
    }[kind]
    return {
        "database": database,
        "kind": kind,
        "path": f"{database}/{database}_{suffix}",
        "oid": _git_blob_oid(content),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_sources(tmp_path: Path) -> tuple[Path, Path]:
    database = "alpha_large"
    schema = (
        "CREATE TABLE first_table (\n"
        "id bigint NOT NULL\n"
        ");\n\n"
        "First 3 rows:\n"
        "value containing CREATE TABLE is sample data\n"
        "...\n\n\n"
        "CREATE TABLE second_table (\n"
        "payload jsonb NULL\n"
        ");\n\n"
        "First 3 rows:\n"
        "{}\n"
        "...\n"
    ).encode()
    meanings = json.dumps(
        {
            f"{database}|first_table|id": "BIGINT. Identifier.",
            f"{database}|second_table|payload": {
                "column_meaning": "JSONB payload.",
                "fields_meaning": {
                    "flat": "TEXT. Flat field.",
                    "nested": {"leaf": "REAL. Nested field."},
                    "sequence": ["TEXT. First item.", "TEXT. Second item."],
                },
            },
        },
        sort_keys=True,
    ).encode()
    source_root = tmp_path / "source"
    database_root = source_root / database
    database_root.mkdir(parents=True)
    (database_root / f"{database}_schema.txt").write_bytes(schema)
    (database_root / f"{database}_column_meaning_base.json").write_bytes(meanings)
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": DATASET,
                "revision": REVISION,
                "files": [
                    _source(database, "schema", schema),
                    _source(database, "column_meanings", meanings),
                ],
            }
        )
    )
    return inventory_path, source_root


def test_inspection_counts_only_ddl_and_preserves_nested_meaning_shape(
    tmp_path: Path,
) -> None:
    inventory_path, source_root = _write_sources(tmp_path)

    report = inspect_public_schema_sources(inventory_path, source_root)

    assert report["dataset"] == DATASET
    assert report["revision"] == REVISION
    assert report["counts"] == {
        "bytes": sum(item["bytes"] for item in report["databases"].values()),
        "column_meanings": 2,
        "databases": 1,
        "ddl_tables": 2,
        "files": 2,
        "structured_columns": 1,
        "structured_leaf_descriptions": 4,
        "structured_maximum_depth": 2,
        "structured_top_level_fields": 3,
    }
    assert report["databases"]["alpha_large"]["ddl_tables"] == 2


def test_inspection_rejects_malformed_schema_export(tmp_path: Path) -> None:
    inventory_path, source_root = _write_sources(tmp_path)
    schema_path = source_root / "alpha_large" / "alpha_large_schema.txt"
    schema = schema_path.read_bytes().replace(b"First 3 rows:", b"Rows:")
    schema_path.write_bytes(schema)
    value = json.loads(inventory_path.read_text())
    schema_record = next(item for item in value["files"] if item["kind"] == "schema")
    schema_record.update(_source("alpha_large", "schema", schema))
    inventory_path.write_text(json.dumps(value))

    with pytest.raises(SchemaInspectionError, match="First 3 rows"):
        inspect_public_schema_sources(inventory_path, source_root)


def test_inspection_rejects_excessive_structured_meaning_depth(
    tmp_path: Path,
) -> None:
    inventory_path, source_root = _write_sources(tmp_path)
    database = "alpha_large"
    nested: object = "TEXT. Leaf."
    for index in range(40):
        nested = {f"level_{index}": nested}
    meanings = json.dumps(
        {
            f"{database}|second_table|payload": {
                "column_meaning": "JSONB payload.",
                "fields_meaning": {"nested": nested},
            }
        }
    ).encode()
    meaning_path = source_root / database / f"{database}_column_meaning_base.json"
    meaning_path.write_bytes(meanings)
    inventory = json.loads(inventory_path.read_text())
    inventory_path.write_text(
        json.dumps(
            {
                **inventory,
                "files": [
                    _source(database, "column_meanings", meanings)
                    if item["kind"] == "column_meanings"
                    else item
                    for item in inventory["files"]
                ],
            }
        )
    )

    with pytest.raises(SchemaInspectionError, match="maximum supported depth"):
        inspect_public_schema_sources(inventory_path, source_root)


def test_inspection_rejects_source_root_with_symlinked_parent(
    tmp_path: Path,
) -> None:
    inventory_path, source_root = _write_sources(tmp_path)
    outside = tmp_path / "outside"
    source_root.rename(outside)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)

    with pytest.raises(SchemaInspectionError, match="regular non-symlink"):
        inspect_public_schema_sources(inventory_path, linked_parent / "outside")

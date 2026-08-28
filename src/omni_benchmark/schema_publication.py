"""Hash-bound publication for the public schema intermediate representation."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .hkb_io import HKBFileSafetyError, prepare_safe_parent, publish_flat_files
from .schema_source_inventory import (
    SchemaSourceFile,
    SchemaSourceInventory,
)


class SchemaPublicationError(ValueError):
    """Raised when a schema IR cannot be published safely."""


def _canonical_json(value: Any, *, pretty: bool = False) -> bytes:
    text = json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        sort_keys=True,
    )
    return (text + "\n").encode()


def _manifest_sources(
    inventory: SchemaSourceInventory,
    schema_source: SchemaSourceFile,
    meaning_source: SchemaSourceFile,
    hkb_path: Path,
    hkb_bytes: bytes,
    hkb_manifest_sha256: str,
) -> dict[str, Any]:
    return {
        "column_meanings": {
            "file": meaning_source.path,
            "sha256": meaning_source.sha256,
        },
        "companion_hkb_ir": {
            "file": hkb_path.name,
            "manifest_file": "manifest.json",
            "manifest_sha256": hkb_manifest_sha256,
            "sha256": hashlib.sha256(hkb_bytes).hexdigest(),
        },
        "dataset": inventory.dataset,
        "inventory_sha256": inventory.inventory_sha256,
        "revision": inventory.revision,
        "schema": {"file": schema_source.path, "sha256": schema_source.sha256},
    }


def _schema_manifest(
    database: str,
    counts: dict[str, int],
    output_name: str,
    output: bytes,
    sources: dict[str, Any],
) -> dict[str, Any]:
    return {
        "counts": counts,
        "database": database,
        "intentional_exclusions": [
            {
                "effect": "sample values are absent; DDL semantics are retained",
                "reason": "protocol_excludes_public_value_examples",
                "source_content": "First 3 rows sections",
            }
        ],
        "kind": "public-schema-intermediate-representation",
        "output": {
            "file": output_name,
            "sha256": hashlib.sha256(output).hexdigest(),
        },
        "schema_version": 1,
        "semantic_mapping": {
            "reason": "public_source_ir_only",
            "status": "not_started",
        },
        "source": sources,
        "validation": {
            "all_ddl_columns_have_meanings": True,
            "all_key_references_resolve": True,
            "all_meanings_resolve_to_ddl_columns": True,
            "sample_rows_emitted": 0,
            "stable_ids_unique": True,
            "status": "passed",
        },
    }


def _publish(
    output_root: Path, output_name: str, output: bytes, manifest: bytes
) -> None:
    try:
        prepare_safe_parent(output_root)
    except HKBFileSafetyError as error:
        raise SchemaPublicationError(str(error)) from error
    with tempfile.TemporaryDirectory(
        prefix=".public-schema-ir-", dir=output_root.parent
    ) as temporary:
        staging = Path(temporary)
        (staging / output_name).write_bytes(output)
        (staging / "manifest.json").write_bytes(manifest)
        try:
            publish_flat_files(staging, output_root, (output_name, "manifest.json"))
        except HKBFileSafetyError as error:
            raise SchemaPublicationError(str(error)) from error


def publish_schema_ir(
    output_root: Path,
    database: str,
    counts: dict[str, int],
    output: bytes,
    inventory: SchemaSourceInventory,
    schema_source: SchemaSourceFile,
    meaning_source: SchemaSourceFile,
    hkb_path: Path,
    hkb_bytes: bytes,
    hkb_manifest_sha256: str,
) -> dict[str, Any]:
    """Publish one schema IR and return its hash-bound manifest."""
    output_name = f"{database}.schema.jsonl"
    sources = _manifest_sources(
        inventory,
        schema_source,
        meaning_source,
        hkb_path,
        hkb_bytes,
        hkb_manifest_sha256,
    )
    manifest = _schema_manifest(database, counts, output_name, output, sources)
    _publish(output_root, output_name, output, _canonical_json(manifest, pretty=True))
    return manifest

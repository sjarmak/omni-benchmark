"""Validated inventory for public LiveSQLBench schema metadata."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .hkb_io import HKBFileSafetyError, read_regular_file


class SchemaSourceInventoryError(ValueError):
    """Raised when the public schema-source inventory is invalid."""


SchemaSourceKind = Literal["column_meanings", "schema"]


@dataclass(frozen=True)
class SchemaSourceFile:
    database: str
    kind: SchemaSourceKind
    path: str
    oid: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SchemaSourceInventory:
    dataset: str
    revision: str
    files: tuple[SchemaSourceFile, ...]
    inventory_sha256: str


PUBLIC_SCHEMA_DATASET = "birdsql/livesqlbench-large-v1"
_TOP_LEVEL_FIELDS = frozenset({"schema_version", "dataset", "revision", "files"})
_FILE_FIELDS = frozenset({"database", "kind", "path", "oid", "size", "sha256"})
_KINDS: tuple[SchemaSourceKind, ...] = ("column_meanings", "schema")
_MAXIMUM_INVENTORY_BYTES = 1_048_576
_SUFFIX_BY_KIND = {
    "column_meanings": "column_meaning_base.json",
    "schema": "schema.txt",
}


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SchemaSourceInventoryError(f"duplicate JSON field {key}")
        value[key] = item
    return value


def _require_exact_fields(
    value: dict[str, Any], expected: frozenset[str], label: str
) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise SchemaSourceInventoryError(
            f"{label} missing fields: {', '.join(missing)}"
        )
    if unknown:
        raise SchemaSourceInventoryError(
            f"{label} unknown fields: {', '.join(unknown)}"
        )


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SchemaSourceInventoryError(f"{label} must be a non-empty string")
    return value


def _require_hex(value: Any, length: int, label: str) -> str:
    text = _require_string(value, label)
    if len(text) != length or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise SchemaSourceInventoryError(
            f"{label} must be {length} lowercase hex characters"
        )
    return text


def _parse_kind(value: Any, label: str) -> SchemaSourceKind:
    if value not in _KINDS:
        raise SchemaSourceInventoryError(f"{label} has unsupported source kind")
    return value


def _parse_source(value: Any, index: int) -> SchemaSourceFile:
    label = f"files[{index}]"
    if not isinstance(value, dict):
        raise SchemaSourceInventoryError(f"{label} must be an object")
    _require_exact_fields(value, _FILE_FIELDS, label)
    database = _require_string(value["database"], f"{label}.database")
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
        for character in database
    ):
        raise SchemaSourceInventoryError(
            f"{label}.database must contain only lowercase letters, digits, and underscores"
        )
    kind = _parse_kind(value["kind"], f"{label}.kind")
    path = _require_string(value["path"], f"{label}.path")
    expected_path = f"{database}/{database}_{_SUFFIX_BY_KIND[kind]}"
    if path != expected_path:
        raise SchemaSourceInventoryError(
            f"{label}.path must be the canonical {kind} path {expected_path}"
        )
    size = value["size"]
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise SchemaSourceInventoryError(f"{label}.size must be a positive integer")
    return SchemaSourceFile(
        database=database,
        kind=kind,
        path=path,
        oid=_require_hex(value["oid"], 40, f"{label}.oid"),
        size=size,
        sha256=_require_hex(value["sha256"], 64, f"{label}.sha256"),
    )


def _validate_pairs(files: tuple[SchemaSourceFile, ...]) -> None:
    by_database: dict[str, set[SchemaSourceKind]] = {}
    for item in files:
        kinds = by_database.setdefault(item.database, set())
        if item.kind in kinds:
            raise SchemaSourceInventoryError(
                f"database {item.database} has duplicate source kind {item.kind}"
            )
        kinds.add(item.kind)
    expected = set(_KINDS)
    for database, kinds in sorted(by_database.items()):
        if kinds != expected:
            raise SchemaSourceInventoryError(
                f"database {database} must contain exactly one schema and one column_meanings source"
            )


def load_schema_source_inventory(path: Path | str) -> SchemaSourceInventory:
    source = Path(path)
    try:
        content = read_regular_file(
            source,
            maximum_bytes=_MAXIMUM_INVENTORY_BYTES,
        )
        value = json.loads(content, object_pairs_hook=_strict_json_object)
    except (
        HKBFileSafetyError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as error:
        raise SchemaSourceInventoryError(
            f"cannot parse schema-source inventory {source}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise SchemaSourceInventoryError(
            "schema-source inventory must be a JSON object"
        )
    _require_exact_fields(value, _TOP_LEVEL_FIELDS, "inventory")
    schema_version = value["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise SchemaSourceInventoryError(
            "inventory.schema_version must equal integer 1"
        )
    if value["dataset"] != PUBLIC_SCHEMA_DATASET:
        raise SchemaSourceInventoryError(
            f"inventory.dataset must equal {PUBLIC_SCHEMA_DATASET}"
        )
    raw_files = value["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise SchemaSourceInventoryError("inventory.files must be a non-empty list")
    files = tuple(
        sorted(
            (_parse_source(item, index) for index, item in enumerate(raw_files)),
            key=lambda item: (item.database, item.kind),
        )
    )
    _validate_pairs(files)
    return SchemaSourceInventory(
        dataset=PUBLIC_SCHEMA_DATASET,
        revision=_require_hex(value["revision"], 40, "inventory.revision"),
        files=files,
        inventory_sha256=hashlib.sha256(content).hexdigest(),
    )

"""Deterministically inspect verified public schema semantics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hkb_io import HKBFileSafetyError, read_relative_regular_file
from .schema_source_inventory import (
    SchemaSourceFile,
    SchemaSourceInventoryError,
    load_schema_source_inventory,
)
from .schema_sources import SchemaSourceError, verify_schema_source


class SchemaInspectionError(ValueError):
    """Raised when a pinned public schema source is structurally invalid."""


_MAXIMUM_STRUCTURED_DEPTH = 32


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SchemaInspectionError(f"duplicate JSON field {key}")
        value[key] = item
    return value


def _verified_bytes(source_root: Path, source: SchemaSourceFile) -> bytes:
    try:
        content = read_relative_regular_file(
            source_root,
            source.path,
            maximum_bytes=source.size + 1,
        )
        verify_schema_source(
            content,
            size=source.size,
            sha256=source.sha256,
            oid=source.oid,
            path=source.path,
        )
    except (HKBFileSafetyError, SchemaSourceError) as error:
        raise SchemaInspectionError(str(error)) from error
    return content


def _require_nonempty_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SchemaInspectionError(f"{label} must be a non-empty string")
    return value


def _tree_stats(value: Any, label: str, depth: int) -> tuple[int, int]:
    if depth > _MAXIMUM_STRUCTURED_DEPTH:
        raise SchemaInspectionError(
            f"{label} exceeds maximum supported depth {_MAXIMUM_STRUCTURED_DEPTH}"
        )
    if isinstance(value, str):
        _require_nonempty_text(value, label)
        return 1, depth
    if isinstance(value, dict):
        if not value:
            raise SchemaInspectionError(f"{label} must not be empty")
        child_stats = tuple(
            _tree_stats(
                child,
                f"{label}.{_require_nonempty_text(key, f'{label} key')}",
                depth + 1,
            )
            for key, child in value.items()
        )
    elif isinstance(value, list):
        if not value:
            raise SchemaInspectionError(f"{label} must not be empty")
        child_stats = tuple(
            _tree_stats(child, f"{label}[{index}]", depth + 1)
            for index, child in enumerate(value)
        )
    else:
        raise SchemaInspectionError(
            f"{label} must contain only objects, arrays, or string descriptions"
        )
    return sum(leaves for leaves, _ in child_stats), max(
        maximum_depth for _, maximum_depth in child_stats
    )


def _column_meaning_stats(content: bytes, database: str) -> dict[str, int]:
    try:
        value = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise SchemaInspectionError(
            f"cannot parse column meanings for {database}: {error}"
        ) from error
    if not isinstance(value, dict) or not value:
        raise SchemaInspectionError(
            f"column meanings for {database} must be a non-empty object"
        )

    structured = 0
    top_level_fields = 0
    leaf_descriptions = 0
    maximum_depth = 0
    for key, meaning in value.items():
        key_text = _require_nonempty_text(key, f"{database} column key")
        parts = key_text.split("|")
        if len(parts) != 3 or parts[0] != database or not all(parts[1:]):
            raise SchemaInspectionError(
                f"column key {key_text} must equal <database>|<table>|<column>"
            )
        if isinstance(meaning, str):
            _require_nonempty_text(meaning, key_text)
            continue
        if not isinstance(meaning, dict):
            raise SchemaInspectionError(
                f"column meaning {key_text} must be a string or structured object"
            )
        if set(meaning) != {"column_meaning", "fields_meaning"}:
            raise SchemaInspectionError(
                f"structured column meaning {key_text} has invalid fields"
            )
        _require_nonempty_text(meaning["column_meaning"], f"{key_text}.column_meaning")
        fields = meaning["fields_meaning"]
        if not isinstance(fields, dict) or not fields:
            raise SchemaInspectionError(
                f"{key_text}.fields_meaning must be a non-empty object"
            )
        stats = tuple(
            _tree_stats(
                child,
                f"{key_text}.{_require_nonempty_text(field, f'{key_text} field')}",
                1,
            )
            for field, child in fields.items()
        )
        structured += 1
        top_level_fields += len(fields)
        leaf_descriptions += sum(leaves for leaves, _ in stats)
        maximum_depth = max(
            maximum_depth,
            max(depth for _, depth in stats),
        )
    return {
        "column_meanings": len(value),
        "structured_columns": structured,
        "structured_leaf_descriptions": leaf_descriptions,
        "structured_maximum_depth": maximum_depth,
        "structured_top_level_fields": top_level_fields,
    }


def _ddl_table_count(content: bytes, database: str) -> int:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise SchemaInspectionError(f"schema for {database} is not UTF-8") from error
    index = 0
    tables = 0
    while index < len(lines):
        while index < len(lines) and not lines[index]:
            index += 1
        if index == len(lines):
            break
        if not lines[index].startswith("CREATE TABLE "):
            raise SchemaInspectionError(
                f"schema for {database} expected CREATE TABLE at line {index + 1}"
            )
        while index < len(lines) and lines[index] != ");":
            index += 1
        if index == len(lines):
            raise SchemaInspectionError(
                f"schema for {database} has an unterminated CREATE TABLE"
            )
        index += 1
        while index < len(lines) and not lines[index]:
            index += 1
        if index == len(lines) or lines[index] != "First 3 rows:":
            raise SchemaInspectionError(
                f"schema for {database} expected First 3 rows after DDL"
            )
        index += 1
        while index < len(lines) and lines[index] != "...":
            index += 1
        if index == len(lines):
            raise SchemaInspectionError(
                f"schema for {database} has an unterminated example-row section"
            )
        index += 1
        tables += 1
    return tables


def _inspect_database(
    source_root: Path,
    database: str,
    sources: tuple[SchemaSourceFile, ...],
) -> dict[str, int]:
    source_by_kind = {source.kind: source for source in sources}
    schema = _verified_bytes(source_root, source_by_kind["schema"])
    meanings = _verified_bytes(source_root, source_by_kind["column_meanings"])
    return {
        "bytes": len(schema) + len(meanings),
        "ddl_tables": _ddl_table_count(schema, database),
        **_column_meaning_stats(meanings, database),
    }


def inspect_public_schema_sources(
    inventory_path: Path | str,
    source_root: Path | str,
) -> dict[str, Any]:
    """Return reproducible structural counts from verified, row-separated inputs."""

    try:
        inventory = load_schema_source_inventory(inventory_path)
    except SchemaSourceInventoryError as error:
        raise SchemaInspectionError(str(error)) from error
    source_root_path = Path(source_root)
    databases = tuple(sorted({source.database for source in inventory.files}))
    reports = {
        database: _inspect_database(
            source_root_path,
            database,
            tuple(source for source in inventory.files if source.database == database),
        )
        for database in databases
    }
    count_fields = (
        "bytes",
        "ddl_tables",
        "column_meanings",
        "structured_columns",
        "structured_leaf_descriptions",
        "structured_top_level_fields",
    )
    additive_counts = {
        field: sum(report[field] for report in reports.values())
        for field in count_fields
    }
    counts = {
        **additive_counts,
        "databases": len(databases),
        "files": len(inventory.files),
        "structured_maximum_depth": max(
            report["structured_maximum_depth"] for report in reports.values()
        ),
    }
    return {
        "dataset": inventory.dataset,
        "revision": inventory.revision,
        "inventory_sha256": inventory.inventory_sha256,
        "counts": dict(sorted(counts.items())),
        "databases": reports,
    }

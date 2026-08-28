"""Deterministic, row-free public schema intermediate representation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from .hkb_io import (
    HKBFileSafetyError,
    read_regular_file,
    read_relative_regular_file,
)
from .schema_ddl import (
    ColumnDefinition,
    ForeignKeyDefinition,
    IdentifierDefinition,
    SchemaDDLDataError,
    TableDefinition,
    parse_public_ddl,
)
from .schema_publication import SchemaPublicationError, publish_schema_ir
from .schema_source_inventory import (
    SchemaSourceFile,
    SchemaSourceInventory,
    SchemaSourceInventoryError,
    load_schema_source_inventory,
)
from .schema_sources import SchemaSourceError, verify_schema_source


class SchemaIRDataError(ValueError):
    """Raised when public schema inputs violate the mechanical IR contract."""


_MAXIMUM_HKB_IR_BYTES = 16 * 1024 * 1024
_MAXIMUM_HKB_MANIFEST_BYTES = 1024 * 1024
_MAXIMUM_STRUCTURED_DEPTH = 32


@dataclass(frozen=True)
class ColumnMeaning:
    description: str
    fields: Mapping[str, Any] | None
    source_key: str


def _canonical_json(value: Any, *, pretty: bool = False) -> bytes:
    text = json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
        sort_keys=True,
    )
    return (text + "\n").encode()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SchemaIRDataError(f"duplicate JSON field {key}")
        value[key] = item
    return value


def _verified_bytes(root: Path, source: SchemaSourceFile) -> bytes:
    try:
        content = read_relative_regular_file(
            root,
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
        raise SchemaIRDataError(str(error)) from error
    return content


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], label: str
) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise SchemaIRDataError(f"{label} missing fields: {', '.join(missing)}")
    if unknown:
        raise SchemaIRDataError(f"{label} unknown fields: {', '.join(unknown)}")


def _read_hkb_manifest(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        manifest_bytes = read_regular_file(
            path,
            maximum_bytes=_MAXIMUM_HKB_MANIFEST_BYTES,
        )
        manifest = json.loads(manifest_bytes, object_pairs_hook=_strict_object)
    except HKBFileSafetyError as error:
        raise SchemaIRDataError(str(error)) from error
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise SchemaIRDataError("cannot parse companion HKB manifest") from error
    if not isinstance(manifest, dict):
        raise SchemaIRDataError("companion HKB manifest must be an object")
    return manifest_bytes, manifest


def _hkb_expected_sha256(
    manifest: Mapping[str, Any],
    path: Path,
    database: str,
    inventory: SchemaSourceInventory,
) -> str:
    _require_exact_fields(
        manifest,
        frozenset({"schema_version", "kind", "source", "counts", "databases"}),
        "companion HKB manifest",
    )
    if manifest["schema_version"] != 1 or isinstance(manifest["schema_version"], bool):
        raise SchemaIRDataError("companion HKB manifest schema_version must equal 1")
    if manifest["kind"] != "public-hkb-intermediate-representation":
        raise SchemaIRDataError("companion HKB manifest has an invalid kind")
    source = manifest["source"]
    if not isinstance(source, dict):
        raise SchemaIRDataError("companion HKB manifest source must be an object")
    if source.get("dataset") != inventory.dataset:
        raise SchemaIRDataError("companion HKB manifest dataset mismatch")
    if source.get("revision") != inventory.revision:
        raise SchemaIRDataError("companion HKB manifest revision mismatch")
    databases = manifest["databases"]
    if not isinstance(databases, dict) or not isinstance(databases.get(database), dict):
        raise SchemaIRDataError(
            f"companion HKB manifest has no database entry for {database}"
        )
    entry = databases[database]
    if entry.get("ir_file") != path.name:
        raise SchemaIRDataError("companion HKB IR filename mismatch")
    expected_sha256 = entry.get("ir_sha256")
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise SchemaIRDataError("companion HKB IR SHA-256 is invalid")
    return expected_sha256


def _companion_hkb(
    path: Path,
    *,
    database: str,
    inventory: SchemaSourceInventory,
) -> tuple[bytes, str]:
    manifest_bytes, manifest = _read_hkb_manifest(path.parent / "manifest.json")
    expected_sha256 = _hkb_expected_sha256(manifest, path, database, inventory)
    try:
        content = read_regular_file(path, maximum_bytes=_MAXIMUM_HKB_IR_BYTES)
    except HKBFileSafetyError as error:
        raise SchemaIRDataError(str(error)) from error
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise SchemaIRDataError("companion HKB IR SHA-256 mismatch")
    return content, hashlib.sha256(manifest_bytes).hexdigest()


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SchemaIRDataError(f"{label} must be a non-empty string")
    return value


def _validate_structured(value: Any, label: str, depth: int = 0) -> None:
    if depth > _MAXIMUM_STRUCTURED_DEPTH:
        raise SchemaIRDataError(
            f"{label} exceeds maximum supported depth {_MAXIMUM_STRUCTURED_DEPTH}"
        )
    if isinstance(value, str):
        _require_text(value, label)
        return
    if not isinstance(value, (dict, list)) or not value:
        raise SchemaIRDataError(
            f"{label} must contain only non-empty objects, arrays, or string descriptions"
        )
    values = value.items() if isinstance(value, dict) else enumerate(value)
    for key, child in values:
        if isinstance(value, dict):
            _require_text(key, f"{label} key")
        _validate_structured(child, f"{label}.{key}", depth + 1)


def _column_meanings(
    content: bytes, database: str
) -> dict[tuple[str, str], ColumnMeaning]:
    try:
        value = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise SchemaIRDataError(
            f"cannot parse column meanings for {database}: {error}"
        ) from error
    if not isinstance(value, dict) or not value:
        raise SchemaIRDataError(f"column meanings for {database} must be an object")
    meanings: dict[tuple[str, str], ColumnMeaning] = {}
    for source_key, raw in value.items():
        parts = source_key.split("|")
        if len(parts) != 3 or parts[0] != database or not all(parts[1:]):
            raise SchemaIRDataError(
                f"column key {source_key} must equal <database>|<table>|<column>"
            )
        if isinstance(raw, str):
            meaning = ColumnMeaning(_require_text(raw, source_key), None, source_key)
        else:
            if not isinstance(raw, dict) or set(raw) != {
                "column_meaning",
                "fields_meaning",
            }:
                raise SchemaIRDataError(
                    f"structured column meaning {source_key} has invalid fields"
                )
            fields = raw["fields_meaning"]
            if not isinstance(fields, dict) or not fields:
                raise SchemaIRDataError(
                    f"{source_key}.fields_meaning must be a non-empty object"
                )
            _validate_structured(fields, f"{source_key}.fields_meaning")
            meaning = ColumnMeaning(
                _require_text(raw["column_meaning"], f"{source_key}.column_meaning"),
                fields,
                source_key,
            )
        meanings[(parts[1], parts[2])] = meaning
    return meanings


def _encoded(value: str) -> str:
    return quote(value, safe="-._~")


def _identifier_record(identifier: IdentifierDefinition) -> dict[str, Any]:
    return {
        "canonical_sql": identifier.canonical_sql,
        "name": identifier.name,
        "quoted": identifier.quoted,
    }


def _table_id(database: str, table: str) -> str:
    return f"{database}:table:{_encoded(table)}"


def _column_id(database: str, table: str, column: str) -> str:
    return f"{database}:column:{_encoded(table)}:{_encoded(column)}"


def _pointer_segment(value: str | int) -> str:
    if isinstance(value, int):
        return str(value)
    return value.replace("~", "~0").replace("/", "~1")


def _json_pointer(values: Sequence[str | int]) -> str:
    return "".join(f"/{_pointer_segment(value)}" for value in values)


def _structured_leaves(
    fields: Mapping[str, Any],
) -> list[tuple[list[dict[str, Any]], tuple[str | int, ...], str]]:
    leaves: list[tuple[list[dict[str, Any]], tuple[str | int, ...], str]] = []

    def visit(
        value: Any,
        path: tuple[dict[str, Any], ...],
        raw_path: tuple[str | int, ...],
    ) -> None:
        if isinstance(value, str):
            leaves.append((list(path), raw_path, value))
            return
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for ordinal, (key, child) in enumerate(items):
            if isinstance(value, dict):
                segment = {"key": key, "kind": "object_key", "ordinal": ordinal}
            else:
                segment = {"index": key, "kind": "array_index"}
            visit(child, (*path, segment), (*raw_path, key))

    for ordinal, (key, child) in enumerate(fields.items()):
        visit(
            child,
            ({"key": key, "kind": "object_key", "ordinal": ordinal},),
            (key,),
        )
    return leaves


def _typed_path_identity(path: Sequence[dict[str, Any]]) -> str:
    tokens = [
        f"k:{_encoded(segment['key'])}"
        if segment["kind"] == "object_key"
        else f"i:{segment['index']}"
        for segment in path
    ]
    return "/".join(tokens)


def _ddl_source(
    inventory: SchemaSourceInventory,
    source: SchemaSourceFile,
    table: TableDefinition,
) -> dict[str, Any]:
    return {
        "byte_end_exclusive": table.byte_end_exclusive,
        "byte_start": table.byte_start,
        "dataset": inventory.dataset,
        "file": source.path,
        "file_sha256": source.sha256,
        "kind": "schema_ddl",
        "revision": inventory.revision,
        "statement_sha256": hashlib.sha256(table.ddl.encode()).hexdigest(),
    }


def _provenance(content: list[str], sources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "content": content,
        "intervention": "mechanical_baseline_transformation",
        "sources": sources,
        "transformation_class": "mechanical",
    }


def _schema_indexes(
    tables: Sequence[TableDefinition],
) -> tuple[dict[str, TableDefinition], dict[str, set[str]]]:
    table_index: dict[str, TableDefinition] = {}
    column_names: dict[str, set[str]] = {}
    for table in tables:
        table_name = table.identifier.name
        if table_name in table_index:
            raise SchemaIRDataError(f"duplicate DDL table {table_name}")
        table_index[table_name] = table
        names = {column.identifier.name for column in table.columns}
        if len(names) != len(table.columns):
            raise SchemaIRDataError(f"DDL table {table_name} has duplicate columns")
        column_names[table_name] = names
    return table_index, column_names


def _validate_meaning_references(
    meanings: Mapping[tuple[str, str], ColumnMeaning],
    table_index: Mapping[str, TableDefinition],
    column_names: Mapping[str, set[str]],
) -> None:
    for table_name, column_name in meanings:
        if table_name not in table_index:
            raise SchemaIRDataError(
                f"column metadata references unknown DDL table {table_name}"
            )
        if column_name not in column_names[table_name]:
            raise SchemaIRDataError(
                f"column metadata references unknown DDL column {table_name}.{column_name}"
            )


def _validate_foreign_key(
    table_name: str,
    source_names: set[str],
    foreign_key: ForeignKeyDefinition,
    column_names: Mapping[str, set[str]],
) -> None:
    unknown_sources = set(foreign_key.source_columns) - source_names
    if unknown_sources:
        source_column = sorted(unknown_sources)[0]
        raise SchemaIRDataError(
            f"FOREIGN KEY references unknown source column {table_name}.{source_column}"
        )
    target_names = column_names.get(foreign_key.target_table)
    if target_names is None:
        raise SchemaIRDataError(
            f"FOREIGN KEY references unknown table {foreign_key.target_table}"
        )
    unknown_targets = set(foreign_key.target_columns) - target_names
    if unknown_targets:
        target_column = sorted(unknown_targets)[0]
        raise SchemaIRDataError(
            "FOREIGN KEY references unknown target column "
            f"{foreign_key.target_table}.{target_column}"
        )
    if len(foreign_key.source_columns) != len(foreign_key.target_columns):
        raise SchemaIRDataError("FOREIGN KEY column counts do not match")


def _validate_table_constraints(
    meanings: Mapping[tuple[str, str], ColumnMeaning],
    table_index: Mapping[str, TableDefinition],
    column_names: Mapping[str, set[str]],
) -> None:
    for table_name, names in column_names.items():
        missing = sorted(name for name in names if (table_name, name) not in meanings)
        if missing:
            raise SchemaIRDataError(
                f"DDL table {table_name} is missing column meanings: {', '.join(missing)}"
            )
        table = table_index[table_name]
        for key_name in (
            *table.primary_key,
            *(key for keys in table.unique_keys for key in keys),
        ):
            if key_name not in names:
                raise SchemaIRDataError(
                    f"key constraint references unknown column {table_name}.{key_name}"
                )
        for foreign_key in table.foreign_keys:
            _validate_foreign_key(table_name, names, foreign_key, column_names)


def _validate_schema(
    tables: Sequence[TableDefinition], meanings: Mapping[tuple[str, str], ColumnMeaning]
) -> None:
    table_index, column_names = _schema_indexes(tables)
    _validate_meaning_references(meanings, table_index, column_names)
    _validate_table_constraints(meanings, table_index, column_names)


def _foreign_key_record(
    database: str,
    table: TableDefinition,
    foreign_key: ForeignKeyDefinition,
    ddl_source: dict[str, Any],
) -> dict[str, Any]:
    table_name = table.identifier.name
    identity = {
        "source_columns": list(foreign_key.source_columns),
        "source_table": table_name,
        "target_columns": list(foreign_key.target_columns),
        "target_table": foreign_key.target_table,
    }
    digest = hashlib.sha256(_canonical_json(identity).rstrip(b"\n")).hexdigest()
    return {
        "database": database,
        "provenance": _provenance(["public_schema"], [ddl_source]),
        "record_kind": "foreign_key",
        "schema_version": 1,
        "source_column_stable_ids": [
            _column_id(database, table_name, name)
            for name in foreign_key.source_columns
        ],
        "source_ordinal": foreign_key.source_ordinal,
        "source_table_stable_id": _table_id(database, table_name),
        "stable_id": f"{database}:foreign-key:sha256:{digest}",
        "target_column_stable_ids": [
            _column_id(database, foreign_key.target_table, name)
            for name in foreign_key.target_columns
        ],
        "target_table_stable_id": _table_id(database, foreign_key.target_table),
    }


def _table_record(
    database: str,
    table: TableDefinition,
    ddl_source: dict[str, Any],
) -> dict[str, Any]:
    table_name = table.identifier.name
    return {
        "database": database,
        "identifier": _identifier_record(table.identifier),
        "primary_key_column_stable_ids": [
            _column_id(database, table_name, name) for name in table.primary_key
        ],
        "provenance": _provenance(["public_schema"], [ddl_source]),
        "record_kind": "table",
        "schema_version": 1,
        "source_ordinal": table.source_ordinal,
        "stable_id": _table_id(database, table_name),
        "unique_keys": [
            [_column_id(database, table_name, name) for name in key]
            for key in table.unique_keys
        ],
    }


def _meaning_provenance(
    meaning: ColumnMeaning,
    meaning_source: SchemaSourceFile,
) -> tuple[str, dict[str, Any]]:
    pointer = "/" + _pointer_segment(meaning.source_key)
    return pointer, {
        "file": meaning_source.path,
        "file_sha256": meaning_source.sha256,
        "json_pointer": pointer + "/column_meaning",
        "kind": "column_meaning",
        "source_key": meaning.source_key,
    }


def _structured_leaf_record(
    database: str,
    column_stable_id: str,
    meaning: ColumnMeaning,
    meaning_source: SchemaSourceFile,
    meaning_pointer: str,
    leaf: tuple[list[dict[str, Any]], list[str | int], str],
    stable_id: str,
    ordinal: int,
) -> dict[str, Any]:
    path, raw_path, description = leaf
    pointer = _json_pointer(raw_path)
    source = {
        "file": meaning_source.path,
        "file_sha256": meaning_source.sha256,
        "json_pointer": meaning_pointer + "/fields_meaning" + pointer,
        "kind": "structured_column_meaning",
        "source_key": meaning.source_key,
    }
    return {
        "column_stable_id": column_stable_id,
        "data_json_pointer": pointer,
        "database": database,
        "depth_first_ordinal": ordinal,
        "description": description,
        "path": path,
        "provenance": _provenance(["public_column_metadata"], [source]),
        "record_kind": "structured_leaf",
        "schema_version": 1,
        "stable_id": stable_id,
    }


def _column_record(
    database: str,
    table: TableDefinition,
    column: ColumnDefinition,
    meaning: ColumnMeaning,
    ddl_source: dict[str, Any],
    meaning_source: dict[str, Any],
    leaf_ids: list[str],
) -> dict[str, Any]:
    table_name = table.identifier.name
    column_name = column.identifier.name
    return {
        "database": database,
        "declared_type_sql": column.declared_type_sql,
        "default_expression_sql": column.default_expression_sql,
        "description": meaning.description,
        "identifier": _identifier_record(column.identifier),
        "nullable": column.nullable and column_name not in table.primary_key,
        "provenance": _provenance(
            ["public_schema", "public_column_metadata"],
            [ddl_source, meaning_source],
        ),
        "record_kind": "column",
        "schema_version": 1,
        "source_ordinal": column.source_ordinal,
        "stable_id": _column_id(database, table_name, column_name),
        "structured_leaf_stable_ids": leaf_ids,
        "table_stable_id": _table_id(database, table_name),
    }


def _compile_column_records(
    database: str,
    table: TableDefinition,
    column: ColumnDefinition,
    meaning: ColumnMeaning,
    ddl_source: dict[str, Any],
    meaning_source: SchemaSourceFile,
) -> list[dict[str, Any]]:
    leaves = [] if meaning.fields is None else _structured_leaves(meaning.fields)
    if leaves and column.declared_type_sql.upper() not in {"JSON", "JSONB"}:
        raise SchemaIRDataError(
            f"structured meaning {meaning.source_key} requires a JSON/JSONB column"
        )
    table_name = table.identifier.name
    column_name = column.identifier.name
    column_stable_id = _column_id(database, table_name, column_name)
    leaf_ids = [
        f"{database}:structured-leaf:{_encoded(table_name)}:"
        f"{_encoded(column_name)}:{_typed_path_identity(path)}"
        for path, _, _ in leaves
    ]
    meaning_pointer, source = _meaning_provenance(meaning, meaning_source)
    records = [
        _column_record(database, table, column, meaning, ddl_source, source, leaf_ids)
    ]
    records.extend(
        _structured_leaf_record(
            database,
            column_stable_id,
            meaning,
            meaning_source,
            meaning_pointer,
            leaf,
            stable_id,
            ordinal,
        )
        for ordinal, (leaf, stable_id) in enumerate(zip(leaves, leaf_ids, strict=True))
    )
    return records


def _record_counts(
    records: Sequence[dict[str, Any]], tables: Sequence[TableDefinition]
) -> dict[str, int]:
    kinds = [record["record_kind"] for record in records]
    return {
        "columns": kinds.count("column"),
        "foreign_keys": kinds.count("foreign_key"),
        "primary_keys": sum(bool(table.primary_key) for table in tables),
        "structured_columns": sum(
            bool(record["structured_leaf_stable_ids"])
            for record in records
            if record["record_kind"] == "column"
        ),
        "structured_leaves": kinds.count("structured_leaf"),
        "tables": kinds.count("table"),
    }


def _compile_records(
    database: str,
    tables: Sequence[TableDefinition],
    meanings: Mapping[tuple[str, str], ColumnMeaning],
    inventory: SchemaSourceInventory,
    schema_source: SchemaSourceFile,
    meaning_source: SchemaSourceFile,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    for table in tables:
        table_name = table.identifier.name
        ddl_source = _ddl_source(inventory, schema_source, table)
        records.append(_table_record(database, table, ddl_source))
        for column in table.columns:
            records.extend(
                _compile_column_records(
                    database,
                    table,
                    column,
                    meanings[(table_name, column.identifier.name)],
                    ddl_source,
                    meaning_source,
                )
            )
        records.extend(
            _foreign_key_record(database, table, foreign_key, ddl_source)
            for foreign_key in table.foreign_keys
        )
    stable_ids = [record["stable_id"] for record in records]
    if len(stable_ids) != len(set(stable_ids)):
        raise SchemaIRDataError("schema IR contains duplicate stable IDs")
    return records, _record_counts(records, tables)


def _load_database_sources(
    source_root: Path,
    inventory_path: Path | str,
    database: str,
) -> tuple[
    SchemaSourceInventory,
    SchemaSourceFile,
    SchemaSourceFile,
    bytes,
    bytes,
]:
    try:
        inventory = load_schema_source_inventory(inventory_path)
    except SchemaSourceInventoryError as error:
        raise SchemaIRDataError(str(error)) from error
    sources = tuple(item for item in inventory.files if item.database == database)
    if not sources:
        raise SchemaIRDataError(
            f"database {database} is not present in schema inventory"
        )
    source_by_kind = {item.kind: item for item in sources}
    schema_source = source_by_kind["schema"]
    meaning_source = source_by_kind["column_meanings"]
    return (
        inventory,
        schema_source,
        meaning_source,
        _verified_bytes(source_root, schema_source),
        _verified_bytes(source_root, meaning_source),
    )


def _publish_result(
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
    try:
        return publish_schema_ir(
            output_root,
            database,
            counts,
            output,
            inventory,
            schema_source,
            meaning_source,
            hkb_path,
            hkb_bytes,
            hkb_manifest_sha256,
        )
    except SchemaPublicationError as error:
        raise SchemaIRDataError(str(error)) from error


def generate_public_schema_ir(
    source_root: Path | str,
    inventory_path: Path | str,
    output_root: Path | str,
    *,
    database: str,
    companion_hkb_ir: Path | str,
) -> dict[str, Any]:
    """Generate one hash-bound public schema IR without reading example rows."""
    inventory, schema_source, meaning_source, schema_bytes, meaning_bytes = (
        _load_database_sources(Path(source_root), inventory_path, database)
    )
    hkb_path = Path(companion_hkb_ir)
    if hkb_path.name != f"{database}.hkb.jsonl":
        raise SchemaIRDataError(f"companion HKB IR must be named {database}.hkb.jsonl")
    hkb_bytes, hkb_manifest_sha256 = _companion_hkb(
        hkb_path,
        database=database,
        inventory=inventory,
    )
    try:
        tables = parse_public_ddl(schema_bytes, database)
    except SchemaDDLDataError as error:
        raise SchemaIRDataError(str(error)) from error
    meanings = _column_meanings(meaning_bytes, database)
    _validate_schema(tables, meanings)
    records, counts = _compile_records(
        database,
        tables,
        meanings,
        inventory,
        schema_source,
        meaning_source,
    )
    output = b"".join(_canonical_json(record) for record in records)
    return _publish_result(
        Path(output_root),
        database,
        counts,
        output,
        inventory,
        schema_source,
        meaning_source,
        hkb_path,
        hkb_bytes,
        hkb_manifest_sha256,
    )

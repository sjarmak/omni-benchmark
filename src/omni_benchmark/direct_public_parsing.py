"""Pure parsers and bounded payload validation for direct public contexts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from .content_policy import ContentPolicy
from .direct_sql_result import DirectResultError, validate_json_value
from .omni_result_adapter import OmniResultContractError, reject_forbidden_keys


class DirectPublicContextError(RuntimeError):
    """Raised before a direct comparator can observe an invalid public context."""


def schema_payload(
    database: str,
    records: tuple[dict[str, Any], ...],
    artifact_sha256: str,
    manifest_sha256: str,
    maximum_bytes: int,
    policy: ContentPolicy,
) -> dict[str, Any]:
    """Compile public schema IR into deterministic compact table context."""
    tables, columns, leaves, foreign_keys = _partition_schema_records(database, records)
    _attach_columns(tables, columns, leaves)
    _attach_foreign_keys(tables, foreign_keys)
    payload = {
        "database": database,
        "kind": "public-schema-context",
        "source": {
            "artifact_sha256": artifact_sha256,
            "manifest_sha256": manifest_sha256,
        },
        "tables": _ordered_tables(tables),
        "truncated": False,
    }
    validate_payload(payload, maximum_bytes, policy)
    return payload


def _partition_schema_records(
    database: str, records: tuple[dict[str, Any], ...]
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    tables: dict[str, dict[str, Any]] = {}
    columns: dict[str, dict[str, Any]] = {}
    leaves: dict[str, list[dict[str, Any]]] = {}
    foreign_keys: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("database") != database:
            raise DirectPublicContextError("schema IR database does not match")
        kind = record.get("record_kind")
        if kind == "table":
            table = _schema_table(record)
            if table["stable_id"] in tables:
                raise DirectPublicContextError("schema table IDs must be unique")
            tables[table["stable_id"]] = table
        elif kind == "column":
            column = _schema_column(record)
            if column["stable_id"] in columns:
                raise DirectPublicContextError("schema column IDs must be unique")
            columns[column["stable_id"]] = column
        elif kind == "structured_leaf":
            leaves.setdefault(required_text(record, "column_stable_id"), []).append(
                _schema_leaf(record)
            )
        elif kind == "foreign_key":
            foreign_keys.setdefault(
                required_text(record, "source_table_stable_id"), []
            ).append(_schema_foreign_key(record))
        else:
            raise DirectPublicContextError("schema IR record kind is unsupported")
    return tables, columns, leaves, foreign_keys


def _attach_columns(
    tables: dict[str, dict[str, Any]],
    columns: dict[str, dict[str, Any]],
    leaves: dict[str, list[dict[str, Any]]],
) -> None:
    for column_id, column in columns.items():
        column["structured_leaves"] = sorted(
            leaves.pop(column_id, []), key=lambda item: item["_source_ordinal"]
        )
        for leaf in column["structured_leaves"]:
            leaf.pop("_source_ordinal")
        table_id = column.pop("_table_stable_id")
        if table_id not in tables:
            raise DirectPublicContextError("schema column references a missing table")
        tables[table_id]["columns"].append(column)
    if leaves:
        raise DirectPublicContextError("structured leaf references a missing column")


def _attach_foreign_keys(
    tables: dict[str, dict[str, Any]],
    foreign_keys: dict[str, list[dict[str, Any]]],
) -> None:
    for table_id, values in foreign_keys.items():
        if table_id not in tables:
            raise DirectPublicContextError("foreign key references a missing table")
        tables[table_id]["foreign_keys"] = sorted(
            values, key=lambda item: item["_source_ordinal"]
        )
        for foreign_key in tables[table_id]["foreign_keys"]:
            foreign_key.pop("_source_ordinal")


def _ordered_tables(tables: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = sorted(tables.values(), key=lambda item: item["_source_ordinal"])
    for table in materialized:
        table["columns"] = sorted(
            table["columns"], key=lambda item: item["_source_ordinal"]
        )
        for column in table["columns"]:
            column.pop("_source_ordinal")
        table.pop("_source_ordinal")
    return materialized


def _schema_table(record: Mapping[str, Any]) -> dict[str, Any]:
    identifier = _identifier(record)
    unique_keys = record.get("unique_keys")
    if not isinstance(unique_keys, list):
        raise DirectPublicContextError("unique keys must be a list")
    return {
        "_source_ordinal": required_nonnegative_int(record, "source_ordinal"),
        "canonical_sql": required_text(identifier, "canonical_sql"),
        "columns": [],
        "foreign_keys": [],
        "name": required_text(identifier, "name"),
        "primary_key_column_stable_ids": text_list(
            record.get("primary_key_column_stable_ids"), "primary keys"
        ),
        "quoted": required_bool(identifier, "quoted"),
        "stable_id": required_text(record, "stable_id"),
        "unique_keys": list(unique_keys),
    }


def _schema_column(record: Mapping[str, Any]) -> dict[str, Any]:
    identifier = _identifier(record)
    return {
        "_source_ordinal": required_nonnegative_int(record, "source_ordinal"),
        "_table_stable_id": required_text(record, "table_stable_id"),
        "canonical_sql": required_text(identifier, "canonical_sql"),
        "declared_type_sql": required_text(record, "declared_type_sql"),
        "description": required_text(record, "description"),
        "name": required_text(identifier, "name"),
        "nullable": required_bool(record, "nullable"),
        "quoted": required_bool(identifier, "quoted"),
        "stable_id": required_text(record, "stable_id"),
    }


def _schema_leaf(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "_source_ordinal": required_nonnegative_int(record, "depth_first_ordinal"),
        "data_json_pointer": required_text(record, "data_json_pointer"),
        "description": required_text(record, "description"),
        "stable_id": required_text(record, "stable_id"),
    }


def _schema_foreign_key(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "_source_ordinal": required_nonnegative_int(record, "source_ordinal"),
        "source_column_stable_ids": text_list(
            record.get("source_column_stable_ids"), "foreign-key source columns"
        ),
        "stable_id": required_text(record, "stable_id"),
        "target_column_stable_ids": text_list(
            record.get("target_column_stable_ids"), "foreign-key target columns"
        ),
        "target_table_stable_id": required_text(record, "target_table_stable_id"),
    }


def _identifier(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("identifier")
    if not isinstance(value, dict):
        raise DirectPublicContextError("schema identifier is invalid")
    return value


def semantic_file_items(file_name: str, content: bytes) -> list[dict[str, Any]]:
    """Parse searchable objects only from an actual Omni view or topic file."""
    try:
        value = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError) as error:
        raise DirectPublicContextError(
            "semantic bundle file is invalid YAML"
        ) from error
    if not isinstance(value, dict):
        raise DirectPublicContextError("semantic bundle file must be an object")
    if file_name.endswith(".view"):
        return _view_items(file_name, value)
    return [_topic_item(file_name, value)]


def _view_items(file_name: str, value: Mapping[str, Any]) -> list[dict[str, Any]]:
    view_id = (
        f"{required_text(value, 'catalog')}_{required_text(value, 'schema')}__"
        f"{required_text(value, 'table_name')}"
    )
    items = [
        {
            "description": required_text(value, "description"),
            "label": required_text(value, "label"),
            "object_id": view_id,
            "object_kind": "view",
            "source_file": file_name,
        }
    ]
    dimensions = value.get("dimensions")
    if not isinstance(dimensions, dict) or not dimensions:
        raise DirectPublicContextError("semantic view dimensions are invalid")
    for name, dimension in dimensions.items():
        if not isinstance(name, str) or not name or not isinstance(dimension, dict):
            raise DirectPublicContextError("semantic dimension is invalid")
        item = {
            "description": required_text(dimension, "description"),
            "label": required_text(dimension, "label"),
            "object_id": f"{view_id}.{name}",
            "object_kind": "dimension",
            "source_file": file_name,
        }
        for field in ("sql", "ai_context"):
            if field in dimension:
                item[field] = required_text(dimension, field)
        items.append(item)
    return items


def _topic_item(file_name: str, value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ai_context": required_text(value, "ai_context"),
        "base_view": required_text(value, "base_view"),
        "description": required_text(value, "description"),
        "fields": text_list(value.get("fields"), "semantic topic fields"),
        "label": required_text(value, "label"),
        "object_id": f"topic:{Path(file_name).stem}",
        "object_kind": "topic",
        "source_file": file_name,
    }


def validate_payload(
    payload: Mapping[str, Any], maximum_bytes: int, policy: ContentPolicy
) -> None:
    """Require a finite, secret-free JSON payload below a byte ceiling."""
    try:
        reject_forbidden_keys(payload)
        validate_json_value(payload)
    except OmniResultContractError as error:
        raise DirectPublicContextError(
            "public context contains a forbidden field"
        ) from error
    except DirectResultError as error:
        raise DirectPublicContextError("public context is not finite JSON") from error
    if policy.sanitize_json(dict(payload)) != dict(payload):
        raise DirectPublicContextError("public context contains sensitive content")
    if len(canonical(payload)) > maximum_bytes:
        raise DirectPublicContextError("public context exceeds its size bound")


def canonical(value: object) -> bytes:
    """Encode finite canonical JSON for deterministic bounds and identities."""
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
    except (TypeError, ValueError) as error:
        raise DirectPublicContextError("public context must be finite JSON") from error


def required_text(value: Mapping[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise DirectPublicContextError(f"{field} must be a non-empty string")
    return item


def required_bool(value: Mapping[str, Any], field: str) -> bool:
    item = value.get(field)
    if type(item) is not bool:
        raise DirectPublicContextError(f"{field} must be a boolean")
    return item


def required_nonnegative_int(value: Mapping[str, Any], field: str) -> int:
    item = value.get(field)
    if type(item) is not int or item < 0:
        raise DirectPublicContextError(f"{field} must be a non-negative integer")
    return item


def text_list(value: object, description: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise DirectPublicContextError(f"{description} must be a list of strings")
    return list(value)

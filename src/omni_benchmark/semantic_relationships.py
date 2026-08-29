"""Conservative public-schema relationship contracts for E02."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from omni_benchmark.semantic_bundle import SemanticBundleError, reject_protected_fields


class SemanticRelationshipError(ValueError):
    """Raised when public schema records cannot form a safe relationship plan."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticRelationshipError(f"{label} must be non-empty text")
    return value


def _text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise SemanticRelationshipError(f"{label} must be an array of strings")
    if len(value) != len(set(value)):
        raise SemanticRelationshipError(f"{label} must contain unique values")
    return list(value)


def _index(
    records: Sequence[Mapping[str, Any]], record_kind: str
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        if record.get("record_kind") != record_kind:
            continue
        stable_id = _text(record.get("stable_id"), f"{record_kind} stable_id")
        if stable_id in indexed:
            raise SemanticRelationshipError(f"duplicate {record_kind} {stable_id}")
        indexed[stable_id] = record
    return indexed


def _keys(table: Mapping[str, Any]) -> list[list[str]]:
    primary = _text_list(table.get("primary_key_column_stable_ids"), "primary key")
    raw_unique = table.get("unique_keys")
    if not isinstance(raw_unique, list):
        raise SemanticRelationshipError("unique_keys must be an array")
    unique = [_text_list(item, "unique key") for item in raw_unique]
    return ([primary] if primary else []) + unique


def _source_grain(table: Mapping[str, Any]) -> list[str] | None:
    keys = _keys(table)
    if not keys:
        return None
    primary = _text_list(table.get("primary_key_column_stable_ids"), "primary key")
    if primary:
        return primary
    return min(keys, key=lambda key: (len(key), tuple(key)))


def _target_grain(
    table: Mapping[str, Any], target_columns: list[str]
) -> list[str] | None:
    matches = [
        key
        for key in _keys(table)
        if len(key) == len(target_columns) and set(key) == set(target_columns)
    ]
    if not matches:
        return None
    exact = [key for key in matches if key == target_columns]
    return min(exact or matches, key=lambda key: tuple(key))


def _database(records: Sequence[Mapping[str, Any]]) -> str:
    databases = {_text(record.get("database"), "record database") for record in records}
    if len(databases) != 1:
        raise SemanticRelationshipError("schema records must have one database")
    return next(iter(databases))


def plan_relationship_contracts(
    schema_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Plan only PK/unique-backed many-to-one relationships from public schema."""
    if not isinstance(schema_records, Sequence) or isinstance(
        schema_records, (str, bytes)
    ):
        raise SemanticRelationshipError("schema records must be a sequence")
    records = list(schema_records)
    if not records or any(not isinstance(record, Mapping) for record in records):
        raise SemanticRelationshipError("schema records must be non-empty objects")
    try:
        reject_protected_fields(records)
    except SemanticBundleError as error:
        raise SemanticRelationshipError(str(error)) from error
    for record in records:
        if record.get("schema_version") != 1:
            raise SemanticRelationshipError("schema_version must equal 1")

    database = _database(records)
    tables = _index(records, "table")
    columns = _index(records, "column")
    foreign_keys = _index(records, "foreign_key")
    relationships: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []

    for foreign_key_id, foreign_key in sorted(foreign_keys.items()):
        provenance = foreign_key.get("provenance")
        if not isinstance(provenance, Mapping) or provenance.get("content") != [
            "public_schema"
        ]:
            raise SemanticRelationshipError(
                f"foreign key {foreign_key_id} provenance must be public-schema-only"
            )
        source_table_id = _text(
            foreign_key.get("source_table_stable_id"), "source table"
        )
        target_table_id = _text(
            foreign_key.get("target_table_stable_id"), "target table"
        )
        source_columns = _text_list(
            foreign_key.get("source_column_stable_ids"), "source columns"
        )
        target_columns = _text_list(
            foreign_key.get("target_column_stable_ids"), "target columns"
        )
        if not source_columns or len(source_columns) != len(target_columns):
            raise SemanticRelationshipError(
                f"foreign key {foreign_key_id} has mismatched columns"
            )

        reasons: list[str] = []
        source_table = tables.get(source_table_id)
        target_table = tables.get(target_table_id)
        if source_table is None:
            reasons.append("source_table_unresolved")
        if target_table is None:
            reasons.append("target_table_unresolved")
        missing_source_columns = [
            item for item in source_columns if item not in columns
        ]
        missing_target_columns = [
            item for item in target_columns if item not in columns
        ]
        if missing_source_columns:
            reasons.append("source_column_unresolved")
        if missing_target_columns:
            reasons.append("target_column_unresolved")
        if any(
            columns[item].get("table_stable_id") != source_table_id
            for item in source_columns
            if item in columns
        ):
            reasons.append("source_column_wrong_table")
        if any(
            columns[item].get("table_stable_id") != target_table_id
            for item in target_columns
            if item in columns
        ):
            reasons.append("target_column_wrong_table")

        source_grain = None if source_table is None else _source_grain(source_table)
        target_grain = (
            None
            if target_table is None
            else _target_grain(target_table, target_columns)
        )
        if source_table is not None and source_grain is None:
            reasons.append("source_grain_unknown")
        if target_table is not None and target_grain is None:
            reasons.append("target_not_unique")
        if source_grain is not None and any(
            item not in columns
            or columns[item].get("table_stable_id") != source_table_id
            for item in source_grain
        ):
            reasons.append("source_grain_unresolved")
        if target_grain is not None and any(
            item not in columns
            or columns[item].get("table_stable_id") != target_table_id
            for item in target_grain
        ):
            reasons.append("target_grain_unresolved")
        if reasons:
            deferred.append(
                {
                    "foreign_key_stable_id": foreign_key_id,
                    "reasons": sorted(set(reasons)),
                }
            )
            continue

        nullable_values = [columns[item].get("nullable") for item in source_columns]
        if any(not isinstance(value, bool) for value in nullable_values):
            raise SemanticRelationshipError(
                f"foreign key {foreign_key_id} source nullable flags must be booleans"
            )
        source_optional = any(nullable_values)
        relationships.append(
            {
                "cardinality": "many_to_one",
                "foreign_key_stable_id": foreign_key_id,
                "provenance": provenance,
                "source_column_stable_ids": source_columns,
                "source_grain_column_stable_ids": source_grain,
                "source_match": "zero_or_one" if source_optional else "exactly_one",
                "source_table_stable_id": source_table_id,
                "target_column_stable_ids": target_columns,
                "target_grain_column_stable_ids": target_grain,
                "target_table_stable_id": target_table_id,
            }
        )

    return {
        "database": database,
        "deferred": deferred,
        "relationships": relationships,
        "schema_version": 1,
    }

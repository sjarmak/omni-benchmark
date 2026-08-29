from __future__ import annotations

import pytest

from omni_benchmark.semantic_relationships import (
    SemanticRelationshipError,
    plan_relationship_contracts,
)


DB = "example_large"


def _table(name: str, *, primary: tuple[str, ...] = (), unique=()):
    return {
        "database": DB,
        "primary_key_column_stable_ids": [
            f"{DB}:column:{name}:{item}" for item in primary
        ],
        "record_kind": "table",
        "schema_version": 1,
        "stable_id": f"{DB}:table:{name}",
        "unique_keys": [
            [f"{DB}:column:{name}:{item}" for item in key] for key in unique
        ],
    }


def _column(table: str, name: str, *, nullable: bool = False):
    return {
        "database": DB,
        "nullable": nullable,
        "record_kind": "column",
        "schema_version": 1,
        "stable_id": f"{DB}:column:{table}:{name}",
        "table_stable_id": f"{DB}:table:{table}",
    }


def _foreign_key(
    source: str,
    source_columns: tuple[str, ...],
    target: str,
    target_columns: tuple[str, ...],
    *,
    suffix: str = "one",
):
    return {
        "database": DB,
        "provenance": {"content": ["public_schema"]},
        "record_kind": "foreign_key",
        "schema_version": 1,
        "source_column_stable_ids": [
            f"{DB}:column:{source}:{item}" for item in source_columns
        ],
        "source_table_stable_id": f"{DB}:table:{source}",
        "stable_id": f"{DB}:foreign-key:{suffix}",
        "target_column_stable_ids": [
            f"{DB}:column:{target}:{item}" for item in target_columns
        ],
        "target_table_stable_id": f"{DB}:table:{target}",
    }


def test_primary_key_target_produces_explicit_many_to_one_contract() -> None:
    records = [
        _table("orders", primary=("order_id",)),
        _column("orders", "order_id"),
        _column("orders", "customer_id", nullable=True),
        _table("customers", primary=("customer_id",)),
        _column("customers", "customer_id"),
        _foreign_key("orders", ("customer_id",), "customers", ("customer_id",)),
    ]

    result = plan_relationship_contracts(records)

    assert result["database"] == DB
    assert result["deferred"] == []
    assert result["relationships"] == [
        {
            "cardinality": "many_to_one",
            "foreign_key_stable_id": f"{DB}:foreign-key:one",
            "provenance": {"content": ["public_schema"]},
            "source_column_stable_ids": [f"{DB}:column:orders:customer_id"],
            "source_grain_column_stable_ids": [f"{DB}:column:orders:order_id"],
            "source_match": "zero_or_one",
            "source_table_stable_id": f"{DB}:table:orders",
            "target_column_stable_ids": [f"{DB}:column:customers:customer_id"],
            "target_grain_column_stable_ids": [f"{DB}:column:customers:customer_id"],
            "target_table_stable_id": f"{DB}:table:customers",
        }
    ]


def test_unique_target_and_unique_source_grain_are_accepted_deterministically() -> None:
    records = [
        _foreign_key(
            "events", ("tenant", "actor"), "actors", ("tenant", "actor"), suffix="b"
        ),
        _table("actors", unique=(("actor", "tenant"),)),
        _column("actors", "tenant"),
        _column("actors", "actor"),
        _table("events", unique=(("event_id",), ("tenant", "event_id"))),
        _column("events", "event_id"),
        _column("events", "tenant"),
        _column("events", "actor"),
    ]

    first = plan_relationship_contracts(records)
    second = plan_relationship_contracts(list(reversed(records)))

    assert first == second
    relationship = first["relationships"][0]
    assert relationship["source_grain_column_stable_ids"] == [
        f"{DB}:column:events:event_id"
    ]
    assert relationship["target_grain_column_stable_ids"] == [
        f"{DB}:column:actors:actor",
        f"{DB}:column:actors:tenant",
    ]
    assert relationship["source_match"] == "exactly_one"


def test_ambiguous_edges_are_deferred_with_explicit_reasons() -> None:
    records = [
        _table("no_grain"),
        _column("no_grain", "target_id"),
        _table("target", primary=("id",)),
        _column("target", "id"),
        _foreign_key("no_grain", ("target_id",), "target", ("id",), suffix="a"),
        _table("source", primary=("id",)),
        _column("source", "id"),
        _column("source", "code"),
        _table("non_unique", primary=("id",)),
        _column("non_unique", "id"),
        _column("non_unique", "code"),
        _foreign_key("source", ("code",), "non_unique", ("code",), suffix="b"),
    ]

    result = plan_relationship_contracts(records)

    assert result["relationships"] == []
    assert result["deferred"] == [
        {
            "foreign_key_stable_id": f"{DB}:foreign-key:a",
            "reasons": ["source_grain_unknown"],
        },
        {
            "foreign_key_stable_id": f"{DB}:foreign-key:b",
            "reasons": ["target_not_unique"],
        },
    ]


def test_protected_fields_are_rejected_recursively() -> None:
    records = [_table("source", primary=("id",))]
    records[0]["provenance"] = {"nested": {"gold_sql": "do not inspect"}}

    with pytest.raises(SemanticRelationshipError, match="protected field"):
        plan_relationship_contracts(records)


def test_claimed_grains_and_join_columns_must_resolve_to_their_tables() -> None:
    records = [
        _table("source", primary=("missing",)),
        _column("source", "target_id"),
        _table("target", primary=("id",)),
        _column("target", "id"),
        _column("other", "wrong"),
        _foreign_key("source", ("target_id",), "target", ("id",), suffix="a"),
        _foreign_key("source", ("wrong",), "target", ("id",), suffix="b"),
    ]
    records[-1]["source_column_stable_ids"] = [f"{DB}:column:other:wrong"]

    result = plan_relationship_contracts(records)

    assert result["relationships"] == []
    assert result["deferred"] == [
        {
            "foreign_key_stable_id": f"{DB}:foreign-key:a",
            "reasons": ["source_grain_unresolved"],
        },
        {
            "foreign_key_stable_id": f"{DB}:foreign-key:b",
            "reasons": ["source_column_wrong_table", "source_grain_unresolved"],
        },
    ]


def test_foreign_key_provenance_must_be_public_schema_only() -> None:
    records = [
        _table("source", primary=("id",)),
        _column("source", "id"),
        _column("source", "target_id"),
        _table("target", primary=("id",)),
        _column("target", "id"),
        _foreign_key("source", ("target_id",), "target", ("id",)),
    ]
    records[-1]["provenance"] = {"content": ["public_schema", "other"]}

    with pytest.raises(SemanticRelationshipError, match="public-schema-only"):
        plan_relationship_contracts(records)

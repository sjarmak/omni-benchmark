from __future__ import annotations

import pytest

from omni_benchmark.content_policy import ContentPolicy
from omni_benchmark.direct_public_parsing import DirectPublicContextError, canonical
from omni_benchmark.direct_public_search import (
    MAX_SCHEMA_MATCHES,
    MAX_SCHEMA_PAYLOAD_BYTES,
    search_schema,
)


def _schema(tables: list[dict[str, object]]) -> bytes:
    return canonical(
        {
            "database": "public_database",
            "kind": "public-schema-context",
            "source": {
                "artifact_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
            },
            "tables": tables,
            "truncated": False,
        }
    )


def _table(
    index: int, *, description: str = "shared public value"
) -> dict[str, object]:
    table_id = f"public_database:table:table_{index}"
    return {
        "canonical_sql": f"table_{index}",
        "columns": [
            {
                "canonical_sql": "value",
                "declared_type_sql": "TEXT",
                "description": description,
                "name": "value",
                "nullable": False,
                "quoted": False,
                "stable_id": f"public_database:column:table_{index}:value",
                "structured_leaves": [],
            }
        ],
        "foreign_keys": [],
        "name": f"table_{index}",
        "primary_key_column_stable_ids": [],
        "quoted": False,
        "stable_id": table_id,
        "unique_keys": [],
    }


def test_schema_search_caps_matches_and_marks_truncation() -> None:
    result = search_schema(
        _schema([_table(index) for index in range(MAX_SCHEMA_MATCHES + 2)]),
        ContentPolicy.from_environment({}),
        "c" * 64,
        "shared value",
    )

    assert len(result.payload["tables"]) == MAX_SCHEMA_MATCHES
    assert result.payload["truncated"] is True
    assert len(canonical(result.payload)) <= MAX_SCHEMA_PAYLOAD_BYTES


def test_schema_search_bounds_repeated_context_growth() -> None:
    """Five exploratory searches cannot accumulate the prior 187 KiB payload."""
    schema = _schema(
        [_table(index, description="shared " + "x" * 10_000) for index in range(8)]
    )
    policy = ContentPolicy.from_environment({})

    payload_sizes = [
        len(canonical(search_schema(schema, policy, "c" * 64, query).payload))
        for query in (
            "shared value",
            "shared public",
            "value public",
            "public shared value",
            "shared public value",
        )
    ]

    assert MAX_SCHEMA_MATCHES == 2
    assert sum(payload_sizes) <= 5 * 24 * 1024


def test_schema_search_shrinks_oversized_match_set_deterministically() -> None:
    schema = _schema(
        [_table(index, description="shared " + "x" * 39_000) for index in range(3)]
    )
    policy = ContentPolicy.from_environment({})

    first = search_schema(schema, policy, "c" * 64, "shared")
    second = search_schema(schema, policy, "c" * 64, "shared")

    assert first == second
    assert len(first.payload["tables"]) == 1
    assert first.payload["truncated"] is True
    assert len(canonical(first.payload)) <= MAX_SCHEMA_PAYLOAD_BYTES


@pytest.mark.parametrize("query", ["", "   ", ".-", "x" * 513, 42])
def test_schema_search_rejects_invalid_queries(query: object) -> None:
    with pytest.raises(DirectPublicContextError, match="query"):
        search_schema(
            _schema([_table(0)]),
            ContentPolicy.from_environment({}),
            "c" * 64,
            query,  # type: ignore[arg-type]
        )


def test_schema_search_rejects_secret_query_without_persisting_it() -> None:
    policy = ContentPolicy.from_environment({"OMNI_API_TOKEN": "live-secret-value"})

    with pytest.raises(DirectPublicContextError, match="sensitive") as error:
        search_schema(_schema([_table(0)]), policy, "c" * 64, "live-secret-value")

    assert "live-secret-value" not in str(error.value)

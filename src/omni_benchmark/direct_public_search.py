"""Deterministic bounded retrieval over committed public reference data."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from .content_policy import ContentPolicy
from .direct_capture_contract import DirectReferenceResult
from .direct_public_parsing import (
    DirectPublicContextError,
    canonical,
    validate_payload,
)

MAX_QUERY_CHARS = 512
MAX_SCHEMA_MATCHES = 2
MAX_SCHEMA_PAYLOAD_BYTES = 64 * 1024

_TERM = re.compile(r"[^\W_]+", re.UNICODE)


def search_schema(
    canonical_schema: bytes,
    policy: ContentPolicy,
    context_sha256: str,
    query: str,
) -> DirectReferenceResult:
    """Return only public schema tables relevant to a bounded lexical query."""
    source = _schema_source(canonical_schema)
    terms = search_query(query, policy)
    tables = source["tables"]
    matched = list(
        rank_public_records(
            tables,
            terms,
            ("stable_id", "name", "canonical_sql", "columns", "foreign_keys"),
        )
    )
    selected = matched[:MAX_SCHEMA_MATCHES]
    while True:
        payload = {
            "database": source["database"],
            "kind": "public-schema-search",
            "query": query,
            "retrieved_schema_stable_ids": _schema_stable_ids(selected),
            "source": source["source"],
            "tables": selected,
            "truncated": len(selected) < len(matched),
        }
        if len(canonical(payload)) <= MAX_SCHEMA_PAYLOAD_BYTES:
            break
        if not selected:
            raise DirectPublicContextError("schema search payload exceeds its bound")
        selected = selected[:-1]
    validate_payload(payload, MAX_SCHEMA_PAYLOAD_BYTES, policy)
    return DirectReferenceResult(payload, context_sha256, "inspect_schema")


def rank_public_records(
    records: Sequence[Mapping[str, Any]],
    terms: tuple[str, ...],
    fields: tuple[str, ...],
) -> tuple[Mapping[str, Any], ...]:
    """Rank public text with unweighted FTS5 BM25 and canonical-order ties."""
    documents = tuple(
        " ".join(str(record[field]) for field in fields if field in record)
        for record in records
    )
    try:
        with sqlite3.connect(":memory:") as connection:
            connection.execute(
                "CREATE VIRTUAL TABLE public_search USING "
                "fts5(content, tokenize='unicode61 remove_diacritics 2')"
            )
            connection.executemany(
                "INSERT INTO public_search(content) VALUES (?)",
                ((document,) for document in documents),
            )
            rows = connection.execute(
                "SELECT rowid FROM public_search "
                "WHERE public_search MATCH ? ORDER BY rank, rowid",
                (_fts5_or_query(terms),),
            ).fetchall()
    except sqlite3.Error as error:
        raise DirectPublicContextError("public FTS5 search is unavailable") from error
    return tuple(records[rowid - 1] for (rowid,) in rows)


def search_query(query: str, policy: ContentPolicy) -> tuple[str, ...]:
    """Validate one public lexical retrieval query and return stable terms."""
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise DirectPublicContextError("search query must be non-empty and bounded")
    if not policy.query_is_safe(query):
        raise DirectPublicContextError("search query contains sensitive content")
    terms = tuple(sorted(set(_TERM.findall(query.casefold()))))
    if not terms:
        raise DirectPublicContextError("search query contains no searchable terms")
    return terms


def _schema_source(canonical_schema: bytes) -> dict[str, Any]:
    try:
        value = json.loads(canonical_schema)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DirectPublicContextError("canonical schema context is invalid") from error
    if (
        not isinstance(value, dict)
        or value.get("kind") != "public-schema-context"
        or not isinstance(value.get("database"), str)
        or not isinstance(value.get("source"), dict)
        or not isinstance(value.get("tables"), list)
    ):
        raise DirectPublicContextError("canonical schema context is invalid")
    if any(not isinstance(table, dict) for table in value["tables"]):
        raise DirectPublicContextError("canonical schema tables are invalid")
    return value


def _schema_stable_ids(tables: Sequence[Mapping[str, Any]]) -> list[str]:
    values: set[str] = set()
    for table in tables:
        _add_stable_id(values, table)
        for column in _object_sequence(table.get("columns"), "schema columns"):
            _add_stable_id(values, column)
            for leaf in _object_sequence(
                column.get("structured_leaves"), "structured schema leaves"
            ):
                _add_stable_id(values, leaf)
        for relationship in _object_sequence(
            table.get("foreign_keys"), "schema foreign keys"
        ):
            _add_stable_id(values, relationship)
    return sorted(values)


def _object_sequence(value: object, description: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise DirectPublicContextError(f"{description} are invalid")
    return tuple(value)


def _add_stable_id(values: set[str], value: Mapping[str, Any]) -> None:
    stable_id = value.get("stable_id")
    if not isinstance(stable_id, str) or not stable_id:
        raise DirectPublicContextError("schema object stable ID is invalid")
    values.add(stable_id)


def _fts5_or_query(terms: tuple[str, ...]) -> str:
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)

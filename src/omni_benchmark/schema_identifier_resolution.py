"""Reconcile public metadata keys with PostgreSQL identifier semantics."""

from __future__ import annotations

from typing import Mapping, Sequence, TypeVar

from .schema_ddl import IdentifierDefinition, TableDefinition


class SchemaIdentifierResolutionError(ValueError):
    """Raised when metadata identifiers cannot be reconciled unambiguously."""


_Value = TypeVar("_Value")


def _casefolded_unquoted_name(
    source_name: str,
    identifiers: Sequence[IdentifierDefinition],
) -> str | None:
    matches = {
        identifier.name
        for identifier in identifiers
        if not identifier.quoted
        and identifier.name.casefold() == source_name.casefold()
    }
    return next(iter(matches)) if len(matches) == 1 else None


def canonicalize_metadata_identifiers(
    tables: Sequence[TableDefinition],
    meanings: Mapping[tuple[str, str], _Value],
) -> dict[tuple[str, str], _Value]:
    """Resolve metadata spelling only to unique unquoted DDL identifiers."""
    table_index = {table.identifier.name: table for table in tables}
    table_identifiers = tuple(table.identifier for table in tables)
    canonical: dict[tuple[str, str], _Value] = {}
    for (source_table, source_column), meaning in meanings.items():
        table_name = source_table
        table = table_index.get(table_name)
        if table is None:
            table_name = (
                _casefolded_unquoted_name(source_table, table_identifiers)
                or source_table
            )
            table = table_index.get(table_name)
        column_name = source_column
        if table is not None and not any(
            column.identifier.name == column_name for column in table.columns
        ):
            column_name = (
                _casefolded_unquoted_name(
                    source_column,
                    tuple(column.identifier for column in table.columns),
                )
                or source_column
            )
        key = (table_name, column_name)
        if key in canonical:
            raise SchemaIdentifierResolutionError(
                "metadata identifiers resolve to duplicate DDL column "
                f"{table_name}.{column_name}"
            )
        canonical[key] = meaning
    return canonical

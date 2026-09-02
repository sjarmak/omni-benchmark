"""Row values bound to the telemetry table layout, and their idempotent upsert."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping

from psycopg import sql
from psycopg.types.json import Jsonb

from .schema import SCHEMA_NAME, TABLE_SPECS, TableSpec

DEFAULT_BATCH_SIZE = 500
JSON_COLUMN_TYPE = "jsonb"


class RowError(ValueError):
    """Raised when a row does not fit its table or cannot be written."""


@dataclass(frozen=True)
class Row:
    """Values for one telemetry table row; unset columns load as NULL."""

    table: str
    values: Mapping[str, Any]

    def __post_init__(self) -> None:
        spec = TABLE_SPECS.get(self.table)
        if spec is None:
            raise RowError(f"unknown telemetry table {self.table!r}")
        unknown = sorted(set(self.values) - set(spec.columns))
        if unknown:
            raise RowError(f"{self.table}: unknown columns {unknown}")
        missing = [key for key in spec.primary_key if self.values.get(key) is None]
        if missing:
            raise RowError(f"{self.table}: primary key columns are null {missing}")
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def spec(self) -> TableSpec:
        """The parsed table layout this row is bound to."""
        return TABLE_SPECS[self.table]

    def to_tuple(self) -> tuple[Any, ...]:
        """Values in schema column order, None for every unset column."""
        return tuple(self.values.get(column) for column in self.spec.columns)


def build_upsert_statement(spec: TableSpec) -> sql.Composed:
    """INSERT ... ON CONFLICT (primary key) DO UPDATE for every column of spec."""
    identifiers = sql.SQL(", ").join(sql.Identifier(name) for name in spec.columns)
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in spec.columns)
    conflict_target = sql.SQL(", ").join(
        sql.Identifier(name) for name in spec.primary_key
    )
    if spec.value_columns:
        assignments = sql.SQL(", ").join(
            sql.SQL("{column} = EXCLUDED.{column}").format(column=sql.Identifier(name))
            for name in spec.value_columns
        )
        action = sql.SQL("DO UPDATE SET {assignments}").format(assignments=assignments)
    else:
        action = sql.SQL("DO NOTHING")
    return sql.SQL(
        "INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
        "ON CONFLICT ({conflict}) {action}"
    ).format(
        table=sql.Identifier(SCHEMA_NAME, spec.name),
        columns=identifiers,
        placeholders=placeholders,
        conflict=conflict_target,
        action=action,
    )


def adapt_parameters(spec: TableSpec, row: Row) -> tuple[Any, ...]:
    """Column-ordered parameters with JSON columns wrapped for psycopg."""
    return tuple(
        Jsonb(value)
        if value is not None and spec.column_types[column] == JSON_COLUMN_TYPE
        else value
        for column, value in zip(spec.columns, row.to_tuple(), strict=True)
    )


def _batches(items: Iterator[tuple[Any, ...]], size: int) -> Iterator[list[Any]]:
    while batch := list(islice(items, size)):
        yield batch


def upsert_rows(
    conn: Any,
    table: str,
    rows: Iterable[Row],
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Upsert rows into table in batches within the caller's transaction.

    Returns the number of rows submitted. Re-loading identical rows updates the
    existing copies in place, so a load is idempotent. The caller commits.
    """
    spec = TABLE_SPECS.get(table)
    if spec is None:
        raise RowError(f"unknown telemetry table {table!r}")
    if batch_size < 1:
        raise RowError("batch_size must be at least 1")
    statement = build_upsert_statement(spec)
    parameters = (adapt_parameters(spec, _bound_to(row, table)) for row in rows)
    submitted = 0
    with conn.cursor() as cursor:
        for batch in _batches(parameters, batch_size):
            cursor.executemany(statement, batch)
            submitted += len(batch)
    return submitted


def _bound_to(row: Row, table: str) -> Row:
    if row.table != table:
        raise RowError(f"row bound to {row.table!r} cannot load into {table!r}")
    return row

"""Telemetry database DDL and the table layout parsed from it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_NAME = "telemetry"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_TABLE_PATTERN = re.compile(
    r"^CREATE TABLE IF NOT EXISTS telemetry\.(\w+) \(\n(.*?)\n\);$",
    re.DOTALL | re.MULTILINE,
)
_COLUMN_PATTERN = re.compile(r"^(\w+) (\w+)(?: NOT NULL)?$")
_PRIMARY_KEY_PATTERN = re.compile(r"^PRIMARY KEY \(([\w, ]+)\)$")


class SchemaError(ValueError):
    """Raised when schema.sql does not follow the parseable table layout."""


@dataclass(frozen=True)
class TableSpec:
    """Column order, column types, and primary key of one telemetry table."""

    name: str
    columns: tuple[str, ...]
    column_types: Mapping[str, str]
    primary_key: tuple[str, ...]

    @property
    def value_columns(self) -> tuple[str, ...]:
        """Columns outside the primary key, in declaration order."""
        return tuple(name for name in self.columns if name not in self.primary_key)


def load_schema_sql() -> str:
    """Return the idempotent DDL shipped next to this module."""
    return SCHEMA_PATH.read_text(encoding="utf-8")


def apply_schema(conn: Any) -> None:
    """Apply the DDL on an open psycopg connection inside its transaction."""
    with conn.cursor() as cursor:
        cursor.execute(load_schema_sql())


def parse_table_specs(sql: str) -> Mapping[str, TableSpec]:
    """Parse every CREATE TABLE body into a TableSpec keyed by table name."""
    specs: dict[str, TableSpec] = {}
    for match in _TABLE_PATTERN.finditer(sql):
        name, body = match.group(1), match.group(2)
        if name in specs:
            raise SchemaError(f"table {name} is declared twice")
        specs[name] = _parse_table_body(name, body)
    if not specs:
        raise SchemaError("schema declares no tables")
    return MappingProxyType(specs)


def _parse_table_body(name: str, body: str) -> TableSpec:
    columns: dict[str, str] = {}
    primary_key: tuple[str, ...] | None = None
    for raw_line in body.splitlines():
        line = raw_line.strip().rstrip(",")
        key_match = _PRIMARY_KEY_PATTERN.match(line)
        if key_match is not None:
            if primary_key is not None:
                raise SchemaError(f"table {name} declares two primary keys")
            primary_key = tuple(part.strip() for part in key_match.group(1).split(","))
            continue
        column_match = _COLUMN_PATTERN.match(line)
        if column_match is None:
            raise SchemaError(f"table {name} has an unparseable line: {line!r}")
        column, column_type = column_match.groups()
        if column in columns:
            raise SchemaError(f"table {name} declares column {column} twice")
        columns[column] = column_type
    if primary_key is None:
        raise SchemaError(f"table {name} has no primary key")
    missing = [key for key in primary_key if key not in columns]
    if missing:
        raise SchemaError(f"table {name} primary key names unknown columns {missing}")
    return TableSpec(
        name=name,
        columns=tuple(columns),
        column_types=MappingProxyType(dict(columns)),
        primary_key=primary_key,
    )


TABLE_SPECS: Mapping[str, TableSpec] = parse_table_specs(load_schema_sql())
TABLE_COLUMNS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {name: spec.columns for name, spec in TABLE_SPECS.items()}
)
TABLE_PRIMARY_KEYS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {name: spec.primary_key for name, spec in TABLE_SPECS.items()}
)

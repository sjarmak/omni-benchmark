from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .database_postgres import PostgresClient, validate_identifier


SCHEMA_QUERY = r"""
COPY (
  SELECT 'column', n.nspname, c.relname, a.attnum::text, a.attname,
         pg_catalog.format_type(a.atttypid, a.atttypmod), a.attnotnull::text,
         a.attidentity::text, a.attgenerated::text,
         COALESCE(pg_catalog.pg_get_expr(d.adbin, d.adrelid), '')
  FROM pg_catalog.pg_attribute a
  JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_catalog.pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
  WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
    AND n.nspname !~ '^pg_toast' AND c.relkind IN ('r', 'p', 'v', 'm')
    AND a.attnum > 0 AND NOT a.attisdropped
  UNION ALL
  SELECT 'constraint', n.nspname, c.relname, '0', con.conname,
         con.contype::text, '', '', '', pg_catalog.pg_get_constraintdef(con.oid, true)
  FROM pg_catalog.pg_constraint con
  JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
  JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  UNION ALL
  SELECT 'index', schemaname, tablename, '0', indexname, '', '', '', '', indexdef
  FROM pg_catalog.pg_indexes
  WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
  UNION ALL
  SELECT 'extension', '', '', '0', extname, extversion, '', '', '', ''
  FROM pg_catalog.pg_extension
  ORDER BY 1, 2, 3, 4, 5, 6, 10
) TO STDOUT WITH (FORMAT csv, ENCODING 'UTF8');
"""

TABLE_QUERY = r"""
SELECT n.nspname || E'\t' || c.relname
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND n.nspname !~ '^pg_toast'
ORDER BY n.nspname COLLATE "C", c.relname COLLATE "C";
"""


@dataclass(frozen=True)
class TableFingerprint:
    schema: str
    table: str
    row_count: int
    content_sha256: str


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _quote_identifier(value: str) -> str:
    return f'"{validate_identifier(value)}"'


def fingerprint_database(client: PostgresClient, database: str) -> dict[str, Any]:
    validate_identifier(database)
    server_version = (
        client.run(database, sql="SHOW server_version_num;").decode().strip()
    )
    schema_bytes = client.run(database, sql=SCHEMA_QUERY)
    table_lines = client.run(database, sql=TABLE_QUERY).decode("utf-8").splitlines()
    tables: list[TableFingerprint] = []
    for line in table_lines:
        schema, table = line.split("\t", maxsplit=1)
        qualified = f"{_quote_identifier(schema)}.{_quote_identifier(table)}"
        row_count = int(
            client.run(database, sql=f"SELECT count(*) FROM {qualified};")
            .decode()
            .strip()
        )
        content = client.run(
            database,
            sql=(
                "COPY (SELECT to_jsonb(row_value)::text AS row_json "
                f"FROM {qualified} AS row_value "
                'ORDER BY to_jsonb(row_value)::text COLLATE "C") '
                "TO STDOUT WITH (FORMAT csv, ENCODING 'UTF8');"
            ),
        )
        tables.append(
            TableFingerprint(
                schema=schema,
                table=table,
                row_count=row_count,
                content_sha256=_sha256(content),
            )
        )
    table_payload = [table.__dict__ for table in tables]
    content_bytes = json.dumps(
        table_payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "format_version": 1,
        "database": database,
        "postgres_server_version_num": server_version,
        "schema_sha256": _sha256(schema_bytes),
        "content_sha256": _sha256(content_bytes),
        "table_count": len(tables),
        "row_count": sum(table.row_count for table in tables),
        "tables": table_payload,
    }


def compare_fingerprints(left: Path, right: Path) -> int:
    try:
        left_value = json.loads(left.read_text(encoding="utf-8"))
        right_value = json.loads(right.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 2
    if not _valid_fingerprint(left_value) or not _valid_fingerprint(right_value):
        return 2
    fields = (
        "format_version",
        "database",
        "postgres_server_version_num",
        "schema_sha256",
        "content_sha256",
        "table_count",
        "row_count",
        "tables",
    )
    return 0 if all(left_value[field] == right_value[field] for field in fields) else 1


def _valid_fingerprint(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = {
        "format_version",
        "database",
        "postgres_server_version_num",
        "schema_sha256",
        "content_sha256",
        "table_count",
        "row_count",
        "tables",
    }
    if not required.issubset(value):
        return False
    if value["format_version"] != 1:
        return False
    if not isinstance(value["database"], str) or not value["database"]:
        return False
    version = value["postgres_server_version_num"]
    if not isinstance(version, str) or not version.isdigit():
        return False
    sha256 = re.compile(r"^[0-9a-f]{64}$")
    if not all(
        isinstance(value[field], str) and sha256.fullmatch(value[field])
        for field in ("schema_sha256", "content_sha256")
    ):
        return False
    table_count = value["table_count"]
    row_count = value["row_count"]
    tables = value["tables"]
    if (
        not isinstance(table_count, int)
        or table_count < 0
        or not isinstance(row_count, int)
        or row_count < 0
        or not isinstance(tables, list)
        or len(tables) != table_count
    ):
        return False
    for table in tables:
        if not isinstance(table, dict):
            return False
        if set(table) != {"schema", "table", "row_count", "content_sha256"}:
            return False
        if not all(
            isinstance(table[field], str) and table[field]
            for field in ("schema", "table")
        ):
            return False
        if not isinstance(table["row_count"], int) or table["row_count"] < 0:
            return False
        if not isinstance(table["content_sha256"], str) or not sha256.fullmatch(
            table["content_sha256"]
        ):
            return False
    if sum(table["row_count"] for table in tables) != row_count:
        return False
    content = json.dumps(tables, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(content).hexdigest() == value["content_sha256"]

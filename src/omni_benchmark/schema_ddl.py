"""Fail-closed PostgreSQL DDL adapter for the public schema IR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlglot import errors, exp, parse_one


class SchemaDDLDataError(ValueError):
    """Raised when a row-separated public DDL source cannot be represented."""


@dataclass(frozen=True)
class IdentifierDefinition:
    name: str
    quoted: bool
    canonical_sql: str


@dataclass(frozen=True)
class ColumnDefinition:
    identifier: IdentifierDefinition
    declared_type_sql: str
    nullable: bool
    default_expression_sql: str | None
    source_ordinal: int


@dataclass(frozen=True)
class ForeignKeyDefinition:
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]
    source_ordinal: int


@dataclass(frozen=True)
class TableDefinition:
    identifier: IdentifierDefinition
    ddl: str
    byte_start: int
    byte_end_exclusive: int
    source_ordinal: int
    columns: tuple[ColumnDefinition, ...]
    primary_key: tuple[str, ...]
    unique_keys: tuple[tuple[str, ...], ...]
    foreign_keys: tuple[ForeignKeyDefinition, ...]


@dataclass(frozen=True)
class _DDLBlock:
    ddl: str
    byte_start: int
    byte_end_exclusive: int
    source_ordinal: int


def _line_value(line: bytes) -> bytes:
    return line.removesuffix(b"\n").removesuffix(b"\r")


def _line_offsets(lines: Sequence[bytes]) -> tuple[int, ...]:
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    return tuple(offsets)


def _skip_empty(lines: Sequence[bytes], index: int) -> int:
    while index < len(lines) and _line_value(lines[index]) == b"":
        index += 1
    return index


def _ddl_end(lines: Sequence[bytes], start: int, database: str) -> int:
    if not _line_value(lines[start]).startswith(b"CREATE TABLE "):
        raise SchemaDDLDataError(
            f"schema for {database} expected CREATE TABLE at line {start + 1}"
        )
    index = start
    while index < len(lines):
        current = _line_value(lines[index])
        if current == b");":
            return index + 1
        if current == b"First 3 rows:":
            break
        index += 1
    raise SchemaDDLDataError(f"schema for {database} has an unterminated CREATE TABLE")


def _sample_end(lines: Sequence[bytes], index: int, database: str) -> int:
    index = _skip_empty(lines, index)
    if index == len(lines) or _line_value(lines[index]) != b"First 3 rows:":
        raise SchemaDDLDataError(
            f"schema for {database} expected First 3 rows after DDL"
        )
    index += 1
    while index < len(lines) and _line_value(lines[index]) != b"...":
        index += 1
    if index == len(lines):
        raise SchemaDDLDataError(
            f"schema for {database} has an unterminated example-row section"
        )
    return index + 1


def _block_at(
    content: bytes,
    lines: Sequence[bytes],
    offsets: Sequence[int],
    start: int,
    ordinal: int,
    database: str,
) -> tuple[_DDLBlock, int]:
    ddl_line_end = _ddl_end(lines, start, database)
    ddl_byte_end = (
        offsets[ddl_line_end] if ddl_line_end < len(offsets) else len(content)
    )
    block = _DDLBlock(
        ddl=content[offsets[start] : ddl_byte_end].decode("utf-8"),
        byte_start=offsets[start],
        byte_end_exclusive=ddl_byte_end,
        source_ordinal=ordinal,
    )
    return block, _sample_end(lines, ddl_line_end, database)


def _split_row_free_ddl(content: bytes, database: str) -> tuple[_DDLBlock, ...]:
    try:
        content.decode("utf-8")
    except UnicodeError as error:
        raise SchemaDDLDataError(f"schema for {database} is not UTF-8") from error
    lines = content.splitlines(keepends=True)
    offsets = _line_offsets(lines)
    blocks: list[_DDLBlock] = []
    index = 0
    while index < len(lines):
        index = _skip_empty(lines, index)
        if index == len(lines):
            break
        block, index = _block_at(content, lines, offsets, index, len(blocks), database)
        blocks.append(block)
    if not blocks:
        raise SchemaDDLDataError(f"schema for {database} contains no DDL tables")
    return tuple(blocks)


def _identifier(value: exp.Identifier) -> IdentifierDefinition:
    quoted = bool(value.args.get("quoted"))
    return IdentifierDefinition(
        name=value.name if quoted else value.name.lower(),
        quoted=quoted,
        canonical_sql=value.sql(dialect="postgres"),
    )


def _identifier_names(values: Sequence[exp.Expression]) -> tuple[str, ...]:
    names: list[str] = []
    for value in values:
        if not isinstance(value, exp.Identifier):
            raise SchemaDDLDataError("key constraint contains a non-identifier column")
        names.append(_identifier(value).name)
    if not names:
        raise SchemaDDLDataError("key constraint must contain at least one column")
    return tuple(names)


def _unqualified_table_identifier(
    value: exp.Table, *, label: str
) -> IdentifierDefinition:
    if value.args.get("db") is not None or value.args.get("catalog") is not None:
        raise SchemaDDLDataError(f"{label} must not be schema-qualified")
    if not isinstance(value.this, exp.Identifier):
        raise SchemaDDLDataError(f"{label} must be an identifier")
    return _identifier(value.this)


def _column_constraints(
    constraints: Sequence[exp.ColumnConstraint],
) -> tuple[bool, str | None, bool, bool]:
    nullable = True
    default_expression: str | None = None
    primary = False
    unique = False
    for constraint in constraints:
        kind = constraint.kind
        if isinstance(kind, exp.NotNullColumnConstraint):
            nullable = bool(kind.args.get("allow_null"))
        elif isinstance(kind, exp.DefaultColumnConstraint):
            if default_expression is not None:
                raise SchemaDDLDataError("column has multiple DEFAULT constraints")
            default_expression = kind.this.sql(dialect="postgres")
        elif isinstance(kind, exp.PrimaryKeyColumnConstraint):
            primary = True
        elif isinstance(kind, exp.UniqueColumnConstraint):
            unique = True
        else:
            raise SchemaDDLDataError(
                f"unsupported column constraint {type(kind).__name__}"
            )
    return nullable, default_expression, primary, unique


def _foreign_key(value: exp.ForeignKey, source_ordinal: int) -> ForeignKeyDefinition:
    reference = value.args.get("reference")
    if not isinstance(reference, exp.Reference):
        raise SchemaDDLDataError("FOREIGN KEY must contain a REFERENCES clause")
    target_schema = reference.this
    if not isinstance(target_schema, exp.Schema) or not isinstance(
        target_schema.this, exp.Table
    ):
        raise SchemaDDLDataError("FOREIGN KEY target must be one table")
    target_identifier = _unqualified_table_identifier(
        target_schema.this, label="FOREIGN KEY target"
    )
    return ForeignKeyDefinition(
        source_columns=_identifier_names(value.expressions),
        target_table=target_identifier.name,
        target_columns=_identifier_names(target_schema.expressions),
        source_ordinal=source_ordinal,
    )


def _column(
    expression: exp.ColumnDef,
    source_ordinal: int,
) -> tuple[ColumnDefinition, bool, bool]:
    if not isinstance(expression.this, exp.Identifier) or not isinstance(
        expression.kind, exp.DataType
    ):
        raise SchemaDDLDataError("column definition is missing its identifier or type")
    nullable, default, primary, unique = _column_constraints(expression.constraints)
    return (
        ColumnDefinition(
            identifier=_identifier(expression.this),
            declared_type_sql=expression.kind.sql(dialect="postgres"),
            nullable=nullable,
            default_expression_sql=default,
            source_ordinal=source_ordinal,
        ),
        primary,
        unique,
    )


def _table_elements(
    expressions: Sequence[exp.Expression],
) -> tuple[
    tuple[ColumnDefinition, ...],
    tuple[str, ...],
    tuple[tuple[str, ...], ...],
    tuple[ForeignKeyDefinition, ...],
]:
    columns: list[ColumnDefinition] = []
    primary_key: tuple[str, ...] = ()
    unique_keys: list[tuple[str, ...]] = []
    foreign_keys: list[ForeignKeyDefinition] = []
    inline_primary: list[str] = []
    for expression in expressions:
        if isinstance(expression, exp.ColumnDef):
            column, primary, unique = _column(expression, len(columns))
            columns.append(column)
            inline_primary.extend([column.identifier.name] if primary else [])
            unique_keys.extend([(column.identifier.name,)] if unique else [])
        elif isinstance(expression, exp.PrimaryKey):
            if primary_key:
                raise SchemaDDLDataError("table has multiple PRIMARY KEY constraints")
            primary_key = _identifier_names(expression.expressions)
        elif isinstance(expression, exp.ForeignKey):
            foreign_keys.append(_foreign_key(expression, len(foreign_keys)))
        elif isinstance(expression, exp.UniqueColumnConstraint):
            unique_keys.append(_identifier_names(expression.expressions))
        else:
            raise SchemaDDLDataError(
                f"unsupported CREATE TABLE element {type(expression).__name__}"
            )
    if inline_primary and primary_key:
        raise SchemaDDLDataError("table mixes inline and table PRIMARY KEY constraints")
    if not columns:
        raise SchemaDDLDataError("CREATE TABLE must contain at least one column")
    return (
        tuple(columns),
        tuple(inline_primary) if inline_primary else primary_key,
        tuple(unique_keys),
        tuple(foreign_keys),
    )


def _table(block: _DDLBlock, database: str) -> TableDefinition:
    try:
        parsed = parse_one(block.ddl, read="postgres")
    except (errors.ParseError, RecursionError) as error:
        raise SchemaDDLDataError(
            f"cannot parse DDL table {block.source_ordinal} for {database}"
        ) from error
    if not isinstance(parsed, exp.Create) or not isinstance(parsed.this, exp.Schema):
        raise SchemaDDLDataError("DDL block must contain exactly one CREATE TABLE")
    table_expression = parsed.this.this
    if not isinstance(table_expression, exp.Table):
        raise SchemaDDLDataError("CREATE TABLE must name one table identifier")
    table_identifier = _unqualified_table_identifier(
        table_expression, label="CREATE TABLE name"
    )
    columns, primary_key, unique_keys, foreign_keys = _table_elements(
        parsed.this.expressions
    )
    return TableDefinition(
        identifier=table_identifier,
        ddl=block.ddl,
        byte_start=block.byte_start,
        byte_end_exclusive=block.byte_end_exclusive,
        source_ordinal=block.source_ordinal,
        columns=columns,
        primary_key=primary_key,
        unique_keys=unique_keys,
        foreign_keys=foreign_keys,
    )


def parse_public_ddl(content: bytes, database: str) -> tuple[TableDefinition, ...]:
    """Return immutable source definitions without exposing example-row content."""

    return tuple(
        _table(block, database) for block in _split_row_free_ddl(content, database)
    )

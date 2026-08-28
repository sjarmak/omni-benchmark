"""Fail-closed PostgreSQL Query-only admission shared by generation and scoring."""

from __future__ import annotations

from collections.abc import Sequence

import sqlglot
from sqlglot import exp
from sqlglot.dialects import Dialect
from sqlglot.parsers.postgres import PostgresParser
from sqlglot.tokens import Token, TokenType

_SIDE_EFFECT_FUNCTIONS = frozenset(
    {
        "nextval",
        "pg_cancel_backend",
        "pg_create_restore_point",
        "pg_export_snapshot",
        "pg_log_backend_memory_contexts",
        "pg_notify",
        "pg_promote",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "pg_switch_wal",
        "pg_terminate_backend",
        "set_config",
        "setseed",
        "setval",
    }
)
_SIDE_EFFECT_FUNCTION_PREFIXES = ("lo_", "pg_")


class _QuietPostgresParser(PostgresParser):
    """Reject unsupported commands without logging their source text."""

    def _warn_unsupported(self) -> None:
        return


_POSTGRES_DIALECT = Dialect.get_or_raise("postgres")


def query_sql_is_admissible(statements: str | Sequence[str]) -> bool:
    """Return true only for non-empty PostgreSQL Query expressions."""
    values: object = (statements,) if isinstance(statements, str) else statements
    if not isinstance(values, Sequence) or not values:
        return False
    if any(
        not isinstance(statement, str) or not statement.strip() for statement in values
    ):
        return False
    try:
        parsed = tuple(
            expression
            for statement in values
            for expression in _parse_without_source_logging(statement)
        )
    except (sqlglot.errors.SqlglotError, TypeError, ValueError):
        return False
    if not parsed or any(
        not isinstance(expression, exp.Query) for expression in parsed
    ):
        return False
    if any(
        expression.find(exp.DML) is not None or expression.find(exp.Into) is not None
        for expression in parsed
    ):
        return False
    return not any(
        _side_effect_function(function.name)
        for expression in parsed
        for function in expression.find_all(exp.Anonymous)
    )


def _parse_without_source_logging(statement: str) -> list[exp.Expr | None]:
    parser = _QuietPostgresParser(dialect=_POSTGRES_DIALECT)
    tokens = _POSTGRES_DIALECT.tokenize(statement)
    if _has_unicode_identifier(tokens):
        return [None]
    return parser.parse(tokens, statement)


def _has_unicode_identifier(tokens: list[Token]) -> bool:
    return any(
        first.token_type is TokenType.VAR
        and first.text.casefold() == "u"
        and second.token_type is TokenType.AMP
        and third.token_type is TokenType.IDENTIFIER
        for first, second, third in zip(tokens, tokens[1:], tokens[2:])
    )


def _side_effect_function(name: str) -> bool:
    normalized = name.lower()
    return normalized in _SIDE_EFFECT_FUNCTIONS or normalized.startswith(
        _SIDE_EFFECT_FUNCTION_PREFIXES
    )

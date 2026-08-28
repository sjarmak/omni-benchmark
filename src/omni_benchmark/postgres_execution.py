"""Typed PostgreSQL execution matching the public LiveSQLBench Query runner."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from threading import Event, Timer
from typing import Any, Literal, Protocol

MAX_RESULT_ROWS = 10_000
STATEMENT_TIMEOUT_SECONDS = 60
MAX_STATEMENT_TIMEOUT_MS = STATEMENT_TIMEOUT_SECONDS * 1_000
STATEMENT_TIMEOUT_SQL = "SET statement_timeout = '60s';"
READ_ONLY_TRANSACTION_SQL = "SET TRANSACTION READ ONLY;"
QUERY_CANCELED_SQLSTATE = "57014"


class PostgreSQLCursor(Protocol):
    """The DB-API cursor surface needed by the sealed evaluator."""

    description: object | None

    def execute(self, sql: str) -> None: ...

    def fetchmany(self, size: int) -> Sequence[Sequence[Any]]: ...

    def nextset(self) -> bool | None: ...

    def close(self) -> None: ...


class PostgreSQLConnection(Protocol):
    """The DB-API connection surface needed by the sealed evaluator."""

    def cursor(self) -> PostgreSQLCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def cancel_safe(self) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class QuerySequenceResult:
    """Rows from the last statement and public execution metadata."""

    rows: tuple[tuple[Any, ...], ...] | None = field(repr=False)
    statement_count: int
    row_limit_exceeded: bool = False


class PostgreSQLExecutionError(RuntimeError):
    """Sanitized database failure with no SQL or driver message attached."""

    def __init__(
        self,
        *,
        kind: Literal["timeout", "statement", "infrastructure"],
        sqlstate: str | None,
        statement_index: int,
    ) -> None:
        super().__init__(f"PostgreSQL {kind} failure at statement {statement_index}")
        self.kind = kind
        self.sqlstate = sqlstate
        self.statement_index = statement_index


def execute_query_sequence(
    connection: PostgreSQLConnection,
    statements: str | Sequence[str],
    *,
    statement_timeout_ms: int = MAX_STATEMENT_TIMEOUT_MS,
    read_only: bool = False,
) -> QuerySequenceResult:
    """Execute statements sequentially and retain only the last result."""
    normalized = _normalize_statements(statements)
    timeout_sql = _timeout_sql(statement_timeout_ms)
    result: tuple[tuple[Any, ...], ...] | None = None
    row_limit_exceeded = False
    for index, sql in enumerate(normalized):
        result, row_limit_exceeded = _execute_statement(
            connection,
            sql,
            index,
            timeout_sql,
            timeout_ms=statement_timeout_ms,
            read_only=read_only,
        )
    return QuerySequenceResult(
        rows=result,
        statement_count=len(normalized),
        row_limit_exceeded=row_limit_exceeded,
    )


def _normalize_statements(statements: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(statements, str):
        values: object = (statements,)
    else:
        values = statements
    if not isinstance(values, Sequence) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ValueError("SQL statements must be non-empty strings")
    return tuple(values)


def _execute_statement(
    connection: PostgreSQLConnection,
    sql: str,
    statement_index: int,
    timeout_sql: str,
    *,
    timeout_ms: int,
    read_only: bool,
) -> tuple[tuple[tuple[Any, ...], ...] | None, bool]:
    try:
        cursor = connection.cursor()
    except Exception:
        raise _infrastructure_error(statement_index) from None
    operation_error: PostgreSQLExecutionError | None = None
    result: tuple[tuple[Any, ...], ...] | None = None
    row_limit_exceeded = False
    try:
        cursor.execute(timeout_sql)
        if read_only:
            cursor.execute(READ_ONLY_TRANSACTION_SQL)
        _execute_with_client_timeout(
            connection,
            cursor,
            sql,
            statement_index,
            timeout_ms=timeout_ms,
        )
        connection.commit()
        while cursor.nextset():
            pass
        if cursor.description is not None:
            rows = cursor.fetchmany(MAX_RESULT_ROWS + 1)
            result = tuple(tuple(row) for row in rows[:MAX_RESULT_ROWS])
            row_limit_exceeded = len(rows) > MAX_RESULT_ROWS
    except Exception as error:
        operation_error = _execution_error(error, statement_index)
        try:
            connection.rollback()
        except Exception:
            operation_error = _infrastructure_error(statement_index)
    try:
        cursor.close()
    except Exception:
        raise _infrastructure_error(statement_index) from None
    if operation_error is not None:
        raise operation_error from None
    return result, row_limit_exceeded


def _execute_with_client_timeout(
    connection: PostgreSQLConnection,
    cursor: PostgreSQLCursor,
    sql: str,
    statement_index: int,
    *,
    timeout_ms: int,
) -> None:
    cancellation_fired = Event()
    cancellation_failed = Event()

    def cancel() -> None:
        cancellation_fired.set()
        try:
            connection.cancel_safe()
        except Exception:
            cancellation_failed.set()
            try:
                connection.close()
            except Exception:
                return

    timer = Timer(timeout_ms / 1_000, cancel)
    timer.daemon = True
    timer.start()
    execution_error: Exception | None = None
    try:
        cursor.execute(sql)
    except Exception as error:
        execution_error = error
    finally:
        timer.cancel()
        timer.join()
    if cancellation_failed.is_set():
        raise _infrastructure_error(statement_index) from None
    if execution_error is not None:
        raise execution_error
    if cancellation_fired.is_set():
        raise PostgreSQLExecutionError(
            kind="timeout",
            sqlstate=QUERY_CANCELED_SQLSTATE,
            statement_index=statement_index,
        )


def _execution_error(
    error: Exception, statement_index: int
) -> PostgreSQLExecutionError:
    sqlstate = _sqlstate(error)
    if sqlstate == QUERY_CANCELED_SQLSTATE:
        kind: Literal["timeout", "statement", "infrastructure"] = "timeout"
    elif (sqlstate is not None and sqlstate.startswith("08")) or isinstance(
        error, (ConnectionError, OSError, TimeoutError)
    ):
        kind = "infrastructure"
    else:
        kind = "statement"
    return PostgreSQLExecutionError(
        kind=kind,
        sqlstate=sqlstate,
        statement_index=statement_index,
    )


def _sqlstate(error: Exception) -> str | None:
    value = getattr(error, "sqlstate", None)
    if value is None:
        value = getattr(error, "pgcode", None)
    return value if isinstance(value, str) else None


def _infrastructure_error(statement_index: int) -> PostgreSQLExecutionError:
    return PostgreSQLExecutionError(
        kind="infrastructure", sqlstate=None, statement_index=statement_index
    )


def _timeout_sql(statement_timeout_ms: int) -> str:
    if (
        isinstance(statement_timeout_ms, bool)
        or not isinstance(statement_timeout_ms, int)
        or not 1 <= statement_timeout_ms <= MAX_STATEMENT_TIMEOUT_MS
    ):
        raise ValueError("statement_timeout_ms must be an integer from 1 through 60000")
    if statement_timeout_ms == MAX_STATEMENT_TIMEOUT_MS:
        return STATEMENT_TIMEOUT_SQL
    return f"SET statement_timeout = '{statement_timeout_ms}ms';"

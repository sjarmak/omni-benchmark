"""Public conformance tests for typed PostgreSQL statement execution."""

from __future__ import annotations

import time

import pytest

from omni_benchmark.postgres_execution import (
    MAX_RESULT_ROWS,
    READ_ONLY_TRANSACTION_SQL,
    STATEMENT_TIMEOUT_SQL,
    PostgreSQLExecutionError,
    execute_query_sequence,
)
from tests.execution_fixtures import SyntheticConnection, SyntheticDatabaseError


def test_sequence_uses_official_timeout_and_returns_only_last_statement_rows() -> None:
    events: list[tuple[object, ...]] = []
    connection = SyntheticConnection({"SELECT 1": [(1,)], "SELECT 2": [(2,)]}, events)

    result = execute_query_sequence(connection, ("SELECT 1", "SELECT 2"))

    assert result.rows == ((2,),)
    assert result.statement_count == 2
    assert not result.row_limit_exceeded
    assert [event for event in events if event[0] == "execute"] == [
        ("execute", STATEMENT_TIMEOUT_SQL),
        ("execute", "SELECT 1"),
        ("execute", STATEMENT_TIMEOUT_SQL),
        ("execute", "SELECT 2"),
    ]
    assert events.count(("commit",)) == 2


def test_semicolon_batch_is_passed_verbatim_and_uses_driver_last_result() -> None:
    sql = "SELECT 1; SELECT 2"
    events: list[tuple[object, ...]] = []
    connection = SyntheticConnection({sql: [(2,)]}, events)

    result = execute_query_sequence(connection, sql)

    assert result.rows == ((2,),)
    assert ("execute", sql) in events
    assert ("nextset",) in events


def test_non_default_timeout_is_bounded_and_expressed_in_milliseconds() -> None:
    events: list[tuple[object, ...]] = []
    connection = SyntheticConnection({"SELECT pg_sleep(1)": []}, events)

    execute_query_sequence(connection, "SELECT pg_sleep(1)", statement_timeout_ms=25)

    assert ("execute", "SET statement_timeout = '25ms';") in events


def test_read_only_execution_marks_each_statement_transaction_read_only() -> None:
    events: list[tuple[object, ...]] = []
    connection = SyntheticConnection({"SELECT 1": [(1,)]}, events)

    execute_query_sequence(connection, "SELECT 1", read_only=True)

    assert [event for event in events if event[0] == "execute"] == [
        ("execute", STATEMENT_TIMEOUT_SQL),
        ("execute", READ_ONLY_TRANSACTION_SQL),
        ("execute", "SELECT 1"),
    ]


def test_row_transport_fetches_one_extra_and_caps_at_ten_thousand() -> None:
    rows = [(index,) for index in range(MAX_RESULT_ROWS + 1)]
    events: list[tuple[object, ...]] = []
    connection = SyntheticConnection({"SELECT n": rows}, events)

    result = execute_query_sequence(connection, "SELECT n")

    assert result.rows is not None
    assert len(result.rows) == MAX_RESULT_ROWS
    assert result.rows[-1] == (MAX_RESULT_ROWS - 1,)
    assert result.row_limit_exceeded
    assert ("fetchmany", MAX_RESULT_ROWS + 1) in events


def test_non_row_statement_and_empty_sequence_have_no_result() -> None:
    events: list[tuple[object, ...]] = []
    connection = SyntheticConnection({"SET application_name = 'x'": None}, events)

    statement = execute_query_sequence(connection, "SET application_name = 'x'")
    empty = execute_query_sequence(connection, ())

    assert statement.rows is None
    assert statement.statement_count == 1
    assert empty.rows is None
    assert empty.statement_count == 0


def test_query_result_repr_never_contains_executed_rows() -> None:
    connection = SyntheticConnection({"SELECT marker": [("sealed-marker",)]}, [])

    result = execute_query_sequence(connection, "SELECT marker")

    assert "sealed-marker" not in repr(result)


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (SyntheticDatabaseError("57014"), "timeout"),
        (SyntheticDatabaseError("08006"), "infrastructure"),
        (SyntheticDatabaseError("42601"), "statement"),
        (ConnectionError("synthetic"), "infrastructure"),
    ],
)
def test_failures_are_sanitized_classified_and_rolled_back(
    error: Exception, kind: str
) -> None:
    events: list[tuple[object, ...]] = []
    connection = SyntheticConnection({"SECRET SQL": error}, events)

    with pytest.raises(PostgreSQLExecutionError) as captured:
        execute_query_sequence(connection, "SECRET SQL")

    assert captured.value.kind == kind
    assert captured.value.statement_index == 0
    assert "SECRET SQL" not in str(captured.value)
    assert events.count(("rollback",)) == 1
    assert events[-1] == ("cursor_close",)


@pytest.mark.parametrize("statements", [[""], ["SELECT 1", 7], 42])
def test_statement_inputs_fail_closed(statements: object) -> None:
    connection = SyntheticConnection({}, [])

    with pytest.raises(ValueError, match="SQL statements"):
        execute_query_sequence(connection, statements)  # type: ignore[arg-type]


@pytest.mark.parametrize("timeout", [True, 0, -1, 60_001])
def test_timeout_override_cannot_weaken_the_official_upper_bound(
    timeout: object,
) -> None:
    connection = SyntheticConnection({}, [])

    with pytest.raises(ValueError, match="statement_timeout_ms"):
        execute_query_sequence(
            connection,
            "SELECT 1",
            statement_timeout_ms=timeout,  # type: ignore[arg-type]
        )


class CursorCreationFailingConnection(SyntheticConnection):
    def cursor(self):  # type: ignore[no-untyped-def]
        raise ConnectionError("synthetic cursor failure")


def test_cursor_creation_failure_is_sanitized_as_infrastructure() -> None:
    connection = CursorCreationFailingConnection({}, [])

    with pytest.raises(PostgreSQLExecutionError) as captured:
        execute_query_sequence(connection, "SELECT private_value")

    assert captured.value.kind == "infrastructure"
    assert "private_value" not in str(captured.value)


class RollbackFailingConnection(SyntheticConnection):
    def rollback(self) -> None:
        super().rollback()
        raise ConnectionError("synthetic rollback failure")


def test_rollback_failure_is_not_swallowed_and_is_infrastructure_owned() -> None:
    connection = RollbackFailingConnection(
        {"SELECT broken": SyntheticDatabaseError("42601")}, []
    )

    with pytest.raises(PostgreSQLExecutionError) as captured:
        execute_query_sequence(connection, "SELECT broken")

    assert captured.value.kind == "infrastructure"


class SlowCursorConnection(SyntheticConnection):
    def cursor(self):  # type: ignore[no-untyped-def]
        cursor = super().cursor()
        original_execute = cursor.execute

        def execute(sql: str) -> None:
            if sql == "SELECT slow_operation":
                time.sleep(0.03)
            original_execute(sql)

        cursor.execute = execute  # type: ignore[method-assign]
        return cursor


def test_client_wall_clock_cancellation_cannot_be_disabled_by_sql() -> None:
    events: list[tuple[object, ...]] = []
    connection = SlowCursorConnection({"SELECT slow_operation": [(1,)]}, events)

    with pytest.raises(PostgreSQLExecutionError) as captured:
        execute_query_sequence(
            connection,
            "SELECT slow_operation",
            statement_timeout_ms=10,
        )

    assert captured.value.kind == "timeout"
    assert ("cancel_safe",) in events

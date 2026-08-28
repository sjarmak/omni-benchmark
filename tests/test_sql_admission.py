from __future__ import annotations

import pytest

from omni_benchmark.sql_admission import query_sql_is_admissible


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH values_cte AS (SELECT 1 AS value) SELECT value FROM values_cte",
        "SELECT 1; SELECT 2",
        "SELECT * FROM (VALUES (1), (2)) AS values_table(value)",
    ],
)
def test_query_admission_accepts_postgres_query_only_sql(sql: str) -> None:
    assert query_sql_is_admissible(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "",
        "UPDATE accounts SET enabled = false",
        "DELETE FROM accounts",
        "SELECT 1 INTO TEMP TABLE answer",
        "SELECT set_config('default_transaction_read_only', 'off', false)",
        "SELECT pg_notify('channel', 'payload')",
        "SELECT E'unterminated\\",
        'SELECT U&"unsafe" FROM values_table',
    ],
)
def test_query_admission_rejects_non_query_or_unsafe_sql(sql: str) -> None:
    assert not query_sql_is_admissible(sql)


def test_query_admission_accepts_a_sequence_but_rejects_invalid_members() -> None:
    assert query_sql_is_admissible(("SELECT 1", "SELECT 2"))
    assert not query_sql_is_admissible(("SELECT 1", "TRUNCATE values_table"))
    assert not query_sql_is_admissible(())

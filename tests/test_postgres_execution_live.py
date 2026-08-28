"""Opt-in live PostgreSQL oracle for public/synthetic evaluator behavior."""

from __future__ import annotations

import os

import pytest

from omni_benchmark.postgres_execution import (
    MAX_RESULT_ROWS,
    PostgreSQLExecutionError,
    execute_query_sequence,
)
from omni_benchmark.postgres_isolation import (
    PostgreSQLIsolationError,
    PsycopgTemplateIsolationProvider,
)
from omni_benchmark.sealed_scoring import (
    FailureClass,
    ScoringMode,
    SealedQueryCase,
    score_query,
)


LIVE_DSN = os.environ.get("OMNI_BENCHMARK_LIVE_POSTGRES_DSN")
LIVE_EXECUTION_DSN = os.environ.get("OMNI_BENCHMARK_LIVE_POSTGRES_EXECUTION_DSN")
LIVE_TEMPLATE = os.environ.get("OMNI_BENCHMARK_LIVE_TEMPLATE_DATABASE")
LIVE_UNSAFE_EXECUTION_DSN = os.environ.get(
    "OMNI_BENCHMARK_LIVE_POSTGRES_UNSAFE_EXECUTION_DSN"
)
LIVE_UNSAFE_TEMPLATE = os.environ.get(
    "OMNI_BENCHMARK_LIVE_POSTGRES_UNSAFE_TEMPLATE_DATABASE"
)


@pytest.mark.skipif(
    not LIVE_DSN or not LIVE_EXECUTION_DSN or not LIVE_TEMPLATE,
    reason="requires explicit synthetic PostgreSQL oracle configuration",
)
def test_live_timeout_last_result_row_cap_and_clone_reset() -> None:
    assert LIVE_DSN is not None
    assert LIVE_EXECUTION_DSN is not None
    assert LIVE_TEMPLATE is not None
    provider = PsycopgTemplateIsolationProvider(
        LIVE_DSN,
        LIVE_EXECUTION_DSN,
        {"public_oracle": LIVE_TEMPLATE},
    )
    blocked_candidates = (
        "ALTER ROLE scorer PASSWORD 'changed-by-candidate'; SELECT 1",
        "SELECT lo_create(987654)",
        "SELECT set_config('default_transaction_read_only', 'off', false), "
        "lo_create(987655)",
        "SELECT pg_logical_emit_message(false, 'security-review', 'payload')",
        "SELECT pg_try_advisory_lock(42)",
        "SELECT pg_try_advisory_xact_lock(42)",
        'SELECT U&"pg\\005flogical\\005femit\\005fmessage"('
        "false, 'security-review', 'unicode-bypass')",
    )
    for candidate_sql in blocked_candidates:
        result = score_query(
            SealedQueryCase(
                database="public_oracle",
                candidate_sql=candidate_sql,
                gold_sql="SELECT 1",
                conditions={"decimal": -1, "order": False},
            ),
            ScoringMode.SENSITIVITY,
            provider,
        )
        assert result.outcome == "refused_or_error"
        assert result.failure_class is FailureClass.CANDIDATE_DISALLOWED_STATEMENT
    first = provider.acquire("public_oracle")
    try:
        connection = first.connect_scoring()
        try:
            last = execute_query_sequence(connection, "SELECT 1; SELECT 2")
            capped = execute_query_sequence(
                connection, "SELECT generate_series(1, 10001)"
            )
            with pytest.raises(PostgreSQLExecutionError) as read_only_failure:
                execute_query_sequence(
                    connection,
                    "CREATE TABLE sealed_execution_mutation (id integer)",
                    read_only=True,
                )
            assert read_only_failure.value.kind == "statement"
            bypass_payloads = (
                "SET TRANSACTION READ WRITE; "
                "CREATE TABLE read_write_bypass_one (id integer); SELECT 1",
                "COMMIT; SET default_transaction_read_only=off; "
                "BEGIN READ WRITE; "
                "CREATE TABLE read_write_bypass_two (id integer); SELECT 1",
            )
            for payload in bypass_payloads:
                with pytest.raises(PostgreSQLExecutionError) as bypass_failure:
                    execute_query_sequence(connection, payload, read_only=True)
                assert bypass_failure.value.kind == "statement"
            with pytest.raises(PostgreSQLExecutionError) as client_timeout:
                execute_query_sequence(
                    connection,
                    "SELECT set_config('statement_timeout', '0', false), pg_sleep(0.2)",
                    statement_timeout_ms=25,
                    read_only=True,
                )
            assert client_timeout.value.kind == "timeout"
            with pytest.raises(PostgreSQLExecutionError) as captured:
                execute_query_sequence(
                    connection,
                    "SELECT pg_sleep(0.2)",
                    statement_timeout_ms=25,
                )
            assert captured.value.kind == "timeout"
            assert last.rows == ((2,),)
            assert capped.rows is not None
            assert len(capped.rows) == MAX_RESULT_ROWS
            assert capped.row_limit_exceeded
        finally:
            connection.close()

        trusted = first.connect_trusted()
        try:
            execute_query_sequence(
                trusted, "CREATE TABLE sealed_execution_mutation (id integer)"
            )
        finally:
            trusted.close()
    finally:
        first.reset()
        first.release()

    second = provider.acquire("public_oracle")
    try:
        connection = second.connect_scoring()
        try:
            pristine = execute_query_sequence(
                connection, "SELECT to_regclass('public.sealed_execution_mutation')"
            )
            assert pristine.rows == ((None,),)
        finally:
            connection.close()
    finally:
        second.reset()
        second.release()


@pytest.mark.skipif(
    not LIVE_DSN or not LIVE_UNSAFE_EXECUTION_DSN or not LIVE_UNSAFE_TEMPLATE,
    reason="requires explicit unsafe-role PostgreSQL oracle configuration",
)
def test_live_privilege_attestation_rejects_write_capable_execution_role() -> None:
    assert LIVE_DSN is not None
    assert LIVE_UNSAFE_EXECUTION_DSN is not None
    assert LIVE_UNSAFE_TEMPLATE is not None
    provider = PsycopgTemplateIsolationProvider(
        LIVE_DSN,
        LIVE_UNSAFE_EXECUTION_DSN,
        {"unsafe_oracle": LIVE_UNSAFE_TEMPLATE},
    )
    isolate = provider.acquire("unsafe_oracle")
    try:
        with pytest.raises(PostgreSQLIsolationError, match="restricted"):
            isolate.connect_scoring()
    finally:
        isolate.reset()
        isolate.release()

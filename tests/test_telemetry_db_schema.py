from __future__ import annotations

from typing import Any

import psycopg
import pytest

from omni_benchmark.telemetry_db import (
    SCHEMA_NAME,
    TABLE_COLUMNS,
    TABLE_PRIMARY_KEYS,
    TABLE_SPECS,
    SchemaError,
    apply_schema,
    load_schema_sql,
    parse_table_specs,
)

ATTEMPT_KEY = ("attempt_id", "generation_record_sha256")
EXPECTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "load_run": (
        "load_id",
        "started_at",
        "finished_at",
        "source_manifests",
        "row_counts",
        "loader_version",
        "system_commit",
    ),
    "run": (
        "run_id",
        "cohort_id",
        "condition",
        "arm",
        "repetition",
        "scope",
        "partition",
        "model_name",
        "model_provider",
        "model_version",
        "system_commit",
        "semantic_model_ref",
        "semantic_model_sha256",
        "started_at",
        "finished_at",
        "question_count",
        "manifest",
    ),
    "question": (
        "instance_id",
        "database",
        "partition",
        "category",
        "high_level",
        "question",
        "public_fields",
    ),
    "deployment": (
        "deployment_id",
        "database",
        "connection_id",
        "branch_id",
        "branch_name",
        "file_count",
        "failure_stage",
        "failure_detail",
        "file_sha256",
    ),
    "attempt": (
        *ATTEMPT_KEY,
        "run_id",
        "instance_id",
        "database",
        "condition",
        "arm",
        "repetition",
        "partition",
        "started_at",
        "finished_at",
        "latency_ms",
        "model_name",
        "model_provider",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "token_source",
        "cost_usd",
        "cost_source",
        "cost_unavailable_reason",
        "generation_outcome",
        "execution_status",
        "failure_origin",
        "terminal_failure_class",
        "harness_failure",
        "generated_sql",
        "generated_query",
        "query_unavailable_reason",
        "tool_call_count",
        "tool_calls_by_name",
        "database_query_count",
        "retry_count",
        "validation_attempt_count",
        "actual_result_status",
        "actual_result_hash",
        "trace_captured",
        "trace_truncated",
        "trace_degraded_reason",
        "telemetry_unavailable",
        "artifact_dir",
        "generation_record",
    ),
    "score": (
        *ATTEMPT_KEY,
        "scorer",
        "scorer_version",
        "outcome",
        "status",
        "failure_category",
        "score_artifact_sha256",
    ),
    "trace_event": (
        *ATTEMPT_KEY,
        "seq",
        "timestamp",
        "component",
        "event_type",
        "tool_name",
        "status",
        "failure_class",
        "duration_ms",
        "elapsed_ms",
        "input_tokens",
        "output_tokens",
        "model",
        "provider",
        "retry_delta",
        "tool_call_delta",
        "database_query_delta",
        "validation_attempt_delta",
        "metadata_sha256",
    ),
    "action_evidence": (
        *ATTEMPT_KEY,
        "trace_seq",
        "tool_name",
        "retrieval_query",
        "retrieved_public_ids",
        "exploratory_sql",
    ),
    "sealed_aggregate": (
        "run_id",
        "scorer",
        "condition",
        "report",
        "correct",
        "wrong_answer",
        "refused_or_error",
        "mean_accuracy",
        "pass_3_rate",
        "wrong_rate",
        "refused_or_error_rate",
        "error_rate",
        "correctness_flip_rate",
        "scoreable_attempts",
    ),
    "attempt_label": (
        "label_id",
        "attempt_id",
        "generation_record_sha256",
        "taxonomy_version",
        "category",
        "labeler",
        "rationale",
        "created_at",
        "pass_id",
    ),
}
EXPECTED_PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "load_run": ("load_id",),
    "run": ("run_id",),
    "question": ("instance_id",),
    "deployment": ("deployment_id", "database"),
    "attempt": ATTEMPT_KEY,
    "score": (*ATTEMPT_KEY, "scorer"),
    "trace_event": (*ATTEMPT_KEY, "seq"),
    "action_evidence": (*ATTEMPT_KEY, "trace_seq"),
    "sealed_aggregate": ("run_id", "scorer", "condition"),
    "attempt_label": ("label_id",),
}
EXPECTED_INDEXES = {
    "attempt_run_id_idx",
    "attempt_instance_id_idx",
    "attempt_condition_arm_idx",
    "score_scorer_outcome_idx",
    "trace_event_attempt_id_idx",
    "attempt_label_attempt_id_idx",
}
EXPECTED_VIEWS = {"attempt_label_latest", "attempt_scored", "dev_a_frame"}


def test_table_columns_parsed_from_sql_match_the_fixed_contract() -> None:
    assert dict(TABLE_COLUMNS) == EXPECTED_COLUMNS
    assert dict(TABLE_PRIMARY_KEYS) == EXPECTED_PRIMARY_KEYS
    assert list(TABLE_COLUMNS) == list(EXPECTED_COLUMNS)


def test_table_specs_expose_types_and_value_columns() -> None:
    attempt = TABLE_SPECS["attempt"]
    assert attempt.column_types["generation_record"] == "jsonb"
    assert attempt.column_types["cost_usd"] == "numeric"
    assert attempt.column_types["trace_captured"] == "boolean"
    assert attempt.value_columns == EXPECTED_COLUMNS["attempt"][2:]
    with pytest.raises(TypeError):
        attempt.column_types["new"] = "text"  # type: ignore[index]


def test_schema_sql_is_idempotent_and_declares_views_and_indexes() -> None:
    ddl = load_schema_sql()
    assert ddl.count("CREATE SCHEMA IF NOT EXISTS telemetry;") == 1
    assert ddl.count("CREATE TABLE IF NOT EXISTS") == len(EXPECTED_COLUMNS)
    assert "CREATE TABLE " not in ddl.replace("CREATE TABLE IF NOT EXISTS", "")
    for view in EXPECTED_VIEWS:
        assert f"CREATE OR REPLACE VIEW telemetry.{view} AS" in ddl
    for index in EXPECTED_INDEXES:
        assert f"CREATE INDEX IF NOT EXISTS {index}\n" in ddl
    assert "'official_soft_ex'" in ddl and "'sensitivity'" in ddl


def test_parse_table_specs_reads_a_minimal_table() -> None:
    specs = parse_table_specs(
        "CREATE TABLE IF NOT EXISTS telemetry.t (\n"
        "    a text NOT NULL,\n"
        "    b jsonb,\n"
        "    PRIMARY KEY (a)\n"
        ");\n"
    )
    assert list(specs) == ["t"]
    assert specs["t"].columns == ("a", "b")
    assert specs["t"].primary_key == ("a",)
    assert dict(specs["t"].column_types) == {"a": "text", "b": "jsonb"}
    with pytest.raises(TypeError):
        specs["u"] = specs["t"]  # type: ignore[index]


@pytest.mark.parametrize(
    ("ddl", "message"),
    [
        ("SELECT 1;\n", "declares no tables"),
        (
            "CREATE TABLE IF NOT EXISTS telemetry.t (\n    a text\n);\n",
            "no primary key",
        ),
        (
            "CREATE TABLE IF NOT EXISTS telemetry.t (\n"
            "    a text,\n    a int,\n    PRIMARY KEY (a)\n);\n",
            "column a twice",
        ),
        (
            "CREATE TABLE IF NOT EXISTS telemetry.t (\n"
            "    a text,\n    PRIMARY KEY (a),\n    PRIMARY KEY (a)\n);\n",
            "two primary keys",
        ),
        (
            "CREATE TABLE IF NOT EXISTS telemetry.t (\n"
            "    a text,\n    PRIMARY KEY (b)\n);\n",
            r"unknown columns \['b'\]",
        ),
        (
            "CREATE TABLE IF NOT EXISTS telemetry.t (\n"
            "    a text REFERENCES other,\n    PRIMARY KEY (a)\n);\n",
            "unparseable line",
        ),
        (
            "CREATE TABLE IF NOT EXISTS telemetry.t (\n    a text,\n"
            "    PRIMARY KEY (a)\n);\n"
            "CREATE TABLE IF NOT EXISTS telemetry.t (\n    a text,\n"
            "    PRIMARY KEY (a)\n);\n",
            "declared twice",
        ),
    ],
)
def test_parse_table_specs_rejects_layout_drift(ddl: str, message: str) -> None:
    with pytest.raises(SchemaError, match=message):
        parse_table_specs(ddl)


class _RecordingCursor:
    def __init__(self, executed: list[str]) -> None:
        self.executed = executed

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.executed.append(statement)


class _RecordingConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self.executed)


def test_apply_schema_executes_the_shipped_ddl_once() -> None:
    conn = _RecordingConnection()
    apply_schema(conn)
    assert conn.executed == [load_schema_sql()]


def _ordered_columns(conn: psycopg.Connection[Any], table: str) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (SCHEMA_NAME, table),
    ).fetchall()
    return tuple(row[0] for row in rows)


def _primary_key(conn: psycopg.Connection[Any], table: str) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT kcu.column_name FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "ON kcu.constraint_name = tc.constraint_name "
        "AND kcu.table_schema = tc.table_schema "
        "WHERE tc.table_schema = %s AND tc.table_name = %s "
        "AND tc.constraint_type = 'PRIMARY KEY' ORDER BY kcu.ordinal_position",
        (SCHEMA_NAME, table),
    ).fetchall()
    return tuple(row[0] for row in rows)


def test_apply_schema_matches_parsed_layout_and_is_reapplicable(
    throwaway_database: str,
) -> None:
    with psycopg.connect(throwaway_database) as conn:
        apply_schema(conn)
        conn.commit()
        apply_schema(conn)
        conn.commit()
        for table, columns in TABLE_COLUMNS.items():
            assert _ordered_columns(conn, table) == columns, table
            assert _primary_key(conn, table) == TABLE_PRIMARY_KEYS[table], table
        views = conn.execute(
            "SELECT table_name FROM information_schema.views WHERE table_schema = %s",
            (SCHEMA_NAME,),
        ).fetchall()
        assert {row[0] for row in views} == EXPECTED_VIEWS
        indexes = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = %s", (SCHEMA_NAME,)
        ).fetchall()
        assert EXPECTED_INDEXES <= {row[0] for row in indexes}
        scored = _ordered_columns(conn, "attempt_scored")
        assert scored[: len(TABLE_COLUMNS["attempt"])] == TABLE_COLUMNS["attempt"]
        assert {"official_outcome", "sensitivity_outcome", "run_cohort_id"} <= set(
            scored
        )

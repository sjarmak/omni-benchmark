from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from omni_benchmark.telemetry_db import (
    TABLE_SPECS,
    Row,
    RowError,
    TableSpec,
    adapt_parameters,
    apply_schema,
    build_upsert_statement,
    upsert_rows,
)

SHA = "a" * 64
STARTED = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _score_row(outcome: str = "correct") -> Row:
    return Row(
        "score",
        {
            "attempt_id": "att-1",
            "generation_record_sha256": SHA,
            "scorer": "official_soft_ex",
            "outcome": outcome,
        },
    )


def test_row_to_tuple_follows_schema_column_order_with_nulls() -> None:
    row = _score_row()
    assert row.to_tuple() == (
        "att-1",
        SHA,
        "official_soft_ex",
        None,
        "correct",
        None,
        None,
        None,
    )
    assert row.spec is TABLE_SPECS["score"]


def test_row_values_are_immutable() -> None:
    source = {"instance_id": "q1", "database": "db"}
    row = Row("question", source)
    source["database"] = "other"
    assert row.values["database"] == "db"
    assert isinstance(row.values, MappingProxyType)
    with pytest.raises(TypeError):
        row.values["database"] = "x"  # type: ignore[index]
    with pytest.raises(AttributeError):
        row.table = "attempt"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("table", "values", "message"),
    [
        ("nope", {"x": 1}, "unknown telemetry table 'nope'"),
        ("question", {"instance_id": "q", "gold": 1}, r"unknown columns \['gold'\]"),
        (
            "score",
            {"attempt_id": "a", "scorer": "s"},
            r"null \['generation_record_sha256'\]",
        ),
        (
            "score",
            {"attempt_id": "a", "scorer": None, "generation_record_sha256": SHA},
            r"null \['scorer'\]",
        ),
    ],
)
def test_row_rejects_unbound_or_keyless_values(
    table: str, values: dict[str, Any], message: str
) -> None:
    with pytest.raises(RowError, match=message):
        Row(table, values)


def test_build_upsert_statement_updates_every_non_key_column() -> None:
    statement = build_upsert_statement(TABLE_SPECS["deployment"]).as_string()
    assert statement.startswith(
        'INSERT INTO "telemetry"."deployment" ("deployment_id", "database", '
    )
    assert 'ON CONFLICT ("deployment_id", "database") DO UPDATE SET' in statement
    assert '"file_sha256" = EXCLUDED."file_sha256"' in statement
    assert '"deployment_id" = EXCLUDED' not in statement
    assert statement.count("%s") == len(TABLE_SPECS["deployment"].columns)


def test_build_upsert_statement_for_key_only_table_does_nothing_on_conflict() -> None:
    spec = TableSpec(
        name="pair",
        columns=("a", "b"),
        column_types=MappingProxyType({"a": "text", "b": "int"}),
        primary_key=("a", "b"),
    )
    statement = build_upsert_statement(spec).as_string()
    assert statement.endswith('ON CONFLICT ("a", "b") DO NOTHING')


def test_adapt_parameters_wraps_only_json_columns() -> None:
    row = Row(
        "question",
        {"instance_id": "q1", "public_fields": {"k": [1, 2]}, "question": "why"},
    )
    adapted = adapt_parameters(TABLE_SPECS["question"], row)
    assert adapted[:2] == ("q1", None)
    assert adapted[5] == "why"
    assert isinstance(adapted[6], Jsonb)
    assert adapted[6].obj == {"k": [1, 2]}
    assert (
        adapt_parameters(
            TABLE_SPECS["question"], Row("question", {"instance_id": "q"})
        )[6]
        is None
    )


class _FakeCursor:
    def __init__(self, calls: list[tuple[Any, list[Any]]]) -> None:
        self.calls = calls

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def executemany(self, statement: Any, params: list[Any]) -> None:
        self.calls.append((statement, list(params)))


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, list[Any]]] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.calls)


def test_upsert_rows_batches_with_executemany() -> None:
    conn = _FakeConnection()
    rows = [
        Row("attempt_label", {"label_id": f"l{i}", "category": "c"}) for i in range(5)
    ]
    assert upsert_rows(conn, "attempt_label", iter(rows), batch_size=2) == 5
    assert [len(params) for _, params in conn.calls] == [2, 2, 1]
    statements = {statement.as_string() for statement, _ in conn.calls}
    assert statements == {
        build_upsert_statement(TABLE_SPECS["attempt_label"]).as_string()
    }
    assert conn.calls[0][1][0] == ("l0", None, None, None, "c", None, None, None, None)


def test_upsert_rows_with_nothing_to_write_touches_nothing() -> None:
    conn = _FakeConnection()
    assert upsert_rows(conn, "score", []) == 0
    assert conn.calls == []


@pytest.mark.parametrize(
    ("table", "rows", "kwargs", "message"),
    [
        ("missing", [], {}, "unknown telemetry table 'missing'"),
        ("score", [], {"batch_size": 0}, "batch_size must be at least 1"),
        (
            "attempt",
            [_score_row()],
            {},
            "row bound to 'score' cannot load into 'attempt'",
        ),
    ],
)
def test_upsert_rows_rejects_bad_targets(
    table: str, rows: list[Row], kwargs: dict[str, Any], message: str
) -> None:
    conn = _FakeConnection()
    with pytest.raises(RowError, match=message):
        upsert_rows(conn, table, rows, **kwargs)
    assert conn.calls == []


def _attempt_row(instance_id: str, tokens: int) -> Row:
    return Row(
        "attempt",
        {
            "attempt_id": f"att-{instance_id}",
            "generation_record_sha256": SHA,
            "run_id": "run-1",
            "instance_id": instance_id,
            "partition": "dev-A",
            "started_at": STARTED,
            "input_tokens": tokens,
            "cost_usd": Decimal("0.123456"),
            "trace_captured": True,
            "tool_calls_by_name": {"sql": 2},
            "generation_record": {"generation_outcome": "completed", "n": tokens},
        },
    )


def test_upsert_rows_round_trips_and_is_idempotent(throwaway_database: str) -> None:
    with psycopg.connect(throwaway_database) as conn:
        apply_schema(conn)
        upsert_rows(conn, "run", [Row("run", {"run_id": "run-1", "cohort_id": "c"})])
        first = [_attempt_row("q1", 10), _attempt_row("q2", 20)]
        assert upsert_rows(conn, "attempt", first, batch_size=1) == 2
        assert upsert_rows(conn, "attempt", first) == 2
        assert upsert_rows(conn, "attempt", [_attempt_row("q2", 99)]) == 1
        upsert_rows(conn, "score", [_score_row("wrong_answer"), _score_row("correct")])
        conn.commit()
        count, tokens = conn.execute(
            "SELECT count(*), sum(input_tokens) FROM telemetry.attempt"
        ).fetchone()
        assert (count, tokens) == (2, 109)
        stored = conn.execute(
            "SELECT started_at, cost_usd, trace_captured, tool_calls_by_name, "
            "generation_record, partition FROM telemetry.attempt "
            "WHERE attempt_id = 'att-q2'"
        ).fetchone()
        assert stored == (
            STARTED,
            Decimal("0.123456"),
            True,
            {"sql": 2},
            {"generation_outcome": "completed", "n": 99},
            "dev-A",
        )
        scored = conn.execute(
            "SELECT official_outcome, sensitivity_outcome, run_cohort_id "
            "FROM telemetry.attempt_scored WHERE attempt_id = 'att-1'"
        ).fetchall()
        assert scored == []
        assert conn.execute(
            "SELECT outcome FROM telemetry.score WHERE attempt_id = 'att-1'"
        ).fetchall() == [("correct",)]


def _label_rows() -> list[Row]:
    common = {"attempt_id": "att-1", "generation_record_sha256": SHA}
    return [
        Row(
            "attempt_label",
            {
                **common,
                "label_id": label_id,
                "taxonomy_version": "v1",
                "labeler": labeler,
                "category": category,
                "created_at": created,
            },
        )
        for label_id, labeler, category, created in [
            ("l1", "human", "old", STARTED),
            ("l2", "human", "new", STARTED.replace(hour=13)),
            ("l3", "model", "model-view", STARTED),
        ]
    ]


def _score_rows() -> list[Row]:
    return [
        Row(
            "score",
            {
                "attempt_id": "att-q1",
                "generation_record_sha256": SHA,
                "scorer": scorer,
                "outcome": outcome,
            },
        )
        for scorer, outcome in (
            ("official_soft_ex", "correct"),
            ("sensitivity", "wrong_answer"),
        )
    ]


def _assert_attempt_label_latest_rows(conn: psycopg.Connection) -> None:
    latest = conn.execute(
        "SELECT labeler, category FROM telemetry.attempt_label_latest ORDER BY labeler"
    ).fetchall()
    assert latest == [("human", "new"), ("model", "model-view")]


def _assert_attempt_scored_rows(conn: psycopg.Connection) -> None:
    scored = conn.execute(
        "SELECT official_outcome, sensitivity_outcome FROM telemetry.attempt_scored"
    ).fetchall()
    assert scored == [("correct", "wrong_answer")]


def test_attempt_label_latest_view_keeps_the_newest_label(
    throwaway_database: str,
) -> None:
    with psycopg.connect(throwaway_database) as conn:
        apply_schema(conn)
        upsert_rows(conn, "attempt", [_attempt_row("q1", 1)])
        upsert_rows(conn, "attempt_label", _label_rows())
        upsert_rows(conn, "score", _score_rows())
        conn.commit()
        _assert_attempt_label_latest_rows(conn)
        _assert_attempt_scored_rows(conn)

"""Generation record parsing, scalar coercions, and per-attempt row builders."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.telemetry_db import CustodyViolation, ReaderError
from omni_benchmark.telemetry_db.generation_rows import (
    GenerationRecord,
    action_evidence_rows,
    as_boolean,
    as_decimal,
    as_float,
    as_integer,
    as_text,
    instance_of_attempt_id,
    parse_timestamp,
    read_generation_records,
    trace_event_rows,
)
from omni_benchmark.telemetry_db.sources import collapse

from .telemetry_db_helpers import _dump_json, _dump_jsonl, generation_record


def test_generation_record_validation(tmp_path: Path) -> None:
    path = tmp_path / "generation.jsonl"
    good = generation_record("run", "alpha_large_Q1", "C1")
    _dump_jsonl(path, [good, {**good, "attempt_id": "run:alpha_large_Q1:C1:2"}])
    with pytest.raises(ReaderError, match="disagrees"):
        read_generation_records(path)
    _dump_jsonl(path, [{**good, "attempt_id": "run:x"}])
    with pytest.raises(ReaderError, match="four"):
        read_generation_records(path)
    _dump_jsonl(path, [{**good, "repetition": "1"}])
    with pytest.raises(ReaderError, match="repetition"):
        read_generation_records(path)
    _dump_jsonl(path, [{**good, "run_id": ""}])
    with pytest.raises(ReaderError, match="run_id"):
        read_generation_records(path)
    _dump_jsonl(path, [{**good, "gold_sql": "SELECT"}])
    with pytest.raises(CustodyViolation, match="gold_sql"):
        read_generation_records(path)
    path.write_text("[]\n\n", encoding="utf-8")
    with pytest.raises(ReaderError, match="not an object"):
        read_generation_records(path)
    path.write_text("{\n", encoding="utf-8")
    with pytest.raises(ReaderError, match="invalid JSON"):
        read_generation_records(path)
    _dump_jsonl(path, [good])
    (record,) = read_generation_records(path)
    assert record.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert record.context == f"{path}:1"


def test_scalar_coercions() -> None:
    assert parse_timestamp(None, "c") is None
    assert (
        parse_timestamp("2026-01-01T00:00:00+02:00", "c").utcoffset().total_seconds()
        == 7200
    )
    for value, match in (
        (5, "must be text"),
        ("2026-01-01T00:00:00", "no offset"),
        ("nope", "invalid timestamp"),
    ):
        with pytest.raises(ReaderError, match=match):
            parse_timestamp(value, "c")
    assert (
        as_integer(2.0, "c") == 2
        and as_integer(3, "c") == 3
        and as_integer(None, "c") is None
    )
    for value, match in (
        (True, "boolean"),
        (2.5, "expected an integer, got 2.5"),
        (float("inf"), "expected an integer"),
        ("4", "expected an integer"),
    ):
        with pytest.raises(ReaderError, match=match):
            as_integer(value, "c")
    assert as_float(2.5, "c") == 2.5 and as_float(3, "c") == 3.0
    assert as_float(None, "c") is None
    for value, match in (
        (False, "expected a number, got False"),
        ("2.5", "expected a number"),
        (float("nan"), "expected a finite number"),
    ):
        with pytest.raises(ReaderError, match=match):
            as_float(value, "c")
    assert as_decimal("1.5", "c") == Decimal("1.5") and as_decimal(None, "c") is None
    with pytest.raises(ReaderError, match="numeric"):
        as_decimal(False, "c")
    with pytest.raises(ReaderError, match="invalid numeric"):
        as_decimal("abc", "c")
    assert as_text(None, "c") is None and as_boolean(None, "c") is None
    with pytest.raises(ReaderError, match="expected text"):
        as_text(1, "c")
    with pytest.raises(ReaderError, match="expected a boolean"):
        as_boolean("true", "c")
    with pytest.raises(ReaderError, match="malformed"):
        instance_of_attempt_id("a:b", "c")
    assert collapse([1, 1]) == (1, ())
    assert collapse([{"a": 2}, {"a": 1}]) == (None, ({"a": 1}, {"a": 2}))


def _generation(tmp_path: Path, **overrides: Any) -> GenerationRecord:
    path = tmp_path / "generation.jsonl"
    _dump_jsonl(path, [generation_record("run", "alpha_large_Q1", "C1", **overrides)])
    (record,) = read_generation_records(path)
    return record


def test_attempt_row_rejects_non_object_model(tmp_path: Path) -> None:
    from omni_benchmark.telemetry_db.generation_rows import attempt_row

    generation = _generation(tmp_path, model="claude")
    with pytest.raises(ReaderError, match="model: expected an object"):
        attempt_row(
            generation,
            arm="C1",
            database="alpha_large",
            partition="dev-a",
            artifact_dir="d",
        )
    generation = _generation(tmp_path, latency_ms="5000")
    with pytest.raises(ReaderError, match="latency_ms: expected a number"):
        attempt_row(
            generation,
            arm="C1",
            database="alpha_large",
            partition="dev-a",
            artifact_dir="d",
        )


@pytest.mark.parametrize(
    ("events", "error", "match"),
    [
        (
            [{"seq": 1}, {"seq": 0, "status": "ok"}, {"seq": 1}],
            ReaderError,
            "duplicate trace seq",
        ),
        ([{"seq": "1"}], ReaderError, "seq must be an integer"),
        ("[1]\n", ReaderError, "trace event is not an object"),
        ("{bad\n", ReaderError, "invalid JSON"),
        ([{"seq": 2, "expected_result": 1}], CustodyViolation, "expected_result"),
    ],
)
def test_trace_event_validation(
    tmp_path: Path, events: Any, error: type[Exception], match: str
) -> None:
    generation = _generation(tmp_path)
    trace = tmp_path / "attempt.trace.jsonl"
    if isinstance(events, str):
        trace.write_text(events, encoding="utf-8")
    else:
        _dump_jsonl(trace, events)
    with pytest.raises(error, match=match):
        trace_event_rows(trace, generation)


def test_trace_event_rows_sort_by_seq_and_ignore_blank_lines(tmp_path: Path) -> None:
    generation = _generation(tmp_path)
    trace = tmp_path / "attempt.trace.jsonl"
    _dump_jsonl(trace, [{"seq": 2}, {"seq": 0}])
    trace.write_text(trace.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    rows = trace_event_rows(trace, generation)
    assert [row.values["seq"] for row in rows] == [0, 2]


def test_action_evidence_validation(tmp_path: Path) -> None:
    generation = _generation(tmp_path)
    evidence = tmp_path / "attempt.action-evidence.json"
    for payload, match in (
        ({"kind": "other", "records": []}, "kind is not"),
        ({"kind": "direct-action-evidence", "records": {}}, "records must be a list"),
        ({"kind": "direct-action-evidence", "records": [1]}, "expected an object"),
        (
            {"kind": "direct-action-evidence", "records": [{"trace_seq": None}]},
            "trace_seq must be",
        ),
        (
            {
                "kind": "direct-action-evidence",
                "records": [{"trace_seq": 1}, {"trace_seq": 1}],
            },
            "duplicate trace_seq",
        ),
        (
            {
                "kind": "direct-action-evidence",
                "records": [{"trace_seq": 1, "retrieved_public_ids": "x"}],
            },
            "must be a list",
        ),
    ):
        _dump_json(evidence, payload)
        with pytest.raises(ReaderError, match=match):
            action_evidence_rows(evidence, generation)
    _dump_json(
        evidence,
        {
            "kind": "direct-action-evidence",
            "records": [{"trace_seq": 1, "test_cases": []}],
        },
    )
    with pytest.raises(CustodyViolation, match="test_cases"):
        action_evidence_rows(evidence, generation)
    _dump_json(
        evidence,
        {
            "kind": "direct-action-evidence",
            "records": [{"trace_seq": 3}, {"trace_seq": 1}],
        },
    )
    assert [
        row.values["trace_seq"] for row in action_evidence_rows(evidence, generation)
    ] == [1, 3]

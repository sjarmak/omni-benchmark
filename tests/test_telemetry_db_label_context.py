"""Public evidence packaged for a failure-labeling pass."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest

from omni_benchmark.telemetry_db import Row, SplitIds, apply_schema, upsert_rows
from omni_benchmark.telemetry_db.custody import CustodyViolation
from omni_benchmark.telemetry_db.label_context import (
    SAMPLE_LIMIT,
    Cohort,
    LabelContextError,
    context_rows,
    render_prompt,
)

SHA = "b" * 64
SPLIT = SplitIds(dev_a=frozenset({"alpha_Q1", "alpha_Q2"}), test=frozenset({"z_T9"}))


def _attempt(attempt_id: str, **values: Any) -> Row:
    return Row(
        "attempt",
        {
            "attempt_id": attempt_id,
            "generation_record_sha256": SHA,
            "partition": "dev-a",
            "database": "alpha",
            "condition": "C4",
            **values,
        },
    )


@pytest.fixture
def seeded(throwaway_database: str) -> str:
    attempts = [
        _attempt(
            "a1",
            instance_id="alpha_Q1",
            arm="C4",
            generation_outcome="errored",
            terminal_failure_class="unsupported_semantic_result_type",
            generated_query='{"userEditedSQL": "SELECT ${t.m} FROM ${t}"}',
            tool_call_count=7,
            tool_calls_by_name={"run_query": 5, "search": 2},
            database_query_count=4,
            retry_count=1,
            validation_attempt_count=2,
            latency_ms=41000.0,
        ),
        _attempt(
            "a2",
            instance_id="alpha_Q2",
            arm="C4",
            generation_outcome="answered",
            execution_status="complete",
            generated_sql="SELECT 1",
            tool_call_count=3,
            latency_ms=22000.0,
        ),
        _attempt(
            "a3",
            instance_id="alpha_Q1",
            arm="C1",
            generation_outcome="answered",
            execution_status="complete",
            tool_call_count=2,
            latency_ms=9000.0,
        ),
        _attempt("a9", instance_id="z_T9", arm="C4", partition="test"),
    ]
    scores = [
        Row(
            "score",
            {
                "attempt_id": attempt_id,
                "generation_record_sha256": SHA,
                "scorer": "official_soft_ex",
                "outcome": outcome,
                "status": "scored",
                "failure_category": category,
            },
        )
        for attempt_id, outcome, category in (
            ("a1", "refused_or_error", "candidate_execution_error"),
            ("a2", "wrong_answer", None),
            ("a3", "correct", None),
        )
    ]
    questions = [
        Row(
            "question",
            {
                "instance_id": instance,
                "database": "alpha",
                "partition": "dev-a",
                "category": "Query",
                "high_level": False,
                "question": text,
            },
        )
        for instance, text in (
            ("alpha_Q1", "Which region grew fastest last quarter?"),
            ("alpha_Q2", "How many active accounts are there?"),
        )
    ]
    traces = [
        Row(
            "trace_event",
            {
                "attempt_id": "a1",
                "generation_record_sha256": SHA,
                "seq": seq,
                "component": "agent",
                "event_type": "tool_call",
                "tool_name": tool,
                "status": status,
                "failure_class": failure,
            },
        )
        for seq, tool, status, failure in (
            (0, "search_topics", "ok", None),
            (1, "run_query", "error", "unsupported_semantic_result_type"),
        )
    ]
    evidence = [
        Row(
            "action_evidence",
            {
                "attempt_id": "a1",
                "generation_record_sha256": SHA,
                "trace_seq": 0,
                "tool_name": "search_topics",
                "retrieval_query": "regional growth",
                "retrieved_public_ids": ["alpha.region"],
            },
        )
    ]
    with psycopg.connect(throwaway_database) as conn:
        apply_schema(conn)
        upsert_rows(conn, "attempt", attempts)
        upsert_rows(conn, "score", scores)
        upsert_rows(conn, "question", questions)
        upsert_rows(conn, "trace_event", traces)
        upsert_rows(conn, "action_evidence", evidence)
        conn.commit()
    return throwaway_database


def test_cohort_selects_by_arm_outcome_and_failure_class(seeded: str) -> None:
    cohort = Cohort(
        arms=("C4",),
        outcomes=("refused_or_error",),
        terminal_failure_classes=("unsupported_semantic_result_type",),
    )
    with psycopg.connect(seeded) as conn:
        rows = context_rows(conn, cohort, SPLIT)
    assert [row["attempt_id"] for row in rows] == ["a1"]
    row = rows[0]
    assert row["question"] == "Which region grew fastest last quarter?"
    assert row["official_outcome"] == "refused_or_error"
    assert row["terminal_failure_class"] == "unsupported_semantic_result_type"
    assert row["tool_calls_by_name"] == {"run_query": 5, "search": 2}
    assert row["failing_trace_events"] == [
        {
            "seq": 1,
            "tool_name": "run_query",
            "status": "error",
            "failure_class": "unsupported_semantic_result_type",
        }
    ]
    assert row["retrieval_query_sample"] == ["regional growth"]
    assert row["retrieved_public_id_sample"] == ["alpha.region"]
    assert row["retrieved_public_id_count"] == 1


def test_repeated_evidence_is_deduplicated_and_bounded(seeded: str) -> None:
    """A long retrieval trace is sampled, and the full count stays visible."""
    identifiers = [f"alpha.t{index}" for index in range(SAMPLE_LIMIT + 12)]
    rows = [
        Row(
            "action_evidence",
            {
                "attempt_id": "a1",
                "generation_record_sha256": SHA,
                "trace_seq": seq,
                "tool_name": "search_topics",
                "retrieval_query": "regional growth",
                "retrieved_public_ids": identifiers,
            },
        )
        for seq in (5, 6)
    ]
    with psycopg.connect(seeded) as conn:
        upsert_rows(conn, "action_evidence", rows)
        conn.commit()
        context = context_rows(
            conn, Cohort(arms=("C4",), outcomes=("refused_or_error",)), SPLIT
        )[0]
    assert context["retrieved_public_id_count"] == len(identifiers) + 1
    assert len(context["retrieved_public_id_sample"]) == SAMPLE_LIMIT
    assert context["retrieval_query_sample"] == ["regional growth"]
    assert context["retrieval_query_count"] == 1


def test_cohort_widens_to_wrong_answers_without_a_failure_class(seeded: str) -> None:
    cohort = Cohort(arms=("C4",), outcomes=("wrong_answer",))
    with psycopg.connect(seeded) as conn:
        rows = context_rows(conn, cohort, SPLIT)
    assert [row["attempt_id"] for row in rows] == ["a2"]
    assert rows[0]["failing_trace_events"] == []
    assert rows[0]["generated_sql"] == "SELECT 1"


def test_limit_bounds_the_cohort_deterministically(seeded: str) -> None:
    cohort = Cohort(arms=("C1", "C4"), outcomes=("correct", "wrong_answer"), limit=1)
    with psycopg.connect(seeded) as conn:
        rows = context_rows(conn, cohort, SPLIT)
    assert [row["attempt_id"] for row in rows] == ["a2"]


def test_a_non_dev_a_instance_is_refused(seeded: str) -> None:
    cohort = Cohort(arms=("C4",), outcomes=("refused_or_error",))
    empty = SplitIds(dev_a=frozenset(), test=SPLIT.test)
    with psycopg.connect(seeded) as conn:
        with pytest.raises(CustodyViolation):
            context_rows(conn, cohort, empty)


def test_an_empty_cohort_is_an_error(seeded: str) -> None:
    with pytest.raises(LabelContextError):
        Cohort(arms=(), outcomes=("correct",))


def test_render_prompt_names_every_taxonomy_code_and_the_evidence(seeded: str) -> None:
    cohort = Cohort(arms=("C4",), outcomes=("refused_or_error",))
    with psycopg.connect(seeded) as conn:
        rows = context_rows(conn, cohort, SPLIT)
    prompt = render_prompt(rows[0])
    assert "unsupported_semantic_result_type" in prompt
    assert "Which region grew fastest last quarter?" in prompt
    assert "semantic_compilation" in prompt and "scorer_data_ambiguity" in prompt
    assert "gold" not in prompt.lower()


def test_prompt_cli_writes_deterministic_batches(
    seeded: str, tmp_path: Any, monkeypatch: Any, capsys: Any
) -> None:
    """The CLI batches the cohort, writes each prompt, and records a manifest."""
    import importlib.util

    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "dev_a_ids.txt").write_text("alpha_Q1\nalpha_Q2\n", encoding="utf-8")
    (manifests / "test_ids.txt").write_text("z_T9\n", encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "build_label_prompts", "scripts/build_label_prompts.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("TEST_TELEMETRY_DSN", seeded)
    out = tmp_path / "prompts"
    code = module.main(
        [
            "--out-dir",
            str(out),
            "--manifests-dir",
            str(manifests),
            "--dsn-env",
            "TEST_TELEMETRY_DSN",
            "--arm",
            "C4",
            "--batch-size",
            "1",
        ]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["attempts"] == 2 and summary["batches"] == 2
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["attempts"][0]["attempt_id"] for entry in manifest] == ["a2", "a1"]
    assert "Which region grew fastest last quarter?" in (
        out / "batch-001.txt"
    ).read_text(encoding="utf-8")

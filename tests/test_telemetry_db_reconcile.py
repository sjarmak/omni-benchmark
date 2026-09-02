"""Reconciliation of the telemetry database against frozen aggregates.

Unit tests cover the shared arithmetic and the leaf comparison; the database
tests load a tiny synthetic dataset through ``upsert_rows`` and assert both a
passing reconciliation and a failing one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psycopg
import pytest

from omni_benchmark.telemetry_db import Row, apply_schema, upsert_rows
from omni_benchmark.telemetry_db import reconcile_observed as observed
from omni_benchmark.telemetry_db.reconcile import (
    ARTIFACT_PATHS,
    SEALED_SCORE_DIR,
    SEALED_SCORERS,
    FrozenArtifacts,
    ReconcileError,
    Reconciliation,
    build_checks,
    compare_scalar,
    flatten,
    load_frozen_artifacts,
    reconcile,
    render_table,
    write_report,
)
from omni_benchmark.telemetry_db.reconcile_stats import (
    ReconcileStatsError,
    cost_summary,
    median_coverage,
    percent,
    tukey_distribution,
)
from omni_benchmark.telemetry_db.sealed_readers import SEALED_RUN_ID

SHA = "a" * 64
ARMS = observed.FRAME_ARMS
#: (arm, instance) -> (official outcome, sensitivity outcome); None = unscorable.
VERDICTS: dict[tuple[str, str], tuple[str | None, str | None]] = {
    ("C1", "q1"): ("correct", "correct"),
    ("C1", "q2"): ("wrong_answer", "wrong_answer"),
    ("C1", "q3"): ("correct", "correct"),
    ("C2", "q1"): ("correct", "correct"),
    ("C2", "q2"): ("correct", "wrong_answer"),
    ("C2", "q3"): ("wrong_answer", "wrong_answer"),
    ("C3", "q1"): ("wrong_answer", "wrong_answer"),
    ("C3", "q2"): ("refused_or_error", "refused_or_error"),
    ("C3", "q3"): ("correct", "correct"),
    ("C4", "q1"): ("correct", "correct"),
    ("C4", "q2"): ("wrong_answer", "wrong_answer"),
    ("C4", "q3"): (None, "wrong_answer"),
    ("C5", "q1"): ("refused_or_error", "refused_or_error"),
    ("C5", "q2"): ("refused_or_error", "wrong_answer"),
    ("C5", "q3"): ("correct", "correct"),
}
LATENCY = {"q1": 1000.0, "q2": 3000.0, "q3": 5000.0}
TOKENS = {"q1": (100, 10), "q2": (300, 30), "q3": (500, 50)}
COST = {"q1": 0.5, "q2": 1.5, "q3": 2.5}


def _attempt(attempt_id: str, **values: Any) -> Row:
    return Row(
        "attempt",
        {"attempt_id": attempt_id, "generation_record_sha256": SHA, **values},
    )


def _dev_a_rows() -> tuple[list[Row], list[Row]]:
    attempts: list[Row] = []
    scores: list[Row] = []
    for (arm, instance), (official, sensitivity) in VERDICTS.items():
        attempt_id = f"{arm}-{instance}"
        tokens = TOKENS[instance]
        attempts.append(
            _attempt(
                attempt_id,
                run_id=f"run-{arm}",
                instance_id=instance,
                arm=arm,
                condition="C4" if arm == "C5" else arm,
                repetition=1,
                partition="dev-a",
                generation_outcome="answered" if official else "errored",
                latency_ms=LATENCY[instance],
                input_tokens=tokens[0],
                output_tokens=tokens[1],
                total_tokens=sum(tokens),
                cost_usd=None if arm in ("C4", "C5") else COST[instance],
            )
        )
        for scorer, outcome in (
            ("official_soft_ex", official),
            ("sensitivity", sensitivity),
        ):
            scores.append(
                Row(
                    "score",
                    {
                        "attempt_id": attempt_id,
                        "generation_record_sha256": SHA,
                        "scorer": scorer,
                        "outcome": outcome,
                        "status": "scored" if outcome else "unscorable",
                    },
                )
            )
    return attempts, scores


SEALED_COMMON: dict[str, Any] = {
    "partition": "test",
    "token_source": "provider_reported",
    "model_name": "claude-opus-5",
    "model_provider": "anthropic_claude_code_oauth",
    "generation_record": {"model": {"version": "v1"}},
    "cost_source": "provider_reported",
    "telemetry_unavailable": [],
    "repetition": 1,
}
#: (attempt_id, resource unit, per-attempt overrides); the unit scales the telemetry.
SEALED_ATTEMPTS: tuple[tuple[str, int, dict[str, Any]], ...] = (
    ("s1", 1, {"condition": "C1", "generation_outcome": "answered"}),
    (
        "s2",
        3,
        {
            "condition": "C1",
            "generation_outcome": "errored",
            "failure_origin": "evaluated_system",
            "terminal_failure_class": "model_budget_error",
            "database_query_count": 0,
            "telemetry_unavailable": ["retry_count"],
        },
    ),
    (
        "s3",
        2,
        {
            "condition": "C1",
            "repetition": 2,
            "generation_outcome": "refused",
            "failure_origin": "evaluated_system",
            "terminal_failure_class": "no_answer_insufficient_context",
        },
    ),
    (
        "s4",
        4,
        {
            "condition": "C4",
            "generation_outcome": "answered",
            "model_name": "m",
            "model_provider": "bedrock",
            "generation_record": {"model": {"version": None}},
            "database_query_count": None,
            "cost_usd": None,
            "cost_source": "unavailable",
            "telemetry_unavailable": ["database_query_count", "model_version"],
        },
    ),
)


def _sealed_attempt(attempt_id: str, unit: int, overrides: dict[str, Any]) -> Row:
    scaled = {
        "latency_ms": 1000.0 * unit,
        "input_tokens": 100 * unit,
        "output_tokens": 10 * unit,
        "total_tokens": 110 * unit,
        "tool_call_count": unit,
        "database_query_count": unit,
        "cost_usd": 0.25 * unit,
    }
    return _attempt(attempt_id, **{**SEALED_COMMON, **scaled, **overrides})


def _sealed_rows() -> list[Row]:
    return [_sealed_attempt(*entry) for entry in SEALED_ATTEMPTS]


def _governed_rows() -> list[Row]:
    scoped = json.dumps(
        {
            "userEditedSQL": "SELECT SUM(${t.m}) FROM ${t} WHERE ${t.x} > 1",
            "join_paths_from_topic_name": "t",
        }
    )
    bare = json.dumps(
        {"userEditedSQL": "select ${a} from tbl", "join_paths_from_topic_name": ""}
    )
    return [
        _attempt("g1", run_id="gov", partition="dev-a", arm="C4", generated_query=None),
        _attempt(
            "g2", run_id="gov", partition="dev-a", arm="C4", generated_query=scoped
        ),
        _attempt("g3", run_id="gov", partition="dev-a", arm="C4", generated_query=bare),
        _attempt(
            "g4",
            run_id="gov",
            partition="dev-a",
            arm="C4",
            generated_query="{not json",
        ),
    ]


@pytest.fixture
def loaded(throwaway_database: str) -> str:
    attempts, scores = _dev_a_rows()
    with psycopg.connect(throwaway_database) as conn:
        apply_schema(conn)
        upsert_rows(conn, "attempt", [*attempts, *_sealed_rows(), *_governed_rows()])
        upsert_rows(conn, "score", scores)
        upsert_rows(
            conn,
            "sealed_aggregate",
            [
                Row(
                    "sealed_aggregate",
                    {
                        "run_id": SEALED_RUN_ID,
                        "scorer": "official_soft_ex",
                        "condition": "C1",
                        "correct": 1,
                        "wrong_answer": 0,
                        "refused_or_error": 2,
                        "mean_accuracy": 0.333333,
                        "scoreable_attempts": 3,
                    },
                )
            ],
        )
        conn.commit()
    return throwaway_database


def _frame_expectation(scorer: str) -> dict[str, dict[str, object]]:
    index = 0 if scorer == "official" else 1
    frame = {
        instance
        for instance in ("q1", "q2", "q3")
        if all(VERDICTS[(arm, instance)][index] is not None for arm in ARMS)
    }
    expected: dict[str, dict[str, object]] = {}
    for arm in ARMS:
        verdicts = [VERDICTS[(arm, q)][index] for q in sorted(frame)]
        correct = verdicts.count("correct")
        expected[arm] = {
            "correct": correct,
            "wrong_answer": verdicts.count("wrong_answer"),
            "refused_or_error": verdicts.count("refused_or_error"),
            "scoreable_attempts": len(verdicts),
            "accuracy_percent": percent(correct, len(verdicts)),
        }
    return expected


# --- arithmetic ------------------------------------------------------------------


def test_tukey_distribution_matches_frozen_convention() -> None:
    odd = tukey_distribution([5, 1, 3, 9, 7], total=6)
    assert odd == {
        "observed": 5,
        "missing": 1,
        "median": 5.0,
        "tukey_iqr": {"q1": 2.0, "q3": 8.0},
    }
    even = tukey_distribution([4, 1, 3, 2])
    assert even["median"] == 2.5 and even["tukey_iqr"] == {"q1": 1.5, "q3": 3.5}
    single = tukey_distribution([7.25])
    assert single["tukey_iqr"] == {"q1": 7.25, "q3": 7.25}
    assert tukey_distribution([], total=3) == {
        "observed": 0,
        "missing": 3,
        "median": None,
        "tukey_iqr": None,
    }
    with pytest.raises(ReconcileStatsError):
        tukey_distribution([1, 2], total=1)


def test_cost_summary_and_coverage_report_status() -> None:
    assert cost_summary([], total=2) == {
        "observed": 0,
        "missing": 2,
        "status": "unavailable",
    }
    assert cost_summary([1.0], total=2)["status"] == "partially_observed"
    full = cost_summary([0.1234567, 0.2], total=2)
    assert full == {
        "observed": 2,
        "missing": 0,
        "status": "fully_observed",
        "mean": 0.161728,
        "total": 0.323457,
    }
    assert median_coverage([], total=4) == {"observed": 0, "missing": 4, "median": None}
    assert percent(1, 3) == 33.3 and percent(0, 0) is None


# --- comparison --------------------------------------------------------------------


def test_compare_scalar_applies_exact_and_float_tolerances() -> None:
    assert compare_scalar(122, 122) == ("exact", True)
    assert compare_scalar(122, 122.0) == ("exact", True)
    assert compare_scalar(122, 123) == ("exact", False)
    assert compare_scalar(0.978792, 0.9787925) == ("abs<=1e-06", True)
    assert compare_scalar(0.978792, 0.978794) == ("abs<=1e-06", False)
    assert compare_scalar(True, 1) == ("exact", False)
    assert compare_scalar(None, None) == ("exact", True)
    assert compare_scalar("a", "a") == ("exact", True)
    assert compare_scalar("a", None) == ("exact", False)


def test_flatten_keeps_empty_containers_as_leaves() -> None:
    assert flatten({"a": {"b": [1, {"c": None}]}, "d": {}, "e": []}) == {
        "a.b[0]": 1,
        "a.b[1].c": None,
        "d": {},
        "e": [],
    }


def test_build_checks_flags_missing_unexpected_and_mismatch() -> None:
    checks = build_checks("g", {"x": 1, "y": 2.0, "z": "s"}, {"x": 1, "y": 2.5, "w": 0})
    by_path = {check.path: check.status for check in checks}
    assert by_path == {"w": "unexpected", "x": "match", "y": "mismatch", "z": "missing"}
    table = render_table(checks)
    assert "g:y" in table and "mismatch" in table


def _write_frozen_tree(root: Path) -> list[Path]:
    """Every artifact ``load_frozen_artifacts`` reads, each a minimal object."""
    relatives = [*ARTIFACT_PATHS.values()]
    relatives.extend(
        SEALED_SCORE_DIR / scorer / "aggregate.json" for scorer in SEALED_SCORERS
    )
    for relative in relatives:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
    return [root / relative for relative in relatives]


def test_load_frozen_artifacts_names_a_malformed_file(tmp_path: Path) -> None:
    written = _write_frozen_tree(tmp_path)
    artifacts = load_frozen_artifacts(tmp_path)
    assert set(artifacts.sources) == set(artifacts.documents)
    malformed = tmp_path / ARTIFACT_PATHS["matched_122_rollup"]
    malformed.write_text("{not json", encoding="utf-8")
    with pytest.raises(ReconcileError, match="matched-122-cost-time-rollup-v1.json"):
        load_frozen_artifacts(tmp_path)
    written[0].write_text("[]", encoding="utf-8")
    malformed.write_text("{}", encoding="utf-8")
    with pytest.raises(ReconcileError, match="top level must be an object"):
        load_frozen_artifacts(tmp_path)


def test_write_report_refuses_overwrite(tmp_path: Path) -> None:
    result = Reconciliation(checks=(), load_runs=(), sources={})
    target = tmp_path / "report.json"
    write_report(target, result)
    assert json.loads(target.read_text())["summary"]["checks"] == 0
    with pytest.raises(ReconcileError, match="refusing overwrite"):
        write_report(target, result)


# --- database ------------------------------------------------------------------------


def test_dev_a_frame_view_marks_membership_per_scorer(loaded: str) -> None:
    """The view flags each dev-A question in or out of each scorer's matched frame."""
    with psycopg.connect(loaded) as conn:
        rows = conn.execute(
            "SELECT instance_id, in_official_frame, in_sensitivity_frame "
            "FROM telemetry.dev_a_frame ORDER BY instance_id"
        ).fetchall()
    assert rows == [
        ("q1", True, True),
        ("q2", True, True),
        ("q3", False, True),
    ]


def test_dev_a_frame_view_agrees_with_the_reconciliation_frame(loaded: str) -> None:
    """The exposed view and the independent reconciliation SQL select one frame."""
    with psycopg.connect(loaded) as conn:
        for scorer, column in (
            ("official", "in_official_frame"),
            ("sensitivity", "in_sensitivity_frame"),
        ):
            view = {
                row[0]
                for row in conn.execute(
                    f"SELECT instance_id FROM telemetry.dev_a_frame WHERE {column}"
                ).fetchall()
            }
            assert view == {
                row["instance_id"] for row in observed.frame_rows(conn, scorer)
            }, scorer


def test_frame_counts_and_rollup_from_synthetic_rows(loaded: str) -> None:
    with psycopg.connect(loaded) as conn:
        counts = observed.dev_a_frame_counts(conn)
        rollup = observed.matched_frame_rollup(conn)
    assert counts["official"] == _frame_expectation("official")
    assert counts["sensitivity"] == _frame_expectation("sensitivity")
    assert counts["official"]["C4"]["scoreable_attempts"] == 2
    assert counts["sensitivity"]["C4"]["scoreable_attempts"] == 3
    assert rollup["question_count"] == 2
    c1 = rollup["arms"]["C1"]
    assert c1["attempts"] == 2 and c1["official_correct"] == 1
    assert c1["spend"] == {"coverage": 2, "total_usd": 2.0, "median_usd": 1.0}
    assert c1["cost_per_correct_answer_usd"] == 2.0
    assert c1["wall_time"] == {
        "coverage": 2,
        "total_hours": 0.001111,
        "median_ms": 2000.0,
    }
    assert c1["distributions"]["total_tokens"] == {
        "observed": 2,
        "missing": 0,
        "median": 220.0,
        "tukey_iqr": {"q1": 110.0, "q3": 330.0},
    }
    c3 = rollup["arms"]["C3"]
    assert c3["official_correct"] == 0 and c3["spend"]["coverage"] == 2
    assert c3["cost_per_correct_answer_usd"] is None
    c4 = rollup["arms"]["C4"]
    assert c4["spend"] == {"coverage": 0}
    assert "cost_per_correct_answer_usd" not in c4
    assert c4["distributions"]["cost_usd"]["missing"] == 2


def _assert_c1_summary(c1: dict[str, Any]) -> None:
    assert c1["attempt_count"] == 3 and c1["repetitions"] == {"1": 2, "2": 1}
    assert c1["outcomes"] == {"answered": 1, "errored": 1, "refused": 1}
    assert c1["refusal"] == {"status": "observed", "count": 1}
    assert c1["model_identities"] == [
        {
            "name": "claude-opus-5",
            "provider": "anthropic_claude_code_oauth",
            "version": "v1",
            "attempt_count": 3,
        }
    ]
    assert c1["failure_origins"] == {"evaluated_system": 2}
    assert c1["declared_unavailable"] == {"retry_count": 1}
    assert c1["telemetry"]["latency_ms"]["tukey_iqr"] == {"q1": 1000.0, "q3": 3000.0}
    assert c1["telemetry"]["cost_usd"] == {
        "observed": 3,
        "missing": 0,
        "status": "fully_observed",
        "mean": 0.5,
        "total": 1.5,
    }
    errored = c1["outcome_resource_medians"]["errored"]
    assert errored["attempt_count"] == 1 and errored["database_query_count"] == 0.0


def _assert_c4_summary(c4: dict[str, Any]) -> None:
    assert c4["outcomes"]["refused"] is None
    assert c4["refusal"] == {"status": "unavailable", "count": None}
    assert c4["model_identities"][0]["version"] == "unreported"
    assert c4["telemetry"]["database_query_count"] == {
        "observed": 0,
        "missing": 1,
        "median": None,
    }
    assert c4["telemetry"]["cost_usd"]["status"] == "unavailable"


def test_sealed_summary_from_synthetic_rows(loaded: str) -> None:
    with psycopg.connect(loaded) as conn:
        summaries = observed.sealed_condition_summaries(conn, ("C1", "C4"))
        tallies = observed.sealed_outcome_tallies(conn, ("C1", "C4"))
        aggregates = observed.sealed_aggregates(conn, SEALED_RUN_ID)
        pooled = observed.pooled_matrix_summary(conn, SEALED_RUN_ID)
    _assert_c1_summary(summaries["C1"])
    _assert_c4_summary(summaries["C4"])
    assert tallies["C1"]["terminal_failure_classes"] == {
        "model_budget_error": 1,
        "no_answer_insufficient_context": 1,
    }
    assert tallies["C4"]["failure_classes_including_none"] == {"none": 1}
    assert aggregates["official_soft_ex"]["C1"]["mean_accuracy"] == 0.333333
    assert pooled["official_soft_ex"]["C1"] == {
        "correct": 1,
        "n": 3,
        "percent": 33.3,
        "refused_or_error": 2,
        "wrong_answer": 0,
    }


def test_query_path_tally_and_run_comparison(loaded: str) -> None:
    with psycopg.connect(loaded) as conn:
        tally = observed.query_path_tally(conn, "gov")
        comparison = observed.run_comparison(conn, {"C4": "run-C4", "C5": "run-C5"})
        with pytest.raises(observed.ObservedError, match="no attempts loaded"):
            observed.query_path_tally(conn, "absent")
    assert tally == {
        "attempts": 4,
        "no_semantic_query": 2,
        "parseable_attempts": 2,
        "user_edited_sql": 2,
        "topic_scoped": 1,
        "user_edited_sql_and_topic_scoped": 1,
        "semantic_token_present": 2,
        "qualified_token_present": 1,
        "inline_aggregate_over_token": 1,
        "bare_table_from": 1,
        "semantic_token_total": 4,
        "shares_of_parseable_percent": {
            "user_edited_sql": 100.0,
            "topic_scoped": 50.0,
            "user_edited_sql_and_topic_scoped": 50.0,
            "semantic_token_present": 100.0,
            "qualified_token_present": 50.0,
            "inline_aggregate_over_token": 50.0,
            "bare_table_from": 50.0,
        },
    }
    assert comparison["matched_attempt_count"] == 3
    matched = comparison["runs"]["C5"]["matched"]
    assert matched["cost"]["status"] == "unavailable"
    assert matched["all_attempts"]["latency_ms"]["median"] == 3000.0
    assert matched["models"] == [
        {"name": "None", "provider": "unknown", "attempt_count": 3}
    ]


def test_reconcile_passes_then_fails_on_a_perturbed_artifact(loaded: str) -> None:
    document = {
        "official": _frame_expectation("official"),
        "sensitivity": _frame_expectation("sensitivity"),
    }
    artifacts = FrozenArtifacts(documents={"c5_matched_122": document})
    with psycopg.connect(loaded) as conn:
        passing = reconcile(conn, artifacts, ("dev_a_frame",))
        perturbed = json.loads(json.dumps(document))
        perturbed["official"]["C2"]["correct"] = 99
        failing = reconcile(
            conn,
            FrozenArtifacts(documents={"c5_matched_122": perturbed}),
            ("dev_a_frame",),
        )
        with pytest.raises(ReconcileError, match="was not loaded"):
            reconcile(conn, artifacts, ("query_path_tally",))
    assert passing.summary() == {
        "checks": 50,
        "matches": 50,
        "failures": 0,
        "by_status": {"match": 50},
    }
    assert passing.load_runs == ()
    assert [(c.path, c.expected, c.observed) for c in failing.failures] == [
        ("official.C2.correct", 99, 2)
    ]
    assert failing.summary()["by_status"] == {"match": 49, "mismatch": 1}

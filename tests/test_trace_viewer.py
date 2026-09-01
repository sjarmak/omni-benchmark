"""The explorer must agree with the committed aggregate, or it is not evidence."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VIEWER = ROOT / "experiments/trace_viewer"
sys.path.insert(0, str(VIEWER))

COMPARISON = ROOT / "experiments/analysis/c5-matched-122-comparison-v1.json"
CONDITIONS = ("C1", "C2", "C3", "C4", "C5")


@pytest.fixture(scope="module")
def rows():
    if not (ROOT / "experiments/autoresearch/raw").is_dir():
        pytest.skip("frozen run artifacts are not present in this checkout")
    import collect

    return collect.build()


def test_frame_is_the_matched_122(rows):
    assert len(rows) == 122
    assert len({row["instance_id"] for row in rows}) == 122


def test_outcomes_reproduce_the_committed_aggregate(rows):
    published = json.loads(COMPARISON.read_text(encoding="utf-8"))["official"]
    for condition in CONDITIONS:
        counts = Counter(row["arms"][condition]["outcome"] for row in rows)
        expected = published[condition]
        assert counts["correct"] == expected["correct"], condition
        assert counts["wrong_answer"] == expected["wrong_answer"], condition
        assert counts["refused_or_error"] == expected["refused_or_error"], condition


def test_every_arm_carries_its_question_and_artifact(rows):
    for row in rows:
        assert row["question"], row["instance_id"]
        assert row["database"], row["instance_id"]
        for condition in CONDITIONS:
            arm = row["arms"][condition]
            assert (ROOT / arm["artifact_dir"]).is_dir()
            assert arm["outcome"] in {"correct", "wrong_answer", "refused_or_error"}


def test_governed_arms_report_no_measured_cost_and_say_why(rows):
    """C4/C5 cost is absent by mechanism, not by omission; the page must say so."""
    for row in rows:
        for condition in ("C4", "C5"):
            arm = row["arms"][condition]
            assert arm["cost_usd"] is None
            assert arm["cost_unavailable_reason"] == "omni_job_api_does_not_expose_cost"


def test_credit_estimate_stands_in_for_the_governed_arms(rows):
    """The credit bracket postdates this frame, so the arm estimate must cover it."""
    import collect

    estimate = collect.governed_cost_estimate()
    assert estimate is not None
    assert 0 < estimate["per_attempt_usd"] <= estimate["upper_bound_usd"]
    assert estimate["caveats"]


def test_classification_is_consistent_with_the_outcomes(rows):
    for row in rows:
        correct = {c for c in CONDITIONS if row["arms"][c]["outcome"] == "correct"}
        pattern = row["pattern"]
        if pattern.startswith("only_"):
            assert correct == {pattern.removeprefix("only_")}
        elif pattern == "all_correct":
            assert len(correct) == 5
        elif pattern.startswith("all_wrong"):
            assert not correct
        elif pattern == "C5_recovers_C4":
            assert "C5" in correct and "C4" not in correct
        elif pattern == "C5_loses_C4":
            assert "C4" in correct and "C5" not in correct


def test_every_arm_carries_its_trajectory(rows):
    """A row that shows only an outcome is not a trace; each arm needs its steps."""
    for row in rows:
        for condition in CONDITIONS:
            arm = row["arms"][condition]
            assert arm["steps"], f"{condition} {row['instance_id']} has no trace"
            assert [s["seq"] for s in arm["steps"]] == sorted(
                s["seq"] for s in arm["steps"]
            )
            assert all(s["event_type"] for s in arm["steps"])


def test_direct_arms_record_what_they_asked_for(rows):
    """Retrieval queries exist only for the direct arms; governed arms have none."""
    direct = sum(
        len(row["arms"][c]["actions"]) for row in rows for c in ("C1", "C2", "C3")
    )
    governed = sum(len(row["arms"][c]["actions"]) for row in rows for c in ("C4", "C5"))
    assert direct > 0
    assert governed == 0


def test_page_builds_and_inlines_its_data(rows, tmp_path):
    import build as builder

    out = tmp_path / "index.html"
    builder.render(rows, str(out))
    page = out.read_text(encoding="utf-8")
    assert "@@" not in page
    assert page.startswith("<!doctype html>")
    payload = page.split("var ROWS = ", 1)[1].split(";\nvar CONDS", 1)[0]
    assert len(json.loads(payload)) == 122

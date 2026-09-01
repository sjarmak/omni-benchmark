"""The five-arm cost-and-time rollup must agree with the committed evidence.

The rollup is the artifact RESULTS.md, README.md, and the evidence index quote,
so the checks here are the ones that would let a wrong number reach a reader:
the frame, the correctness counts already published elsewhere, and the rule that
a governed dollar figure is never presented as a measurement.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/analysis"))

import matched_122_cost_time_rollup as rollup  # noqa: E402

COMMITTED = ROOT / "experiments/analysis/matched-122-cost-time-rollup-v1.json"
COMPARISON = ROOT / "experiments/analysis/c5-matched-122-comparison-v1.json"
MEASURED_ARMS = ("C1", "C2", "C3")
GOVERNED_ARMS = ("C4", "C5")


def payload() -> dict:
    return json.loads(COMMITTED.read_text())


def test_committed_artifact_regenerates_byte_identically():
    assert rollup.canonical_bytes(rollup.build()) == COMMITTED.read_bytes()


def test_frame_is_the_matched_122_under_the_official_scorer():
    data = payload()
    assert data["frame"]["question_count"] == 122
    assert data["frame"]["scorer"] == "official"
    assert all(arm["attempts"] == 122 for arm in data["arms"].values())


def test_correct_counts_reproduce_the_committed_comparison():
    published = json.loads(COMPARISON.read_text())
    counts = json.dumps(published)
    for arm, expected in (("C1", 9), ("C2", 29), ("C3", 16), ("C4", 5), ("C5", 13)):
        assert payload()["arms"][arm]["official_correct"] == expected
        assert str(expected) in counts


def test_direct_arms_report_measured_cost_with_complete_coverage():
    for arm in MEASURED_ARMS:
        spend = payload()["arms"][arm]["spend"]
        assert spend["cost_measured"] is True
        assert spend["cost_source"] == "provider_reported_per_attempt"
        assert spend["coverage"] == 122
        assert spend["total_usd"] > 100.0


def test_governed_arms_never_present_an_estimate_as_a_measurement():
    data = payload()
    per_attempt = data["governed_cost_estimate"]["per_attempt_usd"]
    for arm in GOVERNED_ARMS:
        spend = data["arms"][arm]["spend"]
        assert spend["cost_measured"] is False
        assert spend["cost_source"] == "arm_level_credit_estimate"
        assert spend["coverage"] == 0
        assert spend["median_usd"] == per_attempt
        assert spend["upper_bound_total_usd"] > spend["total_usd"]
        assert data["arms"][arm]["distributions"]["cost_usd"]["observed"] == 0


def test_wall_time_and_tokens_are_measured_in_every_arm():
    for arm, summary in payload()["arms"].items():
        assert summary["wall_time"]["coverage"] == 122, arm
        assert summary["wall_time"]["median_ms"] > 1000.0, arm
        assert summary["distributions"]["input_tokens"]["observed"] == 122, arm


def test_c5_spends_less_wall_time_than_c4_on_the_same_frame():
    arms = payload()["arms"]
    assert (
        arms["C5"]["wall_time"]["total_hours"] < arms["C4"]["wall_time"]["total_hours"]
    )
    assert arms["C5"]["wall_time"]["median_ms"] < arms["C4"]["wall_time"]["median_ms"]


def test_artifact_carries_no_protected_field():
    raw = COMMITTED.read_text()
    for field in (
        "sol_sql",
        "gold_sql",
        "test_cases",
        "external_knowledge",
        "gold_result",
        "expected_result",
        "instance_id",
    ):
        assert field not in raw

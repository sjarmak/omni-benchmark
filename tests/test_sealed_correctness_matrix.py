"""Cover the committed correctness matrix and the bounded reanalysis built on it.

The matrix is the first artifact in this project to publish a per-question
result for the sealed frame, so the tests that matter most are the ones that
prove what it does not contain and the ones that prove it refuses to assemble
itself from mismatched inputs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).parents[1]
COMMITTED_MATRIX = (
    REPOSITORY_ROOT / "experiments/analysis/sealed-correctness-matrix-v1.json"
)

#: Fields the protocol forbids at any nesting depth in a generation artifact.
FORBIDDEN_FIELDS = (
    "sol_sql",
    "gold_sql",
    "test_cases",
    "external_knowledge",
    "test_correctness",
    "gold_result",
    "expected_result",
)


def _module(name: str) -> Any:
    path = REPOSITORY_ROOT / "experiments" / "analysis" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _matrix_module() -> Any:
    return _module("sealed_correctness_matrix")


def _reanalysis_module() -> Any:
    return _module("sealed_bounded_reanalysis")


def _row(
    index: str, database: str, outcomes: list[str], failures: list[str]
) -> dict[str, Any]:
    return {
        "database": database,
        "question_index": index,
        "results": {
            scorer: {
                condition: list(outcomes) for condition in ("C1", "C2", "C3", "C4")
            }
            for scorer in ("official_soft_ex", "sensitivity")
        },
        "terminal_failure": {
            condition: list(failures) for condition in ("C1", "C2", "C3", "C4")
        },
    }


def _synthetic_matrix() -> dict[str, Any]:
    return {
        "lineage": {"freeze_b_sha256": "0" * 64},
        "questions": [
            _row(
                "q01",
                "alpha_large",
                ["correct", "correct", "correct"],
                ["none", "none", "none"],
            ),
            _row(
                "q02",
                "alpha_large",
                ["wrong_answer", "refused_or_error", "refused_or_error"],
                ["none", "model_budget_error", "no_answer_insufficient_context"],
            ),
            _row(
                "q03",
                "bravo_large",
                ["refused_or_error", "wrong_answer", "correct"],
                ["model_rate_limit_error", "none", "none"],
            ),
        ],
    }


def test_question_id_parsing_rejects_a_malformed_attempt_id() -> None:
    module = _matrix_module()
    with pytest.raises(module.CorrectnessMatrixError, match="unexpected attempt id"):
        module._question_id("dev-a:some_question:C4")


@pytest.mark.parametrize(
    ("failure", "assignment", "expected"),
    [
        # The correction that matters: the per-turn spend cap is ours, not the
        # provider's, so it is apparatus under the primary reading.
        ("model_budget_error", "primary", "apparatus"),
        ("model_budget_error", "alternate", "system"),
        ("model_rate_limit_error", "primary", "provider"),
        ("model_rate_limit_error", "alternate", "provider"),
        ("unsupported_semantic_result_type", "primary", "apparatus"),
        ("unsupported_semantic_result_type", "alternate", "system"),
        ("no_answer_insufficient_context", "primary", "system"),
        ("no_answer_insufficient_context", "alternate", "system"),
        ("none", "primary", "answered"),
    ],
)
def test_failure_bucket_resolution(
    failure: str, assignment: str, expected: str
) -> None:
    assert _reanalysis_module()._bucket(failure, assignment) == expected


def test_unknown_failure_class_is_refused_rather_than_absorbed() -> None:
    """A new failure class must break the build, not land silently in a bucket."""

    module = _reanalysis_module()
    with pytest.raises(module.BoundedReanalysisError, match="unbucketed"):
        module._bucket("some_new_failure_mode", "primary")


def test_bounds_are_ordered_and_reduce_to_as_scored_without_reassignable_attempts() -> (
    None
):
    module = _reanalysis_module()

    # Every attempt answered: nothing to reassign, so all three rules agree.
    answered_only = [("correct", "answered"), ("wrong_answer", "answered")]
    bounds = module.bounded_accuracy(answered_only)
    assert bounds["as_scored"] == bounds["neutral"] == bounds["charitable"] == 0.5
    assert bounds["reassignable"] == 0

    # One provider failure alongside a 50% answered rate: neutral credits it at
    # 0.5 and charitable credits it fully, so the three rules separate.
    mixed = [
        ("correct", "answered"),
        ("wrong_answer", "answered"),
        ("refused_or_error", "provider"),
    ]
    bounds = module.bounded_accuracy(mixed)
    assert bounds["as_scored"] == pytest.approx(1 / 3)
    assert bounds["neutral"] == pytest.approx((1 + 0.5) / 3)
    assert bounds["charitable"] == pytest.approx(2 / 3)
    assert bounds["as_scored"] < bounds["neutral"] < bounds["charitable"]


def test_a_system_failure_is_never_imputed_away() -> None:
    """System failures are results about the system and stay counted as wrong."""

    module = _reanalysis_module()
    cells = [("correct", "answered"), ("refused_or_error", "system")]
    bounds = module.bounded_accuracy(cells)
    assert bounds["reassignable"] == 0
    assert bounds["charitable"] == pytest.approx(0.5)


def test_build_report_covers_both_assignments_and_every_contrast() -> None:
    report = _reanalysis_module().build_report(_synthetic_matrix())
    assert set(report["contrast_bounds"]) == {"primary", "alternate"}
    for assignment in ("primary", "alternate"):
        for scorer in ("official_soft_ex", "sensitivity"):
            assert set(report["contrast_bounds"][assignment][scorer]) == {
                "C4-C1",
                "C2-C1",
                "C3-C2",
                "C4-C3",
            }
    # Three questions cannot produce six discordant pairs, so the frame reports
    # no reachable significance floor rather than inventing one.
    assert (
        report["minimum_detectable_effect"]["smallest_significant_discordant_pairs"]
        is None
    )


def test_minimum_detectable_effect_on_the_sealed_frame() -> None:
    """Six discordant pairs is the floor, and five leaves no rejection region."""

    module = _reanalysis_module()
    report = module.minimum_detectable_effect(
        89, {"C4-C3": 5, "C2-C1": 12, "C3-C2": 14}
    )
    assert report["smallest_significant_discordant_pairs"] == 6

    at_five = report["detectable_at_observed_discordant"]["C4-C3"]
    assert at_five["minimum_favor_rate_for_target_power"] is None
    assert at_five["power_if_every_discordant_pair_favors_one_arm"] == 0.0

    # More discordant pairs does not monotonically lower the detectable effect.
    # The rejection region is discrete, so adding a pair can tighten it faster
    # than it adds information: at 12 pairs the test rejects on 2 or fewer in
    # one direction out of 12, at 14 pairs still on 2 or fewer out of 14. The
    # required favor rate therefore rises from 12 pairs to 14.
    twelve = report["detectable_at_observed_discordant"]["C2-C1"]
    fourteen = report["detectable_at_observed_discordant"]["C3-C2"]
    assert twelve["minimum_favor_rate_for_target_power"] == pytest.approx(0.87)
    assert fourteen["minimum_favor_rate_for_target_power"] == pytest.approx(0.889)
    assert module._rejection_region(12, 0.05) == (0, 1, 2, 10, 11, 12)
    assert module._rejection_region(14, 0.05) == (0, 1, 2, 12, 13, 14)


def test_clustered_interval_rejects_an_unknown_cluster_level() -> None:
    module = _reanalysis_module()
    with pytest.raises(module.BoundedReanalysisError, match="unknown cluster level"):
        module.clustered_interval(_synthetic_matrix(), "sensitivity", "C1", "cohort")


@pytest.mark.skipif(
    not COMMITTED_MATRIX.exists(),
    reason="requires the committed sealed correctness matrix",
)
@pytest.mark.parametrize("cluster_by", ["question", "database"])
def test_clustered_interval_brackets_its_own_point_estimate(cluster_by: str) -> None:
    matrix = json.loads(COMMITTED_MATRIX.read_text(encoding="utf-8"))
    interval = _reanalysis_module().clustered_interval(
        matrix, "official_soft_ex", "C4", cluster_by
    )
    assert interval["clusters"] == (89 if cluster_by == "question" else 16)
    assert interval["lower"] <= interval["estimate"] <= interval["upper"]


@pytest.mark.skipif(
    not COMMITTED_MATRIX.exists(),
    reason="requires the committed sealed correctness matrix",
)
def test_question_clustered_interval_reproduces_the_frozen_c4_endpoint() -> None:
    """The recomputed preregistered interval must match the published one.

    This is the check that licenses publishing question-clustered intervals for
    C1 to C3, which the frozen aggregate never published. If the reimplementation
    drifted from ``sealed_results``, this is where it would show.
    """

    matrix = json.loads(COMMITTED_MATRIX.read_text(encoding="utf-8"))
    interval = _reanalysis_module().clustered_interval(
        matrix, "official_soft_ex", "C4", "question"
    )
    # runs/preserved/sealed-final-v6/score/official_soft_ex/aggregate.json,
    # report.primary.c4_mean_one_shot, rounded to the artifact's six places.
    assert interval["estimate"] == pytest.approx(0.086142)
    assert interval["lower"] == pytest.approx(0.037453)
    assert interval["upper"] == pytest.approx(0.146067)


@pytest.mark.skipif(
    not COMMITTED_MATRIX.exists(),
    reason="requires the committed sealed correctness matrix",
)
def test_committed_matrix_carries_no_identifier_or_forbidden_field() -> None:
    """The published matrix must not name a question or leak a protected field."""

    text = COMMITTED_MATRIX.read_text(encoding="utf-8")
    for field in FORBIDDEN_FIELDS:
        assert field not in text

    matrix = json.loads(text)
    sealed_ids = (
        (REPOSITORY_ROOT / "data/manifests/sealed_mvp_ids.txt")
        .read_text(encoding="utf-8")
        .split()
    )
    for question_id in sealed_ids:
        assert question_id not in text

    indices = [row["question_index"] for row in matrix["questions"]]
    assert indices == [f"q{position:02d}" for position in range(1, len(indices) + 1)]
    assert len(indices) == len(sealed_ids) == 89


@pytest.mark.skipif(
    not COMMITTED_MATRIX.exists(),
    reason="requires the committed sealed correctness matrix",
)
def test_committed_matrix_reproduces_its_own_published_aggregates() -> None:
    """Recompute the per-arm accuracy from the cells and match the stored summary."""

    matrix = json.loads(COMMITTED_MATRIX.read_text(encoding="utf-8"))
    summary = matrix["arm_summary"]
    for scorer in ("official_soft_ex", "sensitivity"):
        for condition in ("C1", "C2", "C3", "C4"):
            outcomes = [
                outcome
                for row in matrix["questions"]
                for outcome in row["results"][scorer][condition]
            ]
            correct = sum(1 for outcome in outcomes if outcome == "correct")
            assert summary[scorer][condition]["pooled"]["correct"] == correct
            assert summary[scorer][condition]["pooled"]["n"] == 267

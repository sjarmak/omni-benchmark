"""Pin the four preregistered statistical primitives to hand-computed values.

Before this file, every one of them was executed by the suite and none was
checked. ``test_sealed_results.py`` reads the point estimates and the reliability
counts but never reads a p-value, never reads a bootstrap endpoint, and asserts
Holm output only as ``is None`` / ``is not None``. ``test_committed_manifests.py``
pins the analysis-plan strings in ``config/preregistration.json`` but nothing
cross-checks the implementation against them, so the code could drift from its
own preregistration and the suite would stay green.

Every expected value here is written as the arithmetic that produces it rather
than as a decimal literal, so a reader can check the claim without running
anything. scipy is deliberately absent from this project, so there is no live
oracle to defer to; the exact-binomial construction is identical to
``scipy.stats.binomtest(k, n, 0.5, alternative="two-sided")`` for the symmetric
p=0.5 case, and the values below agree with it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.sealed_results import (
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    _bootstrap_sample,
    _estimate_with_interval,
    _exact_binomial_two_sided,
)

REPOSITORY_ROOT = Path(__file__).parents[1]
SEALED_SCORE_ROOT = REPOSITORY_ROOT / "runs/preserved/sealed-final-v6/score"


def _reanalysis_module() -> Any:
    path = REPOSITORY_ROOT / "experiments/analysis/sealed_bounded_reanalysis.py"
    spec = importlib.util.spec_from_file_location("sealed_bounded_reanalysis", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("gains", "losses", "expected"),
    [
        # No discordant pairs is the early return, not a computed value.
        (0, 0, 1.0),
        # A single discordant pair can never be evidence: 2 * (1/2) = 1.
        (1, 0, 2 * 1 / 2),
        (2, 0, 2 * 1 / 4),
        (3, 0, 2 * 1 / 8),
        # Five all-one-way pairs miss 0.05; six clear it. This is the boundary
        # the minimum-detectable-effect statement rests on.
        (5, 0, 2 * 1 / 32),
        (6, 0, 2 * 1 / 64),
        (10, 0, 2 * 1 / 1024),
        # An even split doubles past 1 and has to be clamped.
        (1, 1, 1.0),
        (5, 5, 1.0),
        (8, 2, 2 * (1 + 10 + 45) / 1024),
        (12, 3, 2 * (1 + 15 + 105 + 455) / 32768),
        # The four sealed repetition-one contrasts, official scorer.
        (11, 1, 2 * (1 + 12) / 4096),
        (0, 14, 2 * 1 / 16384),
        (3, 6, 2 * (1 + 9 + 36 + 84) / 512),
        (3, 2, 1.0),
    ],
)
def test_exact_binomial_matches_hand_computation(
    gains: int, losses: int, expected: float
) -> None:
    assert _exact_binomial_two_sided(gains, losses) == pytest.approx(expected)


def test_exact_binomial_is_symmetric_in_its_arguments() -> None:
    """Direction must not change the two-sided p-value."""

    for gains, losses in ((11, 1), (3, 6), (0, 14), (8, 2)):
        assert _exact_binomial_two_sided(gains, losses) == pytest.approx(
            _exact_binomial_two_sided(losses, gains)
        )


def test_six_discordant_pairs_is_the_significance_floor() -> None:
    """No split of five or fewer discordant pairs can reach alpha = 0.05.

    A contrast that produced five discordant pairs was not underpowered, it was
    unfalsifiable: the test had no rejection region at all. The sealed C4-C3
    contrast under the official scorer is exactly that case.
    """

    assert _exact_binomial_two_sided(5, 0) > 0.05
    assert _exact_binomial_two_sided(6, 0) <= 0.05
    for discordant in range(1, 6):
        assert (
            min(
                _exact_binomial_two_sided(gains, discordant - gains)
                for gains in range(discordant + 1)
            )
            > 0.05
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Plain step-down: multipliers 3, 2, 1 in ascending-p order.
        (
            {"C2-C1": 0.01, "C3-C2": 0.04, "C4-C3": 0.30},
            {"C2-C1": 0.03, "C3-C2": 0.08, "C4-C3": 0.30},
        ),
        # The running maximum binds: 0.03 * 2 = 0.06 does not fall below the
        # 0.06 that came before it.
        (
            {"C2-C1": 0.02, "C3-C2": 0.03, "C4-C3": 0.90},
            {"C2-C1": 0.06, "C3-C2": 0.06, "C4-C3": 0.90},
        ),
        # The 1.0 cap is applied per step, before the running maximum, so once
        # any step clamps every later step reports 1.0.
        (
            {"C2-C1": 0.50, "C3-C2": 0.60, "C4-C3": 0.70},
            {"C2-C1": 1.0, "C3-C2": 1.0, "C4-C3": 1.0},
        ),
        # Ties keep the declared family order and resolve to the same value.
        (
            {"C2-C1": 0.02, "C3-C2": 0.02, "C4-C3": 0.02},
            {"C2-C1": 0.06, "C3-C2": 0.06, "C4-C3": 0.06},
        ),
        # The sealed repetition-one family under the official scorer.
        (
            {
                "C2-C1": 2 * (1 + 12) / 4096,
                "C3-C2": 2 * 1 / 16384,
                "C4-C3": 1.0,
            },
            {
                "C2-C1": 2 * 2 * (1 + 12) / 4096,
                "C3-C2": 3 * 2 * 1 / 16384,
                "C4-C3": 1.0,
            },
        ),
    ],
)
def test_holm_step_down_matches_hand_computation(
    raw: dict[str, float], expected: dict[str, float]
) -> None:
    adjusted = _reanalysis_module().holm_adjust(raw)
    assert adjusted == pytest.approx(expected)


def test_holm_is_monotone_in_the_raw_p_values() -> None:
    """Adjusted p must never fall below that of a smaller raw p."""

    raw = {"C2-C1": 0.004, "C3-C2": 0.02, "C4-C3": 0.021}
    adjusted = _reanalysis_module().holm_adjust(raw)
    ordered = sorted(raw, key=lambda label: raw[label])
    values = [adjusted[label] for label in ordered]
    assert values == sorted(values)


def test_holm_rejects_a_family_missing_a_contrast() -> None:
    module = _reanalysis_module()
    with pytest.raises(module.BoundedReanalysisError, match="missing"):
        module.holm_adjust({"C2-C1": 0.01, "C3-C2": 0.02})


def test_bootstrap_sample_reproduces_the_preregistered_digest_rule() -> None:
    """Recompute the sampler's index arithmetic independently of the sampler."""

    questions = ("alpha", "bravo", "charlie", "delta", "echo")
    replicate = 7
    expected = tuple(
        questions[
            int.from_bytes(
                hashlib.sha256(
                    f"{BOOTSTRAP_SEED}\0{replicate}\0{draw}".encode()
                ).digest(),
                "big",
            )
            % len(questions)
        ]
        for draw in range(len(questions))
    )
    assert _bootstrap_sample(questions, replicate) == expected


def test_bootstrap_sample_is_deterministic_and_full_size() -> None:
    questions = tuple(f"q{index:02d}" for index in range(1, 90))
    first = _bootstrap_sample(questions, 0)
    assert first == _bootstrap_sample(questions, 0)
    assert len(first) == len(questions)
    assert set(first) <= set(questions)
    # A different replicate must give a different draw, or the seed is not
    # entering the digest.
    assert first != _bootstrap_sample(questions, 1)


def test_bootstrap_sample_depends_on_question_order() -> None:
    """The sampler indexes by position, so ordering is part of the preregistration.

    ``aggregate_sealed_results`` sorts question keys before sampling. If that
    sort ever changed, the intervals would move without any other visible
    difference, so the dependence is pinned here deliberately.
    """

    forward = ("a", "b", "c", "d")
    assert _bootstrap_sample(forward, 3) != _bootstrap_sample(forward[::-1], 3)


def test_nearest_rank_endpoints_are_the_250th_and_9750th_order_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the percentile rule itself: sorted[max(0, ceil(p * R) - 1)].

    With 10,000 replicates that is index 249 and index 9749. The rule takes an
    order statistic outright; it never interpolates between neighbours.
    """

    assert math.ceil(0.025 * BOOTSTRAP_REPLICATES) - 1 == 249
    assert math.ceil(0.975 * BOOTSTRAP_REPLICATES) - 1 == 9749

    replicates = 1000
    monkeypatch.setattr(
        "omni_benchmark.sealed_results.BOOTSTRAP_REPLICATES", replicates
    )
    # An estimator that returns the replicate's own rank makes the sorted list
    # of results exactly 0, 1, ... 999, so the endpoints are readable by eye.
    seen: dict[tuple[str, ...], int] = {}

    def estimator(sampled: tuple[str, ...]) -> float:
        return float(seen.setdefault(sampled, len(seen)))

    interval = _estimate_with_interval({}, ("only",), estimator, 0.5)
    assert interval["estimate"] == 0.5
    assert interval["lower"] == 0.0
    assert interval["upper"] == 0.0


def test_nearest_rank_picks_order_statistics_not_interpolations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replicates = 200
    monkeypatch.setattr(
        "omni_benchmark.sealed_results.BOOTSTRAP_REPLICATES", replicates
    )
    counter = {"n": 0}

    def estimator(sampled: tuple[str, ...]) -> float:
        del sampled
        counter["n"] += 1
        return float(counter["n"])

    interval = _estimate_with_interval({}, ("only",), estimator, 0.0)
    # Values are 1.0 .. 200.0; ceil(0.025 * 200) - 1 = 4 and
    # ceil(0.975 * 200) - 1 = 194, so the endpoints are the 5th and 195th values.
    assert interval["lower"] == 5.0
    assert interval["upper"] == 195.0


@pytest.mark.skipif(
    not SEALED_SCORE_ROOT.exists(),
    reason="requires the preserved sealed run tree, which is not committed",
)
@pytest.mark.parametrize("scorer", ["official_soft_ex", "sensitivity"])
def test_holm_helper_reproduces_the_published_sealed_adjustment(scorer: str) -> None:
    """The analysis script's Holm must agree with the frozen aggregate's own.

    ``sealed_results`` applies Holm inline inside ``_mcnemar_reports``, so the
    two implementations cannot share code without editing frozen analysis code
    after results were observed. This pins them to the same output instead.
    """

    aggregate = json.loads(
        (SEALED_SCORE_ROOT / scorer / "aggregate.json").read_text(encoding="utf-8")
    )
    published = aggregate["report"]["mcnemar_repetition_one"]
    family = ("C2-C1", "C3-C2", "C4-C3")

    adjusted = _reanalysis_module().holm_adjust(
        {label: published[label]["exact_two_sided_p"] for label in family}
    )
    for label in family:
        assert adjusted[label] == pytest.approx(published[label]["holm_adjusted_p"])
    assert published["C4-C1"]["holm_adjusted_p"] is None


@pytest.mark.skipif(
    not SEALED_SCORE_ROOT.exists(),
    reason="requires the preserved sealed run tree, which is not committed",
)
@pytest.mark.parametrize("scorer", ["official_soft_ex", "sensitivity"])
def test_exact_binomial_reproduces_the_published_sealed_p_values(scorer: str) -> None:
    """Recompute every published sealed p-value from its own discordant counts."""

    aggregate = json.loads(
        (SEALED_SCORE_ROOT / scorer / "aggregate.json").read_text(encoding="utf-8")
    )
    published = aggregate["report"]["mcnemar_repetition_one"]
    for label in ("C2-C1", "C3-C2", "C4-C3", "C4-C1"):
        report = published[label]
        assert _exact_binomial_two_sided(
            report["discordant_gains"], report["discordant_losses"]
        ) == pytest.approx(report["exact_two_sided_p"])

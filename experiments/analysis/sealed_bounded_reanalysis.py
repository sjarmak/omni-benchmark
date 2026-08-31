#!/usr/bin/env python3
"""Bound the sealed contrasts against the attempts that never reached an answer.

``RESULTS.md`` reports C4 minus C1 as a null. That contrast is only as strong as
the assumption behind it, which is that a failed attempt is evidence about the
evaluated system. On the sealed frame that assumption is false in different ways
for different conditions, and the differences are large:

* C1, C2, and C3 each lost dozens of attempts to the model provider's own spend
  cap and rate limiter. The evaluated system never got to answer.
* C4 lost 32 attempts to this benchmark's fail-closed result-type adapter and 4
  more to its response contract. Omni answered; our apparatus would not take it.

Both kinds are scored the same way an actual wrong answer is scored. So the
measured contrast mixes a claim about the systems with a claim about who ran out
of budget and whose result type our adapter happened to support. This analyzer
does not resolve that. It bounds it, which is the honest available move: it
recomputes every headline quantity under an as-scored rule, a neutral imputation,
and a maximally charitable rule, and reports whether any conclusion depends on
which rule you pick.

It also emits two things the preregistered analysis does not:

* a database-clustered percentile bootstrap, using the same seeded sampler and
  the same nearest-rank rule as the preregistered question-clustered one, so the
  two are comparable. This is post-hoc and labeled post-hoc everywhere it
  appears. Sixteen clusters is few, and the interval should be read as a
  robustness probe, not as a second official result.
* a minimum detectable effect for the paired exact test at n=89, so a reader can
  see what size of difference the sealed frame could have found at all.

Input is the committed identity-free correctness matrix, not the run tree, so
this reproduces from public artifacts.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from omni_benchmark.sealed_results import (
    BOOTSTRAP_REPLICATES,
    _bootstrap_sample,
    _exact_binomial_two_sided,
)

CONDITIONS = ("C1", "C2", "C3", "C4")
SCORERS = ("official_soft_ex", "sensitivity")

#: Where each terminal failure class puts the blame, and where a reasonable
#: reader might put it instead.
#:
#: ``provider`` - the failure came from outside the evaluated system entirely.
#: ``apparatus`` - the system produced something this benchmark refused to take.
#: ``system`` - the system itself declined, stalled, or emitted failing SQL.
#:
#: Four classes are genuinely arguable, and three of them are large enough to
#: move a conclusion, so the second column is not decoration. Each entry is
#: ``(primary, alternate)``; where the two differ, the artifact reports bounds
#: under both assignments rather than picking one and hoping nobody checks.
#:
#: The largest correction in this table is ``model_budget_error``. It is not a
#: provider account cap. The harness passes ``--max-budget-usd 1.0`` per turn
#: (``claude_direct_transport.py:479-480`` against
#: ``config/conditions/direct-runtime-v1.json``), and the 86 sealed instances had
#: already spent $2.27 to $6.23 across 5 to 10 completed turns when one turn
#: crossed our line. The cutoff is ours; the spending is the system's.
FAILURE_BUCKETS: dict[str, tuple[str, str]] = {
    # The system wrote SQL and Postgres rejected it on the final-answer path.
    "database_statement_error": ("system", "system"),
    # Our own per-turn spend ceiling, not a provider quota. Alternate reading:
    # the system chose to spend that much on one turn.
    "model_budget_error": ("apparatus", "system"),
    # D-042 records this class masking an expired-OAuth session failure, so it
    # is not cleanly a provider event or cleanly a strictness artifact.
    "model_identity_mismatch": ("provider", "apparatus"),
    # HTTP 429. Provoked by our own concurrency-4 dispatch on one identity,
    # which is a caveat on the number, not a reassignment of it.
    "model_rate_limit_error": ("provider", "provider"),
    # The system emitted the structured refuse action it was offered.
    "no_answer_insufficient_context": ("system", "system"),
    "none": ("answered", "answered"),
    # Omni cancelled or failed its own job. In C4 Omni is the system, which is
    # why the harness itself labels this evaluated_system.
    "omni_job_terminal_failure": ("system", "provider"),
    # The class is a wide net, but the four sealed instances are jobs Omni
    # completed having produced no usable query, which is a system result.
    "response_contract_error": ("system", "apparatus"),
    # Our admission gate refused the final SQL. The artifacts do not record
    # which gate fired, so the two readings cannot be separated. n=2.
    "sql_not_admitted": ("apparatus", "system"),
    # Twelve turns consumed without converging, against a limit we set.
    "turn_limit_exhausted": ("system", "system"),
    # The C4 story. Our closed seven-type frozenset refused 32 completed Omni
    # queries. Alternate reading: the planner declared UNKNOWN for columns the
    # deployed model never defines, which is a real gap in the governed contract.
    "unsupported_semantic_result_type": ("apparatus", "system"),
}

#: Buckets whose attempts the bounded rules may reassign. A system failure is a
#: real result about the system and is never imputed away.
_NON_SYSTEM = ("provider", "apparatus")

#: The two bucket assignments the report is computed under.
_ASSIGNMENTS = ("primary", "alternate")


class BoundedReanalysisError(ValueError):
    """Raised when the matrix cannot support a bounded reanalysis."""


def _bucket(failure: str, assignment: str) -> str:
    """Resolve one failure class to a bucket under the named assignment."""

    buckets = FAILURE_BUCKETS.get(failure)
    if buckets is None:
        raise BoundedReanalysisError(f"unbucketed failure class {failure!r}")
    return buckets[_ASSIGNMENTS.index(assignment)]


def _cells(
    matrix: dict[str, Any], scorer: str, condition: str, assignment: str
) -> list[tuple[str, str]]:
    """Return ``(outcome, failure_bucket)`` for every attempt in one arm."""

    cells: list[tuple[str, str]] = []
    for row in matrix["questions"]:
        outcomes = row["results"][scorer][condition]
        failures = row["terminal_failure"][condition]
        if len(outcomes) != len(failures):
            raise BoundedReanalysisError(
                f"{condition} row {row['question_index']} has mismatched cell counts"
            )
        for outcome, failure in zip(outcomes, failures, strict=True):
            cells.append((outcome, _bucket(failure, assignment)))
    return cells


def bounded_accuracy(cells: list[tuple[str, str]]) -> dict[str, Any]:
    """Recompute one arm's accuracy under the three rules.

    ``as_scored`` is what the frozen scorers reported. ``neutral`` credits each
    non-system failure at the rate the arm achieved on attempts that did reach an
    answer. ``charitable`` credits every non-system failure as correct, which is
    not believable but is the ceiling, and a null that survives the ceiling is a
    null worth reporting.
    """

    total = len(cells)
    correct = sum(1 for outcome, _ in cells if outcome == "correct")
    answered = sum(1 for _, bucket in cells if bucket == "answered")
    reassignable = sum(1 for _, bucket in cells if bucket in _NON_SYSTEM)
    answered_rate = correct / answered if answered else 0.0

    return {
        "answered": answered,
        "answered_accuracy": round(answered_rate, 6),
        "as_scored": round(correct / total, 6),
        "charitable": round((correct + reassignable) / total, 6),
        "correct": correct,
        "n": total,
        "neutral": round((correct + reassignable * answered_rate) / total, 6),
        "reassignable": reassignable,
        "reassignable_by_bucket": {
            bucket: sum(1 for _, value in cells if value == bucket)
            for bucket in _NON_SYSTEM
        },
    }


def paired_rep_one(
    matrix: dict[str, Any], scorer: str, left: str, right: str, assignment: str
) -> dict[str, Any]:
    """Rerun the preregistered rep-1 exact test under the as-scored and ceiling rules.

    The preregistered test pairs repetition one only. Under the ceiling rule a
    non-system failure on either side is treated as correct, which can create or
    destroy discordant pairs; both p-values are reported so a reader can see
    whether the verdict is rule-dependent.
    """

    def side(condition: str, index: int) -> tuple[bool, bool]:
        row = matrix["questions"][index]
        outcome = row["results"][scorer][condition][0]
        bucket = _bucket(row["terminal_failure"][condition][0], assignment)
        return outcome == "correct", bucket in _NON_SYSTEM

    results: dict[str, Any] = {}
    for rule in ("as_scored", "charitable"):
        gains = losses = 0
        for index in range(len(matrix["questions"])):
            left_correct, left_excused = side(left, index)
            right_correct, right_excused = side(right, index)
            if rule == "charitable":
                left_correct = left_correct or left_excused
                right_correct = right_correct or right_excused
            if left_correct and not right_correct:
                gains += 1
            elif right_correct and not left_correct:
                losses += 1
        results[rule] = {
            "discordant": gains + losses,
            "gains": gains,
            "losses": losses,
            "p_value": _exact_binomial_two_sided(gains, losses),
        }
    return results


#: The preregistered exploratory family. C4-C1 is primary and unadjusted, so it
#: is deliberately absent. Mirrors the family in ``sealed_results._mcnemar_reports``.
_EXPLORATORY_FAMILY = ("C2-C1", "C3-C2", "C4-C3")


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    """Holm step-down over the preregistered exploratory family.

    Deliberately mirrors the inlined block in ``sealed_results._mcnemar_reports``,
    including the detail that the 1.0 cap is applied per step before the running
    maximum. ``tests/test_sealed_statistics_known_answers.py`` pins both against
    one shared table of hand-computed values, so a divergence fails the suite
    rather than quietly producing two different corrections.
    """

    missing = [label for label in _EXPLORATORY_FAMILY if label not in p_values]
    if missing:
        raise BoundedReanalysisError(f"exploratory family is missing {missing}")

    ordered = sorted(_EXPLORATORY_FAMILY, key=lambda label: p_values[label])
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, label in enumerate(ordered):
        running = max(
            running, min(1.0, (len(_EXPLORATORY_FAMILY) - index) * p_values[label])
        )
        adjusted[label] = running
    return adjusted


def clustered_interval(
    matrix: dict[str, Any], scorer: str, condition: str, cluster_by: str
) -> dict[str, float]:
    """Percentile bootstrap over question clusters or database clusters.

    Deliberately reuses the frozen sampler and the frozen nearest-rank rule from
    ``sealed_results``. Reimplementing either here would make the post-hoc
    database-clustered interval incomparable to the preregistered
    question-clustered one, which is the only reason to compute it.

    ``cluster_by="question"`` reproduces the preregistered clustering. The frozen
    aggregate publishes that interval only for the C4 primary endpoints, so
    computing it here for all four arms is what makes the database-clustered
    numbers readable as a comparison rather than as free-standing values.
    """

    if cluster_by not in ("question", "database"):
        raise BoundedReanalysisError(f"unknown cluster level {cluster_by!r}")

    by_cluster: dict[str, list[bool]] = {}
    for row in matrix["questions"]:
        key = row["database"] if cluster_by == "database" else row["question_index"]
        outcomes = row["results"][scorer][condition]
        by_cluster.setdefault(key, []).extend(
            outcome == "correct" for outcome in outcomes
        )
    clusters = sorted(by_cluster)

    def estimate(sampled: tuple[str, ...]) -> float:
        drawn = [value for name in sampled for value in by_cluster[name]]
        return sum(drawn) / len(drawn)

    values = sorted(
        estimate(_bootstrap_sample(clusters, replicate))
        for replicate in range(BOOTSTRAP_REPLICATES)
    )
    return {
        "clusters": len(clusters),
        "estimate": round(
            sum(sum(v) for v in by_cluster.values())
            / sum(len(v) for v in by_cluster.values()),
            6,
        ),
        "lower": round(values[max(0, math.ceil(0.025 * BOOTSTRAP_REPLICATES) - 1)], 6),
        "upper": round(values[max(0, math.ceil(0.975 * BOOTSTRAP_REPLICATES) - 1)], 6),
    }


def _rejection_region(discordant: int, alpha: float) -> tuple[int, ...]:
    """Gains counts the exact two-sided test rejects at ``alpha``, given ``discordant``."""

    return tuple(
        gains
        for gains in range(discordant + 1)
        if _exact_binomial_two_sided(gains, discordant - gains) <= alpha
    )


def _power(discordant: int, favor_rate: float, alpha: float) -> float:
    """Chance of rejecting when each discordant pair favors one arm w.p. ``favor_rate``."""

    region = _rejection_region(discordant, alpha)
    return sum(
        math.comb(discordant, gains)
        * favor_rate**gains
        * (1.0 - favor_rate) ** (discordant - gains)
        for gains in region
    )


def minimum_detectable_effect(
    questions: int,
    observed_discordant: dict[str, int],
    alpha: float = 0.05,
    power: float = 0.80,
) -> dict[str, Any]:
    """What the rep-1 exact test at n=89 could and could not have detected.

    The preregistered test conditions on the discordant pairs, so its power is
    governed by how many there are, not by the 89. Two things a reader needs:
    the smallest discordant count that can reach significance at all, and, for
    the discordant counts this run actually produced, the smallest true effect
    the test had an 80% chance of catching. Where that minimum exceeds 1.0 the
    honest answer is that no effect was detectable at that discordant count.
    """

    smallest_significant = next(
        (
            discordant
            for discordant in range(1, questions + 1)
            if _exact_binomial_two_sided(discordant, 0) <= alpha
        ),
        None,
    )

    def minimum_favor_rate(discordant: int) -> float | None:
        if not _rejection_region(discordant, alpha):
            return None
        # Power rises monotonically in favor_rate over [0.5, 1.0]; a 0.001 grid
        # is finer than any effect this frame could resolve.
        for step in range(500, 1001):
            rate = step / 1000.0
            if _power(discordant, rate, alpha) >= power:
                return rate
        return None

    return {
        "alpha": alpha,
        "detectable_at_observed_discordant": {
            label: {
                "discordant_pairs": discordant,
                "minimum_favor_rate_for_target_power": minimum_favor_rate(discordant),
                "power_if_every_discordant_pair_favors_one_arm": round(
                    _power(discordant, 1.0, alpha), 6
                ),
            }
            for label, discordant in sorted(observed_discordant.items())
        },
        "note": (
            "a null on this frame is not evidence of equivalence; at these"
            " discordant counts the test could only have found effects at or"
            " above the listed favor rates"
        ),
        "power_target": power,
        "questions": questions,
        "smallest_significant_discordant_pairs": smallest_significant,
    }


def build_report(matrix: dict[str, Any]) -> dict[str, Any]:
    """Assemble every bounded quantity from the committed matrix."""

    contrast_pairs = (("C4", "C1"), ("C2", "C1"), ("C3", "C2"), ("C4", "C3"))

    failure_table = {
        condition: {
            "by_bucket": {
                assignment: {
                    bucket: sum(
                        1
                        for row in matrix["questions"]
                        for failure in row["terminal_failure"][condition]
                        if _bucket(failure, assignment) == bucket
                    )
                    for bucket in ("answered", "provider", "apparatus", "system")
                }
                for assignment in _ASSIGNMENTS
            },
            "by_class": {
                failure: sum(
                    1
                    for row in matrix["questions"]
                    for value in row["terminal_failure"][condition]
                    if value == failure
                )
                for failure in sorted(
                    {
                        value
                        for row in matrix["questions"]
                        for value in row["terminal_failure"][condition]
                    }
                )
            },
        }
        for condition in CONDITIONS
    }

    accuracy: dict[str, Any] = {}
    contrasts: dict[str, Any] = {}
    paired: dict[str, Any] = {}
    holm: dict[str, Any] = {}
    for assignment in _ASSIGNMENTS:
        per_assignment_accuracy = {
            scorer: {
                condition: bounded_accuracy(
                    _cells(matrix, scorer, condition, assignment)
                )
                for condition in CONDITIONS
            }
            for scorer in SCORERS
        }
        accuracy[assignment] = per_assignment_accuracy
        contrasts[assignment] = {
            scorer: {
                f"{left}-{right}": {
                    rule: round(
                        per_assignment_accuracy[scorer][left][rule]
                        - per_assignment_accuracy[scorer][right][rule],
                        6,
                    )
                    for rule in ("as_scored", "neutral", "charitable")
                }
                for left, right in contrast_pairs
            }
            for scorer in SCORERS
        }
        per_assignment_paired = {
            scorer: {
                f"{left}-{right}": paired_rep_one(
                    matrix, scorer, left, right, assignment
                )
                for left, right in contrast_pairs
            }
            for scorer in SCORERS
        }
        paired[assignment] = per_assignment_paired
        holm[assignment] = {
            scorer: {
                rule: holm_adjust(
                    {
                        label: per_assignment_paired[scorer][label][rule]["p_value"]
                        for label in _EXPLORATORY_FAMILY
                    }
                )
                for rule in ("as_scored", "charitable")
            }
            for scorer in SCORERS
        }

    clustered = {
        cluster_by: {
            scorer: {
                condition: clustered_interval(matrix, scorer, condition, cluster_by)
                for condition in CONDITIONS
            }
            for scorer in SCORERS
        }
        for cluster_by in ("question", "database")
    }

    return {
        "artifact_kind": "sealed_bounded_reanalysis",
        "bounded_accuracy": accuracy,
        "bucket_assignments": {
            "alternate": "every arguable class flipped to its second reading",
            "primary": "the reading the disclosure defends, class by class",
        },
        "contrast_bounds": contrasts,
        "clustered_bootstrap": clustered,
        "clustered_bootstrap_status": (
            "the question level reproduces the preregistered clustering, which"
            " the frozen aggregate publishes only for the C4 primary endpoints;"
            " the database level is post-hoc, not preregistered, and with 16"
            " clusters it is a robustness probe beside the question-clustered"
            " interval, never a replacement for it"
        ),
        "failure_buckets": {
            name: dict(zip(_ASSIGNMENTS, buckets, strict=True))
            for name, buckets in sorted(FAILURE_BUCKETS.items())
        },
        "holm_adjusted_exploratory_family": holm,
        "minimum_detectable_effect": minimum_detectable_effect(
            len(matrix["questions"]),
            {
                f"{scorer}:{contrast}": values["as_scored"]["discordant"]
                for scorer, contrasts_for_scorer in paired["primary"].items()
                for contrast, values in contrasts_for_scorer.items()
            },
        ),
        "paired_repetition_one": paired,
        "schema_version": 1,
        "source_lineage": matrix["lineage"],
        "terminal_failure_table": failure_table,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)

    matrix = json.loads(
        arguments.matrix.resolve(strict=True).read_text(encoding="utf-8")
    )
    report = build_report(matrix)
    content = (
        json.dumps(report, allow_nan=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    if arguments.output is not None:
        arguments.output.write_text(content, encoding="utf-8")
    else:
        print(content.rstrip("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

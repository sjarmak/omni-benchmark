"""Aggregate-only held-out reporting from complete sealed score labels."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_benchmark.dev_a_baseline_scoring import ModeAttemptScore
from omni_benchmark.scoring import OFFICIAL_SOFT_EX_VERSION, SENSITIVITY_SCORER_VERSION
from omni_benchmark.sealed_results import (
    SealedResultError,
    SealedScoredAttempt,
    aggregate_sealed_results,
    publish_sealed_aggregate,
)
from omni_benchmark.sealed_scoring import FailureClass, ScoringMode, SealedScoringResult


def _score(mode: ScoringMode, outcome: str) -> ModeAttemptScore:
    identity, version = (
        ("official_soft_ex", OFFICIAL_SOFT_EX_VERSION)
        if mode is ScoringMode.OFFICIAL
        else ("sensitivity", SENSITIVITY_SCORER_VERSION)
    )
    failure = FailureClass.AGENT_REFUSAL if outcome == "refused_or_error" else None
    return ModeAttemptScore(
        result=SealedScoringResult(
            scorer_identity=identity,
            scorer_version=version,
            outcome=outcome,  # type: ignore[arg-type]
            failure_origin="evaluated_system" if failure else None,
            failure_class=failure,
        )
    )


def _attempts() -> tuple[SealedScoredAttempt, ...]:
    attempts = []
    for question in range(4):
        for condition in ("C1", "C2", "C3", "C4"):
            for repetition in (1, 2, 3):
                correct = {
                    "C1": question in {1},
                    "C2": question in {1, 2},
                    "C3": question in {1, 2, 3},
                    "C4": question != 0 or repetition == 1,
                }[condition]
                outcome = "correct" if correct else "wrong_answer"
                attempts.append(
                    SealedScoredAttempt(
                        attempt_id=f"sealed:q-{question}:{condition}:{repetition}",
                        condition=condition,
                        generation_outcome="answered",
                        generation_record_sha256=f"{question + 1:064x}",
                        generation_sha256=f"{repetition + 10:064x}",
                        question_key=f"question-{question}",
                        repetition=repetition,
                        official=_score(ScoringMode.OFFICIAL, outcome),
                        sensitivity=_score(ScoringMode.SENSITIVITY, outcome),
                        terminal_failure_class=None,
                    )
                )
    return tuple(attempts)


def test_aggregate_contains_preregistered_endpoints_without_identities() -> None:
    report = aggregate_sealed_results(_attempts(), ScoringMode.OFFICIAL)

    assert report["primary"]["c4_mean_one_shot"]["estimate"] == pytest.approx(10 / 12)
    assert report["primary"]["c4_repetition_one"]["estimate"] == pytest.approx(1.0)
    assert report["primary"]["c4_minus_c1"]["estimate"] == pytest.approx(7 / 12)
    assert report["conditions"]["C1"]["pass_3_count"] == 1
    assert report["conditions"]["C4"]["correctness_flip_count"] == 1
    assert report["conditions"]["C4"]["pass_3_rate"] == pytest.approx(0.75)
    assert report["conditions"]["C4"]["content_refusal_rate"] is None
    assert report["conditions"]["C4"]["insufficient_context_rate"] is None
    assert set(report["contrasts"]) == {"C2-C1", "C3-C2", "C4-C1", "C4-C3"}
    assert report["mcnemar_repetition_one"]["C4-C1"]["holm_adjusted_p"] is None
    assert report["mcnemar_repetition_one"]["C2-C1"]["holm_adjusted_p"] is not None
    assert report["bootstrap"]["replicates"] == 10_000
    rendered = json.dumps(report, sort_keys=True)
    assert "sealed:q-" not in rendered
    assert "question-" not in rendered


def test_aggregate_rejects_an_incomplete_or_unpublishable_matrix() -> None:
    with pytest.raises(SealedResultError, match="complete C1-C4 by three-repetition"):
        aggregate_sealed_results(_attempts()[:-1], ScoringMode.OFFICIAL)

    broken = list(_attempts())
    broken[0] = SealedScoredAttempt(
        **{
            **broken[0].__dict__,
            "official": ModeAttemptScore(
                result=SealedScoringResult(
                    scorer_identity="official_soft_ex",
                    scorer_version=OFFICIAL_SOFT_EX_VERSION,
                    outcome=None,
                    failure_origin="benchmark_infrastructure",
                    failure_class=FailureClass.DATABASE_ACQUIRE_FAILED,
                )
            ),
        }
    )
    with pytest.raises(SealedResultError, match="infrastructure"):
        aggregate_sealed_results(tuple(broken), ScoringMode.OFFICIAL)


def test_publish_aggregate_is_private_immutable_and_identity_free(
    tmp_path: Path,
) -> None:
    workspace = tmp_path.resolve()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    report = aggregate_sealed_results(_attempts(), ScoringMode.SENSITIVITY)
    destination = Path("runs/sealed-score/aggregate-sensitivity.json")

    summary = publish_sealed_aggregate(
        workspace,
        destination=destination,
        freeze_b_sha256="a" * 64,
        release_sha256="b" * 64,
        score_artifact_sha256s=("c" * 64,) * 12,
        report=report,
    )

    output = workspace / destination
    assert output.stat().st_mode & 0o777 == 0o600
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["kind"] == "sealed-aggregate-result"
    assert value["report"] == report
    rendered = output.read_text(encoding="utf-8")
    assert "sealed:q-" not in rendered
    assert "question-" not in rendered
    assert set(summary) == {"aggregate_sha256", "path"}
    with pytest.raises(SealedResultError, match="exists"):
        publish_sealed_aggregate(
            workspace,
            destination=destination,
            freeze_b_sha256="a" * 64,
            release_sha256="b" * 64,
            score_artifact_sha256s=("c" * 64,) * 12,
            report=report,
        )

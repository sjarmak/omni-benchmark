"""Identity-free preregistered summaries of complete sealed score labels."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError
from .dev_a_baseline_scoring import (
    UNSCORABLE_GOLD_FAILURES,
    ModeAttemptScore,
)
from .scoring import OFFICIAL_SOFT_EX_VERSION, SENSITIVITY_SCORER_VERSION
from .sealed_scoring import ScoringMode

CONDITIONS = ("C1", "C2", "C3", "C4")
REPETITIONS = (1, 2, 3)
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = "omni-livesqlbench-large-v1-analysis-v1"
SCHEMA_VERSION = 1


class SealedResultError(RuntimeError):
    """A sanitized failure at the held-out aggregate publication boundary."""


@dataclass(frozen=True)
class SealedScoredAttempt:
    """One private score label plus non-gold generation provenance."""

    attempt_id: str
    condition: str
    repetition: int
    generation_sha256: str
    generation_record_sha256: str
    question_key: str
    generation_outcome: str
    terminal_failure_class: str | None
    official: ModeAttemptScore
    sensitivity: ModeAttemptScore


def aggregate_sealed_results(
    attempts: Sequence[SealedScoredAttempt], mode: ScoringMode
) -> dict[str, Any]:
    """Compute fixed held-out endpoints without retaining question identities."""
    matrix = _validated_matrix(attempts, mode)
    questions = tuple(sorted(matrix))
    condition_reports = {
        condition: _condition_report(matrix, questions, condition, mode)
        for condition in CONDITIONS
    }
    contrasts = {
        label: _contrast_report(matrix, questions, after, before, mode)
        for label, after, before in (
            ("C2-C1", "C2", "C1"),
            ("C3-C2", "C3", "C2"),
            ("C4-C1", "C4", "C1"),
            ("C4-C3", "C4", "C3"),
        )
    }
    c4_mean = _condition_estimator(matrix, questions, "C4", REPETITIONS, mode)
    c4_run_one = _condition_estimator(matrix, questions, "C4", (1,), mode)
    mcnemar = _mcnemar_reports(matrix, questions, mode)
    return {
        "bootstrap": {
            "ci_level": 0.95,
            "interval": "percentile_nearest_rank",
            "replicates": BOOTSTRAP_REPLICATES,
            "sampler": "sha256_modulo_question_count_v1",
            "seed": BOOTSTRAP_SEED,
        },
        "conditions": condition_reports,
        "contrasts": contrasts,
        "mcnemar_repetition_one": mcnemar,
        "primary": {
            "c4_mean_one_shot": _estimate_with_interval(
                matrix,
                questions,
                lambda sampled: _condition_estimator(
                    matrix, sampled, "C4", REPETITIONS, mode
                ),
                c4_mean,
            ),
            "c4_minus_c1": contrasts["C4-C1"],
            "c4_repetition_one": _estimate_with_interval(
                matrix,
                questions,
                lambda sampled: _condition_estimator(matrix, sampled, "C4", (1,), mode),
                c4_run_one,
            ),
        },
        "question_count": len(questions),
        "scorer": {
            "identity": mode.value,
            "version": _scorer_version(mode),
        },
    }


def publish_sealed_aggregate(
    workspace: Path,
    *,
    destination: Path,
    freeze_b_sha256: str,
    release_sha256: str,
    score_artifact_sha256s: Sequence[str],
    report: Mapping[str, Any],
) -> dict[str, str]:
    """Write one immutable private aggregate whose body contains no identities."""
    freeze_digest = _digest(freeze_b_sha256, "Freeze-B SHA-256")
    release_digest = _digest(release_sha256, "release SHA-256")
    score_digests = tuple(
        _digest(value, "score artifact SHA-256") for value in score_artifact_sha256s
    )
    if len(score_digests) != 12:
        raise SealedResultError("aggregate must bind exactly twelve score artifacts")
    payload = {
        "freeze_b_sha256": freeze_digest,
        "kind": "sealed-aggregate-result",
        "release_sha256": release_digest,
        "report": dict(report),
        "schema_version": SCHEMA_VERSION,
        "score_artifact_sha256s": list(score_digests),
    }
    root = _workspace(workspace)
    selected = Path(destination)
    if selected.is_absolute() or not selected.parts or ".." in selected.parts:
        raise SealedResultError("aggregate destination must be confined")
    try:
        stored = ArtifactStore(root, selected.parent).write_json(
            Path(selected.name), payload
        )
    except ArtifactStoreError as error:
        raise SealedResultError(str(error)) from error
    return {
        "aggregate_sha256": stored.sha256,
        "path": stored.path.relative_to(root).as_posix(),
    }


def _validated_matrix(
    attempts: Sequence[SealedScoredAttempt], mode: ScoringMode
) -> dict[str, dict[tuple[str, int], SealedScoredAttempt]]:
    if not isinstance(mode, ScoringMode):
        raise SealedResultError("scoring mode is invalid")
    if isinstance(attempts, (str, bytes)) or not isinstance(attempts, Sequence):
        raise SealedResultError("sealed attempts must be a sequence")
    matrix: dict[str, dict[tuple[str, int], SealedScoredAttempt]] = {}
    seen_attempts: set[str] = set()
    expected_coordinates = {
        (condition, repetition)
        for condition in CONDITIONS
        for repetition in REPETITIONS
    }
    for attempt in attempts:
        if not isinstance(attempt, SealedScoredAttempt):
            raise SealedResultError("sealed score record is invalid")
        if attempt.attempt_id in seen_attempts:
            raise SealedResultError("sealed score records contain duplicate attempts")
        seen_attempts.add(attempt.attempt_id)
        if (
            attempt.condition not in CONDITIONS
            or type(attempt.repetition) is not int
            or attempt.repetition not in REPETITIONS
            or not isinstance(attempt.question_key, str)
            or not attempt.question_key
            or attempt.generation_outcome not in {"answered", "refused", "errored"}
        ):
            raise SealedResultError("sealed score record identity is invalid")
        _digest(attempt.generation_sha256, "generation SHA-256")
        _digest(attempt.generation_record_sha256, "generation record SHA-256")
        key = (attempt.condition, attempt.repetition)
        if key in matrix.setdefault(attempt.question_key, {}):
            raise SealedResultError(
                "sealed score records contain duplicate coordinates"
            )
        matrix[attempt.question_key][key] = attempt
        _validated_disposition(_mode_score(attempt, mode), mode)
    if not matrix or any(set(row) != expected_coordinates for row in matrix.values()):
        raise SealedResultError(
            "sealed scores must form a complete C1-C4 by three-repetition matrix"
        )
    for row in matrix.values():
        dispositions = {
            _mode_score(item, mode).unscorable_failure for item in row.values()
        }
        if len(dispositions) != 1:
            raise SealedResultError(
                "gold scoreability must be fixed per question and scorer"
            )
    return matrix


def _validated_disposition(score: ModeAttemptScore, mode: ScoringMode) -> None:
    if not isinstance(score, ModeAttemptScore):
        raise SealedResultError("sealed score disposition is invalid")
    if score.unscorable_failure is not None:
        if score.unscorable_failure not in UNSCORABLE_GOLD_FAILURES:
            raise SealedResultError("gold-unscorable category is invalid")
        return
    result = score.result
    if result is None:
        raise SealedResultError("sealed score disposition is invalid")
    if result.outcome is None or result.failure_origin == "benchmark_infrastructure":
        raise SealedResultError("infrastructure failures block aggregate publication")
    if (result.scorer_identity, result.scorer_version) != (
        mode.value,
        _scorer_version(mode),
    ):
        raise SealedResultError("sealed scorer identity is invalid")


def _condition_report(
    matrix: Mapping[str, Mapping[tuple[str, int], SealedScoredAttempt]],
    questions: Sequence[str],
    condition: str,
    mode: ScoringMode,
) -> dict[str, Any]:
    rows = [
        matrix[question][(condition, repetition)]
        for question in questions
        for repetition in REPETITIONS
    ]
    dispositions = [_mode_score(item, mode) for item in rows]
    scoreable = [item for item in dispositions if item.result is not None]
    outcomes = Counter(
        item.result.outcome for item in scoreable if item.result is not None
    )
    generation = Counter(item.generation_outcome for item in rows)
    terminal = Counter(
        item.terminal_failure_class
        for item in rows
        if item.terminal_failure_class is not None
    )
    scoreable_questions = [
        question
        for question in questions
        if _mode_score(matrix[question][(condition, 1)], mode).result is not None
    ]
    reliability = Counter()
    for question in scoreable_questions:
        correct = sum(
            _outcome(matrix[question][(condition, repetition)], mode) == "correct"
            for repetition in REPETITIONS
        )
        reliability[f"pass_{correct}"] += 1
    denominator = len(scoreable)
    pass_3 = reliability["pass_3"]
    flips = reliability["pass_1"] + reliability["pass_2"]
    return {
        "content_refusal_rate": None,
        "correct": outcomes["correct"],
        "correctness_flip_count": flips,
        "correctness_flip_rate": _ratio(flips, len(scoreable_questions)),
        "error_rate": _ratio(generation["errored"], len(rows)),
        "generation_outcomes": dict(sorted(generation.items())),
        "insufficient_context_rate": None,
        "mean_accuracy": _ratio(outcomes["correct"], denominator),
        "pass_0_count": reliability["pass_0"],
        "pass_1_count": reliability["pass_1"],
        "pass_2_count": reliability["pass_2"],
        "pass_3_count": pass_3,
        "pass_3_rate": _ratio(pass_3, len(scoreable_questions)),
        "per_repetition_accuracy": {
            str(repetition): _condition_estimator(
                matrix, questions, condition, (repetition,), mode
            )
            for repetition in REPETITIONS
        },
        "refused_or_error": outcomes["refused_or_error"],
        "refused_or_error_rate": _ratio(outcomes["refused_or_error"], denominator),
        "scheduled_attempts": len(rows),
        "scoreable_attempts": denominator,
        "scoreable_questions": len(scoreable_questions),
        "terminal_failure_classes": dict(sorted(terminal.items())),
        "refusal_subtype_status": "not_observable_from_frozen_generation_contract",
        "unscorable_attempts": len(rows) - denominator,
        "wrong_answer": outcomes["wrong_answer"],
        "wrong_rate": _ratio(outcomes["wrong_answer"], denominator),
    }


def _outcome(attempt: SealedScoredAttempt, mode: ScoringMode) -> str | None:
    score = _mode_score(attempt, mode)
    return None if score.result is None else score.result.outcome


def _condition_estimator(
    matrix: Mapping[str, Mapping[tuple[str, int], SealedScoredAttempt]],
    questions: Sequence[str],
    condition: str,
    repetitions: Sequence[int],
    mode: ScoringMode,
) -> float:
    values = [
        _outcome(matrix[question][(condition, repetition)], mode) == "correct"
        for question in questions
        for repetition in repetitions
        if _outcome(matrix[question][(condition, repetition)], mode) is not None
    ]
    if not values:
        raise SealedResultError("endpoint has no scoreable observations")
    return sum(values) / len(values)


def _contrast_report(
    matrix: Mapping[str, Mapping[tuple[str, int], SealedScoredAttempt]],
    questions: Sequence[str],
    after: str,
    before: str,
    mode: ScoringMode,
) -> dict[str, Any]:
    def estimator(sampled: Sequence[str]) -> float:
        differences = []
        for question in sampled:
            for repetition in REPETITIONS:
                after_value = _outcome(matrix[question][(after, repetition)], mode)
                before_value = _outcome(matrix[question][(before, repetition)], mode)
                if after_value is None or before_value is None:
                    continue
                differences.append(
                    int(after_value == "correct") - int(before_value == "correct")
                )
        if not differences:
            raise SealedResultError("paired contrast has no scoreable observations")
        return sum(differences) / len(differences)

    gains = losses = 0
    for question in questions:
        for repetition in REPETITIONS:
            after_value = _outcome(matrix[question][(after, repetition)], mode)
            before_value = _outcome(matrix[question][(before, repetition)], mode)
            gains += after_value == "correct" and before_value != "correct"
            losses += before_value == "correct" and after_value != "correct"
    report = _estimate_with_interval(matrix, questions, estimator, estimator(questions))
    report.update({"discordant_gains": gains, "discordant_losses": losses})
    return report


def _mcnemar_reports(
    matrix: Mapping[str, Mapping[tuple[str, int], SealedScoredAttempt]],
    questions: Sequence[str],
    mode: ScoringMode,
) -> dict[str, Any]:
    pairs = (
        ("C2-C1", "C2", "C1"),
        ("C3-C2", "C3", "C2"),
        ("C4-C1", "C4", "C1"),
        ("C4-C3", "C4", "C3"),
    )
    reports: dict[str, dict[str, Any]] = {}
    for label, after, before in pairs:
        gains = losses = 0
        for question in questions:
            after_value = _outcome(matrix[question][(after, 1)], mode)
            before_value = _outcome(matrix[question][(before, 1)], mode)
            gains += after_value == "correct" and before_value != "correct"
            losses += before_value == "correct" and after_value != "correct"
        reports[label] = {
            "discordant_gains": gains,
            "discordant_losses": losses,
            "exact_two_sided_p": _exact_binomial_two_sided(gains, losses),
            "holm_adjusted_p": None,
        }
    exploratory = ("C2-C1", "C3-C2", "C4-C3")
    ordered = sorted(exploratory, key=lambda label: reports[label]["exact_two_sided_p"])
    running = 0.0
    for index, label in enumerate(ordered):
        adjusted = min(
            1.0,
            (len(exploratory) - index) * reports[label]["exact_two_sided_p"],
        )
        running = max(running, adjusted)
        reports[label]["holm_adjusted_p"] = running
    return reports


def _exact_binomial_two_sided(gains: int, losses: int) -> float:
    discordant = gains + losses
    if discordant == 0:
        return 1.0
    tail = sum(
        math.comb(discordant, value) for value in range(min(gains, losses) + 1)
    ) / (2**discordant)
    return min(1.0, 2 * tail)


def _estimate_with_interval(
    matrix: Mapping[str, Mapping[tuple[str, int], SealedScoredAttempt]],
    questions: Sequence[str],
    estimator: Any,
    estimate: float,
) -> dict[str, float]:
    del matrix
    values = sorted(
        estimator(_bootstrap_sample(questions, replicate))
        for replicate in range(BOOTSTRAP_REPLICATES)
    )
    return {
        "estimate": estimate,
        "lower": values[max(0, math.ceil(0.025 * BOOTSTRAP_REPLICATES) - 1)],
        "upper": values[max(0, math.ceil(0.975 * BOOTSTRAP_REPLICATES) - 1)],
    }


def _bootstrap_sample(questions: Sequence[str], replicate: int) -> tuple[str, ...]:
    count = len(questions)
    return tuple(
        questions[
            int.from_bytes(
                hashlib.sha256(
                    f"{BOOTSTRAP_SEED}\0{replicate}\0{draw}".encode("utf-8")
                ).digest(),
                "big",
            )
            % count
        ]
        for draw in range(count)
    )


def _mode_score(attempt: SealedScoredAttempt, mode: ScoringMode) -> ModeAttemptScore:
    return attempt.official if mode is ScoringMode.OFFICIAL else attempt.sensitivity


def _scorer_version(mode: ScoringMode) -> str:
    return (
        OFFICIAL_SOFT_EX_VERSION
        if mode is ScoringMode.OFFICIAL
        else SENSITIVITY_SCORER_VERSION
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _digest(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SealedResultError(f"{description} must be a lowercase SHA-256")
    return value


def _workspace(value: Path) -> Path:
    absolute = Path(value).absolute()
    try:
        resolved = Path(value).resolve(strict=True)
    except OSError as error:
        raise SealedResultError("workspace is unavailable") from error
    if absolute != resolved or not resolved.is_dir() or resolved.is_symlink():
        raise SealedResultError("workspace must be a non-symlink directory")
    return resolved

#!/usr/bin/env python3
"""Build the identity-free per-question correctness matrix for the sealed frame.

Every headline number in ``RESULTS.md`` is an aggregate over 1,068 sealed
attempts. An outside reader can check the aggregates against each other, but
cannot recompute them, cannot re-run the paired tests, and cannot cluster the
bootstrap any way but the one we chose. This analyzer emits the matrix those
checks need: 89 questions by 4 conditions by 3 repetitions, under both frozen
scorers, with a database label per question so a reader can cluster on either
question or database.

What the matrix carries per cell is the scorer's own verdict, the terminal
outcome class the scorer recorded, and the terminal failure class the generation
side recorded. That third field is what makes a bounded reanalysis possible: an
attempt the provider killed on a spend cap and an attempt where the system
answered wrongly are both scored ``incorrect``, and no aggregate can tell them
apart. What the matrix does not carry is question text, gold SQL, gold results,
hidden annotations, emitted SQL, model identity, cost, or any question
identifier. Questions appear as opaque indices ``q01`` through
``q89``, assigned in sorted order of the committed sealed frame manifest. That
mapping is deliberately reproducible rather than obscured: split membership is
already public in ``data/manifests/sealed_mvp_ids.txt`` and the per-database
counts are already public in ``sealed_mvp_frame_metadata.json``, so hiding the
ordinal would cost auditability and protect nothing. What the manifests do not
publish, and this artifact does not add, is any link from a question to its
gold.

The script refuses to emit anything if the 24 source artifacts disagree about
the question set, the freeze lineage, or the scorer identity, or if the
generation records do not cover exactly the scored attempts, because a matrix
assembled across mismatched frames would be worse than no matrix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

CONDITIONS = ("C1", "C2", "C3", "C4")
REPETITIONS = (1, 2, 3)
SCORERS = ("official_soft_ex", "sensitivity")

#: Lineage fields that must agree across all 24 source artifacts. A matrix
#: assembled from two different freezes would silently mix evaluation frames.
_SHARED_LINEAGE_FIELDS = (
    "freeze_b_sha256",
    "generation_freeze_b_sha256",
    "plan_sha256",
    "release_sha256",
    "test_ids_sha256",
)

#: Outcome classes the sealed scorers emit. Anything else is a schema change we
#: want to hear about loudly rather than absorb into an "other" bucket.
_KNOWN_OUTCOMES = frozenset({"correct", "wrong_answer", "refused_or_error"})

#: Generation-record fields this analyzer is permitted to read. Everything else
#: on a sealed generation record - question text, emitted SQL, result hashes,
#: model identity, cost - stays out of the committed matrix.
_GENERATION_FIELDS = ("attempt_id", "terminal_failure_class")

#: Placeholder for an attempt that reached scoring without a terminal failure.
#: JSON nulls in a matrix cell read as missing data; this reads as measured.
_NO_TERMINAL_FAILURE = "none"


class CorrectnessMatrixError(ValueError):
    """Raised when the sealed score artifacts cannot yield a coherent matrix."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _question_id(attempt_id: str) -> str:
    """Extract the question identifier from ``sealed:<question>:<cond>:<rep>``."""

    parts = attempt_id.split(":")
    if len(parts) != 4 or parts[0] != "sealed" or not parts[1]:
        raise CorrectnessMatrixError(f"unexpected attempt id shape: {attempt_id!r}")
    return parts[1]


def load_database_labels(manifest: Path, question_ids: set[str]) -> dict[str, str]:
    """Map each sealed question to its database, reading only two public fields."""

    labels: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        instance_id = record.get("instance_id")
        if instance_id in question_ids:
            database = record.get("selected_database")
            if not isinstance(database, str) or not database:
                raise CorrectnessMatrixError(
                    f"{instance_id} carries no selected_database in {manifest}"
                )
            labels[instance_id] = database
    missing = sorted(question_ids - set(labels))
    if missing:
        raise CorrectnessMatrixError(
            f"{len(missing)} sealed questions absent from {manifest}: {missing[:3]}"
        )
    return labels


def load_terminal_failures(cohort_root: Path) -> dict[str, str]:
    """Read the terminal failure class of every sealed attempt, and nothing else.

    Only the two fields in ``_GENERATION_FIELDS`` are touched. The generation
    records also carry question text, emitted SQL, and model identity; none of
    that is read here and none of it reaches the committed matrix.
    """

    failures: dict[str, str] = {}
    for path in sorted(cohort_root.glob("*/generation.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            attempt_id = record[_GENERATION_FIELDS[0]]
            if attempt_id in failures:
                raise CorrectnessMatrixError(
                    f"duplicate generation record {attempt_id}"
                )
            failure = record.get(_GENERATION_FIELDS[1])
            failures[attempt_id] = (
                _NO_TERMINAL_FAILURE if failure is None else str(failure)
            )
    if not failures:
        raise CorrectnessMatrixError(f"no generation records under {cohort_root}")
    return failures


def load_arm(path: Path) -> dict[str, Any]:
    """Read one score artifact and index its attempts by question."""

    artifact = json.loads(path.read_text(encoding="utf-8"))
    attempts = artifact.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise CorrectnessMatrixError(f"{path} carries no attempts")

    outcomes: dict[str, str] = {}
    attempt_ids: dict[str, str] = {}
    for attempt in attempts:
        attempt_id = attempt["attempt_id"]
        question = _question_id(attempt_id)
        if question in outcomes:
            raise CorrectnessMatrixError(f"{path} repeats question {question}")
        outcome = attempt["outcome"]
        if outcome not in _KNOWN_OUTCOMES:
            raise CorrectnessMatrixError(f"{path} carries unknown outcome {outcome!r}")
        outcomes[question] = outcome
        attempt_ids[question] = attempt_id

    return {
        "attempt_ids": attempt_ids,
        "lineage": {field: artifact.get(field) for field in _SHARED_LINEAGE_FIELDS},
        "outcomes": outcomes,
        "scorer": artifact.get("scorer"),
        "sha256": _sha256(path),
    }


def _arm_path(score_root: Path, scorer: str, condition: str, repetition: int) -> Path:
    return score_root / scorer / f"{condition.lower()}-r{repetition}.score.json"


def build_matrix(
    score_root: Path, cohort_root: Path, eligible_manifest: Path
) -> dict[str, Any]:
    """Assemble the full matrix, refusing any inconsistency across the 24 arms."""

    arms: dict[tuple[str, str, int], dict[str, Any]] = {}
    for scorer in SCORERS:
        for condition in CONDITIONS:
            for repetition in REPETITIONS:
                path = _arm_path(score_root, scorer, condition, repetition)
                arms[scorer, condition, repetition] = load_arm(path)

    reference_key = (SCORERS[0], CONDITIONS[0], REPETITIONS[0])
    reference = arms[reference_key]
    questions = set(reference["outcomes"])
    for key, arm in arms.items():
        if set(arm["outcomes"]) != questions:
            raise CorrectnessMatrixError(f"{key} covers a different question set")
        if arm["lineage"] != reference["lineage"]:
            raise CorrectnessMatrixError(f"{key} disagrees on freeze lineage")

    # Both scorers read the same attempts. The terminal failure class is joined
    # through one scorer's attempt ids, so that has to be true rather than assumed.
    for condition in CONDITIONS:
        for repetition in REPETITIONS:
            expected = arms[SCORERS[0], condition, repetition]["attempt_ids"]
            for scorer in SCORERS[1:]:
                if arms[scorer, condition, repetition]["attempt_ids"] != expected:
                    raise CorrectnessMatrixError(
                        f"{scorer} scores different attempts than {SCORERS[0]} "
                        f"for {condition} r{repetition}"
                    )

    scorer_versions: dict[str, str] = {}
    for (scorer, _, _), arm in arms.items():
        identity = arm["scorer"] or {}
        version = identity.get("version")
        if identity.get("identity") != scorer or not version:
            raise CorrectnessMatrixError(f"{scorer} arm carries scorer {identity!r}")
        if scorer_versions.setdefault(scorer, version) != version:
            raise CorrectnessMatrixError(f"{scorer} arms disagree on scorer version")

    failures = load_terminal_failures(cohort_root)
    scored_ids = {
        attempt_id
        for arm in arms.values()
        for attempt_id in arm["attempt_ids"].values()
    }
    if not scored_ids <= set(failures):
        missing = sorted(scored_ids - set(failures))
        raise CorrectnessMatrixError(
            f"{len(missing)} scored attempts have no generation record: {missing[:3]}"
        )

    databases = load_database_labels(eligible_manifest, questions)
    ordered = sorted(questions)
    index_of = {
        question: f"q{position:02d}" for position, question in enumerate(ordered, 1)
    }

    rows = [
        {
            "database": databases[question],
            "question_index": index_of[question],
            "results": {
                scorer: {
                    condition: [
                        arms[scorer, condition, repetition]["outcomes"][question]
                        for repetition in REPETITIONS
                    ]
                    for condition in CONDITIONS
                }
                for scorer in SCORERS
            },
            "terminal_failure": {
                condition: [
                    failures[
                        arms[SCORERS[0], condition, repetition]["attempt_ids"][question]
                    ]
                    for repetition in REPETITIONS
                ]
                for condition in CONDITIONS
            },
        }
        for question in ordered
    ]

    return {
        "arm_sha256s": {
            f"{scorer}/{condition.lower()}-r{repetition}": arms[
                scorer, condition, repetition
            ]["sha256"]
            for scorer in SCORERS
            for condition in CONDITIONS
            for repetition in REPETITIONS
        },
        "artifact_kind": "sealed_correctness_matrix",
        "lineage": reference["lineage"],
        "question_index_rule": (
            "sorted order of data/manifests/sealed_mvp_ids.txt; the matrix carries"
            " no question identifier, question text, gold, or emitted SQL"
        ),
        "questions": rows,
        "repetitions": list(REPETITIONS),
        "scorer_versions": scorer_versions,
        "schema_version": 1,
    }


def summarize(matrix: dict[str, Any]) -> dict[str, Any]:
    """Recompute per-arm accuracy and outcome counts straight from the matrix.

    These are the numbers ``RESULTS.md`` reports. Emitting them beside the cells
    they come from lets a reader confirm the aggregates without trusting the
    scoring pipeline that produced them.
    """

    summary: dict[str, Any] = {}
    for scorer in SCORERS:
        per_scorer: dict[str, Any] = {}
        for condition in CONDITIONS:
            per_condition: dict[str, Any] = {}
            for offset, repetition in enumerate(REPETITIONS):
                outcomes = [
                    row["results"][scorer][condition][offset]
                    for row in matrix["questions"]
                ]
                correct = sum(1 for outcome in outcomes if outcome == "correct")
                per_condition[f"r{repetition}"] = {
                    "correct": correct,
                    "n": len(outcomes),
                    "percent": round(100.0 * correct / len(outcomes), 1),
                    "refused_or_error": sum(
                        1 for outcome in outcomes if outcome == "refused_or_error"
                    ),
                    "wrong_answer": sum(
                        1 for outcome in outcomes if outcome == "wrong_answer"
                    ),
                }
            pooled = [
                row["results"][scorer][condition][offset]
                for row in matrix["questions"]
                for offset in range(len(REPETITIONS))
            ]
            per_condition["pooled"] = {
                "correct": sum(1 for outcome in pooled if outcome == "correct"),
                "n": len(pooled),
                "percent": round(
                    100.0 * sum(1 for o in pooled if o == "correct") / len(pooled), 1
                ),
                "refused_or_error": sum(
                    1 for outcome in pooled if outcome == "refused_or_error"
                ),
                "wrong_answer": sum(1 for o in pooled if o == "wrong_answer"),
            }
            per_scorer[condition] = per_condition
        summary[scorer] = per_scorer

    failure_counts: dict[str, dict[str, int]] = {}
    for condition in CONDITIONS:
        counts: dict[str, int] = {}
        for row in matrix["questions"]:
            for failure in row["terminal_failure"][condition]:
                counts[failure] = counts.get(failure, 0) + 1
        failure_counts[condition] = dict(sorted(counts.items()))
    summary["terminal_failure_classes"] = failure_counts
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--score-root",
        type=Path,
        required=True,
        help="directory holding official_soft_ex/ and sensitivity/ score artifacts",
    )
    parser.add_argument(
        "--cohort-root",
        type=Path,
        required=True,
        help="directory holding the per-arm generation.jsonl records",
    )
    parser.add_argument(
        "--eligible-manifest",
        type=Path,
        default=Path("data/manifests/eligible_questions.jsonl"),
        help="public manifest supplying the question-to-database mapping",
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)

    matrix = build_matrix(
        arguments.score_root.resolve(strict=True),
        arguments.cohort_root.resolve(strict=True),
        arguments.eligible_manifest.resolve(strict=True),
    )
    matrix["arm_summary"] = summarize(matrix)

    content = (
        json.dumps(matrix, allow_nan=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    if arguments.output is not None:
        arguments.output.write_text(content, encoding="utf-8")
    else:
        print(content.rstrip("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Batch-boundary tests proving generation completes before sealed scoring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.autoresearch_metrics import ValidatedGenerationOutputs
from omni_benchmark.score_artifacts import (
    create_score_artifact,
    validate_score_artifact,
)
from omni_benchmark.sealed_batch import (
    FrozenGenerationAttempt,
    SealedBatchResult,
    SealedGoldRecord,
    score_completed_generation,
)
from omni_benchmark.sealed_scoring import ScoringMode, SealedQueryCase, score_query
from tests.execution_fixtures import SyntheticIsolationProvider


def _generation(attempt_id: str, sql: str = "SELECT x") -> FrozenGenerationAttempt:
    return FrozenGenerationAttempt(attempt_id=attempt_id, candidate_sql=sql)


def _gold(attempt_id: str, sql: str = "SELECT x") -> SealedGoldRecord:
    return SealedGoldRecord(
        attempt_id=attempt_id,
        database="public_fixture",
        gold_sql=sql,
        conditions={"decimal": -1, "order": False},
    )


def _final_ids() -> tuple[str, ...]:
    return tuple(f"run:q-{index}:C1:1" for index in range(1, 1_213))


def test_complete_generation_scores_both_policies_in_committed_order() -> None:
    ids = _final_ids()
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    result = score_completed_generation(
        generations=tuple(_generation(attempt_id) for attempt_id in reversed(ids)),
        gold_records=tuple(_gold(attempt_id) for attempt_id in ids),
        expected_attempt_ids=ids,
        provider=provider,
    )

    assert result.attempt_ids == ids
    assert len(result.scores(ScoringMode.OFFICIAL)) == 1_212
    assert all(
        score.outcome == "correct" for score in result.scores(ScoringMode.OFFICIAL)
    )
    assert result.score_records(ScoringMode.SENSITIVITY)[:2] == (
        {"attempt_id": ids[0], "outcome": "correct"},
        {"attempt_id": ids[1], "outcome": "correct"},
    )
    assert provider.events.count(("acquire", "public_fixture")) == 4_848


@pytest.mark.parametrize(
    ("generations", "gold_records", "message"),
    [
        (
            tuple(_generation(attempt_id) for attempt_id in _final_ids()[1:]),
            tuple(_gold(attempt_id) for attempt_id in _final_ids()),
            "generation attempt set",
        ),
        (
            tuple(_generation(attempt_id) for attempt_id in _final_ids()),
            tuple(_gold(attempt_id) for attempt_id in _final_ids()[1:]),
            "gold attempt set",
        ),
        (
            (_generation("run:q-1:C1:1"), _generation("run:q-1:C1:1")),
            (_gold("run:q-1:C1:1"), _gold("run:q-2:C4:3")),
            "duplicate generation",
        ),
    ],
)
def test_incomplete_or_duplicate_inputs_fail_before_database_acquisition(
    generations: tuple[FrozenGenerationAttempt, ...],
    gold_records: tuple[SealedGoldRecord, ...],
    message: str,
) -> None:
    ids = _final_ids()
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    with pytest.raises(ValueError, match=message):
        score_completed_generation(
            generations=generations,
            gold_records=gold_records,
            expected_attempt_ids=ids,
            provider=provider,
        )

    assert provider.events == []


def test_final_gate_requires_exactly_1212_attempts() -> None:
    attempt_id = "run:q-1:C1:1"
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    with pytest.raises(ValueError, match="1,212"):
        score_completed_generation(
            generations=(_generation(attempt_id),),
            gold_records=(_gold(attempt_id),),
            expected_attempt_ids=(attempt_id,),
            provider=provider,
        )

    assert provider.events == []


def test_every_case_is_validated_before_first_database_acquisition() -> None:
    ids = _final_ids()
    invalid_last = SealedGoldRecord(
        attempt_id=ids[-1],
        database="public_fixture",
        gold_sql="SELECT x",
        conditions={"decimal": 7, "order": False},
    )
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    with pytest.raises(ValueError, match="conditions.decimal"):
        score_completed_generation(
            generations=tuple(_generation(attempt_id) for attempt_id in ids),
            gold_records=tuple(_gold(attempt_id) for attempt_id in ids[:-1])
            + (invalid_last,),
            expected_attempt_ids=ids,
            provider=provider,
        )

    assert provider.events == []


def test_private_sql_is_absent_from_batch_input_repr_and_output() -> None:
    attempt_id = "run:q-1:C1:1"
    generation = _generation(attempt_id, "SELECT 'candidate-private'")
    gold = _gold(attempt_id, "SELECT 'gold-private'")

    assert "candidate-private" not in repr(generation)
    assert "gold-private" not in repr(gold)


def test_batch_scores_bind_to_existing_immutable_score_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    attempt_id = "run:q-1:C1:1"
    generation_store = ArtifactStore(workspace, Path("runs/final"))
    stored_generation = generation_store.write_jsonl(
        Path("generation.jsonl"),
        [{"attempt_id": attempt_id, "generated_sql": "SELECT 1"}],
    )
    generation = ValidatedGenerationOutputs(
        path=stored_generation.path,
        sha256=stored_generation.sha256,
        question_count=1,
        scope="train",
        condition="C1",
        run_id="run",
        repetition=1,
    )
    provider = SyntheticIsolationProvider({"SELECT 1": [(1,)]})
    score = score_query(
        SealedQueryCase(
            database="public_fixture",
            candidate_sql="SELECT 1",
            gold_sql="SELECT 1",
            conditions={"decimal": -1, "order": False},
        ),
        ScoringMode.OFFICIAL,
        provider,
    )
    batch = SealedBatchResult(
        attempt_ids=(attempt_id,),
        official=(score,),
        sensitivity=(score,),
    )
    scorer_result = batch.scores(ScoringMode.OFFICIAL)[0]

    stored_score = create_score_artifact(
        workspace,
        generation=generation,
        destination=Path("runs/final/official-score.json"),
        scorer_identity=scorer_result.scorer_identity,
        scorer_version=scorer_result.scorer_version,
        scores=batch.score_records(ScoringMode.OFFICIAL),
    )
    validated = validate_score_artifact(
        workspace,
        generation=generation,
        score_path=stored_score.path,
        expected_score_sha256=stored_score.sha256,
    )

    assert validated.correct_count == 1
    payload = json.loads(stored_score.path.read_text(encoding="utf-8"))
    assert "gold_sql" not in payload
    assert "generated_sql" not in payload

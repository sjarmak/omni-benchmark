"""Batch-boundary tests proving generation completes before sealed scoring."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.autoresearch_metrics import ValidatedGenerationOutputs
from omni_benchmark.score_artifacts import (
    create_score_artifact,
    validate_score_artifact,
)
from omni_benchmark.freeze_b import FreezeBManifest, SealedRunManifest, schedule_sha256
from omni_benchmark.scoring import scorer_metadata
from omni_benchmark.sealed_batch import (
    FrozenGenerationAttempt,
    SealedBatchResult,
    SealedGoldRecord,
    score_completed_generation,
)
from omni_benchmark.sealed_scoring import ScoringMode, SealedQueryCase, score_query
from tests.execution_fixtures import SyntheticIsolationProvider


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
COMMIT = "f" * 40


def _condition(condition: str) -> dict[str, object]:
    harness_sha = {
        "C1": SHA_A,
        "C2": SHA_B,
        "C3": SHA_C,
        "C4": SHA_D,
    }[condition]
    return {
        "budget_id": "sealed-default-v1",
        "condition": condition,
        "harness_config_sha256": harness_sha,
        "instructions_sha256": SHA_B,
        "model": "managed-standard",
        "model_config_id": "frozen-final-v1",
        "prompt_sha256": SHA_C,
        "provider": "aws-bedrock",
        "runtime_policy_sha256": SHA_D,
        "semantic_model_ref": "none" if condition == "C1" else "export:final-v1",
        "semantic_model_sha256": None if condition == "C1" else SHA_E,
    }


def _freeze(ids: tuple[str, ...]) -> FreezeBManifest:
    return FreezeBManifest.from_dict(
        {
            "conditions": [
                _condition(condition) for condition in ("C1", "C2", "C3", "C4")
            ],
            "database": {
                "libpq_version": "18.6",
                "postgresql_version": "18.6",
                "snapshot_manifest_sha256": SHA_A,
            },
            "expected_test_outputs": 1_212,
            "freeze_a_commit": "1" * 40,
            "frozen_files": {"EVALUATION_PROTOCOL.md": SHA_A},
            "kind": "freeze-b-manifest",
            "question_count": 101,
            "recorded_at": "2026-08-29T05:30:00Z",
            "repetitions": 3,
            "schedule": {
                "algorithm": "committed_block_interleaved_v1",
                "seed": "human-supplied-final-seed",
                "sha256": schedule_sha256(ids),
            },
            "schema_version": 1,
            "scorer": {"metadata": scorer_metadata(), "source_commit": COMMIT},
            "system_commit": COMMIT,
        }
    )


def _run_manifests(freeze: FreezeBManifest) -> tuple[SealedRunManifest, ...]:
    result = []
    for condition_name in ("C1", "C2", "C3", "C4"):
        condition = freeze.condition(condition_name)
        for repetition in (1, 2, 3):
            result.append(
                SealedRunManifest.from_dict(
                    {
                        "budget_id": condition.budget_id,
                        "cli_versions": {"omni": "1.1.2"},
                        "condition": condition_name,
                        "finished_at": "2026-08-29T06:02:00Z",
                        "freeze_b_sha256": freeze.sha256(),
                        "generation_sha256": hashlib.sha256(
                            f"{condition_name}:{repetition}".encode()
                        ).hexdigest(),
                        "harness_config_sha256": condition.harness_config_sha256,
                        "instructions_sha256": condition.instructions_sha256,
                        "kind": "sealed-run-manifest",
                        "model": condition.model,
                        "model_config_id": condition.model_config_id,
                        "prompt_sha256": condition.prompt_sha256,
                        "provider": condition.provider,
                        "question_count": 101,
                        "repetition": repetition,
                        "runtime_policy_sha256": condition.runtime_policy_sha256,
                        "schedule_sha256": freeze.schedule_sha256,
                        "schema_version": 1,
                        "scope": "test",
                        "semantic_model_ref": condition.semantic_model_ref,
                        "semantic_model_sha256": condition.semantic_model_sha256,
                        "software_versions": {
                            "omni-benchmark": "0.1.0",
                            "python": "3.11.15",
                        },
                        "started_at": "2026-08-29T06:00:00Z",
                        "system_commit": freeze.system_commit,
                    },
                    freeze_b=freeze,
                )
            )
    return tuple(result)


def _generation(
    attempt_id: str,
    run_manifests: tuple[SealedRunManifest, ...],
    sql: str = "SELECT x",
) -> FrozenGenerationAttempt:
    _, condition, repetition_text = attempt_id.rsplit(":", 2)
    repetition = int(repetition_text)
    run = next(
        item
        for item in run_manifests
        if item.condition == condition and item.repetition == repetition
    )
    return FrozenGenerationAttempt(
        attempt_id=attempt_id,
        candidate_sql=sql,
        condition=condition,
        repetition=repetition,
        generation_sha256=run.generation_sha256,
        run_manifest_sha256=run.sha256(),
        generation_record_sha256=SHA_D,
    )


def _gold(attempt_id: str, sql: str = "SELECT x") -> SealedGoldRecord:
    return SealedGoldRecord(
        attempt_id=attempt_id,
        database="public_fixture",
        gold_sql=sql,
        conditions={"decimal": -1, "order": False},
    )


def _final_ids() -> tuple[str, ...]:
    return tuple(
        f"sealed:q-{question}:{condition}:{repetition}"
        for question in range(1, 102)
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    )


class _GoldMustRemainUnread(Sequence[SealedGoldRecord]):
    def __getitem__(self, index: int) -> SealedGoldRecord:
        raise AssertionError(f"gold was read at index {index}")

    def __len__(self) -> int:
        raise AssertionError("gold length was read")


def test_complete_generation_scores_both_policies_in_committed_order() -> None:
    ids = _final_ids()
    freeze = _freeze(ids)
    run_manifests = _run_manifests(freeze)
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    result = score_completed_generation(
        freeze_b=freeze,
        run_manifests=run_manifests,
        generations=tuple(
            _generation(attempt_id, run_manifests) for attempt_id in reversed(ids)
        ),
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


def _assert_provenance_rejected(
    message: str,
    *,
    freeze: FreezeBManifest,
    ids: tuple[str, ...],
    run_manifests: tuple[SealedRunManifest, ...],
    generations: tuple[FrozenGenerationAttempt, ...],
) -> None:
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    with pytest.raises(ValueError, match=message):
        score_completed_generation(
            freeze_b=freeze,
            run_manifests=run_manifests,
            generations=generations,
            gold_records=_GoldMustRemainUnread(),
            expected_attempt_ids=ids,
            provider=provider,
        )

    assert provider.events == []


def test_schedule_mismatch_fails_before_database_acquisition() -> None:
    ids = _final_ids()
    freeze = _freeze(tuple(reversed(ids)))
    run_manifests = _run_manifests(freeze)

    _assert_provenance_rejected(
        "schedule does not match Freeze B",
        freeze=freeze,
        ids=ids,
        run_manifests=run_manifests,
        generations=tuple(_generation(attempt_id, run_manifests) for attempt_id in ids),
    )


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing", "manifest set"),
        ("duplicate", "duplicate sealed run manifest"),
        ("config", "harness_config_sha256"),
        ("semantic", "semantic_model_sha256"),
    ],
)
def test_run_manifest_mismatch_fails_before_database_acquisition(
    case: str, message: str
) -> None:
    ids = _final_ids()
    freeze = _freeze(ids)
    valid = _run_manifests(freeze)
    if case == "missing":
        supplied = valid[:-1]
    elif case == "duplicate":
        supplied = valid + (valid[0],)
    elif case == "config":
        supplied = (replace(valid[0], harness_config_sha256=SHA_E),) + valid[1:]
    else:
        supplied = valid[:-1] + (replace(valid[-1], semantic_model_sha256=SHA_A),)

    _assert_provenance_rejected(
        message,
        freeze=freeze,
        ids=ids,
        run_manifests=supplied,
        generations=tuple(_generation(attempt_id, valid) for attempt_id in ids),
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("condition", "C2", "condition/repetition"),
        ("generation_sha256", SHA_A, "generation sha256"),
        ("run_manifest_sha256", SHA_A, "run_manifest_sha256"),
        ("generation_record_sha256", "A" * 64, "generation_record_sha256"),
    ],
)
def test_generation_provenance_mismatch_fails_before_database_acquisition(
    field: str, value: object, message: str
) -> None:
    ids = _final_ids()
    freeze = _freeze(ids)
    run_manifests = _run_manifests(freeze)
    generations = tuple(_generation(attempt_id, run_manifests) for attempt_id in ids)
    generations = (replace(generations[0], **{field: value}),) + generations[1:]

    _assert_provenance_rejected(
        message,
        freeze=freeze,
        ids=ids,
        run_manifests=run_manifests,
        generations=generations,
    )


@pytest.mark.parametrize("case", ["generation_missing", "gold_missing", "duplicate"])
def test_incomplete_or_duplicate_inputs_fail_before_database_acquisition(
    case: str,
) -> None:
    ids = _final_ids()
    freeze = _freeze(ids)
    run_manifests = _run_manifests(freeze)
    generations = tuple(_generation(attempt_id, run_manifests) for attempt_id in ids)
    gold_records = tuple(_gold(attempt_id) for attempt_id in ids)
    if case == "generation_missing":
        generations = generations[1:]
        message = "generation attempt set"
    elif case == "gold_missing":
        gold_records = gold_records[1:]
        message = "gold attempt set"
    else:
        generations = (generations[0], generations[0])
        gold_records = (_gold(ids[0]), _gold(ids[1]))
        message = "duplicate generation"
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    with pytest.raises(ValueError, match=message):
        score_completed_generation(
            freeze_b=freeze,
            run_manifests=run_manifests,
            generations=generations,
            gold_records=gold_records,
            expected_attempt_ids=ids,
            provider=provider,
        )

    assert provider.events == []


def test_final_gate_requires_exactly_1212_attempts() -> None:
    ids = _final_ids()
    freeze = _freeze(ids)
    run_manifests = _run_manifests(freeze)
    attempt_id = ids[0]
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    with pytest.raises(ValueError, match="1,212"):
        score_completed_generation(
            freeze_b=freeze,
            run_manifests=run_manifests,
            generations=(_generation(attempt_id, run_manifests),),
            gold_records=(_gold(attempt_id),),
            expected_attempt_ids=(attempt_id,),
            provider=provider,
        )

    assert provider.events == []


def test_every_case_is_validated_before_first_database_acquisition() -> None:
    ids = _final_ids()
    freeze = _freeze(ids)
    run_manifests = _run_manifests(freeze)
    invalid_last = SealedGoldRecord(
        attempt_id=ids[-1],
        database="public_fixture",
        gold_sql="SELECT x",
        conditions={"decimal": 7, "order": False},
    )
    provider = SyntheticIsolationProvider({"SELECT x": [(1,)]})

    with pytest.raises(ValueError, match="conditions.decimal"):
        score_completed_generation(
            freeze_b=freeze,
            run_manifests=run_manifests,
            generations=tuple(
                _generation(attempt_id, run_manifests) for attempt_id in ids
            ),
            gold_records=tuple(_gold(attempt_id) for attempt_id in ids[:-1])
            + (invalid_last,),
            expected_attempt_ids=ids,
            provider=provider,
        )

    assert provider.events == []


def test_private_sql_is_absent_from_batch_input_repr_and_output() -> None:
    ids = _final_ids()
    freeze = _freeze(ids)
    run_manifests = _run_manifests(freeze)
    attempt_id = ids[0]
    generation = _generation(attempt_id, run_manifests, "SELECT 'candidate-private'")
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

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.autoresearch_metrics import ValidatedGenerationOutputs
from omni_benchmark.score_artifacts import (
    ScoreArtifactError,
    create_score_artifact,
    validate_score_artifact,
)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return workspace


def _generation(
    workspace: Path,
    *,
    records: list[dict[str, object]] | None = None,
) -> ValidatedGenerationOutputs:
    generation_records = records or [
        {
            "attempt_id": "run-1:q-1:C4:1",
            "generated_sql": "SELECT 1",
            "instance_id": "q-1",
            "latency_ms": 120,
        },
        {
            "attempt_id": "run-1:q-2:C4:1",
            "generated_sql": "SELECT 2",
            "instance_id": "q-2",
            "latency_ms": 80,
        },
    ]
    stored = ArtifactStore(workspace, Path("runs/e01")).write_jsonl(
        Path("generation.jsonl"), generation_records
    )
    return ValidatedGenerationOutputs(
        path=stored.path,
        sha256=stored.sha256,
        question_count=len(generation_records),
        scope="dev-a",
        condition="C4",
        run_id="run-1",
        repetition=1,
    )


def _scores() -> list[dict[str, object]]:
    return [
        {"attempt_id": "run-1:q-1:C4:1", "outcome": "correct"},
        {
            "attempt_id": "run-1:q-2:C4:1",
            "failure_category": "aggregation_error",
            "outcome": "wrong_answer",
        },
    ]


def _create_valid_artifact(workspace: Path, generation: ValidatedGenerationOutputs):
    return create_score_artifact(
        workspace,
        generation=generation,
        destination=Path("runs/e01/scores.json"),
        scorer_identity="official_soft_ex",
        scorer_version="livesqlbench-soft-ex-e15cd221-v1",
        scores=_scores(),
    )


def test_score_artifact_is_minimal_private_and_hash_bound(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)

    stored = _create_valid_artifact(workspace, generation)
    payload = json.loads(stored.path.read_text(encoding="utf-8"))
    validated = validate_score_artifact(
        workspace,
        generation=generation,
        score_path=stored.path,
        expected_score_sha256=stored.sha256,
    )

    assert set(payload) == {"attempts", "generation", "schema_version", "scorer"}
    assert payload["schema_version"] == "score-artifact-v1"
    assert payload["generation"] == {
        "path": "runs/e01/generation.jsonl",
        "sha256": generation.sha256,
    }
    assert set(payload["attempts"][0]) == {
        "attempt_id",
        "generation_record_sha256",
        "outcome",
    }
    assert "generated_sql" not in stored.path.read_text(encoding="utf-8")
    assert "latency_ms" not in stored.path.read_text(encoding="utf-8")
    assert stat.S_IMODE(stored.path.stat().st_mode) == 0o600
    assert validated.generation_sha256 == generation.sha256
    assert validated.scorer_identity == "official_soft_ex"
    assert validated.correct_count == 1
    assert validated.wrong_answer_count == 1
    assert validated.refused_or_error_count == 0


@pytest.mark.parametrize(
    ("scores", "message"),
    [
        (
            [
                {"attempt_id": "run-1:q-1:C4:1", "outcome": "correct"},
                {"attempt_id": "run-1:q-1:C4:1", "outcome": "correct"},
            ],
            "duplicate score attempt_id",
        ),
        (
            [{"attempt_id": "run-1:q-1:C4:1", "outcome": "correct"}],
            "missing generation attempts",
        ),
        (
            _scores() + [{"attempt_id": "run-1:q-3:C4:1", "outcome": "correct"}],
            "unknown generation attempts",
        ),
    ],
)
def test_materialization_rejects_duplicate_missing_or_extra_attempts(
    tmp_path: Path,
    scores: list[dict[str, object]],
    message: str,
) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)

    with pytest.raises(ScoreArtifactError, match=message):
        create_score_artifact(
            workspace,
            generation=generation,
            destination=Path("runs/e01/invalid-scores.json"),
            scorer_identity="official_soft_ex",
            scorer_version="v1",
            scores=scores,
        )


def test_generation_mutation_is_detected_before_and_after_scoring(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    stored = _create_valid_artifact(workspace, generation)
    generation.path.write_text(
        generation.path.read_text(encoding="utf-8").replace("SELECT 2", "SELECT 9"),
        encoding="utf-8",
    )

    with pytest.raises(ScoreArtifactError, match="generation artifact changed"):
        create_score_artifact(
            workspace,
            generation=generation,
            destination=Path("runs/e01/post-mutation-scores.json"),
            scorer_identity="official_soft_ex",
            scorer_version="v1",
            scores=_scores(),
        )
    with pytest.raises(ScoreArtifactError, match="generation artifact changed"):
        validate_score_artifact(
            workspace,
            generation=generation,
            score_path=stored.path,
            expected_score_sha256=stored.sha256,
        )


def test_score_label_mutation_is_detected_against_recorded_hash(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    stored = _create_valid_artifact(workspace, generation)
    stored.path.write_text(
        stored.path.read_text(encoding="utf-8").replace(
            '"outcome":"correct"', '"outcome":"wrong_answer"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ScoreArtifactError, match="score artifact changed"):
        validate_score_artifact(
            workspace,
            generation=generation,
            score_path=stored.path,
            expected_score_sha256=stored.sha256,
        )


def test_validation_rejects_bad_per_attempt_hash_and_generation_attempt_set(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    stored = _create_valid_artifact(workspace, generation)
    payload = json.loads(stored.path.read_text(encoding="utf-8"))

    payload["attempts"][0]["generation_record_sha256"] = "0" * 64
    bad_hash = ArtifactStore(workspace, Path("runs/e01")).write_json(
        Path("bad-hash.json"), payload
    )
    with pytest.raises(ScoreArtifactError, match="generation record hash"):
        validate_score_artifact(
            workspace,
            generation=generation,
            score_path=bad_hash.path,
            expected_score_sha256=bad_hash.sha256,
        )

    payload = json.loads(stored.path.read_text(encoding="utf-8"))
    payload["attempts"].pop()
    missing = ArtifactStore(workspace, Path("runs/e01")).write_json(
        Path("missing-attempt.json"), payload
    )
    with pytest.raises(ScoreArtifactError, match="attempt set"):
        validate_score_artifact(
            workspace,
            generation=generation,
            score_path=missing.path,
            expected_score_sha256=missing.sha256,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"generated_sql": "SELECT 1"}, "unsupported field"),
        ({"outcome": "maybe"}, "outcome"),
        ({"failure_category": "x" * 81}, "failure_category"),
    ],
)
def test_score_records_have_an_exact_bounded_schema(
    tmp_path: Path,
    mutation: dict[str, object],
    message: str,
) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    scores = _scores()
    scores[0].update(mutation)

    with pytest.raises(ScoreArtifactError, match=message):
        create_score_artifact(
            workspace,
            generation=generation,
            destination=Path("runs/e01/unsupported.json"),
            scorer_identity="official_soft_ex",
            scorer_version="v1",
            scores=scores,
        )


def test_score_artifact_validation_rejects_payload_copy_and_duplicate_attempt(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    stored = _create_valid_artifact(workspace, generation)
    payload = json.loads(stored.path.read_text(encoding="utf-8"))
    payload["attempts"][0]["question"] = "copied question"
    copied = ArtifactStore(workspace, Path("runs/e01")).write_json(
        Path("copied-payload.json"), payload
    )

    with pytest.raises(ScoreArtifactError, match="unsupported field"):
        validate_score_artifact(
            workspace,
            generation=generation,
            score_path=copied.path,
            expected_score_sha256=copied.sha256,
        )

    payload = json.loads(stored.path.read_text(encoding="utf-8"))
    payload["attempts"][1]["attempt_id"] = payload["attempts"][0]["attempt_id"]
    duplicate = ArtifactStore(workspace, Path("runs/e01")).write_json(
        Path("duplicate-attempt.json"), payload
    )
    with pytest.raises(ScoreArtifactError, match="duplicate score attempt_id"):
        validate_score_artifact(
            workspace,
            generation=generation,
            score_path=duplicate.path,
            expected_score_sha256=duplicate.sha256,
        )


def test_generation_duplicate_attempts_are_rejected(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(
        workspace,
        records=[
            {"attempt_id": "same", "generated_sql": "SELECT 1"},
            {"attempt_id": "same", "generated_sql": "SELECT 2"},
        ],
    )

    with pytest.raises(ScoreArtifactError, match="duplicate generation attempt_id"):
        create_score_artifact(
            workspace,
            generation=generation,
            destination=Path("runs/e01/duplicate-generation.json"),
            scorer_identity="official_soft_ex",
            scorer_version="v1",
            scores=[{"attempt_id": "same", "outcome": "correct"}],
        )


def test_score_artifacts_require_ignored_confined_private_files(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    stored = _create_valid_artifact(workspace, generation)
    stored.path.chmod(0o644)

    with pytest.raises(ScoreArtifactError, match="mode 0600"):
        validate_score_artifact(
            workspace,
            generation=generation,
            score_path=stored.path,
            expected_score_sha256=stored.sha256,
        )
    with pytest.raises(ScoreArtifactError, match="ignored raw-run root"):
        create_score_artifact(
            workspace,
            generation=generation,
            destination=Path("docs/scores.json"),
            scorer_identity="official_soft_ex",
            scorer_version="v1",
            scores=_scores(),
        )


def test_score_artifact_validation_rejects_final_symlink(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    stored = _create_valid_artifact(workspace, generation)
    link = workspace / "runs" / "e01" / "score-link.json"
    link.symlink_to(stored.path)

    with pytest.raises(ScoreArtifactError, match="single-link regular file"):
        validate_score_artifact(
            workspace,
            generation=generation,
            score_path=link,
            expected_score_sha256=stored.sha256,
        )


def test_non_string_outcome_is_rejected_as_invalid_input(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    scores = _scores()
    scores[0]["outcome"] = []

    with pytest.raises(ScoreArtifactError, match="outcome"):
        create_score_artifact(
            workspace,
            generation=generation,
            destination=Path("runs/e01/non-string-outcome.json"),
            scorer_identity="official_soft_ex",
            scorer_version="v1",
            scores=scores,
        )


def test_score_artifact_uses_existing_refusal_outcome_vocabulary(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    scores = _scores()
    scores[1] = {
        "attempt_id": "run-1:q-2:C4:1",
        "failure_category": "provider_error",
        "outcome": "refused_or_error",
    }
    stored = create_score_artifact(
        workspace,
        generation=generation,
        destination=Path("runs/e01/refusal-scores.json"),
        scorer_identity="official_soft_ex",
        scorer_version="v1",
        scores=scores,
    )

    validated = validate_score_artifact(
        workspace,
        generation=generation,
        score_path=stored.path,
        expected_score_sha256=stored.sha256,
    )

    assert validated.refused_or_error_count == 1


def test_sensitive_failure_category_never_persists(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    generation = _generation(workspace)
    scores = _scores()
    scores[0]["failure_category"] = "live-secret-value"

    with pytest.raises(ScoreArtifactError, match="sensitive content"):
        create_score_artifact(
            workspace,
            generation=generation,
            destination=Path("runs/e01/sensitive.json"),
            scorer_identity="official_soft_ex",
            scorer_version="v1",
            scores=scores,
            environment={"OMNI_API_TOKEN": "live-secret-value"},
        )
    assert not (workspace / "runs" / "e01" / "sensitive.json").exists()

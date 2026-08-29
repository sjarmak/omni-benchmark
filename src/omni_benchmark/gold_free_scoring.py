"""Gold-free scorer plumbing exercise over repeated public dev-A results."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore, StoredArtifact
from .autoresearch_metrics import ValidatedGenerationOutputs
from .omni_result_adapter import (
    OmniResultContractError,
    decode_result_artifact_rows,
    reject_forbidden_keys,
)
from .score_artifacts import (
    ValidatedScoreArtifact,
    create_score_artifact,
    validate_score_artifact,
)
from .scoring import (
    OFFICIAL_SOFT_EX_VERSION,
    SENSITIVITY_SCORER_VERSION,
    official_soft_ex_equal,
    sensitivity_equal,
)

ORACLE_IDENTITY = "result_set_self_consistency_not_correctness"


class GoldFreeScoringError(ValueError):
    """Raised when public attempts cannot safely enter the plumbing exercise."""


@dataclass(frozen=True)
class GoldFreeScoringReceipt:
    """Hash-bound receipt for one two-repetition self-consistency exercise."""

    condition: str
    evidence: StoredArtifact
    instance_id: str
    left_result_sha256: str
    official_agreement: bool
    official_score: ValidatedScoreArtifact
    right_result_sha256: str
    sensitivity_agreement: bool
    sensitivity_score: ValidatedScoreArtifact

    def as_dict(self, workspace: Path) -> dict[str, object]:
        return {
            "condition": self.condition,
            "evidence_path": self.evidence.path.relative_to(workspace).as_posix(),
            "evidence_sha256": self.evidence.sha256,
            "instance_id": self.instance_id,
            "left_result_sha256": self.left_result_sha256,
            "official_agreement": self.official_agreement,
            "official_score_path": self.official_score.path.relative_to(
                workspace
            ).as_posix(),
            "official_score_sha256": self.official_score.sha256,
            "oracle": ORACLE_IDENTITY,
            "right_result_sha256": self.right_result_sha256,
            "sensitivity_agreement": self.sensitivity_agreement,
            "sensitivity_score_path": self.sensitivity_score.path.relative_to(
                workspace
            ).as_posix(),
            "sensitivity_score_sha256": self.sensitivity_score.sha256,
        }


@dataclass(frozen=True)
class _AttemptInput:
    attempt_id: str
    condition: str
    generation_bytes: bytes
    generation_sha256: str
    instance_id: str
    repetition: int
    result_bytes: bytes
    result_rows: tuple[tuple[Any, ...], ...]
    result_sha256: str
    run_id: str


def run_self_consistency_exercise(
    workspace: Path,
    *,
    left_generation: Path,
    left_result: Path,
    right_generation: Path,
    right_result: Path,
    output_root: Path,
) -> GoldFreeScoringReceipt:
    """Compare repeated dev-A results and bind agreement to score artifacts.

    The score artifact's ``correct`` label means only that the two repeated
    result sets agree under the named normalization policy. It is never a
    LiveSQLBench correctness judgment.
    """

    resolved_workspace = Path(workspace).resolve(strict=True)
    dev_a_ids = _dev_a_ids(resolved_workspace)
    left = _load_attempt(left_generation, left_result, dev_a_ids)
    right = _load_attempt(right_generation, right_result, dev_a_ids)
    _require_comparable(left, right)
    conditions = _public_conditions(resolved_workspace, left.instance_id)
    official_agreement = official_soft_ex_equal(
        left.result_rows, right.result_rows, conditions=conditions
    )
    sensitivity_agreement = sensitivity_equal(
        left.result_rows, right.result_rows, conditions=conditions
    )
    store = ArtifactStore(resolved_workspace, output_root, require_new_root=True)
    copied = _copy_inputs(store, left, right)
    generation = ValidatedGenerationOutputs(
        path=copied["left_generation"].path,
        sha256=copied["left_generation"].sha256,
        question_count=1,
        scope="dev-a",
        condition=left.condition,
        run_id=left.run_id,
        repetition=left.repetition,
    )
    official_score = _create_and_validate_score(
        resolved_workspace,
        generation,
        output_root / "official-score.json",
        identity="gold-free-self-consistency-official",
        version=OFFICIAL_SOFT_EX_VERSION,
        attempt_id=left.attempt_id,
        agreement=official_agreement,
    )
    sensitivity_score = _create_and_validate_score(
        resolved_workspace,
        generation,
        output_root / "sensitivity-score.json",
        identity="gold-free-self-consistency-sensitivity",
        version=SENSITIVITY_SCORER_VERSION,
        attempt_id=left.attempt_id,
        agreement=sensitivity_agreement,
    )
    evidence = store.write_json(
        Path("evidence.json"),
        _evidence_payload(
            left,
            right,
            conditions,
            official_agreement,
            sensitivity_agreement,
            copied,
            official_score,
            sensitivity_score,
        ),
    )
    return GoldFreeScoringReceipt(
        condition=left.condition,
        evidence=evidence,
        instance_id=left.instance_id,
        left_result_sha256=left.result_sha256,
        official_agreement=official_agreement,
        official_score=official_score,
        right_result_sha256=right.result_sha256,
        sensitivity_agreement=sensitivity_agreement,
        sensitivity_score=sensitivity_score,
    )


def _load_attempt(
    generation_path: Path, result_path: Path, dev_a_ids: frozenset[str]
) -> _AttemptInput:
    generation_bytes = Path(generation_path).read_bytes()
    lines = generation_bytes.splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise GoldFreeScoringError("generation artifact must contain one record")
    record = _object(lines[0], "generation artifact")
    reject_forbidden_keys(record)
    instance_id = _string(record, "instance_id")
    if instance_id not in dev_a_ids:
        raise GoldFreeScoringError("exercise inputs must belong to dev-A")
    if record.get("generation_outcome") != "answered":
        raise GoldFreeScoringError("exercise inputs must be answered attempts")
    if record.get("actual_result_status") != "complete":
        raise GoldFreeScoringError("exercise inputs must have complete results")
    result_bytes = Path(result_path).read_bytes()
    result_sha256 = hashlib.sha256(result_bytes).hexdigest()
    expected_result_hash = record.get("actual_result_hash")
    if expected_result_hash != result_sha256:
        raise GoldFreeScoringError(
            "generation result hash does not match result artifact"
        )
    result_value = _object(result_bytes, "result artifact")
    try:
        rows = decode_result_artifact_rows(result_value)
    except OmniResultContractError as error:
        raise GoldFreeScoringError(str(error)) from error
    repetition = record.get("repetition")
    if type(repetition) is not int or repetition < 1:
        raise GoldFreeScoringError("generation repetition is invalid")
    return _AttemptInput(
        attempt_id=_string(record, "attempt_id"),
        condition=_string(record, "condition"),
        generation_bytes=generation_bytes,
        generation_sha256=hashlib.sha256(generation_bytes).hexdigest(),
        instance_id=instance_id,
        repetition=repetition,
        result_bytes=result_bytes,
        result_rows=rows,
        result_sha256=result_sha256,
        run_id=_string(record, "run_id"),
    )


def _require_comparable(left: _AttemptInput, right: _AttemptInput) -> None:
    if left.instance_id != right.instance_id or left.condition != right.condition:
        raise GoldFreeScoringError("attempts must share instance_id and condition")
    if left.attempt_id == right.attempt_id:
        raise GoldFreeScoringError("attempts must have distinct attempt IDs")


def _copy_inputs(
    store: ArtifactStore, left: _AttemptInput, right: _AttemptInput
) -> dict[str, StoredArtifact]:
    return {
        "left_generation": store.write_bytes(
            Path("inputs/left/generation.jsonl"), left.generation_bytes
        ),
        "left_result": store.write_bytes(
            Path("inputs/left/answer.result.json"), left.result_bytes
        ),
        "right_generation": store.write_bytes(
            Path("inputs/right/generation.jsonl"), right.generation_bytes
        ),
        "right_result": store.write_bytes(
            Path("inputs/right/answer.result.json"), right.result_bytes
        ),
    }


def _create_and_validate_score(
    workspace: Path,
    generation: ValidatedGenerationOutputs,
    destination: Path,
    *,
    identity: str,
    version: str,
    attempt_id: str,
    agreement: bool,
) -> ValidatedScoreArtifact:
    stored = create_score_artifact(
        workspace,
        generation=generation,
        destination=destination,
        scorer_identity=identity,
        scorer_version=version,
        scores=[
            {
                "attempt_id": attempt_id,
                "outcome": "correct" if agreement else "wrong_answer",
            }
        ],
    )
    return validate_score_artifact(
        workspace,
        generation=generation,
        score_path=stored.path,
        expected_score_sha256=stored.sha256,
    )


def _evidence_payload(
    left: _AttemptInput,
    right: _AttemptInput,
    conditions: Mapping[str, Any],
    official_agreement: bool,
    sensitivity_agreement: bool,
    copied: Mapping[str, StoredArtifact],
    official_score: ValidatedScoreArtifact,
    sensitivity_score: ValidatedScoreArtifact,
) -> dict[str, object]:
    return {
        "condition": left.condition,
        "conditions": dict(conditions),
        "instance_id": left.instance_id,
        "interpretation": (
            "Score-artifact correct means repeated-result agreement only; "
            "this exercise does not estimate benchmark correctness."
        ),
        "inputs": {
            "left": _input_evidence(left, copied, "left"),
            "right": _input_evidence(right, copied, "right"),
        },
        "oracle": ORACLE_IDENTITY,
        "schema_version": 1,
        "scorers": {
            "official": {
                "agreement": official_agreement,
                "score_artifact_sha256": official_score.sha256,
                "version": OFFICIAL_SOFT_EX_VERSION,
            },
            "sensitivity": {
                "agreement": sensitivity_agreement,
                "score_artifact_sha256": sensitivity_score.sha256,
                "version": SENSITIVITY_SCORER_VERSION,
            },
        },
    }


def _input_evidence(
    attempt: _AttemptInput,
    copied: Mapping[str, StoredArtifact],
    side: str,
) -> dict[str, object]:
    return {
        "attempt_id": attempt.attempt_id,
        "generation_copy_sha256": copied[f"{side}_generation"].sha256,
        "generation_sha256": attempt.generation_sha256,
        "result_copy_sha256": copied[f"{side}_result"].sha256,
        "result_sha256": attempt.result_sha256,
        "row_count": len(attempt.result_rows),
        "run_id": attempt.run_id,
    }


def _dev_a_ids(workspace: Path) -> frozenset[str]:
    path = workspace / "data/manifests/dev_a_ids.txt"
    values = frozenset(
        line.strip() for line in path.read_text().splitlines() if line.strip()
    )
    if not values:
        raise GoldFreeScoringError("dev-A manifest is empty")
    return values


def _public_conditions(workspace: Path, instance_id: str) -> Mapping[str, Any]:
    path = workspace / "data/manifests/eligible_questions.jsonl"
    for line in path.read_bytes().splitlines():
        record = _object(line, "eligible question manifest")
        if record.get("instance_id") == instance_id:
            conditions = record.get("conditions")
            if not isinstance(conditions, Mapping):
                break
            return conditions
    raise GoldFreeScoringError("public scoring conditions are unavailable")


def _object(raw: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GoldFreeScoringError(f"{description} is invalid JSON") from error
    if not isinstance(value, dict):
        raise GoldFreeScoringError(f"{description} must be an object")
    return value


def _string(record: Mapping[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise GoldFreeScoringError(f"generation {field} is invalid")
    return value

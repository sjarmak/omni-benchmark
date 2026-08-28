"""Immutable score labels cryptographically bound to generation artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_store import (
    ALLOWED_RAW_ROOTS,
    MAX_ARTIFACT_BYTES,
    ArtifactStore,
    ArtifactStoreError,
    StoredArtifact,
    _is_gitignored,
)
from .autoresearch_config import AutoresearchError, _read_confined_private_bytes
from .autoresearch_metrics import ValidatedGenerationOutputs
from .content_policy import ContentPolicy
from .run_quarantine import is_quarantined_run, quarantined_attempt

SCORE_SCHEMA_VERSION = "score-artifact-v1"
MAX_SCORE_ARTIFACT_BYTES = 16 * 1024 * 1024
OUTCOMES = frozenset({"correct", "wrong_answer", "refused_or_error"})
TOP_LEVEL_FIELDS = frozenset({"attempts", "generation", "schema_version", "scorer"})
GENERATION_FIELDS = frozenset({"path", "sha256"})
SCORER_FIELDS = frozenset({"identity", "version"})
ATTEMPT_REQUIRED_FIELDS = frozenset(
    {"attempt_id", "generation_record_sha256", "outcome"}
)
ATTEMPT_OPTIONAL_FIELDS = frozenset({"failure_category"})
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")
FAILURE_CATEGORY_PATTERN = re.compile(r"[a-z][a-z0-9._-]{0,79}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ScoreArtifactError(ValueError):
    """Raised when score labels are not safely and exactly generation-bound."""


@dataclass(frozen=True)
class AttemptScore:
    """One validated outcome label and its immutable generation-record binding."""

    attempt_id: str
    generation_record_sha256: str
    outcome: str
    failure_category: str | None


@dataclass(frozen=True)
class ValidatedScoreArtifact:
    """Validated minimal score artifact metadata and outcomes."""

    path: Path
    sha256: str
    generation_path: Path
    generation_sha256: str
    scorer_identity: str
    scorer_version: str
    attempts: tuple[AttemptScore, ...]

    @property
    def correct_count(self) -> int:
        return sum(attempt.outcome == "correct" for attempt in self.attempts)

    @property
    def wrong_answer_count(self) -> int:
        return sum(attempt.outcome == "wrong_answer" for attempt in self.attempts)

    @property
    def refused_or_error_count(self) -> int:
        return sum(attempt.outcome == "refused_or_error" for attempt in self.attempts)


@dataclass(frozen=True)
class _GenerationRecordBinding:
    attempt_id: str
    sha256: str


@dataclass(frozen=True)
class _GenerationBinding:
    path: Path
    relative_path: str
    sha256: str
    records: tuple[_GenerationRecordBinding, ...]


@dataclass(frozen=True)
class _InputScore:
    attempt_id: str
    outcome: str
    failure_category: str | None


def create_score_artifact(
    workspace: Path,
    *,
    generation: ValidatedGenerationOutputs,
    destination: Path,
    scorer_identity: str,
    scorer_version: str,
    scores: Sequence[Mapping[str, Any]],
    environment: Mapping[str, str] | None = None,
) -> StoredArtifact:
    """Write a minimal, immutable score artifact for one frozen generation."""
    resolved_workspace = _resolved_workspace(workspace)
    binding = _generation_binding(resolved_workspace, generation)
    identity = _bounded_identifier(scorer_identity, "scorer identity")
    version = _bounded_identifier(scorer_version, "scorer version")
    scores_by_attempt = _input_scores_by_attempt(scores)
    expected_attempts = {record.attempt_id for record in binding.records}
    supplied_attempts = scores_by_attempt.keys()
    unknown = set(supplied_attempts) - expected_attempts
    if unknown:
        raise ScoreArtifactError("scores contain unknown generation attempts")
    missing = expected_attempts - set(supplied_attempts)
    if missing:
        raise ScoreArtifactError("scores are missing generation attempts")
    attempts = [
        _bound_attempt_payload(record, scores_by_attempt[record.attempt_id])
        for record in binding.records
    ]
    payload = {
        "attempts": attempts,
        "generation": {
            "path": binding.relative_path,
            "sha256": binding.sha256,
        },
        "schema_version": SCORE_SCHEMA_VERSION,
        "scorer": {"identity": identity, "version": version},
    }
    policy = ContentPolicy.from_environment(
        os.environ if environment is None else environment
    )
    if policy.sanitize_json(payload) != payload:
        raise ScoreArtifactError("score artifact contains sensitive content")
    score_path = _confined_raw_path(resolved_workspace, destination, "score artifact")
    try:
        store = ArtifactStore(
            resolved_workspace,
            score_path.parent.relative_to(resolved_workspace),
            environment=environment,
        )
        return store.write_json(Path(score_path.name), payload)
    except ArtifactStoreError as error:
        raise ScoreArtifactError(str(error)) from error


def validate_score_artifact(
    workspace: Path,
    *,
    generation: ValidatedGenerationOutputs,
    score_path: Path,
    expected_score_sha256: str,
    environment: Mapping[str, str] | None = None,
) -> ValidatedScoreArtifact:
    """Validate exact score schema and every file- and record-level hash binding."""
    resolved_workspace = _resolved_workspace(workspace)
    binding = _generation_binding(resolved_workspace, generation)
    resolved_score_path = _confined_raw_path(
        resolved_workspace, score_path, "score artifact"
    )
    content = _private_bytes(
        resolved_workspace,
        resolved_score_path,
        "score artifact",
        maximum_bytes=MAX_SCORE_ARTIFACT_BYTES,
    )
    if (
        not isinstance(expected_score_sha256, str)
        or SHA256_PATTERN.fullmatch(expected_score_sha256) is None
    ):
        raise ScoreArtifactError("expected_score_sha256 must be a SHA-256 digest")
    score_sha256 = hashlib.sha256(content).hexdigest()
    if score_sha256 != expected_score_sha256:
        raise ScoreArtifactError("score artifact changed after its hash was recorded")
    value = _json_object(content, "score artifact")
    policy = ContentPolicy.from_environment(
        os.environ if environment is None else environment
    )
    if policy.sanitize_json(value) != value:
        raise ScoreArtifactError("score artifact contains sensitive content")
    attempts, identity, version = _validate_payload(value, binding)
    return ValidatedScoreArtifact(
        path=resolved_score_path,
        sha256=score_sha256,
        generation_path=binding.path,
        generation_sha256=binding.sha256,
        scorer_identity=identity,
        scorer_version=version,
        attempts=attempts,
    )


def _resolved_workspace(workspace: Path) -> Path:
    try:
        return Path(workspace).resolve(strict=True)
    except OSError as error:
        raise ScoreArtifactError("workspace does not exist") from error


def _confined_raw_path(workspace: Path, path: Path, description: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        relative = candidate.relative_to(workspace)
    except ValueError as error:
        raise ScoreArtifactError(
            f"{description} must resolve inside workspace"
        ) from error
    if not relative.parts or ".." in relative.parts:
        raise ScoreArtifactError(f"{description} must resolve inside workspace")
    if not any(relative.is_relative_to(root) for root in ALLOWED_RAW_ROOTS):
        raise ScoreArtifactError(f"{description} must use an ignored raw-run root")
    if not _is_gitignored(workspace, relative):
        raise ScoreArtifactError(f"{description} must be gitignored")
    return candidate


def _private_bytes(
    workspace: Path,
    path: Path,
    description: str,
    *,
    maximum_bytes: int,
) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ScoreArtifactError(f"cannot read {description}") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ScoreArtifactError(f"{description} must be a single-link regular file")
    try:
        return _read_confined_private_bytes(
            workspace,
            path,
            description,
            maximum_bytes=maximum_bytes,
        )
    except AutoresearchError as error:
        raise ScoreArtifactError(str(error)) from error


def _generation_binding(
    workspace: Path, generation: ValidatedGenerationOutputs
) -> _GenerationBinding:
    if is_quarantined_run(generation.run_id):
        raise ScoreArtifactError("generation run is quarantined and non-scoreable")
    path = _confined_raw_path(workspace, generation.path, "generation artifact")
    content = _private_bytes(
        workspace,
        path,
        "generation artifact",
        maximum_bytes=MAX_ARTIFACT_BYTES,
    )
    current_sha256 = hashlib.sha256(content).hexdigest()
    if current_sha256 != generation.sha256:
        raise ScoreArtifactError("generation artifact changed after validation")
    records = _generation_record_bindings(content)
    if len(records) != generation.question_count:
        raise ScoreArtifactError("generation artifact record count changed")
    return _GenerationBinding(
        path=path,
        relative_path=path.relative_to(workspace).as_posix(),
        sha256=current_sha256,
        records=records,
    )


def _generation_record_bindings(
    content: bytes,
) -> tuple[_GenerationRecordBinding, ...]:
    bindings: list[_GenerationRecordBinding] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(content.splitlines(keepends=True), start=1):
        if not raw_line.strip():
            raise ScoreArtifactError(
                f"generation artifact contains a blank line at {line_number}"
            )
        record = _json_object(raw_line, f"generation artifact line {line_number}")
        attempt_id = _bounded_identifier(record.get("attempt_id"), "attempt_id")
        if quarantined_attempt(attempt_id):
            raise ScoreArtifactError("generation run is quarantined and non-scoreable")
        if attempt_id in seen:
            raise ScoreArtifactError(
                "generation artifact has duplicate generation attempt_id"
            )
        seen.add(attempt_id)
        bindings.append(
            _GenerationRecordBinding(
                attempt_id=attempt_id,
                sha256=hashlib.sha256(raw_line).hexdigest(),
            )
        )
    if not bindings:
        raise ScoreArtifactError("generation artifact is empty")
    return tuple(bindings)


def _input_scores_by_attempt(
    scores: Sequence[Mapping[str, Any]],
) -> dict[str, _InputScore]:
    if isinstance(scores, (str, bytes)) or not isinstance(scores, Sequence):
        raise ScoreArtifactError("scores must be a sequence of objects")
    by_attempt: dict[str, _InputScore] = {}
    for score in scores:
        validated = _validate_attempt_input(score)
        if validated.attempt_id in by_attempt:
            raise ScoreArtifactError("scores contain a duplicate score attempt_id")
        by_attempt[validated.attempt_id] = validated
    return by_attempt


def _validate_attempt_input(score: Mapping[str, Any]) -> _InputScore:
    if not isinstance(score, Mapping):
        raise ScoreArtifactError("each score must be an object")
    required = frozenset({"attempt_id", "outcome"})
    optional = frozenset({"failure_category"})
    if required - score.keys():
        raise ScoreArtifactError("score record is missing a required field")
    if score.keys() - required - optional:
        raise ScoreArtifactError("score record contains an unsupported field")
    attempt_id = _bounded_identifier(score["attempt_id"], "attempt_id")
    outcome = score["outcome"]
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        raise ScoreArtifactError("score outcome is invalid")
    failure_category = _failure_category(score.get("failure_category"))
    return _InputScore(
        attempt_id=attempt_id,
        failure_category=failure_category,
        outcome=outcome,
    )


def _bound_attempt_payload(
    record: _GenerationRecordBinding, score: _InputScore
) -> dict[str, str]:
    payload = {
        "attempt_id": record.attempt_id,
        "generation_record_sha256": record.sha256,
        "outcome": score.outcome,
    }
    failure_category = score.failure_category
    if failure_category is not None:
        payload["failure_category"] = failure_category
    return payload


def _validate_payload(
    value: dict[str, Any], binding: _GenerationBinding
) -> tuple[tuple[AttemptScore, ...], str, str]:
    if set(value) != TOP_LEVEL_FIELDS:
        raise ScoreArtifactError("score artifact has an unsupported top-level field")
    if value["schema_version"] != SCORE_SCHEMA_VERSION:
        raise ScoreArtifactError("score artifact schema_version is invalid")
    generation = value["generation"]
    if not isinstance(generation, dict) or set(generation) != GENERATION_FIELDS:
        raise ScoreArtifactError("score artifact generation binding is invalid")
    if generation["path"] != binding.relative_path:
        raise ScoreArtifactError("score artifact generation path does not match")
    if generation["sha256"] != binding.sha256:
        raise ScoreArtifactError("score artifact generation hash does not match")
    scorer = value["scorer"]
    if not isinstance(scorer, dict) or set(scorer) != SCORER_FIELDS:
        raise ScoreArtifactError("score artifact scorer identity is invalid")
    identity = _bounded_identifier(scorer["identity"], "scorer identity")
    version = _bounded_identifier(scorer["version"], "scorer version")
    attempts_value = value["attempts"]
    if not isinstance(attempts_value, list):
        raise ScoreArtifactError("score artifact attempts must be an array")
    attempts = tuple(_validate_bound_attempt(item) for item in attempts_value)
    attempt_ids = [attempt.attempt_id for attempt in attempts]
    if len(set(attempt_ids)) != len(attempt_ids):
        raise ScoreArtifactError("score artifact has a duplicate score attempt_id")
    expected = tuple(record.attempt_id for record in binding.records)
    if tuple(attempt_ids) != expected:
        raise ScoreArtifactError("score artifact attempt set does not match generation")
    for attempt, record in zip(attempts, binding.records, strict=True):
        if attempt.generation_record_sha256 != record.sha256:
            raise ScoreArtifactError(
                "score artifact generation record hash does not match"
            )
    return attempts, identity, version


def _validate_bound_attempt(value: Any) -> AttemptScore:
    if not isinstance(value, dict):
        raise ScoreArtifactError("score artifact attempt must be an object")
    fields = set(value)
    if (
        ATTEMPT_REQUIRED_FIELDS - fields
        or fields - ATTEMPT_REQUIRED_FIELDS - ATTEMPT_OPTIONAL_FIELDS
    ):
        raise ScoreArtifactError("score artifact attempt has an unsupported field")
    attempt_id = _bounded_identifier(value["attempt_id"], "attempt_id")
    record_sha256 = value["generation_record_sha256"]
    if (
        not isinstance(record_sha256, str)
        or SHA256_PATTERN.fullmatch(record_sha256) is None
    ):
        raise ScoreArtifactError("generation_record_sha256 must be a SHA-256 digest")
    outcome = value["outcome"]
    if not isinstance(outcome, str) or outcome not in OUTCOMES:
        raise ScoreArtifactError("score outcome is invalid")
    return AttemptScore(
        attempt_id=attempt_id,
        generation_record_sha256=record_sha256,
        outcome=outcome,
        failure_category=_failure_category(value.get("failure_category")),
    )


def _bounded_identifier(value: Any, description: str) -> str:
    if not isinstance(value, str) or IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ScoreArtifactError(f"{description} must be a bounded identifier")
    return value


def _failure_category(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or FAILURE_CATEGORY_PATTERN.fullmatch(value) is None:
        raise ScoreArtifactError("failure_category must be a bounded safe identifier")
    return value


def _json_object(content: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ScoreArtifactError(f"{description} is not valid UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ScoreArtifactError(f"{description} must be a JSON object")
    return value

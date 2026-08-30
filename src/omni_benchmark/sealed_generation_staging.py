"""Offline preparation and atomic staging for Freeze-B-bound generations."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .artifact_store import ALLOWED_RAW_ROOTS, ArtifactStore, ArtifactStoreError
from .content_policy import ContentPolicy
from .freeze_b import (
    CONDITIONS,
    FreezeBCondition,
    FreezeBError,
    FreezeBManifest,
    schedule_sha256,
)
from .protected_fields import ProtectedFieldError, reject_protected_fields
from .sealed_execution_plan import SealedExecutionPlan, SealedPlannedAttempt

SCHEDULE_PATH = "data/final-schedule.jsonl"
PUBLIC_MANIFEST_PATH = "data/manifests/eligible_questions.jsonl"

MAX_STAGED_ATTEMPT_BYTES = 16 * 1024 * 1024
STAGED_FILENAME = "attempt.json"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")
_PATH_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_AUTHORITY_KEY = secrets.token_bytes(32)
_SCORED_FIELDS = frozenset({"accuracy", "correctness", "outcome", "scored_outcome"})
_ENVELOPE_FIELDS = frozenset({"binding", "generation_record", "kind", "schema_version"})
_BINDING_FIELDS = frozenset(
    {
        "attempt_id",
        "cohort_id",
        "condition",
        "condition_binding_sha256",
        "control_commit",
        "database",
        "freeze_b_sha256",
        "instance_id",
        "plan_sha256",
        "question_sha256",
        "repetition",
        "schedule_sha256",
        "system_commit",
    }
)


class SealedGenerationStagingError(RuntimeError):
    """Raised when a planned attempt or staged output is not exactly bound."""


@dataclass(frozen=True)
class SealedPreparedAttempt:
    """One offline attempt bound to its plan, Freeze B, and public question."""

    attempt_id: str
    cohort_id: str
    condition: str
    database: str
    instance_id: str
    repetition: int
    question_sha256: str
    plan_sha256: str
    freeze_b_sha256: str
    schedule_sha256: str
    system_commit: str
    control_commit: str
    condition_binding: FreezeBCondition
    question: str = field(repr=False)
    _authorization: str = field(repr=False)

    def binding_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "cohort_id": self.cohort_id,
            "condition": self.condition,
            "condition_binding_sha256": _condition_sha256(self.condition_binding),
            "control_commit": self.control_commit,
            "database": self.database,
            "freeze_b_sha256": self.freeze_b_sha256,
            "instance_id": self.instance_id,
            "plan_sha256": self.plan_sha256,
            "question_sha256": self.question_sha256,
            "repetition": self.repetition,
            "schedule_sha256": self.schedule_sha256,
            "system_commit": self.system_commit,
        }


@dataclass(frozen=True)
class SealedStagedAttempt:
    """Private immutable capture with an SQL-free public summary."""

    prepared: SealedPreparedAttempt
    path: Path
    envelope_sha256: str
    generation_record_sha256: str
    generation_record_bytes: bytes = field(repr=False)
    candidate_sql: str | None = field(repr=False)
    already_present: bool = False

    def public_summary(self) -> dict[str, object]:
        return {
            "already_present": self.already_present,
            "envelope_sha256": self.envelope_sha256,
            "generation_record_sha256": self.generation_record_sha256,
            "plan_sha256": self.prepared.plan_sha256,
        }


def prepare_sealed_attempt(
    *,
    plan: SealedExecutionPlan,
    freeze_b: FreezeBManifest,
    attempt_id: str,
    question: str,
) -> SealedPreparedAttempt:
    """Bind one plan row to validated Freeze B and exact public question text."""
    validated_plan = _validated_plan(plan)
    validated_freeze = _validated_freeze(freeze_b)
    if (
        validated_plan.freeze_b_sha256 != validated_freeze.sha256()
        or validated_plan.schedule_sha256 != validated_freeze.schedule_sha256
        or validated_plan.system_commit != validated_freeze.system_commit
    ):
        raise SealedGenerationStagingError("sealed plan does not match Freeze B")
    frozen = dict(validated_freeze.frozen_files)
    expected_frozen = {
        SCHEDULE_PATH: validated_plan.schedule_file_sha256,
        PUBLIC_MANIFEST_PATH: validated_plan.public_manifest_sha256,
    }
    if (
        any(frozen.get(path) != digest for path, digest in expected_frozen.items())
        or validated_plan.test_ids_sha256 not in frozen.values()
    ):
        raise SealedGenerationStagingError(
            "sealed plan public inputs do not match Freeze B"
        )
    matches = tuple(
        item for item in validated_plan.attempts if item.attempt_id == attempt_id
    )
    if len(matches) != 1:
        raise SealedGenerationStagingError(
            "sealed attempt identity is absent or duplicated"
        )
    planned = matches[0]
    if not isinstance(question, str) or not question:
        raise SealedGenerationStagingError("public question is invalid")
    policy = ContentPolicy.from_environment(os.environ)
    if (
        not policy.query_is_safe(question)
        or hashlib.sha256(question.encode()).hexdigest() != planned.question_sha256
    ):
        raise SealedGenerationStagingError(
            "public question does not match the sealed plan"
        )
    condition = validated_freeze.condition(planned.condition)
    prepared = SealedPreparedAttempt(
        attempt_id=planned.attempt_id,
        cohort_id=planned.cohort_id,
        condition=planned.condition,
        database=planned.database,
        instance_id=planned.instance_id,
        repetition=planned.repetition,
        question_sha256=planned.question_sha256,
        plan_sha256=validated_plan.sha256,
        freeze_b_sha256=validated_freeze.sha256(),
        schedule_sha256=validated_freeze.schedule_sha256,
        system_commit=validated_freeze.system_commit,
        control_commit=validated_plan.control_commit,
        condition_binding=condition,
        question=question,
        _authorization="",
    )
    return replace(prepared, _authorization=_prepared_authorization(prepared))


class SealedAttemptRepository:
    """Atomically stage and reconcile one private envelope per planned attempt."""

    def __init__(self, workspace: Path, output_root: Path) -> None:
        absolute = workspace.absolute()
        try:
            resolved = workspace.resolve(strict=True)
        except OSError as error:
            raise SealedGenerationStagingError(
                "sealed artifact workspace is unavailable"
            ) from error
        if absolute != resolved or workspace.is_symlink() or not resolved.is_dir():
            raise SealedGenerationStagingError(
                "sealed artifact workspace must be a non-symlink directory"
            )
        root = Path(output_root)
        if root.is_absolute() or not root.parts or ".." in root.parts:
            raise SealedGenerationStagingError("sealed output root must be confined")
        if not any(root.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS):
            raise SealedGenerationStagingError(
                "sealed output root must be an ignored raw-run path"
            )
        self._workspace = resolved
        self._output_root = root
        self._validate_root()

    def attempt_path(self, prepared: SealedPreparedAttempt) -> Path:
        value = _validated_prepared(prepared)
        self._validate_root()
        return (
            self._workspace
            / self._output_root
            / value.database
            / value.condition.lower()
            / f"{value.instance_id}-r{value.repetition}"
            / STAGED_FILENAME
        )

    def require_workspace(self, workspace: Path) -> None:
        """Reject a finalizer configured for a different private workspace."""
        try:
            resolved = workspace.resolve(strict=True)
        except OSError as error:
            raise SealedGenerationStagingError(
                "sealed artifact workspace is unavailable"
            ) from error
        if resolved != self._workspace:
            raise SealedGenerationStagingError(
                "sealed attempt repository workspace does not match"
            )

    def stage(
        self, prepared: SealedPreparedAttempt, generation_record: Mapping[str, Any]
    ) -> SealedStagedAttempt:
        value = _validated_prepared(prepared)
        record = _validated_generation_record(value, generation_record)
        envelope = _envelope(value, record)
        content = _canonical_bytes(envelope)
        expected_digest = hashlib.sha256(content).hexdigest()
        path = self.attempt_path(value)
        if os.path.lexists(path):
            return self._existing_or_conflicting(value, content)
        relative_root = path.parent.relative_to(self._workspace)
        try:
            store = ArtifactStore(self._workspace, relative_root)
            store.write_bytes(Path(STAGED_FILENAME), content)
        except ArtifactStoreError:
            if os.path.lexists(path):
                return self._existing_or_conflicting(value, content)
            raise SealedGenerationStagingError(
                "sealed attempt could not be staged atomically"
            ) from None
        staged = self.reconcile(value)
        if staged is None or staged.envelope_sha256 != expected_digest:
            raise SealedGenerationStagingError(
                "staged sealed attempt failed immutable reconciliation"
            )
        return staged

    def reconcile(self, prepared: SealedPreparedAttempt) -> SealedStagedAttempt | None:
        value = _validated_prepared(prepared)
        path = self.attempt_path(value)
        if not os.path.lexists(path.parent):
            return None
        try:
            directory = path.parent
            metadata = directory.stat(follow_symlinks=False)
            if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise SealedGenerationStagingError(
                    "sealed attempt directory is invalid"
                )
            if (
                stat.S_IMODE(metadata.st_mode) != 0o700
                or metadata.st_uid != os.getuid()
            ):
                raise SealedGenerationStagingError(
                    "sealed attempt directory is not private"
                )
            entries = tuple(directory.iterdir())
            if entries != (path,):
                raise SealedGenerationStagingError(
                    "sealed attempt directory is incomplete or ambiguous"
                )
            content = _read_private_file(path)
            envelope = json.loads(content, parse_constant=_reject_constant)
            reject_protected_fields(envelope)
            _reject_scored_fields(envelope)
            if not isinstance(envelope, Mapping) or set(envelope) != _ENVELOPE_FIELDS:
                raise SealedGenerationStagingError(
                    "sealed attempt envelope schema is invalid"
                )
            if _canonical_bytes(envelope) != content:
                raise SealedGenerationStagingError(
                    "sealed attempt envelope must be canonical"
                )
            if (
                envelope["kind"] != "sealed-staged-attempt"
                or type(envelope["schema_version"]) is not int
                or envelope["schema_version"] != 1
            ):
                raise SealedGenerationStagingError(
                    "sealed attempt envelope metadata is invalid"
                )
            if envelope["binding"] != value.binding_dict():
                raise SealedGenerationStagingError(
                    "sealed attempt binding does not match the plan"
                )
            record = _validated_generation_record(value, envelope["generation_record"])
        except SealedGenerationStagingError:
            raise
        except (
            ArtifactStoreError,
            json.JSONDecodeError,
            OSError,
            ProtectedFieldError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as error:
            raise SealedGenerationStagingError(
                "existing sealed attempt is invalid"
            ) from error
        return _staged(value, path, content, record, already_present=False)

    def _existing_or_conflicting(
        self, prepared: SealedPreparedAttempt, expected_content: bytes
    ) -> SealedStagedAttempt:
        existing = self.reconcile(prepared)
        if (
            existing is None
            or existing.envelope_sha256 != hashlib.sha256(expected_content).hexdigest()
        ):
            raise SealedGenerationStagingError(
                "conflicting sealed attempt already exists"
            )
        return replace(existing, already_present=True)

    def _validate_root(self) -> None:
        candidate = self._workspace / self._output_root
        try:
            resolved = candidate.resolve(strict=False)
        except OSError as error:
            raise SealedGenerationStagingError(
                "sealed output root is unavailable"
            ) from error
        if resolved != candidate:
            raise SealedGenerationStagingError(
                "sealed output root must not contain a symlink"
            )


def _validated_plan(value: object) -> SealedExecutionPlan:
    if type(value) is not SealedExecutionPlan:
        raise SealedGenerationStagingError("validated sealed plan is required")
    if any(type(item) is not SealedPlannedAttempt for item in value.attempts):
        raise SealedGenerationStagingError("sealed plan attempt is invalid")
    if (
        len(value.attempts) != value.expected_test_outputs
        or len({item.attempt_id for item in value.attempts})
        != value.expected_test_outputs
    ):
        raise SealedGenerationStagingError("sealed plan is incomplete")
    try:
        ordered_schedule_sha256 = schedule_sha256(
            tuple(item.attempt_id for item in value.attempts)
        )
    except FreezeBError as error:
        raise SealedGenerationStagingError("sealed plan schedule is invalid") from error
    if ordered_schedule_sha256 != value.schedule_sha256:
        raise SealedGenerationStagingError("sealed plan schedule digest is invalid")
    for digest in (
        value.freeze_b_sha256,
        value.schedule_sha256,
        value.schedule_file_sha256,
        value.test_ids_sha256,
        value.public_manifest_sha256,
        value.sha256,
    ):
        if _SHA256.fullmatch(digest) is None:
            raise SealedGenerationStagingError("sealed plan digest is invalid")
    if (
        _COMMIT.fullmatch(value.system_commit) is None
        or _COMMIT.fullmatch(value.control_commit) is None
    ):
        raise SealedGenerationStagingError("sealed plan commit is invalid")
    return value


def _validated_freeze(value: object) -> FreezeBManifest:
    if type(value) is not FreezeBManifest:
        raise SealedGenerationStagingError("validated Freeze B is required")
    try:
        parsed = FreezeBManifest.from_dict(value.as_dict())
    except FreezeBError as error:
        raise SealedGenerationStagingError("Freeze B is invalid") from error
    if parsed != value:
        raise SealedGenerationStagingError("Freeze B is not canonical")
    return parsed


def _validated_prepared(value: object) -> SealedPreparedAttempt:
    if type(value) is not SealedPreparedAttempt:
        raise SealedGenerationStagingError("prepared sealed attempt is required")
    binding = value.binding_dict()
    if set(binding) != _BINDING_FIELDS:
        raise SealedGenerationStagingError("prepared sealed binding is invalid")
    if not isinstance(value._authorization, str) or not hmac.compare_digest(
        value._authorization, _prepared_authorization(value)
    ):
        raise SealedGenerationStagingError("prepared sealed binding is not authorized")
    for digest_field in (
        "freeze_b_sha256",
        "plan_sha256",
        "question_sha256",
        "schedule_sha256",
    ):
        if _SHA256.fullmatch(str(binding[digest_field])) is None:
            raise SealedGenerationStagingError("prepared sealed digest is invalid")
    if (
        _COMMIT.fullmatch(value.system_commit) is None
        or _COMMIT.fullmatch(value.control_commit) is None
        or value.condition not in CONDITIONS
        or type(value.repetition) is not int
        or value.repetition not in (1, 2, 3)
        or any(
            _IDENTIFIER.fullmatch(item) is None
            for item in (value.attempt_id, value.cohort_id)
        )
        or any(
            _PATH_COMPONENT.fullmatch(item) is None
            for item in (value.database, value.instance_id)
        )
        or value.attempt_id
        != f"sealed:{value.instance_id}:{value.condition}:{value.repetition}"
        or value.cohort_id != f"sealed-{value.condition.lower()}-r{value.repetition}"
        or value.condition_binding.condition != value.condition
        or not isinstance(value.question, str)
        or not value.question
        or hashlib.sha256(value.question.encode()).hexdigest() != value.question_sha256
    ):
        raise SealedGenerationStagingError("prepared sealed binding is invalid")
    return value


def _prepared_authorization(value: SealedPreparedAttempt) -> str:
    payload = _canonical_bytes(
        {
            "binding": value.binding_dict(),
            "condition": value.condition_binding.as_dict(),
            "question": value.question,
        }
    )
    return hmac.new(_AUTHORITY_KEY, payload, hashlib.sha256).hexdigest()


def _condition_sha256(value: FreezeBCondition) -> str:
    if type(value) is not FreezeBCondition:
        raise SealedGenerationStagingError(
            "prepared sealed condition binding is invalid"
        )
    return hashlib.sha256(_canonical_bytes(value.as_dict())).hexdigest()


def _validated_generation_record(
    prepared: SealedPreparedAttempt, supplied: object
) -> dict[str, Any]:
    if not isinstance(supplied, Mapping):
        raise SealedGenerationStagingError("sealed generation record must be an object")
    record = dict(supplied)
    try:
        reject_protected_fields(record)
    except ProtectedFieldError as error:
        raise SealedGenerationStagingError(str(error)) from error
    _reject_scored_fields(record)
    expected = {
        "attempt_id": prepared.attempt_id,
        "condition": prepared.condition,
        "instance_id": prepared.instance_id,
        "partition": "test",
        "question": prepared.question,
        "repetition": prepared.repetition,
        "run_id": prepared.cohort_id,
    }
    if (
        any(
            record.get(field) != expected_value
            for field, expected_value in expected.items()
        )
        or type(record.get("repetition")) is not int
    ):
        raise SealedGenerationStagingError(
            "sealed generation identity does not match the prepared attempt"
        )
    outcome = record.get("generation_outcome")
    failure = record.get("terminal_failure_class")
    failure_origin = record.get("failure_origin")
    if outcome not in {"answered", "refused", "errored"}:
        raise SealedGenerationStagingError("sealed generation outcome is invalid")
    if outcome == "answered":
        if failure is not None or failure_origin is not None:
            raise SealedGenerationStagingError(
                "sealed generation outcome and failure are inconsistent"
            )
    elif (
        not isinstance(failure, str)
        or not failure
        or failure_origin not in {"evaluated_system", "benchmark_infrastructure"}
    ):
        raise SealedGenerationStagingError(
            "sealed generation outcome and failure are inconsistent"
        )
    if failure_origin == "benchmark_infrastructure":
        raise SealedGenerationStagingError(
            "benchmark infrastructure failure is not a completed generation"
        )
    generated_sql = record.get("generated_sql")
    generated_query = record.get("generated_query")
    expected_output = generated_query if prepared.condition == "C4" else generated_sql
    forbidden_output = generated_sql if prepared.condition == "C4" else generated_query
    if forbidden_output is not None or (
        expected_output is not None
        and (not isinstance(expected_output, str) or not expected_output)
    ):
        raise SealedGenerationStagingError(
            "sealed candidate output does not match its condition lane"
        )
    if outcome == "answered" and expected_output is None:
        raise SealedGenerationStagingError(
            "answered sealed outcome requires a candidate output"
        )
    started_at = record.get("started_at")
    finished_at = record.get("finished_at")
    if any(
        not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None
        for value in (started_at, finished_at)
    ) or _parse_timestamp(finished_at) < _parse_timestamp(started_at):
        raise SealedGenerationStagingError("sealed generation timestamps are invalid")
    policy = ContentPolicy.from_environment(os.environ)
    if policy.sanitize_json(record) != record:
        raise SealedGenerationStagingError(
            "sealed generation record contains sensitive content"
        )
    try:
        _canonical_bytes(record)
    except (TypeError, ValueError) as error:
        raise SealedGenerationStagingError(
            "sealed generation record must contain finite JSON"
        ) from error
    return record


def _envelope(
    prepared: SealedPreparedAttempt, record: Mapping[str, Any]
) -> dict[str, object]:
    return {
        "binding": prepared.binding_dict(),
        "generation_record": dict(record),
        "kind": "sealed-staged-attempt",
        "schema_version": 1,
    }


def _staged(
    prepared: SealedPreparedAttempt,
    path: Path,
    content: bytes,
    record: Mapping[str, Any],
    *,
    already_present: bool,
) -> SealedStagedAttempt:
    output = (
        record.get("generated_query")
        if prepared.condition == "C4"
        else record.get("generated_sql")
    )
    return SealedStagedAttempt(
        prepared=prepared,
        path=path,
        envelope_sha256=hashlib.sha256(content).hexdigest(),
        generation_record_sha256=hashlib.sha256(
            _canonical_bytes(dict(record))
        ).hexdigest(),
        generation_record_bytes=_canonical_bytes(dict(record)),
        candidate_sql=output if isinstance(output, str) else None,
        already_present=already_present,
    )


def _read_private_file(path: Path) -> bytes:
    try:
        metadata = path.stat(follow_symlinks=False)
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
            or metadata.st_size > MAX_STAGED_ATTEMPT_BYTES
        ):
            raise SealedGenerationStagingError(
                "sealed attempt is not a private regular file"
            )
        content = path.read_bytes()
    except SealedGenerationStagingError:
        raise
    except OSError as error:
        raise SealedGenerationStagingError(
            "sealed attempt private file is invalid"
        ) from error
    if len(content) != metadata.st_size:
        raise SealedGenerationStagingError(
            "sealed attempt private file changed while reading"
        )
    return content


def _reject_scored_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _SCORED_FIELDS:
                raise SealedGenerationStagingError(f"scored field {key} is not allowed")
            _reject_scored_fields(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _reject_scored_fields(item)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _reject_constant(value: str) -> None:
    raise SealedGenerationStagingError(
        f"non-finite JSON constant is forbidden: {value}"
    )


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SealedGenerationStagingError(
            "sealed generation timestamps are invalid"
        ) from error

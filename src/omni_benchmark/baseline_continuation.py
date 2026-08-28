"""Auditable continuation of a baseline after authorized infrastructure failure."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any

from .baseline_batch import (
    BaselineAttempt,
    BaselineBatchError,
    BaselineSchedule,
    ImmutableAttemptRepository,
)
from .run_manifest import RunManifest, RunManifestError, UTC_TIMESTAMP_PATTERN

_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_AUTHORIZED_FAILURE_CLASS = "model_setup_error"
_ACTIONS = frozenset({"preserve", "rerun_infrastructure", "never_attempted"})
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ContinuationAuthorization:
    """Human-approved, result-independent infrastructure incident boundary."""

    authorization_id: str
    expected_invalidated_attempts: int
    finished_at_start: str
    finished_at_end: str
    terminal_failure_class: str

    def __post_init__(self) -> None:
        _identifier(self.authorization_id, "authorization ID")
        if (
            type(self.expected_invalidated_attempts) is not int
            or self.expected_invalidated_attempts < 1
        ):
            raise BaselineBatchError(
                "expected invalidated attempts must be a positive integer"
            )
        _utc_timestamp(self.finished_at_start, "incident start")
        _utc_timestamp(self.finished_at_end, "incident end")
        if _timestamp_lower(self.finished_at_end) < _timestamp_lower(
            self.finished_at_start
        ):
            raise BaselineBatchError("incident end precedes incident start")
        if self.terminal_failure_class != _AUTHORIZED_FAILURE_CLASS:
            raise BaselineBatchError(
                "continuation authorizes only the recorded OAuth setup failure class"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "authorization_id": self.authorization_id,
            "expected_invalidated_attempts": self.expected_invalidated_attempts,
            "finished_at_end": self.finished_at_end,
            "finished_at_start": self.finished_at_start,
            "terminal_failure_class": self.terminal_failure_class,
        }


@dataclass(frozen=True, slots=True)
class PredecessorEvidence:
    """Hash-bound evidence for one immutable original attempt."""

    adjudicated_failure_origin: str | None
    attempt_id: str
    finished_at: str
    generation_outcome: str
    generation_sha256: str
    recorded_failure_origin: str | None
    run_manifest_sha256: str
    started_at: str
    terminal_failure_class: str | None

    def __post_init__(self) -> None:
        _attempt_id(self.attempt_id)
        for value, name in (
            (self.generation_sha256, "generation SHA-256"),
            (self.run_manifest_sha256, "run-manifest SHA-256"),
        ):
            if _SHA256_PATTERN.fullmatch(value) is None:
                raise BaselineBatchError(f"predecessor {name} is invalid")
        _utc_timestamp(self.started_at, "predecessor start")
        _utc_timestamp(self.finished_at, "predecessor finish")
        if self.generation_outcome not in {"answered", "refused", "errored"}:
            raise BaselineBatchError("predecessor outcome is invalid")
        if self.recorded_failure_origin not in {
            None,
            "benchmark_infrastructure",
            "evaluated_system",
        }:
            raise BaselineBatchError("predecessor recorded failure origin is invalid")
        if self.adjudicated_failure_origin not in {None, "benchmark_infrastructure"}:
            raise BaselineBatchError(
                "predecessor adjudicated failure origin is invalid"
            )
        if self.terminal_failure_class is not None and not isinstance(
            self.terminal_failure_class, str
        ):
            raise BaselineBatchError("predecessor failure class is invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "adjudicated_failure_origin": self.adjudicated_failure_origin,
            "attempt_id": self.attempt_id,
            "finished_at": self.finished_at,
            "generation_outcome": self.generation_outcome,
            "generation_sha256": self.generation_sha256,
            "recorded_failure_origin": self.recorded_failure_origin,
            "run_manifest_sha256": self.run_manifest_sha256,
            "started_at": self.started_at,
            "terminal_failure_class": self.terminal_failure_class,
        }


@dataclass(frozen=True, slots=True)
class ContinuationEntry:
    """One source trial's single disposition in the continuation plan."""

    action: str
    condition: str
    continuation_attempt_id: str | None
    database: str
    instance_id: str
    predecessor: PredecessorEvidence | None
    repetition: int
    trial_key: str

    def __post_init__(self) -> None:
        if self.action not in _ACTIONS:
            raise BaselineBatchError("continuation action is invalid")
        for value, name in (
            (self.database, "database"),
            (self.instance_id, "instance ID"),
        ):
            _identifier(value, name)
        if self.condition not in {"C1", "C2", "C3"}:
            raise BaselineBatchError("continuation condition is invalid")
        if self.repetition != 1:
            raise BaselineBatchError("continuation repetition must be one")
        expected_key = f"{self.instance_id}:{self.condition}:{self.repetition}"
        if self.trial_key != expected_key:
            raise BaselineBatchError("continuation trial key is invalid")
        should_continue = self.action != "preserve"
        if should_continue != (self.continuation_attempt_id is not None):
            raise BaselineBatchError("continuation attempt identity is inconsistent")
        if self.continuation_attempt_id is not None:
            _attempt_id(self.continuation_attempt_id)
        has_predecessor = self.action != "never_attempted"
        if has_predecessor != (self.predecessor is not None):
            raise BaselineBatchError("continuation predecessor is inconsistent")
        if (
            self.action == "rerun_infrastructure"
            and self.predecessor is not None
            and self.predecessor.adjudicated_failure_origin
            != "benchmark_infrastructure"
        ):
            raise BaselineBatchError("rerun lacks infrastructure adjudication")
        if (
            self.action == "preserve"
            and self.predecessor is not None
            and self.predecessor.adjudicated_failure_origin is not None
        ):
            raise BaselineBatchError(
                "preserved attempt cannot be adjudicated for rerun"
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "condition": self.condition,
            "continuation_attempt_id": self.continuation_attempt_id,
            "database": self.database,
            "instance_id": self.instance_id,
            "predecessor": (
                None if self.predecessor is None else self.predecessor.as_dict()
            ),
            "repetition": self.repetition,
            "trial_key": self.trial_key,
        }


@dataclass(frozen=True, slots=True)
class ContinuationManifest:
    """Canonical plan that partitions every source trial exactly once."""

    authorization: ContinuationAuthorization
    continuation_run_id: str
    counts: Mapping[str, int]
    entries: tuple[ContinuationEntry, ...]
    original_run_id: str
    source_commit: str
    source_schedule_sha256: str
    kind: str = "public-baseline-infrastructure-continuation"
    schema_version: int = 1

    def __post_init__(self) -> None:
        _identifier(self.continuation_run_id, "continuation run ID")
        _identifier(self.original_run_id, "original run ID")
        if self.continuation_run_id == self.original_run_id:
            raise BaselineBatchError("continuation run ID must be fresh")
        if re.fullmatch(r"[0-9a-f]{40,64}", self.source_commit) is None:
            raise BaselineBatchError("continuation source commit is invalid")
        if _SHA256_PATTERN.fullmatch(self.source_schedule_sha256) is None:
            raise BaselineBatchError("continuation source schedule SHA-256 is invalid")
        expected_counts = {
            "never_attempted": sum(
                entry.action == "never_attempted" for entry in self.entries
            ),
            "preserved": sum(entry.action == "preserve" for entry in self.entries),
            "rerun_infrastructure": sum(
                entry.action == "rerun_infrastructure" for entry in self.entries
            ),
            "source_schedule": len(self.entries),
        }
        if self.counts != expected_counts:
            raise BaselineBatchError("continuation counts do not match entries")
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))
        trial_keys = tuple(entry.trial_key for entry in self.entries)
        if len(set(trial_keys)) != len(trial_keys):
            raise BaselineBatchError("continuation contains duplicate trial keys")
        continuation_ids = tuple(
            entry.continuation_attempt_id
            for entry in self.entries
            if entry.continuation_attempt_id is not None
        )
        if len(set(continuation_ids)) != len(continuation_ids):
            raise BaselineBatchError("continuation contains duplicate attempt IDs")
        if (
            expected_counts["rerun_infrastructure"]
            != self.authorization.expected_invalidated_attempts
        ):
            raise BaselineBatchError(
                "authorized invalidated attempt count does not match"
            )
        if self.kind != "public-baseline-infrastructure-continuation":
            raise BaselineBatchError("continuation kind is invalid")
        if self.schema_version != 1:
            raise BaselineBatchError("continuation schema version is invalid")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "authorization": self.authorization.as_dict(),
            "continuation_run_id": self.continuation_run_id,
            "counts": dict(sorted(self.counts.items())),
            "entries": [entry.as_dict() for entry in self.entries],
            "kind": self.kind,
            "original_run_id": self.original_run_id,
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "source_schedule_sha256": self.source_schedule_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_json(self.as_dict())


@dataclass(frozen=True, slots=True)
class ContinuationReconciliation:
    complete: bool
    completed_continuation_attempts: int
    missing_continuation_attempts: int
    preserved_attempts: int
    reconciled_trial_count: int
    source_schedule_attempts: int

    def as_dict(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "completed_continuation_attempts": self.completed_continuation_attempts,
            "missing_continuation_attempts": self.missing_continuation_attempts,
            "preserved_attempts": self.preserved_attempts,
            "reconciled_trial_count": self.reconciled_trial_count,
            "source_schedule_attempts": self.source_schedule_attempts,
        }


def build_continuation_manifest(
    schedule: BaselineSchedule,
    *,
    repository: ImmutableAttemptRepository,
    continuation_run_id: str,
    authorization: ContinuationAuthorization,
) -> ContinuationManifest:
    """Partition the source schedule without inspecting correctness outcomes."""
    _identifier(continuation_run_id, "continuation run ID")
    original_run_ids = {attempt.run_id for attempt in schedule.attempts}
    if len(original_run_ids) != 1:
        raise BaselineBatchError("source schedule must use one original run ID")
    original_run_id = next(iter(original_run_ids))
    entries = tuple(
        _build_entry(
            attempt,
            repository=repository,
            continuation_run_id=continuation_run_id,
            authorization=authorization,
            expected_commit=schedule.source_commit,
        )
        for attempt in schedule.attempts
    )
    counts = {
        "never_attempted": sum(entry.action == "never_attempted" for entry in entries),
        "preserved": sum(entry.action == "preserve" for entry in entries),
        "rerun_infrastructure": sum(
            entry.action == "rerun_infrastructure" for entry in entries
        ),
        "source_schedule": len(entries),
    }
    if counts["rerun_infrastructure"] != authorization.expected_invalidated_attempts:
        raise BaselineBatchError(
            "authorized invalidated attempt count does not match source artifacts"
        )
    return ContinuationManifest(
        authorization=authorization,
        continuation_run_id=continuation_run_id,
        counts=counts,
        entries=entries,
        original_run_id=original_run_id,
        source_commit=schedule.source_commit,
        source_schedule_sha256=schedule.sha256,
    )


def continuation_schedule(
    source: BaselineSchedule, manifest: ContinuationManifest
) -> BaselineSchedule:
    """Derive only authorized reruns and never-attempted trials with fresh IDs."""
    _validate_source_identity(source, manifest)
    source_by_key = {_trial_key(attempt): attempt for attempt in source.attempts}
    attempts = tuple(
        _fresh_attempt(source_by_key[entry.trial_key], manifest.continuation_run_id)
        for entry in manifest.entries
        if entry.action != "preserve"
    )
    return BaselineSchedule(
        attempts=attempts,
        eligible_manifest_sha256=source.eligible_manifest_sha256,
        source_commit=source.source_commit,
        train_ids_sha256=source.train_ids_sha256,
        exclusion_manifest_sha256=source.exclusion_manifest_sha256,
        exclusions=source.exclusions,
    )


def reconcile_continuation(
    source: BaselineSchedule,
    manifest: ContinuationManifest,
    *,
    source_repository: ImmutableAttemptRepository,
    continuation_repository: ImmutableAttemptRepository,
) -> ContinuationReconciliation:
    """Verify source evidence and account for each original trial exactly once."""
    try:
        rebuilt = build_continuation_manifest(
            source,
            repository=source_repository,
            continuation_run_id=manifest.continuation_run_id,
            authorization=manifest.authorization,
        )
    except BaselineBatchError as error:
        raise BaselineBatchError(
            "source artifacts do not match continuation manifest"
        ) from error
    if rebuilt != manifest:
        raise BaselineBatchError("source artifacts do not match continuation manifest")
    continuation = continuation_schedule(source, manifest)
    completed = 0
    for attempt in continuation.attempts:
        if (
            continuation_repository.reconcile(
                attempt, expected_commit=source.source_commit
            )
            is not None
        ):
            completed += 1
    preserved = manifest.counts["preserved"]
    missing = len(continuation.attempts) - completed
    reconciled = preserved + completed
    return ContinuationReconciliation(
        complete=reconciled == len(source.attempts),
        completed_continuation_attempts=completed,
        missing_continuation_attempts=missing,
        preserved_attempts=preserved,
        reconciled_trial_count=reconciled,
        source_schedule_attempts=len(source.attempts),
    )


def write_continuation_manifest(path: Path, manifest: ContinuationManifest) -> str:
    """Create one private canonical manifest without allowing overwrite."""
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(descriptor, manifest.canonical_bytes())
    finally:
        os.close(descriptor)
    return manifest.sha256


def load_continuation_manifest(
    path: Path, *, expected_sha256: str
) -> ContinuationManifest:
    """Load a canonical private manifest bound to its expected digest."""
    if _SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise BaselineBatchError("expected continuation SHA-256 is invalid")
    content = _read_private_file(path)
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise BaselineBatchError("continuation manifest SHA-256 does not match")
    try:
        value = json.loads(content)
        manifest = _manifest_from_dict(value)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise BaselineBatchError("continuation manifest is invalid") from error
    if content != manifest.canonical_bytes():
        raise BaselineBatchError("continuation manifest is not canonical")
    return manifest


def _build_entry(
    attempt: BaselineAttempt,
    *,
    repository: ImmutableAttemptRepository,
    continuation_run_id: str,
    authorization: ContinuationAuthorization,
    expected_commit: str,
) -> ContinuationEntry:
    observation = repository.reconcile(attempt, expected_commit=expected_commit)
    fresh = _fresh_attempt(attempt, continuation_run_id)
    if observation is None:
        return _entry(attempt, "never_attempted", fresh.attempt_id, None)
    evidence = _source_evidence(repository, attempt)
    if _matches_authorization(evidence, authorization):
        evidence = PredecessorEvidence(
            **{
                **evidence.as_dict(),
                "adjudicated_failure_origin": "benchmark_infrastructure",
            }
        )
        return _entry(attempt, "rerun_infrastructure", fresh.attempt_id, evidence)
    return _entry(attempt, "preserve", None, evidence)


def _entry(
    attempt: BaselineAttempt,
    action: str,
    continuation_attempt_id: str | None,
    predecessor: PredecessorEvidence | None,
) -> ContinuationEntry:
    return ContinuationEntry(
        action=action,
        condition=attempt.condition,
        continuation_attempt_id=continuation_attempt_id,
        database=attempt.database,
        instance_id=attempt.instance_id,
        predecessor=predecessor,
        repetition=attempt.repetition,
        trial_key=_trial_key(attempt),
    )


def _source_evidence(
    repository: ImmutableAttemptRepository, attempt: BaselineAttempt
) -> PredecessorEvidence:
    root = repository.attempt_root(attempt)
    try:
        generation = _read_private_file(root / "generation.jsonl")
        manifest_content = _read_private_file(root / "run.json")
        record = json.loads(generation)
        run_manifest = RunManifest.from_dict(
            json.loads(manifest_content), environment={}
        )
    except (
        BaselineBatchError,
        RunManifestError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ) as error:
        raise BaselineBatchError("source artifact evidence is invalid") from error
    if not isinstance(record, dict):
        raise BaselineBatchError("source artifact evidence is invalid")
    return PredecessorEvidence(
        adjudicated_failure_origin=None,
        attempt_id=attempt.attempt_id,
        finished_at=run_manifest.finished_at,
        generation_outcome=_required_string(record, "generation_outcome"),
        generation_sha256=hashlib.sha256(generation).hexdigest(),
        recorded_failure_origin=_optional_string(record, "failure_origin"),
        run_manifest_sha256=hashlib.sha256(manifest_content).hexdigest(),
        started_at=run_manifest.started_at,
        terminal_failure_class=_optional_string(record, "terminal_failure_class"),
    )


def _matches_authorization(
    evidence: PredecessorEvidence, authorization: ContinuationAuthorization
) -> bool:
    return (
        evidence.generation_outcome == "errored"
        and evidence.terminal_failure_class == authorization.terminal_failure_class
        and _timestamp_lower(authorization.finished_at_start)
        <= _timestamp_lower(evidence.finished_at)
        < _timestamp_upper_exclusive(authorization.finished_at_end)
    )


def _validate_source_identity(
    source: BaselineSchedule, manifest: ContinuationManifest
) -> None:
    if (
        source.sha256 != manifest.source_schedule_sha256
        or source.source_commit != manifest.source_commit
        or {attempt.run_id for attempt in source.attempts} != {manifest.original_run_id}
        or tuple(_trial_key(attempt) for attempt in source.attempts)
        != tuple(entry.trial_key for entry in manifest.entries)
    ):
        raise BaselineBatchError("source schedule does not match continuation manifest")


def _fresh_attempt(attempt: BaselineAttempt, run_id: str) -> BaselineAttempt:
    return BaselineAttempt(
        condition=attempt.condition,
        database=attempt.database,
        instance_id=attempt.instance_id,
        repetition=attempt.repetition,
        run_id=run_id,
    )


def _trial_key(attempt: BaselineAttempt) -> str:
    return f"{attempt.instance_id}:{attempt.condition}:{attempt.repetition}"


def _manifest_from_dict(value: Any) -> ContinuationManifest:
    if not isinstance(value, dict) or set(value) != {
        "authorization",
        "continuation_run_id",
        "counts",
        "entries",
        "kind",
        "original_run_id",
        "schema_version",
        "source_commit",
        "source_schedule_sha256",
    }:
        raise BaselineBatchError("continuation manifest must use the exact schema")
    authorization = value["authorization"]
    if not isinstance(authorization, dict) or set(authorization) != {
        "authorization_id",
        "expected_invalidated_attempts",
        "finished_at_end",
        "finished_at_start",
        "terminal_failure_class",
    }:
        raise BaselineBatchError("continuation authorization is invalid")
    entries = value["entries"]
    if not isinstance(entries, list):
        raise BaselineBatchError("continuation entries are invalid")
    return ContinuationManifest(
        authorization=ContinuationAuthorization(**authorization),
        continuation_run_id=value["continuation_run_id"],
        counts=value["counts"],
        entries=tuple(_entry_from_dict(entry) for entry in entries),
        kind=value["kind"],
        original_run_id=value["original_run_id"],
        schema_version=value["schema_version"],
        source_commit=value["source_commit"],
        source_schedule_sha256=value["source_schedule_sha256"],
    )


def _entry_from_dict(value: Any) -> ContinuationEntry:
    if not isinstance(value, dict) or set(value) != {
        "action",
        "condition",
        "continuation_attempt_id",
        "database",
        "instance_id",
        "predecessor",
        "repetition",
        "trial_key",
    }:
        raise BaselineBatchError("continuation entry is invalid")
    predecessor = value["predecessor"]
    if predecessor is not None:
        if not isinstance(predecessor, dict) or set(predecessor) != {
            "adjudicated_failure_origin",
            "attempt_id",
            "finished_at",
            "generation_outcome",
            "generation_sha256",
            "recorded_failure_origin",
            "run_manifest_sha256",
            "started_at",
            "terminal_failure_class",
        }:
            raise BaselineBatchError("continuation predecessor is invalid")
        predecessor = PredecessorEvidence(**predecessor)
    return ContinuationEntry(
        action=value["action"],
        condition=value["condition"],
        continuation_attempt_id=value["continuation_attempt_id"],
        database=value["database"],
        instance_id=value["instance_id"],
        predecessor=predecessor,
        repetition=value["repetition"],
        trial_key=value["trial_key"],
    )


def _read_private_file(path: Path) -> bytes:
    try:
        metadata = path.stat(follow_symlinks=False)
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or not 0 < metadata.st_size <= _MAX_MANIFEST_BYTES
        ):
            raise OSError("unsafe file")
        content = path.read_bytes()
        if len(content) != metadata.st_size:
            raise OSError("file changed")
        return content
    except OSError as error:
        raise BaselineBatchError(
            "source artifact is not a private regular file"
        ) from error


def _required_string(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise BaselineBatchError(f"source artifact {field} is invalid")
    return item


def _optional_string(value: dict[str, Any], field: str) -> str | None:
    item = value.get(field)
    if item is not None and (not isinstance(item, str) or not item):
        raise BaselineBatchError(f"source artifact {field} is invalid")
    return item


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise BaselineBatchError(f"continuation {name} is invalid")


def _attempt_id(value: str) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        raise BaselineBatchError("continuation attempt ID is invalid")


def _utc_timestamp(value: str, name: str) -> None:
    if not isinstance(value, str) or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise BaselineBatchError(f"{name} must be an RFC3339 UTC timestamp")


def _timestamp_lower(value: str) -> datetime:
    _utc_timestamp(value, "timestamp")
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _timestamp_upper_exclusive(value: str) -> datetime:
    parsed = _timestamp_lower(value)
    if "." not in value:
        return parsed + timedelta(seconds=1)
    return parsed + timedelta(microseconds=1)


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()

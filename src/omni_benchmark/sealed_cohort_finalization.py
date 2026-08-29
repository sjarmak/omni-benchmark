"""Finalize complete staged cohorts without dispatching or scoring."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .artifact_store import ALLOWED_RAW_ROOTS, ArtifactStore, ArtifactStoreError
from .freeze_b import FreezeBError, FreezeBManifest, SealedRunManifest
from .sealed_execution_plan import SealedExecutionPlan, SealedPlannedAttempt
from .sealed_generation_staging import (
    SealedAttemptRepository,
    SealedGenerationStagingError,
    _parse_timestamp,
    _read_private_file,
    _validated_freeze,
    _validated_plan,
    prepare_sealed_attempt,
)

GENERATION_FILENAME = "generation.jsonl"
RUN_MANIFEST_FILENAME = "run.json"


class SealedCohortFinalizationError(RuntimeError):
    """Raised when a complete immutable sealed cohort cannot be proven."""


@dataclass(frozen=True)
class SealedCohortResult:
    """Hashes and paths for one complete condition/repetition cohort."""

    condition: str
    repetition: int
    attempt_count: int
    generation_path: Path
    generation_sha256: str
    run_manifest_path: Path
    run_manifest: SealedRunManifest
    already_present: bool = False

    def public_summary(self) -> dict[str, object]:
        return {
            "already_present": self.already_present,
            "attempt_count": self.attempt_count,
            "condition": self.condition,
            "generation_sha256": self.generation_sha256,
            "repetition": self.repetition,
            "run_manifest_sha256": self.run_manifest.sha256(),
        }


def finalize_sealed_cohort(
    *,
    workspace: Path,
    output_root: Path,
    plan: SealedExecutionPlan,
    freeze_b: FreezeBManifest,
    attempt_repository: SealedAttemptRepository,
    condition: str,
    repetition: int,
    questions: Mapping[str, str],
    software_versions: Mapping[str, str],
    cli_versions: Mapping[str, str],
    started_at: str,
    finished_at: str,
) -> SealedCohortResult:
    """Aggregate exactly one 101-attempt cohort in committed schedule order."""
    try:
        root = _workspace_root(workspace)
        validated_plan = _validated_plan(plan)
        validated_freeze = _validated_freeze(freeze_b)
        if type(attempt_repository) is not SealedAttemptRepository:
            raise SealedCohortFinalizationError("sealed attempt repository is invalid")
        attempt_repository.require_workspace(root)
        cohort = _cohort_attempts(validated_plan, condition, repetition)
        question_map = _question_map(questions, cohort)
        staged = []
        for planned in cohort:
            prepared = prepare_sealed_attempt(
                plan=validated_plan,
                freeze_b=validated_freeze,
                attempt_id=planned.attempt_id,
                question=question_map[planned.instance_id],
            )
            result = attempt_repository.reconcile(prepared)
            if result is None:
                raise SealedCohortFinalizationError("sealed cohort is incomplete")
            staged.append(result)
    except SealedCohortFinalizationError:
        raise
    except SealedGenerationStagingError as error:
        raise SealedCohortFinalizationError(
            "staged sealed cohort is invalid"
        ) from error

    generation = b"".join(result.generation_record_bytes for result in staged)
    records = tuple(json.loads(result.generation_record_bytes) for result in staged)
    observed_starts = tuple(str(record["started_at"]) for record in records)
    observed_finishes = tuple(str(record["finished_at"]) for record in records)
    if started_at != min(observed_starts, key=_parse_timestamp) or finished_at != max(
        observed_finishes, key=_parse_timestamp
    ):
        raise SealedCohortFinalizationError(
            "sealed cohort timestamps do not match staged attempts"
        )
    generation_sha256 = hashlib.sha256(generation).hexdigest()
    manifest = _run_manifest(
        validated_freeze,
        condition=condition,
        repetition=repetition,
        generation_sha256=generation_sha256,
        software_versions=software_versions,
        cli_versions=cli_versions,
        started_at=started_at,
        finished_at=finished_at,
    )
    repository = _CohortRepository(root, output_root)
    return repository.write_or_reconcile(
        condition=condition,
        repetition=repetition,
        generation=generation,
        manifest=manifest,
    )


def _cohort_attempts(
    plan: SealedExecutionPlan, condition: str, repetition: int
) -> tuple[SealedPlannedAttempt, ...]:
    if condition not in {"C1", "C2", "C3", "C4"}:
        raise SealedCohortFinalizationError("sealed cohort condition is invalid")
    if type(repetition) is not int or repetition not in (1, 2, 3):
        raise SealedCohortFinalizationError("sealed cohort repetition is invalid")
    result = tuple(
        attempt
        for attempt in plan.attempts
        if (attempt.condition, attempt.repetition) == (condition, repetition)
    )
    if len(result) != 101 or len({attempt.instance_id for attempt in result}) != 101:
        raise SealedCohortFinalizationError(
            "sealed cohort must contain exactly 101 planned attempts"
        )
    return result


def _question_map(
    value: object, cohort: tuple[SealedPlannedAttempt, ...]
) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not isinstance(question, str) or not question
        for key, question in value.items()
    ):
        raise SealedCohortFinalizationError("sealed cohort question map is invalid")
    result = dict(value)
    expected = {attempt.instance_id for attempt in cohort}
    if set(result) != expected:
        raise SealedCohortFinalizationError(
            "sealed cohort question set does not match the plan"
        )
    if any(
        hashlib.sha256(result[attempt.instance_id].encode()).hexdigest()
        != attempt.question_sha256
        for attempt in cohort
    ):
        raise SealedCohortFinalizationError(
            "sealed cohort question content does not match the plan"
        )
    return result


def _run_manifest(
    freeze_b: FreezeBManifest,
    *,
    condition: str,
    repetition: int,
    generation_sha256: str,
    software_versions: Mapping[str, str],
    cli_versions: Mapping[str, str],
    started_at: str,
    finished_at: str,
) -> SealedRunManifest:
    frozen = freeze_b.condition(condition)
    try:
        return SealedRunManifest.from_dict(
            {
                "budget_id": frozen.budget_id,
                "cli_versions": dict(cli_versions),
                "condition": condition,
                "finished_at": finished_at,
                "freeze_b_sha256": freeze_b.sha256(),
                "generation_sha256": generation_sha256,
                "harness_config_sha256": frozen.harness_config_sha256,
                "instructions_sha256": frozen.instructions_sha256,
                "kind": "sealed-run-manifest",
                "model": frozen.model,
                "model_config_id": frozen.model_config_id,
                "prompt_sha256": frozen.prompt_sha256,
                "provider": frozen.provider,
                "question_count": 101,
                "repetition": repetition,
                "runtime_policy_sha256": frozen.runtime_policy_sha256,
                "schedule_sha256": freeze_b.schedule_sha256,
                "schema_version": 1,
                "scope": "test",
                "semantic_model_ref": frozen.semantic_model_ref,
                "semantic_model_sha256": frozen.semantic_model_sha256,
                "software_versions": dict(software_versions),
                "started_at": started_at,
                "system_commit": freeze_b.system_commit,
            },
            freeze_b=freeze_b,
        )
    except (FreezeBError, TypeError, ValueError) as error:
        raise SealedCohortFinalizationError(
            "sealed cohort run metadata is invalid"
        ) from error


class _CohortRepository:
    def __init__(self, workspace: Path, output_root: Path) -> None:
        root = Path(output_root)
        if root.is_absolute() or not root.parts or ".." in root.parts:
            raise SealedCohortFinalizationError(
                "sealed cohort output root must be confined"
            )
        if not any(root.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS):
            raise SealedCohortFinalizationError(
                "sealed cohort output root must be an ignored raw-run path"
            )
        self.workspace = workspace
        self.output_root = root
        self._validate_root()

    def write_or_reconcile(
        self,
        *,
        condition: str,
        repetition: int,
        generation: bytes,
        manifest: SealedRunManifest,
    ) -> SealedCohortResult:
        destination = self._destination(condition, repetition)
        manifest_bytes = manifest.canonical_bytes()
        if os.path.lexists(destination):
            return replace(
                self._reconcile(destination, generation, manifest, manifest_bytes),
                already_present=True,
            )
        temporary_path: Path | None = None
        try:
            ArtifactStore(self.workspace, self.output_root)
            temporary = self.output_root / (
                f".{condition.lower()}-r{repetition}.tmp-{secrets.token_hex(8)}"
            )
            temporary_path = self.workspace / temporary
            store = ArtifactStore(self.workspace, temporary, require_new_root=True)
            store.write_bytes(Path(GENERATION_FILENAME), generation)
            store.write_bytes(Path(RUN_MANIFEST_FILENAME), manifest_bytes)
            try:
                os.rename(temporary_path, destination)
            except OSError:
                if os.path.lexists(destination):
                    return replace(
                        self._reconcile(
                            destination, generation, manifest, manifest_bytes
                        ),
                        already_present=True,
                    )
                raise
        except (ArtifactStoreError, OSError) as error:
            raise SealedCohortFinalizationError(
                "sealed cohort could not be finalized atomically"
            ) from error
        finally:
            if temporary_path is not None and os.path.lexists(temporary_path):
                _cleanup_temporary(temporary_path)
        return self._reconcile(destination, generation, manifest, manifest_bytes)

    def _destination(self, condition: str, repetition: int) -> Path:
        self._validate_root()
        return self.workspace / self.output_root / f"{condition.lower()}-r{repetition}"

    def _validate_root(self) -> None:
        candidate = self.workspace / self.output_root
        try:
            if candidate.resolve(strict=False) != candidate:
                raise SealedCohortFinalizationError(
                    "sealed cohort output root must not contain a symlink"
                )
        except OSError as error:
            raise SealedCohortFinalizationError(
                "sealed cohort output root is unavailable"
            ) from error

    def _reconcile(
        self,
        destination: Path,
        expected_generation: bytes,
        manifest: SealedRunManifest,
        expected_manifest: bytes,
    ) -> SealedCohortResult:
        try:
            metadata = destination.stat(follow_symlinks=False)
            if (
                destination.is_symlink()
                or not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or metadata.st_uid != os.getuid()
            ):
                raise SealedCohortFinalizationError("existing sealed cohort is invalid")
            generation_path = destination / GENERATION_FILENAME
            manifest_path = destination / RUN_MANIFEST_FILENAME
            if set(destination.iterdir()) != {generation_path, manifest_path}:
                raise SealedCohortFinalizationError(
                    "existing sealed cohort is incomplete"
                )
            generation = _read_private_file(generation_path)
            manifest_bytes = _read_private_file(manifest_path)
            if generation != expected_generation or manifest_bytes != expected_manifest:
                raise SealedCohortFinalizationError(
                    "existing sealed cohort conflicts with staged attempts"
                )
        except SealedCohortFinalizationError:
            raise
        except (OSError, SealedGenerationStagingError) as error:
            raise SealedCohortFinalizationError(
                "existing sealed cohort is invalid"
            ) from error
        return SealedCohortResult(
            condition=manifest.condition,
            repetition=manifest.repetition,
            attempt_count=101,
            generation_path=generation_path,
            generation_sha256=hashlib.sha256(generation).hexdigest(),
            run_manifest_path=manifest_path,
            run_manifest=manifest,
        )


def _workspace_root(workspace: Path) -> Path:
    absolute = workspace.absolute()
    try:
        resolved = workspace.resolve(strict=True)
    except OSError as error:
        raise SealedCohortFinalizationError(
            "sealed cohort workspace is unavailable"
        ) from error
    if absolute != resolved or workspace.is_symlink() or not resolved.is_dir():
        raise SealedCohortFinalizationError(
            "sealed cohort workspace must be a non-symlink directory"
        )
    return resolved


def _cleanup_temporary(path: Path) -> None:
    for name in (GENERATION_FILENAME, RUN_MANIFEST_FILENAME):
        try:
            (path / name).unlink()
        except FileNotFoundError:
            pass
    try:
        path.rmdir()
    except FileNotFoundError:
        pass

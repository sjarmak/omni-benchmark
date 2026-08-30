"""Canonical Freeze-B and sealed-run provenance bindings."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from .content_policy import ContentPolicy
from .scoring import scorer_metadata

SCHEMA_VERSION = 1
KIND = "freeze-b-manifest"
SEALED_RUN_KIND = "sealed-run-manifest"
CONDITIONS = ("C1", "C2", "C3", "C4")
QUESTION_COUNT = 101
REPETITIONS = 3
EXPECTED_TEST_OUTPUTS = 1_212
SCHEDULE_ALGORITHM = "committed_block_interleaved_v1"

_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}")
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_FREEZE_FIELDS = frozenset(
    {
        "conditions",
        "database",
        "expected_test_outputs",
        "freeze_a_commit",
        "frozen_files",
        "kind",
        "question_count",
        "recorded_at",
        "repetitions",
        "schedule",
        "schema_version",
        "scorer",
        "system_commit",
    }
)
_CONDITION_FIELDS = frozenset(
    {
        "budget_id",
        "condition",
        "harness_config_sha256",
        "instructions_sha256",
        "model",
        "model_config_id",
        "prompt_sha256",
        "provider",
        "runtime_policy_sha256",
        "semantic_model_ref",
        "semantic_model_sha256",
    }
)
_DATABASE_FIELDS = frozenset(
    {"libpq_version", "postgresql_version", "snapshot_manifest_sha256"}
)
_SCHEDULE_FIELDS = frozenset({"algorithm", "seed", "sha256"})
_SCORER_FIELDS = frozenset({"metadata", "source_commit"})
_SEALED_RUN_FIELDS = frozenset(
    {
        "budget_id",
        "cli_versions",
        "condition",
        "finished_at",
        "freeze_b_sha256",
        "generation_sha256",
        "harness_config_sha256",
        "instructions_sha256",
        "kind",
        "model",
        "model_config_id",
        "prompt_sha256",
        "provider",
        "question_count",
        "repetition",
        "runtime_policy_sha256",
        "schedule_sha256",
        "schema_version",
        "scope",
        "semantic_model_ref",
        "semantic_model_sha256",
        "software_versions",
        "started_at",
        "system_commit",
    }
)


class FreezeBError(ValueError):
    """Raised when Freeze-B or final-run provenance is incomplete or mutable."""


def expected_test_output_count(question_count: int) -> int:
    """Return the complete C1-C4 by repetition coordinate count for a frame."""
    if type(question_count) is not int or question_count <= 0:
        raise FreezeBError("question_count must be a positive integer")
    return question_count * len(CONDITIONS) * REPETITIONS


@dataclass(frozen=True)
class FreezeBCondition:
    """One frozen condition specification shared by all final repetitions."""

    condition: str
    harness_config_sha256: str
    runtime_policy_sha256: str
    provider: str
    model: str
    model_config_id: str
    budget_id: str
    prompt_sha256: str
    instructions_sha256: str
    semantic_model_ref: str
    semantic_model_sha256: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "budget_id": self.budget_id,
            "condition": self.condition,
            "harness_config_sha256": self.harness_config_sha256,
            "instructions_sha256": self.instructions_sha256,
            "model": self.model,
            "model_config_id": self.model_config_id,
            "prompt_sha256": self.prompt_sha256,
            "provider": self.provider,
            "runtime_policy_sha256": self.runtime_policy_sha256,
            "semantic_model_ref": self.semantic_model_ref,
            "semantic_model_sha256": self.semantic_model_sha256,
        }


@dataclass(frozen=True)
class FreezeBManifest:
    """Exact pre-test system freeze with no generation or correctness data."""

    freeze_a_commit: str
    system_commit: str
    recorded_at: str
    conditions: tuple[FreezeBCondition, ...]
    frozen_files: tuple[tuple[str, str], ...]
    schedule_algorithm: str
    schedule_seed: str
    schedule_sha256: str
    snapshot_manifest_sha256: str
    postgresql_version: str
    libpq_version: str
    scorer_source_commit: str
    scorer_metadata_json: str
    question_count: int = QUESTION_COUNT
    repetitions: int = REPETITIONS
    expected_test_outputs: int = EXPECTED_TEST_OUTPUTS
    schema_version: int = SCHEMA_VERSION
    kind: str = KIND

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        environment: Mapping[str, str] | None = None,
    ) -> FreezeBManifest:
        if not isinstance(value, Mapping) or set(value) != _FREEZE_FIELDS:
            raise FreezeBError("Freeze B manifest must use the exact schema")
        policy = ContentPolicy.from_environment(
            os.environ if environment is None else environment
        )
        materialized = _plain_json_object(value, "Freeze B manifest")
        if policy.sanitize_json(materialized) != materialized:
            raise FreezeBError("Freeze B manifest contains sensitive content")
        _require_fixed(materialized)
        freeze_a_commit = _commit(materialized["freeze_a_commit"], "freeze_a_commit")
        system_commit = _commit(materialized["system_commit"], "system_commit")
        recorded_at = _timestamp(materialized["recorded_at"], "recorded_at")
        conditions = _conditions(materialized["conditions"], policy)
        frozen_files = _frozen_files(materialized["frozen_files"])
        schedule = _exact_mapping(
            materialized["schedule"], _SCHEDULE_FIELDS, "schedule"
        )
        if schedule["algorithm"] != SCHEDULE_ALGORITHM:
            raise FreezeBError("schedule algorithm is invalid")
        schedule_seed = _identifier(schedule["seed"], "schedule seed", policy)
        schedule_digest = _sha256(schedule["sha256"], "schedule sha256")
        database = _exact_mapping(
            materialized["database"], _DATABASE_FIELDS, "database"
        )
        snapshot_digest = _sha256(
            database["snapshot_manifest_sha256"], "database snapshot_manifest_sha256"
        )
        postgresql_version = _version(
            database["postgresql_version"], "database postgresql_version"
        )
        libpq_version = _version(database["libpq_version"], "database libpq_version")
        scorer = _exact_mapping(materialized["scorer"], _SCORER_FIELDS, "scorer")
        scorer_source_commit = _commit(scorer["source_commit"], "scorer source_commit")
        if scorer_source_commit != system_commit:
            raise FreezeBError("scorer source_commit must equal system_commit")
        expected_metadata = scorer_metadata()
        if scorer["metadata"] != expected_metadata:
            raise FreezeBError("scorer metadata does not match frozen scorers")
        scorer_metadata_json = json.dumps(
            expected_metadata,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return cls(
            freeze_a_commit=freeze_a_commit,
            system_commit=system_commit,
            recorded_at=recorded_at,
            conditions=conditions,
            frozen_files=frozen_files,
            schedule_algorithm=SCHEDULE_ALGORITHM,
            schedule_seed=schedule_seed,
            schedule_sha256=schedule_digest,
            snapshot_manifest_sha256=snapshot_digest,
            postgresql_version=postgresql_version,
            libpq_version=libpq_version,
            scorer_source_commit=scorer_source_commit,
            scorer_metadata_json=scorer_metadata_json,
            question_count=materialized["question_count"],
            expected_test_outputs=materialized["expected_test_outputs"],
        )

    def condition(self, condition: str) -> FreezeBCondition:
        for item in self.conditions:
            if item.condition == condition:
                return item
        raise FreezeBError("condition is absent from Freeze B")

    def as_dict(self) -> dict[str, object]:
        return {
            "conditions": [condition.as_dict() for condition in self.conditions],
            "database": {
                "libpq_version": self.libpq_version,
                "postgresql_version": self.postgresql_version,
                "snapshot_manifest_sha256": self.snapshot_manifest_sha256,
            },
            "expected_test_outputs": self.expected_test_outputs,
            "freeze_a_commit": self.freeze_a_commit,
            "frozen_files": dict(self.frozen_files),
            "kind": self.kind,
            "question_count": self.question_count,
            "recorded_at": self.recorded_at,
            "repetitions": self.repetitions,
            "schedule": {
                "algorithm": self.schedule_algorithm,
                "seed": self.schedule_seed,
                "sha256": self.schedule_sha256,
            },
            "schema_version": self.schema_version,
            "scorer": {
                "metadata": json.loads(self.scorer_metadata_json),
                "source_commit": self.scorer_source_commit,
            },
            "system_commit": self.system_commit,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class SealedRunManifest:
    """One final condition/repetition run bound to an exact Freeze B."""

    freeze_b_sha256: str
    schedule_sha256: str
    system_commit: str
    generation_sha256: str
    condition: str
    repetition: int
    harness_config_sha256: str
    runtime_policy_sha256: str
    provider: str
    model: str
    model_config_id: str
    budget_id: str
    prompt_sha256: str
    instructions_sha256: str
    semantic_model_ref: str
    semantic_model_sha256: str | None
    software_versions: tuple[tuple[str, str], ...]
    cli_versions: tuple[tuple[str, str], ...]
    started_at: str
    finished_at: str
    question_count: int = QUESTION_COUNT
    scope: str = "test"
    schema_version: int = SCHEMA_VERSION
    kind: str = SEALED_RUN_KIND

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        freeze_b: FreezeBManifest,
        environment: Mapping[str, str] | None = None,
    ) -> SealedRunManifest:
        if not isinstance(freeze_b, FreezeBManifest):
            raise FreezeBError("sealed run requires a validated Freeze B manifest")
        if not isinstance(value, Mapping) or set(value) != _SEALED_RUN_FIELDS:
            raise FreezeBError("sealed run manifest must use the exact schema")
        policy = ContentPolicy.from_environment(
            os.environ if environment is None else environment
        )
        materialized = _plain_json_object(value, "sealed run manifest")
        if policy.sanitize_json(materialized) != materialized:
            raise FreezeBError("sealed run manifest contains sensitive content")
        if materialized["kind"] != SEALED_RUN_KIND:
            raise FreezeBError("sealed run kind is invalid")
        if (
            materialized["schema_version"] != SCHEMA_VERSION
            or type(materialized["schema_version"]) is not int
        ):
            raise FreezeBError("sealed run schema_version is invalid")
        if materialized["scope"] != "test":
            raise FreezeBError("sealed run scope must be test")
        if materialized["question_count"] != freeze_b.question_count:
            raise FreezeBError("sealed run question_count does not match Freeze B")
        repetition = materialized["repetition"]
        if type(repetition) is not int or repetition not in range(1, REPETITIONS + 1):
            raise FreezeBError("sealed run repetition must be 1, 2, or 3")
        freeze_digest = _sha256(
            materialized["freeze_b_sha256"], "sealed run freeze_b_sha256"
        )
        if freeze_digest != freeze_b.sha256():
            raise FreezeBError("sealed run freeze_b_sha256 does not match Freeze B")
        schedule_digest = _sha256(
            materialized["schedule_sha256"], "sealed run schedule_sha256"
        )
        if schedule_digest != freeze_b.schedule_sha256:
            raise FreezeBError("sealed run schedule_sha256 does not match Freeze B")
        system_commit = _commit(
            materialized["system_commit"], "sealed run system_commit"
        )
        if system_commit != freeze_b.system_commit:
            raise FreezeBError("sealed run system_commit does not match Freeze B")
        condition_name = materialized["condition"]
        if condition_name not in CONDITIONS:
            raise FreezeBError("sealed run condition is invalid")
        condition = freeze_b.condition(condition_name)
        _require_condition_match(materialized, condition)
        generation_digest = _sha256(
            materialized["generation_sha256"], "sealed run generation_sha256"
        )
        software_versions = _versions(
            materialized["software_versions"], "software_versions", policy
        )
        cli_versions = _versions(materialized["cli_versions"], "cli_versions", policy)
        started_at = _timestamp(materialized["started_at"], "started_at")
        finished_at = _timestamp(materialized["finished_at"], "finished_at")
        if _parse_timestamp(finished_at) < _parse_timestamp(started_at):
            raise FreezeBError("sealed run finished_at precedes started_at")
        return cls(
            freeze_b_sha256=freeze_digest,
            schedule_sha256=schedule_digest,
            system_commit=system_commit,
            generation_sha256=generation_digest,
            condition=condition.condition,
            repetition=repetition,
            harness_config_sha256=condition.harness_config_sha256,
            runtime_policy_sha256=condition.runtime_policy_sha256,
            provider=condition.provider,
            model=condition.model,
            model_config_id=condition.model_config_id,
            budget_id=condition.budget_id,
            prompt_sha256=condition.prompt_sha256,
            instructions_sha256=condition.instructions_sha256,
            semantic_model_ref=condition.semantic_model_ref,
            semantic_model_sha256=condition.semantic_model_sha256,
            software_versions=software_versions,
            cli_versions=cli_versions,
            started_at=started_at,
            finished_at=finished_at,
            question_count=materialized["question_count"],
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "budget_id": self.budget_id,
            "cli_versions": dict(self.cli_versions),
            "condition": self.condition,
            "finished_at": self.finished_at,
            "freeze_b_sha256": self.freeze_b_sha256,
            "generation_sha256": self.generation_sha256,
            "harness_config_sha256": self.harness_config_sha256,
            "instructions_sha256": self.instructions_sha256,
            "kind": self.kind,
            "model": self.model,
            "model_config_id": self.model_config_id,
            "prompt_sha256": self.prompt_sha256,
            "provider": self.provider,
            "question_count": self.question_count,
            "repetition": self.repetition,
            "runtime_policy_sha256": self.runtime_policy_sha256,
            "schedule_sha256": self.schedule_sha256,
            "schema_version": self.schema_version,
            "scope": self.scope,
            "semantic_model_ref": self.semantic_model_ref,
            "semantic_model_sha256": self.semantic_model_sha256,
            "software_versions": dict(self.software_versions),
            "started_at": self.started_at,
            "system_commit": self.system_commit,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def schedule_sha256(attempt_ids: Sequence[str]) -> str:
    """Hash one exact ordered trial schedule without reading question content."""
    values = tuple(attempt_ids)
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise FreezeBError("schedule attempt IDs must be non-empty strings")
    if len(values) != len(set(values)):
        raise FreezeBError("schedule attempt IDs must be unique")
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def _require_fixed(value: Mapping[str, Any]) -> None:
    fixed = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "repetitions": REPETITIONS,
    }
    for field, expected in fixed.items():
        if type(value[field]) is not type(expected) or value[field] != expected:
            raise FreezeBError(f"{field} must equal {expected!r}")
    question_count = value["question_count"]
    expected_outputs = value["expected_test_outputs"]
    expected = expected_test_output_count(question_count)
    if type(expected_outputs) is not int or expected_outputs != expected:
        raise FreezeBError(f"expected_test_outputs must equal {expected!r}")


def _conditions(value: object, policy: ContentPolicy) -> tuple[FreezeBCondition, ...]:
    if not isinstance(value, list) or len(value) != len(CONDITIONS):
        raise FreezeBError("Freeze B must contain exactly four conditions")
    result: list[FreezeBCondition] = []
    for expected_name, raw in zip(CONDITIONS, value, strict=True):
        item = _exact_mapping(raw, _CONDITION_FIELDS, "condition")
        if item["condition"] != expected_name:
            raise FreezeBError("Freeze B condition order must be C1, C2, C3, C4")
        semantic_digest = item["semantic_model_sha256"]
        if expected_name == "C1":
            if semantic_digest is not None:
                raise FreezeBError("C1 semantic_model_sha256 must be null")
        elif expected_name in {"C3", "C4"}:
            semantic_digest = _sha256(
                semantic_digest, f"{expected_name} semantic_model_sha256"
            )
        elif semantic_digest is not None:
            semantic_digest = _sha256(
                semantic_digest, f"{expected_name} semantic_model_sha256"
            )
        result.append(
            FreezeBCondition(
                condition=expected_name,
                harness_config_sha256=_sha256(
                    item["harness_config_sha256"],
                    f"{expected_name} harness_config_sha256",
                ),
                runtime_policy_sha256=_sha256(
                    item["runtime_policy_sha256"],
                    f"{expected_name} runtime_policy_sha256",
                ),
                provider=_identifier(item["provider"], "provider", policy),
                model=_identifier(item["model"], "model", policy),
                model_config_id=_identifier(
                    item["model_config_id"], "model_config_id", policy
                ),
                budget_id=_identifier(item["budget_id"], "budget_id", policy),
                prompt_sha256=_sha256(
                    item["prompt_sha256"], f"{expected_name} prompt_sha256"
                ),
                instructions_sha256=_sha256(
                    item["instructions_sha256"],
                    f"{expected_name} instructions_sha256",
                ),
                semantic_model_ref=_identifier(
                    item["semantic_model_ref"], "semantic_model_ref", policy
                ),
                semantic_model_sha256=semantic_digest,
            )
        )
    return tuple(result)


def _frozen_files(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping) or not value:
        raise FreezeBError("frozen_files must be a non-empty object")
    result: list[tuple[str, str]] = []
    for raw_path, digest in value.items():
        if not isinstance(raw_path, str) or not raw_path:
            raise FreezeBError("frozen file path is invalid")
        path = PurePosixPath(raw_path)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in raw_path
            or str(path) != raw_path
        ):
            raise FreezeBError("frozen file path is invalid")
        result.append((raw_path, _sha256(digest, f"frozen file {raw_path}")))
    return tuple(sorted(result))


def _require_condition_match(
    value: Mapping[str, Any], condition: FreezeBCondition
) -> None:
    expected = condition.as_dict()
    for field in _CONDITION_FIELDS - {"condition"}:
        if value[field] != expected[field]:
            raise FreezeBError(
                f"sealed run {field} does not match Freeze B condition specification"
            )


def _versions(
    value: object, field: str, policy: ContentPolicy
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping) or not value:
        raise FreezeBError(f"sealed run {field} must be a non-empty object")
    result: list[tuple[str, str]] = []
    for name, version in value.items():
        if not isinstance(name, str) or _VERSION.fullmatch(name) is None:
            raise FreezeBError(f"sealed run {field} key is invalid")
        if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
            raise FreezeBError(f"sealed run {field} value is invalid")
        if not policy.identifier_is_safe(name) or not policy.identifier_is_safe(
            version
        ):
            raise FreezeBError("sealed run manifest contains sensitive content")
        result.append((name, version))
    return tuple(sorted(result))


def _exact_mapping(
    value: object, fields: frozenset[str], description: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise FreezeBError(f"{description} must use the exact schema")
    if any(not isinstance(key, str) for key in value):
        raise FreezeBError(f"{description} keys must be strings")
    return value


def _plain_json_object(value: Mapping[str, Any], description: str) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise FreezeBError(
            f"{description} must contain canonical JSON values"
        ) from error
    if not isinstance(decoded, dict):
        raise FreezeBError(f"{description} must be an object")
    return decoded


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
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


def _sha256(value: object, description: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise FreezeBError(f"{description} must be a lowercase SHA-256")
    return value


def _commit(value: object, description: str) -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise FreezeBError(f"{description} must be a full lowercase commit hash")
    return value


def _identifier(value: object, description: str, policy: ContentPolicy) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise FreezeBError(f"{description} must be a compact identifier")
    if not policy.identifier_is_safe(value):
        raise FreezeBError("Freeze B manifest contains sensitive content")
    return value


def _version(value: object, description: str) -> str:
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        raise FreezeBError(f"{description} is invalid")
    return value


def _timestamp(value: object, description: str) -> str:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        raise FreezeBError(f"{description} must be RFC3339 UTC")
    _parse_timestamp(value)
    return value


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise FreezeBError("timestamp is invalid") from error

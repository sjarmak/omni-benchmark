"""Immutable, hash-bound provenance manifest for one generation run."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .artifact_store import ALLOWED_RAW_ROOTS
from .content_policy import ContentPolicy

SCHEMA_VERSION = 2
MAX_MANIFEST_BYTES = 64 * 1024
CONDITIONS = frozenset({"C1", "C2", "C3", "C4"})
DEVELOPMENT_SCOPES = frozenset({"train", "dev-a", "dev-b"})
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}")
VERSION_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}")
UTC_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z"
)
FIELDS = frozenset(
    {
        "budget_id",
        "cli_versions",
        "condition",
        "controllable_seed",
        "finished_at",
        "generation_sha256",
        "git_commit",
        "harness_config_sha256",
        "instructions_sha256",
        "model",
        "model_config_id",
        "prompt_sha256",
        "provider",
        "repetition",
        "schema_version",
        "scope",
        "semantic_model_ref",
        "semantic_model_sha256",
        "software_versions",
        "started_at",
    }
)


class RunManifestError(ValueError):
    """Raised when run provenance is ambiguous or violates custody policy."""


@dataclass(frozen=True)
class RunManifest:
    """Exact immutable provenance for outputs generated under one harness."""

    generation_sha256: str
    harness_config_sha256: str
    git_commit: str
    condition: str
    scope: str
    repetition: int
    controllable_seed: int | None
    software_versions: tuple[tuple[str, str], ...]
    cli_versions: tuple[tuple[str, str], ...]
    provider: str
    model: str
    model_config_id: str
    budget_id: str
    prompt_sha256: str
    instructions_sha256: str
    semantic_model_ref: str
    semantic_model_sha256: str | None
    started_at: str
    finished_at: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
        *,
        environment: Mapping[str, str] | None = None,
    ) -> RunManifest:
        """Validate an exact external representation and construct the manifest."""
        if not isinstance(value, Mapping) or set(value) != FIELDS:
            raise RunManifestError("run manifest must use the exact schema")
        policy = ContentPolicy.from_environment(
            os.environ if environment is None else environment
        )
        materialized = dict(value)
        if policy.sanitize_json(materialized) != materialized:
            raise RunManifestError("run manifest contains sensitive content")
        _validate_manifest(materialized, policy)
        return cls(
            generation_sha256=materialized["generation_sha256"],
            harness_config_sha256=materialized["harness_config_sha256"],
            git_commit=materialized["git_commit"],
            condition=materialized["condition"],
            scope=materialized["scope"],
            repetition=materialized["repetition"],
            controllable_seed=materialized["controllable_seed"],
            software_versions=_version_items(materialized["software_versions"]),
            cli_versions=_version_items(materialized["cli_versions"]),
            provider=materialized["provider"],
            model=materialized["model"],
            model_config_id=materialized["model_config_id"],
            budget_id=materialized["budget_id"],
            prompt_sha256=materialized["prompt_sha256"],
            instructions_sha256=materialized["instructions_sha256"],
            semantic_model_ref=materialized["semantic_model_ref"],
            semantic_model_sha256=materialized["semantic_model_sha256"],
            started_at=materialized["started_at"],
            finished_at=materialized["finished_at"],
            schema_version=materialized["schema_version"],
        )

    def as_dict(self) -> dict[str, object]:
        """Return the exact JSON-ready schema."""
        return {
            "budget_id": self.budget_id,
            "cli_versions": dict(self.cli_versions),
            "condition": self.condition,
            "controllable_seed": self.controllable_seed,
            "finished_at": self.finished_at,
            "generation_sha256": self.generation_sha256,
            "git_commit": self.git_commit,
            "harness_config_sha256": self.harness_config_sha256,
            "instructions_sha256": self.instructions_sha256,
            "model": self.model,
            "model_config_id": self.model_config_id,
            "prompt_sha256": self.prompt_sha256,
            "provider": self.provider,
            "repetition": self.repetition,
            "schema_version": self.schema_version,
            "scope": self.scope,
            "semantic_model_ref": self.semantic_model_ref,
            "semantic_model_sha256": self.semantic_model_sha256,
            "software_versions": dict(self.software_versions),
            "started_at": self.started_at,
        }

    def canonical_bytes(self) -> bytes:
        """Encode stable canonical JSON suitable for content hashing."""
        return (
            json.dumps(
                self.as_dict(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

    def sha256(self) -> str:
        """Return the canonical manifest digest."""
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def read_run_manifest(
    workspace: Path,
    path: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> RunManifest:
    """Read one canonical private run.json through a no-follow boundary."""
    relative_path = _validate_path(path)
    content = _read_private_file(workspace, relative_path)
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RunManifestError("run manifest must contain valid JSON") from error
    if not isinstance(value, dict):
        raise RunManifestError("run manifest must use the exact schema")
    manifest = RunManifest.from_dict(value, environment=environment)
    if content != manifest.canonical_bytes():
        raise RunManifestError("run manifest must use canonical JSON")
    return manifest


def read_bound_run_manifest(
    workspace: Path,
    path: Path,
    *,
    expected_sha256: str,
    generation_sha256: str,
    condition: str,
    scope: str,
    repetition: int,
    provider: str,
    model: str,
    started_at: str,
    finished_at: str,
    environment: Mapping[str, str] | None = None,
) -> RunManifest:
    """Read a manifest and bind it to the exact validated generation identity."""
    if SHA256_PATTERN.fullmatch(expected_sha256) is None:
        raise RunManifestError("expected SHA-256 is invalid")
    manifest = read_run_manifest(workspace, path, environment=environment)
    if manifest.sha256() != expected_sha256:
        raise RunManifestError("run manifest does not match its expected SHA-256")
    expected_fields = {
        "generation_sha256": generation_sha256,
        "condition": condition,
        "scope": scope,
        "repetition": repetition,
        "provider": provider,
        "model": model,
    }
    for field, expected in expected_fields.items():
        if getattr(manifest, field) != expected:
            raise RunManifestError(f"run manifest {field} does not match generation")
    if (manifest.started_at, manifest.finished_at) != (started_at, finished_at):
        raise RunManifestError("run manifest timestamps do not match generation")
    return manifest


def _validate_manifest(value: Mapping[str, Any], policy: ContentPolicy) -> None:
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != SCHEMA_VERSION
    ):
        raise RunManifestError(f"schema_version must equal {SCHEMA_VERSION}")
    for field in (
        "generation_sha256",
        "harness_config_sha256",
        "prompt_sha256",
        "instructions_sha256",
    ):
        if (
            not isinstance(value[field], str)
            or SHA256_PATTERN.fullmatch(value[field]) is None
        ):
            raise RunManifestError(f"{field} must be a lowercase SHA-256")
    if (
        not isinstance(value["git_commit"], str)
        or COMMIT_PATTERN.fullmatch(value["git_commit"]) is None
    ):
        raise RunManifestError("git_commit must be a full lowercase commit hash")
    if value["condition"] not in CONDITIONS:
        raise RunManifestError("condition must be C1, C2, C3, or C4")
    if value["scope"] not in DEVELOPMENT_SCOPES:
        raise RunManifestError("scope must be train, dev-a, or dev-b")
    repetition = value["repetition"]
    if type(repetition) is not int or repetition < 1:
        raise RunManifestError("repetition must be a positive integer")
    seed = value["controllable_seed"]
    if seed is not None and type(seed) is not int:
        raise RunManifestError("controllable_seed must be an integer or null")
    _version_items(value["software_versions"], field="software_versions")
    _version_items(value["cli_versions"], field="cli_versions")
    for field in ("provider", "model", "model_config_id", "budget_id"):
        item = value[field]
        if not isinstance(item, str) or IDENTIFIER_PATTERN.fullmatch(item) is None:
            raise RunManifestError(f"{field} must be a compact identifier")
        if not policy.identifier_is_safe(item):
            raise RunManifestError("run manifest contains sensitive content")
    _validate_semantic_model(value, policy)
    started = _timestamp(value["started_at"], "started_at")
    finished = _timestamp(value["finished_at"], "finished_at")
    if finished < started:
        raise RunManifestError("finished_at must not precede started_at")


def _validate_semantic_model(value: Mapping[str, Any], policy: ContentPolicy) -> None:
    semantic_model_ref = value["semantic_model_ref"]
    if (
        not isinstance(semantic_model_ref, str)
        or IDENTIFIER_PATTERN.fullmatch(semantic_model_ref) is None
    ):
        raise RunManifestError("semantic_model_ref must be a compact identifier")
    if not policy.identifier_is_safe(semantic_model_ref):
        raise RunManifestError("run manifest contains sensitive content")
    semantic_model_sha256 = value["semantic_model_sha256"]
    if semantic_model_sha256 is not None and (
        not isinstance(semantic_model_sha256, str)
        or SHA256_PATTERN.fullmatch(semantic_model_sha256) is None
    ):
        raise RunManifestError("semantic_model_sha256 must be null or a SHA-256")


def _version_items(
    value: object, *, field: str = "version map"
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or not value:
        raise RunManifestError(f"{field} must be a non-empty object")
    items: list[tuple[str, str]] = []
    for name, version in value.items():
        if not isinstance(name, str) or VERSION_NAME_PATTERN.fullmatch(name) is None:
            raise RunManifestError(f"{field} has an invalid tool name")
        if not isinstance(version, str) or not version or len(version) > 160:
            raise RunManifestError(f"{field} has an invalid version")
        items.append((name, version))
    return tuple(sorted(items))


def _timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise RunManifestError(f"{field} must be an RFC3339 UTC timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RunManifestError(f"{field} must be an RFC3339 UTC timestamp") from error


def _validate_path(path: Path) -> Path:
    candidate = Path(path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or candidate.name != "run.json"
        or not any(candidate.is_relative_to(root) for root in ALLOWED_RAW_ROOTS)
    ):
        raise RunManifestError("run manifest path must be a confined raw run.json")
    return candidate


def _read_private_file(workspace: Path, relative_path: Path) -> bytes:
    try:
        resolved_workspace = Path(workspace).resolve(strict=True)
        descriptor = _open_private_parent(resolved_workspace, relative_path.parent)
        try:
            return _read_private_entry(descriptor, relative_path.name)
        finally:
            os.close(descriptor)
    except RunManifestError:
        raise
    except OSError as error:
        raise RunManifestError("run manifest must be a private regular file") from error


def _open_private_parent(workspace: Path, relative_parent: Path) -> int:
    descriptor = os.open(
        workspace,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        for part in relative_parent.parts:
            next_descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise RunManifestError("run manifest must be a private regular file")
        return descriptor
    except (OSError, RunManifestError):
        os.close(descriptor)
        raise


def _read_private_entry(parent_descriptor: int, name: str) -> bytes:
    file_descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=parent_descriptor,
    )
    try:
        metadata = os.fstat(file_descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size < 1
            or metadata.st_size > MAX_MANIFEST_BYTES
        ):
            raise RunManifestError("run manifest must be a private regular file")
        with os.fdopen(file_descriptor, "rb") as handle:
            file_descriptor = -1
            content = handle.read(MAX_MANIFEST_BYTES + 1)
        if len(content) > MAX_MANIFEST_BYTES:
            raise RunManifestError("run manifest must be a private regular file")
        return content
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)

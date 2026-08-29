"""Post-consumption construction of all exact sealed production adapters."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .freeze_b import FreezeBError, FreezeBManifest
from .freeze_b_record import FreezeBRecordError, _committed_input, _relative_path
from .protected_fields import ProtectedFieldError, reject_protected_fields
from .sealed_direct_factory import (
    SealedDirectProductionConfig,
    build_sealed_direct_adapter_factory,
)
from .sealed_dispatch import AdapterFactory, SealedDispatchPreflight
from .sealed_omni_factory import (
    SealedOmniDeploymentGate,
    SealedOmniDeploymentTarget,
    SealedOmniProductionConfig,
    build_sealed_omni_adapter_factory,
)
from .sealed_runtime_inputs import load_sealed_runtime_inputs

_MAX_GATE_BYTES = 4 * 1024 * 1024
_MAX_RECORD_BYTES = 4 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")
_GATE_FIELDS = frozenset(
    {
        "deployment_run_id",
        "deployment_source_commit",
        "kind",
        "schema_version",
        "semantic_model_ref",
        "semantic_model_sha256",
        "targets",
    }
)
_TARGET_FIELDS = frozenset(
    {
        "branch_id",
        "database",
        "model_id",
        "record_path",
        "record_sha256",
        "semantic_model_sha256",
    }
)


class SealedProductionFactoryError(RuntimeError):
    """Raised when exact frozen production adapters cannot be constructed."""


@dataclass(frozen=True)
class SealedProductionAdapterConfig:
    """Operator-owned paths used only by the post-consumption builder."""

    input_spec_path: Path
    omni_deployment_gate_path: Path
    claude_config_directories: tuple[Path, Path, Path]
    database_environment_root: Path
    runtime_parent: Path

    @classmethod
    def create(
        cls,
        *,
        input_spec_path: Path,
        omni_deployment_gate_path: Path,
        claude_config_directories: tuple[Path, Path, Path],
        database_environment_root: Path,
        runtime_parent: Path,
    ) -> SealedProductionAdapterConfig:
        input_path = _repository_path(input_spec_path, "input specification")
        gate_path = _repository_path(omni_deployment_gate_path, "Omni deployment gate")
        profiles = tuple(Path(path) for path in claude_config_directories)
        external = (*profiles, Path(database_environment_root), Path(runtime_parent))
        if (
            len(profiles) != 3
            or len(set(external)) != len(external)
            or any(not path.is_absolute() for path in external)
        ):
            raise SealedProductionFactoryError(
                "production resource paths must be distinct absolute paths"
            )
        return cls(
            input_spec_path=input_path,
            omni_deployment_gate_path=gate_path,
            claude_config_directories=profiles,  # type: ignore[arg-type]
            database_environment_root=Path(database_environment_root),
            runtime_parent=Path(runtime_parent),
        )


def build_sealed_production_adapter_factories(
    config: SealedProductionAdapterConfig,
    preflight: SealedDispatchPreflight,
) -> Mapping[str, AdapterFactory]:
    """Construct four frozen factories after dispatcher receipt consumption."""
    selected = _validated_config(config)
    workspace = preflight.workspace
    system_commit = preflight.plan.system_commit
    if system_commit != preflight.freeze_b.system_commit:
        raise SealedProductionFactoryError("sealed preflight system identity changed")
    scheduled_databases = {
        attempt.database
        for attempt in preflight.plan.attempts
        if attempt.condition == "C4"
    }
    runtime_inputs = load_sealed_runtime_inputs(
        workspace,
        system_commit=system_commit,
        input_spec_path=selected.input_spec_path,
        freeze_b=preflight.freeze_b,
    )
    deployment_gate = load_sealed_omni_deployment_gate(
        workspace,
        system_commit=system_commit,
        gate_path=selected.omni_deployment_gate_path,
        freeze_b=preflight.freeze_b,
        scheduled_databases=scheduled_databases,
    )
    capture_root = preflight.output_root / "captures"
    direct_config = SealedDirectProductionConfig.create(
        workspace=workspace,
        system_commit=system_commit,
        runtime_inputs=runtime_inputs,
        capture_root=capture_root,
        claude_config_directories=selected.claude_config_directories,
        database_environment_root=selected.database_environment_root,
        runtime_parent=selected.runtime_parent,
    )
    omni_config = SealedOmniProductionConfig.create(
        workspace=workspace,
        system_commit=system_commit,
        runtime_inputs=runtime_inputs,
        capture_root=capture_root,
        deployment_gate=deployment_gate,
        scheduled_databases=scheduled_databases,
    )
    factories = {
        condition: build_sealed_direct_adapter_factory(
            direct_config,
            condition=condition,
            policy=preflight.policy,
        )
        for condition in ("C1", "C2", "C3")
    }
    factories["C4"] = build_sealed_omni_adapter_factory(
        omni_config,
        policy=preflight.policy,
    )
    return factories


def load_sealed_omni_deployment_gate(
    workspace: Path,
    *,
    system_commit: str,
    gate_path: Path,
    freeze_b: FreezeBManifest,
    scheduled_databases: set[str] | frozenset[str],
) -> SealedOmniDeploymentGate:
    """Load exact verified C4 deployment evidence from frozen Git objects."""
    manifest = _validated_freeze(freeze_b)
    if system_commit != manifest.system_commit:
        raise SealedProductionFactoryError("deployment system commit is invalid")
    try:
        relative = _relative_path(gate_path, "sealed Omni deployment gate path")
        committed = _committed_input(
            workspace,
            system_commit,
            relative,
            maximum_bytes=_MAX_GATE_BYTES,
        )
    except FreezeBRecordError as error:
        raise SealedProductionFactoryError(
            "sealed Omni deployment gate is unavailable"
        ) from error
    frozen = dict(manifest.frozen_files)
    if frozen.get(relative) != committed.sha256:
        raise SealedProductionFactoryError("sealed Omni deployment gate is not frozen")
    value = _canonical_json(committed.content, "sealed Omni deployment gate")
    if not isinstance(value, Mapping) or set(value) != _GATE_FIELDS:
        raise SealedProductionFactoryError("sealed Omni deployment gate is invalid")
    targets_value = value["targets"]
    if (
        value["kind"] != "sealed-omni-deployment-gate"
        or value["schema_version"] != 1
        or not isinstance(targets_value, list)
        or not targets_value
    ):
        raise SealedProductionFactoryError("sealed Omni deployment gate is invalid")
    c4 = manifest.condition("C4")
    deployment_run_id = value["deployment_run_id"]
    deployment_source_commit = value["deployment_source_commit"]
    if (
        value["semantic_model_ref"] != c4.semantic_model_ref
        or value["semantic_model_sha256"] != c4.semantic_model_sha256
        or not isinstance(deployment_run_id, str)
        or _IDENTIFIER.fullmatch(deployment_run_id) is None
        or not isinstance(deployment_source_commit, str)
        or _COMMIT.fullmatch(deployment_source_commit) is None
    ):
        raise SealedProductionFactoryError(
            "sealed Omni deployment identity does not match Freeze B"
        )
    targets: dict[str, SealedOmniDeploymentTarget] = {}
    for item in targets_value:
        target = _deployment_target(
            workspace,
            system_commit,
            frozen,
            item,
            deployment_run_id=deployment_run_id,
            deployment_source_commit=deployment_source_commit,
        )
        if target.database in targets:
            raise SealedProductionFactoryError(
                "sealed Omni deployment contains a duplicate database"
            )
        targets[target.database] = target
    expected = frozenset(scheduled_databases)
    if not expected or frozenset(targets) != expected:
        raise SealedProductionFactoryError(
            "sealed Omni deployment gate coverage is invalid"
        )
    if tuple(targets) != tuple(sorted(targets)):
        raise SealedProductionFactoryError(
            "sealed Omni deployment targets are not sorted"
        )
    return SealedOmniDeploymentGate.create(
        semantic_model_ref=c4.semantic_model_ref,
        semantic_model_sha256=c4.semantic_model_sha256,
        targets=targets,
    )


def _deployment_target(
    workspace: Path,
    system_commit: str,
    frozen: Mapping[str, str],
    value: object,
    *,
    deployment_run_id: str,
    deployment_source_commit: str,
) -> SealedOmniDeploymentTarget:
    if not isinstance(value, Mapping) or set(value) != _TARGET_FIELDS:
        raise SealedProductionFactoryError("sealed Omni deployment target is invalid")
    record_digest = value["record_sha256"]
    if not isinstance(record_digest, str) or _SHA256.fullmatch(record_digest) is None:
        raise SealedProductionFactoryError("deployment record digest is invalid")
    try:
        record_path = _relative_path(value["record_path"], "deployment record path")
        committed = _committed_input(
            workspace,
            system_commit,
            record_path,
            maximum_bytes=_MAX_RECORD_BYTES,
        )
    except FreezeBRecordError as error:
        raise SealedProductionFactoryError(
            "sealed Omni deployment record is unavailable"
        ) from error
    if committed.sha256 != record_digest or frozen.get(record_path) != record_digest:
        raise SealedProductionFactoryError("deployment record digest changed")
    record = _canonical_json(committed.content, "sealed Omni deployment record")
    source_commit = record.get("source_commit") if isinstance(record, Mapping) else None
    required = {
        "branch_id": value["branch_id"],
        "database": value["database"],
        "model_id": value["model_id"],
        "semantic_model_sha256": value["semantic_model_sha256"],
    }
    if (
        not isinstance(record, Mapping)
        or record.get("kind") != "public-omni-semantic-deployment"
        or record.get("schema_version") != 2
        or record.get("run_id") != deployment_run_id
        or record.get("status") != "verified"
        or record.get("validation_issue_count") != 0
        or record.get("readback_verified") is not True
        or not isinstance(source_commit, str)
        or _COMMIT.fullmatch(source_commit) is None
        or source_commit != deployment_source_commit
        or any(record.get(key) != expected for key, expected in required.items())
    ):
        raise SealedProductionFactoryError(
            "sealed Omni deployment record is not verified"
        )
    try:
        return SealedOmniDeploymentTarget.create(**required)  # type: ignore[arg-type]
    except Exception as error:
        raise SealedProductionFactoryError(
            "sealed Omni deployment target is invalid"
        ) from error


def _canonical_json(content: bytes, description: str) -> Any:
    try:
        value = json.loads(content)
        reject_protected_fields(value)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SealedProductionFactoryError(f"{description} is invalid JSON") from error
    except ProtectedFieldError as error:
        raise SealedProductionFactoryError(
            f"{description} contains a protected field"
        ) from error
    if content != _canonical_bytes(value):
        raise SealedProductionFactoryError(f"{description} is not canonical")
    return value


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _repository_path(value: Path, description: str) -> Path:
    try:
        return Path(_relative_path(value, description))
    except FreezeBRecordError as error:
        raise SealedProductionFactoryError(f"{description} path is invalid") from error


def _validated_config(value: object) -> SealedProductionAdapterConfig:
    if type(value) is not SealedProductionAdapterConfig:
        raise SealedProductionFactoryError("production adapter config is invalid")
    parsed = SealedProductionAdapterConfig.create(
        input_spec_path=value.input_spec_path,
        omni_deployment_gate_path=value.omni_deployment_gate_path,
        claude_config_directories=value.claude_config_directories,
        database_environment_root=value.database_environment_root,
        runtime_parent=value.runtime_parent,
    )
    if parsed != value:
        raise SealedProductionFactoryError("production adapter config is not canonical")
    return parsed


def _validated_freeze(value: object) -> FreezeBManifest:
    if type(value) is not FreezeBManifest:
        raise SealedProductionFactoryError("canonical Freeze B is required")
    try:
        parsed = FreezeBManifest.from_dict(value.as_dict())
    except FreezeBError as error:
        raise SealedProductionFactoryError("Freeze B is invalid") from error
    if parsed != value:
        raise SealedProductionFactoryError("Freeze B is not canonical")
    return parsed

"""Commit-addressed database identity loader for direct comparators."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .content_policy import ContentPolicy
from .direct_runtime_binding import (
    DirectDatabaseIdentity,
    DirectRuntimeIdentityError,
)
from .omni_probe_preflight import CommittedSpec, OmniProbePreflightError, committed_spec
from .omni_result_adapter import OmniResultContractError, reject_forbidden_keys

_INVENTORY_PATH = Path("config/databases/livesqlbench-large-v1.json")
_TARGETS_PATH = Path("config/conditions/direct-database-targets-v1.json")
_BENCHMARK = "LiveSQLBench Large-v1"
_INVENTORY_FORMAT_VERSION = 2
_TARGETS_FORMAT_VERSION = 1
_POSTGRES_MAJOR = 18
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DATABASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,127}")
_TARGETS_FIELDS = frozenset(
    {"benchmark", "databases", "format_version", "inventory_path", "inventory_sha256"}
)
_TARGET_FIELDS = frozenset({"connection_target_sha256", "name", "physical_database"})
_MIRROR_FIELDS = frozenset(
    {
        "branch_id",
        "branch_name",
        "organization_id",
        "project_id",
        "provider",
        "region_id",
        "runtime_role",
    }
)


class DirectDatabaseLoadError(ValueError):
    """Raised when committed deployment evidence cannot authorize a database."""


def load_committed_direct_database_identity(
    workspace: Path,
    commit: str,
    *,
    selected_database: str,
    environment: Mapping[str, str] | None = None,
) -> DirectDatabaseIdentity:
    """Combine a committed public inventory with its credential-free target map."""
    database = _database_name(selected_database)
    inventory_spec, targets_spec = _committed_inputs(workspace, commit)
    policy = ContentPolicy.from_environment(
        os.environ if environment is None else environment
    )
    inventory = _safe_json(inventory_spec.content, policy, "database inventory")
    targets = _safe_json(targets_spec.content, policy, "database target sidecar")
    records = _inventory_records(inventory)
    target_records = _target_records(
        targets,
        inventory_sha256=inventory_spec.sha256,
        inventory_names=frozenset(records),
    )
    try:
        record = records[database]
        target = target_records[database]
    except KeyError as error:
        raise DirectDatabaseLoadError(
            "selected database is not present in the committed inventory"
        ) from error
    deployment = _deployment(record, target, database)
    verification = _verification(record)
    return _database_identity(
        database,
        inventory_spec.sha256,
        record,
        deployment,
        verification,
        environment,
    )


def _committed_inputs(
    workspace: Path, commit: str
) -> tuple[CommittedSpec, CommittedSpec]:
    try:
        inventory = committed_spec(workspace, commit, _INVENTORY_PATH)
        targets = committed_spec(workspace, commit, _TARGETS_PATH)
    except OmniProbePreflightError as error:
        raise DirectDatabaseLoadError(str(error)) from error
    return inventory, targets


def _safe_json(
    content: bytes, policy: ContentPolicy, description: str
) -> dict[str, Any]:
    value = _json_object(content, description)
    try:
        reject_forbidden_keys(value)
    except OmniResultContractError as error:
        raise DirectDatabaseLoadError(
            f"{description} contains forbidden fields"
        ) from error
    if policy.sanitize_json(value) != value:
        raise DirectDatabaseLoadError(f"{description} contains sensitive content")
    return value


def _inventory_records(inventory: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if inventory.get("format_version") != _INVENTORY_FORMAT_VERSION:
        raise DirectDatabaseLoadError(
            "database inventory format version is unsupported"
        )
    if (
        inventory.get("benchmark") != _BENCHMARK
        or inventory.get("postgres_major") != _POSTGRES_MAJOR
    ):
        raise DirectDatabaseLoadError(
            "database inventory benchmark identity is invalid"
        )
    values = inventory.get("databases")
    if not isinstance(values, list) or not values:
        raise DirectDatabaseLoadError("database inventory has no database records")
    records: dict[str, Mapping[str, Any]] = {}
    for value in values:
        if not isinstance(value, Mapping):
            raise DirectDatabaseLoadError("database inventory record is invalid")
        name = _database_name(value.get("name"))
        if value.get("alias") != name or name in records:
            raise DirectDatabaseLoadError("database inventory records are not unique")
        _mirror(value)
        _verification(value)
        records[name] = value
    return records


def _target_records(
    sidecar: Mapping[str, Any],
    *,
    inventory_sha256: str,
    inventory_names: frozenset[str],
) -> dict[str, Mapping[str, Any]]:
    if set(sidecar) != _TARGETS_FIELDS:
        raise DirectDatabaseLoadError(
            "database target sidecar must use the exact schema"
        )
    if (
        sidecar.get("format_version") != _TARGETS_FORMAT_VERSION
        or sidecar.get("benchmark") != _BENCHMARK
        or sidecar.get("inventory_path") != _INVENTORY_PATH.as_posix()
    ):
        raise DirectDatabaseLoadError("database target sidecar identity is invalid")
    if sidecar.get("inventory_sha256") != inventory_sha256:
        raise DirectDatabaseLoadError(
            "database target sidecar does not match inventory"
        )
    records = _parse_targets(sidecar.get("databases"))
    if frozenset(records) != inventory_names:
        raise DirectDatabaseLoadError("database target sidecar coverage is not exact")
    return records


def _parse_targets(values: object) -> dict[str, Mapping[str, Any]]:
    if not isinstance(values, list):
        raise DirectDatabaseLoadError("database target sidecar records are invalid")
    records: dict[str, Mapping[str, Any]] = {}
    target_digests: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping) or set(value) != _TARGET_FIELDS:
            raise DirectDatabaseLoadError(
                "database target sidecar must use the exact schema"
            )
        name = _database_name(value.get("name"))
        _database_name(value.get("physical_database"))
        target_digest = _sha256(
            value.get("connection_target_sha256"), "database target"
        )
        if name in records or target_digest in target_digests:
            raise DirectDatabaseLoadError(
                "database target sidecar names and targets are not unique"
            )
        records[name] = value
        target_digests.add(target_digest)
    return records


def _mirror(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("managed_mirror")
    if not isinstance(value, Mapping) or set(value) != _MIRROR_FIELDS:
        raise DirectDatabaseLoadError("database deployment identity is incomplete")
    if value.get("provider") != "neon":
        raise DirectDatabaseLoadError("database deployment provider is unsupported")
    for field in _MIRROR_FIELDS - {"provider"}:
        item = value.get(field)
        if not isinstance(item, str) or not item or "\x00" in item:
            raise DirectDatabaseLoadError("database deployment identity is invalid")
    return value


def _deployment(
    record: Mapping[str, Any], target: Mapping[str, Any], database: str
) -> Mapping[str, Any]:
    mirror = _mirror(record)
    if record.get("name") != database or target.get("name") != database:
        raise DirectDatabaseLoadError("database deployment record does not match")
    return {
        "connection_target_sha256": target["connection_target_sha256"],
        "physical_database": target["physical_database"],
        "runtime_role": mirror["runtime_role"],
    }


def _verification(record: Mapping[str, Any]) -> Mapping[str, Any]:
    value = record.get("verification")
    if not isinstance(value, Mapping):
        raise DirectDatabaseLoadError("database verification is missing")
    if (
        value.get("readonly_role_verified") is not True
        or value.get("external_parity") is not True
    ):
        raise DirectDatabaseLoadError("database deployment is not verified")
    _sha256(value.get("schema_sha256"), "schema")
    _sha256(value.get("content_sha256"), "content")
    server = value.get("postgres_server_version_num")
    if (
        not isinstance(server, str)
        or not server.isdigit()
        or int(server) // 10000 != _POSTGRES_MAJOR
    ):
        raise DirectDatabaseLoadError("database server version is invalid")
    return value


def _database_identity(
    database: str,
    inventory_sha256: str,
    record: Mapping[str, Any],
    deployment: Mapping[str, Any],
    verification: Mapping[str, Any],
    environment: Mapping[str, str] | None,
) -> DirectDatabaseIdentity:
    value = {
        "backend": "postgresql",
        "connection_target_sha256": deployment["connection_target_sha256"],
        "content_sha256": verification["content_sha256"],
        "database_record_sha256": _digest(record),
        "deployment_identity_sha256": _digest(deployment),
        "inventory_sha256": inventory_sha256,
        "physical_database": deployment["physical_database"],
        "postgres_server_version_num": int(verification["postgres_server_version_num"]),
        "runtime_role": deployment["runtime_role"],
        "schema_sha256": verification["schema_sha256"],
        "selected_database": database,
    }
    try:
        return DirectDatabaseIdentity.from_dict(value, environment=environment)
    except DirectRuntimeIdentityError as error:
        raise DirectDatabaseLoadError(
            "committed database identity is invalid"
        ) from error


def _json_object(content: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(
            content.decode("utf-8"),
            parse_constant=lambda constant: _reject_nonfinite(constant),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DirectDatabaseLoadError(f"{description} must be valid JSON") from error
    _require_finite(value)
    if not isinstance(value, dict):
        raise DirectDatabaseLoadError(f"{description} must be an object")
    return value


def _reject_nonfinite(constant: str) -> None:
    raise DirectDatabaseLoadError("database deployment inputs must contain finite JSON")


def _require_finite(value: object) -> None:
    if isinstance(value, Mapping):
        for nested in value.values():
            _require_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _require_finite(nested)
    elif isinstance(value, float) and not math.isfinite(value):
        raise DirectDatabaseLoadError(
            "database deployment inputs must contain finite JSON"
        )


def _database_name(value: object) -> str:
    if not isinstance(value, str) or _DATABASE.fullmatch(value) is None:
        raise DirectDatabaseLoadError("database name is invalid")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DirectDatabaseLoadError(f"{label} SHA-256 is invalid")
    return value


def _digest(value: object) -> str:
    try:
        content = (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
    except (TypeError, ValueError) as error:
        raise DirectDatabaseLoadError(
            "database identity must contain strict JSON"
        ) from error
    return hashlib.sha256(content).hexdigest()

"""Validated inventory for pinned public LiveSQLBench HKB files."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class HKBInventoryError(ValueError):
    """Raised when the committed public HKB inventory is invalid."""


@dataclass(frozen=True)
class HKBSourceFile:
    """One immutable public HKB source object."""

    database: str
    path: str
    oid: str
    size: int
    sha256: str


@dataclass(frozen=True)
class HKBSourceInventory:
    """Pinned dataset identity and its expected HKB source objects."""

    dataset: str
    revision: str
    files: tuple[HKBSourceFile, ...]
    inventory_sha256: str


_TOP_LEVEL_FIELDS = frozenset({"schema_version", "dataset", "revision", "files"})
_FILE_FIELDS = frozenset({"database", "path", "oid", "size", "sha256"})
PUBLIC_HKB_DATASET = "birdsql/livesqlbench-large-v1"


def _require_exact_fields(
    value: dict[str, Any], expected: frozenset[str], label: str
) -> None:
    missing = sorted(expected - value.keys())
    unknown = sorted(value.keys() - expected)
    if missing:
        raise HKBInventoryError(f"{label} missing fields: {', '.join(missing)}")
    if unknown:
        raise HKBInventoryError(f"{label} unknown fields: {', '.join(unknown)}")


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise HKBInventoryError(f"{label} must be a non-empty string")
    return value


def _require_hex(value: Any, length: int, label: str) -> str:
    text = _require_string(value, label)
    if len(text) != length or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise HKBInventoryError(f"{label} must be {length} lowercase hex characters")
    return text


def _parse_source_file(value: Any, index: int) -> HKBSourceFile:
    label = f"files[{index}]"
    if not isinstance(value, dict):
        raise HKBInventoryError(f"{label} must be an object")
    _require_exact_fields(value, _FILE_FIELDS, label)
    database = _require_string(value["database"], f"{label}.database")
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
        for character in database
    ):
        raise HKBInventoryError(
            f"{label}.database must contain only lowercase letters, digits, and underscores"
        )
    path = _require_string(value["path"], f"{label}.path")
    expected_path = f"{database}/{database}_kb.jsonl"
    if path != expected_path:
        raise HKBInventoryError(
            f"{label}.path must be the canonical HKB path {expected_path}"
        )
    size = value["size"]
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise HKBInventoryError(f"{label}.size must be a positive integer")
    return HKBSourceFile(
        database=database,
        path=path,
        oid=_require_hex(value["oid"], 40, f"{label}.oid"),
        size=size,
        sha256=_require_hex(value["sha256"], 64, f"{label}.sha256"),
    )


def _decode_inventory(content: bytes, source: Path) -> dict[str, Any]:
    try:
        value = json.loads(content, object_pairs_hook=_strict_json_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise HKBInventoryError(
            f"cannot parse HKB inventory {source}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise HKBInventoryError("HKB inventory must be a JSON object")
    return value


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise HKBInventoryError(f"duplicate JSON field {key}")
        value[key] = item
    return value


def git_blob_oid(content: bytes) -> str:
    """Return the Git blob identifier for public-source provenance."""

    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def load_hkb_source_inventory(path: Path | str) -> HKBSourceInventory:
    """Load a strict, hashable inventory without accepting extra fields."""

    source = Path(path)
    try:
        content = source.read_bytes()
    except OSError as error:
        raise HKBInventoryError(
            f"cannot read HKB inventory {source}: {error}"
        ) from error
    value = _decode_inventory(content, source)
    _require_exact_fields(value, _TOP_LEVEL_FIELDS, "inventory")
    schema_version = value["schema_version"]
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        raise HKBInventoryError("inventory.schema_version must equal integer 1")
    if value["dataset"] != PUBLIC_HKB_DATASET:
        raise HKBInventoryError(f"inventory.dataset must equal {PUBLIC_HKB_DATASET}")
    raw_files = value["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise HKBInventoryError("inventory.files must be a non-empty list")
    files = tuple(
        sorted(
            (_parse_source_file(item, index) for index, item in enumerate(raw_files)),
            key=lambda item: item.database,
        )
    )
    databases = [item.database for item in files]
    if len(set(databases)) != len(databases):
        raise HKBInventoryError("inventory contains duplicate databases")
    return HKBSourceInventory(
        dataset=PUBLIC_HKB_DATASET,
        revision=_require_hex(value["revision"], 40, "inventory.revision"),
        files=files,
        inventory_sha256=hashlib.sha256(content).hexdigest(),
    )

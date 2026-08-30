"""Reproduce the human-selected sealed MVP identity frame from public inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .protected_fields import ProtectedFieldError, reject_protected_fields


class SealedMVPFrameError(RuntimeError):
    """Fail-closed public frame construction error."""


def generate_sealed_mvp_frame(
    *,
    eligible_manifest: Path,
    test_ids_path: Path,
    config_path: Path,
    ids_output: Path,
    metadata_output: Path,
) -> dict[str, Any]:
    """Select frozen test identities by public database membership."""
    config = _mapping(_read_json(config_path), "frame spec")
    if set(config) != {
        "decision_bead_id",
        "excluded_databases",
        "expected_question_count",
        "kind",
        "schema_version",
    }:
        raise SealedMVPFrameError("frame spec schema is invalid")
    if config["kind"] != "sealed-mvp-frame-spec" or config["schema_version"] != 1:
        raise SealedMVPFrameError("frame spec identity is invalid")
    decision = _text(config["decision_bead_id"], "decision bead")
    excluded = _strings(config["excluded_databases"], "excluded databases")
    expected_count = config["expected_question_count"]
    if (
        isinstance(expected_count, bool)
        or not isinstance(expected_count, int)
        or expected_count <= 0
    ):
        raise SealedMVPFrameError("expected question count is invalid")

    test_content = test_ids_path.read_bytes()
    test_ids = _ids(test_content)
    public_content = eligible_manifest.read_bytes()
    databases = _public_databases(public_content)
    if not set(test_ids).issubset(databases):
        raise SealedMVPFrameError("test identity is absent from public manifest")
    selected = tuple(item for item in test_ids if databases[item] not in excluded)
    removed = tuple(item for item in test_ids if databases[item] in excluded)
    if len(selected) != expected_count:
        raise SealedMVPFrameError("selected question count does not match frame spec")
    if {databases[item] for item in removed} != set(excluded):
        raise SealedMVPFrameError("excluded database coverage is incomplete")

    ids_bytes = "".join(f"{item}\n" for item in selected).encode()
    metadata = {
        "decision_bead_id": decision,
        "excluded_count": len(removed),
        "excluded_databases": list(excluded),
        "kind": "sealed-mvp-frame-metadata",
        "schema_version": 1,
        "selected_count": len(selected),
        "selected_database_counts": dict(
            sorted(Counter(databases[item] for item in selected).items())
        ),
        "selected_ids_sha256": hashlib.sha256(ids_bytes).hexdigest(),
        "source": {
            "eligible_manifest_path": str(eligible_manifest),
            "eligible_manifest_sha256": hashlib.sha256(public_content).hexdigest(),
            "frame_spec_path": str(config_path),
            "frame_spec_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
            "test_ids_path": str(test_ids_path),
            "test_ids_sha256": hashlib.sha256(test_content).hexdigest(),
        },
    }
    ids_output.parent.mkdir(parents=True, exist_ok=True)
    metadata_output.parent.mkdir(parents=True, exist_ok=True)
    ids_output.write_bytes(ids_bytes)
    metadata_output.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return metadata


def sealed_mvp_frame_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eligible-manifest", type=Path, required=True)
    parser.add_argument("--test-ids", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ids-output", type=Path, required=True)
    parser.add_argument("--metadata-output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    generate_sealed_mvp_frame(
        eligible_manifest=arguments.eligible_manifest,
        test_ids_path=arguments.test_ids,
        config_path=arguments.config,
        ids_output=arguments.ids_output,
        metadata_output=arguments.metadata_output,
    )
    return 0


def _public_databases(content: bytes) -> dict[str, str]:
    records: dict[str, str] = {}
    try:
        lines = content.splitlines(keepends=True)
        if not lines or any(not line.endswith(b"\n") for line in lines):
            raise SealedMVPFrameError("public manifest must be newline-terminated")
        for raw in lines:
            value = json.loads(raw)
            reject_protected_fields(value)
            record = _mapping(value, "public manifest record")
            instance_id = _text(record.get("instance_id"), "public instance identity")
            database = _text(record.get("selected_database"), "public database")
            if instance_id in records:
                raise SealedMVPFrameError("public manifest identity is duplicated")
            records[instance_id] = database
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SealedMVPFrameError("public manifest is invalid JSONL") from error
    except ProtectedFieldError as error:
        raise SealedMVPFrameError(
            "public manifest contains a protected field"
        ) from error
    return records


def _ids(content: bytes) -> tuple[str, ...]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise SealedMVPFrameError("test IDs are invalid UTF-8") from error
    if not text or not text.endswith("\n") or "\r" in text:
        raise SealedMVPFrameError("test IDs must be newline-terminated")
    values = tuple(text.splitlines())
    if any(not value or value.strip() != value for value in values):
        raise SealedMVPFrameError("test identity is invalid")
    if len(values) != len(set(values)) or values != tuple(sorted(values)):
        raise SealedMVPFrameError("test IDs must be unique and sorted")
    return values


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SealedMVPFrameError("frame spec is invalid JSON") from error


def _mapping(value: object, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SealedMVPFrameError(f"{description} is invalid")
    return value


def _text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise SealedMVPFrameError(f"{description} is invalid")
    return value


def _strings(value: object, description: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SealedMVPFrameError(f"{description} are invalid")
    result = tuple(_text(item, description) for item in value)
    if not result or len(result) != len(set(result)) or result != tuple(sorted(result)):
        raise SealedMVPFrameError(f"{description} must be unique and sorted")
    return result

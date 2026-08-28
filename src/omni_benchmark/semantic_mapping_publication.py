"""Build hash-bound public HKB-to-schema mapping artifacts."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .hkb_io import (
    HKBFileSafetyError,
    prepare_safe_parent,
    publish_flat_files,
    read_regular_file,
)
from .semantic_mapping import compile_mapping_spec, encode_mapping_jsonl


class SemanticMappingPublicationError(ValueError):
    """Raised when public mapping inputs or their provenance are invalid."""


MAX_SPEC_BYTES = 256_000
MAX_HKB_BYTES = 2_000_000
MAX_SCHEMA_BYTES = 8_000_000
MAX_MANIFEST_BYTES = 256_000


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SemanticMappingPublicationError(f"duplicate JSON field {key}")
        value[key] = item
    return value


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SemanticMappingPublicationError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise SemanticMappingPublicationError(f"{label} must be a JSON object")
    return value


def _jsonl_objects(content: bytes, label: str) -> list[dict[str, Any]]:
    if not content or not content.endswith(b"\n"):
        raise SemanticMappingPublicationError(f"{label} must end with a newline")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        records.append(_json_object(line, f"{label} line {line_number}"))
    return records


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SemanticMappingPublicationError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticMappingPublicationError(f"{label} must be text")
    return value


def _verified_source_metadata(
    manifest: Mapping[str, Any], hkb_bytes: bytes, schema_bytes: bytes
) -> dict[str, str]:
    if manifest.get("kind") != "public-schema-intermediate-representation":
        raise SemanticMappingPublicationError("unexpected schema manifest kind")
    output = _mapping(manifest.get("output"), "schema manifest output")
    if output.get("sha256") != _sha256(schema_bytes):
        raise SemanticMappingPublicationError("schema IR hash does not match manifest")
    source = _mapping(manifest.get("source"), "schema manifest source")
    hkb = _mapping(source.get("companion_hkb_ir"), "companion HKB source")
    if hkb.get("sha256") != _sha256(hkb_bytes):
        raise SemanticMappingPublicationError("HKB IR hash does not match manifest")
    return {
        "dataset": _text(source.get("dataset"), "source dataset"),
        "hkb_manifest_sha256": _text(hkb.get("manifest_sha256"), "HKB manifest hash"),
        "revision": _text(source.get("revision"), "source revision"),
    }


def _manifest(
    spec: Mapping[str, Any],
    spec_bytes: bytes,
    hkb_bytes: bytes,
    schema_bytes: bytes,
    schema_manifest_bytes: bytes,
    output: bytes,
    summary: Mapping[str, Any],
    source: Mapping[str, str],
) -> dict[str, Any]:
    database = _text(spec.get("database"), "mapping database")
    return {
        "counts": summary,
        "database": database,
        "kind": "public-hkb-semantic-mapping",
        "output": {
            "file": f"{database}.mapping.jsonl",
            "sha256": _sha256(output),
        },
        "schema_version": 1,
        "source": {
            "dataset": source["dataset"],
            "hkb_ir": {
                "manifest_sha256": source["hkb_manifest_sha256"],
                "sha256": _sha256(hkb_bytes),
            },
            "mapping_spec": {"sha256": _sha256(spec_bytes)},
            "revision": source["revision"],
            "schema_ir": {
                "manifest_sha256": _sha256(schema_manifest_bytes),
                "sha256": _sha256(schema_bytes),
            },
        },
        "validation": {
            "all_hkb_nodes_classified_once": True,
            "all_schema_bindings_resolve": True,
            "hidden_annotations_used": False,
            "public_inputs_only": True,
            "status": "passed",
        },
    }


def build_mapping_artifacts(
    spec_bytes: bytes,
    hkb_bytes: bytes,
    schema_bytes: bytes,
    schema_manifest_bytes: bytes,
) -> tuple[bytes, dict[str, Any]]:
    """Compile authenticated public inputs into mapping JSONL and a manifest."""
    spec = _json_object(spec_bytes, "mapping specification")
    hkb_records = _jsonl_objects(hkb_bytes, "HKB IR")
    schema_records = _jsonl_objects(schema_bytes, "schema IR")
    schema_manifest = _json_object(schema_manifest_bytes, "schema manifest")
    source = _verified_source_metadata(schema_manifest, hkb_bytes, schema_bytes)
    if spec.get("database") != schema_manifest.get("database"):
        raise SemanticMappingPublicationError("mapping/schema database mismatch")
    records = compile_mapping_spec(spec, hkb_records, schema_records)
    output = encode_mapping_jsonl(records)
    dispositions: dict[str, int] = {}
    for record in records:
        disposition = record["disposition"]
        dispositions[disposition] = dispositions.get(disposition, 0) + 1
    summary = {
        "dispositions": dict(sorted(dispositions.items())),
        "hkb_nodes": len(records),
    }
    return output, _manifest(
        spec,
        spec_bytes,
        hkb_bytes,
        schema_bytes,
        schema_manifest_bytes,
        output,
        summary,
        source,
    )


def _manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _safe_output_name(value: Any) -> str:
    name = _text(value, "mapping output file")
    if name != Path(name).name or "/" in name or "\\" in name or "\x00" in name:
        raise SemanticMappingPublicationError(
            "mapping output must be one safe file name"
        )
    return name


def _read_inputs(
    spec_path: Path,
    hkb_path: Path,
    schema_path: Path,
    schema_manifest_path: Path,
) -> tuple[bytes, bytes, bytes, bytes]:
    try:
        return (
            read_regular_file(spec_path, maximum_bytes=MAX_SPEC_BYTES),
            read_regular_file(hkb_path, maximum_bytes=MAX_HKB_BYTES),
            read_regular_file(schema_path, maximum_bytes=MAX_SCHEMA_BYTES),
            read_regular_file(schema_manifest_path, maximum_bytes=MAX_MANIFEST_BYTES),
        )
    except HKBFileSafetyError as error:
        raise SemanticMappingPublicationError(str(error)) from error


def publish_mapping_artifacts(
    spec_path: Path,
    hkb_path: Path,
    schema_path: Path,
    schema_manifest_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Publish a deterministic mapping JSONL and manifest to a safe directory."""
    inputs = _read_inputs(spec_path, hkb_path, schema_path, schema_manifest_path)
    output, manifest = build_mapping_artifacts(*inputs)
    output_name = _safe_output_name(manifest["output"]["file"])
    try:
        prepare_safe_parent(output_root)
        with tempfile.TemporaryDirectory(
            prefix=".public-semantic-mapping-", dir=output_root.parent
        ) as temporary:
            staging = Path(temporary)
            (staging / output_name).write_bytes(output)
            (staging / "manifest.json").write_bytes(_manifest_bytes(manifest))
            publish_flat_files(staging, output_root, (output_name, "manifest.json"))
    except HKBFileSafetyError as error:
        raise SemanticMappingPublicationError(str(error)) from error
    return manifest

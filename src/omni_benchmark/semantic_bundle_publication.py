"""Authenticate and publish deterministic public Omni semantic bundles."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from .hkb_io import (
    HKBFileSafetyError,
    prepare_safe_parent,
    publish_flat_files,
    read_regular_file,
)
from .semantic_bundle import (
    SemanticBundle,
    SemanticBundleError,
    compile_e02_relationship_bundle,
    compile_semantic_bundle,
    reject_protected_fields,
)
from .semantic_c5 import compile_c5_tuned_bundle


class SemanticBundlePublicationError(ValueError):
    """Raised when bundle sources or publication boundaries are invalid."""


MAX_SPEC_BYTES = 256_000
MAX_HKB_BYTES = 2_000_000
MAX_SCHEMA_BYTES = 8_000_000
MAX_MAPPING_BYTES = 2_000_000
MAX_MANIFEST_BYTES = 256_000
_TRUSTED_MAPPING_VALIDATION = {
    "all_hkb_nodes_classified_once": True,
    "all_schema_bindings_resolve": True,
    "hidden_annotations_used": False,
    "public_inputs_only": True,
    "status": "passed",
}


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SemanticBundlePublicationError(f"duplicate JSON field {key}")
        result[key] = value
    return result


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SemanticBundlePublicationError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise SemanticBundlePublicationError(f"{label} must be a JSON object")
    return value


def _jsonl_objects(content: bytes, label: str) -> list[dict[str, Any]]:
    if not content or not content.endswith(b"\n"):
        raise SemanticBundlePublicationError(f"{label} must end with a newline")
    return [
        _json_object(line, f"{label} line {number}")
        for number, line in enumerate(content.splitlines(), start=1)
    ]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SemanticBundlePublicationError(f"{label} must be an object")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticBundlePublicationError(f"{label} must be text")
    return value


def _sha256_text(value: Any, label: str) -> str:
    digest = _text(value, label)
    invalid_character = any(character not in "0123456789abcdef" for character in digest)
    if len(digest) != 64 or invalid_character:
        raise SemanticBundlePublicationError(f"{label} must be a SHA-256 digest")
    return digest


def _verify_mapping_provenance(source: Mapping[str, Any]) -> None:
    _text(source.get("dataset"), "mapping source dataset")
    _text(source.get("revision"), "mapping source revision")
    hkb_source = _mapping(source.get("hkb_ir"), "mapping HKB source")
    schema_source = _mapping(source.get("schema_ir"), "mapping schema source")
    spec_source = _mapping(source.get("mapping_spec"), "mapping specification source")
    _sha256_text(hkb_source.get("manifest_sha256"), "HKB manifest hash")
    _sha256_text(schema_source.get("manifest_sha256"), "schema manifest hash")
    _sha256_text(spec_source.get("sha256"), "mapping specification hash")


def _verified_mapping_manifest(
    manifest: Mapping[str, Any], hkb: bytes, schema: bytes, mapping: bytes
) -> str:
    if manifest.get("kind") != "public-hkb-semantic-mapping":
        raise SemanticBundlePublicationError("unexpected mapping manifest kind")
    if manifest.get("schema_version") != 1:
        raise SemanticBundlePublicationError(
            "unsupported mapping manifest schema_version"
        )
    if manifest.get("validation") != _TRUSTED_MAPPING_VALIDATION:
        raise SemanticBundlePublicationError(
            "mapping manifest validation is not trusted"
        )
    database = _text(manifest.get("database"), "mapping database")
    output = _mapping(manifest.get("output"), "mapping manifest output")
    if output.get("file") != f"{database}.mapping.jsonl":
        raise SemanticBundlePublicationError("unexpected mapping output file")
    if output.get("sha256") != _sha256(mapping):
        raise SemanticBundlePublicationError("mapping hash does not match manifest")
    source = _mapping(manifest.get("source"), "mapping manifest source")
    _verify_mapping_provenance(source)
    hkb_source = _mapping(source.get("hkb_ir"), "mapping HKB source")
    schema_source = _mapping(source.get("schema_ir"), "mapping schema source")
    if hkb_source.get("sha256") != _sha256(hkb):
        raise SemanticBundlePublicationError("HKB hash does not match mapping manifest")
    if schema_source.get("sha256") != _sha256(schema):
        raise SemanticBundlePublicationError(
            "schema hash does not match mapping manifest"
        )
    return database


def _file_records(files: Mapping[str, bytes]) -> list[dict[str, Any]]:
    return [
        {
            "file": name,
            "sha256": _sha256(content),
            "size_bytes": len(content),
        }
        for name, content in files.items()
    ]


def _manifest(
    compiled: Mapping[str, Any],
    files: Mapping[str, bytes],
    spec: bytes,
    hkb: bytes,
    schema: bytes,
    mapping: bytes,
    mapping_manifest: bytes,
) -> dict[str, Any]:
    return {
        **dict(compiled),
        "files": _file_records(files),
        "source": {
            "bundle_spec": {"sha256": _sha256(spec)},
            "hkb_ir": {"sha256": _sha256(hkb)},
            "mapping": {"sha256": _sha256(mapping)},
            "mapping_manifest": {"sha256": _sha256(mapping_manifest)},
            "schema_ir": {"sha256": _sha256(schema)},
        },
    }


def build_bundle_artifacts(
    spec_bytes: bytes,
    hkb_bytes: bytes,
    schema_bytes: bytes,
    mapping_bytes: bytes,
    mapping_manifest_bytes: bytes,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Authenticate public inputs and compile a hash-bound Omni bundle."""
    return _build_bundle_artifacts(
        spec_bytes,
        hkb_bytes,
        schema_bytes,
        mapping_bytes,
        mapping_manifest_bytes,
        compile_semantic_bundle,
    )


def build_e02_bundle_artifacts(
    spec_bytes: bytes,
    hkb_bytes: bytes,
    schema_bytes: bytes,
    mapping_bytes: bytes,
    mapping_manifest_bytes: bytes,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Authenticate public inputs and compile the opt-in E02 candidate."""
    return _build_bundle_artifacts(
        spec_bytes,
        hkb_bytes,
        schema_bytes,
        mapping_bytes,
        mapping_manifest_bytes,
        compile_e02_relationship_bundle,
    )


def build_c5_bundle_artifacts(
    spec_bytes: bytes,
    hkb_bytes: bytes,
    schema_bytes: bytes,
    mapping_bytes: bytes,
    mapping_manifest_bytes: bytes,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Authenticate public inputs and compile the C5 tuned governed bundle."""
    return _build_bundle_artifacts(
        spec_bytes,
        hkb_bytes,
        schema_bytes,
        mapping_bytes,
        mapping_manifest_bytes,
        compile_c5_tuned_bundle,
    )


def _build_bundle_artifacts(
    spec_bytes: bytes,
    hkb_bytes: bytes,
    schema_bytes: bytes,
    mapping_bytes: bytes,
    mapping_manifest_bytes: bytes,
    compiler: Callable[
        [
            Mapping[str, Any],
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, Any]],
        ],
        SemanticBundle,
    ],
) -> tuple[dict[str, bytes], dict[str, Any]]:
    spec = _json_object(spec_bytes, "bundle specification")
    hkb_records = _jsonl_objects(hkb_bytes, "HKB IR")
    schema_records = _jsonl_objects(schema_bytes, "schema IR")
    mapping_records = _jsonl_objects(mapping_bytes, "semantic mapping")
    mapping_manifest = _json_object(mapping_manifest_bytes, "mapping manifest")
    try:
        reject_protected_fields(mapping_manifest)
    except SemanticBundleError as error:
        raise SemanticBundlePublicationError(str(error)) from error
    database = _verified_mapping_manifest(
        mapping_manifest, hkb_bytes, schema_bytes, mapping_bytes
    )
    if spec.get("database") != database:
        raise SemanticBundlePublicationError("bundle/mapping database mismatch")
    try:
        compiled = compiler(spec, hkb_records, schema_records, mapping_records)
    except SemanticBundleError as error:
        raise SemanticBundlePublicationError(str(error)) from error
    files = {name: content.encode() for name, content in compiled.files.items()}
    return files, _manifest(
        compiled.manifest,
        files,
        spec_bytes,
        hkb_bytes,
        schema_bytes,
        mapping_bytes,
        mapping_manifest_bytes,
    )


def _read_inputs(
    spec_path: Path,
    hkb_path: Path,
    schema_path: Path,
    mapping_path: Path,
    mapping_manifest_path: Path,
) -> tuple[bytes, bytes, bytes, bytes, bytes]:
    try:
        return (
            read_regular_file(spec_path, maximum_bytes=MAX_SPEC_BYTES),
            read_regular_file(hkb_path, maximum_bytes=MAX_HKB_BYTES),
            read_regular_file(schema_path, maximum_bytes=MAX_SCHEMA_BYTES),
            read_regular_file(mapping_path, maximum_bytes=MAX_MAPPING_BYTES),
            read_regular_file(mapping_manifest_path, maximum_bytes=MAX_MANIFEST_BYTES),
        )
    except HKBFileSafetyError as error:
        raise SemanticBundlePublicationError(str(error)) from error


def _manifest_bytes(manifest: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def publish_bundle_artifacts(
    spec_path: Path,
    hkb_path: Path,
    schema_path: Path,
    mapping_path: Path,
    mapping_manifest_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Publish exactly one flat semantic bundle and its provenance manifest."""
    return _publish_bundle_artifacts(
        spec_path,
        hkb_path,
        schema_path,
        mapping_path,
        mapping_manifest_path,
        output_root,
        build_bundle_artifacts,
    )


def publish_e02_bundle_artifacts(
    spec_path: Path,
    hkb_path: Path,
    schema_path: Path,
    mapping_path: Path,
    mapping_manifest_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Publish one flat, hash-bound E02 candidate bundle."""
    return _publish_bundle_artifacts(
        spec_path,
        hkb_path,
        schema_path,
        mapping_path,
        mapping_manifest_path,
        output_root,
        build_e02_bundle_artifacts,
    )


def publish_c5_bundle_artifacts(
    spec_path: Path,
    hkb_path: Path,
    schema_path: Path,
    mapping_path: Path,
    mapping_manifest_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Publish one flat, hash-bound C5 tuned governed bundle."""
    return _publish_bundle_artifacts(
        spec_path,
        hkb_path,
        schema_path,
        mapping_path,
        mapping_manifest_path,
        output_root,
        build_c5_bundle_artifacts,
    )


def _publish_bundle_artifacts(
    spec_path: Path,
    hkb_path: Path,
    schema_path: Path,
    mapping_path: Path,
    mapping_manifest_path: Path,
    output_root: Path,
    builder: Callable[
        [bytes, bytes, bytes, bytes, bytes],
        tuple[dict[str, bytes], dict[str, Any]],
    ],
) -> dict[str, Any]:
    inputs = _read_inputs(
        spec_path, hkb_path, schema_path, mapping_path, mapping_manifest_path
    )
    files, manifest = builder(*inputs)
    output_names = (*files, "manifest.json")
    try:
        prepare_safe_parent(output_root)
        with tempfile.TemporaryDirectory(
            prefix=".public-semantic-bundle-", dir=output_root.parent
        ) as temporary:
            staging = Path(temporary)
            for name, content in files.items():
                (staging / name).write_bytes(content)
            (staging / "manifest.json").write_bytes(_manifest_bytes(manifest))
            publish_flat_files(staging, output_root, output_names)
    except HKBFileSafetyError as error:
        raise SemanticBundlePublicationError(str(error)) from error
    return manifest

"""Pure deployment planning and readback verification for public Omni bundles."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_MANIFEST_NAME = "manifest.json"
_MANIFEST_KIND = "public-omni-semantic-bundle"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_FIELD_REFERENCE = rf"\$\{{{_IDENTIFIER}\.{_IDENTIFIER}\}}"
_RELATIONSHIP_ON_SQL = re.compile(
    rf"{_FIELD_REFERENCE} = {_FIELD_REFERENCE}"
    rf"(?: AND {_FIELD_REFERENCE} = {_FIELD_REFERENCE})*"
)
_VIEW_NAME = re.compile(
    rf"(?P<catalog>{_IDENTIFIER})\."
    rf"(?P<schema>{_IDENTIFIER})__(?P<table>{_IDENTIFIER})\.view"
)
_FLAT_VIEW_NAME = re.compile(rf"(?P<table>{_IDENTIFIER})\.view")
_TOPIC_NAME = re.compile(rf"{_IDENTIFIER}\.topic")
_VIEW_IDENTITY_KEYS = frozenset({"catalog", "schema", "table_name"})
_FILE_FIELDS = frozenset({"file", "sha256", "size_bytes"})
_DIRECT_BINDING_FIELDS = frozenset({"field_name", "file", "source_stable_id", "sql"})
# A physical column name can hold characters no bare identifier may carry, such
# as the slash in "total_escape_rate_kg/s"; quoted, it is still a bare reference.
_QUOTED_COLUMN_SQL = r'"[^"\x00-\x1f]+"'
_DIRECT_IDENTIFIER_SQL = re.compile(rf"(?:{_IDENTIFIER}|{_QUOTED_COLUMN_SQL})")
_RELATIONSHIP_FIELDS = frozenset(
    {
        "join_from_view",
        "join_to_view",
        "join_type",
        "on_sql",
        "relationship_type",
        "reversible",
    }
)


class OmniSemanticDeploymentError(ValueError):
    """Raised when a public bundle or branch readback is not exact."""


@dataclass(frozen=True)
class OmniSemanticDeploymentFile:
    """One authenticated local file and its deterministic remote extension path."""

    local_name: str
    remote_path: str
    content: bytes
    sha256: str


@dataclass(frozen=True)
class OmniSemanticDirectPhysicalBinding:
    """One compiler-attested public-schema identity binding."""

    remote_path: str
    field_name: str
    source_stable_id: str
    sql: str


@dataclass(frozen=True)
class OmniSemanticDeploymentPlan:
    """Authenticated public-only inputs for one database deployment."""

    database: str
    manifest_sha256: str
    files: tuple[OmniSemanticDeploymentFile, ...]
    direct_physical_bindings: tuple[OmniSemanticDirectPhysicalBinding, ...]


class _UniqueSafeLoader(yaml.SafeLoader):
    """SafeLoader variant that refuses duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueSafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as error:
            raise OmniSemanticDeploymentError(
                "YAML mapping key is not scalar"
            ) from error
        if duplicate:
            raise OmniSemanticDeploymentError(f"YAML contains duplicate key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def build_semantic_deployment_plan(root: Path) -> OmniSemanticDeploymentPlan:
    """Authenticate a manifest and map every local bundle file to Omni paths."""
    bundle_root = _require_bundle_root(root)
    manifest_bytes = _read_regular_file(bundle_root / _MANIFEST_NAME, "manifest")
    manifest = _parse_manifest(manifest_bytes)
    database = _require_identifier(manifest.get("database"), "manifest database")
    records = _manifest_records(manifest.get("files"))
    _require_exact_local_files(bundle_root, tuple(record["file"] for record in records))
    files = tuple(
        _deployment_file(bundle_root, record, database)
        for record in sorted(records, key=lambda item: item["file"])
    )
    _require_unique_paths(files)
    direct_physical_bindings = _direct_physical_bindings(
        manifest.get("direct_physical_bindings", []), files, database
    )
    return OmniSemanticDeploymentPlan(
        database=database,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        files=files,
        direct_physical_bindings=direct_physical_bindings,
    )


def verify_semantic_deployment_readback(
    plan: OmniSemanticDeploymentPlan, readback: Mapping[str, str | bytes]
) -> None:
    """Compare safe-parsed remote documents after the exact view projection."""
    if not isinstance(plan, OmniSemanticDeploymentPlan):
        raise OmniSemanticDeploymentError("readback requires a deployment plan")
    remote = _canonical_readback(readback)
    expected_paths = {item.remote_path for item in plan.files}
    if set(remote) != expected_paths:
        raise OmniSemanticDeploymentError("readback path set does not match plan")
    for item in plan.files:
        expected = _expected_remote_document(item)
        actual = _parse_yaml(
            remote[item.remote_path],
            f"readback {item.remote_path}",
            allow_sequence=item.local_name == "relationships",
        )
        if item.local_name != "relationships":
            assert isinstance(actual, Mapping)
            assert isinstance(expected, Mapping)
            actual = _project_attested_view_identity(actual, item)
            actual = _restore_stripped_direct_physical_sql(
                actual,
                expected,
                tuple(
                    binding
                    for binding in plan.direct_physical_bindings
                    if binding.remote_path == item.remote_path
                ),
            )
        if not _semantic_documents_equal(actual, expected):
            raise OmniSemanticDeploymentError(
                f"readback semantic content differs for {item.remote_path}"
            )


def semantic_deployment_sha256(plan: OmniSemanticDeploymentPlan) -> str:
    """Hash the authenticated semantic projection deployed to Omni."""
    if not isinstance(plan, OmniSemanticDeploymentPlan):
        raise OmniSemanticDeploymentError("semantic digest requires a deployment plan")
    documents = {
        item.remote_path: _expected_remote_document(item) for item in plan.files
    }
    try:
        content = json.dumps(
            documents,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise OmniSemanticDeploymentError(
            "semantic deployment content is not canonical JSON"
        ) from error
    return hashlib.sha256(content).hexdigest()


def verified_semantic_deployment_sha256(
    plan: OmniSemanticDeploymentPlan,
    readback: Mapping[str, str | bytes],
) -> str:
    """Verify a branch readback, then return its authenticated plan digest."""
    verify_semantic_deployment_readback(plan, readback)
    return semantic_deployment_sha256(plan)


def _require_bundle_root(root: Path) -> Path:
    if not isinstance(root, Path):
        raise OmniSemanticDeploymentError("bundle root must be a Path")
    try:
        metadata = root.lstat()
        if root.is_symlink():
            raise OmniSemanticDeploymentError("bundle root cannot be a symlink")
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise OmniSemanticDeploymentError("bundle root is unavailable") from error
    if not stat.S_ISDIR(metadata.st_mode) or not resolved.is_dir():
        raise OmniSemanticDeploymentError("bundle root must be a directory")
    return resolved


def _parse_manifest(content: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(content, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OmniSemanticDeploymentError("manifest is not valid JSON") from error
    if not isinstance(value, Mapping):
        raise OmniSemanticDeploymentError("manifest must be an object")
    if value.get("kind") != _MANIFEST_KIND:
        raise OmniSemanticDeploymentError("manifest kind is invalid")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise OmniSemanticDeploymentError("manifest schema version is invalid")
    return value


def _unique_json_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OmniSemanticDeploymentError(f"manifest contains duplicate key {key}")
        result[key] = value
    return result


def _manifest_records(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise OmniSemanticDeploymentError("manifest files must be a non-empty array")
    records = tuple(_manifest_record(item) for item in value)
    names = [record["file"] for record in records]
    if len(names) != len(set(names)):
        raise OmniSemanticDeploymentError(
            "manifest contains duplicate local file names"
        )
    if len(names) != len({name.casefold() for name in names}):
        raise OmniSemanticDeploymentError("manifest local file names have a collision")
    return records


def _manifest_record(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FILE_FIELDS:
        raise OmniSemanticDeploymentError("manifest file record is malformed")
    name = _require_local_name(value.get("file"))
    digest = value.get("sha256")
    size = value.get("size_bytes")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise OmniSemanticDeploymentError("manifest file hash is invalid")
    if type(size) is not int or size < 0:
        raise OmniSemanticDeploymentError("manifest file size is invalid")
    return {"file": name, "sha256": digest, "size_bytes": size}


def _require_local_name(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise OmniSemanticDeploymentError("local file name is invalid")
    if "/" in value or "\\" in value or ".." in value or Path(value).name != value:
        raise OmniSemanticDeploymentError("local file path is not confined")
    if value not in {"relationships", "model"} and (
        _VIEW_NAME.fullmatch(value) is None
        and _FLAT_VIEW_NAME.fullmatch(value) is None
        and _TOPIC_NAME.fullmatch(value) is None
    ):
        suffix = Path(value).suffix
        detail = "suffix" if suffix not in {".view", ".topic"} else "view or topic name"
        raise OmniSemanticDeploymentError(f"local file {detail} is invalid")
    return value


def _require_exact_local_files(root: Path, expected: tuple[str, ...]) -> None:
    actual = {entry.name for entry in root.iterdir() if entry.name != _MANIFEST_NAME}
    if actual != set(expected):
        raise OmniSemanticDeploymentError("local file set does not match manifest")


def _deployment_file(
    root: Path, record: Mapping[str, Any], database: str
) -> OmniSemanticDeploymentFile:
    name = record["file"]
    content = _read_regular_file(root / name, f"bundle file {name}")
    if len(content) != record["size_bytes"]:
        raise OmniSemanticDeploymentError(f"bundle file size mismatch for {name}")
    digest = hashlib.sha256(content).hexdigest()
    if digest != record["sha256"]:
        raise OmniSemanticDeploymentError(f"bundle file hash mismatch for {name}")
    document = _parse_yaml(
        content, f"local file {name}", allow_sequence=name == "relationships"
    )
    if name == "relationships":
        _validate_relationship_document(document)
    if name == "model":
        _validate_model_document(document)
    remote_path = _remote_path(name, database, document)
    deployment_file = OmniSemanticDeploymentFile(name, remote_path, content, digest)
    _expected_remote_document(deployment_file)
    return deployment_file


def _remote_path(name: str, database: str, document: object) -> str:
    match = _VIEW_NAME.fullmatch(name)
    flat_match = _FLAT_VIEW_NAME.fullmatch(name)
    if match is None and flat_match is None:
        return name
    if not isinstance(document, Mapping):
        raise OmniSemanticDeploymentError("view YAML must be a mapping")
    if match is not None and match["catalog"] != database:
        raise OmniSemanticDeploymentError(
            "view catalog does not match manifest database"
        )
    catalog = _require_identifier(document.get("catalog"), "view catalog")
    schema = _require_identifier(document.get("schema"), "view schema")
    _require_identifier(document.get("table_name"), "view physical table")
    if catalog != database:
        raise OmniSemanticDeploymentError(
            "view catalog does not match manifest database"
        )
    if match is not None:
        if catalog != match["catalog"] or schema != match["schema"]:
            raise OmniSemanticDeploymentError(
                "local view identity does not match file name"
            )
        logical_table = match["table"]
    else:
        assert flat_match is not None
        logical_table = flat_match["table"]
    return f"{catalog}.{schema}/{logical_table}.view"


def _require_unique_paths(files: Sequence[OmniSemanticDeploymentFile]) -> None:
    paths = [item.remote_path for item in files]
    if len(paths) != len(set(paths)) or len(paths) != len(
        {path.casefold() for path in paths}
    ):
        raise OmniSemanticDeploymentError("remote extension path collision")


def _direct_physical_bindings(
    value: object,
    files: Sequence[OmniSemanticDeploymentFile],
    database: str,
) -> tuple[OmniSemanticDirectPhysicalBinding, ...]:
    if not isinstance(value, list):
        raise OmniSemanticDeploymentError(
            "manifest direct physical bindings must be an array"
        )
    files_by_name = {item.local_name: item for item in files}
    result: list[OmniSemanticDirectPhysicalBinding] = []
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != _DIRECT_BINDING_FIELDS:
            raise OmniSemanticDeploymentError(
                "manifest direct physical binding is malformed"
            )
        local_name = _require_local_name(raw.get("file"))
        item = files_by_name.get(local_name)
        if item is None or not local_name.endswith(".view"):
            raise OmniSemanticDeploymentError(
                "manifest direct physical binding file is invalid"
            )
        field_name = _require_identifier(
            raw.get("field_name"), "direct physical binding field"
        )
        source_id = raw.get("source_stable_id")
        if not isinstance(source_id, str) or not source_id.startswith(
            f"{database}:column:"
        ):
            raise OmniSemanticDeploymentError(
                "direct physical binding source is invalid"
            )
        sql = raw.get("sql")
        if not isinstance(sql, str) or _DIRECT_IDENTIFIER_SQL.fullmatch(sql) is None:
            raise OmniSemanticDeploymentError(
                "direct physical binding SQL is not an identity"
            )
        expected = _expected_remote_document(item)
        dimensions = expected.get("dimensions")
        dimension = (
            dimensions.get(field_name) if isinstance(dimensions, Mapping) else None
        )
        if not isinstance(dimension, Mapping) or dimension.get("sql") != sql:
            raise OmniSemanticDeploymentError(
                "direct physical binding does not match bundle content"
            )
        result.append(
            OmniSemanticDirectPhysicalBinding(
                remote_path=item.remote_path,
                field_name=field_name,
                source_stable_id=source_id,
                sql=sql,
            )
        )
    identities = [(item.remote_path, item.field_name) for item in result]
    if len(identities) != len(set(identities)):
        raise OmniSemanticDeploymentError("duplicate direct physical binding")
    return tuple(sorted(result, key=lambda item: (item.remote_path, item.field_name)))


def _restore_stripped_direct_physical_sql(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    bindings: Sequence[OmniSemanticDirectPhysicalBinding],
) -> Mapping[str, Any]:
    if not bindings:
        return actual
    actual_dimensions = actual.get("dimensions")
    expected_dimensions = expected.get("dimensions")
    if not isinstance(actual_dimensions, Mapping) or not isinstance(
        expected_dimensions, Mapping
    ):
        return actual
    restored_dimensions = dict(actual_dimensions)
    changed = False
    for binding in bindings:
        actual_field = actual_dimensions.get(binding.field_name)
        expected_field = expected_dimensions.get(binding.field_name)
        if (
            isinstance(actual_field, Mapping)
            and "sql" not in actual_field
            and isinstance(expected_field, Mapping)
            and expected_field.get("sql") == binding.sql
        ):
            restored_dimensions[binding.field_name] = {
                **actual_field,
                "sql": binding.sql,
            }
            changed = True
    return {**actual, "dimensions": restored_dimensions} if changed else actual


def _read_regular_file(path: Path, description: str) -> bytes:
    try:
        metadata = path.lstat()
        content = path.read_bytes()
    except OSError as error:
        raise OmniSemanticDeploymentError(f"{description} is unavailable") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise OmniSemanticDeploymentError(f"{description} is not a regular file")
    return content


def _canonical_readback(value: Mapping[str, str | bytes]) -> dict[str, bytes]:
    if not isinstance(value, Mapping):
        raise OmniSemanticDeploymentError("readback must be a path mapping")
    if any(not isinstance(path, str) or not path for path in value):
        raise OmniSemanticDeploymentError("readback path is invalid")
    paths = tuple(value)
    if len(paths) != len({path.casefold() for path in paths}):
        raise OmniSemanticDeploymentError("readback path collision")
    return {path: _text_bytes(content, path) for path, content in value.items()}


def _text_bytes(value: object, path: str) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bytes):
        return value
    raise OmniSemanticDeploymentError(f"readback {path} must be text or bytes")


def _expected_remote_document(item: OmniSemanticDeploymentFile) -> object:
    document = _parse_yaml(
        item.content,
        f"local file {item.local_name}",
        allow_sequence=item.local_name == "relationships",
    )
    if not item.local_name.endswith(".view"):
        return document
    return {
        key: value for key, value in document.items() if key not in _VIEW_IDENTITY_KEYS
    }


def _project_attested_view_identity(
    document: Mapping[str, object], item: OmniSemanticDeploymentFile
) -> Mapping[str, object]:
    if not item.local_name.endswith(".view"):
        return document
    present = set(document) & _VIEW_IDENTITY_KEYS
    if not present:
        return document
    if present != _VIEW_IDENTITY_KEYS:
        raise OmniSemanticDeploymentError(
            f"readback view identity is incomplete for {item.remote_path}"
        )
    local = _parse_yaml(item.content, f"local file {item.local_name}")
    assert isinstance(local, Mapping)
    if any(document[key] != local[key] for key in _VIEW_IDENTITY_KEYS):
        raise OmniSemanticDeploymentError(
            f"readback view identity differs for {item.remote_path}"
        )
    return {
        key: value for key, value in document.items() if key not in _VIEW_IDENTITY_KEYS
    }


def _parse_yaml(
    content: bytes, description: str, *, allow_sequence: bool = False
) -> object:
    try:
        text = content.decode("utf-8")
        value = yaml.load(text, Loader=_UniqueSafeLoader)
    except (UnicodeError, yaml.YAMLError) as error:
        raise OmniSemanticDeploymentError(f"{description} YAML is unsafe") from error
    if allow_sequence and not isinstance(value, list):
        raise OmniSemanticDeploymentError(f"{description} YAML must be a sequence")
    if not allow_sequence and not isinstance(value, Mapping):
        raise OmniSemanticDeploymentError(f"{description} YAML must be a mapping")
    _require_string_mapping_keys(value, description)
    return value


def _validate_relationship_document(value: object) -> None:
    if not isinstance(value, list):
        raise OmniSemanticDeploymentError("relationships YAML must be a sequence")
    for relationship in value:
        if not isinstance(relationship, Mapping) or set(relationship) != (
            _RELATIONSHIP_FIELDS
        ):
            raise OmniSemanticDeploymentError("relationship entry is malformed")
        _require_identifier(
            relationship.get("join_from_view"), "relationship join_from_view"
        )
        _require_identifier(
            relationship.get("join_to_view"), "relationship join_to_view"
        )
        if relationship.get("join_type") != "always_left":
            raise OmniSemanticDeploymentError(
                "relationship join_type must be always_left"
            )
        if relationship.get("relationship_type") != "many_to_one":
            raise OmniSemanticDeploymentError("relationship_type must be many_to_one")
        if relationship.get("reversible") is not False:
            raise OmniSemanticDeploymentError("relationship reversible must be false")
        on_sql = relationship.get("on_sql")
        if (
            not isinstance(on_sql, str)
            or _RELATIONSHIP_ON_SQL.fullmatch(on_sql) is None
        ):
            raise OmniSemanticDeploymentError("relationship on_sql is invalid")


def _validate_model_document(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {"ai_context"}:
        raise OmniSemanticDeploymentError(
            "model document must declare exactly ai_context"
        )
    context = value.get("ai_context")
    if not isinstance(context, str) or not context.strip():
        raise OmniSemanticDeploymentError("model ai_context must be non-empty text")


def _semantic_documents_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _semantic_documents_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _semantic_documents_equal(first, second)
            for first, second in zip(left, right, strict=True)
        )
    return left == right


def _require_string_mapping_keys(value: object, description: str) -> None:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise OmniSemanticDeploymentError(
                f"{description} YAML mapping keys must be strings"
            )
        for item in value.values():
            _require_string_mapping_keys(item, description)
    elif isinstance(value, list):
        for item in value:
            _require_string_mapping_keys(item, description)


def _require_identifier(value: object, description: str) -> str:
    if not isinstance(value, str) or re.fullmatch(_IDENTIFIER, value) is None:
        raise OmniSemanticDeploymentError(f"{description} is invalid")
    return value

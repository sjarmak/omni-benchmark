"""Generate the blinded public-evidence measure review catalog for R2-M1."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .e02_candidate import E02CandidateError, _artifact_sets
from .hkb_io import HKBFileSafetyError, prepare_safe_parent, read_regular_file
from .semantic_bundle import SemanticBundleError, _omni_name, reject_protected_fields
from .semantic_bundle_publication import (
    MAX_HKB_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_MAPPING_BYTES,
    MAX_SCHEMA_BYTES,
    MAX_SPEC_BYTES,
    SemanticBundlePublicationError,
    _json_object,
    _jsonl_objects,
    build_c5_bundle_artifacts,
)
from .semantic_c5 import _widened_c5_spec
from .semantic_mapping import SemanticMappingError, validate_mapping_records


class MeasureCatalogError(ValueError):
    """Raised when a measure review catalog cannot be generated safely."""


_GENERATOR_VERSION = "r2-public-evidence-measure-candidates-v1"
_TARGET_KIND = "r2-public-evidence-measure-targets"
_TARGET_KEYS = frozenset({"databases", "kind", "schema_version"})
_NON_CATALOG_KEYS = frozenset(
    {
        "correctness",
        "instance_id",
        "outcome",
        "question",
        "question_id",
        "question_path",
    }
)
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MACHINE_AGGREGATE = re.compile(
    r"^(?:[^=\n]{1,240}=\s*)?"
    r"(?P<function>AVG|AVERAGE|SUM|COUNT_DISTINCT)"
    r"\(\s*(?P<role>[A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\.?\s*$",
    re.IGNORECASE,
)
_AGGREGATE_TYPES = {
    "average": "average",
    "avg": "average",
    "count_distinct": "count_distinct",
    "sum": "sum",
}
_REVIEW_RECORD = {
    "active_review_seconds": None,
    "binding_correction": None,
    "decision": None,
    "reason_code": None,
    "status": "pending",
}


def canonical_catalog_bytes(value: Any) -> bytes:
    """Return the canonical byte representation used for IDs and artifacts."""
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise MeasureCatalogError("catalog value is not canonical JSON") from error
    return (encoded + "\n").encode()


def propose_database_measure_candidates(inputs: Mapping[str, object]) -> dict[str, Any]:
    """Propose every strict measure candidate for one public C5 database."""
    _reject_forbidden_inputs(inputs)
    database = _text(inputs.get("database"), "database")
    schema_records = _object_list(inputs.get("schema_records"), "schema records")
    hkb_records = _object_list(inputs.get("hkb_records"), "HKB records")
    mapping_records = _object_list(inputs.get("mapping_records"), "mapping records")
    views = _object_list(inputs.get("views"), "views")
    input_files = _input_file_records(inputs.get("input_files", []))

    schema_index = _index(schema_records, "stable_id", "schema record")
    mappings = _index(mapping_records, "hkb_stable_id", "mapping record")
    view_index = _index(views, "table_stable_id", "view")
    screening = {
        "entity_count": Counter[str](),
        "hkb_aggregate": Counter[str](),
    }
    screened: list[dict[str, str]] = []
    candidates: list[dict[str, Any]] = []

    tables = sorted(
        (record for record in schema_records if record.get("record_kind") == "table"),
        key=lambda item: _text(item.get("stable_id"), "table stable_id"),
    )
    for table in tables:
        candidate, reason = _entity_count_candidate(
            database, table, schema_index, view_index
        )
        if candidate is None:
            screening["entity_count"][reason] += 1
            screened.append(_screening_record(database, "entity_count", table, reason))
        else:
            candidates.append(candidate)

    for hkb in sorted(
        hkb_records,
        key=lambda item: _text(item.get("stable_id"), "HKB stable_id"),
    ):
        candidate, reason = _hkb_aggregate_candidate(
            database, hkb, mappings, schema_index, view_index
        )
        if candidate is None:
            screening["hkb_aggregate"][reason] += 1
            screened.append(_screening_record(database, "hkb_aggregate", hkb, reason))
        else:
            candidates.append(candidate)

    identified = [_identify_candidate(item) for item in candidates]
    identified.sort(key=lambda item: item["candidate_id"])
    return {
        "candidates": identified,
        "database": database,
        "input_files": input_files,
        "screened": sorted(
            screened,
            key=lambda item: (
                item["candidate_class"],
                item["source_stable_id"],
            ),
        ),
        "screening": {
            candidate_class: dict(sorted(counts.items()))
            for candidate_class, counts in screening.items()
        },
    }


def build_measure_review_catalog(
    database_inputs: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    """Build one deterministic, self-describing review catalog."""
    if not isinstance(database_inputs, Sequence) or isinstance(
        database_inputs, (str, bytes)
    ):
        raise MeasureCatalogError("database inputs must be a sequence")
    results = [propose_database_measure_candidates(item) for item in database_inputs]
    results.sort(key=lambda item: item["database"])
    databases = [item["database"] for item in results]
    if len(databases) != len(set(databases)):
        raise MeasureCatalogError("database inputs contain duplicates")

    candidates = sorted(
        (candidate for result in results for candidate in result["candidates"]),
        key=lambda item: item["candidate_id"],
    )
    class_counts = Counter(item["candidate_class"] for item in candidates)
    screening: dict[str, Counter[str]] = {
        "entity_count": Counter(),
        "hkb_aggregate": Counter(),
    }
    for result in results:
        for candidate_class, counts in result["screening"].items():
            screening[candidate_class].update(counts)

    catalog: dict[str, Any] = {
        "candidates": candidates,
        "database_summaries": [
            {
                "candidate_count": len(result["candidates"]),
                "database": result["database"],
                "input_files": result["input_files"],
                "screened": result["screened"],
                "screening": result["screening"],
            }
            for result in results
        ],
        "generator_version": _GENERATOR_VERSION,
        "kind": "public-evidence-measure-review-catalog",
        "manifest": {
            "candidate_count": len(candidates),
            "candidate_count_by_class": dict(sorted(class_counts.items())),
            "database_count": len(databases),
            "databases": databases,
            "ordered_candidate_ids": [item["candidate_id"] for item in candidates],
            "screening": {
                candidate_class: dict(sorted(counts.items()))
                for candidate_class, counts in screening.items()
            },
        },
        "schema_version": 1,
    }
    catalog["manifest"]["catalog_sha256"] = _sha256(canonical_catalog_bytes(catalog))
    return catalog


def generate_workspace_measure_review_catalog(
    workspace: Path, target_config: Path
) -> dict[str, Any]:
    """Generate the review catalog from authenticated public C5 source inputs."""
    try:
        root = workspace.resolve(strict=True)
    except OSError as error:
        raise MeasureCatalogError("workspace is unavailable") from error
    config_path = target_config if target_config.is_absolute() else root / target_config
    config_bytes = _read_file(config_path, maximum_bytes=64_000)
    config = _parse_json_object(config_bytes, "target configuration")
    unsupported = sorted(set(config) - _TARGET_KEYS)
    if unsupported:
        raise MeasureCatalogError(
            f"target configuration has unsupported fields: {', '.join(unsupported)}"
        )
    if config.get("kind") != _TARGET_KIND or config.get("schema_version") != 1:
        raise MeasureCatalogError("target configuration identity is invalid")
    databases = config.get("databases")
    if not isinstance(databases, list) or any(
        not isinstance(item, str) or not _SAFE_NAME.fullmatch(item)
        for item in databases
    ):
        raise MeasureCatalogError("target databases must be safe names")
    if databases != sorted(databases) or len(databases) != len(set(databases)):
        raise MeasureCatalogError("target databases must be unique and sorted")
    if len(databases) != 16:
        raise MeasureCatalogError("R2 target configuration must name 16 databases")

    try:
        artifact_sets = _artifact_sets(root)
    except E02CandidateError as error:
        raise MeasureCatalogError(str(error)) from error
    available = {item[0]: item[1:] for item in artifact_sets}
    unknown = sorted(set(databases) - set(available))
    if unknown:
        raise MeasureCatalogError(
            f"target databases are not public C5 inputs: {', '.join(unknown)}"
        )

    config_record = _input_file_record(root, config_path, config_bytes)
    database_inputs: list[dict[str, object]] = []
    for database in databases:
        spec_path, hkb_path, schema_path, mapping_path, manifest_path = available[
            database
        ]
        paths = (spec_path, hkb_path, schema_path, mapping_path, manifest_path)
        contents = (
            _read_file(spec_path, maximum_bytes=MAX_SPEC_BYTES),
            _read_file(hkb_path, maximum_bytes=MAX_HKB_BYTES),
            _read_file(schema_path, maximum_bytes=MAX_SCHEMA_BYTES),
            _read_file(mapping_path, maximum_bytes=MAX_MAPPING_BYTES),
            _read_file(manifest_path, maximum_bytes=MAX_MANIFEST_BYTES),
        )
        database_inputs.append(
            _database_inputs_from_c5(
                root,
                database,
                paths,
                contents,
                config_record,
            )
        )
    return build_measure_review_catalog(database_inputs)


def write_measure_review_catalog(
    destination: Path, catalog: Mapping[str, object]
) -> None:
    """Write one canonical catalog without permitting overwrite."""
    _reject_forbidden_inputs(catalog)
    content = canonical_catalog_bytes(catalog)
    try:
        prepare_safe_parent(destination)
        parent_descriptor = os.open(
            destination.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except (HKBFileSafetyError, OSError) as error:
        raise MeasureCatalogError("catalog destination parent is unsafe") from error

    temporary = f".{destination.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_descriptor,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary,
                destination.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            raise MeasureCatalogError(
                f"{destination.name} already exists; refusing overwrite"
            ) from error
        os.fsync(parent_descriptor)
    except MeasureCatalogError:
        raise
    except OSError as error:
        raise MeasureCatalogError("catalog could not be written safely") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent_descriptor)


def _entity_count_candidate(
    database: str,
    table: Mapping[str, Any],
    schema_index: Mapping[str, Mapping[str, Any]],
    view_index: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    table_id = _text(table.get("stable_id"), "table stable_id")
    view = view_index.get(table_id)
    if view is None:
        return None, "view_unpublished"
    primary = _text_list(table.get("primary_key_column_stable_ids", []), "primary key")
    unique_keys = table.get("unique_keys", [])
    if not isinstance(unique_keys, list) or any(
        not isinstance(key, list) or any(not isinstance(item, str) for item in key)
        for key in unique_keys
    ):
        raise MeasureCatalogError("table unique keys are invalid")
    if len(primary) == 1:
        identity_id = primary[0]
        identity_kind = "primary_key"
    else:
        singles = sorted({key[0] for key in unique_keys if len(key) == 1})
        if len(singles) > 1:
            return None, "ambiguous_single_unique_identity"
        if not singles:
            return None, "no_single_identity"
        identity_id = singles[0]
        identity_kind = "unique_key"

    identity = schema_index.get(identity_id)
    if identity is None or identity.get("record_kind") != "column":
        return None, "identity_binding_unresolved"
    fields = _field_map(view)
    field_name = fields.get(identity_id)
    if field_name is None:
        return None, "identity_binding_unresolved"
    view_name = _text(view.get("view_name"), "view name")
    view_label = _text(view.get("label"), "view label")
    definition = {
        "aggregate_type": "count_distinct",
        "description": f"Count of distinct {view_label} public identity values.",
        "label": f"{view_label} Count",
        "sql": f"${{{view_name}.{field_name}}}",
    }
    evidence = {
        "identity_field_stable_id": identity_id,
        "identity_kind": identity_kind,
        "public_records": [_evidence_record(table), _evidence_record(identity)],
        "table_stable_id": table_id,
    }
    return (
        _candidate_body(
            database=database,
            view=view,
            candidate_class="entity_count",
            measure_name="count",
            definition=definition,
            signature={
                "aggregate_type": "count_distinct",
                "source_field_stable_ids": [identity_id],
            },
            evidence=evidence,
        ),
        "",
    )


def _hkb_aggregate_candidate(
    database: str,
    hkb: Mapping[str, Any],
    mappings: Mapping[str, Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
    view_index: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, str]:
    definition_text = _text(hkb.get("definition"), "HKB definition")
    match = _MACHINE_AGGREGATE.fullmatch(definition_text.strip())
    if match is None:
        return None, "aggregation_not_machine_explicit"
    hkb_id = _text(hkb.get("stable_id"), "HKB stable_id")
    mapping = mappings.get(hkb_id)
    if mapping is None:
        return None, "mapping_missing"
    dependencies = {
        *_text_list(hkb.get("dependency_stable_ids", []), "HKB dependencies"),
        *_text_list(
            mapping.get("dependency_hkb_stable_ids", []), "mapping dependencies"
        ),
    }
    if dependencies:
        return None, "dependency_unresolved"
    target = mapping.get("target_table_stable_id")
    relationships = mapping.get("relationship_requirements", [])
    if (
        mapping.get("disposition") != "compile"
        or not isinstance(target, str)
        or mapping.get("dependency_mode") != "same_grain"
        or not isinstance(relationships, list)
        or relationships
    ):
        return None, "grain_or_relationship_unresolved"
    view = view_index.get(target)
    if view is None:
        return None, "grain_or_relationship_unresolved"

    role = match.group("role")
    bindings = mapping.get("source_bindings", [])
    if not isinstance(bindings, list):
        raise MeasureCatalogError("mapping source bindings must be a list")
    matching = [
        item
        for item in bindings
        if isinstance(item, dict)
        and isinstance(item.get("role"), str)
        and item["role"].casefold() == role.casefold()
        and item.get("confidence") == "exact"
        and isinstance(item.get("schema_stable_id"), str)
    ]
    if len(matching) != 1:
        return None, "aggregate_binding_unresolved"
    source_id = matching[0]["schema_stable_id"]
    source = schema_index.get(source_id)
    if source is None or _schema_table(source, schema_index) != target:
        return None, "aggregate_binding_unresolved"
    field_name = _field_map(view).get(source_id)
    if field_name is None:
        return None, "aggregate_binding_unresolved"

    aggregate_type = _AGGREGATE_TYPES[match.group("function").casefold()]
    semantic_name = _text(mapping.get("semantic_name"), "mapping semantic name")
    if not _SAFE_NAME.fullmatch(semantic_name):
        return None, "measure_name_unrepresentable"
    measure_name = f"{semantic_name}_measure"
    view_name = _text(view.get("view_name"), "view name")
    definition = {
        "aggregate_type": aggregate_type,
        "description": _text(hkb.get("description"), "HKB description"),
        "label": _text(hkb.get("knowledge"), "HKB knowledge"),
        "sql": f"${{{view_name}.{field_name}}}",
    }
    evidence = {
        "compiler_disposition": "compile",
        "dependency_closure_stable_ids": [],
        "hkb_stable_id": hkb_id,
        "public_records": [
            _evidence_record(hkb),
            _evidence_record(mapping),
            _evidence_record(source),
        ],
        "relationship_requirements": [],
        "source_field_stable_id": source_id,
        "target_table_stable_id": target,
    }
    return (
        _candidate_body(
            database=database,
            view=view,
            candidate_class="hkb_aggregate",
            measure_name=measure_name,
            definition=definition,
            signature={
                "aggregate_type": aggregate_type,
                "source_field_stable_ids": [source_id],
            },
            evidence=evidence,
        ),
        "",
    )


def _candidate_body(
    *,
    database: str,
    view: Mapping[str, Any],
    candidate_class: str,
    measure_name: str,
    definition: Mapping[str, Any],
    signature: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    yaml_document = {"measures": {measure_name: dict(definition)}}
    return {
        "candidate_class": candidate_class,
        "database": database,
        "evidence": dict(evidence),
        "inline_equivalent_signature": dict(signature),
        "measure": {"definition": dict(definition), "name": measure_name},
        "proposed_omni_yaml": yaml.safe_dump(
            yaml_document, allow_unicode=True, sort_keys=True, width=1000
        ),
        "view": {
            "file_name": _text(view.get("file_name"), "view file name"),
            "table_stable_id": _text(
                view.get("table_stable_id"), "view table stable_id"
            ),
            "view_name": _text(view.get("view_name"), "view name"),
        },
    }


def _identify_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    semantic_bytes = canonical_catalog_bytes(candidate)
    candidate_digest = _sha256(semantic_bytes)
    identified = copy.deepcopy(dict(candidate))
    identified["candidate_id"] = f"r2m1-{candidate_digest}"
    identified["measure_id"] = "r2m1m-" + _sha256(
        canonical_catalog_bytes(
            {
                "candidate_id": identified["candidate_id"],
                "database": identified["database"],
                "measure": identified["measure"]["name"],
                "view": identified["view"]["view_name"],
            }
        )
    )
    identified["review"] = copy.deepcopy(_REVIEW_RECORD)
    return identified


def _screening_record(
    database: str,
    candidate_class: str,
    source: Mapping[str, Any],
    reason: str,
) -> dict[str, str]:
    source_id = _text(
        source.get("stable_id") or source.get("hkb_stable_id"),
        "screening source stable ID",
    )
    return {
        "candidate_class": candidate_class,
        "database": database,
        "reason": reason,
        "source_record_sha256": _sha256(canonical_catalog_bytes(source)),
        "source_stable_id": source_id,
    }


def _database_inputs_from_c5(
    root: Path,
    database: str,
    paths: Sequence[Path],
    contents: Sequence[bytes],
    config_record: Mapping[str, str],
) -> dict[str, object]:
    spec_bytes, hkb_bytes, schema_bytes, mapping_bytes, _manifest_bytes = contents
    try:
        spec = _json_object(spec_bytes, "bundle specification")
        hkb_records = _jsonl_objects(hkb_bytes, "HKB IR")
        schema_records = _jsonl_objects(schema_bytes, "schema IR")
        mapping_records = _jsonl_objects(mapping_bytes, "semantic mapping")
        validate_mapping_records(hkb_records, schema_records, mapping_records)
        _files, compiled_manifest = build_c5_bundle_artifacts(*contents)
        widened, _report, injections = _widened_c5_spec(
            spec, schema_records, mapping_records
        )
    except (
        SemanticBundleError,
        SemanticBundlePublicationError,
        SemanticMappingError,
    ) as error:
        raise MeasureCatalogError(
            f"public C5 inputs for {database} are invalid"
        ) from error
    if (
        spec.get("database") != database
        or compiled_manifest.get("database") != database
    ):
        raise MeasureCatalogError(f"public C5 input identity for {database} is invalid")

    schema_index = _index(schema_records, "stable_id", "schema record")
    raw_views = widened.get("views")
    if not isinstance(raw_views, list):
        raise MeasureCatalogError("widened C5 views must be a list")
    views: dict[str, dict[str, Any]] = {}
    files_by_name = _files
    for raw_view in raw_views:
        if not isinstance(raw_view, dict):
            raise MeasureCatalogError("widened C5 view must be an object")
        table_id = _text(raw_view.get("table_stable_id"), "view table stable_id")
        file_name = _text(raw_view.get("file_name"), "view file name")
        document = yaml.safe_load(files_by_name[file_name])
        if not isinstance(document, dict) or not isinstance(
            document.get("dimensions"), dict
        ):
            raise MeasureCatalogError("compiled C5 view has no dimensions")
        views[table_id] = {
            "file_name": file_name,
            "fields": {},
            "label": _text(raw_view.get("label"), "view label"),
            "table_stable_id": table_id,
            "view_name": _text(raw_view.get("view_name"), "view name"),
            "_dimension_names": frozenset(document["dimensions"]),
        }

    physical_fields = widened.get("physical_fields")
    if not isinstance(physical_fields, list):
        raise MeasureCatalogError("widened C5 physical fields must be a list")
    for raw_field in physical_fields:
        if not isinstance(raw_field, dict):
            raise MeasureCatalogError("widened C5 physical field must be an object")
        source_id = _text(raw_field.get("schema_stable_id"), "schema stable_id")
        source = schema_index.get(source_id)
        if source is None:
            raise MeasureCatalogError("widened C5 physical source is missing")
        table_id = _schema_table(source, schema_index)
        field_name = _omni_name(raw_field.get("name"), "physical field name")
        if table_id in views and field_name in views[table_id]["_dimension_names"]:
            views[table_id]["fields"][source_id] = field_name
    for injection in injections:
        table_id = injection["table_stable_id"]
        if (
            table_id in views
            and injection["field_name"] in views[table_id]["_dimension_names"]
        ):
            views[table_id]["fields"][injection["stable_id"]] = injection["field_name"]
    direct_bindings = compiled_manifest.get("direct_physical_bindings")
    if not isinstance(direct_bindings, list):
        raise MeasureCatalogError("compiled C5 direct bindings are invalid")
    table_by_file = {item["file_name"]: table_id for table_id, item in views.items()}
    for binding in direct_bindings:
        if not isinstance(binding, dict):
            raise MeasureCatalogError("compiled C5 direct binding is invalid")
        table_id = table_by_file.get(binding.get("file"))
        source_id = binding.get("source_stable_id")
        field_name = binding.get("field_name")
        if (
            table_id is not None
            and isinstance(source_id, str)
            and isinstance(field_name, str)
            and field_name in views[table_id]["_dimension_names"]
        ):
            views[table_id]["fields"][source_id] = field_name
    for view in views.values():
        del view["_dimension_names"]

    input_files = [dict(config_record)]
    input_files.extend(
        _input_file_record(root, path, content)
        for path, content in zip(paths, contents, strict=True)
    )
    return {
        "database": database,
        "hkb_records": hkb_records,
        "input_files": input_files,
        "mapping_records": mapping_records,
        "schema_records": schema_records,
        "views": sorted(views.values(), key=lambda item: item["table_stable_id"]),
    }


def _input_file_record(root: Path, path: Path, content: bytes) -> dict[str, str]:
    try:
        relative = path.resolve(strict=True).relative_to(root).as_posix()
    except (OSError, ValueError) as error:
        raise MeasureCatalogError(
            "public input path must remain inside workspace"
        ) from error
    return {"path": relative, "sha256": _sha256(content)}


def _input_file_records(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise MeasureCatalogError("input files must be a list")
    records: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise MeasureCatalogError("input file record is invalid")
        path = _text(item.get("path"), "input path")
        digest = _text(item.get("sha256"), "input SHA-256")
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest
        ):
            raise MeasureCatalogError("input SHA-256 is invalid")
        records.append({"path": path, "sha256": digest})
    return sorted(records, key=lambda item: item["path"])


def _field_map(view: Mapping[str, Any]) -> Mapping[str, str]:
    fields = view.get("fields")
    if not isinstance(fields, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in fields.items()
    ):
        raise MeasureCatalogError("view fields must be a text mapping")
    return fields


def _schema_table(
    record: Mapping[str, Any], schema_index: Mapping[str, Mapping[str, Any]]
) -> str:
    if record.get("record_kind") == "column":
        return _text(record.get("table_stable_id"), "column table stable_id")
    if record.get("record_kind") == "structured_leaf":
        column_id = _text(record.get("column_stable_id"), "leaf column stable_id")
        column = schema_index.get(column_id)
        if column is None:
            raise MeasureCatalogError("structured leaf parent column is missing")
        return _text(column.get("table_stable_id"), "column table stable_id")
    raise MeasureCatalogError("measure source must be a column or structured leaf")


def _evidence_record(record: Mapping[str, Any]) -> dict[str, str]:
    stable_id = _text(
        record.get("stable_id") or record.get("hkb_stable_id"), "evidence stable ID"
    )
    excerpt_source = next(
        (
            record.get(key)
            for key in ("definition", "description", "knowledge", "notes")
            if isinstance(record.get(key), str) and record.get(key)
        ),
        stable_id,
    )
    excerpt = " ".join(str(excerpt_source).split())[:600]
    return {
        "public_excerpt": excerpt,
        "record_sha256": _sha256(canonical_catalog_bytes(record)),
        "stable_id": stable_id,
    }


def _reject_forbidden_inputs(value: object) -> None:
    try:
        reject_protected_fields(value)
    except SemanticBundleError as error:
        raise MeasureCatalogError(str(error)) from error
    found = _find_key(value, _NON_CATALOG_KEYS)
    if found is not None:
        raise MeasureCatalogError(f"non-catalog field {found} is not allowed")


def _find_key(value: object, forbidden: frozenset[str]) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if normalized in forbidden:
                return str(key)
            found = _find_key(nested, forbidden)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            found = _find_key(nested, forbidden)
            if found is not None:
                return found
    return None


def _object_list(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise MeasureCatalogError(f"{label} must be a list of objects")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MeasureCatalogError(f"{label} must be non-empty text")
    return value


def _text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MeasureCatalogError(f"{label} must be a list of text")
    return value


def _index(
    records: Sequence[Mapping[str, Any]], key: str, label: str
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        identity = _text(record.get(key), f"{label} {key}")
        if identity in indexed:
            raise MeasureCatalogError(f"duplicate {label} {identity}")
        indexed[identity] = record
    return indexed


def _read_file(path: Path, *, maximum_bytes: int) -> bytes:
    try:
        return read_regular_file(path, maximum_bytes=maximum_bytes)
    except HKBFileSafetyError as error:
        raise MeasureCatalogError(str(error)) from error


def _parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        return _json_object(content, label)
    except SemanticBundlePublicationError as error:
        raise MeasureCatalogError(str(error)) from error


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

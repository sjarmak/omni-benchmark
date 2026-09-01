"""Build the paired offline R2-C5B and R2-M1 semantic-model bundles.

This module is deliberately question-blind.  It authenticates the frozen
accepted catalog and the public C5 compiler outputs, materializes the explicit
Balanced settings common to both arms, and adds accepted measures only to the
R2-M1 view files.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .e02_candidate import E02CandidateError, _artifact_sets
from .hkb_io import (
    HKBFileSafetyError,
    prepare_safe_parent,
    read_regular_file,
)
from .measure_catalog_review import MeasureReviewError, _reject_forbidden_value
from .measure_review_catalog import canonical_catalog_bytes
from .omni_semantic_deployment import (
    BALANCED_AI_SETTINGS,
    OmniSemanticDeploymentError,
    build_semantic_deployment_plan,
)
from .protected_fields import ProtectedFieldError, reject_protected_fields
from .semantic_bundle_publication import (
    SemanticBundlePublicationError,
    _read_inputs,
    build_c5_bundle_artifacts,
)


class MeasureBundleError(ValueError):
    """Raised when the paired offline measure bundles cannot be proven exact."""


EXPECTED_ACCEPTED_CATALOG_SHA256 = (
    "2d2f9c15bc5f5271db924fa4377b41c26a0e61bcec221ed31d10b3365358039a"
)
EXPECTED_MEASURE_COUNT = 812
EXPECTED_DATABASE_COUNT = 16

SERIES_ID = "r2-public-evidence-measures-v1"
GENERATOR_VERSION = "r2-public-evidence-measure-bundles-v1"
CONTROL_CONDITION = "R2-C5B"
TREATMENT_CONDITION = "R2-M1"

BALANCED_AI_SETTINGS_YAML = (
    b"ai_settings:\n"
    b"  query_all_views_and_fields: enabled\n"
    b"  validate_analysis: disabled\n"
    b"  conversation_prune_length: max\n"
    b"  analyze_configuration:\n"
    b"    model: standard\n"
    b"    thinking: none\n"
    b"  build_configuration:\n"
    b"    model: smartest\n"
    b"    thinking: none\n"
    b"  simple_summarize_configuration:\n"
    b"    model: fastest\n"
    b"    thinking: none\n"
)

_CATALOG_TOP_KEYS = frozenset(
    {
        "accepted_candidates",
        "catalog_version",
        "generator",
        "kind",
        "manifest",
        "schema_version",
        "source",
        "summary",
    }
)
_CATALOG_MANIFEST_KEYS = frozenset(
    {"artifact_sha256", "ordered_candidate_ids", "ordered_measure_ids"}
)
_CANDIDATE_KEYS = frozenset(
    {
        "candidate_class",
        "candidate_id",
        "database",
        "evidence",
        "inline_equivalent_signature",
        "measure",
        "measure_id",
        "proposed_omni_yaml",
        "view",
    }
)
_TARGET_KEYS = frozenset({"databases", "kind", "schema_version"})
_TARGET_KIND = "r2-public-evidence-measure-targets"
_FILE_RECORD_KEYS = frozenset({"file", "sha256", "size_bytes"})
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CANDIDATE_ID = re.compile(r"^r2m1-[0-9a-f]{64}$")
_MEASURE_ID = re.compile(r"^r2m1m-[0-9a-f]{64}$")
_FIELD_REFERENCE = re.compile(
    r"^\$\{(?P<view>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<field>[A-Za-z_][A-Za-z0-9_]*)\}$"
)
_AGGREGATE_TYPES = frozenset({"average", "count_distinct", "sum"})
_MEASURE_DEFINITION_KEYS = frozenset({"aggregate_type", "description", "label", "sql"})
_CONDITION_DIRECTORIES = {
    CONTROL_CONDITION: "r2-c5b",
    TREATMENT_CONDITION: "r2-m1",
}


class _UniqueSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


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
            raise MeasureBundleError("YAML mapping key is not scalar") from error
        if duplicate:
            raise MeasureBundleError(f"YAML contains duplicate key {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True)
class DatabaseMeasureBundlePair:
    """One database's authenticated control and treatment artifacts."""

    control_files: dict[str, bytes]
    control_manifest: dict[str, Any]
    treatment_files: dict[str, bytes]
    treatment_manifest: dict[str, Any]
    record: dict[str, Any]


@dataclass(frozen=True)
class MeasureBundleSet:
    """All sixteen paired bundles plus their root provenance manifest."""

    files: dict[str, bytes]
    manifest: dict[str, Any]


def build_database_measure_bundle_pair(
    database: str,
    c5_files: Mapping[str, bytes],
    c5_manifest: Mapping[str, object],
    accepted_catalog_bytes: bytes,
    *,
    expected_catalog_sha256: str = EXPECTED_ACCEPTED_CATALOG_SHA256,
) -> DatabaseMeasureBundlePair:
    """Build one authenticated R2 pair from C5 and the frozen catalog."""
    catalog, catalog_sha256 = _validated_accepted_catalog(
        accepted_catalog_bytes,
        expected_sha256=expected_catalog_sha256,
    )
    return _build_database_pair(
        _identifier(database, "database"),
        c5_files,
        c5_manifest,
        catalog,
        catalog_sha256,
    )


def build_workspace_measure_bundle_set(
    workspace: Path,
    target_config: Path,
    accepted_catalog: Path,
) -> MeasureBundleSet:
    """Compile the complete public-only sixteen-database offline bundle set."""
    root = _workspace_root(workspace)
    config_path = _inside_workspace(root, target_config, "target configuration")
    catalog_path = _inside_workspace(root, accepted_catalog, "accepted catalog")
    config_bytes = _read(config_path, 64_000)
    catalog_bytes = _read(catalog_path, 16_000_000)
    databases = _validated_targets(config_bytes)
    catalog, catalog_sha256 = _validated_accepted_catalog(
        catalog_bytes,
        expected_sha256=EXPECTED_ACCEPTED_CATALOG_SHA256,
    )
    summary = _mapping(catalog.get("summary"), "accepted catalog summary")
    if (
        databases != summary.get("accepted_databases")
        or len(databases) != EXPECTED_DATABASE_COUNT
        or summary.get("accepted_candidate_count") != EXPECTED_MEASURE_COUNT
    ):
        raise MeasureBundleError(
            "accepted catalog and R2 target inventory do not match the frozen scope"
        )

    try:
        artifact_sets = _artifact_sets(root)
    except E02CandidateError as error:
        raise MeasureBundleError(str(error)) from error
    available = {item[0]: item[1:] for item in artifact_sets}
    if sorted(set(databases) - set(available)):
        raise MeasureBundleError("R2 target database has no public C5 source")

    files: dict[str, bytes] = {}
    database_records: list[dict[str, Any]] = []
    for database in databases:
        paths = available[database]
        try:
            inputs = _read_inputs(*paths)
            c5_files, c5_manifest = build_c5_bundle_artifacts(*inputs)
        except SemanticBundlePublicationError as error:
            raise MeasureBundleError(
                f"public C5 source for {database} is invalid"
            ) from error
        pair = _build_database_pair(
            database,
            c5_files,
            c5_manifest,
            catalog,
            catalog_sha256,
        )
        for condition, arm_files, arm_manifest in (
            (CONTROL_CONDITION, pair.control_files, pair.control_manifest),
            (TREATMENT_CONDITION, pair.treatment_files, pair.treatment_manifest),
        ):
            prefix = f"{_CONDITION_DIRECTORIES[condition]}/{database}/"
            for name, content in sorted(arm_files.items()):
                files[prefix + name] = content
            files[prefix + "manifest.json"] = canonical_catalog_bytes(arm_manifest)
        database_records.append(pair.record)

    manifest: dict[str, Any] = {
        "accepted_catalog": {
            "internal_artifact_sha256": catalog["manifest"]["artifact_sha256"],
            "path": catalog_path.relative_to(root).as_posix(),
            "sha256": catalog_sha256,
        },
        "balanced_ai_settings": copy.deepcopy(BALANCED_AI_SETTINGS),
        "conditions": {
            CONTROL_CONDITION: {
                "directory": _CONDITION_DIRECTORIES[CONTROL_CONDITION],
                "measure_count": 0,
            },
            TREATMENT_CONDITION: {
                "directory": _CONDITION_DIRECTORIES[TREATMENT_CONDITION],
                "measure_count": EXPECTED_MEASURE_COUNT,
            },
        },
        "databases": database_records,
        "generator_version": GENERATOR_VERSION,
        "information_boundary": {
            "benchmark_questions_used": False,
            "correctness_used": False,
            "dev_b_used": False,
            "hidden_annotations_used": False,
            "opportunity_map_used": False,
            "public_c5_sources_only": True,
            "sealed_test_used": False,
        },
        "kind": "r2-public-evidence-measure-bundle-set",
        "schema_version": 1,
        "series_id": SERIES_ID,
        "summary": {
            "control_measure_count": 0,
            "database_count": len(database_records),
            "treatment_measure_count": sum(
                record["measure_count"] for record in database_records
            ),
        },
        "target_configuration": {
            "path": config_path.relative_to(root).as_posix(),
            "sha256": _sha256(config_bytes),
        },
    }
    manifest["manifest"] = {
        "files": _relative_file_records(files),
    }
    manifest["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(manifest))
    _reject_forbidden(manifest)
    bundle = MeasureBundleSet(files=files, manifest=manifest)
    _validate_bundle_set(bundle)
    return bundle


def write_measure_bundle_set(destination: Path, bundle: MeasureBundleSet) -> None:
    """Publish one private append-only directory tree, with the root manifest last."""
    _validate_bundle_set(bundle)
    try:
        prepare_safe_parent(destination)
        destination.lstat()
    except FileNotFoundError:
        pass
    except (HKBFileSafetyError, OSError) as error:
        raise MeasureBundleError(
            f"{destination.name} already exists; refusing overwrite"
        ) from error
    else:
        raise MeasureBundleError(
            f"{destination.name} already exists; refusing overwrite"
        )

    try:
        destination.mkdir(mode=0o700)
        for relative, content in sorted(bundle.files.items()):
            target = _publication_path(destination, relative)
            _prepare_publication_parent(destination, relative)
            _write_exclusive(target, content)
        _write_exclusive(
            destination / "manifest.json", canonical_catalog_bytes(bundle.manifest)
        )
        _fsync_directory(destination)
    except OSError as error:
        raise MeasureBundleError(
            "measure bundle publication failed; use a new output root"
        ) from error


def verify_measure_bundle_set(source: Path) -> MeasureBundleSet:
    """Read back and authenticate a published offline bundle tree."""
    root = _published_root(source)
    manifest_bytes = _read(root / "manifest.json", 16_000_000)
    manifest = _json_object(manifest_bytes, "published bundle-set manifest")
    content_manifest = _mapping(
        manifest.get("manifest"), "published bundle-set content manifest"
    )
    raw_records = content_manifest.get("files")
    if not isinstance(raw_records, list) or not raw_records:
        raise MeasureBundleError("published bundle-set file records are invalid")
    records: dict[str, Mapping[str, Any]] = {}
    for raw_record in raw_records:
        record = _mapping(raw_record, "published bundle-set file record")
        if set(record) != {"path", "sha256", "size_bytes"}:
            raise MeasureBundleError("published bundle-set file record is malformed")
        relative = _text(record.get("path"), "published bundle path")
        _publication_path(root, relative)
        if relative in records:
            raise MeasureBundleError("published bundle-set file record is duplicated")
        records[relative] = record
    observed = _published_relative_files(root)
    if observed != {*records, "manifest.json"}:
        raise MeasureBundleError("published bundle-set file inventory is not exact")

    files: dict[str, bytes] = {}
    for relative, record in sorted(records.items()):
        content = _read(_publication_path(root, relative), 16_000_000)
        if record.get("sha256") != _sha256(content) or record.get("size_bytes") != len(
            content
        ):
            raise MeasureBundleError(f"published file record for {relative} is invalid")
        files[relative] = content
    bundle = MeasureBundleSet(files=files, manifest=manifest)
    _validate_bundle_set(bundle)

    bundle_roots = sorted(
        {(Path(relative).parts[0], Path(relative).parts[1]) for relative in files}
    )
    for condition, database in bundle_roots:
        try:
            plan = build_semantic_deployment_plan(root / condition / database)
        except OmniSemanticDeploymentError as error:
            raise MeasureBundleError(
                f"published semantic bundle {condition}/{database} is invalid"
            ) from error
        if plan.database != database:
            raise MeasureBundleError("published semantic bundle database is invalid")
    return bundle


def _build_database_pair(
    database: str,
    c5_files: Mapping[str, bytes],
    c5_manifest: Mapping[str, object],
    catalog: Mapping[str, Any],
    catalog_sha256: str,
) -> DatabaseMeasureBundlePair:
    base_files = _validated_c5_bundle(database, c5_files, c5_manifest)
    candidates = [
        candidate
        for candidate in catalog["accepted_candidates"]
        if candidate["database"] == database
    ]
    if not candidates:
        raise MeasureBundleError(
            f"accepted catalog has no measures for database {database}"
        )
    control_files = _with_balanced_settings(base_files)
    treatment_files, changed_views, measure_ids = _with_accepted_measures(
        database,
        control_files,
        candidates,
    )
    source_manifest_sha256 = _sha256(canonical_catalog_bytes(c5_manifest))
    control_manifest = _condition_manifest(
        c5_manifest,
        control_files,
        condition=CONTROL_CONDITION,
        catalog_sha256=catalog_sha256,
        source_manifest_sha256=source_manifest_sha256,
        measure_ids=[],
    )
    treatment_manifest = _condition_manifest(
        c5_manifest,
        treatment_files,
        condition=TREATMENT_CONDITION,
        catalog_sha256=catalog_sha256,
        source_manifest_sha256=source_manifest_sha256,
        measure_ids=measure_ids,
    )
    _validate_condition_pair(
        control_files,
        treatment_files,
        changed_views,
        candidates,
    )
    record = {
        "changed_view_files": changed_views,
        "control_file_count": len(control_files),
        "control_manifest_sha256": _sha256(canonical_catalog_bytes(control_manifest)),
        "database": database,
        "measure_count": len(measure_ids),
        "measure_ids": measure_ids,
        "source_c5_manifest_sha256": source_manifest_sha256,
        "treatment_file_count": len(treatment_files),
        "treatment_manifest_sha256": _sha256(
            canonical_catalog_bytes(treatment_manifest)
        ),
    }
    return DatabaseMeasureBundlePair(
        control_files=control_files,
        control_manifest=control_manifest,
        treatment_files=treatment_files,
        treatment_manifest=treatment_manifest,
        record=record,
    )


def _validated_accepted_catalog(
    content: bytes,
    *,
    expected_sha256: str,
) -> tuple[dict[str, Any], str]:
    expected = _digest(expected_sha256, "expected accepted catalog SHA-256")
    observed = _sha256(content)
    if observed != expected:
        raise MeasureBundleError("accepted catalog SHA-256 does not match")
    catalog = _json_object(content, "accepted catalog")
    _reject_forbidden(catalog)
    if set(catalog) != _CATALOG_TOP_KEYS:
        raise MeasureBundleError("accepted catalog shape is invalid")
    if (
        catalog.get("kind") != "public-evidence-measure-catalog"
        or catalog.get("catalog_version") != "public-evidence-measure-catalog-v1"
        or catalog.get("schema_version") != 1
    ):
        raise MeasureBundleError("accepted catalog identity is invalid")
    manifest = _mapping(catalog.get("manifest"), "accepted catalog manifest")
    if set(manifest) != _CATALOG_MANIFEST_KEYS:
        raise MeasureBundleError("accepted catalog manifest shape is invalid")
    internal = _digest(
        manifest.get("artifact_sha256"), "accepted catalog internal artifact hash"
    )
    unhashed = copy.deepcopy(catalog)
    del unhashed["manifest"]["artifact_sha256"]
    if _sha256(canonical_catalog_bytes(unhashed)) != internal:
        raise MeasureBundleError("accepted catalog internal artifact hash is invalid")

    raw_candidates = catalog.get("accepted_candidates")
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise MeasureBundleError("accepted catalog candidates are invalid")
    candidates: list[dict[str, Any]] = []
    for raw_candidate in raw_candidates:
        candidate = _mapping(raw_candidate, "accepted candidate")
        if set(candidate) != _CANDIDATE_KEYS:
            raise MeasureBundleError("accepted candidate shape is invalid")
        candidate_id = _text(candidate.get("candidate_id"), "candidate ID")
        measure_id = _text(candidate.get("measure_id"), "measure ID")
        if not _CANDIDATE_ID.fullmatch(candidate_id):
            raise MeasureBundleError("accepted candidate ID is invalid")
        if not _MEASURE_ID.fullmatch(measure_id):
            raise MeasureBundleError("accepted measure ID is invalid")
        _identifier(candidate.get("database"), "candidate database")
        candidates.append(dict(candidate))
    candidate_ids = [item["candidate_id"] for item in candidates]
    measure_ids = [item["measure_id"] for item in candidates]
    if (
        candidate_ids != sorted(candidate_ids)
        or len(candidate_ids) != len(set(candidate_ids))
        or len(measure_ids) != len(set(measure_ids))
        or manifest.get("ordered_candidate_ids") != candidate_ids
        or manifest.get("ordered_measure_ids") != measure_ids
    ):
        raise MeasureBundleError("accepted catalog ordered identities are invalid")

    summary = _mapping(catalog.get("summary"), "accepted catalog summary")
    database_counts = Counter(item["database"] for item in candidates)
    class_counts = Counter(item.get("candidate_class") for item in candidates)
    databases = sorted(database_counts)
    if summary != {
        "accepted_candidate_count": len(candidates),
        "accepted_database_count": len(databases),
        "accepted_databases": databases,
        "candidate_count_by_class": dict(sorted(class_counts.items())),
        "measure_count_by_database": dict(sorted(database_counts.items())),
    }:
        raise MeasureBundleError("accepted catalog summary is invalid")
    generator = _mapping(catalog.get("generator"), "accepted catalog generator")
    if (
        generator.get("database_count") != len(databases)
        or generator.get("databases") != databases
    ):
        raise MeasureBundleError("accepted catalog generator inventory is invalid")
    catalog["accepted_candidates"] = candidates
    return catalog, observed


def _validated_c5_bundle(
    database: str,
    raw_files: Mapping[str, bytes],
    raw_manifest: Mapping[str, object],
) -> dict[str, bytes]:
    if not isinstance(raw_files, Mapping) or not raw_files:
        raise MeasureBundleError("C5 files must be a non-empty mapping")
    files: dict[str, bytes] = {}
    for raw_name, content in raw_files.items():
        name = _flat_name(raw_name, "C5 file")
        if not isinstance(content, bytes) or not content or not content.endswith(b"\n"):
            raise MeasureBundleError(f"C5 file {name} bytes are invalid")
        files[name] = content
    manifest = _mapping(raw_manifest, "C5 manifest")
    _reject_forbidden(manifest)
    if (
        manifest.get("kind") != "public-omni-semantic-bundle"
        or manifest.get("schema_version") != 1
        or manifest.get("database") != database
    ):
        raise MeasureBundleError("C5 manifest identity is invalid")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise MeasureBundleError("C5 manifest file records are invalid")
    indexed: dict[str, Mapping[str, Any]] = {}
    for raw_record in records:
        record = _mapping(raw_record, "C5 manifest file record")
        if set(record) != _FILE_RECORD_KEYS:
            raise MeasureBundleError("C5 manifest file record is malformed")
        name = _flat_name(record.get("file"), "C5 manifest file")
        if name in indexed:
            raise MeasureBundleError("C5 manifest file record is duplicated")
        indexed[name] = record
    if set(indexed) != set(files):
        raise MeasureBundleError("C5 manifest file record set does not match files")
    for name, content in files.items():
        record = indexed[name]
        if record.get("sha256") != _sha256(content) or record.get("size_bytes") != len(
            content
        ):
            raise MeasureBundleError(f"C5 manifest file record for {name} is invalid")
        document = _yaml_document(content, f"C5 file {name}")
        if name == "relationships":
            if not isinstance(document, list):
                raise MeasureBundleError("C5 relationships must be a YAML sequence")
        elif not isinstance(document, Mapping):
            raise MeasureBundleError(f"C5 file {name} must be a YAML mapping")
        _reject_protected(document)
    if "model" not in files:
        raise MeasureBundleError("C5 bundle has no model file")
    return files


def _with_balanced_settings(files: Mapping[str, bytes]) -> dict[str, bytes]:
    model = files["model"]
    document = _yaml_mapping(model, "C5 model")
    if "ai_settings" in document:
        raise MeasureBundleError("C5 model already declares ai_settings")
    updated = dict(files)
    updated["model"] = model + BALANCED_AI_SETTINGS_YAML
    emitted = _yaml_mapping(updated["model"], "R2 model")
    if emitted.get("ai_settings") != BALANCED_AI_SETTINGS:
        raise MeasureBundleError("R2 Balanced ai_settings materialization failed")
    return updated


def _with_accepted_measures(
    database: str,
    control_files: Mapping[str, bytes],
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, bytes], list[str], list[str]]:
    by_file: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    measure_ids: list[str] = []
    for candidate in candidates:
        if candidate.get("database") != database:
            raise MeasureBundleError("cross-database accepted candidate is invalid")
        view = _mapping(candidate.get("view"), "accepted candidate view")
        if set(view) != {"file_name", "table_stable_id", "view_name"}:
            raise MeasureBundleError("accepted candidate view shape is invalid")
        file_name = _flat_name(view.get("file_name"), "bound view file")
        if file_name not in control_files:
            raise MeasureBundleError(f"bound view file is missing: {file_name}")
        if not file_name.endswith(".view"):
            raise MeasureBundleError("bound view file identity is invalid")
        view_name = _identifier(view.get("view_name"), "bound view name")
        document = _yaml_mapping(control_files[file_name], f"bound view {file_name}")
        if "measures" in document:
            raise MeasureBundleError(
                f"bound view {file_name} already declares measures"
            )
        dimensions = _mapping(document.get("dimensions"), "bound view dimensions")
        measure = _mapping(candidate.get("measure"), "accepted measure")
        if set(measure) != {"definition", "name"}:
            raise MeasureBundleError("accepted measure shape is invalid")
        name = _identifier(measure.get("name"), "measure name")
        definition = _mapping(measure.get("definition"), "measure definition")
        if set(definition) != _MEASURE_DEFINITION_KEYS:
            raise MeasureBundleError("measure definition shape is invalid")
        aggregate_type = _text(definition.get("aggregate_type"), "aggregate type")
        if aggregate_type not in _AGGREGATE_TYPES:
            raise MeasureBundleError("measure aggregate type is invalid")
        _text(definition.get("description"), "measure description")
        _text(definition.get("label"), "measure label")
        sql = _text(definition.get("sql"), "measure SQL")
        match = _FIELD_REFERENCE.fullmatch(sql)
        if match is None or match.group("view") != view_name:
            raise MeasureBundleError("measure SQL view binding is invalid")
        if match.group("field") not in dimensions:
            raise MeasureBundleError("measure SQL field binding is invalid")
        expected_yaml = yaml.safe_dump(
            {"measures": {name: dict(definition)}},
            allow_unicode=True,
            sort_keys=True,
            width=1000,
        )
        if candidate.get("proposed_omni_yaml") != expected_yaml:
            raise MeasureBundleError("candidate proposed Omni YAML is invalid")
        by_file[file_name].append((name, dict(definition)))
        measure_ids.append(_text(candidate.get("measure_id"), "measure ID"))

    treatment = dict(control_files)
    for file_name, definitions in sorted(by_file.items()):
        names = [name for name, _definition in definitions]
        if len(names) != len(set(names)):
            raise MeasureBundleError(f"duplicate measure name in {file_name}")
        payload = {
            "measures": {name: definition for name, definition in sorted(definitions)}
        }
        addition = yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=True,
            width=1000,
        ).encode()
        treatment[file_name] = control_files[file_name] + addition
        emitted = _yaml_mapping(treatment[file_name], f"treatment view {file_name}")
        if emitted.get("measures") != payload["measures"]:
            raise MeasureBundleError("treatment measure materialization failed")
    if len(measure_ids) != len(set(measure_ids)):
        raise MeasureBundleError("accepted measure IDs are duplicated")
    return treatment, sorted(by_file), measure_ids


def _condition_manifest(
    c5_manifest: Mapping[str, object],
    files: Mapping[str, bytes],
    *,
    condition: str,
    catalog_sha256: str,
    source_manifest_sha256: str,
    measure_ids: Sequence[str],
) -> dict[str, Any]:
    manifest = copy.deepcopy(dict(c5_manifest))
    manifest["files"] = _file_records(files)
    manifest["r2_public_evidence_measures"] = {
        "accepted_catalog_sha256": catalog_sha256,
        "balanced_ai_settings": copy.deepcopy(BALANCED_AI_SETTINGS),
        "condition_id": condition,
        "measure_count": len(measure_ids),
        "measure_ids": list(measure_ids),
        "series_id": SERIES_ID,
        "source_c5_manifest_sha256": source_manifest_sha256,
    }
    _reject_forbidden(manifest)
    return manifest


def _validate_condition_pair(
    control: Mapping[str, bytes],
    treatment: Mapping[str, bytes],
    changed_views: Sequence[str],
    candidates: Sequence[Mapping[str, Any]],
) -> None:
    if set(control) != set(treatment):
        raise MeasureBundleError("paired semantic file sets differ")
    changed = {name for name in control if control[name] != treatment[name]}
    if changed != set(changed_views):
        raise MeasureBundleError("paired non-measure file equivalence failed")
    expected_by_file: dict[str, dict[str, Any]] = defaultdict(dict)
    for candidate in candidates:
        file_name = candidate["view"]["file_name"]
        name = candidate["measure"]["name"]
        expected_by_file[file_name][name] = candidate["measure"]["definition"]
    observed_ids = 0
    for file_name in changed_views:
        if not treatment[file_name].startswith(control[file_name]):
            raise MeasureBundleError("treatment changed non-measure view bytes")
        control_document = _yaml_mapping(control[file_name], "control view")
        treatment_document = _yaml_mapping(treatment[file_name], "treatment view")
        if "measures" in control_document:
            raise MeasureBundleError("control view declares measures")
        measures = treatment_document.pop("measures", None)
        if measures != expected_by_file[file_name]:
            raise MeasureBundleError("treatment measure set is not one-to-one")
        if treatment_document != control_document:
            raise MeasureBundleError("paired non-measure semantics differ")
        observed_ids += len(measures)
    if observed_ids != len(candidates):
        raise MeasureBundleError("accepted measure injection is incomplete")


def _validate_bundle_set(bundle: MeasureBundleSet) -> None:
    if not isinstance(bundle, MeasureBundleSet):
        raise MeasureBundleError("bundle set type is invalid")
    manifest = _mapping(bundle.manifest, "bundle-set manifest")
    if (
        manifest.get("kind") != "r2-public-evidence-measure-bundle-set"
        or manifest.get("schema_version") != 1
    ):
        raise MeasureBundleError("bundle-set manifest identity is invalid")
    root = _mapping(manifest.get("manifest"), "bundle-set content manifest")
    internal = _digest(root.get("artifact_sha256"), "bundle-set artifact SHA-256")
    unhashed = copy.deepcopy(dict(manifest))
    del unhashed["manifest"]["artifact_sha256"]
    if _sha256(canonical_catalog_bytes(unhashed)) != internal:
        raise MeasureBundleError("bundle-set internal artifact hash is invalid")
    if root.get("files") != _relative_file_records(bundle.files):
        raise MeasureBundleError("bundle-set file manifest does not match files")
    for relative, content in bundle.files.items():
        _publication_path(Path("/bundle"), relative)
        if not isinstance(content, bytes) or not content:
            raise MeasureBundleError("bundle-set file bytes are invalid")
    _reject_forbidden(manifest)


def _validated_targets(content: bytes) -> list[str]:
    config = _json_object(content, "target configuration")
    _reject_forbidden(config)
    if set(config) != _TARGET_KEYS:
        raise MeasureBundleError("target configuration shape is invalid")
    if config.get("kind") != _TARGET_KIND or config.get("schema_version") != 1:
        raise MeasureBundleError("target configuration identity is invalid")
    databases = config.get("databases")
    if not isinstance(databases, list):
        raise MeasureBundleError("target databases must be a list")
    normalized = [_identifier(item, "target database") for item in databases]
    if normalized != sorted(normalized) or len(normalized) != len(set(normalized)):
        raise MeasureBundleError("target databases must be unique and sorted")
    if len(normalized) != EXPECTED_DATABASE_COUNT:
        raise MeasureBundleError("R2 target configuration must name 16 databases")
    return normalized


def _file_records(files: Mapping[str, bytes]) -> list[dict[str, object]]:
    return [
        {"file": name, "sha256": _sha256(content), "size_bytes": len(content)}
        for name, content in sorted(files.items())
    ]


def _relative_file_records(files: Mapping[str, bytes]) -> list[dict[str, object]]:
    return [
        {"path": name, "sha256": _sha256(content), "size_bytes": len(content)}
        for name, content in sorted(files.items())
    ]


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    if not content or len(content) > 16_000_000:
        raise MeasureBundleError(f"{label} size is invalid")
    try:
        value = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MeasureBundleError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise MeasureBundleError(f"{label} must be a JSON object")
    return value


def _strict_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MeasureBundleError(f"duplicate JSON field {key}")
        result[key] = value
    return result


def _yaml_document(content: bytes, label: str) -> object:
    try:
        return yaml.load(content, Loader=_UniqueSafeLoader)
    except (UnicodeError, yaml.YAMLError) as error:
        raise MeasureBundleError(f"{label} is not valid unique-key YAML") from error


def _yaml_mapping(content: bytes, label: str) -> dict[str, Any]:
    value = _yaml_document(content, label)
    if not isinstance(value, dict):
        raise MeasureBundleError(f"{label} must be a YAML mapping")
    return value


def _reject_forbidden(value: object) -> None:
    try:
        _reject_forbidden_value(value)
    except MeasureReviewError as error:
        raise MeasureBundleError(str(error)) from error


def _reject_protected(value: object) -> None:
    try:
        reject_protected_fields(value)
    except ProtectedFieldError as error:
        raise MeasureBundleError(str(error)) from error


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MeasureBundleError(f"{label} must be an object")
    return dict(value)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MeasureBundleError(f"{label} must be non-empty text")
    return value


def _identifier(value: object, label: str) -> str:
    text = _text(value, label)
    if not _IDENTIFIER.fullmatch(text):
        raise MeasureBundleError(f"{label} must be a safe identifier")
    return text


def _flat_name(value: object, label: str) -> str:
    name = _text(value, label)
    if name in {".", ".."} or "/" in name or "\x00" in name:
        raise MeasureBundleError(f"{label} must be one safe path component")
    return name


def _digest(value: object, label: str) -> str:
    digest = _text(value, label)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise MeasureBundleError(f"{label} is invalid")
    return digest


def _workspace_root(workspace: Path) -> Path:
    if not isinstance(workspace, Path):
        raise MeasureBundleError("workspace must be a Path")
    try:
        return workspace.resolve(strict=True)
    except OSError as error:
        raise MeasureBundleError("workspace is unavailable") from error


def _published_root(source: Path) -> Path:
    if not isinstance(source, Path):
        raise MeasureBundleError("published bundle root must be a Path")
    try:
        metadata = source.lstat()
        if source.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise OSError("not a dedicated directory")
        return source.resolve(strict=True)
    except OSError as error:
        raise MeasureBundleError("published bundle root is unavailable") from error


def _published_relative_files(root: Path) -> set[str]:
    observed: set[str] = set()
    try:
        for current, directories, names in os.walk(root, followlinks=False):
            current_path = Path(current)
            for directory in directories:
                metadata = (current_path / directory).lstat()
                if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    raise OSError("unsafe published directory")
            for name in names:
                path = current_path / name
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                    raise OSError("unsafe published file")
                observed.add(path.relative_to(root).as_posix())
    except OSError as error:
        raise MeasureBundleError("published bundle tree is unsafe") from error
    return observed


def _inside_workspace(root: Path, path: Path, label: str) -> Path:
    selected = path if path.is_absolute() else root / path
    try:
        resolved = selected.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise MeasureBundleError(f"{label} must be inside the workspace") from error
    return resolved


def _read(path: Path, maximum_bytes: int) -> bytes:
    try:
        return read_regular_file(path, maximum_bytes=maximum_bytes)
    except HKBFileSafetyError as error:
        raise MeasureBundleError(str(error)) from error


def _publication_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str):
        raise MeasureBundleError("bundle relative path must be text")
    parts = Path(relative).parts
    if (
        len(parts) != 3
        or parts[0] not in _CONDITION_DIRECTORIES.values()
        or not _IDENTIFIER.fullmatch(parts[1])
        or parts[2] in {"", ".", ".."}
        or "/" in parts[2]
    ):
        raise MeasureBundleError(f"bundle relative path is invalid: {relative}")
    return root.joinpath(*parts)


def _prepare_publication_parent(root: Path, relative: str) -> None:
    target = _publication_path(root, relative)
    for directory in (target.parents[1], target.parent):
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            metadata = directory.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_ISLNK(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise OSError("publication directory is not private")


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


__all__ = [
    "BALANCED_AI_SETTINGS",
    "BALANCED_AI_SETTINGS_YAML",
    "EXPECTED_ACCEPTED_CATALOG_SHA256",
    "DatabaseMeasureBundlePair",
    "MeasureBundleError",
    "MeasureBundleSet",
    "build_database_measure_bundle_pair",
    "build_workspace_measure_bundle_set",
    "verify_measure_bundle_set",
    "write_measure_bundle_set",
]

"""Hash-bound public reference adapters for the C1-C3 direct-SQL conditions."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal

from .content_policy import ContentPolicy
from .direct_public_parsing import (
    DirectPublicContextError,
    canonical,
    required_nonnegative_int,
    required_text,
    schema_payload,
    semantic_file_items,
    text_list,
    validate_payload,
)
from .direct_public_search import (
    rank_public_records as _rank_public_records,
    search_query as _search_query,
    search_schema,
)
from .direct_capture_contract import DirectReferenceResult
from .direct_runtime_binding import DirectContextIdentity
from .omni_probe_preflight import OmniProbePreflightError, committed_spec

DirectPublicCondition = Literal["C1", "C2", "C3"]

MAX_HKB_MATCHES = 8
MAX_SEMANTIC_MATCHES = 8
MAX_SCHEMA_SOURCE_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_HKB_PAYLOAD_BYTES = 128 * 1024
MAX_SEMANTIC_PAYLOAD_BYTES = 64 * 1024

_CONDITION_PATHS = {
    "C1": Path("config/conditions/c1-direct-sql-v1.json"),
    "C2": Path("config/conditions/c2-direct-sql-v1.json"),
    "C3": Path("config/conditions/c3-direct-sql-v1.json"),
}
_INSTRUCTIONS_PATH = Path("config/instructions/direct-sql-v1.json")
_PROMPT_PATH = Path("config/prompts/direct-sql-v1.txt")
_SCHEMA_MANIFEST = Path("semantic_models/public_schema_ir/manifest.json")
_HKB_MANIFEST = Path("semantic_models/public_ir/manifest.json")
_SEMANTIC_MANIFEST = Path("semantic_models/public_bundle/manifest.json")
_PUBLIC_BASELINE_ROOT = Path("semantic_models/public_baseline")
_LEGACY_CANARY_DATABASE = "archeology_scan_large"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DATABASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,127}")
_POLICY_METADATA_INSTRUCTION = (
    "Use only condition-specific public reference tools and read-only Query SQL; "
    "refuse when public information is insufficient."
)


@dataclass(frozen=True)
class DirectPublicTools:
    """Condition-scoped callbacks passed to ``DirectSqlCapture``."""

    identity: DirectContextIdentity
    inspect_schema: Callable[[str], DirectReferenceResult]
    search_hkb: Callable[[str], DirectReferenceResult] | None
    search_semantic_model: Callable[[str], DirectReferenceResult] | None
    render_question: Callable[[str], str]


@dataclass(frozen=True)
class _CommittedInput:
    content: bytes
    sha256: str
    path: Path


@dataclass(frozen=True)
class _PublicBaseInputs:
    condition: DirectPublicCondition
    database: str
    environment: Mapping[str, str]
    policy: ContentPolicy
    condition_spec: _CommittedInput
    instructions: _CommittedInput
    prompt: _CommittedInput
    schema_manifest: _CommittedInput
    schema_input: _CommittedInput
    schema_bytes: bytes


@dataclass(frozen=True)
class _ConditionReferences:
    hkb_manifest: _CommittedInput | None = None
    hkb_input: _CommittedInput | None = None
    hkb_bytes: bytes | None = None
    semantic_manifest: _CommittedInput | None = None
    semantic_bytes: bytes | None = None


def load_direct_public_tools(
    workspace: Path,
    commit: str,
    database: str,
    condition: str,
    *,
    environment: Mapping[str, str] | None = None,
) -> DirectPublicTools:
    """Load one condition from committed public artifacts and expose exact tools."""
    base = _load_public_base(
        workspace, commit, database, condition, environment=environment
    )
    references = _load_condition_references(workspace, commit, base)
    identity = _identity(
        base.condition,
        base.database,
        base.condition_spec,
        base.instructions,
        base.prompt,
        base.schema_manifest,
        base.schema_input,
        references.hkb_manifest,
        references.hkb_input,
        references.semantic_manifest,
        base.environment,
    )
    return _public_tools(base, references, identity)


def _load_public_base(
    workspace: Path,
    commit: str,
    database: str,
    condition: str,
    *,
    environment: Mapping[str, str] | None,
) -> _PublicBaseInputs:
    selected = _condition(condition)
    selected_database = _database(database)
    selected_environment = os.environ if environment is None else environment
    policy = ContentPolicy.from_environment(selected_environment)
    condition_spec = _load_committed(
        workspace, commit, _CONDITION_PATHS[selected], policy
    )
    instructions = _load_committed(workspace, commit, _INSTRUCTIONS_PATH, policy)
    prompt = _load_committed(workspace, commit, _PROMPT_PATH, policy)
    _validate_condition_spec(condition_spec.content, selected)
    _validate_instructions(instructions.content)
    _validate_prompt(prompt.content)

    schema_manifest = _load_committed(
        workspace, commit, _schema_manifest_path(selected_database), policy
    )
    schema_input = _schema_input(
        workspace, commit, selected_database, schema_manifest, policy
    )
    schema_context = schema_payload(
        selected_database,
        _jsonl_records(schema_input.content, "schema IR"),
        schema_input.sha256,
        schema_manifest.sha256,
        MAX_SCHEMA_SOURCE_PAYLOAD_BYTES,
        policy,
    )
    return _PublicBaseInputs(
        selected,
        selected_database,
        selected_environment,
        policy,
        condition_spec,
        instructions,
        prompt,
        schema_manifest,
        schema_input,
        canonical(schema_context),
    )


def _load_condition_references(
    workspace: Path, commit: str, base: _PublicBaseInputs
) -> _ConditionReferences:
    if base.condition == "C2":
        hkb_manifest = _load_committed(workspace, commit, _HKB_MANIFEST, base.policy)
        hkb_input = _hkb_input(
            workspace, commit, base.database, hkb_manifest, base.policy
        )
        hkb_records = _validated_hkb_records(
            base.database, _jsonl_records(hkb_input.content, "HKB IR")
        )
        return _ConditionReferences(
            hkb_manifest=hkb_manifest,
            hkb_input=hkb_input,
            hkb_bytes=canonical(hkb_records),
        )
    if base.condition == "C3":
        semantic_manifest = _load_committed(
            workspace,
            commit,
            _semantic_manifest_path(base.database),
            base.policy,
        )
        semantic_items = _semantic_items(
            workspace, commit, base.database, semantic_manifest, base.policy
        )
        return _ConditionReferences(
            semantic_manifest=semantic_manifest,
            semantic_bytes=canonical(semantic_items),
        )
    return _ConditionReferences()


def _schema_manifest_path(database: str) -> Path:
    if database == _LEGACY_CANARY_DATABASE:
        return _SCHEMA_MANIFEST
    return _PUBLIC_BASELINE_ROOT / database / "schema_ir/manifest.json"


def _semantic_manifest_path(database: str) -> Path:
    if database == _LEGACY_CANARY_DATABASE:
        return _SEMANTIC_MANIFEST
    return _PUBLIC_BASELINE_ROOT / database / "bundle/manifest.json"


def _public_tools(
    base: _PublicBaseInputs,
    references: _ConditionReferences,
    identity: DirectContextIdentity,
) -> DirectPublicTools:
    return DirectPublicTools(
        identity=identity,
        inspect_schema=partial(
            search_schema, base.schema_bytes, base.policy, identity.context_sha256
        ),
        search_hkb=(
            partial(
                _search_hkb,
                base.database,
                references.hkb_bytes,
                base.policy,
                identity.context_sha256,
            )
            if base.condition == "C2"
            else None
        ),
        search_semantic_model=(
            partial(
                _search_semantic,
                base.database,
                references.semantic_bytes,
                base.policy,
                identity.context_sha256,
            )
            if base.condition == "C3"
            else None
        ),
        render_question=partial(_render_question, base.prompt.content, base.policy),
    )


def _load_committed(
    workspace: Path,
    commit: str,
    path: Path,
    policy: ContentPolicy,
) -> _CommittedInput:
    try:
        value = committed_spec(workspace, commit, path)
    except OmniProbePreflightError as error:
        raise DirectPublicContextError(str(error)) from error
    if not policy.bytes_are_safe(value.content):
        raise DirectPublicContextError(
            "committed public artifact contains sensitive content"
        )
    return _CommittedInput(value.content, value.sha256, value.path)


def _schema_input(
    workspace: Path,
    commit: str,
    database: str,
    manifest_input: _CommittedInput,
    policy: ContentPolicy,
) -> _CommittedInput:
    manifest = _json_object(manifest_input.content, "schema manifest")
    if (
        manifest.get("kind") != "public-schema-intermediate-representation"
        or manifest.get("schema_version") != 1
        or manifest.get("database") != database
        or not isinstance(manifest.get("output"), dict)
        or not isinstance(manifest.get("validation"), dict)
        or manifest["validation"].get("status") != "passed"
    ):
        raise DirectPublicContextError("schema manifest is invalid")
    output = manifest["output"]
    artifact = _load_committed(
        workspace,
        commit,
        manifest_input.path.parent / _manifest_child(output.get("file")),
        policy,
    )
    _verify_artifact(artifact, output)
    return artifact


def _hkb_input(
    workspace: Path,
    commit: str,
    database: str,
    manifest_input: _CommittedInput,
    policy: ContentPolicy,
) -> _CommittedInput:
    manifest = _json_object(manifest_input.content, "HKB manifest")
    databases = manifest.get("databases")
    if (
        manifest.get("kind") != "public-hkb-intermediate-representation"
        or manifest.get("schema_version") != 1
        or not isinstance(databases, dict)
        or not isinstance(databases.get(database), dict)
    ):
        raise DirectPublicContextError("HKB manifest is invalid")
    metadata = databases[database]
    artifact = _load_committed(
        workspace,
        commit,
        manifest_input.path.parent / _manifest_child(metadata.get("ir_file")),
        policy,
    )
    _verify_artifact(
        artifact,
        {"sha256": metadata.get("ir_sha256"), "size_bytes": None},
    )
    return artifact


def _semantic_items(
    workspace: Path,
    commit: str,
    database: str,
    manifest_input: _CommittedInput,
    policy: ContentPolicy,
) -> tuple[dict[str, Any], ...]:
    manifest = _json_object(manifest_input.content, "semantic bundle manifest")
    files = manifest.get("files")
    validation = manifest.get("validation")
    if (
        manifest.get("kind") != "public-omni-semantic-bundle"
        or manifest.get("schema_version") != 1
        or manifest.get("database") != database
        or not isinstance(files, list)
        or not files
        or not isinstance(validation, dict)
        or validation.get("status") != "passed"
        or validation.get("public_inputs_only") is not True
    ):
        raise DirectPublicContextError("semantic bundle manifest is invalid")
    items: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    for metadata in files:
        if not isinstance(metadata, dict):
            raise DirectPublicContextError("semantic bundle file metadata is invalid")
        file_name = _manifest_child(metadata.get("file"))
        if file_name in seen_files or not file_name.endswith((".view", ".topic")):
            raise DirectPublicContextError("semantic bundle file list is invalid")
        seen_files.add(file_name)
        artifact = _load_committed(
            workspace, commit, manifest_input.path.parent / file_name, policy
        )
        _verify_artifact(artifact, metadata)
        items.extend(semantic_file_items(file_name, artifact.content))
    if not items:
        raise DirectPublicContextError("semantic bundle contains no searchable objects")
    return tuple(sorted(items, key=lambda item: item["object_id"]))


def _verify_artifact(artifact: _CommittedInput, metadata: Mapping[str, Any]) -> None:
    expected = metadata.get("sha256")
    if not isinstance(expected, str) or _SHA256.fullmatch(expected) is None:
        raise DirectPublicContextError("public artifact SHA-256 is invalid")
    if artifact.sha256 != expected:
        raise DirectPublicContextError("public artifact SHA-256 does not match")
    size = metadata.get("size_bytes")
    if size is not None and (type(size) is not int or size != len(artifact.content)):
        raise DirectPublicContextError("public artifact size does not match")


def _validated_hkb_records(
    database: str, records: tuple[dict[str, Any], ...]
) -> tuple[dict[str, Any], ...]:
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("database") != database:
            raise DirectPublicContextError("HKB IR database does not match")
        stable_id = required_text(record, "stable_id")
        if stable_id in indexed:
            raise DirectPublicContextError("HKB IR stable IDs must be unique")
        required_text(record, "knowledge")
        required_text(record, "description")
        required_text(record, "definition")
        required_text(record, "source_type")
        dependencies = text_list(
            record.get("dependency_stable_ids"), "HKB dependencies"
        )
        closure = text_list(record.get("dependency_closure_stable_ids"), "HKB closure")
        if len(dependencies) != len(set(dependencies)):
            raise DirectPublicContextError("HKB dependencies must be unique")
        if len(closure) != len(set(closure)):
            raise DirectPublicContextError("HKB closure IDs must be unique")
        required_nonnegative_int(record, "dependency_depth")
        if not isinstance(record.get("provenance"), dict):
            raise DirectPublicContextError("HKB provenance is invalid")
        indexed[stable_id] = record
    direct_dependencies = {
        stable_id: tuple(
            text_list(record.get("dependency_stable_ids"), "HKB dependencies")
        )
        for stable_id, record in indexed.items()
    }
    for record in indexed.values():
        for dependency in text_list(
            record.get("dependency_stable_ids"), "HKB dependencies"
        ):
            if dependency not in indexed:
                raise DirectPublicContextError(
                    "HKB dependency references a missing record"
                )
        for dependency in text_list(
            record.get("dependency_closure_stable_ids"), "HKB closure"
        ):
            if dependency not in indexed:
                raise DirectPublicContextError(
                    "HKB closure references a missing record"
                )
    _validate_hkb_dependency_graph(indexed, direct_dependencies)
    return tuple(indexed[key] for key in sorted(indexed, key=_stable_id_key))


def _validate_hkb_dependency_graph(
    records: Mapping[str, Mapping[str, Any]],
    direct_dependencies: Mapping[str, tuple[str, ...]],
) -> None:
    memo: dict[str, tuple[frozenset[str], int]] = {}
    active: set[str] = set()

    def resolve(stable_id: str) -> tuple[frozenset[str], int]:
        if stable_id in memo:
            return memo[stable_id]
        if stable_id in active:
            raise DirectPublicContextError("HKB dependency graph contains a cycle")
        active.add(stable_id)
        expected_closure: set[str] = set()
        expected_depth = 0
        for dependency in direct_dependencies[stable_id]:
            dependency_closure, dependency_depth = resolve(dependency)
            expected_closure.add(dependency)
            expected_closure.update(dependency_closure)
            expected_depth = max(expected_depth, dependency_depth + 1)
        active.remove(stable_id)

        record = records[stable_id]
        declared_closure = set(
            text_list(record.get("dependency_closure_stable_ids"), "HKB closure")
        )
        if declared_closure != expected_closure:
            raise DirectPublicContextError(
                "HKB closure does not match the dependency graph"
            )
        if required_nonnegative_int(record, "dependency_depth") != expected_depth:
            raise DirectPublicContextError(
                "HKB dependency depth does not match the dependency graph"
            )
        resolved = frozenset(expected_closure), expected_depth
        memo[stable_id] = resolved
        return resolved

    for stable_id in sorted(records, key=_stable_id_key):
        resolve(stable_id)


def _search_hkb(
    database: str,
    canonical_records: bytes | None,
    policy: ContentPolicy,
    context_sha256: str,
    query: str,
) -> DirectReferenceResult:
    records = _decode_canonical_records(canonical_records, "HKB search records")
    terms = _search_query(query, policy)
    matched = list(
        _rank_public_records(
            records,
            terms,
            ("stable_id", "knowledge", "description", "definition", "source_type"),
        )
    )
    selected = matched[:MAX_HKB_MATCHES]
    while True:
        payload = _hkb_payload(
            database, query, selected, len(matched) > len(selected), records
        )
        if len(canonical(payload)) <= MAX_HKB_PAYLOAD_BYTES:
            break
        if not selected:
            raise DirectPublicContextError("HKB search payload exceeds its bound")
        selected = selected[:-1]
    validate_payload(payload, MAX_HKB_PAYLOAD_BYTES, policy)
    return DirectReferenceResult(
        json.loads(canonical(payload)), context_sha256, "search_hkb"
    )


def _hkb_payload(
    database: str,
    query: str,
    matched: Sequence[Mapping[str, Any]],
    truncated: bool,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    index = {record["stable_id"]: record for record in records}
    required_by: dict[str, set[str]] = {}
    for record in matched:
        for dependency in record["dependency_closure_stable_ids"]:
            required_by.setdefault(dependency, set()).add(record["stable_id"])
    dependencies = [
        {
            **_hkb_summary(index[stable_id]),
            "required_by": sorted(required_by[stable_id], key=_stable_id_key),
            "retrieval_role": "dependency_closure",
        }
        for stable_id in sorted(required_by, key=_stable_id_key)
        if stable_id not in {record["stable_id"] for record in matched}
    ]
    retrieved_ids = {record["stable_id"] for record in (*matched, *dependencies)}
    return {
        "database": database,
        "dependencies": dependencies,
        "kind": "public-hkb-search",
        "matches": [
            {**_hkb_summary(record), "retrieval_role": "direct_match"}
            for record in matched
        ],
        "query": query,
        "retrieved_hkb_stable_ids": sorted(retrieved_ids, key=_stable_id_key),
        "truncated": truncated,
    }


def _hkb_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "definition": record["definition"],
        "dependency_closure_stable_ids": list(record["dependency_closure_stable_ids"]),
        "dependency_depth": record["dependency_depth"],
        "dependency_stable_ids": list(record["dependency_stable_ids"]),
        "description": record["description"],
        "knowledge": record["knowledge"],
        "provenance": record["provenance"],
        "source_type": record["source_type"],
        "stable_id": record["stable_id"],
    }


def _search_semantic(
    database: str,
    canonical_items: bytes | None,
    policy: ContentPolicy,
    context_sha256: str,
    query: str,
) -> DirectReferenceResult:
    items = _decode_canonical_records(canonical_items, "semantic search items")
    terms = _search_query(query, policy)
    searchable_fields = tuple(
        sorted(
            set()
            .union(*(item.keys() for item in items))
            .difference({"source_file", "object_kind"})
        )
    )
    matched = list(_rank_public_records(items, terms, searchable_fields))
    selected = matched[:MAX_SEMANTIC_MATCHES]
    while True:
        payload = {
            "database": database,
            "kind": "public-omni-semantic-search",
            "matches": selected,
            "query": query,
            "truncated": len(matched) > len(selected),
        }
        if len(canonical(payload)) <= MAX_SEMANTIC_PAYLOAD_BYTES:
            break
        if not selected:
            raise DirectPublicContextError("semantic search payload exceeds its bound")
        selected = selected[:-1]
    validate_payload(payload, MAX_SEMANTIC_PAYLOAD_BYTES, policy)
    return DirectReferenceResult(
        json.loads(canonical(payload)),
        context_sha256,
        "search_semantic_model",
        semantic_objects=tuple(item["object_id"] for item in selected),
    )


def _identity(
    condition: DirectPublicCondition,
    selected_database: str,
    condition_spec: _CommittedInput,
    instructions: _CommittedInput,
    prompt: _CommittedInput,
    schema_manifest: _CommittedInput,
    schema: _CommittedInput,
    hkb_manifest: _CommittedInput | None,
    hkb: _CommittedInput | None,
    semantic_manifest: _CommittedInput | None,
    environment: Mapping[str, str],
) -> DirectContextIdentity:
    components = {
        "condition_config": condition_spec.sha256,
        "instructions": instructions.sha256,
        "prompt": prompt.sha256,
        "schema": schema.sha256,
        "schema_manifest": schema_manifest.sha256,
    }
    if hkb_manifest is not None and hkb is not None:
        components.update({"hkb": hkb.sha256, "hkb_manifest": hkb_manifest.sha256})
    if semantic_manifest is not None:
        components["semantic_manifest"] = semantic_manifest.sha256
    return DirectContextIdentity.from_components(
        condition=condition,
        selected_database=selected_database,
        component_sha256=components,
        environment=environment,
    )


def _validate_condition_spec(content: bytes, condition: DirectPublicCondition) -> None:
    value = _json_object(content, "condition specification")
    expected = {
        "condition": condition,
        "execution": "direct_sql_harness",
        "hkb_access": "searchable" if condition == "C2" else "none",
        "hkb_manifest": _HKB_MANIFEST.as_posix() if condition == "C2" else None,
        "knowledge": {
            "C1": "public_schema",
            "C2": "public_schema_and_searchable_public_hkb",
            "C3": "public_schema_and_searchable_omni_semantic_bundle",
        }[condition],
        "question_specific_hidden_annotations": False,
        "runtime_oracle_context": False,
        "schema_access": "inspect",
        "schema_manifest": _SCHEMA_MANIFEST.as_posix(),
        "semantic_enforcement": "none",
        "semantic_model_access": "searchable" if condition == "C3" else "none",
        "semantic_model_manifest": (
            _SEMANTIC_MANIFEST.as_posix() if condition == "C3" else None
        ),
    }
    if value != expected:
        raise DirectPublicContextError("condition specification is unsupported")


def _validate_instructions(content: bytes) -> None:
    expected = {
        "adapter_instruction": _POLICY_METADATA_INSTRUCTION,
        "question_specific_hidden_annotations": False,
        "runtime_oracle_context": False,
    }
    if _json_object(content, "instruction specification") != expected:
        raise DirectPublicContextError("instruction specification is unsupported")


def _validate_prompt(content: bytes) -> None:
    if content != b"{question}\n":
        raise DirectPublicContextError("prompt specification is unsupported")


def _render_question(content: bytes, policy: ContentPolicy, question: str) -> str:
    _validate_prompt(content)
    if not isinstance(question, str) or not question.strip():
        raise DirectPublicContextError("question must be a non-empty string")
    if not policy.query_is_safe(question):
        raise DirectPublicContextError("question contains sensitive content")
    return question


def _condition(value: str) -> DirectPublicCondition:
    if value not in _CONDITION_PATHS:
        raise DirectPublicContextError("condition must be C1, C2, or C3")
    return value  # type: ignore[return-value]


def _database(value: str) -> str:
    if not isinstance(value, str) or _DATABASE.fullmatch(value) is None:
        raise DirectPublicContextError("database must be a compact public identifier")
    return value


def _manifest_child(value: object) -> str:
    if not isinstance(value, str):
        raise DirectPublicContextError("public artifact file name is invalid")
    path = Path(value)
    if path.is_absolute() or len(path.parts) != 1 or path.name != value:
        raise DirectPublicContextError("public artifact file name is invalid")
    return value


def _json_object(content: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DirectPublicContextError(
            f"{description} must contain valid JSON"
        ) from error
    if not isinstance(value, dict):
        raise DirectPublicContextError(f"{description} must be an object")
    return value


def _jsonl_records(content: bytes, description: str) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    try:
        for line in content.decode("utf-8").splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("record is not an object")
            records.append(value)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise DirectPublicContextError(
            f"{description} must contain valid JSONL"
        ) from error
    if not records:
        raise DirectPublicContextError(f"{description} must not be empty")
    return tuple(records)


def _decode_canonical_records(
    content: bytes | None, description: str
) -> tuple[dict[str, Any], ...]:
    if content is None:
        raise DirectPublicContextError(f"{description} are unavailable")
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DirectPublicContextError(f"{description} are invalid") from error
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise DirectPublicContextError(f"{description} are invalid")
    return tuple(value)


def _stable_id_key(value: str) -> tuple[str, int | str]:
    prefix, separator, suffix = value.rpartition(":")
    if separator and suffix.isdigit():
        return prefix, int(suffix)
    return value, value

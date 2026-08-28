"""Structural validation for public-only HKB-to-semantic mapping decisions."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Mapping, Sequence


class SemanticMappingError(ValueError):
    """Raised when a mapping decision violates the public-only contract."""


MAPPING_FIELDS = frozenset(
    {
        "database",
        "dependency_audit",
        "dependency_hkb_stable_ids",
        "dependency_mode",
        "disposition",
        "generality",
        "hkb_stable_id",
        "loss_codes",
        "notes",
        "provenance",
        "relationship_requirements",
        "representation",
        "schema_version",
        "semantic_name",
        "source_bindings",
        "target_table_stable_id",
    }
)
DISPOSITIONS = frozenset(
    {"compile", "context_only", "defer_cross_grain", "unsupported"}
)
REPRESENTATIONS = frozenset(
    {
        "boolean_derived_dimension",
        "categorical_derived_dimension",
        "field_context",
        "numeric_derived_dimension",
    }
)
LOSS_CODES = frozenset(
    {
        "aggregation_unspecified",
        "boundary_semantics_unverified",
        "cardinality_unknown",
        "categorical_mapping_underspecified",
        "categorical_match_semantics_unspecified",
        "context_only_no_executable_object",
        "cross_grain_no_identity",
        "date_boundary_semantics_unspecified",
        "dependency_omission",
        "dependency_redundancy",
        "depends_on_ambiguous_mapping",
        "depends_on_unsupported_mapping",
        "entity_existence_semantics_missing",
        "null_boolean_semantics_unspecified",
        "null_category_semantics_unspecified",
        "null_zero_domain_unspecified",
        "omni_expression_support_unverified",
        "open_ended_value_examples",
        "source_alias_uncertain",
        "source_field_missing",
        "source_type_requires_parsing",
        "source_type_requires_parsing_if_executable",
        "vocabulary_conflict",
        "zero_match_semantics_missing",
    }
)
RELATIONSHIP_REQUIREMENTS = frozenset(
    {
        "target_grain",
        "relationship_path",
        "cardinality",
        "deduplication",
        "multiple_match_behavior",
        "zero_match_behavior",
        "temporal_behavior",
    }
)
BINDING_FIELDS = frozenset({"confidence", "role", "schema_stable_id"})
BINDING_CONFIDENCE = frozenset({"exact", "medium", "ambiguous"})
DEPENDENCY_AUDIT_FIELDS = frozenset({"missing_references", "redundant_references"})
CONTENT_PROVENANCE = frozenset(
    {"public_hkb", "public_schema", "public_column_metadata"}
)
SPEC_FIELDS = frozenset({"database", "records", "schema_aliases", "schema_version"})
SPEC_RECORD_FIELDS = frozenset(
    {
        "bindings",
        "dependency_audit",
        "dependency_mode",
        "disposition",
        "hkb_id",
        "loss_codes",
        "notes",
        "relationship_requirements",
        "representation",
        "semantic_name",
        "target_alias",
    }
)
SPEC_BINDING_FIELDS = frozenset({"alias", "confidence", "role"})
SPEC_DEPENDENCY_AUDIT_FIELDS = frozenset({"missing_ids", "redundant_ids"})


def _source_bindings(value: Any, hkb_id: str) -> list[str]:
    if not isinstance(value, list):
        raise SemanticMappingError(f"{hkb_id} source bindings must be a list")
    roles: set[str] = set()
    schema_ids: list[str] = []
    for index, binding in enumerate(value):
        if not isinstance(binding, dict):
            raise SemanticMappingError(f"{hkb_id} binding {index} must be an object")
        _require_exact_fields(binding, BINDING_FIELDS, f"{hkb_id} binding {index}")
        role = _require_text(binding["role"], f"{hkb_id} binding role")
        schema_id = _require_text(binding["schema_stable_id"], f"{hkb_id} schema ID")
        if role in roles or schema_id in schema_ids:
            raise SemanticMappingError(f"{hkb_id} source bindings must be unique")
        if binding["confidence"] not in BINDING_CONFIDENCE:
            raise SemanticMappingError(f"{hkb_id} binding confidence is invalid")
        roles.add(role)
        schema_ids.append(schema_id)
    return schema_ids


def _dependency_audit(
    value: Any,
    hkb_id: str,
    hkb_index: Mapping[str, Mapping[str, Any]],
    direct_dependencies: list[str],
) -> None:
    if not isinstance(value, dict):
        raise SemanticMappingError(f"{hkb_id} dependency audit must be an object")
    _require_exact_fields(value, DEPENDENCY_AUDIT_FIELDS, f"{hkb_id} dependency audit")
    missing = _require_text_list(value["missing_references"], f"{hkb_id} missing refs")
    redundant = _require_text_list(
        value["redundant_references"], f"{hkb_id} redundant refs"
    )
    if any(item not in hkb_index or item in direct_dependencies for item in missing):
        raise SemanticMappingError(f"{hkb_id} missing dependency audit is invalid")
    if any(item not in direct_dependencies for item in redundant):
        raise SemanticMappingError(f"{hkb_id} redundant dependency audit is invalid")


def _losses_and_relationships(mapping: Mapping[str, Any], hkb_id: str) -> None:
    losses = _require_text_list(mapping["loss_codes"], f"{hkb_id} loss codes")
    if not set(losses).issubset(LOSS_CODES):
        raise SemanticMappingError(f"{hkb_id} has invalid loss codes")
    requirements = _require_text_list(
        mapping["relationship_requirements"], f"{hkb_id} relationship requirements"
    )
    if not set(requirements).issubset(RELATIONSHIP_REQUIREMENTS):
        raise SemanticMappingError(f"{hkb_id} has invalid relationship requirements")


def _validate_audit_loss_contract(mapping: Mapping[str, Any], hkb_id: str) -> None:
    audit = mapping["dependency_audit"]
    losses = set(mapping["loss_codes"])
    missing = bool(audit["missing_references"])
    redundant = bool(audit["redundant_references"])
    if missing != ("dependency_omission" in losses):
        raise SemanticMappingError(f"{hkb_id} dependency omission mismatch")
    if redundant != ("dependency_redundancy" in losses):
        raise SemanticMappingError(f"{hkb_id} dependency redundancy mismatch")


def _require_cross_grain_requirements(mapping: Mapping[str, Any], hkb_id: str) -> None:
    requirements = set(mapping["relationship_requirements"])
    required = {"target_grain", "relationship_path", "cardinality"}
    if not required.issubset(requirements):
        raise SemanticMappingError(
            f"{hkb_id} lacks cross-grain relationship requirements"
        )
    structural_losses = {
        "aggregation_unspecified",
        "cardinality_unknown",
        "cross_grain_no_identity",
    }
    if structural_losses.isdisjoint(mapping["loss_codes"]):
        raise SemanticMappingError(f"{hkb_id} lacks cross-grain loss provenance")


def _require_exact_fields(
    record: Mapping[str, Any], expected: frozenset[str], label: str
) -> None:
    missing = sorted(expected - record.keys())
    unknown = sorted(record.keys() - expected)
    if missing:
        raise SemanticMappingError(f"{label} missing fields: {', '.join(missing)}")
    if unknown:
        raise SemanticMappingError(f"{label} unknown fields: {', '.join(unknown)}")


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticMappingError(f"{label} must be a non-empty string")
    return value


def _require_text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise SemanticMappingError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise SemanticMappingError(f"{label} must not contain duplicates")
    return value


def _require_non_negative_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SemanticMappingError(f"{label} must be a non-negative integer")
    return value


def _schema_aliases(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise SemanticMappingError("schema_aliases must be an object")
    aliases: dict[str, str] = {}
    for alias, stable_id in value.items():
        aliases[_require_text(alias, "schema alias")] = _require_text(
            stable_id, f"schema alias {alias}"
        )
    return aliases


def _resolve_alias(value: Any, aliases: Mapping[str, str], label: str) -> str | None:
    if value is None:
        return None
    alias = _require_text(value, label)
    try:
        return aliases[alias]
    except KeyError as error:
        raise SemanticMappingError(f"unknown schema alias {alias}") from error


def _compile_spec_bindings(
    value: Any, aliases: Mapping[str, str], hkb_id: str
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise SemanticMappingError(f"{hkb_id} spec bindings must be a list")
    bindings: list[dict[str, str]] = []
    for index, binding in enumerate(value):
        if not isinstance(binding, dict):
            raise SemanticMappingError(f"{hkb_id} spec binding {index} is invalid")
        _require_exact_fields(
            binding, SPEC_BINDING_FIELDS, f"{hkb_id} spec binding {index}"
        )
        bindings.append(
            {
                "confidence": binding["confidence"],
                "role": binding["role"],
                "schema_stable_id": _resolve_alias(
                    binding["alias"], aliases, f"{hkb_id} binding alias"
                ),
            }
        )
    return bindings


def _compile_spec_audit(value: Any, database: str, hkb_id: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise SemanticMappingError(f"{hkb_id} spec dependency audit is invalid")
    _require_exact_fields(value, SPEC_DEPENDENCY_AUDIT_FIELDS, f"{hkb_id} spec audit")

    def stable_ids(items: Any, label: str) -> list[str]:
        if not isinstance(items, list):
            raise SemanticMappingError(f"{hkb_id} {label} must be a list")
        return [
            f"{database}:hkb:{_require_non_negative_int(item, label)}" for item in items
        ]

    return {
        "missing_references": stable_ids(value["missing_ids"], "missing IDs"),
        "redundant_references": stable_ids(value["redundant_ids"], "redundant IDs"),
    }


def _compile_spec_record(
    spec_record: Mapping[str, Any],
    database: str,
    aliases: Mapping[str, str],
    hkb: Mapping[str, Any],
) -> dict[str, Any]:
    hkb_id = _require_text(hkb.get("stable_id"), "HKB stable ID")
    _require_exact_fields(spec_record, SPEC_RECORD_FIELDS, f"{hkb_id} spec")
    bindings = _compile_spec_bindings(spec_record["bindings"], aliases, hkb_id)
    schema_ids = [binding["schema_stable_id"] for binding in bindings]
    content = ["public_hkb"]
    if schema_ids:
        content.extend(["public_schema", "public_column_metadata"])
    return {
        "database": database,
        "dependency_audit": _compile_spec_audit(
            spec_record["dependency_audit"], database, hkb_id
        ),
        "dependency_hkb_stable_ids": hkb.get("dependency_stable_ids"),
        "dependency_mode": spec_record["dependency_mode"],
        "disposition": spec_record["disposition"],
        "generality": "database_specific_legitimate_modeling",
        "hkb_stable_id": hkb_id,
        "loss_codes": spec_record["loss_codes"],
        "notes": spec_record["notes"],
        "provenance": {
            "content": content,
            "intervention": "human_general_modeling_inference",
            "sources": {
                "hkb_stable_id": hkb_id,
                "schema_stable_ids": schema_ids,
            },
            "transformation_class": "interpretive",
        },
        "relationship_requirements": spec_record["relationship_requirements"],
        "representation": spec_record["representation"],
        "schema_version": 1,
        "semantic_name": spec_record["semantic_name"],
        "source_bindings": bindings,
        "target_table_stable_id": _resolve_alias(
            spec_record["target_alias"], aliases, f"{hkb_id} target alias"
        ),
    }


def _index_records(
    records: Sequence[Mapping[str, Any]], label: str
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        stable_id = _require_text(record.get("stable_id"), f"{label} stable_id")
        if stable_id in indexed:
            raise SemanticMappingError(f"duplicate {label} stable ID {stable_id}")
        indexed[stable_id] = record
    if not indexed:
        raise SemanticMappingError(f"{label} records must not be empty")
    return indexed


def _schema_table_id(
    stable_id: str,
    schema_index: Mapping[str, Mapping[str, Any]],
) -> str:
    record = schema_index.get(stable_id)
    if record is None:
        raise SemanticMappingError(f"mapping references unknown schema ID {stable_id}")
    kind = record.get("record_kind")
    if kind == "table":
        return stable_id
    if kind == "column":
        return _require_text(record.get("table_stable_id"), f"{stable_id} table")
    if kind == "structured_leaf":
        column_id = _require_text(record.get("column_stable_id"), f"{stable_id} column")
        return _schema_table_id(column_id, schema_index)
    raise SemanticMappingError(f"schema ID {stable_id} cannot be a mapping input")


def _validate_provenance(
    mapping: Mapping[str, Any], hkb_id: str, schema_ids: list[str]
) -> None:
    provenance = mapping.get("provenance")
    if not isinstance(provenance, dict):
        raise SemanticMappingError(f"{hkb_id} provenance must be an object")
    _require_exact_fields(
        provenance,
        frozenset({"content", "intervention", "sources", "transformation_class"}),
        f"{hkb_id} provenance",
    )
    content = _require_text_list(provenance["content"], f"{hkb_id} content provenance")
    if not set(content).issubset(CONTENT_PROVENANCE) or "public_hkb" not in content:
        raise SemanticMappingError(f"{hkb_id} has invalid content provenance")
    if schema_ids and not {"public_schema", "public_column_metadata"}.issubset(content):
        raise SemanticMappingError(f"{hkb_id} schema inputs lack public provenance")
    if provenance["intervention"] != "human_general_modeling_inference":
        raise SemanticMappingError(f"{hkb_id} has invalid intervention provenance")
    if provenance["transformation_class"] != "interpretive":
        raise SemanticMappingError(f"{hkb_id} has invalid transformation class")
    _validate_provenance_sources(provenance["sources"], hkb_id, schema_ids)


def _validate_provenance_sources(
    sources: Any, hkb_id: str, schema_ids: list[str]
) -> None:
    if not isinstance(sources, dict):
        raise SemanticMappingError(f"{hkb_id} provenance sources must be an object")
    _require_exact_fields(
        sources,
        frozenset({"hkb_stable_id", "schema_stable_ids"}),
        f"{hkb_id} provenance sources",
    )
    if sources["hkb_stable_id"] != hkb_id:
        raise SemanticMappingError(f"{hkb_id} provenance HKB source mismatch")
    if sources["schema_stable_ids"] != schema_ids:
        raise SemanticMappingError(f"{hkb_id} provenance schema sources mismatch")


def _validate_common_mapping(
    mapping: Mapping[str, Any],
    hkb: Mapping[str, Any],
    hkb_index: Mapping[str, Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    hkb_id = _require_text(mapping.get("hkb_stable_id"), "mapping HKB stable ID")
    _require_exact_fields(mapping, MAPPING_FIELDS, hkb_id)
    if mapping["schema_version"] != 1 or isinstance(mapping["schema_version"], bool):
        raise SemanticMappingError(f"{hkb_id} schema_version must equal 1")
    if mapping["database"] != hkb.get("database"):
        raise SemanticMappingError(f"{hkb_id} database mismatch")
    dependencies = _require_text_list(
        mapping["dependency_hkb_stable_ids"], f"{hkb_id} dependencies"
    )
    if dependencies != hkb.get("dependency_stable_ids"):
        raise SemanticMappingError(f"{hkb_id} dependency list mismatch")
    unknown_dependencies = [item for item in dependencies if item not in hkb_index]
    if unknown_dependencies:
        raise SemanticMappingError(
            f"{hkb_id} references unknown HKB dependency "
            + ", ".join(unknown_dependencies)
        )
    schema_ids = _source_bindings(mapping["source_bindings"], hkb_id)
    for schema_id in schema_ids:
        _schema_table_id(schema_id, schema_index)
    _dependency_audit(mapping["dependency_audit"], hkb_id, hkb_index, dependencies)
    _losses_and_relationships(mapping, hkb_id)
    _validate_audit_loss_contract(mapping, hkb_id)
    _require_text(mapping["notes"], f"{hkb_id} notes")
    if mapping["generality"] != "database_specific_legitimate_modeling":
        raise SemanticMappingError(f"{hkb_id} has invalid generality")
    _validate_provenance(mapping, hkb_id, schema_ids)
    return schema_ids, dependencies


def _validate_compile(
    mapping: Mapping[str, Any],
    schema_ids: list[str],
    dependencies: list[str],
    schema_index: Mapping[str, Mapping[str, Any]],
    mapping_index: Mapping[str, Mapping[str, Any]],
) -> None:
    hkb_id = mapping["hkb_stable_id"]
    if "source_field_missing" in mapping["loss_codes"]:
        raise SemanticMappingError(f"{hkb_id} compile mapping has non-executable loss")
    target = _require_text(mapping["target_table_stable_id"], f"{hkb_id} target")
    if _schema_table_id(target, schema_index) != target:
        raise SemanticMappingError(f"{hkb_id} target must be a table")
    if mapping["representation"] not in REPRESENTATIONS - {"field_context"}:
        raise SemanticMappingError(f"{hkb_id} has invalid compile representation")
    _require_text(mapping["semantic_name"], f"{hkb_id} semantic name")
    if mapping["dependency_mode"] != "same_grain":
        raise SemanticMappingError(
            f"{hkb_id} compile dependency mode must be same_grain"
        )
    if mapping["relationship_requirements"]:
        raise SemanticMappingError(f"{hkb_id} compile mapping has relationship gaps")
    if not schema_ids and not dependencies:
        raise SemanticMappingError(f"{hkb_id} compile mapping has no inputs")
    if any(_schema_table_id(item, schema_index) != target for item in schema_ids):
        raise SemanticMappingError(f"{hkb_id} has an input outside target table")
    for dependency in dependencies:
        dependency_mapping = mapping_index[dependency]
        if dependency_mapping.get("disposition") != "compile":
            raise SemanticMappingError(f"{hkb_id} has a non-compiled dependency")
        if dependency_mapping.get("target_table_stable_id") != target:
            raise SemanticMappingError(f"{hkb_id} dependency is outside target table")


def _validate_non_compile(
    mapping: Mapping[str, Any],
    schema_ids: list[str],
    schema_index: Mapping[str, Mapping[str, Any]],
) -> None:
    hkb_id = mapping["hkb_stable_id"]
    disposition = mapping["disposition"]
    if mapping["semantic_name"] is not None:
        raise SemanticMappingError(f"{hkb_id} non-compile semantic name must be null")
    if disposition == "context_only":
        target = _require_text(mapping["target_table_stable_id"], f"{hkb_id} target")
        if (
            len(schema_ids) != 1
            or _schema_table_id(schema_ids[0], schema_index) != target
        ):
            raise SemanticMappingError(
                f"{hkb_id} context mapping must target one field"
            )
        if mapping["representation"] != "field_context":
            raise SemanticMappingError(f"{hkb_id} context representation is invalid")
        if mapping["dependency_mode"] != "none":
            raise SemanticMappingError(f"{hkb_id} context dependency mode must be none")
        if mapping["relationship_requirements"]:
            raise SemanticMappingError(
                f"{hkb_id} context mapping has relationship gaps"
            )
        if "context_only_no_executable_object" not in mapping["loss_codes"]:
            raise SemanticMappingError(f"{hkb_id} lacks explicit non-executable loss")
        return
    if (
        mapping["target_table_stable_id"] is not None
        or mapping["representation"] is not None
    ):
        raise SemanticMappingError(f"{hkb_id} deferred representation must be null")
    expected_mode = (
        "cross_grain_unresolved" if disposition == "defer_cross_grain" else "blocked"
    )
    if mapping["dependency_mode"] != expected_mode:
        raise SemanticMappingError(
            f"{hkb_id} has invalid {disposition} dependency mode"
        )
    if disposition == "unsupported" and not mapping["loss_codes"]:
        raise SemanticMappingError(f"{hkb_id} lacks explicit non-executable loss")
    if disposition == "defer_cross_grain":
        _require_cross_grain_requirements(mapping, hkb_id)


def _validate_mapping(
    mapping: Mapping[str, Any],
    hkb: Mapping[str, Any],
    hkb_index: Mapping[str, Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
    mapping_index: Mapping[str, Mapping[str, Any]],
) -> None:
    disposition = mapping.get("disposition")
    if disposition not in DISPOSITIONS:
        raise SemanticMappingError(
            f"{mapping.get('hkb_stable_id')} disposition is invalid"
        )
    schema_ids, dependencies = _validate_common_mapping(
        mapping, hkb, hkb_index, schema_index
    )
    if disposition == "compile":
        _validate_compile(
            mapping, schema_ids, dependencies, schema_index, mapping_index
        )
    else:
        _validate_non_compile(mapping, schema_ids, schema_index)


def _hkb_by_numeric_id(
    hkb_records: Sequence[Mapping[str, Any]], database: str
) -> dict[int, Mapping[str, Any]]:
    indexed: dict[int, Mapping[str, Any]] = {}
    for hkb in hkb_records:
        hkb_id = _require_non_negative_int(hkb.get("hkb_id"), "HKB ID")
        if hkb.get("database") != database:
            raise SemanticMappingError(f"HKB {hkb_id} database mismatch")
        if hkb.get("stable_id") != f"{database}:hkb:{hkb_id}":
            raise SemanticMappingError(f"HKB stable ID namespace mismatch for {hkb_id}")
        if hkb_id in indexed:
            raise SemanticMappingError(f"duplicate HKB numeric ID {hkb_id}")
        indexed[hkb_id] = hkb
    return indexed


def _validate_schema_namespace(
    schema_records: Sequence[Mapping[str, Any]], database: str
) -> None:
    prefix = f"{database}:"
    for record in schema_records:
        stable_id = _require_text(record.get("stable_id"), "schema stable ID")
        if record.get("database") != database:
            raise SemanticMappingError(f"{stable_id} schema database mismatch")
        if not stable_id.startswith(prefix):
            raise SemanticMappingError(
                f"{stable_id} schema stable ID namespace mismatch"
            )


def compile_mapping_spec(
    spec: Mapping[str, Any],
    hkb_records: Sequence[Mapping[str, Any]],
    schema_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Mechanically expand a reviewed public-only mapping specification."""
    _require_exact_fields(spec, SPEC_FIELDS, "mapping spec")
    if spec["schema_version"] != 1 or isinstance(spec["schema_version"], bool):
        raise SemanticMappingError("mapping spec schema_version must equal 1")
    database = _require_text(spec["database"], "mapping spec database")
    aliases = _schema_aliases(spec["schema_aliases"])
    records = spec["records"]
    if not isinstance(records, list):
        raise SemanticMappingError("mapping spec records must be a list")
    hkb_by_id = _hkb_by_numeric_id(hkb_records, database)
    _validate_schema_namespace(schema_records, database)
    compiled: list[dict[str, Any]] = []
    for index, spec_record in enumerate(records):
        if not isinstance(spec_record, dict):
            raise SemanticMappingError(f"mapping spec record {index} is invalid")
        numeric_id = _require_non_negative_int(spec_record.get("hkb_id"), "HKB ID")
        hkb = hkb_by_id.get(numeric_id)
        if hkb is None:
            raise SemanticMappingError(
                f"mapping spec references unknown HKB ID {numeric_id}"
            )
        compiled.append(_compile_spec_record(spec_record, database, aliases, hkb))
    compiled.sort(key=lambda item: int(item["hkb_stable_id"].rsplit(":", 1)[1]))
    validate_mapping_records(hkb_records, schema_records, compiled)
    return compiled


def encode_mapping_jsonl(records: Sequence[Mapping[str, Any]]) -> bytes:
    """Encode validated mapping records as canonical row-separated JSON."""
    lines = [
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        for record in records
    ]
    return ("\n".join(lines) + "\n").encode()


def validate_mapping_records(
    hkb_records: Sequence[Mapping[str, Any]],
    schema_records: Sequence[Mapping[str, Any]],
    mapping_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate complete public-only mapping decisions and return exact counts."""
    hkb_index = _index_records(hkb_records, "HKB")
    schema_index = _index_records(schema_records, "schema")
    mapping_index: dict[str, Mapping[str, Any]] = {}
    for mapping in mapping_records:
        hkb_id = _require_text(mapping.get("hkb_stable_id"), "mapping HKB stable ID")
        if hkb_id in mapping_index:
            raise SemanticMappingError(f"duplicate mapping for {hkb_id}")
        mapping_index[hkb_id] = mapping
    missing = sorted(hkb_index.keys() - mapping_index.keys())
    extra = sorted(mapping_index.keys() - hkb_index.keys())
    if missing:
        raise SemanticMappingError(f"missing HKB mappings: {', '.join(missing)}")
    if extra:
        raise SemanticMappingError(
            f"mappings reference unknown HKB IDs: {', '.join(extra)}"
        )
    for hkb_id in sorted(hkb_index):
        _validate_mapping(
            mapping_index[hkb_id],
            hkb_index[hkb_id],
            hkb_index,
            schema_index,
            mapping_index,
        )
    dispositions = Counter(item["disposition"] for item in mapping_records)
    representations = Counter(
        item["representation"]
        for item in mapping_records
        if item["representation"] is not None
    )
    databases = {item.get("database") for item in hkb_records}
    if len(databases) != 1:
        raise SemanticMappingError("HKB records must belong to one database")
    return {
        "database": databases.pop(),
        "dispositions": dict(sorted(dispositions.items())),
        "hkb_nodes": len(hkb_index),
        "representations": dict(sorted(representations.items())),
    }

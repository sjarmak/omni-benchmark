"""Compile an audited public semantic mapping into Omni extension files."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import sqlglot
from sqlglot import expressions as exp
import yaml

from .semantic_mapping import SemanticMappingError, validate_mapping_records


class SemanticBundleError(ValueError):
    """Raised when a semantic bundle cannot be compiled safely."""


@dataclass(frozen=True)
class SemanticBundle:
    """Deterministic Omni files and their public-only provenance manifest."""

    files: dict[str, str]
    manifest: dict[str, Any]


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FIELD_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PROTECTED_KEYS = frozenset(
    {
        "external_knowledge",
        "expected_result",
        "gold_sql",
        "gold_result",
        "oracle_hint",
        "oracle_sql",
        "sol_sql",
        "test_correctness",
        "test_cases",
        "test_case",
    }
)
_SPEC_KEYS = frozenset(
    {
        "catalog",
        "database",
        "derived_fields",
        "format_version",
        "physical_fields",
        "schema",
        "views",
    }
)
_VIEW_KEYS = frozenset(
    {
        "description",
        "file_name",
        "label",
        "table_stable_id",
        "topic_file_name",
        "view_name",
    }
)
_PHYSICAL_FIELD_KEYS = frozenset({"label", "name", "schema_stable_id", "sql"})
_DERIVED_FIELD_KEYS = frozenset({"hkb_stable_id", "sql"})


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SemanticBundleError(f"{label} must be an object")
    return value


def _items(value: Any, label: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise SemanticBundleError(f"{label} must be a list")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticBundleError(f"{label} must be non-empty text")
    return value


def _safe_name(value: Any, label: str) -> str:
    name = _text(value, label)
    if not _NAME.fullmatch(name):
        raise SemanticBundleError(f"{label} must be a safe identifier")
    return name


def _safe_file_name(value: Any, label: str, suffix: str) -> str:
    name = _text(value, label)
    if "/" in name or "\\" in name or "\x00" in name or not name.endswith(suffix):
        raise SemanticBundleError(
            f"{label} must be one safe file name ending in {suffix}"
        )
    if name in {f".{suffix}", f"..{suffix}"} or name.startswith("."):
        raise SemanticBundleError(
            f"{label} must be one safe file name ending in {suffix}"
        )
    return name


_FIELD_SENTINEL = "__omni_modeled_field_reference__"


def reject_protected_fields(value: Any) -> None:
    """Reject hidden benchmark fields recursively before interpreting input."""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _PROTECTED_KEYS:
                raise SemanticBundleError(f"protected field {key} is not allowed")
            reject_protected_fields(item)
    elif isinstance(value, list):
        for item in value:
            reject_protected_fields(item)


def _exact_keys(value: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SemanticBundleError(
            f"{label} has unsupported fields: {', '.join(unknown)}"
        )


def _index(
    records: Sequence[Mapping[str, Any]], key: str, label: str
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        stable_id = _text(record.get(key), f"{label} {key}")
        if stable_id in indexed:
            raise SemanticBundleError(f"duplicate {label} {stable_id}")
        indexed[stable_id] = record
    return indexed


def _validate_database(
    records: Sequence[Mapping[str, Any]], database: str, label: str
) -> None:
    if any(record.get("database") != database for record in records):
        raise SemanticBundleError(f"{label} database does not match bundle")


def _validated_views(
    spec: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    views: dict[str, Mapping[str, Any]] = {}
    output_names: set[str] = set()
    for raw in _items(spec.get("views"), "views"):
        view = _mapping(raw, "view")
        _exact_keys(view, _VIEW_KEYS, "view")
        table_id = _text(view.get("table_stable_id"), "view table_stable_id")
        if table_id in views:
            raise SemanticBundleError(f"duplicate view table {table_id}")
        _safe_name(view.get("view_name"), "view_name")
        names = {
            _safe_file_name(view.get("file_name"), "view file_name", ".view"),
            _safe_file_name(view.get("topic_file_name"), "topic file_name", ".topic"),
        }
        if output_names.intersection(names):
            raise SemanticBundleError("bundle output file names must be unique")
        output_names.update(names)
        views[table_id] = view
    if not views:
        raise SemanticBundleError("views must not be empty")
    return views


def _schema_table_for(
    record: Mapping[str, Any], schema_index: Mapping[str, Mapping[str, Any]]
) -> str:
    kind = record.get("record_kind")
    if kind == "column":
        return _text(record.get("table_stable_id"), "column table_stable_id")
    if kind == "structured_leaf":
        column_id = _text(record.get("column_stable_id"), "leaf column_stable_id")
        column = schema_index.get(column_id)
        if column is None:
            raise SemanticBundleError(f"structured leaf column {column_id} is missing")
        return _text(column.get("table_stable_id"), "column table_stable_id")
    raise SemanticBundleError(
        "physical field source must be a column or structured leaf"
    )


def _validated_physical_fields(
    spec: Mapping[str, Any],
    schema_index: Mapping[str, Mapping[str, Any]],
    views: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, list[Mapping[str, Any]]]]:
    by_schema_id: dict[str, Mapping[str, Any]] = {}
    by_table: dict[str, list[Mapping[str, Any]]] = {table: [] for table in views}
    for raw in _items(spec.get("physical_fields"), "physical_fields"):
        field = _mapping(raw, "physical field")
        _exact_keys(field, _PHYSICAL_FIELD_KEYS, "physical field")
        schema_id = _text(field.get("schema_stable_id"), "schema_stable_id")
        if schema_id in by_schema_id:
            raise SemanticBundleError(f"duplicate physical field source {schema_id}")
        source = schema_index.get(schema_id)
        if source is None:
            raise SemanticBundleError(f"physical field source {schema_id} is missing")
        table_id = _schema_table_for(source, schema_index)
        if table_id not in views:
            raise SemanticBundleError(f"physical field table {table_id} has no view")
        _safe_name(field.get("name"), "physical field name")
        by_schema_id[schema_id] = field
        by_table[table_id].append(field)
    return by_schema_id, by_table


def _compile_mappings(
    mapping_records: Sequence[Mapping[str, Any]], disposition: str
) -> dict[str, Mapping[str, Any]]:
    selected = [
        record for record in mapping_records if record.get("disposition") == disposition
    ]
    return _index(selected, "hkb_stable_id", f"{disposition} mapping")


def _validated_derived_fields(
    spec: Mapping[str, Any], compile_mappings: Mapping[str, Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    derived: dict[str, Mapping[str, Any]] = {}
    for raw in _items(spec.get("derived_fields"), "derived_fields"):
        field = _mapping(raw, "derived field")
        _exact_keys(field, _DERIVED_FIELD_KEYS, "derived field")
        hkb_id = _text(field.get("hkb_stable_id"), "derived hkb_stable_id")
        if hkb_id in derived:
            raise SemanticBundleError(f"duplicate derived field {hkb_id}")
        _text(field.get("sql"), "derived field sql")
        derived[hkb_id] = field
    if set(derived) != set(compile_mappings):
        raise SemanticBundleError(
            "compile mappings and derived fields must match exactly"
        )
    return derived


def _compile_names(
    compile_mappings: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    names: dict[str, str] = {}
    for hkb_id, mapping in compile_mappings.items():
        name = _safe_name(mapping.get("semantic_name"), "semantic_name")
        if name in names:
            raise SemanticBundleError(f"duplicate compiled semantic name {name}")
        names[name] = hkb_id
    return names


def _declared_dependency_names(
    mapping: Mapping[str, Any],
    compile_mappings: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    audit = _mapping(mapping.get("dependency_audit"), "dependency audit")
    redundant = set(
        _text(item, "redundant dependency")
        for item in _items(audit.get("redundant_references"), "redundant dependencies")
    )
    dependency_ids = {
        _text(item, "mapping dependency")
        for item in _items(
            mapping.get("dependency_hkb_stable_ids"), "mapping dependencies"
        )
    } - redundant
    return {
        _safe_name(compile_mappings[item].get("semantic_name"), "semantic_name")
        for item in dependency_ids
    }


def _validate_derived_dependencies(
    compile_mappings: Mapping[str, Mapping[str, Any]],
    derived: Mapping[str, Mapping[str, Any]],
) -> None:
    names = _compile_names(compile_mappings)
    for hkb_id, mapping in compile_mappings.items():
        table_id = mapping.get("target_table_stable_id")
        table_names = {
            name
            for name, dependency_id in names.items()
            if compile_mappings[dependency_id].get("target_table_stable_id") == table_id
        }
        sql = _text(derived[hkb_id].get("sql"), "derived field sql")
        actual = set(_field_references(sql)).intersection(table_names)
        expected = _declared_dependency_names(mapping, compile_mappings)
        missing = sorted(expected - actual)
        undeclared = sorted(actual - expected)
        if missing:
            raise SemanticBundleError(
                f"derived field {hkb_id} is missing declared dependency reference "
                f"{', '.join(missing)}"
            )
        if undeclared:
            raise SemanticBundleError(
                f"derived field {hkb_id} has undeclared derived dependency "
                f"{', '.join(undeclared)}"
            )


def _column_names_by_table(
    schema_records: Sequence[Mapping[str, Any]],
) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {}
    for record in schema_records:
        if record.get("record_kind") != "column":
            continue
        table_id = _text(record.get("table_stable_id"), "column table_stable_id")
        identifier = _mapping(record.get("identifier"), "column identifier")
        name = _safe_name(identifier.get("name"), "column name")
        names.setdefault(table_id, set()).add(name)
    return names


def _field_references(sql: str) -> list[str]:
    references = _FIELD_REFERENCE.findall(sql)
    if "${" in _FIELD_REFERENCE.sub("", sql):
        raise SemanticBundleError("SQL contains an invalid field reference")
    return references


def _validate_sql(sql: str, allowed_fields: set[str]) -> None:
    references = _field_references(sql)
    for reference in sorted(set(references)):
        if reference not in allowed_fields:
            raise SemanticBundleError(f"unknown field reference {reference}")
    if _FIELD_SENTINEL in sql.lower():
        raise SemanticBundleError("field SQL contains a reserved identifier")
    parseable = _FIELD_REFERENCE.sub(
        lambda match: f"{_FIELD_SENTINEL}('{match.group(1)}')", sql
    )
    try:
        statements = sqlglot.parse(f"SELECT {parseable}", read="postgres")
    except sqlglot.errors.ParseError as error:
        raise SemanticBundleError("field SQL is not valid PostgreSQL syntax") from error
    if not _is_modeled_scalar(statements, references):
        raise SemanticBundleError("field SQL must be one modeled scalar expression")


def _is_modeled_scalar(
    statements: Sequence[exp.Expression | None], references: Sequence[str]
) -> bool:
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return False
    statement = statements[0]
    if len(statement.expressions) != 1:
        return False
    if any(
        value is not None
        for key, value in statement.args.items()
        if key != "expressions"
    ):
        return False
    if any(
        node is not statement and isinstance(node, exp.Query)
        for node in statement.walk()
    ):
        return False
    forbidden_nodes = (
        exp.AggFunc,
        exp.Alias,
        exp.Column,
        exp.Star,
        exp.Subquery,
        exp.Table,
        exp.Window,
    )
    if any(isinstance(node, forbidden_nodes) for node in statement.walk()):
        return False
    sentinels = [node for node in statement.find_all(exp.Anonymous)]
    if any(node.name.lower() != _FIELD_SENTINEL for node in sentinels):
        return False
    sentinel_names: list[str] = []
    for node in sentinels:
        if len(node.expressions) != 1 or not isinstance(
            node.expressions[0], exp.Literal
        ):
            return False
        literal = node.expressions[0]
        if not literal.is_string:
            return False
        sentinel_names.append(str(literal.this))
    return Counter(sentinel_names) == Counter(references)


def _ordered_compile_ids(
    compile_mappings: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    ordered: list[str] = []
    visiting: set[str] = set()

    def visit(hkb_id: str) -> None:
        if hkb_id in visiting:
            raise SemanticBundleError("compile mapping dependency cycle")
        if hkb_id in ordered:
            return
        visiting.add(hkb_id)
        dependencies = _items(
            compile_mappings[hkb_id].get("dependency_hkb_stable_ids"),
            "mapping dependencies",
        )
        for dependency in dependencies:
            dependency_id = _text(dependency, "mapping dependency")
            if dependency_id not in compile_mappings:
                raise SemanticBundleError(
                    f"compile dependency {dependency_id} is missing"
                )
            visit(dependency_id)
        visiting.remove(hkb_id)
        ordered.append(hkb_id)

    for hkb_id in sorted(compile_mappings):
        visit(hkb_id)
    return ordered


def _source_description(record: Mapping[str, Any]) -> str:
    return _text(record.get("description"), "schema source description")


def _context_by_schema_id(
    context_mappings: Mapping[str, Mapping[str, Any]],
    hkb_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, list[str]]:
    contexts: dict[str, list[str]] = {}
    for hkb_id, mapping in sorted(context_mappings.items()):
        bindings = _items(mapping.get("source_bindings"), "context bindings")
        if len(bindings) != 1:
            raise SemanticBundleError(f"context mapping {hkb_id} must have one binding")
        binding = _mapping(bindings[0], "context binding")
        schema_id = _text(binding.get("schema_stable_id"), "context schema_stable_id")
        hkb = hkb_index.get(hkb_id)
        if hkb is None:
            raise SemanticBundleError(f"HKB record {hkb_id} is missing")
        title = _text(hkb.get("knowledge"), "HKB knowledge")
        definition = _text(hkb.get("definition"), "HKB definition")
        contexts.setdefault(schema_id, []).append(f"{title}: {definition}")
    return contexts


def _physical_dimension(
    field: Mapping[str, Any], source: Mapping[str, Any], contexts: Sequence[str]
) -> dict[str, Any]:
    dimension: dict[str, Any] = {"description": _source_description(source)}
    if "label" in field:
        dimension["label"] = _text(field.get("label"), "physical field label")
    if "sql" in field:
        dimension["sql"] = _text(field.get("sql"), "physical field sql")
    if contexts:
        dimension["ai_context"] = "\n".join(contexts)
    return dimension


def _derived_dimension(
    definition: Mapping[str, Any], hkb: Mapping[str, Any], mapping: Mapping[str, Any]
) -> dict[str, Any]:
    representation = mapping.get("representation")
    supported = {
        "boolean_derived_dimension",
        "categorical_derived_dimension",
        "numeric_derived_dimension",
    }
    if representation not in supported:
        raise SemanticBundleError(
            f"unsupported compiled representation {representation}"
        )
    label = _text(hkb.get("knowledge"), "HKB knowledge")
    return {
        "label": label,
        "description": _text(hkb.get("description"), "HKB description"),
        "sql": _text(definition.get("sql"), "derived field sql"),
        "ai_context": f"Use this modeled field for {label}; do not reconstruct its formula.",
    }


def _table_name(table: Mapping[str, Any]) -> str:
    identifier = _mapping(table.get("identifier"), "table identifier")
    return _text(identifier.get("name"), "table name")


def _view_document(
    view: Mapping[str, Any],
    table: Mapping[str, Any],
    dimensions: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "label": _text(view.get("label"), "view label"),
        "description": _text(view.get("description"), "view description"),
        "catalog": _text(spec.get("catalog"), "catalog"),
        "schema": _text(spec.get("schema"), "schema"),
        "table_name": _table_name(table),
        "dimensions": dimensions,
    }


def _topic_document(
    view: Mapping[str, Any], modeled_fields: Sequence[str]
) -> dict[str, Any]:
    view_name = _safe_name(view.get("view_name"), "view_name")
    field_names = ", ".join(modeled_fields)
    return {
        "base_view": view_name,
        "label": _text(view.get("label"), "topic label"),
        "description": _text(view.get("description"), "topic description"),
        "fields": [f"{view_name}.*"],
        "ai_context": (
            f"Use the modeled business fields {field_names} rather than reconstructing "
            "their definitions. This topic intentionally models no cross-table joins."
        ),
    }


def _yaml(document: Mapping[str, Any]) -> str:
    return yaml.safe_dump(
        dict(document), allow_unicode=True, sort_keys=False, width=1000
    )


def _content_provenance(mapping: Mapping[str, Any]) -> list[str]:
    provenance = _mapping(mapping.get("provenance"), "mapping provenance")
    content = provenance.get("content")
    return sorted(
        _text(item, "content provenance")
        for item in _items(content, "content provenance")
    )


def _intervention_provenance(mapping: Mapping[str, Any]) -> str:
    provenance = _mapping(mapping.get("provenance"), "mapping provenance")
    value = provenance.get("intervention")
    return _text(value, "intervention provenance")


def _semantic_element(
    mapping: Mapping[str, Any], hkb_id: str, semantic_name: str, kind: str
) -> dict[str, Any]:
    loss_codes = mapping.get("loss_codes")
    return {
        "content_provenance": _content_provenance(mapping),
        "hkb_stable_id": hkb_id,
        "intervention_provenance": _intervention_provenance(mapping),
        "kind": kind,
        "loss_codes": sorted(
            _text(item, "mapping loss code")
            for item in _items(loss_codes, "mapping loss codes")
        ),
        "semantic_name": semantic_name,
        "table_stable_id": _text(
            mapping.get("target_table_stable_id"), "mapping target table"
        ),
    }


def _file_manifest(files: Mapping[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "file": name,
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "size_bytes": len(content.encode()),
        }
        for name, content in files.items()
    ]


def compile_semantic_bundle(
    spec: Mapping[str, Any],
    hkb_records: Sequence[Mapping[str, Any]],
    schema_records: Sequence[Mapping[str, Any]],
    mapping_records: Sequence[Mapping[str, Any]],
) -> SemanticBundle:
    """Compile public records into deterministic, no-join Omni extensions."""
    hkb_index, schema_index = _validated_bundle_inputs(
        spec, hkb_records, schema_records, mapping_records
    )
    views = _validated_views(spec)
    compile_mappings = _compile_mappings(mapping_records, "compile")
    _require_compile_views(compile_mappings, views)
    context_mappings = _compile_mappings(mapping_records, "context_only")
    derived = _validated_derived_fields(spec, compile_mappings)
    _validate_derived_dependencies(compile_mappings, derived)
    physical, physical_by_table = _validated_physical_fields(spec, schema_index, views)
    contexts = _context_by_schema_id(context_mappings, hkb_index)
    for schema_id in contexts:
        if schema_id not in physical:
            raise SemanticBundleError(
                f"context target {schema_id} has no physical field"
            )
    return _build_bundle(
        spec,
        hkb_index,
        schema_index,
        schema_records,
        views,
        compile_mappings,
        context_mappings,
        derived,
        physical_by_table,
        contexts,
    )


def _validated_bundle_inputs(
    spec: Mapping[str, Any],
    hkb_records: Sequence[Mapping[str, Any]],
    schema_records: Sequence[Mapping[str, Any]],
    mapping_records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    for value in (spec, hkb_records, schema_records, mapping_records):
        reject_protected_fields(value)
    _exact_keys(spec, _SPEC_KEYS, "bundle specification")
    if spec.get("format_version") != 1:
        raise SemanticBundleError("unsupported bundle format_version")
    database = _text(spec.get("database"), "database")
    for records, label in (
        (hkb_records, "HKB records"),
        (schema_records, "schema records"),
        (mapping_records, "mapping records"),
    ):
        _validate_database(records, database, label)
    try:
        validate_mapping_records(hkb_records, schema_records, mapping_records)
    except SemanticMappingError as error:
        raise SemanticBundleError(
            f"semantic mapping contract invalid: {error}"
        ) from error
    hkb_index = _index(hkb_records, "stable_id", "HKB record")
    schema_index = _index(schema_records, "stable_id", "schema record")
    return hkb_index, schema_index


def _require_compile_views(
    compile_mappings: Mapping[str, Mapping[str, Any]],
    views: Mapping[str, Mapping[str, Any]],
) -> None:
    missing = sorted(
        {
            _text(mapping.get("target_table_stable_id"), "mapping target table")
            for mapping in compile_mappings.values()
            if mapping.get("target_table_stable_id") not in views
        }
    )
    if missing:
        raise SemanticBundleError(
            f"compile mapping target {', '.join(missing)} has no view"
        )


def _build_bundle(
    spec: Mapping[str, Any],
    hkb_index: Mapping[str, Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
    schema_records: Sequence[Mapping[str, Any]],
    views: Mapping[str, Mapping[str, Any]],
    compile_mappings: Mapping[str, Mapping[str, Any]],
    context_mappings: Mapping[str, Mapping[str, Any]],
    derived: Mapping[str, Mapping[str, Any]],
    physical_by_table: Mapping[str, list[Mapping[str, Any]]],
    contexts: Mapping[str, list[str]],
) -> SemanticBundle:
    column_names = _column_names_by_table(schema_records)
    ordered_ids = _ordered_compile_ids(compile_mappings)
    files: dict[str, str] = {}
    elements: list[dict[str, Any]] = []
    for table_id, view in views.items():
        table = schema_index.get(table_id)
        if table is None or table.get("record_kind") != "table":
            raise SemanticBundleError(f"view table {table_id} is missing")
        dimensions, names = _table_dimensions(
            table_id,
            hkb_index,
            schema_index,
            compile_mappings,
            context_mappings,
            derived,
            physical_by_table,
            contexts,
            column_names.get(table_id, set()),
            ordered_ids,
            elements,
        )
        view_file = _text(view.get("file_name"), "view file_name")
        topic_file = _text(view.get("topic_file_name"), "topic file_name")
        files[view_file] = _yaml(_view_document(view, table, dimensions, spec))
        files[topic_file] = _yaml(_topic_document(view, names))
    return SemanticBundle(
        files=files,
        manifest=_bundle_manifest(spec, files, elements, compile_mappings),
    )


def _bundle_manifest(
    spec: Mapping[str, Any],
    files: Mapping[str, str],
    elements: Sequence[Mapping[str, Any]],
    compile_mappings: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    materialized = {
        item["hkb_stable_id"]
        for item in elements
        if item["kind"] == "derived_dimension"
    }
    if materialized != set(compile_mappings):
        raise SemanticBundleError("not all compile mappings were materialized")
    return {
        "database": _text(spec.get("database"), "database"),
        "files": _file_manifest(files),
        "kind": "public-omni-semantic-bundle",
        "schema_version": 1,
        "semantic_elements": sorted(
            elements, key=lambda item: (item["hkb_stable_id"], item["kind"])
        ),
        "validation": {
            "all_compile_mappings_materialized": True,
            "hidden_annotations_used": False,
            "joins_generated": False,
            "public_inputs_only": True,
            "status": "passed",
        },
    }


def _table_dimensions(
    table_id: str,
    hkb_index: Mapping[str, Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
    compile_mappings: Mapping[str, Mapping[str, Any]],
    context_mappings: Mapping[str, Mapping[str, Any]],
    derived: Mapping[str, Mapping[str, Any]],
    physical_by_table: Mapping[str, list[Mapping[str, Any]]],
    contexts: Mapping[str, list[str]],
    base_names: set[str],
    ordered_ids: Sequence[str],
    elements: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    dimensions: dict[str, Any] = {}
    allowed = set(base_names)
    for field in physical_by_table[table_id]:
        schema_id = _text(field.get("schema_stable_id"), "schema_stable_id")
        name = _safe_name(field.get("name"), "physical field name")
        if name in dimensions:
            raise SemanticBundleError(f"duplicate field name {name} in {table_id}")
        if "sql" in field:
            _validate_sql(_text(field.get("sql"), "physical field sql"), allowed)
        dimensions[name] = _physical_dimension(
            field, schema_index[schema_id], contexts.get(schema_id, [])
        )
        allowed.add(name)
        for hkb_id, mapping in context_mappings.items():
            bindings = _items(mapping.get("source_bindings"), "context bindings")
            target = _mapping(bindings[0], "context binding").get("schema_stable_id")
            if target == schema_id:
                elements.append(
                    _semantic_element(mapping, hkb_id, name, "field_context")
                )
    for hkb_id in ordered_ids:
        mapping = compile_mappings[hkb_id]
        if mapping.get("target_table_stable_id") != table_id:
            continue
        name = _safe_name(mapping.get("semantic_name"), "semantic_name")
        if name in dimensions:
            raise SemanticBundleError(f"duplicate field name {name} in {table_id}")
        sql = _text(derived[hkb_id].get("sql"), "derived field sql")
        _validate_sql(sql, allowed)
        hkb = hkb_index.get(hkb_id)
        if hkb is None:
            raise SemanticBundleError(f"HKB record {hkb_id} is missing")
        dimensions[name] = _derived_dimension(derived[hkb_id], hkb, mapping)
        allowed.add(name)
        elements.append(_semantic_element(mapping, hkb_id, name, "derived_dimension"))
    return dimensions, list(dimensions)

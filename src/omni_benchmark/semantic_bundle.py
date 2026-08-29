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

from .protected_fields import ProtectedFieldError
from .protected_fields import reject_protected_fields as _reject_protected_fields
from .semantic_mapping import SemanticMappingError, validate_mapping_records
from .semantic_relationships import plan_relationship_contracts


class SemanticBundleError(ValueError):
    """Raised when a semantic bundle cannot be compiled safely."""


@dataclass(frozen=True)
class SemanticBundle:
    """Deterministic Omni files and their public-only provenance manifest."""

    files: dict[str, str]
    manifest: dict[str, Any]


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FIELD_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
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
_PHYSICAL_FIELD_KEYS = frozenset(
    {"label", "name", "omni_parser_mode", "schema_stable_id", "sql"}
)
_DERIVED_FIELD_KEYS = frozenset({"hkb_stable_id", "sql"})
_DO_NOT_PARSE_DIRECTIVE = "-- DO NOT PARSE"


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


def _omni_name(value: Any, label: str) -> str:
    name = _safe_name(value, label)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


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
    try:
        _reject_protected_fields(value)
    except ProtectedFieldError as error:
        raise SemanticBundleError(str(error)) from error


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
        if "omni_parser_mode" in field:
            if field.get("omni_parser_mode") != "do_not_parse":
                raise SemanticBundleError(
                    "omni_parser_mode must be exactly do_not_parse"
                )
            if "sql" not in field:
                raise SemanticBundleError(
                    "omni_parser_mode requires physical field sql"
                )
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


def _column_bindings_by_table(
    schema_records: Sequence[Mapping[str, Any]],
    modeled_table_ids: frozenset[str],
) -> dict[str, dict[str, tuple[str, ...]]]:
    collected: dict[str, dict[str, list[str]]] = {}
    for record in schema_records:
        if record.get("record_kind") != "column":
            continue
        table_id = _text(record.get("table_stable_id"), "column table_stable_id")
        if table_id not in modeled_table_ids:
            continue
        identifier = _mapping(record.get("identifier"), "column identifier")
        name = _omni_name(identifier.get("name"), "column name")
        stable_id = _text(record.get("stable_id"), "column stable_id")
        table_bindings = collected.setdefault(table_id, {})
        table_bindings.setdefault(name, []).append(stable_id)
    return {
        table_id: {
            name: tuple(sorted(stable_ids))
            for name, stable_ids in table_bindings.items()
        }
        for table_id, table_bindings in collected.items()
    }


def _source_name_collisions(
    bindings_by_table: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> list[dict[str, Any]]:
    return [
        {
            "omni_field_name": name,
            "source_stable_ids": list(stable_ids),
            "table_stable_id": table_id,
        }
        for table_id, bindings in sorted(bindings_by_table.items())
        for name, stable_ids in sorted(bindings.items())
        if len(stable_ids) > 1
    ]


def _source_column(
    source: Mapping[str, Any], schema_index: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any]:
    if source.get("record_kind") == "column":
        return source
    column_id = _text(source.get("column_stable_id"), "leaf column_stable_id")
    column = schema_index.get(column_id)
    if column is None or column.get("record_kind") != "column":
        raise SemanticBundleError(f"structured leaf column {column_id} is missing")
    return column


def _source_column_name(
    source: Mapping[str, Any], schema_index: Mapping[str, Mapping[str, Any]]
) -> tuple[str, str]:
    column = _source_column(source, schema_index)
    identifier = _mapping(column.get("identifier"), "column identifier")
    raw_name = _safe_name(identifier.get("name"), "column name")
    return raw_name, _omni_name(raw_name, "column name")


def _source_column_sql(
    source: Mapping[str, Any], schema_index: Mapping[str, Mapping[str, Any]]
) -> str:
    column = _source_column(source, schema_index)
    identifier = _mapping(column.get("identifier"), "column identifier")
    name = _safe_name(identifier.get("name"), "column name")
    quoted = identifier.get("quoted", False)
    if type(quoted) is not bool:
        raise SemanticBundleError("column quoted flag must be boolean")
    return f'"{name}"' if quoted else name


def _structured_leaf_sql(
    source: Mapping[str, Any], schema_index: Mapping[str, Mapping[str, Any]]
) -> str:
    if source.get("record_kind") != "structured_leaf":
        raise SemanticBundleError("structured leaf SQL requires a structured leaf")
    _, source_name = _source_column_name(source, schema_index)
    path = _items(source.get("path"), "structured leaf path")
    if not path:
        raise SemanticBundleError("structured leaf path must not be empty")
    sql = f"${{{source_name}}}"
    for position, raw_segment in enumerate(path):
        segment = _mapping(raw_segment, "structured leaf path segment")
        operator = "->>" if position == len(path) - 1 else "->"
        kind = segment.get("kind")
        if kind == "object_key":
            if not set(segment) <= {"key", "kind", "ordinal"}:
                raise SemanticBundleError("structured object path segment is malformed")
            key = _text(segment.get("key"), "structured leaf object key")
            quoted_key = key.replace("'", "''")
            sql += f" {operator} '{quoted_key}'"
        elif kind == "array_index":
            if set(segment) != {"index", "kind"}:
                raise SemanticBundleError("structured array path segment is malformed")
            index = segment.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise SemanticBundleError("structured leaf array index is invalid")
            sql += f" {operator} {index}"
        else:
            raise SemanticBundleError("structured leaf path kind is invalid")
    return sql


def _rewrite_field_references(sql: str, names: Mapping[str, str]) -> str:
    return _FIELD_REFERENCE.sub(
        lambda match: f"${{{names.get(match.group(1), match.group(1))}}}", sql
    )


def _field_references(sql: str) -> list[str]:
    references = _FIELD_REFERENCE.findall(sql)
    if "${" in _FIELD_REFERENCE.sub("", sql):
        raise SemanticBundleError("SQL contains an invalid field reference")
    return references


def _validate_sql(sql: str, allowed_fields: set[str]) -> None:
    if _DO_NOT_PARSE_DIRECTIVE.lower() in sql.lower():
        raise SemanticBundleError("reserved Omni parser directive in field SQL")
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
    field: Mapping[str, Any],
    source: Mapping[str, Any],
    contexts: Sequence[str],
    sql: str | None,
) -> dict[str, Any]:
    dimension: dict[str, Any] = {"description": _source_description(source)}
    if "label" in field:
        dimension["label"] = _text(field.get("label"), "physical field label")
    if sql is not None:
        if field.get("omni_parser_mode") == "do_not_parse":
            sql = f"{_DO_NOT_PARSE_DIRECTIVE}\n{sql}"
        dimension["sql"] = sql
    if contexts:
        dimension["ai_context"] = "\n".join(contexts)
    return dimension


def _derived_dimension(
    hkb: Mapping[str, Any], mapping: Mapping[str, Any], sql: str
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
        "sql": sql,
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
        "joins": {},
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


def compile_e02_relationship_bundle(
    spec: Mapping[str, Any],
    hkb_records: Sequence[Mapping[str, Any]],
    schema_records: Sequence[Mapping[str, Any]],
    mapping_records: Sequence[Mapping[str, Any]],
) -> SemanticBundle:
    """Compile the opt-in E02 bundle without changing the frozen baseline."""
    baseline = compile_semantic_bundle(
        spec, hkb_records, schema_records, mapping_records
    )
    views = _validated_views(spec)
    schema_index = _index(schema_records, "stable_id", "schema record")
    bindings = _column_bindings_by_table(schema_records, frozenset(views))
    plan = plan_relationship_contracts(schema_records)
    emitted: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    outgoing: dict[str, set[str]] = {}
    seen_pairs: set[tuple[str, str]] = set()

    for contract in plan["relationships"]:
        source_table = contract["source_table_stable_id"]
        target_table = contract["target_table_stable_id"]
        if source_table not in views or target_table not in views:
            continue
        pair = (source_table, target_table)
        if pair in seen_pairs:
            raise SemanticBundleError(
                "E02 requires an explicit alias for duplicate source-target joins"
            )
        source_fields = _relationship_fields(
            contract["source_column_stable_ids"],
            source_table,
            schema_index,
            bindings,
        )
        target_fields = _relationship_fields(
            contract["target_column_stable_ids"],
            target_table,
            schema_index,
            bindings,
        )
        if source_fields is None or target_fields is None:
            continue
        source_view = _safe_name(views[source_table].get("view_name"), "view_name")
        target_view = _safe_name(views[target_table].get("view_name"), "view_name")
        predicates = [
            f"${{{source_view}.{source_field}}} = ${{{target_view}.{target_field}}}"
            for source_field, target_field in zip(
                source_fields, target_fields, strict=True
            )
        ]
        emitted.append(
            {
                "join_from_view": source_view,
                "join_to_view": target_view,
                "join_type": "always_left",
                "on_sql": " AND ".join(predicates),
                "relationship_type": "many_to_one",
                "reversible": False,
            }
        )
        contracts.append(
            {
                "cardinality": contract["cardinality"],
                "foreign_key_stable_id": contract["foreign_key_stable_id"],
                "provenance": contract["provenance"],
                "source_match": contract["source_match"],
                "source_table_stable_id": source_table,
                "target_table_stable_id": target_table,
            }
        )
        outgoing.setdefault(source_table, set()).add(target_view)
        seen_pairs.add(pair)

    files = dict(baseline.files)
    for table_id, targets in sorted(outgoing.items()):
        topic_file = _text(views[table_id].get("topic_file_name"), "topic file_name")
        topic = yaml.safe_load(files[topic_file])
        if not isinstance(topic, dict):
            raise SemanticBundleError("compiled topic must be an object")
        topic["joins"] = {target: {} for target in sorted(targets)}
        context = _text(topic.get("ai_context"), "topic ai_context")
        topic["ai_context"] = context.replace(
            "This topic intentionally models no cross-table joins.",
            "This topic exposes only declared PK/unique-backed many-to-one joins.",
        )
        files[topic_file] = _yaml(topic)
    files["relationships"] = yaml.safe_dump(
        emitted, allow_unicode=True, sort_keys=False, width=1000
    )

    manifest = dict(baseline.manifest)
    manifest["files"] = _file_manifest(files)
    manifest["relationship_contracts"] = contracts
    manifest["validation"] = {
        **baseline.manifest["validation"],
        "joins_generated": bool(emitted),
        "relationship_contracts_public_only": True,
    }
    return SemanticBundle(files=files, manifest=manifest)


def _relationship_fields(
    stable_ids: Sequence[str],
    table_id: str,
    schema_index: Mapping[str, Mapping[str, Any]],
    bindings: Mapping[str, Mapping[str, tuple[str, ...]]],
) -> list[str] | None:
    fields: list[str] = []
    for stable_id in stable_ids:
        column = schema_index.get(stable_id)
        if column is None or column.get("record_kind") != "column":
            raise SemanticBundleError(f"relationship column {stable_id} is missing")
        if column.get("table_stable_id") != table_id:
            raise SemanticBundleError(
                f"relationship column {stable_id} is outside its table"
            )
        identifier = _mapping(column.get("identifier"), "column identifier")
        field = _omni_name(identifier.get("name"), "relationship field")
        if bindings.get(table_id, {}).get(field) != (stable_id,):
            return None
        fields.append(field)
    return fields


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
    column_bindings = _column_bindings_by_table(schema_records, frozenset(views))
    ordered_ids = _ordered_compile_ids(compile_mappings)
    files: dict[str, str] = {}
    elements: list[dict[str, Any]] = []
    direct_physical_bindings: list[dict[str, str]] = []
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
            column_bindings.get(table_id, {}),
            ordered_ids,
            elements,
        )
        view_file = _text(view.get("file_name"), "view file_name")
        topic_file = _text(view.get("topic_file_name"), "topic file_name")
        files[view_file] = _yaml(_view_document(view, table, dimensions, spec))
        files[topic_file] = _yaml(_topic_document(view, names))
        direct_physical_bindings.extend(
            _direct_physical_bindings(
                view_file, physical_by_table[table_id], schema_index
            )
        )
    return SemanticBundle(
        files=files,
        manifest=_bundle_manifest(
            spec,
            files,
            elements,
            compile_mappings,
            direct_physical_bindings,
            _source_name_collisions(column_bindings),
        ),
    )


def _direct_physical_bindings(
    view_file: str,
    physical_fields: Sequence[Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, str]]:
    bindings: list[dict[str, str]] = []
    for field in physical_fields:
        if "sql" in field:
            continue
        schema_id = _text(field.get("schema_stable_id"), "schema_stable_id")
        source = schema_index[schema_id]
        if source.get("record_kind") != "column":
            continue
        source_id = _text(source.get("stable_id"), "column stable_id")
        bindings.append(
            {
                "field_name": _omni_name(field.get("name"), "physical field name"),
                "file": view_file,
                "source_stable_id": source_id,
                "sql": _source_column_sql(source, schema_index),
            }
        )
    return sorted(bindings, key=lambda item: (item["file"], item["field_name"]))


def _bundle_manifest(
    spec: Mapping[str, Any],
    files: Mapping[str, str],
    elements: Sequence[Mapping[str, Any]],
    compile_mappings: Mapping[str, Mapping[str, Any]],
    direct_physical_bindings: Sequence[Mapping[str, str]],
    source_name_collisions: Sequence[Mapping[str, Any]],
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
        "direct_physical_bindings": list(direct_physical_bindings),
        "files": _file_manifest(files),
        "kind": "public-omni-semantic-bundle",
        "representability": {
            "normalized_source_name_collisions": list(source_name_collisions)
        },
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
    base_fields: Mapping[str, tuple[str, ...]],
    ordered_ids: Sequence[str],
    elements: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    dimensions: dict[str, Any] = {}
    allowed = {name for name, stable_ids in base_fields.items() if len(stable_ids) == 1}
    physical_names: dict[str, str] = {}
    reference_names: dict[str, str] = {}
    normalized_names: set[str] = set()
    for field in physical_by_table[table_id]:
        raw_name = _safe_name(field.get("name"), "physical field name")
        name = _omni_name(raw_name, "physical field name")
        if name in normalized_names:
            raise SemanticBundleError(
                f"duplicate normalized physical field name {name} in {table_id}"
            )
        normalized_names.add(name)
        physical_names[raw_name] = name
        schema_id = _text(field.get("schema_stable_id"), "schema_stable_id")
        source_raw_name, source_name = _source_column_name(
            schema_index[schema_id], schema_index
        )
        source_column = _source_column(schema_index[schema_id], schema_index)
        source_column_id = _text(source_column.get("stable_id"), "column stable_id")
        source_bindings = base_fields.get(source_name, ())
        if source_bindings != (source_column_id,):
            raise SemanticBundleError(
                f"modeled source field {source_name} is ambiguous in {table_id}"
            )
        shadowed_sources = base_fields.get(name, ())
        if shadowed_sources and shadowed_sources != (source_column_id,):
            raise SemanticBundleError(
                f"physical alias {name} shadows source field in {table_id}"
            )
        reference_names[source_raw_name] = source_name
        reference_names[raw_name] = name
    for field in physical_by_table[table_id]:
        schema_id = _text(field.get("schema_stable_id"), "schema_stable_id")
        raw_name = _safe_name(field.get("name"), "physical field name")
        name = physical_names[raw_name]
        if name in dimensions:
            raise SemanticBundleError(f"duplicate field name {name} in {table_id}")
        source = schema_index[schema_id]
        sql: str | None = None
        validate_sql = False
        if "sql" in field:
            sql = _rewrite_field_references(
                _text(field.get("sql"), "physical field sql"), reference_names
            )
            validate_sql = True
        elif source.get("record_kind") == "column":
            sql = _source_column_sql(source, schema_index)
        elif source.get("record_kind") == "structured_leaf":
            sql = _structured_leaf_sql(source, schema_index)
            validate_sql = True
        if sql is not None and validate_sql:
            _validate_sql(sql, allowed)
        dimensions[name] = _physical_dimension(
            field, source, contexts.get(schema_id, []), sql
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
        sql = _rewrite_field_references(
            _text(derived[hkb_id].get("sql"), "derived field sql"),
            reference_names,
        )
        _validate_sql(sql, allowed)
        hkb = hkb_index.get(hkb_id)
        if hkb is None:
            raise SemanticBundleError(f"HKB record {hkb_id} is missing")
        dimensions[name] = _derived_dimension(hkb, mapping, sql)
        allowed.add(name)
        elements.append(_semantic_element(mapping, hkb_id, name, "derived_dimension"))
    return dimensions, list(dimensions)

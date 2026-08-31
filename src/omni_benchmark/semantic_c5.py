"""Compile the C5 docs-idiomatic tuned governed Omni bundle from public inputs.

C5 is the successor condition to the frozen C4 baseline and the E02 candidate
(design: docs/c5-tuned-governed-condition.md). It widens the published surface
to every public table, declares a join for every FK contract that passes the
conservative cardinality rule, and ports the complete HKB to ai_context at
field, topic, and model level. Content provenance is identical to the baseline
compiler: public schema IR, public column meanings, public HKB IR.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping, Sequence

import yaml

from .semantic_bundle import (
    SemanticBundle,
    SemanticBundleError,
    _column_bindings_by_table,
    _file_manifest,
    _index,
    _items,
    _mapping,
    _omni_name,
    _published_identity_fields,
    _relationship_fields,
    _safe_name,
    _text,
    _validated_views,
    _yaml,
    compile_semantic_bundle,
    reject_protected_fields,
)
from .semantic_relationships import plan_relationship_contracts

SOFT_AI_CONTEXT_CHARS = 150_000
HARD_AI_CONTEXT_CHARS = 175_000
MODEL_FILE_NAME = "model"

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_IDENTIFIER_RUN = re.compile(r"[^a-z0-9]+")
_PORTED_DISPOSITIONS = frozenset({"defer_cross_grain", "unsupported"})
_MODEL_GUIDANCE = (
    "Prefer the declared semantic model when answering questions: pick the "
    "topic whose base view matches the question's grain, reach related tables "
    "through the topic's declared joins, and use modeled business fields "
    "instead of reconstructing their formulas. Declared joins are many-to-one "
    "and safe to traverse; when aggregating across the one-to-many direction, "
    "aggregate at the child grain or deduplicate with DISTINCT before "
    "combining. For ranking questions, order explicitly and apply the "
    "requested tie behavior. Domain definitions ported from the public "
    "knowledge base appear below and in each topic's context; treat them as "
    "authoritative."
)


def compile_c5_tuned_bundle(
    spec: Mapping[str, Any],
    hkb_records: Sequence[Mapping[str, Any]],
    schema_records: Sequence[Mapping[str, Any]],
    mapping_records: Sequence[Mapping[str, Any]],
) -> SemanticBundle:
    """Compile the widened, joined, fully HKB-carrying C5 bundle."""
    widened_spec, widening, injections = _widened_c5_spec(
        spec, schema_records, mapping_records
    )
    base = compile_semantic_bundle(
        widened_spec, hkb_records, schema_records, mapping_records
    )
    files = dict(base.files)
    views = _validated_views(widened_spec)
    schema_index = _index(schema_records, "stable_id", "schema record")
    hkb_index = _index(hkb_records, "stable_id", "HKB record")
    _inject_unrepresentable_fields(files, views, schema_index, injections)
    emitted, contracts, skipped_joins, adjacency = _c5_relationships(
        schema_records, views, schema_index, base.manifest
    )
    topic_context, model_context = _routed_hkb_context(
        mapping_records, hkb_index, schema_index, views
    )
    derived_names = _derived_names_by_table(base.manifest)
    _rewrite_topics(files, views, adjacency, topic_context, derived_names)
    files["relationships"] = yaml.safe_dump(
        emitted, allow_unicode=True, sort_keys=False, width=1000
    )
    files[MODEL_FILE_NAME] = _yaml(_model_document(model_context))
    ai_context_chars = _total_ai_context_chars(files)
    if ai_context_chars > HARD_AI_CONTEXT_CHARS:
        raise SemanticBundleError(
            f"bundle ai_context is {ai_context_chars} characters, above the "
            f"{HARD_AI_CONTEXT_CHARS} hard budget"
        )
    manifest = dict(base.manifest)
    manifest["files"] = _file_manifest(files)
    manifest["relationship_contracts"] = contracts
    manifest["c5"] = {
        "ai_context_chars": ai_context_chars,
        "ai_context_soft_budget_exceeded": ai_context_chars > SOFT_AI_CONTEXT_CHARS,
        "context_port": {
            "model_level": len(model_context),
            "topic_level": sum(len(items) for items in topic_context.values()),
        },
        "relationships_skipped": skipped_joins,
        "widening": widening,
    }
    manifest["validation"] = {
        **base.manifest["validation"],
        "hkb_context_ported": True,
        "joins_generated": bool(emitted),
        "relationship_contracts_public_only": True,
    }
    return SemanticBundle(files=files, manifest=manifest)


def _synthesized_field_name(raw: str) -> str | None:
    name = _NON_IDENTIFIER_RUN.sub("_", _CAMEL_BOUNDARY.sub("_", raw).lower()).strip(
        "_"
    )
    if not name:
        return None
    return f"_{name}" if name[0].isdigit() else name


def _binding_table_id(
    record: Mapping[str, Any], schema_index: Mapping[str, Mapping[str, Any]]
) -> str:
    kind = record.get("record_kind")
    if kind == "table":
        return _text(record.get("stable_id"), "table stable_id")
    if kind == "column":
        return _text(record.get("table_stable_id"), "column table_stable_id")
    if kind == "structured_leaf":
        column_id = _text(record.get("column_stable_id"), "leaf column_stable_id")
        column = schema_index.get(column_id)
        if column is None:
            raise SemanticBundleError(f"structured leaf column {column_id} is missing")
        return _text(column.get("table_stable_id"), "column table_stable_id")
    raise SemanticBundleError("binding must target a table, column, or structured leaf")


def _leaf_path_keys(leaf: Mapping[str, Any]) -> list[str]:
    keys: list[str] = []
    for raw_segment in _items(leaf.get("path"), "structured leaf path"):
        segment = _mapping(raw_segment, "structured leaf path segment")
        kind = segment.get("kind")
        if kind == "object_key":
            keys.append(_text(segment.get("key"), "structured leaf object key"))
        elif kind == "array_index":
            index = segment.get("index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise SemanticBundleError("structured leaf array index is invalid")
            keys.append(str(index))
        else:
            raise SemanticBundleError("structured leaf path kind is invalid")
    if not keys:
        raise SemanticBundleError("structured leaf path must not be empty")
    return keys


def _widened_c5_spec(
    spec: Mapping[str, Any],
    schema_records: Sequence[Mapping[str, Any]],
    mapping_records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    reject_protected_fields([spec, list(schema_records), list(mapping_records)])
    spec = _mapping(spec, "bundle specification")
    database = _safe_name(spec.get("database"), "database")
    schema_name = _safe_name(spec.get("schema"), "schema")
    schema_index = _index(schema_records, "stable_id", "schema record")

    declared_views = [
        _mapping(raw, "view") for raw in _items(spec.get("views"), "views")
    ]
    covered = {view.get("table_stable_id") for view in declared_views}
    output_names: set[str] = set()
    view_names: set[str] = set()
    for view in declared_views:
        output_names.update(
            {view.get("file_name"), view.get("topic_file_name")} - {None}
        )
        view_names.add(view.get("view_name"))

    skipped: list[dict[str, str]] = []
    added_views: list[dict[str, str]] = []
    viewed_tables = set(covered)
    tables = sorted(
        (record for record in schema_records if record.get("record_kind") == "table"),
        key=lambda record: _text(record.get("stable_id"), "table stable_id"),
    )
    for table in tables:
        table_id = _text(table.get("stable_id"), "table stable_id")
        if table_id in covered:
            continue
        raw_name = _text(
            _mapping(table.get("identifier"), "table identifier").get("name"),
            "table name",
        )
        if not _IDENTIFIER.fullmatch(raw_name):
            skipped.append(
                {"reason": "table_name_unrepresentable", "stable_id": table_id}
            )
            continue
        # Omni snake-cases a view's name, so a CamelCase table joined or referenced
        # under its physical name resolves to a view the product never created.
        omni_name = _omni_name(raw_name, "table name")
        view_name = f"{database}_{schema_name}__{omni_name}"
        file_name = f"{database}.{schema_name}__{omni_name}.view"
        topic_file = f"{omni_name}_semantics.topic"
        if view_name in view_names or {file_name, topic_file} & output_names:
            skipped.append({"reason": "output_name_collision", "stable_id": table_id})
            continue
        added_views.append(
            {
                "description": f"All columns of the public table {raw_name}.",
                "file_name": file_name,
                "label": raw_name,
                "table_stable_id": table_id,
                "topic_file_name": topic_file,
                "view_name": view_name,
            }
        )
        view_names.add(view_name)
        output_names.update({file_name, topic_file})
        viewed_tables.add(table_id)

    declared_fields = [
        _mapping(raw, "physical field")
        for raw in _items(spec.get("physical_fields"), "physical_fields")
    ]
    declared_ids = {field.get("schema_stable_id") for field in declared_fields}
    used_names: dict[str, set[str]] = {table_id: set() for table_id in viewed_tables}
    for field in declared_fields:
        source = schema_index.get(
            _text(field.get("schema_stable_id"), "schema_stable_id")
        )
        if source is None:
            continue
        table_id = _binding_table_id(source, schema_index)
        used_names.setdefault(table_id, set()).add(
            _omni_name(field.get("name"), "physical field name")
        )
    for record in mapping_records:
        record = _mapping(record, "mapping record")
        if record.get("disposition") != "compile":
            continue
        target = record.get("target_table_stable_id")
        if isinstance(target, str):
            used_names.setdefault(target, set()).add(
                _text(record.get("semantic_name"), "semantic_name")
            )

    normalized: dict[str, Counter[str]] = {}
    for record in schema_records:
        if record.get("record_kind") != "column":
            continue
        table_id = record.get("table_stable_id")
        if table_id not in viewed_tables:
            continue
        raw = _mapping(record.get("identifier"), "column identifier").get("name")
        if not isinstance(raw, str) or not _IDENTIFIER.fullmatch(raw):
            continue
        normalized.setdefault(table_id, Counter())[_omni_name(raw, "column name")] += 1

    added_fields: list[dict[str, str]] = []
    injections: list[dict[str, str]] = []
    columns = sorted(
        (record for record in schema_records if record.get("record_kind") == "column"),
        key=lambda record: _text(record.get("stable_id"), "column stable_id"),
    )
    for column in columns:
        table_id = _text(column.get("table_stable_id"), "column table_stable_id")
        if table_id not in viewed_tables:
            continue
        stable_id = _text(column.get("stable_id"), "column stable_id")
        if stable_id in declared_ids:
            continue
        raw = _text(
            _mapping(column.get("identifier"), "column identifier").get("name"),
            "column name",
        )
        if _IDENTIFIER.fullmatch(raw):
            name = _omni_name(raw, "column name")
            if normalized[table_id][name] > 1:
                skipped.append(
                    {"reason": "ambiguous_normalized_name", "stable_id": stable_id}
                )
                continue
            if name in used_names[table_id]:
                skipped.append({"reason": "name_collision", "stable_id": stable_id})
                continue
            used_names[table_id].add(name)
            added_fields.append({"name": raw, "schema_stable_id": stable_id})
            continue
        synthesized = _synthesized_field_name(raw)
        if synthesized is None or '"' in raw or synthesized in used_names[table_id]:
            skipped.append(
                {"reason": "unrepresentable_column_skipped", "stable_id": stable_id}
            )
            continue
        used_names[table_id].add(synthesized)
        injections.append(
            {
                "field_name": synthesized,
                "kind": "column",
                "stable_id": stable_id,
                "table_stable_id": table_id,
            }
        )

    leaves = sorted(
        (
            record
            for record in schema_records
            if record.get("record_kind") == "structured_leaf"
        ),
        key=lambda record: _text(record.get("stable_id"), "leaf stable_id"),
    )
    for leaf in leaves:
        column_id = _text(leaf.get("column_stable_id"), "leaf column_stable_id")
        column = schema_index.get(column_id)
        if column is None or column.get("record_kind") != "column":
            raise SemanticBundleError(f"structured leaf column {column_id} is missing")
        table_id = _text(column.get("table_stable_id"), "column table_stable_id")
        if table_id not in viewed_tables:
            continue
        stable_id = _text(leaf.get("stable_id"), "leaf stable_id")
        if stable_id in declared_ids:
            continue
        parent_raw = _text(
            _mapping(column.get("identifier"), "column identifier").get("name"),
            "column name",
        )
        synthesized = _synthesized_field_name(
            "_".join([parent_raw, *_leaf_path_keys(leaf)])
        )
        if synthesized is None or synthesized in used_names[table_id]:
            skipped.append(
                {"reason": "leaf_name_unrepresentable", "stable_id": stable_id}
            )
            continue
        if _IDENTIFIER.fullmatch(parent_raw):
            used_names[table_id].add(synthesized)
            added_fields.append({"name": synthesized, "schema_stable_id": stable_id})
            continue
        if '"' in parent_raw:
            skipped.append(
                {"reason": "unrepresentable_column_skipped", "stable_id": stable_id}
            )
            continue
        used_names[table_id].add(synthesized)
        injections.append(
            {
                "field_name": synthesized,
                "kind": "leaf",
                "stable_id": stable_id,
                "table_stable_id": table_id,
            }
        )

    widened = {
        **spec,
        "physical_fields": [*declared_fields, *added_fields],
        "views": [*declared_views, *added_views],
    }
    report = {
        "physical_fields_added": len(added_fields),
        "skipped": skipped,
        "unrepresentable_fields_injected": len(injections),
        "views_added": len(added_views),
    }
    return widened, report, injections


def _quoted_identifier(column: Mapping[str, Any]) -> str:
    name = _text(
        _mapping(column.get("identifier"), "column identifier").get("name"),
        "column name",
    )
    if '"' in name:
        raise SemanticBundleError("column name cannot be safely quoted")
    return f'"{name}"'


def _quoted_leaf_sql(
    leaf: Mapping[str, Any], schema_index: Mapping[str, Mapping[str, Any]]
) -> str:
    column = schema_index[_text(leaf.get("column_stable_id"), "leaf column_stable_id")]
    arguments = [_quoted_identifier(column)]
    for key in _leaf_path_keys(leaf):
        arguments.append("'" + key.replace("'", "''") + "'")
    return f"JSONB_EXTRACT_PATH_TEXT({', '.join(arguments)})"


def _inject_unrepresentable_fields(
    files: dict[str, str],
    views: Mapping[str, Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
    injections: Sequence[Mapping[str, str]],
) -> None:
    for entry in injections:
        view = views[entry["table_stable_id"]]
        view_file = _text(view.get("file_name"), "view file_name")
        document = yaml.safe_load(files[view_file])
        if not isinstance(document, dict) or not isinstance(
            document.get("dimensions"), dict
        ):
            raise SemanticBundleError("compiled view must declare dimensions")
        dimensions = document["dimensions"]
        if entry["field_name"] in dimensions:
            raise SemanticBundleError(
                f"injected field {entry['field_name']} collides in {view_file}"
            )
        record = schema_index[entry["stable_id"]]
        if entry["kind"] == "column":
            sql = _quoted_identifier(record)
        else:
            sql = _quoted_leaf_sql(record, schema_index)
        dimensions[entry["field_name"]] = {
            "description": _text(
                record.get("description"), "schema source description"
            ),
            "sql": sql,
        }
        files[view_file] = _yaml(document)


def _c5_relationships(
    schema_records: Sequence[Mapping[str, Any]],
    views: Mapping[str, Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, str]],
    dict[str, list[str]],
]:
    plan = plan_relationship_contracts(schema_records)
    published = _published_identity_fields(manifest)
    bindings = _column_bindings_by_table(schema_records, frozenset(views))
    emitted: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    adjacency: dict[str, list[str]] = {}
    seen_pairs: set[tuple[str, str]] = set()

    for contract in plan["relationships"]:
        foreign_key_id = contract["foreign_key_stable_id"]
        source_table = contract["source_table_stable_id"]
        target_table = contract["target_table_stable_id"]
        if source_table not in views or target_table not in views:
            skipped.append(
                {
                    "foreign_key_stable_id": foreign_key_id,
                    "reason": "endpoint_table_unpublished",
                }
            )
            continue
        if source_table == target_table:
            skipped.append(
                {
                    "foreign_key_stable_id": foreign_key_id,
                    "reason": "self_join_unsupported",
                }
            )
            continue
        pair = (source_table, target_table)
        if pair in seen_pairs:
            skipped.append(
                {"foreign_key_stable_id": foreign_key_id, "reason": "duplicate_pair"}
            )
            continue
        source_fields = _relationship_fields(
            contract["source_column_stable_ids"],
            source_table,
            schema_index,
            bindings,
            published,
        )
        target_fields = _relationship_fields(
            contract["target_column_stable_ids"],
            target_table,
            schema_index,
            bindings,
            published,
        )
        if source_fields is None or target_fields is None:
            skipped.append(
                {
                    "foreign_key_stable_id": foreign_key_id,
                    "reason": "endpoint_field_unresolved",
                }
            )
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
                "foreign_key_stable_id": foreign_key_id,
                "provenance": contract["provenance"],
                "source_match": contract["source_match"],
                "source_table_stable_id": source_table,
                "target_table_stable_id": target_table,
            }
        )
        adjacency.setdefault(source_view, []).append(target_view)
        seen_pairs.add(pair)
    return emitted, contracts, skipped, adjacency


def _topic_join_tree(
    root: str, adjacency: Mapping[str, Sequence[str]]
) -> dict[str, Any]:
    visited = {root}
    tree: dict[str, Any] = {}
    queue: list[tuple[dict[str, Any], str]] = [(tree, root)]
    while queue:
        node, view = queue.pop(0)
        for target in sorted(adjacency.get(view, [])):
            if target in visited:
                continue
            visited.add(target)
            child: dict[str, Any] = {}
            node[target] = child
            queue.append((child, target))
    return tree


def _tree_views(tree: Mapping[str, Any]) -> list[str]:
    views: list[str] = []
    for name, child in tree.items():
        views.append(name)
        views.extend(_tree_views(child))
    return views


def _routed_hkb_context(
    mapping_records: Sequence[Mapping[str, Any]],
    hkb_index: Mapping[str, Mapping[str, Any]],
    schema_index: Mapping[str, Mapping[str, Any]],
    views: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, list[str]], list[str]]:
    topic_entries: dict[str, list[tuple[int, str, str]]] = {}
    model_entries: list[tuple[int, str, str]] = []
    ported = sorted(
        (
            _mapping(record, "mapping record")
            for record in mapping_records
            if _mapping(record, "mapping record").get("disposition")
            in _PORTED_DISPOSITIONS
        ),
        key=lambda record: _text(record.get("hkb_stable_id"), "hkb_stable_id"),
    )
    for record in ported:
        hkb_id = _text(record.get("hkb_stable_id"), "hkb_stable_id")
        hkb = hkb_index.get(hkb_id)
        if hkb is None:
            raise SemanticBundleError(f"HKB record {hkb_id} is missing")
        depth = hkb.get("dependency_depth", 0)
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise SemanticBundleError(f"HKB record {hkb_id} dependency depth invalid")
        text = (
            _text(hkb.get("knowledge"), "HKB knowledge")
            + ": "
            + _text(hkb.get("definition"), "HKB definition")
        )
        tables = {
            _binding_table_id(
                _require_binding_record(binding, schema_index), schema_index
            )
            for binding in _items(record.get("source_bindings"), "context bindings")
        }
        entry = (depth, hkb_id, text)
        if len(tables) == 1 and (table_id := next(iter(tables))) in views:
            topic_entries.setdefault(table_id, []).append(entry)
        else:
            model_entries.append(entry)
    return (
        {
            table_id: [text for _, _, text in sorted(entries)]
            for table_id, entries in topic_entries.items()
        },
        [text for _, _, text in sorted(model_entries)],
    )


def _require_binding_record(
    binding: Any, schema_index: Mapping[str, Mapping[str, Any]]
) -> Mapping[str, Any]:
    schema_id = _text(
        _mapping(binding, "context binding").get("schema_stable_id"),
        "context schema_stable_id",
    )
    record = schema_index.get(schema_id)
    if record is None:
        raise SemanticBundleError(f"binding target {schema_id} is missing")
    return record


def _derived_names_by_table(manifest: Mapping[str, Any]) -> dict[str, list[str]]:
    names: dict[str, list[str]] = {}
    for element in _items(manifest.get("semantic_elements"), "semantic elements"):
        element = _mapping(element, "semantic element")
        if element.get("kind") != "derived_dimension":
            continue
        table_id = _text(element.get("table_stable_id"), "element table")
        names.setdefault(table_id, []).append(
            _text(element.get("semantic_name"), "semantic_name")
        )
    return {table_id: sorted(items) for table_id, items in names.items()}


def _topic_ai_context(
    join_tree: Mapping[str, Any],
    derived_names: Sequence[str],
    context_entries: Sequence[str],
) -> str:
    parts: list[str] = []
    if join_tree:
        parts.append(
            "Reach related views through the declared joins on this topic "
            "instead of re-deriving relationships."
        )
    else:
        parts.append("This topic models no cross-table joins.")
    if derived_names:
        parts.append(
            "Use the modeled business fields "
            + ", ".join(derived_names)
            + " rather than reconstructing their formulas."
        )
    if context_entries:
        parts.append(
            "Domain definitions for this topic:\n- " + "\n- ".join(context_entries)
        )
    return "\n".join(parts)


def _rewrite_topics(
    files: dict[str, str],
    views: Mapping[str, Mapping[str, Any]],
    adjacency: Mapping[str, Sequence[str]],
    topic_context: Mapping[str, Sequence[str]],
    derived_names: Mapping[str, Sequence[str]],
) -> None:
    for table_id, view in views.items():
        topic_file = _text(view.get("topic_file_name"), "topic file_name")
        view_name = _safe_name(view.get("view_name"), "view_name")
        document = yaml.safe_load(files[topic_file])
        if not isinstance(document, dict):
            raise SemanticBundleError("compiled topic must be an object")
        tree = _topic_join_tree(view_name, adjacency)
        document["joins"] = tree
        document["fields"] = [f"{view_name}.*"] + [
            f"{joined}.*" for joined in sorted(_tree_views(tree))
        ]
        document["ai_context"] = _topic_ai_context(
            tree,
            derived_names.get(table_id, []),
            topic_context.get(table_id, []),
        )
        files[topic_file] = _yaml(document)


def _model_document(model_entries: Sequence[str]) -> dict[str, str]:
    context = _MODEL_GUIDANCE
    if model_entries:
        context += "\nDatabase-wide domain definitions:\n- " + "\n- ".join(
            model_entries
        )
    return {"ai_context": context}


def _ai_context_chars(value: object) -> int:
    if isinstance(value, dict):
        return sum(
            len(item)
            if key == "ai_context" and isinstance(item, str)
            else _ai_context_chars(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return sum(_ai_context_chars(item) for item in value)
    return 0


def _total_ai_context_chars(files: Mapping[str, str]) -> int:
    return sum(
        _ai_context_chars(yaml.safe_load(content))
        for name, content in files.items()
        if name != "relationships"
    )

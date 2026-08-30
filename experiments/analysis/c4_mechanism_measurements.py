"""Aggregate mechanism measurements for the frozen C4 dev-A baseline.

Answers three offline questions posed by ``docs/c4-failure-attribution.md`` §6.4:

1. E05 precondition. For the terminal ``omni_unknown_result_type`` failures,
   classify each attempt's selected semantic fields as compiled-derived
   (HKB-backed), compiled-physical (schema column), or product-generated
   (not present in any compiled bundle).
2. SQL path shape. Count ``userEditedSQL`` presence by outcome and characterize
   where multi-relation access originates.
3. Relation-count confounder. Recompute relation statistics with CTE names,
   alias duplicates, and subquery-derived sources removed.

Reads only immutable score envelopes, the hash-pinned recovery manifest, their
hash-bound generation records, and the committed public semantic bundles. It
never reads gold SQL, result values, question text, or hidden annotations, and
it emits only aggregates: no question identifier, SQL text, or per-question
label appears in the output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import sqlglot
import yaml
from sqlglot import exp

MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
SCORE_ROOT_NAME = "public-c4-baseline-v8-dev-a-scores-v2"
RECOVERY_ROOT_NAME = "public-c4-baseline-v8-recovery-v5"
RECOVERY_MANIFEST_SHA256 = (
    "5d6ff474f30d3de6d703ad5c6c59373fe8093515eabb83473bdb352c4f30fd9f"
)
OMNI_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.]*)\}")
FIELD_CLASSES = (
    "derived",
    "physical",
    "omni_count_builtin",
    "schema_column_not_in_bundle",
    "unmatched_name",
    "unmodeled_view",
    "query_local",
)
COMPILED_FIELD_CLASSES = ("derived", "physical")
QUERY_FLAGS = (
    "ai_generated",
    "declares_join_via_map",
    "declares_topic_join_path",
    "rewrite_sql",
    "table_is_query_local",
)


def _bounded_bytes(path: Path) -> bytes:
    metadata = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > MAX_ARTIFACT_BYTES
    ):
        raise ValueError(f"unsafe or oversized artifact: {path}")
    content = path.read_bytes()
    if len(content) != metadata.st_size:
        raise ValueError(f"artifact changed while reading: {path}")
    return content


def _json(path: Path) -> Any:
    return json.loads(_bounded_bytes(path))


# --------------------------------------------------------------------------
# Compiled bundle field index
# --------------------------------------------------------------------------


def _derived_names_by_table(database_dir: Path) -> dict[str, set[str]]:
    """Return compiled HKB-backed field names for each source table."""
    derived: dict[str, set[str]] = defaultdict(set)
    for mapping_path in sorted((database_dir / "mapping").glob("*.mapping.jsonl")):
        for line in _bounded_bytes(mapping_path).splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            name = record.get("semantic_name")
            table_stable_id = record.get("target_table_stable_id")
            if (
                record.get("disposition") != "compile"
                or not isinstance(name, str)
                or not isinstance(table_stable_id, str)
            ):
                continue
            derived[table_stable_id].add(name)
    return derived


def _view_dimensions(view_path: Path) -> dict[str, Any]:
    document = yaml.safe_load(_bounded_bytes(view_path).decode())
    dimensions = document.get("dimensions") if isinstance(document, dict) else None
    if not isinstance(dimensions, dict):
        raise ValueError(f"view declares no dimensions: {view_path.name}")
    return dimensions


def _index_specified_bundle(
    database_dir: Path, index: dict[str, dict[str, str]]
) -> None:
    spec = _json(database_dir / "bundle.spec.json")
    derived_by_table = _derived_names_by_table(database_dir)
    classified_derived = 0
    for view in spec["views"]:
        view_name = view["view_name"]
        dimensions = _view_dimensions(database_dir / "bundle" / view["file_name"])
        derived = derived_by_table.get(view["table_stable_id"], set())
        classified = {
            name: ("derived" if name in derived else "physical") for name in dimensions
        }
        classified_derived += sum(value == "derived" for value in classified.values())
        if view_name in index:
            raise ValueError(f"duplicate compiled view identifier: {view_name}")
        index[view_name] = classified
    if classified_derived != len(spec["derived_fields"]):
        raise ValueError(
            f"derived-field classification disagrees with {database_dir.name} spec"
        )


def _index_specless_bundle(
    bundle_dir: Path, mapping_dir: Path, index: dict[str, dict[str, str]]
) -> None:
    """Index a bundle published without a ``bundle.spec.json`` sidecar."""
    derived_by_table = _derived_names_by_table(mapping_dir.parent)
    for view_path in sorted(bundle_dir.glob("*.view")):
        stem = view_path.name[: -len(".view")]
        catalog, dot, remainder = stem.partition(".")
        if not dot:
            raise ValueError(f"unexpected view filename: {view_path.name}")
        view_name = f"{catalog}_{remainder}"
        document = yaml.safe_load(_bounded_bytes(view_path).decode())
        table_stable_id = f"{catalog}:table:{document['table_name']}"
        derived = derived_by_table.get(table_stable_id, set())
        if view_name in index:
            raise ValueError(f"duplicate compiled view identifier: {view_name}")
        index[view_name] = {
            name: ("derived" if name in derived else "physical")
            for name in _view_dimensions(view_path)
        }


def build_field_index(workspace: Path) -> dict[str, dict[str, str]]:
    """Map every compiled ``view.field`` to ``derived`` or ``physical``."""
    index: dict[str, dict[str, str]] = {}
    baseline_root = workspace / "semantic_models/public_baseline"
    for database_dir in sorted(
        path for path in baseline_root.iterdir() if path.is_dir()
    ):
        _index_specified_bundle(database_dir, index)
    _index_specless_bundle(
        workspace / "semantic_models/public_bundle",
        workspace / "semantic_models/public_mapping",
        index,
    )
    return index


def build_view_columns(workspace: Path) -> dict[str, frozenset[str]]:
    """Map each compiled view to the schema columns of the table it wraps."""
    tables: dict[str, set[str]] = defaultdict(set)
    schema_paths = sorted(
        list(
            workspace.glob("semantic_models/public_baseline/*/schema_ir/*.schema.jsonl")
        )
        + list(workspace.glob("semantic_models/public_schema_ir/*.schema.jsonl"))
    )
    for path in schema_paths:
        for line in _bounded_bytes(path).splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            table_stable_id = record.get("table_stable_id")
            if record.get("record_kind") == "column" and isinstance(
                table_stable_id, str
            ):
                tables[table_stable_id].add(record["identifier"]["name"])

    view_tables: dict[str, str] = {}
    baseline_root = workspace / "semantic_models/public_baseline"
    for database_dir in sorted(
        path for path in baseline_root.iterdir() if path.is_dir()
    ):
        for view in _json(database_dir / "bundle.spec.json")["views"]:
            view_tables[view["view_name"]] = view["table_stable_id"]
    for view_path in sorted(
        (workspace / "semantic_models/public_bundle").glob("*.view")
    ):
        catalog, _, remainder = view_path.name[: -len(".view")].partition(".")
        document = yaml.safe_load(_bounded_bytes(view_path).decode())
        view_tables[f"{catalog}_{remainder}"] = (
            f"{catalog}:table:{document['table_name']}"
        )
    return {
        view_name: frozenset(tables.get(table_stable_id, set()))
        for view_name, table_stable_id in view_tables.items()
    }


def classify_field(
    field: str,
    index: dict[str, dict[str, str]],
    view_columns: dict[str, frozenset[str]],
    query_local: frozenset[str],
) -> str:
    """Classify one selected semantic-query field reference."""
    view, _, name = field.rpartition(".")
    if not view or view.lower() in query_local:
        return "query_local"
    fields = index.get(view)
    if fields is None:
        return "unmodeled_view"
    if name in fields:
        return fields[name]
    if name == "count":
        return "omni_count_builtin"
    if name in view_columns.get(view, frozenset()):
        return "schema_column_not_in_bundle"
    return "unmatched_name"


# --------------------------------------------------------------------------
# Structural features
# --------------------------------------------------------------------------


def _local_names(tree: exp.Expression) -> set[str]:
    """Return names a query defines for itself: CTE names and source aliases."""
    names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        if cte.alias:
            names.add(cte.alias.lower())
    for table in tree.find_all(exp.Table):
        if table.alias:
            names.add(table.alias.lower())
    for subquery in tree.find_all(exp.Subquery):
        if subquery.alias:
            names.add(subquery.alias.lower())
    return names


def sql_relation_features(sql: str) -> dict[str, Any]:
    """Return published and CTE-corrected relation features for one query."""
    tree = sqlglot.parse_one(OMNI_REFERENCE.sub(r"\1", sql), read="postgres")
    published = {table.sql(dialect="postgres") for table in tree.find_all(exp.Table)}
    local = _local_names(tree)
    ctes = {cte.alias.lower() for cte in tree.find_all(exp.CTE) if cte.alias}
    base_names = {
        table.name.lower()
        for table in tree.find_all(exp.Table)
        if table.name and table.name.lower() not in ctes
    }
    source_views = {
        column.table
        for column in tree.find_all(exp.Column)
        if column.table and column.table.lower() not in local
    }
    return {
        "aggregate": any(tree.find_all(exp.AggFunc)),
        "corrected_multi_relation": len(base_names) >= 2,
        "corrected_relation_count": len(base_names),
        "cte_count": len(ctes),
        "distinct_source_views": len(source_views),
        "join": any(tree.find_all(exp.Join)),
        "local_names": frozenset(local),
        "multi_source_view": len(source_views) >= 2,
        "nested": any(tree.find_all(exp.Subquery)),
        "published_multi_relation": len(published) >= 2,
        "published_relation_count": len(published),
    }


# --------------------------------------------------------------------------
# Artifact resolution
# --------------------------------------------------------------------------


def _generation_index(root: Path) -> dict[str, list[Path]]:
    indexed: dict[str, list[Path]] = defaultdict(list)
    for path in root.rglob("generation.jsonl"):
        content = _bounded_bytes(path)
        indexed[hashlib.sha256(content).hexdigest()].append(path)
    return dict(indexed)


def _record_for_attempt(
    paths: list[Path], attempt_id: str, record_sha256: str
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in paths:
        for line in _bounded_bytes(path).splitlines(keepends=True):
            if hashlib.sha256(line).hexdigest() != record_sha256:
                continue
            record = json.loads(line)
            if isinstance(record, dict) and record.get("attempt_id") == attempt_id:
                matches.append(record)
    if len(matches) != 1:
        raise ValueError("score attempt does not resolve to one generation record")
    return matches[0]


def _verified_official_score(workspace: Path) -> tuple[dict[str, Any], str]:
    score_root = workspace / "experiments/autoresearch/raw" / SCORE_ROOT_NAME
    receipt = _json(score_root / "receipt.json")
    score_content = _bounded_bytes(workspace / receipt["artifacts"]["official"]["path"])
    expected = receipt["artifacts"]["official"]["sha256"]
    if hashlib.sha256(score_content).hexdigest() != expected:
        raise ValueError("official score artifact hash changed")
    if receipt["c4_recovery_sha256"] != RECOVERY_MANIFEST_SHA256:
        raise ValueError("score receipt binds an unexpected recovery manifest")
    return json.loads(score_content), expected


def _verified_recovery_manifest(workspace: Path) -> dict[str, Any]:
    path = (
        workspace
        / "experiments/autoresearch/raw"
        / RECOVERY_ROOT_NAME
        / "recovery.manifest.json"
    )
    content = _bounded_bytes(path)
    if hashlib.sha256(content).hexdigest() != RECOVERY_MANIFEST_SHA256:
        raise ValueError("recovery manifest hash changed")
    return json.loads(content)


def _semantic_query(record: dict[str, Any]) -> dict[str, Any] | None:
    generated_query = record.get("generated_query")
    if isinstance(generated_query, str):
        try:
            generated_query = json.loads(generated_query)
        except json.JSONDecodeError:
            return None
    return generated_query if isinstance(generated_query, dict) else None


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _query_flags(
    semantic_query: dict[str, Any] | None, query_local: frozenset[str]
) -> dict[str, bool] | None:
    """Return the declared-structure flags of one generated semantic query."""
    if semantic_query is None:
        return None
    table = semantic_query.get("table")
    return {
        "ai_generated": bool(semantic_query.get("aiGenerated")),
        "declares_join_via_map": bool(semantic_query.get("join_via_map")),
        "declares_topic_join_path": bool(
            semantic_query.get("join_paths_from_topic_name")
        ),
        "rewrite_sql": bool(semantic_query.get("rewriteSql")),
        "table_is_query_local": isinstance(table, str) and table.lower() in query_local,
    }


def _field_composition(classes: list[str]) -> str:
    """Bucket one attempt by what its selected fields could have been typed from."""
    present = set(classes)
    if not present:
        return "no_fields"
    if present == {"derived"}:
        return "all_derived"
    if present == {"physical"}:
        return "all_physical"
    if present <= set(COMPILED_FIELD_CLASSES):
        return "compiled_derived_and_physical"
    if "derived" in present:
        return "derived_plus_uncompiled"
    if "physical" in present:
        return "physical_plus_uncompiled"
    return "no_compiled_field"


def _group_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    parsed = [row for row in rows if row["relations"] is not None]
    with_sql = [row for row in rows if row["has_user_edited_sql"]]
    field_rows = [row for row in rows if row["field_classes"] is not None]
    flag_rows = [row for row in rows if row["flags"] is not None]
    summary: dict[str, Any] = {
        "attempts": len(rows),
        "semantic_query_flags": {
            flag: sum(row["flags"][flag] for row in flag_rows) for flag in QUERY_FLAGS
        },
        "with_generated_sql": sum(row["has_generated_sql"] for row in rows),
        "with_semantic_query": sum(row["has_semantic_query"] for row in rows),
        "with_user_edited_sql": len(with_sql),
        "parsed_sql": len(parsed),
        "field_composition": dict(
            Counter(row["composition"] for row in field_rows).most_common()
        ),
        "selected_field_class_totals": {
            name: sum(row["field_classes"].count(name) for row in field_rows)
            for name in FIELD_CLASSES
        },
        "attempts_with_at_least_one_derived": sum(
            "derived" in row["field_classes"] for row in field_rows
        ),
        "attempts_with_at_least_one_uncompiled_field": sum(
            any(value not in COMPILED_FIELD_CLASSES for value in row["field_classes"])
            for row in field_rows
        ),
        "attempts_with_all_fields_uncompiled": sum(
            all(value not in COMPILED_FIELD_CLASSES for value in row["field_classes"])
            for row in field_rows
        ),
    }
    if parsed:
        summary["relations"] = {
            "published_mean": round(
                sum(row["relations"]["published_relation_count"] for row in parsed)
                / len(parsed),
                3,
            ),
            "corrected_mean": round(
                sum(row["relations"]["corrected_relation_count"] for row in parsed)
                / len(parsed),
                3,
            ),
            "published_multi_relation": sum(
                row["relations"]["published_multi_relation"] for row in parsed
            ),
            "corrected_multi_relation": sum(
                row["relations"]["corrected_multi_relation"] for row in parsed
            ),
            "multi_source_view": sum(
                row["relations"]["multi_source_view"] for row in parsed
            ),
            "source_view_mean": round(
                sum(row["relations"]["distinct_source_views"] for row in parsed)
                / len(parsed),
                3,
            ),
            "with_cte": sum(bool(row["relations"]["cte_count"]) for row in parsed),
            "with_join": sum(row["relations"]["join"] for row in parsed),
            "with_nested": sum(row["relations"]["nested"] for row in parsed),
            "cross_source_without_declared_join": sum(
                row["relations"]["corrected_multi_relation"]
                and not row["flags"]["declares_join_via_map"]
                for row in parsed
            ),
        }
    return summary


def analyze(workspace: Path, generation_root: Path) -> dict[str, Any]:
    """Measure C4 field provenance, SQL path shape, and relation confounding."""
    score, score_sha256 = _verified_official_score(workspace)
    recovery = _verified_recovery_manifest(workspace)
    index = build_field_index(workspace)
    view_columns = build_view_columns(workspace)
    generations = _generation_index(generation_root)
    reason_by_attempt = {
        entry["attempt_id"]: entry["reason"]
        for entry in recovery["entries"]
        if entry["disposition"] == "evaluated_system_failure"
    }

    rows: list[dict[str, Any]] = []
    for attempt in score["attempts"]:
        if attempt.get("status") != "scored":
            raise ValueError("official C4 score contains an unscored attempt")
        attempt_id = attempt["attempt_id"]
        if attempt_id.rsplit(":", 3)[2] != "C4":
            raise ValueError("C4 score artifact contains another condition")
        record = _record_for_attempt(
            generations.get(attempt["generation_sha256"], []),
            attempt_id,
            attempt["generation_record_sha256"],
        )
        semantic_query = _semantic_query(record)
        user_edited_sql = (
            semantic_query.get("userEditedSQL") if semantic_query else None
        )
        has_sql = isinstance(user_edited_sql, str) and bool(user_edited_sql)
        relations = None
        if has_sql:
            try:
                relations = sql_relation_features(user_edited_sql)
            except sqlglot.errors.SqlglotError:
                relations = None
        query_local: frozenset[str] = (
            relations["local_names"] if relations else frozenset()
        )
        fields = semantic_query.get("fields") if semantic_query else None
        field_classes = (
            [
                classify_field(field, index, view_columns, query_local)
                for field in fields
            ]
            if isinstance(fields, list)
            else None
        )
        generated_sql = record.get("generated_sql")
        rows.append(
            {
                "composition": (
                    _field_composition(field_classes)
                    if field_classes is not None
                    else "no_semantic_query"
                ),
                "failure_reason": reason_by_attempt.get(attempt_id),
                "field_classes": field_classes,
                "flags": _query_flags(semantic_query, query_local),
                "has_generated_sql": isinstance(generated_sql, str)
                and bool(generated_sql),
                "has_semantic_query": semantic_query is not None,
                "has_user_edited_sql": has_sql,
                "outcome": attempt["outcome"],
                "relations": relations,
            }
        )

    by_outcome = defaultdict(list)
    for row in rows:
        by_outcome[row["outcome"]].append(row)
    by_reason = defaultdict(list)
    for row in rows:
        if row["failure_reason"] is not None:
            by_reason[row["failure_reason"]].append(row)

    return {
        "compiled_view_count": len(index),
        "recovery_manifest_sha256": RECOVERY_MANIFEST_SHA256,
        "recovery_reason_counts": dict(
            Counter(entry["reason"] for entry in recovery["entries"]).most_common()
        ),
        "row_count": len(rows),
        "schema_version": 1,
        "score_artifact_sha256": score_sha256,
        "summary_by_failure_reason": {
            reason: _group_summary(group) for reason, group in sorted(by_reason.items())
        },
        "summary_by_outcome": {
            outcome: _group_summary(group)
            for outcome, group in sorted(by_outcome.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--c4-generation-root", type=Path, required=True)
    arguments = parser.parse_args()
    result = analyze(
        arguments.workspace.resolve(strict=True),
        arguments.c4_generation_root.resolve(strict=True),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

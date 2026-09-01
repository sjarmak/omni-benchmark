from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.measure_review_catalog import (
    MeasureCatalogError,
    build_measure_review_catalog,
    canonical_catalog_bytes,
    generate_workspace_measure_review_catalog,
    propose_database_measure_candidates,
    write_measure_review_catalog,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _source(kind: str, name: str) -> dict[str, object]:
    return {
        "kind": kind,
        "file": f"public/{name}.json",
        "file_sha256": hashlib.sha256(name.encode()).hexdigest(),
    }


def _table(
    name: str,
    *,
    primary: tuple[str, ...] = (),
    unique: tuple[tuple[str, ...], ...] = (),
) -> dict[str, object]:
    table_id = f"db:table:{name}"
    return {
        "database": "db",
        "identifier": {"name": name},
        "primary_key_column_stable_ids": [
            f"db:column:{name}:{column}" for column in primary
        ],
        "provenance": {"sources": [_source("schema_ddl", name)]},
        "record_kind": "table",
        "schema_version": 1,
        "stable_id": table_id,
        "unique_keys": [
            [f"db:column:{name}:{column}" for column in key] for key in unique
        ],
    }


def _column(table: str, name: str, declared_type: str = "BIGINT") -> dict[str, object]:
    return {
        "database": "db",
        "declared_type_sql": declared_type,
        "description": f"Public {name} field.",
        "identifier": {"name": name},
        "provenance": {"sources": [_source("schema_ddl", f"{table}-{name}")]},
        "record_kind": "column",
        "schema_version": 1,
        "stable_id": f"db:column:{table}:{name}",
        "table_stable_id": f"db:table:{table}",
    }


def _view(table: str, *fields: str) -> dict[str, object]:
    return {
        "file_name": f"db.public__{table}.view",
        "fields": {f"db:column:{table}:{field}": field.lower() for field in fields},
        "label": table.replace("_", " ").title(),
        "table_stable_id": f"db:table:{table}",
        "view_name": f"db_public__{table}",
    }


def _hkb(
    definition: str,
    *,
    stable_id: str = "db:hkb:1",
    dependencies: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "database": "db",
        "definition": definition,
        "dependency_closure_stable_ids": list(dependencies),
        "dependency_depth": int(bool(dependencies)),
        "dependency_stable_ids": list(dependencies),
        "description": "A public aggregate definition.",
        "hkb_id": 1,
        "knowledge": "Average Latency",
        "provenance": {
            "content": "public_hkb",
            "source": {
                **_source("public_hkb", stable_id.replace(":", "-")),
                "line": 1,
                "record_sha256": hashlib.sha256(definition.encode()).hexdigest(),
            },
        },
        "schema_version": 1,
        "source_type": "calculation_knowledge",
        "stable_id": stable_id,
    }


def _mapping(
    *,
    role: str = "latency_ms",
    source: str = "db:column:requests:latency_ms",
    target: str | None = "db:table:requests",
    dependencies: tuple[str, ...] = (),
    relationship_requirements: tuple[str, ...] = (),
    disposition: str = "compile",
) -> dict[str, object]:
    return {
        "database": "db",
        "dependency_audit": {
            "missing_references": [],
            "redundant_references": [],
        },
        "dependency_hkb_stable_ids": list(dependencies),
        "dependency_mode": (
            "same_grain" if disposition == "compile" else "cross_grain_unresolved"
        ),
        "disposition": disposition,
        "hkb_stable_id": "db:hkb:1",
        "loss_codes": [],
        "provenance": {
            "content": ["public_hkb", "public_schema"],
            "sources": {
                "hkb_stable_id": "db:hkb:1",
                "schema_stable_ids": [source],
            },
        },
        "relationship_requirements": list(relationship_requirements),
        "representation": "numeric_derived_dimension",
        "schema_version": 1,
        "semantic_name": "average_latency",
        "source_bindings": [
            {"confidence": "exact", "role": role, "schema_stable_id": source}
        ],
        "target_table_stable_id": target,
    }


def _database_inputs(
    *,
    schema_records: list[dict[str, object]],
    hkb_records: list[dict[str, object]] | None = None,
    mapping_records: list[dict[str, object]] | None = None,
    views: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "database": "db",
        "hkb_records": hkb_records or [],
        "input_files": [
            {
                "path": "semantic_models/public_schema_ir/db.schema.jsonl",
                "sha256": "1" * 64,
            }
        ],
        "mapping_records": mapping_records or [],
        "schema_records": schema_records,
        "views": views or [],
    }


def test_entity_count_uses_a_declared_single_column_primary_key() -> None:
    inputs = _database_inputs(
        schema_records=[_table("orders", primary=("id",)), _column("orders", "id")],
        views=[_view("orders", "id")],
    )

    result = propose_database_measure_candidates(inputs)

    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["candidate_class"] == "entity_count"
    assert candidate["measure"]["name"] == "count"
    assert candidate["measure"]["definition"] == {
        "aggregate_type": "count_distinct",
        "description": "Count of distinct Orders public identity values.",
        "label": "Orders Count",
        "sql": "${db_public__orders.id}",
    }
    assert candidate["inline_equivalent_signature"] == {
        "aggregate_type": "count_distinct",
        "source_field_stable_ids": ["db:column:orders:id"],
    }
    assert candidate["review"] == {
        "active_review_seconds": None,
        "binding_correction": None,
        "decision": None,
        "reason_code": None,
        "status": "pending",
    }


def test_one_declared_single_column_unique_key_is_an_eligible_fallback() -> None:
    inputs = _database_inputs(
        schema_records=[
            _table("users", unique=(("email",),)),
            _column("users", "email", "TEXT"),
        ],
        views=[_view("users", "email")],
    )

    candidate = propose_database_measure_candidates(inputs)["candidates"][0]

    assert candidate["evidence"]["identity_kind"] == "unique_key"
    assert candidate["inline_equivalent_signature"]["source_field_stable_ids"] == [
        "db:column:users:email"
    ]


@pytest.mark.parametrize(
    ("table", "reason"),
    [
        (_table("links", primary=("left_id", "right_id")), "no_single_identity"),
        (
            _table("aliases", unique=(("email",), ("external_id",))),
            "ambiguous_single_unique_identity",
        ),
    ],
)
def test_composite_or_ambiguous_identity_is_screened_out(
    table: dict[str, object], reason: str
) -> None:
    name = table["identifier"]["name"]
    columns = [
        _column(name, stable_id.rsplit(":", 1)[-1])
        for stable_id in (
            *table["primary_key_column_stable_ids"],
            *(item for key in table["unique_keys"] for item in key),
        )
    ]
    view_fields = [column["identifier"]["name"] for column in columns]
    inputs = _database_inputs(
        schema_records=[table, *columns], views=[_view(name, *view_fields)]
    )

    result = propose_database_measure_candidates(inputs)

    assert result["candidates"] == []
    assert result["screening"]["entity_count"][reason] == 1
    assert result["screened"] == [
        {
            "candidate_class": "entity_count",
            "database": "db",
            "reason": reason,
            "source_record_sha256": hashlib.sha256(
                canonical_catalog_bytes(table)
            ).hexdigest(),
            "source_stable_id": table["stable_id"],
        }
    ]


def test_numeric_type_never_creates_an_inferred_sum_or_average() -> None:
    inputs = _database_inputs(
        schema_records=[_table("facts"), _column("facts", "amount", "NUMERIC")],
        views=[_view("facts", "amount")],
    )

    result = propose_database_measure_candidates(inputs)

    assert result["candidates"] == []
    serialized = canonical_catalog_bytes(result)
    assert b'"aggregate_type":"sum"' not in serialized
    assert b'"aggregate_type":"average"' not in serialized


def test_machine_explicit_hkb_average_with_resolved_same_grain_binding_is_eligible() -> (
    None
):
    inputs = _database_inputs(
        schema_records=[
            _table("requests", primary=("id",)),
            _column("requests", "id"),
            _column("requests", "latency_ms", "NUMERIC"),
        ],
        hkb_records=[_hkb("Average latency = AVG(latency_ms).")],
        mapping_records=[_mapping()],
        views=[_view("requests", "id", "latency_ms")],
    )

    result = propose_database_measure_candidates(inputs)
    hkb_candidate = next(
        item
        for item in result["candidates"]
        if item["candidate_class"] == "hkb_aggregate"
    )

    assert hkb_candidate["measure"]["definition"]["aggregate_type"] == "average"
    assert hkb_candidate["measure"]["definition"]["sql"] == (
        "${db_public__requests.latency_ms}"
    )
    assert hkb_candidate["evidence"]["hkb_stable_id"] == "db:hkb:1"


@pytest.mark.parametrize(
    ("hkb", "mapping", "reason"),
    [
        (
            _hkb("The average latency observed by requests."),
            _mapping(),
            "aggregation_not_machine_explicit",
        ),
        (
            _hkb("Average latency = AVG(latency_ms)."),
            _mapping(target=None, relationship_requirements=("target_grain",)),
            "grain_or_relationship_unresolved",
        ),
        (
            _hkb("Average latency = AVG(latency_ms).", dependencies=("db:hkb:2",)),
            _mapping(dependencies=("db:hkb:2",)),
            "dependency_unresolved",
        ),
        (
            _hkb("Average latency = AVG(unknown_role)."),
            _mapping(),
            "aggregate_binding_unresolved",
        ),
    ],
)
def test_hkb_semantics_are_screened_out_instead_of_guessed(
    hkb: dict[str, object], mapping: dict[str, object], reason: str
) -> None:
    inputs = _database_inputs(
        schema_records=[
            _table("requests", primary=("id",)),
            _column("requests", "id"),
            _column("requests", "latency_ms", "NUMERIC"),
        ],
        hkb_records=[hkb],
        mapping_records=[mapping],
        views=[_view("requests", "id", "latency_ms")],
    )

    result = propose_database_measure_candidates(inputs)

    assert not any(
        item["candidate_class"] == "hkb_aggregate" for item in result["candidates"]
    )
    assert result["screening"]["hkb_aggregate"][reason] == 1
    screened = next(
        item
        for item in result["screened"]
        if item["candidate_class"] == "hkb_aggregate"
    )
    assert screened["source_stable_id"] == hkb["stable_id"]
    assert screened["reason"] == reason


def test_catalog_order_ids_and_bytes_are_deterministic() -> None:
    left = _database_inputs(
        schema_records=[
            _table("zebra", primary=("id",)),
            _column("zebra", "id"),
            _table("alpha", primary=("id",)),
            _column("alpha", "id"),
        ],
        views=[_view("zebra", "id"), _view("alpha", "id")],
    )
    right = copy.deepcopy(left)
    right["schema_records"].reverse()
    right["views"].reverse()

    first = build_measure_review_catalog([left])
    second = build_measure_review_catalog([right])

    assert canonical_catalog_bytes(first) == canonical_catalog_bytes(second)
    ids = [item["candidate_id"] for item in first["candidates"]]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert all(item.startswith("r2m1-") and len(item) == 69 for item in ids)
    assert first["manifest"]["catalog_sha256"] == second["manifest"]["catalog_sha256"]


def test_forbidden_benchmark_fields_are_rejected_recursively() -> None:
    inputs = _database_inputs(
        schema_records=[_table("orders", primary=("id",)), _column("orders", "id")],
        views=[_view("orders", "id")],
    )
    inputs["schema_records"][0]["nested"] = {"gold_sql": "SELECT secret"}

    with pytest.raises(MeasureCatalogError, match="gold_sql"):
        propose_database_measure_candidates(inputs)


def test_target_config_cannot_smuggle_question_or_outcome_inputs(
    tmp_path: Path,
) -> None:
    config = tmp_path / "targets.json"
    config.write_text(
        json.dumps(
            {
                "databases": ["db"],
                "kind": "r2-public-evidence-measure-targets",
                "question_path": "data/manifests/eligible_questions.jsonl",
                "schema_version": 1,
            }
        )
    )

    with pytest.raises(MeasureCatalogError, match="unsupported fields"):
        generate_workspace_measure_review_catalog(tmp_path, config)


def test_writer_is_append_only_and_mode_0600(tmp_path: Path) -> None:
    catalog = build_measure_review_catalog(
        [
            _database_inputs(
                schema_records=[
                    _table("orders", primary=("id",)),
                    _column("orders", "id"),
                ],
                views=[_view("orders", "id")],
            )
        ]
    )
    destination = tmp_path / "catalog.json"

    write_measure_review_catalog(destination, catalog)

    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.read_bytes() == canonical_catalog_bytes(catalog)
    with pytest.raises(MeasureCatalogError, match="refusing overwrite"):
        write_measure_review_catalog(destination, catalog)


def test_workspace_generation_is_public_only_complete_and_read_only(
    tmp_path: Path,
) -> None:
    target_config = (
        REPOSITORY_ROOT
        / "config/conditions/r2-public-evidence-measure-databases-v1.json"
    )
    semantic_root = REPOSITORY_ROOT / "semantic_models"
    before = _tree_digest(semantic_root)

    first = generate_workspace_measure_review_catalog(REPOSITORY_ROOT, target_config)
    second = generate_workspace_measure_review_catalog(REPOSITORY_ROOT, target_config)

    assert first["manifest"]["database_count"] == 16
    assert first["manifest"]["databases"] == sorted(first["manifest"]["databases"])
    assert canonical_catalog_bytes(first) == canonical_catalog_bytes(second)
    assert _tree_digest(semantic_root) == before
    assert first["candidates"]
    serialized = canonical_catalog_bytes(first)
    for forbidden in (
        b'"instance_id"',
        b'"question"',
        b'"correctness"',
        b'"outcome"',
        b'"gold_sql"',
        b'"test_cases"',
    ):
        assert forbidden not in serialized
    output = tmp_path / "catalog.json"
    write_measure_review_catalog(output, first)
    assert json.loads(output.read_bytes()) == first


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()

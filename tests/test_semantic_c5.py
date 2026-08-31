from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from omni_benchmark.omni_semantic_deployment import (
    OmniSemanticDeploymentError,
    build_semantic_deployment_plan,
    verify_semantic_deployment_readback,
)
from omni_benchmark.semantic_bundle import SemanticBundleError
from omni_benchmark.semantic_c5 import compile_c5_tuned_bundle


def _hkb_records() -> list[dict[str, object]]:
    return [
        {
            "database": "db",
            "definition": "Index = resolution * 2.",
            "description": "A row-level resolution index.",
            "dependency_stable_ids": [],
            "hkb_id": 0,
            "knowledge": "Resolution Index",
            "provenance": {"content": "public_hkb"},
            "stable_id": "db:hkb:0",
        },
        {
            "database": "db",
            "definition": "Values below 1.0 preserve fine detail.",
            "description": "Interprets scan resolution values.",
            "dependency_stable_ids": [],
            "hkb_id": 20,
            "knowledge": "Scan Resolution",
            "provenance": {"content": "public_hkb"},
            "stable_id": "db:hkb:20",
        },
        {
            "database": "db",
            "definition": "A site is premium when its name is registered.",
            "dependency_depth": 0,
            "description": "Classifies excavation sites.",
            "dependency_stable_ids": [],
            "hkb_id": 30,
            "knowledge": "Premium Site",
            "provenance": {"content": "public_hkb"},
            "stable_id": "db:hkb:30",
        },
        {
            "database": "db",
            "definition": "Coverage = scans per site divided by site count.",
            "dependency_depth": 1,
            "description": "Cross-grain coverage ratio.",
            "dependency_stable_ids": [],
            "hkb_id": 40,
            "knowledge": "Site Coverage",
            "provenance": {"content": "public_hkb"},
            "stable_id": "db:hkb:40",
        },
        {
            "database": "db",
            "definition": "A region groups every site inside one survey boundary.",
            "dependency_depth": 0,
            "description": "Scopes knowledge to a whole table.",
            "dependency_stable_ids": [],
            "hkb_id": 50,
            "knowledge": "Region Grouping",
            "provenance": {"content": "public_hkb"},
            "stable_id": "db:hkb:50",
        },
    ]


def _schema_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = [
        {
            "database": "db",
            "identifier": {"name": "pointcloud"},
            "primary_key_column_stable_ids": ["db:column:pointcloud:id"],
            "record_kind": "table",
            "stable_id": "db:table:pointcloud",
            "unique_keys": [],
        },
        {
            "database": "db",
            "description": "Point-cloud identifier.",
            "identifier": {"name": "id"},
            "nullable": False,
            "record_kind": "column",
            "stable_id": "db:column:pointcloud:id",
            "table_stable_id": "db:table:pointcloud",
        },
        {
            "database": "db",
            "description": "Referenced site identifier.",
            "identifier": {"name": "site_id"},
            "nullable": True,
            "record_kind": "column",
            "stable_id": "db:column:pointcloud:site_id",
            "table_stable_id": "db:table:pointcloud",
        },
        {
            "database": "db",
            "description": "JSONB scan measurements.",
            "identifier": {"name": "cloud_metrics"},
            "nullable": True,
            "record_kind": "column",
            "stable_id": "db:column:pointcloud:cloud_metrics",
            "table_stable_id": "db:table:pointcloud",
        },
        {
            "column_stable_id": "db:column:pointcloud:cloud_metrics",
            "database": "db",
            "description": "REAL. Scan resolution in millimeters.",
            "path": [{"key": "Scan_Resol_Mm", "kind": "object_key"}],
            "record_kind": "structured_leaf",
            "stable_id": "db:leaf:resolution",
        },
        {
            "column_stable_id": "db:column:pointcloud:cloud_metrics",
            "database": "db",
            "description": "REAL. Point density per square meter.",
            "path": [{"key": "Point_Dense", "kind": "object_key"}],
            "record_kind": "structured_leaf",
            "stable_id": "db:leaf:density",
        },
        {
            "database": "db",
            "identifier": {"name": "sites"},
            "primary_key_column_stable_ids": ["db:column:sites:id"],
            "record_kind": "table",
            "stable_id": "db:table:sites",
            "unique_keys": [],
        },
        {
            "database": "db",
            "description": "Site identifier.",
            "identifier": {"name": "id"},
            "nullable": False,
            "record_kind": "column",
            "stable_id": "db:column:sites:id",
            "table_stable_id": "db:table:sites",
        },
        {
            "database": "db",
            "description": "Registered site name.",
            "identifier": {"name": "name"},
            "nullable": False,
            "record_kind": "column",
            "stable_id": "db:column:sites:name",
            "table_stable_id": "db:table:sites",
        },
        {
            "database": "db",
            "description": "Referenced region identifier.",
            "identifier": {"name": "region_id"},
            "nullable": True,
            "record_kind": "column",
            "stable_id": "db:column:sites:region_id",
            "table_stable_id": "db:table:sites",
        },
        {
            "database": "db",
            "description": "Parent site identifier.",
            "identifier": {"name": "parent_site_id"},
            "nullable": True,
            "record_kind": "column",
            "stable_id": "db:column:sites:parent_site_id",
            "table_stable_id": "db:table:sites",
        },
        {
            "database": "db",
            "identifier": {"name": "regions"},
            "primary_key_column_stable_ids": ["db:column:regions:id"],
            "record_kind": "table",
            "stable_id": "db:table:regions",
            "unique_keys": [],
        },
        {
            "database": "db",
            "description": "Region identifier.",
            "identifier": {"name": "id"},
            "nullable": False,
            "record_kind": "column",
            "stable_id": "db:column:regions:id",
            "table_stable_id": "db:table:regions",
        },
        {
            "database": "db",
            "description": "Region name.",
            "identifier": {"name": "name"},
            "nullable": False,
            "record_kind": "column",
            "stable_id": "db:column:regions:name",
            "table_stable_id": "db:table:regions",
        },
        {
            "database": "db",
            "identifier": {"name": "measurements"},
            "primary_key_column_stable_ids": ["db:column:measurements:id"],
            "record_kind": "table",
            "stable_id": "db:table:measurements",
            "unique_keys": [],
        },
        {
            "database": "db",
            "description": "Measurement identifier.",
            "identifier": {"name": "id"},
            "nullable": False,
            "record_kind": "column",
            "stable_id": "db:column:measurements:id",
            "table_stable_id": "db:table:measurements",
        },
        {
            "database": "db",
            "description": "REAL. Flux in watts per square meter.",
            "identifier": {"name": "flux_w/m²", "quoted": True},
            "nullable": True,
            "record_kind": "column",
            "stable_id": "db:column:measurements:flux",
            "table_stable_id": "db:table:measurements",
        },
        {
            "database": "db",
            "provenance": {"content": ["public_schema"]},
            "record_kind": "foreign_key",
            "source_column_stable_ids": ["db:column:pointcloud:site_id"],
            "source_table_stable_id": "db:table:pointcloud",
            "stable_id": "db:foreign-key:a-site",
            "target_column_stable_ids": ["db:column:sites:id"],
            "target_table_stable_id": "db:table:sites",
        },
        {
            "database": "db",
            "provenance": {"content": ["public_schema"]},
            "record_kind": "foreign_key",
            "source_column_stable_ids": ["db:column:pointcloud:site_id"],
            "source_table_stable_id": "db:table:pointcloud",
            "stable_id": "db:foreign-key:b-site-duplicate",
            "target_column_stable_ids": ["db:column:sites:id"],
            "target_table_stable_id": "db:table:sites",
        },
        {
            "database": "db",
            "provenance": {"content": ["public_schema"]},
            "record_kind": "foreign_key",
            "source_column_stable_ids": ["db:column:sites:region_id"],
            "source_table_stable_id": "db:table:sites",
            "stable_id": "db:foreign-key:c-region",
            "target_column_stable_ids": ["db:column:regions:id"],
            "target_table_stable_id": "db:table:regions",
        },
        {
            "database": "db",
            "provenance": {"content": ["public_schema"]},
            "record_kind": "foreign_key",
            "source_column_stable_ids": ["db:column:sites:parent_site_id"],
            "source_table_stable_id": "db:table:sites",
            "stable_id": "db:foreign-key:d-self",
            "target_column_stable_ids": ["db:column:sites:id"],
            "target_table_stable_id": "db:table:sites",
        },
    ]
    for record in records:
        record["schema_version"] = 1
    return records


def _camel_case_schema_records() -> list[dict[str, object]]:
    """Add a table whose physical name is CamelCase, as several databases have."""
    records = _schema_records()
    added: list[dict[str, object]] = [
        {
            "database": "db",
            "identifier": {"name": "FieldNotes"},
            "primary_key_column_stable_ids": ["db:column:FieldNotes:id"],
            "record_kind": "table",
            "stable_id": "db:table:FieldNotes",
            "unique_keys": [],
        },
        {
            "database": "db",
            "description": "Field note identifier.",
            "identifier": {"name": "id"},
            "nullable": False,
            "record_kind": "column",
            "stable_id": "db:column:FieldNotes:id",
            "table_stable_id": "db:table:FieldNotes",
        },
        {
            "database": "db",
            "description": "Referenced site identifier.",
            "identifier": {"name": "site_id"},
            "nullable": True,
            "record_kind": "column",
            "stable_id": "db:column:FieldNotes:site_id",
            "table_stable_id": "db:table:FieldNotes",
        },
        {
            "database": "db",
            "provenance": {"content": ["public_schema"]},
            "record_kind": "foreign_key",
            "source_column_stable_ids": ["db:column:FieldNotes:site_id"],
            "source_table_stable_id": "db:table:FieldNotes",
            "stable_id": "db:foreign-key:e-field-notes-site",
            "target_column_stable_ids": ["db:column:sites:id"],
            "target_table_stable_id": "db:table:sites",
        },
    ]
    for record in added:
        record["schema_version"] = 1
    return records + added


def _base_mapping(hkb_id: int) -> dict[str, object]:
    return {
        "database": "db",
        "dependency_audit": {
            "missing_references": [],
            "redundant_references": [],
        },
        "dependency_hkb_stable_ids": [],
        "generality": "database_specific_legitimate_modeling",
        "hkb_stable_id": f"db:hkb:{hkb_id}",
        "notes": "Synthetic public-only mapping.",
        "provenance": {
            "content": ["public_hkb", "public_schema", "public_column_metadata"],
            "intervention": "human_general_modeling_inference",
            "sources": {
                "hkb_stable_id": f"db:hkb:{hkb_id}",
                "schema_stable_ids": [],
            },
            "transformation_class": "interpretive",
        },
        "schema_version": 1,
    }


def _mapping_records() -> list[dict[str, object]]:
    compiled = _base_mapping(0)
    compiled.update(
        {
            "dependency_mode": "same_grain",
            "disposition": "compile",
            "loss_codes": [],
            "relationship_requirements": [],
            "representation": "numeric_derived_dimension",
            "semantic_name": "resolution_index",
            "source_bindings": [
                {
                    "confidence": "exact",
                    "role": "resolution_mm",
                    "schema_stable_id": "db:leaf:resolution",
                }
            ],
            "target_table_stable_id": "db:table:pointcloud",
        }
    )
    compiled["provenance"]["sources"]["schema_stable_ids"] = ["db:leaf:resolution"]
    context = _base_mapping(20)
    context.update(
        {
            "dependency_mode": "none",
            "disposition": "context_only",
            "loss_codes": ["context_only_no_executable_object"],
            "relationship_requirements": [],
            "representation": "field_context",
            "semantic_name": None,
            "source_bindings": [
                {
                    "confidence": "exact",
                    "role": "target",
                    "schema_stable_id": "db:leaf:resolution",
                }
            ],
            "target_table_stable_id": "db:table:pointcloud",
        }
    )
    context["provenance"]["sources"]["schema_stable_ids"] = ["db:leaf:resolution"]
    deferred = _base_mapping(30)
    deferred.update(
        {
            "dependency_mode": "cross_grain_unresolved",
            "disposition": "defer_cross_grain",
            "loss_codes": ["cardinality_unknown"],
            "relationship_requirements": [
                "target_grain",
                "relationship_path",
                "cardinality",
            ],
            "representation": None,
            "semantic_name": None,
            "source_bindings": [
                {
                    "confidence": "exact",
                    "role": "site_name",
                    "schema_stable_id": "db:column:sites:name",
                }
            ],
            "target_table_stable_id": None,
        }
    )
    deferred["provenance"]["sources"]["schema_stable_ids"] = ["db:column:sites:name"]
    unsupported = _base_mapping(40)
    unsupported.update(
        {
            "dependency_mode": "blocked",
            "disposition": "unsupported",
            "loss_codes": ["aggregation_unspecified"],
            "relationship_requirements": [],
            "representation": None,
            "semantic_name": None,
            "source_bindings": [
                {
                    "confidence": "exact",
                    "role": "scan",
                    "schema_stable_id": "db:column:pointcloud:site_id",
                },
                {
                    "confidence": "exact",
                    "role": "site",
                    "schema_stable_id": "db:column:sites:id",
                },
            ],
            "target_table_stable_id": None,
        }
    )
    unsupported["provenance"]["sources"]["schema_stable_ids"] = [
        "db:column:pointcloud:site_id",
        "db:column:sites:id",
    ]
    table_scoped = _base_mapping(50)
    table_scoped.update(
        {
            "dependency_mode": "cross_grain_unresolved",
            "disposition": "defer_cross_grain",
            "loss_codes": ["cardinality_unknown"],
            "relationship_requirements": [
                "target_grain",
                "relationship_path",
                "cardinality",
            ],
            "representation": None,
            "semantic_name": None,
            "source_bindings": [
                {
                    "confidence": "exact",
                    "role": "region",
                    "schema_stable_id": "db:table:regions",
                }
            ],
            "target_table_stable_id": None,
        }
    )
    table_scoped["provenance"]["sources"]["schema_stable_ids"] = ["db:table:regions"]
    return [compiled, context, deferred, unsupported, table_scoped]


def _spec() -> dict[str, object]:
    return {
        "catalog": "db",
        "database": "db",
        "format_version": 1,
        "schema": "public",
        "views": [
            {
                "description": "Point-cloud records at one row per scan artifact.",
                "file_name": "db.public__pointcloud.view",
                "label": "Point Clouds",
                "table_stable_id": "db:table:pointcloud",
                "topic_file_name": "pointcloud_semantics.topic",
                "view_name": "db_public__pointcloud",
            }
        ],
        "physical_fields": [
            {
                "name": "scan_resolution_mm",
                "schema_stable_id": "db:leaf:resolution",
                "sql": (
                    "CAST(${cloud_metrics} ->> 'Scan_Resol_Mm' AS DOUBLE PRECISION)"
                ),
            }
        ],
        "derived_fields": [
            {
                "hkb_stable_id": "db:hkb:0",
                "sql": "${scan_resolution_mm} * 2.0",
            }
        ],
    }


def _compile():
    return compile_c5_tuned_bundle(
        _spec(), _hkb_records(), _schema_records(), _mapping_records()
    )


def test_c5_widens_views_to_every_public_table() -> None:
    bundle = _compile()

    for name in (
        "db.public__sites.view",
        "db.public__regions.view",
        "db.public__measurements.view",
        "sites_semantics.topic",
        "regions_semantics.topic",
        "measurements_semantics.topic",
    ):
        assert name in bundle.files
    sites = yaml.safe_load(bundle.files["db.public__sites.view"])
    assert set(sites["dimensions"]) == {"id", "name", "region_id", "parent_site_id"}
    assert sites["dimensions"]["name"]["description"] == "Registered site name."
    assert bundle.manifest["c5"]["widening"]["views_added"] == 3


def test_c5_names_camel_case_tables_the_way_omni_names_them() -> None:
    """Omni derives a view's name by snake-casing it, so the bundle must too."""
    bundle = compile_c5_tuned_bundle(
        _spec(), _hkb_records(), _camel_case_schema_records(), _mapping_records()
    )

    assert "db.public__field_notes.view" in bundle.files
    assert "field_notes_semantics.topic" in bundle.files
    assert "db.public__FieldNotes.view" not in bundle.files
    view = yaml.safe_load(bundle.files["db.public__field_notes.view"])
    assert view["table_name"] == "FieldNotes"
    assert view["label"] == "FieldNotes"
    relationships = yaml.safe_load(bundle.files["relationships"])
    assert ("db_public__field_notes", "db_public__sites") in [
        (item["join_from_view"], item["join_to_view"]) for item in relationships
    ]
    topic = yaml.safe_load(bundle.files["field_notes_semantics.topic"])
    assert topic["base_view"] == "db_public__field_notes"


def test_c5_auto_publishes_undeclared_columns_and_leaves_on_declared_views() -> None:
    bundle = _compile()

    pointcloud = yaml.safe_load(bundle.files["db.public__pointcloud.view"])
    dimensions = pointcloud["dimensions"]
    assert "id" in dimensions and "site_id" in dimensions
    assert dimensions["cloud_metrics_point_dense"]["sql"] == (
        "JSONB_EXTRACT_PATH_TEXT(cloud_metrics, 'Point_Dense')"
    )
    assert "resolution_index" in dimensions
    assert "Scan Resolution" in dimensions["scan_resolution_mm"]["ai_context"]


def test_c5_declares_deduplicated_directional_joins() -> None:
    bundle = _compile()

    relationships = yaml.safe_load(bundle.files["relationships"])
    assert [
        (item["join_from_view"], item["join_to_view"]) for item in relationships
    ] == [
        ("db_public__pointcloud", "db_public__sites"),
        ("db_public__sites", "db_public__regions"),
    ]
    skipped = {
        item["foreign_key_stable_id"]: item["reason"]
        for item in bundle.manifest["c5"]["relationships_skipped"]
    }
    assert skipped == {
        "db:foreign-key:b-site-duplicate": "duplicate_pair",
        "db:foreign-key:d-self": "self_join_unsupported",
    }
    assert len(bundle.manifest["relationship_contracts"]) == 2
    assert bundle.manifest["validation"]["joins_generated"] is True


def test_c5_topic_join_tree_is_transitive() -> None:
    bundle = _compile()

    topic = yaml.safe_load(bundle.files["pointcloud_semantics.topic"])
    assert topic["joins"] == {"db_public__sites": {"db_public__regions": {}}}
    assert topic["fields"] == [
        "db_public__pointcloud.*",
        "db_public__regions.*",
        "db_public__sites.*",
    ]
    leaf_topic = yaml.safe_load(bundle.files["measurements_semantics.topic"])
    assert leaf_topic["joins"] == {}
    assert "no cross-table joins" in leaf_topic["ai_context"]


def test_c5_ports_deferred_hkb_to_owning_topic_context() -> None:
    bundle = _compile()

    topic = yaml.safe_load(bundle.files["sites_semantics.topic"])
    assert (
        "Premium Site: A site is premium when its name is registered."
        in topic["ai_context"]
    )


def test_c5_ports_cross_table_hkb_to_model_context() -> None:
    bundle = _compile()

    model = yaml.safe_load(bundle.files["model"])
    assert set(model) == {"ai_context"}
    assert (
        "Site Coverage: Coverage = scans per site divided by site count."
        in model["ai_context"]
    )
    assert bundle.manifest["c5"]["context_port"] == {
        "model_level": 1,
        "topic_level": 2,
    }


def test_c5_routes_table_scoped_hkb_to_that_tables_topic() -> None:
    """Public HKB may bind a whole table, not only a column or leaf."""
    bundle = _compile()

    topic = yaml.safe_load(bundle.files["regions_semantics.topic"])
    assert (
        "Region Grouping: A region groups every site inside one survey boundary."
        in topic["ai_context"]
    )


def test_c5_injects_unrepresentable_quoted_column() -> None:
    bundle = _compile()

    measurements = yaml.safe_load(bundle.files["db.public__measurements.view"])
    assert measurements["dimensions"]["flux_w_m"] == {
        "description": "REAL. Flux in watts per square meter.",
        "sql": '"flux_w/m²"',
    }
    assert bundle.manifest["c5"]["widening"]["unrepresentable_fields_injected"] == 1
    assert {
        "field_name": "flux_w_m",
        "file": "db.public__measurements.view",
        "source_stable_id": "db:column:measurements:flux",
        "sql": '"flux_w/m\u00b2"',
    } in bundle.manifest["direct_physical_bindings"]


def test_c5_field_kinds_classify_the_injected_unrepresentable_column() -> None:
    """A dimension the spec cannot name is still classified, not silently absent."""
    bundle = _compile()

    measurements = yaml.safe_load(bundle.files["db.public__measurements.view"])
    assert set(bundle.field_kinds["db:table:measurements"]).issuperset(
        measurements["dimensions"]
    )
    # The fixture column declares no type, so the compiler cannot classify it.
    assert bundle.field_kinds["db:table:measurements"]["flux_w_m"] == "unknown"
    assert "field_kinds" not in bundle.manifest


def test_c5_refuses_an_unattested_physical_column_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lint runs at compile time so no unrestorable document is ever uploaded."""
    from omni_benchmark import semantic_c5

    original = semantic_c5._inject_unrepresentable_fields

    def unattested(
        files: dict[str, str], views: object, schema_index: object, injections: object
    ) -> tuple[list[dict[str, str]], list[tuple[str, str, str]]]:
        _bindings, kinds = original(files, views, schema_index, injections)
        return [], kinds

    monkeypatch.setattr(semantic_c5, "_inject_unrepresentable_fields", unattested)

    with pytest.raises(SemanticBundleError, match="attested direct binding"):
        _compile()


def test_c5_injected_column_reads_back_when_omni_strips_its_sql(
    tmp_path: Path,
) -> None:
    """Omni resolves a bare column reference itself and drops the binding."""
    bundle = _compile()
    root = tmp_path / "bundle"
    root.mkdir()
    for name, content in bundle.files.items():
        (root / name).write_text(content)
    (root / "manifest.json").write_text(json.dumps(bundle.manifest))
    plan = build_semantic_deployment_plan(root)
    view = next(
        item for item in plan.files if item.local_name == "db.public__measurements.view"
    )

    stripped = yaml.safe_load(view.content)
    del stripped["dimensions"]["flux_w_m"]["sql"]
    readback = {item.remote_path: item.content for item in plan.files}
    readback[view.remote_path] = yaml.safe_dump(stripped, allow_unicode=True)

    verify_semantic_deployment_readback(plan, readback)


def test_c5_keeps_baseline_topic_guidance_for_modeled_fields() -> None:
    bundle = _compile()

    topic = yaml.safe_load(bundle.files["pointcloud_semantics.topic"])
    assert "resolution_index" in topic["ai_context"]
    assert "declared joins" in topic["ai_context"]


def test_c5_manifest_reports_budget_and_is_deterministic() -> None:
    first = _compile()
    second = _compile()

    assert first.files == second.files
    assert first.manifest == second.manifest
    c5 = first.manifest["c5"]
    assert c5["ai_context_chars"] > 0
    assert c5["ai_context_soft_budget_exceeded"] is False
    validation = first.manifest["validation"]
    assert validation["hkb_context_ported"] is True
    assert validation["relationship_contracts_public_only"] is True


def test_c5_hard_budget_rejects_oversized_context() -> None:
    hkb = _hkb_records()
    oversized = next(item for item in hkb if item["stable_id"] == "db:hkb:40")
    oversized["definition"] = "x" * 200_000

    with pytest.raises(SemanticBundleError, match="hard budget"):
        compile_c5_tuned_bundle(_spec(), hkb, _schema_records(), _mapping_records())


def test_c5_bundle_deploys_and_reads_back_with_model_file(tmp_path: Path) -> None:
    bundle = _compile()
    root = tmp_path / "bundle"
    root.mkdir()
    for name, content in bundle.files.items():
        (root / name).write_text(content)
    (root / "manifest.json").write_text(json.dumps(bundle.manifest))

    plan = build_semantic_deployment_plan(root)

    assert {item.remote_path for item in plan.files} >= {"model", "relationships"}
    readback = {item.remote_path: item.content for item in plan.files}
    verify_semantic_deployment_readback(plan, readback)


def test_deployment_rejects_malformed_model_document(tmp_path: Path) -> None:
    bundle = _compile()
    files = dict(bundle.files)
    files["model"] = yaml.safe_dump({"ai_context": "ok", "extra": 1})
    manifest = copy.deepcopy(bundle.manifest)
    for record in manifest["files"]:
        if record["file"] == "model":
            import hashlib

            record["sha256"] = hashlib.sha256(files["model"].encode()).hexdigest()
            record["size_bytes"] = len(files["model"].encode())
    root = tmp_path / "bundle"
    root.mkdir()
    for name, content in files.items():
        (root / name).write_text(content)
    (root / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(
        OmniSemanticDeploymentError, match="model document must declare"
    ):
        build_semantic_deployment_plan(root)

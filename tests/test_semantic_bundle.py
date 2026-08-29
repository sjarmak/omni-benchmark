from __future__ import annotations

import copy

import pytest
import yaml

from omni_benchmark.semantic_bundle import (
    SemanticBundleError,
    compile_e02_relationship_bundle,
    compile_semantic_bundle,
)


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
    ]


def _schema_records() -> list[dict[str, object]]:
    return [
        {
            "database": "db",
            "identifier": {"name": "pointcloud"},
            "record_kind": "table",
            "stable_id": "db:table:pointcloud",
        },
        {
            "database": "db",
            "description": "JSONB scan measurements.",
            "identifier": {"name": "cloud_metrics"},
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
            "database": "db",
            "identifier": {"name": "unmodeled"},
            "record_kind": "table",
            "stable_id": "db:table:unmodeled",
        },
        {
            "database": "db",
            "description": "A value on an intentionally unmodeled table.",
            "identifier": {"name": "value"},
            "record_kind": "column",
            "stable_id": "db:column:unmodeled:value",
            "table_stable_id": "db:table:unmodeled",
        },
    ]


def _compiled_mapping() -> dict[str, object]:
    return {
        "database": "db",
        "dependency_audit": {
            "missing_references": [],
            "redundant_references": [],
        },
        "dependency_hkb_stable_ids": [],
        "dependency_mode": "same_grain",
        "disposition": "compile",
        "generality": "database_specific_legitimate_modeling",
        "hkb_stable_id": "db:hkb:0",
        "loss_codes": [],
        "notes": "Synthetic public-only same-grain definition.",
        "provenance": {
            "content": [
                "public_hkb",
                "public_schema",
                "public_column_metadata",
            ],
            "intervention": "human_general_modeling_inference",
            "sources": {
                "hkb_stable_id": "db:hkb:0",
                "schema_stable_ids": ["db:leaf:resolution"],
            },
            "transformation_class": "interpretive",
        },
        "relationship_requirements": [],
        "representation": "numeric_derived_dimension",
        "schema_version": 1,
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


def _context_mapping() -> dict[str, object]:
    return {
        "database": "db",
        "dependency_audit": {
            "missing_references": [],
            "redundant_references": [],
        },
        "dependency_hkb_stable_ids": [],
        "dependency_mode": "none",
        "disposition": "context_only",
        "generality": "database_specific_legitimate_modeling",
        "hkb_stable_id": "db:hkb:20",
        "loss_codes": ["context_only_no_executable_object"],
        "notes": "Synthetic public-only field context.",
        "provenance": {
            "content": [
                "public_hkb",
                "public_schema",
                "public_column_metadata",
            ],
            "intervention": "human_general_modeling_inference",
            "sources": {
                "hkb_stable_id": "db:hkb:20",
                "schema_stable_ids": ["db:leaf:resolution"],
            },
            "transformation_class": "interpretive",
        },
        "relationship_requirements": [],
        "representation": "field_context",
        "schema_version": 1,
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


def _mapping_records() -> list[dict[str, object]]:
    return [_compiled_mapping(), _context_mapping()]


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
                "sql": "CAST(${cloud_metrics} ->> 'Scan_Resol_Mm' AS DOUBLE PRECISION)",
            }
        ],
        "derived_fields": [
            {
                "hkb_stable_id": "db:hkb:0",
                "sql": "${scan_resolution_mm} * 2.0",
            }
        ],
    }


def _e02_inputs():
    spec = copy.deepcopy(_spec())
    spec["views"].append(
        {
            "description": "Sites referenced by point-cloud records.",
            "file_name": "db.public__sites.view",
            "label": "Sites",
            "table_stable_id": "db:table:sites",
            "topic_file_name": "sites_semantics.topic",
            "view_name": "db_public__sites",
        }
    )
    schema = copy.deepcopy(_schema_records())
    for record in schema:
        record["schema_version"] = 1
    pointcloud = next(
        record for record in schema if record["stable_id"] == "db:table:pointcloud"
    )
    pointcloud["primary_key_column_stable_ids"] = ["db:column:pointcloud:id"]
    pointcloud["unique_keys"] = []
    unmodeled = next(
        record for record in schema if record["stable_id"] == "db:table:unmodeled"
    )
    unmodeled["primary_key_column_stable_ids"] = []
    unmodeled["unique_keys"] = []
    schema.extend(
        [
            {
                "database": "db",
                "description": "Point-cloud identifier.",
                "identifier": {"name": "id"},
                "nullable": False,
                "record_kind": "column",
                "schema_version": 1,
                "stable_id": "db:column:pointcloud:id",
                "table_stable_id": "db:table:pointcloud",
            },
            {
                "database": "db",
                "description": "Referenced site identifier.",
                "identifier": {"name": "site_id"},
                "nullable": True,
                "record_kind": "column",
                "schema_version": 1,
                "stable_id": "db:column:pointcloud:site_id",
                "table_stable_id": "db:table:pointcloud",
            },
            {
                "database": "db",
                "identifier": {"name": "sites"},
                "primary_key_column_stable_ids": ["db:column:sites:id"],
                "record_kind": "table",
                "schema_version": 1,
                "stable_id": "db:table:sites",
                "unique_keys": [],
            },
            {
                "database": "db",
                "description": "Site identifier.",
                "identifier": {"name": "id"},
                "nullable": False,
                "record_kind": "column",
                "schema_version": 1,
                "stable_id": "db:column:sites:id",
                "table_stable_id": "db:table:sites",
            },
            {
                "database": "db",
                "provenance": {"content": ["public_schema"]},
                "record_kind": "foreign_key",
                "schema_version": 1,
                "source_column_stable_ids": ["db:column:pointcloud:site_id"],
                "source_table_stable_id": "db:table:pointcloud",
                "stable_id": "db:foreign-key:site",
                "target_column_stable_ids": ["db:column:sites:id"],
                "target_table_stable_id": "db:table:sites",
            },
        ]
    )
    for record in schema:
        if record.get("record_kind") == "column":
            record.setdefault("nullable", False)
    return spec, schema


def test_e02_compiler_emits_only_directional_public_relationships() -> None:
    spec, schema = _e02_inputs()

    baseline = compile_semantic_bundle(spec, _hkb_records(), schema, _mapping_records())
    candidate = compile_e02_relationship_bundle(
        spec, _hkb_records(), schema, _mapping_records()
    )

    assert "relationships" not in baseline.files
    assert baseline.manifest["validation"]["joins_generated"] is False
    assert yaml.safe_load(candidate.files["relationships"]) == [
        {
            "join_from_view": "db_public__pointcloud",
            "join_to_view": "db_public__sites",
            "join_type": "always_left",
            "on_sql": "${db_public__pointcloud.site_id} = ${db_public__sites.id}",
            "relationship_type": "many_to_one",
            "reversible": False,
        }
    ]
    source_topic = yaml.safe_load(candidate.files["pointcloud_semantics.topic"])
    target_topic = yaml.safe_load(candidate.files["sites_semantics.topic"])
    assert source_topic["joins"] == {"db_public__sites": {}}
    assert target_topic["joins"] == {}
    assert candidate.manifest["validation"]["joins_generated"] is True
    assert candidate.manifest["relationship_contracts"] == [
        {
            "cardinality": "many_to_one",
            "foreign_key_stable_id": "db:foreign-key:site",
            "provenance": {"content": ["public_schema"]},
            "source_match": "zero_or_one",
            "source_table_stable_id": "db:table:pointcloud",
            "target_table_stable_id": "db:table:sites",
        }
    ]


def test_compile_bundle_emits_executable_field_context_topic_and_provenance() -> None:
    bundle = compile_semantic_bundle(
        _spec(), _hkb_records(), _schema_records(), _mapping_records()
    )

    assert tuple(bundle.files) == (
        "db.public__pointcloud.view",
        "pointcloud_semantics.topic",
    )
    view = yaml.safe_load(bundle.files["db.public__pointcloud.view"])
    assert view["catalog"] == "db"
    assert view["schema"] == "public"
    assert view["table_name"] == "pointcloud"
    assert view["dimensions"]["resolution_index"]["sql"] == (
        "${scan_resolution_mm} * 2.0"
    )
    assert all(
        "data_type" not in dimension for dimension in view["dimensions"].values()
    )
    assert "Values below 1.0" in view["dimensions"]["scan_resolution_mm"]["ai_context"]
    topic = yaml.safe_load(bundle.files["pointcloud_semantics.topic"])
    assert topic["base_view"] == "db_public__pointcloud"
    assert topic["fields"] == ["db_public__pointcloud.*"]
    assert topic["joins"] == {}
    assert "resolution_index" in topic["ai_context"]
    assert bundle.manifest["validation"] == {
        "all_compile_mappings_materialized": True,
        "hidden_annotations_used": False,
        "joins_generated": False,
        "public_inputs_only": True,
        "status": "passed",
    }
    _assert_semantic_elements(bundle.manifest["semantic_elements"])


def test_compile_bundle_normalizes_physical_names_and_emits_explicit_alias_sql() -> (
    None
):
    schema = _schema_records()
    schema.extend(
        [
            {
                "database": "db",
                "description": "Process compliance state.",
                "identifier": {"name": "procComp", "quoted": True},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:procComp",
                "table_stable_id": "db:table:pointcloud",
            },
            {
                "database": "db",
                "description": "Route complexity state.",
                "identifier": {"name": "RouteComplex", "quoted": True},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:RouteComplex",
                "table_stable_id": "db:table:pointcloud",
            },
            {
                "database": "db",
                "description": "Total findings.",
                "identifier": {"name": "FINDTALLY", "quoted": True},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:FINDTALLY",
                "table_stable_id": "db:table:pointcloud",
            },
        ]
    )
    spec = copy.deepcopy(_spec())
    spec["physical_fields"].extend(
        [
            {
                "name": "procComp",
                "schema_stable_id": "db:column:pointcloud:procComp",
            },
            {
                "name": "route_complexity",
                "schema_stable_id": "db:column:pointcloud:RouteComplex",
            },
            {
                "name": "FINDTALLY",
                "schema_stable_id": "db:column:pointcloud:FINDTALLY",
            },
        ]
    )

    bundle = compile_semantic_bundle(spec, _hkb_records(), schema, _mapping_records())

    view = yaml.safe_load(bundle.files["db.public__pointcloud.view"])
    assert "procComp" not in view["dimensions"]
    assert view["dimensions"]["proc_comp"] == {
        "description": "Process compliance state.",
        "sql": '"procComp"',
    }
    assert view["dimensions"]["findtally"] == {
        "description": "Total findings.",
        "sql": '"FINDTALLY"',
    }
    assert view["dimensions"]["route_complexity"]["sql"] == '"RouteComplex"'
    assert bundle.manifest["direct_physical_bindings"] == [
        {
            "field_name": "findtally",
            "file": "db.public__pointcloud.view",
            "source_stable_id": "db:column:pointcloud:FINDTALLY",
            "sql": '"FINDTALLY"',
        },
        {
            "field_name": "proc_comp",
            "file": "db.public__pointcloud.view",
            "source_stable_id": "db:column:pointcloud:procComp",
            "sql": '"procComp"',
        },
        {
            "field_name": "route_complexity",
            "file": "db.public__pointcloud.view",
            "source_stable_id": "db:column:pointcloud:RouteComplex",
            "sql": '"RouteComplex"',
        },
    ]


def test_compile_bundle_does_not_mark_authored_or_derived_sql_as_direct_binding() -> (
    None
):
    bundle = compile_semantic_bundle(
        _spec(), _hkb_records(), _schema_records(), _mapping_records()
    )

    assert bundle.manifest["direct_physical_bindings"] == []


def test_compile_bundle_rewrites_derived_references_to_normalized_physical_names() -> (
    None
):
    spec = copy.deepcopy(_spec())
    spec["physical_fields"][0]["name"] = "scanResolutionMm"
    spec["derived_fields"][0]["sql"] = "${scanResolutionMm} * 2.0"

    bundle = compile_semantic_bundle(
        spec, _hkb_records(), _schema_records(), _mapping_records()
    )

    view = yaml.safe_load(bundle.files["db.public__pointcloud.view"])
    assert "scanResolutionMm" not in view["dimensions"]
    assert view["dimensions"]["resolution_index"]["sql"] == (
        "${scan_resolution_mm} * 2.0"
    )


def test_compile_bundle_rejects_normalized_physical_name_collisions() -> None:
    schema = _schema_records()
    schema.extend(
        [
            {
                "database": "db",
                "description": "First value.",
                "identifier": {"name": "first_value"},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:first_value",
                "table_stable_id": "db:table:pointcloud",
            },
            {
                "database": "db",
                "description": "Second value.",
                "identifier": {"name": "second_value"},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:second_value",
                "table_stable_id": "db:table:pointcloud",
            },
        ]
    )
    spec = copy.deepcopy(_spec())
    spec["physical_fields"].extend(
        [
            {
                "name": "procComp",
                "schema_stable_id": "db:column:pointcloud:first_value",
            },
            {
                "name": "proc_comp",
                "schema_stable_id": "db:column:pointcloud:second_value",
            },
        ]
    )

    with pytest.raises(SemanticBundleError, match="normalized physical field"):
        compile_semantic_bundle(spec, _hkb_records(), schema, _mapping_records())


def test_compile_bundle_allows_unused_normalized_source_column_collisions() -> None:
    schema = _schema_records()
    schema.extend(
        [
            {
                "database": "db",
                "description": "First source.",
                "identifier": {"name": "procComp"},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:procComp",
                "table_stable_id": "db:table:pointcloud",
            },
            {
                "database": "db",
                "description": "Second source.",
                "identifier": {"name": "proc_comp"},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:proc_comp",
                "table_stable_id": "db:table:pointcloud",
            },
        ]
    )

    bundle = compile_semantic_bundle(
        _spec(), _hkb_records(), schema, _mapping_records()
    )

    assert "db.public__pointcloud.view" in bundle.files
    assert bundle.manifest["representability"] == {
        "normalized_source_name_collisions": [
            {
                "omni_field_name": "proc_comp",
                "source_stable_ids": [
                    "db:column:pointcloud:procComp",
                    "db:column:pointcloud:proc_comp",
                ],
                "table_stable_id": "db:table:pointcloud",
            }
        ]
    }


def test_compile_bundle_rejects_modeled_ambiguous_source_column() -> None:
    schema = _schema_records()
    schema.extend(
        [
            {
                "database": "db",
                "description": "First source.",
                "identifier": {"name": "procComp"},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:procComp",
                "table_stable_id": "db:table:pointcloud",
            },
            {
                "database": "db",
                "description": "Second source.",
                "identifier": {"name": "proc_comp"},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:proc_comp",
                "table_stable_id": "db:table:pointcloud",
            },
        ]
    )
    spec = copy.deepcopy(_spec())
    spec["physical_fields"].append(
        {
            "name": "proc_comp",
            "schema_stable_id": "db:column:pointcloud:procComp",
        }
    )

    with pytest.raises(
        SemanticBundleError,
        match="modeled source field proc_comp is ambiguous",
    ):
        compile_semantic_bundle(spec, _hkb_records(), schema, _mapping_records())


def test_compile_bundle_rejects_alias_that_shadows_another_source_column() -> None:
    schema = _schema_records()
    schema.extend(
        [
            {
                "database": "db",
                "description": "Route complexity source.",
                "identifier": {"name": "RouteComplex"},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:RouteComplex",
                "table_stable_id": "db:table:pointcloud",
            },
            {
                "database": "db",
                "description": "Existing field with the requested alias name.",
                "identifier": {"name": "route_complexity"},
                "record_kind": "column",
                "stable_id": "db:column:pointcloud:route_complexity",
                "table_stable_id": "db:table:pointcloud",
            },
        ]
    )
    spec = copy.deepcopy(_spec())
    spec["physical_fields"].append(
        {
            "name": "route_complexity",
            "schema_stable_id": "db:column:pointcloud:RouteComplex",
        }
    )

    with pytest.raises(SemanticBundleError, match="shadows source field"):
        compile_semantic_bundle(spec, _hkb_records(), schema, _mapping_records())


def test_compile_bundle_emits_parser_bypass_only_for_allowlisted_physical_sql() -> None:
    spec = copy.deepcopy(_spec())
    spec["physical_fields"][0]["omni_parser_mode"] = "do_not_parse"

    bundle = compile_semantic_bundle(
        spec, _hkb_records(), _schema_records(), _mapping_records()
    )

    raw_view = bundle.files["db.public__pointcloud.view"]
    view = yaml.safe_load(raw_view)
    assert view["dimensions"]["scan_resolution_mm"]["sql"] == (
        "-- DO NOT PARSE\n"
        "CAST(${cloud_metrics} ->> 'Scan_Resol_Mm' AS DOUBLE PRECISION)"
    )
    assert "-- DO NOT PARSE" in raw_view
    assert view["dimensions"]["resolution_index"]["sql"] == (
        "${scan_resolution_mm} * 2.0"
    )


@pytest.mark.parametrize("parser_mode", (None, "", "parse", True, 1))
def test_compile_bundle_rejects_unknown_physical_parser_mode(
    parser_mode: object,
) -> None:
    spec = copy.deepcopy(_spec())
    spec["physical_fields"][0]["omni_parser_mode"] = parser_mode

    with pytest.raises(
        SemanticBundleError,
        match="omni_parser_mode must be exactly do_not_parse",
    ):
        compile_semantic_bundle(
            spec, _hkb_records(), _schema_records(), _mapping_records()
        )


def test_compile_bundle_rejects_parser_mode_without_physical_sql() -> None:
    spec = copy.deepcopy(_spec())
    del spec["physical_fields"][0]["sql"]
    spec["physical_fields"][0]["omni_parser_mode"] = "do_not_parse"

    with pytest.raises(
        SemanticBundleError,
        match="omni_parser_mode requires physical field sql",
    ):
        compile_semantic_bundle(
            spec, _hkb_records(), _schema_records(), _mapping_records()
        )


@pytest.mark.parametrize("field_kind", ("physical_fields", "derived_fields"))
def test_compile_bundle_rejects_injected_omni_parser_directive(
    field_kind: str,
) -> None:
    spec = copy.deepcopy(_spec())
    spec[field_kind][0]["sql"] = "-- DO NOT PARSE\n${scan_resolution_mm} * 2.0"

    with pytest.raises(
        SemanticBundleError,
        match="reserved Omni parser directive in field SQL",
    ):
        compile_semantic_bundle(
            spec, _hkb_records(), _schema_records(), _mapping_records()
        )


def _assert_semantic_elements(elements: object) -> None:
    assert elements == [
        {
            "content_provenance": [
                "public_column_metadata",
                "public_hkb",
                "public_schema",
            ],
            "hkb_stable_id": "db:hkb:0",
            "intervention_provenance": "human_general_modeling_inference",
            "kind": "derived_dimension",
            "loss_codes": [],
            "semantic_name": "resolution_index",
            "table_stable_id": "db:table:pointcloud",
        },
        {
            "content_provenance": [
                "public_column_metadata",
                "public_hkb",
                "public_schema",
            ],
            "hkb_stable_id": "db:hkb:20",
            "intervention_provenance": "human_general_modeling_inference",
            "kind": "field_context",
            "loss_codes": ["context_only_no_executable_object"],
            "semantic_name": "scan_resolution_mm",
            "table_stable_id": "db:table:pointcloud",
        },
    ]


def _dependent_inputs() -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    spec = copy.deepcopy(_spec())
    hkb = copy.deepcopy(_hkb_records())
    mappings = copy.deepcopy(_mapping_records())
    dependent_hkb = copy.deepcopy(hkb[0])
    dependent_hkb.update(
        {
            "definition": "Adjusted Index = Resolution Index + 1.",
            "dependency_stable_ids": ["db:hkb:0"],
            "hkb_id": 1,
            "knowledge": "Adjusted Index",
            "stable_id": "db:hkb:1",
        }
    )
    dependent_mapping = copy.deepcopy(mappings[0])
    dependent_mapping.update(
        {
            "dependency_hkb_stable_ids": ["db:hkb:0"],
            "hkb_stable_id": "db:hkb:1",
            "semantic_name": "adjusted_index",
        }
    )
    dependent_mapping["provenance"]["sources"]["hkb_stable_id"] = "db:hkb:1"
    hkb.append(dependent_hkb)
    mappings.append(dependent_mapping)
    spec["derived_fields"].append(
        {"hkb_stable_id": "db:hkb:1", "sql": "${resolution_index} + 1.0"}
    )
    return spec, hkb, _schema_records(), mappings


def test_compile_bundle_rejects_missing_declared_dependency_reference() -> None:
    spec, hkb, schema, mappings = _dependent_inputs()
    spec["derived_fields"][1]["sql"] = "${scan_resolution_mm} + 1.0"

    with pytest.raises(
        SemanticBundleError, match="missing declared dependency.*resolution_index"
    ):
        compile_semantic_bundle(spec, hkb, schema, mappings)


def test_compile_bundle_rejects_undeclared_derived_dependency_reference() -> None:
    spec, hkb, schema, mappings = _dependent_inputs()
    hkb[2]["dependency_stable_ids"] = []
    mappings[2]["dependency_hkb_stable_ids"] = []

    with pytest.raises(
        SemanticBundleError, match="undeclared derived dependency.*resolution_index"
    ):
        compile_semantic_bundle(spec, hkb, schema, mappings)


def test_compile_bundle_is_byte_deterministic() -> None:
    first = compile_semantic_bundle(
        _spec(), _hkb_records(), _schema_records(), _mapping_records()
    )
    second = compile_semantic_bundle(
        _spec(), _hkb_records(), _schema_records(), _mapping_records()
    )

    assert second.files == first.files
    assert second.manifest == first.manifest


def test_compile_bundle_ignores_unsafe_physical_names_on_unmodeled_tables() -> None:
    schema = _schema_records()
    schema[-1]["identifier"]["name"] = "MassTransferRate_solar_masses/year"

    bundle = compile_semantic_bundle(
        _spec(), _hkb_records(), schema, _mapping_records()
    )

    assert "db.public__pointcloud.view" in bundle.files


def test_compile_bundle_rejects_unsafe_physical_name_on_modeled_table() -> None:
    schema = _schema_records()
    schema[1]["identifier"]["name"] = "unsafe/name"

    with pytest.raises(SemanticBundleError, match="column name must be a safe"):
        compile_semantic_bundle(_spec(), _hkb_records(), schema, _mapping_records())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda spec: spec["derived_fields"].clear(),
            "compile mappings and derived fields must match exactly",
        ),
        (
            lambda spec: spec["derived_fields"][0].update(
                {"sql": "${missing_field} * 2.0"}
            ),
            "unknown field reference missing_field",
        ),
        (
            lambda spec: spec.update({"external_knowledge": [0]}),
            "protected field external_knowledge",
        ),
        (
            lambda spec: spec["views"][0].update({"file_name": "../escape.view"}),
            "one safe file name",
        ),
    ],
)
def test_compile_bundle_rejects_invalid_or_privileged_spec(
    mutation: object, message: str
) -> None:
    spec = copy.deepcopy(_spec())
    mutation(spec)

    with pytest.raises(SemanticBundleError, match=message):
        compile_semantic_bundle(
            spec, _hkb_records(), _schema_records(), _mapping_records()
        )


def test_compile_bundle_rejects_context_without_physical_field() -> None:
    spec = _spec()
    spec["physical_fields"] = []

    with pytest.raises(
        SemanticBundleError,
        match="context target db:leaf:resolution has no physical field",
    ):
        compile_semantic_bundle(
            spec, _hkb_records(), _schema_records(), _mapping_records()
        )


PROTECTED_FIELDS = (
    "expected_result",
    "external_knowledge",
    "gold_result",
    "gold_sql",
    "oracle_hint",
    "oracle_sql",
    "sol_sql",
    "test_case",
    "test_cases",
    "test_correctness",
)


@pytest.mark.parametrize("protected_field", PROTECTED_FIELDS)
@pytest.mark.parametrize("input_name", ("spec", "hkb", "schema", "mapping"))
def test_compile_bundle_rejects_protected_fields_in_every_input(
    protected_field: str, input_name: str
) -> None:
    inputs = {
        "spec": copy.deepcopy(_spec()),
        "hkb": copy.deepcopy(_hkb_records()),
        "schema": copy.deepcopy(_schema_records()),
        "mapping": copy.deepcopy(_mapping_records()),
    }
    target = inputs[input_name]
    if isinstance(target, list):
        target[0]["nested"] = {protected_field: "DO-NOT-INSPECT"}
    else:
        target["nested"] = {protected_field: "DO-NOT-INSPECT"}

    with pytest.raises(SemanticBundleError, match=f"protected field {protected_field}"):
        compile_semantic_bundle(
            inputs["spec"], inputs["hkb"], inputs["schema"], inputs["mapping"]
        )


@pytest.mark.parametrize(
    "sql",
    (
        "1; DROP TABLE important",
        "(SELECT secret FROM private_table LIMIT 1)",
        "secret_column + 1",
        "*",
        "1 AS alias",
        "COUNT(*)",
        "EXISTS(SELECT 1)",
    ),
)
@pytest.mark.parametrize("field_kind", ("physical_fields", "derived_fields"))
def test_compile_bundle_rejects_non_scalar_or_unmodeled_sql(
    sql: str, field_kind: str
) -> None:
    spec = copy.deepcopy(_spec())
    spec[field_kind][0]["sql"] = sql

    with pytest.raises(SemanticBundleError, match="one modeled scalar expression"):
        compile_semantic_bundle(
            spec, _hkb_records(), _schema_records(), _mapping_records()
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda records: records[1].update({"loss_codes": []}),
            "lacks explicit non-executable loss",
        ),
        (
            lambda records: records[0]["provenance"].update(
                {"content": ["public_hkb", "train_gold_sql"]}
            ),
            "invalid content provenance",
        ),
        (
            lambda records: records[0].update({"loss_codes": ["source_field_missing"]}),
            "non-executable loss",
        ),
    ],
)
def test_compile_bundle_authenticates_mapping_contract(
    mutation: object, message: str
) -> None:
    mappings = copy.deepcopy(_mapping_records())
    mutation(mappings)

    with pytest.raises(SemanticBundleError, match=message):
        compile_semantic_bundle(_spec(), _hkb_records(), _schema_records(), mappings)


def test_compile_bundle_rejects_compile_target_without_view() -> None:
    mappings = copy.deepcopy(_mapping_records())
    mappings[0]["source_bindings"] = [
        {
            "confidence": "exact",
            "role": "value",
            "schema_stable_id": "db:column:unmodeled:value",
        }
    ]
    mappings[0]["provenance"]["sources"]["schema_stable_ids"] = [
        "db:column:unmodeled:value"
    ]
    mappings[0]["target_table_stable_id"] = "db:table:unmodeled"

    with pytest.raises(
        SemanticBundleError, match="compile mapping target.*has no view"
    ):
        compile_semantic_bundle(_spec(), _hkb_records(), _schema_records(), mappings)

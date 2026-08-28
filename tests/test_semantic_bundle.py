from __future__ import annotations

import copy

import pytest
import yaml

from omni_benchmark.semantic_bundle import (
    SemanticBundleError,
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

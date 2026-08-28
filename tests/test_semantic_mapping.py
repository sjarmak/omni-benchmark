from __future__ import annotations

from copy import deepcopy

import pytest

from omni_benchmark.semantic_mapping import (
    SemanticMappingError,
    compile_mapping_spec,
    encode_mapping_jsonl,
    validate_mapping_records,
)


DATABASE = "alpha_large"
TABLE = f"{DATABASE}:table:measurements"
OTHER_TABLE = f"{DATABASE}:table:other"
COLUMN = f"{DATABASE}:column:measurements:value"
OTHER_COLUMN = f"{DATABASE}:column:other:value"


def _hkb(hkb_id: int, dependencies: list[int]) -> dict[str, object]:
    return {
        "database": DATABASE,
        "dependency_stable_ids": [f"{DATABASE}:hkb:{item}" for item in dependencies],
        "hkb_id": hkb_id,
        "source_type": "calculation_knowledge",
        "stable_id": f"{DATABASE}:hkb:{hkb_id}",
    }


def _schema() -> list[dict[str, object]]:
    return [
        {
            "database": DATABASE,
            "record_kind": "table",
            "stable_id": TABLE,
        },
        {
            "database": DATABASE,
            "record_kind": "column",
            "stable_id": COLUMN,
            "table_stable_id": TABLE,
        },
        {
            "database": DATABASE,
            "record_kind": "table",
            "stable_id": OTHER_TABLE,
        },
        {
            "database": DATABASE,
            "record_kind": "column",
            "stable_id": OTHER_COLUMN,
            "table_stable_id": OTHER_TABLE,
        },
    ]


def _mapping(
    hkb_id: int,
    *,
    dependencies: list[int] | None = None,
    disposition: str = "compile",
    representation: str | None = "numeric_derived_dimension",
    semantic_name: str | None = None,
    target_table: str | None = TABLE,
    schema_ids: list[str] | None = None,
    dependency_mode: str = "same_grain",
    loss_codes: list[str] | None = None,
    relationship_requirements: list[str] | None = None,
    missing_dependencies: list[int] | None = None,
    redundant_dependencies: list[int] | None = None,
) -> dict[str, object]:
    stable_id = f"{DATABASE}:hkb:{hkb_id}"
    inputs = schema_ids if schema_ids is not None else [COLUMN]
    return {
        "database": DATABASE,
        "dependency_hkb_stable_ids": [
            f"{DATABASE}:hkb:{item}" for item in dependencies or []
        ],
        "dependency_mode": dependency_mode,
        "disposition": disposition,
        "dependency_audit": {
            "missing_references": [
                f"{DATABASE}:hkb:{item}" for item in missing_dependencies or []
            ],
            "redundant_references": [
                f"{DATABASE}:hkb:{item}" for item in redundant_dependencies or []
            ],
        },
        "generality": "database_specific_legitimate_modeling",
        "hkb_stable_id": stable_id,
        "loss_codes": loss_codes or [],
        "notes": "Synthetic public-only mapping decision.",
        "provenance": {
            "content": ["public_hkb", "public_schema", "public_column_metadata"],
            "intervention": "human_general_modeling_inference",
            "sources": {
                "hkb_stable_id": stable_id,
                "schema_stable_ids": inputs,
            },
            "transformation_class": "interpretive",
        },
        "relationship_requirements": relationship_requirements or [],
        "representation": representation,
        "schema_version": 1,
        "semantic_name": semantic_name
        or (f"metric_{hkb_id}" if disposition == "compile" else None),
        "source_bindings": [
            {
                "confidence": "exact",
                "role": f"input_{index}",
                "schema_stable_id": schema_id,
            }
            for index, schema_id in enumerate(inputs)
        ],
        "target_table_stable_id": target_table,
    }


def test_complete_same_grain_mapping_contract_is_valid() -> None:
    hkb_records = [_hkb(0, []), _hkb(1, [0])]
    mappings = [_mapping(0), _mapping(1, dependencies=[0])]

    summary = validate_mapping_records(hkb_records, _schema(), mappings)

    assert summary == {
        "database": DATABASE,
        "dispositions": {"compile": 2},
        "hkb_nodes": 2,
        "representations": {"numeric_derived_dimension": 2},
    }


def test_mapping_requires_complete_hkb_coverage() -> None:
    with pytest.raises(SemanticMappingError, match="missing HKB mappings.*hkb:1"):
        validate_mapping_records([_hkb(0, []), _hkb(1, [])], _schema(), [_mapping(0)])


def test_mapping_dependencies_must_match_public_hkb_exactly() -> None:
    with pytest.raises(SemanticMappingError, match="dependency list mismatch"):
        validate_mapping_records(
            [_hkb(0, []), _hkb(1, [0])], _schema(), [_mapping(0), _mapping(1)]
        )


def test_direct_hkb_dependencies_must_resolve() -> None:
    mapping = _mapping(
        0,
        dependencies=[99],
        disposition="unsupported",
        representation=None,
        target_table=None,
        dependency_mode="blocked",
        loss_codes=["source_field_missing"],
    )

    with pytest.raises(SemanticMappingError, match="unknown HKB dependency.*hkb:99"):
        validate_mapping_records([_hkb(0, [99])], _schema(), [mapping])


def test_compile_disposition_rejects_cross_grain_inputs() -> None:
    mapping = _mapping(0, schema_ids=[COLUMN, OTHER_COLUMN])

    with pytest.raises(SemanticMappingError, match="outside target table"):
        validate_mapping_records([_hkb(0, [])], _schema(), [mapping])


def test_compile_disposition_rejects_missing_source_loss() -> None:
    mapping = _mapping(0, loss_codes=["source_field_missing"])

    with pytest.raises(SemanticMappingError, match="non-executable loss"):
        validate_mapping_records([_hkb(0, [])], _schema(), [mapping])


def test_mapping_provenance_must_match_declared_sources() -> None:
    mapping = _mapping(0)
    tampered = deepcopy(mapping)
    tampered["provenance"]["sources"]["schema_stable_ids"] = []

    with pytest.raises(SemanticMappingError, match="provenance schema sources"):
        validate_mapping_records([_hkb(0, [])], _schema(), [tampered])


def test_source_bindings_require_unique_roles_and_schema_ids() -> None:
    mapping = _mapping(0, schema_ids=[COLUMN, OTHER_COLUMN])
    mapping["source_bindings"][1]["role"] = "input_0"

    with pytest.raises(SemanticMappingError, match="source bindings must be unique"):
        validate_mapping_records([_hkb(0, [])], _schema(), [mapping])


def test_dependency_audit_distinguishes_missing_and_redundant_references() -> None:
    hkb_records = [_hkb(0, []), _hkb(1, [0]), _hkb(2, [])]
    mappings = [
        _mapping(0),
        _mapping(
            1,
            dependencies=[0],
            redundant_dependencies=[0],
            loss_codes=["dependency_redundancy"],
        ),
        _mapping(
            2,
            disposition="unsupported",
            representation=None,
            semantic_name=None,
            target_table=None,
            schema_ids=[],
            dependency_mode="blocked",
            loss_codes=["dependency_omission"],
            missing_dependencies=[1],
        ),
    ]

    summary = validate_mapping_records(hkb_records, _schema(), mappings)

    assert summary["hkb_nodes"] == 3


def test_cross_grain_deferral_requires_relationship_contract() -> None:
    mapping = _mapping(
        0,
        disposition="defer_cross_grain",
        representation=None,
        target_table=None,
        dependency_mode="cross_grain_unresolved",
        loss_codes=["cross_grain_no_identity"],
    )

    with pytest.raises(SemanticMappingError, match="relationship requirements"):
        validate_mapping_records([_hkb(0, [])], _schema(), [mapping])


@pytest.mark.parametrize(
    ("disposition", "representation", "target", "dependency_mode"),
    [
        ("context_only", "field_context", TABLE, "none"),
        ("unsupported", None, None, "blocked"),
    ],
)
def test_non_executable_mapping_requires_explicit_loss(
    disposition: str,
    representation: str | None,
    target: str | None,
    dependency_mode: str,
) -> None:
    mapping = _mapping(
        0,
        disposition=disposition,
        representation=representation,
        target_table=target,
        dependency_mode=dependency_mode,
        loss_codes=[],
    )

    with pytest.raises(SemanticMappingError, match="explicit non-executable loss"):
        validate_mapping_records([_hkb(0, [])], _schema(), [mapping])


def test_dependency_audit_and_loss_code_must_correspond() -> None:
    mapping = _mapping(
        0,
        disposition="unsupported",
        representation=None,
        target_table=None,
        dependency_mode="blocked",
        loss_codes=["source_field_missing"],
        missing_dependencies=[1],
    )

    with pytest.raises(SemanticMappingError, match="dependency omission mismatch"):
        validate_mapping_records(
            [_hkb(0, []), _hkb(1, [])], _schema(), [mapping, _mapping(1)]
        )


def test_mapping_spec_expands_aliases_and_public_provenance() -> None:
    spec = {
        "database": DATABASE,
        "records": [
            {
                "bindings": [
                    {
                        "alias": "VALUE",
                        "confidence": "exact",
                        "role": "input_value",
                    }
                ],
                "dependency_audit": {
                    "missing_ids": [],
                    "redundant_ids": [],
                },
                "dependency_mode": "same_grain",
                "disposition": "compile",
                "hkb_id": 0,
                "loss_codes": ["omni_expression_support_unverified"],
                "notes": "A reviewed public-only same-grain definition.",
                "relationship_requirements": [],
                "representation": "numeric_derived_dimension",
                "semantic_name": "metric_0",
                "target_alias": "TABLE",
            }
        ],
        "schema_aliases": {"TABLE": TABLE, "VALUE": COLUMN},
        "schema_version": 1,
    }

    records = compile_mapping_spec(spec, [_hkb(0, [])], _schema())

    assert records[0]["source_bindings"] == [
        {"confidence": "exact", "role": "input_value", "schema_stable_id": COLUMN}
    ]
    assert records[0]["provenance"]["sources"]["schema_stable_ids"] == [COLUMN]
    assert encode_mapping_jsonl(records).endswith(b"\n")


def test_mapping_spec_rejects_unknown_schema_alias() -> None:
    spec = {
        "database": DATABASE,
        "records": [
            {
                "bindings": [],
                "dependency_audit": {"missing_ids": [], "redundant_ids": []},
                "dependency_mode": "same_grain",
                "disposition": "compile",
                "hkb_id": 0,
                "loss_codes": [],
                "notes": "Invalid target alias.",
                "relationship_requirements": [],
                "representation": "numeric_derived_dimension",
                "semantic_name": "metric_0",
                "target_alias": "MISSING",
            }
        ],
        "schema_aliases": {},
        "schema_version": 1,
    }

    with pytest.raises(SemanticMappingError, match="unknown schema alias MISSING"):
        compile_mapping_spec(spec, [_hkb(0, [])], _schema())


def test_mapping_spec_rejects_mismatched_hkb_namespace() -> None:
    hkb = _hkb(0, [])
    hkb["stable_id"] = "other_large:hkb:0"

    with pytest.raises(SemanticMappingError, match="HKB stable ID namespace"):
        compile_mapping_spec(
            {
                "database": DATABASE,
                "records": [],
                "schema_aliases": {},
                "schema_version": 1,
            },
            [hkb],
            _schema(),
        )


def test_mapping_spec_rejects_mixed_schema_database() -> None:
    schema = _schema()
    schema[1]["database"] = "other_large"

    with pytest.raises(SemanticMappingError, match="schema database mismatch"):
        compile_mapping_spec(
            {
                "database": DATABASE,
                "records": [],
                "schema_aliases": {},
                "schema_version": 1,
            },
            [_hkb(0, [])],
            schema,
        )


@pytest.mark.parametrize(
    ("disposition", "dependency_mode", "representation", "target", "losses"),
    [
        (
            "context_only",
            "none",
            "field_context",
            TABLE,
            ["context_only_no_executable_object"],
        ),
        (
            "defer_cross_grain",
            "cross_grain_unresolved",
            None,
            None,
            ["cross_grain_no_identity"],
        ),
        (
            "unsupported",
            "blocked",
            None,
            None,
            ["source_field_missing"],
        ),
    ],
)
def test_non_compile_disposition_contracts(
    disposition: str,
    dependency_mode: str,
    representation: str | None,
    target: str | None,
    losses: list[str],
) -> None:
    mapping = _mapping(
        0,
        disposition=disposition,
        representation=representation,
        target_table=target,
        dependency_mode=dependency_mode,
        loss_codes=losses,
        relationship_requirements=(
            ["target_grain", "relationship_path", "cardinality"]
            if disposition == "defer_cross_grain"
            else []
        ),
    )

    summary = validate_mapping_records([_hkb(0, [])], _schema(), [mapping])

    assert summary["dispositions"] == {disposition: 1}

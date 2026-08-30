from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from omni_benchmark.omni_result_adapter import (
    OmniResultContractError,
    bind_typed_query_result,
    build_replayed_result_artifact,
    decode_result_artifact_rows,
    parse_omni_job_result,
)


def _query_action(
    *,
    csv_result: str,
    query: dict[str, object],
    total_row_count: int,
    truncated: bool = False,
    status: str = "success",
) -> dict[str, object]:
    return {
        "message": "I ran a governed query.",
        "result": {
            "csvResult": csv_result,
            "csvResultWasTruncated": truncated,
            "hasResults": total_row_count > 0,
            "query": query,
            "queryName": "Governed answer",
            "resultId": "result-private-1",
            "status": status,
            "totalRowCount": total_row_count,
        },
        "timestamp": "2026-08-27T12:00:01Z",
        "type": "generate_query",
    }


def _plan(*fields: tuple[str, str]) -> dict[str, object]:
    names = [name for name, _ in fields]
    return {
        "query": {"model_job": {"fields": names}},
        "status": "PLANNED",
        "summary": {
            "fields": {
                name: {
                    "data_type": data_type,
                    "fully_qualified_name": name,
                }
                for name, data_type in fields
            },
            "invalid_calculations": {},
            "missing_fields": [],
        },
    }


def test_truncated_final_preview_binds_complete_metadata_typed_rerun() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="Number,Numeric-looking code,Enabled,Day,Observed at\n",
                    query={
                        "fields": [
                            "answer.number",
                            "answer.code",
                            "answer.enabled",
                            "answer.day",
                            "answer.observed_at",
                        ]
                    },
                    total_row_count=1,
                    truncated=True,
                )
            ]
        }
    )

    parsed = bind_typed_query_result(
        parsed_query,
        [
            {
                "Number": "12.500",
                "Numeric-looking code": "00123",
                "Enabled": True,
                "Day": "2026-08-28",
                "Observed at": "2026-08-28T13:14:15Z",
            }
        ],
        _plan(
            ("answer.number", "NUMBER"),
            ("answer.code", "STRING"),
            ("answer.enabled", "YESNO"),
            ("answer.day", "DATE"),
            ("answer.observed_at", "TIMESTAMP"),
        ),
    )

    artifact = parsed.as_result_artifact()
    assert artifact["rows"] == [
        [
            {"type": "decimal", "value": "12.500"},
            "00123",
            True,
            {"type": "date", "value": "2026-08-28"},
            {"type": "datetime", "value": "2026-08-28T13:14:15+00:00"},
        ]
    ]
    assert decode_result_artifact_rows(artifact) == (
        (
            Decimal("12.500"),
            "00123",
            True,
            date(2026, 8, 28),
            datetime(2026, 8, 28, 13, 14, 15, tzinfo=timezone.utc),
        ),
    )


def test_typed_binding_accepts_omni_boolean_metadata() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="Enabled\ntrue\n",
                    query={"fields": ["answer.enabled"]},
                    total_row_count=1,
                )
            ]
        }
    )

    parsed = bind_typed_query_result(
        parsed_query,
        [{"Enabled": True}],
        _plan(("answer.enabled", "BOOLEAN")),
    )

    assert parsed.as_result_artifact()["rows"] == [[True]]


@pytest.mark.parametrize(
    "data_type", ["BOOLEAN", "DATE", "JSON", "NUMBER", "TIMESTAMP"]
)
def test_typed_binding_treats_empty_non_string_cell_as_null(data_type: str) -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result='Value\n""\n',
                    query={"fields": ["answer.value"]},
                    total_row_count=1,
                )
            ]
        }
    )

    parsed = bind_typed_query_result(
        parsed_query,
        [{"Value": ""}],
        _plan(("answer.value", data_type)),
    )

    assert parsed.as_result_artifact()["rows"] == [[None]]


def test_typed_binding_preserves_empty_string_cell() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result='Value\n""\n',
                    query={"fields": ["answer.value"]},
                    total_row_count=1,
                )
            ]
        }
    )

    parsed = bind_typed_query_result(
        parsed_query,
        [{"Value": ""}],
        _plan(("answer.value", "STRING")),
    )

    assert parsed.as_result_artifact()["rows"] == [[""]]


def test_replayed_semantic_query_builds_type_faithful_artifact_without_csv() -> None:
    artifact = build_replayed_result_artifact(
        {"fields": ["answer.label", "answer.amount", "answer.enabled"]},
        [{"Label": "A", "Amount": "12.50", "Enabled": False}],
        _plan(
            ("answer.label", "STRING"),
            ("answer.amount", "NUMBER"),
            ("answer.enabled", "BOOLEAN"),
        ),
    )

    assert artifact == {
        "columns": ["Label", "Amount", "Enabled"],
        "rows": [["A", {"type": "decimal", "value": "12.50"}, False]],
        "schema_version": 1,
        "truncated": False,
    }


def test_replayed_semantic_query_uses_field_ids_for_empty_results() -> None:
    artifact = build_replayed_result_artifact(
        {"fields": ["answer.label"]},
        [],
        _plan(("answer.label", "STRING")),
    )

    assert artifact["columns"] == ["answer.label"]
    assert artifact["rows"] == []


@pytest.mark.parametrize(
    ("query", "rows", "plan", "message"),
    [
        (
            {"fields": ["answer.value"]},
            [{"Value": 1}],
            _plan(("answer.value", "UNKNOWN")),
            "unsupported",
        ),
        (
            {"fields": ["answer.left", "answer.right"]},
            [{"Only": 1}],
            _plan(("answer.left", "NUMBER"), ("answer.right", "NUMBER")),
            "columns",
        ),
        (
            {"fields": ["answer.value"]},
            [{"Value": 1}, {"Other": 2}],
            _plan(("answer.value", "NUMBER")),
            "columns",
        ),
    ],
)
def test_replayed_semantic_query_rejects_ambiguous_results(
    query: dict[str, object],
    rows: list[dict[str, object]],
    plan: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(OmniResultContractError, match=message):
        build_replayed_result_artifact(query, rows, plan)


def test_parse_accepts_product_truncation_section_markers() -> None:
    parsed = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result=(
                        "Label,Value\n"
                        "# FIRST 1 ROWS:\n"
                        "first,1\n"
                        "# SAMPLED 1 ROWS FROM MIDDLE (rows 2-9):\n"
                        "middle,5\n"
                        "# LAST 1 ROWS:\n"
                        "last,10\n"
                    ),
                    query={"fields": ["answer.label", "answer.value"]},
                    total_row_count=10,
                    truncated=True,
                )
            ]
        }
    )

    assert parsed.expected_columns == ("Label", "Value")
    assert parsed.expected_row_count == 10


def test_parse_accepts_product_failure_action_without_timestamp() -> None:
    failure_action = {
        "durationMs": 42,
        "error": "The governed query failed validation.",
        "isError": True,
        "message": "Query failed",
        "toolName": "generate_query",
        "type": "failure",
    }
    parsed = parse_omni_job_result(
        {
            "actions": [
                failure_action,
                _query_action(
                    csv_result="answer\n2\n",
                    query={"fields": ["answer.value"]},
                    total_row_count=1,
                ),
            ]
        }
    )

    assert parsed.observed_actions_by_type == (("failure", 1), ("generate_query", 1))


def test_parse_does_not_strip_truncation_markers_from_untruncated_csv() -> None:
    action = _query_action(
        csv_result="Label,Value\n# FIRST 1 ROWS:\nfirst,1\n",
        query={"fields": ["answer.label", "answer.value"]},
        total_row_count=2,
    )

    with pytest.raises(OmniResultContractError, match="ragged"):
        parse_omni_job_result({"actions": [action]})


def test_parse_rejects_malformed_timestamp_free_failure_action() -> None:
    failure_action = {
        "durationMs": 42,
        "isError": False,
        "message": "Query failed",
        "toolName": "generate_query",
        "type": "failure",
    }

    with pytest.raises(OmniResultContractError, match="failure action"):
        parse_omni_job_result({"actions": [failure_action]})


@pytest.mark.parametrize(
    ("plan", "message"),
    [
        (_plan(("answer.value", "UNSUPPORTED")), "unsupported"),
        (_plan(), "field metadata"),
        (
            {
                **_plan(("answer.value", "NUMBER")),
                "status": "COMPLETE",
            },
            "PLANNED",
        ),
    ],
)
def test_typed_rerun_rejects_ambiguous_or_unsupported_plan_metadata(
    plan: dict[str, object], message: str
) -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="Value\n1\n",
                    query={"fields": ["answer.value"]},
                    total_row_count=1,
                )
            ]
        }
    )

    with pytest.raises(OmniResultContractError, match=message):
        bind_typed_query_result(parsed_query, [{"Value": "1"}], plan)


def test_number_metadata_rejects_non_numeric_string_without_fallback() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="Value\nnot-a-number\n",
                    query={"fields": ["answer.value"]},
                    total_row_count=1,
                )
            ]
        }
    )

    with pytest.raises(OmniResultContractError, match="NUMBER"):
        bind_typed_query_result(
            parsed_query,
            [{"Value": "not-a-number"}],
            _plan(("answer.value", "NUMBER")),
        )


def test_parse_uses_last_successful_query_action_and_preserves_typed_multiset() -> None:
    first = _query_action(
        csv_result="ignored\n1\n",
        query={"fields": ["orders.count"]},
        total_row_count=1,
    )
    final_query = {
        "fields": ["orders.status", "orders.count"],
        "filters": {"orders.status": {"is": "complete"}},
    }
    final = _query_action(
        csv_result='status,count\r\ncomplete,"2,345"\r\ncomplete,"2,345"\r\n',
        query=final_query,
        total_row_count=2,
    )

    parsed_query = parse_omni_job_result(
        {
            "actions": [
                first,
                {
                    "message": "I validated the result.",
                    "timestamp": "2026-08-27T12:00:02Z",
                    "type": "validate",
                },
                final,
            ],
            "message": "Complete",
        }
    )
    parsed = bind_typed_query_result(
        parsed_query,
        [
            {"status": "complete", "count": 2345},
            {"status": "complete", "count": 2345},
        ],
        _plan(("orders.status", "STRING"), ("orders.count", "NUMBER")),
    )

    assert parsed.columns == ("status", "count")
    assert parsed.rows == (
        ("complete", {"type": "decimal", "value": "2345"}),
        ("complete", {"type": "decimal", "value": "2345"}),
    )
    assert parsed.generated_query == json.dumps(
        final_query, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert parsed.semantic_objects == ("orders.count", "orders.status")
    assert parsed.observed_actions_by_type == (
        ("generate_query", 2),
        ("validate", 1),
    )
    assert parsed.database_query_count == 2


def test_parse_supports_empty_result_with_header() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="status,count\n",
                    query={"fields": ["orders.status", "orders.count"]},
                    total_row_count=0,
                )
            ]
        }
    )
    parsed = bind_typed_query_result(
        parsed_query,
        [],
        _plan(("orders.status", "STRING"), ("orders.count", "NUMBER")),
    )

    assert parsed.columns == ("status", "count")
    assert parsed.rows == ()


def test_typed_result_preserves_json_scalar_and_nested_value_types() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result=(
                        'number,ratio,enabled,note,metadata\n42,1.25,true,,"[1,null]"\n'
                    ),
                    query={
                        "fields": [
                            "answer.number",
                            "answer.ratio",
                            "answer.enabled",
                            "answer.note",
                            "answer.metadata",
                        ]
                    },
                    total_row_count=1,
                )
            ]
        }
    )

    parsed = bind_typed_query_result(
        parsed_query,
        [
            {
                "number": 42,
                "ratio": 1.25,
                "enabled": True,
                "note": None,
                "metadata": {"items": [1, None]},
            }
        ],
        _plan(
            ("answer.number", "NUMBER"),
            ("answer.ratio", "NUMBER"),
            ("answer.enabled", "YESNO"),
            ("answer.note", "STRING"),
            ("answer.metadata", "JSON"),
        ),
    )

    assert parsed.as_result_artifact()["rows"] == [
        [
            {"type": "decimal", "value": "42"},
            {"type": "decimal", "value": "1.25"},
            True,
            None,
            {"type": "json", "value": {"items": [1, None]}},
        ]
    ]


def test_json_object_cannot_collide_with_typed_cell_encoding() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="metadata\nobject\n",
                    query={"fields": ["answer.metadata"]},
                    total_row_count=1,
                )
            ]
        }
    )
    json_value = {"type": "decimal", "value": "12"}

    parsed = bind_typed_query_result(
        parsed_query,
        [{"metadata": json_value}],
        _plan(("answer.metadata", "JSON")),
    )
    artifact = parsed.as_result_artifact()

    assert decode_result_artifact_rows(artifact) == ((json_value,),)


@pytest.mark.parametrize("missing", ["message", "timestamp"])
def test_parse_requires_every_official_action_field(missing: str) -> None:
    malformed = _query_action(
        csv_result="answer\n1\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )
    malformed.pop(missing)

    with pytest.raises(OmniResultContractError, match=missing):
        parse_omni_job_result({"actions": [malformed]})


def test_parse_requires_iso_8601_action_timestamp() -> None:
    malformed = _query_action(
        csv_result="answer\n1\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )
    malformed["timestamp"] = "not-a-timestamp"

    with pytest.raises(OmniResultContractError, match="timestamp"):
        parse_omni_job_result({"actions": [malformed]})


def test_parse_allows_schema_valid_early_error_before_final_success() -> None:
    early_error = _query_action(
        csv_result="",
        query={"fields": ["answer.value"]},
        total_row_count=0,
        status="error",
    )
    final = _query_action(
        csv_result="answer\n2\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )

    parsed = parse_omni_job_result({"actions": [early_error, final]})

    assert parsed.expected_row_count == 1
    assert parsed.agent_database_query_count == 2


def test_parse_preserves_product_error_before_final_success() -> None:
    early_error = {
        "isError": True,
        "message": "The governed query failed.",
        "result": {
            "error": {
                "detail": "The query could not be executed.",
                "message": "Query execution failed.",
            },
            "query": {"fields": ["answer.value"]},
            "queryName": "Failed governed query",
            "resultId": "result-failed-1",
            "status": "error",
        },
        "timestamp": "2026-08-27T12:00:00Z",
        "type": "generate_query",
    }
    final = _query_action(
        csv_result="answer\n2\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )

    parsed = parse_omni_job_result({"actions": [early_error, final]})

    assert parsed.expected_row_count == 1
    assert parsed.observed_actions_by_type == (("generate_query", 2),)
    assert parsed.agent_database_query_count == 2


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda action: action.pop("isError"), "failed generate_query action"),
        (lambda action: action["result"].pop("error"), "error is missing"),
        (
            lambda action: action["result"]["error"].pop("detail"),
            "error detail is missing",
        ),
        (
            lambda action: action["result"].pop("resultId"),
            "resultId is missing",
        ),
    ],
)
def test_parse_rejects_malformed_product_error_before_final_success(
    mutation: object, match: str
) -> None:
    early_error = {
        "isError": True,
        "message": "The governed query failed.",
        "result": {
            "error": {"detail": "detail", "message": "message"},
            "query": {"fields": ["answer.value"]},
            "queryName": "Failed governed query",
            "resultId": "result-failed-1",
            "status": "error",
        },
        "timestamp": "2026-08-27T12:00:00Z",
        "type": "generate_query",
    }
    assert callable(mutation)
    mutation(early_error)
    final = _query_action(
        csv_result="answer\n2\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )

    with pytest.raises(OmniResultContractError, match=match):
        parse_omni_job_result({"actions": [early_error, final]})


def test_parse_allows_earlier_truncated_success_when_final_success_is_scoreable() -> (
    None
):
    early_truncated = _query_action(
        csv_result="answer\n1\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
        truncated=True,
    )
    final = _query_action(
        csv_result="answer\n2\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )

    parsed = parse_omni_job_result({"actions": [early_truncated, final]})

    assert parsed.expected_row_count == 1


@pytest.mark.parametrize(
    "missing",
    [
        "csvResult",
        "csvResultWasTruncated",
        "hasResults",
        "query",
        "queryName",
        "status",
        "totalRowCount",
    ],
)
def test_parse_validates_every_generate_query_result_before_selection(
    missing: str,
) -> None:
    malformed = _query_action(
        csv_result="answer\n1\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )
    malformed_result = malformed["result"]
    assert isinstance(malformed_result, dict)
    malformed_result.pop(missing)
    valid = _query_action(
        csv_result="answer\n2\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )

    with pytest.raises(OmniResultContractError, match=missing):
        parse_omni_job_result({"actions": [malformed, valid]})


def test_parse_rejects_generate_query_without_result_even_before_valid_action() -> None:
    malformed = {
        "message": "I tried to query.",
        "timestamp": "2026-08-27T12:00:00Z",
        "type": "generate_query",
    }
    valid = _query_action(
        csv_result="answer\n2\n",
        query={"fields": ["answer.value"]},
        total_row_count=1,
    )

    with pytest.raises(OmniResultContractError, match="result"):
        parse_omni_job_result({"actions": [malformed, valid]})


def test_parse_rejects_recursive_forbidden_keys_before_serialization() -> None:
    action = _query_action(
        csv_result="answer\n2\n",
        query={
            "fields": ["answer.value"],
            "metadata": {"external_knowledge": ["hidden-node"]},
        },
        total_row_count=1,
    )

    with pytest.raises(OmniResultContractError, match="forbidden field"):
        parse_omni_job_result({"actions": [action]})


@pytest.mark.parametrize(
    "encoded_key",
    [
        " external_knowledge",
        "external_knowledge ",
        "gold SQL",
        "test cases",
        "oracle hint",
        "expected.result",
    ],
)
def test_parse_rejects_superficially_encoded_forbidden_keys(
    encoded_key: str,
) -> None:
    action = _query_action(
        csv_result="answer\n2\n",
        query={"fields": ["answer.value"], "metadata": {encoded_key: "hidden"}},
        total_row_count=1,
    )

    with pytest.raises(OmniResultContractError, match="forbidden field"):
        parse_omni_job_result({"actions": [action]})


def test_typed_result_rejects_recursive_forbidden_keys_before_serialization() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="answer\n2\n",
                    query={"fields": ["answer.value"]},
                    total_row_count=1,
                )
            ]
        }
    )

    with pytest.raises(OmniResultContractError, match="forbidden field"):
        bind_typed_query_result(
            parsed_query,
            [{"answer": {"external_knowledge": ["hidden-node"]}}],
            _plan(("answer.value", "NUMBER")),
        )


def test_typed_result_rejects_row_shape_or_count_mismatch() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="answer\n2\n",
                    query={"fields": ["answer.value"]},
                    total_row_count=1,
                )
            ]
        }
    )

    with pytest.raises(OmniResultContractError, match="columns"):
        bind_typed_query_result(
            parsed_query,
            [{"different": 2, "extra": 3}],
            _plan(("answer.value", "NUMBER")),
        )
    with pytest.raises(OmniResultContractError, match="row count"):
        bind_typed_query_result(
            parsed_query,
            [],
            _plan(("answer.value", "NUMBER")),
        )


def test_typed_result_uses_authoritative_json_keys_when_csv_has_friendly_labels() -> (
    None
):
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="Total Revenue\n42\n",
                    query={"fields": ["orders.total_revenue"]},
                    total_row_count=1,
                )
            ]
        }
    )

    parsed = bind_typed_query_result(
        parsed_query,
        [{"orders.total_revenue": 42}],
        _plan(("orders.total_revenue", "NUMBER")),
    )

    assert parsed.columns == ("orders.total_revenue",)
    assert parsed.rows == (({"type": "decimal", "value": "42"},),)


def test_typed_result_allows_plan_metadata_for_dependency_fields() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="Label,Value\nA,42\n",
                    query={"fields": ["answer.label", "answer.value"]},
                    total_row_count=1,
                )
            ]
        }
    )
    plan = _plan(("answer.label", "STRING"), ("answer.value", "NUMBER"))
    plan["summary"]["fields"]["answer.hidden_dependency"] = {
        "data_type": "STRING",
        "fully_qualified_name": "answer.hidden_dependency",
    }

    parsed = bind_typed_query_result(
        parsed_query,
        [{"Label": "A", "Value": 42}],
        plan,
    )

    assert parsed.rows == (("A", {"type": "decimal", "value": "42"}),)


@pytest.mark.parametrize(
    "case",
    [
        "planned_fields_mismatch",
        "duplicate_query_field",
        "empty_query_field",
        "missing_selected_metadata",
        "output_cardinality_mismatch",
    ],
)
def test_typed_result_rejects_ambiguous_selected_plan_fields(case: str) -> None:
    query_fields = ["answer.label", "answer.value"]
    csv_result = "Label,Value\nA,42\n"
    plan = _plan(("answer.label", "STRING"), ("answer.value", "NUMBER"))
    if case == "planned_fields_mismatch":
        plan["query"]["model_job"]["fields"] = list(reversed(query_fields))  # type: ignore[index]
    elif case == "duplicate_query_field":
        query_fields = ["answer.label", "answer.label"]
        plan["query"]["model_job"]["fields"] = query_fields  # type: ignore[index]
    elif case == "empty_query_field":
        query_fields = ["answer.label", ""]
        plan["query"]["model_job"]["fields"] = query_fields  # type: ignore[index]
    elif case == "missing_selected_metadata":
        del plan["summary"]["fields"]["answer.value"]  # type: ignore[index]
    else:
        query_fields = ["answer.label"]
        plan = _plan(("answer.label", "STRING"))
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result=csv_result,
                    query={"fields": query_fields},
                    total_row_count=1,
                )
            ]
        }
    )

    with pytest.raises(OmniResultContractError, match="field metadata"):
        bind_typed_query_result(
            parsed_query,
            [{"Label": "A", "Value": 42}],
            plan,
        )


def test_typed_result_rejects_non_string_data_type_metadata() -> None:
    parsed_query = parse_omni_job_result(
        {
            "actions": [
                _query_action(
                    csv_result="Value\n42\n",
                    query={"fields": ["answer.value"]},
                    total_row_count=1,
                )
            ]
        }
    )
    plan = _plan(("answer.value", "NUMBER"))
    plan["summary"]["fields"]["answer.value"]["data_type"] = 7  # type: ignore[index]

    with pytest.raises(OmniResultContractError, match="invalid data type metadata"):
        bind_typed_query_result(parsed_query, [{"Value": 42}], plan)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({"message": "Complete"}, "actions"),
        ({"actions": []}, "successful query"),
        (
            {
                "actions": [
                    _query_action(
                        csv_result="answer\n42\n",
                        query={"fields": ["answer"]},
                        total_row_count=0,
                        truncated=True,
                    )
                ]
            },
            "exceeds",
        ),
        (
            {
                "actions": [
                    _query_action(
                        csv_result="answer\n42\n",
                        query={"fields": ["answer"]},
                        total_row_count=2,
                    )
                ]
            },
            "row count",
        ),
    ],
)
def test_parse_rejects_ambiguous_or_incomplete_completed_results(
    response: dict[str, object], message: str
) -> None:
    with pytest.raises(OmniResultContractError, match=message):
        parse_omni_job_result(response)

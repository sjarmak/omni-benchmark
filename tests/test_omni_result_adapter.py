from __future__ import annotations

import json

import pytest

from omni_benchmark.omni_result_adapter import (
    OmniResultContractError,
    bind_typed_query_result,
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
    )

    assert parsed.columns == ("status", "count")
    assert parsed.rows == (("complete", 2345), ("complete", 2345))
    assert parsed.generated_query == json.dumps(
        final_query, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert parsed.semantic_objects == ("orders.count", "orders.status")
    assert parsed.observed_actions_by_type == (
        ("generate_query", 2),
        ("validate", 1),
    )
    assert parsed.database_query_count == 3


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
    parsed = bind_typed_query_result(parsed_query, [])

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
    )

    assert parsed.as_result_artifact()["rows"] == [
        [42, 1.25, True, None, {"items": [1, None]}]
    ]


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
        bind_typed_query_result(parsed_query, [{"different": 2, "extra": 3}])
    with pytest.raises(OmniResultContractError, match="row count"):
        bind_typed_query_result(parsed_query, [])


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

    parsed = bind_typed_query_result(parsed_query, [{"orders.total_revenue": 42}])

    assert parsed.columns == ("orders.total_revenue",)
    assert parsed.rows == ((42,),)


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
                        total_row_count=1,
                        truncated=True,
                    )
                ]
            },
            "truncated",
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

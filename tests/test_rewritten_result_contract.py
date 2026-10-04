from __future__ import annotations

import pytest

from omni_benchmark.rewritten_result_contract import (
    RewrittenResultContractError,
    classify_legacy_plan_boundary,
    result_page_sha256,
    summarize_result_contracts,
    validate_rewritten_result,
)


def _selected(
    name: str,
    ordinal: int,
    logical_type: str,
    *,
    nullable: bool = False,
    source_type: str | None = None,
) -> dict[str, object]:
    return {
        "logical_type": logical_type,
        "name": name,
        "nullable": nullable,
        "ordinal": ordinal,
        "semantic_role": "measure" if ordinal else "dimension",
        "source_type": source_type or logical_type,
    }


def _success(
    selected: list[dict[str, object]], rows: list[list[object]]
) -> dict[str, object]:
    envelope = {
        "schema_version": 1,
        "status": "success",
        "fields": {"selected": selected, "dependencies": []},
        "page": {
            "completeness": "complete",
            "content_sha256": result_page_sha256(selected, rows),
            "next_cursor": None,
            "returned_row_count": len(rows),
            "rows": rows,
            "total_row_count": len(rows),
        },
        "failure": None,
    }
    return envelope


def test_success_uses_selected_fields_only_and_allows_dependency_unknown() -> None:
    envelope = _success(
        [_selected("orders.revenue", 0, "decimal", nullable=True)],
        [[{"type": "decimal", "value": "12.50"}], [None]],
    )
    envelope["fields"]["dependencies"] = [
        {
            "logical_type": "unknown",
            "name": "orders.helper_expression",
            "nullable": True,
            "semantic_role": "calculation",
            "source_type": "WAREHOUSE_EXTENSION",
        }
    ]

    observation = validate_rewritten_result(envelope)

    assert observation.status == "success"
    assert observation.selected_field_count == 1
    assert observation.dependency_field_count == 1
    assert observation.selected_logical_types == ("decimal",)


def test_selected_unknown_has_total_opaque_extension_path() -> None:
    selected = _selected(
        "orders.vendor_value", 0, "unknown", source_type="VENDOR_GEOGRAPHY"
    )
    envelope = _success(
        [selected],
        [
            [
                {
                    "encoding": "json",
                    "source_type": "VENDOR_GEOGRAPHY",
                    "type": "opaque",
                    "value": {"latitude": 1.5, "longitude": 2.5},
                }
            ]
        ],
    )

    assert validate_rewritten_result(envelope).selected_logical_types == ("unknown",)

    envelope["page"]["rows"][0][0]["source_type"] = "OTHER"
    with pytest.raises(RewrittenResultContractError, match="opaque source type"):
        validate_rewritten_result(envelope)


def test_nullability_and_scalar_types_are_enforced_without_guessing() -> None:
    envelope = _success([_selected("orders.count", 0, "integer")], [[None]])
    with pytest.raises(RewrittenResultContractError, match="not nullable"):
        validate_rewritten_result(envelope)

    envelope["page"]["rows"] = [[True]]
    with pytest.raises(RewrittenResultContractError, match="integer"):
        validate_rewritten_result(envelope)


def test_paged_results_require_cursor_and_complete_results_forbid_it() -> None:
    envelope = _success([_selected("orders.id", 0, "string")], [["a"]])
    envelope["page"].update(
        {
            "completeness": "paged",
            "next_cursor": None,
            "total_row_count": None,
        }
    )
    with pytest.raises(RewrittenResultContractError, match="cursor"):
        validate_rewritten_result(envelope)

    envelope["page"]["next_cursor"] = "page-002"
    assert validate_rewritten_result(envelope).pagination == "paged"


@pytest.mark.parametrize(
    ("owner", "code"),
    [
        ("planner", "output_type_unresolved"),
        ("semantic_execution", "database_error"),
        ("transport", "provider_unavailable"),
        ("adapter", "result_cardinality_mismatch"),
    ],
)
def test_terminal_failure_codes_are_owned_and_typed(owner: str, code: str) -> None:
    envelope = {
        "schema_version": 1,
        "status": "failed",
        "fields": {"selected": [], "dependencies": []},
        "page": None,
        "failure": {"code": code, "owner": owner, "retryable": False},
    }

    observation = validate_rewritten_result(envelope)
    assert observation.failure_owner == owner
    assert observation.failure_code == code

    envelope["failure"]["code"] = "database_error"
    if owner != "semantic_execution":
        with pytest.raises(RewrittenResultContractError, match="owner"):
            validate_rewritten_result(envelope)


def test_legacy_unknown_selected_type_reproduces_planner_boundary() -> None:
    result = classify_legacy_plan_boundary(
        {"fields": ["orders.ratio"]},
        {
            "status": "PLANNED",
            "query": {"model_job": {"fields": ["orders.ratio"]}},
            "summary": {
                "fields": {
                    "orders.ratio": {"data_type": "UNKNOWN"},
                    "orders.helper": {"data_type": "NUMBER"},
                },
                "invalid_calculations": {},
                "missing_fields": [],
            },
        },
    )

    assert result == {
        "dependency_field_count": 1,
        "failure_code": "output_type_unresolved",
        "failure_owner": "planner",
        "selected_field_count": 1,
        "status": "failed",
    }


def test_aggregate_oracle_emits_no_rows_or_field_names() -> None:
    success = validate_rewritten_result(
        _success([_selected("orders.id", 0, "string")], [["one"]])
    )
    failure = validate_rewritten_result(
        {
            "schema_version": 1,
            "status": "failed",
            "fields": {"selected": [], "dependencies": []},
            "page": None,
            "failure": {
                "code": "output_type_unresolved",
                "owner": "planner",
                "retryable": False,
            },
        }
    )

    summary = summarize_result_contracts([success, failure])

    assert summary["status_counts"] == {"failed": 1, "success": 1}
    assert summary["failure_owner_counts"] == {"planner": 1}
    assert "orders.id" not in str(summary)
    assert "one" not in str(summary)

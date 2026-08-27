from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from omni_benchmark.scoring import (
    OFFICIAL_EVALUATOR_COMMIT,
    OFFICIAL_SOFT_EX_VERSION,
    SENSITIVITY_SCORER_VERSION,
    ScoringPolicyError,
    official_soft_ex_equal,
    rewrite_sql_official,
    rewrite_sql_sensitivity,
    scorer_metadata,
    sensitivity_equal,
)


def test_scorer_metadata_pins_versions_and_is_returned_by_value() -> None:
    first = scorer_metadata()
    second = scorer_metadata()

    assert first == {
        "official_soft_ex": {
            "decimal_policy": "fixed_2_half_up",
            "version": OFFICIAL_SOFT_EX_VERSION,
            "upstream_commit": OFFICIAL_EVALUATOR_COMMIT,
        },
        "sensitivity": {
            "decimal_policy": "minus_one_exact_nonnegative_half_up",
            "version": SENSITIVITY_SCORER_VERSION,
            "upstream_commit": None,
        },
    }
    assert first is not second
    assert first["official_soft_ex"] is not second["official_soft_ex"]


def test_official_soft_ex_normalizes_dates_numbers_and_json_recursively() -> None:
    predicted = [
        (
            datetime(2026, 8, 27, 23, 59),
            Decimal("1.235"),
            {"z": [Decimal("2.345")], "a": 1},
        )
    ]
    gold = [
        (
            date(2026, 8, 27),
            1.235,
            {"a": 1, "z": [2.345]},
        )
    ]

    assert official_soft_ex_equal(predicted, gold, conditions={"order": True})


def test_official_soft_ex_uses_sequence_or_duplicate_losing_set_semantics() -> None:
    duplicated = [(1,), (1,), (2,)]
    unique_reordered = [(2,), (1,)]

    assert official_soft_ex_equal(
        duplicated, unique_reordered, conditions={"order": False}
    )
    assert not official_soft_ex_equal(
        duplicated, unique_reordered, conditions={"order": True}
    )
    assert not official_soft_ex_equal([], [], conditions={"order": False})
    assert not official_soft_ex_equal([(1,)], [], conditions={"order": False})


def test_official_soft_ex_defaults_to_unordered_and_validates_order() -> None:
    assert official_soft_ex_equal([(1,), (2,)], [(2,), (1,)])

    with pytest.raises(ScoringPolicyError, match="conditions.order must be a boolean"):
        official_soft_ex_equal([(1,)], [(1,)], conditions={"order": 1})


def test_sensitivity_scorer_preserves_multiplicity_order_and_empty_results() -> None:
    duplicated = [(1,), (1,), (2,)]
    unique_reordered = [(2,), (1,)]
    reordered_duplicates = [(2,), (1,), (1,)]

    assert not sensitivity_equal(
        duplicated,
        unique_reordered,
        conditions={"decimal": -1, "order": False},
    )
    assert sensitivity_equal(
        duplicated,
        reordered_duplicates,
        conditions={"decimal": -1, "order": False},
    )
    assert not sensitivity_equal(
        duplicated,
        reordered_duplicates,
        conditions={"decimal": -1, "order": True},
    )
    assert sensitivity_equal([], [], conditions={"decimal": -1, "order": False})
    assert not sensitivity_equal([], [(1,)], conditions={"decimal": -1, "order": False})


def test_sensitivity_scorer_honors_decimal_metadata_without_rounding_minus_one() -> (
    None
):
    assert sensitivity_equal(
        [(Decimal("1.235"),)],
        [(1.235,)],
        conditions={"decimal": -1, "order": True},
    )
    assert not sensitivity_equal(
        [(Decimal("1.235"),)],
        [(Decimal("1.24"),)],
        conditions={"decimal": -1, "order": True},
    )
    assert sensitivity_equal(
        [(Decimal("1.44"),)],
        [(1.4,)],
        conditions={"decimal": 1, "order": True},
    )
    assert not sensitivity_equal(
        [(Decimal("1.44"),)],
        [(1.4,)],
        conditions={"decimal": 2, "order": True},
    )


def test_sensitivity_scorer_has_stable_null_and_type_representation() -> None:
    conditions = {"decimal": 2, "order": True}

    assert sensitivity_equal([(None,)], [(None,)], conditions=conditions)
    assert not sensitivity_equal([(None,)], [("null",)], conditions=conditions)
    assert not sensitivity_equal([(True,)], [(1,)], conditions=conditions)
    assert sensitivity_equal(
        [({"b": [1, None], "a": "x"},)],
        [({"a": "x", "b": [1, None]},)],
        conditions=conditions,
    )


@pytest.mark.parametrize(
    ("conditions", "message"),
    [
        (None, "conditions must be a mapping"),
        ({"order": False}, "conditions.decimal is required"),
        ({"decimal": 7, "order": False}, "conditions.decimal must be one of"),
        ({"decimal": True, "order": False}, "conditions.decimal must be an integer"),
        ({"decimal": 2, "order": "false"}, "conditions.order must be a boolean"),
    ],
)
def test_sensitivity_scorer_rejects_invalid_conditions(
    conditions: object, message: str
) -> None:
    with pytest.raises(ScoringPolicyError, match=message):
        sensitivity_equal([(1,)], [(1,)], conditions=conditions)  # type: ignore[arg-type]


def test_official_sql_rewrite_matches_public_comment_and_distinct_behavior() -> None:
    sql = """/* header */
    SELECT DISTINCT customer_id -- explanation
    FROM customers
    """

    assert rewrite_sql_official(sql) == "SELECT customer_id FROM customers"
    assert (
        rewrite_sql_official(
            "SELECT DISTINCT ON (customer_id) customer_id FROM customers"
        )
        == "SELECT DISTINCT ON (customer_id) customer_id FROM customers"
    )
    assert (
        rewrite_sql_official(
            "SELECT DISTINCT t.customer_id FROM t JOIN u ON t.id = u.id"
        )
        == "SELECT DISTINCT t.customer_id FROM t JOIN u ON t.id = u.id"
    )


def test_official_sql_rewrite_removes_nested_round_but_sensitivity_is_verbatim() -> (
    None
):
    sql = "SELECT ROUND(COALESCE(ROUND(amount, 2), 0), 1) FROM payments"

    assert rewrite_sql_official(sql) == "SELECT COALESCE(amount, 0) FROM payments"
    assert rewrite_sql_sensitivity(sql) == sql


def test_official_sql_rewrite_leaves_unclosed_round_for_execution_to_reject() -> None:
    sql = "SELECT ROUND(amount, 2 FROM payments"

    assert rewrite_sql_official(sql) == sql

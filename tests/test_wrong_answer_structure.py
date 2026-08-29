from __future__ import annotations

import importlib.util
from pathlib import Path


def _analysis_module():
    path = (
        Path(__file__).parents[1]
        / "experiments"
        / "analysis"
        / "wrong_answer_structure.py"
    )
    spec = importlib.util.spec_from_file_location("wrong_answer_structure", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sql_features_identify_join_grouping_and_aggregation() -> None:
    module = _analysis_module()

    features = module.sql_features(
        "SELECT a.id, SUM(b.amount) FROM accounts a "
        "JOIN balances b ON b.account_id = a.id "
        "WHERE a.active GROUP BY a.id"
    )

    assert features == {
        "aggregate": True,
        "distinct": False,
        "grouped": True,
        "join": True,
        "multi_relation": True,
        "nested": False,
        "relation_count": 2,
        "where": True,
        "window": False,
    }


def test_sql_features_identify_distinct_window_and_nesting() -> None:
    module = _analysis_module()

    features = module.sql_features(
        "SELECT DISTINCT x.id, ROW_NUMBER() OVER (ORDER BY x.id) AS rank "
        "FROM (SELECT id FROM accounts) x"
    )

    assert features["distinct"] is True
    assert features["window"] is True
    assert features["nested"] is True

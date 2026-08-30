from __future__ import annotations

import importlib.util
from pathlib import Path


def _analysis_module():
    path = (
        Path(__file__).parents[1]
        / "experiments"
        / "analysis"
        / "c4_mechanism_measurements.py"
    )
    spec = importlib.util.spec_from_file_location("c4_mechanism_measurements", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_INDEX = {"db_public__t": {"modeled_ratio": "derived", "raw_col": "physical"}}
_COLUMNS = {"db_public__t": frozenset({"raw_col", "undeclared_col"})}


def test_classify_field_separates_derived_from_physical() -> None:
    module = _analysis_module()

    assert (
        module.classify_field(
            "db_public__t.modeled_ratio", _INDEX, _COLUMNS, frozenset()
        )
        == "derived"
    )
    assert (
        module.classify_field("db_public__t.raw_col", _INDEX, _COLUMNS, frozenset())
        == "physical"
    )


def test_classify_field_separates_uncompiled_reference_kinds() -> None:
    module = _analysis_module()

    assert (
        module.classify_field("db_public__t.count", _INDEX, _COLUMNS, frozenset())
        == "omni_count_builtin"
    )
    assert (
        module.classify_field(
            "db_public__t.undeclared_col", _INDEX, _COLUMNS, frozenset()
        )
        == "schema_column_not_in_bundle"
    )
    assert (
        module.classify_field("db_public__t.invented", _INDEX, _COLUMNS, frozenset())
        == "unmatched_name"
    )
    assert (
        module.classify_field("db_public__other.raw_col", _INDEX, _COLUMNS, frozenset())
        == "unmodeled_view"
    )
    assert (
        module.classify_field("avg_value", _INDEX, _COLUMNS, frozenset())
        == "query_local"
    )
    assert (
        module.classify_field(
            "rollup.avg_value", _INDEX, _COLUMNS, frozenset({"rollup"})
        )
        == "query_local"
    )


def test_field_composition_requires_a_compiled_field() -> None:
    module = _analysis_module()

    assert module._field_composition(["derived", "derived"]) == "all_derived"
    assert module._field_composition(["physical"]) == "all_physical"
    assert (
        module._field_composition(["derived", "physical"])
        == "compiled_derived_and_physical"
    )
    assert (
        module._field_composition(["derived", "query_local"])
        == "derived_plus_uncompiled"
    )
    assert (
        module._field_composition(["query_local", "unmatched_name"])
        == "no_compiled_field"
    )


def test_relation_features_drop_cte_and_alias_duplicates() -> None:
    module = _analysis_module()

    features = module.sql_relation_features(
        "WITH rollup AS (SELECT id, SUM(x) AS total FROM ${topic_a} GROUP BY 1) "
        "SELECT ${db_public__t.raw_col}, rollup.total "
        "FROM ${topic_a} a JOIN rollup ON rollup.id = a.id"
    )

    assert features["published_relation_count"] == 3
    assert features["corrected_relation_count"] == 1
    assert features["published_multi_relation"] is True
    assert features["corrected_multi_relation"] is False
    assert features["cte_count"] == 1
    assert "rollup" in features["local_names"]
    assert features["distinct_source_views"] == 1

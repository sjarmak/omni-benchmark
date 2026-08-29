from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _analysis_module():
    path = ROOT / "experiments/analysis/e02_relationship_inventory.py"
    spec = importlib.util.spec_from_file_location("e02_relationship_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_relationship_inventory_is_aggregate_and_complete() -> None:
    result = _analysis_module().inventory(ROOT)

    assert set(result) == {
        "database_count",
        "deferred_by_reason",
        "deferred_count",
        "exactly_one_count",
        "foreign_key_count",
        "multi_column_count",
        "relationship_count",
        "schema_version",
        "zero_or_one_count",
    }
    assert result["schema_version"] == 1
    assert result["database_count"] == 18
    assert result["foreign_key_count"] == (
        result["relationship_count"] + result["deferred_count"]
    )
    assert result["relationship_count"] > 0
    assert (
        result["exactly_one_count"] + result["zero_or_one_count"]
        == result["relationship_count"]
    )

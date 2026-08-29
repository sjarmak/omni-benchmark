from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _analysis_module():
    path = ROOT / "experiments/analysis/e02_bundle_inventory.py"
    spec = importlib.util.spec_from_file_location("e02_bundle_inventory", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_e02_candidate_inventory_is_bounded_and_does_not_reclassify_metrics() -> None:
    result = _analysis_module().inventory(ROOT)

    assert result == {
        "bundle_file_count": 272,
        "database_count": 18,
        "metric_disposition_changes": 0,
        "relationship_count": 91,
        "relationship_database_count": 16,
        "schema_version": 1,
        "topic_with_join_count": 67,
    }

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _analysis_module():
    path = ROOT / "experiments/analysis/e01_baseline_collision.py"
    spec = importlib.util.spec_from_file_location("e01_baseline_collision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_public_baseline_already_satisfies_e01_contract() -> None:
    result = _analysis_module().audit(ROOT)

    assert result["schema_version"] == 1
    assert result["database_count"] == 18
    assert result["compile_count"] == 193
    assert result["compiled_with_dependencies"] > 0
    assert result["executable_dependency_edge_count"] > 0
    assert result["maximum_compiled_dependency_depth"] >= 2
    assert result["all_bundles_regenerate_exactly"] is True
    assert result["all_compile_dependencies_same_grain"] is True
    assert result["baseline_already_satisfies_e01"] is True


def test_audit_output_contains_only_aggregate_keys() -> None:
    result = _analysis_module().audit(ROOT)

    assert set(result) == {
        "all_bundles_regenerate_exactly",
        "all_compile_dependencies_same_grain",
        "baseline_already_satisfies_e01",
        "compile_count",
        "compiled_with_dependencies",
        "database_count",
        "executable_dependency_edge_count",
        "maximum_compiled_dependency_depth",
        "regenerated_file_count",
        "schema_version",
    }

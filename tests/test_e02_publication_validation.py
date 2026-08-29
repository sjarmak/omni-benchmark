from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _analysis_module():
    path = ROOT / "experiments/analysis/e02_publication_validation.py"
    spec = importlib.util.spec_from_file_location("e02_publication_validation", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_e02_candidates_publish_and_authenticate_locally() -> None:
    result = _analysis_module().validate(ROOT)

    assert set(result) == {
        "candidate_set_sha256",
        "database_count",
        "deployment_plan_count",
        "file_count",
        "relationship_count",
        "schema_version",
    }
    assert result["database_count"] == 18
    assert result["deployment_plan_count"] == 18
    assert result["file_count"] == 272
    assert result["relationship_count"] == 91
    assert len(result["candidate_set_sha256"]) == 64

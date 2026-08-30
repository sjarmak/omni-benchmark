from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


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


def test_sql_features_accept_omni_semantic_placeholders() -> None:
    module = _analysis_module()

    features = module.sql_features(
        "SELECT ${orders.customer_id}, AVG(${orders.amount}) "
        "FROM ${orders_semantics} GROUP BY 1"
    )

    assert features["aggregate"] is True
    assert features["grouped"] is True
    assert features["relation_count"] == 1


def test_c4_attempt_identity_is_accepted() -> None:
    module = _analysis_module()

    assert module._attempt_identity("frozen-run:private_instance_7:C4:1") == (
        "private_instance_7",
        "C4",
    )


def test_analyze_c4_hash_binds_records_and_emits_aggregates_only(
    tmp_path: Path,
) -> None:
    module = _analysis_module()
    workspace = tmp_path / "workspace"
    generation_root = tmp_path / "frozen-c4"
    attempt_root = generation_root / "sample_large" / "c4" / "private_instance_7-r1"
    attempt_root.mkdir(parents=True)
    generation = {
        "attempt_id": "frozen-run:private_instance_7:C4:1",
        "generated_query": json.dumps(
            {
                "userEditedSQL": (
                    "SELECT account_id, COUNT(*) FROM private_accounts "
                    "GROUP BY account_id"
                )
            }
        ),
        "question": "private question text that must not escape",
    }
    generation_bytes = (
        json.dumps(generation, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    (attempt_root / "generation.jsonl").write_bytes(generation_bytes)
    generation_sha256 = hashlib.sha256(generation_bytes).hexdigest()

    score_root = (
        workspace / "experiments/autoresearch/raw/public-c4-baseline-v8-dev-a-scores-v2"
    )
    score_root.mkdir(parents=True)
    score = {
        "attempts": [
            {
                "attempt_id": "frozen-run:private_instance_7:C4:1",
                "generation_record_sha256": generation_sha256,
                "generation_sha256": generation_sha256,
                "outcome": "correct",
                "status": "scored",
            }
        ]
    }
    score_bytes = json.dumps(score, sort_keys=True, separators=(",", ":")).encode()
    (score_root / "official.score.json").write_bytes(score_bytes)
    (score_root / "receipt.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "official": {
                        "path": (
                            "experiments/autoresearch/raw/"
                            "public-c4-baseline-v8-dev-a-scores-v2/"
                            "official.score.json"
                        ),
                        "sha256": hashlib.sha256(score_bytes).hexdigest(),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    result = module.analyze_c4(workspace, generation_root)

    assert result["row_count"] == 1
    assert result["sql_shape_summary"]["C4:correct"] == {
        "count": 1,
        "feature_counts": {
            "aggregate": 1,
            "distinct": 0,
            "grouped": 1,
            "join": 0,
            "multi_relation": 0,
            "nested": 0,
            "where": 0,
            "window": 0,
        },
        "mean_relation_count": 1.0,
        "parsed_sql_count": 1,
    }
    serialized = json.dumps(result, sort_keys=True)
    assert "private_instance_7" not in serialized
    assert "private question text" not in serialized
    assert "private_accounts" not in serialized


def test_analyze_c4_rejects_score_hash_mismatch(tmp_path: Path) -> None:
    module = _analysis_module()
    workspace = tmp_path / "workspace"
    score_root = (
        workspace / "experiments/autoresearch/raw/public-c4-baseline-v8-dev-a-scores-v2"
    )
    score_root.mkdir(parents=True)
    (score_root / "official.score.json").write_text(
        '{"attempts": []}', encoding="utf-8"
    )
    (score_root / "receipt.json").write_text(
        json.dumps(
            {
                "artifacts": {
                    "official": {
                        "path": (
                            "experiments/autoresearch/raw/"
                            "public-c4-baseline-v8-dev-a-scores-v2/"
                            "official.score.json"
                        ),
                        "sha256": "0" * 64,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="official score artifact hash changed"):
        module.analyze_c4(workspace, tmp_path / "frozen-c4")

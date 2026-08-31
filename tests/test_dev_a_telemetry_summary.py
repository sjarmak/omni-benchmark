from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
ANALYZER_PATH = ROOT / "experiments/analysis/dev_a_telemetry_summary.py"

FORBIDDEN_OUTPUT_KEYS = {
    "attempt_id",
    "correct",
    "correctness",
    "generated_query",
    "generated_sql",
    "gold",
    "gold_sql",
    "hidden_annotation",
    "instance_id",
    "question",
    "result",
    "result_hash",
    "rows",
    "score",
}


def _analysis_module():
    spec = importlib.util.spec_from_file_location(
        "dev_a_telemetry_summary", ANALYZER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(instance: str, *, outcome: str = "answered", tokens: int = 1000):
    return {
        "instance_id": instance,
        "repetition": 1,
        "condition": "C4",
        "generation_outcome": outcome,
        "latency_ms": 1234.5,
        "model": {"name": "claude-opus-5", "provider": "bedrock", "version": None},
        "token_source": "provider_reported",
        "token_usage": {
            "input_tokens": tokens,
            "output_tokens": 10,
            "total_tokens": tokens + 10,
        },
        "cost_source": "unavailable",
        "cost_usd": None,
        "cost_unavailable_reason": "omni_job_api_does_not_expose_cost",
        "tool_call_count": 7,
        "database_query_count": 2,
        "question": "this must never reach the aggregate",
        "generated_sql": "SELECT 1",
    }


def _write_run(root: Path, records) -> Path:
    for index, record in enumerate(records):
        directory = root / f"db_{index}_large" / "c4" / f"{record['instance_id']}-r1"
        directory.mkdir(parents=True)
        (directory / "generation.jsonl").write_text(
            json.dumps(record) + "\n", encoding="utf-8"
        )
    return root


def test_summary_carries_no_question_level_identity(tmp_path):
    module = _analysis_module()
    run = _write_run(
        tmp_path / "run", [_record(f"instance_{i}_large") for i in range(4)]
    )

    payload = module.summarize_run(run)
    serialized = module.canonical_bytes(payload).decode()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in FORBIDDEN_OUTPUT_KEYS
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    for instance in ("instance_0_large", "instance_1_large", "instance_2_large"):
        assert instance not in serialized
    assert "this must never reach the aggregate" not in serialized
    assert "SELECT 1" not in serialized


def test_summary_is_deterministic_and_hash_sealed(tmp_path):
    module = _analysis_module()
    run = _write_run(
        tmp_path / "run", [_record(f"instance_{i}_large") for i in range(3)]
    )

    first = module.canonical_bytes(module.summarize_run(run))
    second = module.canonical_bytes(module.summarize_run(run))
    assert first == second

    payload = json.loads(first)
    digest = payload.pop("aggregate_payload_sha256")
    import hashlib

    assert digest == hashlib.sha256(module.canonical_bytes(payload)).hexdigest()


def test_summary_counts_outcomes_and_reports_cost_unavailable(tmp_path):
    module = _analysis_module()
    run = _write_run(
        tmp_path / "run",
        [
            _record("instance_0"),
            _record("instance_1", outcome="errored"),
            _record("instance_2"),
        ],
    )

    arm = module.summarize_run(run)["arm"]
    assert arm["attempt_count"] == 3
    assert arm["outcomes"] == {"answered": 2, "errored": 1, "refused": 0}
    assert arm["cost"]["status"] == "unavailable"
    assert arm["cost"]["unavailable_reason"] == ["omni_job_api_does_not_expose_cost"]
    assert arm["models"] == [
        {"name": "claude-opus-5", "provider": "bedrock", "attempt_count": 3}
    ]
    assert arm["all_attempts"]["total_tokens"]["observed"] == 3


def test_compare_restricts_both_arms_to_shared_coordinates(tmp_path):
    module = _analysis_module()
    left = _write_run(
        tmp_path / "left", [_record(f"instance_{i}_large") for i in range(4)]
    )
    right = _write_run(
        tmp_path / "right", [_record(f"instance_{i}_large") for i in range(2, 6)]
    )

    payload = module.compare_runs([("left", left), ("right", right)])
    assert payload["matched_attempt_count"] == 2
    for label in ("left", "right"):
        assert payload["runs"][label]["attempt_count"] == 4
        assert payload["runs"][label]["matched"]["attempt_count"] == 2


def test_compare_rejects_runs_with_no_shared_coordinate(tmp_path):
    module = _analysis_module()
    left = _write_run(tmp_path / "left", [_record("instance_0")])
    right = _write_run(tmp_path / "right", [_record("instance_9")])

    with pytest.raises(module.SummaryError):
        module.compare_runs([("left", left), ("right", right)])


def test_reading_an_empty_run_root_fails(tmp_path):
    module = _analysis_module()
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(module.SummaryError):
        module.read_run(empty)

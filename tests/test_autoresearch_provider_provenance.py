from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from omni_benchmark.autoresearch import AutoresearchError, validate_run
from omni_benchmark.direct_capture_contract import DirectModelTurnProvenance
from tests.test_autoresearch_hardening import _record, _workspace, _write_jsonl


def _model_turn_provenance() -> dict[str, object]:
    return {
        "availability": "unavailable",
        "binary_sha256": "1" * 64,
        "cli_version": "fixture-cli-v1",
        "cost_source": "unavailable",
        "duration_ms": None,
        "model_identity_sha256": "2" * 64,
        "provider": "test-provider",
        "realized_models": [],
        "request_sha256": None,
        "requested_model": "test-model",
        "result_subtype": None,
        "session_sha256": None,
        "stream_sha256": None,
        "token_source": "unavailable",
        "trace_seq": 0,
    }


def _attach_trace(workspace: Path, record: dict[str, object], *, suffix: str) -> None:
    provenance = DirectModelTurnProvenance.from_dict(
        record["model_turn_provenance"][0]  # type: ignore[index]
    )
    path = workspace / "runs" / f"provider-provenance-{suffix}.trace.jsonl"
    _write_jsonl(
        path,
        [
            {
                "component": "direct-sql-harness",
                "database_query_delta": 1,
                "duration_ms": 100,
                "elapsed_ms": 100,
                "event_type": "direct_model_turn",
                "failure_class": None,
                "input_tokens": 10,
                "metadata_sha256": provenance.sha256(),
                "model": "test-model",
                "output_tokens": 5,
                "provider": "test-provider",
                "retry_delta": 0,
                "schema_version": "trace-event-v2",
                "seq": 0,
                "status": "SUCCESS",
                "timestamp": "2026-08-27T12:00:00.100Z",
                "tool_call_delta": 1,
                "tool_name": "query",
                "validation_attempt_delta": 1,
            }
        ],
    )
    record.update(
        {
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": path.relative_to(workspace).as_posix(),
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )


def test_run_validator_accepts_strict_reduced_model_turn_provenance(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record(instance_id) for instance_id in config.dev_a_ids]
    for index, record in enumerate(records):
        record["model_turn_provenance"] = [_model_turn_provenance()]
        _attach_trace(workspace, record, suffix=str(index))
    path = workspace / "runs" / "provider-provenance.jsonl"
    _write_jsonl(path, records)

    assert validate_run(config, path).question_count == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session_id", "raw-session-must-never-persist"),
        ("request_sha256", "raw-request-must-never-persist"),
        ("realized_models", ["forged-model"]),
    ],
)
def test_run_validator_rejects_forged_or_raw_model_turn_provenance(
    tmp_path: Path, field: str, value: object
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record(instance_id) for instance_id in config.dev_a_ids]
    for record in records:
        provenance = _model_turn_provenance()
        provenance[field] = value
        record["model_turn_provenance"] = [provenance]
    path = workspace / "runs" / "forged-provider-provenance.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="model turn provenance"):
        validate_run(config, path)


def test_run_validator_rejects_provenance_substitution_after_trace_capture(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record(instance_id) for instance_id in config.dev_a_ids]
    for index, record in enumerate(records):
        record["model_turn_provenance"] = [_model_turn_provenance()]
        _attach_trace(workspace, record, suffix=f"forged-{index}")
        record["model_turn_provenance"][0]["binary_sha256"] = "3" * 64  # type: ignore[index]
    path = workspace / "runs" / "substituted-provider-provenance.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="does not match trace"):
        validate_run(config, path)

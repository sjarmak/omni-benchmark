from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from omni_benchmark.autoresearch import (
    AutoresearchError,
    create_public_dev_a_view,
    propose_experiment,
    stop_optimization,
    validate_run,
)

from tests.test_autoresearch_hardening import (
    _baseline,
    _proposal,
    _record,
    _workspace,
    _write_json,
    _write_jsonl,
)


def test_run_rejects_sensitive_diagnostic_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, config = _workspace(tmp_path)
    monkeypatch.setenv("UNRELATED_SERVICE_TOKEN", "live-secret-value")
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "failure_origin": "evaluated_system",
            "generated_query": None,
            "generation_outcome": "errored",
            "harness_failure": "provider echoed live-secret-value",
            "outcome": "refused_or_error",
            "terminal_failure_class": "provider_error",
        }
    )
    path = workspace / "runs" / "secret-diagnostic.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="sensitive content"):
        validate_run(config, path)


@pytest.mark.parametrize("location", ["attempt_id", "run_id", "tool_name"])
def test_run_rejects_live_secret_in_any_persisted_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    workspace, config = _workspace(tmp_path)
    monkeypatch.setenv("OMNI_API_TOKEN", "live-secret-value")
    records = [_record("dev_a_1"), _record("dev_a_2")]
    if location == "tool_name":
        records[0]["tool_calls_by_name"] = [{"count": 1, "name": "live-secret-value"}]
    else:
        records[0][location] = "live-secret-value"
    path = workspace / "runs" / f"secret-{location}.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="sensitive content"):
        validate_run(config, path)


def test_run_rejects_query_containing_exact_live_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, config = _workspace(tmp_path)
    monkeypatch.setenv("OMNI_API_TOKEN", "live-secret-value")
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0]["generated_query"] = "SELECT 'live-secret-value'"
    path = workspace / "runs" / "secret-query.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="generated query contains"):
        validate_run(config, path)


def test_run_rejects_token_shaped_generated_query(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0]["generated_query"] = "SELECT 'Bearer abcdefghijklmnop'"
    path = workspace / "runs" / "token-shaped-query.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="generated query contains"):
        validate_run(config, path)


def test_trace_artifact_rejects_hardlinks(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    trace_path = workspace / "runs" / "linked.trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            {
                "component": "agent",
                "database_query_delta": 1,
                "duration_ms": 100,
                "elapsed_ms": 100,
                "event_type": "query",
                "failure_class": None,
                "input_tokens": 10,
                "metadata_sha256": None,
                "model": "test-model",
                "output_tokens": 5,
                "provider": "test-provider",
                "retry_delta": 0,
                "schema_version": "trace-event-v2",
                "seq": 0,
                "status": "ok",
                "timestamp": "2026-08-27T12:00:00.100Z",
                "tool_call_delta": 1,
                "tool_name": "query",
                "validation_attempt_delta": 1,
            }
        ],
    )
    (workspace / "runs" / "linked-copy.trace.jsonl").hardlink_to(trace_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": "runs/linked.trace.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        }
    )
    path = workspace / "runs" / "linked-trace-run.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="single-link regular file"):
        validate_run(config, path)


def test_trace_sequence_rejects_boolean_even_when_equal_to_zero(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    trace_path = workspace / "runs" / "boolean-seq.trace.jsonl"
    _write_jsonl(
        trace_path,
        [
            {
                "component": "agent",
                "database_query_delta": 1,
                "duration_ms": 100,
                "elapsed_ms": 100,
                "event_type": "query",
                "failure_class": None,
                "input_tokens": 10,
                "metadata_sha256": None,
                "model": "test-model",
                "output_tokens": 5,
                "provider": "test-provider",
                "retry_delta": 0,
                "schema_version": "trace-event-v2",
                "seq": False,
                "status": "ok",
                "timestamp": "2026-08-27T12:00:00.100Z",
                "tool_call_delta": 1,
                "tool_name": "query",
                "validation_attempt_delta": 1,
            }
        ],
    )
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": "runs/boolean-seq.trace.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        }
    )
    path = workspace / "runs" / "boolean-seq-run.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="sequence"):
        validate_run(config, path)


def test_result_sidecar_preserves_duplicate_labels_and_rejects_boolean_version(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    result_path = workspace / "runs" / "duplicate-columns.json"
    _write_json(
        result_path,
        {
            "columns": ["value", "value"],
            "rows": [[1, 2]],
            "schema_version": 1,
            "truncated": False,
        },
    )
    result_path.chmod(0o600)
    digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "actual_result_hash": digest,
            "actual_result_status": "complete",
            "result_artifact_path": "runs/duplicate-columns.json",
            "result_artifact_schema_version": 1,
            "result_artifact_sha256": digest,
        }
    )
    run_path = workspace / "runs" / "duplicate-columns-run.jsonl"
    _write_jsonl(run_path, records)

    assert validate_run(config, run_path).question_count == 2

    result_path.unlink()
    _write_json(
        result_path,
        {
            "columns": ["value", "value"],
            "rows": [[1, 2]],
            "schema_version": True,
            "truncated": False,
        },
    )
    result_path.chmod(0o600)
    bad_digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    records[0].update(
        {
            "actual_result_hash": bad_digest,
            "result_artifact_sha256": bad_digest,
        }
    )
    bad_run_path = workspace / "runs" / "boolean-result-version-run.jsonl"
    _write_jsonl(bad_run_path, records)

    with pytest.raises(AutoresearchError, match="metadata"):
        validate_run(config, bad_run_path)


@pytest.mark.parametrize(
    ("column", "expected_error"),
    [
        ("api_key", "sensitive column"),
        ("token", "sensitive column"),
        ("gold_sql", "forbidden column"),
        ("external_knowledge", "forbidden column"),
    ],
)
def test_result_sidecar_rejects_sensitive_or_forbidden_columns(
    tmp_path: Path,
    column: str,
    expected_error: str,
) -> None:
    workspace, config = _workspace(tmp_path)
    result_path = workspace / "runs" / f"unsafe-{column}.json"
    _write_json(
        result_path,
        {
            "columns": [column],
            "rows": [["opaque-provider-value"]],
            "schema_version": 1,
            "truncated": False,
        },
    )
    result_path.chmod(0o600)
    digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "actual_result_hash": digest,
            "actual_result_status": "complete",
            "result_artifact_path": f"runs/unsafe-{column}.json",
            "result_artifact_schema_version": 1,
            "result_artifact_sha256": digest,
        }
    )
    run_path = workspace / "runs" / f"unsafe-{column}-run.jsonl"
    _write_jsonl(run_path, records)

    with pytest.raises(AutoresearchError, match=expected_error):
        validate_run(config, run_path)


def test_run_question_must_match_committed_public_manifest(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0]["question"] = "Different public-looking question"
    path = workspace / "runs" / "question-mismatch.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="committed public question"):
        validate_run(config, path)


def test_run_requires_committed_public_question(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].pop("question")
    path = workspace / "runs" / "question-missing.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="missing required fields"):
        validate_run(config, path)


def test_run_and_trace_artifacts_must_be_private_single_link_files(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    path = workspace / "runs" / "unsafe-run.jsonl"
    _write_jsonl(path, records)
    path.chmod(0o664)

    with pytest.raises(AutoresearchError, match="mode 0600"):
        validate_run(config, path)

    path.chmod(0o600)
    (workspace / "runs" / "unsafe-run-copy.jsonl").hardlink_to(path)
    with pytest.raises(AutoresearchError, match="single-link regular file"):
        validate_run(config, path)


def test_answered_opaque_omni_result_is_bound_to_private_sidecar(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    result_path = workspace / "runs" / "opaque-result.json"
    _write_json(
        result_path,
        {
            "columns": ["answer"],
            "rows": [[42]],
            "schema_version": 1,
            "truncated": False,
        },
    )
    result_path.chmod(0o600)
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "actual_result_hash": result_sha256,
            "actual_result_status": "complete",
            "generated_query": None,
            "query_unavailable_reason": "Omni returned governed rows without executable query text",
            "result_artifact_path": "runs/opaque-result.json",
            "result_artifact_schema_version": 1,
            "result_artifact_sha256": result_sha256,
        }
    )
    path = workspace / "runs" / "opaque-result-run.jsonl"
    _write_jsonl(path, records)

    assert validate_run(config, path).question_count == 2


def test_result_sidecar_requires_private_mode_and_single_link(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    result_path = workspace / "runs" / "unsafe-result.json"
    _write_json(
        result_path,
        {
            "columns": ["answer"],
            "rows": [[42]],
            "schema_version": 1,
            "truncated": False,
        },
    )
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "actual_result_hash": result_sha256,
            "actual_result_status": "complete",
            "result_artifact_path": "runs/unsafe-result.json",
            "result_artifact_schema_version": 1,
            "result_artifact_sha256": result_sha256,
        }
    )
    path = workspace / "runs" / "unsafe-result-run.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="mode 0600"):
        validate_run(config, path)


def test_result_sidecar_rejects_hardlinks(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    result_path = workspace / "runs" / "linked-result.json"
    _write_json(
        result_path,
        {
            "columns": ["answer"],
            "rows": [[42]],
            "schema_version": 1,
            "truncated": False,
        },
    )
    result_path.chmod(0o600)
    (workspace / "runs" / "linked-result-copy.json").hardlink_to(result_path)
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "actual_result_hash": result_sha256,
            "actual_result_status": "complete",
            "result_artifact_path": "runs/linked-result.json",
            "result_artifact_schema_version": 1,
            "result_artifact_sha256": result_sha256,
        }
    )
    path = workspace / "runs" / "linked-result-run.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="single-link regular file"):
        validate_run(config, path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("result_artifact_path", ["runs", "result.json"]),
        ("result_artifact_schema_version", True),
    ],
)
def test_result_sidecar_binding_requires_exact_field_types(
    tmp_path: Path, field: str, value: object
) -> None:
    workspace, config = _workspace(tmp_path)
    result_path = workspace / "runs" / "result.json"
    _write_json(
        result_path,
        {
            "columns": ["answer"],
            "rows": [[42]],
            "schema_version": 1,
            "truncated": False,
        },
    )
    result_path.chmod(0o600)
    result_sha256 = hashlib.sha256(result_path.read_bytes()).hexdigest()
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "actual_result_hash": result_sha256,
            "actual_result_status": "complete",
            "result_artifact_path": "runs/result.json",
            "result_artifact_schema_version": 1,
            "result_artifact_sha256": result_sha256,
            field: value,
        }
    )
    path = workspace / "runs" / f"invalid-{field}.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="result artifact"):
        validate_run(config, path)


def test_stop_blocks_public_view_creation(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    _baseline(config, workspace)
    stop_optimization(
        config,
        reason="final candidate selected",
        rationale="Optimization is complete.",
        git_commit="b" * 40,
    )
    config.stop_path.unlink()

    with pytest.raises(AutoresearchError, match="optimization has stopped"):
        create_public_dev_a_view(config)


def test_ledger_anchor_detects_suffix_truncation(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    _baseline(config, workspace)
    _proposal(config)
    config.ledger_path.write_bytes(b"")

    with pytest.raises(AutoresearchError, match="ledger anchor"):
        propose_experiment(
            config,
            experiment_id="exp-002",
            parent="baseline",
            hypothesis="A second generic mechanism may help.",
            intervention="Preserve a second generic graph invariant.",
            affected_class="dependency",
            mechanism="Mechanical validation.",
            predicted_direction="Increase correctness.",
            regression_risk="Strict validation may reject definitions.",
            subsystem="transformer",
            generality_rationale="Applies across databases.",
            condition="C4",
            content_provenance="Public HKB.",
            intervention_provenance="Generic transformer change.",
            tuning_actor="human_agent_collaboration",
            tuning_effort="One targeted evaluation.",
            optimization_surface="structural",
            candidate_generation_method="Trace-guided code change.",
            generality_scope="cross_database_general",
        )

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.autoresearch import (
    AutoresearchError,
    create_baseline,
    load_config,
    propose_experiment,
    validate_generation_outputs,
    validate_run,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _record(instance_id: str, *, scored: bool = True) -> dict[str, object]:
    value: dict[str, object] = {
        "attempt_id": f"run-1:{instance_id}:C4:1",
        "condition": "C4",
        "cost_source": "provider_reported",
        "cost_usd": 0.01,
        "database_query_count": 1,
        "failure_origin": None,
        "finished_at": "2026-08-27T12:00:00.100Z",
        "generated_query": "SELECT 1",
        "generation_outcome": "answered",
        "harness_failure": None,
        "instance_id": instance_id,
        "latency_ms": 100,
        "model": {
            "provider": "test-provider",
            "name": "test-model",
            "version": "test-version",
        },
        "partition": "dev-a" if scored else "train",
        "question": f"Question for {instance_id}",
        "repetition": 1,
        "retry_count": 0,
        "run_id": "run-1",
        "semantic_objects": ["topic.safe"],
        "started_at": "2026-08-27T12:00:00Z",
        "telemetry_unavailable": [],
        "terminal_failure_class": None,
        "token_source": "provider_reported",
        "token_usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
        "tool_call_count": 1,
        "tool_calls_by_name": [{"count": 1, "name": "query"}],
        "trace_captured": False,
        "trace_degraded_reason": "synthetic fixture has no raw trace",
        "trace_path": None,
        "trace_schema_version": None,
        "trace_sha256": None,
        "trace_truncated": False,
        "validation_attempt_count": 1,
    }
    if scored:
        value["outcome"] = "correct"
    return value


def _workspace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    manifests = workspace / "data" / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "train_ids.txt").write_text(
        "dev_a_1\ndev_a_2\ndev_b_1\n", encoding="utf-8"
    )
    (manifests / "dev_a_ids.txt").write_text("dev_a_1\ndev_a_2\n", encoding="utf-8")
    (manifests / "dev_b_ids.txt").write_text("dev_b_1\n", encoding="utf-8")
    (manifests / "test_ids.txt").write_text("test_1\n", encoding="utf-8")
    questions = [
        {
            "category": "Query",
            "conditions": {"order": False},
            "instance_id": instance_id,
            "query": f"Question for {instance_id}",
            "selected_database": "safe_database",
        }
        for instance_id in ("dev_a_1", "dev_a_2", "dev_b_1", "test_1")
    ]
    _write_jsonl(manifests / "eligible_questions.jsonl", questions)
    config_path = workspace / "config" / "autoresearch.json"
    _write_json(
        config_path,
        {
            "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
            "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
            "dev_b_max_evaluations": 2,
            "expected_dev_a_count": 2,
            "expected_dev_b_count": 1,
            "expected_train_count": 3,
            "forbidden_fields": ["gold_sql", "external_knowledge"],
            "guardian_public_key_sha256": "a" * 64,
            "ledger_path": "experiments/autoresearch/ledger.jsonl",
            "public_manifest_path": "data/manifests/eligible_questions.jsonl",
            "state_dir": "experiments/autoresearch/state",
            "test_ids_path": "data/manifests/test_ids.txt",
            "train_ids_path": "data/manifests/train_ids.txt",
        },
    )
    return workspace, load_config(config_path, workspace=workspace)


def _baseline(config, workspace: Path) -> Path:
    path = workspace / "runs" / "baseline.jsonl"
    _write_jsonl(
        path,
        [_record(instance_id, scored=False) for instance_id in config.train_ids],
    )
    create_baseline(config, run_path=path, git_commit="a" * 40)
    return path


def _proposal(config) -> None:
    propose_experiment(
        config,
        experiment_id="exp-001",
        parent="baseline",
        hypothesis="Dependency edges are incomplete.",
        intervention="Preserve every declared dependency edge.",
        affected_class="dependency",
        mechanism="Mechanical graph traversal.",
        predicted_direction="Increase correctness.",
        regression_risk="Cycles may reject definitions.",
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


def test_run_artifacts_must_live_under_ignored_raw_roots(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    path = workspace / "docs" / "trackable-run.jsonl"
    _write_jsonl(path, [_record("dev_a_1"), _record("dev_a_2")])

    with pytest.raises(AutoresearchError, match="ignored raw-run root"):
        validate_run(config, path)


def test_run_and_generation_final_symlinks_are_rejected(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    scored_target = workspace / "runs" / "scored-target.jsonl"
    _write_jsonl(scored_target, [_record("dev_a_1"), _record("dev_a_2")])
    scored_link = workspace / "runs" / "scored-link.jsonl"
    scored_link.symlink_to(scored_target.name)

    with pytest.raises(AutoresearchError, match="cannot read run artifact"):
        validate_run(config, scored_link)

    generation_target = workspace / "runs" / "generation-target.jsonl"
    _write_jsonl(
        generation_target,
        [
            _record("dev_a_1", scored=False) | {"partition": "dev-a"},
            _record("dev_a_2", scored=False) | {"partition": "dev-a"},
        ],
    )
    generation_link = workspace / "runs" / "generation-link.jsonl"
    generation_link.symlink_to(generation_target.name)

    with pytest.raises(AutoresearchError, match="cannot read generation artifact"):
        validate_generation_outputs(config, generation_link, scope="dev-a")


def test_frozen_baseline_detects_output_overwrite(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    _baseline(config, workspace)
    records = [_record(instance_id, scored=False) for instance_id in config.train_ids]
    records[0]["generated_query"] = "SELECT 2"
    _write_jsonl(config.baseline_outputs_path, records)

    with pytest.raises(AutoresearchError, match="baseline output.*changed"):
        _proposal(config)


@pytest.mark.parametrize("mutation", ["mixed_condition", "duplicate_attempt"])
def test_baseline_requires_one_run_configuration(tmp_path: Path, mutation: str) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record(instance_id, scored=False) for instance_id in config.train_ids]
    if mutation == "mixed_condition":
        records[0]["condition"] = "C1"
    else:
        records[0]["attempt_id"] = records[1]["attempt_id"]
    path = workspace / "runs" / f"baseline-{mutation}.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(
        AutoresearchError, match="baseline output artifact.*(condition|attempt_id)"
    ):
        create_baseline(config, run_path=path, git_commit="a" * 40)


@pytest.mark.parametrize("generation_outcome", ["refused", "errored"])
def test_non_answers_require_failure_provenance(
    tmp_path: Path, generation_outcome: str
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {"generation_outcome": generation_outcome, "outcome": "refused_or_error"}
    )
    if generation_outcome == "refused":
        records[0]["condition"] = "C1"
        records[0]["attempt_id"] = records[0]["attempt_id"].replace(":C4:", ":C1:")
        records[1]["condition"] = "C1"
        records[1]["attempt_id"] = records[1]["attempt_id"].replace(":C4:", ":C1:")
    path = workspace / "runs" / "missing-failure-provenance.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="failure_origin.*failure class"):
        validate_run(config, path)


def test_errored_attempt_may_have_no_generated_query(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "failure_origin": "evaluated_system",
            "generated_query": None,
            "generation_outcome": "errored",
            "harness_failure": None,
            "outcome": "refused_or_error",
            "terminal_failure_class": "query_generation_failure",
        }
    )
    path = workspace / "runs" / "no-query-error.jsonl"
    _write_jsonl(path, records)

    run = validate_run(config, path)

    assert run.refused_or_error_rate == 0.5
    assert run.refusal_observable is False
    assert run.refusal_rate is None
    assert run.error_rate == 0.5
    assert run.refused_ids == frozenset()
    assert run.errored_ids == frozenset({"dev_a_1"})


def test_harness_failure_cannot_be_owned_by_evaluated_system(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "failure_origin": "evaluated_system",
            "generated_query": None,
            "generation_outcome": "errored",
            "harness_failure": "adapter_transport_error",
            "outcome": "refused_or_error",
            "terminal_failure_class": "adapter_transport_error",
        }
    )
    path = workspace / "runs" / "contradictory-harness-origin.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(
        AutoresearchError,
        match="harness_failure.*benchmark_infrastructure",
    ):
        validate_run(config, path)


def test_validated_run_preserves_refused_and_errored_as_distinct_outcomes(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    for record in records:
        record["condition"] = "C1"
        record["attempt_id"] = record["attempt_id"].replace(":C4:", ":C1:")
    records[0].update(
        {
            "failure_origin": "evaluated_system",
            "generated_query": None,
            "generation_outcome": "refused",
            "harness_failure": None,
            "outcome": "refused_or_error",
            "terminal_failure_class": "direct_refusal",
        }
    )
    records[1].update(
        {
            "failure_origin": "evaluated_system",
            "generated_query": None,
            "generation_outcome": "errored",
            "harness_failure": None,
            "outcome": "refused_or_error",
            "terminal_failure_class": "query_generation_failure",
        }
    )
    path = workspace / "runs" / "distinct-non-answer-outcomes.jsonl"
    _write_jsonl(path, records)

    run = validate_run(config, path)
    manifest = run.as_manifest(workspace)

    assert run.refused_or_error_ids == frozenset({"dev_a_1", "dev_a_2"})
    assert run.refusal_observable is True
    assert run.refused_ids == frozenset({"dev_a_1"})
    assert run.errored_ids == frozenset({"dev_a_2"})
    assert run.refused_or_error_rate == 1
    assert run.refusal_rate == 0.5
    assert run.error_rate == 0.5
    assert manifest["refused_or_error_count"] == 2
    assert manifest["refusal_observable"] is True
    assert manifest["refused_count"] == 1
    assert manifest["errored_count"] == 1


def test_c4_manifest_marks_refusal_rate_unobservable(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "failure_origin": "evaluated_system",
            "generated_query": None,
            "generation_outcome": "errored",
            "harness_failure": None,
            "outcome": "refused_or_error",
            "terminal_failure_class": "response_contract_error",
        }
    )
    path = workspace / "runs" / "c4-refusal-unobservable.jsonl"
    _write_jsonl(path, records)

    manifest = validate_run(config, path).as_manifest(workspace)

    assert manifest["refusal_observable"] is False
    assert manifest["refused_count"] is None
    assert manifest["refusal_rate"] is None


def test_c4_rejects_refusal_without_a_structured_product_signal(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [
        _record("dev_a_1", scored=False),
        _record("dev_a_2", scored=False),
    ]
    for record in records:
        record["partition"] = "dev-a"
    records[0].update(
        {
            "failure_origin": "evaluated_system",
            "generated_query": None,
            "generation_outcome": "refused",
            "harness_failure": None,
            "terminal_failure_class": "direct_refusal",
        }
    )
    path = workspace / "runs" / "unsupported-c4-refusal.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="C4 refusal.*not observable"):
        validate_generation_outputs(config, path, scope="dev-a")


def test_benchmark_infrastructure_failure_must_be_rerun_before_scoring(
    tmp_path: Path,
) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "failure_origin": "benchmark_infrastructure",
            "generated_query": None,
            "generation_outcome": "errored",
            "harness_failure": "database_infrastructure_error",
            "outcome": "refused_or_error",
            "terminal_failure_class": "database_infrastructure_error",
        }
    )
    path = workspace / "runs" / "infrastructure-invalid.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="rerun before scoring"):
        validate_run(config, path)


def test_answered_attempt_cannot_report_terminal_failure(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "failure_origin": "benchmark_infrastructure",
            "harness_failure": "crash",
            "terminal_failure_class": "timeout",
        }
    )
    path = workspace / "runs" / "contradictory-terminal-failure.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="answered attempts cannot"):
        validate_run(config, path)


def test_latency_must_match_attempt_timestamps(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0]["latency_ms"] = 10
    path = workspace / "runs" / "bad-latency.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="latency_ms.*timestamps"):
        validate_run(config, path)


@pytest.mark.parametrize(
    ("field", "value"),
    [("latency_ms", float("nan")), ("cost_usd", float("inf"))],
)
def test_run_metrics_must_be_finite(tmp_path: Path, field: str, value: float) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0][field] = value
    path = workspace / "runs" / f"non-finite-{field}.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match=f"{field} must be finite"):
        validate_run(config, path)


def test_provider_token_report_requires_complete_counts(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0]["token_usage"] = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    path = workspace / "runs" / "bad-token-source.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="token_usage.*complete"):
        validate_run(config, path)


def test_complete_trace_must_reconcile_with_envelope(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    trace_path = workspace / "runs" / "attempt.trace.jsonl"
    event = {
        "component": "agent",
        "database_query_delta": 1,
        "duration_ms": 100,
        "elapsed_ms": 100,
        "event_type": "query",
        "failure_class": None,
        "input_tokens": 2,
        "metadata_sha256": None,
        "model": "test-model",
        "output_tokens": 3,
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
    _write_jsonl(trace_path, [event])
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": "runs/attempt.trace.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        }
    )
    path = workspace / "runs" / "trace-mismatch.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="trace token totals"):
        validate_run(config, path)


def test_trace_event_timestamp_must_be_timezone_aware_iso8601(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    trace_path = workspace / "runs" / "bad-timestamp.trace.jsonl"
    event = {
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
        "timestamp": "not-a-timestamp",
        "tool_call_delta": 1,
        "tool_name": "query",
        "validation_attempt_delta": 1,
    }
    _write_jsonl(trace_path, [event])
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": "runs/bad-timestamp.trace.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        }
    )
    path = workspace / "runs" / "bad-timestamp.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="trace event timestamp.*ISO-8601"):
        validate_run(config, path)


def test_trace_and_result_final_symlinks_are_rejected(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    trace_target = workspace / "runs" / "trace-target.jsonl"
    trace_event = {
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
    _write_jsonl(trace_target, [trace_event])
    trace_link = workspace / "runs" / "trace-link.jsonl"
    trace_link.symlink_to(trace_target.name)
    trace_records = [_record("dev_a_1"), _record("dev_a_2")]
    trace_records[0].update(
        {
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": "runs/trace-link.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_target.read_bytes()).hexdigest(),
        }
    )
    trace_run = workspace / "runs" / "trace-symlink-run.jsonl"
    _write_jsonl(trace_run, trace_records)

    with pytest.raises(AutoresearchError, match="cannot read trace artifact"):
        validate_run(config, trace_run)

    result_target = workspace / "runs" / "result-target.json"
    _write_json(
        result_target,
        {"columns": ["value"], "rows": [[1]], "schema_version": 1, "truncated": False},
    )
    result_target.chmod(0o600)
    result_link = workspace / "runs" / "result-link.json"
    result_link.symlink_to(result_target.name)
    result_digest = hashlib.sha256(result_target.read_bytes()).hexdigest()
    result_records = [_record("dev_a_1"), _record("dev_a_2")]
    result_records[0].update(
        {
            "actual_result_hash": result_digest,
            "generated_query": None,
            "query_unavailable_reason": "product returned an opaque result",
            "result_artifact_path": "runs/result-link.json",
            "result_artifact_schema_version": 1,
            "result_artifact_sha256": result_digest,
        }
    )
    result_run = workspace / "runs" / "result-symlink-run.jsonl"
    _write_jsonl(result_run, result_records)

    with pytest.raises(AutoresearchError, match="cannot read result artifact"):
        validate_run(config, result_run)


@pytest.mark.parametrize(
    (
        "trace_status",
        "trace_failure_class",
        "generation_outcome",
        "terminal_failure_class",
        "message",
    ),
    [
        (
            "FAILED",
            "omni_job_terminal_failure",
            "answered",
            None,
            "terminal failure.*generation outcome",
        ),
        (
            "COMPLETE",
            None,
            "errored",
            "provider_error",
            "terminal failure.*generation outcome",
        ),
        ("FAILED", None, "answered", None, "status.*failure_class"),
        (
            "COMPLETE",
            "provider_error",
            "errored",
            "provider_error",
            "status.*failure_class",
        ),
        (
            "FAILED",
            "trace_compilation_error",
            "errored",
            "envelope_provider_error",
            "failure_class.*terminal_failure_class",
        ),
    ],
)
def test_complete_trace_terminal_failure_must_match_attempt_envelope(
    tmp_path: Path,
    trace_status: str,
    trace_failure_class: str | None,
    generation_outcome: str,
    terminal_failure_class: str | None,
    message: str,
) -> None:
    workspace, config = _workspace(tmp_path)
    trace_path = workspace / "runs" / "terminal-consistency.trace.jsonl"
    event = {
        "component": "omni-agent",
        "database_query_delta": 1,
        "duration_ms": 100,
        "elapsed_ms": 100,
        "event_type": "omni_job_status",
        "failure_class": trace_failure_class,
        "input_tokens": 10,
        "metadata_sha256": None,
        "model": "test-model",
        "output_tokens": 5,
        "provider": "test-provider",
        "retry_delta": 0,
        "schema_version": "trace-event-v2",
        "seq": 0,
        "status": trace_status,
        "timestamp": "2026-08-27T12:00:00.100Z",
        "tool_call_delta": 1,
        "tool_name": "query",
        "validation_attempt_delta": 1,
    }
    _write_jsonl(trace_path, [event])
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": "runs/terminal-consistency.trace.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        }
    )
    if generation_outcome != "answered":
        records[0].update(
            {
                "failure_origin": "evaluated_system",
                "generated_query": None,
                "generation_outcome": generation_outcome,
                "harness_failure": None,
                "outcome": "refused_or_error",
                "terminal_failure_class": terminal_failure_class,
            }
        )
    path = workspace / "runs" / f"terminal-{trace_status}-{generation_outcome}.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match=message):
        validate_run(config, path)


def test_complete_trace_preserves_unavailable_counters_as_null(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    trace_path = workspace / "runs" / "unavailable.trace.jsonl"
    event = {
        "component": "omni-agent",
        "database_query_delta": None,
        "duration_ms": 100,
        "elapsed_ms": 100,
        "event_type": "job_complete",
        "failure_class": None,
        "input_tokens": None,
        "metadata_sha256": None,
        "model": None,
        "output_tokens": None,
        "provider": None,
        "retry_delta": None,
        "schema_version": "trace-event-v2",
        "seq": 0,
        "status": "ok",
        "timestamp": "2026-08-27T12:00:00.100Z",
        "tool_call_delta": None,
        "tool_name": None,
        "validation_attempt_delta": None,
    }
    _write_jsonl(trace_path, [event])
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "database_query_count": None,
            "retry_count": None,
            "telemetry_unavailable": [
                "database_query_count",
                "retry_count",
                "tool_call_count",
                "validation_attempt_count",
            ],
            "token_source": "unavailable",
            "token_usage": None,
            "tool_call_count": None,
            "tool_calls_by_name": [],
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": "runs/unavailable.trace.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            "validation_attempt_count": None,
        }
    )
    path = workspace / "runs" / "unavailable-trace-counts.jsonl"
    _write_jsonl(path, records)

    assert validate_run(config, path).question_count == 2


@pytest.mark.parametrize(
    ("event_field", "message"),
    [
        ("input_tokens", "token totals must remain unavailable"),
        ("tool_call_delta", "tool_call_delta must remain unavailable"),
        ("database_query_delta", "database_query_delta must remain unavailable"),
        ("retry_delta", "retry_delta must remain unavailable"),
        (
            "validation_attempt_delta",
            "validation_attempt_delta must remain unavailable",
        ),
    ],
)
def test_complete_trace_cannot_claim_observed_values_missing_from_envelope(
    tmp_path: Path, event_field: str, message: str
) -> None:
    workspace, config = _workspace(tmp_path)
    trace_path = workspace / "runs" / f"contradictory-{event_field}.trace.jsonl"
    event = {
        "component": "omni-agent",
        "database_query_delta": None,
        "duration_ms": 100,
        "elapsed_ms": 100,
        "event_type": "job_complete",
        "failure_class": None,
        "input_tokens": None,
        "metadata_sha256": None,
        "model": None,
        "output_tokens": None,
        "provider": None,
        "retry_delta": None,
        "schema_version": "trace-event-v2",
        "seq": 0,
        "status": "ok",
        "timestamp": "2026-08-27T12:00:00.100Z",
        "tool_call_delta": None,
        "tool_name": None,
        "validation_attempt_delta": None,
    }
    event[event_field] = 1
    _write_jsonl(trace_path, [event])
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "database_query_count": None,
            "retry_count": None,
            "telemetry_unavailable": [
                "database_query_count",
                "retry_count",
                "tool_call_count",
                "validation_attempt_count",
            ],
            "token_source": "unavailable",
            "token_usage": None,
            "tool_call_count": None,
            "tool_calls_by_name": [],
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": f"runs/contradictory-{event_field}.trace.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            "validation_attempt_count": None,
        }
    )
    path = workspace / "runs" / f"contradictory-{event_field}.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match=message):
        validate_run(config, path)


def test_complete_trace_must_reconcile_tool_call_totals(tmp_path: Path) -> None:
    workspace, config = _workspace(tmp_path)
    trace_path = workspace / "runs" / "tool-count.trace.jsonl"
    event = {
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
        "tool_call_delta": 0,
        "tool_name": "query",
        "validation_attempt_delta": 1,
    }
    _write_jsonl(trace_path, [event])
    records = [_record("dev_a_1"), _record("dev_a_2")]
    records[0].update(
        {
            "trace_captured": True,
            "trace_degraded_reason": None,
            "trace_path": "runs/tool-count.trace.jsonl",
            "trace_schema_version": "trace-event-v2",
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        }
    )
    path = workspace / "runs" / "tool-count-mismatch.jsonl"
    _write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="tool_call_delta total"):
        validate_run(config, path)

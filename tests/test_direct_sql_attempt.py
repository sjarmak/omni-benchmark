from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from omni_benchmark.artifact_store import ArtifactStore, StoredArtifact
from omni_benchmark.content_policy import ContentPolicy
import omni_benchmark.direct_sql_attempt as direct_attempt
import omni_benchmark.direct_trace_validation as direct_trace
from omni_benchmark.direct_capture_receipt import (
    capture_receipt_payload,
    capture_summary_payload,
)
from omni_benchmark.direct_sql_attempt import DirectAttemptSpec, write_direct_attempt
from omni_benchmark.direct_runtime_binding import DirectRuntimeBinding
from omni_benchmark.direct_sql_capture import (
    DirectModelTurnProvenance,
    DirectProbeResult,
)
from tests.direct_attempt_fixtures import attempt_spec, capture_probe
from tests.direct_capture_fixtures import runtime_binding


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
COMMIT = "e" * 40
QUESTION = "Public synthetic question"
QUESTION_SHA256 = hashlib.sha256(QUESTION.encode("utf-8")).hexdigest()


def _workspace(tmp_path: Path) -> tuple[Path, ArtifactStore]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return workspace, ArtifactStore(workspace, Path("runs/direct-attempt"))


def _matrix_event(**changes: object) -> dict[str, object]:
    event: dict[str, object] = {
        "component": "direct-sql-harness",
        "database_query_delta": 0,
        "event_type": "direct_model_turn",
        "failure_class": None,
        "input_tokens": 1,
        "output_tokens": 1,
        "retry_delta": 0,
        "status": "SUCCESS",
        "tool_call_delta": 0,
        "tool_name": None,
        "validation_attempt_delta": 0,
    }
    return {**event, **changes}


def _receipt(
    store: ArtifactStore,
    *,
    binding: DirectRuntimeBinding,
    trace: StoredArtifact,
    action_evidence: StoredArtifact,
    result: StoredArtifact | None,
    sql: str | None,
    capture_summary: Mapping[str, Any],
    name: str = "capture.receipt.json",
) -> StoredArtifact:
    return store.write_json(
        Path(name),
        capture_receipt_payload(
            store=store,
            binding=binding,
            sql=sql,
            trace=trace,
            action_evidence=action_evidence,
            result=result,
            capture_summary=capture_summary,
        ),
    )


def _refused_attempt(
    tmp_path: Path,
) -> tuple[Path, ArtifactStore, DirectProbeResult, DirectAttemptSpec]:
    workspace, store, binding, probe = capture_probe(
        tmp_path,
        actions=[{"type": "refuse", "reason": "cannot_answer_safely"}],
        instance_id="public-atomic",
        run_id="run-atomic",
        system_commit=COMMIT,
    )
    return workspace, store, probe, attempt_spec(binding)


@pytest.mark.parametrize(
    ("condition", "event"),
    [
        ("C1", _matrix_event()),
        (
            "C2",
            _matrix_event(
                event_type="direct_tool_dispatch",
                input_tokens=0,
                output_tokens=0,
                tool_call_delta=1,
                tool_name="search_hkb",
            ),
        ),
        (
            "C3",
            _matrix_event(
                database_query_delta=1,
                event_type="direct_tool_dispatch",
                input_tokens=0,
                output_tokens=0,
                tool_call_delta=1,
                tool_name="execute_sql",
            ),
        ),
        (
            "C1",
            _matrix_event(
                database_query_delta=1,
                event_type="direct_final_sql_execution",
                input_tokens=0,
                output_tokens=0,
                status="COMPLETE",
                tool_name="execute_sql",
            ),
        ),
        (
            "C1",
            _matrix_event(
                event_type="direct_refusal",
                failure_class="agent_refusal",
                input_tokens=0,
                output_tokens=0,
                status="DENIED",
            ),
        ),
        (
            "C1",
            _matrix_event(
                event_type="direct_capture_failure",
                failure_class="turn_limit_exhausted",
                input_tokens=0,
                output_tokens=0,
                status="ERROR",
            ),
        ),
        (
            "C1",
            _matrix_event(
                database_query_delta=None,
                event_type="direct_final_sql_execution",
                failure_class="database_infrastructure_error",
                input_tokens=0,
                output_tokens=0,
                status="ERROR",
                tool_name="execute_sql",
            ),
        ),
        (
            "C1",
            _matrix_event(
                database_query_delta=0,
                event_type="direct_tool_dispatch",
                failure_class="database_identity_mismatch",
                input_tokens=0,
                output_tokens=0,
                status="ERROR",
                tool_call_delta=1,
                tool_name="execute_sql",
            ),
        ),
    ],
)
def test_publisher_accepts_only_the_direct_trace_event_matrix(
    condition: str, event: dict[str, object]
) -> None:
    direct_trace._validate_trace_capability(event, condition)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "event",
    [
        _matrix_event(status="COMPLETE"),
        _matrix_event(database_query_delta=1),
        _matrix_event(validation_attempt_delta=1),
        _matrix_event(
            event_type="direct_tool_dispatch",
            input_tokens=0,
            output_tokens=0,
            tool_call_delta=1,
            tool_name="inspect_schema",
            database_query_delta=1,
        ),
        _matrix_event(
            event_type="direct_final_sql_execution",
            input_tokens=0,
            output_tokens=0,
            status="COMPLETE",
            tool_name="execute_sql",
        ),
        _matrix_event(
            event_type="direct_refusal",
            failure_class="wrong_failure",
            input_tokens=0,
            output_tokens=0,
            status="DENIED",
        ),
    ],
)
def test_publisher_rejects_impossible_trace_event_combinations(
    event: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        direct_trace._validate_trace_capability(event, "C1")


@pytest.mark.parametrize(
    ("outcome", "events"),
    [
        (
            "answered",
            [
                _matrix_event(),
                _matrix_event(
                    event_type="direct_final_sql_execution", status="COMPLETE"
                ),
            ],
        ),
        (
            "refused",
            [
                _matrix_event(),
                _matrix_event(event_type="direct_refusal", status="DENIED"),
            ],
        ),
        ("errored", [_matrix_event(status="ERROR")]),
    ],
)
def test_publisher_requires_outcome_specific_terminal_lifecycle(
    outcome: str, events: list[dict[str, object]]
) -> None:
    direct_trace._validate_trace_lifecycle(
        events, SimpleNamespace(generation_outcome=outcome, maximum_turns=12)
    )


def test_turn_limit_after_tool_dispatch_captures_and_publishes_failure(
    tmp_path: Path,
) -> None:
    workspace, store, binding, probe = capture_probe(
        tmp_path,
        actions=[
            {"type": "tool", "name": "inspect_schema", "arguments": {}},
        ],
        instance_id="public-exhausted",
        maximum_turns=1,
        run_id="run-exhausted",
        system_commit=COMMIT,
    )

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=store,
        spec=attempt_spec(binding),
        probe=probe,
    )

    generation = json.loads(artifacts.generation.path.read_text())
    assert generation["generation_outcome"] == "errored"
    assert generation["terminal_failure_class"] == "turn_limit_exhausted"


def test_arbitrary_capture_failure_cannot_bypass_turn_sequence() -> None:
    events = [
        _matrix_event(),
        _matrix_event(
            event_type="direct_tool_dispatch",
            input_tokens=0,
            output_tokens=0,
            tool_call_delta=1,
            tool_name="inspect_schema",
        ),
        _matrix_event(
            event_type="direct_capture_failure",
            failure_class="unauthorized_tool",
            input_tokens=0,
            output_tokens=0,
            status="ERROR",
        ),
    ]

    with pytest.raises(ValueError, match="begin each turn"):
        direct_trace._validate_trace_lifecycle(
            events,
            SimpleNamespace(
                failure_class="unauthorized_tool",
                generation_outcome="errored",
                maximum_turns=12,
            ),
        )


def test_turn_limit_terminal_requires_a_preceding_tool_dispatch() -> None:
    terminal = _matrix_event(
        event_type="direct_capture_failure",
        failure_class="turn_limit_exhausted",
        input_tokens=0,
        output_tokens=0,
        status="ERROR",
    )

    with pytest.raises(ValueError, match="turn-limit terminal"):
        direct_trace._validate_trace_lifecycle(
            [terminal],
            SimpleNamespace(
                failure_class="turn_limit_exhausted",
                generation_outcome="errored",
                maximum_turns=1,
            ),
        )


def test_turn_limit_terminal_cannot_follow_a_successful_model_turn() -> None:
    events = [
        _matrix_event(),
        _matrix_event(
            event_type="direct_capture_failure",
            failure_class="turn_limit_exhausted",
            input_tokens=0,
            output_tokens=0,
            status="ERROR",
        ),
    ]

    with pytest.raises(ValueError, match="turn-limit terminal"):
        direct_trace._validate_trace_lifecycle(
            events,
            SimpleNamespace(
                failure_class="turn_limit_exhausted",
                generation_outcome="errored",
                maximum_turns=1,
            ),
        )


def test_turn_limit_terminal_requires_exactly_the_configured_model_turns() -> None:
    events = [
        _matrix_event(),
        _matrix_event(
            event_type="direct_tool_dispatch",
            input_tokens=0,
            output_tokens=0,
            tool_call_delta=1,
            tool_name="inspect_schema",
        ),
        _matrix_event(
            event_type="direct_capture_failure",
            failure_class="turn_limit_exhausted",
            input_tokens=0,
            output_tokens=0,
            status="ERROR",
        ),
    ]

    with pytest.raises(ValueError, match="turn-limit terminal"):
        direct_trace._validate_trace_lifecycle(
            events,
            SimpleNamespace(
                failure_class="turn_limit_exhausted",
                generation_outcome="errored",
                maximum_turns=2,
            ),
        )


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_publisher_rejects_nonfinite_result_json(tmp_path: Path, constant: str) -> None:
    workspace, store = _workspace(tmp_path)
    artifact = store.write_bytes(
        Path(f"nonfinite-{constant.removeprefix('-')}.result.json"),
        (
            '{"columns":["column_1"],"rows":[['
            + constant
            + ']],"schema_version":1,"truncated":false}\n'
        ).encode(),
    )

    with pytest.raises(ValueError, match="not valid JSON"):
        direct_attempt._validate_result_artifact(
            workspace,
            SimpleNamespace(result_artifact=artifact),
            ContentPolicy.from_environment({}),
        )


@pytest.mark.parametrize(
    "foreign_field", ["receipt", "trace", "action_evidence", "result_artifact"]
)
def test_publisher_rejects_cross_attempt_artifact_substitution(
    tmp_path: Path, foreign_field: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    first = ArtifactStore(workspace, Path("runs/attempt-a"))
    second = ArtifactStore(workspace, Path("runs/attempt-b"))

    def artifacts(store: ArtifactStore, value: str) -> SimpleNamespace:
        return SimpleNamespace(
            receipt=store.write_json(Path("capture.receipt.json"), {"value": value}),
            trace=store.write_jsonl(Path("attempt.trace.jsonl"), [{"value": value}]),
            action_evidence=store.write_json(
                Path("attempt.action-evidence.json"), {"value": value}
            ),
            result_artifact=store.write_json(
                Path("answer.result.json"), {"value": value}
            ),
        )

    own = artifacts(first, "a")
    foreign = artifacts(second, "b")
    substituted = SimpleNamespace(
        receipt=foreign.receipt if foreign_field == "receipt" else own.receipt,
        trace=foreign.trace if foreign_field == "trace" else own.trace,
        action_evidence=(
            foreign.action_evidence
            if foreign_field == "action_evidence"
            else own.action_evidence
        ),
        result_artifact=(
            foreign.result_artifact
            if foreign_field == "result_artifact"
            else own.result_artifact
        ),
    )

    with pytest.raises(ValueError, match="destination root"):
        direct_attempt._validate_root_binding(workspace, first, substituted)


@pytest.mark.parametrize(
    "event",
    [
        _matrix_event(
            database_query_delta=1,
            event_type="direct_tool_dispatch",
            failure_class="sql_not_admitted",
            input_tokens=0,
            output_tokens=0,
            status="ERROR",
            tool_call_delta=1,
            tool_name="execute_sql",
        ),
        _matrix_event(
            event_type="direct_final_sql_execution",
            failure_class="candidate_no_result",
            input_tokens=0,
            output_tokens=0,
            status="ERROR",
            tool_name="execute_sql",
        ),
        _matrix_event(
            event_type="direct_final_sql_execution",
            failure_class="database_execution_error",
            input_tokens=0,
            output_tokens=0,
            status="ERROR",
            tool_name="execute_sql",
        ),
    ],
)
def test_publisher_rejects_failure_specific_database_delta_mismatches(
    event: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="database query|SQL execution"):
        direct_trace._validate_trace_capability(event, "C1")


@pytest.mark.parametrize(
    "spec_change",
    [
        {"semantic_model_ref": "invalid provenance with spaces"},
        {"controllable_seed": "invalid"},
    ],
)
def test_invalid_manifest_provenance_publishes_no_attempt_artifacts(
    tmp_path: Path, spec_change: dict[str, object]
) -> None:
    workspace, store, probe, spec = _refused_attempt(tmp_path)

    with pytest.raises(ValueError, match="semantic_model_ref|controllable_seed"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=replace(spec, **spec_change),
            probe=probe,
        )

    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()
    assert not (workspace / "runs/direct-attempt/run.json").exists()


@pytest.mark.parametrize("field", ["latency_ms", "cost_usd"])
@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")])
def test_publisher_rejects_nonfinite_attempt_record(
    tmp_path: Path, constant: float, field: str
) -> None:
    workspace, store, probe, spec = _refused_attempt(tmp_path)

    with pytest.raises(ValueError, match="finite JSON"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, **{field: constant}),
        )
    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()


@pytest.mark.parametrize(
    ("field", "value"), [("latency_ms", -0.1), ("cost_usd", -0.001)]
)
def test_publisher_rejects_negative_attempt_measurements(
    tmp_path: Path, field: str, value: float
) -> None:
    workspace, store, probe, spec = _refused_attempt(tmp_path)

    with pytest.raises(ValueError, match="non-negative"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, **{field: value}),
        )
    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()
    assert not (workspace / "runs/direct-attempt/run.json").exists()


@pytest.mark.parametrize("field", ["duration_ms", "elapsed_ms"])
@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")])
def test_publisher_rejects_nonfinite_trace_durations(
    constant: float, field: str
) -> None:
    event = {
        "component": "direct-sql-harness",
        "duration_ms": 0.0,
        "elapsed_ms": 0.0,
        "event_type": "direct_model_turn",
        "metadata_sha256": None,
        "status": "SUCCESS",
    }
    event[field] = constant

    with pytest.raises(ValueError, match="duration"):
        direct_trace._validate_trace_scalars(event)


def test_capture_failure_terminal_rejects_database_failure_classes() -> None:
    event = _matrix_event(
        event_type="direct_capture_failure",
        failure_class="database_statement_error",
        input_tokens=0,
        output_tokens=0,
        status="ERROR",
    )

    with pytest.raises(ValueError, match="capture failure"):
        direct_trace._validate_trace_capability(event, "C1")


def test_lifecycle_rejects_more_model_turns_than_the_capture_budget() -> None:
    events = [
        _matrix_event(),
        _matrix_event(
            event_type="direct_tool_dispatch",
            input_tokens=0,
            output_tokens=0,
            tool_call_delta=1,
            tool_name="inspect_schema",
        ),
        _matrix_event(),
        _matrix_event(
            event_type="direct_refusal",
            failure_class="agent_refusal",
            input_tokens=0,
            output_tokens=0,
            status="DENIED",
        ),
    ]

    with pytest.raises(ValueError, match="maximum_turns"):
        direct_trace._validate_trace_lifecycle(
            events,
            SimpleNamespace(
                failure_class="agent_refusal",
                generation_outcome="refused",
                maximum_turns=1,
            ),
        )


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "retry_delta"])
def test_failed_model_turn_rejects_invalid_usage(field: str) -> None:
    event = _matrix_event(
        status="ERROR",
        failure_class="model_rate_limit_error",
        input_tokens=0,
        output_tokens=0,
        retry_delta=0,
    )
    event[field] = -1

    with pytest.raises(ValueError, match="model usage telemetry"):
        direct_trace._validate_trace_capability(event, "C1")


def test_failed_model_turn_preserves_observable_usage() -> None:
    event = _matrix_event(
        status="ERROR",
        failure_class="model_rate_limit_error",
        input_tokens=123,
        output_tokens=7,
        retry_delta=2,
    )

    direct_trace._validate_trace_capability(event, "C1")


def test_attempt_rejects_condition_or_model_identity_mismatch(tmp_path: Path) -> None:
    binding = runtime_binding(
        "C1",
        instance_id="public-1",
        run_id="run-1",
        system_commit=COMMIT,
    )
    workspace, store = _workspace(tmp_path)
    turn_provenance = DirectModelTurnProvenance.unavailable(
        trace_seq=0, identity=binding.model
    )
    trace = store.write_jsonl(
        Path("attempt.trace.jsonl"),
        [
            {
                "component": "direct-sql-harness",
                "database_query_delta": 0,
                "duration_ms": 0.0,
                "elapsed_ms": 0.0,
                "event_type": "direct_model_turn",
                "failure_class": None,
                "input_tokens": None,
                "metadata_sha256": turn_provenance.sha256(),
                "model": "fixture-model",
                "output_tokens": None,
                "provider": "fixture-provider",
                "retry_delta": None,
                "schema_version": "trace-event-v2",
                "seq": 0,
                "status": "SUCCESS",
                "timestamp": "2026-08-28T04:00:00Z",
                "tool_call_delta": 0,
                "tool_name": None,
                "validation_attempt_delta": 0,
            },
            {
                "component": "direct-sql-harness",
                "database_query_delta": 0,
                "duration_ms": 0.0,
                "elapsed_ms": 0.0,
                "event_type": "direct_refusal",
                "failure_class": "agent_refusal",
                "input_tokens": None,
                "metadata_sha256": SHA_B,
                "model": "fixture-model",
                "output_tokens": None,
                "provider": "fixture-provider",
                "retry_delta": None,
                "schema_version": "trace-event-v2",
                "seq": 1,
                "status": "DENIED",
                "timestamp": "2026-08-28T04:00:00Z",
                "tool_call_delta": 0,
                "tool_name": None,
                "validation_attempt_delta": 0,
            },
        ],
    )
    action_evidence = store.write_json(
        Path("attempt.action-evidence.json"),
        {
            "kind": "direct-action-evidence",
            "records": [],
            "runtime_binding_sha256": binding.sha256(),
            "schema_version": 1,
            "trace_sha256": trace.sha256,
        },
    )
    probe = DirectProbeResult(
        binding=binding,
        condition="C1",
        attempt_id="run-1:public-1:C1:1",
        maximum_turns=12,
        question_sha256=QUESTION_SHA256,
        generation_outcome="refused",
        failure_class="agent_refusal",
        trace=trace,
        action_evidence=action_evidence,
        receipt=_receipt(
            store,
            binding=binding,
            trace=trace,
            action_evidence=action_evidence,
            result=None,
            sql=None,
            capture_summary=capture_summary_payload(
                generation_outcome="refused",
                failure_class="agent_refusal",
                failure_origin="evaluated_system",
                semantic_objects=(),
                tool_calls_by_name=(),
                tool_call_count=0,
                database_query_count=0,
                validation_attempt_count=0,
                retry_count=None,
                token_usage=None,
                token_source="unavailable",
                cost_usd=None,
                cost_source="unavailable",
                started_at="2026-08-28T04:00:00Z",
                finished_at="2026-08-28T04:00:00Z",
                latency_ms=0.0,
                model_turn_provenance=(turn_provenance,),
            ),
        ),
        result_artifact=None,
        generated_sql=None,
        semantic_objects=(),
        tool_calls_by_name=(),
        tool_call_count=0,
        database_query_count=0,
        validation_attempt_count=0,
        retry_count=None,
        token_usage=None,
        token_source="unavailable",
        cost_usd=None,
        cost_source="unavailable",
        provider="fixture-provider",
        model="fixture-model",
        started_at="2026-08-28T04:00:00Z",
        finished_at="2026-08-28T04:00:00Z",
        latency_ms=0.0,
        model_turn_provenance=(turn_provenance,),
        failure_origin="evaluated_system",
    )
    other_binding = runtime_binding(
        "C2",
        instance_id="public-1",
        run_id="run-1",
        system_commit=COMMIT,
    )
    spec = attempt_spec(other_binding)

    with pytest.raises(ValueError, match="runtime binding"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=probe,
        )

    aligned_spec = attempt_spec(binding)
    with pytest.raises(ValueError, match="token source"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=aligned_spec,
            probe=replace(probe, token_source="provider_reported"),
        )

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=store,
        spec=aligned_spec,
        probe=probe,
    )
    generation = json.loads(artifacts.generation.path.read_text())
    assert generation["generation_outcome"] == "refused"
    assert generation["database_query_count"] == 0
    assert generation["telemetry_unavailable"] == ["retry_count"]

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from omni_benchmark.artifact_store import ArtifactStore, StoredArtifact
from omni_benchmark.content_policy import ContentPolicy
import omni_benchmark.direct_sql_attempt as direct_attempt
from omni_benchmark.direct_sql_attempt import DirectAttemptSpec, write_direct_attempt
from omni_benchmark.direct_sql_capture import (
    DirectDatabaseAttestation,
    DirectModelTurn,
    DirectProbeResult,
    DirectReferenceResult,
    DirectSqlCapture,
)


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
    attempt_id: str,
    condition: str,
    trace: StoredArtifact,
    result: StoredArtifact | None,
    sql: str | None,
    name: str = "capture.receipt.json",
) -> StoredArtifact:
    trace_path = store.relative_path(trace)
    result_path = store.relative_path(result) if result is not None else None
    return store.write_json(
        Path(name),
        {
            "artifact_root_identity": store.root_identity,
            "attempt_id": attempt_id,
            "condition": condition,
            "generated_sql_sha256": hashlib.sha256(sql.encode()).hexdigest()
            if sql
            else None,
            "maximum_turns": 12,
            "model": "fixture-model",
            "provider": "fixture-provider",
            "question_sha256": QUESTION_SHA256,
            "result_path": result_path.as_posix() if result_path else None,
            "result_sha256": result.sha256 if result is not None else None,
            "schema_version": 1,
            "trace_path": trace_path.as_posix(),
            "trace_sha256": trace.sha256,
        },
    )


def _refused_attempt(
    tmp_path: Path,
) -> tuple[Path, ArtifactStore, DirectProbeResult, DirectAttemptSpec]:
    class RefusingModel:
        def next_turn(self, messages: object, tool_specs: object) -> DirectModelTurn:
            return DirectModelTurn(
                action={"type": "refuse", "reason": "cannot_answer_safely"},
                input_tokens=1,
                output_tokens=1,
                retry_count=0,
                cost_usd=0.001,
            )

    class AttestedDatabase:
        execution_attestation = DirectDatabaseAttestation(True, True)

        def connect(self) -> object:
            raise AssertionError("refused attempt must not connect")

    workspace, store = _workspace(tmp_path)
    probe = DirectSqlCapture(
        condition="C1",
        model_transport=RefusingModel(),
        database=AttestedDatabase(),
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(20)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture(QUESTION, attempt_id="run-atomic:public-atomic:C1:1")
    spec = DirectAttemptSpec(
        condition="C1",
        scope="dev-a",
        instance_id="public-atomic",
        question=QUESTION,
        run_id="run-atomic",
        repetition=1,
        controllable_seed=None,
        provider="fixture-provider",
        model="fixture-model",
        model_version="fixture-v1",
        git_commit=COMMIT,
        harness_config_sha256=SHA_A,
        prompt_sha256=SHA_B,
        instructions_sha256=SHA_C,
        semantic_model_ref="raw-schema:fixture-v1",
        semantic_model_sha256=None,
        model_config_id="direct-sql-v1",
        budget_id="standard-120s-v1",
        software_versions={"omni-benchmark": "0.1.0"},
        cli_versions={"direct-harness": "0.1.0"},
    )
    return workspace, store, probe, spec


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
    ],
)
def test_publisher_accepts_only_the_direct_trace_event_matrix(
    condition: str, event: dict[str, object]
) -> None:
    direct_attempt._validate_trace_capability(event, condition)  # type: ignore[arg-type]


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
        direct_attempt._validate_trace_capability(event, "C1")


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
    direct_attempt._validate_trace_lifecycle(
        events, SimpleNamespace(generation_outcome=outcome, maximum_turns=12)
    )


def test_turn_limit_after_tool_dispatch_captures_and_publishes_failure(
    tmp_path: Path,
) -> None:
    class ToolModel:
        def next_turn(self, messages: object, tool_specs: object) -> DirectModelTurn:
            return DirectModelTurn(
                action={"type": "tool", "name": "inspect_schema", "arguments": {}},
                input_tokens=4,
                output_tokens=2,
                retry_count=0,
                cost_usd=0.001,
            )

    class AttestedDatabase:
        execution_attestation = DirectDatabaseAttestation(True, True)

        def connect(self) -> object:
            raise AssertionError("schema-only exhausted attempt must not connect")

    workspace, store = _workspace(tmp_path)
    probe = DirectSqlCapture(
        condition="C1",
        model_transport=ToolModel(),
        database=AttestedDatabase(),
        inspect_schema=lambda: DirectReferenceResult({"tables": ["public_table"]}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        maximum_turns=1,
        clock=iter(index / 10 for index in range(20)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture(QUESTION, attempt_id="run-exhausted:public-exhausted:C1:1")
    spec = DirectAttemptSpec(
        condition="C1",
        scope="dev-a",
        instance_id="public-exhausted",
        question=QUESTION,
        run_id="run-exhausted",
        repetition=1,
        controllable_seed=None,
        provider="fixture-provider",
        model="fixture-model",
        model_version="fixture-v1",
        git_commit=COMMIT,
        harness_config_sha256=SHA_A,
        prompt_sha256=SHA_B,
        instructions_sha256=SHA_C,
        semantic_model_ref="raw-schema:fixture-v1",
        semantic_model_sha256=None,
        model_config_id="direct-sql-v1",
        budget_id="standard-120s-v1",
        software_versions={"omni-benchmark": "0.1.0"},
        cli_versions={"direct-harness": "0.1.0"},
    )

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=store,
        spec=spec,
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
        direct_attempt._validate_trace_lifecycle(
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
        direct_attempt._validate_trace_lifecycle(
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
        direct_attempt._validate_trace_lifecycle(
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
        direct_attempt._validate_trace_lifecycle(
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


@pytest.mark.parametrize("foreign_field", ["receipt", "trace", "result_artifact"])
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
            result_artifact=store.write_json(
                Path("answer.result.json"), {"value": value}
            ),
        )

    own = artifacts(first, "a")
    foreign = artifacts(second, "b")
    substituted = SimpleNamespace(
        receipt=foreign.receipt if foreign_field == "receipt" else own.receipt,
        trace=foreign.trace if foreign_field == "trace" else own.trace,
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
        direct_attempt._validate_trace_capability(event, "C1")


@pytest.mark.parametrize(
    "spec_change",
    [
        {"scope": "sealed-test"},
        {"semantic_model_ref": "invalid provenance with spaces"},
    ],
)
def test_invalid_manifest_provenance_publishes_no_attempt_artifacts(
    tmp_path: Path, spec_change: dict[str, object]
) -> None:
    workspace, store, probe, spec = _refused_attempt(tmp_path)

    with pytest.raises(ValueError, match="scope|semantic_model_ref"):
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
        direct_attempt._validate_trace_scalars(event)


def test_capture_failure_terminal_rejects_database_failure_classes() -> None:
    event = _matrix_event(
        event_type="direct_capture_failure",
        failure_class="database_statement_error",
        input_tokens=0,
        output_tokens=0,
        status="ERROR",
    )

    with pytest.raises(ValueError, match="capture failure"):
        direct_attempt._validate_trace_capability(event, "C1")


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
        direct_attempt._validate_trace_lifecycle(
            events,
            SimpleNamespace(
                failure_class="agent_refusal",
                generation_outcome="refused",
                maximum_turns=1,
            ),
        )


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "retry_delta"])
def test_failed_model_turn_cannot_claim_usage(field: str) -> None:
    event = _matrix_event(
        status="ERROR",
        failure_class="model_transport_error",
        input_tokens=0,
        output_tokens=0,
        retry_delta=0,
    )
    event[field] = 1

    with pytest.raises(ValueError, match="usage telemetry"):
        direct_attempt._validate_trace_capability(event, "C1")


def test_answered_attempt_writes_generation_and_hash_bound_run_manifest(
    tmp_path: Path,
) -> None:
    workspace, store = _workspace(tmp_path)
    trace = store.write_jsonl(
        Path("attempt.trace.jsonl"),
        [
            {
                "component": "direct-sql-harness",
                "database_query_delta": 0,
                "duration_ms": 1.0,
                "elapsed_ms": 1.0,
                "event_type": "direct_model_turn",
                "failure_class": None,
                "input_tokens": 10,
                "metadata_sha256": SHA_A,
                "model": "fixture-model",
                "output_tokens": 2,
                "provider": "fixture-provider",
                "retry_delta": 0,
                "schema_version": "trace-event-v2",
                "seq": 0,
                "status": "SUCCESS",
                "timestamp": "2026-08-28T04:00:01Z",
                "tool_call_delta": 0,
                "tool_name": None,
                "validation_attempt_delta": 0,
            },
            {
                "component": "direct-sql-harness",
                "database_query_delta": 1,
                "duration_ms": 1.0,
                "elapsed_ms": 2.0,
                "event_type": "direct_final_sql_execution",
                "failure_class": None,
                "input_tokens": 0,
                "metadata_sha256": SHA_B,
                "model": "fixture-model",
                "output_tokens": 0,
                "provider": "fixture-provider",
                "retry_delta": 0,
                "schema_version": "trace-event-v2",
                "seq": 1,
                "status": "COMPLETE",
                "timestamp": "2026-08-28T04:00:02Z",
                "tool_call_delta": 0,
                "tool_name": "execute_sql",
                "validation_attempt_delta": 0,
            },
        ],
    )
    result_artifact = store.write_json(
        Path("answer.result.json"),
        {
            "columns": ["column_1"],
            "rows": [[42]],
            "schema_version": 1,
            "truncated": False,
        },
    )
    receipt = _receipt(
        store,
        attempt_id="run-1:public-1:C2:1",
        condition="C2",
        trace=trace,
        result=result_artifact,
        sql="SELECT 42",
    )
    probe = DirectProbeResult(
        condition="C2",
        attempt_id="run-1:public-1:C2:1",
        maximum_turns=12,
        question_sha256=QUESTION_SHA256,
        generation_outcome="answered",
        failure_class=None,
        trace=trace,
        receipt=receipt,
        result_artifact=result_artifact,
        generated_sql="SELECT 42",
        semantic_objects=(),
        tool_calls_by_name=(),
        tool_call_count=0,
        database_query_count=1,
        validation_attempt_count=0,
        retry_count=0,
        token_usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        token_source="provider_reported",
        cost_usd=0.001,
        cost_source="provider_reported",
        provider="fixture-provider",
        model="fixture-model",
        started_at="2026-08-28T04:00:00Z",
        finished_at="2026-08-28T04:00:01Z",
        latency_ms=1000.0,
    )
    spec = DirectAttemptSpec(
        condition="C2",
        scope="dev-a",
        instance_id="public-1",
        question=QUESTION,
        run_id="run-1",
        repetition=1,
        controllable_seed=17,
        provider="fixture-provider",
        model="fixture-model",
        model_version="fixture-v1",
        git_commit=COMMIT,
        harness_config_sha256=SHA_A,
        prompt_sha256=SHA_B,
        instructions_sha256=SHA_C,
        semantic_model_ref="public-hkb:fixture-v1",
        semantic_model_sha256=SHA_D,
        model_config_id="direct-sql-v1",
        budget_id="standard-120s-v1",
        software_versions={"omni-benchmark": "0.1.0", "python": "3.11.9"},
        cli_versions={"direct-harness": "0.1.0"},
    )

    with pytest.raises(ValueError, match="trace telemetry"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, tool_call_count=2),
        )
    with pytest.raises(ValueError, match="question"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=replace(spec, question="A different public question"),
            probe=probe,
        )
    impossible_trace = store.write_jsonl(
        Path("impossible.trace.jsonl"),
        [
            {
                "component": "direct-sql-harness",
                "database_query_delta": 1,
                "duration_ms": 1.0,
                "elapsed_ms": 1.0,
                "event_type": "direct_model_turn",
                "failure_class": None,
                "input_tokens": 10,
                "metadata_sha256": SHA_A,
                "model": "fixture-model",
                "output_tokens": 2,
                "provider": "fixture-provider",
                "retry_delta": 0,
                "schema_version": "trace-event-v2",
                "seq": 0,
                "status": "COMPLETE",
                "timestamp": "2026-08-28T04:00:01Z",
                "tool_call_delta": 0,
                "tool_name": None,
                "validation_attempt_delta": 0,
            }
        ],
    )
    with pytest.raises(ValueError, match="trace.*(lifecycle|model|database)"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, trace=impossible_trace),
        )
    valid_events = [json.loads(line) for line in trace.path.read_text().splitlines()]
    event_after_terminal = {
        **valid_events[0],
        "elapsed_ms": 3.0,
        "input_tokens": 0,
        "metadata_sha256": SHA_C,
        "output_tokens": 0,
        "seq": 2,
        "timestamp": "2026-08-28T04:00:03Z",
    }
    post_terminal_trace = store.write_jsonl(
        Path("post-terminal.trace.jsonl"),
        [*valid_events, event_after_terminal],
    )
    with pytest.raises(ValueError, match="after a terminal event"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, trace=post_terminal_trace),
        )
    duplicate_terminal = {
        **valid_events[-1],
        "elapsed_ms": 3.0,
        "metadata_sha256": SHA_C,
        "seq": 2,
        "timestamp": "2026-08-28T04:00:03Z",
    }
    duplicate_terminal_trace = store.write_jsonl(
        Path("duplicate-terminal.trace.jsonl"),
        [*valid_events, duplicate_terminal],
    )
    with pytest.raises(ValueError, match="after a terminal event"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(
                probe,
                trace=duplicate_terminal_trace,
                database_query_count=2,
            ),
        )
    forged_trace = store.write_jsonl(
        Path("forged.trace.jsonl"),
        [
            {
                "component": "direct-sql-harness",
                "database_query_delta": 0,
                "duration_ms": 1.0,
                "elapsed_ms": 1.0,
                "event_type": "direct_tool_dispatch",
                "failure_class": None,
                "input_tokens": 10,
                "metadata_sha256": SHA_A,
                "model": "fixture-model",
                "output_tokens": 2,
                "provider": "fixture-provider",
                "retry_delta": 0,
                "schema_version": "trace-event-v2",
                "seq": 0,
                "status": "SUCCESS",
                "timestamp": "2026-08-28T04:00:01Z",
                "tool_call_delta": 1,
                "tool_name": "search_hkb",
                "validation_attempt_delta": 0,
            },
            {
                "component": "direct-sql-harness",
                "database_query_delta": 1,
                "duration_ms": 1.0,
                "elapsed_ms": 2.0,
                "event_type": "direct_final_sql_execution",
                "failure_class": None,
                "input_tokens": 0,
                "metadata_sha256": SHA_B,
                "model": "fixture-model",
                "output_tokens": 0,
                "provider": "fixture-provider",
                "retry_delta": 0,
                "schema_version": "trace-event-v2",
                "seq": 1,
                "status": "COMPLETE",
                "timestamp": "2026-08-28T04:00:02Z",
                "tool_call_delta": 0,
                "tool_name": "execute_sql",
                "validation_attempt_delta": 0,
            },
        ],
    )
    c1_spec = replace(
        spec,
        condition="C1",
        semantic_model_ref="raw-schema:fixture-v1",
        semantic_model_sha256=None,
    )
    forged_probe = replace(
        probe,
        condition="C1",
        attempt_id="run-1:public-1:C1:1",
        trace=forged_trace,
        generated_sql="UPDATE x SET y = 1",
        semantic_objects=("forged.metric",),
        tool_calls_by_name=(("search_hkb", 1),),
        tool_call_count=1,
    )
    with pytest.raises(ValueError, match="SQL|capability|semantic|attempt"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=c1_spec,
            probe=forged_probe,
        )
    with pytest.raises(ValueError, match="capability"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=c1_spec,
            probe=replace(
                forged_probe,
                generated_sql="SELECT 42",
                semantic_objects=(),
            ),
        )
    with pytest.raises(ValueError, match="semantic"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=c1_spec,
            probe=replace(
                probe,
                condition="C1",
                attempt_id="run-1:public-1:C1:1",
                semantic_objects=("forged.metric",),
            ),
        )
    with pytest.raises(ValueError, match="result artifact"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(
                probe,
                result_artifact=replace(result_artifact, sha256=SHA_A),
            ),
        )
    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=store,
        spec=spec,
        probe=probe,
    )

    generation = json.loads(artifacts.generation.path.read_text())
    manifest = json.loads(artifacts.run_manifest.path.read_text())
    assert generation["attempt_id"] == "run-1:public-1:C2:1"
    assert generation["generation_outcome"] == "answered"
    assert generation["generated_sql"] == "SELECT 42"
    assert generation["actual_result_hash"] == result_artifact.sha256
    assert generation["tool_call_count"] == 0
    assert generation["token_usage"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
    }
    assert manifest["condition"] == "C2"
    assert manifest["scope"] == "dev-a"
    assert manifest["controllable_seed"] == 17
    assert manifest["generation_sha256"] == artifacts.generation.sha256
    assert manifest["semantic_model_sha256"] == SHA_D


def test_attempt_rejects_condition_or_model_identity_mismatch(tmp_path: Path) -> None:
    workspace, store = _workspace(tmp_path)
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
                "metadata_sha256": SHA_A,
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
    probe = DirectProbeResult(
        condition="C1",
        attempt_id="run-1:public-1:C1:1",
        maximum_turns=12,
        question_sha256=QUESTION_SHA256,
        generation_outcome="refused",
        failure_class="agent_refusal",
        trace=trace,
        receipt=_receipt(
            store,
            attempt_id="run-1:public-1:C1:1",
            condition="C1",
            trace=trace,
            result=None,
            sql=None,
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
    )
    spec = DirectAttemptSpec(
        condition="C2",
        scope="dev-a",
        instance_id="public-1",
        question=QUESTION,
        run_id="run-1",
        repetition=1,
        controllable_seed=None,
        provider="fixture-provider",
        model="fixture-model",
        model_version=None,
        git_commit=COMMIT,
        harness_config_sha256=SHA_A,
        prompt_sha256=SHA_B,
        instructions_sha256=SHA_C,
        semantic_model_ref="public-hkb:fixture-v1",
        semantic_model_sha256=SHA_D,
        model_config_id="direct-sql-v1",
        budget_id="standard-120s-v1",
        software_versions={"omni-benchmark": "0.1.0"},
        cli_versions={"direct-harness": "0.1.0"},
    )

    with pytest.raises(ValueError, match="condition"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=probe,
        )

    aligned_spec = replace(
        spec,
        condition="C1",
        semantic_model_ref="raw-schema:fixture-v1",
        semantic_model_sha256=None,
    )
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
    assert generation["telemetry_unavailable"] == ["model_version", "retry_count"]

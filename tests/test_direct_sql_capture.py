from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import omni_benchmark.direct_sql_capture as direct_capture
from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.direct_sql_capture import (
    DirectCaptureError,
    DirectDatabaseAttestation,
    DirectModelTurn,
    DirectReferenceResult,
    DirectSqlCapture,
)
from tests.execution_fixtures import SyntheticConnection


class SequenceModel:
    def __init__(self, actions: list[Mapping[str, Any]]) -> None:
        self._actions = iter(actions)
        self.observed_tools: list[tuple[str, ...]] = []
        self.observed_messages: list[tuple[Mapping[str, Any], ...]] = []

    def next_turn(
        self,
        messages: tuple[Mapping[str, Any], ...],
        tool_specs: tuple[Mapping[str, Any], ...],
    ) -> DirectModelTurn:
        self.observed_messages.append(messages)
        self.observed_tools.append(tuple(tool["name"] for tool in tool_specs))
        return DirectModelTurn(
            action=next(self._actions),
            input_tokens=10,
            output_tokens=2,
            retry_count=0,
            cost_usd=0.001,
        )


class UnmeteredModel(SequenceModel):
    def next_turn(
        self,
        messages: tuple[Mapping[str, Any], ...],
        tool_specs: tuple[Mapping[str, Any], ...],
    ) -> DirectModelTurn:
        self.observed_messages.append(messages)
        self.observed_tools.append(tuple(tool["name"] for tool in tool_specs))
        return DirectModelTurn(action=next(self._actions))


class SyntheticDatabase:
    execution_attestation = DirectDatabaseAttestation(
        role_is_read_only=True,
        no_execute_on_non_system_functions=True,
    )

    def __init__(self, responses: Mapping[str, object]) -> None:
        self.responses = responses
        self.events: list[tuple[Any, ...]] = []

    def connect(self) -> SyntheticConnection:
        self.events.append(("connect",))
        return SyntheticConnection(self.responses, self.events)


class CloseFailingDatabase(SyntheticDatabase):
    def connect(self) -> SyntheticConnection:
        connection = super().connect()

        def fail_close() -> None:
            raise RuntimeError("synthetic close failure")

        connection.close = fail_close  # type: ignore[method-assign]
        return connection


class UnattestedDatabase:
    def connect(self) -> SyntheticConnection:
        raise AssertionError("an unattested database must never be connected")


def _store(tmp_path: Path, name: str = "direct") -> tuple[Path, ArtifactStore]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return workspace, ArtifactStore(workspace, Path("runs") / name)


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("C1", {"inspect_schema", "execute_sql"}),
        ("C2", {"inspect_schema", "search_hkb", "execute_sql"}),
        ("C3", {"inspect_schema", "search_semantic_model", "execute_sql"}),
    ],
)
def test_conditions_expose_only_the_preregistered_tool_capabilities(
    tmp_path: Path,
    condition: str,
    expected: set[str],
) -> None:
    _, store = _store(tmp_path, condition.lower())
    model = SequenceModel([{"type": "refuse", "reason": "cannot_answer_safely"}])

    result = DirectSqlCapture(
        condition=condition,
        model_transport=model,
        database=SyntheticDatabase({}),
        inspect_schema=lambda: DirectReferenceResult({"tables": ["values_table"]}),
        search_hkb=(
            (lambda query: DirectReferenceResult({"matches": [query]}))
            if condition == "C2"
            else None
        ),
        search_semantic_model=(
            (
                lambda query: DirectReferenceResult(
                    {"matches": [query]}, semantic_objects=("values.value",)
                )
            )
            if condition == "C3"
            else None
        ),
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(10)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert set(model.observed_tools[0]) == expected
    assert result.generation_outcome == "refused"
    assert result.failure_class == "agent_refusal"


def test_capture_runs_a_harness_owned_tool_loop_with_measured_telemetry(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    model = SequenceModel(
        [
            {"type": "tool", "name": "inspect_schema", "arguments": {}},
            {
                "type": "tool",
                "name": "search_hkb",
                "arguments": {"query": "public metric"},
            },
            {
                "type": "tool",
                "name": "execute_sql",
                "arguments": {"sql": "SELECT 42"},
            },
            {"type": "answer", "sql": "SELECT 42"},
        ]
    )
    database = SyntheticDatabase({"SELECT 42": [(42,)]})

    result = DirectSqlCapture(
        condition="C2",
        model_transport=model,
        database=database,
        inspect_schema=lambda: DirectReferenceResult({"tables": ["values_table"]}),
        search_hkb=lambda query: DirectReferenceResult(
            {"matches": [{"id": "hkb-1", "text": query}]}
        ),
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(40)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C2:1")

    assert result.generation_outcome == "answered"
    assert result.generated_sql == "SELECT 42"
    assert result.tool_call_count == 3
    assert result.tool_calls_by_name == (
        ("execute_sql", 1),
        ("inspect_schema", 1),
        ("search_hkb", 1),
    )
    assert result.database_query_count == 2
    assert result.validation_attempt_count == 0
    assert result.retry_count == 0
    assert result.token_usage == {
        "input_tokens": 40,
        "output_tokens": 8,
        "total_tokens": 48,
    }
    assert result.cost_usd == pytest.approx(0.004)
    assert result.result_artifact is not None
    assert json.loads(result.result_artifact.path.read_text()) == {
        "columns": ["column_1"],
        "rows": [[42]],
        "schema_version": 1,
        "truncated": False,
    }
    executed = [event[1] for event in database.events if event[0] == "execute"]
    assert executed.count("SELECT 42") == 2
    assert executed.count("SET TRANSACTION READ ONLY;") == 2
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert sum(event["tool_call_delta"] for event in trace) == 3
    assert sum(event["database_query_delta"] for event in trace) == 2
    assert sum(event["validation_attempt_delta"] for event in trace) == 0
    assert trace[-1]["status"] == "COMPLETE"


def test_capture_rejects_an_unavailable_condition_tool_without_dispatch(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    model = SequenceModel(
        [
            {
                "type": "tool",
                "name": "search_hkb",
                "arguments": {"query": "must not dispatch"},
            }
        ]
    )
    database = SyntheticDatabase({})

    result = DirectSqlCapture(
        condition="C1",
        model_transport=model,
        database=database,
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(10)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert result.failure_class == "unauthorized_tool"
    assert result.tool_call_count == 0
    assert database.events == []


def test_disallowed_final_sql_never_reaches_the_database(tmp_path: Path) -> None:
    _, store = _store(tmp_path)
    model = SequenceModel(
        [{"type": "answer", "sql": "UPDATE values_table SET value = 0"}]
    )
    database = SyntheticDatabase({})

    result = DirectSqlCapture(
        condition="C1",
        model_transport=model,
        database=database,
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(10)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert result.failure_class == "sql_not_admitted"
    assert database.events == []


def test_no_result_preserves_safely_generated_sql_for_diagnosis(tmp_path: Path) -> None:
    _, store = _store(tmp_path)

    result = DirectSqlCapture(
        condition="C1",
        model_transport=SequenceModel([{"type": "answer", "sql": "SELECT nothing"}]),
        database=SyntheticDatabase({"SELECT nothing": None}),
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(20)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert result.failure_class == "candidate_no_result"
    assert result.generated_sql == "SELECT nothing"


def test_unknown_database_progress_is_null_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store = _store(tmp_path)

    def fail_after_dispatch(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic unknown-progress failure")

    monkeypatch.setattr(direct_capture, "execute_query_sequence", fail_after_dispatch)
    result = DirectSqlCapture(
        condition="C1",
        model_transport=SequenceModel([{"type": "answer", "sql": "SELECT 42"}]),
        database=SyntheticDatabase({}),
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(20)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert result.database_query_count is None
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert all(event["database_query_delta"] is None for event in trace)


def test_rejected_sql_tool_is_observable_and_the_model_may_recover(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    model = SequenceModel(
        [
            {
                "type": "tool",
                "name": "execute_sql",
                "arguments": {"sql": "DELETE FROM values_table"},
            },
            {"type": "answer", "sql": "SELECT 42"},
        ]
    )
    database = SyntheticDatabase({"SELECT 42": [(42,)]})

    result = DirectSqlCapture(
        condition="C1",
        model_transport=model,
        database=database,
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(20)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "answered"
    assert result.tool_call_count == 1
    assert result.database_query_count == 1
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    tool_event = next(event for event in trace if event["tool_call_delta"] == 1)
    assert tool_event["status"] == "ERROR"
    assert tool_event["failure_class"] == "sql_not_admitted"


def test_connection_close_failure_is_not_silently_swallowed(tmp_path: Path) -> None:
    _, store = _store(tmp_path)

    result = DirectSqlCapture(
        condition="C1",
        model_transport=SequenceModel([{"type": "answer", "sql": "SELECT 42"}]),
        database=CloseFailingDatabase({"SELECT 42": [(42,)]}),
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(20)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert result.failure_class == "database_infrastructure_error"
    assert result.result_artifact is None


def test_forbidden_nested_database_value_cannot_enter_result_artifact(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)

    result = DirectSqlCapture(
        condition="C1",
        model_transport=SequenceModel([{"type": "answer", "sql": "SELECT payload"}]),
        database=SyntheticDatabase(
            {"SELECT payload": [({"external_knowledge": ["hidden-marker"]},)]}
        ),
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(20)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert result.failure_class == "forbidden_result_payload"
    assert result.result_artifact is None
    assert "hidden-marker" not in result.trace.path.read_text()


def test_forbidden_reference_payload_fails_closed_without_persisting_values(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    model = SequenceModel([{"type": "tool", "name": "inspect_schema", "arguments": {}}])

    result = DirectSqlCapture(
        condition="C1",
        model_transport=model,
        database=SyntheticDatabase({}),
        inspect_schema=lambda: DirectReferenceResult(
            {"external_knowledge": ["hidden-marker"]}
        ),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(10)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert result.failure_class == "forbidden_tool_payload"
    persisted = result.trace.path.read_text()
    assert "external_knowledge" not in persisted
    assert "hidden-marker" not in persisted


def test_forbidden_model_action_is_rejected_before_any_tool_dispatch(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    model = SequenceModel(
        [
            {
                "type": "tool",
                "name": "execute_sql",
                "arguments": {"sql": "SELECT 42"},
                "externalKnowledge": ["hidden-marker"],
            }
        ]
    )
    database = SyntheticDatabase({"SELECT 42": [(42,)]})

    result = DirectSqlCapture(
        condition="C1",
        model_transport=model,
        database=database,
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(10)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert result.tool_call_count == 0
    assert database.events == []
    persisted = result.trace.path.read_text()
    assert "externalKnowledge" not in persisted
    assert "hidden-marker" not in persisted


def test_live_secret_in_tool_argument_is_rejected_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNI_API_TOKEN", "live-secret-value")
    _, store = _store(tmp_path)
    calls: list[str] = []

    result = DirectSqlCapture(
        condition="C2",
        model_transport=SequenceModel(
            [
                {
                    "type": "tool",
                    "name": "search_hkb",
                    "arguments": {"query": "live-secret-value"},
                }
            ]
        ),
        database=SyntheticDatabase({}),
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=lambda query: (
            calls.append(query) or DirectReferenceResult({"matches": []})
        ),
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(10)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C2:1")

    assert result.generation_outcome == "errored"
    assert calls == []
    assert "live-secret-value" not in result.trace.path.read_text()


def test_live_secret_in_reference_payload_is_not_sent_back_to_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNI_API_TOKEN", "live-secret-value")
    _, store = _store(tmp_path)
    model = SequenceModel(
        [
            {"type": "tool", "name": "inspect_schema", "arguments": {}},
            {"type": "refuse", "reason": "cannot_answer_safely"},
        ]
    )

    result = DirectSqlCapture(
        condition="C1",
        model_transport=model,
        database=SyntheticDatabase({}),
        inspect_schema=lambda: DirectReferenceResult(
            {"innocuous_field": "live-secret-value"}
        ),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(15)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.generation_outcome == "errored"
    assert len(model.observed_messages) == 1
    assert "live-secret-value" not in result.trace.path.read_text()


def test_unobservable_provider_usage_remains_null_throughout_complete_trace(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)

    result = DirectSqlCapture(
        condition="C1",
        model_transport=UnmeteredModel(
            [{"type": "refuse", "reason": "insufficient_information"}]
        ),
        database=SyntheticDatabase({}),
        inspect_schema=lambda: DirectReferenceResult({"tables": []}),
        search_hkb=None,
        search_semantic_model=None,
        store=store,
        provider="fixture-provider",
        model="fixture-model",
        clock=iter(index / 10 for index in range(10)).__next__,
        utc_now=lambda: "2026-08-28T04:00:00Z",
    ).capture("Public synthetic question", attempt_id="run:public:C1:1")

    assert result.token_usage is None
    assert result.token_source == "unavailable"
    assert result.retry_count is None
    assert result.cost_usd is None
    assert result.cost_source == "unavailable"
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert all(event["input_tokens"] is None for event in trace)
    assert all(event["output_tokens"] is None for event in trace)
    assert all(event["retry_delta"] is None for event in trace)


def test_constructor_requires_exact_condition_backends(tmp_path: Path) -> None:
    _, store = _store(tmp_path)

    with pytest.raises(DirectCaptureError, match="C2 requires HKB"):
        DirectSqlCapture(
            condition="C2",
            model_transport=SequenceModel([]),
            database=SyntheticDatabase({}),
            inspect_schema=lambda: DirectReferenceResult({"tables": []}),
            search_hkb=None,
            search_semantic_model=None,
            store=store,
            provider="fixture-provider",
            model="fixture-model",
        )


def test_constructor_rejects_database_without_complete_side_effect_attestation(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    model = SequenceModel(
        [{"type": "answer", "sql": "SELECT dblink_exec('foreign', 'DELETE')"}]
    )

    with pytest.raises(DirectCaptureError, match="database execution attestation"):
        DirectSqlCapture(
            condition="C1",
            model_transport=model,
            database=UnattestedDatabase(),
            inspect_schema=lambda: DirectReferenceResult({"tables": []}),
            search_hkb=None,
            search_semantic_model=None,
            store=store,
            provider="fixture-provider",
            model="fixture-model",
        )

    assert model.observed_messages == []


def test_constructor_rejects_attestation_with_function_execute_privileges(
    tmp_path: Path,
) -> None:
    _, store = _store(tmp_path)
    database = SyntheticDatabase({})
    database.execution_attestation = DirectDatabaseAttestation(
        role_is_read_only=True,
        no_execute_on_non_system_functions=False,
    )

    with pytest.raises(DirectCaptureError, match="database execution attestation"):
        DirectSqlCapture(
            condition="C1",
            model_transport=SequenceModel([]),
            database=database,
            inspect_schema=lambda: DirectReferenceResult({"tables": []}),
            search_hkb=None,
            search_semantic_model=None,
            store=store,
            provider="fixture-provider",
            model="fixture-model",
        )


@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")])
def test_model_turn_rejects_nonfinite_reported_cost(constant: float) -> None:
    with pytest.raises(DirectCaptureError, match="cost_usd"):
        direct_capture._validate_turn(
            DirectModelTurn(
                action={"type": "answer", "sql": "SELECT 1"}, cost_usd=constant
            )
        )


def test_cost_aggregation_rejects_finite_inputs_that_overflow() -> None:
    turns = [
        DirectModelTurn(action={}, cost_usd=1e308),
        DirectModelTurn(action={}, cost_usd=1e308),
    ]

    with pytest.raises(DirectCaptureError, match="aggregate"):
        direct_capture._cost(turns)

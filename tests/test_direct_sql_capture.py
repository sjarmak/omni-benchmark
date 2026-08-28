from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import omni_benchmark.direct_sql_capture as direct_capture
from omni_benchmark.direct_model_observability import (
    DirectModelObservationError,
    cost as model_cost,
)
from omni_benchmark.direct_sql_capture import (
    DirectCaptureError,
    DirectDatabaseAttestation,
    DirectModelTurn,
    DirectReferenceResult,
    DirectSqlCapture,
)
from omni_benchmark.direct_capture_contract import (
    DirectModelFailure,
    DirectModelUsage,
)
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    SyntheticDatabase,
    UnmeteredModel,
    capture_with_test_time,
    database_identity,
    prepared_attempt,
    runtime_binding,
    store,
)
from tests.execution_fixtures import SyntheticConnection


def _run(
    tmp_path: Path,
    actions: list[dict[str, Any]],
    *,
    condition: str = "C1",
    responses: dict[str, object] | None = None,
    tools: BoundPublicTools | None = None,
    hkb_payload: Any | None = None,
    model_class: type[SequenceModel] = SequenceModel,
    database_class: type[SyntheticDatabase] = SyntheticDatabase,
    name: str = "direct",
    clock_steps: int = 80,
) -> tuple[Any, SequenceModel, SyntheticDatabase]:
    binding = runtime_binding(condition)
    model = model_class(binding, actions)
    database = database_class(binding, responses or {})
    _, artifact_store = store(tmp_path, name)
    prepared = prepared_attempt(
        binding,
        model=model,
        database=database,
        public_tools=tools or BoundPublicTools(binding, hkb_payload=hkb_payload),
        artifact_store=artifact_store,
    )
    return (
        capture_with_test_time(prepared, clock_steps=clock_steps),
        model,
        database,
    )


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ("C1", {"inspect_schema", "execute_sql"}),
        ("C2", {"inspect_schema", "search_hkb", "execute_sql"}),
        ("C3", {"inspect_schema", "search_semantic_model", "execute_sql"}),
    ],
)
def test_conditions_expose_only_preregistered_capabilities(
    tmp_path: Path, condition: str, expected: set[str]
) -> None:
    result, model, _ = _run(
        tmp_path,
        [{"type": "refuse", "reason": "cannot_answer_safely"}],
        condition=condition,
        name=condition.lower(),
    )

    assert set(model.observed_tools[0]) == expected
    assert result.generation_outcome == "refused"
    assert result.failure_class == "agent_refusal"
    assert result.failure_origin == "evaluated_system"


def test_harness_owned_loop_captures_full_telemetry_and_typed_result(
    tmp_path: Path,
) -> None:
    actions = [
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

    result, _, database = _run(
        tmp_path,
        actions,
        condition="C2",
        responses={"SELECT 42": [(42,)]},
        hkb_payload={
            "matches": [],
            "retrieved_hkb_stable_ids": ["public:hkb:metric"],
        },
    )

    assert result.generation_outcome == "answered"
    assert result.generated_sql == "SELECT 42"
    assert result.tool_calls_by_name == (
        ("execute_sql", 1),
        ("inspect_schema", 1),
        ("search_hkb", 1),
    )
    assert result.tool_call_count == 3
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
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert sum(event["tool_call_delta"] for event in trace) == 3
    assert sum(event["database_query_delta"] for event in trace) == 2
    assert trace[-1]["status"] == "COMPLETE"
    evidence = json.loads(result.action_evidence.path.read_text())
    assert evidence["runtime_binding_sha256"] == result.binding.sha256()
    assert evidence["trace_sha256"] == result.trace.sha256
    assert evidence["records"] == [
        {
            "exploratory_sql": None,
            "retrieval_query": "public metric",
            "retrieved_public_ids": ["public:hkb:metric"],
            "tool_name": "search_hkb",
            "trace_seq": 3,
        },
        {
            "exploratory_sql": "SELECT 42",
            "retrieval_query": None,
            "retrieved_public_ids": [],
            "tool_name": "execute_sql",
            "trace_seq": 5,
        },
    ]


def test_c3_action_evidence_retains_semantic_object_ids(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [
            {
                "type": "tool",
                "name": "search_semantic_model",
                "arguments": {"query": "public value"},
            },
            {"type": "refuse", "reason": "cannot_answer_safely"},
        ],
        condition="C3",
    )

    evidence = json.loads(result.action_evidence.path.read_text())
    assert evidence["records"][0]["retrieval_query"] == "public value"
    assert evidence["records"][0]["retrieved_public_ids"] == ["values.value"]


def test_unavailable_condition_tool_never_dispatches(tmp_path: Path) -> None:
    result, _, database = _run(
        tmp_path,
        [
            {
                "type": "tool",
                "name": "search_hkb",
                "arguments": {"query": "must not dispatch"},
            }
        ],
    )

    assert result.failure_class == "unauthorized_tool"
    assert result.tool_call_count == 0
    assert database.events == []


def test_disallowed_final_sql_never_reaches_database(tmp_path: Path) -> None:
    result, _, database = _run(
        tmp_path,
        [{"type": "answer", "sql": "UPDATE values_table SET value = 0"}],
    )

    assert result.failure_class == "sql_not_admitted"
    assert result.generated_sql is None
    assert database.events == []


def test_multiple_final_sql_statements_never_reach_database(tmp_path: Path) -> None:
    result, _, database = _run(
        tmp_path,
        [{"type": "answer", "sql": "SELECT 1; SELECT 2"}],
    )

    assert result.failure_class == "sql_not_admitted"
    assert result.generated_sql is None
    assert result.database_query_count == 0
    assert database.events == []


def test_no_result_preserves_safely_generated_sql(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [{"type": "answer", "sql": "SELECT nothing"}],
        responses={"SELECT nothing": None},
    )

    assert result.failure_class == "candidate_no_result"
    assert result.generated_sql == "SELECT nothing"


def test_unknown_database_progress_is_null_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_after_dispatch(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic unknown-progress failure")

    monkeypatch.setattr(direct_capture, "execute_query_sequence", fail_after_dispatch)
    result, _, _ = _run(
        tmp_path,
        [{"type": "answer", "sql": "SELECT 42"}],
        responses={"SELECT 42": [(42,)]},
    )

    assert result.database_query_count is None
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert [event["database_query_delta"] for event in trace] == [0, None]


@pytest.mark.parametrize(
    "rows",
    [[(object(),)], [(float("nan"),)], [(1,), (1, 2)]],
    ids=["unsupported", "nonfinite", "ragged"],
)
def test_post_query_adaptation_failure_is_evaluated_contract_error(
    tmp_path: Path, rows: list[tuple[object, ...]]
) -> None:
    sql = "SELECT malformed_result"
    result, _, database = _run(
        tmp_path, [{"type": "answer", "sql": sql}], responses={sql: rows}
    )

    assert result.failure_class == "result_contract_error"
    assert result.generated_sql == sql
    assert result.database_query_count == 1
    assert result.result_artifact is None
    assert ("connection_close",) in database.events
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    execution = next(
        event for event in trace if event["event_type"] == "direct_final_sql_execution"
    )
    assert execution["failure_class"] == "result_contract_error"
    assert execution["database_query_delta"] == 1


def test_rejected_sql_tool_is_observable_and_model_may_recover(
    tmp_path: Path,
) -> None:
    result, _, _ = _run(
        tmp_path,
        [
            {
                "type": "tool",
                "name": "execute_sql",
                "arguments": {"sql": "DELETE FROM values_table"},
            },
            {"type": "answer", "sql": "SELECT 42"},
        ],
        responses={"SELECT 42": [(42,)]},
    )

    assert result.generation_outcome == "answered"
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    rejected = next(event for event in trace if event["tool_call_delta"] == 1)
    assert rejected["failure_class"] == "sql_not_admitted"
    assert rejected["database_query_delta"] == 0


class CloseFailingDatabase(SyntheticDatabase):
    def connect(self) -> SyntheticConnection:
        connection = super().connect()

        def fail_close() -> None:
            raise RuntimeError("synthetic close failure")

        connection.close = fail_close  # type: ignore[method-assign]
        return connection


def test_connection_close_failure_is_not_swallowed(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [{"type": "answer", "sql": "SELECT 42"}],
        responses={"SELECT 42": [(42,)]},
        database_class=CloseFailingDatabase,
    )

    assert result.failure_class == "database_infrastructure_error"
    assert result.result_artifact is None


class ConnectFailingDatabase(SyntheticDatabase):
    def connect(self) -> SyntheticConnection:
        self.events.append(("connect",))
        raise RuntimeError("synthetic database outage")


class IdentityChangingDatabase(SyntheticDatabase):
    def connect(self) -> SyntheticConnection:
        connection = super().connect()
        self.runtime_identity = database_identity(selected_database="other_database")
        return connection


class PostQueryIdentityChangingDatabase(SyntheticDatabase):
    close_fails = False

    def connect(self) -> SyntheticConnection:
        self.events.append(("connect",))
        connection = SyntheticConnection(self.responses, self.events)
        original_cursor = connection.cursor

        def identity_changing_cursor() -> Any:
            cursor = original_cursor()
            original_execute = cursor.execute

            def execute_then_drift(sql: str) -> None:
                original_execute(sql)
                if sql == "SELECT 42":
                    self.runtime_identity = database_identity(
                        selected_database="other_database"
                    )

            cursor.execute = execute_then_drift
            return cursor

        connection.cursor = identity_changing_cursor  # type: ignore[method-assign]
        if self.close_fails:

            def fail_close() -> None:
                raise RuntimeError("synthetic close failure")

            connection.close = fail_close  # type: ignore[method-assign]
        return connection


class PostQueryIdentityChangingCloseFailingDatabase(PostQueryIdentityChangingDatabase):
    close_fails = True


@pytest.mark.parametrize(
    ("database_class", "expected_failure"),
    [
        (PostQueryIdentityChangingDatabase, "database_identity_mismatch"),
        (
            PostQueryIdentityChangingCloseFailingDatabase,
            "database_infrastructure_error",
        ),
    ],
)
def test_post_query_identity_drift_preserves_query_count_and_primary_failure(
    tmp_path: Path,
    database_class: type[SyntheticDatabase],
    expected_failure: str,
) -> None:
    result, _, database = _run(
        tmp_path,
        [{"type": "answer", "sql": "SELECT 42"}],
        responses={"SELECT 42": [(42,)]},
        database_class=database_class,
        name=f"post-query-{expected_failure}",
    )

    assert ("execute", "SELECT 42") in database.events
    assert result.generation_outcome == "errored"
    assert result.failure_class == expected_failure
    assert result.database_query_count == 1
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    execution = next(
        event for event in trace if event["event_type"] == "direct_final_sql_execution"
    )
    assert execution["failure_class"] == expected_failure
    assert execution["database_query_delta"] == 1


@pytest.mark.parametrize(
    ("database_class", "expected_failure"),
    [
        (ConnectFailingDatabase, "database_infrastructure_error"),
        (IdentityChangingDatabase, "database_identity_mismatch"),
    ],
)
def test_database_boundary_failure_during_tool_use_terminates_attempt(
    tmp_path: Path,
    database_class: type[SyntheticDatabase],
    expected_failure: str,
) -> None:
    result, model, database = _run(
        tmp_path,
        [
            {
                "type": "tool",
                "name": "execute_sql",
                "arguments": {"sql": "SELECT 42"},
            },
            {"type": "refuse", "reason": "cannot_answer_safely"},
        ],
        responses={"SELECT 42": [(42,)]},
        database_class=database_class,
        name=expected_failure,
    )

    assert result.generation_outcome == "errored"
    assert result.failure_class == expected_failure
    assert result.failure_origin == "benchmark_infrastructure"
    assert result.database_query_count == 0
    assert len(model.observed_messages) == 1
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert trace[-1]["event_type"] == "direct_tool_dispatch"
    assert trace[-1]["failure_class"] == expected_failure
    assert trace[-1]["database_query_delta"] == 0
    assert not any(event[0] == "execute" for event in database.events)


def test_capture_constructor_rejects_caller_controlled_clocks(tmp_path: Path) -> None:
    binding = runtime_binding()
    _, artifact_store = store(tmp_path, "caller-clock")
    prepared = prepared_attempt(
        binding,
        model=SequenceModel(
            binding, [{"type": "refuse", "reason": "cannot_answer_safely"}]
        ),
        database=SyntheticDatabase(binding, {}),
        public_tools=BoundPublicTools(binding),
        artifact_store=artifact_store,
    )

    with pytest.raises(TypeError):
        DirectSqlCapture(
            prepared=prepared,
            clock=lambda: 0.0,
            utc_now=lambda: "2000-01-01T00:00:00Z",
        )


def test_forbidden_nested_database_value_cannot_enter_result(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [{"type": "answer", "sql": "SELECT payload"}],
        responses={"SELECT payload": [({"external_knowledge": ["hidden"]},)]},
    )

    assert result.failure_class == "forbidden_result_payload"
    assert "hidden" not in result.trace.path.read_text()


def test_forbidden_reference_payload_is_not_persisted(tmp_path: Path) -> None:
    binding = runtime_binding()
    tools = BoundPublicTools(binding)
    tools.inspect_schema = lambda: DirectReferenceResult(  # type: ignore[method-assign]
        payload={"external_knowledge": ["hidden-marker"]},
        context_sha256=binding.context.context_sha256,
        capability="inspect_schema",
    )
    result, _, _ = _run(
        tmp_path,
        [{"type": "tool", "name": "inspect_schema", "arguments": {}}],
        tools=tools,
    )

    assert result.failure_class == "forbidden_tool_payload"
    assert "hidden-marker" not in result.trace.path.read_text()


def test_forbidden_model_action_is_rejected_before_dispatch(tmp_path: Path) -> None:
    result, _, database = _run(
        tmp_path,
        [
            {
                "type": "tool",
                "name": "execute_sql",
                "arguments": {"sql": "SELECT 42"},
                "externalKnowledge": ["hidden-marker"],
            }
        ],
        responses={"SELECT 42": [(42,)]},
    )

    assert result.failure_class == "model_transport_error"
    assert database.events == []
    assert "hidden-marker" not in result.trace.path.read_text()


def test_live_secret_in_tool_argument_is_rejected_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNI_API_TOKEN", "live-secret-value")
    result, _, database = _run(
        tmp_path,
        [
            {
                "type": "tool",
                "name": "search_hkb",
                "arguments": {"query": "live-secret-value"},
            }
        ],
        condition="C2",
    )

    assert result.generation_outcome == "errored"
    assert database.events == []
    assert "live-secret-value" not in result.trace.path.read_text()


def test_live_secret_in_reference_payload_is_not_returned_to_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNI_API_TOKEN", "live-secret-value")
    binding = runtime_binding()
    tools = BoundPublicTools(binding)
    tools.inspect_schema = lambda: DirectReferenceResult(  # type: ignore[method-assign]
        payload={"innocuous_field": "live-secret-value"},
        context_sha256=binding.context.context_sha256,
        capability="inspect_schema",
    )
    result, model, _ = _run(
        tmp_path,
        [
            {"type": "tool", "name": "inspect_schema", "arguments": {}},
            {"type": "refuse", "reason": "cannot_answer_safely"},
        ],
        tools=tools,
    )

    assert result.generation_outcome == "errored"
    assert len(model.observed_messages) == 1
    assert "live-secret-value" not in result.trace.path.read_text()


def test_unobservable_usage_remains_null_through_trace(tmp_path: Path) -> None:
    result, _, _ = _run(
        tmp_path,
        [{"type": "refuse", "reason": "insufficient_information"}],
        model_class=UnmeteredModel,
    )

    assert result.token_usage is None
    assert result.retry_count is None
    assert result.cost_usd is None
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert [event["input_tokens"] for event in trace] == [None, 0]
    assert [event["output_tokens"] for event in trace] == [None, 0]
    assert [event["retry_delta"] for event in trace] == [None, 0]


class PartiallyMeteredFailureModel(SequenceModel):
    def next_turn(self, messages: Any, tool_specs: Any) -> DirectModelTurn:
        if not self.observed_messages:
            return super().next_turn(messages, tool_specs)
        self.observed_messages.append(messages)
        self.observed_tools.append(tuple(tool["name"] for tool in tool_specs))
        raise DirectModelFailure("infrastructure", "unmetered provider failure")


def test_partial_observability_preserves_raw_per_turn_telemetry(
    tmp_path: Path,
) -> None:
    result, _, _ = _run(
        tmp_path,
        [{"type": "tool", "name": "inspect_schema", "arguments": {}}],
        model_class=PartiallyMeteredFailureModel,
        name="partial-observability",
    )

    assert result.token_usage is None
    assert result.retry_count is None
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert trace[0]["input_tokens"] == 10
    assert trace[0]["output_tokens"] == 2
    assert trace[0]["retry_delta"] == 0
    assert trace[-1]["input_tokens"] is None
    assert trace[-1]["output_tokens"] is None
    assert trace[-1]["retry_delta"] is None


def test_constructor_requires_exact_condition_tools(tmp_path: Path) -> None:
    binding = runtime_binding("C2")
    tools = BoundPublicTools(binding)
    tools.search_hkb = None  # type: ignore[method-assign]
    _, artifact_store = store(tmp_path)

    with pytest.raises((DirectCaptureError, ValueError), match="C2 requires HKB"):
        prepared_attempt(
            binding,
            model=SequenceModel(binding, []),
            database=SyntheticDatabase(binding, {}),
            public_tools=tools,
            artifact_store=artifact_store,
        )


class UnattestedDatabase(SyntheticDatabase):
    execution_attestation = DirectDatabaseAttestation(
        role_is_read_only=True,
        no_execute_on_non_system_functions=False,
    )


def test_constructor_rejects_incomplete_database_attestation(tmp_path: Path) -> None:
    binding = runtime_binding()
    model = SequenceModel(binding, [])
    database = UnattestedDatabase(binding, {})
    _, artifact_store = store(tmp_path)

    with pytest.raises((DirectCaptureError, ValueError), match="database identity"):
        prepared_attempt(
            binding,
            model=model,
            database=database,
            public_tools=BoundPublicTools(binding),
            artifact_store=artifact_store,
        )
    assert model.observed_messages == []


class RateLimitedModel(SequenceModel):
    def next_turn(self, messages: Any, tool_specs: Any) -> DirectModelTurn:
        self.observed_messages.append(messages)
        self.observed_tools.append(tuple(tool["name"] for tool in tool_specs))
        raise DirectModelFailure(
            "rate_limit",
            "provider rate limit",
            partial_usage=DirectModelUsage(input_tokens=123, output_tokens=7),
            retry_count=2,
            terminal_cost_usd=0.42,
        )


def test_provider_failure_preserves_category_and_observable_telemetry(
    tmp_path: Path,
) -> None:
    result, _, database = _run(
        tmp_path,
        [],
        model_class=RateLimitedModel,
        name="provider-failure",
    )

    assert result.generation_outcome == "errored"
    assert result.failure_class == "model_rate_limit_error"
    assert result.token_usage == {
        "input_tokens": 123,
        "output_tokens": 7,
        "total_tokens": 130,
    }
    assert result.retry_count == 2
    assert result.cost_usd == pytest.approx(0.42)
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert trace == [
        {
            **trace[0],
            "event_type": "direct_model_turn",
            "failure_class": "model_rate_limit_error",
            "input_tokens": 123,
            "output_tokens": 7,
            "retry_delta": 2,
            "status": "ERROR",
        }
    ]
    assert database.events == []


@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")])
def test_model_turn_rejects_nonfinite_reported_cost(constant: float) -> None:
    binding = runtime_binding()
    with pytest.raises(DirectCaptureError, match="cost_usd"):
        direct_capture._validate_turn(
            DirectModelTurn(
                action={"type": "answer", "sql": "SELECT 1"},
                model_identity=binding.model,
                cost_usd=constant,
            ),
            binding.model,
        )


def test_cost_aggregation_rejects_finite_inputs_that_overflow() -> None:
    binding = runtime_binding()
    turns = [
        DirectModelTurn(action={}, model_identity=binding.model, cost_usd=1e308),
        DirectModelTurn(action={}, model_identity=binding.model, cost_usd=1e308),
    ]

    with pytest.raises(DirectModelObservationError, match="aggregate"):
        model_cost(turns)

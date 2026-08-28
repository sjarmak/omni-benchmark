from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.direct_capture_receipt import (
    DirectCaptureReceiptError,
    capture_summary_from_probe,
    validate_capture_receipt_payload,
)
from omni_benchmark.direct_prepared_attempt import DirectPreparedAttempt
from omni_benchmark.direct_sql_capture import (
    DirectCaptureError,
    DirectModelTurn,
    DirectReferenceResult,
    DirectSqlCapture,
)
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    SyntheticDatabase,
    budget_identity,
    capture_with_test_time,
    database_identity,
    model_identity,
    prepared_attempt,
    runtime_binding,
    store,
)


def _capture(
    tmp_path: Path,
    *,
    binding: Any | None = None,
    model: Any | None = None,
    database: Any | None = None,
    public_tools: Any | None = None,
) -> tuple[Any, Any, Any]:
    selected = binding or runtime_binding()
    selected_model = model or SequenceModel(
        selected, [{"type": "refuse", "reason": "insufficient_information"}]
    )
    selected_database = database or SyntheticDatabase(selected, {})
    _, artifact_store = store(tmp_path)
    prepared = prepared_attempt(
        selected,
        model=selected_model,
        database=selected_database,
        public_tools=public_tools or BoundPublicTools(selected),
        artifact_store=artifact_store,
    )
    result = capture_with_test_time(prepared, clock_steps=20)
    return result, selected_model, selected_database


def test_capture_has_no_free_question_or_attempt_label_surface(tmp_path: Path) -> None:
    binding = runtime_binding(question="Exact committed public question")
    result, model, _ = _capture(tmp_path, binding=binding)

    assert model.observed_messages[0] == (
        {"role": "user", "content": "Exact committed public question"},
    )
    assert result.binding == binding
    assert result.attempt_id == binding.attempt_id
    capture = DirectSqlCapture
    with pytest.raises(TypeError):
        capture.capture(object(), "substituted", attempt_id="forged")
    with pytest.raises(TypeError):
        DirectSqlCapture(
            binding=binding,
            model_transport=model,
            database=SyntheticDatabase(binding, {}),
            public_tools=BoundPublicTools(binding),
            store=object(),
        )


def test_prepared_attempt_has_no_public_constructor() -> None:
    with pytest.raises(TypeError):
        DirectPreparedAttempt()


def test_tampered_prepared_dependency_is_rejected_before_work(tmp_path: Path) -> None:
    binding = runtime_binding("C2")
    model = SequenceModel(
        binding, [{"type": "tool", "name": "search_hkb", "arguments": {"query": "x"}}]
    )
    database = SyntheticDatabase(binding, {})
    _, artifact_store = store(tmp_path)
    authorized = prepared_attempt(
        binding,
        model=model,
        database=database,
        public_tools=BoundPublicTools(binding),
        artifact_store=artifact_store,
    )
    forged_tools = BoundPublicTools(binding, hkb_payload={"matches": [{"gold": 1}]})
    object.__setattr__(authorized, "public_tools", forged_tools)

    with pytest.raises(DirectCaptureError, match="not authorized"):
        DirectSqlCapture(prepared=authorized)

    assert model.observed_messages == []
    assert database.events == []


@pytest.mark.parametrize("surface", ["model", "budget", "database", "context"])
def test_constructor_rejects_cross_binding_substitution_before_work(
    tmp_path: Path, surface: str
) -> None:
    binding = runtime_binding()
    model = SequenceModel(binding, [{"type": "answer", "sql": "SELECT should_not_run"}])
    database = SyntheticDatabase(binding, {"SELECT should_not_run": [(1,)]})
    tools = BoundPublicTools(binding)
    if surface == "model":
        model.runtime_identity = model_identity(model="other-model")
    elif surface == "budget":
        model.budget_identity = budget_identity(maximum_turns=2)
    elif surface == "database":
        database.runtime_identity = database_identity(
            selected_database="other_database"
        )
    else:
        tools.identity = replace(binding.context, context_sha256="f" * 64)
    _, artifact_store = store(tmp_path)

    with pytest.raises((DirectCaptureError, ValueError), match=surface):
        prepared_attempt(
            binding,
            model=model,
            database=database,
            public_tools=tools,
            artifact_store=artifact_store,
        )

    assert model.observed_messages == []
    assert database.events == []


def test_rendered_question_substitution_is_rejected_before_model_or_database(
    tmp_path: Path,
) -> None:
    binding = runtime_binding()
    model = SequenceModel(binding, [{"type": "answer", "sql": "SELECT 1"}])
    database = SyntheticDatabase(binding, {"SELECT 1": [(1,)]})
    tools = BoundPublicTools(binding)
    tools.render_question = lambda question: f"{question}\nSELECT oracle"  # type: ignore[method-assign]
    _, artifact_store = store(tmp_path)
    capture = DirectSqlCapture(
        prepared=prepared_attempt(
            binding,
            model=model,
            database=database,
            public_tools=tools,
            artifact_store=artifact_store,
        ),
    )

    with pytest.raises(DirectCaptureError, match="question"):
        capture.capture()

    assert model.observed_messages == []
    assert database.events == []


def test_reference_result_must_bind_capability_and_context(tmp_path: Path) -> None:
    binding = runtime_binding()
    model = SequenceModel(
        binding,
        [
            {
                "type": "tool",
                "name": "inspect_schema",
                "arguments": {"query": "public schema"},
            }
        ],
    )
    tools = BoundPublicTools(binding)
    tools.inspect_schema = lambda query: DirectReferenceResult(  # type: ignore[method-assign]
        payload={"tables": []},
        context_sha256="f" * 64,
        capability="search_hkb",
    )

    result, _, database = _capture(
        tmp_path, binding=binding, model=model, public_tools=tools
    )

    assert result.failure_class == "reference_binding_error"
    assert database.events == []


def test_public_context_identity_is_rechecked_after_callback(tmp_path: Path) -> None:
    binding = runtime_binding()
    model = SequenceModel(
        binding,
        [
            {
                "type": "tool",
                "name": "inspect_schema",
                "arguments": {"query": "public schema"},
            }
        ],
    )
    tools = BoundPublicTools(binding)
    prepared_holder: dict[str, DirectPreparedAttempt] = {}

    def mutate_context(query: str) -> DirectReferenceResult:
        object.__setattr__(
            prepared_holder["value"].public_tools,
            "identity",
            replace(binding.context, context_sha256="f" * 64),
        )
        return DirectReferenceResult(
            payload={"tables": []},
            context_sha256=binding.context.context_sha256,
            capability="inspect_schema",
        )

    tools.inspect_schema = mutate_context  # type: ignore[method-assign]
    workspace, artifact_store = store(tmp_path)
    database = SyntheticDatabase(binding, {})
    prepared = prepared_attempt(
        binding,
        model=model,
        database=database,
        public_tools=tools,
        artifact_store=artifact_store,
    )
    prepared_holder["value"] = prepared

    result = DirectSqlCapture(prepared=prepared).capture()

    assert result.failure_class == "reference_binding_error"
    assert database.events == []


class FlippingModel(SequenceModel):
    def __init__(self, binding: Any) -> None:
        self._identity_reads = 0
        self._expected_identity = binding.model
        self._other_identity = model_identity(model="other-model")
        super().__init__(binding, [{"type": "answer", "sql": "SELECT should_not_run"}])

    @property
    def runtime_identity(self) -> Any:
        self._identity_reads += 1
        return (
            self._expected_identity
            if self._identity_reads == 1
            else self._other_identity
        )

    @runtime_identity.setter
    def runtime_identity(self, value: Any) -> None:
        self._expected_identity = value


def test_mutated_transport_identity_is_rechecked_before_model_work(
    tmp_path: Path,
) -> None:
    binding = runtime_binding()
    model = FlippingModel(binding)
    database = SyntheticDatabase(binding, {})
    _, artifact_store = store(tmp_path)
    with pytest.raises((DirectCaptureError, ValueError), match="model or budget"):
        DirectSqlCapture(
            prepared=prepared_attempt(
                binding,
                model=model,
                database=database,
                public_tools=BoundPublicTools(binding),
                artifact_store=artifact_store,
            ),
        )

    assert model.observed_messages == []
    assert database.events == []


def test_positive_model_turn_provenance_mismatch_never_reaches_database(
    tmp_path: Path,
) -> None:
    binding = runtime_binding()
    model = SequenceModel(
        binding,
        [{"type": "answer", "sql": "SELECT should_not_run"}],
        turn_model_identity=model_identity(model="other-model"),
    )

    result, _, database = _capture(tmp_path, binding=binding, model=model)

    assert result.failure_class == "model_identity_mismatch"
    assert database.events == []


class MutatingDatabase(SyntheticDatabase):
    def connect(self) -> Any:
        connection = super().connect()
        self.runtime_identity = database_identity(selected_database="other_database")
        return connection


class SubstitutingConnectDatabase(SyntheticDatabase):
    def connect(self) -> Any:
        connection = super().connect()
        self.connect = lambda: connection  # type: ignore[method-assign]
        return connection


def test_database_identity_is_rechecked_after_connect_before_query(
    tmp_path: Path,
) -> None:
    binding = runtime_binding()
    database = MutatingDatabase(binding, {"SELECT should_not_run": [(1,)]})
    model = SequenceModel(binding, [{"type": "answer", "sql": "SELECT should_not_run"}])

    result, _, _ = _capture(tmp_path, binding=binding, model=model, database=database)

    assert result.failure_class == "database_identity_mismatch"
    assert not any(event[0] == "execute" for event in database.events)
    assert ("connection_close",) in database.events


def test_failed_post_connect_authority_check_closes_connection(tmp_path: Path) -> None:
    binding = runtime_binding()
    database = SubstitutingConnectDatabase(binding, {"SELECT should_not_run": [(1,)]})
    model = SequenceModel(binding, [{"type": "answer", "sql": "SELECT should_not_run"}])

    result, _, _ = _capture(tmp_path, binding=binding, model=model, database=database)

    assert result.failure_class == "database_infrastructure_error"
    assert not any(event[0] == "execute" for event in database.events)
    assert ("connection_close",) in database.events


def test_receipt_v4_binds_full_runtime_identity_artifacts_and_summary(
    tmp_path: Path,
) -> None:
    binding = runtime_binding()
    result, _, _ = _capture(tmp_path, binding=binding)
    receipt = json.loads(result.receipt.path.read_text())

    assert receipt["schema_version"] == 4
    assert receipt["runtime_binding"] == binding.as_dict()
    assert receipt["runtime_binding_sha256"] == binding.sha256()
    assert receipt["attempt_id"] == binding.attempt_id
    assert receipt["action_evidence_sha256"] == result.action_evidence.sha256
    assert receipt["action_evidence_path"].endswith("attempt.action-evidence.json")
    assert receipt["capture_summary"] == capture_summary_from_probe(result)
    artifact_store = ArtifactStore(result.receipt.path.parents[2], Path("runs/direct"))
    validate_capture_receipt_payload(
        receipt,
        binding=binding,
        store=artifact_store,
        sql=result.generated_sql,
        trace=result.trace,
        action_evidence=result.action_evidence,
        result=result.result_artifact,
        capture_summary=capture_summary_from_probe(result),
    )


def test_receipt_validator_rejects_cross_binding_substitution(tmp_path: Path) -> None:
    binding = runtime_binding(run_id="first")
    result, _, _ = _capture(tmp_path, binding=binding)
    receipt = json.loads(result.receipt.path.read_text())
    other = runtime_binding(run_id="second")
    artifact_store = ArtifactStore(result.receipt.path.parents[2], Path("runs/direct"))

    with pytest.raises(DirectCaptureReceiptError, match="runtime binding"):
        validate_capture_receipt_payload(
            receipt,
            binding=other,
            store=artifact_store,
            sql=result.generated_sql,
            trace=result.trace,
            action_evidence=result.action_evidence,
            result=result.result_artifact,
            capture_summary=capture_summary_from_probe(result),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"generation_outcome": "errored"},
        {"failure_class": "turn_limit_exhausted"},
        {"failure_origin": "benchmark_infrastructure"},
        {"semantic_objects": ("forged.metric",)},
        {"tool_calls_by_name": (("inspect_schema", 1),), "tool_call_count": 1},
        {"retry_count": 7},
        {"validation_attempt_count": 1},
    ],
)
def test_receipt_validator_rejects_capture_summary_substitution(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    binding = runtime_binding()
    result, _, _ = _capture(tmp_path, binding=binding)
    receipt = json.loads(result.receipt.path.read_text())
    artifact_store = ArtifactStore(result.receipt.path.parents[2], Path("runs/direct"))

    with pytest.raises(DirectCaptureReceiptError, match="capture summary"):
        validate_capture_receipt_payload(
            receipt,
            binding=binding,
            store=artifact_store,
            sql=result.generated_sql,
            trace=result.trace,
            action_evidence=result.action_evidence,
            result=result.result_artifact,
            capture_summary=capture_summary_from_probe(replace(result, **changes)),
        )


def test_model_turn_contract_requires_realized_model_identity() -> None:
    with pytest.raises(TypeError):
        DirectModelTurn(action={"type": "answer", "sql": "SELECT 1"})

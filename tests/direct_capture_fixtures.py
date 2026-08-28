from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import patch

import omni_benchmark.direct_prepared_attempt as prepared_module
import omni_benchmark.direct_sql_capture as capture_module
from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.direct_public_context import (
    DirectPublicTools as CommittedDirectPublicTools,
)
from omni_benchmark.direct_runtime_binding import (
    DirectBudgetIdentity,
    DirectContextIdentity,
    DirectDatabaseIdentity,
    DirectModelIdentity,
    DirectQuestionIdentity,
    DirectRuntimeBinding,
)
from omni_benchmark.direct_prepared_attempt import (
    DirectPreparedAttempt,
    prepare_committed_direct_attempt,
)
from omni_benchmark.direct_sql_capture import (
    DirectDatabaseAttestation,
    DirectModelTurn,
    DirectProbeResult,
    DirectReferenceResult,
    DirectSqlCapture,
)
from tests.execution_fixtures import SyntheticConnection

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
QUESTION = "Public synthetic question"


def model_identity(*, model: str = "fixture-model") -> DirectModelIdentity:
    return DirectModelIdentity.from_dict(
        {
            "adapter": "fixture-adapter",
            "adapter_version": "1.0.0",
            "executable_sha256": SHA_A,
            "executable_version": "1.0.0",
            "model": model,
            "provider": "fixture-provider",
            "system_prompt_sha256": SHA_B,
            "transport_config_sha256": SHA_C,
        },
        environment={},
    )


def budget_identity(*, maximum_turns: int = 12) -> DirectBudgetIdentity:
    return DirectBudgetIdentity.from_dict(
        {
            "budget_id": "fixture-budget",
            "maximum_turns": maximum_turns,
            "per_turn_max_cost_usd": 5.0,
            "per_turn_timeout_seconds": 120.0,
        },
        environment={},
    )


def database_identity(
    *, selected_database: str = "archeology_scan_large"
) -> DirectDatabaseIdentity:
    return DirectDatabaseIdentity.from_dict(
        {
            "backend": "postgresql",
            "connection_target_sha256": SHA_A,
            "content_sha256": SHA_B,
            "database_record_sha256": SHA_C,
            "deployment_identity_sha256": SHA_D,
            "inventory_sha256": SHA_E,
            "physical_database": "neondb",
            "postgres_server_version_num": 180000,
            "runtime_role": "omni_benchmark_reader",
            "schema_sha256": SHA_F,
            "selected_database": selected_database,
        },
        environment={},
    )


def runtime_binding(
    condition: str = "C1",
    *,
    question: str = QUESTION,
    instance_id: str = "public",
    model: DirectModelIdentity | None = None,
    budget: DirectBudgetIdentity | None = None,
    database: DirectDatabaseIdentity | None = None,
    run_id: str = "run",
    system_commit: str = "1" * 40,
) -> DirectRuntimeBinding:
    selected_database = database or database_identity()
    question_identity = DirectQuestionIdentity.from_dict(
        {
            "instance_id": instance_id,
            "public_manifest_path": "data/manifests/eligible_questions.jsonl",
            "public_manifest_sha256": SHA_A,
            "public_record_sha256": SHA_B,
            "question": question,
            "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            "scope": "dev-a",
            "scope_ids_path": "data/manifests/dev_a_ids.txt",
            "scope_ids_sha256": SHA_C,
            "selected_database": selected_database.selected_database,
        },
        environment={},
    )
    components = {
        "instructions": SHA_C,
        "prompt": SHA_B,
        "public_context": SHA_D,
    }
    if condition == "C2":
        components["hkb"] = SHA_E
    if condition == "C3":
        components["semantic_manifest"] = SHA_E
    context = DirectContextIdentity.from_components(
        condition=condition,
        selected_database=selected_database.selected_database,
        component_sha256=components,
        environment={},
    )
    return DirectRuntimeBinding.from_parts(
        system_commit=system_commit,
        run_id=run_id,
        repetition=1,
        condition=condition,
        question=question_identity,
        context=context,
        database=selected_database,
        model=model or model_identity(),
        budget=budget or budget_identity(),
        environment={},
    )


class SequenceModel:
    def __init__(
        self,
        binding: DirectRuntimeBinding,
        actions: list[Mapping[str, Any]],
        *,
        turn_model_identity: DirectModelIdentity | None = None,
    ) -> None:
        self.execution_authority = "synthetic-model-state"
        self.runtime_identity = binding.model
        self.budget_identity = binding.budget
        self._turn_model_identity = turn_model_identity or binding.model
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
            model_identity=self._turn_model_identity,
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
        return DirectModelTurn(
            action=next(self._actions), model_identity=self._turn_model_identity
        )


class SyntheticDatabase:
    execution_attestation = DirectDatabaseAttestation(
        role_is_read_only=True,
        no_execute_on_non_system_functions=True,
    )

    def __init__(
        self, binding: DirectRuntimeBinding, responses: Mapping[str, object]
    ) -> None:
        self.execution_authority = "synthetic-database-state"
        self.runtime_identity = binding.database
        self.responses = responses
        self.events: list[tuple[Any, ...]] = []

    def connect(self) -> SyntheticConnection:
        self.events.append(("connect",))
        return SyntheticConnection(self.responses, self.events)


class BoundPublicTools:
    def __init__(
        self,
        binding: DirectRuntimeBinding,
        *,
        schema_payload: Any | None = None,
        hkb_payload: Any | None = None,
        semantic_payload: Any | None = None,
    ) -> None:
        self.identity = binding.context
        self._schema_payload = (
            {"retrieved_schema_stable_ids": [], "tables": []}
            if schema_payload is None
            else schema_payload
        )
        self._hkb_payload = {"matches": []} if hkb_payload is None else hkb_payload
        self._semantic_payload = (
            {"matches": []} if semantic_payload is None else semantic_payload
        )
        if binding.condition == "C1":
            self.search_hkb = None  # type: ignore[method-assign]
            self.search_semantic_model = None  # type: ignore[method-assign]
        elif binding.condition == "C2":
            self.search_semantic_model = None  # type: ignore[method-assign]
        else:
            self.search_hkb = None  # type: ignore[method-assign]

    def inspect_schema(self, query: str) -> DirectReferenceResult:
        return self._result("inspect_schema", {**self._schema_payload, "query": query})

    def search_hkb(self, query: str) -> DirectReferenceResult:
        return self._result("search_hkb", {**self._hkb_payload, "query": query})

    def search_semantic_model(self, query: str) -> DirectReferenceResult:
        return self._result(
            "search_semantic_model",
            {**self._semantic_payload, "query": query},
            semantic_objects=("values.value",),
        )

    def _result(
        self,
        capability: str,
        payload: Any,
        *,
        semantic_objects: tuple[str, ...] = (),
    ) -> DirectReferenceResult:
        return DirectReferenceResult(
            payload=payload,
            context_sha256=self.identity.context_sha256,
            capability=capability,
            semantic_objects=semantic_objects,
        )

    def render_question(self, question: str) -> str:
        return question


def capture_with_test_time(
    prepared: DirectPreparedAttempt,
    *,
    clock_steps: int = 80,
    started_at: str = "2026-08-28T04:00:00Z",
) -> DirectProbeResult:
    """Capture with explicit test-only time patching outside production APIs."""
    clock = iter(index / 10 for index in range(clock_steps)).__next__
    with (
        patch.object(capture_module, "_monotonic", clock),
        patch.object(capture_module, "_utc_now", lambda: started_at),
    ):
        return DirectSqlCapture(prepared=prepared).capture()


def prepared_attempt(
    binding: DirectRuntimeBinding,
    *,
    model: Any,
    database: Any,
    public_tools: Any,
    artifact_store: ArtifactStore,
) -> DirectPreparedAttempt:
    """Exercise committed preflight with test-only patched external adapters."""
    committed_tools = CommittedDirectPublicTools(
        identity=public_tools.identity,
        inspect_schema=public_tools.inspect_schema,
        search_hkb=public_tools.search_hkb,
        search_semantic_model=public_tools.search_semantic_model,
        render_question=public_tools.render_question,
    )
    workspace = artifact_store._workspace
    with (
        patch.object(prepared_module, "verify_system_commit", return_value=None),
        patch.object(prepared_module, "_verify_runtime_package", return_value=None),
        patch.object(
            prepared_module,
            "load_committed_direct_question",
            return_value=binding.question,
        ),
        patch.object(
            prepared_module,
            "load_direct_public_tools",
            return_value=committed_tools,
        ),
        patch.object(
            prepared_module,
            "load_committed_direct_database_identity",
            return_value=binding.database,
        ),
        patch.object(
            prepared_module,
            "ClaudeDirectTransport",
            side_effect=lambda config: model,
        ),
        patch.object(
            prepared_module,
            "AttestedDirectPostgresTransport",
            side_effect=lambda environment, expected_identity: database,
        ),
    ):
        prepared = prepare_committed_direct_attempt(
            workspace=workspace,
            commit=binding.system_commit,
            scope="dev-a",
            instance_id=binding.question.instance_id,
            condition=binding.condition,
            run_id=binding.run_id,
            repetition=binding.repetition,
            claude_config=object(),
            database_environment={},
            store=artifact_store,
            environment={},
        )
    for surface in ("model", "budget", "database", "context"):
        if getattr(prepared.binding, surface) != getattr(binding, surface):
            raise ValueError(f"{surface} does not match the requested test binding")
    return prepared


def store(tmp_path: Path, name: str = "direct") -> tuple[Path, ArtifactStore]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return workspace, ArtifactStore(workspace, Path("runs") / name)

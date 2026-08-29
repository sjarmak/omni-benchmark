from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.direct_runtime_binding import (
    DirectBudgetIdentity,
    DirectContextIdentity,
    DirectDatabaseIdentity,
    DirectModelIdentity,
    DirectQuestionIdentity,
    DirectRuntimeIdentityError,
)
from omni_benchmark.sealed_direct_adapter import (
    SealedDirectAdapterError,
    SealedDirectConditionAdapter,
    SealedDirectRuntimeBinding,
    SealedDirectSqlCapture,
    build_sealed_direct_generation_record,
    prepare_sealed_direct_capture,
)
from omni_benchmark.sealed_generation_staging import (
    SealedAttemptRepository,
    prepare_sealed_attempt,
)
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    SyntheticDatabase,
)
from tests.test_sealed_dispatch import _policy
from tests.test_sealed_generation_staging import _plan, _workspace


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _prepared(*, condition: str = "C1"):  # type: ignore[no-untyped-def]
    plan, freeze = _plan()
    attempts = tuple(
        replace(item, database="db_1") if item.instance_id == "q-001" else item
        for item in plan.attempts
    )
    plan = replace(plan, attempts=attempts)
    return prepare_sealed_attempt(
        plan=plan,
        freeze_b=freeze,
        attempt_id=f"sealed:q-001:{condition}:1",
        question="Public synthetic question 1?",
    )


def _identities(prepared):  # type: ignore[no-untyped-def]
    components = {
        "condition_config": prepared.condition_binding.harness_config_sha256,
        "instructions": prepared.condition_binding.instructions_sha256,
        "prompt": prepared.condition_binding.prompt_sha256,
        "public_context": SHA_E,
        "schema": SHA_F,
    }
    if prepared.condition == "C2":
        components["hkb"] = prepared.condition_binding.semantic_model_sha256
    if prepared.condition == "C3":
        components["semantic_manifest"] = (
            prepared.condition_binding.semantic_model_sha256
        )
    context = DirectContextIdentity.from_components(
        condition=prepared.condition,
        selected_database=prepared.database,
        component_sha256=components,
        environment={},
    )
    database = DirectDatabaseIdentity.from_dict(
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
            "selected_database": prepared.database,
        },
        environment={},
    )
    model = DirectModelIdentity.from_dict(
        {
            "adapter": "frozen-final-v1",
            "adapter_version": "1.0.0",
            "executable_sha256": SHA_A,
            "executable_version": "1.0.0",
            "model": prepared.condition_binding.model,
            "provider": prepared.condition_binding.provider,
            "system_prompt_sha256": prepared.condition_binding.prompt_sha256,
            "transport_config_sha256": SHA_C,
        },
        environment={},
    )
    budget = DirectBudgetIdentity.from_dict(
        {
            "budget_id": prepared.condition_binding.budget_id,
            "maximum_turns": 12,
            "per_turn_max_cost_usd": 5.0,
            "per_turn_timeout_seconds": 120.0,
        },
        environment={},
    )
    return context, database, model, budget


def _authority(
    workspace: Path,
    prepared,
    actions,  # type: ignore[no-untyped-def]
    responses=None,  # type: ignore[no-untyped-def]
    connect_failure: bool = False,
    store: ArtifactStore | None = None,
):
    context, database_identity, model_identity, budget_identity = _identities(prepared)
    binding = SealedDirectRuntimeBinding.from_prepared(
        prepared=prepared,
        context=context,
        database=database_identity,
        model=model_identity,
        budget=budget_identity,
        environment={},
    )
    model = SequenceModel(binding, actions)
    database_type = ConnectFailingDatabase if connect_failure else SyntheticDatabase
    database = database_type(
        binding,
        {"SELECT 42": [(42,)]} if responses is None else responses,
    )
    tools = BoundPublicTools(binding)
    if store is None:
        store = ArtifactStore(
            workspace,
            Path(
                f"runs/sealed-final-v1/captures/{prepared.database}/"
                f"{prepared.condition.lower()}/{prepared.instance_id}"
            ),
            require_new_root=True,
        )
    authority = prepare_sealed_direct_capture(
        prepared=prepared,
        binding=binding,
        model_transport=model,
        database=database,
        public_tools=tools,
        store=store,
    )
    return authority, store


class ConnectFailingDatabase(SyntheticDatabase):
    def connect(self):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic database outage")


def _capture_record(tmp_path: Path, *, condition: str, actions):  # type: ignore[no-untyped-def]
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition=condition)
    authority, store = _authority(workspace, prepared, actions)
    probe = SealedDirectSqlCapture(prepared=authority).capture()
    record = build_sealed_direct_generation_record(
        workspace=workspace,
        prepared=prepared,
        authority=authority,
        probe=probe,
    )
    return workspace, prepared, store, probe, record


def test_sealed_direct_capture_stages_exact_unscored_test_record(
    tmp_path: Path,
) -> None:
    workspace, prepared, _store, probe, record = _capture_record(
        tmp_path,
        condition="C1",
        actions=[{"type": "answer", "sql": "SELECT 42"}],
    )

    staged = SealedAttemptRepository(
        workspace, Path("runs/sealed-final-v1/attempts")
    ).stage(prepared, record)
    persisted = json.loads(staged.generation_record_bytes)

    assert probe.binding.question.scope == "test"
    assert persisted["attempt_id"] == prepared.attempt_id
    assert persisted["condition"] == "C1"
    assert persisted["instance_id"] == prepared.instance_id
    assert persisted["partition"] == "test"
    assert persisted["question"] == prepared.question
    assert persisted["run_id"] == prepared.cohort_id
    assert persisted["generated_sql"] == "SELECT 42"
    assert "correctness" not in persisted
    assert "gold_sql" not in persisted


def test_sealed_direct_condition_adapter_is_dispatch_compatible(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C2")

    @contextmanager
    def factory(value, store):  # type: ignore[no-untyped-def]
        yield _authority(
            workspace,
            value,
            [{"type": "answer", "sql": "SELECT 42"}],
            store=store,
        )[0]

    adapter = SealedDirectConditionAdapter(
        workspace=workspace,
        capture_root=Path("runs/sealed-final-v1/captures"),
        condition_binding=prepared.condition_binding,
        policy=_policy(),
        capture_factory=factory,
    )

    result = adapter.execute(prepared)

    assert adapter.condition_binding == prepared.condition_binding
    assert result.generation_record["partition"] == "test"
    assert result.generation_record["generated_sql"] == "SELECT 42"
    assert (
        len(list((workspace / "runs/sealed-final-v1/captures").rglob("*.json*"))) == 4
    )


@pytest.mark.parametrize("condition", ["C1", "C2", "C3"])
def test_sealed_direct_binding_covers_each_direct_condition(
    tmp_path: Path, condition: str
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition=condition)
    authority, _store = _authority(
        workspace,
        prepared,
        [{"type": "refuse", "reason": "insufficient_information"}],
    )

    probe = SealedDirectSqlCapture(prepared=authority).capture()
    record = build_sealed_direct_generation_record(
        workspace=workspace,
        prepared=prepared,
        authority=authority,
        probe=probe,
    )

    assert authority.binding.condition == condition
    assert authority.binding.sealed_authority["plan_sha256"] == prepared.plan_sha256
    assert record["generation_outcome"] == "refused"
    assert record["terminal_failure_class"] == "agent_refusal"


def test_sealed_direct_preserves_evaluated_system_failure(tmp_path: Path) -> None:
    _workspace_path, _prepared_value, _store, _probe, record = _capture_record(
        tmp_path,
        condition="C1",
        actions=[{"type": "not-a-tool"}],
    )

    assert record["generation_outcome"] == "errored"
    assert record["failure_origin"] == "evaluated_system"
    assert record["terminal_failure_class"] == "invalid_model_action"


def test_sealed_direct_quarantines_infrastructure_failure(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C1")
    authority, _store = _authority(
        workspace,
        prepared,
        [{"type": "answer", "sql": "SELECT 42"}],
        connect_failure=True,
    )
    probe = SealedDirectSqlCapture(prepared=authority).capture()

    with pytest.raises(SealedDirectAdapterError, match="infrastructure"):
        build_sealed_direct_generation_record(
            workspace=workspace,
            prepared=prepared,
            authority=authority,
            probe=probe,
        )

    assert not list(workspace.rglob("attempt.json"))


def test_sealed_direct_rejects_capture_receipt_mutation(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C1")
    authority, _store = _authority(
        workspace,
        prepared,
        [{"type": "refuse", "reason": "cannot_answer_safely"}],
    )
    probe = SealedDirectSqlCapture(prepared=authority).capture()
    probe.receipt.path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SealedDirectAdapterError, match="artifacts"):
        build_sealed_direct_generation_record(
            workspace=workspace,
            prepared=prepared,
            authority=authority,
            probe=probe,
        )


def test_sealed_direct_rejects_tampering_and_keeps_dev_loader_closed(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C1")
    authority, _store = _authority(
        workspace,
        prepared,
        [{"type": "refuse", "reason": "cannot_answer_safely"}],
    )
    authority.model_transport.runtime_identity = DirectModelIdentity.from_dict(
        {**authority.binding.model.as_dict(), "model": "substituted-model"},
        environment={},
    )

    with pytest.raises(Exception, match="model|authorized|binding"):
        SealedDirectSqlCapture(prepared=authority).capture()

    with pytest.raises(DirectRuntimeIdentityError, match="train, dev-a, or dev-b"):
        DirectQuestionIdentity.from_dict(
            {
                "instance_id": prepared.instance_id,
                "public_manifest_path": "data/manifests/eligible_questions.jsonl",
                "public_manifest_sha256": SHA_A,
                "public_record_sha256": SHA_B,
                "question": prepared.question,
                "question_sha256": hashlib.sha256(
                    prepared.question.encode()
                ).hexdigest(),
                "scope": "test",
                "scope_ids_path": "data/manifests/test_ids.txt",
                "scope_ids_sha256": SHA_C,
                "selected_database": prepared.database,
            },
            environment={},
        )


def test_sealed_direct_adapter_rejects_invalid_construction_and_condition(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    c1 = _prepared(condition="C1")
    c2 = _prepared(condition="C2")
    _plan_value, freeze = _plan()

    with pytest.raises(SealedDirectAdapterError, match="identity"):
        SealedDirectConditionAdapter(
            workspace=workspace,
            capture_root=Path("runs/sealed-final-v1/captures"),
            condition_binding=freeze.condition("C4"),
            policy=_policy(),
            capture_factory=lambda _prepared, _store: None,  # type: ignore[arg-type,return-value]
        )
    with pytest.raises(SealedDirectAdapterError, match="policy"):
        SealedDirectConditionAdapter(
            workspace=workspace,
            capture_root=Path("runs/sealed-final-v1/captures"),
            condition_binding=c1.condition_binding,
            policy=None,  # type: ignore[arg-type]
            capture_factory=lambda _prepared, _store: None,  # type: ignore[arg-type,return-value]
        )
    with pytest.raises(SealedDirectAdapterError, match="factory"):
        SealedDirectConditionAdapter(
            workspace=workspace,
            capture_root=Path("runs/sealed-final-v1/captures"),
            condition_binding=c1.condition_binding,
            policy=_policy(),
            capture_factory=None,  # type: ignore[arg-type]
        )
    with pytest.raises(SealedDirectAdapterError, match="root"):
        SealedDirectConditionAdapter(
            workspace=workspace,
            capture_root=Path("../escape"),
            condition_binding=c1.condition_binding,
            policy=_policy(),
            capture_factory=lambda _prepared, _store: None,  # type: ignore[arg-type,return-value]
        )

    adapter = SealedDirectConditionAdapter(
        workspace=workspace,
        capture_root=Path("runs/sealed-final-v1/captures"),
        condition_binding=c1.condition_binding,
        policy=_policy(),
        capture_factory=lambda _prepared, _store: None,  # type: ignore[arg-type,return-value]
    )
    with pytest.raises(SealedDirectAdapterError, match="condition"):
        adapter.execute(c2)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: {**value, "schema_version": 2}, "scalars"),
        (lambda value: {**value, "condition": "C4"}, "scalars"),
        (
            lambda value: {
                **value,
                "question": {**value["question"], "scope": "dev-a"},
            },
            "scope",
        ),
        (
            lambda value: {
                **value,
                "sealed_authority": {
                    **value["sealed_authority"],
                    "control_commit": "short",
                },
            },
            "full commit",
        ),
    ],
)
def test_sealed_direct_runtime_parser_rejects_substitution(
    tmp_path: Path,
    mutation,
    message: str,  # type: ignore[no-untyped-def]
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C1")
    authority, _store = _authority(
        workspace,
        prepared,
        [{"type": "refuse", "reason": "cannot_answer_safely"}],
    )

    with pytest.raises(SealedDirectAdapterError, match=message):
        SealedDirectRuntimeBinding.from_dict(mutation(authority.binding.as_dict()))

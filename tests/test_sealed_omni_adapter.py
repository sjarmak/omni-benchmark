from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.omni_capture import OmniProbeResult
from omni_benchmark.sealed_generation_staging import (
    SealedAttemptRepository,
    prepare_sealed_attempt,
)
from omni_benchmark.sealed_omni_adapter import (
    SealedOmniAdapterError,
    SealedOmniConditionAdapter,
)
from tests.test_sealed_dispatch import _policy
from tests.test_sealed_generation_staging import _plan, _workspace


def _prepared(condition: str = "C4"):  # type: ignore[no-untyped-def]
    plan, freeze = _plan()
    return (
        plan,
        freeze,
        prepare_sealed_attempt(
            plan=plan,
            freeze_b=freeze,
            attempt_id=f"sealed:q-001:{condition}:1",
            question="Public synthetic question 1?",
        ),
    )


def _probe(
    store: ArtifactStore,
    *,
    failure_class: str | None = None,
    job_result_observed: bool | None = None,
) -> OmniProbeResult:
    trace = store.write_jsonl(
        Path("attempt.trace.jsonl"),
        [
            {
                "component": "benchmark-adapter",
                "database_query_delta": 1 if failure_class is None else None,
                "duration_ms": 10.0,
                "elapsed_ms": 10.0,
                "event_type": "synthetic_omni_capture",
                "failure_class": failure_class,
                "input_tokens": None,
                "metadata_sha256": "a" * 64,
                "model": None,
                "output_tokens": None,
                "provider": None,
                "retry_delta": None,
                "schema_version": "trace-event-v2",
                "seq": 0,
                "status": "ok" if failure_class is None else "error",
                "timestamp": "2026-08-29T07:00:00Z",
                "tool_call_delta": None,
                "tool_name": None,
                "validation_attempt_delta": None,
            }
        ],
    )
    shape = store.write_json(
        Path("response-shape.json"), {"responses": [], "schema_version": 1}
    )
    result = (
        store.write_json(
            Path("answer.result.json"),
            {
                "columns": ["answer"],
                "rows": [[42]],
                "schema_version": 1,
                "truncated": False,
            },
        )
        if failure_class is None
        else None
    )
    return OmniProbeResult(
        job_id="synthetic-job",
        terminal_state=(
            "COMPLETE"
            if failure_class is None
            else "CONTRACT_ERROR"
            if failure_class == "response_contract_error"
            else "ERROR"
        ),
        failure_class=failure_class,
        job_result_observed=(
            failure_class is None
            if job_result_observed is None
            else job_result_observed
        ),
        trace=trace,
        response_shape=shape,
        result_artifact=result,
        generated_query="{fields:[answers.value]}" if failure_class is None else None,
        semantic_objects=("answers",) if failure_class is None else (),
        model_name=None,
        model_provider=None,
        token_usage=None,
        tool_calls_by_name=(),
        tool_call_count=None,
        database_query_count=1 if failure_class is None else None,
        validation_attempt_count=None,
        started_at="2026-08-29T07:00:00Z",
        finished_at="2026-08-29T07:00:01Z",
        latency_ms=1_000.0,
        observer_retry_count=0,
        observer_retry_wait_ms=0.0,
    )


def _adapter(
    workspace: Path,
    freeze,
    runner,  # type: ignore[no-untyped-def]
) -> SealedOmniConditionAdapter:
    return SealedOmniConditionAdapter(
        workspace=workspace,
        capture_root=Path("runs/sealed-final-v1/captures"),
        condition_binding=freeze.condition("C4"),
        policy=_policy(),
        probe_runner=runner,
    )


def test_c4_adapter_projects_success_to_exact_unscored_test_record(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, prepared = _prepared()
    adapter = _adapter(workspace, freeze, lambda _prepared, store: _probe(store))

    result = adapter.execute(prepared)
    repository = SealedAttemptRepository(
        workspace, Path("runs/sealed-final-v1/attempts")
    )
    staged = repository.stage(prepared, result.generation_record)
    record = json.loads(staged.generation_record_bytes)

    assert adapter.condition_binding == freeze.condition("C4")
    assert record["attempt_id"] == prepared.attempt_id
    assert record["condition"] == "C4"
    assert record["instance_id"] == prepared.instance_id
    assert record["partition"] == "test"
    assert record["question"] == prepared.question
    assert record["run_id"] == prepared.cohort_id
    assert record["generated_sql"] is None
    assert record["generated_query"] == "{fields:[answers.value]}"
    assert "correctness" not in record
    capture_files = list((workspace / "runs/sealed-final-v1/captures").rglob("*.json*"))
    assert len(capture_files) == 3
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in capture_files)
    assert all(path.parent.stat().st_mode & 0o777 == 0o700 for path in capture_files)
    assert plan.sha256 == prepared.plan_sha256


def test_c4_adapter_preserves_evaluated_system_terminal_failure(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _, freeze, prepared = _prepared()
    adapter = _adapter(
        workspace,
        freeze,
        lambda _prepared, store: _probe(
            store, failure_class="omni_job_terminal_failure"
        ),
    )

    result = adapter.execute(prepared)
    record = dict(result.generation_record)

    assert record["generation_outcome"] == "errored"
    assert record["failure_origin"] == "evaluated_system"
    assert record["terminal_failure_class"] == "omni_job_terminal_failure"
    assert record.get("generated_query") is None


def test_c4_adapter_leaves_infrastructure_failure_unstaged(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _, freeze, prepared = _prepared()
    adapter = _adapter(
        workspace,
        freeze,
        lambda _prepared, store: _probe(store, failure_class="adapter_transport_error"),
    )

    with pytest.raises(SealedOmniAdapterError, match="infrastructure"):
        adapter.execute(prepared)

    assert not list((workspace / "runs/sealed-final-v1").rglob("attempt.json"))


def test_c4_adapter_preserves_completed_job_without_parseable_query(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _, freeze, prepared = _prepared()
    adapter = _adapter(
        workspace,
        freeze,
        lambda _prepared, store: _probe(
            store,
            failure_class="response_contract_error",
            job_result_observed=True,
        ),
    )

    result = adapter.execute(prepared)
    record = dict(result.generation_record)

    assert record["generation_outcome"] == "errored"
    assert record["failure_origin"] == "evaluated_system"
    assert record["harness_failure"] is None
    assert record["terminal_failure_class"] == "response_contract_error"
    assert record.get("generated_query") is None


def test_c4_adapter_keeps_pre_result_contract_error_unstaged(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _, freeze, prepared = _prepared()
    adapter = _adapter(
        workspace,
        freeze,
        lambda _prepared, store: _probe(
            store,
            failure_class="response_contract_error",
            job_result_observed=False,
        ),
    )

    with pytest.raises(SealedOmniAdapterError, match="infrastructure"):
        adapter.execute(prepared)


def test_c4_adapter_rejects_wrong_condition_before_capture(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    _, freeze, prepared = _prepared("C1")
    calls: list[str] = []
    adapter = _adapter(
        workspace,
        freeze,
        lambda _prepared, store: calls.append("called") or _probe(store),
    )

    with pytest.raises(SealedOmniAdapterError, match="C4"):
        adapter.execute(prepared)

    assert calls == []
    assert not (workspace / "runs").exists()


def test_c4_adapter_rejects_non_c4_identity_and_runner_exception(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _, freeze, prepared = _prepared()
    with pytest.raises(SealedOmniAdapterError, match="identity"):
        SealedOmniConditionAdapter(
            workspace=workspace,
            capture_root=Path("runs/sealed-final-v1/captures"),
            condition_binding=freeze.condition("C1"),
            policy=_policy(),
            probe_runner=lambda _prepared, _store: None,  # type: ignore[arg-type,return-value]
        )

    adapter = _adapter(
        workspace,
        freeze,
        lambda _prepared, _store: (_ for _ in ()).throw(RuntimeError("synthetic")),
    )
    with pytest.raises(SealedOmniAdapterError, match="capture failed"):
        adapter.execute(prepared)

    capture_directories = [
        path
        for path in (workspace / "runs/sealed-final-v1/captures").rglob("*")
        if path.is_dir()
    ]
    assert capture_directories
    assert all(os.stat(path).st_mode & 0o777 == 0o700 for path in capture_directories)


def test_c4_adapter_rejects_invalid_root_runner_authority_and_result(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    _, freeze, prepared = _prepared()
    with pytest.raises(SealedOmniAdapterError, match="root"):
        SealedOmniConditionAdapter(
            workspace=workspace,
            capture_root=Path("../escape"),
            condition_binding=freeze.condition("C4"),
            policy=_policy(),
            probe_runner=lambda _prepared, _store: _probe(_store),
        )
    with pytest.raises(SealedOmniAdapterError, match="runner"):
        SealedOmniConditionAdapter(
            workspace=workspace,
            capture_root=Path("runs/sealed-final-v1/captures"),
            condition_binding=freeze.condition("C4"),
            policy=_policy(),
            probe_runner=object(),  # type: ignore[arg-type]
        )

    adapter = _adapter(workspace, freeze, lambda _prepared, _store: None)
    with pytest.raises(SealedOmniAdapterError, match="result"):
        adapter.execute(prepared)
    with pytest.raises(SealedOmniAdapterError, match="authority"):
        adapter.execute(object())  # type: ignore[arg-type]

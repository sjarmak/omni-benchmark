from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.direct_sql_attempt import DirectAttemptSpec, write_direct_attempt
from omni_benchmark.direct_capture_receipt import (
    capture_receipt_payload,
    capture_summary_from_probe,
)
from omni_benchmark.direct_runtime_binding import (
    DirectContextIdentity,
    DirectRuntimeBinding,
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

SHA_D = "d" * 64


def _spec(binding: object) -> DirectAttemptSpec:
    return DirectAttemptSpec(
        binding=binding,
        controllable_seed=None,
        semantic_model_ref="raw-schema:fixture-v1",
        semantic_model_sha256=None,
        software_versions={"omni-benchmark": "0.1.0"},
        cli_versions={"direct-harness": "0.1.0"},
    )


def _refused_capture(tmp_path: Path, *, run_id: str = "run") -> tuple[object, ...]:
    binding = runtime_binding(run_id=run_id)
    workspace, artifact_store = store(tmp_path, "direct-attempt")
    model = SequenceModel(
        binding,
        [{"type": "refuse", "reason": "insufficient_information"}],
    )
    database = SyntheticDatabase(binding, {})
    prepared = prepared_attempt(
        binding,
        model=model,
        database=database,
        public_tools=BoundPublicTools(binding),
        artifact_store=artifact_store,
    )
    probe = capture_with_test_time(prepared, clock_steps=20)
    return workspace, artifact_store, binding, probe


def test_direct_attempt_derives_identity_from_one_runtime_binding(
    tmp_path: Path,
) -> None:
    workspace, artifact_store, binding, probe = _refused_capture(tmp_path)

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=artifact_store,
        spec=_spec(binding),
        probe=probe,
    )

    generation = json.loads(artifacts.generation.path.read_text())
    assert generation["runtime_binding_sha256"] == binding.sha256()
    assert generation["attempt_id"] == binding.attempt_id
    assert generation["condition"] == binding.condition
    assert generation["instance_id"] == binding.question.instance_id
    assert generation["question"] == binding.question.question
    assert generation["model"] == {
        "name": binding.model.model,
        "provider": binding.model.provider,
        "version": binding.model.model,
    }
    manifest = json.loads(artifacts.run_manifest.path.read_text())
    assert manifest["git_commit"] == binding.system_commit
    assert manifest["budget_id"] == binding.budget.budget_id
    assert manifest["harness_config_sha256"] == binding.model.transport_config_sha256
    assert manifest["prompt_sha256"] == binding.model.system_prompt_sha256


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempt_id", "forged:attempt:C1:1"),
        ("condition", "C2"),
        ("maximum_turns", 999),
        ("question_sha256", SHA_D),
        ("provider", "other-provider"),
        ("model", "other-model"),
    ],
)
def test_publisher_rejects_duplicate_probe_label_substitution_before_writes(
    tmp_path: Path, field: str, value: object
) -> None:
    workspace, artifact_store, binding, probe = _refused_capture(tmp_path)
    substituted = replace(probe, **{field: value})

    with pytest.raises(ValueError, match="binding|identity|budget|question|model"):
        write_direct_attempt(
            workspace=workspace,
            store=artifact_store,
            spec=_spec(binding),
            probe=substituted,
        )

    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()
    assert not (workspace / "runs/direct-attempt/run.json").exists()


def test_publisher_rejects_cross_binding_before_writes(tmp_path: Path) -> None:
    workspace, artifact_store, _, probe = _refused_capture(tmp_path, run_id="first")
    other = runtime_binding(run_id="second")

    with pytest.raises(ValueError, match="runtime binding"):
        write_direct_attempt(
            workspace=workspace,
            store=artifact_store,
            spec=_spec(other),
            probe=probe,
        )

    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()


@pytest.mark.parametrize("surface", ["database", "context", "model", "budget"])
def test_publisher_rejects_runtime_component_substitution(
    tmp_path: Path, surface: str
) -> None:
    workspace, artifact_store, binding, probe = _refused_capture(tmp_path)
    if surface == "database":
        other = runtime_binding(
            database=database_identity(selected_database="other_database")
        )
    elif surface == "model":
        other = runtime_binding(model=model_identity(model="other-model"))
    elif surface == "budget":
        other = runtime_binding(budget=budget_identity(maximum_turns=2))
    else:
        components = dict(binding.context.component_sha256)
        components["public_context"] = "f" * 64
        context = DirectContextIdentity.from_components(
            condition=binding.condition,
            selected_database=binding.database.selected_database,
            component_sha256=components,
            environment={},
        )
        other = DirectRuntimeBinding.from_parts(
            system_commit=binding.system_commit,
            run_id=binding.run_id,
            repetition=binding.repetition,
            condition=binding.condition,
            question=binding.question,
            context=context,
            database=binding.database,
            model=binding.model,
            budget=binding.budget,
            environment={},
        )

    with pytest.raises(ValueError, match="runtime binding"):
        write_direct_attempt(
            workspace=workspace,
            store=artifact_store,
            spec=_spec(binding),
            probe=replace(probe, binding=other),
        )

    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()


def test_attempt_spec_rejects_non_binding_value() -> None:
    with pytest.raises((TypeError, ValueError), match="binding"):
        _spec({"forged": "runtime"})


def test_attempt_spec_reparses_and_rejects_noncanonical_binding() -> None:
    binding = runtime_binding()

    with pytest.raises(ValueError, match="runtime binding"):
        _spec(replace(binding, attempt_id="forged:attempt:C1:1"))


def _relocated_probe(
    workspace: Path,
    probe: object,
    *,
    root: str,
    receipt_binding: DirectRuntimeBinding | None,
) -> tuple[ArtifactStore, object]:
    relocated = ArtifactStore(workspace, Path("runs") / root)
    trace = relocated.write_bytes(
        Path("attempt.trace.jsonl"), probe.trace.path.read_bytes()
    )
    action_evidence = relocated.write_bytes(
        Path("attempt.action-evidence.json"), probe.action_evidence.path.read_bytes()
    )
    if receipt_binding is None:
        receipt_payload = {
            "artifact_root_identity": relocated.root_identity,
            "attempt_id": probe.attempt_id,
            "schema_version": 1,
            "trace_path": relocated.relative_path(trace).as_posix(),
            "trace_sha256": trace.sha256,
        }
    else:
        receipt_payload = capture_receipt_payload(
            store=relocated,
            binding=receipt_binding,
            sql=probe.generated_sql,
            trace=trace,
            action_evidence=action_evidence,
            result=None,
            capture_summary=capture_summary_from_probe(probe),
        )
    receipt = relocated.write_json(Path("capture.receipt.json"), receipt_payload)
    return relocated, replace(
        probe, receipt=receipt, trace=trace, action_evidence=action_evidence
    )


def test_publisher_rejects_receipt_v1_forgery(tmp_path: Path) -> None:
    workspace, _, binding, probe = _refused_capture(tmp_path)
    relocated, forged = _relocated_probe(
        workspace,
        probe,
        root="receipt-v1",
        receipt_binding=None,
    )

    with pytest.raises(ValueError, match="capture receipt"):
        write_direct_attempt(
            workspace=workspace,
            store=relocated,
            spec=_spec(binding),
            probe=forged,
        )

    assert not (workspace / "runs/receipt-v1/generation.jsonl").exists()


def test_publisher_rejects_cross_binding_receipt(tmp_path: Path) -> None:
    workspace, _, binding, probe = _refused_capture(tmp_path, run_id="first")
    other = runtime_binding(run_id="second")
    relocated, forged = _relocated_probe(
        workspace,
        probe,
        root="cross-binding-receipt",
        receipt_binding=other,
    )

    with pytest.raises(ValueError, match="capture receipt"):
        write_direct_attempt(
            workspace=workspace,
            store=relocated,
            spec=_spec(binding),
            probe=forged,
        )


def test_publisher_rejects_artifact_root_substitution(tmp_path: Path) -> None:
    workspace, _, binding, probe = _refused_capture(tmp_path)
    other_store = ArtifactStore(workspace, Path("runs/other-root"))

    with pytest.raises(ValueError, match="destination root"):
        write_direct_attempt(
            workspace=workspace,
            store=other_store,
            spec=_spec(binding),
            probe=probe,
        )

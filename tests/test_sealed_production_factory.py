from __future__ import annotations

import hashlib
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.sealed_production_factory as factory_module
import omni_benchmark.sealed_direct_factory as direct_factory_module
import omni_benchmark.sealed_omni_factory as omni_factory_module
from omni_benchmark.freeze_b import FreezeBManifest
from omni_benchmark.sealed_direct_adapter import (
    SealedDirectRuntimeBinding,
    prepare_sealed_direct_capture,
)
from omni_benchmark.sealed_dispatch import execute_sealed_dispatch
from omni_benchmark.sealed_production_factory import (
    SealedProductionAdapterConfig,
    SealedProductionFactoryError,
    build_sealed_production_adapter_factories,
    load_sealed_omni_deployment_gate,
)
from omni_benchmark.sealed_omni_factory import (
    SealedOmniDeploymentGate,
    SealedOmniDeploymentTarget,
)
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    SyntheticDatabase,
)
from tests.test_sealed_direct_adapter import _identities, _prepared
from tests.test_sealed_direct_factory import _policy, _runtime_inputs
from tests.test_sealed_generation_staging import _plan, _workspace
from tests.test_sealed_omni_factory import _gate, _specs
from tests.test_sealed_omni_adapter import _probe
from tests.test_sealed_dispatch import _preflight


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _deployment_repository(
    tmp_path: Path,
) -> tuple[Path, str, Path, FreezeBManifest]:
    repo = tmp_path / "repo"
    repo.mkdir()
    gate_path = Path("config/sealed-omni-deployment-gate-v1.json")
    record_path = Path("experiments/deployments/final/final.db_1.json")
    record = {
        "branch_id": "branch-db-1",
        "database": "db_1",
        "kind": "public-omni-semantic-deployment",
        "model_id": "model-db-1",
        "readback_verified": True,
        "run_id": "sealed-final-deployment-v1",
        "schema_version": 2,
        "semantic_model_sha256": "e" * 64,
        "source_commit": "1" * 40,
        "status": "verified",
        "validation_issue_count": 0,
    }
    record_bytes = _canonical(record)
    gate = {
        "deployment_run_id": "sealed-final-deployment-v1",
        "deployment_source_commit": "1" * 40,
        "kind": "sealed-omni-deployment-gate",
        "schema_version": 1,
        "semantic_model_ref": "export:final-v1",
        "semantic_model_sha256": "d" * 64,
        "targets": [
            {
                "branch_id": "branch-db-1",
                "database": "db_1",
                "model_id": "model-db-1",
                "record_path": record_path.as_posix(),
                "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
                "semantic_model_sha256": "e" * 64,
            }
        ],
    }
    gate_bytes = _canonical(gate)
    for path, content in ((gate_path, gate_bytes), (record_path, record_bytes)):
        destination = repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Synthetic Test")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "deployment gate")
    commit = _git(repo, "rev-parse", "HEAD")

    _unused, original = _plan()
    value = original.as_dict()
    value["system_commit"] = commit
    value["scorer"]["source_commit"] = commit
    for condition in value["conditions"]:
        if condition["condition"] == "C4":
            condition["semantic_model_ref"] = gate["semantic_model_ref"]
            condition["semantic_model_sha256"] = gate["semantic_model_sha256"]
    value["frozen_files"][gate_path.as_posix()] = hashlib.sha256(gate_bytes).hexdigest()
    value["frozen_files"][record_path.as_posix()] = hashlib.sha256(
        record_bytes
    ).hexdigest()
    return repo, commit, gate_path, FreezeBManifest.from_dict(value)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def test_load_deployment_gate_uses_only_frozen_git_evidence(tmp_path: Path) -> None:
    repo, commit, path, freeze = _deployment_repository(tmp_path)

    gate = load_sealed_omni_deployment_gate(
        repo,
        system_commit=commit,
        gate_path=path,
        freeze_b=freeze,
        scheduled_databases={"db_1"},
    )
    (repo / path).write_text("{}\n", encoding="utf-8")
    repeated = load_sealed_omni_deployment_gate(
        repo,
        system_commit=commit,
        gate_path=path,
        freeze_b=freeze,
        scheduled_databases={"db_1"},
    )

    assert repeated == gate
    assert gate.target("db_1").branch_id == "branch-db-1"
    assert gate.semantic_model_sha256 == "d" * 64


def test_load_deployment_gate_rejects_unfrozen_incomplete_or_changed_evidence(
    tmp_path: Path,
) -> None:
    repo, commit, path, freeze = _deployment_repository(tmp_path)

    value = freeze.as_dict()
    del value["frozen_files"][path.as_posix()]
    with pytest.raises(SealedProductionFactoryError, match="frozen"):
        load_sealed_omni_deployment_gate(
            repo,
            system_commit=commit,
            gate_path=path,
            freeze_b=FreezeBManifest.from_dict(value),
            scheduled_databases={"db_1"},
        )

    with pytest.raises(SealedProductionFactoryError, match="coverage"):
        load_sealed_omni_deployment_gate(
            repo,
            system_commit=commit,
            gate_path=path,
            freeze_b=freeze,
            scheduled_databases={"db_1", "db_2"},
        )

    record_path = Path("experiments/deployments/final/final.db_1.json")
    record = json.loads((repo / record_path).read_bytes())
    record["branch_id"] = "substituted"
    (repo / record_path).write_bytes(_canonical(record))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "substituted evidence")
    changed = _git(repo, "rev-parse", "HEAD")
    value = freeze.as_dict()
    value["system_commit"] = changed
    value["scorer"]["source_commit"] = changed
    with pytest.raises(SealedProductionFactoryError, match="digest"):
        load_sealed_omni_deployment_gate(
            repo,
            system_commit=changed,
            gate_path=path,
            freeze_b=FreezeBManifest.from_dict(value),
            scheduled_databases={"db_1"},
        )


def test_build_factories_binds_all_conditions_without_external_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C4")
    runtime_inputs = _runtime_inputs()
    freeze = _plan()[1]
    plan = SimpleNamespace(
        attempts=(SimpleNamespace(condition="C4", database=prepared.database),),
        system_commit=prepared.system_commit,
    )
    preflight = SimpleNamespace(
        workspace=workspace,
        output_root=Path("runs/sealed-final-v1"),
        plan=plan,
        freeze_b=freeze,
        policy=_policy(),
    )
    config = SealedProductionAdapterConfig.create(
        input_spec_path=Path("config/freeze-b-input.json"),
        omni_deployment_gate_path=Path("config/sealed-omni-gate.json"),
        claude_config_directories=(
            Path("/external/lease-1"),
            Path("/external/lease-2"),
            Path("/external/lease-3"),
        ),
        database_environment_root=Path("/external/database-environments"),
        runtime_parent=Path("/external/runtime-parent"),
    )
    events: list[object] = []
    monkeypatch.setattr(
        factory_module,
        "load_sealed_runtime_inputs",
        lambda *_a, **_k: events.append("runtime") or runtime_inputs,
    )
    monkeypatch.setattr(
        factory_module,
        "load_sealed_omni_deployment_gate",
        lambda *_a, **_k: events.append("gate") or _gate(prepared),
    )

    def direct(_config, *, condition, policy):  # type: ignore[no-untyped-def]
        events.append(("direct", condition))
        return condition

    monkeypatch.setattr(factory_module, "build_sealed_direct_adapter_factory", direct)
    monkeypatch.setattr(
        factory_module,
        "build_sealed_omni_adapter_factory",
        lambda _config, *, policy: events.append("omni") or "C4",
    )

    factories = build_sealed_production_adapter_factories(config, preflight)

    assert factories == {"C1": "C1", "C2": "C2", "C3": "C3", "C4": "C4"}
    assert events == [
        "runtime",
        "gate",
        ("direct", "C1"),
        ("direct", "C2"),
        ("direct", "C3"),
        "omni",
    ]


def test_production_config_rejects_relative_external_paths() -> None:
    with pytest.raises(SealedProductionFactoryError, match="absolute"):
        SealedProductionAdapterConfig.create(
            input_spec_path=Path("config/freeze-b-input.json"),
            omni_deployment_gate_path=Path("config/sealed-omni-gate.json"),
            claude_config_directories=(
                Path("relative/lease-1"),
                Path("/external/lease-2"),
                Path("/external/lease-3"),
            ),
            database_environment_root=Path("/external/database-environments"),
            runtime_parent=Path("/external/runtime-parent"),
        )
    with pytest.raises(SealedProductionFactoryError, match="distinct absolute"):
        SealedProductionAdapterConfig.create(
            input_spec_path=Path("config/freeze-b-input.json"),
            omni_deployment_gate_path=Path("config/sealed-omni-gate.json"),
            claude_config_directories=(
                Path("/external/lease-1"),
                Path("/external/lease-2"),
                Path("/external/lease-3"),
            ),
            database_environment_root=Path("/external/shared"),
            runtime_parent=Path("/external/shared"),
        )


def test_public_factory_boundaries_reject_noncanonical_inputs(tmp_path: Path) -> None:
    repo, commit, path, freeze = _deployment_repository(tmp_path)
    with pytest.raises(SealedProductionFactoryError, match="system commit"):
        load_sealed_omni_deployment_gate(
            repo,
            system_commit="0" * 40,
            gate_path=path,
            freeze_b=freeze,
            scheduled_databases={"db_1"},
        )
    with pytest.raises(SealedProductionFactoryError, match="invalid JSON"):
        factory_module._canonical_json(b"{", "synthetic")  # noqa: SLF001
    with pytest.raises(SealedProductionFactoryError, match="not canonical"):
        factory_module._canonical_json(b"{}", "synthetic")  # noqa: SLF001
    with pytest.raises(SealedProductionFactoryError, match="protected field"):
        factory_module._canonical_json(  # noqa: SLF001
            _canonical({"gold_sql": "forbidden"}), "synthetic"
        )
    with pytest.raises(SealedProductionFactoryError, match="config"):
        build_sealed_production_adapter_factories(  # type: ignore[arg-type]
            object(), object()
        )
    with pytest.raises(SealedProductionFactoryError, match="path is invalid"):
        SealedProductionAdapterConfig.create(
            input_spec_path=Path("/absolute/input.json"),
            omni_deployment_gate_path=Path("config/gate.json"),
            claude_config_directories=(
                Path("/external/lease-1"),
                Path("/external/lease-2"),
                Path("/external/lease-3"),
            ),
            database_environment_root=Path("/external/database-environments"),
            runtime_parent=Path("/external/runtime-parent"),
        )


def test_real_production_factories_complete_all_1212_synthetic_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    preflight = _preflight(workspace, policy=_policy())
    prepared_c4 = _prepared(condition="C4")
    databases = sorted(
        {
            attempt.database
            for attempt in preflight.plan.attempts
            if attempt.condition == "C4"
        }
    )
    deployment_gate = SealedOmniDeploymentGate.create(
        semantic_model_ref=prepared_c4.condition_binding.semantic_model_ref,
        semantic_model_sha256=(prepared_c4.condition_binding.semantic_model_sha256),
        targets={
            database: SealedOmniDeploymentTarget.create(
                database=database,
                branch_id=f"branch-{index}",
                model_id=f"model-{index}",
                semantic_model_sha256=f"{index:064x}",
            )
            for index, database in enumerate(databases, start=1)
        },
    )
    config = SealedProductionAdapterConfig.create(
        input_spec_path=Path("config/freeze-b-input.json"),
        omni_deployment_gate_path=Path("config/sealed-omni-gate.json"),
        claude_config_directories=(
            Path("/external/lease-1"),
            Path("/external/lease-2"),
            Path("/external/lease-3"),
        ),
        database_environment_root=Path("/external/database-environments"),
        runtime_parent=Path("/external/runtime-parent"),
    )
    monkeypatch.setattr(
        factory_module,
        "load_sealed_runtime_inputs",
        lambda *_a, **_k: _runtime_inputs(),
    )
    monkeypatch.setattr(
        factory_module,
        "load_sealed_omni_deployment_gate",
        lambda *_a, **_k: deployment_gate,
    )
    monkeypatch.setattr(
        omni_factory_module,
        "load_c4_probe_specs",
        lambda *_a, **_k: _specs(prepared_c4),
    )

    @contextmanager
    def synthetic_direct_capture(_config, _condition_input, prepared, store):  # type: ignore[no-untyped-def]
        context, database_identity, model_identity, budget_identity = _identities(
            prepared
        )
        shell = SimpleNamespace(
            condition=prepared.condition,
            context=context,
            database=database_identity,
            model=model_identity,
            budget=budget_identity,
        )
        model = SequenceModel(
            shell, [{"type": "refuse", "reason": "insufficient_information"}]
        )
        database = SyntheticDatabase(shell, {})
        public_tools = BoundPublicTools(shell)
        binding = SealedDirectRuntimeBinding.from_prepared(
            prepared=prepared,
            context=context,
            database=database_identity,
            model=model_identity,
            budget=budget_identity,
        )
        yield prepare_sealed_direct_capture(
            prepared=prepared,
            binding=binding,
            model_transport=model,
            database=database,
            public_tools=public_tools,
            store=store,
        )

    monkeypatch.setattr(
        direct_factory_module, "_capture_dependencies", synthetic_direct_capture
    )
    monkeypatch.setattr(
        omni_factory_module,
        "_run_probe",
        lambda _config, _specs_value, _policy_value, _prepared_value, store: _probe(
            store
        ),
    )

    report = execute_sealed_dispatch(
        preflight,
        adapter_factories_builder=lambda value: (
            build_sealed_production_adapter_factories(config, value)
        ),
    )

    assert report.attempt_count == 1_212
    assert report.completed_this_run == 1_212
    assert report.remaining_count == 0
    assert len(report.cohorts) == 12

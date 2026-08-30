from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.sealed_direct_factory as factory_module
from omni_benchmark.claude_direct_transport import (
    PINNED_CLAUDE_BINARY_SHA256,
    PINNED_CLAUDE_VERSION,
)
from omni_benchmark.direct_probe_cli import DirectRuntimeSpec
from omni_benchmark.sealed_direct_factory import (
    DatabaseEnvironmentDirectory,
    SealedDirectFactoryError,
    SealedDirectProductionConfig,
    build_sealed_direct_adapter_factory,
)
from omni_benchmark.sealed_dispatch import SealedDispatchPolicy
from omni_benchmark.sealed_runtime_inputs import (
    SealedConditionRuntimeInput,
    SealedRuntimeInputs,
)
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    SyntheticDatabase,
)
from tests.test_sealed_direct_adapter import _identities, _prepared
from tests.test_sealed_generation_staging import _plan, _workspace


def _runtime_inputs() -> SealedRuntimeInputs:
    _plan_value, freeze = _plan()
    conditions = []
    for name in ("C1", "C2", "C3", "C4"):
        semantic = {
            "C1": None,
            "C2": Path("semantic_models/public_ir/manifest.json"),
            "C3": Path("semantic_models/public_baseline/manifest.json"),
            "C4": Path("semantic_models/public_bundle/manifest.json"),
        }[name]
        conditions.append(
            SealedConditionRuntimeInput(
                condition=name,
                harness_config_path=Path(
                    f"config/conditions/{name.lower()}-direct-sql-v1.json"
                    if name != "C4"
                    else "config/conditions/c4-production-v1.json"
                ),
                instructions_path=Path(
                    "config/instructions/direct-sql-v1.json"
                    if name != "C4"
                    else "config/instructions/c4-managed-instructions-v1.json"
                ),
                prompt_path=Path(
                    "config/prompts/direct-sql-v1.txt"
                    if name != "C4"
                    else "config/prompts/c4-user-prompt-v1.txt"
                ),
                runtime_policy_path=Path(
                    "config/conditions/direct-runtime-v1.json"
                    if name != "C4"
                    else "config/conditions/c4-production-v1.json"
                ),
                semantic_model_path=semantic,
                freeze_b_condition=freeze.condition(name),
            )
        )
    return SealedRuntimeInputs(
        system_commit=freeze.system_commit,
        freeze_a_commit=freeze.freeze_a_commit,
        input_spec_path=Path("config/freeze-b-input.json"),
        input_spec_sha256="a" * 64,
        database_snapshot_path=Path("data/database-snapshot.json"),
        database_snapshot_sha256=freeze.snapshot_manifest_sha256,
        conditions=tuple(conditions),
    )


def _policy() -> SealedDispatchPolicy:
    cli = {
        "claude": PINNED_CLAUDE_VERSION,
        "claude.sha256": PINNED_CLAUDE_BINARY_SHA256,
    }
    return SealedDispatchPolicy.create(
        maximum_concurrency=3,
        maximum_wall_clock_seconds=43_200,
        cost_ceiling_usd="1212.000000",
        reservation_usd_by_condition={
            name: "1.000000" for name in ("C1", "C2", "C3", "C4")
        },
        software_versions={"omni-benchmark": "0.1.0"},
        cli_versions_by_condition={
            "C1": cli,
            "C2": cli,
            "C3": cli,
            "C4": {"omni": "1.1.2", "omni.sha256": "a" * 64},
        },
    )


def _config(workspace: Path) -> SealedDirectProductionConfig:
    return SealedDirectProductionConfig.create(
        workspace=workspace,
        system_commit=_runtime_inputs().system_commit,
        runtime_inputs=_runtime_inputs(),
        capture_root=Path("runs/sealed-final-v1/captures"),
        claude_config_directories=(
            Path("/external/lease-1"),
            Path("/external/lease-2"),
            Path("/external/lease-3"),
        ),
        database_environment_root=Path("/external/database-environments"),
        runtime_parent=Path("/external/runtime-parent"),
    )


def test_factory_is_inert_until_attempt_and_cleans_runtime_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C2")
    context, database_identity, model_identity, budget_identity = _identities(prepared)
    events: list[object] = []
    runtime = DirectRuntimeSpec(
        adapter=model_identity.adapter,
        adapter_version=model_identity.adapter_version,
        budget_id=budget_identity.budget_id,
        effort="high",
        harness_retry_ceiling=0,
        input_token_ceiling=None,
        maximum_cost_usd_per_turn=budget_identity.per_turn_max_cost_usd,
        maximum_turns=budget_identity.maximum_turns,
        model=model_identity.model,
        output_token_ceiling=None,
        provider=model_identity.provider,
        timeout_seconds_per_turn=budget_identity.per_turn_timeout_seconds,
        token_ceiling_unavailable_reason="synthetic",
        sha256=prepared.condition_binding.runtime_policy_sha256,
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

    monkeypatch.setattr(
        factory_module,
        "load_committed_direct_runtime_spec",
        lambda *_args: events.append("runtime") or runtime,
    )
    monkeypatch.setattr(
        factory_module,
        "load_direct_public_tools",
        lambda *_args, **_kwargs: events.append("public") or public_tools,
    )
    monkeypatch.setattr(
        factory_module,
        "load_committed_direct_database_identity",
        lambda *_args, **_kwargs: (
            events.append("database_identity") or database_identity
        ),
    )
    monkeypatch.setattr(
        factory_module,
        "_validate_oauth_directory",
        lambda path: events.append(("lease", path)),
    )
    monkeypatch.setattr(
        factory_module,
        "_validate_external_private_directory",
        lambda workspace, path, description: path,
    )

    class FakeDirectory:
        def __init__(self, workspace: Path, root: Path) -> None:
            events.append(("database_root", root))

        def for_database(self, name: str) -> dict[str, str]:
            events.append(("database_environment", name))
            return {"synthetic": "database"}

    @contextmanager
    def runtime_directories(parent: Path):  # type: ignore[no-untyped-def]
        events.append(("runtime_enter", parent))
        yield (Path("/runtime/home"), Path("/runtime/tmp"), Path("/runtime/work"))
        events.append("runtime_exit")

    monkeypatch.setattr(factory_module, "DatabaseEnvironmentDirectory", FakeDirectory)
    monkeypatch.setattr(
        factory_module, "private_runtime_directories", runtime_directories
    )
    monkeypatch.setattr(
        factory_module,
        "ClaudeDirectTransport",
        lambda _config: events.append("model_transport") or model,
    )
    monkeypatch.setattr(
        factory_module,
        "AttestedDirectPostgresTransport",
        lambda _environment, expected_identity: (
            events.append("database_transport") or database
        ),
    )

    adapter_factory = build_sealed_direct_adapter_factory(
        _config(workspace), condition="C2", policy=_policy()
    )
    assert events == []
    adapter = adapter_factory(prepared.condition_binding)
    assert events == []

    result = adapter.execute(prepared)

    assert result.generation_record["generation_outcome"] == "refused"
    assert ("lease", Path("/external/lease-1")) in events
    assert events[-1] == "runtime_exit"
    assert events.index("runtime") < events.index("model_transport")
    assert events.index("database_identity") < events.index("database_transport")


def test_factory_rejects_wrong_frozen_path_cli_or_condition_without_external_access(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    config = _config(workspace)
    bad_conditions = list(config.runtime_inputs.conditions)
    bad_conditions[0] = replace(
        bad_conditions[0], prompt_path=Path("config/prompts/substituted.txt")
    )
    bad_inputs = replace(config.runtime_inputs, conditions=tuple(bad_conditions))

    with pytest.raises(SealedDirectFactoryError, match="path"):
        build_sealed_direct_adapter_factory(
            replace(config, runtime_inputs=bad_inputs), condition="C1", policy=_policy()
        )

    value = _policy().as_dict()
    value["cli_versions_by_condition"]["C1"] = {"claude": "wrong"}
    with pytest.raises(SealedDirectFactoryError, match="CLI"):
        build_sealed_direct_adapter_factory(
            config,
            condition="C1",
            policy=SealedDispatchPolicy.from_dict(value),
        )

    factory = build_sealed_direct_adapter_factory(
        config, condition="C1", policy=_policy()
    )
    with pytest.raises(SealedDirectFactoryError, match="condition"):
        factory(config.runtime_inputs.condition("C2").freeze_b_condition)


def test_database_environment_directory_requires_external_private_exact_files(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    root = tmp_path / "database-environments"
    root.mkdir(mode=0o700)
    path = root / "db_1.json"
    value = {
        "PGDATABASE": "neondb",
        "PGHOST": "public.invalid",
        "PGPASSWORD": "synthetic-secret",
        "PGPORT": "5432",
        "PGSSLMODE": "verify-full",
        "PGUSER": "reader",
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)

    directory = DatabaseEnvironmentDirectory(workspace, root)

    assert directory.for_database("db_1") == {
        **value,
        "PGSSLROOTCERT": "/etc/ssl/certs/ca-certificates.crt",
    }
    assert "synthetic-secret" not in repr(directory)

    path.chmod(0o644)
    with pytest.raises(SealedDirectFactoryError, match="unavailable"):
        directory.for_database("db_1")
    with pytest.raises(SealedDirectFactoryError, match="identity"):
        directory.for_database("../escape")

    internal = workspace / "private-db"
    internal.mkdir(mode=0o700)
    with pytest.raises(SealedDirectFactoryError, match="external"):
        DatabaseEnvironmentDirectory(workspace, internal)


def test_production_config_rejects_ambiguous_external_paths(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    common = {
        "workspace": workspace,
        "system_commit": _runtime_inputs().system_commit,
        "runtime_inputs": _runtime_inputs(),
        "capture_root": Path("runs/sealed-final-v1/captures"),
        "database_environment_root": Path("/external/database-environments"),
        "runtime_parent": Path("/external/runtime-parent"),
    }

    with pytest.raises(SealedDirectFactoryError, match="three distinct"):
        SealedDirectProductionConfig.create(
            **common,
            claude_config_directories=(
                Path("/external/lease-1"),
                Path("/external/lease-1"),
                Path("/external/lease-1"),
            ),
        )
    with pytest.raises(SealedDirectFactoryError, match="absolute"):
        SealedDirectProductionConfig.create(
            **{**common, "database_environment_root": Path("relative")},
            claude_config_directories=(
                Path("/external/lease-1"),
                Path("/external/lease-2"),
                Path("/external/lease-3"),
            ),
        )


def test_runtime_and_lease_directories_must_be_external_private(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    external = tmp_path / "external-runtime"
    external.mkdir(mode=0o700)

    assert (
        factory_module._validate_external_private_directory(  # noqa: SLF001
            workspace, external, "runtime parent"
        )
        == external.resolve()
    )

    external.chmod(0o755)
    with pytest.raises(SealedDirectFactoryError, match="external private"):
        factory_module._validate_external_private_directory(  # noqa: SLF001
            workspace, external, "runtime parent"
        )
    internal = workspace / "lease"
    internal.mkdir(mode=0o700)
    with pytest.raises(SealedDirectFactoryError, match="external private"):
        factory_module._validate_external_private_directory(  # noqa: SLF001
            workspace, internal, "Claude lease directory"
        )

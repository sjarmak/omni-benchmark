from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import omni_benchmark.sealed_omni_factory as factory_module
from omni_benchmark.omni_cli import OmniCliSettings
from omni_benchmark.omni_probe_preflight import (
    C4ConditionSpec,
    C4ProbeSpecs,
    CommittedSpec,
)
from omni_benchmark.sealed_omni_factory import (
    SealedOmniDeploymentGate,
    SealedOmniDeploymentTarget,
    SealedOmniFactoryError,
    SealedOmniProductionConfig,
    build_sealed_omni_adapter_factory,
    specs_condition,
)
from omni_benchmark.sealed_omni_adapter import SealedOmniAdapterError
from tests.test_sealed_direct_adapter import _prepared
from tests.test_sealed_direct_factory import _policy, _runtime_inputs
from tests.test_sealed_generation_staging import _workspace
from tests.test_sealed_omni_adapter import _probe


def _gate(prepared) -> SealedOmniDeploymentGate:  # type: ignore[no-untyped-def]
    return SealedOmniDeploymentGate.create(
        semantic_model_ref=prepared.condition_binding.semantic_model_ref,
        semantic_model_sha256=prepared.condition_binding.semantic_model_sha256,
        targets={
            prepared.database: SealedOmniDeploymentTarget.create(
                database=prepared.database,
                branch_id="branch-db-1",
                model_id="model-db-1",
                semantic_model_sha256="e" * 64,
            )
        },
    )


def _config(workspace: Path, prepared) -> SealedOmniProductionConfig:  # type: ignore[no-untyped-def]
    return SealedOmniProductionConfig.create(
        workspace=workspace,
        system_commit=prepared.system_commit,
        runtime_inputs=_runtime_inputs(),
        capture_root=Path("runs/sealed-final-v1/captures"),
        deployment_gate=_gate(prepared),
        scheduled_databases={prepared.database},
    )


def _specs(prepared) -> C4ProbeSpecs:  # type: ignore[no-untyped-def]
    frozen = prepared.condition_binding
    return C4ProbeSpecs(
        condition=C4ConditionSpec(
            managed_llm_identity=frozen.model,
            maximum_status_checks=60,
            model_config_id=frozen.model_config_id,
            omni_cli_sha256="a" * 64,
            omni_cli_version="1.1.2",
            poll_schedule_seconds=(2.0, 5.0, 10.0),
            provider=frozen.provider,
        ),
        condition_sha256=frozen.harness_config_sha256,
        prompt=CommittedSpec(
            path=Path("config/prompts/c4-user-prompt-v1.txt"),
            content=b"{question}\n",
            sha256=frozen.prompt_sha256,
        ),
        prompt_sha256=frozen.prompt_sha256,
        instructions_sha256=frozen.instructions_sha256,
    )


def test_factory_is_inert_and_runs_exact_c4_capture_after_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C4")
    config = _config(workspace, prepared)
    events: list[object] = []
    settings = OmniCliSettings(
        base_url="https://example.invalid",
        model_id="model-db-1",
        profile="benchmark-infra",
        branch_id="branch-db-1",
        binary="/pinned/omni",
    )

    monkeypatch.setattr(
        factory_module,
        "load_c4_probe_specs",
        lambda *_args, **_kwargs: events.append("specs") or _specs(prepared),
    )

    def load_settings(environment):  # type: ignore[no-untyped-def]
        events.append(("settings", dict(environment)))
        return settings

    monkeypatch.setattr(factory_module, "_load_settings", load_settings)
    monkeypatch.setattr(
        factory_module,
        "pin_omni_cli_binary",
        lambda value, environment, digest: (
            events.append(("pin", digest)) or (value, digest)
        ),
    )
    monkeypatch.setattr(
        factory_module,
        "observe_omni_cli_version",
        lambda value, environment: events.append("version") or "1.1.2",
    )
    monkeypatch.setattr(
        factory_module,
        "render_public_question",
        lambda prompt, question: events.append("render") or question,
    )

    class Client:
        def whoami(self):  # type: ignore[no-untyped-def]
            events.append("whoami")
            return {"id": "synthetic"}

    monkeypatch.setattr(
        factory_module,
        "OmniCliClient",
        lambda value, environment: events.append("client") or Client(),
    )

    class Capture:
        def __init__(self, client, store, **options):  # type: ignore[no-untyped-def]
            events.append(("capture", options))
            self.store = store

        def probe(self, question):  # type: ignore[no-untyped-def]
            events.append(("probe", question))
            return _probe(self.store)

    monkeypatch.setattr(factory_module, "OmniJobCapture", Capture)

    adapter_factory = build_sealed_omni_adapter_factory(config, policy=_policy())
    assert events == ["specs"]
    adapter = adapter_factory(prepared.condition_binding)
    assert events == ["specs"]

    result = adapter.execute(prepared)

    assert result.generation_record["partition"] == "test"
    assert result.generation_record["generated_query"] == "{fields:[answers.value]}"
    assert events.index("specs") < events.index("whoami")
    environment = next(
        item[1]
        for item in events
        if isinstance(item, tuple) and len(item) == 2 and item[0] == "settings"
    )
    assert environment["OMNI_BRANCH_ID"] == "branch-db-1"
    assert environment["OMNI_MODEL_ID"] == "model-db-1"
    assert environment["OMNI_SEMANTIC_DATABASE"] == prepared.database
    assert environment["OMNI_SEMANTIC_MODEL_SHA256"] == "e" * 64


def test_factory_rejects_gate_coverage_condition_path_and_cli_before_live_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C4")
    config = _config(workspace, prepared)
    monkeypatch.setattr(
        factory_module,
        "load_c4_probe_specs",
        lambda *_args, **_kwargs: _specs(prepared),
    )

    with pytest.raises(SealedOmniFactoryError, match="coverage"):
        SealedOmniProductionConfig.create(
            workspace=workspace,
            system_commit=prepared.system_commit,
            runtime_inputs=_runtime_inputs(),
            capture_root=Path("runs/sealed-final-v1/captures"),
            deployment_gate=_gate(prepared),
            scheduled_databases={prepared.database, "missing_db"},
        )

    inputs = _runtime_inputs()
    c4 = inputs.condition("C4")
    wrong = replace(c4, prompt_path=Path("wrong.txt"))
    bad_inputs = replace(
        inputs,
        conditions=tuple(
            wrong if item.condition == "C4" else item for item in inputs.conditions
        ),
    )
    with pytest.raises(SealedOmniFactoryError, match="path"):
        build_sealed_omni_adapter_factory(
            replace(config, runtime_inputs=bad_inputs),
            policy=_policy(),
        )

    value = _policy().as_dict()
    value["cli_versions_by_condition"]["C4"] = {"omni": "wrong"}
    with pytest.raises(SealedOmniFactoryError, match="CLI"):
        build_sealed_omni_adapter_factory(
            config,
            policy=factory_module.SealedDispatchPolicy.from_dict(value),
        )

    factory = build_sealed_omni_adapter_factory(config, policy=_policy())
    with pytest.raises(SealedOmniFactoryError, match="condition"):
        factory(_runtime_inputs().condition("C3").freeze_b_condition)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database", ""),
        ("branch_id", "bad branch"),
        ("model_id", object()),
        ("semantic_model_sha256", "short"),
    ],
)
def test_deployment_target_rejects_invalid_identity(field: str, value: object) -> None:
    values: dict[str, object] = {
        "database": "db_1",
        "branch_id": "branch-db-1",
        "model_id": "model-db-1",
        "semantic_model_sha256": "e" * 64,
    }
    values[field] = value

    with pytest.raises(SealedOmniFactoryError, match="target is invalid"):
        SealedOmniDeploymentTarget.create(**values)  # type: ignore[arg-type]


def test_deployment_gate_rejects_bad_evidence_and_missing_database() -> None:
    target = SealedOmniDeploymentTarget.create(
        database="db_1",
        branch_id="branch-db-1",
        model_id="model-db-1",
        semantic_model_sha256="e" * 64,
    )
    with pytest.raises(SealedOmniFactoryError, match="gate is invalid"):
        SealedOmniDeploymentGate.create(
            semantic_model_ref="",
            semantic_model_sha256="f" * 64,
            targets={"db_1": target},
        )
    with pytest.raises(SealedOmniFactoryError, match="gate target is invalid"):
        SealedOmniDeploymentGate.create(
            semantic_model_ref="bundle:v1",
            semantic_model_sha256="f" * 64,
            targets={"wrong": target},
        )

    gate = SealedOmniDeploymentGate.create(
        semantic_model_ref="bundle:v1",
        semantic_model_sha256="f" * 64,
        targets={"db_1": target},
    )
    with pytest.raises(SealedOmniFactoryError, match="absent"):
        gate.target("db_2")


def test_factory_rejects_noncanonical_config_and_freeze_b_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C4")
    config = _config(workspace, prepared)
    specs = _specs(prepared)
    monkeypatch.setattr(
        factory_module,
        "load_c4_probe_specs",
        lambda *_args, **_kwargs: specs,
    )

    with pytest.raises(SealedOmniFactoryError, match="configuration"):
        build_sealed_omni_adapter_factory(object(), policy=_policy())  # type: ignore[arg-type]

    wrong_inputs = _runtime_inputs()
    c4 = wrong_inputs.condition("C4")
    wrong_c4 = replace(
        c4,
        freeze_b_condition=replace(c4.freeze_b_condition, provider="wrong"),
    )
    wrong_inputs = replace(
        wrong_inputs,
        conditions=tuple(
            wrong_c4 if item.condition == "C4" else item
            for item in wrong_inputs.conditions
        ),
    )
    with pytest.raises(SealedOmniFactoryError, match="Freeze B"):
        build_sealed_omni_adapter_factory(
            replace(config, runtime_inputs=wrong_inputs),
            policy=_policy(),
        )

    with pytest.raises(SealedOmniFactoryError, match="specifications are invalid"):
        factory_module._require_c4_identity(  # noqa: SLF001
            object(),
            prepared.condition_binding,
            config.deployment_gate,
            _policy(),
        )


def test_probe_rejects_settings_and_cli_identity_before_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition="C4")
    config = _config(workspace, prepared)
    specs = _specs(prepared)
    client_events: list[str] = []
    monkeypatch.setattr(factory_module, "load_c4_probe_specs", lambda *_a, **_k: specs)
    monkeypatch.setattr(
        factory_module,
        "OmniCliClient",
        lambda *_a, **_k: client_events.append("client"),
    )
    adapter = build_sealed_omni_adapter_factory(config, policy=_policy())(
        prepared.condition_binding
    )

    monkeypatch.setattr(
        factory_module,
        "_load_settings",
        lambda _environment: OmniCliSettings(
            base_url="https://example.invalid",
            model_id="wrong-model",
            profile="benchmark-infra",
            branch_id="branch-db-1",
            binary="/pinned/omni",
        ),
    )
    with pytest.raises(
        SealedOmniAdapterError, match="capture failed"
    ) as settings_error:
        adapter.execute(prepared)
    assert isinstance(settings_error.value.__cause__, SealedOmniFactoryError)
    assert "settings" in str(settings_error.value.__cause__)
    assert client_events == []

    settings = OmniCliSettings(
        base_url="https://example.invalid",
        model_id="model-db-1",
        profile="benchmark-infra",
        branch_id="branch-db-1",
        binary="/pinned/omni",
    )
    monkeypatch.setattr(factory_module, "_load_settings", lambda _environment: settings)
    monkeypatch.setattr(
        factory_module,
        "pin_omni_cli_binary",
        lambda *_a, **_k: (settings, "a" * 64),
    )
    monkeypatch.setattr(
        factory_module,
        "observe_omni_cli_version",
        lambda *_a, **_k: "wrong-version",
    )
    with pytest.raises(SealedOmniAdapterError, match="capture failed") as cli_error:
        adapter.execute(prepared)
    assert isinstance(cli_error.value.__cause__, SealedOmniFactoryError)
    assert "dispatch policy" in str(cli_error.value.__cause__)
    assert client_events == []

    with pytest.raises(SealedOmniFactoryError, match="Freeze B"):
        specs_condition(
            replace(specs, prompt_sha256="0" * 64),
            config,
        )

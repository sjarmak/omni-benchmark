from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.baseline_attempt_adapter as adapter


def test_baseline_preparer_reuses_direct_preflight_with_public_train_scope(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}
    question = object()
    tools = object()
    database_identity = object()
    model_transport = object()
    database = object()
    binding = object()
    prepared = object()

    monkeypatch.setattr(
        adapter.direct_prepared,
        "_verify_preparation_environment",
        lambda *args: observed.setdefault("verify", args),
    )

    def load(*args, **kwargs):
        observed["load"] = (args, kwargs)
        return question, tools, database_identity

    monkeypatch.setattr(adapter.direct_prepared, "_load_attempt_inputs", load)
    monkeypatch.setattr(
        adapter.direct_prepared,
        "_require_database_alignment",
        lambda *args: observed.setdefault("align", args),
    )
    monkeypatch.setattr(
        adapter.direct_prepared,
        "_construct_transports",
        lambda *args: (model_transport, database),
    )
    monkeypatch.setattr(
        adapter.direct_prepared,
        "_build_runtime_binding",
        lambda *args: binding,
    )
    monkeypatch.setattr(
        adapter.direct_prepared,
        "_mint_prepared_attempt",
        lambda *args: prepared,
    )
    plan = SimpleNamespace(
        workspace="workspace",
        arguments=SimpleNamespace(
            system_commit="a" * 40,
            instance_id="question-1",
            condition="C2",
            run_id="baseline-v1",
            repetition=1,
        ),
        claude_config="claude-config",
        database_environment={"PGHOST": "db.example"},
        store="store",
        environment={},
    )

    result = adapter.prepare_public_baseline_direct_attempt(plan)

    assert result is prepared
    assert observed["load"][0][2] == "train"
    assert observed["load"][0][3] == "question-1"


def test_baseline_direct_main_delegates_cli_parsing_to_existing_probe(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}

    def direct_main(argv, *, environment, attempt_runner):
        observed.update(
            argv=argv, environment=environment, attempt_runner=attempt_runner
        )
        return 7

    monkeypatch.setattr(adapter, "direct_probe_main", direct_main)

    result = adapter.baseline_direct_probe_main(["--example"], environment={})

    assert result == 7
    assert observed["argv"] == ["--example"]
    assert observed["attempt_runner"] is adapter.run_public_baseline_direct_attempt


def test_baseline_omni_question_loader_uses_public_train_scope(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def load(*args, **kwargs):
        observed.update(args=args, kwargs=kwargs)
        return SimpleNamespace(question="Public question")

    monkeypatch.setattr(adapter, "load_committed_direct_question", load)

    question = adapter.load_public_baseline_question(
        "workspace", "a" * 40, "question-1", {}
    )

    assert question == "Public question"
    assert observed["kwargs"]["scope"] == "train"
    assert observed["kwargs"]["instance_id"] == "question-1"


def test_baseline_c4_writer_publishes_train_partition_and_scope(monkeypatch) -> None:
    written: dict[str, object] = {}
    generation = SimpleNamespace(sha256="a" * 64)
    run_manifest = object()

    class Store:
        def write_jsonl(self, path, records):
            written["generation"] = (path, records)
            return generation

        def write_json(self, path, value):
            written["manifest"] = (path, value)
            return run_manifest

    monkeypatch.setattr(
        adapter.omni_attempt,
        "_attempt_record",
        lambda **_: {"partition": "dev-a", "generation_outcome": "answered"},
    )
    monkeypatch.setattr(
        adapter.omni_attempt,
        "_run_manifest",
        lambda *_: SimpleNamespace(
            as_dict=lambda: {
                "scope": "dev-a",
                "generation_sha256": "0" * 64,
            }
        ),
    )
    monkeypatch.setattr(
        adapter.RunManifest,
        "from_dict",
        lambda value: SimpleNamespace(as_dict=lambda: value),
    )

    artifacts = adapter.write_public_baseline_c4_attempt(
        workspace="workspace", store=Store(), spec=object(), probe=object()
    )

    assert written["generation"][1][0]["partition"] == "train"
    assert written["manifest"][1]["scope"] == "train"
    assert written["manifest"][1]["generation_sha256"] == "a" * 64
    assert artifacts.generation is generation
    assert artifacts.run_manifest is run_manifest


def test_baseline_direct_runner_reuses_capture_and_publication(monkeypatch) -> None:
    prepared = SimpleNamespace(binding="binding")
    probe = SimpleNamespace(generation_outcome="answered", failure_class=None)
    artifacts = object()
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        adapter, "prepare_public_baseline_direct_attempt", lambda _: prepared
    )

    class Capture:
        def __init__(self, *, prepared):
            observed["prepared"] = prepared

        def capture(self):
            return probe

    monkeypatch.setattr(adapter, "DirectSqlCapture", Capture)
    monkeypatch.setattr(
        adapter, "_semantic_identity", lambda _: ("semantic-ref", "c" * 64)
    )
    monkeypatch.setattr(
        adapter, "DirectAttemptSpec", lambda **kwargs: SimpleNamespace(**kwargs)
    )

    def write_attempt(**kwargs):
        observed["write"] = kwargs
        return artifacts

    monkeypatch.setattr(adapter, "write_direct_attempt", write_attempt)
    monkeypatch.setattr(
        adapter,
        "_attempt_receipt",
        lambda *args: {"outcome": args[1], "artifacts": args[3]},
    )
    plan = SimpleNamespace(workspace="workspace", store="store")

    receipt = adapter.run_public_baseline_direct_attempt(plan)

    assert observed["prepared"] is prepared
    assert observed["write"]["probe"] is probe
    assert receipt == {"outcome": "answered", "artifacts": artifacts}


def test_baseline_omni_main_uses_existing_capture_and_receipt_path(
    monkeypatch, capsys
) -> None:
    arguments = SimpleNamespace(execute_authenticated_smoke=True)
    plan = SimpleNamespace(workspace="workspace", store="store")
    result = object()
    spec = object()
    artifacts = object()
    monkeypatch.setattr(
        adapter.omni_probe,
        "_parser",
        lambda: SimpleNamespace(parse_args=lambda _: arguments),
    )
    monkeypatch.setattr(adapter, "_prepare_public_baseline_omni_plan", lambda *_: plan)
    monkeypatch.setattr(
        adapter, "_capture_public_baseline_omni", lambda *_, **__: result
    )
    monkeypatch.setattr(adapter, "_c4_attempt_spec", lambda _: spec)
    monkeypatch.setattr(
        adapter, "write_public_baseline_c4_attempt", lambda **_: artifacts
    )
    monkeypatch.setattr(
        adapter.omni_probe, "_receipt", lambda *_: {"status": "captured"}
    )

    assert adapter.baseline_omni_probe_main([], environment={}) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "captured"}


def test_baseline_omni_plan_reuses_committed_probe_preflight(
    tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    condition = SimpleNamespace(
        omni_cli_sha256="a" * 64,
        omni_cli_version="1.0.0",
        managed_llm_identity="managed",
        model_config_id="model-config",
        provider="provider",
    )
    specs = SimpleNamespace(
        condition=condition,
        prompt="prompt",
        condition_sha256="b" * 64,
        prompt_sha256="c" * 64,
        instructions_sha256="d" * 64,
    )
    settings = SimpleNamespace()
    arguments = SimpleNamespace(
        workspace=workspace,
        system_commit="e" * 40,
        harness_config="condition",
        prompt_spec="prompt",
        instructions_spec="instructions",
        instance_id="question-1",
        output_root="runs/baseline",
        run_id="baseline-v1",
        repetition=1,
        budget_id="budget",
    )
    observed: dict[str, object] = {}
    monkeypatch.setattr(adapter.omni_probe, "_load_protocol_config", lambda *_: None)
    monkeypatch.setattr(adapter, "verify_system_commit", lambda *_: None)
    monkeypatch.setattr(adapter, "load_c4_probe_specs", lambda *_, **__: specs)
    monkeypatch.setattr(
        adapter, "load_public_baseline_question", lambda *_: "Public question"
    )
    monkeypatch.setattr(adapter, "render_public_question", lambda *_: "Rendered")
    monkeypatch.setattr(adapter.omni_probe, "_load_settings", lambda _: settings)
    monkeypatch.setattr(
        adapter.omni_probe, "_software_versions", lambda: {"package": "1"}
    )
    monkeypatch.setattr(adapter, "semantic_model_ref", lambda _: "branch:one")
    monkeypatch.setattr(
        adapter.omni_probe, "_prevalidate_attempt_identity", lambda *_: None
    )
    monkeypatch.setattr(
        adapter, "pin_omni_cli_binary", lambda *args: (settings, "f" * 64)
    )
    monkeypatch.setattr(adapter.omni_probe, "_new_store", lambda *_: "store")
    monkeypatch.setattr(adapter, "_c4_attempt_spec", lambda _: "spec")
    monkeypatch.setattr(
        adapter,
        "_prevalidate_train_manifest",
        lambda spec, env: observed.update(spec=spec, environment=env),
    )

    plan = adapter._prepare_public_baseline_omni_plan(arguments, {}, lambda *_: "1.0.0")

    assert plan.question == "Rendered"
    assert plan.semantic_model_ref == "branch:one"
    assert observed == {"spec": "spec", "environment": {}}


def test_baseline_omni_capture_and_spec_reuse_product_components(monkeypatch) -> None:
    observed: dict[str, object] = {}
    result = object()

    class Client:
        def read_semantic_model(self):
            return {"view.view": "label: View\n"}

    client = Client()
    condition = SimpleNamespace(
        maximum_status_checks=4,
        poll_schedule_seconds=(0.0,),
        provider="provider",
        managed_llm_identity="managed",
        model_config_id="config",
    )
    plan = SimpleNamespace(
        settings="settings",
        workspace=Path("/workspace"),
        environment={
            "OMNI_SEMANTIC_DATABASE": "sample_large",
            "OMNI_SEMANTIC_MODEL_SHA256": "e" * 64,
            "OMNI_COST_RESERVATION_USD": "7.000000",
            "OMNI_BUDGET_POLICY_SHA256": "f" * 64,
        },
        store="store",
        question="Question",
        specs=SimpleNamespace(
            condition=condition,
            condition_sha256="a" * 64,
            prompt_sha256="b" * 64,
            instructions_sha256="c" * 64,
        ),
        arguments=SimpleNamespace(
            instance_id="question-1",
            run_id="baseline-v1",
            repetition=1,
            system_commit="d" * 40,
            budget_id="budget",
        ),
        semantic_model_ref="branch:one",
        software_versions={"package": "1"},
        cli_versions={"omni": "1"},
    )
    monkeypatch.setattr(
        adapter.omni_probe,
        "_verify_authentication",
        lambda value: observed.setdefault("client", value),
    )

    class Capture:
        def __init__(self, client, store, **options):
            observed.update(capture_client=client, store=store, options=options)

        def probe(self, question):
            observed["question"] = question
            return result

    monkeypatch.setattr(adapter, "OmniJobCapture", Capture)
    semantic_plan = object()
    monkeypatch.setattr(
        adapter,
        "committed_bundle_plan",
        lambda workspace, commit, database: (
            observed.update(
                semantic_workspace=workspace,
                semantic_commit=commit,
                semantic_database=database,
            )
            or semantic_plan
        ),
    )
    monkeypatch.setattr(
        adapter,
        "verified_semantic_deployment_sha256",
        lambda plan, readback: "e" * 64,
    )

    captured = adapter._capture_public_baseline_omni(
        plan, client_factory=lambda _: client, sleep=lambda _: None
    )
    spec = adapter._c4_attempt_spec(plan)

    assert captured is result
    assert observed["client"] is client
    assert observed["question"] == "Question"
    assert spec.semantic_model_ref == "branch:one"
    assert spec.semantic_model_sha256 == "e" * 64
    assert spec.cost_reservation_usd == 7.0
    assert spec.budget_policy_sha256 == "f" * 64
    assert spec.cost_unavailable_reason == "omni_job_api_does_not_expose_cost"
    assert spec.git_commit == "d" * 40
    assert observed["semantic_commit"] == "d" * 40
    assert observed["semantic_database"] == "sample_large"


def test_baseline_omni_refuses_semantic_branch_drift_before_job_capture(
    monkeypatch,
) -> None:
    capture_started = False

    class Client:
        def read_semantic_model(self):
            return {"view.view": "label: Drifted\n"}

    def capture(*_args, **_kwargs):
        nonlocal capture_started
        capture_started = True
        raise AssertionError("job capture must not start after semantic drift")

    plan = SimpleNamespace(
        settings="settings",
        workspace=Path("/workspace"),
        environment={
            "OMNI_SEMANTIC_DATABASE": "sample_large",
            "OMNI_SEMANTIC_MODEL_SHA256": "a" * 64,
        },
        store="store",
        question="Question",
        specs=SimpleNamespace(
            condition=SimpleNamespace(
                maximum_status_checks=4,
                poll_schedule_seconds=(0.0,),
            )
        ),
        arguments=SimpleNamespace(system_commit="d" * 40),
    )
    monkeypatch.setattr(adapter.omni_probe, "_verify_authentication", lambda _: None)
    monkeypatch.setattr(adapter, "OmniJobCapture", capture)
    monkeypatch.setattr(adapter, "committed_bundle_plan", lambda *_: object())
    monkeypatch.setattr(
        adapter,
        "verified_semantic_deployment_sha256",
        lambda *_: "b" * 64,
    )

    with pytest.raises(adapter.omni_probe.OmniProbeCliError, match="semantic.*drift"):
        adapter._capture_public_baseline_omni(
            plan, client_factory=lambda _: Client(), sleep=None
        )

    assert capture_started is False

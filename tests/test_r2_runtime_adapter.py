from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.r2_attempt_cli as attempt_cli
import omni_benchmark.r2_deployment_cli as deployment_cli
import omni_benchmark.r2_runtime_adapter as adapter
from omni_benchmark.artifact_store import StoredArtifact
from omni_benchmark.omni_capture import OmniProbeResult
from omni_benchmark.r2_execution import (
    R2AttemptArtifacts,
    R2ExecutionPlan,
    R2PlannedAttempt,
)
from omni_benchmark.r2_paired_schedule import (
    CONTROL_CONDITION,
    TREATMENT_CONDITION,
)


COMMIT = "a" * 40
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
RAW_ROOT = Path("experiments/autoresearch/raw/r2-runtime-fixture")


def _attempt(condition: str) -> R2PlannedAttempt:
    treatment = condition == TREATMENT_CONDITION
    arm = "r2-m1" if treatment else "r2-c5b"
    return R2PlannedAttempt(
        attempt_id=f"r2attempt-{arm}",
        attempt_position=2 if treatment else 1,
        condition=condition,
        database="sample_large",
        deployment_identity=f"livesqlbench-sample_large-{arm}-v1",
        deployment_run_id=f"{arm}-deployment-v1",
        instance_id="sample_1",
        output_root=RAW_ROOT / arm / "sample_large" / f"001-r2attempt-{arm}",
        pair_id="r2pair-sample",
        pair_position=1,
        repetition=1,
        run_id=f"{arm}-generation-v1",
        semantic_model_sha256=SHA_B if treatment else SHA_A,
        within_pair_position=2 if treatment else 1,
    )


def _plan() -> R2ExecutionPlan:
    return R2ExecutionPlan(
        attempts=(_attempt(CONTROL_CONDITION), _attempt(TREATMENT_CONDITION)),
        balanced_ai_settings_sha256=SHA_C,
        budget_policy_sha256=SHA_B,
        bundle_manifest_sha256=SHA_A,
        bundle_set_sha256=SHA_B,
        harness_config_sha256=SHA_A,
        instructions_sha256=SHA_C,
        output_root=RAW_ROOT,
        projected_arm_cost_usd={
            CONTROL_CONDITION: "1.00",
            TREATMENT_CONDITION: "1.00",
        },
        projected_total_cost_usd="2.00",
        prompt_sha256=SHA_B,
        schedule_sha256=SHA_C,
        system_commit=COMMIT,
    )


def _common_arguments() -> list[str]:
    return [
        "--workspace",
        str(Path(__file__).resolve().parents[1]),
        "--system-commit",
        COMMIT,
        "--output-root",
        RAW_ROOT.as_posix(),
        "--control-run-id",
        "r2-c5b-generation-v1",
        "--treatment-run-id",
        "r2-m1-generation-v1",
        "--control-deployment-run-id",
        "r2-c5b-deployment-v1",
        "--treatment-deployment-run-id",
        "r2-m1-deployment-v1",
        "--control-projected-attempt-cost-usd",
        "1.00",
        "--treatment-projected-attempt-cost-usd",
        "1.00",
        "--budget-policy-sha256",
        SHA_B,
    ]


def _probe(tmp_path: Path) -> OmniProbeResult:
    trace = StoredArtifact(tmp_path / "trace.jsonl", SHA_A, 12)
    shape = StoredArtifact(tmp_path / "shape.json", SHA_B, 10)
    return OmniProbeResult(
        terminal_state="COMPLETE",
        job_id="secret-job-id",
        generated_query='{"userEditedSQL":"SELECT ${sample.id}"}',
        job_result_observed=True,
        result_artifact=None,
        trace=trace,
        response_shape=shape,
        failure_class="no_answer_insufficient_context",
        latency_ms=12.5,
        started_at="2026-09-01T00:00:00+00:00",
        finished_at="2026-09-01T00:00:01+00:00",
        token_usage=None,
        validation_attempt_count=None,
        semantic_objects=("sample",),
        tool_call_count=1,
        tool_calls_by_name=(("query", 1),),
        database_query_count=1,
        model_provider="provider",
        model_name="model",
    )


def test_deployment_adapter_binds_exact_arm_plans_and_remote_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_semantic = object()
    monkeypatch.setattr(
        adapter,
        "semantic_deployment_sha256",
        lambda value: SHA_A if value is control_semantic else SHA_B,
    )

    prepared = adapter.prepare_r2_deployment_adapter(
        _plan(),
        condition=CONTROL_CONDITION,
        semantic_plans={"sample_large": control_semantic},
    )

    assert prepared.deployment_run_id == "r2-c5b-deployment-v1"
    assert prepared.output_root == Path("experiments/deployments/r2-c5b-deployment-v1")
    assert prepared.remote_identity("sample_large") == (
        "livesqlbench-sample_large-r2-c5b-v1",
        "livesqlbench-sample_large-r2-c5b-v1",
    )
    assert prepared.semantic_plans == {"sample_large": control_semantic}
    with pytest.raises(TypeError):
        prepared.semantic_plans["sample_large"] = object()  # type: ignore[index]
    with pytest.raises(TypeError):
        prepared.remote_identities["sample_large"] = "drift"  # type: ignore[index]
    encoded = json.dumps(prepared.public_dict(), sort_keys=True).lower()
    assert "question" not in encoded
    assert "query" not in encoded
    assert "credential" not in encoded
    assert prepared.public_dict()["live_execution"] == "not_started"


@pytest.mark.parametrize(
    ("condition", "plans", "digest", "message"),
    [
        ("C4", {"sample_large": object()}, SHA_A, "condition"),
        (CONTROL_CONDITION, {}, SHA_A, "coverage"),
        (CONTROL_CONDITION, {"sample_large": object()}, SHA_B, "semantic"),
    ],
)
def test_deployment_adapter_rejects_arm_coverage_and_semantic_drift(
    monkeypatch: pytest.MonkeyPatch,
    condition: str,
    plans: dict[str, object],
    digest: str,
    message: str,
) -> None:
    monkeypatch.setattr(adapter, "semantic_deployment_sha256", lambda _: digest)

    with pytest.raises(adapter.R2RuntimeAdapterError, match=message):
        adapter.prepare_r2_deployment_adapter(
            _plan(), condition=condition, semantic_plans=plans
        )


def test_attempt_adapter_requires_the_exact_verified_deployment_target() -> None:
    plan = _plan()
    attempt = plan.attempt("r2attempt-r2-m1")
    target = SimpleNamespace(
        branch_id="branch-generated-id",
        branch_name=attempt.deployment_identity,
        model_id="model-generated-id",
        model_name=attempt.deployment_identity,
        semantic_model_sha256=attempt.semantic_model_sha256,
    )

    prepared = adapter.prepare_r2_attempt_adapter(
        plan, attempt_id=attempt.attempt_id, deployment_target=target
    )

    assert prepared.attempt is attempt
    assert prepared.branch_id == "branch-generated-id"
    assert prepared.branch_name == attempt.deployment_identity
    assert prepared.model_id == "model-generated-id"
    assert prepared.model_name == attempt.deployment_identity
    assert prepared.public_dict()["execution_plan_sha256"] == plan.sha256
    assert "question" not in json.dumps(prepared.public_dict()).lower()

    with pytest.raises(adapter.R2RuntimeAdapterError, match="identity"):
        adapter.prepare_r2_attempt_adapter(
            plan,
            attempt_id=attempt.attempt_id,
            deployment_target=SimpleNamespace(
                branch_id="branch-generated-id",
                branch_name="wrong",
                model_id="model-generated-id",
                model_name=attempt.deployment_identity,
                semantic_model_sha256=attempt.semantic_model_sha256,
            ),
        )
    with pytest.raises(adapter.R2RuntimeAdapterError, match="semantic"):
        adapter.prepare_r2_attempt_adapter(
            plan,
            attempt_id=attempt.attempt_id,
            deployment_target=SimpleNamespace(
                branch_id="branch-generated-id",
                branch_name=attempt.deployment_identity,
                model_id="model-generated-id",
                model_name=attempt.deployment_identity,
                semantic_model_sha256=SHA_C,
            ),
        )


def test_committed_semantic_loader_uses_only_the_plan_commit_and_exact_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: dict[str, object] = {}
    semantic = object()
    monkeypatch.setattr(adapter.r2_execution, "_git_root", lambda _: tmp_path)
    monkeypatch.setattr(
        adapter.r2_execution,
        "_canonical_git_commit",
        lambda workspace, commit: commit,
    )
    monkeypatch.setattr(
        adapter.r2_execution,
        "_committed_archive",
        lambda workspace, commit: observed.update(commit=commit) or b"archive",
    )

    def extract(content: bytes, destination: Path) -> None:
        observed["archive"] = content
        root = (
            destination / adapter.r2_execution._BUNDLE_ROOT / "r2-c5b" / "sample_large"
        )
        root.mkdir(parents=True)

    def build(root: Path) -> object:
        observed["root"] = root
        return semantic

    monkeypatch.setattr(adapter.r2_execution, "_extract_committed_archive", extract)
    monkeypatch.setattr(adapter, "build_semantic_deployment_plan", build)
    monkeypatch.setattr(adapter, "semantic_deployment_sha256", lambda _: SHA_A)

    result = adapter.load_committed_r2_semantic_plans(
        tmp_path, plan=_plan(), condition=CONTROL_CONDITION
    )

    assert result == {"sample_large": semantic}
    assert observed["commit"] == COMMIT
    assert observed["archive"] == b"archive"
    assert Path(observed["root"]).parts[-2:] == (
        "r2-c5b",
        "sample_large",
    )


def test_generation_record_rebinds_c4_capture_to_the_frozen_r2_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = _plan().attempt("r2attempt-r2-c5b")
    monkeypatch.setattr(
        adapter.omni_attempt,
        "_attempt_record",
        lambda **_: {
            "attempt_id": "c4-identity",
            "condition": "C4",
            "cost_unavailable_reason": "job_api_does_not_report_cost",
            "cost_usd": None,
            "generation_outcome": "errored",
            "instance_id": attempt.instance_id,
            "latency_ms": 12.5,
            "partition": "dev-a",
            "repetition": 1,
            "run_id": "c4-run",
            "terminal_failure_class": "no_answer_insufficient_context",
        },
    )

    record = adapter.r2_generation_record(
        workspace=tmp_path,
        plan=_plan(),
        attempt_id=attempt.attempt_id,
        probe=_probe(tmp_path),
        probe_plan=SimpleNamespace(
            arguments=SimpleNamespace(budget_id="budget"),
            specs=SimpleNamespace(
                condition=SimpleNamespace(
                    provider="provider",
                    managed_llm_identity="model",
                    model_config_id="model-config",
                )
            ),
            question="Public question",
            semantic_model_ref=attempt.deployment_identity,
            software_versions={"package": "1"},
            cli_versions={"omni": "1"},
        ),
    )

    assert record["attempt_id"] == attempt.attempt_id
    assert record["condition"] == CONTROL_CONDITION
    assert record["database"] == "sample_large"
    assert record["run_id"] == attempt.run_id
    assert record["instance_id"] == attempt.instance_id


def test_attempt_receipt_contains_hashes_but_no_question_query_or_result_values(
    tmp_path: Path,
) -> None:
    attempt = _plan().attempt("r2attempt-r2-c5b")
    artifacts = R2AttemptArtifacts(
        generation_path=tmp_path / "generation.jsonl",
        generation_sha256=SHA_A,
        manifest_path=tmp_path / "run.json",
        manifest_sha256=SHA_B,
    )
    receipt = adapter.r2_attempt_receipt(
        workspace=tmp_path,
        plan=_plan(),
        attempt_id=attempt.attempt_id,
        artifacts=artifacts,
        probe=_probe(tmp_path),
    )

    assert receipt["attempt_id"] == attempt.attempt_id
    assert receipt["job_id_sha256"] == hashlib.sha256(b"secret-job-id").hexdigest()
    encoded = json.dumps(receipt, sort_keys=True).lower()
    assert "secret-job-id" not in encoded
    assert "question" not in encoded
    assert "generated_query" not in encoded
    assert "usereditedsql" not in encoded
    assert "actual_result" not in encoded


def test_probe_plan_must_match_the_exact_attempt_and_committed_specs() -> None:
    plan = _plan()
    attempt = plan.attempt("r2attempt-r2-c5b")
    probe_plan = SimpleNamespace(
        arguments=SimpleNamespace(
            instance_id=attempt.instance_id,
            output_root=attempt.output_root,
            repetition=attempt.repetition,
            run_id=attempt.run_id,
            system_commit=plan.system_commit,
        ),
        specs=SimpleNamespace(
            condition_sha256=plan.harness_config_sha256,
            instructions_sha256=plan.instructions_sha256,
            prompt_sha256=plan.prompt_sha256,
        ),
    )

    adapter.validate_r2_probe_plan(
        plan, attempt_id=attempt.attempt_id, probe_plan=probe_plan
    )

    probe_plan.arguments.run_id = "wrong-run"
    with pytest.raises(adapter.R2RuntimeAdapterError, match="probe identity"):
        adapter.validate_r2_probe_plan(
            plan, attempt_id=attempt.attempt_id, probe_plan=probe_plan
        )
    probe_plan.arguments.run_id = attempt.run_id
    probe_plan.specs.prompt_sha256 = SHA_C
    with pytest.raises(adapter.R2RuntimeAdapterError, match="specification"):
        adapter.validate_r2_probe_plan(
            plan, attempt_id=attempt.attempt_id, probe_plan=probe_plan
        )


def test_execute_attempt_requires_exact_readback_before_capture_and_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    attempt = plan.attempt("r2attempt-r2-c5b")
    result = _probe(tmp_path)
    artifacts = R2AttemptArtifacts(
        generation_path=tmp_path / "generation.jsonl",
        generation_sha256=SHA_A,
        manifest_path=tmp_path / "run.json",
        manifest_sha256=SHA_B,
    )
    order: list[str] = []
    semantic = object()
    probe_plan = SimpleNamespace(
        workspace=tmp_path,
        settings=SimpleNamespace(
            model_id=attempt.deployment_identity,
            branch_id=attempt.deployment_identity,
        ),
        environment={},
        store=object(),
        question="Public question",
        arguments=SimpleNamespace(
            instance_id=attempt.instance_id,
            output_root=attempt.output_root,
            repetition=attempt.repetition,
            run_id=attempt.run_id,
            system_commit=plan.system_commit,
        ),
        specs=SimpleNamespace(
            condition_sha256=plan.harness_config_sha256,
            instructions_sha256=plan.instructions_sha256,
            prompt_sha256=plan.prompt_sha256,
            condition=SimpleNamespace(
                maximum_status_checks=2,
                poll_schedule_seconds=(0.0,),
            ),
        ),
    )
    monkeypatch.setattr(
        attempt_cli.omni_probe, "_prepare_probe", lambda *args: probe_plan
    )
    monkeypatch.setattr(
        attempt_cli,
        "load_committed_r2_semantic_plans",
        lambda *_, **__: {attempt.database: semantic},
    )

    class Client:
        def whoami(self) -> dict[str, str]:
            order.append("authentication")
            return {"id": "fixture"}

        def read_semantic_model(self) -> dict[str, str]:
            order.append("readback")
            return {"model": "fixture"}

    def verify(plan_value: object, readback: object) -> str:
        assert plan_value is semantic
        assert readback == {"model": "fixture"}
        order.append("verify")
        return attempt.semantic_model_sha256

    class Capture:
        def __init__(self, *args: object, **kwargs: object) -> None:
            order.append("capture_constructed")

        def probe(self, question: str) -> OmniProbeResult:
            assert question == "Public question"
            order.append("capture")
            return result

    monkeypatch.setattr(attempt_cli, "verified_semantic_deployment_sha256", verify)
    monkeypatch.setattr(attempt_cli, "OmniJobCapture", Capture)
    monkeypatch.setattr(
        attempt_cli,
        "capture_with_cost",
        lambda **kwargs: kwargs["capture"](),
    )
    monkeypatch.setattr(
        attempt_cli,
        "r2_generation_record",
        lambda **_: order.append("record") or {"record": True},
    )
    monkeypatch.setattr(
        attempt_cli,
        "write_r2_attempt_artifacts",
        lambda *_, **__: order.append("publish") or artifacts,
    )

    actual = attempt_cli.execute_r2_attempt(
        plan=plan,
        attempt_id=attempt.attempt_id,
        deployment_target=SimpleNamespace(
            branch_id=attempt.deployment_identity,
            branch_name=attempt.deployment_identity,
            model_id=attempt.deployment_identity,
            model_name=attempt.deployment_identity,
            semantic_model_sha256=attempt.semantic_model_sha256,
        ),
        probe_arguments=SimpleNamespace(),
        environment={},
        client_factory=lambda _: Client(),
        sleep=lambda _: None,
        cli_version_observer=None,
    )

    assert actual == (artifacts, result)
    assert order == [
        "authentication",
        "readback",
        "verify",
        "capture_constructed",
        "capture",
        "record",
        "publish",
    ]


def test_execute_attempt_stops_before_capture_on_runtime_readback_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    attempt = plan.attempt("r2attempt-r2-c5b")
    probe_plan = SimpleNamespace(
        workspace=tmp_path,
        settings=SimpleNamespace(
            model_id=attempt.deployment_identity,
            branch_id=attempt.deployment_identity,
        ),
        environment={},
        store=object(),
        question="Public question",
        arguments=SimpleNamespace(
            instance_id=attempt.instance_id,
            output_root=attempt.output_root,
            repetition=attempt.repetition,
            run_id=attempt.run_id,
            system_commit=plan.system_commit,
        ),
        specs=SimpleNamespace(
            condition_sha256=plan.harness_config_sha256,
            instructions_sha256=plan.instructions_sha256,
            prompt_sha256=plan.prompt_sha256,
            condition=SimpleNamespace(
                maximum_status_checks=2,
                poll_schedule_seconds=(0.0,),
            ),
        ),
    )
    monkeypatch.setattr(
        attempt_cli.omni_probe, "_prepare_probe", lambda *args: probe_plan
    )
    monkeypatch.setattr(
        attempt_cli,
        "load_committed_r2_semantic_plans",
        lambda *_, **__: {attempt.database: object()},
    )

    class Client:
        def whoami(self) -> dict[str, str]:
            return {"id": "fixture"}

        def read_semantic_model(self) -> dict[str, str]:
            return {"model": "drift"}

    monkeypatch.setattr(
        attempt_cli, "verified_semantic_deployment_sha256", lambda *_: SHA_C
    )
    monkeypatch.setattr(
        attempt_cli,
        "OmniJobCapture",
        lambda *_args, **_kwargs: pytest.fail("capture must not start"),
    )

    with pytest.raises(adapter.R2RuntimeAdapterError, match="drifted"):
        attempt_cli.execute_r2_attempt(
            plan=plan,
            attempt_id=attempt.attempt_id,
            deployment_target=SimpleNamespace(
                branch_id=attempt.deployment_identity,
                branch_name=attempt.deployment_identity,
                model_id=attempt.deployment_identity,
                model_name=attempt.deployment_identity,
                semantic_model_sha256=attempt.semantic_model_sha256,
            ),
            probe_arguments=SimpleNamespace(),
            environment={},
            client_factory=lambda _: Client(),
            sleep=None,
            cli_version_observer=None,
        )


def test_deployment_cli_is_dry_default_and_live_delegation_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = Path(__file__).resolve().parents[1]
    semantic = object()
    prepared = SimpleNamespace(
        condition=CONTROL_CONDITION,
        deployment_run_id="r2-c5b-deployment-v1",
        output_root=Path("experiments/deployments/r2-c5b-deployment-v1"),
        semantic_plans={"sample_large": semantic},
        remote_identity=lambda database: (
            f"identity-{database}",
            f"identity-{database}",
        ),
        public_dict=lambda: {"live_execution": "not_started"},
    )
    monkeypatch.setattr(deployment_cli, "_load_execution_plan", lambda _: _plan())
    monkeypatch.setattr(
        deployment_cli,
        "load_committed_r2_semantic_plans",
        lambda *_, **__: {"sample_large": semantic},
    )
    monkeypatch.setattr(
        deployment_cli, "prepare_r2_deployment_adapter", lambda *_, **__: prepared
    )

    assert (
        deployment_cli.r2_deployment_main(
            [*_common_arguments(), "--condition", CONTROL_CONDITION]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"live_execution": "not_started"}

    observed: dict[str, object] = {}

    def deploy(argv: list[str], **kwargs: object) -> int:
        observed["argv"] = argv
        plans, failures = kwargs["bundle_loader"](workspace, COMMIT)
        observed["plans"] = plans
        assert failures == {}
        observed["identity"] = kwargs["identity_factory"]("sample_large")
        return 0

    destination = workspace / prepared.output_root
    monkeypatch.setattr(deployment_cli.Path, "exists", lambda path: False)
    assert (
        deployment_cli.r2_deployment_main(
            [
                *_common_arguments(),
                "--condition",
                CONTROL_CONDITION,
                "--profile",
                "fixture",
                "--execute-live-deployment",
            ],
            deployment_runner=deploy,
        )
        == 0
    )
    assert observed["plans"] == {"sample_large": semantic}
    assert observed["identity"] == (
        "identity-sample_large",
        "identity-sample_large",
    )
    assert str(destination) in observed["argv"]


def test_deployment_cli_requires_profile_and_entrypoint_sanitizes_unexpected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    semantic = object()
    prepared = SimpleNamespace(
        output_root=Path("experiments/deployments/r2-c5b-deployment-v1"),
        public_dict=lambda: {},
    )
    monkeypatch.setattr(deployment_cli, "_load_execution_plan", lambda _: _plan())
    monkeypatch.setattr(
        deployment_cli,
        "load_committed_r2_semantic_plans",
        lambda *_, **__: {"sample_large": semantic},
    )
    monkeypatch.setattr(
        deployment_cli, "prepare_r2_deployment_adapter", lambda *_, **__: prepared
    )
    monkeypatch.setattr(deployment_cli.Path, "exists", lambda path: False)

    with pytest.raises(adapter.R2RuntimeAdapterError, match="profile"):
        deployment_cli.r2_deployment_main(
            [
                *_common_arguments(),
                "--condition",
                CONTROL_CONDITION,
                "--execute-live-deployment",
            ]
        )

    monkeypatch.setattr(
        deployment_cli,
        "r2_deployment_main",
        lambda: (_ for _ in ()).throw(RuntimeError("Bearer provider-secret")),
    )
    assert deployment_cli.r2_deployment_entrypoint() == 1
    error = capsys.readouterr().err
    assert "provider-secret" not in error
    assert "internal error" in error


def test_attempt_cli_dry_plan_never_constructs_a_product_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    attempt = _plan().attempt("r2attempt-r2-m1")
    monkeypatch.setattr(attempt_cli, "_load_execution_plan", lambda _: _plan())
    monkeypatch.setattr(
        attempt_cli,
        "prepare_r2_attempt_dry_plan",
        lambda plan, attempt_id: SimpleNamespace(
            public_dict=lambda: {
                "attempt_id": attempt_id,
                "live_execution": "not_started",
            }
        ),
    )

    result = attempt_cli.r2_attempt_main(
        [
            *_common_arguments(),
            "--attempt-id",
            attempt.attempt_id,
            "--dry-run-attempt",
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "attempt_id": attempt.attempt_id,
        "live_execution": "not_started",
    }


def test_attempt_cli_exposes_no_live_or_receipt_bypass() -> None:
    cli = Path("src/omni_benchmark/r2_attempt_cli.py").read_text(encoding="utf-8")
    script = Path("scripts/r2_attempt.py").read_text(encoding="utf-8")

    for content in (cli, script):
        assert "--execute-authenticated-smoke" not in content
        assert "--execute-live" not in content
        assert "verify_deployment_gate" not in content
        assert "consume_" not in content
    assert "--dry-run-attempt" in cli


def test_attempt_entrypoint_sanitizes_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        attempt_cli,
        "r2_attempt_main",
        lambda: (_ for _ in ()).throw(RuntimeError("Bearer provider-secret")),
    )

    assert attempt_cli.r2_attempt_entrypoint() == 1
    error = capsys.readouterr().err
    assert "provider-secret" not in error
    assert "internal error" in error

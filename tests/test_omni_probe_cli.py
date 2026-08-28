from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.omni_cli import OmniCliSettings
from omni_benchmark.omni_probe_cli import OmniProbeCliError, probe_main
from omni_benchmark.autoresearch import load_config, validate_generation_outputs


class FakeClient:
    def __init__(self, settings: OmniCliSettings) -> None:
        self.settings = settings
        self.statuses = iter(({"state": "EXECUTING"}, {"state": "COMPLETE"}))

    def whoami(self) -> dict[str, Any]:
        return {"authenticated": True, "email": "operator@example.com"}

    def submit_job(self, question: str) -> dict[str, Any]:
        assert question == "How many public rows?"
        return {"jobId": "job-private-1"}

    def job_status(self, job_id: str) -> dict[str, Any]:
        assert job_id == "job-private-1"
        return next(self.statuses)

    def job_result(self, job_id: str) -> dict[str, Any]:
        assert job_id == "job-private-1"
        return {
            "actions": [
                {
                    "message": "I generated the governed query.",
                    "result": {
                        "csvResult": "answer\n42\n",
                        "csvResultWasTruncated": False,
                        "hasResults": True,
                        "query": {"fields": ["answers.value"]},
                        "queryName": "Answer",
                        "resultId": "private-result-id",
                        "status": "success",
                        "totalRowCount": 1,
                    },
                    "timestamp": "2026-08-27T12:00:01Z",
                    "type": "generate_query",
                }
            ]
        }

    def run_query_json(self, query: dict[str, Any]) -> list[dict[str, Any]]:
        assert query == {"fields": ["answers.value"]}
        return [{"answer": 42}]

    def plan_query(self, query: dict[str, Any]) -> dict[str, Any]:
        assert query == {"fields": ["answers.value"]}
        return {
            "query": {"model_job": {"fields": ["answers.value"]}},
            "status": "PLANNED",
            "summary": {
                "fields": {
                    "answers.value": {
                        "data_type": "NUMBER",
                        "fully_qualified_name": "answers.value",
                    }
                },
                "invalid_calculations": {},
                "missing_fields": [],
            },
        }


class FailedClient(FakeClient):
    def __init__(self, settings: OmniCliSettings) -> None:
        super().__init__(settings)
        self.statuses = iter(({"state": "FAILED"},))

    def job_result(self, job_id: str) -> dict[str, Any]:
        raise AssertionError("failed jobs must not fetch a result")


class CancelledClient(FailedClient):
    def __init__(self, settings: OmniCliSettings) -> None:
        super().__init__(settings)
        self.statuses = iter(({"state": "CANCELLED"},))


class StatusTransportClient(FakeClient):
    def job_status(self, job_id: str) -> dict[str, Any]:
        assert job_id == "job-private-1"
        raise RuntimeError("observer transport unavailable")

    def job_result(self, job_id: str) -> dict[str, Any]:
        raise AssertionError("transport failures must not fetch a result")


class NeverCompleteClient(FakeClient):
    def job_status(self, job_id: str) -> dict[str, Any]:
        assert job_id == "job-private-1"
        return {"state": "EXECUTING"}

    def job_result(self, job_id: str) -> dict[str, Any]:
        raise AssertionError("non-terminal jobs must not fetch a result")


class TruncatedMetricsClient(FakeClient):
    def __init__(self, settings: OmniCliSettings) -> None:
        super().__init__(settings)
        self.statuses = iter(({"state": "COMPLETE"},))

    def job_result(self, job_id: str) -> dict[str, Any]:
        response = super().job_result(job_id)
        response["actions"][0]["result"]["csvResultWasTruncated"] = True
        response["metrics"] = {
            "durationMs": 23_911,
            "llmMs": 22_427,
            "queryCount": 1,
            "queryDurationMs": 2_030,
            "tokenBuckets": {
                "default": {
                    "tokensByModel": {
                        "claude-opus-5": {
                            "modelProvider": "bedrock",
                            "tokens": {
                                "cacheReadTokens": 161_357,
                                "cacheWriteTokens": 86_137,
                                "inputTokens": 6,
                                "outputTokens": 1_083,
                            },
                        }
                    }
                }
            },
            "toolBreakdown": {
                "generate_query": {"calls": 1, "errors": 0, "totalMs": 2_625},
                "search_model": {"calls": 2, "errors": 0, "totalMs": 128},
            },
            "toolCallCount": 3,
            "toolErrorCount": 0,
        }
        return response


def _workspace(tmp_path: Path, *, guardian_pin: str = "a" * 64) -> tuple[Path, str]:
    workspace = tmp_path / "workspace"
    binary = workspace / "bin" / "omni"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nprintf 'omni version 1.1.2\\n'\n", encoding="utf-8")
    binary.chmod(0o700)
    binary_sha256 = hashlib.sha256(binary.read_bytes()).hexdigest()
    manifests = workspace / "data" / "manifests"
    manifests.mkdir(parents=True)
    (workspace / ".gitignore").write_text(
        "experiments/autoresearch/raw/\n", encoding="utf-8"
    )
    records = [
        {
            "instance_id": instance_id,
            "query": question,
            "selected_database": "db-1",
        }
        for instance_id, question in (
            ("public-1", "How many public rows?"),
            ("dev-b-1", "Public checkpoint question"),
            ("test-1", "Public sealed question"),
        )
    ]
    (manifests / "eligible_questions.jsonl").write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    (manifests / "train_ids.txt").write_text("public-1\ndev-b-1\n", encoding="utf-8")
    (manifests / "dev_a_ids.txt").write_text("public-1\n", encoding="utf-8")
    (manifests / "dev_b_ids.txt").write_text("dev-b-1\n", encoding="utf-8")
    (manifests / "test_ids.txt").write_text("test-1\n", encoding="utf-8")
    for name in (
        "manifest_metadata.json",
        "split_metadata.json",
        "development_split_metadata.json",
    ):
        (manifests / name).write_text('{"fixture":true}\n', encoding="utf-8")
    config = workspace / "config" / "autoresearch.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps(
            {
                "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
                "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
                "dev_b_max_evaluations": 2,
                "expected_dev_a_count": 1,
                "expected_dev_b_count": 1,
                "expected_train_count": 2,
                "forbidden_fields": ["gold_sql", "external_knowledge"],
                "guardian_public_key_sha256": guardian_pin,
                "ledger_path": "experiments/autoresearch/ledger.jsonl",
                "public_manifest_path": "data/manifests/eligible_questions.jsonl",
                "state_dir": "experiments/autoresearch/state",
                "test_ids_path": "data/manifests/test_ids.txt",
                "train_ids_path": "data/manifests/train_ids.txt",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    conditions = workspace / "config" / "conditions"
    prompts = workspace / "config" / "prompts"
    instructions = workspace / "config" / "instructions"
    conditions.mkdir()
    prompts.mkdir()
    instructions.mkdir()
    (conditions / "c4-production-v1.json").write_text(
        json.dumps(
            {
                "condition": "C4",
                "execution": "omni_production_agent_job_api",
                "knowledge": "public_schema_and_hkb_encoded_in_omni_semantic_model",
                "managed_llm_identity": "managed-unobservable",
                "maximum_status_checks": 60,
                "model_config_id": "c4-production-v1",
                "omni_cli_sha256": binary_sha256,
                "omni_cli_version": "1.1.2",
                "poll_schedule_seconds": [2.0, 5.0, 10.0],
                "production_retry_policy": "managed_unobservable",
                "provider": "omni-production",
                "result_selection": "last_successful_generate_query_action",
                "semantic_enforcement": "governed",
                "typed_result_cache": "disabled",
                "typed_result_formatting": False,
                "typed_result_type": "json",
                "truncated_result_policy": "evaluated_system_error",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (prompts / "c4-user-prompt-v1.txt").write_text("{question}\n", encoding="utf-8")
    (instructions / "c4-managed-instructions-v1.json").write_text(
        json.dumps(
            {
                "adapter_instruction": (
                    "Submit the public benchmark question unchanged through Omni's "
                    "production agent job API."
                ),
                "managed_agent_instructions": "not_exposed_by_omni",
                "question_specific_hidden_annotations": False,
                "runtime_oracle_context": False,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    scripts = workspace / "scripts"
    scripts.mkdir()
    (scripts / "probe_entrypoint.py").write_text(
        "ENTRYPOINT = True\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.com"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "test: freeze protocol"],
        cwd=workspace,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return workspace, commit


def _environment(workspace: Path) -> dict[str, str]:
    return {
        "OMNI_API_TOKEN": "provider-live-secret",
        "OMNI_BASE_URL": "https://example.omniapp.co",
        "OMNI_MODEL_ID": "model-1",
        "OMNI_BRANCH_ID": "branch-1",
        "PATH": f"{workspace / 'bin'}:/usr/bin",
    }


def _observe_cli_version(settings: OmniCliSettings, environment: dict[str, str]) -> str:
    assert Path(settings.binary).name == "omni"
    assert Path(settings.binary).is_absolute()
    assert environment["PATH"].endswith(":/usr/bin")
    return "1.1.2"


def _probe_arguments(
    workspace: Path, freeze_a_commit: str, *, instance_id: str = "public-1"
) -> list[str]:
    return [
        "--workspace",
        str(workspace),
        "--config",
        str(workspace / "config" / "autoresearch.json"),
        "--freeze-a-commit",
        freeze_a_commit,
        "--system-commit",
        freeze_a_commit,
        "--instance-id",
        instance_id,
        "--output-root",
        "experiments/autoresearch/raw/c4-contract-probe",
        "--run-id",
        "c4-contract-probe",
        "--harness-config",
        "config/conditions/c4-production-v1.json",
        "--prompt-spec",
        "config/prompts/c4-user-prompt-v1.txt",
        "--instructions-spec",
        "config/instructions/c4-managed-instructions-v1.json",
        "--budget-id",
        "c4-smoke",
        "--execute-authenticated-smoke",
    ]


def test_probe_uses_only_public_dev_a_question_and_emits_safe_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)

    status = probe_main(
        _probe_arguments(workspace, freeze_a_commit),
        environment=_environment(workspace),
        client_factory=FakeClient,
        sleep=lambda _: None,
        cli_version_observer=_observe_cli_version,
    )

    assert status == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["instance_id"] == "public-1"
    assert receipt["terminal_state"] == "COMPLETE"
    assert receipt["job_id_sha256"] == hashlib.sha256(b"job-private-1").hexdigest()
    assert "job-private-1" not in json.dumps(receipt)
    assert receipt["generation"]["path"].endswith("generation.jsonl")
    assert receipt["run_manifest"]["path"].endswith("run.json")
    root = workspace / "experiments" / "autoresearch" / "raw" / "c4-contract-probe"
    persisted = "".join(path.read_text() for path in root.iterdir())
    assert "provider-live-secret" not in persisted
    assert "operator@example.com" not in persisted
    assert "private-result-id" not in persisted
    generation = json.loads((root / "generation.jsonl").read_text())
    assert generation["attempt_id"] == "c4-contract-probe:public-1:C4:1"
    assert generation["condition"] == "C4"
    assert generation["generation_outcome"] == "answered"
    assert "outcome" not in generation
    assert generation["database_query_count"] == 1
    assert generation["tool_call_count"] is None
    assert generation["validation_attempt_count"] is None
    assert "tool_call_count" in generation["telemetry_unavailable"]
    assert "validation_attempt_count" in generation["telemetry_unavailable"]
    assert generation["trace_captured"] is True
    assert generation["result_artifact_sha256"] == generation["actual_result_hash"]
    manifest = json.loads((root / "run.json").read_text())
    assert manifest["generation_sha256"] == receipt["generation"]["sha256"]
    assert manifest["git_commit"] == freeze_a_commit
    assert manifest["condition"] == "C4"
    assert manifest["provider"] == "omni-production"
    assert manifest["model"] == "managed-unobservable"
    assert manifest["semantic_model_ref"] == "branch:branch-1"
    binary_sha256 = hashlib.sha256(
        (workspace / "bin" / "omni").read_bytes()
    ).hexdigest()
    assert manifest["cli_versions"] == {
        "omni": "1.1.2",
        "omni.sha256": binary_sha256,
    }
    config = load_config(
        workspace / "config" / "autoresearch.json",
        workspace=workspace,
        freeze_a_commit=freeze_a_commit,
    )
    validated = validate_generation_outputs(
        config,
        Path(receipt["generation"]["path"]),
        scope="dev-a",
        manifest_path=Path(receipt["run_manifest"]["path"]),
        expected_manifest_sha256=receipt["run_manifest"]["sha256"],
    )
    assert validated.question_count == 1
    assert validated.run_manifest_sha256 == receipt["run_manifest"]["sha256"]


def test_probe_rejects_non_dev_a_id_before_constructing_client(tmp_path: Path) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    constructed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    with pytest.raises(OmniProbeCliError, match="dev-A"):
        probe_main(
            _probe_arguments(workspace, freeze_a_commit, instance_id="sealed-test-id"),
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=_observe_cli_version,
        )

    assert constructed is False


def test_probe_rejects_invalid_run_metadata_before_constructing_client(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    arguments = _probe_arguments(workspace, freeze_a_commit)
    arguments[arguments.index("--budget-id") + 1] = "unsafe budget value"
    constructed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    with pytest.raises(OmniProbeCliError, match="run metadata"):
        probe_main(
            arguments,
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=_observe_cli_version,
        )

    assert constructed is False


def test_probe_persists_a_complete_unscored_error_attempt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)

    status = probe_main(
        _probe_arguments(workspace, freeze_a_commit),
        environment=_environment(workspace),
        client_factory=FailedClient,
        sleep=lambda _: None,
        cli_version_observer=_observe_cli_version,
    )

    assert status == 0
    receipt = json.loads(capsys.readouterr().out)
    generation_path = workspace / receipt["generation"]["path"]
    record = json.loads(generation_path.read_text())
    assert record["generation_outcome"] == "errored"
    assert record["failure_origin"] == "evaluated_system"
    assert record["harness_failure"] is None
    assert record["terminal_failure_class"] == "omni_job_terminal_failure"
    assert record["database_query_count"] is None
    assert record["tool_call_count"] is None
    assert record["validation_attempt_count"] is None
    assert "actual_result_hash" not in record
    assert "outcome" not in record
    config = load_config(
        workspace / "config" / "autoresearch.json",
        workspace=workspace,
        freeze_a_commit=freeze_a_commit,
    )
    assert (
        validate_generation_outputs(
            config,
            Path(receipt["generation"]["path"]),
            scope="dev-a",
            manifest_path=Path(receipt["run_manifest"]["path"]),
            expected_manifest_sha256=receipt["run_manifest"]["sha256"],
        ).question_count
        == 1
    )


def test_probe_persists_status_transport_as_benchmark_infrastructure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)

    status = probe_main(
        _probe_arguments(workspace, freeze_a_commit),
        environment=_environment(workspace),
        client_factory=StatusTransportClient,
        sleep=lambda _: None,
        cli_version_observer=_observe_cli_version,
    )

    assert status == 0
    receipt = json.loads(capsys.readouterr().out)
    generation_path = workspace / receipt["generation"]["path"]
    record = json.loads(generation_path.read_text())
    assert record["generation_outcome"] == "errored"
    assert record["failure_origin"] == "benchmark_infrastructure"
    assert record["harness_failure"] == "adapter_transport_error"
    assert record["terminal_failure_class"] == "adapter_transport_error"
    config = load_config(
        workspace / "config" / "autoresearch.json",
        workspace=workspace,
        freeze_a_commit=freeze_a_commit,
    )
    assert (
        validate_generation_outputs(
            config,
            Path(receipt["generation"]["path"]),
            scope="dev-a",
            manifest_path=Path(receipt["run_manifest"]["path"]),
            expected_manifest_sha256=receipt["run_manifest"]["sha256"],
        ).question_count
        == 1
    )


def test_probe_records_supported_cancelled_state_as_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)

    assert (
        probe_main(
            _probe_arguments(workspace, freeze_a_commit),
            environment=_environment(workspace),
            client_factory=CancelledClient,
            sleep=lambda _: None,
            cli_version_observer=_observe_cli_version,
        )
        == 0
    )

    receipt = json.loads(capsys.readouterr().out)
    record = json.loads((workspace / receipt["generation"]["path"]).read_text())
    assert record["generation_outcome"] == "errored"
    assert record["generation_outcome"] != "refused"
    assert record["terminal_failure_class"] == "omni_job_terminal_failure"
    trace = [
        json.loads(line)
        for line in (workspace / record["trace_path"]).read_text().splitlines()
    ]
    assert any(event["status"] == "CANCELLED" for event in trace)
    assert trace[-1]["failure_class"] == "omni_job_terminal_failure"


def test_probe_persists_live_metrics_and_recovers_truncated_preview_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)

    status = probe_main(
        _probe_arguments(workspace, freeze_a_commit),
        environment=_environment(workspace),
        client_factory=TruncatedMetricsClient,
        sleep=lambda _: None,
        cli_version_observer=_observe_cli_version,
    )

    assert status == 0
    receipt = json.loads(capsys.readouterr().out)
    record = json.loads((workspace / receipt["generation"]["path"]).read_text())
    assert record["generation_outcome"] == "answered"
    assert record["terminal_failure_class"] is None
    assert record["result_artifact_path"] is not None
    assert record["model"] == {
        "name": "claude-opus-5",
        "provider": "bedrock",
        "version": None,
    }
    assert record["token_source"] == "provider_reported"
    assert record["token_usage"] == {
        "input_tokens": 247_500,
        "output_tokens": 1_083,
        "total_tokens": 248_583,
    }
    assert record["tool_call_count"] == 3
    assert record["tool_calls_by_name"] == [
        {"count": 1, "name": "generate_query"},
        {"count": 2, "name": "search_model"},
    ]
    assert record["database_query_count"] == 1
    assert record["telemetry_unavailable"] == [
        "model_version",
        "retry_count",
        "validation_attempt_count",
    ]
    config = load_config(
        workspace / "config" / "autoresearch.json",
        workspace=workspace,
        freeze_a_commit=freeze_a_commit,
    )
    assert (
        validate_generation_outputs(
            config,
            Path(receipt["generation"]["path"]),
            scope="dev-a",
            manifest_path=Path(receipt["run_manifest"]["path"]),
            expected_manifest_sha256=receipt["run_manifest"]["sha256"],
        ).question_count
        == 1
    )


def test_probe_requires_explicit_execution_acknowledgement(tmp_path: Path) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)

    with pytest.raises(OmniProbeCliError, match="explicit acknowledgement"):
        probe_main(
            [
                argument
                for argument in _probe_arguments(workspace, freeze_a_commit)
                if argument != "--execute-authenticated-smoke"
            ],
            environment=_environment(workspace),
            client_factory=FakeClient,
            cli_version_observer=_observe_cli_version,
        )


def test_probe_rejects_manifest_mutation_after_freeze_before_client(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    manifests = workspace / "data" / "manifests"
    (manifests / "dev_a_ids.txt").write_text(
        "synthetic-unauthorized-id\n", encoding="utf-8"
    )
    (manifests / "train_ids.txt").write_text(
        "synthetic-unauthorized-id\ndev-b-1\n", encoding="utf-8"
    )
    manifest = (manifests / "eligible_questions.jsonl").read_text(encoding="utf-8")
    (manifests / "eligible_questions.jsonl").write_text(
        manifest.replace("public-1", "synthetic-unauthorized-id").replace(
            "How many public rows?", "Synthetic unauthorized question"
        ),
        encoding="utf-8",
    )
    constructed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    with pytest.raises(OmniProbeCliError, match="Freeze-A"):
        probe_main(
            _probe_arguments(
                workspace,
                freeze_a_commit,
                instance_id="synthetic-unauthorized-id",
            ),
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=_observe_cli_version,
        )

    assert constructed is False


def test_probe_rejects_committed_unprovisioned_guardian_before_client(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path, guardian_pin="UNPROVISIONED")
    constructed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    with pytest.raises(OmniProbeCliError, match="guardian key.*provisioned"):
        probe_main(
            _probe_arguments(workspace, freeze_a_commit),
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=_observe_cli_version,
        )

    assert constructed is False


def test_probe_rejects_existing_output_root_before_constructing_client(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    output_root = (
        workspace / "experiments" / "autoresearch" / "raw" / "c4-contract-probe"
    )
    output_root.mkdir(parents=True)
    (output_root / "answer.result.json").write_text("occupied\n", encoding="utf-8")
    constructed = False
    version_observed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    def observe_version(
        settings: OmniCliSettings, environment: Mapping[str, str]
    ) -> str:
        nonlocal version_observed
        version_observed = True
        return _observe_cli_version(settings, environment)

    with pytest.raises(OmniProbeCliError, match="must not already exist"):
        probe_main(
            _probe_arguments(workspace, freeze_a_commit),
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=observe_version,
        )

    assert constructed is False
    assert version_observed is False


def test_probe_rejects_secret_run_id_before_local_or_authenticated_calls(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    arguments = _probe_arguments(workspace, freeze_a_commit)
    arguments[arguments.index("--run-id") + 1] = "provider-live-secret"
    constructed = False
    version_observed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    def observe_version(
        settings: OmniCliSettings, environment: Mapping[str, str]
    ) -> str:
        nonlocal version_observed
        version_observed = True
        return _observe_cli_version(settings, environment)

    with pytest.raises(OmniProbeCliError, match="run identity"):
        probe_main(
            arguments,
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=observe_version,
        )

    assert constructed is False
    assert version_observed is False
    assert not (
        workspace / "experiments" / "autoresearch" / "raw" / "c4-contract-probe"
    ).exists()


def test_probe_rejects_credential_shaped_public_question_before_local_calls(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    environment = _environment(workspace)
    environment["OMNI_API_TOKEN"] = "How many public rows?"
    constructed = False
    version_observed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    def observe_version(
        settings: OmniCliSettings, environment: Mapping[str, str]
    ) -> str:
        nonlocal version_observed
        version_observed = True
        return "1.1.2"

    with pytest.raises(OmniProbeCliError, match="question contains credential"):
        probe_main(
            _probe_arguments(workspace, freeze_a_commit),
            environment=environment,
            client_factory=factory,
            cli_version_observer=observe_version,
        )

    assert constructed is False
    assert version_observed is False
    assert not (
        workspace / "experiments" / "autoresearch" / "raw" / "c4-contract-probe"
    ).exists()


def test_probe_rejects_same_version_cli_with_unpinned_bytes_before_auth(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    wrapper = tmp_path / "wrapper" / "omni"
    wrapper.parent.mkdir()
    wrapper.write_text(
        "#!/bin/sh\n# unpinned wrapper\nprintf 'omni version 1.1.2\\n'\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o700)
    environment = _environment(workspace)
    environment["PATH"] = f"{wrapper.parent}:/usr/bin"
    constructed = False
    version_observed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    def observe_version(
        settings: OmniCliSettings, environment: Mapping[str, str]
    ) -> str:
        nonlocal version_observed
        version_observed = True
        return "1.1.2"

    with pytest.raises(OmniProbeCliError, match="CLI binary SHA-256"):
        probe_main(
            _probe_arguments(workspace, freeze_a_commit),
            environment=environment,
            client_factory=factory,
            cli_version_observer=observe_version,
        )

    assert constructed is False
    assert version_observed is False


def test_probe_rejects_unexpected_cli_version_before_auth(tmp_path: Path) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    constructed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    with pytest.raises(OmniProbeCliError, match="CLI version"):
        probe_main(
            _probe_arguments(workspace, freeze_a_commit),
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=lambda _settings, _environment: "9.9.9",
        )

    assert constructed is False


def test_probe_rejects_untracked_runtime_source_before_constructing_client(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    runtime_source = workspace / "src" / "omni_benchmark"
    runtime_source.mkdir(parents=True)
    (runtime_source / "runtime_override.py").write_text("OVERRIDE = True\n")
    constructed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    with pytest.raises(OmniProbeCliError, match="clean runtime tree"):
        probe_main(
            _probe_arguments(workspace, freeze_a_commit),
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=_observe_cli_version,
        )

    assert constructed is False


def test_probe_rejects_modified_tracked_runtime_before_constructing_client(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    (workspace / "scripts" / "probe_entrypoint.py").write_text(
        "ENTRYPOINT = False\n", encoding="utf-8"
    )
    constructed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    with pytest.raises(OmniProbeCliError, match="clean runtime tree"):
        probe_main(
            _probe_arguments(workspace, freeze_a_commit),
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=_observe_cli_version,
        )

    assert constructed is False


def test_probe_rejects_tree_or_mutated_worktree_file_as_run_spec(
    tmp_path: Path,
) -> None:
    workspace, freeze_a_commit = _workspace(tmp_path)
    arguments = _probe_arguments(workspace, freeze_a_commit)
    arguments[arguments.index("--harness-config") + 1] = "config"
    with pytest.raises(OmniProbeCliError, match="Git blob"):
        probe_main(
            arguments,
            environment=_environment(workspace),
            client_factory=FakeClient,
            cli_version_observer=_observe_cli_version,
        )

    arguments = _probe_arguments(workspace, freeze_a_commit)
    condition = workspace / "config" / "conditions" / "c4-production-v1.json"
    condition.write_text("{}\n", encoding="utf-8")
    with pytest.raises(OmniProbeCliError, match="current bytes"):
        probe_main(
            arguments,
            environment=_environment(workspace),
            client_factory=FakeClient,
            cli_version_observer=_observe_cli_version,
        )


def test_probe_rejects_invalid_c4_spec_before_constructing_client(
    tmp_path: Path,
) -> None:
    workspace, _ = _workspace(tmp_path)
    condition = workspace / "config" / "conditions" / "c4-production-v1.json"
    value = json.loads(condition.read_text())
    value["result_selection"] = "first_query"
    condition.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "test: invalid c4 spec"], cwd=workspace, check=True
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    constructed = False

    def factory(settings: OmniCliSettings) -> FakeClient:
        nonlocal constructed
        constructed = True
        return FakeClient(settings)

    with pytest.raises(OmniProbeCliError, match="C4 condition specification"):
        probe_main(
            _probe_arguments(workspace, commit),
            environment=_environment(workspace),
            client_factory=factory,
            cli_version_observer=_observe_cli_version,
        )

    assert constructed is False

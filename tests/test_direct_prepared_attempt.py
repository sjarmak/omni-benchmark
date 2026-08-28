from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import omni_benchmark.direct_prepared_attempt as prepared_module
from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.direct_capture_contract import (
    DirectDatabaseAttestation,
    DirectModelTurn,
)
from omni_benchmark.direct_prepared_attempt import (
    DirectPreparedAttemptError,
    prepare_committed_direct_attempt,
    validate_direct_prepared_attempt,
)
from omni_benchmark.direct_sql_capture import DirectCaptureError, DirectSqlCapture
from tests.test_direct_database_loader import _database_record, _sidecar, _target
from tests.test_direct_public_context import (
    _fixture_repo,
    _git,
    _mutate_captured_record,
)
from tests.direct_capture_fixtures import budget_identity, model_identity


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _committed_runtime_repo(tmp_path: Path) -> tuple[Path, str]:
    workspace, _ = _fixture_repo(tmp_path)
    record = {
        "category": "Query",
        "clean_up_sqls": [],
        "conditions": {"decimal": 2, "distinct": False, "order": False},
        "high_level": False,
        "instance_id": "dev-a-1",
        "normal_query": "Normal public question",
        "preprocess_sql": [],
        "query": "Public committed question",
        "selected_database": "archeology_scan_large",
        "source_index": 0,
    }
    _write(workspace / "data/manifests/eligible_questions.jsonl", _canonical(record))
    _write(workspace / "data/manifests/train_ids.txt", b"dev-a-1\n")
    _write(workspace / "data/manifests/dev_a_ids.txt", b"dev-a-1\n")
    _write(workspace / "data/manifests/dev_b_ids.txt", b"dev-a-1\n")
    _write(workspace / "data/manifests/test_ids.txt", b"test-1\n")
    _write(
        workspace / "config/autoresearch.json",
        _canonical(
            {
                "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
                "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
                "public_manifest_path": "data/manifests/eligible_questions.jsonl",
                "test_ids_path": "data/manifests/test_ids.txt",
                "train_ids_path": "data/manifests/train_ids.txt",
            }
        ),
    )
    inventory = {
        "benchmark": "LiveSQLBench Large-v1",
        "canary": "archeology_scan_large",
        "canary_verification": {},
        "databases": [_database_record()],
        "format_version": 2,
        "postgres_major": 18,
        "sources": {"dataset_revision": "public-fixture"},
    }
    _write(
        workspace / "config/databases/livesqlbench-large-v1.json",
        _canonical(inventory),
    )
    _write(
        workspace / "config/conditions/direct-database-targets-v1.json",
        _canonical(_sidecar(inventory, [_target()])),
    )
    _write(workspace / ".gitignore", b"runs/\n")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "runtime inputs")
    return workspace, _git(workspace, "rev-parse", "HEAD")


class _FakeClaudeTransport:
    def __init__(self, config: object) -> None:
        self.execution_authority = "model-state-v1"
        self.runtime_identity = model_identity()
        self.budget_identity = budget_identity()
        self.observed_messages: list[Any] = []

    def next_turn(self, messages: Any, tool_specs: Any) -> DirectModelTurn:
        self.observed_messages.append(messages)
        return DirectModelTurn(
            action={"type": "refuse", "reason": "insufficient_information"},
            model_identity=self.runtime_identity,
            input_tokens=1,
            output_tokens=1,
            retry_count=0,
            cost_usd=0.0,
        )


class _FakePostgresTransport:
    execution_attestation = DirectDatabaseAttestation(True, True)

    def __init__(self, environment: object, *, expected_identity: object) -> None:
        self.execution_authority = "database-state-v1"
        self.runtime_identity = expected_identity

    def connect(self) -> object:
        raise AssertionError("refusal must not connect")


def _prepare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, condition: str = "C1"
) -> object:
    workspace, commit = _committed_runtime_repo(tmp_path)
    monkeypatch.setattr(prepared_module, "ClaudeDirectTransport", _FakeClaudeTransport)
    monkeypatch.setattr(
        prepared_module,
        "AttestedDirectPostgresTransport",
        _FakePostgresTransport,
    )
    monkeypatch.setattr(
        prepared_module,
        "verify_system_commit",
        lambda workspace, commit: None,
        raising=False,
    )
    monkeypatch.setattr(
        prepared_module,
        "_verify_runtime_package",
        lambda workspace: None,
        raising=False,
    )
    return prepare_committed_direct_attempt(
        workspace=workspace,
        commit=commit,
        scope="dev-a",
        instance_id="dev-a-1",
        condition=condition,
        run_id="run-1",
        repetition=1,
        claude_config=object(),
        database_environment={},
        store=ArtifactStore(workspace, Path("runs/direct")),
        environment={},
    )


def test_preflight_loads_committed_question_context_and_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare(tmp_path, monkeypatch)

    result = DirectSqlCapture(prepared=prepared).capture()

    assert prepared.binding.question.question == "Public committed question"
    assert prepared.binding.question.scope == "dev-a"
    assert prepared.binding.context.selected_database == "archeology_scan_large"
    assert prepared.binding.database.selected_database == "archeology_scan_large"
    assert result.generation_outcome == "refused"
    assert prepared.model_transport.observed_messages[0] == (
        {"role": "user", "content": "Public committed question"},
    )


@pytest.mark.parametrize("scope", ["train", "dev-b", "test"])
def test_preflight_rejects_non_dev_a_scope_before_transports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scope: str
) -> None:
    workspace, commit = _committed_runtime_repo(tmp_path)
    constructed: list[str] = []

    class RecordingClaude(_FakeClaudeTransport):
        def __init__(self, config: object) -> None:
            constructed.append("model")
            super().__init__(config)

    monkeypatch.setattr(prepared_module, "ClaudeDirectTransport", RecordingClaude)
    monkeypatch.setattr(
        prepared_module,
        "AttestedDirectPostgresTransport",
        _FakePostgresTransport,
    )
    monkeypatch.setattr(
        prepared_module,
        "verify_system_commit",
        lambda workspace, commit: None,
        raising=False,
    )
    monkeypatch.setattr(
        prepared_module,
        "_verify_runtime_package",
        lambda workspace: None,
        raising=False,
    )

    with pytest.raises(DirectPreparedAttemptError, match="dev-A"):
        prepare_committed_direct_attempt(
            workspace=workspace,
            commit=commit,
            scope=scope,
            instance_id="test-1" if scope == "test" else "dev-a-1",
            condition="C1",
            run_id="run-1",
            repetition=1,
            claude_config=object(),
            database_environment={},
            store=ArtifactStore(workspace, Path("runs/direct")),
            environment={},
        )

    assert constructed == []


def test_preflight_rejects_dirty_runtime_before_transports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit = _committed_runtime_repo(tmp_path)
    dirty = workspace / "src/uncommitted_harness.py"
    dirty.parent.mkdir(parents=True)
    dirty.write_text("raise AssertionError\n", encoding="utf-8")
    constructed: list[str] = []

    class RecordingClaude(_FakeClaudeTransport):
        def __init__(self, config: object) -> None:
            constructed.append("model")
            super().__init__(config)

    monkeypatch.setattr(prepared_module, "ClaudeDirectTransport", RecordingClaude)
    monkeypatch.setattr(
        prepared_module,
        "AttestedDirectPostgresTransport",
        _FakePostgresTransport,
    )
    monkeypatch.setattr(
        prepared_module,
        "_verify_runtime_package",
        lambda selected_workspace: None,
        raising=False,
    )

    with pytest.raises(DirectPreparedAttemptError, match="clean runtime tree"):
        prepare_committed_direct_attempt(
            workspace=workspace,
            commit=commit,
            scope="dev-a",
            instance_id="dev-a-1",
            condition="C1",
            run_id="run-1",
            repetition=1,
            claude_config=object(),
            database_environment={},
            store=ArtifactStore(workspace, Path("runs/direct")),
            environment={},
        )

    assert constructed == []


def test_preflight_rejects_artifact_store_from_another_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit = _committed_runtime_repo(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / ".gitignore").write_text("runs/\n", encoding="utf-8")
    foreign_store = ArtifactStore(other, Path("runs/direct"))
    monkeypatch.setattr(
        prepared_module,
        "verify_system_commit",
        lambda selected_workspace, selected_commit: None,
        raising=False,
    )
    monkeypatch.setattr(
        prepared_module,
        "_verify_runtime_package",
        lambda selected_workspace: None,
        raising=False,
    )

    with pytest.raises(DirectPreparedAttemptError, match="artifact store"):
        prepare_committed_direct_attempt(
            workspace=workspace,
            commit=commit,
            scope="dev-a",
            instance_id="dev-a-1",
            condition="C1",
            run_id="run-1",
            repetition=1,
            claude_config=object(),
            database_environment={},
            store=foreign_store,
            environment={},
        )


def test_prepared_authority_detects_public_callback_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare(tmp_path, monkeypatch, condition="C2")
    object.__setattr__(
        prepared.public_tools,
        "search_hkb",
        lambda query: {"matches": [{"fabricated": query}]},
    )

    with pytest.raises(DirectCaptureError, match="not authorized"):
        DirectSqlCapture(prepared=prepared)


def test_prepared_authority_is_rechecked_after_capture_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prepared = _prepare(tmp_path, monkeypatch, condition="C2")
    capture = DirectSqlCapture(prepared=prepared)
    object.__setattr__(
        prepared.public_tools,
        "search_hkb",
        lambda query: {"matches": [{"fabricated": query}]},
    )

    with pytest.raises(DirectCaptureError, match="not authorized"):
        capture.capture()


@pytest.mark.parametrize(
    ("condition", "tool_name", "identifying_key", "identifying_value"),
    [
        (
            "C2",
            "search_hkb",
            "stable_id",
            "archeology_scan_large:hkb:3",
        ),
        (
            "C3",
            "search_semantic_model",
            "object_id",
            "archeology_scan_large_public__scan.premium_scan_quality",
        ),
    ],
)
def test_prepared_authority_cannot_mask_mutated_public_context_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    condition: str,
    tool_name: str,
    identifying_key: str,
    identifying_value: str,
) -> None:
    prepared = _prepare(tmp_path, monkeypatch, condition=condition)
    callback = getattr(prepared.public_tools, tool_name)
    assert callback is not None
    original = callback("premium quality")

    _mutate_captured_record(
        callback,
        identifying_key=identifying_key,
        identifying_value=identifying_value,
        field="description",
        replacement="FABRICATED WHILE AUTHORITY STILL VALID",
    )

    assert validate_direct_prepared_attempt(prepared) is prepared
    assert callback("premium quality") == original


@pytest.mark.parametrize("dependency", ["model", "database"])
def test_prepared_authority_detects_transport_method_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dependency: str
) -> None:
    prepared = _prepare(tmp_path, monkeypatch)
    capture = DirectSqlCapture(prepared=prepared)
    if dependency == "model":
        prepared.model_transport.next_turn = lambda messages, tools: DirectModelTurn(
            action={"type": "refuse", "reason": "insufficient_information"},
            model_identity=prepared.model_transport.runtime_identity,
        )
    else:
        prepared.database.connect = lambda: object()

    with pytest.raises(DirectCaptureError, match="not authorized"):
        capture.capture()


@pytest.mark.parametrize("dependency", ["model", "database"])
def test_prepared_authority_detects_transport_execution_state_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dependency: str
) -> None:
    prepared = _prepare(tmp_path, monkeypatch)
    capture = DirectSqlCapture(prepared=prepared)
    target = prepared.model_transport if dependency == "model" else prepared.database
    target.execution_authority = f"{dependency}-state-v2"

    with pytest.raises(DirectCaptureError, match="not authorized"):
        capture.capture()

from __future__ import annotations

import json
import hashlib
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.c4_result_recovery import (
    C4RecoveryError,
    C4RecoveryManifest,
    C4RecoverySource,
    load_c4_recovery_manifest,
    recover_c4_source,
    recover_c4_selection,
    write_c4_recovery_manifest,
)
from omni_benchmark.omni_cli import OmniCliError


class FakeClient:
    def __init__(self, data_type: str = "BOOLEAN") -> None:
        self.data_type = data_type
        self.plan_calls = 0
        self.run_calls = 0

    def plan_query(self, query: dict[str, object]) -> dict[str, object]:
        self.plan_calls += 1
        field = query["fields"][0]  # type: ignore[index]
        return {
            "query": {"model_job": {"fields": [field]}},
            "status": "PLANNED",
            "summary": {
                "fields": {
                    field: {
                        "data_type": self.data_type,
                        "fully_qualified_name": field,
                    }
                },
                "invalid_calculations": {},
                "missing_fields": [],
            },
        }

    def run_query_json(self, query: dict[str, object]) -> list[dict[str, object]]:
        self.run_calls += 1
        return [{"Enabled": True}]


class FieldAwareClient(FakeClient):
    def plan_query(self, query: dict[str, object]) -> dict[str, object]:
        field = query["fields"][0]  # type: ignore[index]
        self.data_type = "UNKNOWN" if field.endswith(".unknown") else "BOOLEAN"
        return super().plan_query(query)


class RateLimitedFieldAwareClient(FieldAwareClient):
    def __init__(self) -> None:
        super().__init__()
        self.rate_limited = False

    def plan_query(self, query: dict[str, object]) -> dict[str, object]:
        if not self.rate_limited:
            self.rate_limited = True
            raise OmniCliError("request failed with HTTP 429")
        return super().plan_query(query)


class MalformedPlanClient(FakeClient):
    def plan_query(self, query: dict[str, object]) -> dict[str, object]:
        self.plan_calls += 1
        return {"status": "ERROR"}


class RejectedPlanClient(FakeClient):
    def __init__(self, status: int) -> None:
        super().__init__()
        self.status = status

    def plan_query(self, query: dict[str, object]) -> dict[str, object]:
        self.plan_calls += 1
        raise OmniCliError(f"request failed with HTTP {self.status}")


def _store(tmp_path: Path) -> ArtifactStore:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("experiments/autoresearch/\n")
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    return ArtifactStore(
        workspace,
        Path("experiments/autoresearch/raw/c4-recovery-fixture"),
        require_new_root=True,
        environment={},
    )


def _source(
    *,
    failure_class: str = "unsupported_semantic_result_type",
    generated_query: str | None = '{"fields":["answer.enabled"]}',
) -> C4RecoverySource:
    return C4RecoverySource(
        attempt_id="public-c4-baseline-v8:fixture_1:C4:1",
        database="fixture_large",
        generated_query=generated_query,
        source_failure_class=failure_class,
        source_generation_sha256="a" * 64,
    )


def _canonical(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _write(path: Path, value: object) -> str:
    content = _canonical(value)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o600)
    return hashlib.sha256(content).hexdigest()


def test_known_plan_type_replays_only_the_existing_semantic_query(
    tmp_path: Path,
) -> None:
    client = FakeClient()

    entry = recover_c4_source(_source(), client=client, store=_store(tmp_path))

    assert entry.disposition == "recovered_result"
    assert entry.reason == "adapter_semantic_query_replay"
    assert entry.result_artifact_sha256 is not None
    assert entry.result_artifact_path is not None
    artifact = json.loads(
        (tmp_path / "workspace" / entry.result_artifact_path).read_text()
    )
    assert artifact["rows"] == [[True]]
    assert client.plan_calls == 1
    assert client.run_calls == 1


def test_unknown_plan_type_is_adjudicated_without_executing_the_query(
    tmp_path: Path,
) -> None:
    client = FakeClient(data_type="UNKNOWN")

    entry = recover_c4_source(_source(), client=client, store=_store(tmp_path))

    assert entry.disposition == "evaluated_system_failure"
    assert entry.reason == "omni_unknown_result_type"
    assert entry.result_artifact_path is None
    assert entry.result_artifact_sha256 is None
    assert client.plan_calls == 1
    assert client.run_calls == 0


def test_completed_job_without_a_parseable_query_is_system_contract_failure(
    tmp_path: Path,
) -> None:
    client = FakeClient()

    entry = recover_c4_source(
        _source(failure_class="response_contract_error", generated_query=None),
        client=client,
        store=_store(tmp_path),
    )

    assert entry.disposition == "evaluated_system_failure"
    assert entry.reason == "omni_completed_job_contract_invalid"
    assert client.plan_calls == 0
    assert client.run_calls == 0


def test_malformed_omni_plan_is_system_contract_failure(tmp_path: Path) -> None:
    client = MalformedPlanClient()

    entry = recover_c4_source(_source(), client=client, store=_store(tmp_path))

    assert entry.disposition == "evaluated_system_failure"
    assert entry.reason == "omni_query_plan_contract_invalid"
    assert client.plan_calls == 1
    assert client.run_calls == 0


def test_persistent_query_plan_rejection_is_system_failure(tmp_path: Path) -> None:
    client = RejectedPlanClient(400)

    entry = recover_c4_source(_source(), client=client, store=_store(tmp_path))

    assert entry.disposition == "evaluated_system_failure"
    assert entry.reason == "omni_query_plan_rejected"
    assert client.plan_calls == 1


def test_provider_plan_failure_remains_infrastructure(tmp_path: Path) -> None:
    client = RejectedPlanClient(503)

    with pytest.raises(C4RecoveryError, match="provider plan"):
        recover_c4_source(_source(), client=client, store=_store(tmp_path))


@pytest.mark.parametrize(
    ("failure_class", "generated_query"),
    [
        ("omni_job_terminal_failure", '{"fields":["answer.enabled"]}'),
        ("adapter_transport_error", "not-json"),
    ],
)
def test_recovery_rejects_ineligible_or_malformed_sources(
    tmp_path: Path, failure_class: str, generated_query: str
) -> None:
    with pytest.raises(C4RecoveryError):
        recover_c4_source(
            _source(
                failure_class=failure_class,
                generated_query=generated_query,
            ),
            client=FakeClient(),
            store=_store(tmp_path),
        )


def test_recovery_manifest_round_trips_with_exact_counts_and_hash(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    recovered = recover_c4_source(_source(), client=FakeClient(), store=store)
    adjudicated = recover_c4_source(
        C4RecoverySource(
            attempt_id="public-c4-baseline-v8:fixture_2:C4:1",
            database="fixture_large",
            generated_query='{"fields":["answer.enabled"]}',
            source_failure_class="unsupported_semantic_result_type",
            source_generation_sha256="b" * 64,
        ),
        client=FakeClient(data_type="UNKNOWN"),
        store=store,
    )

    stored = write_c4_recovery_manifest(
        store,
        source_commit="c" * 40,
        source_run_id="public-c4-baseline-v8",
        source_selection_sha256="d" * 64,
        entries=(recovered, adjudicated),
    )
    manifest = load_c4_recovery_manifest(
        tmp_path / "workspace",
        store.relative_path(stored),
        expected_sha256=stored.sha256,
    )

    assert isinstance(manifest, C4RecoveryManifest)
    assert manifest.counts == {
        "evaluated_system_failure": 1,
        "recovered_result": 1,
        "source_failures": 2,
    }
    assert manifest.sha256 == stored.sha256


def test_recovery_manifest_rejects_digest_mismatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    entry = recover_c4_source(_source(), client=FakeClient(), store=store)
    stored = write_c4_recovery_manifest(
        store,
        source_commit="c" * 40,
        source_run_id="public-c4-baseline-v8",
        source_selection_sha256="d" * 64,
        entries=(entry,),
    )

    with pytest.raises(C4RecoveryError, match="SHA-256"):
        load_c4_recovery_manifest(
            tmp_path / "workspace",
            store.relative_path(stored),
            expected_sha256="e" * 64,
        )


def test_selection_recovery_processes_only_hash_bound_infrastructure_failures(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("experiments/autoresearch/\n")
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    run_id = "public-c4-baseline-v8"
    entries: list[dict[str, object]] = []
    for instance_id, outcome, failure_class, query in (
        (
            "fixture_1",
            "errored",
            "unsupported_semantic_result_type",
            '{"fields":["answer.enabled"]}',
        ),
        (
            "fixture_2",
            "errored",
            "unsupported_semantic_result_type",
            '{"fields":["answer.unknown"]}',
        ),
        ("fixture_3", "answered", None, '{"fields":["answer.enabled"]}'),
    ):
        attempt_id = f"{run_id}:{instance_id}:C4:1"
        generation = {
            "attempt_id": attempt_id,
            "condition": "C4",
            "failure_origin": (
                "benchmark_infrastructure" if outcome == "errored" else None
            ),
            "generated_query": query,
            "generation_outcome": outcome,
            "instance_id": instance_id,
            "repetition": 1,
            "run_id": run_id,
            "terminal_failure_class": failure_class,
        }
        generation_sha256 = _write(
            workspace
            / "experiments/autoresearch/raw"
            / run_id
            / "fixture_large/c4"
            / f"{instance_id}-r1/generation.jsonl",
            generation,
        )
        entries.append(
            {
                "attempt_id": attempt_id,
                "condition": "C4",
                "database": "fixture_large",
                "generation_sha256": generation_sha256,
                "instance_id": instance_id,
                "repetition": 1,
                "run_manifest_sha256": "f" * 64,
            }
        )
    selection_path = Path("experiments/autoresearch/state/c4-freeze.json")
    selection_sha256 = _write(
        workspace / selection_path,
        {
            "entries": entries,
            "kind": "public-c4-baseline-freeze",
            "run_id": run_id,
            "source_commit": "c" * 40,
        },
    )
    deployment_root = Path("experiments/deployments/public-baseline-v13")
    _write(
        workspace / deployment_root / "public-baseline-v13-20260829.fixture_large.json",
        {
            "branch_id": "branch-id",
            "database": "fixture_large",
            "model_id": "model-id",
            "status": "verified",
        },
    )

    clients: list[RateLimitedFieldAwareClient] = []

    def client_factory(_settings) -> RateLimitedFieldAwareClient:
        client = RateLimitedFieldAwareClient()
        clients.append(client)
        return client

    receipt = recover_c4_selection(
        workspace,
        artifact_workspace=workspace,
        selection_path=selection_path,
        expected_selection_sha256=selection_sha256,
        deployment_workspace=workspace,
        deployment_root=deployment_root,
        deployment_run_id="public-baseline-v13-20260829",
        output_root=Path("experiments/autoresearch/raw/c4-recovery"),
        profile="benchmark",
        expected_source_failures=2,
        client_factory=client_factory,
        minimum_request_interval_seconds=0,
        sleep=lambda _seconds: None,
    )

    assert receipt["counts"] == {
        "evaluated_system_failure": 1,
        "recovered_result": 1,
        "source_failures": 2,
    }
    assert receipt["source_attempts"] == 3
    assert receipt["recovery_manifest_sha256"]
    assert len(clients) == 1
    assert clients[0].rate_limited is True

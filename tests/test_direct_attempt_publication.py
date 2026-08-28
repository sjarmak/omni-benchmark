from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from omni_benchmark.autoresearch_config import AutoresearchError, REQUIRED_RUN_FIELDS
from omni_benchmark.autoresearch_runs import (
    ALLOWED_RUN_FIELDS,
    _validate_runtime_binding_digest,
)
from omni_benchmark.direct_sql_attempt import write_direct_attempt
from tests.direct_attempt_fixtures import attempt_spec, capture_probe
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    SyntheticDatabase,
    capture_with_test_time,
    database_identity,
    prepared_attempt,
    runtime_binding,
    store as capture_store,
)

SHA_A = "a" * 64
SHA_C = "c" * 64
COMMIT = "e" * 40


def test_runtime_binding_digest_is_optional_for_legacy_and_required_by_direct() -> None:
    assert "runtime_binding_sha256" in ALLOWED_RUN_FIELDS
    assert "runtime_binding_sha256" not in REQUIRED_RUN_FIELDS
    _validate_runtime_binding_digest({})
    _validate_runtime_binding_digest({"runtime_binding_sha256": "a" * 64})
    with pytest.raises(AutoresearchError, match="runtime_binding_sha256"):
        _validate_runtime_binding_digest({"runtime_binding_sha256": "not-a-digest"})


def _answered_attempt(tmp_path: Path) -> tuple[object, ...]:
    workspace, store, binding, probe = capture_probe(
        tmp_path,
        actions=[{"type": "answer", "sql": "SELECT 42"}],
        condition="C2",
        instance_id="public-1",
        responses={"SELECT 42": [(42,)]},
        run_id="run-1",
        system_commit=COMMIT,
    )
    return (
        workspace,
        store,
        binding,
        probe,
        replace(
            attempt_spec(binding),
            controllable_seed=17,
            software_versions={"omni-benchmark": "0.1.0", "python": "3.11.9"},
        ),
    )


def _retrieval_attempt(tmp_path: Path) -> tuple[object, ...]:
    binding = runtime_binding(
        "C2",
        instance_id="public-retrieval",
        run_id="run-retrieval",
        system_commit=COMMIT,
    )
    workspace, artifact_store = capture_store(tmp_path, "direct-attempt")
    prepared = prepared_attempt(
        binding,
        model=SequenceModel(
            binding,
            [
                {
                    "type": "tool",
                    "name": "search_hkb",
                    "arguments": {"query": "public metric"},
                },
                {"type": "answer", "sql": "SELECT 42"},
            ],
        ),
        database=SyntheticDatabase(binding, {"SELECT 42": [(42,)]}),
        public_tools=BoundPublicTools(
            binding,
            hkb_payload={"retrieved_hkb_stable_ids": ["public:hkb:metric"]},
        ),
        artifact_store=artifact_store,
    )
    probe = capture_with_test_time(prepared, clock_steps=40)
    return workspace, artifact_store, binding, probe, attempt_spec(binding)


def _replace_action_evidence(probe: object, payload: object) -> object:
    content = (
        json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    probe.action_evidence.path.write_bytes(content)
    artifact = replace(
        probe.action_evidence,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )
    return replace(probe, action_evidence=artifact)


def test_answered_attempt_writes_binding_and_hash_bound_manifest(
    tmp_path: Path,
) -> None:
    workspace, store, binding, probe, spec = _answered_attempt(tmp_path)

    artifacts = write_direct_attempt(
        workspace=workspace, store=store, spec=spec, probe=probe
    )

    generation = json.loads(artifacts.generation.path.read_text())
    manifest = json.loads(artifacts.run_manifest.path.read_text())
    assert generation["attempt_id"] == binding.attempt_id
    assert generation["runtime_binding_sha256"] == binding.sha256()
    assert generation["generation_outcome"] == "answered"
    assert generation["generated_sql"] == "SELECT 42"
    assert generation["actual_result_hash"] == probe.result_artifact.sha256
    assert generation["token_usage"] == {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
    }
    assert manifest["condition"] == "C2"
    assert manifest["scope"] == "dev-a"
    assert manifest["controllable_seed"] == 17
    assert manifest["generation_sha256"] == artifacts.generation.sha256
    assert (
        manifest["semantic_model_sha256"]
        == dict(binding.context.component_sha256)["hkb"]
    )


@pytest.mark.parametrize(
    ("reason", "expected_failure"),
    [
        ("cannot_answer_safely", "refused_content"),
        ("insufficient_information", "no_answer_insufficient_context"),
    ],
)
def test_refusal_reason_survives_into_generation_telemetry(
    tmp_path: Path, reason: str, expected_failure: str
) -> None:
    workspace, artifact_store, binding, probe = capture_probe(
        tmp_path,
        actions=[{"type": "refuse", "reason": reason}],
        instance_id=f"public-{reason}",
        run_id="run-refusal-split",
        system_commit=COMMIT,
    )

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=artifact_store,
        spec=attempt_spec(binding),
        probe=probe,
    )

    generation = json.loads(artifacts.generation.path.read_text())
    assert generation["generation_outcome"] == "refused"
    assert generation["terminal_failure_class"] == expected_failure
    assert generation["failure_origin"] == "evaluated_system"
    assert generation["harness_failure"] is None


class PreQueryInfrastructureFailure(SyntheticDatabase):
    def connect(self) -> object:
        self.events.append(("connect",))
        raise RuntimeError("synthetic pre-query infrastructure failure")


class PreQueryIdentityFailure(SyntheticDatabase):
    def connect(self) -> object:
        connection = super().connect()
        self.runtime_identity = database_identity(selected_database="other_database")
        return connection


@pytest.mark.parametrize(
    ("database_class", "expected_failure"),
    [
        (PreQueryInfrastructureFailure, "database_infrastructure_error"),
        (PreQueryIdentityFailure, "database_identity_mismatch"),
    ],
)
def test_publisher_accepts_terminal_pre_query_database_boundary_failure(
    tmp_path: Path,
    database_class: type[SyntheticDatabase],
    expected_failure: str,
) -> None:
    binding = runtime_binding(
        instance_id="public-infrastructure",
        run_id="run-infrastructure",
        system_commit=COMMIT,
    )
    workspace, artifact_store = capture_store(tmp_path, "direct-attempt")
    prepared = prepared_attempt(
        binding,
        model=SequenceModel(
            binding,
            [
                {
                    "type": "tool",
                    "name": "execute_sql",
                    "arguments": {"sql": "SELECT 1"},
                },
                {"type": "refuse", "reason": "cannot_answer_safely"},
            ],
        ),
        database=database_class(binding, {}),
        public_tools=BoundPublicTools(binding),
        artifact_store=artifact_store,
    )
    probe = capture_with_test_time(prepared, clock_steps=20)

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=artifact_store,
        spec=attempt_spec(binding),
        probe=probe,
    )

    generation = json.loads(artifacts.generation.path.read_text())
    assert generation["generation_outcome"] == "errored"
    assert generation["terminal_failure_class"] == expected_failure
    assert generation["failure_origin"] == "benchmark_infrastructure"
    assert generation["database_query_count"] == 0


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"tool_call_count": 2}, "trace telemetry"),
        ({"question_sha256": SHA_C}, "question"),
        ({"generated_sql": "UPDATE x SET y = 1"}, "SQL"),
        ({"generated_sql": "SELECT 1; SELECT 2"}, "SQL"),
        ({"semantic_objects": ("forged.metric",)}, "semantic"),
    ],
)
def test_publisher_rejects_probe_or_payload_substitution_before_writes(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    workspace, store, _, probe, spec = _answered_attempt(tmp_path)

    with pytest.raises(ValueError, match=message):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, **changes),
        )

    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"cost_usd": 9.99},
        {"latency_ms": 999.0},
        {"started_at": "2026-08-28T03:59:00.000Z"},
        {"finished_at": "2026-08-28T05:00:00.000Z"},
    ],
)
def test_publisher_rejects_capture_summary_substitution_via_receipt(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    workspace, store, _, probe, spec = _answered_attempt(tmp_path)

    with pytest.raises(ValueError, match="capture receipt"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, **changes),
        )

    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()


def test_publisher_rejects_result_artifact_substitution(tmp_path: Path) -> None:
    workspace, store, _, probe, spec = _answered_attempt(tmp_path)
    assert probe.result_artifact is not None

    with pytest.raises(ValueError, match="result artifact"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(
                probe,
                result_artifact=replace(probe.result_artifact, sha256=SHA_A),
            ),
        )


@pytest.mark.parametrize("mutation", ["omit", "substitute", "forbidden"])
def test_publisher_rejects_action_evidence_tampering(
    tmp_path: Path, mutation: str
) -> None:
    workspace, store, _, probe, spec = _retrieval_attempt(tmp_path)
    payload = json.loads(probe.action_evidence.path.read_text())
    if mutation == "omit":
        payload["records"] = []
    elif mutation == "substitute":
        payload["records"][0]["retrieval_query"] = "different metric"
    else:
        payload["records"][0]["retrieval_query"] = "sk-" + "ant-" + "x" * 16
    forged = _replace_action_evidence(probe, payload)

    with pytest.raises(ValueError, match="action evidence"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=forged,
        )

    assert not (workspace / "runs/direct-attempt/generation.jsonl").exists()


def test_publisher_rejects_events_after_terminal(tmp_path: Path) -> None:
    workspace, store, _, probe, spec = _answered_attempt(tmp_path)
    events = [json.loads(line) for line in probe.trace.path.read_text().splitlines()]
    extra = {
        **events[-1],
        "elapsed_ms": 3.0,
        "metadata_sha256": SHA_C,
        "seq": len(events),
        "timestamp": "2026-08-28T04:00:03Z",
    }
    forged_trace = store.write_jsonl(
        Path("post-terminal.trace.jsonl"), [*events, extra]
    )

    with pytest.raises(ValueError, match="after a terminal event"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, trace=forged_trace, database_query_count=2),
        )


def test_publisher_rejects_impossible_model_trace(tmp_path: Path) -> None:
    workspace, store, _, probe, spec = _answered_attempt(tmp_path)
    event = json.loads(probe.trace.path.read_text().splitlines()[0])
    event |= {
        "database_query_delta": 1,
        "status": "COMPLETE",
    }
    forged_trace = store.write_jsonl(Path("impossible.trace.jsonl"), [event])

    with pytest.raises(ValueError, match="trace.*(lifecycle|model|database)"):
        write_direct_attempt(
            workspace=workspace,
            store=store,
            spec=spec,
            probe=replace(probe, trace=forged_trace),
        )

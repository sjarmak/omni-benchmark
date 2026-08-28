from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.claude_direct_contract import (
    ClaudeDirectModelTurn,
    ClaudeTurnProvenance,
    ClaudeUsage,
)
from omni_benchmark.direct_capture_contract import DirectModelTurnProvenance
from omni_benchmark.direct_sql_attempt import write_direct_attempt
from tests.direct_attempt_fixtures import attempt_spec
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    SyntheticDatabase,
    capture_with_test_time,
    prepared_attempt,
    runtime_binding,
    store,
)

REQUEST_SHA256 = "7" * 64
STREAM_SHA256 = "8" * 64


class ProvenanceModel(SequenceModel):
    def __init__(self, *args: Any, session_id: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._session_id = session_id

    def next_turn(
        self,
        messages: tuple[dict[str, Any], ...],
        tool_specs: tuple[dict[str, Any], ...],
    ) -> ClaudeDirectModelTurn:
        self.observed_messages.append(messages)
        self.observed_tools.append(tuple(tool["name"] for tool in tool_specs))
        action = next(self._actions)
        usage = ClaudeUsage(
            input_tokens=10,
            output_tokens=2,
            message_count=1,
            models=(self.runtime_identity.model,),
        )
        return ClaudeDirectModelTurn(
            action=action,
            model_identity=self.runtime_identity,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            retry_count=0,
            cost_usd=0.001,
            provenance=ClaudeTurnProvenance(
                binary_path="/private/runtime/claude",
                binary_sha256=self.runtime_identity.executable_sha256,
                cli_version=self.runtime_identity.executable_version,
                cost_source="claude_result_total_cost_usd",
                duration_seconds=1.25,
                model_identity=self.runtime_identity,
                partial_usage=usage,
                provider=self.runtime_identity.provider,
                realized_models=(self.runtime_identity.model,),
                request_sha256=REQUEST_SHA256,
                requested_model=self.runtime_identity.model,
                result_subtype="success",
                session_id=self._session_id,
                stream_sha256=STREAM_SHA256,
                token_source="claude_result_model_usage",
            ),
        )


def _capture(tmp_path: Path, session_id: str) -> tuple[Any, ...]:
    binding = runtime_binding(
        instance_id="public-provider-provenance",
        run_id="run-provider-provenance",
        system_commit="e" * 40,
    )
    workspace, artifact_store = store(tmp_path, "provider-provenance")
    model = ProvenanceModel(
        binding,
        [{"type": "refuse", "reason": "insufficient_information"}],
        session_id=session_id,
    )
    prepared = prepared_attempt(
        binding,
        model=model,
        database=SyntheticDatabase(binding, {}),
        public_tools=BoundPublicTools(binding),
        artifact_store=artifact_store,
    )
    probe = capture_with_test_time(prepared)
    return workspace, artifact_store, binding, probe


def test_capture_reduces_provider_provenance_and_never_persists_raw_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_session = "live-provider-session-secret"
    monkeypatch.setenv("OMNI_API_TOKEN", raw_session)
    workspace, artifact_store, binding, probe = _capture(tmp_path, raw_session)

    assert len(probe.model_turn_provenance) == 1
    record = probe.model_turn_provenance[0]
    assert record.availability == "observed"
    assert record.provider == binding.model.provider
    assert record.requested_model == binding.model.model
    assert record.realized_models == (binding.model.model,)
    assert record.binary_sha256 == binding.model.executable_sha256
    assert record.cli_version == binding.model.executable_version
    assert record.request_sha256 == REQUEST_SHA256
    assert record.stream_sha256 == STREAM_SHA256
    assert record.session_sha256 == hashlib.sha256(raw_session.encode()).hexdigest()
    assert record.duration_ms == 1250.0
    assert record.result_subtype == "success"
    assert record.token_source == "claude_result_model_usage"
    assert record.cost_source == "claude_result_total_cost_usd"

    trace = [json.loads(line) for line in probe.trace.path.read_text().splitlines()]
    model_event = next(
        event for event in trace if event["event_type"] == "direct_model_turn"
    )
    assert model_event["metadata_sha256"] == record.sha256()

    receipt = json.loads(probe.receipt.path.read_text())
    assert receipt["schema_version"] == 4
    assert receipt["capture_summary"]["model_turn_provenance"] == [record.as_dict()]

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=artifact_store,
        spec=attempt_spec(binding),
        probe=probe,
    )
    generation = json.loads(artifacts.generation.path.read_text())
    assert generation["model_turn_provenance"] == [record.as_dict()]

    persisted = "\n".join(
        path.read_text()
        for path in (
            probe.trace.path,
            probe.receipt.path,
            artifacts.generation.path,
        )
    )
    assert raw_session not in persisted
    assert "/private/runtime/claude" not in persisted
    assert "session_id" not in persisted
    assert "binary_path" not in persisted


def test_synthetic_turn_emits_explicit_unavailable_provenance_marker(
    tmp_path: Path,
) -> None:
    binding = runtime_binding()
    workspace, artifact_store = store(tmp_path, "unavailable-provenance")
    prepared = prepared_attempt(
        binding,
        model=SequenceModel(
            binding,
            [{"type": "refuse", "reason": "insufficient_information"}],
        ),
        database=SyntheticDatabase(binding, {}),
        public_tools=BoundPublicTools(binding),
        artifact_store=artifact_store,
    )

    probe = capture_with_test_time(prepared)

    assert probe.model_turn_provenance == (
        DirectModelTurnProvenance.unavailable(trace_seq=0, identity=binding.model),
    )
    trace = [json.loads(line) for line in probe.trace.path.read_text().splitlines()]
    assert trace[0]["metadata_sha256"] == probe.model_turn_provenance[0].sha256()
    assert workspace.exists()


def test_publisher_rejects_provider_provenance_substitution_after_capture(
    tmp_path: Path,
) -> None:
    workspace, artifact_store, binding, probe = _capture(tmp_path, "session-a")
    forged = replace(
        probe.model_turn_provenance[0],
        session_sha256=hashlib.sha256(b"session-b").hexdigest(),
    )

    with pytest.raises(ValueError, match="provenance|receipt"):
        write_direct_attempt(
            workspace=workspace,
            store=artifact_store,
            spec=attempt_spec(binding),
            probe=replace(probe, model_turn_provenance=(forged,)),
        )

    assert not (workspace / "runs/provider-provenance/generation.jsonl").exists()


def test_capture_rejects_provider_provenance_for_another_model(
    tmp_path: Path,
) -> None:
    binding = runtime_binding()
    workspace, artifact_store = store(tmp_path, "forged-provider-provenance")
    model = ProvenanceModel(
        binding,
        [{"type": "refuse", "reason": "insufficient_information"}],
        session_id="session-a",
    )
    original_next_turn = model.next_turn

    def forged_next_turn(*args: Any, **kwargs: Any) -> ClaudeDirectModelTurn:
        turn = original_next_turn(*args, **kwargs)
        assert turn.provenance is not None
        return replace(
            turn,
            provenance=replace(turn.provenance, requested_model="other-model"),
        )

    model.next_turn = forged_next_turn  # type: ignore[method-assign]
    prepared = prepared_attempt(
        binding,
        model=model,
        database=SyntheticDatabase(binding, {}),
        public_tools=BoundPublicTools(binding),
        artifact_store=artifact_store,
    )

    probe = capture_with_test_time(prepared)

    assert probe.generation_outcome == "errored"
    assert probe.failure_class == "model_identity_mismatch"
    assert probe.model_turn_provenance[0].availability == "unavailable"
    assert "other-model" not in probe.trace.path.read_text()
    assert workspace.exists()

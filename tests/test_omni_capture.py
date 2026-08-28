from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.omni_capture import OmniCaptureError, OmniJobCapture


class FakeOmniClient:
    def __init__(self, statuses: list[dict[str, object]]) -> None:
        self.statuses = iter(statuses)

    def whoami(self) -> dict[str, object]:
        return {"authenticated": True}

    def submit_job(self, question: str) -> dict[str, object]:
        assert question == "Public benchmark question"
        return {"jobId": "job-1"}

    def job_status(self, job_id: str) -> dict[str, object]:
        assert job_id == "job-1"
        return next(self.statuses)

    def job_result(self, job_id: str) -> dict[str, object]:
        assert job_id == "job-1"
        return {
            "actions": [
                {
                    "message": "I generated a governed query.",
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
            ],
            "authorization": "Bearer provider-secret",
        }

    def run_query_json(self, query: dict[str, object]) -> list[dict[str, object]]:
        assert query == {"fields": ["answers.value"]}
        return [{"answer": 42}]

    def plan_query(self, query: dict[str, object]) -> dict[str, object]:
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


class TruncatedMetricsClient(FakeOmniClient):
    def job_result(self, job_id: str) -> dict[str, object]:
        response = super().job_result(job_id)
        action = response["actions"][0]  # type: ignore[index]
        action["result"]["csvResultWasTruncated"] = True  # type: ignore[index]
        return {
            **response,
            "metrics": {
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
            },
        }


class MetricsTypedTransportClient(TruncatedMetricsClient):
    def job_result(self, job_id: str) -> dict[str, object]:
        response = super().job_result(job_id)
        action = response["actions"][0]  # type: ignore[index]
        action["result"]["csvResultWasTruncated"] = False  # type: ignore[index]
        return response

    def run_query_json(self, query: dict[str, object]) -> list[dict[str, object]]:
        raise RuntimeError("typed replay unavailable")


class MultiModelMetricsClient(TruncatedMetricsClient):
    def job_result(self, job_id: str) -> dict[str, object]:
        response = super().job_result(job_id)
        metrics = response["metrics"]  # type: ignore[index]
        models = metrics["tokenBuckets"]["default"]["tokensByModel"]  # type: ignore[index]
        models["claude-sonnet-5"] = {  # type: ignore[index]
            "modelProvider": "bedrock",
            "tokens": {
                "cacheReadTokens": 100,
                "cacheWriteTokens": 200,
                "inputTokens": 3,
                "outputTokens": 5,
            },
        }
        return response


class ContradictoryQueryMetricsClient(TruncatedMetricsClient):
    def job_result(self, job_id: str) -> dict[str, object]:
        response = super().job_result(job_id)
        metrics = response["metrics"]  # type: ignore[index]
        metrics["queryCount"] = 0  # type: ignore[index]
        return response


def _store(tmp_path: Path) -> ArtifactStore:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return ArtifactStore(workspace, Path("runs/c4-probe"))


def test_capture_preserves_shape_and_trace_without_result_values(
    tmp_path: Path,
) -> None:
    clock_values = iter(index / 10 for index in range(12))
    capture = OmniJobCapture(
        FakeOmniClient([{"state": "EXECUTING"}, {"state": "COMPLETE"}]),
        _store(tmp_path),
        clock=lambda: next(clock_values),
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.job_id == "job-1"
    assert result.terminal_state == "COMPLETE"
    assert result.generated_query == '{"fields":["answers.value"]}'
    assert result.semantic_objects == ("answers.value",)
    assert result.tool_call_count is None
    assert result.database_query_count == 1
    assert result.validation_attempt_count is None
    assert result.result_artifact is not None
    assert json.loads(result.result_artifact.path.read_text()) == {
        "columns": ["answer"],
        "rows": [[{"type": "decimal", "value": "42"}]],
        "schema_version": 1,
        "truncated": False,
    }
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert [event["seq"] for event in trace] == [0, 1, 2, 3, 4, 5]
    assert [event["event_type"] for event in trace] == [
        "omni_job_submit",
        "omni_job_status",
        "omni_job_status",
        "omni_job_result",
        "omni_query_plan",
        "omni_query_run_json",
    ]
    assert all(event["retry_delta"] is None for event in trace)
    assert all(event["tool_call_delta"] is None for event in trace)
    assert [event["database_query_delta"] for event in trace] == [0, 0, 0, 1, 0, 0]
    assert all(event["validation_attempt_delta"] is None for event in trace)
    assert stat.S_IMODE(result.trace.path.stat().st_mode) == 0o600
    shape_text = result.response_shape.path.read_text()
    assert "csvResult" in shape_text
    assert '"generate_query":1' in shape_text
    assert "answers.value" in shape_text
    assert '"type":"number"' in shape_text
    assert "authorization" not in shape_text
    assert "provider-secret" not in shape_text
    assert "private-result-id" not in shape_text


def test_capture_recovers_full_result_and_metrics_from_truncated_preview(
    tmp_path: Path,
) -> None:
    capture = OmniJobCapture(
        TruncatedMetricsClient([{"state": "COMPLETE"}]),
        _store(tmp_path),
        clock=iter(index / 10 for index in range(12)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "COMPLETE"
    assert result.failure_class is None
    assert result.result_artifact is not None
    assert result.model_name == "claude-opus-5"
    assert result.model_provider == "bedrock"
    assert result.token_usage is not None
    assert result.token_usage.as_dict() == {
        "input_tokens": 247_500,
        "output_tokens": 1_083,
        "total_tokens": 248_583,
    }
    assert result.tool_call_count == 3
    assert result.tool_calls_by_name == (("generate_query", 1), ("search_model", 2))
    assert result.database_query_count == 1
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert sum(event["input_tokens"] for event in trace) == 247_500
    assert sum(event["output_tokens"] for event in trace) == 1_083
    assert sum(event["tool_call_delta"] for event in trace) == 3
    assert sum(event["database_query_delta"] for event in trace) == 1


def test_capture_preserves_provider_query_count_when_typed_replay_fails(
    tmp_path: Path,
) -> None:
    capture = OmniJobCapture(
        MetricsTypedTransportClient([{"state": "COMPLETE"}]),
        _store(tmp_path),
        clock=iter(index / 10 for index in range(12)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "ADAPTER_ERROR"
    assert result.failure_class == "adapter_transport_error"
    assert result.database_query_count == 1
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert sum(event["database_query_delta"] for event in trace) == 1


def test_capture_rejects_provider_query_count_below_successful_query_actions(
    tmp_path: Path,
) -> None:
    capture = OmniJobCapture(
        ContradictoryQueryMetricsClient([{"state": "COMPLETE"}]),
        _store(tmp_path),
        clock=iter(index / 10 for index in range(12)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "CONTRACT_ERROR"
    assert result.failure_class == "response_contract_error"
    assert result.database_query_count is None


def test_capture_preserves_composite_model_identity(tmp_path: Path) -> None:
    capture = OmniJobCapture(
        MultiModelMetricsClient([{"state": "COMPLETE"}]),
        _store(tmp_path),
        clock=iter(index / 10 for index in range(12)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.model_name == "composite:claude-opus-5+claude-sonnet-5"
    assert result.model_provider == "bedrock"
    assert result.token_usage is not None
    assert result.token_usage.total_tokens == 248_891


def test_capture_rejects_recursive_forbidden_typed_result_and_finalizes_trace(
    tmp_path: Path,
) -> None:
    client = FakeOmniClient([{"state": "COMPLETE"}])
    client.run_query_json = lambda _: [  # type: ignore[method-assign]
        {"answer": {"external_knowledge": ["hidden-node"]}}
    ]
    capture = OmniJobCapture(
        client,
        _store(tmp_path),
        clock=iter(index / 10 for index in range(12)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "CONTRACT_ERROR"
    assert result.failure_class == "response_contract_error"
    assert result.result_artifact is None
    assert result.database_query_count == 1
    assert result.trace.path.is_file()
    assert result.response_shape.path.is_file()
    persisted = result.trace.path.read_text() + result.response_shape.path.read_text()
    assert "external_knowledge" not in persisted
    assert "hidden-node" not in persisted


def test_capture_typed_query_transport_failure_finalizes_errored_attempt(
    tmp_path: Path,
) -> None:
    client = FakeOmniClient([{"state": "COMPLETE"}])
    client.run_query_json = lambda _: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("typed query unavailable")
    )
    capture = OmniJobCapture(
        client,
        _store(tmp_path),
        clock=iter(index / 10 for index in range(12)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "ADAPTER_ERROR"
    assert result.failure_class == "adapter_transport_error"
    assert result.result_artifact is None
    assert result.database_query_count == 1
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert trace[-1]["event_type"] == "omni_capture_failure"
    assert sum(event["database_query_delta"] for event in trace) == 1


def test_capture_preserves_known_query_counts_when_typed_binding_fails(
    tmp_path: Path,
) -> None:
    client = FakeOmniClient([{"state": "COMPLETE"}])
    client.run_query_json = lambda _: [{"answer": 42}, {"answer": 43}]  # type: ignore[method-assign]
    capture = OmniJobCapture(
        client,
        _store(tmp_path),
        clock=iter(index / 10 for index in range(14)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "CONTRACT_ERROR"
    assert result.database_query_count == 1
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert [event["database_query_delta"] for event in trace] == [
        0,
        0,
        1,
        0,
        0,
        0,
    ]


def test_capture_records_completed_unrecognized_result_as_contract_error(
    tmp_path: Path,
) -> None:
    client = FakeOmniClient([{"state": "COMPLETE"}])
    client.job_result = lambda _: {"actions": []}  # type: ignore[method-assign]
    capture = OmniJobCapture(
        client,
        _store(tmp_path),
        clock=iter((0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "CONTRACT_ERROR"
    assert result.failure_class == "response_contract_error"
    assert result.result_artifact is None
    assert result.generated_query is None


def test_capture_records_unknown_submit_contract(tmp_path: Path) -> None:
    client = FakeOmniClient([])
    client.submit_job = lambda _: {"unexpected": "shape"}  # type: ignore[method-assign]
    capture = OmniJobCapture(
        client,
        _store(tmp_path),
        clock=iter((0.0, 0.1, 0.2)).__next__,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "CONTRACT_ERROR"
    assert result.failure_class == "response_contract_error"


def test_capture_reports_terminal_failed_job_without_fetching_result(
    tmp_path: Path,
) -> None:
    capture = OmniJobCapture(
        FakeOmniClient([{"state": "FAILED"}]),
        _store(tmp_path),
        clock=iter((0.0, 0.1, 0.2, 0.3, 0.4)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "FAILED"
    assert result.failure_class == "omni_job_terminal_failure"
    trace = [json.loads(line) for line in result.trace.path.read_text().splitlines()]
    assert [event["event_type"] for event in trace] == [
        "omni_job_submit",
        "omni_job_status",
        "omni_capture_failure",
    ]
    assert all(event["database_query_delta"] is None for event in trace)


def test_capture_persists_terminal_failure_when_provider_call_raises(
    tmp_path: Path,
) -> None:
    client = FakeOmniClient([])
    client.submit_job = lambda _: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("Bearer secret-that-must-not-persist")
    )
    capture = OmniJobCapture(
        client,
        _store(tmp_path),
        clock=iter((0.0, 0.1)).__next__,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.job_id is None
    assert result.terminal_state == "ADAPTER_ERROR"
    assert result.failure_class == "adapter_transport_error"
    trace_text = result.trace.path.read_text()
    assert "secret-that-must-not-persist" not in trace_text
    trace = [json.loads(line) for line in trace_text.splitlines()]
    assert trace[-1]["event_type"] == "omni_capture_failure"
    assert trace[-1]["failure_class"] == "adapter_transport_error"


def test_capture_persists_poll_exhaustion_and_rejects_reuse(tmp_path: Path) -> None:
    capture = OmniJobCapture(
        FakeOmniClient([{"state": "EXECUTING"}]),
        _store(tmp_path),
        maximum_status_checks=1,
        clock=iter((0.0, 0.1, 0.2, 0.3, 0.4)).__next__,
        sleep=lambda _: None,
        utc_now=lambda: "2026-08-27T12:00:00Z",
    )

    result = capture.probe("Public benchmark question")

    assert result.terminal_state == "POLL_EXHAUSTED"
    assert result.failure_class == "capture_poll_exhausted"
    with pytest.raises(OmniCaptureError, match="single use"):
        capture.probe("Public benchmark question")

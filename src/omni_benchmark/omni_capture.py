"""Public-only probe of Omni's production agent response and trace surface."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from .artifact_store import ArtifactStore, StoredArtifact
from .autoresearch_config import _canonical_bytes
from .autoresearch_runs import TRACE_SCHEMA_VERSION
from .content_policy import REDACTED, ContentPolicy
from .omni_result_adapter import (
    OmniResultContractError,
    ParsedOmniQuery,
    ParsedOmniResult,
    bind_typed_query_result,
    parse_omni_job_result,
    reject_forbidden_keys,
)

TERMINAL_STATES = frozenset({"CANCELLED", "COMPLETE", "DENIED", "FAILED"})


class OmniCaptureError(RuntimeError):
    """Raised when the production job contract cannot be captured faithfully."""


class OmniJobClient(Protocol):
    """The narrow production-agent transport consumed by the probe."""

    def whoami(self) -> dict[str, Any]: ...

    def submit_job(self, question: str) -> dict[str, Any]: ...

    def job_status(self, job_id: str) -> dict[str, Any]: ...

    def job_result(self, job_id: str) -> dict[str, Any]: ...

    def run_query_json(self, query: Mapping[str, Any]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class OmniProbeResult:
    """Private probe references; no answer values or correctness."""

    job_id: str | None
    terminal_state: str
    failure_class: str | None
    trace: StoredArtifact
    response_shape: StoredArtifact
    result_artifact: StoredArtifact | None
    generated_query: str | None
    semantic_objects: tuple[str, ...]
    tool_calls_by_name: tuple[tuple[str, int], ...]
    tool_call_count: int | None
    database_query_count: int | None
    validation_attempt_count: int | None
    started_at: str
    finished_at: str
    latency_ms: float


class _TransportCaptureError(OmniCaptureError):
    """Provider operation failed before producing a response."""


class _PollExhaustedError(OmniCaptureError):
    """The adapter exhausted its declared status-check policy."""


@dataclass(frozen=True)
class _CaptureOutcome:
    job_id: str | None
    terminal_state: str
    failure_class: str | None
    parsed_result: ParsedOmniResult | None
    result_artifact: StoredArtifact | None


class OmniJobCapture:
    """Submit, poll, and inspect shape without persisting provider response bodies."""

    def __init__(
        self,
        client: OmniJobClient,
        store: ArtifactStore,
        *,
        poll_schedule_seconds: tuple[float, ...] = (2.0, 5.0, 10.0),
        maximum_status_checks: int = 60,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        utc_now: Callable[[], str] | None = None,
    ) -> None:
        if maximum_status_checks < 1 or not poll_schedule_seconds:
            raise OmniCaptureError(
                "polling policy must permit at least one status check"
            )
        self._client = client
        self._store = store
        self._poll_schedule = poll_schedule_seconds
        self._maximum_status_checks = maximum_status_checks
        self._clock = clock
        self._sleep = sleep
        self._utc_now = _utc_now if utc_now is None else utc_now
        self._content_policy = ContentPolicy.from_environment({})
        self._events: list[dict[str, Any]] = []
        self._shapes: list[dict[str, Any]] = []
        self._origin: float | None = None
        self._last_observed: float | None = None
        self._started_at: str | None = None
        self._database_queries_observable = False
        self._parsed_query: ParsedOmniQuery | None = None
        self._used = False

    def probe(self, question: str) -> OmniProbeResult:
        """Run one fresh public question through the production job API."""
        self._start(question)
        outcome = self._capture(question)
        return self._finalize(outcome)

    def _start(self, question: str) -> None:
        if not isinstance(question, str) or not question.strip():
            raise OmniCaptureError("question must be a non-empty string")
        if self._used:
            raise OmniCaptureError("Omni job capture instances are single use")
        self._used = True
        self._started_at = self._utc_now()

    def _capture(self, question: str) -> _CaptureOutcome:
        job_id: str | None = None
        try:
            submitted = self._observe_mapping(
                "omni_job_submit", lambda: self._client.submit_job(question)
            )
            job_id = _required_path_string(
                submitted,
                (("jobId",), ("id",), ("job", "id")),
                "job identifier",
            )
            terminal_state = self._poll(job_id)
            if terminal_state == "COMPLETE":
                return self._capture_complete(job_id)
            return self._failure_outcome(
                job_id, terminal_state, "omni_job_terminal_failure"
            )
        except _PollExhaustedError:
            return self._failure_outcome(
                job_id, "POLL_EXHAUSTED", "capture_poll_exhausted"
            )
        except _TransportCaptureError:
            return self._failure_outcome(
                job_id, "ADAPTER_ERROR", "adapter_transport_error"
            )
        except (OmniCaptureError, OmniResultContractError):
            return self._failure_outcome(
                job_id, "CONTRACT_ERROR", "response_contract_error"
            )

    def _capture_complete(self, job_id: str) -> _CaptureOutcome:
        response = self._observe_mapping(
            "omni_job_result", lambda: self._client.job_result(job_id)
        )
        parsed_query = parse_omni_job_result(response)
        self._parsed_query = parsed_query
        self._record_agent_query_telemetry(parsed_query)
        self._database_queries_observable = True
        typed_rows = self._observe(
            "omni_query_run_json",
            lambda: self._client.run_query_json(parsed_query.semantic_query),
            database_query_delta=1,
        )
        parsed_result = bind_typed_query_result(parsed_query, typed_rows)
        result_artifact = self._store.write_json(
            "answer.result.json", parsed_result.as_result_artifact()
        )
        return _CaptureOutcome(job_id, "COMPLETE", None, parsed_result, result_artifact)

    def _failure_outcome(
        self, job_id: str | None, state: str, failure_class: str
    ) -> _CaptureOutcome:
        failure_delta: int | None = 0
        if not self._database_queries_observable:
            self._events = [
                {**event, "database_query_delta": None} for event in self._events
            ]
            failure_delta = None
        self._record_failure(failure_class, failure_delta)
        return _CaptureOutcome(job_id, state, failure_class, None, None)

    def _finalize(self, outcome: _CaptureOutcome) -> OmniProbeResult:
        trace = self._store.write_jsonl("attempt.trace.jsonl", self._events)
        response_shape = self._store.write_json(
            "response-shape.json",
            {"responses": self._shapes, "schema_version": 1},
        )
        latency_ms = self._elapsed_ms()
        parsed_result = outcome.parsed_result
        parsed_query = self._parsed_query
        return OmniProbeResult(
            job_id=outcome.job_id,
            terminal_state=outcome.terminal_state,
            failure_class=outcome.failure_class,
            trace=trace,
            response_shape=response_shape,
            result_artifact=outcome.result_artifact,
            generated_query=(
                parsed_result.generated_query
                if parsed_result is not None
                else None
                if parsed_query is None
                else parsed_query.generated_query
            ),
            semantic_objects=(
                parsed_result.semantic_objects
                if parsed_result is not None
                else ()
                if parsed_query is None
                else parsed_query.semantic_objects
            ),
            tool_calls_by_name=(),
            tool_call_count=None,
            database_query_count=self._database_query_count(parsed_result),
            validation_attempt_count=None,
            started_at=self._started_at,
            finished_at=_timestamp_after(self._started_at, latency_ms),
            latency_ms=latency_ms,
        )

    def _poll(self, job_id: str) -> str:
        for check_number in range(self._maximum_status_checks):
            status = self._observe_mapping(
                "omni_job_status", lambda: self._client.job_status(job_id)
            )
            state = _required_path_string(
                status,
                (("state",), ("status",), ("job", "state"), ("job", "status")),
                "job state",
            ).upper()
            if state in TERMINAL_STATES:
                return state
            delay = self._poll_schedule[min(check_number, len(self._poll_schedule) - 1)]
            self._sleep(delay)
        raise _PollExhaustedError("Omni job did not reach a terminal state")

    def _observe_mapping(
        self, event_type: str, operation: Callable[[], Any]
    ) -> Mapping[str, Any]:
        value = self._observe(event_type, operation)
        if not isinstance(value, Mapping):
            raise OmniCaptureError("Omni provider response must be an object")
        return value

    def _observe(
        self,
        event_type: str,
        operation: Callable[[], Any],
        *,
        database_query_delta: int = 0,
    ) -> Any:
        started = self._clock()
        if self._origin is None:
            self._origin = started
        try:
            response = operation()
        except Exception as error:
            finished = self._clock()
            self._last_observed = finished
            transport_delta: int | None = database_query_delta
            if database_query_delta:
                self._database_queries_observable = False
                transport_delta = None
            self._record_transport_failure(
                event_type, started, finished, transport_delta
            )
            raise _TransportCaptureError("Omni provider operation failed") from error
        finished = self._clock()
        self._last_observed = finished
        try:
            reject_forbidden_keys(response)
        except OmniResultContractError as error:
            self._record_rejected_response(event_type, finished, database_query_delta)
            raise OmniCaptureError(
                "Omni provider response contains forbidden fields"
            ) from error
        self._record_response(
            event_type, response, started, finished, database_query_delta
        )
        return response

    def _record_response(
        self,
        event_type: str,
        response: Any,
        started: float,
        finished: float,
        database_query_delta: int,
    ) -> None:
        response_sha256 = hashlib.sha256(_canonical_bytes(response)).hexdigest()
        status = _optional_state(response) if isinstance(response, Mapping) else None
        status = status or "ok"
        self._append_observation(
            self._response_event(
                event_type,
                response_sha256,
                status,
                started,
                finished,
                database_query_delta,
            ),
            {
                "event_type": event_type,
                "response_sha256": response_sha256,
                "shape": _json_shape(response, content_policy=self._content_policy),
            },
        )

    def _response_event(
        self,
        event_type: str,
        digest: str,
        status: str,
        started: float,
        finished: float,
        database_query_delta: int,
    ) -> dict[str, Any]:
        elapsed_ms = (finished - self._origin_or_error()) * 1000
        failure = (
            "omni_job_terminal_failure"
            if status.upper() in TERMINAL_STATES - {"COMPLETE"}
            else None
        )
        return {
            "component": "benchmark-adapter",
            "database_query_delta": database_query_delta,
            "duration_ms": (finished - started) * 1000,
            "elapsed_ms": elapsed_ms,
            "event_type": event_type,
            "failure_class": failure,
            "input_tokens": None,
            "metadata_sha256": digest,
            "model": None,
            "output_tokens": None,
            "provider": None,
            "retry_delta": None,
            "schema_version": TRACE_SCHEMA_VERSION,
            "seq": len(self._events),
            "status": status,
            "timestamp": _timestamp_after(self._started_at_or_error(), elapsed_ms),
            "tool_call_delta": None,
            "tool_name": _tool_name(event_type),
            "validation_attempt_delta": None,
        }

    def _append_observation(self, event: dict[str, Any], shape: dict[str, Any]) -> None:
        self._events.append(event)
        self._shapes.append(shape)

    def _record_rejected_response(
        self, event_type: str, finished: float, database_query_delta: int
    ) -> None:
        digest = hashlib.sha256(b"forbidden-provider-response").hexdigest()
        elapsed_ms = (finished - self._origin_or_error()) * 1000
        self._append_observation(
            self._diagnostic_event(
                event_type,
                "response_contract_error",
                elapsed_ms,
                digest,
                database_query_delta,
            ),
            {
                "event_type": event_type,
                "response_sha256": digest,
                "shape": {"type": "rejected"},
            },
        )

    def _record_failure(
        self, failure_class: str, database_query_delta: int | None
    ) -> None:
        observed = self._last_observed
        if observed is None:
            observed = self._clock()
        if self._origin is None:
            self._origin = observed
        self._last_observed = observed
        digest = hashlib.sha256(failure_class.encode()).hexdigest()
        elapsed_ms = (observed - self._origin) * 1000
        self._append_observation(
            self._diagnostic_event(
                "omni_capture_failure",
                failure_class,
                elapsed_ms,
                digest,
                database_query_delta,
            ),
            {
                "event_type": "omni_capture_failure",
                "failure_class": failure_class,
                "response_sha256": digest,
                "shape": {"type": "error"},
            },
        )

    def _record_transport_failure(
        self,
        event_type: str,
        started: float,
        finished: float,
        database_query_delta: int | None,
    ) -> None:
        digest = hashlib.sha256(b"provider-transport-failure").hexdigest()
        elapsed_ms = (finished - self._origin_or_error()) * 1000
        self._append_observation(
            self._diagnostic_event(
                event_type,
                "adapter_transport_error",
                elapsed_ms,
                digest,
                database_query_delta,
            ),
            {
                "event_type": event_type,
                "response_sha256": digest,
                "shape": {"type": "transport_error"},
            },
        )

    def _diagnostic_event(
        self,
        event_type: str,
        failure_class: str,
        elapsed_ms: float,
        digest: str,
        database_query_delta: int | None,
    ) -> dict[str, Any]:
        return {
            "component": "benchmark-adapter",
            "database_query_delta": database_query_delta,
            "duration_ms": 0.0,
            "elapsed_ms": elapsed_ms,
            "event_type": event_type,
            "failure_class": failure_class,
            "input_tokens": None,
            "metadata_sha256": digest,
            "model": None,
            "output_tokens": None,
            "provider": None,
            "retry_delta": None,
            "schema_version": TRACE_SCHEMA_VERSION,
            "seq": len(self._events),
            "status": "error",
            "timestamp": _timestamp_after(self._started_at_or_error(), elapsed_ms),
            "tool_call_delta": None,
            "tool_name": _tool_name(event_type),
            "validation_attempt_delta": None,
        }

    def _record_agent_query_telemetry(self, result: ParsedOmniQuery) -> None:
        if not self._events or self._events[-1]["event_type"] != "omni_job_result":
            raise OmniCaptureError("result telemetry has no matching trace event")
        final_event = {
            **self._events[-1],
            "database_query_delta": result.agent_database_query_count,
        }
        self._events = [*self._events[:-1], final_event]
        current_shape = self._shapes[-1]
        self._shapes[-1] = {
            **current_shape,
            "observed_actions_by_type": dict(result.observed_actions_by_type),
        }

    def _database_query_count(
        self, parsed_result: ParsedOmniResult | None
    ) -> int | None:
        if parsed_result is not None:
            return parsed_result.database_query_count
        if not self._database_queries_observable:
            return None
        deltas = [event["database_query_delta"] for event in self._events]
        if any(delta is None for delta in deltas):
            raise OmniCaptureError("observable database-query trace is incomplete")
        return sum(deltas)

    def _elapsed_ms(self) -> float:
        if self._origin is None or self._last_observed is None:
            raise OmniCaptureError("capture produced no observable events")
        return (self._last_observed - self._origin) * 1000

    def _started_at_or_error(self) -> str:
        if self._started_at is None:
            raise OmniCaptureError("capture start time is unavailable")
        return self._started_at

    def _origin_or_error(self) -> float:
        if self._origin is None:
            raise OmniCaptureError("capture origin is unavailable")
        return self._origin


def _required_path_string(
    value: Mapping[str, Any], paths: tuple[tuple[str, ...], ...], description: str
) -> str:
    for path in paths:
        current: Any = value
        for component in path:
            if not isinstance(current, Mapping) or component not in current:
                break
            current = current[component]
        else:
            if isinstance(current, str) and current:
                return current
    raise OmniCaptureError(f"Omni response did not expose a {description}")


def _optional_state(value: Mapping[str, Any]) -> str | None:
    try:
        return _required_path_string(
            value,
            (("state",), ("status",), ("job", "state"), ("job", "status")),
            "job state",
        )
    except OmniCaptureError:
        return None


def _tool_name(event_type: str) -> str | None:
    if event_type == "omni_capture_failure":
        return None
    if event_type == "omni_query_run_json":
        return "omni.query.run"
    action = event_type.removeprefix("omni_job_").replace("_", "-")
    return f"omni.ai.{action}"


def _json_shape(
    value: Any, *, content_policy: ContentPolicy, depth: int = 0
) -> dict[str, Any]:
    if depth >= 12:
        return {"type": "depth_limit"}
    if isinstance(value, dict):
        return {
            "fields": {
                (
                    REDACTED
                    if content_policy.field_name_is_sensitive(str(key))
                    else str(key)
                ): _json_shape(item, content_policy=content_policy, depth=depth + 1)
                for key, item in sorted(value.items(), key=lambda item: str(item[0]))
            },
            "type": "object",
        }
    if isinstance(value, list):
        samples = [
            _json_shape(item, content_policy=content_policy, depth=depth + 1)
            for item in value[:3]
        ]
        return {"length": len(value), "samples": samples, "type": "array"}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    return {"type": "string"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_after(started_at: str, elapsed_ms: float) -> str:
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise OmniCaptureError("capture clock returned an invalid timestamp") from error
    if started.tzinfo is None:
        raise OmniCaptureError("capture clock timestamp must include a timezone")
    return (
        (started + timedelta(milliseconds=elapsed_ms))
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

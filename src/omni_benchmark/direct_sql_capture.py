from __future__ import annotations

import hashlib
import math
import os
import time
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from .artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from .autoresearch_artifacts import TRACE_SCHEMA_VERSION
from .autoresearch_config import _canonical_bytes
from .content_policy import ContentPolicy
from .direct_sql_result import (
    DirectExecution,
    DirectResultError,
    adapt_query_result,
    capture_receipt_payload,
    database_failure,
    validate_json_value,
)
from .omni_result_adapter import OmniResultContractError, reject_forbidden_keys
from .postgres_execution import (
    PostgreSQLConnection,
    PostgreSQLExecutionError,
    execute_query_sequence,
)
from .sql_admission import query_sql_is_admissible

DirectCondition = Literal["C1", "C2", "C3"]
GenerationOutcome = Literal["answered", "refused", "errored"]
_REFUSAL_REASONS = frozenset({"cannot_answer_safely", "insufficient_information"})
_TOOL_NAMES = {
    "C1": ("inspect_schema", "execute_sql"),
    "C2": ("inspect_schema", "search_hkb", "execute_sql"),
    "C3": ("inspect_schema", "search_semantic_model", "execute_sql"),
}


class DirectCaptureError(RuntimeError):
    """Raised when a direct comparator cannot be configured safely."""


class DirectModelTransport(Protocol):
    """One provider adapter turn; the harness owns conversation and tools."""

    def next_turn(
        self,
        messages: tuple[Mapping[str, Any], ...],
        tool_specs: tuple[Mapping[str, Any], ...],
    ) -> DirectModelTurn: ...


class DirectDatabaseTransport(Protocol):
    """A factory whose role/function audit contains Query-only SQL side effects."""

    @property
    def execution_attestation(self) -> DirectDatabaseAttestation: ...

    def connect(self) -> PostgreSQLConnection: ...


@dataclass(frozen=True)
class DirectModelTurn:
    """A structured model action plus authoritative provider telemetry."""

    action: Mapping[str, Any]
    input_tokens: int | None = None
    output_tokens: int | None = None
    retry_count: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class DirectReferenceResult:
    """Public reference payload with optional semantic-object provenance."""

    payload: Any
    semantic_objects: tuple[str, ...] = ()


@dataclass(frozen=True)
class DirectDatabaseAttestation:
    """External audit assertions required because AST admission is not a sandbox."""

    role_is_read_only: bool
    no_execute_on_non_system_functions: bool


@dataclass(frozen=True)
class DirectProbeResult:
    """Unscored comparator output and measured attempt telemetry."""

    condition: DirectCondition
    attempt_id: str
    maximum_turns: int
    question_sha256: str
    generation_outcome: GenerationOutcome
    failure_class: str | None
    trace: StoredArtifact
    receipt: StoredArtifact
    result_artifact: StoredArtifact | None
    generated_sql: str | None
    semantic_objects: tuple[str, ...]
    tool_calls_by_name: tuple[tuple[str, int], ...]
    tool_call_count: int
    database_query_count: int | None
    validation_attempt_count: int
    retry_count: int | None
    token_usage: dict[str, int] | None
    token_source: str
    cost_usd: float | None
    cost_source: str
    provider: str
    model: str
    started_at: str
    finished_at: str
    latency_ms: float


@dataclass(frozen=True)
class _ToolAction:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class _AnswerAction:
    sql: str


@dataclass(frozen=True)
class _RefusalAction:
    reason: str


class DirectSqlCapture:
    """Run one comparator attempt with condition-locked public tools."""

    def __init__(
        self,
        *,
        condition: str,
        model_transport: DirectModelTransport,
        database: DirectDatabaseTransport,
        inspect_schema: Callable[[], DirectReferenceResult],
        search_hkb: Callable[[str], DirectReferenceResult] | None,
        search_semantic_model: Callable[[str], DirectReferenceResult] | None,
        store: ArtifactStore,
        provider: str,
        model: str,
        maximum_turns: int = 12,
        clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], str] | None = None,
    ) -> None:
        self._condition = _validate_configuration(
            condition, search_hkb, search_semantic_model, maximum_turns
        )
        self._model_transport = model_transport
        self._database = _validate_database_transport(database)
        self._inspect_schema = inspect_schema
        self._search_hkb = search_hkb
        self._search_semantic_model = search_semantic_model
        self._store = store
        self._provider = _identifier(provider, "provider")
        self._model = _identifier(model, "model")
        self._maximum_turns = maximum_turns
        self._clock = clock
        self._utc_now = _utc_now if utc_now is None else utc_now
        self._policy = ContentPolicy.from_environment(os.environ)
        self._events: list[dict[str, Any]] = []
        self._messages: list[Mapping[str, Any]] = []
        self._turns: list[DirectModelTurn] = []
        self._tools: Counter[str] = Counter()
        self._semantic_objects: set[str] = set()
        self._database_query_count: int | None = 0
        self._origin = 0.0
        self._started_at = ""
        self._question_sha256 = ""
        self._used = False

    def capture(self, question: str, *, attempt_id: str) -> DirectProbeResult:
        """Run one fresh public question and always persist a terminal trace."""
        self._start(question)
        attempt_id = _identifier(attempt_id, "attempt_id")
        outcome, failure, sql, result_artifact = self._run_turns()
        latency_ms = max(0.0, (self._clock() - self._origin) * 1000)
        self._normalize_unavailable_trace_telemetry()
        trace = self._store.write_jsonl(Path("attempt.trace.jsonl"), self._events)
        receipt = self._write_receipt(attempt_id, sql, trace, result_artifact)
        return self._probe_result(
            attempt_id,
            outcome,
            failure,
            sql,
            result_artifact,
            trace,
            receipt,
            latency_ms,
        )

    def _write_receipt(
        self,
        attempt_id: str,
        sql: str | None,
        trace: StoredArtifact,
        result: StoredArtifact | None,
    ) -> StoredArtifact:
        return self._store.write_json(
            Path("capture.receipt.json"),
            capture_receipt_payload(
                store=self._store,
                attempt_id=attempt_id,
                condition=self._condition,
                question_sha256=self._question_sha256,
                provider=self._provider,
                model=self._model,
                maximum_turns=self._maximum_turns,
                sql=sql,
                trace=trace,
                result=result,
            ),
        )

    def _start(self, question: str) -> None:
        if self._used:
            raise DirectCaptureError("direct SQL capture instances are single use")
        if not isinstance(question, str) or not question.strip():
            raise DirectCaptureError("question must be a non-empty string")
        if not self._policy.query_is_safe(question):
            raise DirectCaptureError("question contains sensitive content")
        self._used = True
        self._origin = self._clock()
        self._started_at = self._utc_now()
        self._question_sha256 = hashlib.sha256(question.encode("utf-8")).hexdigest()
        self._messages.append({"role": "user", "content": question})

    def _run_turns(
        self,
    ) -> tuple[GenerationOutcome, str | None, str | None, StoredArtifact | None]:
        for _ in range(self._maximum_turns):
            turn = self._next_turn()
            if turn is None:
                return self._terminal_error("model_transport_error")
            try:
                action = _parse_action(turn.action)
            except (DirectCaptureError, OmniResultContractError):
                return self._terminal_error("invalid_model_action")
            self._messages.append({"role": "assistant", "content": dict(turn.action)})
            if isinstance(action, _ToolAction):
                failure = self._dispatch_tool(action)
                if failure is not None:
                    return self._terminal_error(failure)
                continue
            if isinstance(action, _RefusalAction):
                self._append_terminal("direct_refusal", "DENIED", "agent_refusal")
                return "refused", "agent_refusal", None, None
            return self._finish_answer(action.sql)
        return self._terminal_error("turn_limit_exhausted")

    def _next_turn(self) -> DirectModelTurn | None:
        started = self._clock()
        try:
            reject_forbidden_keys(self._messages)
            if self._policy.sanitize_json(self._messages) != self._messages:
                raise DirectCaptureError("outbound messages contain sensitive content")
            turn = self._model_transport.next_turn(
                tuple(self._messages), _tool_specs(self._condition)
            )
            _validate_turn(turn)
            reject_forbidden_keys(turn.action)
            if self._policy.sanitize_json(dict(turn.action)) != dict(turn.action):
                raise DirectCaptureError("model action contains sensitive content")
        except Exception:
            self._append_event(
                event_type="direct_model_turn",
                status="ERROR",
                started=started,
                failure_class="model_transport_error",
            )
            return None
        self._turns.append(turn)
        self._append_event(
            event_type="direct_model_turn",
            status="SUCCESS",
            started=started,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            retry_delta=turn.retry_count,
        )
        return turn

    def _dispatch_tool(self, action: _ToolAction) -> str | None:
        if action.name not in _TOOL_NAMES[self._condition]:
            return "unauthorized_tool"
        started = self._clock()
        self._tools[action.name] += 1
        if action.name == "execute_sql":
            return self._dispatch_database_tool(action, started)
        try:
            result = self._tool_result(action)
            _validate_reference_result(result, self._policy)
            if result.semantic_objects and not (
                self._condition == "C3" and action.name == "search_semantic_model"
            ):
                raise DirectCaptureError(
                    "semantic objects require C3 semantic-model search provenance"
                )
        except OmniResultContractError:
            self._append_tool_event(
                action.name, started, "ERROR", "forbidden_tool_payload"
            )
            return "forbidden_tool_payload"
        except Exception:
            self._append_tool_event(
                action.name, started, "ERROR", "tool_execution_error"
            )
            return "tool_execution_error"
        self._semantic_objects.update(result.semantic_objects)
        self._messages.append(
            {"role": "tool", "name": action.name, "content": result.payload}
        )
        self._append_tool_event(action.name, started, "SUCCESS", None)
        return None

    def _dispatch_database_tool(
        self, action: _ToolAction, started: float
    ) -> str | None:
        execution = self._execute_sql(action.arguments["sql"])
        try:
            reject_forbidden_keys(execution.payload)
            validate_json_value(execution.payload)
            if self._policy.sanitize_json(execution.payload) != execution.payload:
                raise DirectCaptureError(
                    "database tool payload contains sensitive content"
                )
        except (DirectCaptureError, DirectResultError, OmniResultContractError):
            self._append_tool_event(
                action.name, started, "ERROR", "forbidden_tool_payload"
            )
            return "forbidden_tool_payload"
        self._messages.append(
            {"role": "tool", "name": action.name, "content": execution.payload}
        )
        status = "ERROR" if execution.failure_class is not None else "SUCCESS"
        self._append_tool_event(action.name, started, status, execution.failure_class)
        return None

    def _tool_result(self, action: _ToolAction) -> DirectReferenceResult:
        if action.name == "inspect_schema":
            return self._inspect_schema()
        if action.name == "search_hkb":
            if self._search_hkb is None:
                raise DirectCaptureError("HKB search is unavailable")
            return self._search_hkb(action.arguments["query"])
        if action.name == "search_semantic_model":
            if self._search_semantic_model is None:
                raise DirectCaptureError("semantic-model search is unavailable")
            return self._search_semantic_model(action.arguments["query"])
        raise DirectCaptureError("tool is not a public reference tool")

    def _execute_sql(self, sql: str) -> DirectExecution:
        if not self._policy.query_is_safe(sql) or not query_sql_is_admissible(sql):
            return DirectExecution(
                {"failure_class": "sql_not_admitted", "status": "error"},
                None,
                "sql_not_admitted",
            )
        try:
            connection = self._database.connect()
        except Exception:
            return database_failure("database_infrastructure_error")
        try:
            result = execute_query_sequence(connection, sql, read_only=True)
            self._record_database_queries(result.statement_count)
            execution = adapt_query_result(result)
        except PostgreSQLExecutionError as error:
            self._record_database_queries(max(1, error.statement_index + 1))
            execution = database_failure(f"database_{error.kind}_error")
        except Exception:
            self._database_query_count = None
            execution = database_failure("database_infrastructure_error")
        try:
            connection.close()
        except Exception:
            return database_failure("database_infrastructure_error")
        return execution

    def _finish_answer(
        self, sql: str
    ) -> tuple[GenerationOutcome, str | None, str | None, StoredArtifact | None]:
        started = self._clock()
        execution = self._execute_sql(sql)
        generated_sql = None if execution.failure_class == "sql_not_admitted" else sql
        if execution.failure_class is not None:
            self._append_final_execution(started, "ERROR", execution.failure_class)
            return "errored", execution.failure_class, generated_sql, None
        if execution.result is None or execution.result.rows is None:
            self._append_final_execution(started, "ERROR", "candidate_no_result")
            return "errored", "candidate_no_result", generated_sql, None
        if execution.result.row_limit_exceeded:
            self._append_final_execution(started, "ERROR", "candidate_result_overflow")
            return "errored", "candidate_result_overflow", generated_sql, None
        try:
            reject_forbidden_keys(execution.payload)
            if self._policy.sanitize_json(execution.payload) != execution.payload:
                raise ArtifactStoreError("result artifact contains sensitive content")
            artifact = self._store.write_json(
                Path("answer.result.json"), execution.payload
            )
        except OmniResultContractError:
            self._append_final_execution(started, "ERROR", "forbidden_result_payload")
            return "errored", "forbidden_result_payload", sql, None
        except ArtifactStoreError:
            self._append_final_execution(started, "ERROR", "result_artifact_rejected")
            return "errored", "result_artifact_rejected", sql, None
        self._append_final_execution(started, "COMPLETE", None)
        return "answered", None, sql, artifact

    def _terminal_error(
        self, failure: str
    ) -> tuple[GenerationOutcome, str, None, None]:
        if not self._events or self._events[-1]["failure_class"] != failure:
            self._append_terminal("direct_capture_failure", "ERROR", failure)
        return "errored", failure, None, None

    def _append_tool_event(
        self, name: str, started: float, status: str, failure: str | None
    ) -> None:
        database_delta = 0
        if name == "execute_sql" and failure != "sql_not_admitted":
            database_delta = self._last_database_delta()
        self._append_event(
            event_type="direct_tool_dispatch",
            status=status,
            started=started,
            tool_call_delta=1,
            tool_name=name,
            database_query_delta=database_delta,
            failure_class=failure,
        )

    def _append_final_execution(
        self, started: float, status: str, failure: str | None
    ) -> None:
        self._append_event(
            event_type="direct_final_sql_execution",
            status=status,
            started=started,
            tool_name="execute_sql",
            database_query_delta=self._last_database_delta(),
            failure_class=failure,
        )

    def _record_database_queries(self, count: int) -> None:
        if self._database_query_count is not None:
            self._database_query_count += count

    def _last_database_delta(self) -> int | None:
        if self._database_query_count is None:
            return None
        observed = sum(event["database_query_delta"] for event in self._events)
        return self._database_query_count - observed

    def _append_terminal(self, event_type: str, status: str, failure: str) -> None:
        now = self._clock()
        self._append_event(
            event_type=event_type,
            status=status,
            started=now,
            failure_class=failure,
        )

    def _append_event(
        self,
        *,
        event_type: str,
        status: str,
        started: float,
        failure_class: str | None = None,
        tool_call_delta: int = 0,
        tool_name: str | None = None,
        database_query_delta: int | None = 0,
        input_tokens: int | None = 0,
        output_tokens: int | None = 0,
        retry_delta: int | None = 0,
    ) -> None:
        finished = self._clock()
        elapsed_ms = max(0.0, (finished - self._origin) * 1000)
        self._events.append(
            {
                "component": "direct-sql-harness",
                "database_query_delta": database_query_delta,
                "duration_ms": max(0.0, (finished - started) * 1000),
                "elapsed_ms": elapsed_ms,
                "event_type": event_type,
                "failure_class": failure_class,
                "input_tokens": input_tokens,
                "metadata_sha256": _event_digest(event_type, status, len(self._events)),
                "model": self._model,
                "output_tokens": output_tokens,
                "provider": self._provider,
                "retry_delta": retry_delta,
                "schema_version": TRACE_SCHEMA_VERSION,
                "seq": len(self._events),
                "status": status,
                "timestamp": _timestamp_after(self._started_at, elapsed_ms),
                "tool_call_delta": tool_call_delta,
                "tool_name": tool_name,
                "validation_attempt_delta": 0,
            }
        )

    def _normalize_unavailable_trace_telemetry(self) -> None:
        tokens_available = bool(self._turns) and all(
            turn.input_tokens is not None and turn.output_tokens is not None
            for turn in self._turns
        )
        retries_available = bool(self._turns) and all(
            turn.retry_count is not None for turn in self._turns
        )
        self._events = [
            {
                **event,
                "input_tokens": event["input_tokens"] if tokens_available else None,
                "output_tokens": event["output_tokens"] if tokens_available else None,
                "retry_delta": event["retry_delta"] if retries_available else None,
                "database_query_delta": (
                    event["database_query_delta"]
                    if self._database_query_count is not None
                    else None
                ),
            }
            for event in self._events
        ]

    def _probe_result(
        self,
        attempt_id: str,
        outcome: GenerationOutcome,
        failure: str | None,
        sql: str | None,
        result_artifact: StoredArtifact | None,
        trace: StoredArtifact,
        receipt: StoredArtifact,
        latency_ms: float,
    ) -> DirectProbeResult:
        token_usage = _token_usage(self._turns)
        cost = _cost(self._turns)
        return DirectProbeResult(
            condition=self._condition,
            attempt_id=attempt_id,
            maximum_turns=self._maximum_turns,
            question_sha256=self._question_sha256,
            generation_outcome=outcome,
            failure_class=failure,
            trace=trace,
            receipt=receipt,
            result_artifact=result_artifact,
            generated_sql=sql,
            semantic_objects=tuple(sorted(self._semantic_objects)),
            tool_calls_by_name=tuple(sorted(self._tools.items())),
            tool_call_count=sum(self._tools.values()),
            database_query_count=self._database_query_count,
            validation_attempt_count=0,
            retry_count=_retry_count(self._turns),
            token_usage=token_usage,
            token_source="provider_reported"
            if token_usage is not None
            else "unavailable",
            cost_usd=cost,
            cost_source="provider_reported" if cost is not None else "unavailable",
            provider=self._provider,
            model=self._model,
            started_at=self._started_at,
            finished_at=_timestamp_after(self._started_at, latency_ms),
            latency_ms=latency_ms,
        )


def _validate_configuration(
    condition: str,
    search_hkb: Callable[[str], DirectReferenceResult] | None,
    search_semantic_model: Callable[[str], DirectReferenceResult] | None,
    maximum_turns: int,
) -> DirectCondition:
    if condition not in _TOOL_NAMES:
        raise DirectCaptureError("condition must be C1, C2, or C3")
    if type(maximum_turns) is not int or maximum_turns < 1:
        raise DirectCaptureError("maximum_turns must be a positive integer")
    if condition == "C1" and (
        search_hkb is not None or search_semantic_model is not None
    ):
        raise DirectCaptureError("C1 cannot expose HKB or semantic-model search")
    if condition == "C2" and (search_hkb is None or search_semantic_model is not None):
        raise DirectCaptureError(
            "C2 requires HKB search and forbids semantic-model search"
        )
    if condition == "C3" and (search_semantic_model is None or search_hkb is not None):
        raise DirectCaptureError(
            "C3 requires semantic-model search and forbids HKB search"
        )
    return condition  # type: ignore[return-value]


def _validate_database_transport(
    database: DirectDatabaseTransport,
) -> DirectDatabaseTransport:
    try:
        attestation = database.execution_attestation
    except Exception as error:
        raise DirectCaptureError(
            "database execution attestation is required"
        ) from error
    required = DirectDatabaseAttestation(True, True)
    if (
        not isinstance(attestation, DirectDatabaseAttestation)
        or attestation != required
    ):
        raise DirectCaptureError("database execution attestation is incomplete")
    return database


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DirectCaptureError(f"{field} must be a non-empty string")
    return value


def _tool_specs(condition: DirectCondition) -> tuple[Mapping[str, Any], ...]:
    definitions = {
        "inspect_schema": ("Inspect the public database schema.", {}),
        "search_hkb": (
            "Search the public database-level business knowledge base.",
            {"query": {"type": "string"}},
        ),
        "search_semantic_model": (
            "Search the public Omni semantic-model representation.",
            {"query": {"type": "string"}},
        ),
        "execute_sql": (
            "Execute admitted Query-only SQL using a read-only transaction.",
            {"sql": {"type": "string"}},
        ),
    }
    return tuple(
        {
            "description": definitions[name][0],
            "input_schema": {
                "additionalProperties": False,
                "properties": definitions[name][1],
                "required": list(definitions[name][1]),
                "type": "object",
            },
            "name": name,
        }
        for name in _TOOL_NAMES[condition]
    )


def _validate_turn(turn: object) -> None:
    if not isinstance(turn, DirectModelTurn) or not isinstance(turn.action, Mapping):
        raise DirectCaptureError("model turn must use the strict transport contract")
    for value, field in (
        (turn.input_tokens, "input_tokens"),
        (turn.output_tokens, "output_tokens"),
        (turn.retry_count, "retry_count"),
    ):
        if value is not None and (type(value) is not int or value < 0):
            raise DirectCaptureError(f"{field} must be a non-negative integer or null")
    if turn.cost_usd is not None and (
        isinstance(turn.cost_usd, bool)
        or not isinstance(turn.cost_usd, (int, float))
        or turn.cost_usd < 0
        or not math.isfinite(turn.cost_usd)
    ):
        raise DirectCaptureError("cost_usd must be a non-negative number or null")


def _parse_action(
    action: Mapping[str, Any],
) -> _ToolAction | _AnswerAction | _RefusalAction:
    action_type = action.get("type")
    if action_type == "tool":
        if set(action) != {"type", "name", "arguments"}:
            raise DirectCaptureError("tool action must use the exact schema")
        return _parse_tool_action(action)
    if action_type == "answer":
        if set(action) != {"type", "sql"} or not _nonempty(action.get("sql")):
            raise DirectCaptureError("answer action must contain only non-empty SQL")
        return _AnswerAction(action["sql"])
    if action_type == "refuse":
        if (
            set(action) != {"type", "reason"}
            or action.get("reason") not in _REFUSAL_REASONS
        ):
            raise DirectCaptureError("refusal action must use an allowed reason")
        return _RefusalAction(action["reason"])
    raise DirectCaptureError("model action type is invalid")


def _parse_tool_action(action: Mapping[str, Any]) -> _ToolAction:
    name = action.get("name")
    arguments = action.get("arguments")
    if not isinstance(name, str) or not isinstance(arguments, Mapping):
        raise DirectCaptureError("tool action name and arguments are invalid")
    expected = {
        "inspect_schema": set(),
        "search_hkb": {"query"},
        "search_semantic_model": {"query"},
        "execute_sql": {"sql"},
    }
    if name not in expected or set(arguments) != expected[name]:
        raise DirectCaptureError("tool arguments do not match the strict schema")
    if any(not _nonempty(value) for value in arguments.values()):
        raise DirectCaptureError("tool string arguments must be non-empty")
    return _ToolAction(name, dict(arguments))


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_reference_result(
    result: DirectReferenceResult, policy: ContentPolicy
) -> None:
    if not isinstance(result, DirectReferenceResult):
        raise DirectCaptureError("reference tool must return DirectReferenceResult")
    reject_forbidden_keys(result.payload)
    validate_json_value(result.payload)
    if policy.sanitize_json(result.payload) != result.payload:
        raise DirectCaptureError("reference tool payload contains sensitive content")
    if any(
        not isinstance(value, str) or not value or not policy.identifier_is_safe(value)
        for value in result.semantic_objects
    ):
        raise DirectCaptureError("semantic object identifiers are invalid")


def _token_usage(turns: list[DirectModelTurn]) -> dict[str, int] | None:
    if not turns or any(
        turn.input_tokens is None or turn.output_tokens is None for turn in turns
    ):
        return None
    input_tokens = sum(
        turn.input_tokens for turn in turns if turn.input_tokens is not None
    )
    output_tokens = sum(
        turn.output_tokens for turn in turns if turn.output_tokens is not None
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def _retry_count(turns: list[DirectModelTurn]) -> int | None:
    if not turns or any(turn.retry_count is None for turn in turns):
        return None
    return sum(turn.retry_count for turn in turns if turn.retry_count is not None)


def _cost(turns: list[DirectModelTurn]) -> float | None:
    if not turns or any(turn.cost_usd is None for turn in turns):
        return None
    total = sum(turn.cost_usd for turn in turns if turn.cost_usd is not None)
    if not math.isfinite(total):
        raise DirectCaptureError("provider cost aggregate is non-finite")
    return total


def _event_digest(event_type: str, status: str, seq: int) -> str:
    return hashlib.sha256(
        _canonical_bytes({"event_type": event_type, "seq": seq, "status": status})
    ).hexdigest()


def _timestamp_after(started_at: str, elapsed_ms: float) -> str:
    parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return (
        (parsed + timedelta(milliseconds=elapsed_ms))
        .astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

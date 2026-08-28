from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from time import monotonic as _monotonic
from typing import Any

from .artifact_store import ArtifactStoreError, StoredArtifact
from .autoresearch_artifacts import TRACE_SCHEMA_VERSION
from .content_policy import ContentPolicy
from .direct_action_evidence import (
    DirectActionEvidence,
    DirectActionEvidenceError,
    action_evidence_payload,
    public_ids_from_reference,
    tool_action_evidence,
    validate_action_evidence_input,
)
from .direct_action_protocol import (
    DIRECT_TOOL_NAMES,
    DirectActionProtocolError,
    DirectRefusalAction,
    DirectToolAction,
    direct_tool_specs,
    parse_direct_action,
)
from .direct_capture_binding import (
    DirectCaptureBindingError,
    DirectDatabaseBindingError,
    DirectModelBindingError,
    DirectReferenceBindingError,
    require_database_identity,
    require_model_identity,
    require_public_identity,
    require_runtime_boundaries,
)
from .direct_capture_contract import (
    DirectCondition as DirectCondition,
    DirectDatabaseAttestation,
    DirectModelFailure,
    DirectModelFailureObservation,
    DirectModelTurn,
    DirectModelTurnProvenance,
    DirectProbeResult,
    DirectReferenceResult,
    GenerationOutcome,
)
from .direct_capture_receipt import capture_receipt_payload, capture_summary_payload
from .direct_capture_validation import (
    DirectCaptureError,
    event_digest as _event_digest,
    validate_reference_result as _validate_reference_result,
    validate_turn as _validate_turn,
)
from .direct_capture_telemetry import (
    DirectProbeTelemetry as _ProbeTelemetry,
    failure_origin as _failure_origin,
    timestamp_after as _timestamp_after,
    utc_now as _utc_now,
)
from .direct_model_observability import (
    cost as model_cost,
    reduce_turn_provenance,
    retry_count as model_retry_count,
    token_usage as model_token_usage,
)
from .direct_prepared_attempt import (
    DirectPreparedAttempt,
    DirectPreparedAttemptError,
    validate_direct_prepared_attempt,
)
from .direct_sql_result import (
    DirectExecution,
    DirectResultError,
    adapt_query_result,
    database_failure,
    validate_json_value,
)
from .omni_result_adapter import OmniResultContractError, reject_forbidden_keys
from .postgres_execution import (
    PostgreSQLExecutionError,
    execute_query_sequence,
)
from .sql_admission import single_query_sql_is_admissible

_MODEL_FAILURE_CLASSES = {
    "auth": "model_auth_error",
    "budget": "model_budget_error",
    "infrastructure": "model_infrastructure_error",
    "model_identity": "model_identity_mismatch",
    "protocol": "model_protocol_error",
    "quota": "model_quota_error",
    "rate_limit": "model_rate_limit_error",
    "setup": "model_setup_error",
    "structured_output": "model_structured_output_error",
    "timeout": "model_timeout_error",
    "tool_surface": "model_tool_surface_error",
}
_TERMINAL_DATABASE_FAILURES = frozenset(
    {"database_identity_mismatch", "database_infrastructure_error"}
)
__all__ = [
    "DirectCaptureError",
    "DirectDatabaseAttestation",
    "DirectModelTurn",
    "DirectProbeResult",
    "DirectReferenceResult",
    "DirectSqlCapture",
]


class DirectSqlCapture:
    """Run one comparator attempt with condition-locked public tools."""

    def __init__(
        self,
        *,
        prepared: DirectPreparedAttempt,
    ) -> None:
        try:
            authorized = validate_direct_prepared_attempt(prepared)
            self._prepared = authorized
            self._binding = authorized.binding
            self._model_transport = authorized.model_transport
            self._database = authorized.database
            self._public_tools = authorized.public_tools
            self._store = authorized.store
        except (DirectCaptureBindingError, DirectPreparedAttemptError) as error:
            raise DirectCaptureError(str(error)) from error
        self._condition = self._binding.condition
        self._provider = self._binding.model.provider
        self._model = self._binding.model.model
        self._maximum_turns = self._binding.budget.maximum_turns
        self._clock = _monotonic
        self._utc_now = _utc_now
        self._policy = ContentPolicy.from_environment(os.environ)
        self._events: list[dict[str, Any]] = []
        self._action_evidence: list[DirectActionEvidence] = []
        self._messages: list[Mapping[str, Any]] = []
        self._turns: list[DirectModelTurn] = []
        self._model_turn_provenance: list[DirectModelTurnProvenance] = []
        self._model_failures: list[DirectModelFailureObservation] = []
        self._tools: Counter[str] = Counter()
        self._semantic_objects: set[str] = set()
        self._database_query_count: int | None = 0
        self._origin = 0.0
        self._started_at = ""
        self._question_sha256 = self._binding.question.question_sha256
        self._used = False
        self._model_failure = "model_transport_error"

    def capture(self) -> DirectProbeResult:
        """Run the single question authorized by the immutable runtime binding."""
        self._start()
        outcome, failure, sql, result_artifact = self._run_turns()
        latency_ms = max(0.0, (self._clock() - self._origin) * 1000)
        trace = self._store.write_jsonl(Path("attempt.trace.jsonl"), self._events)
        action_evidence = self._store.write_json(
            Path("attempt.action-evidence.json"),
            action_evidence_payload(
                binding=self._binding,
                trace_sha256=trace.sha256,
                records=self._action_evidence,
                trace_events=self._events,
                policy=self._policy,
            ),
        )
        return self._probe_result(
            outcome,
            failure,
            sql,
            result_artifact,
            trace,
            action_evidence,
            latency_ms,
        )

    def _write_receipt(
        self,
        sql: str | None,
        trace: StoredArtifact,
        action_evidence: StoredArtifact,
        result: StoredArtifact | None,
        summary: Mapping[str, Any],
    ) -> StoredArtifact:
        return self._store.write_json(
            Path("capture.receipt.json"),
            capture_receipt_payload(
                store=self._store,
                binding=self._binding,
                sql=sql,
                trace=trace,
                action_evidence=action_evidence,
                result=result,
                capture_summary=summary,
            ),
        )

    def _start(self) -> None:
        if self._used:
            raise DirectCaptureError("direct SQL capture instances are single use")
        self._revalidate_prepared()
        try:
            require_runtime_boundaries(
                self._binding,
                self._model_transport,
                self._database,
                self._public_tools,
            )
        except DirectCaptureBindingError as error:
            raise DirectCaptureError(str(error)) from error
        try:
            question = self._public_tools.render_question(
                self._binding.question.question
            )
        except Exception as error:
            raise DirectCaptureError("public question rendering failed") from error
        try:
            require_public_identity(self._binding, self._public_tools)
            self._revalidate_prepared()
        except DirectReferenceBindingError as error:
            raise DirectCaptureError(str(error)) from error
        if question != self._binding.question.question:
            raise DirectCaptureError("rendered question does not match runtime binding")
        if not self._policy.query_is_safe(question):
            raise DirectCaptureError("question contains sensitive content")
        self._used = True
        self._origin = self._clock()
        self._started_at = self._utc_now()
        self._messages.append({"role": "user", "content": question})

    def _run_turns(
        self,
    ) -> tuple[GenerationOutcome, str | None, str | None, StoredArtifact | None]:
        for _ in range(self._maximum_turns):
            turn = self._next_turn()
            if turn is None:
                return self._terminal_error(self._model_failure)
            try:
                action = parse_direct_action(turn.action)
            except (
                DirectActionProtocolError,
                DirectCaptureError,
                OmniResultContractError,
            ):
                return self._terminal_error("invalid_model_action")
            self._messages.append({"role": "assistant", "content": dict(turn.action)})
            if isinstance(action, DirectToolAction):
                failure = self._dispatch_tool(action)
                if failure is not None:
                    return self._terminal_error(failure)
                continue
            if isinstance(action, DirectRefusalAction):
                self._append_terminal("direct_refusal", "DENIED", "agent_refusal")
                return "refused", "agent_refusal", None, None
            return self._finish_answer(action.sql)
        return self._terminal_error("turn_limit_exhausted")

    def _next_turn(self) -> DirectModelTurn | None:
        started = self._clock()
        try:
            turn = self._request_model_turn()
            provenance = reduce_turn_provenance(
                turn,
                self._binding.model,
                trace_seq=len(self._events),
                policy=self._policy,
            )
        except DirectModelBindingError:
            self._record_model_failure(started, "model_identity_mismatch")
            return None
        except DirectModelFailure as error:
            self._model_failures.append(error.observation)
            usage = error.accounted_usage
            self._record_model_failure(
                started,
                _MODEL_FAILURE_CLASSES[error.category],
                input_tokens=None if usage is None else usage.input_tokens,
                output_tokens=None if usage is None else usage.output_tokens,
                retry_delta=error.retry_count,
            )
            return None
        except Exception:
            self._record_model_failure(started, "model_transport_error")
            return None
        self._record_model_success(started, turn, provenance)
        return turn

    def _request_model_turn(self) -> DirectModelTurn:
        require_model_identity(self._binding, self._model_transport)
        self._revalidate_prepared()
        reject_forbidden_keys(self._messages)
        if self._policy.sanitize_json(self._messages) != self._messages:
            raise DirectCaptureError("outbound messages contain sensitive content")
        turn = self._model_transport.next_turn(
            tuple(self._messages), direct_tool_specs(self._condition)
        )
        require_model_identity(self._binding, self._model_transport)
        self._revalidate_prepared()
        _validate_turn(turn, self._binding.model)
        reject_forbidden_keys(turn.action)
        if self._policy.sanitize_json(dict(turn.action)) != dict(turn.action):
            raise DirectCaptureError("model action contains sensitive content")
        return turn

    def _record_model_failure(
        self,
        started: float,
        failure: str,
        *,
        input_tokens: int | None = 0,
        output_tokens: int | None = 0,
        retry_delta: int | None = 0,
    ) -> None:
        self._model_failure = failure
        provenance = DirectModelTurnProvenance.unavailable(
            trace_seq=len(self._events), identity=self._binding.model
        )
        self._model_turn_provenance.append(provenance)
        self._append_event(
            event_type="direct_model_turn",
            status="ERROR",
            started=started,
            failure_class=failure,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retry_delta=retry_delta,
            metadata_sha256=provenance.sha256(),
        )

    def _record_model_success(
        self,
        started: float,
        turn: DirectModelTurn,
        provenance: DirectModelTurnProvenance,
    ) -> None:
        self._turns.append(turn)
        self._model_turn_provenance.append(provenance)
        self._append_event(
            event_type="direct_model_turn",
            status="SUCCESS",
            started=started,
            input_tokens=turn.input_tokens,
            output_tokens=turn.output_tokens,
            retry_delta=turn.retry_count,
            metadata_sha256=provenance.sha256(),
        )

    def _dispatch_tool(self, action: DirectToolAction) -> str | None:
        if action.name not in DIRECT_TOOL_NAMES[self._condition]:
            return "unauthorized_tool"
        try:
            validate_action_evidence_input(action, self._policy)
        except DirectActionEvidenceError:
            return "invalid_model_action"
        started = self._clock()
        self._tools[action.name] += 1
        if action.name == "execute_sql":
            return self._dispatch_database_tool(action, started)
        try:
            result = self._tool_result(action)
            _validate_reference_result(
                result,
                self._policy,
                self._binding,
                action.name,
            )
            if result.semantic_objects and not (
                self._condition == "C3" and action.name == "search_semantic_model"
            ):
                raise DirectCaptureError(
                    "semantic objects require C3 semantic-model search provenance"
                )
            retrieved_ids = public_ids_from_reference(result, self._policy)
        except DirectReferenceBindingError:
            self._append_tool_event(action, started, "ERROR", "reference_binding_error")
            return "reference_binding_error"
        except (DirectActionEvidenceError, OmniResultContractError):
            self._append_tool_event(action, started, "ERROR", "forbidden_tool_payload")
            return "forbidden_tool_payload"
        except Exception:
            self._append_tool_event(action, started, "ERROR", "tool_execution_error")
            return "tool_execution_error"
        self._semantic_objects.update(result.semantic_objects)
        self._messages.append(
            {"role": "tool", "name": action.name, "content": result.payload}
        )
        self._append_tool_event(
            action, started, "SUCCESS", None, retrieved_ids=retrieved_ids
        )
        return None

    def _dispatch_database_tool(
        self, action: DirectToolAction, started: float
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
            self._append_tool_event(action, started, "ERROR", "forbidden_tool_payload")
            return "forbidden_tool_payload"
        self._messages.append(
            {"role": "tool", "name": action.name, "content": execution.payload}
        )
        status = "ERROR" if execution.failure_class is not None else "SUCCESS"
        self._append_tool_event(action, started, status, execution.failure_class)
        if execution.failure_class in _TERMINAL_DATABASE_FAILURES:
            return execution.failure_class
        return None

    def _tool_result(self, action: DirectToolAction) -> DirectReferenceResult:
        require_public_identity(self._binding, self._public_tools)
        self._revalidate_prepared()
        if action.name == "inspect_schema":
            result = self._public_tools.inspect_schema(action.arguments["query"])
        elif action.name == "search_hkb":
            if self._public_tools.search_hkb is None:
                raise DirectCaptureError("HKB search is unavailable")
            result = self._public_tools.search_hkb(action.arguments["query"])
        elif action.name == "search_semantic_model":
            if self._public_tools.search_semantic_model is None:
                raise DirectCaptureError("semantic-model search is unavailable")
            result = self._public_tools.search_semantic_model(action.arguments["query"])
        else:
            raise DirectCaptureError("tool is not a public reference tool")
        require_public_identity(self._binding, self._public_tools)
        self._revalidate_prepared()
        return result

    def _execute_sql(self, sql: str) -> DirectExecution:
        if not _sql_is_admitted(sql, self._policy):
            return DirectExecution(
                {"failure_class": "sql_not_admitted", "status": "error"},
                None,
                "sql_not_admitted",
            )
        connection: Any | None = None
        try:
            require_database_identity(self._binding, self._database)
            self._revalidate_prepared()
            connection = self._database.connect()
            require_database_identity(self._binding, self._database)
            self._revalidate_prepared()
        except DirectDatabaseBindingError:
            return self._database_preflight_failure(
                connection, "database_identity_mismatch"
            )
        except Exception:
            return self._database_preflight_failure(
                connection, "database_infrastructure_error"
            )
        try:
            require_database_identity(self._binding, self._database)
            self._revalidate_prepared()
            result = execute_query_sequence(connection, sql, read_only=True)
            self._record_database_queries(result.statement_count)
            require_database_identity(self._binding, self._database)
            self._revalidate_prepared()
            execution = adapt_query_result(result)
        except DirectDatabaseBindingError:
            execution = database_failure("database_identity_mismatch")
        except PostgreSQLExecutionError as error:
            self._record_database_queries(max(1, error.statement_index + 1))
            execution = database_failure(f"database_{error.kind}_error")
        except DirectResultError:
            execution = database_failure("result_contract_error")
        except Exception:
            self._database_query_count = None
            execution = database_failure("database_infrastructure_error")
        cleanup_failure = self._close_database_connection(connection)
        if cleanup_failure == "database_infrastructure_error":
            return database_failure("database_infrastructure_error")
        if (
            cleanup_failure == "database_identity_mismatch"
            and execution.failure_class != "database_identity_mismatch"
        ):
            return database_failure(cleanup_failure)
        return execution

    def _close_database_connection(self, connection: Any) -> str | None:
        authority_failure: str | None = None
        try:
            require_database_identity(self._binding, self._database)
            self._revalidate_prepared()
        except DirectDatabaseBindingError:
            authority_failure = "database_identity_mismatch"
        except Exception:
            authority_failure = "database_infrastructure_error"
        try:
            connection.close()
        except Exception:
            return "database_infrastructure_error"
        try:
            require_database_identity(self._binding, self._database)
            self._revalidate_prepared()
        except DirectDatabaseBindingError:
            return "database_identity_mismatch"
        except Exception:
            return "database_infrastructure_error"
        return authority_failure

    @staticmethod
    def _database_preflight_failure(
        connection: Any | None, failure: str
    ) -> DirectExecution:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                return database_failure("database_infrastructure_error")
        return database_failure(failure)

    def _revalidate_prepared(self) -> None:
        try:
            validate_direct_prepared_attempt(self._prepared)
        except (DirectCaptureBindingError, DirectPreparedAttemptError) as error:
            raise DirectCaptureError(str(error)) from error

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
        self,
        action: DirectToolAction,
        started: float,
        status: str,
        failure: str | None,
        *,
        retrieved_ids: tuple[str, ...] = (),
    ) -> None:
        evidence = tool_action_evidence(
            action=action,
            trace_seq=len(self._events),
            failure_class=failure,
            retrieved_ids=retrieved_ids,
            policy=self._policy,
        )
        if evidence is not None:
            self._action_evidence.append(evidence)
        database_delta = 0
        if action.name == "execute_sql" and failure != "sql_not_admitted":
            database_delta = self._last_database_delta()
        self._append_event(
            event_type="direct_tool_dispatch",
            status=status,
            started=started,
            tool_call_delta=1,
            tool_name=action.name,
            database_query_delta=database_delta,
            failure_class=failure,
            metadata_sha256=None if evidence is None else evidence.sha256(),
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
        metadata_sha256: str | None = None,
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
                "metadata_sha256": metadata_sha256
                or _event_digest(event_type, status, len(self._events)),
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

    def _probe_result(
        self,
        outcome: GenerationOutcome,
        failure: str | None,
        sql: str | None,
        result_artifact: StoredArtifact | None,
        trace: StoredArtifact,
        action_evidence: StoredArtifact,
        latency_ms: float,
    ) -> DirectProbeResult:
        telemetry = self._probe_telemetry(failure, latency_ms)
        summary = self._capture_summary(outcome, failure, telemetry, latency_ms)
        receipt = self._write_receipt(
            sql, trace, action_evidence, result_artifact, summary
        )
        return self._build_probe_result(
            outcome,
            failure,
            sql,
            result_artifact,
            trace,
            action_evidence,
            receipt,
            telemetry,
            latency_ms,
        )

    def _probe_telemetry(
        self, failure: str | None, latency_ms: float
    ) -> _ProbeTelemetry:
        return _ProbeTelemetry(
            token_usage=model_token_usage(self._turns, self._model_failures),
            cost_usd=model_cost(self._turns, self._model_failures),
            retry_count=model_retry_count(self._turns, self._model_failures),
            semantic_objects=tuple(sorted(self._semantic_objects)),
            tool_calls_by_name=tuple(sorted(self._tools.items())),
            tool_call_count=sum(self._tools.values()),
            failure_origin=_failure_origin(failure),
            finished_at=_timestamp_after(self._started_at, latency_ms),
        )

    def _capture_summary(
        self,
        outcome: GenerationOutcome,
        failure: str | None,
        telemetry: _ProbeTelemetry,
        latency_ms: float,
    ) -> dict[str, Any]:
        return capture_summary_payload(
            generation_outcome=outcome,
            failure_class=failure,
            failure_origin=telemetry.failure_origin,
            semantic_objects=telemetry.semantic_objects,
            tool_calls_by_name=telemetry.tool_calls_by_name,
            tool_call_count=telemetry.tool_call_count,
            database_query_count=self._database_query_count,
            validation_attempt_count=0,
            retry_count=telemetry.retry_count,
            token_usage=telemetry.token_usage,
            token_source=telemetry.token_source,
            cost_usd=telemetry.cost_usd,
            cost_source=telemetry.cost_source,
            started_at=self._started_at,
            finished_at=telemetry.finished_at,
            latency_ms=latency_ms,
            model_turn_provenance=tuple(self._model_turn_provenance),
        )

    def _build_probe_result(
        self,
        outcome: GenerationOutcome,
        failure: str | None,
        sql: str | None,
        result_artifact: StoredArtifact | None,
        trace: StoredArtifact,
        action_evidence: StoredArtifact,
        receipt: StoredArtifact,
        telemetry: _ProbeTelemetry,
        latency_ms: float,
    ) -> DirectProbeResult:
        return DirectProbeResult(
            binding=self._binding,
            condition=self._condition,
            attempt_id=self._binding.attempt_id,
            maximum_turns=self._maximum_turns,
            question_sha256=self._question_sha256,
            generation_outcome=outcome,
            failure_class=failure,
            trace=trace,
            action_evidence=action_evidence,
            receipt=receipt,
            result_artifact=result_artifact,
            generated_sql=sql,
            semantic_objects=telemetry.semantic_objects,
            tool_calls_by_name=telemetry.tool_calls_by_name,
            tool_call_count=telemetry.tool_call_count,
            database_query_count=self._database_query_count,
            validation_attempt_count=0,
            retry_count=telemetry.retry_count,
            token_usage=telemetry.token_usage,
            token_source=telemetry.token_source,
            cost_usd=telemetry.cost_usd,
            cost_source=telemetry.cost_source,
            provider=self._provider,
            model=self._model,
            started_at=self._started_at,
            finished_at=telemetry.finished_at,
            latency_ms=latency_ms,
            model_turn_provenance=tuple(self._model_turn_provenance),
            failure_origin=telemetry.failure_origin,
        )


def _sql_is_admitted(sql: str, policy: ContentPolicy) -> bool:
    return policy.query_is_safe(sql) and single_query_sql_is_admissible(sql)

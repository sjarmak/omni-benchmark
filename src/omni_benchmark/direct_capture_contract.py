"""Strict protocols and immutable values crossing direct-capture boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any, Literal, Protocol

from .artifact_store import StoredArtifact
from .direct_runtime_binding import (
    DirectBudgetIdentity,
    DirectContextIdentity,
    DirectDatabaseIdentity,
    DirectModelIdentity,
    DirectRuntimeBinding,
)
from .postgres_execution import PostgreSQLConnection

DirectCondition = Literal["C1", "C2", "C3"]
GenerationOutcome = Literal["answered", "refused", "errored"]
FailureOrigin = Literal["evaluated_system", "benchmark_infrastructure"]
ReferenceCapability = Literal["inspect_schema", "search_hkb", "search_semantic_model"]
DirectModelFailureCategory = Literal[
    "auth",
    "budget",
    "infrastructure",
    "model_identity",
    "protocol",
    "quota",
    "rate_limit",
    "setup",
    "structured_output",
    "timeout",
    "tool_surface",
]
_MODEL_FAILURE_CATEGORIES = frozenset(
    {
        "auth",
        "budget",
        "infrastructure",
        "model_identity",
        "protocol",
        "quota",
        "rate_limit",
        "setup",
        "structured_output",
        "timeout",
        "tool_surface",
    }
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PROVENANCE_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")


@dataclass(frozen=True)
class DirectModelUsage:
    """Provider-observed token usage at one stream boundary."""

    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        for field, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")


@dataclass(frozen=True)
class DirectModelFailureObservation:
    """All finite telemetry observable when a provider turn fails."""

    category: DirectModelFailureCategory
    partial_usage: DirectModelUsage | None
    retry_count: int | None
    terminal_cost_usd: float | None
    terminal_usage: DirectModelUsage | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.category, str)
            or self.category not in _MODEL_FAILURE_CATEGORIES
        ):
            raise ValueError("category is not a supported model failure category")
        for field, value in (
            ("partial_usage", self.partial_usage),
            ("terminal_usage", self.terminal_usage),
        ):
            if value is not None and not isinstance(value, DirectModelUsage):
                raise ValueError(f"{field} must use DirectModelUsage or null")
        if self.retry_count is not None and (
            type(self.retry_count) is not int or self.retry_count < 0
        ):
            raise ValueError("retry_count must be a non-negative integer or null")
        if self.terminal_cost_usd is not None and (
            isinstance(self.terminal_cost_usd, bool)
            or not isinstance(self.terminal_cost_usd, (int, float))
            or not math.isfinite(self.terminal_cost_usd)
            or self.terminal_cost_usd < 0
        ):
            raise ValueError(
                "terminal_cost_usd must be finite and non-negative or null"
            )

    @property
    def accounted_usage(self) -> DirectModelUsage | None:
        """Prefer cumulative terminal usage, otherwise retain partial usage."""
        return self.terminal_usage or self.partial_usage

    @property
    def token_source(self) -> str:
        return (
            "provider_reported" if self.accounted_usage is not None else "unavailable"
        )

    @property
    def token_observation(self) -> str:
        if self.terminal_usage is not None:
            return "terminal"
        if self.partial_usage is not None:
            return "partial"
        return "unavailable"

    @property
    def cost_source(self) -> str:
        return (
            "provider_reported" if self.terminal_cost_usd is not None else "unavailable"
        )


class DirectModelFailure(RuntimeError):
    """Provider-neutral classified model failure with audited telemetry."""

    def __init__(
        self,
        category: DirectModelFailureCategory,
        message: str,
        *,
        partial_usage: DirectModelUsage | None = None,
        retry_count: int | None = None,
        terminal_cost_usd: float | None = None,
        terminal_usage: DirectModelUsage | None = None,
    ) -> None:
        if not isinstance(message, str) or not message:
            raise ValueError("message must be a non-empty sanitized string")
        super().__init__(message)
        self._observation = DirectModelFailureObservation(
            category=category,
            partial_usage=partial_usage,
            retry_count=retry_count,
            terminal_cost_usd=terminal_cost_usd,
            terminal_usage=terminal_usage,
        )

    @property
    def observation(self) -> DirectModelFailureObservation:
        return self._observation

    @property
    def category(self) -> DirectModelFailureCategory:
        return self._observation.category

    @property
    def partial_usage(self) -> DirectModelUsage | None:
        return self._observation.partial_usage

    @property
    def retry_count(self) -> int | None:
        return self._observation.retry_count

    @property
    def terminal_cost_usd(self) -> float | None:
        return self._observation.terminal_cost_usd

    @property
    def terminal_usage(self) -> DirectModelUsage | None:
        return self._observation.terminal_usage

    @property
    def accounted_usage(self) -> DirectModelUsage | None:
        return self._observation.accounted_usage

    @property
    def token_source(self) -> str:
        return self._observation.token_source

    @property
    def token_observation(self) -> str:
        return self._observation.token_observation

    @property
    def cost_source(self) -> str:
        return self._observation.cost_source

    @property
    def retryable(self) -> bool:
        return self.category in {"infrastructure", "timeout"}


@dataclass(frozen=True)
class DirectModelTurn:
    """A structured model action plus realized model identity and telemetry."""

    action: Mapping[str, Any]
    model_identity: DirectModelIdentity
    input_tokens: int | None = None
    output_tokens: int | None = None
    retry_count: int | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class DirectModelTurnProvenance:
    """Content-safe evidence retained for one realized model turn."""

    availability: Literal["observed", "unavailable"]
    binary_sha256: str
    cli_version: str
    cost_source: str
    duration_ms: float | None
    model_identity_sha256: str
    provider: str
    realized_models: tuple[str, ...]
    request_sha256: str | None
    requested_model: str
    result_subtype: str | None
    session_sha256: str | None
    stream_sha256: str | None
    token_source: str
    trace_seq: int

    def __post_init__(self) -> None:
        if self.availability not in {"observed", "unavailable"}:
            raise ValueError("model turn provenance availability is invalid")
        if type(self.trace_seq) is not int or self.trace_seq < 0:
            raise ValueError("model turn provenance trace_seq is invalid")
        for field, value in (
            ("binary_sha256", self.binary_sha256),
            ("model_identity_sha256", self.model_identity_sha256),
        ):
            _provenance_sha256(value, field, nullable=False)
        for field, value in (
            ("request_sha256", self.request_sha256),
            ("session_sha256", self.session_sha256),
            ("stream_sha256", self.stream_sha256),
        ):
            _provenance_sha256(value, field, nullable=True)
        for field, value in (
            ("cli_version", self.cli_version),
            ("cost_source", self.cost_source),
            ("provider", self.provider),
            ("requested_model", self.requested_model),
            ("token_source", self.token_source),
        ):
            _provenance_label(value, field)
        if not isinstance(self.realized_models, tuple) or any(
            not isinstance(value, str) or _PROVENANCE_LABEL.fullmatch(value) is None
            for value in self.realized_models
        ):
            raise ValueError("model turn provenance realized_models are invalid")
        if self.result_subtype is not None:
            _provenance_label(self.result_subtype, "result_subtype")
        if self.duration_ms is not None and (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, (int, float))
            or not math.isfinite(self.duration_ms)
            or self.duration_ms < 0
        ):
            raise ValueError("model turn provenance duration_ms is invalid")
        if self.availability == "observed":
            self._require_observed()
        else:
            self._require_unavailable()

    @classmethod
    def from_dict(cls, value: object) -> DirectModelTurnProvenance:
        """Parse the exact persisted provider-neutral provenance schema."""
        fields = frozenset(
            {
                "availability",
                "binary_sha256",
                "cli_version",
                "cost_source",
                "duration_ms",
                "model_identity_sha256",
                "provider",
                "realized_models",
                "request_sha256",
                "requested_model",
                "result_subtype",
                "session_sha256",
                "stream_sha256",
                "token_source",
                "trace_seq",
            }
        )
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("model turn provenance must use the exact schema")
        realized = value["realized_models"]
        if not isinstance(realized, list):
            raise ValueError("model turn provenance realized_models must be an array")
        return cls(
            availability=value["availability"],
            binary_sha256=value["binary_sha256"],
            cli_version=value["cli_version"],
            cost_source=value["cost_source"],
            duration_ms=value["duration_ms"],
            model_identity_sha256=value["model_identity_sha256"],
            provider=value["provider"],
            realized_models=tuple(realized),
            request_sha256=value["request_sha256"],
            requested_model=value["requested_model"],
            result_subtype=value["result_subtype"],
            session_sha256=value["session_sha256"],
            stream_sha256=value["stream_sha256"],
            token_source=value["token_source"],
            trace_seq=value["trace_seq"],
        )

    @classmethod
    def unavailable(
        cls, *, trace_seq: int, identity: DirectModelIdentity
    ) -> DirectModelTurnProvenance:
        """Create an explicit marker when a transport exposes no turn evidence."""
        return cls(
            availability="unavailable",
            binary_sha256=identity.executable_sha256,
            cli_version=identity.executable_version,
            cost_source="unavailable",
            duration_ms=None,
            model_identity_sha256=identity.sha256(),
            provider=identity.provider,
            realized_models=(),
            request_sha256=None,
            requested_model=identity.model,
            result_subtype=None,
            session_sha256=None,
            stream_sha256=None,
            token_source="unavailable",
            trace_seq=trace_seq,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "availability": self.availability,
            "binary_sha256": self.binary_sha256,
            "cli_version": self.cli_version,
            "cost_source": self.cost_source,
            "duration_ms": self.duration_ms,
            "model_identity_sha256": self.model_identity_sha256,
            "provider": self.provider,
            "realized_models": list(self.realized_models),
            "request_sha256": self.request_sha256,
            "requested_model": self.requested_model,
            "result_subtype": self.result_subtype,
            "session_sha256": self.session_sha256,
            "stream_sha256": self.stream_sha256,
            "token_source": self.token_source,
            "trace_seq": self.trace_seq,
        }

    def sha256(self) -> str:
        payload = json.dumps(
            self.as_dict(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _require_observed(self) -> None:
        if (
            not self.realized_models
            or self.duration_ms is None
            or self.result_subtype is None
            or any(
                value is None
                for value in (
                    self.request_sha256,
                    self.session_sha256,
                    self.stream_sha256,
                )
            )
        ):
            raise ValueError("observed model turn provenance is incomplete")

    def _require_unavailable(self) -> None:
        if (
            self.realized_models
            or self.duration_ms is not None
            or self.result_subtype is not None
            or any(
                value is not None
                for value in (
                    self.request_sha256,
                    self.session_sha256,
                    self.stream_sha256,
                )
            )
            or self.token_source != "unavailable"
            or self.cost_source != "unavailable"
        ):
            raise ValueError("unavailable model turn provenance contains observations")


def _provenance_sha256(value: object, field: str, *, nullable: bool) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"model turn provenance {field} is invalid")


def _provenance_label(value: object, field: str) -> None:
    if not isinstance(value, str) or _PROVENANCE_LABEL.fullmatch(value) is None:
        raise ValueError(f"model turn provenance {field} is invalid")


@dataclass(frozen=True)
class DirectReferenceResult:
    """One public payload bound to its context and exact tool capability."""

    payload: Any
    context_sha256: str
    capability: ReferenceCapability
    semantic_objects: tuple[str, ...] = ()


@dataclass(frozen=True)
class DirectDatabaseAttestation:
    """External audit assertions required because AST admission is not a sandbox."""

    role_is_read_only: bool
    no_execute_on_non_system_functions: bool


@dataclass(frozen=True)
class DirectProbeResult:
    """Unscored comparator output bound to its complete immutable runtime."""

    binding: DirectRuntimeBinding
    condition: DirectCondition
    attempt_id: str
    maximum_turns: int
    question_sha256: str
    generation_outcome: GenerationOutcome
    failure_class: str | None
    trace: StoredArtifact
    action_evidence: StoredArtifact
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
    model_turn_provenance: tuple[DirectModelTurnProvenance, ...]
    failure_origin: FailureOrigin | None = None


class DirectModelTransport(Protocol):
    """One exact model/budget adapter; the harness owns conversation and tools."""

    @property
    def runtime_identity(self) -> DirectModelIdentity: ...

    @property
    def budget_identity(self) -> DirectBudgetIdentity: ...

    @property
    def execution_authority(self) -> str: ...

    def next_turn(
        self,
        messages: tuple[Mapping[str, Any], ...],
        tool_specs: tuple[Mapping[str, Any], ...],
    ) -> DirectModelTurn: ...


class DirectDatabaseTransport(Protocol):
    """An exact attested database deployment and fresh connection factory."""

    @property
    def runtime_identity(self) -> DirectDatabaseIdentity: ...

    @property
    def execution_attestation(self) -> DirectDatabaseAttestation: ...

    @property
    def execution_authority(self) -> str: ...

    def connect(self) -> PostgreSQLConnection: ...


class DirectPublicTools(Protocol):
    """One condition-scoped public context adapter with no hidden oracle input."""

    @property
    def identity(self) -> DirectContextIdentity: ...

    def inspect_schema(self) -> DirectReferenceResult: ...

    search_hkb: Callable[[str], DirectReferenceResult] | None
    search_semantic_model: Callable[[str], DirectReferenceResult] | None

    def render_question(self, question: str) -> str: ...

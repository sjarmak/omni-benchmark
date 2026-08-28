"""Reduce and aggregate provider observations for direct model turns."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence

from .content_policy import ContentPolicy
from .direct_capture_binding import DirectModelBindingError
from .direct_capture_contract import (
    DirectModelFailureObservation,
    DirectModelTurn,
    DirectModelTurnProvenance,
)
from .direct_runtime_binding import DirectModelIdentity


class DirectModelObservationError(ValueError):
    """Raised when provider observations cannot be reduced safely."""


def reduce_turn_provenance(
    turn: DirectModelTurn,
    expected_model: DirectModelIdentity,
    *,
    trace_seq: int,
    policy: ContentPolicy,
) -> DirectModelTurnProvenance:
    """Reduce optional provider evidence without retaining raw provider content."""
    raw = getattr(turn, "provenance", None)
    if raw is None:
        return DirectModelTurnProvenance.unavailable(
            trace_seq=trace_seq, identity=expected_model
        )
    try:
        if raw.model_identity != expected_model:
            raise DirectModelBindingError(
                "turn provenance model identity does not match binding"
            )
        record = _observed_record(raw, expected_model, trace_seq)
    except (AttributeError, TypeError, ValueError) as error:
        raise DirectModelObservationError("model turn provenance is invalid") from error
    _validate_provenance_identity(record, expected_model)
    if policy.sanitize_json(record.as_dict()) != record.as_dict():
        raise DirectModelObservationError(
            "model turn provenance contains sensitive content"
        )
    return record


def _observed_record(
    raw: object, expected: DirectModelIdentity, trace_seq: int
) -> DirectModelTurnProvenance:
    session_id = _required_text(getattr(raw, "session_id"), "session_id")
    duration_seconds = _duration_seconds(getattr(raw, "duration_seconds"))
    return DirectModelTurnProvenance(
        availability="observed",
        binary_sha256=getattr(raw, "binary_sha256"),
        cli_version=getattr(raw, "cli_version"),
        cost_source=getattr(raw, "cost_source"),
        duration_ms=duration_seconds * 1000,
        model_identity_sha256=expected.sha256(),
        provider=getattr(raw, "provider"),
        realized_models=tuple(getattr(raw, "realized_models")),
        request_sha256=getattr(raw, "request_sha256"),
        requested_model=getattr(raw, "requested_model"),
        result_subtype=getattr(raw, "result_subtype"),
        session_sha256=hashlib.sha256(session_id.encode("utf-8")).hexdigest(),
        stream_sha256=getattr(raw, "stream_sha256"),
        token_source=getattr(raw, "token_source"),
        trace_seq=trace_seq,
    )


def _validate_provenance_identity(
    record: DirectModelTurnProvenance, expected: DirectModelIdentity
) -> None:
    if (
        record.provider != expected.provider
        or record.requested_model != expected.model
        or set(record.realized_models) != {expected.model}
        or record.binary_sha256 != expected.executable_sha256
        or record.cli_version != expected.executable_version
        or record.model_identity_sha256 != expected.sha256()
    ):
        raise DirectModelBindingError(
            "model turn provenance identity does not match binding"
        )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise DirectModelObservationError(f"model turn provenance {field} is invalid")
    return value


def _duration_seconds(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise DirectModelObservationError("model turn provenance duration is invalid")
    return float(value)


def token_usage(
    turns: Sequence[DirectModelTurn],
    failures: Sequence[DirectModelFailureObservation] = (),
) -> dict[str, int] | None:
    usage = [(turn.input_tokens, turn.output_tokens) for turn in turns] + [
        (
            None
            if failure.accounted_usage is None
            else failure.accounted_usage.input_tokens,
            None
            if failure.accounted_usage is None
            else failure.accounted_usage.output_tokens,
        )
        for failure in failures
    ]
    if not usage or any(first is None or second is None for first, second in usage):
        return None
    input_tokens = sum(first for first, _ in usage if first is not None)
    output_tokens = sum(second for _, second in usage if second is not None)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def retry_count(
    turns: Sequence[DirectModelTurn],
    failures: Sequence[DirectModelFailureObservation] = (),
) -> int | None:
    retries = [turn.retry_count for turn in turns] + [
        failure.retry_count for failure in failures
    ]
    if not retries or any(value is None for value in retries):
        return None
    return sum(value for value in retries if value is not None)


def cost(
    turns: Sequence[DirectModelTurn],
    failures: Sequence[DirectModelFailureObservation] = (),
) -> float | None:
    costs = [turn.cost_usd for turn in turns] + [
        failure.terminal_cost_usd for failure in failures
    ]
    if not costs or any(value is None for value in costs):
        return None
    total = sum(value for value in costs if value is not None)
    if not math.isfinite(total):
        raise DirectModelObservationError("provider cost aggregate is non-finite")
    return total

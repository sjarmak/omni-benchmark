"""Small validation helpers shared by direct-SQL capture."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping

from .autoresearch_config import _canonical_bytes
from .content_policy import ContentPolicy
from .direct_capture_binding import (
    DirectModelBindingError,
    DirectReferenceBindingError,
)
from .direct_capture_contract import DirectModelTurn, DirectReferenceResult
from .direct_runtime_binding import DirectModelIdentity, DirectRuntimeBinding
from .direct_sql_result import validate_json_value
from .omni_result_adapter import reject_forbidden_keys


class DirectCaptureError(RuntimeError):
    """Raised when a direct comparator cannot be configured safely."""


def validate_turn(turn: object, expected_model: DirectModelIdentity) -> None:
    if not isinstance(turn, DirectModelTurn) or not isinstance(turn.action, Mapping):
        raise DirectCaptureError("model turn must use the strict transport contract")
    if turn.model_identity != expected_model:
        raise DirectModelBindingError("realized model identity does not match binding")
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


def validate_reference_result(
    result: DirectReferenceResult,
    policy: ContentPolicy,
    binding: DirectRuntimeBinding,
    capability: str,
) -> None:
    if not isinstance(result, DirectReferenceResult):
        raise DirectCaptureError("reference tool must return DirectReferenceResult")
    if (
        result.context_sha256 != binding.context.context_sha256
        or result.capability != capability
    ):
        raise DirectReferenceBindingError(
            "reference result does not match context capability"
        )
    reject_forbidden_keys(result.payload)
    validate_json_value(result.payload)
    if policy.sanitize_json(result.payload) != result.payload:
        raise DirectCaptureError("reference tool payload contains sensitive content")
    if any(
        not isinstance(value, str) or not value or not policy.identifier_is_safe(value)
        for value in result.semantic_objects
    ):
        raise DirectCaptureError("semantic object identifiers are invalid")


def event_digest(event_type: str, status: str, seq: int) -> str:
    return hashlib.sha256(
        _canonical_bytes({"event_type": event_type, "seq": seq, "status": status})
    ).hexdigest()

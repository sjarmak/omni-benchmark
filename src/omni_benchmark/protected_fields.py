"""Shared recursive guard for benchmark fields forbidden in public artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


PROTECTED_KEYS = frozenset(
    {
        "external_knowledge",
        "expected_result",
        "gold_sql",
        "gold_result",
        "oracle_hint",
        "oracle_sql",
        "sol_sql",
        "test_correctness",
        "test_cases",
        "test_case",
    }
)


class ProtectedFieldError(ValueError):
    """Raised when a recursively nested protected benchmark field appears."""


def reject_protected_fields(value: Any) -> None:
    """Reject hidden benchmark fields recursively before interpreting input."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in PROTECTED_KEYS:
                raise ProtectedFieldError(f"protected field {key} is not allowed")
            reject_protected_fields(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            reject_protected_fields(item)

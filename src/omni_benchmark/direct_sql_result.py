"""Typed database-result adaptation and strict JSON boundary validation."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from .artifact_store import ArtifactStore, StoredArtifact
from .postgres_execution import QuerySequenceResult


class DirectResultError(RuntimeError):
    """Raised when a direct-SQL result cannot cross the JSON boundary safely."""


@dataclass(frozen=True)
class DirectExecution:
    """A typed execution result or a sanitized terminal failure."""

    payload: dict[str, Any]
    result: QuerySequenceResult | None
    failure_class: str | None


def capture_receipt_payload(
    *,
    store: ArtifactStore,
    attempt_id: str,
    condition: str,
    question_sha256: str,
    provider: str,
    model: str,
    maximum_turns: int,
    sql: str | None,
    trace: StoredArtifact,
    result: StoredArtifact | None,
) -> dict[str, Any]:
    """Bind an attempt identity to its exact immutable capture artifacts."""
    return {
        "artifact_root_identity": store.root_identity,
        "attempt_id": attempt_id,
        "condition": condition,
        "generated_sql_sha256": (
            hashlib.sha256(sql.encode()).hexdigest() if sql is not None else None
        ),
        "maximum_turns": maximum_turns,
        "model": model,
        "provider": provider,
        "question_sha256": question_sha256,
        "result_path": store.relative_path(result).as_posix() if result else None,
        "result_sha256": result.sha256 if result else None,
        "schema_version": 1,
        "trace_path": store.relative_path(trace).as_posix(),
        "trace_sha256": trace.sha256,
    }


def adapt_query_result(result: QuerySequenceResult) -> DirectExecution:
    """Convert a PostgreSQL result into the direct harness's typed JSON shape."""
    if result.rows is None:
        return DirectExecution({"status": "no_result"}, result, None)
    width = len(result.rows[0]) if result.rows else 0
    if any(len(row) != width for row in result.rows):
        return database_failure("ragged_result")
    payload = {
        "columns": [f"column_{index + 1}" for index in range(width)],
        "rows": [[_json_cell(cell) for cell in row] for row in result.rows],
        "schema_version": 1,
        "truncated": result.row_limit_exceeded,
    }
    return DirectExecution(payload, result, None)


def database_failure(failure: str) -> DirectExecution:
    """Build the sanitized tool payload for a database-side failure."""
    return DirectExecution(
        {"failure_class": failure, "status": "error"},
        None,
        failure,
    )


def validate_json_value(value: Any) -> None:
    """Reject values outside strict, finite JSON before provider exposure."""
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DirectResultError("tool payload must contain finite JSON numbers")
        return
    if isinstance(value, list):
        for item in value:
            validate_json_value(item)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            validate_json_value(item)
        return
    raise DirectResultError("tool payload must use strict JSON types")


def _json_cell(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DirectResultError("database result contains a non-finite number")
        return value
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, (datetime, date, time)):
        return {"type": type(value).__name__, "value": value.isoformat()}
    if isinstance(value, UUID):
        return {"type": "uuid", "value": str(value)}
    if isinstance(value, bytes):
        return {"hex": value.hex(), "type": "bytes"}
    if isinstance(value, (list, tuple)):
        return [_json_cell(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_cell(item) for key, item in value.items()}
    raise DirectResultError("database result contains an unsupported value")

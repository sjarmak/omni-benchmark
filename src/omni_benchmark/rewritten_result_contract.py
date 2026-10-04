"""Typed acceptance oracle for results produced from Omni-authored SQL."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .omni_result_adapter import reject_forbidden_keys

_DIGEST = re.compile(r"[0-9a-f]{64}")
_LOGICAL_TYPES = frozenset(
    {"boolean", "date", "decimal", "integer", "json", "string", "timestamp", "unknown"}
)
_SEMANTIC_ROLES = frozenset({"calculation", "dimension", "measure"})
_FAILURE_CODES = {
    "planner": frozenset(
        {"invalid_semantic_plan", "output_type_unresolved", "planning_failed"}
    ),
    "semantic_execution": frozenset(
        {"database_error", "query_cancelled", "query_execution_failed"}
    ),
    "transport": frozenset(
        {"malformed_provider_response", "provider_unavailable", "request_timeout"}
    ),
    "adapter": frozenset({"result_cardinality_mismatch", "unsupported_value_encoding"}),
}
_SELECTED_KEYS = frozenset(
    {"logical_type", "name", "nullable", "ordinal", "semantic_role", "source_type"}
)
_DEPENDENCY_KEYS = _SELECTED_KEYS - {"ordinal"}


class RewrittenResultContractError(ValueError):
    """Raised when a rewritten-SQL result envelope is incomplete or ambiguous."""


@dataclass(frozen=True, slots=True)
class RewrittenResultObservation:
    """Aggregate-safe observation; intentionally excludes names and row values."""

    status: str
    selected_field_count: int
    dependency_field_count: int
    selected_logical_types: tuple[str, ...]
    pagination: str | None
    failure_owner: str | None
    failure_code: str | None


def validate_rewritten_result(
    envelope: Mapping[str, Any],
) -> RewrittenResultObservation:
    """Validate the total v1 envelope and return only aggregate-safe properties."""
    if not isinstance(envelope, Mapping):
        raise RewrittenResultContractError("result envelope must be an object")
    reject_forbidden_keys(envelope)
    if set(envelope) != {"schema_version", "status", "fields", "page", "failure"}:
        raise RewrittenResultContractError("result envelope fields are invalid")
    if envelope.get("schema_version") != 1:
        raise RewrittenResultContractError("result schema version is unsupported")
    fields = envelope.get("fields")
    if not isinstance(fields, Mapping) or set(fields) != {"selected", "dependencies"}:
        raise RewrittenResultContractError("result field metadata is invalid")
    selected = _fields(fields.get("selected"), selected=True)
    dependencies = _fields(fields.get("dependencies"), selected=False)
    names = [field["name"] for field in (*selected, *dependencies)]
    if len(names) != len(set(names)):
        raise RewrittenResultContractError(
            "selected and dependency names must be unique"
        )

    status = envelope.get("status")
    if status == "success":
        if not selected:
            raise RewrittenResultContractError(
                "successful result has no selected fields"
            )
        if envelope.get("failure") is not None:
            raise RewrittenResultContractError(
                "successful result cannot contain a failure"
            )
        pagination = _page(envelope.get("page"), selected)
        owner = code = None
    elif status == "failed":
        if envelope.get("page") is not None:
            raise RewrittenResultContractError("failed result cannot contain a page")
        owner, code = _failure(envelope.get("failure"))
        pagination = None
    else:
        raise RewrittenResultContractError("result status is invalid")
    return RewrittenResultObservation(
        status=status,
        selected_field_count=len(selected),
        dependency_field_count=len(dependencies),
        selected_logical_types=tuple(field["logical_type"] for field in selected),
        pagination=pagination,
        failure_owner=owner,
        failure_code=code,
    )


def result_page_sha256(
    selected_fields: Sequence[Mapping[str, Any]], rows: Sequence[Sequence[Any]]
) -> str:
    """Hash the exact ordered output schema and page values canonically."""
    payload = {"rows": rows, "selected_fields": selected_fields}
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def classify_legacy_plan_boundary(
    semantic_query: Mapping[str, Any], plan: Mapping[str, Any]
) -> dict[str, object]:
    """Reproduce the UNKNOWN selected-type boundary without SQL or result values."""
    reject_forbidden_keys((semantic_query, plan))
    query_fields = semantic_query.get("fields")
    summary = plan.get("summary")
    metadata = summary.get("fields") if isinstance(summary, Mapping) else None
    model_query = plan.get("query")
    model_job = (
        model_query.get("model_job") if isinstance(model_query, Mapping) else None
    )
    planned_fields = model_job.get("fields") if isinstance(model_job, Mapping) else None
    if (
        plan.get("status") != "PLANNED"
        or not isinstance(query_fields, list)
        or not query_fields
        or any(not isinstance(name, str) or not name for name in query_fields)
        or len(set(query_fields)) != len(query_fields)
        or planned_fields != query_fields
        or not isinstance(metadata, Mapping)
        or any(name not in metadata for name in query_fields)
    ):
        raise RewrittenResultContractError("legacy plan selected fields are ambiguous")
    dependency_count = len(set(metadata) - set(query_fields))
    unresolved = any(
        not isinstance(metadata[name], Mapping)
        or metadata[name].get("data_type") in {None, "", "UNKNOWN"}
        for name in query_fields
    )
    result: dict[str, object] = {
        "dependency_field_count": dependency_count,
        "selected_field_count": len(query_fields),
        "status": "failed" if unresolved else "ready",
    }
    if unresolved:
        result.update(
            {
                "failure_code": "output_type_unresolved",
                "failure_owner": "planner",
            }
        )
    return result


def summarize_result_contracts(
    observations: Sequence[RewrittenResultObservation],
) -> dict[str, object]:
    """Aggregate typed outcomes without names, rows, SQL, or identifiers."""
    if any(not isinstance(item, RewrittenResultObservation) for item in observations):
        raise RewrittenResultContractError("result observation is invalid")
    return {
        "attempt_count": len(observations),
        "failure_code_counts": dict(
            sorted(
                Counter(
                    item.failure_code for item in observations if item.failure_code
                ).items()
            )
        ),
        "failure_owner_counts": dict(
            sorted(
                Counter(
                    item.failure_owner for item in observations if item.failure_owner
                ).items()
            )
        ),
        "pagination_counts": dict(
            sorted(
                Counter(
                    item.pagination for item in observations if item.pagination
                ).items()
            )
        ),
        "selected_logical_type_counts": dict(
            sorted(
                Counter(
                    logical_type
                    for item in observations
                    for logical_type in item.selected_logical_types
                ).items()
            )
        ),
        "status_counts": dict(
            sorted(Counter(item.status for item in observations).items())
        ),
    }


def _fields(value: object, *, selected: bool) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise RewrittenResultContractError("result fields must be arrays")
    expected_keys = _SELECTED_KEYS if selected else _DEPENDENCY_KEYS
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping) or set(raw) != expected_keys:
            raise RewrittenResultContractError("result field shape is invalid")
        name = raw.get("name")
        logical_type = raw.get("logical_type")
        nullable = raw.get("nullable")
        semantic_role = raw.get("semantic_role")
        source_type = raw.get("source_type")
        if not isinstance(name, str) or not name or len(name) > 240:
            raise RewrittenResultContractError("result field name is invalid")
        if logical_type not in _LOGICAL_TYPES:
            raise RewrittenResultContractError("result logical type is invalid")
        if not isinstance(nullable, bool):
            raise RewrittenResultContractError("result nullability is invalid")
        if semantic_role not in _SEMANTIC_ROLES:
            raise RewrittenResultContractError("result semantic role is invalid")
        if (
            not isinstance(source_type, str)
            or not source_type
            or len(source_type) > 120
        ):
            raise RewrittenResultContractError("result source type is invalid")
        if selected and raw.get("ordinal") != index:
            raise RewrittenResultContractError(
                "selected field ordinals must be contiguous"
            )
        result.append(dict(raw))
    return tuple(result)


def _page(value: object, selected: tuple[dict[str, Any], ...]) -> str:
    expected = {
        "completeness",
        "content_sha256",
        "next_cursor",
        "returned_row_count",
        "rows",
        "total_row_count",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise RewrittenResultContractError("result page shape is invalid")
    completeness = value.get("completeness")
    cursor = value.get("next_cursor")
    total = value.get("total_row_count")
    rows = value.get("rows")
    returned = value.get("returned_row_count")
    digest = value.get("content_sha256")
    if completeness not in {"complete", "paged"}:
        raise RewrittenResultContractError("result completeness is invalid")
    if completeness == "complete":
        if cursor is not None:
            raise RewrittenResultContractError("complete result cannot have a cursor")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise RewrittenResultContractError("complete result total is invalid")
    elif not isinstance(cursor, str) or not cursor or len(cursor) > 512:
        raise RewrittenResultContractError("paged result requires a cursor")
    elif total is not None and (
        isinstance(total, bool) or not isinstance(total, int) or total < 0
    ):
        raise RewrittenResultContractError("paged result total is invalid")
    if not isinstance(rows, list):
        raise RewrittenResultContractError("result rows must be an array")
    if returned != len(rows):
        raise RewrittenResultContractError("returned row count does not match rows")
    if completeness == "complete" and total != len(rows):
        raise RewrittenResultContractError("complete total does not match rows")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(selected):
            raise RewrittenResultContractError("result row cardinality is invalid")
        for cell, field in zip(row, selected, strict=True):
            _cell(cell, field)
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise RewrittenResultContractError("result page digest is invalid")
    if digest != result_page_sha256(selected, rows):
        raise RewrittenResultContractError("result page digest does not match content")
    return completeness


def _failure(value: object) -> tuple[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"code", "owner", "retryable"}:
        raise RewrittenResultContractError("result failure shape is invalid")
    owner, code, retryable = (
        value.get("owner"),
        value.get("code"),
        value.get("retryable"),
    )
    if owner not in _FAILURE_CODES or code not in _FAILURE_CODES[owner]:
        raise RewrittenResultContractError("result failure code does not match owner")
    if not isinstance(retryable, bool):
        raise RewrittenResultContractError("result failure retryability is invalid")
    return str(owner), str(code)


def _cell(value: Any, field: Mapping[str, Any]) -> None:
    logical_type = field["logical_type"]
    if value is None:
        if not field["nullable"]:
            raise RewrittenResultContractError(
                "result cell is null but field is not nullable"
            )
        return
    if logical_type == "boolean" and not isinstance(value, bool):
        raise RewrittenResultContractError("boolean result cell is invalid")
    if logical_type == "integer" and (
        isinstance(value, bool) or not isinstance(value, int)
    ):
        raise RewrittenResultContractError("integer result cell is invalid")
    if logical_type == "string" and not isinstance(value, str):
        raise RewrittenResultContractError("string result cell is invalid")
    if logical_type == "decimal":
        _tagged_decimal(value)
    elif logical_type == "date":
        _tagged_date(value)
    elif logical_type == "timestamp":
        _tagged_timestamp(value)
    elif logical_type == "json":
        _json_value(value)
    elif logical_type == "unknown":
        _opaque(value, str(field["source_type"]))


def _tagged_decimal(value: object) -> None:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "value"}
        or value.get("type") != "decimal"
    ):
        raise RewrittenResultContractError("decimal result cell is invalid")
    try:
        number = Decimal(value.get("value"))
    except (InvalidOperation, TypeError) as error:
        raise RewrittenResultContractError("decimal result cell is invalid") from error
    if not number.is_finite():
        raise RewrittenResultContractError("decimal result cell is non-finite")


def _tagged_date(value: object) -> None:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "value"}
        or value.get("type") != "date"
    ):
        raise RewrittenResultContractError("date result cell is invalid")
    try:
        date.fromisoformat(value["value"])
    except (TypeError, ValueError) as error:
        raise RewrittenResultContractError("date result cell is invalid") from error


def _tagged_timestamp(value: object) -> None:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"type", "value"}
        or value.get("type") != "timestamp"
    ):
        raise RewrittenResultContractError("timestamp result cell is invalid")
    try:
        datetime.fromisoformat(value["value"])
    except (TypeError, ValueError) as error:
        raise RewrittenResultContractError(
            "timestamp result cell is invalid"
        ) from error


def _opaque(value: object, source_type: str) -> None:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"encoding", "source_type", "type", "value"}
        or value.get("type") != "opaque"
        or value.get("encoding") != "json"
        or value.get("source_type") != source_type
    ):
        raise RewrittenResultContractError("opaque source type or encoding is invalid")
    _json_value(value.get("value"))


def _json_value(value: object) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RewrittenResultContractError("JSON result cell is non-finite")
        return
    if isinstance(value, list):
        for item in value:
            _json_value(item)
        return
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_value(item)
        return
    raise RewrittenResultContractError("JSON result cell is invalid")

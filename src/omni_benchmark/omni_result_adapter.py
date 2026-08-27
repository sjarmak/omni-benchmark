"""Strict adapter for Omni production-agent query actions and typed rows."""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .autoresearch_config import MANDATORY_FORBIDDEN_FIELDS


class OmniResultContractError(ValueError):
    """Raised when a completed Omni job has no scoreable governed result."""


@dataclass(frozen=True)
class ParsedOmniQuery:
    """Validated final agent query awaiting a type-faithful result rerun."""

    semantic_query: dict[str, Any]
    generated_query: str
    semantic_objects: tuple[str, ...]
    expected_columns: tuple[str, ...]
    expected_row_count: int
    expected_has_results: bool
    observed_actions_by_type: tuple[tuple[str, int], ...]
    agent_database_query_count: int


@dataclass(frozen=True)
class ParsedOmniResult:
    """One untruncated typed query result plus observable action telemetry."""

    generated_query: str
    semantic_objects: tuple[str, ...]
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    observed_actions_by_type: tuple[tuple[str, int], ...]
    database_query_count: int

    def as_result_artifact(self) -> dict[str, object]:
        """Return the canonical, type-faithful result-sidecar representation."""
        value = {
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
            "schema_version": 1,
            "truncated": False,
        }
        reject_forbidden_keys(value)
        _validate_json_value(value)
        return value


def parse_omni_job_result(response: Mapping[str, Any]) -> ParsedOmniQuery:
    """Validate every action and select the final successful governed query."""
    reject_forbidden_keys(response)
    actions = response.get("actions")
    if not isinstance(actions, list):
        raise OmniResultContractError("completed Omni result must expose actions")
    typed_actions = tuple(_validated_action(action) for action in actions)
    query_results = tuple(
        action["result"]
        for action in typed_actions
        if action["type"] == "generate_query"
    )
    successful = tuple(
        result for result in query_results if result["status"] == "success"
    )
    if not successful:
        raise OmniResultContractError(
            "completed Omni result has no successful query action"
        )
    selected = _validated_scoreable_query_result(successful[-1])
    return _parsed_query(selected, typed_actions, len(query_results))


def bind_typed_query_result(
    parsed: ParsedOmniQuery, rows: Sequence[Mapping[str, Any]]
) -> ParsedOmniResult:
    """Bind a raw JSON query rerun without coercing any cell values."""
    if not isinstance(rows, list):
        raise OmniResultContractError("typed Omni result must be an array")
    reject_forbidden_keys(rows)
    columns = _typed_columns(rows, parsed.expected_columns)
    typed_rows = tuple(_typed_row(row, columns) for row in rows)
    if len(typed_rows) != parsed.expected_row_count:
        raise OmniResultContractError("typed Omni query row count does not match CSV")
    if bool(typed_rows) != parsed.expected_has_results:
        raise OmniResultContractError(
            "typed Omni query result presence does not match CSV"
        )
    return ParsedOmniResult(
        generated_query=parsed.generated_query,
        semantic_objects=parsed.semantic_objects,
        columns=columns,
        rows=typed_rows,
        observed_actions_by_type=parsed.observed_actions_by_type,
        database_query_count=parsed.agent_database_query_count + 1,
    )


def reject_forbidden_keys(value: Any) -> None:
    """Reject hidden-label keys recursively before an artifact is serialized."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if _normalized_key(str(key)) in MANDATORY_FORBIDDEN_FIELDS:
                raise OmniResultContractError("Omni payload contains a forbidden field")
            reject_forbidden_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            reject_forbidden_keys(nested)


def _validated_action(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OmniResultContractError("Omni actions must be objects")
    for field in ("message", "timestamp", "type"):
        if field not in value:
            raise OmniResultContractError(f"Omni action {field} is missing")
        if not isinstance(value[field], str):
            raise OmniResultContractError(f"Omni action {field} must be a string")
    _validate_timestamp(value["timestamp"])
    if value["type"] == "generate_query":
        if "result" not in value or not isinstance(value["result"], Mapping):
            raise OmniResultContractError("Omni generate_query result is missing")
        return {**value, "result": _validated_query_result(value["result"])}
    return value


def _validated_query_result(value: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "csvResult",
        "csvResultWasTruncated",
        "hasResults",
        "query",
        "queryName",
        "status",
        "totalRowCount",
    )
    for field in required:
        if field not in value:
            raise OmniResultContractError(f"Omni query result {field} is missing")
    _validate_query_result_types(value)
    return dict(value)


def _validated_scoreable_query_result(value: Mapping[str, Any]) -> dict[str, Any]:
    if value["csvResultWasTruncated"]:
        raise OmniResultContractError("Omni query result is truncated")
    columns, row_count = _parse_csv(value["csvResult"])
    if row_count != value["totalRowCount"]:
        raise OmniResultContractError("Omni query row count does not match CSV")
    if value["hasResults"] != bool(row_count):
        raise OmniResultContractError("Omni query result presence does not match CSV")
    return {**value, "_validated_columns": columns}


def _validate_query_result_types(value: Mapping[str, Any]) -> None:
    if not isinstance(value["csvResult"], str):
        raise OmniResultContractError("Omni query result csvResult must be a string")
    if not isinstance(value["csvResultWasTruncated"], bool):
        raise OmniResultContractError(
            "Omni query result csvResultWasTruncated must be boolean"
        )
    if not isinstance(value["hasResults"], bool):
        raise OmniResultContractError("Omni query result hasResults must be boolean")
    if not isinstance(value["queryName"], str):
        raise OmniResultContractError("Omni query result queryName must be a string")
    if value["status"] not in {"success", "error"}:
        raise OmniResultContractError("Omni query result status is invalid")
    row_count = value["totalRowCount"]
    if type(row_count) is not int or row_count < 0:
        raise OmniResultContractError("Omni query result totalRowCount is invalid")
    _validate_semantic_query(value["query"])


def _validate_semantic_query(value: Any) -> None:
    if not isinstance(value, dict) or not value:
        raise OmniResultContractError("Omni query result query is invalid")
    fields = value.get("fields")
    if not isinstance(fields, list) or any(
        not isinstance(item, str) for item in fields
    ):
        raise OmniResultContractError("Omni semantic query fields are invalid")
    _validate_json_value(value)


def _parsed_query(
    selected: Mapping[str, Any],
    actions: Sequence[Mapping[str, Any]],
    database_query_count: int,
) -> ParsedOmniQuery:
    query = _json_copy(selected["query"])
    operational_types = [
        action["type"] for action in actions if action["type"] != "summarize"
    ]
    counts = Counter(operational_types)
    return ParsedOmniQuery(
        semantic_query=query,
        generated_query=_canonical_json(query),
        semantic_objects=_semantic_objects(query),
        expected_columns=selected["_validated_columns"],
        expected_row_count=selected["totalRowCount"],
        expected_has_results=selected["hasResults"],
        observed_actions_by_type=tuple(sorted(counts.items())),
        agent_database_query_count=database_query_count,
    )


def _parse_csv(value: str) -> tuple[tuple[str, ...], int]:
    try:
        parsed = list(csv.reader(io.StringIO(value, newline=""), strict=True))
    except csv.Error as error:
        raise OmniResultContractError("Omni query result CSV is invalid") from error
    if not parsed or not parsed[0] or any(not column for column in parsed[0]):
        raise OmniResultContractError("Omni query result CSV has no valid header")
    columns = tuple(parsed[0])
    if len(set(columns)) != len(columns):
        raise OmniResultContractError("Omni query result CSV has duplicate columns")
    if any(len(row) != len(columns) for row in parsed[1:]):
        raise OmniResultContractError("Omni query result CSV rows are ragged")
    for column in columns:
        reject_forbidden_keys({column: None})
    return columns, len(parsed) - 1


def _typed_row(value: Mapping[str, Any], columns: tuple[str, ...]) -> tuple[Any, ...]:
    if not isinstance(value, dict):
        raise OmniResultContractError("typed Omni result rows must be objects")
    if set(value) != set(columns):
        raise OmniResultContractError("typed Omni result columns do not match CSV")
    _validate_json_value(value)
    return tuple(value[column] for column in columns)


def _typed_columns(
    rows: Sequence[Mapping[str, Any]], expected_columns: tuple[str, ...]
) -> tuple[str, ...]:
    if not rows:
        return expected_columns
    first = rows[0]
    if not isinstance(first, dict):
        raise OmniResultContractError("typed Omni result rows must be objects")
    columns = tuple(first)
    if len(columns) != len(expected_columns):
        raise OmniResultContractError("typed Omni result columns do not match CSV")
    return columns


def _validate_timestamp(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise OmniResultContractError("Omni action timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise OmniResultContractError("Omni action timestamp must include a timezone")


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OmniResultContractError("Omni JSON contains a non-finite number")
        return
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise OmniResultContractError("Omni JSON object keys must be strings")
        for nested in value.values():
            _validate_json_value(nested)
        return
    if isinstance(value, list):
        for nested in value:
            _validate_json_value(nested)
        return
    raise OmniResultContractError("Omni result contains a non-JSON value")


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    copied = json.loads(_canonical_json(value))
    if not isinstance(copied, dict):
        raise OmniResultContractError("Omni semantic query is not an object")
    return copied


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _semantic_objects(query: Mapping[str, Any]) -> tuple[str, ...]:
    objects: set[str] = set()
    for key, value in query.items():
        if key == "fields" and isinstance(value, list):
            objects.update(item for item in value if isinstance(item, str) and item)
        elif key == "filters" and isinstance(value, Mapping):
            objects.update(item for item in value if isinstance(item, str) and item)
        if isinstance(value, Mapping):
            objects.update(_semantic_objects(value))
        elif isinstance(value, list):
            objects.update(
                child
                for item in value
                if isinstance(item, Mapping)
                for child in _semantic_objects(item)
            )
    return tuple(sorted(objects))


def _normalized_key(value: str) -> str:
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    separated = re.sub(r"[^A-Za-z0-9]+", "_", snake.strip())
    return separated.strip("_").lower()

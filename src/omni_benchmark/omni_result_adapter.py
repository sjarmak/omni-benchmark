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
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .autoresearch_config import MANDATORY_FORBIDDEN_FIELDS


class OmniResultContractError(ValueError):
    """Raised when a completed Omni job has no scoreable governed result."""


class OmniUnsupportedResultTypeError(OmniResultContractError):
    """Raised when Omni does not expose a type-faithful result field type."""


SUPPORTED_OMNI_RESULT_TYPES = frozenset(
    {"BOOLEAN", "DATE", "JSON", "NUMBER", "STRING", "TIMESTAMP", "YESNO"}
)


_TRUNCATED_CSV_MARKER = re.compile(
    r"# (?:FIRST [0-9]+ ROWS:|"
    r"SAMPLED [0-9]+ ROWS FROM MIDDLE \(rows [0-9]+-[0-9]+\):|"
    r"LAST [0-9]+ ROWS:)"
)


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
    parsed: ParsedOmniQuery,
    rows: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
) -> ParsedOmniResult:
    """Bind a complete JSON rerun using only authoritative Omni field types."""
    if not isinstance(rows, list):
        raise OmniResultContractError("typed Omni result must be an array")
    reject_forbidden_keys(rows)
    columns = _typed_columns(rows, parsed.expected_columns)
    data_types = _planned_data_types(parsed, plan, columns)
    typed_rows = tuple(_typed_row(row, columns, data_types) for row in rows)
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
        database_query_count=parsed.agent_database_query_count,
    )


def build_replayed_result_artifact(
    semantic_query: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
) -> dict[str, object]:
    """Build a typed sidecar by replaying an already-generated semantic query."""
    if not isinstance(semantic_query, Mapping) or not semantic_query:
        raise OmniResultContractError("replayed Omni query must be a non-empty object")
    fields = _semantic_query_fields(semantic_query)
    if not isinstance(rows, list):
        raise OmniResultContractError("typed Omni result must be an array")
    columns = _typed_columns(rows, tuple(fields))
    parsed = ParsedOmniQuery(
        semantic_query=dict(semantic_query),
        generated_query=json.dumps(
            semantic_query, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ),
        semantic_objects=(),
        expected_columns=columns,
        expected_row_count=len(rows),
        expected_has_results=bool(rows),
        observed_actions_by_type=(),
        agent_database_query_count=0,
    )
    return bind_typed_query_result(parsed, rows, plan).as_result_artifact()


def planned_query_data_types(
    semantic_query: Mapping[str, Any], plan: Mapping[str, Any]
) -> tuple[str, ...]:
    """Return authoritative planner types before deciding whether replay is safe."""
    fields = _semantic_query_fields(semantic_query)
    parsed = ParsedOmniQuery(
        semantic_query=dict(semantic_query),
        generated_query="",
        semantic_objects=(),
        expected_columns=fields,
        expected_row_count=0,
        expected_has_results=False,
        observed_actions_by_type=(),
        agent_database_query_count=0,
    )
    return _planned_data_types(parsed, plan, fields, require_supported=False)


def decode_result_artifact_rows(
    artifact: Mapping[str, Any],
) -> tuple[tuple[Any, ...], ...]:
    """Decode persisted typed cells for the frozen execution scorers."""
    if not isinstance(artifact, Mapping):
        raise OmniResultContractError("result artifact must be an object")
    reject_forbidden_keys(artifact)
    if set(artifact) != {"columns", "rows", "schema_version", "truncated"}:
        raise OmniResultContractError("result artifact has an invalid schema")
    columns = artifact["columns"]
    rows = artifact["rows"]
    if (
        not isinstance(columns, list)
        or any(not isinstance(column, str) or not column for column in columns)
        or len(set(columns)) != len(columns)
        or not isinstance(rows, list)
        or artifact["schema_version"] != 1
        or artifact["truncated"] is not False
    ):
        raise OmniResultContractError("result artifact has invalid metadata")
    decoded: list[tuple[Any, ...]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise OmniResultContractError("result artifact rows are ragged")
        decoded.append(tuple(_decode_typed_cell(cell) for cell in row))
    return tuple(decoded)


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
    for field in ("message", "type"):
        if field not in value:
            raise OmniResultContractError(f"Omni action {field} is missing")
        if not isinstance(value[field], str):
            raise OmniResultContractError(f"Omni action {field} must be a string")
    timestamp = value.get("timestamp")
    if timestamp is None and value["type"] == "failure":
        _validate_failure_action(value)
    elif timestamp is None:
        raise OmniResultContractError("Omni action timestamp is missing")
    elif not isinstance(timestamp, str):
        raise OmniResultContractError("Omni action timestamp must be a string")
    else:
        _validate_timestamp(timestamp)
    if value["type"] == "generate_query":
        if "result" not in value or not isinstance(value["result"], Mapping):
            raise OmniResultContractError("Omni generate_query result is missing")
        return {
            **value,
            "result": _validated_query_result(
                value["result"], failed_action=value.get("isError") is True
            ),
        }
    return value


def _validated_query_result(
    value: Mapping[str, Any], *, failed_action: bool
) -> dict[str, Any]:
    if value.get("status") == "error" and "csvResult" not in value:
        return _validated_failed_query_result(value, failed_action=failed_action)
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


def _validated_failed_query_result(
    value: Mapping[str, Any], *, failed_action: bool
) -> dict[str, Any]:
    if not failed_action:
        raise OmniResultContractError(
            "Omni failed generate_query action must expose isError"
        )
    required = ("error", "query", "queryName", "resultId", "status")
    for field in required:
        if field not in value:
            raise OmniResultContractError(f"Omni query result {field} is missing")
    if set(value) != set(required):
        raise OmniResultContractError("Omni failed query result schema is invalid")
    error = value["error"]
    if not isinstance(error, Mapping):
        raise OmniResultContractError("Omni query result error must be an object")
    for field in ("detail", "message"):
        if field not in error:
            raise OmniResultContractError(f"Omni query result error {field} is missing")
        if not isinstance(error[field], str):
            raise OmniResultContractError(
                f"Omni query result error {field} must be a string"
            )
    if set(error) != {"detail", "message"}:
        raise OmniResultContractError("Omni query result error schema is invalid")
    for field in ("queryName", "resultId"):
        if not isinstance(value[field], str) or not value[field]:
            raise OmniResultContractError(
                f"Omni query result {field} must be a non-empty string"
            )
    _validate_semantic_query(value["query"])
    return dict(value)


def _validated_scoreable_query_result(value: Mapping[str, Any]) -> dict[str, Any]:
    columns, row_count = _parse_csv(
        value["csvResult"], truncated=value["csvResultWasTruncated"]
    )
    if value["csvResultWasTruncated"]:
        if row_count > value["totalRowCount"]:
            raise OmniResultContractError("Omni query preview exceeds total row count")
    elif row_count != value["totalRowCount"]:
        raise OmniResultContractError("Omni query row count does not match CSV")
    if value["hasResults"] != bool(value["totalRowCount"]):
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


def _parse_csv(value: str, *, truncated: bool) -> tuple[tuple[str, ...], int]:
    try:
        parsed = list(csv.reader(io.StringIO(value, newline=""), strict=True))
    except csv.Error as error:
        raise OmniResultContractError("Omni query result CSV is invalid") from error
    if not parsed or not parsed[0] or any(not column for column in parsed[0]):
        raise OmniResultContractError("Omni query result CSV has no valid header")
    columns = tuple(parsed[0])
    if len(set(columns)) != len(columns):
        raise OmniResultContractError("Omni query result CSV has duplicate columns")
    rows = [
        row
        for row in parsed[1:]
        if not (
            truncated
            and len(row) == 1
            and _TRUNCATED_CSV_MARKER.fullmatch(row[0]) is not None
        )
    ]
    if any(len(row) != len(columns) for row in rows):
        raise OmniResultContractError("Omni query result CSV rows are ragged")
    for column in columns:
        reject_forbidden_keys({column: None})
    return columns, len(rows)


def _validate_failure_action(value: Mapping[str, Any]) -> None:
    duration = value.get("durationMs")
    if (
        value.get("isError") is not True
        or not isinstance(value.get("toolName"), str)
        or not value["toolName"]
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise OmniResultContractError("Omni failure action is invalid")


def _typed_row(
    value: Mapping[str, Any],
    columns: tuple[str, ...],
    data_types: tuple[str, ...],
) -> tuple[Any, ...]:
    if not isinstance(value, dict):
        raise OmniResultContractError("typed Omni result rows must be objects")
    if set(value) != set(columns):
        raise OmniResultContractError("typed Omni result columns do not match CSV")
    _validate_json_value(value)
    return tuple(
        _typed_cell(value[column], data_type)
        for column, data_type in zip(columns, data_types, strict=True)
    )


def _typed_columns(
    rows: Sequence[Mapping[str, Any]], expected_columns: tuple[str, ...]
) -> tuple[str, ...]:
    if not rows:
        return expected_columns
    first = rows[0]
    if not isinstance(first, dict):
        raise OmniResultContractError("typed Omni result rows must be objects")
    columns = tuple(first)
    if len(columns) != len(expected_columns) or len(set(columns)) != len(columns):
        raise OmniResultContractError("typed Omni result columns do not match CSV")
    return columns


def _planned_data_types(
    parsed: ParsedOmniQuery,
    plan: Mapping[str, Any],
    columns: tuple[str, ...],
    *,
    require_supported: bool = True,
) -> tuple[str, ...]:
    if not isinstance(plan, Mapping) or plan.get("status") != "PLANNED":
        raise OmniResultContractError("Omni query plan must reach PLANNED")
    summary = plan.get("summary")
    if not isinstance(summary, Mapping):
        raise OmniResultContractError("Omni query plan summary is missing")
    if summary.get("missing_fields") != [] or summary.get("invalid_calculations") != {}:
        raise OmniResultContractError("Omni query plan contains invalid fields")
    fields = summary.get("fields")
    query_fields = parsed.semantic_query.get("fields")
    planned_query = plan.get("query")
    model_job = (
        planned_query.get("model_job") if isinstance(planned_query, Mapping) else None
    )
    planned_fields = model_job.get("fields") if isinstance(model_job, Mapping) else None
    if (
        not isinstance(fields, Mapping)
        or not isinstance(query_fields, list)
        or not query_fields
        or any(not isinstance(field, str) or not field for field in query_fields)
        or len(set(query_fields)) != len(query_fields)
        or not isinstance(planned_fields, list)
        or planned_fields != query_fields
        or any(field not in fields for field in query_fields)
        or len(query_fields) != len(columns)
    ):
        raise OmniResultContractError("Omni query plan field metadata is ambiguous")
    data_types: list[str] = []
    for field_name in query_fields:
        metadata = fields.get(field_name)
        data_type = metadata.get("data_type") if isinstance(metadata, Mapping) else None
        if not isinstance(data_type, str) or not data_type:
            raise OmniResultContractError(
                f"Omni query plan has invalid data type metadata for {field_name}"
            )
        if require_supported and data_type not in SUPPORTED_OMNI_RESULT_TYPES:
            raise OmniUnsupportedResultTypeError(
                f"Omni query plan has unsupported data type for {field_name}"
            )
        data_types.append(data_type)
    return tuple(data_types)


def _semantic_query_fields(semantic_query: Mapping[str, Any]) -> tuple[str, ...]:
    if not isinstance(semantic_query, Mapping) or not semantic_query:
        raise OmniResultContractError("replayed Omni query must be a non-empty object")
    fields = semantic_query.get("fields")
    if (
        not isinstance(fields, list)
        or not fields
        or any(not isinstance(field, str) or not field for field in fields)
        or len(set(fields)) != len(fields)
    ):
        raise OmniResultContractError("replayed Omni query fields are invalid")
    return tuple(fields)


def _typed_cell(value: Any, data_type: str) -> Any:
    if value is None or (value == "" and data_type != "STRING"):
        return None
    if data_type == "STRING":
        if not isinstance(value, str):
            raise OmniResultContractError("Omni STRING result must be a string")
        return value
    if data_type in {"BOOLEAN", "YESNO"}:
        if not isinstance(value, bool):
            raise OmniResultContractError("Omni Boolean result must be boolean")
        return value
    if data_type == "NUMBER":
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise OmniResultContractError("Omni NUMBER result is invalid")
        try:
            number = Decimal(str(value))
        except InvalidOperation as error:
            raise OmniResultContractError("Omni NUMBER result is invalid") from error
        if not number.is_finite():
            raise OmniResultContractError("Omni NUMBER result is non-finite")
        return {"type": "decimal", "value": str(number)}
    if data_type == "DATE":
        if not isinstance(value, str):
            raise OmniResultContractError("Omni DATE result must be a string")
        try:
            normalized = date.fromisoformat(value).isoformat()
        except ValueError as error:
            raise OmniResultContractError("Omni DATE result is invalid") from error
        return {"type": "date", "value": normalized}
    if data_type == "TIMESTAMP":
        if not isinstance(value, str):
            raise OmniResultContractError("Omni TIMESTAMP result must be a string")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise OmniResultContractError("Omni TIMESTAMP result is invalid") from error
        return {"type": "datetime", "value": parsed.isoformat()}
    if data_type == "JSON":
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as error:
                raise OmniResultContractError("Omni JSON result is invalid") from error
        _validate_json_value(parsed)
        return {"type": "json", "value": parsed}
    raise OmniResultContractError("Omni query plan data type is unsupported")


def _decode_typed_cell(value: Any) -> Any:
    if not isinstance(value, Mapping) or set(value) != {"type", "value"}:
        _validate_json_value(value)
        return value
    kind = value["type"]
    raw = value["value"]
    if kind == "json":
        _validate_json_value(raw)
        return raw
    if not isinstance(kind, str) or not isinstance(raw, str):
        raise OmniResultContractError("typed result cell is invalid")
    try:
        if kind == "decimal":
            decoded = Decimal(raw)
            if not decoded.is_finite():
                raise ValueError
            return decoded
        if kind == "date":
            return date.fromisoformat(raw)
        if kind == "datetime":
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (InvalidOperation, ValueError) as error:
        raise OmniResultContractError("typed result cell is invalid") from error
    raise OmniResultContractError("typed result cell kind is unsupported")


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

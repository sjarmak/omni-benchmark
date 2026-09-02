"""Rows derived from one frozen generation record and its sibling artifacts.

A generation record is identified by the sha256 of its raw JSONL line, which is
the key every score artifact carries. The trace and action-evidence files next
to it map onto ``trace_event`` and ``action_evidence`` rows under that key.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .custody import reject_forbidden_fields
from .rows import Row

ATTEMPT_ID_SEGMENTS = 4
ACTION_EVIDENCE_KIND = "direct-action-evidence"


class ReaderError(ValueError):
    """Raised when a source artifact is structurally malformed."""


@dataclass(frozen=True)
class GenerationRecord:
    """One generation.jsonl line with the hash that names it in score artifacts."""

    record: Mapping[str, Any]
    sha256: str
    path: Path
    line_number: int

    @property
    def context(self) -> str:
        return f"{self.path}:{self.line_number}"

    @property
    def attempt_id(self) -> str:
        return str(self.record["attempt_id"])

    @property
    def run_id(self) -> str:
        return str(self.record["run_id"])

    @property
    def instance_id(self) -> str:
        return str(self.record["instance_id"])

    @property
    def condition(self) -> str:
        return str(self.record["condition"])


def parse_json_object(raw: str | bytes, noun: str, context: str) -> dict[str, Any]:
    """One JSON object from a raw line or document; anything else is an error.

    ``noun`` names what was being read so the message says which artifact was
    malformed, not merely that some JSON was.
    """
    try:
        value = json.loads(raw)
    except ValueError as error:
        raise ReaderError(f"{context}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ReaderError(f"{context}: {noun} is not an object")
    return value


def read_generation_records(path: Path) -> tuple[GenerationRecord, ...]:
    """Parse every record of a generation.jsonl, hashing each raw line."""
    records: list[GenerationRecord] = []
    for number, raw in enumerate(path.read_bytes().splitlines(keepends=True), 1):
        if not raw.strip():
            continue
        context = f"{path}:{number}"
        record = parse_json_object(raw, "generation record", context)
        reject_forbidden_fields(record, context)
        _validate_record_identity(record, context)
        records.append(
            GenerationRecord(
                record=MappingProxyType(record),
                sha256=hashlib.sha256(raw).hexdigest(),
                path=path,
                line_number=number,
            )
        )
    return tuple(records)


def _validate_record_identity(record: Mapping[str, Any], context: str) -> None:
    for key in ("attempt_id", "run_id", "instance_id", "condition", "partition"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ReaderError(f"{context}: {key} must be a non-empty string")
    if not isinstance(record.get("repetition"), int):
        raise ReaderError(f"{context}: repetition must be an integer")
    segments = record["attempt_id"].split(":")
    if len(segments) != ATTEMPT_ID_SEGMENTS:
        raise ReaderError(f"{context}: attempt_id must have four ':' segments")
    expected = (record["instance_id"], record["condition"], str(record["repetition"]))
    if tuple(segments[1:]) != expected:
        raise ReaderError(f"{context}: attempt_id disagrees with record fields")


def instance_of_attempt_id(attempt_id: str, context: str) -> str:
    """The instance segment of ``run:instance:condition:repetition``."""
    segments = attempt_id.split(":")
    if len(segments) != ATTEMPT_ID_SEGMENTS:
        raise ReaderError(f"{context}: attempt_id {attempt_id!r} is malformed")
    return segments[1]


def parse_timestamp(value: Any, context: str) -> datetime | None:
    """RFC 3339 text to an aware datetime; None stays None."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReaderError(f"{context}: timestamp must be text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReaderError(f"{context}: invalid timestamp {value!r}") from error
    if parsed.tzinfo is None:
        raise ReaderError(f"{context}: timestamp {value!r} has no offset")
    return parsed


def as_integer(value: Any, context: str) -> int | None:
    """Integers and integral floats only; a fractional value is an error."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ReaderError(f"{context}: expected an integer, got a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ReaderError(f"{context}: expected an integer, got {value!r}")


def as_float(value: Any, context: str) -> float | None:
    """Finite integers and floats as float; anything else is an error."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReaderError(f"{context}: expected a number, got {value!r}")
    if not math.isfinite(value):
        raise ReaderError(f"{context}: expected a finite number, got {value!r}")
    return float(value)


def as_text(value: Any, context: str) -> str | None:
    if value is None or isinstance(value, str):
        return value
    raise ReaderError(f"{context}: expected text, got {type(value).__name__}")


def as_boolean(value: Any, context: str) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise ReaderError(f"{context}: expected a boolean, got {type(value).__name__}")


def as_decimal(value: Any, context: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ReaderError(f"{context}: expected a numeric value, got {value!r}")
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise ReaderError(f"{context}: invalid numeric value {value!r}") from error


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ReaderError(f"{context}: expected an object")
    return value


def attempt_row(
    generation: GenerationRecord,
    *,
    arm: str,
    database: str,
    partition: str,
    artifact_dir: str,
) -> Row:
    """The ``attempt`` row for one generation record.

    ``database`` and ``partition`` come from the question release, not from the
    record, so an attempt's partition is what the committed split files say.
    """
    record, context = generation.record, generation.context
    model = _mapping(record.get("model"), f"{context}: model")
    usage = _mapping(record.get("token_usage"), f"{context}: token_usage")
    values = {
        "attempt_id": generation.attempt_id,
        "generation_record_sha256": generation.sha256,
        "run_id": generation.run_id,
        "instance_id": generation.instance_id,
        "database": database,
        "condition": generation.condition,
        "arm": arm,
        "repetition": record["repetition"],
        "partition": partition,
        "started_at": parse_timestamp(record.get("started_at"), context),
        "finished_at": parse_timestamp(record.get("finished_at"), context),
        "latency_ms": as_float(record.get("latency_ms"), f"{context}: latency_ms"),
        "model_name": as_text(model.get("name"), f"{context}: model.name"),
        "model_provider": as_text(model.get("provider"), f"{context}: model.provider"),
        "cost_usd": as_decimal(record.get("cost_usd"), f"{context}: cost_usd"),
        "tool_calls_by_name": record.get("tool_calls_by_name"),
        "trace_captured": as_boolean(record.get("trace_captured"), context),
        "trace_truncated": as_boolean(record.get("trace_truncated"), context),
        "telemetry_unavailable": record.get("telemetry_unavailable"),
        "artifact_dir": artifact_dir,
        "generation_record": dict(record),
    }
    for column in _ATTEMPT_TEXT_COLUMNS:
        values[column] = as_text(record.get(column), f"{context}: {column}")
    for column in _ATTEMPT_USAGE_COLUMNS:
        values[column] = as_integer(usage.get(column), f"{context}: {column}")
    for column in _ATTEMPT_COUNT_COLUMNS:
        values[column] = as_integer(record.get(column), f"{context}: {column}")
    return Row("attempt", values)


_ATTEMPT_USAGE_COLUMNS = ("input_tokens", "output_tokens", "total_tokens")
_ATTEMPT_COUNT_COLUMNS = (
    "tool_call_count",
    "database_query_count",
    "retry_count",
    "validation_attempt_count",
)
_ATTEMPT_TEXT_COLUMNS = (
    "token_source",
    "cost_source",
    "cost_unavailable_reason",
    "generation_outcome",
    "execution_status",
    "failure_origin",
    "terminal_failure_class",
    "harness_failure",
    "generated_sql",
    "generated_query",
    "query_unavailable_reason",
    "actual_result_status",
    "actual_result_hash",
    "trace_degraded_reason",
)

_TRACE_TEXT_COLUMNS = (
    "component",
    "event_type",
    "tool_name",
    "status",
    "failure_class",
    "model",
    "provider",
    "metadata_sha256",
)
_TRACE_FLOAT_COLUMNS = ("duration_ms", "elapsed_ms")
_TRACE_BIGINT_COLUMNS = ("input_tokens", "output_tokens")
_TRACE_DELTA_COLUMNS = (
    "retry_delta",
    "tool_call_delta",
    "database_query_delta",
    "validation_attempt_delta",
)


def trace_event_rows(path: Path, generation: GenerationRecord) -> tuple[Row, ...]:
    """``trace_event`` rows from the attempt trace, verified against the record."""
    data = path.read_bytes()
    expected = generation.record.get("trace_sha256")
    if expected is not None and hashlib.sha256(data).hexdigest() != expected:
        raise ReaderError(f"{path}: sha256 differs from trace_sha256 in the record")
    rows: dict[int, Row] = {}
    for number, raw in enumerate(data.decode("utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        context = f"{path}:{number}"
        event = parse_json_object(raw, "trace event", context)
        reject_forbidden_fields(event, context)
        seq = event.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise ReaderError(f"{context}: seq must be an integer")
        if seq in rows:
            raise ReaderError(f"{context}: duplicate trace seq {seq}")
        rows[seq] = _trace_row(event, seq, generation, context)
    return tuple(rows[seq] for seq in sorted(rows))


def _trace_row(
    event: Mapping[str, Any], seq: int, generation: GenerationRecord, context: str
) -> Row:
    values: dict[str, Any] = {
        "attempt_id": generation.attempt_id,
        "generation_record_sha256": generation.sha256,
        "seq": seq,
        "timestamp": parse_timestamp(event.get("timestamp"), context),
    }
    for column in _TRACE_TEXT_COLUMNS:
        values[column] = as_text(event.get(column), f"{context}: {column}")
    for column in _TRACE_FLOAT_COLUMNS:
        values[column] = as_float(event.get(column), f"{context}: {column}")
    for column in _TRACE_BIGINT_COLUMNS + _TRACE_DELTA_COLUMNS:
        values[column] = as_integer(event.get(column), f"{context}: {column}")
    return Row("trace_event", values)


def action_evidence_rows(path: Path, generation: GenerationRecord) -> tuple[Row, ...]:
    """``action_evidence`` rows from a direct arm's action-evidence file."""
    payload = parse_json_object(
        path.read_text(encoding="utf-8"), "action-evidence payload", str(path)
    )
    reject_forbidden_fields(payload, str(path))
    if payload.get("kind") != ACTION_EVIDENCE_KIND:
        raise ReaderError(f"{path}: kind is not {ACTION_EVIDENCE_KIND!r}")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ReaderError(f"{path}: records must be a list")
    rows: dict[int, Row] = {}
    for index, record in enumerate(records):
        context = f"{path}: records[{index}]"
        if not isinstance(record, dict):
            raise ReaderError(f"{context}: expected an object")
        seq = record.get("trace_seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise ReaderError(f"{context}: trace_seq must be an integer")
        if seq in rows:
            raise ReaderError(f"{context}: duplicate trace_seq {seq}")
        ids = record.get("retrieved_public_ids")
        if ids is not None and not isinstance(ids, list):
            raise ReaderError(f"{context}: retrieved_public_ids must be a list")
        rows[seq] = Row(
            "action_evidence",
            {
                "attempt_id": generation.attempt_id,
                "generation_record_sha256": generation.sha256,
                "trace_seq": seq,
                "tool_name": as_text(record.get("tool_name"), context),
                "retrieval_query": as_text(record.get("retrieval_query"), context),
                "retrieved_public_ids": ids,
                "exploratory_sql": as_text(record.get("exploratory_sql"), context),
            },
        )
    return tuple(rows[seq] for seq in sorted(rows))

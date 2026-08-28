"""Versioned receipt binding direct-capture artifacts to one exact runtime."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
import math
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from .direct_capture_contract import DirectModelTurnProvenance, DirectProbeResult
from .direct_runtime_binding import DirectRuntimeBinding, DirectRuntimeIdentityError

_FIELDS = frozenset(
    {
        "action_evidence_path",
        "action_evidence_sha256",
        "artifact_root_identity",
        "attempt_id",
        "capture_summary",
        "generated_sql_sha256",
        "result_path",
        "result_sha256",
        "runtime_binding",
        "runtime_binding_sha256",
        "schema_version",
        "trace_path",
        "trace_sha256",
    }
)
_SUMMARY_FIELDS = frozenset(
    {
        "cost_source",
        "cost_usd",
        "database_query_count",
        "failure_class",
        "failure_origin",
        "finished_at",
        "generation_outcome",
        "latency_ms",
        "model_turn_provenance",
        "retry_count",
        "semantic_objects",
        "started_at",
        "token_source",
        "token_usage",
        "tool_call_count",
        "tool_calls_by_name",
        "validation_attempt_count",
    }
)


class DirectCaptureReceiptError(ValueError):
    """Raised when a capture receipt can be substituted or is malformed."""


def capture_receipt_payload(
    *,
    store: ArtifactStore,
    binding: DirectRuntimeBinding,
    sql: str | None,
    trace: StoredArtifact,
    action_evidence: StoredArtifact,
    result: StoredArtifact | None,
    capture_summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Build and self-validate an exact version-4 capture receipt."""
    summary = _canonical_capture_summary(capture_summary)
    payload = {
        "action_evidence_path": store.relative_path(action_evidence).as_posix(),
        "action_evidence_sha256": action_evidence.sha256,
        "artifact_root_identity": store.root_identity,
        "attempt_id": binding.attempt_id,
        "capture_summary": summary,
        "generated_sql_sha256": _sql_sha256(sql),
        "result_path": store.relative_path(result).as_posix() if result else None,
        "result_sha256": result.sha256 if result else None,
        "runtime_binding": binding.as_dict(),
        "runtime_binding_sha256": binding.sha256(),
        "schema_version": 4,
        "trace_path": store.relative_path(trace).as_posix(),
        "trace_sha256": trace.sha256,
    }
    validate_capture_receipt_payload(
        payload,
        binding=binding,
        store=store,
        sql=sql,
        trace=trace,
        action_evidence=action_evidence,
        result=result,
        capture_summary=summary,
    )
    return payload


def validate_capture_receipt_payload(
    value: object,
    *,
    binding: DirectRuntimeBinding,
    store: ArtifactStore,
    sql: str | None,
    trace: StoredArtifact,
    action_evidence: StoredArtifact,
    result: StoredArtifact | None,
    capture_summary: Mapping[str, Any],
) -> None:
    """Reject receipt replay or substitution across any runtime/artifact boundary."""
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise DirectCaptureReceiptError("capture receipt must use the exact schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != 4:
        raise DirectCaptureReceiptError("capture receipt schema_version must equal 4")
    try:
        embedded = DirectRuntimeBinding.from_dict(value["runtime_binding"])
    except DirectRuntimeIdentityError as error:
        raise DirectCaptureReceiptError(
            "capture receipt runtime binding is invalid"
        ) from error
    if embedded != binding or value["runtime_binding_sha256"] != binding.sha256():
        raise DirectCaptureReceiptError(
            "capture receipt runtime binding does not match"
        )
    actual_summary = _canonical_capture_summary(value["capture_summary"])
    expected_summary = _canonical_capture_summary(capture_summary)
    if actual_summary != expected_summary:
        raise DirectCaptureReceiptError(
            "capture receipt capture summary does not match capture"
        )
    expected = {
        "action_evidence_path": _artifact_path(store, action_evidence),
        "action_evidence_sha256": action_evidence.sha256,
        "artifact_root_identity": store.root_identity,
        "attempt_id": binding.attempt_id,
        "generated_sql_sha256": _sql_sha256(sql),
        "result_path": _artifact_path(store, result),
        "result_sha256": result.sha256 if result else None,
        "trace_path": _artifact_path(store, trace),
        "trace_sha256": trace.sha256,
    }
    for field, expected_value in expected.items():
        if value[field] != expected_value:
            raise DirectCaptureReceiptError(
                f"capture receipt {field} does not match capture"
            )


def capture_summary_from_probe(probe: DirectProbeResult) -> dict[str, Any]:
    """Return the canonical output and measurement summary for one probe."""
    if not isinstance(probe, DirectProbeResult):
        raise DirectCaptureReceiptError("capture summary requires DirectProbeResult")
    return capture_summary_payload(
        generation_outcome=probe.generation_outcome,
        failure_class=probe.failure_class,
        failure_origin=probe.failure_origin,
        semantic_objects=probe.semantic_objects,
        tool_calls_by_name=probe.tool_calls_by_name,
        tool_call_count=probe.tool_call_count,
        database_query_count=probe.database_query_count,
        validation_attempt_count=probe.validation_attempt_count,
        retry_count=probe.retry_count,
        token_usage=probe.token_usage,
        token_source=probe.token_source,
        cost_usd=probe.cost_usd,
        cost_source=probe.cost_source,
        started_at=probe.started_at,
        finished_at=probe.finished_at,
        latency_ms=probe.latency_ms,
        model_turn_provenance=probe.model_turn_provenance,
    )


def capture_summary_payload(
    *,
    generation_outcome: str,
    failure_class: str | None,
    failure_origin: str | None,
    semantic_objects: tuple[str, ...],
    tool_calls_by_name: tuple[tuple[str, int], ...],
    tool_call_count: int,
    database_query_count: int | None,
    validation_attempt_count: int,
    retry_count: int | None,
    token_usage: Mapping[str, int] | None,
    token_source: str,
    cost_usd: float | None,
    cost_source: str,
    started_at: str,
    finished_at: str,
    latency_ms: float,
    model_turn_provenance: tuple[DirectModelTurnProvenance, ...],
) -> dict[str, Any]:
    """Create the canonical JSON representation of a capture summary."""
    return _canonical_capture_summary(
        {
            "cost_source": cost_source,
            "cost_usd": cost_usd,
            "database_query_count": database_query_count,
            "failure_class": failure_class,
            "failure_origin": failure_origin,
            "finished_at": finished_at,
            "generation_outcome": generation_outcome,
            "latency_ms": latency_ms,
            "model_turn_provenance": [
                record.as_dict() for record in model_turn_provenance
            ],
            "retry_count": retry_count,
            "semantic_objects": list(semantic_objects),
            "started_at": started_at,
            "token_source": token_source,
            "token_usage": None if token_usage is None else dict(token_usage),
            "tool_call_count": tool_call_count,
            "tool_calls_by_name": [
                {"count": count, "name": name} for name, count in tool_calls_by_name
            ],
            "validation_attempt_count": validation_attempt_count,
        }
    )


def _canonical_capture_summary(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SUMMARY_FIELDS:
        raise DirectCaptureReceiptError("capture summary must use the exact schema")
    summary = dict(value)
    summary["model_turn_provenance"] = _canonical_model_turn_provenance(
        summary["model_turn_provenance"]
    )
    _validate_summary_outcome(summary)
    _validate_summary_counts(summary)
    _validate_summary_usage(summary)
    _validate_summary_measurements(summary)
    return summary


def _canonical_model_turn_provenance(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise DirectCaptureReceiptError(
            "capture summary model turn provenance must be an array"
        )
    try:
        records = [DirectModelTurnProvenance.from_dict(item) for item in value]
    except ValueError as error:
        raise DirectCaptureReceiptError(
            "capture summary model turn provenance is invalid"
        ) from error
    trace_seqs = [record.trace_seq for record in records]
    if trace_seqs != sorted(set(trace_seqs)):
        raise DirectCaptureReceiptError(
            "capture summary model turn provenance is not canonical"
        )
    return [record.as_dict() for record in records]


def _validate_summary_outcome(summary: Mapping[str, Any]) -> None:
    outcome = summary["generation_outcome"]
    failure = summary["failure_class"]
    origin = summary["failure_origin"]
    if outcome not in {"answered", "refused", "errored"}:
        raise DirectCaptureReceiptError("capture summary outcome is invalid")
    if (outcome == "answered") != (failure is None):
        raise DirectCaptureReceiptError("capture summary terminal state is invalid")
    if failure is not None and (not isinstance(failure, str) or not failure):
        raise DirectCaptureReceiptError("capture summary failure class is invalid")
    if origin not in {None, "evaluated_system", "benchmark_infrastructure"}:
        raise DirectCaptureReceiptError("capture summary failure origin is invalid")
    if (failure is None) != (origin is None):
        raise DirectCaptureReceiptError(
            "capture summary failure origin is inconsistent"
        )


def _validate_summary_counts(summary: Mapping[str, Any]) -> None:
    for field in (
        "database_query_count",
        "retry_count",
    ):
        value = summary[field]
        if value is not None and (type(value) is not int or value < 0):
            raise DirectCaptureReceiptError(f"capture summary {field} is invalid")
    for field in ("tool_call_count", "validation_attempt_count"):
        value = summary[field]
        if type(value) is not int or value < 0:
            raise DirectCaptureReceiptError(f"capture summary {field} is invalid")
    _validate_summary_tools(summary)


def _validate_summary_tools(summary: Mapping[str, Any]) -> None:
    semantic_objects = summary["semantic_objects"]
    if not isinstance(semantic_objects, list) or any(
        not isinstance(value, str) or not value for value in semantic_objects
    ):
        raise DirectCaptureReceiptError("capture summary semantic objects are invalid")
    if semantic_objects != sorted(set(semantic_objects)):
        raise DirectCaptureReceiptError("capture summary semantic objects are invalid")
    tools = summary["tool_calls_by_name"]
    if not isinstance(tools, list) or any(
        not isinstance(item, Mapping)
        or set(item) != {"count", "name"}
        or not isinstance(item["name"], str)
        or not item["name"]
        or type(item["count"]) is not int
        or item["count"] < 1
        for item in tools
    ):
        raise DirectCaptureReceiptError("capture summary tool breakdown is invalid")
    canonical = sorted(tools, key=lambda item: item["name"])
    if tools != canonical or len({item["name"] for item in tools}) != len(tools):
        raise DirectCaptureReceiptError("capture summary tool breakdown is invalid")
    if sum(item["count"] for item in tools) != summary["tool_call_count"]:
        raise DirectCaptureReceiptError("capture summary tool total is inconsistent")


def _validate_summary_usage(summary: Mapping[str, Any]) -> None:
    usage = summary["token_usage"]
    source = summary["token_source"]
    if source not in {"provider_reported", "derived", "unavailable"}:
        raise DirectCaptureReceiptError("capture summary token source is invalid")
    if usage is not None:
        if not isinstance(usage, Mapping) or set(usage) != {
            "input_tokens",
            "output_tokens",
            "total_tokens",
        }:
            raise DirectCaptureReceiptError("capture summary token usage is invalid")
        if any(type(item) is not int or item < 0 for item in usage.values()):
            raise DirectCaptureReceiptError("capture summary token usage is invalid")
        if usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]:
            raise DirectCaptureReceiptError("capture summary token total is invalid")
    if (usage is None) != (source == "unavailable"):
        raise DirectCaptureReceiptError("capture summary token source is inconsistent")


def _validate_summary_measurements(summary: Mapping[str, Any]) -> None:
    cost = summary["cost_usd"]
    source = summary["cost_source"]
    if source not in {"provider_reported", "derived", "unavailable"}:
        raise DirectCaptureReceiptError("capture summary cost source is invalid")
    if (cost is None) != (source == "unavailable"):
        raise DirectCaptureReceiptError("capture summary cost source is inconsistent")
    for field in ("cost_usd", "latency_ms"):
        value = summary[field]
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise DirectCaptureReceiptError(f"capture summary {field} is invalid")
    for field in ("started_at", "finished_at"):
        if not isinstance(summary[field], str) or not summary[field]:
            raise DirectCaptureReceiptError(f"capture summary {field} is invalid")


def _artifact_path(store: ArtifactStore, artifact: StoredArtifact | None) -> str | None:
    if artifact is None:
        return None
    try:
        return store.relative_path(artifact).as_posix()
    except ArtifactStoreError as error:
        raise DirectCaptureReceiptError(
            "capture receipt artifact does not belong to store"
        ) from error


def _sql_sha256(sql: str | None) -> str | None:
    if sql is None:
        return None
    if not isinstance(sql, str):
        raise DirectCaptureReceiptError("capture receipt SQL is invalid")
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()

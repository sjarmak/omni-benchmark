"""Write immutable C1-C3 generation artifacts and provenance manifests."""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from .autoresearch_artifacts import TRACE_SCHEMA_VERSION
from .autoresearch_config import _canonical_bytes
from .content_policy import ContentPolicy
from .direct_action_evidence import (
    DirectActionEvidenceError,
    validate_action_evidence_payload,
)
from .direct_attempt_binding import (
    DirectAttemptSpec,
    instructions_sha256,
    model_config_id,
    validate_attempt_binding,
)
from .direct_capture_receipt import (
    DirectCaptureReceiptError,
    capture_summary_from_probe,
    validate_capture_receipt_payload,
)
from .direct_runtime_binding import DirectRuntimeBinding
from .direct_capture_contract import DirectProbeResult
from .direct_sql_result import DirectResultError, validate_json_value
from .direct_trace_validation import validate_direct_trace
from .omni_result_adapter import reject_forbidden_keys
from .run_manifest import RunManifest
from .sql_admission import single_query_sql_is_admissible

_RESULT_FIELDS = frozenset({"columns", "rows", "schema_version", "truncated"})
_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
_BENCHMARK_INFRASTRUCTURE_FAILURES = frozenset(
    {"database_identity_mismatch", "database_infrastructure_error"}
)


@dataclass(frozen=True)
class DirectAttemptArtifacts:
    """Hash-bound artifacts emitted by one direct-SQL invocation."""

    generation: StoredArtifact
    run_manifest: StoredArtifact


def write_direct_attempt(
    *,
    workspace: Path,
    store: ArtifactStore,
    spec: DirectAttemptSpec,
    probe: DirectProbeResult,
) -> DirectAttemptArtifacts:
    """Write generation.jsonl, then bind it with the exact run manifest."""
    binding = validate_attempt_binding(spec, probe)
    _validate_root_binding(workspace, store, probe)
    policy = ContentPolicy.from_environment(os.environ)
    _validate_probe_outcome(probe)
    _validate_generated_sql(probe, policy)
    _validate_trace_artifact(workspace, probe, policy)
    _validate_action_evidence_artifact(workspace, probe, policy)
    _validate_result_artifact(workspace, probe, policy)
    record = _attempt_record(workspace, spec, binding, probe)
    reject_forbidden_keys(record)
    if policy.sanitize_json(record) != record:
        raise ValueError("attempt record contains sensitive content")
    try:
        validate_json_value(record)
    except DirectResultError as error:
        raise ValueError("attempt record must contain finite JSON") from error
    _validate_attempt_measurements(probe)
    _validate_receipt(workspace, store, binding, probe, policy)
    prospective_digest = hashlib.sha256(_canonical_bytes(record)).hexdigest()
    manifest = _run_manifest(spec, binding, probe, prospective_digest)
    generation = store.write_jsonl(Path("generation.jsonl"), [record])
    run_manifest = store.write_json(Path("run.json"), manifest.as_dict())
    return DirectAttemptArtifacts(generation=generation, run_manifest=run_manifest)


def _validate_probe_outcome(probe: DirectProbeResult) -> None:
    if probe.generation_outcome not in {"answered", "refused", "errored"}:
        raise ValueError("attempt has an invalid generation outcome")
    answered = probe.generation_outcome == "answered"
    if answered and (probe.generated_sql is None or probe.result_artifact is None):
        raise ValueError("answered attempts require SQL and a typed result artifact")
    if not answered and probe.result_artifact is not None:
        raise ValueError("failed attempts cannot bind a result artifact")
    if answered != (probe.failure_class is None):
        raise ValueError("attempt outcome and terminal failure class are inconsistent")
    expected_origin = None
    if probe.failure_class is not None:
        expected_origin = (
            "benchmark_infrastructure"
            if probe.failure_class in _BENCHMARK_INFRASTRUCTURE_FAILURES
            else "evaluated_system"
        )
    if probe.failure_origin != expected_origin:
        raise ValueError("attempt failure origin is inconsistent")
    _validate_semantic_provenance(probe)
    _validate_sources(probe)


def _validate_root_binding(
    workspace: Path, store: ArtifactStore, probe: DirectProbeResult
) -> None:
    try:
        store.require_workspace(workspace)
        store.relative_path(probe.receipt)
        store.relative_path(probe.trace)
        store.relative_path(probe.action_evidence)
        if store.root_relative_path(probe.action_evidence) != Path(
            "attempt.action-evidence.json"
        ):
            raise ArtifactStoreError("action evidence path is not canonical")
        if probe.result_artifact is not None:
            store.relative_path(probe.result_artifact)
    except ArtifactStoreError as error:
        raise ValueError(
            "attempt artifacts do not share the destination root"
        ) from error


def _validate_receipt(
    workspace: Path,
    store: ArtifactStore,
    binding: DirectRuntimeBinding,
    probe: DirectProbeResult,
    policy: ContentPolicy,
) -> None:
    if store.root_relative_path(probe.receipt) != Path("capture.receipt.json"):
        raise ValueError("capture receipt path is invalid")
    content = _read_stored_artifact(workspace, probe.receipt, "capture receipt")
    try:
        actual = json.loads(content)
        validate_json_value(actual)
    except (UnicodeError, json.JSONDecodeError, DirectResultError) as error:
        raise ValueError("capture receipt is not strict JSON") from error
    if policy.sanitize_json(actual) != actual:
        raise ValueError("capture receipt does not match the exact attempt artifacts")
    try:
        validate_capture_receipt_payload(
            actual,
            binding=binding,
            store=store,
            sql=probe.generated_sql,
            trace=probe.trace,
            action_evidence=probe.action_evidence,
            result=probe.result_artifact,
            capture_summary=capture_summary_from_probe(probe),
        )
    except DirectCaptureReceiptError as error:
        raise ValueError(
            "capture receipt does not match the exact attempt artifacts"
        ) from error


def _validate_generated_sql(probe: DirectProbeResult, policy: ContentPolicy) -> None:
    sql = probe.generated_sql
    if sql is not None and (
        not policy.query_is_safe(sql) or not single_query_sql_is_admissible(sql)
    ):
        raise ValueError("captured SQL does not pass publisher SQL admission")


def _validate_semantic_provenance(probe: DirectProbeResult) -> None:
    values = probe.semantic_objects
    if tuple(sorted(set(values))) != values or any(
        not isinstance(value, str) or not value for value in values
    ):
        raise ValueError("captured semantic object provenance is invalid")
    if probe.condition != "C3" and values:
        raise ValueError(f"{probe.condition} cannot publish semantic objects")
    tools = dict(probe.tool_calls_by_name)
    if values and tools.get("search_semantic_model", 0) < 1:
        raise ValueError("semantic objects lack semantic-model tool provenance")


def _validate_sources(probe: DirectProbeResult) -> None:
    for source, value, field in (
        (probe.token_source, probe.token_usage, "token"),
        (probe.cost_source, probe.cost_usd, "cost"),
    ):
        if source not in {"provider_reported", "derived", "unavailable"}:
            raise ValueError(f"attempt {field} source is invalid")
        if (value is None) != (source == "unavailable"):
            raise ValueError(f"attempt {field} source and value disagree")


def _validate_attempt_measurements(probe: DirectProbeResult) -> None:
    values = (
        (probe.latency_ms,)
        if probe.cost_usd is None
        else (
            probe.latency_ms,
            probe.cost_usd,
        )
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        raise ValueError("attempt latency and available cost must be non-negative")


def _validate_trace_artifact(
    workspace: Path, probe: DirectProbeResult, policy: ContentPolicy
) -> None:
    content = _read_stored_artifact(workspace, probe.trace, "trace")
    validate_direct_trace(content, probe, policy)


def _validate_action_evidence_artifact(
    workspace: Path, probe: DirectProbeResult, policy: ContentPolicy
) -> None:
    trace_content = _read_stored_artifact(workspace, probe.trace, "trace")
    content = _read_stored_artifact(workspace, probe.action_evidence, "action evidence")
    try:
        value = json.loads(content)
        trace_events = [json.loads(line) for line in trace_content.splitlines()]
        validate_json_value(value)
    except (UnicodeError, json.JSONDecodeError, DirectResultError) as error:
        raise ValueError("action evidence is not strict JSON") from error
    try:
        validate_action_evidence_payload(
            value,
            binding=probe.binding,
            trace_sha256=probe.trace.sha256,
            trace_events=trace_events,
            policy=policy,
        )
    except DirectActionEvidenceError as error:
        raise ValueError("action evidence does not match the exact trace") from error


def _validate_result_artifact(
    workspace: Path, probe: DirectProbeResult, policy: ContentPolicy
) -> None:
    if probe.result_artifact is None:
        return
    content = _read_stored_artifact(workspace, probe.result_artifact, "result artifact")
    try:
        value = json.loads(content)
        validate_json_value(value)
    except (UnicodeError, json.JSONDecodeError, DirectResultError) as error:
        raise ValueError("result artifact is not valid JSON") from error
    reject_forbidden_keys(value)
    if policy.sanitize_json(value) != value:
        raise ValueError("result artifact contains sensitive content")
    _validate_typed_result(value, policy)


def _validate_typed_result(value: Any, policy: ContentPolicy) -> None:
    if not isinstance(value, dict) or set(value) != _RESULT_FIELDS:
        raise ValueError("result artifact does not use the exact typed schema")
    columns, rows = value["columns"], value["rows"]
    if not isinstance(columns, list) or any(
        not isinstance(column, str) or not column for column in columns
    ):
        raise ValueError("result artifact columns are invalid")
    if len(set(columns)) != len(columns):
        raise ValueError("result artifact columns must be unique")
    for column in columns:
        reject_forbidden_keys({column: None})
    if any(policy.field_name_is_sensitive(column) for column in columns):
        raise ValueError("result artifact columns contain sensitive names")
    if not isinstance(rows, list) or any(
        not isinstance(row, list) or len(row) != len(columns) for row in rows
    ):
        raise ValueError("result artifact rows do not match columns")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("result artifact metadata is invalid")
    if value["truncated"] is not False:
        raise ValueError("result artifact metadata is invalid")


def _read_stored_artifact(
    workspace: Path, artifact: StoredArtifact, description: str
) -> bytes:
    path = artifact.path
    try:
        resolved_workspace = workspace.resolve(strict=True)
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_workspace)
        metadata = path.lstat()
        content = path.read_bytes()
    except (OSError, ValueError) as error:
        raise ValueError(f"{description} is outside the private workspace") from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
    ):
        raise ValueError(f"{description} is not a private regular file")
    digest = hashlib.sha256(content).hexdigest()
    if (
        not content
        or len(content) > _MAX_ARTIFACT_BYTES
        or len(content) != artifact.size_bytes
        or digest != artifact.sha256
    ):
        raise ValueError(f"{description} metadata does not match stored bytes")
    return content


def _attempt_record(
    workspace: Path,
    spec: DirectAttemptSpec,
    binding: DirectRuntimeBinding,
    probe: DirectProbeResult,
) -> dict[str, object]:
    record = {
        **_identity_fields(binding, probe),
        **_telemetry_fields(probe),
        **_trace_fields(workspace, probe),
    }
    if probe.generated_sql is not None:
        record |= {
            "generated_query": None,
            "generated_sql": probe.generated_sql,
            "query_unavailable_reason": None,
        }
    if probe.result_artifact is not None:
        record |= _result_fields(workspace, probe.result_artifact)
    return record


def _identity_fields(
    binding: DirectRuntimeBinding, probe: DirectProbeResult
) -> dict[str, object]:
    failure = probe.failure_class
    return {
        "attempt_id": binding.attempt_id,
        "condition": binding.condition,
        "failure_origin": probe.failure_origin,
        "finished_at": probe.finished_at,
        "generation_outcome": probe.generation_outcome,
        "harness_failure": (
            failure if probe.failure_origin == "benchmark_infrastructure" else None
        ),
        "instance_id": binding.question.instance_id,
        "latency_ms": probe.latency_ms,
        "model": {
            "name": binding.model.model,
            "provider": binding.model.provider,
            "version": binding.model.model,
        },
        "partition": binding.question.scope,
        "question": binding.question.question,
        "repetition": binding.repetition,
        "run_id": binding.run_id,
        "runtime_binding_sha256": binding.sha256(),
        "semantic_objects": list(probe.semantic_objects),
        "started_at": probe.started_at,
        "terminal_failure_class": failure,
    }


def _telemetry_fields(probe: DirectProbeResult) -> dict[str, object]:
    unavailable = [] if probe.retry_count is not None else ["retry_count"]
    if probe.database_query_count is None:
        unavailable.append("database_query_count")
    return {
        "cost_source": probe.cost_source,
        "cost_usd": probe.cost_usd,
        "database_query_count": probe.database_query_count,
        "model_turn_provenance": [
            record.as_dict() for record in probe.model_turn_provenance
        ],
        "retry_count": probe.retry_count,
        "telemetry_unavailable": sorted(unavailable),
        "token_source": probe.token_source,
        "token_usage": probe.token_usage,
        "tool_call_count": probe.tool_call_count,
        "tool_calls_by_name": [
            {"count": count, "name": name} for name, count in probe.tool_calls_by_name
        ],
        "validation_attempt_count": probe.validation_attempt_count,
    }


def _trace_fields(workspace: Path, probe: DirectProbeResult) -> dict[str, object]:
    return {
        "trace_captured": True,
        "trace_degraded_reason": None,
        "trace_path": probe.trace.path.relative_to(workspace).as_posix(),
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "trace_sha256": probe.trace.sha256,
        "trace_truncated": False,
    }


def _result_fields(workspace: Path, result: StoredArtifact) -> dict[str, object]:
    return {
        "actual_result_hash": result.sha256,
        "actual_result_status": "complete",
        "execution_status": "complete",
        "result_artifact_path": result.path.relative_to(workspace).as_posix(),
        "result_artifact_schema_version": 1,
        "result_artifact_sha256": result.sha256,
    }


def _run_manifest(
    spec: DirectAttemptSpec,
    binding: DirectRuntimeBinding,
    probe: DirectProbeResult,
    generation_sha256: str,
) -> RunManifest:
    return RunManifest.from_dict(
        {
            "budget_id": binding.budget.budget_id,
            "cli_versions": dict(spec.cli_versions),
            "condition": binding.condition,
            "controllable_seed": spec.controllable_seed,
            "finished_at": probe.finished_at,
            "generation_sha256": generation_sha256,
            "git_commit": binding.system_commit,
            "harness_config_sha256": binding.model.transport_config_sha256,
            "instructions_sha256": instructions_sha256(binding),
            "model": binding.model.model,
            "model_config_id": model_config_id(binding),
            "prompt_sha256": binding.model.system_prompt_sha256,
            "provider": binding.model.provider,
            "repetition": binding.repetition,
            "schema_version": 2,
            "scope": binding.question.scope,
            "semantic_model_ref": spec.semantic_model_ref,
            "semantic_model_sha256": spec.semantic_model_sha256,
            "software_versions": dict(spec.software_versions),
            "started_at": probe.started_at,
        }
    )

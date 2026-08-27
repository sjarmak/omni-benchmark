"""Produce one complete, unscored C4 attempt and its provenance manifest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .artifact_store import ArtifactStore, StoredArtifact
from .omni_capture import OmniProbeResult
from .omni_result_adapter import reject_forbidden_keys
from .run_manifest import RunManifest


@dataclass(frozen=True)
class C4AttemptArtifacts:
    """Hash-bound artifacts emitted by one governed Omni invocation."""

    generation: StoredArtifact
    run_manifest: StoredArtifact


@dataclass(frozen=True)
class C4AttemptSpec:
    """Immutable run identity and provenance for one C4 attempt."""

    instance_id: str
    question: str
    run_id: str
    repetition: int
    provider: str
    model: str
    model_version: str | None
    git_commit: str
    harness_config_sha256: str
    prompt_sha256: str
    instructions_sha256: str
    semantic_model_ref: str
    semantic_model_sha256: str | None
    model_config_id: str
    budget_id: str
    software_versions: Mapping[str, str]
    cli_versions: Mapping[str, str]


def write_c4_attempt(
    *,
    workspace: Path,
    store: ArtifactStore,
    spec: C4AttemptSpec,
    probe: OmniProbeResult,
) -> C4AttemptArtifacts:
    """Write an immutable generation envelope before binding it with run.json."""
    record = _attempt_record(workspace=workspace, spec=spec, probe=probe)
    reject_forbidden_keys(record)
    generation = store.write_jsonl(Path("generation.jsonl"), [record])
    manifest = _run_manifest(spec, probe, generation.sha256)
    run_manifest = store.write_json(Path("run.json"), manifest.as_dict())
    return C4AttemptArtifacts(generation=generation, run_manifest=run_manifest)


def _attempt_record(
    *,
    workspace: Path,
    spec: C4AttemptSpec,
    probe: OmniProbeResult,
) -> dict[str, object]:
    answered = probe.result_artifact is not None and probe.generated_query is not None
    failure_class = None if answered else probe.failure_class
    return {
        **_identity_fields(spec, probe, answered, failure_class),
        **_telemetry_fields(spec, probe),
        **_trace_fields(workspace, probe),
        **_query_fields(probe),
        **(_answered_result(workspace, probe) if answered else {}),
    }


def _identity_fields(
    spec: C4AttemptSpec,
    probe: OmniProbeResult,
    answered: bool,
    failure_class: str | None,
) -> dict[str, object]:
    return {
        "attempt_id": f"{spec.run_id}:{spec.instance_id}:C4:{spec.repetition}",
        "condition": "C4",
        "failure_origin": None if answered else "evaluated_system",
        "finished_at": probe.finished_at,
        "generation_outcome": "answered" if answered else _failure_outcome(probe),
        "harness_failure": None if answered else failure_class,
        "instance_id": spec.instance_id,
        "latency_ms": probe.latency_ms,
        "model": {
            "name": spec.model,
            "provider": spec.provider,
            "version": spec.model_version,
        },
        "partition": "dev-a",
        "question": spec.question,
        "repetition": spec.repetition,
        "run_id": spec.run_id,
        "semantic_objects": list(probe.semantic_objects),
        "started_at": probe.started_at,
        "terminal_failure_class": failure_class,
    }


def _telemetry_fields(spec: C4AttemptSpec, probe: OmniProbeResult) -> dict[str, object]:
    unavailable = (
        ("retry_count", "tool_call_count", "validation_attempt_count")
        + (("model_version",) if spec.model_version is None else ())
        + (("database_query_count",) if probe.database_query_count is None else ())
    )
    return {
        "cost_source": "unavailable",
        "cost_usd": None,
        "database_query_count": probe.database_query_count,
        "retry_count": None,
        "telemetry_unavailable": sorted(unavailable),
        "token_source": "unavailable",
        "token_usage": None,
        "tool_call_count": probe.tool_call_count,
        "tool_calls_by_name": [
            {"count": count, "name": name} for name, count in probe.tool_calls_by_name
        ],
        "validation_attempt_count": probe.validation_attempt_count,
    }


def _trace_fields(workspace: Path, probe: OmniProbeResult) -> dict[str, object]:
    return {
        "trace_captured": True,
        "trace_degraded_reason": None,
        "trace_path": probe.trace.path.relative_to(workspace).as_posix(),
        "trace_schema_version": "trace-event-v2",
        "trace_sha256": probe.trace.sha256,
        "trace_truncated": False,
    }


def _query_fields(probe: OmniProbeResult) -> dict[str, object]:
    if probe.generated_query is None:
        return {}
    return {
        "generated_query": probe.generated_query,
        "generated_sql": None,
        "query_unavailable_reason": None,
    }


def _answered_result(workspace: Path, probe: OmniProbeResult) -> dict[str, object]:
    result_artifact = probe.result_artifact
    if result_artifact is None:
        raise ValueError("answered C4 attempt must bind a result artifact")
    return {
        "actual_result_hash": result_artifact.sha256,
        "actual_result_status": "complete",
        "execution_status": "complete",
        "result_artifact_path": result_artifact.path.relative_to(workspace).as_posix(),
        "result_artifact_schema_version": 1,
        "result_artifact_sha256": result_artifact.sha256,
    }


def _run_manifest(
    spec: C4AttemptSpec, probe: OmniProbeResult, generation_sha256: str
) -> RunManifest:
    return RunManifest.from_dict(
        {
            "budget_id": spec.budget_id,
            "cli_versions": dict(spec.cli_versions),
            "condition": "C4",
            "controllable_seed": None,
            "finished_at": probe.finished_at,
            "generation_sha256": generation_sha256,
            "git_commit": spec.git_commit,
            "harness_config_sha256": spec.harness_config_sha256,
            "instructions_sha256": spec.instructions_sha256,
            "model": spec.model,
            "model_config_id": spec.model_config_id,
            "prompt_sha256": spec.prompt_sha256,
            "provider": spec.provider,
            "repetition": spec.repetition,
            "schema_version": 2,
            "scope": "dev-a",
            "semantic_model_ref": spec.semantic_model_ref,
            "semantic_model_sha256": spec.semantic_model_sha256,
            "software_versions": dict(spec.software_versions),
            "started_at": probe.started_at,
        }
    )


def _failure_outcome(probe: OmniProbeResult) -> str:
    if probe.terminal_state == "DENIED":
        return "refused"
    return "errored"

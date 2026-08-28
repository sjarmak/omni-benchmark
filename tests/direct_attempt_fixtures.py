"""Public synthetic fixtures for runtime-bound direct attempt publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.direct_runtime_binding import DirectRuntimeBinding
from omni_benchmark.direct_sql_attempt import DirectAttemptSpec
from omni_benchmark.direct_sql_capture import DirectProbeResult
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    SyntheticDatabase,
    budget_identity,
    capture_with_test_time,
    prepared_attempt,
    runtime_binding,
    store,
)

SHA_E = "e" * 64


def attempt_spec(
    binding: DirectRuntimeBinding,
    *,
    semantic_model_ref: str | None = None,
    semantic_model_sha256: str | None = None,
) -> DirectAttemptSpec:
    default_ref = {
        "C1": "raw-schema:fixture-v1",
        "C2": "public-hkb:fixture-v1",
        "C3": "omni-semantic:fixture-v1",
    }[binding.condition]
    default_sha = None if binding.condition == "C1" else SHA_E
    return DirectAttemptSpec(
        binding=binding,
        controllable_seed=None,
        semantic_model_ref=semantic_model_ref or default_ref,
        semantic_model_sha256=(
            default_sha
            if semantic_model_sha256 is None and binding.condition != "C1"
            else semantic_model_sha256
        ),
        software_versions={"omni-benchmark": "0.1.0"},
        cli_versions={"direct-harness": "0.1.0"},
    )


def capture_probe(
    tmp_path: Path,
    *,
    actions: list[dict[str, Any]] | None = None,
    condition: str = "C1",
    instance_id: str = "public",
    maximum_turns: int = 12,
    responses: dict[str, object] | None = None,
    run_id: str = "run",
    system_commit: str = "1" * 40,
) -> tuple[Path, ArtifactStore, DirectRuntimeBinding, DirectProbeResult]:
    binding = runtime_binding(
        condition,
        instance_id=instance_id,
        budget=budget_identity(maximum_turns=maximum_turns),
        run_id=run_id,
        system_commit=system_commit,
    )
    workspace, artifact_store = store(tmp_path, "direct-attempt")
    model = SequenceModel(
        binding,
        actions or [{"type": "refuse", "reason": "insufficient_information"}],
    )
    database = SyntheticDatabase(binding, responses or {})
    prepared = prepared_attempt(
        binding,
        model=model,
        database=database,
        public_tools=BoundPublicTools(binding),
        artifact_store=artifact_store,
    )
    probe = capture_with_test_time(prepared, clock_steps=40)
    return workspace, artifact_store, binding, probe

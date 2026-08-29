"""Sealed-only C4 adapter over the existing Omni capture result contract."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path

from .artifact_store import ALLOWED_RAW_ROOTS, ArtifactStore, ArtifactStoreError
from .freeze_b import FreezeBCondition
from .omni_attempt import C4AttemptSpec, _attempt_record
from .omni_capture import OmniProbeResult
from .sealed_dispatch import (
    SealedAdapterResult,
    SealedDispatchPolicy,
)
from .sealed_generation_staging import (
    SealedGenerationStagingError,
    SealedPreparedAttempt,
    _validated_prepared,
)

OmniProbeRunner = Callable[[SealedPreparedAttempt, ArtifactStore], OmniProbeResult]


class SealedOmniAdapterError(RuntimeError):
    """Raised when C4 cannot produce one exact sealed generation record."""


class SealedOmniConditionAdapter:
    """Project a private Omni capture into an unscored sealed C4 record."""

    def __init__(
        self,
        *,
        workspace: Path,
        capture_root: Path,
        condition_binding: FreezeBCondition,
        policy: SealedDispatchPolicy,
        probe_runner: OmniProbeRunner,
    ) -> None:
        root = _workspace_root(workspace)
        relative = _capture_root(capture_root)
        if (
            type(condition_binding) is not FreezeBCondition
            or condition_binding.condition != "C4"
        ):
            raise SealedOmniAdapterError("sealed Omni adapter identity is invalid")
        if type(policy) is not SealedDispatchPolicy or (
            SealedDispatchPolicy.from_dict(policy.as_dict()) != policy
        ):
            raise SealedOmniAdapterError("sealed Omni adapter policy is invalid")
        if not callable(probe_runner):
            raise SealedOmniAdapterError("sealed Omni probe runner is invalid")
        self._workspace = root
        self._capture_root = relative
        self._condition_binding = condition_binding
        self._policy = policy
        self._probe_runner = probe_runner

    @property
    def condition_binding(self) -> FreezeBCondition:
        """Expose the immutable C4 identity checked by the dispatcher."""
        return self._condition_binding

    def execute(self, prepared: SealedPreparedAttempt) -> SealedAdapterResult:
        """Run one post-receipt C4 capture and preserve only an unscored record."""
        try:
            value = _validated_prepared(prepared)
        except SealedGenerationStagingError as error:
            raise SealedOmniAdapterError(
                "sealed Omni attempt authority is invalid"
            ) from error
        if value.condition != "C4" or value.condition_binding != self.condition_binding:
            raise SealedOmniAdapterError(
                "sealed Omni adapter requires exact C4 identity"
            )
        store = self._new_capture_store(value)
        try:
            probe = self._probe_runner(value, store)
        except Exception as error:
            raise SealedOmniAdapterError("sealed Omni capture failed") from error
        if type(probe) is not OmniProbeResult:
            raise SealedOmniAdapterError("sealed Omni capture result is invalid")
        spec = C4AttemptSpec(
            instance_id=value.instance_id,
            question=value.question,
            run_id=value.cohort_id,
            repetition=value.repetition,
            provider=self.condition_binding.provider,
            model=self.condition_binding.model,
            model_version=None,
            git_commit=value.system_commit,
            harness_config_sha256=self.condition_binding.harness_config_sha256,
            prompt_sha256=self.condition_binding.prompt_sha256,
            instructions_sha256=self.condition_binding.instructions_sha256,
            semantic_model_ref=self.condition_binding.semantic_model_ref,
            semantic_model_sha256=self.condition_binding.semantic_model_sha256,
            model_config_id=self.condition_binding.model_config_id,
            budget_id=self.condition_binding.budget_id,
            software_versions=dict(self._policy.software_versions),
            cli_versions=self._policy.cli_versions("C4"),
            cost_reservation_usd=float(self._policy.reservation("C4")),
            budget_policy_sha256=self._policy.sha256,
            cost_unavailable_reason="omni_job_api_does_not_expose_cost",
        )
        try:
            record = _attempt_record(
                workspace=self._workspace,
                spec=spec,
                probe=probe,
            )
        except (TypeError, ValueError) as error:
            raise SealedOmniAdapterError(
                "sealed Omni capture result is invalid"
            ) from error
        record |= {
            "attempt_id": value.attempt_id,
            "condition": "C4",
            "instance_id": value.instance_id,
            "partition": "test",
            "question": value.question,
            "repetition": value.repetition,
            "run_id": value.cohort_id,
        }
        if record.get("failure_origin") == "benchmark_infrastructure":
            raise SealedOmniAdapterError(
                "sealed Omni benchmark infrastructure failure remains unstaged"
            )
        return SealedAdapterResult(generation_record=record)

    def _new_capture_store(self, prepared: SealedPreparedAttempt) -> ArtifactStore:
        relative = self._capture_root / (
            f"{prepared.database}/c4/{prepared.instance_id}-r{prepared.repetition}/"
            f"capture-{secrets.token_hex(12)}"
        )
        try:
            return ArtifactStore(
                self._workspace,
                relative,
                require_new_root=True,
            )
        except ArtifactStoreError as error:
            raise SealedOmniAdapterError(
                "sealed Omni capture root could not be created"
            ) from error


def _workspace_root(workspace: Path) -> Path:
    absolute = workspace.absolute()
    try:
        resolved = workspace.resolve(strict=True)
    except OSError as error:
        raise SealedOmniAdapterError("sealed Omni workspace is unavailable") from error
    if absolute != resolved or workspace.is_symlink() or not resolved.is_dir():
        raise SealedOmniAdapterError("sealed Omni workspace is unsafe")
    return resolved


def _capture_root(value: Path) -> Path:
    root = Path(value)
    if (
        root.is_absolute()
        or not root.parts
        or ".." in root.parts
        or not any(root.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS)
    ):
        raise SealedOmniAdapterError("sealed Omni capture root is invalid")
    return root

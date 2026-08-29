"""Post-approval construction of the exact C4 production probe runner."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from .artifact_store import ArtifactStore
from .freeze_b import FreezeBCondition
from .omni_capture import OmniJobCapture, OmniProbeResult
from .omni_cli import OmniCliClient, OmniCliError, OmniCliSettings
from .omni_probe_cli import _verify_authentication
from .omni_probe_preflight import (
    C4ProbeSpecs,
    OmniProbePreflightError,
    load_c4_probe_specs,
    observe_omni_cli_version,
    pin_omni_cli_binary,
    render_public_question,
    semantic_model_ref,
)
from .sealed_dispatch import AdapterFactory, SealedDispatchPolicy
from .sealed_generation_staging import SealedPreparedAttempt
from .sealed_omni_adapter import SealedOmniConditionAdapter
from .sealed_runtime_inputs import SealedRuntimeInputs

_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")
_C4_CONDITION_PATH = Path("config/conditions/c4-production-v1.json")
_C4_PROMPT_PATH = Path("config/prompts/c4-user-prompt-v1.txt")
_C4_INSTRUCTIONS_PATH = Path("config/instructions/c4-managed-instructions-v1.json")


class SealedOmniFactoryError(RuntimeError):
    """Raised before an inexact C4 production dependency can execute."""


@dataclass(frozen=True)
class SealedOmniDeploymentTarget:
    """One exact verified production deployment selected by public database."""

    database: str
    branch_id: str
    model_id: str
    semantic_model_sha256: str

    @classmethod
    def create(
        cls,
        *,
        database: str,
        branch_id: str,
        model_id: str,
        semantic_model_sha256: str,
    ) -> SealedOmniDeploymentTarget:
        values = (database, branch_id, model_id)
        if any(
            not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None
            for value in values
        ) or (
            not isinstance(semantic_model_sha256, str)
            or _SHA256.fullmatch(semantic_model_sha256) is None
        ):
            raise SealedOmniFactoryError("Omni deployment target is invalid")
        return cls(database, branch_id, model_id, semantic_model_sha256)


@dataclass(frozen=True)
class SealedOmniDeploymentGate:
    """Verified all-database deployment evidence bound by Freeze B."""

    semantic_model_ref: str
    semantic_model_sha256: str
    targets: Mapping[str, SealedOmniDeploymentTarget]

    @classmethod
    def create(
        cls,
        *,
        semantic_model_ref: str,
        semantic_model_sha256: str | None,
        targets: Mapping[str, SealedOmniDeploymentTarget],
    ) -> SealedOmniDeploymentGate:
        if (
            not isinstance(semantic_model_ref, str)
            or not semantic_model_ref
            or semantic_model_sha256 is None
            or _SHA256.fullmatch(semantic_model_sha256) is None
            or not isinstance(targets, Mapping)
            or not targets
        ):
            raise SealedOmniFactoryError("Omni deployment gate is invalid")
        canonical: dict[str, SealedOmniDeploymentTarget] = {}
        for database, target in targets.items():
            if (
                not isinstance(target, SealedOmniDeploymentTarget)
                or target.database != database
                or database in canonical
            ):
                raise SealedOmniFactoryError("Omni deployment gate target is invalid")
            canonical[database] = SealedOmniDeploymentTarget.create(
                database=target.database,
                branch_id=target.branch_id,
                model_id=target.model_id,
                semantic_model_sha256=target.semantic_model_sha256,
            )
        return cls(
            semantic_model_ref=semantic_model_ref,
            semantic_model_sha256=semantic_model_sha256,
            targets=MappingProxyType(dict(sorted(canonical.items()))),
        )

    def target(self, database: str) -> SealedOmniDeploymentTarget:
        try:
            return self.targets[database]
        except KeyError as error:
            raise SealedOmniFactoryError(
                "sealed database is absent from the Omni deployment gate"
            ) from error


@dataclass(frozen=True)
class SealedOmniProductionConfig:
    """Public frozen inputs needed to construct C4 after approval."""

    workspace: Path
    system_commit: str
    runtime_inputs: SealedRuntimeInputs
    capture_root: Path
    deployment_gate: SealedOmniDeploymentGate
    scheduled_databases: frozenset[str]

    @classmethod
    def create(
        cls,
        *,
        workspace: Path,
        system_commit: str,
        runtime_inputs: SealedRuntimeInputs,
        capture_root: Path,
        deployment_gate: SealedOmniDeploymentGate,
        scheduled_databases: set[str] | frozenset[str],
    ) -> SealedOmniProductionConfig:
        try:
            root = workspace.resolve(strict=True)
        except OSError as error:
            raise SealedOmniFactoryError(
                "Omni production workspace is unavailable"
            ) from error
        if root != workspace.absolute() or workspace.is_symlink() or not root.is_dir():
            raise SealedOmniFactoryError("Omni production workspace is unsafe")
        if (
            type(runtime_inputs) is not SealedRuntimeInputs
            or runtime_inputs.system_commit != system_commit
            or type(deployment_gate) is not SealedOmniDeploymentGate
        ):
            raise SealedOmniFactoryError("Omni production frozen inputs are invalid")
        databases = frozenset(scheduled_databases)
        if not databases or databases != frozenset(deployment_gate.targets):
            raise SealedOmniFactoryError(
                "Omni deployment gate coverage does not match the sealed plan"
            )
        return cls(
            workspace=root,
            system_commit=system_commit,
            runtime_inputs=runtime_inputs,
            capture_root=Path(capture_root),
            deployment_gate=deployment_gate,
            scheduled_databases=databases,
        )


def build_sealed_omni_adapter_factory(
    config: SealedOmniProductionConfig,
    *,
    policy: SealedDispatchPolicy,
) -> AdapterFactory:
    """Load public specs now; return an adapter whose provider runner is deferred."""
    selected = _validated_config(config)
    condition_input = selected.runtime_inputs.condition("C4")
    _require_c4_paths(condition_input)
    try:
        specs = load_c4_probe_specs(
            selected.workspace,
            selected.system_commit,
            condition_path=condition_input.harness_config_path,
            prompt_path=condition_input.prompt_path,
            instructions_path=condition_input.instructions_path,
        )
    except OmniProbePreflightError as error:
        raise SealedOmniFactoryError(
            "frozen C4 specifications are unavailable"
        ) from error
    _require_c4_identity(
        specs,
        condition_input.freeze_b_condition,
        selected.deployment_gate,
        policy,
    )

    def adapter_factory(frozen_condition: FreezeBCondition):
        if frozen_condition != condition_input.freeze_b_condition:
            raise SealedOmniFactoryError(
                "Omni adapter condition does not match frozen inputs"
            )
        return SealedOmniConditionAdapter(
            workspace=selected.workspace,
            capture_root=selected.capture_root,
            condition_binding=frozen_condition,
            policy=policy,
            probe_runner=lambda prepared, store: _run_probe(
                selected,
                specs,
                policy,
                prepared,
                store,
            ),
        )

    return adapter_factory


def _run_probe(
    config: SealedOmniProductionConfig,
    specs: C4ProbeSpecs,
    policy: SealedDispatchPolicy,
    prepared: SealedPreparedAttempt,
    store: ArtifactStore,
) -> OmniProbeResult:
    if prepared.condition != "C4" or prepared.condition_binding != specs_condition(
        specs, config
    ):
        raise SealedOmniFactoryError("prepared C4 attempt identity is invalid")
    target = config.deployment_gate.target(prepared.database)
    environment = {
        **os.environ,
        "OMNI_BRANCH_ID": target.branch_id,
        "OMNI_BUDGET_POLICY_SHA256": policy.sha256,
        "OMNI_COST_RESERVATION_USD": str(policy.reservation("C4")),
        "OMNI_MODEL_ID": target.model_id,
        "OMNI_SEMANTIC_DATABASE": target.database,
        "OMNI_SEMANTIC_MODEL_SHA256": target.semantic_model_sha256,
    }
    settings = _load_settings(environment)
    if (
        settings.branch_id != target.branch_id
        or settings.model_id != target.model_id
        or semantic_model_ref(settings) != f"branch:{target.branch_id}"
    ):
        raise SealedOmniFactoryError("Omni settings do not match deployment target")
    try:
        pinned, binary_sha256 = pin_omni_cli_binary(
            settings,
            environment,
            specs.condition.omni_cli_sha256,
        )
        version = observe_omni_cli_version(pinned, environment)
    except OmniProbePreflightError as error:
        raise SealedOmniFactoryError("Omni CLI identity is unavailable") from error
    expected_cli = policy.cli_versions("C4")
    if expected_cli != {"omni": version, "omni.sha256": binary_sha256}:
        raise SealedOmniFactoryError("observed Omni CLI does not match dispatch policy")
    question = render_public_question(specs.prompt, prepared.question)
    try:
        client = OmniCliClient(pinned, environment=environment)
        _verify_authentication(client)
        return OmniJobCapture(
            client,
            store,
            maximum_status_checks=specs.condition.maximum_status_checks,
            poll_schedule_seconds=specs.condition.poll_schedule_seconds,
        ).probe(question)
    except Exception as error:
        raise SealedOmniFactoryError("Omni production capture failed") from error


def specs_condition(
    specs: C4ProbeSpecs, config: SealedOmniProductionConfig
) -> FreezeBCondition:
    condition = config.runtime_inputs.condition("C4").freeze_b_condition
    _require_c4_identity(specs, condition, config.deployment_gate, None)
    return condition


def _validated_config(value: object) -> SealedOmniProductionConfig:
    if type(value) is not SealedOmniProductionConfig:
        raise SealedOmniFactoryError("Omni production configuration is invalid")
    parsed = SealedOmniProductionConfig.create(
        workspace=value.workspace,
        system_commit=value.system_commit,
        runtime_inputs=value.runtime_inputs,
        capture_root=value.capture_root,
        deployment_gate=value.deployment_gate,
        scheduled_databases=value.scheduled_databases,
    )
    if parsed != value:
        raise SealedOmniFactoryError("Omni production configuration is not canonical")
    return parsed


def _require_c4_paths(value) -> None:  # type: ignore[no-untyped-def]
    if (
        value.condition != "C4"
        or value.harness_config_path != _C4_CONDITION_PATH
        or value.prompt_path != _C4_PROMPT_PATH
        or value.instructions_path != _C4_INSTRUCTIONS_PATH
        or value.semantic_model_path is None
    ):
        raise SealedOmniFactoryError("C4 frozen input path is unsupported")


def _require_c4_identity(
    specs: C4ProbeSpecs,
    frozen: FreezeBCondition,
    deployment: SealedOmniDeploymentGate,
    policy: SealedDispatchPolicy | None,
) -> None:
    if type(specs) is not C4ProbeSpecs:
        raise SealedOmniFactoryError("C4 specifications are invalid")
    expected = {
        "harness_config_sha256": specs.condition_sha256,
        "instructions_sha256": specs.instructions_sha256,
        "model": specs.condition.managed_llm_identity,
        "model_config_id": specs.condition.model_config_id,
        "prompt_sha256": specs.prompt_sha256,
        "provider": specs.condition.provider,
        "semantic_model_ref": deployment.semantic_model_ref,
        "semantic_model_sha256": deployment.semantic_model_sha256,
    }
    if any(getattr(frozen, key) != item for key, item in expected.items()):
        raise SealedOmniFactoryError("C4 specifications do not match Freeze B")
    if policy is not None:
        if type(policy) is not SealedDispatchPolicy or policy.cli_versions("C4") != {
            "omni": specs.condition.omni_cli_version,
            "omni.sha256": specs.condition.omni_cli_sha256,
        }:
            raise SealedOmniFactoryError(
                "C4 CLI identity does not match dispatch policy"
            )


def _load_settings(environment: Mapping[str, str]) -> OmniCliSettings:
    try:
        return OmniCliSettings.from_environment(environment)
    except OmniCliError as error:
        raise SealedOmniFactoryError("Omni settings are unavailable") from error

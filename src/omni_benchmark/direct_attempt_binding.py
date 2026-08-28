"""Canonical runtime-binding validation for direct attempt publication."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .direct_capture_contract import DirectProbeResult
from .direct_runtime_binding import DirectRuntimeBinding, DirectRuntimeIdentityError


@dataclass(frozen=True)
class DirectAttemptSpec:
    """Non-duplicated publication metadata attached to one runtime binding."""

    binding: DirectRuntimeBinding
    controllable_seed: int | None
    semantic_model_ref: str
    semantic_model_sha256: str | None
    software_versions: Mapping[str, str]
    cli_versions: Mapping[str, str]

    def __post_init__(self) -> None:
        _canonical_binding(self.binding, "attempt spec")
        object.__setattr__(
            self,
            "software_versions",
            _immutable_mapping(self.software_versions, "software_versions"),
        )
        object.__setattr__(
            self,
            "cli_versions",
            _immutable_mapping(self.cli_versions, "cli_versions"),
        )


def validate_attempt_binding(
    spec: DirectAttemptSpec, probe: DirectProbeResult
) -> DirectRuntimeBinding:
    """Exact-compare every duplicated probe label against one canonical binding."""
    if not isinstance(spec, DirectAttemptSpec):
        raise ValueError("direct attempt spec is invalid")
    if not isinstance(probe, DirectProbeResult):
        raise ValueError("direct probe is invalid")
    binding = _canonical_binding(spec.binding, "attempt spec")
    captured = _canonical_binding(probe.binding, "captured probe")
    if captured != binding or captured.sha256() != binding.sha256():
        raise ValueError("captured probe runtime binding does not match attempt spec")
    expected = {
        "attempt_id": binding.attempt_id,
        "condition": binding.condition,
        "maximum_turns": binding.budget.maximum_turns,
        "model": binding.model.model,
        "provider": binding.model.provider,
        "question_sha256": binding.question.question_sha256,
    }
    for field, value in expected.items():
        if getattr(probe, field) != value:
            raise ValueError(f"captured probe {field} does not match runtime binding")
    _validate_semantic_digest(spec, binding)
    return binding


def instructions_sha256(binding: DirectRuntimeBinding) -> str:
    """Derive the committed instruction digest from the bound public context."""
    components = dict(binding.context.component_sha256)
    try:
        return components["instructions"]
    except KeyError as error:
        raise ValueError(
            "runtime binding context lacks the instructions component"
        ) from error


def model_config_id(binding: DirectRuntimeBinding) -> str:
    """Derive a stable public model-adapter configuration identifier."""
    return f"{binding.model.adapter}:{binding.model.adapter_version}"


def _canonical_binding(value: object, description: str) -> DirectRuntimeBinding:
    if not isinstance(value, DirectRuntimeBinding):
        raise ValueError(f"{description} runtime binding is invalid")
    try:
        reparsed = DirectRuntimeBinding.from_dict(value.as_dict(), environment={})
    except DirectRuntimeIdentityError as error:
        raise ValueError(f"{description} runtime binding is invalid") from error
    if reparsed != value or reparsed.sha256() != value.sha256():
        raise ValueError(f"{description} runtime binding is not canonical")
    return reparsed


def _immutable_mapping(value: object, description: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not key or not isinstance(item, str) or not item
        for key, item in value.items()
    ):
        raise ValueError(f"{description} must contain non-empty string pairs")
    return MappingProxyType(dict(sorted(value.items())))


def _validate_semantic_digest(
    spec: DirectAttemptSpec, binding: DirectRuntimeBinding
) -> None:
    component = {"C1": None, "C2": "hkb", "C3": "semantic_manifest"}[binding.condition]
    expected = (
        None
        if component is None
        else dict(binding.context.component_sha256).get(component)
    )
    if expected is None and component is not None:
        raise ValueError(f"runtime binding context lacks the {component} component")
    if spec.semantic_model_sha256 != expected:
        raise ValueError(
            "semantic_model_sha256 does not match the condition context component"
        )

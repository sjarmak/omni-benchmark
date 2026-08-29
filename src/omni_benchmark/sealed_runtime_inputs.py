"""Recover exact production adapter input paths from the frozen Git object."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .freeze_b import CONDITIONS, FreezeBError, FreezeBCondition, FreezeBManifest
from .freeze_b_record import (
    MAX_FROZEN_FILE_BYTES,
    MAX_SPEC_BYTES,
    FreezeBRecordError,
    _committed_input,
    _conditions,
    _database,
    _frozen_paths,
    _input_spec,
    _mapping,
    _relative_path,
    _repository_root,
)

_CONDITION_FIELDS = frozenset(
    {
        "budget_id",
        "condition",
        "harness_config_path",
        "instructions_path",
        "model",
        "model_config_id",
        "prompt_path",
        "provider",
        "runtime_policy_path",
        "semantic_model_path",
        "semantic_model_ref",
    }
)


class SealedRuntimeInputError(RuntimeError):
    """Raised when frozen adapter input paths cannot reproduce Freeze B."""


@dataclass(frozen=True)
class SealedConditionRuntimeInput:
    """Exact committed public paths for one frozen production condition."""

    condition: str
    harness_config_path: Path
    instructions_path: Path
    prompt_path: Path
    runtime_policy_path: Path
    semantic_model_path: Path | None
    freeze_b_condition: FreezeBCondition


@dataclass(frozen=True)
class SealedRuntimeInputs:
    """Immutable path specification recovered exclusively from system commit S."""

    system_commit: str
    freeze_a_commit: str
    input_spec_path: Path
    input_spec_sha256: str
    database_snapshot_path: Path
    database_snapshot_sha256: str
    conditions: tuple[SealedConditionRuntimeInput, ...]

    def condition(self, name: str) -> SealedConditionRuntimeInput:
        matches = tuple(item for item in self.conditions if item.condition == name)
        if len(matches) != 1:
            raise SealedRuntimeInputError("sealed runtime condition is unavailable")
        return matches[0]

    def public_summary_json(self) -> str:
        return json.dumps(
            {
                "condition_count": len(self.conditions),
                "database_snapshot_sha256": self.database_snapshot_sha256,
                "input_spec_sha256": self.input_spec_sha256,
                "system_commit": self.system_commit,
            },
            separators=(",", ":"),
            sort_keys=True,
        )


def load_sealed_runtime_inputs(
    workspace: Path,
    *,
    system_commit: str,
    input_spec_path: Path,
    freeze_b: FreezeBManifest,
) -> SealedRuntimeInputs:
    """Load and exact-compare every production input from Git at system commit S."""
    manifest = _validated_freeze_b(freeze_b)
    if system_commit != manifest.system_commit:
        raise SealedRuntimeInputError("system commit does not match Freeze B")
    try:
        root = _repository_root(workspace)
        relative_spec = _relative_path(input_spec_path, "input spec path")
        committed_spec = _committed_input(
            root,
            system_commit,
            relative_spec,
            maximum_bytes=MAX_SPEC_BYTES,
        )
        spec = _input_spec(committed_spec.content)
    except FreezeBRecordError as error:
        raise SealedRuntimeInputError(f"input spec is unavailable: {error}") from error
    if spec["freeze_a_commit"] != manifest.freeze_a_commit:
        raise SealedRuntimeInputError("input spec Freeze A does not match Freeze B")

    frozen = dict(manifest.frozen_files)
    try:
        frozen_paths = _frozen_paths(spec["frozen_files"])
    except FreezeBRecordError as error:
        raise SealedRuntimeInputError(str(error)) from error
    if relative_spec not in frozen_paths or set(frozen_paths) != set(frozen):
        raise SealedRuntimeInputError("input spec frozen paths do not match Freeze B")

    committed = _load_frozen_inputs(root, system_commit, frozen_paths, frozen)
    if committed_spec.sha256 != frozen[relative_spec]:
        raise SealedRuntimeInputError("input spec digest does not match Freeze B")

    try:
        derived_conditions = _conditions(spec["conditions"], committed)
        database, snapshot_path = _database(spec["database"])
    except FreezeBRecordError as error:
        raise SealedRuntimeInputError(str(error)) from error
    expected_conditions = [item.as_dict() for item in manifest.conditions]
    if derived_conditions != expected_conditions:
        raise SealedRuntimeInputError(
            "input spec condition identities do not match Freeze B"
        )
    if (
        database["postgresql_version"] != manifest.postgresql_version
        or database["libpq_version"] != manifest.libpq_version
        or snapshot_path not in committed
        or committed[snapshot_path].sha256 != manifest.snapshot_manifest_sha256
    ):
        raise SealedRuntimeInputError("database snapshot does not match Freeze B")

    conditions = _condition_inputs(spec["conditions"], manifest)
    return SealedRuntimeInputs(
        system_commit=system_commit,
        freeze_a_commit=manifest.freeze_a_commit,
        input_spec_path=Path(relative_spec),
        input_spec_sha256=committed_spec.sha256,
        database_snapshot_path=Path(snapshot_path),
        database_snapshot_sha256=committed[snapshot_path].sha256,
        conditions=conditions,
    )


def _load_frozen_inputs(
    workspace: Path,
    commit: str,
    paths: tuple[str, ...],
    frozen: Mapping[str, str],
) -> dict[str, Any]:
    committed: dict[str, Any] = {}
    try:
        for path in paths:
            value = _committed_input(
                workspace,
                commit,
                path,
                maximum_bytes=MAX_FROZEN_FILE_BYTES,
            )
            if frozen.get(path) != value.sha256:
                raise SealedRuntimeInputError(
                    f"frozen digest for {path} does not match system commit"
                )
            committed[path] = value
    except FreezeBRecordError as error:
        raise SealedRuntimeInputError(str(error)) from error
    return committed


def _condition_inputs(
    value: object, manifest: FreezeBManifest
) -> tuple[SealedConditionRuntimeInput, ...]:
    if not isinstance(value, list) or len(value) != len(CONDITIONS):
        raise SealedRuntimeInputError("input spec conditions are incomplete")
    output: list[SealedConditionRuntimeInput] = []
    try:
        for expected, raw in zip(CONDITIONS, value, strict=True):
            item = _mapping(raw, _CONDITION_FIELDS, "condition")
            if item["condition"] != expected:
                raise SealedRuntimeInputError("input spec condition order is invalid")
            semantic = item["semantic_model_path"]
            output.append(
                SealedConditionRuntimeInput(
                    condition=expected,
                    harness_config_path=Path(
                        _relative_path(
                            item["harness_config_path"],
                            f"{expected} harness config path",
                        )
                    ),
                    instructions_path=Path(
                        _relative_path(
                            item["instructions_path"],
                            f"{expected} instructions path",
                        )
                    ),
                    prompt_path=Path(
                        _relative_path(item["prompt_path"], f"{expected} prompt path")
                    ),
                    runtime_policy_path=Path(
                        _relative_path(
                            item["runtime_policy_path"],
                            f"{expected} runtime policy path",
                        )
                    ),
                    semantic_model_path=(
                        None
                        if semantic is None
                        else Path(
                            _relative_path(semantic, f"{expected} semantic model path")
                        )
                    ),
                    freeze_b_condition=manifest.condition(expected),
                )
            )
    except FreezeBRecordError as error:
        raise SealedRuntimeInputError(str(error)) from error
    return tuple(output)


def _validated_freeze_b(value: object) -> FreezeBManifest:
    if type(value) is not FreezeBManifest:
        raise SealedRuntimeInputError("canonical Freeze B is required")
    try:
        parsed = FreezeBManifest.from_dict(value.as_dict())
    except FreezeBError as error:
        raise SealedRuntimeInputError("Freeze B is invalid") from error
    if parsed != value:
        raise SealedRuntimeInputError("Freeze B is not canonical")
    return parsed

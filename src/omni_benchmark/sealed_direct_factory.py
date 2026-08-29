"""Post-approval construction of exact C1-C3 production dependencies."""

from __future__ import annotations

import os
import json
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .artifact_store import ArtifactStore
from .claude_direct_contract import ClaudeDirectConfig
from .claude_direct_transport import (
    PINNED_CLAUDE_BINARY_SHA256,
    PINNED_CLAUDE_VERSION,
    ClaudeDirectTransport,
)
from .direct_database_loader import load_committed_direct_database_identity
from .direct_probe_cli import (
    DirectRuntimeSpec,
    _validate_oauth_directory,
    load_committed_direct_runtime_spec,
    private_runtime_directories,
)
from .direct_postgres import AttestedDirectPostgresTransport
from .direct_public_context import load_direct_public_tools
from .sealed_direct_adapter import (
    SealedDirectConditionAdapter,
    SealedDirectPreparedCapture,
    SealedDirectRuntimeBinding,
    prepare_sealed_direct_capture,
)
from .sealed_dispatch import AdapterFactory, SealedDispatchPolicy
from .sealed_generation_staging import SealedPreparedAttempt
from .sealed_runtime_inputs import (
    SealedConditionRuntimeInput,
    SealedRuntimeInputs,
)

_DIRECT_PATHS = {
    "C1": Path("config/conditions/c1-direct-sql-v1.json"),
    "C2": Path("config/conditions/c2-direct-sql-v1.json"),
    "C3": Path("config/conditions/c3-direct-sql-v1.json"),
}
_INSTRUCTIONS_PATH = Path("config/instructions/direct-sql-v1.json")
_PROMPT_PATH = Path("config/prompts/direct-sql-v1.txt")
_RUNTIME_PATH = Path("config/conditions/direct-runtime-v1.json")
_SEMANTIC_PATHS = {
    "C1": None,
    "C2": Path("semantic_models/public_ir/manifest.json"),
    "C3": Path("semantic_models/public_bundle/manifest.json"),
}
_PG_FIELDS = frozenset(
    {"PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGPORT", "PGSSLMODE"}
)
_DATABASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,127}")


class SealedDirectFactoryError(RuntimeError):
    """Raised before an inexact direct production dependency can execute."""


class DatabaseEnvironmentDirectory:
    """Read one external mode-0600 PostgreSQL environment after approval."""

    def __init__(self, workspace: Path, root: Path) -> None:
        supplied = Path(root)
        try:
            metadata = supplied.stat(follow_symlinks=False)
            resolved = supplied.resolve(strict=True)
        except OSError as error:
            raise SealedDirectFactoryError(
                "database environment directory is unavailable"
            ) from error
        if (
            resolved.is_relative_to(workspace)
            or supplied.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
        ):
            raise SealedDirectFactoryError(
                "database environment directory must be external and private"
            )
        self._root = resolved

    def __repr__(self) -> str:
        return "DatabaseEnvironmentDirectory(<external-private-directory>)"

    def for_database(self, database: str) -> dict[str, str]:
        if not isinstance(database, str) or _DATABASE.fullmatch(database) is None:
            raise SealedDirectFactoryError("database environment identity is invalid")
        path = self._root / f"{database}.json"
        try:
            metadata = path.stat(follow_symlinks=False)
            if (
                path.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
            ):
                raise OSError("not private")
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SealedDirectFactoryError(
                "private database environment is unavailable"
            ) from error
        if (
            not isinstance(value, dict)
            or set(value) != _PG_FIELDS
            or any(not isinstance(item, str) or not item for item in value.values())
        ):
            raise SealedDirectFactoryError(
                "private database environment schema is invalid"
            )
        return dict(value)


@dataclass(frozen=True)
class SealedDirectProductionConfig:
    """Non-secret paths needed to construct direct transports after approval."""

    workspace: Path
    system_commit: str
    runtime_inputs: SealedRuntimeInputs
    capture_root: Path
    claude_config_directories: tuple[Path, Path, Path]
    database_environment_root: Path
    runtime_parent: Path

    @classmethod
    def create(
        cls,
        *,
        workspace: Path,
        system_commit: str,
        runtime_inputs: SealedRuntimeInputs,
        capture_root: Path,
        claude_config_directories: tuple[Path, Path, Path],
        database_environment_root: Path,
        runtime_parent: Path,
    ) -> SealedDirectProductionConfig:
        try:
            root = workspace.resolve(strict=True)
        except OSError as error:
            raise SealedDirectFactoryError(
                "direct production workspace is unavailable"
            ) from error
        if root != workspace.absolute() or workspace.is_symlink() or not root.is_dir():
            raise SealedDirectFactoryError("direct production workspace is unsafe")
        if (
            type(runtime_inputs) is not SealedRuntimeInputs
            or runtime_inputs.system_commit != system_commit
        ):
            raise SealedDirectFactoryError(
                "sealed runtime inputs do not match system commit"
            )
        profiles = tuple(Path(path) for path in claude_config_directories)
        if (
            len(profiles) != 3
            or len(set(profiles)) != 3
            or any(not path.is_absolute() for path in profiles)
        ):
            raise SealedDirectFactoryError(
                "exactly three distinct absolute Claude lease paths are required"
            )
        database_root = Path(database_environment_root)
        temp_parent = Path(runtime_parent)
        if not database_root.is_absolute() or not temp_parent.is_absolute():
            raise SealedDirectFactoryError(
                "database and runtime roots must be absolute"
            )
        return cls(
            workspace=root,
            system_commit=system_commit,
            runtime_inputs=runtime_inputs,
            capture_root=Path(capture_root),
            claude_config_directories=profiles,  # type: ignore[arg-type]
            database_environment_root=database_root,
            runtime_parent=temp_parent,
        )


def build_sealed_direct_adapter_factory(
    config: SealedDirectProductionConfig,
    *,
    condition: str,
    policy: SealedDispatchPolicy,
) -> AdapterFactory:
    """Return an inert adapter factory; external resources open per attempt only."""
    selected = _validated_config(config)
    condition_input = selected.runtime_inputs.condition(condition)
    _require_direct_paths(condition_input)
    _require_cli_identity(policy, condition)

    def adapter_factory(frozen_condition):  # type: ignore[no-untyped-def]
        if frozen_condition != condition_input.freeze_b_condition:
            raise SealedDirectFactoryError(
                "direct adapter condition does not match frozen inputs"
            )
        return SealedDirectConditionAdapter(
            workspace=selected.workspace,
            capture_root=selected.capture_root,
            condition_binding=frozen_condition,
            policy=policy,
            capture_factory=lambda prepared, store: _capture_dependencies(
                selected,
                condition_input,
                prepared,
                store,
            ),
        )

    return adapter_factory


@contextmanager
def _capture_dependencies(
    config: SealedDirectProductionConfig,
    condition_input: SealedConditionRuntimeInput,
    prepared: SealedPreparedAttempt,
    store: ArtifactStore,
) -> Iterator[SealedDirectPreparedCapture]:
    if (
        prepared.condition != condition_input.condition
        or prepared.condition_binding != condition_input.freeze_b_condition
    ):
        raise SealedDirectFactoryError(
            "prepared direct attempt does not match frozen condition"
        )
    profile = config.claude_config_directories[prepared.repetition - 1]
    _validate_external_private_directory(
        config.workspace, profile, "Claude lease directory"
    )
    _validate_oauth_directory(profile)
    database_directory = DatabaseEnvironmentDirectory(
        config.workspace, config.database_environment_root
    )
    database_environment = database_directory.for_database(prepared.database)
    process_environment = dict(os.environ)
    runtime = load_committed_direct_runtime_spec(config.workspace, config.system_commit)
    _require_runtime_identity(runtime, condition_input, prepared)
    public_tools = load_direct_public_tools(
        config.workspace,
        config.system_commit,
        prepared.database,
        prepared.condition,
        environment=process_environment,
    )
    database_identity = load_committed_direct_database_identity(
        config.workspace,
        config.system_commit,
        selected_database=prepared.database,
        environment=process_environment,
    )
    runtime_parent = _validate_external_private_directory(
        config.workspace, config.runtime_parent, "runtime parent"
    )
    with private_runtime_directories(parent=runtime_parent) as directories:
        runtime_home, temp_directory, working_directory = directories
        model_transport = ClaudeDirectTransport(
            ClaudeDirectConfig(
                budget_id=runtime.budget_id,
                claude_config_dir=profile,
                effort=runtime.effort,
                maximum_cost_usd=runtime.maximum_cost_usd_per_turn,
                maximum_turns=runtime.maximum_turns,
                model=runtime.model,
                runtime_home=runtime_home,
                temp_directory=temp_directory,
                timeout_seconds=runtime.timeout_seconds_per_turn,
                working_directory=working_directory,
            )
        )
        database = AttestedDirectPostgresTransport(
            database_environment,
            expected_identity=database_identity,
        )
        binding = SealedDirectRuntimeBinding.from_prepared(
            prepared=prepared,
            context=public_tools.identity,
            database=database_identity,
            model=model_transport.runtime_identity,
            budget=model_transport.budget_identity,
            environment=process_environment,
        )
        yield prepare_sealed_direct_capture(
            prepared=prepared,
            binding=binding,
            model_transport=model_transport,
            database=database,
            public_tools=public_tools,
            store=store,
        )


def _validated_config(value: object) -> SealedDirectProductionConfig:
    if type(value) is not SealedDirectProductionConfig:
        raise SealedDirectFactoryError("direct production configuration is invalid")
    reparsed = SealedDirectProductionConfig.create(
        workspace=value.workspace,
        system_commit=value.system_commit,
        runtime_inputs=value.runtime_inputs,
        capture_root=value.capture_root,
        claude_config_directories=value.claude_config_directories,
        database_environment_root=value.database_environment_root,
        runtime_parent=value.runtime_parent,
    )
    if reparsed != value:
        raise SealedDirectFactoryError(
            "direct production configuration is not canonical"
        )
    return reparsed


def _validate_external_private_directory(
    workspace: Path, value: Path, description: str
) -> Path:
    supplied = Path(value)
    try:
        metadata = supplied.stat(follow_symlinks=False)
        resolved = supplied.resolve(strict=True)
    except OSError as error:
        raise SealedDirectFactoryError(f"{description} is unavailable") from error
    if (
        resolved.is_relative_to(workspace)
        or supplied.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != os.getuid()
    ):
        raise SealedDirectFactoryError(
            f"{description} must be an external private directory"
        )
    return resolved


def _require_direct_paths(value: SealedConditionRuntimeInput) -> None:
    expected = {
        "harness_config_path": _DIRECT_PATHS.get(value.condition),
        "instructions_path": _INSTRUCTIONS_PATH,
        "prompt_path": _PROMPT_PATH,
        "runtime_policy_path": _RUNTIME_PATH,
        "semantic_model_path": _SEMANTIC_PATHS.get(value.condition),
    }
    if value.condition not in _DIRECT_PATHS or any(
        getattr(value, field) != path for field, path in expected.items()
    ):
        raise SealedDirectFactoryError("direct frozen input path is unsupported")


def _require_cli_identity(policy: SealedDispatchPolicy, condition: str) -> None:
    if type(policy) is not SealedDispatchPolicy:
        raise SealedDirectFactoryError("sealed dispatch policy is invalid")
    expected = {
        "claude": PINNED_CLAUDE_VERSION,
        "claude.sha256": PINNED_CLAUDE_BINARY_SHA256,
    }
    if policy.cli_versions(condition) != expected:
        raise SealedDirectFactoryError("direct CLI identity does not match the pin")


def _require_runtime_identity(
    runtime: DirectRuntimeSpec,
    condition_input: SealedConditionRuntimeInput,
    prepared: SealedPreparedAttempt,
) -> None:
    frozen = condition_input.freeze_b_condition
    expected_model_config = f"{runtime.adapter}:{runtime.adapter_version}"
    if (
        type(runtime) is not DirectRuntimeSpec
        or runtime.sha256 != frozen.runtime_policy_sha256
        or runtime.provider != frozen.provider
        or runtime.model != frozen.model
        or runtime.budget_id != frozen.budget_id
        or frozen.model_config_id not in {runtime.adapter, expected_model_config}
        or prepared.condition_binding != frozen
    ):
        raise SealedDirectFactoryError("direct runtime policy does not match Freeze B")

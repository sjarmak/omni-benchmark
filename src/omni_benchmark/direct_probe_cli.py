"""Run one committed public dev-A question through C1, C2, or C3."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from .claude_direct_contract import ClaudeDirectConfig
from .claude_direct_transport import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    PINNED_CLAUDE_BINARY_SHA256,
    PINNED_CLAUDE_VERSION,
    PROVIDER_ID,
)
from .claude_resource_identity import (
    ClaudeResourceIdentityError,
    validate_private_directory,
)
from .content_policy import ContentPolicy
from .direct_attempt_binding import DirectAttemptSpec
from .direct_prepared_attempt import (
    DirectPreparedAttemptError,
    prepare_committed_direct_attempt,
)
from .direct_sql_attempt import DirectAttemptArtifacts, write_direct_attempt
from .direct_sql_capture import DirectCaptureError, DirectSqlCapture
from .direct_runtime_binding import DirectRuntimeBinding
from .omni_probe_preflight import OmniProbePreflightError, committed_spec

_RUNTIME_SPEC_PATH = Path("config/conditions/direct-runtime-v1.json")
_RUNTIME_FIELDS = frozenset(
    {
        "adapter",
        "adapter_version",
        "budget_id",
        "effort",
        "harness_retry_ceiling",
        "input_token_ceiling",
        "maximum_cost_usd_per_turn",
        "maximum_turns",
        "model",
        "output_token_ceiling",
        "provider",
        "schema_version",
        "timeout_seconds_per_turn",
        "token_ceiling_unavailable_reason",
    }
)
_EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})
_MODEL_PATTERN = re.compile(r"claude-[a-z0-9.-]*\d[a-z0-9.-]*")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_DATABASE_ENVIRONMENT_FIELDS = (
    "PGHOST",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGPORT",
    "PGSSLMODE",
    "PGSSLROOTCERT",
)


class DirectProbeCliError(RuntimeError):
    """Safe failure raised before or around a direct comparator canary."""


@dataclass(frozen=True)
class DirectRuntimeSpec:
    """One common committed model and budget policy for C1-C3."""

    adapter: str
    adapter_version: str
    budget_id: str
    effort: str
    harness_retry_ceiling: int
    input_token_ceiling: int | None
    maximum_cost_usd_per_turn: float
    maximum_turns: int
    model: str
    output_token_ceiling: int | None
    provider: str
    timeout_seconds_per_turn: float
    token_ceiling_unavailable_reason: str
    sha256: str


@dataclass(frozen=True)
class DirectProbeArguments:
    """Validated command-line identity for one direct attempt."""

    workspace: Path
    system_commit: str
    instance_id: str
    condition: str
    output_root: Path
    run_id: str
    repetition: int
    claude_config_dir: Path


@dataclass(frozen=True)
class DirectProbePlan:
    """Exact in-memory dependencies for one acknowledged attempt."""

    arguments: DirectProbeArguments
    workspace: Path
    runtime: DirectRuntimeSpec
    claude_config: ClaudeDirectConfig
    store: ArtifactStore
    environment: Mapping[str, str] = field(repr=False)
    database_environment: Mapping[str, str] = field(repr=False)


AttemptRunner = Callable[[DirectProbePlan], Mapping[str, object]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--condition", choices=("C1", "C2", "C3"), required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--claude-config-dir", type=Path, required=True)
    parser.add_argument("--execute-authenticated-smoke", action="store_true")
    return parser


def direct_probe_main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    attempt_runner: AttemptRunner | None = None,
) -> int:
    """Run one explicitly acknowledged comparator and print a safe receipt."""
    parsed = _parser().parse_args(argv)
    if not parsed.execute_authenticated_smoke:
        raise DirectProbeCliError("direct smoke requires explicit acknowledgement")
    process_environment = dict(os.environ if environment is None else environment)
    arguments = _arguments(parsed)
    runtime = load_committed_direct_runtime_spec(
        arguments.workspace, arguments.system_commit
    )
    _validate_oauth_directory(arguments.claude_config_dir)
    runner = _run_committed_direct_attempt if attempt_runner is None else attempt_runner
    with private_runtime_directories(parent=Path(tempfile.gettempdir())) as directories:
        plan = _plan(arguments, runtime, process_environment, directories)
        receipt = runner(plan)
    _print_receipt(receipt, process_environment)
    return 0


def load_committed_direct_runtime_spec(
    workspace: Path, commit: str
) -> DirectRuntimeSpec:
    """Load the single exact runtime policy shared by C1, C2, and C3."""
    try:
        resolved = workspace.resolve(strict=True)
        if _COMMIT_PATTERN.fullmatch(commit) is None:
            raise DirectProbeCliError("system commit must be a Git object ID")
        spec = committed_spec(resolved, commit, _RUNTIME_SPEC_PATH)
        value = json.loads(spec.content, parse_constant=_reject_json_constant)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        OmniProbePreflightError,
    ) as error:
        raise DirectProbeCliError(
            "committed direct runtime policy is unavailable"
        ) from error
    if not isinstance(value, dict) or set(value) != _RUNTIME_FIELDS:
        raise DirectProbeCliError("direct runtime policy must use the exact schema")
    if ContentPolicy.from_environment({}).sanitize_json(value) != value:
        raise DirectProbeCliError("direct runtime policy contains sensitive content")
    return _runtime_spec(value, spec.sha256)


@contextmanager
def private_runtime_directories(parent: Path) -> Iterator[tuple[Path, Path, Path]]:
    """Yield fresh 0700 home, temporary, and working directories, then remove them."""
    root: Path | None = None
    try:
        resolved_parent = parent.resolve(strict=True)
        if not stat.S_ISDIR(resolved_parent.stat().st_mode):
            raise OSError("runtime parent is not a directory")
        root = Path(
            tempfile.mkdtemp(prefix="omni-direct-runtime-", dir=resolved_parent)
        )
        os.chmod(root, 0o700)
        directories = (
            _private_child(root, "home"),
            _private_child(root, "temp"),
            _private_child(root, "work"),
        )
    except OSError as error:
        if root is not None:
            _remove_runtime_root(root)
        raise DirectProbeCliError(
            "private direct runtime could not be created"
        ) from error
    try:
        yield directories
    finally:
        _remove_runtime_root(root)


def _arguments(value: argparse.Namespace) -> DirectProbeArguments:
    try:
        workspace = value.workspace.resolve(strict=True)
        claude_config = value.claude_config_dir.resolve(strict=True)
    except OSError as error:
        raise DirectProbeCliError(
            "direct smoke workspace or OAuth profile is unavailable"
        ) from error
    if not isinstance(value.instance_id, str) or not value.instance_id:
        raise DirectProbeCliError("instance ID must be a non-empty string")
    if not isinstance(value.run_id, str) or not value.run_id:
        raise DirectProbeCliError("run ID must be a non-empty string")
    if type(value.repetition) is not int or value.repetition < 1:
        raise DirectProbeCliError("repetition must be a positive integer")
    return DirectProbeArguments(
        workspace=workspace,
        system_commit=value.system_commit,
        instance_id=value.instance_id,
        condition=value.condition,
        output_root=value.output_root,
        run_id=value.run_id,
        repetition=value.repetition,
        claude_config_dir=claude_config,
    )


def _plan(
    arguments: DirectProbeArguments,
    runtime: DirectRuntimeSpec,
    environment: Mapping[str, str],
    directories: tuple[Path, Path, Path],
) -> DirectProbePlan:
    try:
        store = ArtifactStore(
            arguments.workspace,
            arguments.output_root,
            environment=environment,
            require_new_root=True,
        )
    except ArtifactStoreError as error:
        raise DirectProbeCliError(str(error)) from error
    runtime_home, temp_directory, working_directory = directories
    claude_config = ClaudeDirectConfig(
        budget_id=runtime.budget_id,
        claude_config_dir=arguments.claude_config_dir,
        effort=runtime.effort,
        maximum_cost_usd=runtime.maximum_cost_usd_per_turn,
        maximum_turns=runtime.maximum_turns,
        model=runtime.model,
        runtime_home=runtime_home,
        temp_directory=temp_directory,
        timeout_seconds=runtime.timeout_seconds_per_turn,
        working_directory=working_directory,
    )
    database_environment = {
        key: environment[key]
        for key in _DATABASE_ENVIRONMENT_FIELDS
        if key in environment
    }
    return DirectProbePlan(
        arguments=arguments,
        workspace=arguments.workspace,
        runtime=runtime,
        claude_config=claude_config,
        store=store,
        environment=MappingProxyType(dict(environment)),
        database_environment=MappingProxyType(database_environment),
    )


def _run_committed_direct_attempt(plan: DirectProbePlan) -> Mapping[str, object]:
    arguments = plan.arguments
    try:
        prepared = prepare_committed_direct_attempt(
            workspace=plan.workspace,
            commit=arguments.system_commit,
            scope="dev-a",
            instance_id=arguments.instance_id,
            condition=arguments.condition,
            run_id=arguments.run_id,
            repetition=arguments.repetition,
            claude_config=plan.claude_config,
            database_environment=plan.database_environment,
            store=plan.store,
            environment=plan.environment,
        )
        probe = DirectSqlCapture(prepared=prepared).capture()
        semantic_ref, semantic_sha = _semantic_identity(prepared.binding)
        artifacts = write_direct_attempt(
            workspace=plan.workspace,
            store=plan.store,
            spec=DirectAttemptSpec(
                binding=prepared.binding,
                controllable_seed=None,
                semantic_model_ref=semantic_ref,
                semantic_model_sha256=semantic_sha,
                software_versions={
                    "omni-benchmark": importlib.metadata.version("omni-benchmark")
                },
                cli_versions={
                    "claude": PINNED_CLAUDE_VERSION,
                    "claude.sha256": PINNED_CLAUDE_BINARY_SHA256,
                },
            ),
            probe=probe,
        )
    except (DirectPreparedAttemptError, DirectCaptureError, ValueError) as error:
        raise DirectProbeCliError(str(error)) from error
    return _attempt_receipt(
        plan, probe.generation_outcome, probe.failure_class, artifacts
    )


def _semantic_identity(binding: DirectRuntimeBinding) -> tuple[str, str | None]:
    components = dict(binding.context.component_sha256)
    component = {"C1": "schema", "C2": "hkb", "C3": "semantic_manifest"}[
        binding.condition
    ]
    digest = components[component]
    prefix = {"C1": "raw-schema", "C2": "public-hkb", "C3": "omni-semantic"}[
        binding.condition
    ]
    return f"{prefix}:{digest}", None if binding.condition == "C1" else digest


def _attempt_receipt(
    plan: DirectProbePlan,
    generation_outcome: str,
    failure_class: str | None,
    artifacts: DirectAttemptArtifacts,
) -> dict[str, object]:
    return {
        "condition": plan.arguments.condition,
        "failure_class": failure_class,
        "generation": _artifact_receipt(plan.workspace, artifacts.generation),
        "generation_outcome": generation_outcome,
        "instance_id": plan.arguments.instance_id,
        "run_manifest": _artifact_receipt(plan.workspace, artifacts.run_manifest),
        "runtime_policy_sha256": plan.runtime.sha256,
    }


def _artifact_receipt(workspace: Path, artifact: StoredArtifact) -> dict[str, object]:
    return {
        "path": artifact.path.relative_to(workspace).as_posix(),
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _runtime_spec(value: Mapping[str, Any], sha256: str) -> DirectRuntimeSpec:
    if (
        value["schema_version"] != 1
        or value["adapter"] != ADAPTER_ID
        or value["adapter_version"] != ADAPTER_VERSION
        or value["provider"] != PROVIDER_ID
    ):
        raise DirectProbeCliError("direct runtime policy identity is unsupported")
    effort = value["effort"]
    model = value["model"]
    maximum_turns = value["maximum_turns"]
    retry_ceiling = value["harness_retry_ceiling"]
    timeout = value["timeout_seconds_per_turn"]
    maximum_cost = value["maximum_cost_usd_per_turn"]
    reason = value["token_ceiling_unavailable_reason"]
    if (
        effort not in _EFFORT_LEVELS
        or not isinstance(model, str)
        or _MODEL_PATTERN.fullmatch(model) is None
    ):
        raise DirectProbeCliError("direct runtime model policy is invalid")
    if type(maximum_turns) is not int or maximum_turns < 1:
        raise DirectProbeCliError("direct runtime maximum turns is invalid")
    if type(retry_ceiling) is not int or retry_ceiling != 0:
        raise DirectProbeCliError("direct harness retry ceiling must be zero")
    _positive_finite(timeout, "timeout")
    _positive_finite(maximum_cost, "maximum cost")
    if (
        value["input_token_ceiling"] is not None
        or value["output_token_ceiling"] is not None
    ):
        raise DirectProbeCliError("unsupported token ceilings must remain null")
    if not isinstance(reason, str) or not reason:
        raise DirectProbeCliError("token ceiling unavailability reason is required")
    budget_id = value["budget_id"]
    if not isinstance(budget_id, str) or not budget_id:
        raise DirectProbeCliError("direct runtime budget ID is invalid")
    return DirectRuntimeSpec(
        adapter=ADAPTER_ID,
        adapter_version=ADAPTER_VERSION,
        budget_id=budget_id,
        effort=effort,
        harness_retry_ceiling=retry_ceiling,
        input_token_ceiling=None,
        maximum_cost_usd_per_turn=float(maximum_cost),
        maximum_turns=maximum_turns,
        model=model,
        output_token_ceiling=None,
        provider=PROVIDER_ID,
        timeout_seconds_per_turn=float(timeout),
        token_ceiling_unavailable_reason=reason,
        sha256=sha256,
    )


def _validate_oauth_directory(path: Path) -> None:
    try:
        validate_private_directory(path, "Claude OAuth directory")
    except ClaudeResourceIdentityError as error:
        raise DirectProbeCliError(str(error)) from error


def _private_child(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(mode=0o700)
    return path


def _remove_runtime_root(root: Path) -> None:
    try:
        shutil.rmtree(root)
    except OSError as error:
        raise DirectProbeCliError(
            "private direct runtime could not be removed"
        ) from error


def _positive_finite(value: object, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise DirectProbeCliError(f"direct runtime {name} is invalid")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _print_receipt(value: Mapping[str, object], environment: Mapping[str, str]) -> None:
    materialized = dict(value)
    if (
        ContentPolicy.from_environment(environment).sanitize_json(materialized)
        != materialized
    ):
        raise DirectProbeCliError("direct smoke receipt contains sensitive content")
    print(
        json.dumps(materialized, allow_nan=False, separators=(",", ":"), sort_keys=True)
    )

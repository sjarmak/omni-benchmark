"""Fail-closed local provenance and specification checks for a C4 probe."""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import math
import os
import py_compile
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .omni_cli import OmniCliSettings

RUNTIME_PATHS = ("src", "scripts", "pyproject.toml", "uv.lock")
CONDITION_FIELDS = frozenset(
    {
        "condition",
        "execution",
        "knowledge",
        "managed_llm_identity",
        "maximum_status_checks",
        "model_config_id",
        "omni_cli_sha256",
        "omni_cli_version",
        "poll_schedule_seconds",
        "production_retry_policy",
        "provider",
        "result_selection",
        "semantic_enforcement",
        "typed_result_cache",
        "typed_result_formatting",
        "typed_result_type",
        "truncated_result_policy",
    }
)
INSTRUCTION_FIELDS = frozenset(
    {
        "adapter_instruction",
        "managed_agent_instructions",
        "question_specific_hidden_annotations",
        "runtime_oracle_context",
    }
)
ADAPTER_INSTRUCTION = (
    "Submit the public benchmark question unchanged through Omni's production "
    "agent job API."
)
VERSION_PATTERN = re.compile(r"omni version ([A-Za-z0-9][A-Za-z0-9._+-]{0,79})")
SAFE_VERSION_ENVIRONMENT = frozenset({"LANG", "LC_ALL", "LC_CTYPE", "PATH", "TMPDIR"})
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
MAX_CLI_BINARY_BYTES = 128 * 1024 * 1024


class OmniProbePreflightError(RuntimeError):
    """Raised before authentication when local probe inputs are not reproducible."""


@dataclass(frozen=True)
class CommittedSpec:
    """One regular Git blob whose worktree bytes match the claimed commit."""

    path: Path
    content: bytes
    sha256: str


@dataclass(frozen=True)
class C4ConditionSpec:
    """Validated production C4 controls that the adapter can apply or enforce."""

    managed_llm_identity: str
    maximum_status_checks: int
    model_config_id: str
    omni_cli_sha256: str
    omni_cli_version: str
    poll_schedule_seconds: tuple[float, ...]
    provider: str


@dataclass(frozen=True)
class C4ProbeSpecs:
    """Validated and hash-bound C4 configuration inputs."""

    condition: C4ConditionSpec
    condition_sha256: str
    prompt: CommittedSpec
    prompt_sha256: str
    instructions_sha256: str


CliVersionObserver = Callable[[OmniCliSettings, Mapping[str, str]], str]


def verify_system_commit(workspace: Path, expected_commit: str) -> None:
    """Bind execution to HEAD and reject tracked or untracked runtime changes."""
    resolved = git_output(workspace, "rev-parse", "HEAD").decode().strip()
    if resolved != expected_commit:
        raise OmniProbePreflightError("system commit does not match workspace HEAD")
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            *RUNTIME_PATHS,
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise OmniProbePreflightError("cannot verify the runtime worktree")
    if completed.stdout:
        raise OmniProbePreflightError(
            "authenticated smoke requires a clean runtime tree"
        )
    _verify_ignored_runtime_files(workspace)


def _verify_ignored_runtime_files(workspace: Path) -> None:
    output = git_output(
        workspace,
        "ls-files",
        "-z",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--",
        "src",
        "scripts",
    )
    for encoded in output.split(b"\0"):
        if not encoded:
            continue
        path = Path(encoded.decode("utf-8"))
        if path.suffix == ".pyc" and _is_loadable_bytecode(path):
            _verify_bytecode_matches_source(workspace, path)
        elif _is_ignored_executable(path):
            raise OmniProbePreflightError(
                "authenticated smoke requires a clean runtime tree"
            )


def _is_ignored_executable(path: Path) -> bool:
    name = path.name
    return path.suffix in {".py", ".pyw"} or any(
        name.endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES
    )


def _is_loadable_bytecode(path: Path) -> bool:
    if path.parent.name != "__pycache__":
        return True
    cache_tag = sys.implementation.cache_tag
    return cache_tag is None or f".{cache_tag}." in path.name


def _verify_bytecode_matches_source(workspace: Path, bytecode_path: Path) -> None:
    try:
        bytecode = _read_regular_file(workspace, bytecode_path)
        source_path = _source_for_bytecode(bytecode_path)
        _read_regular_file(workspace, source_path)
        if not _matches_compiled_source(
            workspace, source_path, bytecode, _bytecode_optimization(bytecode_path)
        ):
            raise ValueError("bytecode differs from source")
    except (OSError, UnicodeError, ValueError, py_compile.PyCompileError) as error:
        raise OmniProbePreflightError(
            "authenticated smoke requires a clean runtime tree"
        ) from error


def _matches_compiled_source(
    workspace: Path, source_path: Path, bytecode: bytes, optimization: int
) -> bool:
    full_source = workspace / source_path
    display_paths = (str(full_source), source_path.as_posix())
    with tempfile.TemporaryDirectory(prefix="omni-probe-bytecode-") as directory:
        for index, display_path in enumerate(display_paths):
            for mode in py_compile.PycInvalidationMode:
                expected_path = Path(directory) / f"expected-{index}-{mode.value}.pyc"
                py_compile.compile(
                    str(full_source),
                    cfile=str(expected_path),
                    dfile=display_path,
                    doraise=True,
                    optimize=optimization,
                    invalidation_mode=mode,
                )
                if expected_path.read_bytes() == bytecode:
                    return True
    return False


def _source_for_bytecode(path: Path) -> Path:
    if path.parent.name != "__pycache__":
        return path.with_suffix(".py")
    cache_tag = sys.implementation.cache_tag
    marker = "" if cache_tag is None else f".{cache_tag}"
    if not marker or marker not in path.name:
        raise ValueError("bytecode cache tag does not match this interpreter")
    module_name = path.name.split(marker, maxsplit=1)[0]
    return path.parent.parent / f"{module_name}.py"


def _bytecode_optimization(path: Path) -> int:
    match = re.search(r"\.opt-(\d+)\.pyc$", path.name)
    return sys.flags.optimize if match is None else int(match.group(1))


def load_c4_probe_specs(
    workspace: Path,
    commit: str,
    *,
    condition_path: Path,
    prompt_path: Path,
    instructions_path: Path,
) -> C4ProbeSpecs:
    """Load exact committed blobs and validate every supported C4 control."""
    condition = committed_spec(workspace, commit, condition_path)
    prompt = committed_spec(workspace, commit, prompt_path)
    instructions = committed_spec(workspace, commit, instructions_path)
    return C4ProbeSpecs(
        condition=_parse_condition(condition.content),
        condition_sha256=condition.sha256,
        prompt=prompt,
        prompt_sha256=_validate_prompt(prompt),
        instructions_sha256=_validate_instructions(instructions),
    )


def committed_spec(workspace: Path, commit: str, path: Path) -> CommittedSpec:
    """Read one committed regular-file blob and compare it to no-follow worktree IO."""
    relative = _confined_path(path)
    object_name = f"{commit}:{relative.as_posix()}"
    object_type = git_output(workspace, "cat-file", "-t", object_name).decode().strip()
    if object_type != "blob":
        raise OmniProbePreflightError("run specification must be a Git blob")
    committed = git_output(workspace, "show", object_name)
    current = _read_regular_file(workspace, relative)
    if current != committed:
        raise OmniProbePreflightError(
            "run specification current bytes must match the system commit"
        )
    return CommittedSpec(
        path=relative,
        content=committed,
        sha256=hashlib.sha256(committed).hexdigest(),
    )


def render_public_question(prompt: CommittedSpec, question: str) -> str:
    """Apply the only supported prompt template without altering public text."""
    _validate_prompt(prompt)
    rendered = prompt.content.decode("utf-8")[:-1].replace("{question}", question)
    if rendered != question:
        raise OmniProbePreflightError("prompt must submit the question unchanged")
    return rendered


def semantic_model_ref(settings: OmniCliSettings) -> str:
    """Identify the semantic model independently from the managed LLM identity."""
    if settings.branch_id is not None:
        return f"branch:{settings.branch_id}"
    return f"model:{settings.model_id}"


def observe_omni_cli_version(
    settings: OmniCliSettings, environment: Mapping[str, str]
) -> str:
    """Read the version from the same configured binary without forwarding secrets."""
    child_environment = {
        key: value
        for key, value in environment.items()
        if key in SAFE_VERSION_ENVIRONMENT and value
    }
    try:
        completed = subprocess.run(
            [settings.binary, "--version"],
            capture_output=True,
            check=False,
            env=child_environment,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OmniProbePreflightError("cannot observe the Omni CLI version") from error
    output = (completed.stdout or completed.stderr).strip()
    match = VERSION_PATTERN.fullmatch(output)
    if completed.returncode != 0 or match is None:
        raise OmniProbePreflightError("Omni CLI returned an invalid version response")
    return match.group(1)


def pin_omni_cli_binary(
    settings: OmniCliSettings,
    environment: Mapping[str, str],
    expected_sha256: str,
) -> tuple[OmniCliSettings, str]:
    """Resolve one executable and require its bytes to match the committed pin."""
    resolved = shutil.which(settings.binary, path=environment.get("PATH"))
    if resolved is None:
        raise OmniProbePreflightError("cannot resolve the pinned Omni CLI binary")
    path = Path(resolved).resolve(strict=True)
    observed_sha256 = hashlib.sha256(_read_cli_binary(path)).hexdigest()
    if observed_sha256 != expected_sha256:
        raise OmniProbePreflightError("Omni CLI binary SHA-256 does not match the pin")
    return replace(settings, binary=str(path)), observed_sha256


def _read_cli_binary(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            mode = stat.S_IMODE(metadata.st_mode)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or mode & 0o022
                or not mode & 0o100
                or not 1 <= metadata.st_size <= MAX_CLI_BINARY_BYTES
            ):
                raise OmniProbePreflightError("pinned Omni CLI binary is unsafe")
            content = stream.read(MAX_CLI_BINARY_BYTES + 1)
            if len(content) != metadata.st_size:
                raise OmniProbePreflightError(
                    "pinned Omni CLI binary changed while read"
                )
            return content
    except OSError as error:
        raise OmniProbePreflightError(
            "cannot read the pinned Omni CLI binary"
        ) from error


def git_output(workspace: Path, *arguments: str) -> bytes:
    """Run one read-only Git command with a generic non-leaking failure."""
    completed = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise OmniProbePreflightError(
            "run provenance must resolve from the system commit"
        )
    return completed.stdout


def _parse_condition(content: bytes) -> C4ConditionSpec:
    value = _json_object(content, "C4 condition specification")
    if set(value) != CONDITION_FIELDS:
        raise OmniProbePreflightError(
            "C4 condition specification must use the exact schema"
        )
    expected = {
        "condition": "C4",
        "execution": "omni_production_agent_job_api",
        "knowledge": "public_schema_and_hkb_encoded_in_omni_semantic_model",
        "production_retry_policy": "managed_unobservable",
        "result_selection": "last_successful_generate_query_action",
        "semantic_enforcement": "governed",
        "typed_result_cache": "disabled",
        "typed_result_formatting": False,
        "typed_result_type": "json",
        "truncated_result_policy": "evaluated_system_error",
    }
    if any(value[key] != expected_value for key, expected_value in expected.items()):
        raise OmniProbePreflightError("C4 condition specification is unsupported")
    managed_identity = _required_identifier(
        value["managed_llm_identity"], "managed LLM identity"
    )
    if managed_identity != "managed-unobservable":
        raise OmniProbePreflightError(
            "C4 managed LLM identity must remain unobservable"
        )
    maximum_checks = value["maximum_status_checks"]
    if type(maximum_checks) is not int or not 1 <= maximum_checks <= 1000:
        raise OmniProbePreflightError("C4 maximum status checks are invalid")
    return C4ConditionSpec(
        managed_llm_identity=managed_identity,
        maximum_status_checks=maximum_checks,
        model_config_id=_required_identifier(
            value["model_config_id"], "model configuration identifier"
        ),
        omni_cli_sha256=_required_sha256(value["omni_cli_sha256"]),
        omni_cli_version=_required_identifier(
            value["omni_cli_version"], "Omni CLI version"
        ),
        poll_schedule_seconds=_poll_schedule(value["poll_schedule_seconds"]),
        provider=_required_identifier(value["provider"], "provider"),
    )


def _validate_prompt(prompt: CommittedSpec) -> str:
    try:
        text = prompt.content.decode("utf-8")
    except UnicodeError as error:
        raise OmniProbePreflightError("prompt specification must be UTF-8") from error
    if text != "{question}\n":
        raise OmniProbePreflightError(
            "prompt specification must contain only the public question template"
        )
    return prompt.sha256


def _validate_instructions(instructions: CommittedSpec) -> str:
    value = _json_object(instructions.content, "instruction specification")
    if set(value) != INSTRUCTION_FIELDS:
        raise OmniProbePreflightError(
            "instruction specification must use the exact schema"
        )
    expected = {
        "adapter_instruction": ADAPTER_INSTRUCTION,
        "managed_agent_instructions": "not_exposed_by_omni",
        "question_specific_hidden_annotations": False,
        "runtime_oracle_context": False,
    }
    if value != expected:
        raise OmniProbePreflightError("instruction specification is unsupported")
    return instructions.sha256


def _confined_path(path: Path) -> Path:
    relative = Path(path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise OmniProbePreflightError(
            "run specification paths must be confined and relative"
        )
    return relative


def _read_regular_file(workspace: Path, relative: Path) -> bytes:
    full_path = workspace / relative
    try:
        metadata = full_path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise OmniProbePreflightError(
                "run specification worktree path must be a regular owned file"
            )
        descriptor = os.open(full_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as stream:
            content = stream.read(metadata.st_size + 1)
        if len(content) != metadata.st_size:
            raise OmniProbePreflightError(
                "run specification changed while it was being read"
            )
        return content
    except OSError as error:
        raise OmniProbePreflightError(
            "cannot read the run specification worktree file"
        ) from error


def _json_object(content: bytes, description: str) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OmniProbePreflightError(
            f"{description} must contain valid JSON"
        ) from error
    if not isinstance(value, dict):
        raise OmniProbePreflightError(f"{description} must contain a JSON object")
    return value


def _required_identifier(value: Any, description: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}", value) is None
    ):
        raise OmniProbePreflightError(f"C4 {description} is invalid")
    return value


def _required_sha256(value: Any) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise OmniProbePreflightError("C4 Omni CLI SHA-256 is invalid")
    return value


def _poll_schedule(value: Any) -> tuple[float, ...]:
    if not isinstance(value, list) or not value:
        raise OmniProbePreflightError("C4 poll schedule is invalid")
    schedule = tuple(float(item) for item in value if type(item) in {int, float})
    if len(schedule) != len(value) or any(
        not math.isfinite(item) or item <= 0 or item > 3600 for item in schedule
    ):
        raise OmniProbePreflightError("C4 poll schedule is invalid")
    return schedule

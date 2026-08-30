"""Load a committed Freeze-B control record without changing the frozen system."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .freeze_b import FreezeBError, FreezeBManifest
from .freeze_b_record import (
    MAX_RUNTIME_SOURCE_BYTES,
    FreezeBRecordError,
    _committed_input,
    _current_exact_commit,
    _git_bytes,
    _git_text,
    _relative_path,
    _repository_root,
    _runtime_source_bytes,
    _verify_runtime_sources,
)

MAX_FREEZE_B_BYTES = 1024 * 1024

_COMMIT = re.compile(r"[0-9a-f]{40}")


class FreezeBControlError(RuntimeError):
    """Raised when the post-freeze control commit changes the frozen system."""


@dataclass(frozen=True)
class FreezeBControl:
    """One canonical Freeze B added by an otherwise empty control commit."""

    manifest: FreezeBManifest
    manifest_path: str
    control_commit: str
    system_commit: str
    freeze_b_sha256: str
    frozen_file_count: int


def load_freeze_b_control(
    workspace: Path,
    *,
    control_commit: str,
    system_commit: str,
    manifest_path: Path,
) -> FreezeBControl:
    """Verify F is a direct child of S that adds only one canonical freeze record."""
    try:
        root = _repository_root(workspace)
        control = _current_exact_commit(root, control_commit)
        system = _exact_commit(root, system_commit, "system commit")
        relative_manifest = _relative_path(manifest_path, "Freeze B manifest path")
        _direct_control_parent(root, control, system)
        _only_manifest_added(root, system, control, relative_manifest)
        _require_regular_non_executable_blob(root, control, relative_manifest)
        committed = _committed_input(
            root,
            control,
            relative_manifest,
            maximum_bytes=MAX_FREEZE_B_BYTES,
        )
        _verify_runtime_sources(root, system)
        _verify_control_runtime_source(root, system)
    except FreezeBRecordError as error:
        raise FreezeBControlError(str(error)) from error
    manifest = _parse_manifest(committed.content)
    if manifest.system_commit != system or manifest.scorer_source_commit != system:
        raise FreezeBControlError(
            "Freeze B recorded system commit does not match the frozen parent"
        )
    return FreezeBControl(
        manifest=manifest,
        manifest_path=relative_manifest,
        control_commit=control,
        system_commit=system,
        freeze_b_sha256=manifest.sha256(),
        frozen_file_count=len(manifest.frozen_files),
    )


def load_archived_freeze_b_control(
    workspace: Path,
    *,
    control_commit: str,
    system_commit: str,
    manifest_path: Path,
) -> FreezeBControl:
    """Authenticate an earlier control record as immutable generation provenance.

    Unlike ``load_freeze_b_control``, this data-only loader does not require the
    archived control to equal HEAD or the currently imported runtime sources to
    match its parent. The active scoring control performs those checks against
    the current system separately.
    """
    try:
        root = _repository_root(workspace)
        control = _exact_commit(root, control_commit, "archived control commit")
        system = _exact_commit(root, system_commit, "archived system commit")
        relative_manifest = _relative_path(manifest_path, "Freeze B manifest path")
        _direct_control_parent(root, control, system)
        _only_manifest_added(root, system, control, relative_manifest)
        _require_regular_non_executable_blob(root, control, relative_manifest)
        committed = _committed_input(
            root,
            control,
            relative_manifest,
            maximum_bytes=MAX_FREEZE_B_BYTES,
        )
    except FreezeBRecordError as error:
        raise FreezeBControlError(str(error)) from error
    manifest = _parse_manifest(committed.content)
    if manifest.system_commit != system or manifest.scorer_source_commit != system:
        raise FreezeBControlError(
            "Freeze B recorded system commit does not match the archived parent"
        )
    return FreezeBControl(
        manifest=manifest,
        manifest_path=relative_manifest,
        control_commit=control,
        system_commit=system,
        freeze_b_sha256=manifest.sha256(),
        frozen_file_count=len(manifest.frozen_files),
    )


def _exact_commit(workspace: Path, supplied: object, description: str) -> str:
    if not isinstance(supplied, str) or _COMMIT.fullmatch(supplied) is None:
        raise FreezeBControlError(f"{description} must be a full lowercase commit hash")
    try:
        resolved = _git_text(workspace, "rev-parse", f"{supplied}^{{commit}}")
    except FreezeBRecordError as error:
        raise FreezeBControlError(f"{description} is unavailable") from error
    if resolved != supplied:
        raise FreezeBControlError(f"{description} is not canonical")
    return supplied


def _direct_control_parent(workspace: Path, control: str, system: str) -> None:
    parents = _git_text(workspace, "rev-list", "--parents", "-n", "1", control).split()
    if parents != [control, system]:
        raise FreezeBControlError(
            "control commit must be a direct child of the frozen system and not a merge"
        )


def _only_manifest_added(
    workspace: Path, system: str, control: str, manifest_path: str
) -> None:
    changed = _git_bytes(
        workspace,
        "diff",
        "--name-status",
        "-z",
        "--no-renames",
        system,
        control,
        "--",
    )
    expected = b"A\0" + manifest_path.encode("utf-8") + b"\0"
    if changed != expected:
        raise FreezeBControlError("control commit must add only the Freeze B manifest")


def _require_regular_non_executable_blob(
    workspace: Path, commit: str, manifest_path: str
) -> None:
    entry = _git_bytes(workspace, "ls-tree", "-z", commit, "--", manifest_path)
    if (
        not entry.startswith(b"100644 blob ")
        or not entry.endswith(b"\0")
        or entry.count(b"\0") != 1
    ):
        raise FreezeBControlError(
            "Freeze B manifest must be a non-executable regular Git blob"
        )


def _verify_control_runtime_source(workspace: Path, system: str) -> None:
    committed = _committed_input(
        workspace,
        system,
        "src/omni_benchmark/freeze_b_control.py",
        maximum_bytes=MAX_RUNTIME_SOURCE_BYTES,
    )
    loaded = hashlib.sha256(_runtime_source_bytes(Path(__file__))).hexdigest()
    if loaded != committed.sha256:
        raise FreezeBControlError(
            "Freeze B control runtime source does not match the frozen system"
        )


def _parse_manifest(content: bytes) -> FreezeBManifest:
    try:
        value = json.loads(content)
        manifest = FreezeBManifest.from_dict(value)
    except (UnicodeDecodeError, json.JSONDecodeError, FreezeBError) as error:
        raise FreezeBControlError("committed Freeze B manifest is invalid") from error
    if manifest.canonical_bytes() != content:
        raise FreezeBControlError("committed Freeze B manifest must be canonical")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the post-freeze control commit without execution"
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--control-commit", required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser


def control_main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = load_freeze_b_control(
        arguments.workspace,
        control_commit=arguments.control_commit,
        system_commit=arguments.system_commit,
        manifest_path=arguments.manifest,
    )
    print(
        json.dumps(
            {
                "control_commit": result.control_commit,
                "freeze_b_sha256": result.freeze_b_sha256,
                "frozen_file_count": result.frozen_file_count,
                "system_commit": result.system_commit,
            },
            sort_keys=True,
        )
    )
    return 0

"""Authenticate archived Freeze-B controls used only for generation provenance."""

from __future__ import annotations

from pathlib import Path

from .freeze_b_control import (
    MAX_FREEZE_B_BYTES,
    FreezeBControl,
    FreezeBControlError,
    _direct_control_parent,
    _exact_commit,
    _only_manifest_added,
    _parse_manifest,
    _require_regular_non_executable_blob,
)
from .freeze_b_record import (
    FreezeBRecordError,
    _committed_input,
    _relative_path,
    _repository_root,
)


def load_archived_freeze_b_control(
    workspace: Path,
    *,
    control_commit: str,
    system_commit: str,
    manifest_path: Path,
) -> FreezeBControl:
    """Authenticate an earlier control record as immutable generation provenance.

    This data-only loader does not require the archived control to equal HEAD or
    the currently imported runtime sources to match its parent. The active
    scoring control performs those checks against the current system separately.
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

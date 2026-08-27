"""Binding between generation records and immutable run provenance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .autoresearch_config import AutoresearchError
from .run_manifest import RunManifestError, read_bound_run_manifest


@dataclass(frozen=True)
class ValidatedManifestBinding:
    """Private path and digest of a generation-bound run manifest."""

    path: Path
    sha256: str


def validate_manifest_binding(
    *,
    workspace: Path,
    records: Sequence[Mapping[str, Any]],
    generation_sha256: str,
    condition: str,
    scope: str,
    repetition: int,
    manifest_path: Path | None,
    expected_manifest_sha256: str | None,
    required: bool,
) -> ValidatedManifestBinding | None:
    """Require a complete pair and cross-check it against validated records."""
    if manifest_path is None or expected_manifest_sha256 is None:
        if manifest_path is not None or expected_manifest_sha256 is not None:
            raise AutoresearchError(
                "run manifest path and hash must be supplied together"
            )
        if required:
            raise AutoresearchError(
                "run manifest path and hash are required by protocol"
            )
        return None
    provider, model = _unique_model_identity(records)
    started_at = _extreme_timestamp(records, "started_at", minimum=True)
    finished_at = _extreme_timestamp(records, "finished_at", minimum=False)
    relative_path = _relative_manifest_path(workspace, manifest_path)
    try:
        read_bound_run_manifest(
            workspace,
            relative_path,
            expected_sha256=expected_manifest_sha256,
            generation_sha256=generation_sha256,
            condition=condition,
            scope=scope,
            repetition=repetition,
            provider=provider,
            model=model,
            started_at=started_at,
            finished_at=finished_at,
        )
    except RunManifestError as error:
        raise AutoresearchError(str(error)) from error
    return ValidatedManifestBinding(
        path=workspace / relative_path,
        sha256=expected_manifest_sha256,
    )


def _unique_model_identity(records: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    identities = {
        (record["model"]["provider"], record["model"]["name"]) for record in records
    }
    if len(identities) != 1 or None in next(iter(identities)):
        raise AutoresearchError(
            "run manifest requires one observable provider and model identity"
        )
    provider, model = next(iter(identities))
    return provider, model


def _extreme_timestamp(
    records: Sequence[Mapping[str, Any]], field: str, *, minimum: bool
) -> str:
    pairs = [
        (datetime.fromisoformat(record[field].replace("Z", "+00:00")), record[field])
        for record in records
    ]
    return (min if minimum else max)(pairs, key=lambda pair: pair[0])[1]


def _relative_manifest_path(workspace: Path, path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate
    try:
        return candidate.relative_to(workspace.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise AutoresearchError(
            "run manifest path must resolve inside workspace"
        ) from error

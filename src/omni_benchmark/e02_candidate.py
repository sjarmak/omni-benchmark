"""Reproduce the public E02 deployment candidate from one exact Git tree."""

from __future__ import annotations

import hashlib
import io
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from .omni_semantic_deployment import (
    OmniSemanticDeploymentPlan,
    build_semantic_deployment_plan,
)
from .semantic_bundle_publication import (
    SemanticBundlePublicationError,
    publish_c5_bundle_artifacts,
    publish_e02_bundle_artifacts,
)

BundlePublisher = Callable[[Path, Path, Path, Path, Path, Path], Mapping[str, object]]

_COMMIT_LENGTH = 40
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_MAX_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024
_ARCHIVE_PATHS = (
    "config/archeology_scan_public_bundle.json",
    "semantic_models/public_ir",
    "semantic_models/public_schema_ir",
    "semantic_models/public_mapping",
    "semantic_models/public_baseline",
)


class E02CandidateError(ValueError):
    """Raised when the exact committed E02 candidate cannot be reproduced."""


@dataclass(frozen=True, slots=True)
class E02CommittedCandidate:
    """Authenticated E02 plans and their aggregate public identity."""

    candidate_set_sha256: str
    plans: Mapping[str, OmniSemanticDeploymentPlan]
    relationship_count: int
    source_commit: str


def load_committed_c5_candidate(
    workspace: Path, source_commit: str
) -> E02CommittedCandidate:
    """Compile and authenticate all C5 tuned bundles from an exact committed tree."""
    return load_committed_e02_candidate(
        workspace, source_commit, publisher=publish_c5_bundle_artifacts
    )


def load_committed_c5_plan(
    workspace: Path, source_commit: str, database: str
) -> OmniSemanticDeploymentPlan:
    """Compile one C5 bundle from the committed tree that carries all eighteen.

    One attempt only ever verifies its own database, and compiling the other
    seventeen tuned bundles costs about a minute of every attempt's wall clock.
    """
    candidate = load_committed_e02_candidate(
        workspace,
        source_commit,
        publisher=publish_c5_bundle_artifacts,
        databases=(database,),
    )
    return candidate.plans[database]


def load_committed_e02_candidate(
    workspace: Path,
    source_commit: str,
    *,
    publisher: BundlePublisher = publish_e02_bundle_artifacts,
    databases: Sequence[str] | None = None,
) -> E02CommittedCandidate:
    """Compile and authenticate committed bundles from an exact committed tree.

    The committed tree must always carry the full eighteen-database candidate.
    ``databases`` narrows only what is compiled, so the returned candidate set
    digest then covers that subset rather than the whole candidate.
    """
    selected = None if databases is None else frozenset(databases)
    root = _git_root(workspace)
    commit = _canonical_commit(root, source_commit)
    archive = _git_archive(root, commit)
    try:
        with tempfile.TemporaryDirectory(prefix="omni-e02-committed-") as directory:
            snapshot = Path(directory) / "snapshot"
            output = Path(directory) / "candidate"
            snapshot.mkdir(mode=0o700)
            output.mkdir(mode=0o700)
            _extract_archive(archive, snapshot)
            plans, manifest_hashes, relationship_count = _compile(
                snapshot, output, publisher, selected
            )
    except (OSError, tarfile.TarError, SemanticBundlePublicationError) as error:
        raise E02CandidateError("committed E02 candidate is invalid") from error
    candidate_bytes = ("\n".join(sorted(manifest_hashes)) + "\n").encode()
    return E02CommittedCandidate(
        candidate_set_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        plans=MappingProxyType(plans),
        relationship_count=relationship_count,
        source_commit=commit,
    )


def _git_root(workspace: Path) -> Path:
    try:
        root = Path(workspace).resolve(strict=True)
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise E02CandidateError("workspace must be a Git repository") from error
    if Path(completed.stdout.strip()).resolve() != root:
        raise E02CandidateError("workspace must be the Git repository root")
    return root


def _canonical_commit(workspace: Path, value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _COMMIT_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise E02CandidateError("source commit must be canonical")
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", f"{value}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise E02CandidateError("source commit is unavailable") from error
    if completed.stdout.strip() != value:
        raise E02CandidateError("source commit is not exact")
    return value


def _git_archive(workspace: Path, commit: str) -> bytes:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "archive",
                "--format=tar",
                commit,
                "--",
                *_ARCHIVE_PATHS,
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise E02CandidateError("committed E02 inputs are unavailable") from error
    if not completed.stdout or len(completed.stdout) > _MAX_ARCHIVE_BYTES:
        raise E02CandidateError("committed E02 input archive is invalid")
    return completed.stdout


def _extract_archive(content: bytes, destination: Path) -> None:
    total = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:") as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            if (
                not relative.parts
                or relative.is_absolute()
                or ".." in relative.parts
                or not (member.isdir() or member.isfile())
                or member.size < 0
                or member.size > _MAX_ARCHIVE_MEMBER_BYTES
            ):
                raise E02CandidateError("committed E02 archive is unsafe")
            total += member.size
            if total > _MAX_ARCHIVE_BYTES:
                raise E02CandidateError("committed E02 archive is too large")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise E02CandidateError("committed E02 archive is malformed")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())


def _artifact_sets(
    workspace: Path,
) -> tuple[tuple[str, Path, Path, Path, Path, Path], ...]:
    sets = [
        (
            "archeology_scan_large",
            workspace / "config/archeology_scan_public_bundle.json",
            workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl",
            workspace
            / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl",
            workspace
            / "semantic_models/public_mapping/archeology_scan_large.mapping.jsonl",
            workspace / "semantic_models/public_mapping/manifest.json",
        )
    ]
    baseline = workspace / "semantic_models/public_baseline"
    try:
        roots = sorted(path for path in baseline.iterdir() if path.is_dir())
    except OSError as error:
        raise E02CandidateError(
            "committed E02 baseline inputs are unavailable"
        ) from error
    for root in roots:
        database = root.name
        sets.append(
            (
                database,
                root / "bundle.spec.json",
                workspace / "semantic_models/public_ir" / f"{database}.hkb.jsonl",
                root / "schema_ir" / f"{database}.schema.jsonl",
                root / "mapping" / f"{database}.mapping.jsonl",
                root / "mapping/manifest.json",
            )
        )
    if len(sets) != 18 or len({item[0] for item in sets}) != 18:
        raise E02CandidateError("E02 candidate must contain exactly 18 databases")
    return tuple(sets)


def _compile(
    workspace: Path,
    output_root: Path,
    publisher: BundlePublisher,
    selected: frozenset[str] | None,
) -> tuple[dict[str, OmniSemanticDeploymentPlan], list[str], int]:
    artifact_sets = _artifact_sets(workspace)
    if selected is not None:
        unknown = sorted(selected - {item[0] for item in artifact_sets})
        if unknown:
            raise E02CandidateError("selected database is not in the candidate")
        artifact_sets = tuple(item for item in artifact_sets if item[0] in selected)
    plans: dict[str, OmniSemanticDeploymentPlan] = {}
    manifest_hashes: list[str] = []
    relationship_count = 0
    for database, spec, hkb, schema, mapping, mapping_manifest in artifact_sets:
        output = output_root / database
        manifest = publisher(spec, hkb, schema, mapping, mapping_manifest, output)
        plan = build_semantic_deployment_plan(output)
        if plan.database != database:
            raise E02CandidateError("E02 plan database does not match its input")
        relationships = manifest.get("relationship_contracts")
        if not isinstance(relationships, list):
            raise E02CandidateError("E02 relationship inventory is invalid")
        plans[database] = plan
        manifest_hashes.append(
            hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
        )
        relationship_count += len(relationships)
    return plans, manifest_hashes, relationship_count

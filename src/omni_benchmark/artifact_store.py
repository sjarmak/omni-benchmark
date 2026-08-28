"""Small secure store for ignored per-attempt traces and result sidecars."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .autoresearch_config import AutoresearchError, _write_exclusive
from .content_policy import ContentPolicy

ALLOWED_RAW_ROOTS = (
    Path("runs"),
    Path("experiments/runs"),
    Path("experiments/autoresearch/raw"),
)
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024


class ArtifactStoreError(RuntimeError):
    """Raised when a raw artifact cannot be stored without weakening custody."""


@dataclass(frozen=True)
class StoredArtifact:
    """Hash-bound reference to one immutable private artifact."""

    path: Path
    sha256: str
    size_bytes: int


class ArtifactStore:
    """Write exclusive mode-0600 artifacts below one ignored mode-0700 root."""

    def __init__(
        self,
        workspace: Path,
        root: Path,
        *,
        environment: Mapping[str, str] | None = None,
        require_new_root: bool = False,
    ) -> None:
        self._workspace = workspace.resolve(strict=True)
        self._root = _validate_relative(root, "artifact root")
        if not any(
            self._root.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS
        ):
            raise ArtifactStoreError("artifact root must be a gitignored raw-run path")
        if not _is_gitignored(self._workspace, self._root):
            raise ArtifactStoreError("artifact root must be gitignored")
        self._content_policy = ContentPolicy.from_environment(
            os.environ if environment is None else environment
        )
        if require_new_root:
            _secure_new_directory(self._workspace, self._root)
        else:
            _secure_directory(self._workspace, self._root)

    @property
    def root_identity(self) -> str:
        """Return an opaque identity for this exact workspace/root pair."""
        value = f"{self._workspace}\0{self._root.as_posix()}".encode()
        return hashlib.sha256(value).hexdigest()

    def relative_path(self, artifact: StoredArtifact) -> Path:
        """Return a workspace-relative path only for an artifact under this root."""
        try:
            resolved = artifact.path.resolve(strict=True)
            relative = resolved.relative_to(self._workspace / self._root)
        except (OSError, ValueError) as error:
            raise ArtifactStoreError(
                "artifact does not belong to this store root"
            ) from error
        return self._root / relative

    def root_relative_path(self, artifact: StoredArtifact) -> Path:
        """Return a path relative to the exact artifact root."""
        workspace_relative = self.relative_path(artifact)
        return workspace_relative.relative_to(self._root)

    def require_workspace(self, workspace: Path) -> None:
        """Reject publishers configured for a different workspace."""
        try:
            resolved = workspace.resolve(strict=True)
        except OSError as error:
            raise ArtifactStoreError("artifact workspace is unavailable") from error
        if resolved != self._workspace:
            raise ArtifactStoreError("artifact store and publisher workspace differ")

    def write_json(self, relative_path: Path, value: Any) -> StoredArtifact:
        """Write canonical JSON only when it contains no sensitive material."""
        if self._content_policy.sanitize_json(value) != value:
            raise ArtifactStoreError("artifact contains sensitive content")
        return self.write_bytes(relative_path, _strict_canonical_bytes(value))

    def write_jsonl(
        self, relative_path: Path, records: list[dict[str, Any]]
    ) -> StoredArtifact:
        """Write canonical ordered JSONL with the same content policy."""
        if self._content_policy.sanitize_json(records) != records:
            raise ArtifactStoreError("artifact contains sensitive content")
        content = b"".join(_strict_canonical_bytes(record) for record in records)
        return self.write_bytes(relative_path, content)

    def write_bytes(self, relative_path: Path, content: bytes) -> StoredArtifact:
        """Write once under the store root and verify its final file metadata."""
        destination = _validate_relative(relative_path, "artifact path")
        if not content or len(content) > MAX_ARTIFACT_BYTES:
            raise ArtifactStoreError("artifact has an invalid byte size")
        if not self._content_policy.bytes_are_safe(content):
            raise ArtifactStoreError("artifact contains sensitive content")
        _secure_directory(self._workspace, self._root / destination.parent)
        full_path = self._workspace / self._root / destination
        try:
            stored_path = _write_exclusive(
                full_path, content, workspace=self._workspace
            )
        except AutoresearchError as error:
            raise ArtifactStoreError(str(error)) from error
        metadata = stored_path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
        ):
            raise ArtifactStoreError("stored artifact failed private-file verification")
        return StoredArtifact(
            path=stored_path,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )


def _strict_canonical_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ArtifactStoreError("artifact must contain finite JSON") from error
    return (encoded + "\n").encode()


def _validate_relative(path: Path, description: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        raise ArtifactStoreError(f"{description} must be a confined relative path")
    return candidate


def _is_gitignored(workspace: Path, relative_path: Path) -> bool:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "check-ignore",
            "--no-index",
            "--quiet",
            "--",
            relative_path.as_posix(),
        ],
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    patterns = (workspace / ".gitignore").read_text(encoding="utf-8").splitlines()
    return any(
        pattern.rstrip("/") == root.as_posix()
        for pattern in patterns
        for root in ALLOWED_RAW_ROOTS
        if relative_path.is_relative_to(root)
    )


def _secure_directory(workspace: Path, relative_path: Path) -> None:
    descriptor = os.open(
        workspace,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        for part in relative_path.parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            next_descriptor = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
            metadata = os.fstat(descriptor)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
                raise ArtifactStoreError("secure artifact directory is invalid")
            os.fchmod(descriptor, 0o700)
    except (OSError, ValueError) as error:
        raise ArtifactStoreError("cannot create secure artifact directory") from error
    finally:
        os.close(descriptor)


def _secure_new_directory(workspace: Path, relative_path: Path) -> None:
    """Create the final directory atomically and reject any prior occupant."""
    parent = relative_path.parent
    if parent != Path("."):
        _secure_directory(workspace, parent)
    descriptor = os.open(
        workspace / parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        try:
            os.mkdir(relative_path.name, mode=0o700, dir_fd=descriptor)
        except FileExistsError as error:
            raise ArtifactStoreError("artifact root must not already exist") from error
        child = os.open(
            relative_path.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=descriptor,
        )
        try:
            metadata = os.fstat(child)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or metadata.st_uid != os.getuid()
            ):
                raise ArtifactStoreError("secure artifact directory is invalid")
        finally:
            os.close(child)
    except (OSError, ValueError) as error:
        raise ArtifactStoreError("cannot create secure artifact directory") from error
    finally:
        os.close(descriptor)

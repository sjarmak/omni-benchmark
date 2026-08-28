"""Content-safe identities for filesystem resources visible to Claude Code.

The pinned CLI is treated as non-adversarial: private read-only snapshots prevent
ordinary source-path races, while persistent source or snapshot drift is detected.
A malicious same-UID runner could deliberately chmod and restore its snapshot; that
stronger boundary requires an OS namespace or LSM and is intentionally not claimed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ClaudeResourceIdentityError(ValueError):
    """Raised when an execution resource cannot be identified safely."""


class _Digest(Protocol):
    def update(self, data: bytes) -> object: ...


@dataclass(frozen=True)
class ClaudeDirectoryIdentity:
    """Opaque identity for one pinned directory and, when relevant, its contents."""

    content_sha256: str | None
    device: int
    inode: int
    mode: int

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            "content_sha256": self.content_sha256,
            "device": self.device,
            "inode": self.inode,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class ClaudeResourceIdentity:
    """Exact non-secret identity of filesystem inputs to one Claude invocation."""

    config: ClaudeDirectoryIdentity
    home: ClaudeDirectoryIdentity
    temporary: ClaudeDirectoryIdentity
    working: ClaudeDirectoryIdentity

    def as_dict(self) -> dict[str, dict[str, int | str | None]]:
        return {
            "config": self.config.as_dict(),
            "home": self.home.as_dict(),
            "temporary": self.temporary.as_dict(),
            "working": self.working.as_dict(),
        }

    def sha256(self) -> str:
        serialized = json.dumps(
            self.as_dict(), allow_nan=False, separators=(",", ":"), sort_keys=True
        )
        return hashlib.sha256(serialized.encode()).hexdigest()


@dataclass(frozen=True)
class PinnedClaudeResources:
    """Open resource descriptors and their verified invocation identity."""

    binary_fd: int
    binary_sha256: str
    config_fd: int
    home_fd: int
    identity: ClaudeResourceIdentity
    execution_identity: ClaudeResourceIdentity
    snapshot_root: Path
    source_config_fd: int
    source_home_fd: int
    source_work_fd: int
    temp_fd: int
    work_fd: int

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return (
            self.binary_fd,
            self.config_fd,
            self.home_fd,
            self.temp_fd,
            self.work_fd,
        )

    def current_identity(self) -> ClaudeResourceIdentity:
        """Re-identify source roots without following their original paths."""
        return identify_claude_resources(
            config_fd=self.source_config_fd,
            home_fd=self.source_home_fd,
            temp_fd=self.temp_fd,
            work_fd=self.source_work_fd,
        )

    def current_execution_identity(self) -> ClaudeResourceIdentity:
        """Re-identify the private materialization consumed by Claude."""
        return identify_claude_resources(
            config_fd=self.config_fd,
            home_fd=self.home_fd,
            temp_fd=self.temp_fd,
            work_fd=self.work_fd,
        )

    def source_matches(self, expected: ClaudeResourceIdentity) -> bool:
        """Return whether pinned sources still match the reviewed identity."""
        try:
            return (
                type(expected) is ClaudeResourceIdentity
                and self.current_identity() == expected
            )
        except (ClaudeResourceIdentityError, OSError):
            return False

    def verify_unchanged(self) -> None:
        """Reject drift in either original inputs or provider-visible snapshots."""
        try:
            source_matches = self.current_identity() == self.identity
            execution_matches = (
                self.current_execution_identity() == self.execution_identity
            )
        except (ClaudeResourceIdentityError, OSError):
            source_matches = execution_matches = False
        if not source_matches or not execution_matches:
            raise ClaudeResourceIdentityError(
                "Claude execution resources changed during invocation"
            )

    def close(self) -> None:
        descriptors = (
            *self.pass_fds,
            self.source_config_fd,
            self.source_home_fd,
            self.source_work_fd,
        )
        for descriptor in dict.fromkeys(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        _remove_execution_snapshot(self.snapshot_root)


def validate_private_directory(path: Path, label: str) -> None:
    """Require an existing root directory inaccessible to group and other users."""
    try:
        metadata = path.lstat()
    except OSError:
        raise ClaudeResourceIdentityError(f"{label} is unavailable") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ClaudeResourceIdentityError(f"{label} must be a real directory")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ClaudeResourceIdentityError(f"{label} must be private (0700)")


def current_claude_resource_identity(
    *,
    config_directory: Path,
    runtime_home: Path,
    temp_directory: Path,
    working_directory: Path,
) -> ClaudeResourceIdentity:
    """Identify the directory objects currently reachable through reviewed paths."""
    descriptors: list[int] = []
    try:
        for path in (
            config_directory,
            runtime_home,
            temp_directory,
            working_directory,
        ):
            descriptors.append(_open_private_directory(path))
        return identify_claude_resources(
            config_fd=descriptors[0],
            home_fd=descriptors[1],
            temp_fd=descriptors[2],
            work_fd=descriptors[3],
        )
    except (ClaudeResourceIdentityError, OSError):
        raise ClaudeResourceIdentityError(
            "Claude execution resources are unavailable or unsafe"
        ) from None
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def pin_claude_resources(
    *,
    binary_path: Path,
    expected_binary_sha256: str,
    config_directory: Path,
    runtime_home: Path,
    temp_directory: Path,
    working_directory: Path,
) -> PinnedClaudeResources:
    """Open and verify every execution resource before provider invocation."""
    paths = (config_directory, runtime_home, temp_directory, working_directory)
    return _pin_claude_resources(binary_path, expected_binary_sha256, paths)


def _pin_claude_resources(
    binary_path: Path,
    expected_binary_sha256: str,
    paths: tuple[Path, Path, Path, Path],
) -> PinnedClaudeResources:
    descriptors: list[int] = []
    try:
        binary_fd = open_claude_binary(binary_path)
        descriptors.append(binary_fd)
        observed = claude_binary_sha256(binary_fd)
        if observed != expected_binary_sha256:
            raise ClaudeResourceIdentityError("pinned Claude binary SHA mismatch")
        directory_fds = _open_source_directories(descriptors, paths)
        identity = identify_claude_resources(
            config_fd=directory_fds[0],
            home_fd=directory_fds[1],
            temp_fd=directory_fds[2],
            work_fd=directory_fds[3],
        )
        snapshot_root, execution_fds, execution_identity = _execution_snapshot(
            config_fd=directory_fds[0],
            home_fd=directory_fds[1],
            temp_fd=directory_fds[2],
            work_fd=directory_fds[3],
            source_identity=identity,
        )
    except ClaudeResourceIdentityError:
        _close_descriptors(descriptors)
        raise
    except OSError:
        _close_descriptors(descriptors)
        raise ClaudeResourceIdentityError(
            "Claude execution resources are unavailable or unsafe"
        ) from None
    return _pinned_resources(
        binary_fd,
        observed,
        directory_fds,
        identity,
        snapshot_root,
        execution_fds,
        execution_identity,
    )


def _open_source_directories(
    descriptors: list[int], paths: tuple[Path, Path, Path, Path]
) -> tuple[int, int, int, int]:
    opened: list[int] = []
    for path in paths:
        descriptor = _open_private_directory(path)
        opened.append(descriptor)
        descriptors.append(descriptor)
    return opened[0], opened[1], opened[2], opened[3]


def _pinned_resources(
    binary_fd: int,
    binary_sha256: str,
    directory_fds: tuple[int, ...],
    identity: ClaudeResourceIdentity,
    snapshot_root: Path,
    execution_fds: tuple[int, int, int],
    execution_identity: ClaudeResourceIdentity,
) -> PinnedClaudeResources:
    return PinnedClaudeResources(
        binary_fd=binary_fd,
        binary_sha256=binary_sha256,
        config_fd=execution_fds[0],
        home_fd=execution_fds[1],
        identity=identity,
        execution_identity=execution_identity,
        snapshot_root=snapshot_root,
        source_config_fd=directory_fds[0],
        source_home_fd=directory_fds[1],
        source_work_fd=directory_fds[3],
        temp_fd=directory_fds[2],
        work_fd=execution_fds[2],
    )


def _close_descriptors(descriptors: list[int]) -> None:
    for descriptor in descriptors:
        os.close(descriptor)


def _execution_snapshot(
    *,
    config_fd: int,
    home_fd: int,
    temp_fd: int,
    work_fd: int,
    source_identity: ClaudeResourceIdentity,
) -> tuple[Path, tuple[int, int, int], ClaudeResourceIdentity]:
    """Materialize immutable invocation inputs for a non-adversarial provider process."""
    root = Path(tempfile.mkdtemp(prefix="omni-claude-execution-"))
    execution_fds: list[int] = []
    try:
        for name, source_fd in (
            ("config", config_fd),
            ("home", home_fd),
            ("work", work_fd),
        ):
            execution_fds.append(_snapshot_tree(root, name, source_fd))
        _verify_snapshot_sources(source_identity, config_fd, home_fd, temp_fd, work_fd)
        os.chmod(root, 0o500)
        frozen = tuple(execution_fds)
        identity = identify_claude_resources(
            config_fd=frozen[0],
            home_fd=frozen[1],
            temp_fd=temp_fd,
            work_fd=frozen[2],
        )
        return root, frozen, identity
    except (ClaudeResourceIdentityError, OSError):
        _close_descriptors(execution_fds)
        _remove_execution_snapshot(root)
        raise ClaudeResourceIdentityError(
            "Claude execution snapshot could not be materialized safely"
        ) from None


def _snapshot_tree(root: Path, name: str, source_fd: int) -> int:
    before = _portable_directory_digest(source_fd)
    destination = root / name
    destination.mkdir(mode=0o700)
    destination_fd = _open_private_directory(destination)
    try:
        _copy_tree(source_fd, destination_fd)
        after = _portable_directory_digest(source_fd)
        copied = _portable_directory_digest(destination_fd)
        if before != after or copied != before:
            raise ClaudeResourceIdentityError(
                "execution resource changed while it was materialized"
            )
        _freeze_tree(destination_fd)
        return destination_fd
    except Exception:
        os.close(destination_fd)
        raise


def _verify_snapshot_sources(
    expected: ClaudeResourceIdentity,
    config_fd: int,
    home_fd: int,
    temp_fd: int,
    work_fd: int,
) -> None:
    observed = identify_claude_resources(
        config_fd=config_fd,
        home_fd=home_fd,
        temp_fd=temp_fd,
        work_fd=work_fd,
    )
    if observed != expected:
        raise ClaudeResourceIdentityError(
            "execution resource changed while it was materialized"
        )


def _copy_tree(source_fd: int, destination_fd: int) -> None:
    names = _directory_names(source_fd)
    for name in names:
        metadata = os.stat(name, dir_fd=source_fd, follow_symlinks=False)
        encoded_name = os.fsencode(name)
        if stat.S_ISREG(metadata.st_mode):
            _copy_regular_file(source_fd, destination_fd, encoded_name, metadata)
        elif stat.S_ISDIR(metadata.st_mode):
            _copy_child_directory(source_fd, destination_fd, encoded_name, metadata)
        else:
            raise ClaudeResourceIdentityError(
                "execution resource contains a non-regular entry"
            )
    if names != _directory_names(source_fd):
        raise ClaudeResourceIdentityError(
            "execution resource changed while it was materialized"
        )


def _copy_regular_file(
    source_parent_fd: int,
    destination_parent_fd: int,
    name: bytes,
    expected: os.stat_result,
) -> None:
    source = os.open(
        name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=source_parent_fd
    )
    destination = -1
    try:
        before = os.fstat(source)
        _require_same_object(expected, before, require_directory=False)
        destination = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
            dir_fd=destination_parent_fd,
        )
        _copy_bytes(source, destination)
        if _change_signature(before) != _change_signature(os.fstat(source)):
            raise ClaudeResourceIdentityError(
                "execution resource changed while it was materialized"
            )
    finally:
        os.close(source)
        if destination >= 0:
            os.close(destination)


def _copy_bytes(source: int, destination: int) -> None:
    while chunk := os.read(source, 1024 * 1024):
        remaining = memoryview(chunk)
        while remaining:
            written = os.write(destination, remaining)
            if written <= 0:
                raise OSError("execution snapshot write failed")
            remaining = remaining[written:]


def _copy_child_directory(
    source_parent_fd: int,
    destination_parent_fd: int,
    name: bytes,
    expected: os.stat_result,
) -> None:
    os.mkdir(name, 0o700, dir_fd=destination_parent_fd)
    source = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
        dir_fd=source_parent_fd,
    )
    destination = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
        dir_fd=destination_parent_fd,
    )
    try:
        _require_same_object(expected, os.fstat(source), require_directory=True)
        _copy_tree(source, destination)
        _freeze_tree(destination)
    finally:
        os.close(source)
        os.close(destination)


def _freeze_tree(descriptor: int) -> None:
    for name in _directory_names(descriptor):
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISREG(metadata.st_mode):
            os.chmod(name, 0o400, dir_fd=descriptor, follow_symlinks=False)
        elif stat.S_ISDIR(metadata.st_mode):
            child = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
                dir_fd=descriptor,
            )
            try:
                _freeze_tree(child)
            finally:
                os.close(child)
        else:
            raise ClaudeResourceIdentityError(
                "execution snapshot contains a non-regular entry"
            )
    os.fchmod(descriptor, 0o500)


def _portable_directory_digest(descriptor: int) -> str:
    digest = hashlib.sha256()
    _hash_portable_tree(descriptor, digest)
    return digest.hexdigest()


def _hash_portable_tree(descriptor: int, digest: _Digest) -> None:
    names = _directory_names(descriptor)
    for name in names:
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        encoded_name = os.fsencode(name)
        if stat.S_ISREG(metadata.st_mode):
            content = _regular_file_content_sha256(descriptor, encoded_name, metadata)
            _update_portable_digest(digest, b"file", encoded_name, content)
        elif stat.S_ISDIR(metadata.st_mode):
            content = _child_portable_digest(descriptor, encoded_name, metadata)
            _update_portable_digest(digest, b"directory", encoded_name, content)
        else:
            raise ClaudeResourceIdentityError(
                "execution resource contains a non-regular entry"
            )
    if names != _directory_names(descriptor):
        raise ClaudeResourceIdentityError(
            "execution resource changed while it was inspected"
        )


def _regular_file_content_sha256(
    parent_fd: int, name: bytes, expected: os.stat_result
) -> str:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent_fd
    )
    try:
        before = os.fstat(descriptor)
        _require_same_object(expected, before, require_directory=False)
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        if _change_signature(before) != _change_signature(os.fstat(descriptor)):
            raise ClaudeResourceIdentityError(
                "execution resource changed while it was inspected"
            )
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _child_portable_digest(
    parent_fd: int, name: bytes, expected: os.stat_result
) -> str:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
        dir_fd=parent_fd,
    )
    try:
        _require_same_object(expected, os.fstat(descriptor), require_directory=True)
        return _portable_directory_digest(descriptor)
    finally:
        os.close(descriptor)


def _update_portable_digest(
    digest: _Digest, kind: bytes, name: bytes, content_sha256: str
) -> None:
    for value in (kind, name, content_sha256.encode()):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)


def _remove_execution_snapshot(root: Path) -> None:
    try:
        if root.exists():
            for directory, names, files in os.walk(root, topdown=True):
                os.chmod(directory, 0o700)
                for name in (*names, *files):
                    os.chmod(Path(directory, name), 0o700, follow_symlinks=False)
            shutil.rmtree(root)
    except OSError:
        raise ClaudeResourceIdentityError(
            "Claude execution snapshot cleanup failed"
        ) from None


def open_claude_binary(path: Path) -> int:
    """Open one non-symlink executable as a stable read-only descriptor."""
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
        os.close(descriptor)
        raise OSError("not an executable regular file")
    return descriptor


def claude_binary_sha256(descriptor: int) -> str:
    """Hash a pinned executable without retaining its bytes."""
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return digest.hexdigest()


def identify_claude_resources(
    *,
    config_fd: int,
    home_fd: int,
    temp_fd: int,
    work_fd: int,
) -> ClaudeResourceIdentity:
    """Hash input-bearing trees while recording every root directory object."""
    return ClaudeResourceIdentity(
        config=_identify_directory(config_fd, include_contents=True),
        home=_identify_directory(home_fd, include_contents=True),
        temporary=_identify_directory(temp_fd, include_contents=False),
        working=_identify_directory(work_fd, include_contents=True),
    )


def _identify_directory(
    descriptor: int, *, include_contents: bool
) -> ClaudeDirectoryIdentity:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ClaudeResourceIdentityError("execution resource is not a directory")
    content_sha256 = _directory_digest(descriptor) if include_contents else None
    return ClaudeDirectoryIdentity(
        content_sha256=content_sha256,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        mode=stat.S_IMODE(metadata.st_mode),
    )


def _directory_digest(descriptor: int) -> str:
    before = os.fstat(descriptor)
    digest = hashlib.sha256()
    _hash_tree(descriptor, digest)
    after = os.fstat(descriptor)
    if _change_signature(before) != _change_signature(after):
        raise ClaudeResourceIdentityError(
            "execution resource changed while it was inspected"
        )
    return digest.hexdigest()


def _hash_tree(descriptor: int, digest: _Digest) -> None:
    names = _directory_names(descriptor)
    for name in names:
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        encoded_name = os.fsencode(name)
        if stat.S_ISREG(metadata.st_mode):
            _hash_regular_file(descriptor, encoded_name, metadata, digest)
        elif stat.S_ISDIR(metadata.st_mode):
            _hash_child_directory(descriptor, encoded_name, metadata, digest)
        else:
            raise ClaudeResourceIdentityError(
                "execution resource contains a non-regular entry"
            )
    if names != _directory_names(descriptor):
        raise ClaudeResourceIdentityError(
            "execution resource changed while it was inspected"
        )


def _directory_names(descriptor: int) -> tuple[str, ...]:
    return tuple(sorted(os.listdir(descriptor), key=os.fsencode))


def _hash_regular_file(
    parent_fd: int,
    name: bytes,
    expected: os.stat_result,
    digest: _Digest,
) -> None:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        before = os.fstat(descriptor)
        _require_same_object(expected, before, require_directory=False)
        content = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            content.update(chunk)
        after = os.fstat(descriptor)
        if _change_signature(before) != _change_signature(after):
            raise ClaudeResourceIdentityError(
                "execution resource changed while it was inspected"
            )
        _update_entry_digest(digest, b"file", name, before, content.hexdigest())
    finally:
        os.close(descriptor)


def _hash_child_directory(
    parent_fd: int,
    name: bytes,
    expected: os.stat_result,
    digest: _Digest,
) -> None:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
        dir_fd=parent_fd,
    )
    try:
        observed = os.fstat(descriptor)
        _require_same_object(expected, observed, require_directory=True)
        child_digest = _directory_digest(descriptor)
        _update_entry_digest(digest, b"directory", name, observed, child_digest)
    finally:
        os.close(descriptor)


def _require_same_object(
    expected: os.stat_result,
    observed: os.stat_result,
    *,
    require_directory: bool,
) -> None:
    expected_type = (
        stat.S_ISDIR(expected.st_mode)
        if require_directory
        else stat.S_ISREG(expected.st_mode)
    )
    observed_type = (
        stat.S_ISDIR(observed.st_mode)
        if require_directory
        else stat.S_ISREG(observed.st_mode)
    )
    if (
        not expected_type
        or not observed_type
        or (
            expected.st_dev,
            expected.st_ino,
        )
        != (observed.st_dev, observed.st_ino)
    ):
        raise ClaudeResourceIdentityError(
            "execution resource changed while it was inspected"
        )


def _update_entry_digest(
    digest: _Digest,
    kind: bytes,
    name: bytes,
    metadata: os.stat_result,
    content_sha256: str,
) -> None:
    for value in (
        kind,
        name,
        str(stat.S_IMODE(metadata.st_mode)).encode(),
        str(metadata.st_dev).encode(),
        str(metadata.st_ino).encode(),
        content_sha256.encode(),
    ):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)


def _change_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _open_private_directory(path: Path) -> int:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY,
    )
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
        os.close(descriptor)
        raise ClaudeResourceIdentityError(
            "Claude execution resource must be private (0700)"
        )
    return descriptor

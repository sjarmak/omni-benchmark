"""Filesystem boundaries for public HKB artifacts."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Sequence


class HKBFileSafetyError(ValueError):
    """Raised when an HKB path is not a regular, dedicated artifact path."""


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _close_all(descriptors: Sequence[int]) -> None:
    for descriptor in reversed(descriptors):
        os.close(descriptor)


def _relative_parts(relative: str) -> tuple[str, ...]:
    parts = tuple(relative.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise HKBFileSafetyError(f"unsafe relative HKB path {relative}")
    return parts


def _read_bounded(file_descriptor: int, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    remaining = maximum_bytes
    while remaining > 0:
        chunk = os.read(file_descriptor, min(65_536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_relative_regular_file(
    root: Path, relative: str, *, maximum_bytes: int
) -> bytes:
    """Read a bounded regular file beneath a no-follow directory descriptor."""

    descriptors: list[int] = []
    try:
        current = os.open(root, _DIRECTORY_FLAGS)
        descriptors.append(current)
        parts = _relative_parts(relative)
        for directory in parts[:-1]:
            current = os.open(directory, _DIRECTORY_FLAGS, dir_fd=current)
            descriptors.append(current)
        file_descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current
        )
        descriptors.append(file_descriptor)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise OSError("not a regular file")
        return _read_bounded(file_descriptor, maximum_bytes)
    except OSError as error:
        raise HKBFileSafetyError(
            f"{relative} must be a regular non-symlink file beneath {root}"
        ) from error
    finally:
        _close_all(descriptors)


def prepare_safe_parent(path: Path) -> None:
    """Create an output parent after rejecting existing symlink components."""

    absolute = path.absolute()
    current = Path(absolute.anchor)
    for component in absolute.parts[1:-1]:
        current /= component
        if current.is_symlink():
            raise HKBFileSafetyError(
                f"output parent contains a symlink component: {current}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)


def _open_output_root(path: Path) -> int:
    try:
        path.mkdir(parents=True, exist_ok=True)
        return os.open(path, _DIRECTORY_FLAGS)
    except OSError as error:
        raise HKBFileSafetyError(
            "output root must be a non-symlink directory"
        ) from error


def _reject_unexpected(
    descriptor: int, expected_names: frozenset[str]
) -> frozenset[str]:
    observed = frozenset(os.listdir(descriptor))
    unexpected = sorted(observed - expected_names)
    if unexpected:
        raise HKBFileSafetyError(
            "output root contains unexpected entries: " + ", ".join(unexpected)
        )
    return observed


def publish_flat_files(
    staging: Path,
    destination: Path,
    names: Sequence[str],
) -> None:
    """Publish a flat verified set, with the caller ordering manifest last."""

    validated_names = tuple(_validate_flat_name(name) for name in names)
    prepare_safe_parent(destination)
    descriptor = _open_output_root(destination)
    try:
        observed = _reject_unexpected(descriptor, frozenset(validated_names))
        for name in observed:
            metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise HKBFileSafetyError(
                    f"existing output {name} must be a regular non-symlink file"
                )
        for name in validated_names:
            os.replace(staging / name, name, dst_dir_fd=descriptor)
    finally:
        os.close(descriptor)


def _validate_flat_name(name: str) -> str:
    if name in {"", ".", ".."} or "/" in name:
        raise HKBFileSafetyError(
            f"flat output name must be one safe path component: {name}"
        )
    return name


def _expected_tree(paths: Sequence[str]) -> dict[str, frozenset[str]]:
    tree: dict[str, set[str]] = {}
    for relative in paths:
        parts = _relative_parts(relative)
        if len(parts) != 2:
            raise HKBFileSafetyError(
                f"public HKB destination path must have two components: {relative}"
            )
        tree.setdefault(parts[0], set()).add(parts[1])
    return {directory: frozenset(files) for directory, files in tree.items()}


def _open_child_directory(root_descriptor: int, name: str) -> int:
    try:
        os.mkdir(name, dir_fd=root_descriptor)
    except FileExistsError:
        pass
    try:
        return os.open(name, _DIRECTORY_FLAGS, dir_fd=root_descriptor)
    except OSError as error:
        raise HKBFileSafetyError(
            f"output child {name} must be a non-symlink directory"
        ) from error


def _publish_child_files(
    staging: Path,
    directory: str,
    descriptor: int,
    names: frozenset[str],
    observed: frozenset[str],
) -> None:
    for name in observed:
        metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode):
            raise HKBFileSafetyError(
                f"existing output {directory}/{name} must be a regular non-symlink file"
            )
    for name in sorted(names):
        os.replace(staging / directory / name, name, dst_dir_fd=descriptor)


def publish_nested_files(
    staging: Path,
    destination: Path,
    paths: Sequence[str],
) -> None:
    """Publish canonical database/file paths without following destination links."""

    tree = _expected_tree(paths)
    prepare_safe_parent(destination)
    root_descriptor = _open_output_root(destination)
    try:
        _reject_unexpected(root_descriptor, frozenset(tree))
        for directory, names in sorted(tree.items()):
            child_descriptor = _open_child_directory(root_descriptor, directory)
            try:
                observed = _reject_unexpected(child_descriptor, names)
                _publish_child_files(
                    staging, directory, child_descriptor, names, observed
                )
            finally:
                os.close(child_descriptor)
    finally:
        os.close(root_descriptor)

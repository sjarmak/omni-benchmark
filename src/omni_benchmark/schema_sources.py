"""Acquire hash-pinned public LiveSQLBench schema metadata."""

from __future__ import annotations

import hashlib
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .hkb_io import HKBFileSafetyError, prepare_safe_parent, publish_nested_files
from .schema_source_inventory import (
    SchemaSourceInventoryError,
    load_schema_source_inventory,
)


class SchemaSourceError(ValueError):
    """Raised when public schema metadata cannot be acquired safely."""


FetchBytes = Callable[[str, int], bytes]


def _fetch_url(url: str, maximum_bytes: int) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            return response.read(maximum_bytes)
    except (OSError, urllib.error.URLError) as error:
        raise SchemaSourceError(
            f"cannot fetch public schema source {url}: {error}"
        ) from error


def _source_url(dataset: str, revision: str, path: str) -> str:
    return (
        f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{path}"
        "?download=true"
    )


def _git_blob_oid(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def verify_schema_source(
    content: bytes, *, size: int, sha256: str, oid: str, path: str
) -> None:
    if not isinstance(content, bytes):
        raise SchemaSourceError(f"fetcher returned non-bytes content for {path}")
    if len(content) != size:
        raise SchemaSourceError(f"size mismatch for {path}")
    if hashlib.sha256(content).hexdigest() != sha256:
        raise SchemaSourceError(f"SHA-256 mismatch for {path}")
    if _git_blob_oid(content) != oid:
        raise SchemaSourceError(f"Git blob OID mismatch for {path}")


def fetch_public_schema_sources(
    inventory_path: Path | str,
    destination_root: Path | str,
    *,
    fetch: FetchBytes = _fetch_url,
) -> dict[str, int | str]:
    """Verify the complete source set before publishing any schema metadata."""

    try:
        inventory = load_schema_source_inventory(inventory_path)
    except SchemaSourceInventoryError as error:
        raise SchemaSourceError(str(error)) from error
    destination = Path(destination_root)
    try:
        prepare_safe_parent(destination)
    except HKBFileSafetyError as error:
        raise SchemaSourceError(str(error)) from error
    paths = tuple(item.path for item in inventory.files)
    total_bytes = 0
    with tempfile.TemporaryDirectory(
        prefix=".public-schema-fetch-", dir=destination.parent
    ) as temporary:
        staging = Path(temporary)
        for item in inventory.files:
            content = fetch(
                _source_url(inventory.dataset, inventory.revision, item.path),
                item.size + 1,
            )
            verify_schema_source(
                content,
                size=item.size,
                sha256=item.sha256,
                oid=item.oid,
                path=item.path,
            )
            staged = staging / item.path
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(content)
            total_bytes += len(content)
        try:
            publish_nested_files(staging, destination, paths)
        except HKBFileSafetyError as error:
            raise SchemaSourceError(str(error)) from error
    return {
        "bytes": total_bytes,
        "files": len(inventory.files),
        "revision": inventory.revision,
    }

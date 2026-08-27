"""Acquire hash-pinned public LiveSQLBench HKB sources."""

from __future__ import annotations

import hashlib
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from omni_benchmark.hkb_inventory import (
    HKBInventoryError,
    git_blob_oid,
    load_hkb_source_inventory,
)
from omni_benchmark.hkb_io import (
    HKBFileSafetyError,
    prepare_safe_parent,
    publish_nested_files,
)


class HKBSourceError(ValueError):
    """Raised when a public HKB source cannot be acquired safely."""


FetchBytes = Callable[[str, int], bytes]


def _fetch_url(url: str, maximum_bytes: int) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            return response.read(maximum_bytes)
    except (OSError, urllib.error.URLError) as error:
        raise HKBSourceError(
            f"cannot fetch public HKB source {url}: {error}"
        ) from error


def _source_url(dataset: str, revision: str, path: str) -> str:
    return (
        f"https://huggingface.co/datasets/{dataset}/resolve/{revision}/{path}"
        "?download=true"
    )


def _verify_source(
    content: bytes, *, size: int, sha256: str, oid: str, path: str
) -> None:
    if not isinstance(content, bytes):
        raise HKBSourceError(f"fetcher returned non-bytes content for {path}")
    if len(content) != size:
        raise HKBSourceError(f"size mismatch for {path}")
    observed = hashlib.sha256(content).hexdigest()
    if observed != sha256:
        raise HKBSourceError(f"SHA-256 mismatch for {path}")
    if git_blob_oid(content) != oid:
        raise HKBSourceError(f"Git blob OID mismatch for {path}")


def fetch_public_hkb_sources(
    inventory_path: Path | str,
    destination_root: Path | str,
    *,
    fetch: FetchBytes = _fetch_url,
) -> dict[str, int | str]:
    """Fetch all pinned HKB objects, verify them, then publish them locally."""

    try:
        inventory = load_hkb_source_inventory(inventory_path)
    except HKBInventoryError as error:
        raise HKBSourceError(str(error)) from error
    destination = Path(destination_root)
    try:
        prepare_safe_parent(destination)
    except HKBFileSafetyError as error:
        raise HKBSourceError(str(error)) from error
    total_bytes = 0
    paths = tuple(item.path for item in inventory.files)
    with tempfile.TemporaryDirectory(
        prefix=".public-hkb-fetch-", dir=destination.parent
    ) as temporary:
        staging = Path(temporary)
        for item in inventory.files:
            url = _source_url(inventory.dataset, inventory.revision, item.path)
            content = fetch(url, item.size + 1)
            _verify_source(
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
            raise HKBSourceError(str(error)) from error
    return {
        "files": len(inventory.files),
        "bytes": total_bytes,
        "revision": inventory.revision,
    }

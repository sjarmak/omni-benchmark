from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.hkb_inventory import HKBInventoryError, load_hkb_source_inventory
from omni_benchmark.hkb_sources import HKBSourceError, fetch_public_hkb_sources


def _git_blob_oid(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _inventory(path: Path, *, content: bytes, sha256: str | None = None) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": "birdsql/livesqlbench-large-v1",
                "revision": "a418e108d5cbb4cf9b783a928eff5e924ad2460d",
                "files": [
                    {
                        "database": "alpha_large",
                        "path": "alpha_large/alpha_large_kb.jsonl",
                        "oid": _git_blob_oid(content),
                        "size": len(content),
                        "sha256": sha256 or hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        )
    )


def test_fetch_uses_pinned_revision_and_writes_verified_bytes(tmp_path: Path) -> None:
    content = b'{"public":"hkb"}\n'
    inventory = tmp_path / "inventory.json"
    _inventory(inventory, content=content)
    requested: list[tuple[str, int]] = []

    def fetch(url: str, maximum_bytes: int) -> bytes:
        requested.append((url, maximum_bytes))
        return content

    result = fetch_public_hkb_sources(
        inventory,
        tmp_path / "source",
        fetch=fetch,
    )

    assert requested == [
        (
            "https://huggingface.co/datasets/birdsql/livesqlbench-large-v1/resolve/"
            "a418e108d5cbb4cf9b783a928eff5e924ad2460d/"
            "alpha_large/alpha_large_kb.jsonl?download=true",
            len(content) + 1,
        )
    ]
    assert (
        tmp_path / "source" / "alpha_large" / "alpha_large_kb.jsonl"
    ).read_bytes() == content
    assert result == {
        "files": 1,
        "bytes": len(content),
        "revision": "a418e108d5cbb4cf9b783a928eff5e924ad2460d",
    }


def test_fetch_does_not_publish_unverified_bytes(tmp_path: Path) -> None:
    expected = b'{"public":"hkb"}\n'
    inventory = tmp_path / "inventory.json"
    _inventory(inventory, content=expected)
    destination = tmp_path / "source"

    with pytest.raises(HKBSourceError, match="size mismatch"):
        fetch_public_hkb_sources(
            inventory,
            destination,
            fetch=lambda _, __: b"corrupt",
        )

    assert not (destination / "alpha_large" / "alpha_large_kb.jsonl").exists()


def test_fetch_rejects_hash_mismatch(tmp_path: Path) -> None:
    content = b'{"public":"hkb"}\n'
    inventory = tmp_path / "inventory.json"
    _inventory(inventory, content=content, sha256="0" * 64)

    with pytest.raises(HKBSourceError, match="SHA-256 mismatch"):
        fetch_public_hkb_sources(
            inventory,
            tmp_path / "source",
            fetch=lambda _, __: content,
        )


def test_inventory_rejects_database_path_components(tmp_path: Path) -> None:
    content = b'{"public":"hkb"}\n'
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": "birdsql/livesqlbench-large-v1",
                "revision": "a418e108d5cbb4cf9b783a928eff5e924ad2460d",
                "files": [
                    {
                        "database": "..",
                        "path": "../../.._kb.jsonl",
                        "oid": "a" * 40,
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        )
    )

    with pytest.raises(HKBSourceError, match="database must contain"):
        fetch_public_hkb_sources(
            inventory,
            tmp_path / "source",
            fetch=lambda _, __: content,
        )


@pytest.mark.parametrize(
    ("inventory_text", "message"),
    [
        (
            '{"schema_version":1,"schema_version":1,"dataset":"x",'
            '"revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","files":[]}',
            "duplicate JSON field schema_version",
        ),
        (
            '{"schema_version":true,"dataset":"birdsql/livesqlbench-large-v1",'
            '"revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","files":[]}',
            "schema_version must equal integer 1",
        ),
        (
            '{"schema_version":1,"dataset":"birdsql/livesqlbench-large-v1\\nleak",'
            '"revision":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","files":[]}',
            "dataset must equal birdsql/livesqlbench-large-v1",
        ),
    ],
)
def test_inventory_rejects_ambiguous_identity_fields(
    tmp_path: Path, inventory_text: str, message: str
) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text(inventory_text)

    with pytest.raises(HKBSourceError, match=message):
        fetch_public_hkb_sources(
            inventory,
            tmp_path / "source",
            fetch=lambda _, __: b"",
        )


def test_fetch_rejects_git_blob_oid_mismatch(tmp_path: Path) -> None:
    content = b'{"public":"hkb"}\n'
    inventory = tmp_path / "inventory.json"
    _inventory(inventory, content=content)
    value = json.loads(inventory.read_text())
    value["files"][0]["oid"] = "0" * 40
    inventory.write_text(json.dumps(value))

    with pytest.raises(HKBSourceError, match="Git blob OID mismatch"):
        fetch_public_hkb_sources(
            inventory,
            tmp_path / "source",
            fetch=lambda _, __: content,
        )


def test_inventory_normalizes_excessive_json_nesting(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text("[" * 2_000 + "0" + "]" * 2_000)

    with pytest.raises(HKBInventoryError, match="cannot parse"):
        load_hkb_source_inventory(inventory)

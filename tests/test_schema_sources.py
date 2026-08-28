from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from omni_benchmark.schema_source_inventory import (
    SchemaSourceInventoryError,
    load_schema_source_inventory,
)
from omni_benchmark.schema_sources import (
    SchemaSourceError,
    fetch_public_schema_sources,
)


DATASET = "birdsql/livesqlbench-large-v1"
REVISION = "a418e108d5cbb4cf9b783a928eff5e924ad2460d"


def _git_blob_oid(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _source(database: str, kind: str, content: bytes) -> dict[str, object]:
    suffix = {
        "column_meanings": "column_meaning_base.json",
        "schema": "schema.txt",
    }[kind]
    return {
        "database": database,
        "kind": kind,
        "path": f"{database}/{database}_{suffix}",
        "oid": _git_blob_oid(content),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_inventory(
    path: Path,
    *,
    schema: bytes = b"CREATE TABLE sample (id bigint);\n",
    meanings: bytes = b'{"alpha_large|sample|id":"BIGINT. Identifier."}\n',
) -> tuple[bytes, bytes]:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": DATASET,
                "revision": REVISION,
                "files": [
                    _source("alpha_large", "schema", schema),
                    _source("alpha_large", "column_meanings", meanings),
                ],
            }
        )
    )
    return schema, meanings


def test_inventory_requires_one_schema_and_meaning_file_per_database(
    tmp_path: Path,
) -> None:
    inventory_path = tmp_path / "inventory.json"
    schema, meanings = _write_inventory(inventory_path)

    inventory = load_schema_source_inventory(inventory_path)

    assert inventory.dataset == DATASET
    assert inventory.revision == REVISION
    assert [(item.kind, item.path) for item in inventory.files] == [
        ("column_meanings", "alpha_large/alpha_large_column_meaning_base.json"),
        ("schema", "alpha_large/alpha_large_schema.txt"),
    ]
    assert [item.size for item in inventory.files] == [len(meanings), len(schema)]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda files: files[:1], "must contain exactly one"),
        (lambda files: [files[0], files[0]], "duplicate source kind"),
        (
            lambda files: [files[0], {**files[1], "path": "../escape"}],
            "canonical column_meanings path",
        ),
        (
            lambda files: [{**files[0], "kind": "gold"}, files[1]],
            "unsupported source kind",
        ),
    ],
)
def test_inventory_rejects_incomplete_or_noncanonical_source_pairs(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    inventory_path = tmp_path / "inventory.json"
    _write_inventory(inventory_path)
    value = json.loads(inventory_path.read_text())
    value["files"] = mutate(value["files"])
    inventory_path.write_text(json.dumps(value))

    with pytest.raises(SchemaSourceInventoryError, match=message):
        load_schema_source_inventory(inventory_path)


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
    ],
)
def test_inventory_rejects_ambiguous_identity_fields(
    tmp_path: Path, inventory_text: str, message: str
) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text(inventory_text)

    with pytest.raises(SchemaSourceInventoryError, match=message):
        load_schema_source_inventory(inventory)


def test_inventory_rejects_symlink_input(tmp_path: Path) -> None:
    target = tmp_path / "inventory.json"
    _write_inventory(target)
    link = tmp_path / "inventory-link.json"
    link.symlink_to(target)

    with pytest.raises(SchemaSourceInventoryError, match="regular non-symlink"):
        load_schema_source_inventory(link)


def test_inventory_rejects_symlinked_parent_component(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    inventory = outside / "inventory.json"
    _write_inventory(inventory)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SchemaSourceInventoryError, match="regular non-symlink"):
        load_schema_source_inventory(linked_parent / "inventory.json")


def test_inventory_rejects_nonregular_input_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "inventory.fifo"
    os.mkfifo(fifo)

    with pytest.raises(SchemaSourceInventoryError, match="regular non-symlink"):
        load_schema_source_inventory(fifo)


def test_inventory_rejects_oversized_input(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_bytes(b" " * (1_048_576 + 1))

    with pytest.raises(SchemaSourceInventoryError, match="exceeds 1048576 bytes"):
        load_schema_source_inventory(inventory)


def test_inventory_normalizes_excessive_json_nesting(tmp_path: Path) -> None:
    inventory = tmp_path / "inventory.json"
    inventory.write_text("[" * 2_000 + "0" + "]" * 2_000)

    with pytest.raises(SchemaSourceInventoryError, match="cannot parse"):
        load_schema_source_inventory(inventory)


def test_fetch_verifies_all_sources_before_publishing(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    schema, meanings = _write_inventory(inventory_path)
    content_by_suffix = {
        "column_meaning_base.json?download=true": meanings,
        "schema.txt?download=true": schema,
    }
    requested: list[tuple[str, int]] = []

    def fetch(url: str, maximum_bytes: int) -> bytes:
        requested.append((url, maximum_bytes))
        return next(
            content
            for suffix, content in content_by_suffix.items()
            if url.endswith(suffix)
        )

    destination = tmp_path / "sources"
    result = fetch_public_schema_sources(
        inventory_path,
        destination,
        fetch=fetch,
    )

    assert len(requested) == 2
    assert all(f"/resolve/{REVISION}/alpha_large/" in url for url, _ in requested)
    assert sorted(limit for _, limit in requested) == sorted(
        [len(schema) + 1, len(meanings) + 1]
    )
    assert (
        destination / "alpha_large" / "alpha_large_schema.txt"
    ).read_bytes() == schema
    assert (
        destination / "alpha_large" / "alpha_large_column_meaning_base.json"
    ).read_bytes() == meanings
    assert result == {
        "bytes": len(schema) + len(meanings),
        "files": 2,
        "revision": REVISION,
    }


def test_fetch_failure_publishes_no_partial_source_set(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    _write_inventory(inventory_path)
    destination = tmp_path / "sources"
    calls = 0

    def fetch(_: str, __: int) -> bytes:
        nonlocal calls
        calls += 1
        return b"corrupt"

    with pytest.raises(SchemaSourceError, match="size mismatch"):
        fetch_public_schema_sources(inventory_path, destination, fetch=fetch)

    assert calls == 1
    assert not destination.exists()


def test_fetch_rejects_exact_size_sha256_mismatch(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    schema, meanings = _write_inventory(inventory_path)
    corrupted_schema = bytes([schema[0] ^ 1]) + schema[1:]

    def fetch(url: str, _: int) -> bytes:
        if url.endswith("schema.txt?download=true"):
            return corrupted_schema
        return meanings

    with pytest.raises(SchemaSourceError, match="SHA-256 mismatch"):
        fetch_public_schema_sources(
            inventory_path,
            tmp_path / "sources",
            fetch=fetch,
        )


def test_fetch_rejects_git_blob_oid_mismatch(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    schema, meanings = _write_inventory(inventory_path)
    value = json.loads(inventory_path.read_text())
    value["files"][0]["oid"] = "0" * 40
    inventory_path.write_text(json.dumps(value))

    def fetch(url: str, _: int) -> bytes:
        if url.endswith("schema.txt?download=true"):
            return schema
        return meanings

    with pytest.raises(SchemaSourceError, match="Git blob OID mismatch"):
        fetch_public_schema_sources(
            inventory_path,
            tmp_path / "sources",
            fetch=fetch,
        )


def test_late_source_verification_failure_publishes_nothing(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    schema, meanings = _write_inventory(inventory_path)
    destination = tmp_path / "sources"

    def fetch(url: str, _: int) -> bytes:
        if url.endswith("schema.txt?download=true"):
            return b"x" * len(schema)
        return meanings

    with pytest.raises(SchemaSourceError, match="SHA-256 mismatch"):
        fetch_public_schema_sources(inventory_path, destination, fetch=fetch)

    assert not destination.exists()

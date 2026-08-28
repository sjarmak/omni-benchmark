from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from omni_benchmark.direct_database_loader import (
    DirectDatabaseLoadError,
    load_committed_direct_database_identity,
)

INVENTORY_PATH = Path("config/databases/livesqlbench-large-v1.json")
TARGETS_PATH = Path("config/conditions/direct-database-targets-v1.json")


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _git(workspace: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def _database_record(name: str = "archeology_scan_large") -> dict[str, object]:
    return {
        "alias": name,
        "dump_file_count": 53,
        "dump_sha256": "1" * 64,
        "dump_size_bytes": 123,
        "managed_mirror": {
            "branch_id": "br-public-fixture",
            "branch_name": "main",
            "organization_id": "org-public-fixture",
            "project_id": "project-public-fixture",
            "provider": "neon",
            "region_id": "aws-us-east-2",
            "runtime_role": "omni_benchmark_reader",
        },
        "name": name,
        "omni_connection": {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": f"LiveSQLBench {name}",
        },
        "verification": {
            "content_sha256": "3" * 64,
            "external_parity": True,
            "postgres_server_version_num": "180006",
            "readonly_role_verified": True,
            "row_count": 10,
            "schema_sha256": "4" * 64,
            "table_count": 2,
        },
    }


def _inventory(records: list[dict[str, object]]) -> dict[str, object]:
    return {
        "benchmark": "LiveSQLBench Large-v1",
        "canary": "archeology_scan_large",
        "canary_verification": {},
        "databases": records,
        "format_version": 2,
        "postgres_major": 18,
        "sources": {"dataset_revision": "public-fixture"},
    }


def _target(name: str = "archeology_scan_large") -> dict[str, object]:
    return {
        "connection_target_sha256": (
            "2" * 64
            if name == "archeology_scan_large"
            else hashlib.sha256(name.encode()).hexdigest()
        ),
        "name": name,
        "physical_database": name,
    }


def _sidecar(
    inventory: dict[str, object], targets: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "benchmark": "LiveSQLBench Large-v1",
        "databases": targets,
        "format_version": 1,
        "inventory_path": INVENTORY_PATH.as_posix(),
        "inventory_sha256": hashlib.sha256(_canonical(inventory)).hexdigest(),
    }


def _repo(
    tmp_path: Path,
    *,
    records: list[dict[str, object]] | None = None,
    mutate_sidecar: Callable[[dict[str, object]], None] | None = None,
) -> tuple[Path, str, dict[str, object], dict[str, object]]:
    workspace = tmp_path / "workspace"
    selected_records = records or [_database_record()]
    inventory = _inventory(selected_records)
    targets = [_target(str(record["name"])) for record in selected_records]
    sidecar = _sidecar(inventory, targets)
    if mutate_sidecar is not None:
        mutate_sidecar(sidecar)
    inventory_path = workspace / INVENTORY_PATH
    targets_path = workspace / TARGETS_PATH
    inventory_path.parent.mkdir(parents=True)
    targets_path.parent.mkdir(parents=True)
    inventory_path.write_bytes(_canonical(inventory))
    targets_path.write_bytes(_canonical(sidecar))
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.test")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "fixture")
    return workspace, _git(workspace, "rev-parse", "HEAD"), inventory, sidecar


def test_loader_combines_committed_v2_inventory_with_exact_sidecar(
    tmp_path: Path,
) -> None:
    workspace, commit, inventory, sidecar = _repo(tmp_path)

    identity = load_committed_direct_database_identity(
        workspace,
        commit,
        selected_database="archeology_scan_large",
        environment={},
    )

    record = inventory["databases"][0]
    deployment = {
        "connection_target_sha256": "2" * 64,
        "physical_database": "archeology_scan_large",
        "runtime_role": "omni_benchmark_reader",
    }
    assert identity.selected_database == "archeology_scan_large"
    assert identity.physical_database == "archeology_scan_large"
    assert identity.runtime_role == "omni_benchmark_reader"
    assert identity.postgres_server_version_num == 180006
    assert identity.connection_target_sha256 == "2" * 64
    assert identity.schema_sha256 == "4" * 64
    assert identity.content_sha256 == "3" * 64
    assert identity.inventory_sha256 == sidecar["inventory_sha256"]
    assert (
        identity.database_record_sha256
        == hashlib.sha256(_canonical(record)).hexdigest()
    )
    assert (
        identity.deployment_identity_sha256
        == hashlib.sha256(_canonical(deployment)).hexdigest()
    )


@pytest.mark.parametrize("artifact", ["inventory", "sidecar"])
def test_loader_rejects_worktree_drift(tmp_path: Path, artifact: str) -> None:
    workspace, commit, _, _ = _repo(tmp_path)
    path = workspace / (INVENTORY_PATH if artifact == "inventory" else TARGETS_PATH)
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(DirectDatabaseLoadError, match="current bytes"):
        load_committed_direct_database_identity(
            workspace,
            commit,
            selected_database="archeology_scan_large",
            environment={},
        )


def test_loader_rejects_unknown_selected_database(tmp_path: Path) -> None:
    workspace, commit, _, _ = _repo(tmp_path)

    with pytest.raises(DirectDatabaseLoadError, match="not present"):
        load_committed_direct_database_identity(
            workspace,
            commit,
            selected_database="other_database",
            environment={},
        )


def _drop_targets(sidecar: dict[str, object]) -> None:
    sidecar["databases"] = []


def _add_unknown_target(sidecar: dict[str, object]) -> None:
    sidecar["databases"].append(_target("other_database"))


def _duplicate_target(sidecar: dict[str, object]) -> None:
    sidecar["databases"].append(_target())


def _add_top_level_field(sidecar: dict[str, object]) -> None:
    sidecar["notes"] = "not allowed"


def _add_target_field(sidecar: dict[str, object]) -> None:
    sidecar["databases"][0]["host"] = "example.test"


def _add_url_field(sidecar: dict[str, object]) -> None:
    sidecar["databases"][0]["url"] = "https://example.test"


def _add_secret_field(sidecar: dict[str, object]) -> None:
    sidecar["databases"][0]["password"] = "never-persist-this"


def _drop_target_field(sidecar: dict[str, object]) -> None:
    del sidecar["databases"][0]["physical_database"]


def _drop_top_level_field(sidecar: dict[str, object]) -> None:
    del sidecar["inventory_path"]


def _wrong_inventory_hash(sidecar: dict[str, object]) -> None:
    sidecar["inventory_sha256"] = "9" * 64


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (_drop_targets, "coverage"),
        (_add_unknown_target, "coverage"),
        (_duplicate_target, "unique"),
        (_add_top_level_field, "exact schema"),
        (_add_target_field, "exact schema"),
        (_add_url_field, "exact schema"),
        (_add_secret_field, "sensitive"),
        (_drop_target_field, "exact schema"),
        (_drop_top_level_field, "exact schema"),
        (_wrong_inventory_hash, "does not match"),
    ],
)
def test_loader_rejects_unsafe_or_noncovering_sidecar(
    tmp_path: Path,
    mutation: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    workspace, commit, _, _ = _repo(tmp_path, mutate_sidecar=mutation)

    with pytest.raises(DirectDatabaseLoadError, match=message):
        load_committed_direct_database_identity(
            workspace,
            commit,
            selected_database="archeology_scan_large",
            environment={},
        )


def test_loader_rejects_duplicate_physical_target_binding(tmp_path: Path) -> None:
    def duplicate_binding(sidecar: dict[str, object]) -> None:
        sidecar["databases"][1]["connection_target_sha256"] = sidecar["databases"][0][
            "connection_target_sha256"
        ]

    workspace, commit, _, _ = _repo(
        tmp_path,
        records=[_database_record(), _database_record("cross_border_large")],
        mutate_sidecar=duplicate_binding,
    )

    with pytest.raises(DirectDatabaseLoadError, match="not unique"):
        load_committed_direct_database_identity(
            workspace,
            commit,
            selected_database="archeology_scan_large",
            environment={},
        )


def test_repository_sidecar_is_secret_free_and_covers_all_18_databases() -> None:
    workspace = Path(__file__).parents[1]
    inventory_bytes = (workspace / INVENTORY_PATH).read_bytes()
    inventory = json.loads(inventory_bytes)
    sidecar = json.loads((workspace / TARGETS_PATH).read_bytes())

    assert sidecar["inventory_sha256"] == hashlib.sha256(inventory_bytes).hexdigest()
    assert len(inventory["databases"]) == len(sidecar["databases"]) == 18
    assert {record["name"] for record in inventory["databases"]} == {
        record["name"] for record in sidecar["databases"]
    }
    assert all(set(record) == set(_target()) for record in sidecar["databases"])
    assert all(
        record["physical_database"] == record["name"]
        and len(record["connection_target_sha256"]) == 64
        for record in sidecar["databases"]
    )
    serialized = json.dumps(sidecar).lower()
    assert all(
        forbidden not in serialized
        for forbidden in ("host", "endpoint", "url", "password", "token", "secret")
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("format", "format version"),
        ("runtime_role", "deployment"),
        ("readonly", "verified"),
        ("parity", "verified"),
        ("server", "server version"),
    ],
)
def test_loader_rejects_unverified_or_incomplete_inventory(
    tmp_path: Path, mutation: str, message: str
) -> None:
    record = _database_record()
    if mutation == "runtime_role":
        del record["managed_mirror"]["runtime_role"]
    elif mutation == "readonly":
        record["verification"]["readonly_role_verified"] = False
    elif mutation == "parity":
        record["verification"]["external_parity"] = False
    elif mutation == "server":
        record["verification"]["postgres_server_version_num"] = "170000"
    workspace, commit, inventory, _ = _repo(tmp_path, records=[record])
    if mutation == "format":
        inventory["format_version"] = 3
        path = workspace / INVENTORY_PATH
        path.write_bytes(_canonical(inventory))
        sidecar_path = workspace / TARGETS_PATH
        sidecar = json.loads(sidecar_path.read_text())
        sidecar["inventory_sha256"] = hashlib.sha256(_canonical(inventory)).hexdigest()
        sidecar_path.write_bytes(_canonical(sidecar))
        _git(workspace, "add", ".")
        _git(workspace, "commit", "-qm", "mutation")
        commit = _git(workspace, "rev-parse", "HEAD")

    with pytest.raises(DirectDatabaseLoadError, match=message):
        load_committed_direct_database_identity(
            workspace,
            commit,
            selected_database="archeology_scan_large",
            environment={},
        )

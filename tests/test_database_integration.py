from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

from omni_benchmark.database_fingerprint import fingerprint_database
from omni_benchmark.database_inventory import (
    fingerprint_dump_directory,
    load_database_inventory,
    verify_restore_order,
)
from omni_benchmark.database_postgres import (
    PostgresClient,
    preflight_restore,
    provision_readonly_role,
    restore_database,
    verify_readonly_role,
)


@pytest.mark.skipif(
    os.environ.get("OMNI_BENCHMARK_POSTGRES_INTEGRATION") != "1",
    reason="requires the explicit public PostgreSQL canary environment",
)
def test_canary_restore_role_and_repeat_fingerprint_parity_e2e(
    monkeypatch,
) -> None:
    inventory = load_database_inventory(
        Path("config/databases/livesqlbench-large-v1.json")
    )
    canary = next(
        database
        for database in inventory.databases
        if database.name == inventory.canary
    )
    dump_directory = Path(
        "data/raw/livesqlbench-large-v1/extracted/postgre_table_dumps_large/"
        "archeology_scan_large_template"
    )
    orders = verify_restore_order(
        inventory, Path("config/databases/restore-order-large-v1.json")
    )
    dump = fingerprint_dump_directory(dump_directory)
    assert (len(dump.files), dump.size_bytes, dump.sha256) == (
        canary.dump_file_count,
        canary.dump_size_bytes,
        canary.dump_sha256,
    )

    client = PostgresClient()
    preflight_restore(client, postgres_major=18, owner_role="root")
    restore_database(
        client,
        database=canary.name,
        dump_directory=dump_directory,
        restore_order=orders[canary.name],
    )
    first = fingerprint_database(client, canary.name)

    monkeypatch.setenv("BENCHMARK_RUNTIME_PASSWORD", secrets.token_hex(24))
    provision_readonly_role(client, database=canary.name, role="omni_benchmark_reader")
    verify_readonly_role(client, database=canary.name, role="omni_benchmark_reader")

    restore_database(
        client,
        database=canary.name,
        dump_directory=dump_directory,
        restore_order=orders[canary.name],
    )
    second = fingerprint_database(client, canary.name)
    assert first == second
    provision_readonly_role(client, database=canary.name, role="omni_benchmark_reader")
    verify_readonly_role(client, database=canary.name, role="omni_benchmark_reader")

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from typing import Iterator

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

import omni_benchmark.claude_direct_transport as claude_transport

TELEMETRY_ADMIN_DSN = os.environ.get(
    "OMNI_BENCHMARK_TELEMETRY_TEST_ADMIN_DSN",
    "host=/var/run/postgresql dbname=postgres",
)


@pytest.fixture(scope="session", autouse=True)
def _use_synthetic_claude_binary_for_mocked_transports(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Keep mocked transport tests independent of a host-installed Claude CLI."""
    binary = tmp_path_factory.mktemp("claude-test-runtime") / "claude"
    content = b"#!/bin/sh\nexit 97\n"
    binary.write_bytes(content)
    binary.chmod(0o700)

    patch = pytest.MonkeyPatch()
    # An operator who set the override in their shell must not steer the suite.
    patch.delenv(claude_transport.CLAUDE_BINARY_PATH_ENV, raising=False)
    patch.setattr(claude_transport, "PINNED_CLAUDE_BINARY", binary)
    patch.setattr(
        claude_transport,
        "PINNED_CLAUDE_BINARY_SHA256",
        hashlib.sha256(content).hexdigest(),
    )
    yield
    patch.undo()


@pytest.fixture
def throwaway_database() -> Iterator[str]:
    """Yield a DSN for a fresh local database, dropped afterwards; skip if none."""
    try:
        admin = psycopg.connect(TELEMETRY_ADMIN_DSN, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as error:
        pytest.skip(f"no local PostgreSQL for telemetry integration tests: {error}")
    name = f"omni_telemetry_test_{secrets.token_hex(6)}"
    with admin:
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        except psycopg.errors.InsufficientPrivilege as error:
            pytest.skip(f"local PostgreSQL refuses CREATE DATABASE: {error}")
        try:
            yield make_conninfo(TELEMETRY_ADMIN_DSN, dbname=name)
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def linux_dump_file_lookup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def exact_lookup(original):
        def lookup(path: Path, *args, **kwargs):
            if path.is_relative_to(tmp_path) and path.suffix == ".sql":
                with os.scandir(path.parent) as entries:
                    names = {entry.name for entry in entries}
                if path.name not in names:
                    return False
            return original(path, *args, **kwargs)

        return lookup

    for method in ("exists", "is_file", "is_symlink"):
        monkeypatch.setattr(Path, method, exact_lookup(getattr(Path, method)))

from __future__ import annotations

import hashlib
import json
import subprocess
import traceback
from pathlib import Path

import pytest

from omni_benchmark.database_fingerprint import compare_fingerprints
from omni_benchmark.database_postgres import (
    DatabaseOperationError,
    PostgresClient,
    _quote_literal,
    preflight_restore,
    provision_readonly_role,
    restore_database,
    validate_identifier,
    verify_readonly_role,
)


class RecordingClient(PostgresClient):
    def __init__(self, responses: list[bytes] | None = None) -> None:
        self.calls: list[tuple[str, str, bytes | None, dict[str, str] | None]] = []
        self.stop_on_error: list[bool] = []
        self.responses = list(responses or [])

    def run(
        self,
        database: str,
        *,
        sql: str | None = None,
        file: Path | None = None,
        stdin: bytes | None = None,
        environment: dict[str, str] | None = None,
        stop_on_error: bool = True,
    ) -> bytes:
        action = sql if sql is not None else str(file)
        self.calls.append((database, action, stdin, environment))
        self.stop_on_error.append(stop_on_error)
        return self.responses.pop(0) if self.responses else b""


class DeniedWriteClient(RecordingClient):
    def run(self, database: str, **kwargs) -> bytes:
        sql = kwargs.get("sql", "")
        if sql.startswith(("CREATE TABLE", "CREATE TEMP TABLE", "BEGIN; SET LOCAL")):
            raise DatabaseOperationError("read-only transaction", sqlstate="25006")
        return super().run(database, **kwargs)


@pytest.mark.parametrize("value", ["bad-name", "bad.name", 'bad"name', ""])
def test_identifier_validation_rejects_unsafe_names(value: str) -> None:
    with pytest.raises(DatabaseOperationError, match="identifier"):
        validate_identifier(value)


def test_postgres_client_runs_psql_without_shell(monkeypatch) -> None:
    recorded: dict[str, object] = {}
    monkeypatch.setenv("AURA_TOKEN", "must-not-reach-psql")

    def fake_run(command, **kwargs):
        recorded["command"] = command
        recorded["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout=b"result\n", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert PostgresClient().run("fixture_db", sql="SELECT 1;") == b"result\n"
    assert recorded["command"][-2:] == ["--command", "SELECT 1;"]
    assert recorded["kwargs"]["check"] is False
    assert "AURA_TOKEN" not in recorded["kwargs"]["env"]


def test_postgres_client_does_not_expose_stdin_sql_on_failure(monkeypatch) -> None:
    def fail(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 3, stdout=b"", stderr=b"ERROR near not-logged-secret"
        )

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(DatabaseOperationError) as captured:
        PostgresClient().run("fixture_db", stdin=b"PASSWORD 'not-logged-secret';")
    assert "not-logged-secret" not in str(captured.value)


def test_postgres_client_extracts_verbose_sqlstate(monkeypatch) -> None:
    def fail(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=b"",
            stderr=b"ERROR:  42501: permission denied\nLOCATION: aclcheck_error",
        )

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(DatabaseOperationError) as captured:
        PostgresClient().run("fixture_db", sql="SELECT 1;")
    assert captured.value.sqlstate == "42501"


def test_postgres_failure_traceback_omits_connection_secrets(monkeypatch) -> None:
    monkeypatch.setenv("PGPASSWORD", "traceback-password-sentinel")
    monkeypatch.setenv("PGPASSFILE", "/traceback-passfile-sentinel")

    def fail(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=b"",
            stderr=b"ERROR:  08006: connection failure",
        )

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(DatabaseOperationError) as captured:
        PostgresClient().run("fixture_db", sql="SELECT 1;")
    rendered = "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert "traceback-password-sentinel" not in rendered
    assert "traceback-passfile-sentinel" not in rendered


def test_postgres_client_requires_exactly_one_input() -> None:
    with pytest.raises(DatabaseOperationError, match="exactly one"):
        PostgresClient().run("fixture_db")


def test_postgres_client_can_match_scorer_error_continuation(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    def fake_run(command, **kwargs):
        recorded["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    PostgresClient().run("fixture_db", file=Path("fixture.sql"), stop_on_error=False)

    assert "--set=ON_ERROR_STOP=0" in recorded["command"]


def test_postgres_literal_escaping_is_independent_of_string_settings() -> None:
    assert _quote_literal("backslash\\quote'") == "E'backslash\\\\quote'''"


def test_restore_database_uses_explicit_order_and_fails_on_missing_dump(
    tmp_path: Path,
) -> None:
    (tmp_path / "parent.sql").write_text("select 1;\n", encoding="utf-8")
    client = RecordingClient()

    with pytest.raises(DatabaseOperationError, match="child.sql"):
        restore_database(
            client,
            database="fixture_db",
            dump_directory=tmp_path,
            restore_order=("parent", "child"),
        )

    assert client.calls == []


def test_restore_database_recreates_from_template0_and_loads_in_order(
    tmp_path: Path,
) -> None:
    for name in ("parent", "child"):
        (tmp_path / f"{name}.sql").write_text(f"-- {name}\n", encoding="utf-8")
    client = RecordingClient()

    restore_database(
        client,
        database="fixture_db",
        dump_directory=tmp_path,
        restore_order=("parent", "child"),
    )

    assert [call[0] for call in client.calls] == [
        "postgres",
        "postgres",
        "postgres",
        "fixture_db",
        "fixture_db",
    ]
    assert "pg_terminate_backend" in client.calls[0][1]
    assert "DROP DATABASE IF EXISTS" in client.calls[1][1]
    assert "CREATE DATABASE" in client.calls[2][1]
    assert client.calls[3][1].endswith("parent.sql")
    assert client.calls[4][1].endswith("child.sql")


def test_restore_allows_only_explicitly_omitted_missing_dump(tmp_path: Path) -> None:
    (tmp_path / "present.sql").write_text("SELECT 1;\n", encoding="utf-8")
    client = RecordingClient()

    restore_database(
        client,
        database="fixture_db",
        dump_directory=tmp_path,
        restore_order=("present", "upstream_missing"),
        omitted_tables=("upstream_missing",),
    )

    assert len(client.calls) == 4
    assert client.calls[-1][1].endswith("present.sql")


def test_restore_rejects_omission_when_dump_file_exists(tmp_path: Path) -> None:
    (tmp_path / "present.sql").write_text("SELECT 1;\n", encoding="utf-8")
    client = RecordingClient()

    with pytest.raises(DatabaseOperationError, match="omitted dump file exists"):
        restore_database(
            client,
            database="fixture_db",
            dump_directory=tmp_path,
            restore_order=("present",),
            omitted_tables=("present",),
        )
    assert client.calls == []


def test_restore_can_match_scorer_sql_error_continuation(tmp_path: Path) -> None:
    (tmp_path / "present.sql").write_text("SELECT 1;\n", encoding="utf-8")
    client = RecordingClient()

    restore_database(
        client,
        database="fixture_db",
        dump_directory=tmp_path,
        restore_order=("present",),
        continue_after_sql_error=True,
    )

    assert client.stop_on_error[-1] is False


def test_restore_rejects_path_traversal_before_database_change(tmp_path: Path) -> None:
    outside = tmp_path / "outside.sql"
    outside.write_text("SELECT 1;\n", encoding="utf-8")
    dump = tmp_path / "dump"
    dump.mkdir()
    client = RecordingClient()

    with pytest.raises(DatabaseOperationError, match="identifier"):
        restore_database(
            client,
            database="fixture_db",
            dump_directory=dump,
            restore_order=("../outside",),
        )
    assert client.calls == []


def test_restore_rejects_symlinked_dump_before_database_change(tmp_path: Path) -> None:
    outside = tmp_path / "outside.sql"
    outside.write_text("SELECT 1;\n", encoding="utf-8")
    dump = tmp_path / "dump"
    dump.mkdir()
    (dump / "table.sql").symlink_to(outside)
    client = RecordingClient()

    with pytest.raises(DatabaseOperationError, match="symlink"):
        restore_database(
            client,
            database="fixture_db",
            dump_directory=dump,
            restore_order=("table",),
        )
    assert client.calls == []


def test_restore_preflight_requires_expected_major_and_owner() -> None:
    client = RecordingClient([b"180006\n", b"1\n"])
    preflight_restore(client, postgres_major=18, owner_role="root")
    assert len(client.calls) == 2

    with pytest.raises(DatabaseOperationError, match="PostgreSQL 18"):
        preflight_restore(
            RecordingClient([b"160015\n"]),
            postgres_major=18,
            owner_role="root",
        )
    with pytest.raises(DatabaseOperationError, match="owner role root"):
        preflight_restore(
            RecordingClient([b"180006\n", b"\n"]),
            postgres_major=18,
            owner_role="root",
        )


def test_readonly_role_password_is_sent_only_over_stdin(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_RUNTIME_PASSWORD", "not-logged-secret")
    client = RecordingClient()

    provision_readonly_role(client, database="fixture_db", role="benchmark_reader")

    assert len(client.calls) == 3
    combined_actions = "\n".join(call[1] for call in client.calls)
    assert "not-logged-secret" not in combined_actions
    assert "pg_catalog.pg_shdepend" in client.calls[0][1]
    assert "dependency.deptype = 'o'" in client.calls[0][1]
    assert "current_database()" in client.calls[0][1]
    role_call = client.calls[2]
    assert role_call[2] is not None
    assert b"ALTER DEFAULT PRIVILEGES" in role_call[2]
    assert b"pg_catalog.pg_namespace" in role_call[2]
    assert b"REVOKE ALL PRIVILEGES ON SCHEMA" in role_call[2]
    assert b"REVOKE ALL PRIVILEGES ON ALL TABLES" in role_call[2]
    assert b"aclexplode(attribute.attacl)" in role_call[2]
    assert b"REVOKE %s (%I) ON TABLE %I.%I FROM PUBLIC" in role_call[2]
    assert b"REVOKE %s (%I) ON TABLE %I.%I FROM %I" in role_call[2]
    assert (
        b"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM PUBLIC" in role_call[2]
    )
    assert b"FROM PUBLIC" in role_call[2]
    cluster_call = client.calls[1]
    assert cluster_call[2] is not None
    assert b"default_transaction_read_only" in cluster_call[2]
    assert b"NOINHERIT" in cluster_call[2]
    assert b"rolsuper OR rolcreatedb OR rolcreaterole" in cluster_call[2]
    assert b"rolreplication OR rolbypassrls" in cluster_call[2]
    assert b"NOSUPERUSER" not in cluster_call[2]
    assert b"NOCREATEDB" not in cluster_call[2]
    assert b"NOCREATEROLE" not in cluster_call[2]
    assert b"NOREPLICATION" not in cluster_call[2]
    assert b"NOBYPASSRLS" not in cluster_call[2]
    assert b"pg_catalog.pg_database" in cluster_call[2]
    assert b"REVOKE CONNECT" in cluster_call[2]
    assert b"REVOKE TEMPORARY" in cluster_call[2]


def test_readonly_role_fails_before_mutation_when_role_owns_objects(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BENCHMARK_RUNTIME_PASSWORD", "runtime-secret")

    class OwnershipClient(RecordingClient):
        def run(self, database: str, **kwargs) -> bytes:
            self.calls.append((database, kwargs.get("sql", ""), None, None))
            raise DatabaseOperationError("runtime role owns target objects")

    client = OwnershipClient()
    with pytest.raises(DatabaseOperationError, match="owns target objects"):
        provision_readonly_role(client, database="fixture_db", role="benchmark_reader")
    assert len(client.calls) == 1


def test_readonly_role_requires_password(monkeypatch) -> None:
    monkeypatch.delenv("BENCHMARK_RUNTIME_PASSWORD", raising=False)

    with pytest.raises(DatabaseOperationError, match="BENCHMARK_RUNTIME_PASSWORD"):
        provision_readonly_role(
            RecordingClient(), database="fixture_db", role="benchmark_reader"
        )


def test_readonly_verification_checks_select_and_denied_write(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_RUNTIME_PASSWORD", "runtime-secret")
    client = DeniedWriteClient([b"on\n", b"analytics\tfixture_table\n", b"1\n", b""])

    verify_readonly_role(client, database="fixture_db", role="benchmark_reader")

    assert len(client.calls) == 4
    assert client.calls[2][1] == 'SELECT 1 FROM "analytics"."fixture_table" LIMIT 1;'
    privilege_audit = client.calls[3][1]
    assert "has_table_privilege" in privilege_audit
    assert "MAINTAIN" in privilege_audit
    assert "has_column_privilege" in privilege_audit
    assert "has_sequence_privilege" in privilege_audit
    assert "has_function_privilege" in privilege_audit
    assert client.calls[0][3] == {
        "PGPASSWORD": "runtime-secret",
        "PGUSER": "benchmark_reader",
    }


def test_readonly_verification_rejects_effective_nonread_privilege(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BENCHMARK_RUNTIME_PASSWORD", "runtime-secret")
    client = RecordingClient([b"on\n", b"public\tfixture_table\n", b"1\n", b"1\n"])

    with pytest.raises(DatabaseOperationError, match="non-read privilege"):
        verify_readonly_role(client, database="fixture_db", role="benchmark_reader")


def test_readonly_verification_rejects_successful_write(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_RUNTIME_PASSWORD", "runtime-secret")
    client = RecordingClient([b"on\n", b"public\tfixture_table\n", b""])

    with pytest.raises(DatabaseOperationError, match="accepted a write"):
        verify_readonly_role(client, database="fixture_db", role="benchmark_reader")


def test_readonly_verification_requires_table_select_access(monkeypatch) -> None:
    monkeypatch.setenv("BENCHMARK_RUNTIME_PASSWORD", "runtime-secret")

    class SelectDeniedClient(RecordingClient):
        def run(self, database: str, **kwargs) -> bytes:
            if kwargs.get("sql", "").startswith("SELECT 1 FROM"):
                raise DatabaseOperationError("permission denied", sqlstate="42501")
            return super().run(database, **kwargs)

    with pytest.raises(DatabaseOperationError, match="permission denied"):
        verify_readonly_role(
            SelectDeniedClient([b"on\n", b"public\tfixture_table\n"]),
            database="fixture_db",
            role="benchmark_reader",
        )


def test_readonly_verification_propagates_unclassified_database_failure(
    monkeypatch,
) -> None:
    monkeypatch.setenv("BENCHMARK_RUNTIME_PASSWORD", "runtime-secret")

    class ConnectionFailureClient(RecordingClient):
        def run(self, database: str, **kwargs) -> bytes:
            if kwargs.get("sql", "").startswith("BEGIN; SET LOCAL"):
                raise DatabaseOperationError("connection lost")
            return super().run(database, **kwargs)

    with pytest.raises(DatabaseOperationError, match="connection lost"):
        verify_readonly_role(
            ConnectionFailureClient([b"on\n", b"public\tfixture_table\n"]),
            database="fixture_db",
            role="benchmark_reader",
        )


def test_fingerprint_compare_exit_contract(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    payload = {
        "format_version": 1,
        "database": "fixture_db",
        "postgres_server_version_num": "180006",
        "schema_sha256": "a" * 64,
        "content_sha256": hashlib.sha256(b"[]").hexdigest(),
        "table_count": 0,
        "row_count": 0,
        "tables": [],
    }
    left.write_text(json.dumps(payload), encoding="utf-8")
    right.write_text(json.dumps(payload), encoding="utf-8")
    assert compare_fingerprints(left, right) == 0

    payload["schema_sha256"] = "c" * 64
    right.write_text(json.dumps(payload), encoding="utf-8")
    assert compare_fingerprints(left, right) == 1
    assert compare_fingerprints(left, tmp_path / "missing.json") == 2


def test_fingerprint_compare_rejects_incomplete_document(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text('{"database":"fixture_db"}', encoding="utf-8")
    right.write_text('{"database":"fixture_db"}', encoding="utf-8")

    assert compare_fingerprints(left, right) == 2


@pytest.mark.parametrize("payload", ["null", '{"database":"fixture_db"}'])
def test_fingerprint_compare_rejects_identically_malformed_documents(
    tmp_path: Path, payload: str
) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(payload, encoding="utf-8")
    right.write_text(payload, encoding="utf-8")

    assert compare_fingerprints(left, right) == 2


def test_fingerprint_compare_requires_same_postgres_version(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    payload = {
        "format_version": 1,
        "database": "fixture_db",
        "postgres_server_version_num": "180006",
        "schema_sha256": "a" * 64,
        "content_sha256": hashlib.sha256(b"[]").hexdigest(),
        "table_count": 0,
        "row_count": 0,
        "tables": [],
    }
    left.write_text(json.dumps(payload), encoding="utf-8")
    payload["postgres_server_version_num"] = "180007"
    right.write_text(json.dumps(payload), encoding="utf-8")

    assert compare_fingerprints(left, right) == 1


def test_restore_skips_a_declared_omission_whose_only_file_differs_in_case(
    tmp_path: Path,
) -> None:
    """The official loader resolves ``<table>.sql`` exactly and skips on a miss.

    ``mental_healths_large`` ships ``facilities.sql`` for a table its restore order
    spells ``Facilities``, so upstream builds its reference database without it.
    Loading the lowercase file here would put 34 tables in this database that the
    scorer's does not have. See docs/research-log.md D-072.
    """
    (tmp_path / "facilities.sql").write_text("SELECT 1;\n", encoding="utf-8")
    client = RecordingClient()

    restore_database(
        client,
        database="fixture_db",
        dump_directory=tmp_path,
        restore_order=("Facilities",),
        omitted_tables=("Facilities",),
    )

    assert not any(str(call).endswith("facilities.sql") for call in client.calls)


def test_restore_rejects_an_omission_whose_exact_file_is_present(
    tmp_path: Path,
) -> None:
    """A declared omission must describe a real upstream skip, not hide a file."""
    (tmp_path / "Facilities.sql").write_text("SELECT 1;\n", encoding="utf-8")
    client = RecordingClient()

    with pytest.raises(DatabaseOperationError, match="omitted dump file exists"):
        restore_database(
            client,
            database="fixture_db",
            dump_directory=tmp_path,
            restore_order=("Facilities",),
            omitted_tables=("Facilities",),
        )
    assert client.calls == []

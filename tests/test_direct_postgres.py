from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from psycopg.conninfo import conninfo_to_dict

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.direct_postgres import (
    AttestedDirectPostgresTransport,
    DirectPostgresConfigurationError,
    DirectPostgresInfrastructureError,
    RUNTIME_IDENTITY_ATTESTATION_SQL,
    direct_postgres_connection_target_sha256,
)
from omni_benchmark.direct_runtime_binding import DirectDatabaseIdentity
from omni_benchmark.direct_sql_capture import (
    DirectDatabaseAttestation,
    DirectSqlCapture,
)
from omni_benchmark.postgres_isolation import EXECUTION_ROLE_ATTESTATION_SQL
from tests.direct_capture_fixtures import (
    BoundPublicTools,
    SequenceModel,
    prepared_attempt,
    runtime_binding,
)
from tests.execution_fixtures import SyntheticConnection


PG_ENVIRONMENT = {
    "PGHOST": "public-reader.example.test",
    "PGPORT": "5432",
    "PGDATABASE": "neondb",
    "PGUSER": "omni_benchmark_reader",
    "PGPASSWORD": "fixture-reader-password",
    "PGSSLMODE": "verify-full",
    "PGSSLROOTCERT": "system",
}
_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64
_SHA_E = "e" * 64


def _database_identity(
    environment: Mapping[str, str] = PG_ENVIRONMENT,
    **changes: object,
) -> DirectDatabaseIdentity:
    value = {
        "backend": "postgresql",
        "connection_target_sha256": direct_postgres_connection_target_sha256(
            host=environment["PGHOST"],
            port=int(environment.get("PGPORT", "5432")),
            physical_database=environment["PGDATABASE"],
            runtime_role=environment["PGUSER"],
        ),
        "content_sha256": _SHA_A,
        "database_record_sha256": _SHA_B,
        "deployment_identity_sha256": _SHA_C,
        "inventory_sha256": _SHA_D,
        "physical_database": environment["PGDATABASE"],
        "postgres_server_version_num": 180000,
        "runtime_role": environment["PGUSER"],
        "schema_sha256": _SHA_E,
        "selected_database": "archeology_scan_large",
    }
    value.update(changes)
    return DirectDatabaseIdentity.from_dict(value, environment={})


class AuditCursor:
    def __init__(
        self,
        row: object,
        events: list[tuple[object, ...]],
        *,
        identity_row: object = ("neondb", "omni_benchmark_reader", 180000),
        fail_execute: bool = False,
    ) -> None:
        self._row = row
        self._events = events
        self._identity_row = identity_row
        self._statement = ""
        self._fail_execute = fail_execute

    def __enter__(self) -> AuditCursor:
        self._events.append(("cursor_enter",))
        return self

    def __exit__(self, *_: object) -> None:
        self._events.append(("cursor_exit",))

    def execute(self, statement: object) -> None:
        self._statement = str(statement)
        self._events.append(("audit_execute", str(statement)))
        if self._fail_execute:
            raise RuntimeError("server leaked fixture-reader-password")

    def fetchone(self) -> object:
        self._events.append(("fetchone",))
        if self._statement == RUNTIME_IDENTITY_ATTESTATION_SQL:
            return self._identity_row
        return self._row


class AuditConnection:
    def __init__(
        self,
        row: object,
        events: list[tuple[object, ...]],
        *,
        identity_row: object = ("neondb", "omni_benchmark_reader", 180000),
        fail_execute: bool = False,
        fail_close: bool = False,
    ) -> None:
        self._row = row
        self._events = events
        self._identity_row = identity_row
        self._fail_execute = fail_execute
        self._fail_close = fail_close

    def cursor(self) -> AuditCursor:
        self._events.append(("cursor",))
        return AuditCursor(
            self._row,
            self._events,
            identity_row=self._identity_row,
            fail_execute=self._fail_execute,
        )

    def close(self) -> None:
        self._events.append(("audit_close",))
        if self._fail_close:
            raise RuntimeError("close leaked fixture-reader-password")


class AttestedQueryConnection:
    def __init__(
        self,
        query_connection: Any,
        events: list[tuple[Any, ...]],
        *,
        audit_row: object = ("omni_benchmark_reader", False),
    ) -> None:
        self._query_connection = query_connection
        self._events = events
        self._audit_row = audit_row
        self._audit_complete = False

    def cursor(self) -> object:
        if not self._audit_complete:
            self._audit_complete = True
            return AuditCursor(self._audit_row, self._events)
        return self._query_connection.cursor()

    def commit(self) -> None:
        self._query_connection.commit()

    def rollback(self) -> None:
        self._query_connection.rollback()

    def cancel_safe(self) -> None:
        self._query_connection.cancel_safe()

    def close(self) -> None:
        self._query_connection.close()


class SequenceConnector:
    def __init__(self, responses: list[object]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[str, Mapping[str, object]]] = []

    def __call__(self, conninfo: str, **kwargs: object) -> object:
        self.calls.append((conninfo, dict(kwargs)))
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class HostileEnvironment(Mapping[str, str]):
    def __getitem__(self, key: str) -> str:
        raise RuntimeError(f"environment access leaked {key} fixture-reader-password")

    def __iter__(self) -> Iterator[str]:
        return iter(PG_ENVIRONMENT)

    def __len__(self) -> int:
        return len(PG_ENVIRONMENT)

    def get(self, key: str, default: object = None) -> str:
        raise RuntimeError(f"environment get leaked {key} fixture-reader-password")


class HostileSslMode(str):
    def __hash__(self) -> int:
        raise RuntimeError("ssl coercion leaked fixture-reader-password")


class HostileAuditRow(Sequence[object]):
    def __init__(self, *, fail_on: str) -> None:
        self._fail_on = fail_on

    def __len__(self) -> int:
        if self._fail_on == "len":
            raise RuntimeError("row length leaked fixture-reader-password")
        return 2

    def __getitem__(self, index: int) -> object:
        raise RuntimeError(f"row item {index} leaked fixture-reader-password")


def _store(tmp_path: Path, name: str) -> ArtifactStore:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return ArtifactStore(workspace, Path("runs") / name)


def test_transport_maps_verified_live_audit_to_exact_attestation() -> None:
    events: list[tuple[object, ...]] = []
    audit = AuditConnection(("omni_benchmark_reader", False), events)
    query = AuditConnection(("omni_benchmark_reader", False), events)
    connector = SequenceConnector([audit, query])
    environment = {
        **PG_ENVIRONMENT,
        "DATABASE_URL": "postgresql://admin:secret@elsewhere/private",
    }

    transport = AttestedDirectPostgresTransport(
        environment,
        expected_identity=_database_identity(environment),
        connector=connector,
    )

    assert transport.execution_attestation == DirectDatabaseAttestation(
        role_is_read_only=True,
        no_execute_on_non_system_functions=True,
    )
    assert transport.runtime_identity == _database_identity(environment)
    with pytest.raises(FrozenInstanceError):
        transport.runtime_identity.runtime_role = "changed"  # type: ignore[misc]
    assert transport.connect() is query
    assert events.count(("audit_execute", str(EXECUTION_ROLE_ATTESTATION_SQL))) == 2
    assert events.count(("audit_close",)) == 1
    assert len(connector.calls) == 2
    for conninfo, kwargs in connector.calls:
        parsed = conninfo_to_dict(conninfo)
        assert parsed == {
            "connect_timeout": "10",
            "dbname": "neondb",
            "host": "public-reader.example.test",
            "options": "-c default_transaction_read_only=on",
            "password": "fixture-reader-password",
            "port": "5432",
            "sslmode": "verify-full",
            "sslrootcert": "system",
            "user": "omni_benchmark_reader",
        }
        assert set(kwargs) == {"cursor_factory"}
    assert "fixture-reader-password" not in repr(transport)
    assert "public-reader.example.test" not in repr(transport)


def test_execution_authority_changes_when_connector_is_replaced() -> None:
    events: list[tuple[object, ...]] = []
    connector = SequenceConnector(
        [AuditConnection(("omni_benchmark_reader", False), events)]
    )
    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
    )
    original = transport.execution_authority

    object.__setattr__(transport, "_connector", object())

    assert transport.execution_authority != original


def test_every_fresh_connection_is_attested_before_it_is_returned() -> None:
    events: list[tuple[object, ...]] = []
    preflight = AuditConnection(("omni_benchmark_reader", False), events)
    first = AuditConnection(("omni_benchmark_reader", False), events)
    second = AuditConnection(("omni_benchmark_reader", False), events)
    connector = SequenceConnector([preflight, first, second])

    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
    )

    assert transport.connect() is first
    assert transport.connect() is second
    assert len(connector.calls) == 3
    assert events.count(("audit_execute", str(EXECUTION_ROLE_ATTESTATION_SQL))) == 3
    assert events.count(("audit_close",)) == 1


@pytest.mark.parametrize(
    ("audit_row", "fail_execute"),
    [
        (("wrong_user", False), False),
        (("omni_benchmark_reader", False), True),
    ],
)
def test_failed_fresh_connection_audit_is_sanitized_and_closes(
    audit_row: object,
    fail_execute: bool,
) -> None:
    preflight_events: list[tuple[object, ...]] = []
    query_events: list[tuple[object, ...]] = []
    connector = SequenceConnector(
        [
            AuditConnection(("omni_benchmark_reader", False), preflight_events),
            AuditConnection(
                audit_row,
                query_events,
                fail_execute=fail_execute,
            ),
        ]
    )
    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
    )

    with pytest.raises(DirectPostgresInfrastructureError) as captured:
        transport.connect()

    assert str(captured.value) == "direct PostgreSQL privilege attestation failed"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert query_events[-1] == ("audit_close",)


def test_conninfo_construction_failure_is_fully_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaked = RuntimeError("conninfo leaked fixture-reader-password")
    leaked.__cause__ = ValueError("nested fixture-reader-password")

    def fail_conninfo(**_: object) -> str:
        raise leaked

    monkeypatch.setattr(
        "omni_benchmark.direct_postgres.make_conninfo",
        fail_conninfo,
    )
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError) as captured:
        AttestedDirectPostgresTransport(
            PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
        )

    error = captured.value
    assert str(error) == "direct PostgreSQL connection configuration failed"
    assert error.args == ("direct PostgreSQL connection configuration failed",)
    assert "fixture-reader-password" not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert connector.calls == []


@pytest.mark.parametrize(
    "environment",
    [
        HostileEnvironment(),
        {**PG_ENVIRONMENT, "PGSSLMODE": HostileSslMode("verify-full")},
    ],
)
def test_hostile_environment_failures_are_fully_sanitized(
    environment: Mapping[str, str],
) -> None:
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError) as captured:
        AttestedDirectPostgresTransport(
            environment,
            expected_identity=_database_identity(),
            connector=connector,
        )

    error = captured.value
    assert str(error) == "direct PostgreSQL environment validation failed"
    assert error.args == ("direct PostgreSQL environment validation failed",)
    assert "fixture-reader-password" not in str(error)
    assert "fixture-reader-password" not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert connector.calls == []


@pytest.mark.parametrize(
    "missing",
    ["PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD"],
)
def test_required_external_pg_environment_fails_before_connecting(
    missing: str,
) -> None:
    connector = SequenceConnector([])
    environment = {
        key: value for key, value in PG_ENVIRONMENT.items() if key != missing
    }

    with pytest.raises(DirectPostgresConfigurationError, match=missing):
        AttestedDirectPostgresTransport(
            environment,
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("PGPORT", "0"),
        ("PGPORT", "65536"),
        ("PGPORT", "not-a-port"),
        ("PGSSLMODE", "prefer"),
        ("PGSSLMODE", "require"),
        ("PGSSLMODE", "verify-ca"),
        ("PGHOST", "bad\x00host"),
    ],
)
def test_invalid_pg_environment_fails_closed(
    field: str,
    value: str,
) -> None:
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError, match=field):
        AttestedDirectPostgresTransport(
            {**PG_ENVIRONMENT, field: value},
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []


@pytest.mark.parametrize(
    "row",
    [
        ("other_reader", False),
        ("omni_benchmark_reader", True),
        ("omni_benchmark_reader", 0),
        ("omni_benchmark_reader", False, "extra"),
        None,
    ],
)
def test_failed_privilege_attestation_is_sanitized_and_closes(row: object) -> None:
    events: list[tuple[object, ...]] = []
    connector = SequenceConnector([AuditConnection(row, events)])

    with pytest.raises(DirectPostgresInfrastructureError) as captured:
        AttestedDirectPostgresTransport(
            PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
        )

    assert str(captured.value) == "direct PostgreSQL privilege attestation failed"
    assert "fixture-reader-password" not in repr(captured.value)
    assert events[-1] == ("audit_close",)


@pytest.mark.parametrize("fail_on", ["len", "getitem"])
@pytest.mark.parametrize("connection_stage", ["preflight", "fresh"])
def test_hostile_audit_row_is_sanitized_and_connection_closes(
    fail_on: str,
    connection_stage: str,
) -> None:
    preflight_events: list[tuple[object, ...]] = []
    rejected_events: list[tuple[object, ...]] = []
    hostile_connection = AuditConnection(
        HostileAuditRow(fail_on=fail_on),
        rejected_events,
    )
    if connection_stage == "preflight":
        connector = SequenceConnector([hostile_connection])
    else:
        connector = SequenceConnector(
            [
                AuditConnection(
                    ("omni_benchmark_reader", False),
                    preflight_events,
                ),
                hostile_connection,
            ]
        )

    with pytest.raises(DirectPostgresInfrastructureError) as captured:
        transport = AttestedDirectPostgresTransport(
            PG_ENVIRONMENT,
            expected_identity=_database_identity(),
            connector=connector,
        )
        transport.connect()

    error = captured.value
    assert str(error) == "direct PostgreSQL privilege attestation failed"
    assert error.args == ("direct PostgreSQL privilege attestation failed",)
    assert "fixture-reader-password" not in str(error)
    assert "fixture-reader-password" not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert rejected_events[-1] == ("audit_close",)


@pytest.mark.parametrize(
    "audit",
    [
        RuntimeError("driver leaked fixture-reader-password"),
        AuditConnection(
            ("omni_benchmark_reader", False),
            [],
            fail_execute=True,
        ),
        AuditConnection(
            ("omni_benchmark_reader", False),
            [],
            fail_close=True,
        ),
    ],
)
def test_audit_infrastructure_failures_never_leak_driver_details(
    audit: object,
) -> None:
    connector = SequenceConnector([audit])

    with pytest.raises(DirectPostgresInfrastructureError) as captured:
        AttestedDirectPostgresTransport(
            PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
        )

    assert str(captured.value) == "direct PostgreSQL privilege attestation failed"
    assert "fixture-reader-password" not in repr(captured.value)


def test_later_connection_failure_is_typed_and_sanitized() -> None:
    events: list[tuple[object, ...]] = []
    connector = SequenceConnector(
        [
            AuditConnection(("omni_benchmark_reader", False), events),
            RuntimeError("connect leaked fixture-reader-password"),
        ]
    )
    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
    )

    with pytest.raises(DirectPostgresInfrastructureError) as captured:
        transport.connect()

    assert str(captured.value) == "direct PostgreSQL connection failed"
    assert "fixture-reader-password" not in repr(captured.value)


def test_direct_capture_closes_attested_query_connection(tmp_path: Path) -> None:
    events: list[tuple[Any, ...]] = []
    connector = SequenceConnector(
        [
            AuditConnection(("omni_benchmark_reader", False), events),
            AttestedQueryConnection(
                SyntheticConnection({"SELECT 1": [(1,)]}, events),
                events,
            ),
        ]
    )
    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
    )
    store = _store(tmp_path, "success")
    binding = runtime_binding(database=transport.runtime_identity)

    model = SequenceModel(binding, [{"type": "answer", "sql": "SELECT 1"}])
    result = DirectSqlCapture(
        prepared=prepared_attempt(
            binding,
            model=model,
            database=transport,
            public_tools=BoundPublicTools(binding),
            artifact_store=store,
        ),
    ).capture()

    assert result.generation_outcome == "answered"
    assert result.database_query_count == 1
    assert events[-1] == ("connection_close",)


class StatementFailure(Exception):
    sqlstate = "42601"


class FailingCursor:
    description = None

    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self._events = events

    def execute(self, sql: str) -> None:
        self._events.append(("execute", sql))
        if sql == "SELECT broken":
            raise StatementFailure("query leaked fixture-reader-password")

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        return []

    def nextset(self) -> bool:
        return False

    def close(self) -> None:
        self._events.append(("cursor_close",))


class StatementFailingConnection:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self._events = events

    def cursor(self) -> FailingCursor:
        return FailingCursor(self._events)

    def commit(self) -> None:
        self._events.append(("commit",))

    def rollback(self) -> None:
        self._events.append(("rollback",))

    def cancel_safe(self) -> None:
        self._events.append(("cancel_safe",))

    def close(self) -> None:
        self._events.append(("close",))


def test_sql_statement_failure_remains_evaluated_system_failure(
    tmp_path: Path,
) -> None:
    events: list[tuple[Any, ...]] = []
    connector = SequenceConnector(
        [
            AuditConnection(("omni_benchmark_reader", False), events),
            AttestedQueryConnection(StatementFailingConnection(events), events),
        ]
    )
    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
    )
    store = _store(tmp_path, "statement-failure")
    binding = runtime_binding(database=transport.runtime_identity)

    model = SequenceModel(binding, [{"type": "answer", "sql": "SELECT broken"}])
    result = DirectSqlCapture(
        prepared=prepared_attempt(
            binding,
            model=model,
            database=transport,
            public_tools=BoundPublicTools(binding),
            artifact_store=store,
        ),
    ).capture()

    assert result.generation_outcome == "errored"
    assert result.failure_class == "database_statement_error"
    assert result.failure_origin == "evaluated_system"
    assert events[-1] == ("close",)


def test_post_attestation_connect_failure_remains_infrastructure_failure(
    tmp_path: Path,
) -> None:
    events: list[tuple[Any, ...]] = []
    connector = SequenceConnector(
        [
            AuditConnection(("omni_benchmark_reader", False), events),
            RuntimeError("outage leaked fixture-reader-password"),
        ]
    )
    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT, expected_identity=_database_identity(), connector=connector
    )
    store = _store(tmp_path, "infrastructure-failure")
    binding = runtime_binding(database=transport.runtime_identity)

    model = SequenceModel(binding, [{"type": "answer", "sql": "SELECT 1"}])
    result = DirectSqlCapture(
        prepared=prepared_attempt(
            binding,
            model=model,
            database=transport,
            public_tools=BoundPublicTools(binding),
            artifact_store=store,
        ),
    ).capture()

    assert result.generation_outcome == "errored"
    assert result.failure_class == "database_infrastructure_error"
    assert result.failure_origin == "benchmark_infrastructure"

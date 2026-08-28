"""Unit tests for the pinned Psycopg disposable-template connector."""

from __future__ import annotations

import pytest
from psycopg.conninfo import conninfo_to_dict

from omni_benchmark.postgres_isolation import (
    PostgreSQLIsolationError,
    PsycopgTemplateIsolationProvider,
)


class FakeCursor:
    def __init__(
        self,
        events: list[tuple[object, ...]],
        *,
        role: str | None,
        fail: bool = False,
        unsafe: bool = False,
        fail_execute_at: int | None = None,
        execute_count: list[int] | None = None,
    ) -> None:
        self._events = events
        self._role = role
        self._fail = fail
        self._unsafe = unsafe
        self._fail_execute_at = fail_execute_at
        self._execute_count = execute_count if execute_count is not None else [0]

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return None

    def execute(self, query, parameters=None):  # type: ignore[no-untyped-def]
        self._execute_count[0] += 1
        self._events.append(("execute", type(query).__name__, parameters))
        if self._fail or self._execute_count[0] == self._fail_execute_at:
            raise RuntimeError("driver included password=private")

    def fetchone(self) -> tuple[str | None, bool]:
        self._events.append(("fetchone",))
        return self._role, self._unsafe


class FakeConnection:
    def __init__(
        self,
        events: list[tuple[object, ...]],
        *,
        role: str | None,
        fail: bool = False,
        unsafe: bool = False,
        fail_execute_at: int | None = None,
        execute_count: list[int] | None = None,
    ) -> None:
        self._events = events
        self._role = role
        self._fail = fail
        self._unsafe = unsafe
        self._fail_execute_at = fail_execute_at
        self._execute_count = execute_count if execute_count is not None else [0]

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        self.close()

    def cursor(self) -> FakeCursor:
        return FakeCursor(
            self._events,
            role=self._role,
            fail=self._fail,
            unsafe=self._unsafe,
            fail_execute_at=self._fail_execute_at,
            execute_count=self._execute_count,
        )

    def close(self) -> None:
        self._events.append(("close",))


class FakeConnector:
    def __init__(
        self,
        *,
        fail_admin: bool = False,
        unsafe_execution: bool = False,
        fail_execute_at: int | None = None,
    ) -> None:
        self.events: list[tuple[object, ...]] = []
        self.fail_admin = fail_admin
        self.unsafe_execution = unsafe_execution
        self.fail_execute_at = fail_execute_at
        self.execute_count = [0]

    def __call__(self, conninfo: str, **kwargs):  # type: ignore[no-untyped-def]
        parsed = conninfo_to_dict(conninfo)
        role = parsed.get("user")
        read_only_default = "default_transaction_read_only=on" in parsed.get(
            "options", ""
        )
        self.events.append(
            (
                "connect",
                role,
                kwargs.get("autocommit"),
                kwargs.get("cursor_factory").__name__,
                read_only_default,
            )
        )
        return FakeConnection(
            self.events,
            role=role,
            fail=self.fail_admin and kwargs.get("autocommit") is True,
            unsafe=self.unsafe_execution and role == "scorer",
            fail_execute_at=self.fail_execute_at,
            execute_count=self.execute_count,
        )


def test_provider_creates_connects_and_drops_one_private_template_clone() -> None:
    connector = FakeConnector()
    provider = PsycopgTemplateIsolationProvider(
        "host=localhost user=clone_admin password=private dbname=postgres",
        "host=localhost user=scorer password=reader-private dbname=postgres",
        {"fixture": "fixture_template"},
        connector=connector,
    )

    isolate = provider.acquire("fixture")
    scoring = isolate.connect_scoring()
    scoring.close()
    trusted = isolate.connect_trusted()
    trusted.close()
    isolate.reset()
    isolate.release()

    assert "private" not in repr(provider)
    assert "private" not in repr(isolate)
    assert [event for event in connector.events if event[0] == "connect"] == [
        ("connect", "clone_admin", True, "ClientCursor", False),
        ("connect", "scorer", None, "ClientCursor", True),
        ("connect", "clone_admin", None, "ClientCursor", False),
        ("connect", "clone_admin", True, "ClientCursor", False),
    ]
    execute_events = [event for event in connector.events if event[0] == "execute"]
    assert len(execute_events) == 6


@pytest.mark.parametrize(
    ("database", "template"),
    [("bad-name", "fixture_template"), ("fixture", "bad-template")],
)
def test_provider_rejects_unsafe_database_identifiers(
    database: str, template: str
) -> None:
    provider = PsycopgTemplateIsolationProvider(
        "host=localhost user=clone_admin dbname=postgres",
        "host=localhost user=scorer dbname=postgres",
        {database: template},
    )

    with pytest.raises(ValueError, match="identifier"):
        provider.acquire(database)


def test_provider_errors_are_sanitized_and_do_not_expose_conninfo() -> None:
    provider = PsycopgTemplateIsolationProvider(
        "host=localhost user=clone_admin password=private dbname=postgres",
        "host=localhost user=scorer password=reader-private dbname=postgres",
        {"fixture": "fixture_template"},
        connector=FakeConnector(fail_admin=True),
    )

    with pytest.raises(PostgreSQLIsolationError) as captured:
        provider.acquire("fixture")

    assert str(captured.value) == "cannot create or remove isolated PostgreSQL database"
    assert "private" not in repr(captured.value)


@pytest.mark.parametrize(
    ("admin", "execution"),
    [
        (
            "host=localhost user=shared dbname=postgres",
            "host=localhost user=shared dbname=postgres",
        ),
        (
            "host=localhost dbname=postgres",
            "host=localhost user=scorer dbname=postgres",
        ),
    ],
)
def test_provider_requires_explicit_distinct_admin_and_execution_roles(
    admin: str, execution: str
) -> None:
    with pytest.raises(ValueError, match="distinct explicit roles"):
        PsycopgTemplateIsolationProvider(
            admin,
            execution,
            {"fixture": "fixture_template"},
        )


def test_provider_rejects_execution_role_with_effective_write_privilege() -> None:
    connector = FakeConnector(unsafe_execution=True)
    provider = PsycopgTemplateIsolationProvider(
        "host=localhost user=clone_admin password=private dbname=postgres",
        "host=localhost user=scorer password=reader-private dbname=postgres",
        {"fixture": "fixture_template"},
        connector=connector,
    )
    isolate = provider.acquire("fixture")

    with pytest.raises(PostgreSQLIsolationError, match="restricted") as captured:
        isolate.connect_scoring()

    assert "private" not in repr(captured.value)
    assert connector.events[-1] == ("close",)


def test_clone_acl_failure_triggers_compensating_drop() -> None:
    connector = FakeConnector(fail_execute_at=2)
    provider = PsycopgTemplateIsolationProvider(
        "host=localhost user=clone_admin password=private dbname=postgres",
        "host=localhost user=scorer password=reader-private dbname=postgres",
        {"fixture": "fixture_template"},
        connector=connector,
    )

    with pytest.raises(PostgreSQLIsolationError, match="create isolated"):
        provider.acquire("fixture")

    execute_events = [event for event in connector.events if event[0] == "execute"]
    assert len(execute_events) == 4


def test_ambiguous_clone_creation_failure_triggers_compensating_drop() -> None:
    connector = FakeConnector(fail_execute_at=1)
    provider = PsycopgTemplateIsolationProvider(
        "host=localhost user=clone_admin password=private dbname=postgres",
        "host=localhost user=scorer password=reader-private dbname=postgres",
        {"fixture": "fixture_template"},
        connector=connector,
    )

    with pytest.raises(PostgreSQLIsolationError, match="create isolated"):
        provider.acquire("fixture")

    execute_events = [event for event in connector.events if event[0] == "execute"]
    assert len(execute_events) == 3

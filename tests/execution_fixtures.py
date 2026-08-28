"""Synthetic DB-API fixtures for sealed execution lifecycle tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any


class SyntheticDatabaseError(Exception):
    """A database error carrying the public PostgreSQL SQLSTATE contract."""

    def __init__(self, sqlstate: str | None = None) -> None:
        super().__init__("synthetic database failure")
        self.sqlstate = sqlstate


SyntheticResponse = Sequence[Sequence[Any]] | Exception | None


class SyntheticCursor:
    """Minimal cursor that records execution without interpreting SQL."""

    def __init__(
        self,
        connection: SyntheticConnection,
        responses: Mapping[str, SyntheticResponse],
    ) -> None:
        self._connection = connection
        self._responses = responses
        self._rows: tuple[tuple[Any, ...], ...] | None = None
        self.description: object | None = None

    def execute(self, sql: str) -> None:
        self._connection.events.append(("execute", sql))
        response = self._responses.get(sql)
        if isinstance(response, Exception):
            raise response
        if response is None:
            self._rows = None
            self.description = None
            return
        self._rows = tuple(tuple(row) for row in response)
        self.description = object()

    def fetchmany(self, size: int) -> list[tuple[Any, ...]]:
        self._connection.events.append(("fetchmany", size))
        assert self._rows is not None
        return list(self._rows[:size])

    def nextset(self) -> bool:
        self._connection.events.append(("nextset",))
        return False

    def close(self) -> None:
        self._connection.events.append(("cursor_close",))


class SyntheticConnection:
    """Minimal transaction-aware connection used by public conformance tests."""

    def __init__(
        self,
        responses: Mapping[str, SyntheticResponse],
        events: list[tuple[Any, ...]],
    ) -> None:
        self._responses = responses
        self.events = events

    def cursor(self) -> SyntheticCursor:
        self.events.append(("cursor",))
        return SyntheticCursor(self, self._responses)

    def commit(self) -> None:
        self.events.append(("commit",))

    def rollback(self) -> None:
        self.events.append(("rollback",))

    def cancel_safe(self) -> None:
        self.events.append(("cancel_safe",))

    def close(self) -> None:
        self.events.append(("connection_close",))


class SyntheticIsolate:
    """One leased database copy with reset and release observability."""

    def __init__(
        self,
        responses: Mapping[str, SyntheticResponse],
        events: list[tuple[Any, ...]],
    ) -> None:
        self._responses = responses
        self._events = events

    def connect_scoring(self) -> SyntheticConnection:
        self._events.append(("connect_scoring",))
        return SyntheticConnection(self._responses, self._events)

    def connect_trusted(self) -> SyntheticConnection:
        self._events.append(("connect_trusted",))
        return SyntheticConnection(self._responses, self._events)

    def reset(self) -> None:
        self._events.append(("reset",))

    def release(self) -> None:
        self._events.append(("release",))


class SyntheticIsolationProvider:
    """Provider that returns a fresh synthetic isolate per scorer."""

    def __init__(
        self,
        responses: Mapping[str, SyntheticResponse],
        *,
        isolate_factory: Callable[
            [Mapping[str, SyntheticResponse], list[tuple[Any, ...]]], SyntheticIsolate
        ] = SyntheticIsolate,
    ) -> None:
        self.responses = responses
        self.events: list[tuple[Any, ...]] = []
        self._isolate_factory = isolate_factory

    def acquire(self, database: str) -> SyntheticIsolate:
        self.events.append(("acquire", database))
        return self._isolate_factory(self.responses, self.events)

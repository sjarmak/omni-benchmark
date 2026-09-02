"""Shared shape of what one source reader hands the loader."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .custody import reject_forbidden_fields
from .generation_rows import ReaderError
from .rows import Row


@dataclass(frozen=True)
class ReleasedQuestion:
    """What the question release says about one instance other readers need."""

    database: str
    partition: str


@dataclass(frozen=True)
class SourceBatch:
    """Rows read from one source plus what was set aside and why."""

    source: str
    rows: Mapping[str, tuple[Row, ...]]
    dropped: Mapping[str, int]
    manifests: Mapping[str, str]
    notes: Mapping[str, Any]

    def count(self, table: str) -> int:
        return len(self.rows.get(table, ()))


class BatchBuilder:
    """Accumulates one source's rows, drop reasons, and manifest hashes."""

    def __init__(self, source: str, repo_root: Path) -> None:
        self.source = source
        self.repo_root = repo_root
        self._rows: dict[str, list[Row]] = defaultdict(list)
        self._dropped: Counter[str] = Counter()
        self._manifests: dict[str, str] = {}
        self._notes: dict[str, Any] = {}

    def add(self, *rows: Row) -> None:
        for row in rows:
            self._rows[row.table].append(row)

    def drop(self, reason: str, count: int = 1) -> None:
        self._dropped[reason] += count

    def manifest(self, path: Path) -> str:
        digest = file_sha256(path)
        self._manifests[relative_to(path, self.repo_root)] = digest
        return digest

    def note(self, key: str, value: Any) -> None:
        self._notes[key] = value

    def freeze(self) -> SourceBatch:
        return SourceBatch(
            source=self.source,
            rows=MappingProxyType(
                {table: tuple(rows) for table, rows in sorted(self._rows.items())}
            ),
            dropped=MappingProxyType(dict(sorted(self._dropped.items()))),
            manifests=MappingProxyType(dict(sorted(self._manifests.items()))),
            notes=MappingProxyType(dict(self._notes)),
        )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_to(path: Path, root: Path) -> str:
    """Repository-relative POSIX path, or the absolute path when outside root."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_json_object(path: Path) -> dict[str, Any]:
    """A JSON object from path, custody-checked; anything else is an error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ReaderError(f"{path}: cannot parse JSON: {error}") from error
    if not isinstance(value, dict):
        raise ReaderError(f"{path}: expected a JSON object")
    reject_forbidden_fields(value, str(path))
    return value


def collapse(values: list[Any]) -> tuple[Any, tuple[Any, ...]]:
    """The one distinct value, or (None, every distinct value) when they differ."""
    distinct = {
        json.dumps(value, sort_keys=True, default=str): value for value in values
    }
    if len(distinct) == 1:
        return next(iter(distinct.values())), ()
    return None, tuple(distinct[key] for key in sorted(distinct))

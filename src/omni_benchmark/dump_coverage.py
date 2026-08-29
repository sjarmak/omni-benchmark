"""Resolve per-table dump files for a restore.

Kept separate from the database client so the same resolution can be audited
offline, without a live PostgreSQL connection.

Dump filenames are selectors only; each file carries its own authoritative
``CREATE TABLE`` identifier. Upstream LiveSQLBench dumps spell some filenames in
the table's declared case and others in lower case, so resolution is
case-insensitive. It is deliberately not case-blind about omissions: a table
declared absent from a dump must have no file under any capitalization, because
treating a case variant as absence silently drops real data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class DumpCoverageError(RuntimeError):
    """Raised when a dump directory cannot be resolved unambiguously."""


@dataclass(frozen=True)
class TableDump:
    """One restore-order table and the dump file it resolved to, if any."""

    table: str
    path: Path | None
    case_mismatch: bool


@dataclass(frozen=True)
class DumpCoverage:
    """What a dump directory offers for one database's restore order."""

    database: str
    tables: tuple[TableDump, ...]
    omitted: tuple[TableDump, ...]

    @property
    def load_paths(self) -> tuple[Path, ...]:
        return tuple(entry.path for entry in self.tables if entry.path is not None)

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(entry.table for entry in self.tables if entry.path is None)

    @property
    def case_mismatched(self) -> tuple[TableDump, ...]:
        return tuple(entry for entry in self.tables if entry.case_mismatch)

    @property
    def contradicted_omissions(self) -> tuple[TableDump, ...]:
        return tuple(entry for entry in self.omitted if entry.path is not None)

    @property
    def is_complete(self) -> bool:
        return not self.missing and not self.contradicted_omissions


def index_dump_files(dump_root: Path) -> dict[str, Path]:
    """Map each casefolded dump stem to its file.

    Raises when two files differ only in capitalization, since no resolution of
    such a pair can be justified from the filename alone.
    """
    index: dict[str, Path] = {}
    for path in sorted(dump_root.glob("*.sql")):
        key = path.stem.casefold()
        collision = index.get(key)
        if collision is not None:
            raise DumpCoverageError(
                "dump directory has case-colliding files: "
                f"{collision.name} and {path.name}"
            )
        index[key] = path
    return index


def describe_dump_coverage(
    *,
    database: str,
    dump_root: Path,
    restore_order: tuple[str, ...],
    omitted_tables: tuple[str, ...] = (),
) -> DumpCoverage:
    """Report how a restore order resolves against a dump directory.

    Reports rather than raises, so an audit can describe every database before
    any of them is restored.
    """
    index = index_dump_files(dump_root)
    omitted = set(omitted_tables)
    loaded: list[TableDump] = []
    skipped: list[TableDump] = []
    for table in restore_order:
        path = index.get(table.casefold())
        entry = TableDump(
            table=table,
            path=path,
            case_mismatch=path is not None and path.stem != table,
        )
        (skipped if table in omitted else loaded).append(entry)
    return DumpCoverage(database=database, tables=tuple(loaded), omitted=tuple(skipped))

"""Audit which dump files the official LiveSQLBench loader actually loads.

The pinned upstream script ``init-databases_postgresql_large_v1.sh`` builds each
reference database with::

    local sql_file="${db_folder}/${table}.sql"
    if [[ -f "$sql_file" ]]; then psql ... -f "${sql_file}"
    else echo "Warning: SQL file ${sql_file} not found for table ${table}"

The lookup is exact, and the archive spells some filenames in the table's
declared case and others in lower case. On the pinned Linux image the mismatched
names do not resolve, so the official reference database is built without those
tables and the questions that reference them cannot be answered there.

This module reproduces that resolution rather than repairing it. Loading a
lowercase file for a table the official loader skips would build a database that
holds more than the scorer's, so results on those questions would stop being
comparable to published LiveSQLBench numbers.

What is worth checking is fidelity: every table the official loader skips must be
recorded in the inventory's ``scorer_omitted_tables``, and nothing else may be.
That invariant is what :func:`describe_dump_coverage` reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TableDump:
    """One restore-order table and how the official loader resolves it."""

    table: str
    path: Path | None
    case_variant: Path | None

    @property
    def is_loaded(self) -> bool:
        return self.path is not None

    @property
    def skipped_over_a_case_variant(self) -> bool:
        """The official loader skips this table though the data is in the archive."""
        return self.path is None and self.case_variant is not None


@dataclass(frozen=True)
class DumpCoverage:
    """How one database's restore order resolves against its dump directory."""

    database: str
    tables: tuple[TableDump, ...]
    declared_omitted: frozenset[str]

    @property
    def loaded(self) -> tuple[TableDump, ...]:
        return tuple(entry for entry in self.tables if entry.is_loaded)

    @property
    def skipped(self) -> tuple[TableDump, ...]:
        """Tables the official loader passes over, for any reason."""
        return tuple(entry for entry in self.tables if not entry.is_loaded)

    @property
    def undeclared_skips(self) -> tuple[str, ...]:
        """Skipped upstream but absent from ``scorer_omitted_tables``."""
        return tuple(
            entry.table
            for entry in self.skipped
            if entry.table not in self.declared_omitted
        )

    @property
    def overdeclared_omissions(self) -> tuple[str, ...]:
        """Declared omitted though the official loader does load them."""
        return tuple(
            entry.table for entry in self.loaded if entry.table in self.declared_omitted
        )

    @property
    def reproduces_official_loader(self) -> bool:
        return not self.undeclared_skips and not self.overdeclared_omissions


def index_case_variants(dump_root: Path) -> dict[str, tuple[Path, ...]]:
    """Group dump files by casefolded stem.

    Used only to explain a skip. Resolution itself never consults this, because
    the official loader does not.
    """
    variants: dict[str, list[Path]] = {}
    for path in sorted(dump_root.glob("*.sql")):
        variants.setdefault(path.stem.casefold(), []).append(path)
    return {key: tuple(value) for key, value in variants.items()}


def describe_dump_coverage(
    *,
    database: str,
    dump_root: Path,
    restore_order: tuple[str, ...],
    omitted_tables: tuple[str, ...] = (),
) -> DumpCoverage:
    """Report how the official loader resolves one database's restore order.

    Reports rather than raises, so an audit can describe every database in one
    pass.
    """
    variants = index_case_variants(dump_root)
    entries: list[TableDump] = []
    for table in restore_order:
        exact = dump_root / f"{table}.sql"
        if exact.is_file():
            entries.append(TableDump(table=table, path=exact, case_variant=None))
            continue
        others = tuple(
            path for path in variants.get(table.casefold(), ()) if path != exact
        )
        entries.append(
            TableDump(
                table=table,
                path=None,
                case_variant=others[0] if others else None,
            )
        )
    return DumpCoverage(
        database=database,
        tables=tuple(entries),
        declared_omitted=frozenset(omitted_tables),
    )

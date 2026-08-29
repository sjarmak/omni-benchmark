from __future__ import annotations

from pathlib import Path

import pytest

from omni_benchmark.dump_coverage import (
    DumpCoverageError,
    describe_dump_coverage,
    index_dump_files,
)


def _write(root: Path, *names: str) -> None:
    for name in names:
        (root / f"{name}.sql").write_text(f"-- {name}\n", encoding="utf-8")


def test_index_rejects_case_colliding_dump_files(tmp_path: Path) -> None:
    _write(tmp_path, "Facilities", "facilities")

    with pytest.raises(DumpCoverageError, match="case-colliding"):
        index_dump_files(tmp_path)


def test_index_ignores_files_that_are_not_dumps(tmp_path: Path) -> None:
    _write(tmp_path, "present")
    (tmp_path / "notes.txt").write_text("ignored\n", encoding="utf-8")

    assert set(index_dump_files(tmp_path)) == {"present"}


def test_coverage_resolves_a_dump_file_differing_only_in_capitalization(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "facilities")

    coverage = describe_dump_coverage(
        database="fixture_db", dump_root=tmp_path, restore_order=("Facilities",)
    )

    assert coverage.load_paths == (tmp_path / "facilities.sql",)
    assert coverage.missing == ()
    assert [entry.table for entry in coverage.case_mismatched] == ["Facilities"]


def test_coverage_reports_an_omission_contradicted_by_a_case_variant(
    tmp_path: Path,
) -> None:
    """Regression for omni-benchmark-39b, which dropped 71 tables this way."""
    _write(tmp_path, "facilities")

    coverage = describe_dump_coverage(
        database="fixture_db",
        dump_root=tmp_path,
        restore_order=("Facilities",),
        omitted_tables=("Facilities",),
    )

    assert [entry.table for entry in coverage.contradicted_omissions] == ["Facilities"]
    assert coverage.load_paths == ()


def test_coverage_keeps_a_genuine_upstream_omission(tmp_path: Path) -> None:
    _write(tmp_path, "present")

    coverage = describe_dump_coverage(
        database="fixture_db",
        dump_root=tmp_path,
        restore_order=("present", "upstream_missing"),
        omitted_tables=("upstream_missing",),
    )

    assert coverage.contradicted_omissions == ()
    assert coverage.missing == ()
    assert coverage.load_paths == (tmp_path / "present.sql",)


def test_coverage_reports_a_dump_missing_from_the_restore_order(tmp_path: Path) -> None:
    _write(tmp_path, "parent")

    coverage = describe_dump_coverage(
        database="fixture_db", dump_root=tmp_path, restore_order=("parent", "child")
    )

    assert coverage.missing == ("child",)
    assert coverage.load_paths == (tmp_path / "parent.sql",)


def test_coverage_preserves_restore_order(tmp_path: Path) -> None:
    _write(tmp_path, "child", "parent")

    coverage = describe_dump_coverage(
        database="fixture_db", dump_root=tmp_path, restore_order=("parent", "child")
    )

    assert coverage.load_paths == (
        tmp_path / "parent.sql",
        tmp_path / "child.sql",
    )

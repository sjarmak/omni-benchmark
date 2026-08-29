"""Fidelity of the dump audit to the pinned upstream loader.

The official ``init-databases_postgresql_large_v1.sh`` resolves each table as
``<table>.sql`` with an exact filename match and skips with a warning on a miss.
These tests pin that reproduction, not a repair of it.
"""

from __future__ import annotations

from pathlib import Path

from omni_benchmark.dump_coverage import describe_dump_coverage, index_case_variants


def _dump(root: Path, *names: str) -> None:
    for name in names:
        (root / name).write_text("SELECT 1;\n", encoding="utf-8")


def test_a_table_whose_file_matches_exactly_is_loaded(tmp_path: Path) -> None:
    _dump(tmp_path, "Facilities.sql")

    coverage = describe_dump_coverage(
        database="fixture", dump_root=tmp_path, restore_order=("Facilities",)
    )

    assert [entry.table for entry in coverage.loaded] == ["Facilities"]
    assert coverage.skipped == ()


def test_a_lowercase_file_does_not_satisfy_a_capitalized_table(tmp_path: Path) -> None:
    """The upstream defect: the data ships, and the official loader cannot see it."""
    _dump(tmp_path, "facilities.sql")

    coverage = describe_dump_coverage(
        database="fixture",
        dump_root=tmp_path,
        restore_order=("Facilities",),
        omitted_tables=("Facilities",),
    )

    (skipped,) = coverage.skipped
    assert skipped.path is None
    assert skipped.case_variant is not None
    assert skipped.case_variant.name == "facilities.sql"
    assert skipped.skipped_over_a_case_variant


def test_a_table_absent_from_the_archive_is_skipped_without_a_variant(
    tmp_path: Path,
) -> None:
    """The genuine omission on labor_certification_applications_large."""
    coverage = describe_dump_coverage(
        database="fixture",
        dump_root=tmp_path,
        restore_order=("Missing",),
        omitted_tables=("Missing",),
    )

    (skipped,) = coverage.skipped
    assert skipped.case_variant is None
    assert not skipped.skipped_over_a_case_variant
    assert coverage.reproduces_official_loader


def test_an_undeclared_skip_breaks_fidelity(tmp_path: Path) -> None:
    _dump(tmp_path, "facilities.sql")

    coverage = describe_dump_coverage(
        database="fixture", dump_root=tmp_path, restore_order=("Facilities",)
    )

    assert coverage.undeclared_skips == ("Facilities",)
    assert not coverage.reproduces_official_loader


def test_declaring_an_omission_the_loader_actually_loads_breaks_fidelity(
    tmp_path: Path,
) -> None:
    _dump(tmp_path, "Facilities.sql")

    coverage = describe_dump_coverage(
        database="fixture",
        dump_root=tmp_path,
        restore_order=("Facilities",),
        omitted_tables=("Facilities",),
    )

    assert coverage.overdeclared_omissions == ("Facilities",)
    assert not coverage.reproduces_official_loader


def test_both_capitalizations_present_resolves_to_the_exact_name(
    tmp_path: Path,
) -> None:
    """No ambiguity exists: the official loader names one file and finds it."""
    _dump(tmp_path, "Facilities.sql", "facilities.sql")

    coverage = describe_dump_coverage(
        database="fixture", dump_root=tmp_path, restore_order=("Facilities",)
    )

    (loaded,) = coverage.loaded
    assert loaded.path is not None
    assert loaded.path.name == "Facilities.sql"


def test_case_variants_are_grouped_and_non_sql_files_ignored(tmp_path: Path) -> None:
    _dump(tmp_path, "Facilities.sql", "facilities.sql", "notes.txt")

    variants = index_case_variants(tmp_path)

    assert [path.name for path in variants["facilities"]] == [
        "Facilities.sql",
        "facilities.sql",
    ]
    assert "notes" not in variants


def test_restore_order_is_preserved(tmp_path: Path) -> None:
    _dump(tmp_path, "a.sql", "b.sql", "c.sql")

    coverage = describe_dump_coverage(
        database="fixture", dump_root=tmp_path, restore_order=("c", "a", "b")
    )

    assert [entry.table for entry in coverage.tables] == ["c", "a", "b"]

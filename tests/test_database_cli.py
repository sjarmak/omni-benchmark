from __future__ import annotations

import hashlib
import json
from pathlib import Path

import omni_benchmark.database_cli as database_cli
from omni_benchmark.database_cli import DEFAULT_INVENTORY, main
from omni_benchmark.database_inventory import load_database_inventory

RESTORE_ORDER = Path("config/databases/restore-order-large-v1.json")


def test_cli_validates_inventory(capsys) -> None:
    assert (
        main(
            [
                "--inventory",
                "config/databases/livesqlbench-large-v1.json",
                "validate-inventory",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt == {
        "benchmark": "LiveSQLBench Large-v1",
        "canary": "archeology_scan_large",
        "database_count": 18,
        "postgres_major": 18,
    }


def test_cli_fingerprints_dump_without_emitting_file_contents(
    tmp_path: Path, capsys
) -> None:
    dump = tmp_path / "dump"
    dump.mkdir()
    (dump / "table.sql").write_text(
        "INSERT INTO table VALUES ('sensitive public row');\n", encoding="utf-8"
    )

    assert main(["fingerprint-dump", "--dump-directory", str(dump)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["file_count"] == 1
    assert "sensitive public row" not in json.dumps(receipt)


def test_cli_compare_preserves_parity_exit_contract(tmp_path: Path) -> None:
    payload = {
        "database": "fixture_db",
        "format_version": 1,
        "postgres_server_version_num": "180006",
        "schema_sha256": "a" * 64,
        "content_sha256": hashlib.sha256(b"[]").hexdigest(),
        "table_count": 0,
        "row_count": 0,
        "tables": [],
    }
    scorer = tmp_path / "scorer.json"
    mirror = tmp_path / "mirror.json"
    scorer.write_text(json.dumps(payload), encoding="utf-8")
    mirror.write_text(json.dumps(payload), encoding="utf-8")

    assert (
        main(
            [
                "compare",
                "--scorer",
                str(scorer),
                "--mirror",
                str(mirror),
            ]
        )
        == 0
    )


def test_cli_restore_runs_all_preflights_before_restore(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(database_cli, "PostgresClient", lambda: object())
    monkeypatch.setattr(
        database_cli,
        "verify_database_dump",
        lambda database, path: events.append("dump"),
    )
    monkeypatch.setattr(
        database_cli,
        "verify_restore_order",
        lambda inventory, path: {"archeology_scan_large": ("sites",)},
    )
    monkeypatch.setattr(
        database_cli,
        "preflight_restore",
        lambda client, **kwargs: events.append("postgres"),
    )
    monkeypatch.setattr(
        database_cli,
        "restore_database",
        lambda client, **kwargs: events.append("restore"),
    )

    assert (
        main(
            [
                "restore",
                "--database",
                "archeology_scan_large",
                "--dump-directory",
                str(tmp_path / "dump"),
                "--restore-order",
                str(tmp_path / "order.json"),
            ]
        )
        == 0
    )
    assert events == ["dump", "postgres", "restore"]


def test_cli_role_and_database_fingerprint_dispatch(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []
    client = object()
    monkeypatch.setattr(database_cli, "PostgresClient", lambda: client)
    monkeypatch.setattr(
        database_cli,
        "provision_readonly_role",
        lambda observed, **kwargs: events.append("provision"),
    )
    monkeypatch.setattr(
        database_cli,
        "verify_readonly_role",
        lambda observed, **kwargs: events.append("verify"),
    )
    monkeypatch.setattr(
        database_cli,
        "fingerprint_database",
        lambda observed, database: {"database": database},
    )

    common = ["--database", "archeology_scan_large", "--role", "reader"]
    assert main(["provision-readonly-role", *common]) == 0
    assert main(["verify-readonly-role", *common]) == 0
    output = tmp_path / "fingerprint.json"
    assert (
        main(
            [
                "fingerprint-database",
                "--database",
                "archeology_scan_large",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert events == ["provision", "verify"]
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "database": "archeology_scan_large"
    }


def _upstream_dump_tree(root: Path, inventory) -> None:
    """Mirror the archive: exact-case files load, case-variant files are skipped.

    The upstream archive spells some dump files in the table's declared case and
    others in lower case. Reproducing that split here keeps these tests honest
    about what the official loader can and cannot see.
    """
    orders = json.loads(RESTORE_ORDER.read_text(encoding="utf-8"))
    for database in inventory.databases:
        directory = root / f"{database.name}_template"
        directory.mkdir(parents=True)
        omitted = set(database.scorer_omitted_tables)
        for table in orders[database.name]:
            name = table.lower() if table in omitted else table
            if name == table and table in omitted:
                continue  # absent from the archive under any spelling
            (directory / f"{name}.sql").write_text(f"-- {table}\n", encoding="utf-8")


def test_cli_dump_coverage_confirms_the_inventory_reproduces_the_official_loader(
    tmp_path: Path, capsys
) -> None:
    """The committed omissions must match what upstream actually skips."""
    inventory = load_database_inventory(DEFAULT_INVENTORY)
    _upstream_dump_tree(tmp_path, inventory)

    exit_code = main(
        [
            "verify-dump-coverage",
            "--dump-root",
            str(tmp_path),
            "--restore-order",
            str(RESTORE_ORDER),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert all(entry["reproduces_official_loader"] for entry in report)
    assert [entry["database"] for entry in report] == sorted(
        database.name for database in inventory.databases
    )
    skipped = {
        entry["database"]: entry["skipped_by_official_loader"] for entry in report
    }
    assert skipped["mental_healths_large"] == 34
    assert skipped["organ_transplant_large"] == 37


def test_cli_dump_coverage_flags_a_skip_the_inventory_does_not_declare(
    tmp_path: Path, capsys
) -> None:
    inventory = load_database_inventory(DEFAULT_INVENTORY)
    _upstream_dump_tree(tmp_path, inventory)
    orders = json.loads(RESTORE_ORDER.read_text(encoding="utf-8"))
    database = inventory.databases[0]
    declared = set(database.scorer_omitted_tables)
    loaded = next(t for t in orders[database.name] if t not in declared)
    (tmp_path / f"{database.name}_template" / f"{loaded}.sql").unlink()

    exit_code = main(
        [
            "verify-dump-coverage",
            "--dump-root",
            str(tmp_path),
            "--restore-order",
            str(RESTORE_ORDER),
        ]
    )
    report = json.loads(capsys.readouterr().out)
    entry = next(e for e in report if e["database"] == database.name)

    assert exit_code == 1
    assert entry["undeclared_skips"] == [loaded]
    assert not entry["reproduces_official_loader"]

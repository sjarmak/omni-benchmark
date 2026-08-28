from __future__ import annotations

import hashlib
import json
from pathlib import Path

import omni_benchmark.database_cli as database_cli
from omni_benchmark.database_cli import main


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

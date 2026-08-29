from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from .database_fingerprint import compare_fingerprints, fingerprint_database
from .dump_coverage import describe_dump_coverage
from .database_inventory import (
    fingerprint_dump_directory,
    load_database_inventory,
    parse_restore_order,
    verify_database_dump,
    verify_restore_order,
)
from .database_postgres import (
    PostgresClient,
    preflight_restore,
    provision_readonly_role,
    restore_database,
    verify_readonly_role,
)


DEFAULT_INVENTORY = Path("config/databases/livesqlbench-large-v1.json")


def _write_exclusive(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _describe_database_coverage(
    *, database: object, restore_order: tuple[str, ...], dump_root: Path
) -> dict[str, object]:
    """Summarize one database's dump resolution without contacting PostgreSQL."""
    coverage = describe_dump_coverage(
        database=database.name,
        dump_root=dump_root,
        restore_order=restore_order,
        omitted_tables=database.scorer_omitted_tables,
    )
    return {
        "database": coverage.database,
        "ordered_tables": len(restore_order),
        "resolvable": len(coverage.load_paths),
        "missing": list(coverage.missing),
        "case_mismatched": [entry.table for entry in coverage.case_mismatched],
        "contradicted_omissions": [
            {"table": entry.table, "dump_file": entry.path.name}
            for entry in coverage.contradicted_omissions
            if entry.path is not None
        ],
        "complete": coverage.is_complete,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Public LiveSQLBench database tooling")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate-inventory")

    dump = commands.add_parser("fingerprint-dump")
    dump.add_argument("--dump-directory", type=Path, required=True)

    order = commands.add_parser("prepare-restore-order")
    order.add_argument("--source", type=Path, required=True)
    order.add_argument("--output", type=Path, required=True)

    coverage = commands.add_parser("verify-dump-coverage")
    coverage.add_argument("--dump-root", type=Path, required=True)
    coverage.add_argument("--restore-order", type=Path, required=True)
    coverage.add_argument("--template-suffix", default="_template")

    restore = commands.add_parser("restore")
    restore.add_argument("--database", required=True)
    restore.add_argument("--dump-directory", type=Path, required=True)
    restore.add_argument("--restore-order", type=Path, required=True)

    role = commands.add_parser("provision-readonly-role")
    role.add_argument("--database", required=True)
    role.add_argument("--role", required=True)

    verify = commands.add_parser("verify-readonly-role")
    verify.add_argument("--database", required=True)
    verify.add_argument("--role", required=True)

    fingerprint = commands.add_parser("fingerprint-database")
    fingerprint.add_argument("--database", required=True)
    fingerprint.add_argument("--output", type=Path, required=True)

    compare = commands.add_parser("compare")
    compare.add_argument("--scorer", type=Path, required=True)
    compare.add_argument("--mirror", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "fingerprint-dump":
        result = fingerprint_dump_directory(args.dump_directory)
        print(
            json.dumps(
                {
                    "file_count": len(result.files),
                    "sha256": result.sha256,
                    "size_bytes": result.size_bytes,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "prepare-restore-order":
        inventory = load_database_inventory(args.inventory)
        orders = parse_restore_order(args.source.read_text(encoding="utf-8"))
        expected = {database.name for database in inventory.databases}
        if set(orders) != expected:
            raise ValueError("restore-order databases do not match inventory")
        _write_exclusive(args.output, orders)
        return 0
    if args.command == "compare":
        return compare_fingerprints(args.scorer, args.mirror)

    inventory = load_database_inventory(args.inventory)
    if args.command == "validate-inventory":
        print(
            json.dumps(
                {
                    "benchmark": inventory.benchmark,
                    "canary": inventory.canary,
                    "database_count": len(inventory.databases),
                    "postgres_major": inventory.postgres_major,
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "verify-dump-coverage":
        orders = verify_restore_order(inventory, args.restore_order)
        report = [
            _describe_database_coverage(
                database=database,
                restore_order=orders[database.name],
                dump_root=args.dump_root / f"{database.name}{args.template_suffix}",
            )
            for database in inventory.databases
        ]
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if all(entry["complete"] for entry in report) else 1

    database_by_name = {database.name: database for database in inventory.databases}
    if args.database not in database_by_name:
        raise ValueError(f"database is not in the public inventory: {args.database}")
    client = PostgresClient()
    if args.command == "restore":
        verify_database_dump(database_by_name[args.database], args.dump_directory)
        orders = verify_restore_order(inventory, args.restore_order)
        preflight_restore(
            client, postgres_major=inventory.postgres_major, owner_role="root"
        )
        restore_database(
            client,
            database=args.database,
            dump_directory=args.dump_directory,
            restore_order=orders[args.database],
            owner_role="root",
            omitted_tables=database_by_name[args.database].scorer_omitted_tables,
            continue_after_sql_error=database_by_name[
                args.database
            ].scorer_continues_after_sql_error,
        )
    elif args.command == "provision-readonly-role":
        provision_readonly_role(client, database=args.database, role=args.role)
    elif args.command == "verify-readonly-role":
        verify_readonly_role(client, database=args.database, role=args.role)
    elif args.command == "fingerprint-database":
        _write_exclusive(args.output, fingerprint_database(client, args.database))
    return 0

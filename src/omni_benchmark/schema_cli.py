from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .schema_ir import generate_public_schema_ir
from .schema_inspection import inspect_public_schema_sources
from .schema_sources import fetch_public_schema_sources


DEFAULT_INVENTORY = Path("config/public_schema_sources.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch pinned public LiveSQLBench schema metadata"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch")
    fetch.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    fetch.add_argument("--destination-root", type=Path, required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    inspect.add_argument("--source-root", type=Path, required=True)
    build = commands.add_parser("build")
    build.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    build.add_argument("--source-root", type=Path, required=True)
    build.add_argument("--output-root", type=Path, required=True)
    build.add_argument("--database", required=True)
    build.add_argument("--companion-hkb-ir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "fetch":
        result = fetch_public_schema_sources(
            args.inventory,
            args.destination_root,
        )
    elif args.command == "inspect":
        result = inspect_public_schema_sources(
            args.inventory,
            args.source_root,
        )
    else:
        result = generate_public_schema_ir(
            args.source_root,
            args.inventory,
            args.output_root,
            database=args.database,
            companion_hkb_ir=args.companion_hkb_ir,
        )
    print(json.dumps(result, sort_keys=True))
    return 0

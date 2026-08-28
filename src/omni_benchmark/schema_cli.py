from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "fetch":
        result = fetch_public_schema_sources(
            args.inventory,
            args.destination_root,
        )
    else:
        result = inspect_public_schema_sources(
            args.inventory,
            args.source_root,
        )
    print(json.dumps(result, sort_keys=True))
    return 0

"""Command-line interface for the public-only HKB preparation boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from omni_benchmark.hkb_ir import generate_public_hkb_ir
from omni_benchmark.hkb_sources import fetch_public_hkb_sources


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch and compile the pinned public LiveSQLBench HKB"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch = subparsers.add_parser("fetch", help="download and verify public HKB files")
    fetch.add_argument("--inventory", required=True, type=Path)
    fetch.add_argument("--destination-root", required=True, type=Path)
    build = subparsers.add_parser("build", help="generate deterministic public HKB IR")
    build.add_argument("--inventory", required=True, type=Path)
    build.add_argument("--source-root", required=True, type=Path)
    build.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicit public HKB preparation operation."""

    args = _parser().parse_args(argv)
    if args.command == "fetch":
        result = fetch_public_hkb_sources(args.inventory, args.destination_root)
    else:
        result = generate_public_hkb_ir(
            args.source_root, args.inventory, args.output_root
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0

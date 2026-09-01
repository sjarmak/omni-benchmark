"""Generate an append-only public-evidence measure review catalog."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .measure_review_catalog import (
    generate_workspace_measure_review_catalog,
    write_measure_review_catalog,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--target-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    catalog = generate_workspace_measure_review_catalog(
        arguments.workspace, arguments.target_config
    )
    write_measure_review_catalog(arguments.output, catalog)
    manifest = catalog["manifest"]
    summary = {
        key: value for key, value in manifest.items() if key != "ordered_candidate_ids"
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

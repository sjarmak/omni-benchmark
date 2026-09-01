"""Build the append-only offline R2-C5B and R2-M1 semantic bundles."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .measure_treatment_bundle import (
    build_workspace_measure_bundle_set,
    write_measure_bundle_set,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--target-config", type=Path, required=True)
    parser.add_argument("--accepted-catalog", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    bundle = build_workspace_measure_bundle_set(
        arguments.workspace,
        arguments.target_config,
        arguments.accepted_catalog,
    )
    write_measure_bundle_set(arguments.output_root, bundle)
    print(
        json.dumps(
            {
                "artifact_sha256": bundle.manifest["manifest"]["artifact_sha256"],
                "output_root": str(arguments.output_root),
                **bundle.manifest["summary"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

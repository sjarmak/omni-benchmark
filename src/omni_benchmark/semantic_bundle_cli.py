"""Publish a public-only Omni semantic bundle for one reviewed mapping."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .semantic_bundle_publication import publish_bundle_artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--hkb-ir", type=Path, required=True)
    parser.add_argument("--schema-ir", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--mapping-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    manifest = publish_bundle_artifacts(
        arguments.spec,
        arguments.hkb_ir,
        arguments.schema_ir,
        arguments.mapping,
        arguments.mapping_manifest,
        arguments.output_root,
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0

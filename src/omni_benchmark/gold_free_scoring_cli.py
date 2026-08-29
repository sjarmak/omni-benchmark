"""Command-line boundary for the gold-free scoring plumbing exercise."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .gold_free_scoring import run_self_consistency_exercise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare two public dev-A result artifacts for scorer self-consistency; "
            "this does not measure benchmark correctness."
        )
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--left-generation", type=Path, required=True)
    parser.add_argument("--left-result", type=Path, required=True)
    parser.add_argument("--right-generation", type=Path, required=True)
    parser.add_argument("--right-result", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the exercise once and print a canonical hash receipt."""

    arguments = _parser().parse_args(argv)
    workspace = arguments.workspace.resolve(strict=True)
    receipt = run_self_consistency_exercise(
        workspace,
        left_generation=arguments.left_generation,
        left_result=arguments.left_result,
        right_generation=arguments.right_generation,
        right_result=arguments.right_result,
        output_root=arguments.output_root,
    )
    print(json.dumps(receipt.as_dict(workspace), separators=(",", ":"), sort_keys=True))
    return 0

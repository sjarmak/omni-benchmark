#!/usr/bin/env python3
"""Regenerate the fixed public-only C1 retrieval sensitivity subset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from omni_benchmark.c1_retrieval_sensitivity import (
    create_c1_retrieval_sensitivity_subset,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    metadata = create_c1_retrieval_sensitivity_subset(arguments.workspace)
    print(json.dumps(metadata, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""User-run entry point for a values-free private attachment shape probe."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.custody import CustodyError, structure_probe_main


if __name__ == "__main__":
    try:
        exit_status = structure_probe_main()
    except CustodyError as error:
        print(f"probe failed: {error}", file=sys.stderr)
        exit_status = 1
    raise SystemExit(exit_status)

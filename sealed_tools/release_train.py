#!/usr/bin/env python3
"""User-run entry point for releasing committed dev-A labels only."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.custody import release_main


if __name__ == "__main__":
    raise SystemExit(release_main())

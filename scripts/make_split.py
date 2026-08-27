#!/usr/bin/env python3
"""Create the deterministic preregistered train/test split."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.split import split_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(split_main())

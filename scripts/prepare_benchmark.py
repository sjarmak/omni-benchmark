#!/usr/bin/env python3
"""Prepare the validated public-only LiveSQLBench manifest."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.split import prepare_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(prepare_main())

#!/usr/bin/env python3
"""Operator entry point for recording the pre-test system freeze."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.freeze_b_record import record_main


if __name__ == "__main__":
    raise SystemExit(record_main())

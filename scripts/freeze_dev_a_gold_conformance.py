#!/usr/bin/env python3
"""Freeze aggregate-only dual-scorer gold conformance for complete dev-A."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.dev_a_gold_conformance_cli import (
    dev_a_gold_conformance_entrypoint,
)


if __name__ == "__main__":
    raise SystemExit(dev_a_gold_conformance_entrypoint())

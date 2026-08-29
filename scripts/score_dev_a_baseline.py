#!/usr/bin/env python3
"""Score the frozen public baseline against the authorized dev-A release."""

from __future__ import annotations

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.dev_a_baseline_scoring_cli import (
    dev_a_baseline_scoring_entrypoint,
)


if __name__ == "__main__":
    raise SystemExit(dev_a_baseline_scoring_entrypoint())

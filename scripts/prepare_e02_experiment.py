#!/usr/bin/env python3
"""Prepare or execute the exact receipt-gated E02 deployment."""

from __future__ import annotations

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.e02_experiment_cli import e02_experiment_entrypoint


if __name__ == "__main__":
    raise SystemExit(e02_experiment_entrypoint())

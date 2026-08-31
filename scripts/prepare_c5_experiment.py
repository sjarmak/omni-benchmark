#!/usr/bin/env python3
"""Prepare or execute the exact committed C5 tuned deployment."""

from __future__ import annotations

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.c5_experiment_cli import c5_experiment_entrypoint


if __name__ == "__main__":
    raise SystemExit(c5_experiment_entrypoint())

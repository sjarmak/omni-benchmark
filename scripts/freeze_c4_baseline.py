#!/usr/bin/env python3
"""Freeze one complete immutable public C4 baseline arm."""

from omni_benchmark.c4_baseline_freeze import c4_baseline_freeze_entrypoint


if __name__ == "__main__":
    raise SystemExit(c4_baseline_freeze_entrypoint())

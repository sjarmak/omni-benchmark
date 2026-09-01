#!/usr/bin/env python3
"""Capture one exact R2 attempt through the guarded production Omni leaf."""

from omni_benchmark.r2_attempt_cli import r2_attempt_entrypoint


if __name__ == "__main__":
    raise SystemExit(r2_attempt_entrypoint())

#!/usr/bin/env python3
"""Validate or explicitly score the complete held-out sealed batch."""

from omni_benchmark.sealed_evaluation_cli import sealed_evaluation_entrypoint


if __name__ == "__main__":
    raise SystemExit(sealed_evaluation_entrypoint())

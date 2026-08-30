#!/usr/bin/env python3
"""Recover C4 result sidecars without rerunning model reasoning."""

from omni_benchmark.c4_result_recovery_cli import c4_result_recovery_entrypoint


if __name__ == "__main__":
    raise SystemExit(c4_result_recovery_entrypoint())

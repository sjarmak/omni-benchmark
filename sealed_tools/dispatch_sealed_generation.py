#!/usr/bin/env python3
"""Validate sealed dispatch inputs; production execution is fail-closed."""

from omni_benchmark.sealed_dispatch_cli import dispatch_main


if __name__ == "__main__":
    raise SystemExit(dispatch_main())

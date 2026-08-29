#!/usr/bin/env python3
"""Capture bounded read-only diagnostics for failed public semantic deployments."""

from omni_benchmark.omni_semantic_diagnostics import diagnostic_main


if __name__ == "__main__":
    raise SystemExit(diagnostic_main())

#!/usr/bin/env python3
"""Render identity-free aggregate held-out results as Markdown."""

from omni_benchmark.sealed_report import sealed_report_entrypoint


if __name__ == "__main__":
    raise SystemExit(sealed_report_entrypoint())

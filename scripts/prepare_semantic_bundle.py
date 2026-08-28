#!/usr/bin/env python3
"""Publish a public-only Omni semantic bundle for one reviewed mapping."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.semantic_bundle_cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create the deterministic dev-A/dev-B split from the frozen train IDs."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.split import development_split_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(development_split_main())

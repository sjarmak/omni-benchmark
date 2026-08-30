#!/usr/bin/env python3
"""Create the deterministic human-selected sealed MVP identity frame."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from omni_benchmark.sealed_mvp_frame import sealed_mvp_frame_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(sealed_mvp_frame_main())

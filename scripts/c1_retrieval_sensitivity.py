#!/usr/bin/env python3
"""Plan or run the prespecified C1 schema-retrieval sensitivity arm."""

from __future__ import annotations

import sys

from omni_benchmark.baseline_batch_cli import baseline_batch_main


if __name__ == "__main__":
    raise SystemExit(baseline_batch_main(["--c1-retrieval-sensitivity", *sys.argv[1:]]))

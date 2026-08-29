#!/usr/bin/env python3
"""Continue only authorized infrastructure failures and unattempted trials."""

from omni_benchmark.baseline_continuation_cli import baseline_continuation_main


if __name__ == "__main__":
    raise SystemExit(baseline_continuation_main())

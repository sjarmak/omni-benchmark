#!/usr/bin/env python3
"""Release only Freeze-B-bound held-out labels into sealed custody."""

from omni_benchmark.sealed_test_release import sealed_test_release_entrypoint


if __name__ == "__main__":
    raise SystemExit(sealed_test_release_entrypoint())

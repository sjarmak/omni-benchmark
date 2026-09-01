#!/usr/bin/env python3
"""Deploy one exact R2 semantic arm through the guarded deployment leaf."""

from omni_benchmark.r2_deployment_cli import r2_deployment_entrypoint


if __name__ == "__main__":
    raise SystemExit(r2_deployment_entrypoint())

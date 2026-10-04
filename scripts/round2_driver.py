import argparse
import subprocess
import sys
from pathlib import Path

from omni_benchmark.round2_driver import DriverError, parse_manifest, run_stages


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run ordered manifest stages and resume from a ledger"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--from-stage")
    args = parser.parse_args()
    try:
        manifest = parse_manifest(args.manifest.read_text(encoding="utf-8"))
        return run_stages(manifest, args.state_root, subprocess.run, args.from_stage)
    except (DriverError, OSError) as error:
        print(f"round2 driver: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Freeze the public-identity-only paired R2 execution schedule."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .hkb_io import HKBFileSafetyError, read_regular_file
from .r2_paired_schedule import (
    EXPECTED_DATABASE_COUNT,
    EXPECTED_DEV_A_COUNT,
    EXPECTED_PAIR_COUNT,
    R2PairedScheduleError,
    build_r2_paired_schedule,
    write_r2_paired_schedule,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-manifest", type=Path, required=True)
    parser.add_argument("--dev-a-ids", type=Path, required=True)
    parser.add_argument("--split-metadata", type=Path, required=True)
    parser.add_argument("--target-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-dev-a-count", type=int, default=EXPECTED_DEV_A_COUNT
    )
    parser.add_argument("--expected-pair-count", type=int, default=EXPECTED_PAIR_COUNT)
    parser.add_argument(
        "--expected-database-count", type=int, default=EXPECTED_DATABASE_COUNT
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    schedule = build_r2_paired_schedule(
        _read(arguments.public_manifest, 64_000_000),
        _read(arguments.dev_a_ids, 2_000_000),
        _read(arguments.split_metadata, 4_000_000),
        _read(arguments.target_config, 128_000),
        expected_dev_a_count=arguments.expected_dev_a_count,
        expected_pair_count=arguments.expected_pair_count,
        expected_database_count=arguments.expected_database_count,
    )
    write_r2_paired_schedule(arguments.output, schedule)
    summary = schedule["summary"]
    print(
        json.dumps(
            {
                "artifact_sha256": schedule["manifest"]["artifact_sha256"],
                "attempt_count": summary["attempt_count"],
                "database_count": summary["database_count"],
                "first_condition_counts": summary["first_condition_counts"],
                "output": str(arguments.output),
                "pair_count": summary["pair_count"],
            },
            sort_keys=True,
        )
    )
    return 0


def _read(path: Path, maximum_bytes: int) -> bytes:
    try:
        return read_regular_file(path, maximum_bytes=maximum_bytes)
    except HKBFileSafetyError as error:
        raise R2PairedScheduleError(str(error)) from error


if __name__ == "__main__":
    raise SystemExit(main())

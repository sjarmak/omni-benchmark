"""Build the aggregate-only R2 semantic-reuse mechanism report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .hkb_io import HKBFileSafetyError, read_regular_file
from .r2_semantic_reuse import (
    EXPECTED_ACCEPTED_CATALOG_SHA256,
    EXPECTED_PAIR_COUNT,
    EXPECTED_SCHEDULE_SHA256,
    R2SemanticReuseError,
    build_r2_semantic_reuse_report,
    write_r2_semantic_reuse_report,
)

_MAX_INPUT_BYTES = 64_000_000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accepted-catalog", type=Path, required=True)
    parser.add_argument("--opportunity-map", type=Path, required=True)
    parser.add_argument("--paired-schedule", type=Path, required=True)
    parser.add_argument("--control-generation", type=Path, required=True)
    parser.add_argument("--treatment-generation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-pair-count", type=int, default=EXPECTED_PAIR_COUNT)
    parser.add_argument(
        "--expected-catalog-sha256",
        default=EXPECTED_ACCEPTED_CATALOG_SHA256,
    )
    parser.add_argument(
        "--expected-schedule-sha256",
        default=EXPECTED_SCHEDULE_SHA256,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    report = build_r2_semantic_reuse_report(
        _read(arguments.accepted_catalog),
        _read(arguments.opportunity_map),
        _read(arguments.paired_schedule),
        _read(arguments.control_generation),
        _read(arguments.treatment_generation),
        expected_pair_count=arguments.expected_pair_count,
        expected_catalog_sha256=arguments.expected_catalog_sha256,
        expected_schedule_sha256=arguments.expected_schedule_sha256,
    )
    write_r2_semantic_reuse_report(arguments.output, report)
    summary = report["summary"]
    print(
        json.dumps(
            {
                "artifact_sha256": report["manifest"]["artifact_sha256"],
                "opportunity_pair_count": summary["opportunity_pair_count"],
                "output": str(arguments.output),
                "unresolved_pair_count": summary["unresolved_pair_count"],
                "verified_replacement_count": summary["verified_replacement_count"],
                "verified_replacement_rate": summary["verified_replacement_rate"],
            },
            sort_keys=True,
        )
    )
    return 0


def _read(path: Path) -> bytes:
    try:
        return read_regular_file(path, maximum_bytes=_MAX_INPUT_BYTES)
    except HKBFileSafetyError as error:
        raise R2SemanticReuseError(str(error)) from error


if __name__ == "__main__":
    raise SystemExit(main())

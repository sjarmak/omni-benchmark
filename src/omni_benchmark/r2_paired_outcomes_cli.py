"""Build the aggregate-only paired R2 secondary-outcome report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .hkb_io import HKBFileSafetyError, read_regular_file
from .r2_paired_outcomes import (
    EXPECTED_PAIR_COUNT,
    EXPECTED_SCHEDULE_SHA256,
    R2PairedOutcomeError,
    build_r2_paired_outcome_report,
    write_r2_paired_outcome_report,
)

_MAX_INPUT_BYTES = 64_000_000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paired-schedule", type=Path, required=True)
    parser.add_argument("--control-generation", type=Path, required=True)
    parser.add_argument("--treatment-generation", type=Path, required=True)
    parser.add_argument("--control-official-score", type=Path, required=True)
    parser.add_argument("--control-sensitivity-score", type=Path, required=True)
    parser.add_argument("--treatment-official-score", type=Path, required=True)
    parser.add_argument("--treatment-sensitivity-score", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-pair-count", type=int, default=EXPECTED_PAIR_COUNT)
    parser.add_argument(
        "--expected-schedule-sha256",
        default=EXPECTED_SCHEDULE_SHA256,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    report = build_r2_paired_outcome_report(
        _read(arguments.paired_schedule),
        _read(arguments.control_generation),
        _read(arguments.treatment_generation),
        _read(arguments.control_official_score),
        _read(arguments.control_sensitivity_score),
        _read(arguments.treatment_official_score),
        _read(arguments.treatment_sensitivity_score),
        expected_pair_count=arguments.expected_pair_count,
        expected_schedule_sha256=arguments.expected_schedule_sha256,
    )
    write_r2_paired_outcome_report(arguments.output, report)
    print(
        json.dumps(
            {
                "artifact_sha256": report["manifest"]["artifact_sha256"],
                "official_accuracy_delta": report["scorers"]["official_soft_ex"][
                    "paired_accuracy"
                ]["estimate"],
                "output": str(arguments.output),
                "pair_count": report["pair_count"],
                "sensitivity_accuracy_delta": report["scorers"]["sensitivity"][
                    "paired_accuracy"
                ]["estimate"],
            },
            sort_keys=True,
        )
    )
    return 0


def _read(path: Path) -> bytes:
    try:
        return read_regular_file(path, maximum_bytes=_MAX_INPUT_BYTES)
    except HKBFileSafetyError as error:
        raise R2PairedOutcomeError(str(error)) from error


if __name__ == "__main__":
    raise SystemExit(main())

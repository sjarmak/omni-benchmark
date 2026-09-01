"""Prepare or freeze the analysis-only R2 dev-A opportunity map."""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections.abc import Sequence
from pathlib import Path

from .hkb_io import HKBFileSafetyError, read_regular_file
from .measure_catalog_review import MeasureReviewError, write_review_artifact
from .measure_opportunity_map import (
    EXPECTED_DEV_A_COUNT,
    EXPECTED_FRAME_COUNT,
    build_measure_opportunity_review_workbook,
    materialize_agent_adjudicated_measure_opportunity_map,
    materialize_measure_opportunity_map,
)
from .measure_review_catalog import canonical_catalog_bytes

_MAX_INPUT_BYTES = 16_000_000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("template", "freeze", "freeze-agent"):
        selected = commands.add_parser(command)
        selected.add_argument("--accepted-catalog", type=Path, required=True)
        selected.add_argument("--public-manifest", type=Path, required=True)
        selected.add_argument("--dev-a-ids", type=Path, required=True)
        if command == "freeze":
            selected.add_argument("--workbook", type=Path, required=True)
        elif command == "freeze-agent":
            for name in (
                "source-workbook",
                "adjudicated-workbook",
                "instructions",
                "prospective-proposal",
                "prospective-approval-record",
                "corrective-proposal",
                "corrective-approval-record",
                "provenance",
                "output-adoption-record",
            ):
                selected.add_argument(f"--{name}", type=Path, required=True)
        selected.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    catalog = _read(arguments.accepted_catalog)
    manifest = _read(arguments.public_manifest)
    dev_a_ids = _read(arguments.dev_a_ids)
    if arguments.command == "template":
        workbook = build_measure_opportunity_review_workbook(
            catalog,
            manifest,
            dev_a_ids,
            expected_dev_a_count=EXPECTED_DEV_A_COUNT,
            expected_frame_count=EXPECTED_FRAME_COUNT,
        )
        write_review_artifact(arguments.output, workbook)
        print(
            json.dumps(
                {
                    "eligible_question_count": sum(
                        1
                        for _row in csv.DictReader(
                            io.StringIO(workbook.decode(), newline="")
                        )
                    ),
                    "output": str(arguments.output),
                },
                sort_keys=True,
            )
        )
        return 0
    if arguments.command == "freeze":
        artifact = materialize_measure_opportunity_map(
            catalog,
            manifest,
            dev_a_ids,
            _read(arguments.workbook),
            expected_dev_a_count=EXPECTED_DEV_A_COUNT,
            expected_frame_count=EXPECTED_FRAME_COUNT,
        )
    else:
        artifact = materialize_agent_adjudicated_measure_opportunity_map(
            catalog,
            manifest,
            dev_a_ids,
            _read(arguments.source_workbook),
            _read(arguments.adjudicated_workbook),
            _read(arguments.instructions),
            _read(arguments.prospective_proposal),
            _read(arguments.prospective_approval_record),
            _read(arguments.corrective_proposal),
            _read(arguments.corrective_approval_record),
            _read(arguments.provenance),
            _read(arguments.output_adoption_record),
            expected_dev_a_count=EXPECTED_DEV_A_COUNT,
            expected_frame_count=EXPECTED_FRAME_COUNT,
        )
    write_review_artifact(arguments.output, canonical_catalog_bytes(artifact))
    print(json.dumps(artifact["summary"], sort_keys=True))
    return 0


def _read(path: Path) -> bytes:
    try:
        return read_regular_file(path, maximum_bytes=_MAX_INPUT_BYTES)
    except HKBFileSafetyError as error:
        raise MeasureReviewError(str(error)) from error


if __name__ == "__main__":
    raise SystemExit(main())

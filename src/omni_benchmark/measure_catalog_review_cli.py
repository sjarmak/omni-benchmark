"""Prepare or validate the blinded R2 public-evidence measure review."""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections.abc import Sequence
from pathlib import Path

from .hkb_io import HKBFileSafetyError, read_regular_file
from .measure_catalog_review import (
    MeasureReviewError,
    build_agent_adjudication_provenance,
    build_measure_review_workbook,
    build_protocol_amendment_approval_record,
    build_protocol_approval_record,
    materialize_measure_agent_adjudication,
    materialize_measure_review_decisions,
    write_review_artifact,
)
from .measure_catalog_freeze import build_accepted_measure_catalog
from .measure_review_catalog import canonical_catalog_bytes

_MAX_INPUT_BYTES = 16_000_000


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    template = commands.add_parser("template")
    template.add_argument("--catalog", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)

    approval = commands.add_parser("approval-record")
    approval.add_argument("--proposal", type=Path, required=True)
    approval.add_argument("--approved-by", required=True)
    approval.add_argument("--approved-at", required=True)
    approval.add_argument("--output", type=Path, required=True)

    amendment_approval = commands.add_parser("amendment-approval-record")
    amendment_approval.add_argument("--proposal", type=Path, required=True)
    amendment_approval.add_argument("--provenance", type=Path, required=True)
    amendment_approval.add_argument("--approved-by", required=True)
    amendment_approval.add_argument("--approved-at", required=True)
    amendment_approval.add_argument("--output", type=Path, required=True)

    provenance = commands.add_parser("agent-provenance")
    provenance.add_argument("--source-workbook", type=Path, required=True)
    provenance.add_argument("--adjudicated-workbook", type=Path, required=True)
    provenance.add_argument("--transcript-extract", type=Path, required=True)
    provenance.add_argument("--transcript-extract-path", required=True)
    provenance.add_argument("--source-url", required=True)
    provenance.add_argument("--retrieved-at", required=True)
    provenance.add_argument("--started-at", required=True)
    provenance.add_argument("--completed-at", required=True)
    provenance.add_argument("--product", required=True)
    provenance.add_argument("--model", required=True)
    provenance.add_argument("--reasoning-effort", required=True)
    provenance.add_argument("--user-instruction-messages", type=int, required=True)
    provenance.add_argument("--assistant-text-messages", type=int, required=True)
    provenance.add_argument("--tool-call-messages", type=int, required=True)
    provenance.add_argument("--correction-rounds", type=int, required=True)
    provenance.add_argument("--output", type=Path, required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("--catalog", type=Path, required=True)
    validate.add_argument("--workbook", type=Path, required=True)
    validate.add_argument("--proposal", type=Path, required=True)
    validate.add_argument("--approval-record", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)

    validate_agent = commands.add_parser("validate-agent")
    validate_agent.add_argument("--catalog", type=Path, required=True)
    validate_agent.add_argument("--source-workbook", type=Path, required=True)
    validate_agent.add_argument("--adjudicated-workbook", type=Path, required=True)
    validate_agent.add_argument("--provenance", type=Path, required=True)
    validate_agent.add_argument("--transcript-extract", type=Path, required=True)
    validate_agent.add_argument("--base-proposal", type=Path, required=True)
    validate_agent.add_argument("--base-approval-record", type=Path, required=True)
    validate_agent.add_argument("--amendment-proposal", type=Path, required=True)
    validate_agent.add_argument("--amendment-approval-record", type=Path, required=True)
    validate_agent.add_argument("--output", type=Path, required=True)

    freeze_agent_catalog = commands.add_parser("freeze-agent-catalog")
    freeze_agent_catalog.add_argument("--catalog", type=Path, required=True)
    freeze_agent_catalog.add_argument("--decisions", type=Path, required=True)
    freeze_agent_catalog.add_argument("--source-workbook", type=Path, required=True)
    freeze_agent_catalog.add_argument(
        "--adjudicated-workbook", type=Path, required=True
    )
    freeze_agent_catalog.add_argument("--provenance", type=Path, required=True)
    freeze_agent_catalog.add_argument("--transcript-extract", type=Path, required=True)
    freeze_agent_catalog.add_argument("--base-proposal", type=Path, required=True)
    freeze_agent_catalog.add_argument(
        "--base-approval-record", type=Path, required=True
    )
    freeze_agent_catalog.add_argument("--amendment-proposal", type=Path, required=True)
    freeze_agent_catalog.add_argument(
        "--amendment-approval-record", type=Path, required=True
    )
    freeze_agent_catalog.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "template":
        catalog = _read(arguments.catalog)
        workbook = build_measure_review_workbook(catalog)
        write_review_artifact(arguments.output, workbook)
        print(
            json.dumps(
                {
                    "candidate_rows": sum(
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
    if arguments.command == "approval-record":
        record = build_protocol_approval_record(
            _read(arguments.proposal),
            approved_by=arguments.approved_by,
            approved_at=arguments.approved_at,
        )
        write_review_artifact(arguments.output, canonical_catalog_bytes(record))
        print(json.dumps(record, sort_keys=True))
        return 0

    if arguments.command == "amendment-approval-record":
        record = build_protocol_amendment_approval_record(
            _read(arguments.proposal),
            provenance_bytes=_read(arguments.provenance),
            approved_by=arguments.approved_by,
            approved_at=arguments.approved_at,
        )
        write_review_artifact(arguments.output, canonical_catalog_bytes(record))
        print(json.dumps(record, sort_keys=True))
        return 0

    if arguments.command == "agent-provenance":
        record = build_agent_adjudication_provenance(
            _read(arguments.source_workbook),
            _read(arguments.adjudicated_workbook),
            transcript_extract_bytes=_read(arguments.transcript_extract),
            transcript_extract_path=arguments.transcript_extract_path,
            source_url=arguments.source_url,
            retrieved_at=arguments.retrieved_at,
            started_at=arguments.started_at,
            completed_at=arguments.completed_at,
            product=arguments.product,
            model=arguments.model,
            reasoning_effort=arguments.reasoning_effort,
            user_instruction_messages=arguments.user_instruction_messages,
            assistant_text_messages=arguments.assistant_text_messages,
            tool_call_messages=arguments.tool_call_messages,
            correction_rounds=arguments.correction_rounds,
        )
        write_review_artifact(arguments.output, canonical_catalog_bytes(record))
        print(json.dumps(record["summary"], sort_keys=True))
        return 0

    if arguments.command == "validate-agent":
        artifact = materialize_measure_agent_adjudication(
            _read(arguments.catalog),
            _read(arguments.source_workbook),
            _read(arguments.adjudicated_workbook),
            _read(arguments.provenance),
            _read(arguments.transcript_extract),
            _read(arguments.base_proposal),
            _read(arguments.base_approval_record),
            _read(arguments.amendment_proposal),
            _read(arguments.amendment_approval_record),
        )
        write_review_artifact(arguments.output, canonical_catalog_bytes(artifact))
        print(json.dumps(artifact["summary"], sort_keys=True))
        return 0

    if arguments.command == "freeze-agent-catalog":
        artifact = build_accepted_measure_catalog(
            _read(arguments.catalog),
            decisions_bytes=_read(arguments.decisions),
            source_workbook_bytes=_read(arguments.source_workbook),
            adjudicated_workbook_bytes=_read(arguments.adjudicated_workbook),
            provenance_bytes=_read(arguments.provenance),
            transcript_extract_bytes=_read(arguments.transcript_extract),
            base_proposal_bytes=_read(arguments.base_proposal),
            base_approval_record_bytes=_read(arguments.base_approval_record),
            amendment_proposal_bytes=_read(arguments.amendment_proposal),
            amendment_approval_record_bytes=_read(arguments.amendment_approval_record),
        )
        write_review_artifact(arguments.output, canonical_catalog_bytes(artifact))
        print(json.dumps(artifact["summary"], sort_keys=True))
        return 0

    artifact = materialize_measure_review_decisions(
        _read(arguments.catalog),
        _read(arguments.workbook),
        _read(arguments.proposal),
        _read(arguments.approval_record),
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

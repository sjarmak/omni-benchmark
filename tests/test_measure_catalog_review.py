from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from omni_benchmark.measure_catalog_review import (
    ACCEPT_REASON_CODES,
    REVIEW_COLUMNS,
    MeasureReviewError,
    build_measure_review_workbook,
    build_protocol_approval_record,
    materialize_measure_review_decisions,
    write_review_artifact,
)
from omni_benchmark.measure_catalog_review_cli import main
from omni_benchmark.measure_review_catalog import (
    build_measure_review_catalog,
    canonical_catalog_bytes,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _catalog_bytes() -> bytes:
    table_id = "db:table:orders"
    column_id = "db:column:orders:id"
    catalog = build_measure_review_catalog(
        [
            {
                "database": "db",
                "hkb_records": [],
                "input_files": [
                    {
                        "path": "semantic_models/public_schema_ir/db.schema.jsonl",
                        "sha256": "1" * 64,
                    }
                ],
                "mapping_records": [],
                "schema_records": [
                    {
                        "database": "db",
                        "identifier": {"name": "orders"},
                        "primary_key_column_stable_ids": [column_id],
                        "record_kind": "table",
                        "stable_id": table_id,
                        "unique_keys": [],
                    },
                    {
                        "database": "db",
                        "description": "Public order identity.",
                        "identifier": {"name": "id"},
                        "record_kind": "column",
                        "stable_id": column_id,
                        "table_stable_id": table_id,
                    },
                ],
                "views": [
                    {
                        "file_name": "db.public__orders.view",
                        "fields": {column_id: "id"},
                        "label": "Orders",
                        "table_stable_id": table_id,
                        "view_name": "db_public__orders",
                    }
                ],
            }
        ]
    )
    return canonical_catalog_bytes(catalog)


def _rows(workbook: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(workbook.decode(), newline="")))


def _encode_rows(rows: list[dict[str, str]], columns: list[str] | None = None) -> bytes:
    output = io.StringIO(newline="")
    fieldnames = list(REVIEW_COLUMNS) if columns is None else columns
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _completed_workbook(
    catalog: bytes,
    *,
    decision: str = "accept",
    reason: str = "public_identity_and_binding_confirmed",
    seconds: str = "1.25",
    correction: str = "",
) -> bytes:
    rows = _rows(build_measure_review_workbook(catalog))
    for row in rows:
        row["decision"] = decision
        row["reason_code"] = reason
        row["active_review_seconds"] = seconds
        row["binding_correction"] = correction
    return _encode_rows(rows)


def _approval(proposal: bytes = b"exact proposed protocol\n") -> tuple[bytes, bytes]:
    record = build_protocol_approval_record(
        proposal,
        approved_by="operator",
        approved_at="2026-09-01T04:00:00Z",
    )
    return proposal, canonical_catalog_bytes(record)


def test_blank_workbook_is_deterministic_hash_bound_and_blinded() -> None:
    catalog = _catalog_bytes()

    first = build_measure_review_workbook(catalog)
    second = build_measure_review_workbook(catalog)

    assert first == second
    reader = csv.DictReader(io.StringIO(first.decode(), newline=""))
    assert reader.fieldnames == list(REVIEW_COLUMNS)
    rows = list(reader)
    assert len(rows) == 1
    row = rows[0]
    assert row["source_catalog_file_sha256"] == hashlib.sha256(catalog).hexdigest()
    assert (
        row["source_catalog_sha256"]
        == json.loads(catalog)["manifest"]["catalog_sha256"]
    )
    assert row["candidate_payload_sha256"]
    assert row["decision"] == ""
    assert row["reason_code"] == ""
    assert row["active_review_seconds"] == ""
    assert row["binding_correction"] == ""
    for forbidden in (b"question", b"correctness", b"outcome", b"instance_id"):
        assert forbidden not in first.lower()


def test_real_catalog_workbook_contains_every_candidate_once() -> None:
    catalog = (
        REPOSITORY_ROOT
        / "experiments/r2-public-evidence-measures/measure-review-catalog-v2.json"
    ).read_bytes()

    workbook = build_measure_review_workbook(catalog)
    rows = _rows(workbook)

    assert len(rows) == 812
    assert len({row["candidate_id"] for row in rows}) == 812
    assert [row["candidate_id"] for row in rows] == sorted(
        row["candidate_id"] for row in rows
    )
    assert workbook == build_measure_review_workbook(catalog)


def test_complete_review_materializes_separate_decisions_without_catalog_mutation() -> (
    None
):
    catalog = _catalog_bytes()
    workbook = _completed_workbook(catalog)
    proposal, approval = _approval()

    artifact = materialize_measure_review_decisions(
        catalog, workbook, proposal, approval
    )

    assert artifact["kind"] == "public-evidence-measure-review-decisions"
    assert artifact["summary"] == {
        "accept": 1,
        "active_review_seconds": 1.25,
        "binding_corrections": 0,
        "defer": 0,
        "reject": 0,
        "reviewed_candidates": 1,
    }
    decision = artifact["decisions"][0]
    assert decision["decision"] == "accept"
    assert decision["reason_code"] in ACCEPT_REASON_CODES
    assert decision["binding_correction"] is None
    assert decision["correction_status"] == "not_applicable"
    assert json.loads(catalog)["candidates"][0]["review"]["status"] == "pending"


@pytest.mark.parametrize(
    ("decision", "reason", "seconds", "message"),
    [
        ("", "", "", "complete review"),
        ("approve", "public_identity_and_binding_confirmed", "1", "decision"),
        ("accept", "needs_domain_authority", "1", "reason_code"),
        ("reject", "not_an_entity", "-1", "active_review_seconds"),
        ("defer", "reviewer_uncertain", "nan", "active_review_seconds"),
        ("defer", "reviewer_uncertain", "1e999", "active_review_seconds"),
    ],
)
def test_review_requires_complete_compatible_decisions_and_finite_time(
    decision: str, reason: str, seconds: str, message: str
) -> None:
    catalog = _catalog_bytes()
    workbook = _completed_workbook(
        catalog, decision=decision, reason=reason, seconds=seconds
    )
    proposal, approval = _approval()

    with pytest.raises(MeasureReviewError, match=message):
        materialize_measure_review_decisions(catalog, workbook, proposal, approval)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "immutable"])
def test_review_rejects_missing_duplicate_or_edited_candidate_rows(
    mutation: str,
) -> None:
    catalog = _catalog_bytes()
    rows = _rows(_completed_workbook(catalog))
    if mutation == "missing":
        rows.clear()
    elif mutation == "duplicate":
        rows.append(dict(rows[0]))
    else:
        rows[0]["sql"] = "${db_public__orders.other_id}"
    workbook = _encode_rows(rows)
    proposal, approval = _approval()

    with pytest.raises(MeasureReviewError, match=mutation):
        materialize_measure_review_decisions(catalog, workbook, proposal, approval)


def test_review_rejects_extra_columns_that_could_smuggle_question_data() -> None:
    catalog = _catalog_bytes()
    rows = _rows(_completed_workbook(catalog))
    rows[0]["question"] = "Which orders?"
    workbook = _encode_rows(rows, [*REVIEW_COLUMNS, "question"])
    proposal, approval = _approval()

    with pytest.raises(MeasureReviewError, match="header"):
        materialize_measure_review_decisions(catalog, workbook, proposal, approval)


def test_mechanical_binding_correction_is_isolated_for_agent_validation() -> None:
    catalog = _catalog_bytes()
    correction = json.dumps(
        {
            "corrected_sql": "${db_public__orders.order_id}",
            "justification": "Public source ID is unchanged; the compiled alias is corrected.",
            "source_field_stable_id": "db:column:orders:id",
        },
        sort_keys=True,
    )
    workbook = _completed_workbook(
        catalog,
        reason="mechanical_binding_corrected",
        correction=correction,
    )
    proposal, approval = _approval()

    artifact = materialize_measure_review_decisions(
        catalog, workbook, proposal, approval
    )

    decision = artifact["decisions"][0]
    assert decision["binding_correction"] == json.loads(correction)
    assert decision["correction_status"] == "requires_public_evidence_validation"


@pytest.mark.parametrize(
    "correction",
    [
        "",
        '{"aggregate_type":"sum"}',
        (
            '{"corrected_sql":"SUM(${db_public__orders.id})",'
            '"justification":"change",'
            '"source_field_stable_id":"db:column:orders:id"}'
        ),
        (
            '{"corrected_sql":"${other_view.id}",'
            '"justification":"change",'
            '"source_field_stable_id":"db:column:orders:id"}'
        ),
        (
            '{"corrected_sql":"${db_public__orders.id}",'
            '"justification":"change",'
            '"source_field_stable_id":"db:column:orders:other"}'
        ),
    ],
)
def test_binding_correction_cannot_change_semantics(correction: str) -> None:
    catalog = _catalog_bytes()
    workbook = _completed_workbook(
        catalog,
        reason="mechanical_binding_corrected",
        correction=correction,
    )
    proposal, approval = _approval()

    with pytest.raises(MeasureReviewError, match="binding correction"):
        materialize_measure_review_decisions(catalog, workbook, proposal, approval)


def test_materialization_requires_an_exact_approved_proposal_record() -> None:
    catalog = _catalog_bytes()
    workbook = _completed_workbook(catalog)
    proposal, approval = _approval()
    rejected = json.loads(approval)
    rejected["decision"] = "rejected"

    with pytest.raises(MeasureReviewError, match="approved proposal"):
        materialize_measure_review_decisions(
            catalog,
            workbook,
            proposal,
            canonical_catalog_bytes(rejected),
        )
    with pytest.raises(MeasureReviewError, match="proposal hash"):
        materialize_measure_review_decisions(
            catalog, workbook, proposal + b"changed", approval
        )


def test_writer_is_append_only_and_mode_0600(tmp_path: Path) -> None:
    destination = tmp_path / "review.csv"
    content = build_measure_review_workbook(_catalog_bytes())

    write_review_artifact(destination, content)

    assert destination.read_bytes() == content
    assert destination.stat().st_mode & 0o777 == 0o600
    with pytest.raises(MeasureReviewError, match="refusing overwrite"):
        write_review_artifact(destination, content)


def test_template_cli_reports_csv_rows_not_embedded_yaml_newlines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = tmp_path / "catalog.json"
    output = tmp_path / "review.csv"
    catalog.write_bytes(_catalog_bytes())

    assert (
        main(
            [
                "template",
                "--catalog",
                str(catalog),
                "--output",
                str(output),
            ]
        )
        == 0
    )

    report = json.loads(capsys.readouterr().out)
    assert report["candidate_rows"] == 1
    assert len(_rows(output.read_bytes())) == 1


def test_approval_and_validation_cli_round_trip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    catalog = tmp_path / "catalog.json"
    workbook = tmp_path / "review.csv"
    proposal = tmp_path / "proposal.md"
    approval = tmp_path / "approval.json"
    decisions = tmp_path / "decisions.json"
    catalog_bytes = _catalog_bytes()
    proposal_bytes = b"exact proposed protocol\n"
    catalog.write_bytes(catalog_bytes)
    workbook.write_bytes(_completed_workbook(catalog_bytes))
    proposal.write_bytes(proposal_bytes)

    assert (
        main(
            [
                "approval-record",
                "--proposal",
                str(proposal),
                "--approved-by",
                "operator",
                "--approved-at",
                "2026-09-01T04:00:00Z",
                "--output",
                str(approval),
            ]
        )
        == 0
    )
    approval_report = json.loads(capsys.readouterr().out)
    assert (
        approval_report["proposal_sha256"] == hashlib.sha256(proposal_bytes).hexdigest()
    )

    assert (
        main(
            [
                "validate",
                "--catalog",
                str(catalog),
                "--workbook",
                str(workbook),
                "--proposal",
                str(proposal),
                "--approval-record",
                str(approval),
                "--output",
                str(decisions),
            ]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out)["reviewed_candidates"] == 1
    assert json.loads(decisions.read_bytes())["summary"]["accept"] == 1
    assert approval.stat().st_mode & 0o777 == 0o600
    assert decisions.stat().st_mode & 0o777 == 0o600

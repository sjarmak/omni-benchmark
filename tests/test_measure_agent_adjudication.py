from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from omni_benchmark.measure_catalog_review import (
    REVIEW_COLUMNS,
    MeasureReviewError,
    build_agent_adjudication_provenance,
    build_protocol_amendment_approval_record,
    build_protocol_approval_record,
    build_measure_review_workbook,
    materialize_measure_agent_adjudication,
    materialize_measure_review_decisions,
)
from omni_benchmark.measure_catalog_review_cli import main
from omni_benchmark.measure_catalog_freeze import (
    AcceptedMeasureCatalogError,
    build_accepted_measure_catalog,
    validate_accepted_measure_catalog,
)
from omni_benchmark.measure_review_catalog import (
    build_measure_review_catalog,
    canonical_catalog_bytes,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPT_EXTRACT = b"bounded normalized transcript extract\n"


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


def _reseal_catalog(catalog: dict[str, object]) -> bytes:
    manifest = catalog["manifest"]
    assert isinstance(manifest, dict)
    manifest.pop("catalog_sha256", None)
    manifest["catalog_sha256"] = hashlib.sha256(
        canonical_catalog_bytes(catalog)
    ).hexdigest()
    return canonical_catalog_bytes(catalog)


def _rows(workbook: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(workbook.decode(), newline="")))


def _encode_rows(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(REVIEW_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _adjudicated_workbook(catalog: bytes) -> tuple[bytes, bytes]:
    source = build_measure_review_workbook(catalog)
    rows = _rows(source)
    for row in rows:
        row["decision"] = "accept"
        row["reason_code"] = "public_identity_and_binding_confirmed"
    return source, _encode_rows(rows)


def _base_approval() -> tuple[bytes, bytes]:
    proposal = b"exact base protocol\n"
    record = build_protocol_approval_record(
        proposal,
        approved_by="operator",
        approved_at="2026-09-01T11:30:31Z",
    )
    return proposal, canonical_catalog_bytes(record)


def _amendment_approval(provenance: bytes) -> tuple[bytes, bytes]:
    amendment = b"exact agent adjudication amendment\n"
    record = build_protocol_amendment_approval_record(
        amendment,
        provenance_bytes=provenance,
        approved_by="operator",
        approved_at="2026-09-01T13:00:00Z",
    )
    return amendment, canonical_catalog_bytes(record)


def _provenance(source: bytes, adjudicated: bytes) -> bytes:
    record = build_agent_adjudication_provenance(
        source,
        adjudicated,
        transcript_extract_bytes=TRANSCRIPT_EXTRACT,
        transcript_extract_path="experiments/r2/agent-transcript-v1.md",
        source_url="https://chatgpt.com/share/6a96c57e-01c0-83ea-aa79-5eda508be2f6",
        retrieved_at="2026-09-01T12:31:00Z",
        started_at="2026-09-01T12:07:17.946000Z",
        completed_at="2026-09-01T12:17:35.588452Z",
        product="ChatGPT",
        model="GPT-5.6 sol",
        reasoning_effort="High",
        user_instruction_messages=2,
        assistant_text_messages=7,
        tool_call_messages=42,
        correction_rounds=1,
    )
    return canonical_catalog_bytes(record)


def _decision_chain(catalog: bytes) -> dict[str, bytes]:
    source, adjudicated = _adjudicated_workbook(catalog)
    provenance = _provenance(source, adjudicated)
    base_proposal, base_approval = _base_approval()
    amendment, amendment_approval = _amendment_approval(provenance)
    decisions = canonical_catalog_bytes(
        materialize_measure_agent_adjudication(
            catalog,
            source,
            adjudicated,
            provenance,
            TRANSCRIPT_EXTRACT,
            base_proposal,
            base_approval,
            amendment,
            amendment_approval,
        )
    )
    return {
        "adjudicated_workbook_bytes": adjudicated,
        "amendment_approval_record_bytes": amendment_approval,
        "amendment_proposal_bytes": amendment,
        "base_approval_record_bytes": base_approval,
        "base_proposal_bytes": base_proposal,
        "decisions_bytes": decisions,
        "provenance_bytes": provenance,
        "source_workbook_bytes": source,
        "transcript_extract_bytes": TRANSCRIPT_EXTRACT,
    }


def _freeze(catalog: bytes, chain: dict[str, bytes]) -> dict[str, object]:
    return build_accepted_measure_catalog(catalog, **chain)


def test_human_review_path_still_rejects_missing_active_seconds() -> None:
    catalog = _catalog_bytes()
    _, adjudicated = _adjudicated_workbook(catalog)
    proposal, approval = _base_approval()

    with pytest.raises(MeasureReviewError, match="complete review fields"):
        materialize_measure_review_decisions(
            catalog,
            adjudicated,
            proposal,
            approval,
        )


def test_accepted_catalog_freeze_is_deterministic_and_removes_pending_review() -> None:
    catalog = _catalog_bytes()
    chain = _decision_chain(catalog)

    first = _freeze(catalog, chain)
    second = _freeze(catalog, chain)

    assert first == second
    assert first["kind"] == "public-evidence-measure-catalog"
    assert first["catalog_version"] == "public-evidence-measure-catalog-v1"
    assert first["summary"] == {
        "accepted_candidate_count": 1,
        "accepted_database_count": 1,
        "accepted_databases": ["db"],
        "candidate_count_by_class": {"entity_count": 1},
        "measure_count_by_database": {"db": 1},
    }
    accepted = first["accepted_candidates"]
    assert isinstance(accepted, list)
    assert len(accepted) == 1
    assert "review" not in accepted[0]
    assert first["generator"] == {
        "database_count": 1,
        "databases": ["db"],
        "input_files": [
            {
                "path": "semantic_models/public_schema_ir/db.schema.jsonl",
                "sha256": "1" * 64,
            }
        ],
        "version": "r2-public-evidence-measure-candidates-v1",
    }
    assert (
        first["source"]["decision_artifact_sha256"]
        == hashlib.sha256(chain["decisions_bytes"]).hexdigest()
    )
    assert first["manifest"]["ordered_candidate_ids"] == [accepted[0]["candidate_id"]]
    assert first["manifest"]["ordered_measure_ids"] == [accepted[0]["measure_id"]]

    content = canonical_catalog_bytes(first)
    assert validate_accepted_measure_catalog(content, catalog, **chain) == first


def test_accepted_catalog_validator_rejects_changed_frozen_content() -> None:
    catalog = _catalog_bytes()
    chain = _decision_chain(catalog)
    frozen = _freeze(catalog, chain)
    frozen["accepted_candidates"][0]["measure"]["definition"]["label"] = "Changed"

    with pytest.raises(
        AcceptedMeasureCatalogError,
        match="does not reproduce from the approved chain",
    ):
        validate_accepted_measure_catalog(
            canonical_catalog_bytes(frozen),
            catalog,
            **chain,
        )


@pytest.mark.parametrize("mutation", ["decision", "provenance_binding", "catalog"])
def test_accepted_catalog_freeze_rejects_changed_authoritative_inputs(
    mutation: str,
) -> None:
    catalog = _catalog_bytes()
    chain = _decision_chain(catalog)
    if mutation in {"decision", "provenance_binding"}:
        decisions = json.loads(chain["decisions_bytes"])
        if mutation == "decision":
            decisions["decisions"][0]["reason_code"] = "mechanical_binding_corrected"
        else:
            decisions["source"]["provenance_sha256"] = "0" * 64
        chain["decisions_bytes"] = canonical_catalog_bytes(decisions)
    else:
        candidate_catalog = json.loads(catalog)
        candidate_catalog["candidates"][0]["measure"]["definition"]["label"] = "Changed"
        catalog = _reseal_catalog(candidate_catalog)

    with pytest.raises(AcceptedMeasureCatalogError):
        _freeze(catalog, chain)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("database_count", "database inventory"),
        ("summary_shape", "summary shape"),
        ("candidate_count", "summary count"),
        ("input_inventory", "input inventory"),
        ("input_shape", "input shape"),
        ("input_digest", "SHA-256 is invalid"),
        ("input_path", "input path is invalid"),
        ("input_order", "inputs must be sorted"),
        ("generator_version", "generator version must be non-empty text"),
    ],
)
def test_accepted_catalog_freeze_rejects_invalid_generator_inventory(
    mutation: str,
    message: str,
) -> None:
    candidate_catalog = json.loads(_catalog_bytes())
    manifest = candidate_catalog["manifest"]
    summary = candidate_catalog["database_summaries"][0]
    input_files = summary["input_files"]
    if mutation == "database_count":
        manifest["database_count"] = 2
    elif mutation == "summary_shape":
        summary["unexpected"] = True
    elif mutation == "candidate_count":
        summary["candidate_count"] = 2
    elif mutation == "input_inventory":
        summary["input_files"] = "not-a-list"
    elif mutation == "input_shape":
        input_files[0]["unexpected"] = True
    elif mutation == "input_digest":
        input_files[0]["sha256"] = "not-a-digest"
    elif mutation == "input_path":
        input_files[0]["path"] = "/absolute/source.jsonl"
    elif mutation == "input_order":
        summary["input_files"] = [
            {"path": "z.jsonl", "sha256": "2" * 64},
            {"path": "a.jsonl", "sha256": "3" * 64},
        ]
    else:
        candidate_catalog["generator_version"] = ""
    catalog = _reseal_catalog(candidate_catalog)
    chain = _decision_chain(catalog)

    with pytest.raises(AcceptedMeasureCatalogError, match=message):
        _freeze(catalog, chain)


def test_agent_provenance_is_deterministic_and_marks_unavailable_metrics() -> None:
    catalog = _catalog_bytes()
    source, adjudicated = _adjudicated_workbook(catalog)

    first = _provenance(source, adjudicated)
    second = _provenance(source, adjudicated)
    record = json.loads(first)

    assert first == second
    assert record["adjudicator"] == {
        "model": "GPT-5.6 sol",
        "product": "ChatGPT",
        "reasoning_effort": "High",
    }
    assert record["information_boundary"] == {
        "benchmark_jsonl_accessed": False,
        "public_dataset_landing_page_opened": True,
        "question_fields_accessed": False,
        "protected_or_gold_accessed": False,
        "underlying_source_artifacts_loaded": False,
    }
    assert record["workflow"]["elapsed_wall_clock_seconds"] == pytest.approx(617.642452)
    assert record["workflow"]["human_active_seconds"] is None
    assert record["workflow"]["tokens"] is None
    assert record["workflow"]["cost_usd"] is None
    assert (
        record["source"]["source_workbook_sha256"] == hashlib.sha256(source).hexdigest()
    )
    assert (
        record["source"]["adjudicated_workbook_sha256"]
        == hashlib.sha256(adjudicated).hexdigest()
    )
    assert (
        record["source"]["transcript_extract_sha256"]
        == hashlib.sha256(TRANSCRIPT_EXTRACT).hexdigest()
    )


def test_agent_adjudication_materializes_null_time_with_exact_approval_chain() -> None:
    catalog = _catalog_bytes()
    source, adjudicated = _adjudicated_workbook(catalog)
    base_proposal, base_approval = _base_approval()
    provenance = _provenance(source, adjudicated)
    amendment, amendment_approval = _amendment_approval(provenance)

    artifact = materialize_measure_agent_adjudication(
        catalog,
        source,
        adjudicated,
        provenance,
        TRANSCRIPT_EXTRACT,
        base_proposal,
        base_approval,
        amendment,
        amendment_approval,
    )

    assert artifact["kind"] == "public-evidence-measure-agent-adjudication-decisions"
    assert artifact["schema_version"] == 1
    assert artifact["adjudication_rule"]["version"] == ("chatgpt_packet_pk_binding_v1")
    assert artifact["adjudicator"] == {
        "model": "GPT-5.6 sol",
        "product": "ChatGPT",
        "reasoning_effort": "High",
    }
    assert artifact["information_boundary"]["question_fields_accessed"] is False
    assert artifact["summary"] == {
        "accept": 1,
        "active_review_seconds": None,
        "adjudicated_candidates": 1,
        "agent_elapsed_wall_clock_seconds": pytest.approx(617.642452),
        "binding_corrections": 0,
        "defer": 0,
        "reject": 0,
    }
    assert artifact["decisions"][0]["active_review_seconds"] is None
    assert artifact["decisions"][0]["status"] == "agent_adjudicated"
    assert (
        artifact["source"]["provenance_sha256"]
        == hashlib.sha256(provenance).hexdigest()
    )
    assert (
        artifact["source"]["amendment_approval_record_sha256"]
        == hashlib.sha256(amendment_approval).hexdigest()
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("timing", "must remain blank"),
        ("decision", "recovered adjudication rule"),
        ("immutable", "immutable candidate column"),
    ],
)
def test_agent_adjudication_rejects_timing_rule_and_immutable_mutations(
    mutation: str,
    message: str,
) -> None:
    catalog = _catalog_bytes()
    source, adjudicated = _adjudicated_workbook(catalog)
    rows = _rows(adjudicated)
    if mutation == "timing":
        rows[0]["active_review_seconds"] = "1"
    elif mutation == "decision":
        rows[0]["decision"] = "defer"
        rows[0]["reason_code"] = "reviewer_uncertain"
    else:
        rows[0]["sql"] = "${db_public__orders.other_id}"
    mutated = _encode_rows(rows)

    with pytest.raises(MeasureReviewError, match=message):
        _provenance(source, mutated)


def test_agent_adjudication_rejects_output_changed_after_provenance() -> None:
    catalog = _catalog_bytes()
    source, adjudicated = _adjudicated_workbook(catalog)
    provenance = _provenance(source, adjudicated)
    rows = _rows(adjudicated)
    rows[0]["decision"] = "defer"
    rows[0]["reason_code"] = "reviewer_uncertain"
    mutated = _encode_rows(rows)
    base_proposal, base_approval = _base_approval()
    amendment, amendment_approval = _amendment_approval(provenance)

    with pytest.raises(MeasureReviewError, match="output workbook hash"):
        materialize_measure_agent_adjudication(
            catalog,
            source,
            mutated,
            provenance,
            TRANSCRIPT_EXTRACT,
            base_proposal,
            base_approval,
            amendment,
            amendment_approval,
        )


def test_agent_adjudication_rejects_provenance_or_amendment_mismatch() -> None:
    catalog = _catalog_bytes()
    source, adjudicated = _adjudicated_workbook(catalog)
    base_proposal, base_approval = _base_approval()
    provenance = _provenance(source, adjudicated)
    amendment, amendment_approval = _amendment_approval(provenance)
    altered_provenance = json.loads(provenance)
    altered_provenance["information_boundary"]["question_fields_accessed"] = True
    altered_provenance_bytes = canonical_catalog_bytes(altered_provenance)
    _, altered_provenance_approval = _amendment_approval(altered_provenance_bytes)

    with pytest.raises(MeasureReviewError, match="information boundary"):
        materialize_measure_agent_adjudication(
            catalog,
            source,
            adjudicated,
            altered_provenance_bytes,
            TRANSCRIPT_EXTRACT,
            base_proposal,
            base_approval,
            amendment,
            altered_provenance_approval,
        )
    with pytest.raises(MeasureReviewError, match="amendment hash"):
        materialize_measure_agent_adjudication(
            catalog,
            source,
            adjudicated,
            provenance,
            TRANSCRIPT_EXTRACT,
            base_proposal,
            base_approval,
            amendment + b"changed",
            amendment_approval,
        )


def test_real_agent_adjudication_workbook_matches_recovered_rule() -> None:
    catalog = (
        REPOSITORY_ROOT
        / "experiments/r2-public-evidence-measures/measure-review-catalog-v2.json"
    ).read_bytes()
    source = (
        REPOSITORY_ROOT
        / "experiments/r2-public-evidence-measures/measure-review-workbook-v1.csv"
    ).read_bytes()
    adjudicated = (
        REPOSITORY_ROOT
        / "experiments/r2-public-evidence-measures/measure-review-workbook-v1-validated.csv"
    ).read_bytes()
    transcript = (
        REPOSITORY_ROOT / "experiments/r2-public-evidence-measures/"
        "agent-adjudication-transcript-extract-v1.md"
    ).read_bytes()
    provenance = (
        REPOSITORY_ROOT / "experiments/r2-public-evidence-measures/"
        "agent-adjudication-provenance-v1.json"
    ).read_bytes()
    base_proposal = (
        REPOSITORY_ROOT / "docs/protocol-amendment-public-evidence-measures-proposal.md"
    ).read_bytes()
    base_approval = (
        REPOSITORY_ROOT
        / "experiments/r2-public-evidence-measures/protocol-approval-v1.json"
    ).read_bytes()
    amendment = b"synthetic exact amendment for offline integration test\n"
    amendment_approval = canonical_catalog_bytes(
        build_protocol_amendment_approval_record(
            amendment,
            provenance_bytes=provenance,
            approved_by="test operator",
            approved_at="2026-09-01T13:00:00Z",
        )
    )

    artifact = materialize_measure_agent_adjudication(
        catalog,
        source,
        adjudicated,
        provenance,
        transcript,
        base_proposal,
        base_approval,
        amendment,
        amendment_approval,
    )

    assert artifact["summary"]["adjudicated_candidates"] == 812
    assert artifact["summary"]["accept"] == 812
    assert artifact["summary"]["active_review_seconds"] is None


def test_real_agent_provenance_regenerates_byte_identically() -> None:
    root = REPOSITORY_ROOT / "experiments/r2-public-evidence-measures"
    source = (root / "measure-review-workbook-v1.csv").read_bytes()
    adjudicated = (root / "measure-review-workbook-v1-validated.csv").read_bytes()
    transcript = (root / "agent-adjudication-transcript-extract-v1.md").read_bytes()
    observed = (root / "agent-adjudication-provenance-v1.json").read_bytes()

    regenerated = canonical_catalog_bytes(
        build_agent_adjudication_provenance(
            source,
            adjudicated,
            transcript_extract_bytes=transcript,
            transcript_extract_path=(
                "experiments/r2-public-evidence-measures/"
                "agent-adjudication-transcript-extract-v1.md"
            ),
            source_url=(
                "https://chatgpt.com/share/6a96c57e-01c0-83ea-aa79-5eda508be2f6"
            ),
            retrieved_at="2026-09-01T12:46:58Z",
            started_at="2026-09-01T12:07:17.946000Z",
            completed_at="2026-09-01T12:17:35.588452Z",
            product="ChatGPT",
            model="GPT-5.6 sol",
            reasoning_effort="High",
            user_instruction_messages=2,
            assistant_text_messages=7,
            tool_call_messages=42,
            correction_rounds=1,
        )
    )

    assert regenerated == observed
    assert hashlib.sha256(observed).hexdigest() == (
        "c6e82efc4cb1f069cd5a257de4f7d1cc68e20cc8ee507e14c9c2a92e8bb7b1b0"
    )


def test_real_agent_decisions_regenerate_byte_identically() -> None:
    root = REPOSITORY_ROOT / "experiments/r2-public-evidence-measures"
    catalog = (root / "measure-review-catalog-v2.json").read_bytes()
    source = (root / "measure-review-workbook-v1.csv").read_bytes()
    adjudicated = (root / "measure-review-workbook-v1-validated.csv").read_bytes()
    provenance = (root / "agent-adjudication-provenance-v1.json").read_bytes()
    transcript = (root / "agent-adjudication-transcript-extract-v1.md").read_bytes()
    base_proposal = (
        REPOSITORY_ROOT / "docs/protocol-amendment-public-evidence-measures-proposal.md"
    ).read_bytes()
    base_approval = (root / "protocol-approval-v1.json").read_bytes()
    amendment = (
        REPOSITORY_ROOT / "docs/protocol-amendment-agent-adjudication-proposal.md"
    ).read_bytes()
    amendment_approval = (
        root / "agent-adjudication-amendment-approval-v1.json"
    ).read_bytes()
    observed = (root / "measure-agent-adjudication-decisions-v1.json").read_bytes()

    regenerated = canonical_catalog_bytes(
        materialize_measure_agent_adjudication(
            catalog,
            source,
            adjudicated,
            provenance,
            transcript,
            base_proposal,
            base_approval,
            amendment,
            amendment_approval,
        )
    )

    assert regenerated == observed
    assert hashlib.sha256(observed).hexdigest() == (
        "332d29892ac362985478a674027cf4aa5a760825c4d9ea253a021b5f869ff5a2"
    )


def test_real_accepted_catalog_regenerates_byte_identically() -> None:
    root = REPOSITORY_ROOT / "experiments/r2-public-evidence-measures"
    catalog = (root / "measure-review-catalog-v2.json").read_bytes()
    chain = {
        "decisions_bytes": (
            root / "measure-agent-adjudication-decisions-v1.json"
        ).read_bytes(),
        "source_workbook_bytes": (root / "measure-review-workbook-v1.csv").read_bytes(),
        "adjudicated_workbook_bytes": (
            root / "measure-review-workbook-v1-validated.csv"
        ).read_bytes(),
        "provenance_bytes": (
            root / "agent-adjudication-provenance-v1.json"
        ).read_bytes(),
        "transcript_extract_bytes": (
            root / "agent-adjudication-transcript-extract-v1.md"
        ).read_bytes(),
        "base_proposal_bytes": (
            REPOSITORY_ROOT
            / "docs/protocol-amendment-public-evidence-measures-proposal.md"
        ).read_bytes(),
        "base_approval_record_bytes": (root / "protocol-approval-v1.json").read_bytes(),
        "amendment_proposal_bytes": (
            REPOSITORY_ROOT / "docs/protocol-amendment-agent-adjudication-proposal.md"
        ).read_bytes(),
        "amendment_approval_record_bytes": (
            root / "agent-adjudication-amendment-approval-v1.json"
        ).read_bytes(),
    }
    path = root / "public-evidence-measure-catalog-v1.json"
    observed = path.read_bytes()

    regenerated = validate_accepted_measure_catalog(observed, catalog, **chain)

    assert regenerated["summary"]["accepted_candidate_count"] == 812
    assert regenerated["summary"]["accepted_database_count"] == 16
    assert len(regenerated["generator"]["input_files"]) == 81
    assert all("review" not in item for item in regenerated["accepted_candidates"])
    assert path.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(observed).hexdigest() == (
        "2d2f9c15bc5f5271db924fa4377b41c26a0e61bcec221ed31d10b3365358039a"
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("summary", "summary"),
        ("limitations", "limitations"),
        ("extra", "shape"),
    ],
)
def test_agent_adjudication_rejects_altered_provenance_claims(
    mutation: str,
    message: str,
) -> None:
    catalog = _catalog_bytes()
    source, adjudicated = _adjudicated_workbook(catalog)
    provenance = json.loads(_provenance(source, adjudicated))
    if mutation == "summary":
        provenance["summary"]["accept"] = 0
    elif mutation == "limitations":
        provenance["limitations"] = []
    else:
        provenance["unsupported_claim"] = True
    provenance.pop("manifest")
    provenance["manifest"] = {
        "artifact_sha256": hashlib.sha256(
            canonical_catalog_bytes(provenance)
        ).hexdigest()
    }
    altered = canonical_catalog_bytes(provenance)
    amendment, amendment_approval = _amendment_approval(altered)
    base_proposal, base_approval = _base_approval()

    with pytest.raises(MeasureReviewError, match=message):
        materialize_measure_agent_adjudication(
            catalog,
            source,
            adjudicated,
            altered,
            TRANSCRIPT_EXTRACT,
            base_proposal,
            base_approval,
            amendment,
            amendment_approval,
        )


def test_agent_adjudication_approval_binds_exact_provenance() -> None:
    catalog = _catalog_bytes()
    source, adjudicated = _adjudicated_workbook(catalog)
    provenance = _provenance(source, adjudicated)
    amendment, amendment_approval = _amendment_approval(provenance)
    altered = provenance + b"\n"
    base_proposal, base_approval = _base_approval()

    with pytest.raises(MeasureReviewError, match="provenance hash"):
        materialize_measure_agent_adjudication(
            catalog,
            source,
            adjudicated,
            altered,
            TRANSCRIPT_EXTRACT,
            base_proposal,
            base_approval,
            amendment,
            amendment_approval,
        )


def test_agent_provenance_and_validation_cli_round_trip(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_bytes = _catalog_bytes()
    source_bytes, adjudicated_bytes = _adjudicated_workbook(catalog_bytes)
    base_proposal_bytes, base_approval_bytes = _base_approval()
    amendment_bytes = b"exact agent adjudication amendment\n"
    catalog = tmp_path / "catalog.json"
    source = tmp_path / "source.csv"
    adjudicated = tmp_path / "adjudicated.csv"
    provenance = tmp_path / "provenance.json"
    transcript_extract = tmp_path / "agent-transcript-v1.md"
    base_proposal = tmp_path / "base-proposal.md"
    base_approval = tmp_path / "base-approval.json"
    amendment = tmp_path / "amendment.md"
    amendment_approval = tmp_path / "amendment-approval.json"
    decisions = tmp_path / "decisions.json"
    frozen_catalog = tmp_path / "accepted-catalog.json"
    catalog.write_bytes(catalog_bytes)
    source.write_bytes(source_bytes)
    adjudicated.write_bytes(adjudicated_bytes)
    transcript_extract.write_bytes(TRANSCRIPT_EXTRACT)
    base_proposal.write_bytes(base_proposal_bytes)
    base_approval.write_bytes(base_approval_bytes)
    amendment.write_bytes(amendment_bytes)

    assert (
        main(
            [
                "agent-provenance",
                "--source-workbook",
                str(source),
                "--adjudicated-workbook",
                str(adjudicated),
                "--transcript-extract",
                str(transcript_extract),
                "--transcript-extract-path",
                "experiments/r2/agent-transcript-v1.md",
                "--source-url",
                "https://chatgpt.com/share/6a96c57e-01c0-83ea-aa79-5eda508be2f6",
                "--retrieved-at",
                "2026-09-01T12:31:00Z",
                "--started-at",
                "2026-09-01T12:07:17.946000Z",
                "--completed-at",
                "2026-09-01T12:17:35.588452Z",
                "--product",
                "ChatGPT",
                "--model",
                "GPT-5.6 sol",
                "--reasoning-effort",
                "High",
                "--user-instruction-messages",
                "2",
                "--assistant-text-messages",
                "7",
                "--tool-call-messages",
                "42",
                "--correction-rounds",
                "1",
                "--output",
                str(provenance),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["adjudicated_candidates"] == 1

    assert (
        main(
            [
                "amendment-approval-record",
                "--proposal",
                str(amendment),
                "--provenance",
                str(provenance),
                "--approved-by",
                "operator",
                "--approved-at",
                "2026-09-01T13:00:00Z",
                "--output",
                str(amendment_approval),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "validate-agent",
                "--catalog",
                str(catalog),
                "--source-workbook",
                str(source),
                "--adjudicated-workbook",
                str(adjudicated),
                "--provenance",
                str(provenance),
                "--transcript-extract",
                str(transcript_extract),
                "--base-proposal",
                str(base_proposal),
                "--base-approval-record",
                str(base_approval),
                "--amendment-proposal",
                str(amendment),
                "--amendment-approval-record",
                str(amendment_approval),
                "--output",
                str(decisions),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["adjudicated_candidates"] == 1
    assert report["active_review_seconds"] is None
    assert provenance.stat().st_mode & 0o777 == 0o600
    assert amendment_approval.stat().st_mode & 0o777 == 0o600
    assert decisions.stat().st_mode & 0o777 == 0o600

    assert (
        main(
            [
                "freeze-agent-catalog",
                "--catalog",
                str(catalog),
                "--decisions",
                str(decisions),
                "--source-workbook",
                str(source),
                "--adjudicated-workbook",
                str(adjudicated),
                "--provenance",
                str(provenance),
                "--transcript-extract",
                str(transcript_extract),
                "--base-proposal",
                str(base_proposal),
                "--base-approval-record",
                str(base_approval),
                "--amendment-proposal",
                str(amendment),
                "--amendment-approval-record",
                str(amendment_approval),
                "--output",
                str(frozen_catalog),
            ]
        )
        == 0
    )
    freeze_report = json.loads(capsys.readouterr().out)
    assert freeze_report == {
        "accepted_candidate_count": 1,
        "accepted_database_count": 1,
        "accepted_databases": ["db"],
        "candidate_count_by_class": {"entity_count": 1},
        "measure_count_by_database": {"db": 1},
    }
    assert frozen_catalog.stat().st_mode & 0o777 == 0o600
    with pytest.raises(MeasureReviewError, match="already exists"):
        main(
            [
                "freeze-agent-catalog",
                "--catalog",
                str(catalog),
                "--decisions",
                str(decisions),
                "--source-workbook",
                str(source),
                "--adjudicated-workbook",
                str(adjudicated),
                "--provenance",
                str(provenance),
                "--transcript-extract",
                str(transcript_extract),
                "--base-proposal",
                str(base_proposal),
                "--base-approval-record",
                str(base_approval),
                "--amendment-proposal",
                str(amendment),
                "--amendment-approval-record",
                str(amendment_approval),
                "--output",
                str(frozen_catalog),
            ]
        )

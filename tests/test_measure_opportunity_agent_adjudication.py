from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from omni_benchmark.measure_opportunity_map import (
    OPPORTUNITY_REVIEW_COLUMNS,
    MeasureOpportunityMapError,
    build_measure_opportunity_review_workbook,
    build_observed_opportunity_amendment_approval_record,
    build_opportunity_output_adoption_record,
    materialize_agent_adjudicated_measure_opportunity_map,
    validate_agent_adjudicated_measure_opportunity_map,
)
from omni_benchmark.measure_review_catalog import canonical_catalog_bytes


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_blob(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324


def _candidate(database: str, suffix: str) -> dict[str, object]:
    field_id = f"{database}:column:things_{suffix}:id"
    return {
        "candidate_class": "entity_count",
        "candidate_id": f"candidate-{database}-{suffix}",
        "database": database,
        "evidence": {
            "identity_field_stable_id": field_id,
            "identity_kind": "primary_key",
            "public_records": [],
            "table_stable_id": f"{database}:table:things_{suffix}",
        },
        "inline_equivalent_signature": {
            "aggregate_type": "count_distinct",
            "source_field_stable_ids": [field_id],
        },
        "measure": {
            "definition": {
                "aggregate_type": "count_distinct",
                "description": f"Count of distinct things {suffix}.",
                "label": f"Things {suffix} Count",
                "sql": f"${{{database}_public__things_{suffix}.id}}",
            },
            "name": "count",
        },
        "measure_id": f"measure-{database}-{suffix}",
        "proposed_omni_yaml": "measures: {}\n",
        "view": {
            "file_name": f"{database}.things_{suffix}.view",
            "table_stable_id": f"{database}:table:things_{suffix}",
            "view_name": f"{database}_public__things_{suffix}",
        },
    }


def _catalog_bytes() -> bytes:
    candidates = [_candidate("db_a", "one"), _candidate("db_a", "two")]
    candidates.sort(key=lambda item: str(item["candidate_id"]))
    artifact: dict[str, object] = {
        "accepted_candidates": candidates,
        "catalog_version": "public-evidence-measure-catalog-v1",
        "generator": {
            "database_count": 1,
            "databases": ["db_a"],
            "input_files": [],
            "version": "r2-public-evidence-measure-candidates-v1",
        },
        "kind": "public-evidence-measure-catalog",
        "manifest": {
            "ordered_candidate_ids": [str(item["candidate_id"]) for item in candidates],
            "ordered_measure_ids": [str(item["measure_id"]) for item in candidates],
        },
        "schema_version": 1,
        "source": {"decision_artifact_sha256": "1" * 64},
        "summary": {
            "accepted_candidate_count": 2,
            "accepted_database_count": 1,
            "accepted_databases": ["db_a"],
            "candidate_count_by_class": {"entity_count": 2},
            "measure_count_by_database": {"db_a": 2},
        },
    }
    manifest = artifact["manifest"]
    assert isinstance(manifest, dict)
    manifest["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    return canonical_catalog_bytes(artifact)


def _record(instance_id: str, query: str) -> dict[str, object]:
    return {
        "category": "Query",
        "clean_up_sqls": [],
        "conditions": {"decimal": 2, "distinct": False, "order": True},
        "high_level": False,
        "instance_id": instance_id,
        "normal_query": f"Normal phrasing for {instance_id}",
        "preprocess_sql": [],
        "query": query,
        "selected_database": "db_a",
        "source_index": 1,
    }


def _rows(workbook: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(workbook.decode(), newline="")))


def _encode_rows(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(OPPORTUNITY_REVIEW_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _prospective_approval(proposal: bytes) -> bytes:
    return canonical_catalog_bytes(
        {
            "approved_at": "2026-09-01T20:00:00Z",
            "approved_by": "operator",
            "decision": "approved",
            "kind": (
                "r2-public-evidence-measures-"
                "opportunity-agent-adjudication-amendment-approval"
            ),
            "proposal_git_blob": _git_blob(proposal),
            "proposal_sha256": _sha256(proposal),
            "schema_version": 1,
        }
    )


def _provenance(
    blank: bytes,
    adjudicated: bytes,
    instructions: bytes,
    prospective_proposal: bytes,
    prospective_approval: bytes,
) -> bytes:
    rows = _rows(adjudicated)
    counts = {decision: 0 for decision in ("ambiguous", "mapped", "none")}
    selected = 0
    ambiguous_ids: list[str] = []
    for row in rows:
        counts[row["decision"]] += 1
        selected += len(json.loads(row["measure_ids_json"]))
        if row["decision"] == "ambiguous":
            ambiguous_ids.append(row["instance_id"])
    artifact: dict[str, object] = {
        "adjudicator": {
            "interface": "Codex",
            "model_family": "GPT-5",
            "product": "ChatGPT Work",
            "reasoning_effort": None,
            "reasoning_effort_status": "runtime_managed_not_exposed",
        },
        "information_boundary": {
            "accepted_catalog_file_accessed": False,
            "benchmark_jsonl_accessed": False,
            "dev_b_accessed": False,
            "external_files_accessed": False,
            "gold_or_correctness_accessed": False,
            "hidden_annotations_accessed": False,
            "normal_query_accessed": False,
            "prior_run_outcomes_accessed": False,
            "sealed_test_accessed": False,
            "sql_accessed": False,
            "web_browsing_used": False,
            "workbook_question_cells_accessed": True,
        },
        "kind": "r2-measure-opportunity-agent-adjudication-provenance",
        "limitations": [
            "exact_model_not_exposed",
            "reasoning_effort_not_exposed",
            "run_preceded_exact_protocol_approval",
            "no_shared_transcript_or_session_timestamps",
            "instruction_delivery_not_independently_authenticated",
            "semantic_decisions_not_independently_revalidated",
        ],
        "manifest": {},
        "schema_version": 1,
        "source": {
            "approved_prospective_amendment_sha256": _sha256(prospective_proposal),
            "blank_workbook_sha256": _sha256(blank),
            "instruction_contract_path": (
                "experiments/r2-public-evidence-measures/"
                "measure-opportunity-agent-adjudication-instructions-v1.md"
            ),
            "instruction_contract_sha256": _sha256(instructions),
            "observed_output_path": (
                "experiments/r2-public-evidence-measures/"
                "measure-opportunity-review-workbook-v1-agent-adjudicated.csv"
            ),
            "observed_output_sha256": _sha256(adjudicated),
            "operator_approval_record_sha256": _sha256(prospective_approval),
            "provenance_basis": (
                "operator-supplied verbatim agent summary in approval turn"
            ),
        },
        "summary": {
            "ambiguous": counts["ambiguous"],
            "ambiguous_instance_ids": ambiguous_ids,
            "mapped": counts["mapped"],
            "none": counts["none"],
            "reviewed_rows": len(rows),
            "selected_measure_assignments": selected,
        },
        "validation": {
            "active_review_seconds_all_blank": True,
            "decision_contract_valid": True,
            "immutable_cells_match_blank_workbook": True,
            "mechanical_status": "passed",
            "row_count": len(rows),
            "selected_ids_same_row_sorted_unique": True,
        },
        "workflow": {
            "active_review_seconds": None,
            "cost_usd": None,
            "elapsed_wall_clock_seconds": None,
            "input_files": ["measure-opportunity-review-workbook-v1.csv"],
            "local_tools": [
                "python_csv_parsing",
                "python_json_parsing",
                "file_generation",
                "validation",
                "sha256_calculation",
            ],
            "tokens": None,
        },
    }
    digest_source = copy.deepcopy(artifact)
    manifest = digest_source["manifest"]
    assert isinstance(manifest, dict)
    manifest["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    return canonical_catalog_bytes(digest_source)


def _fixture() -> dict[str, bytes]:
    catalog = _catalog_bytes()
    records = [
        _record("q1", "How many things one are there?"),
        _record("q2", "Show the average value."),
        _record("q3", "How many things are involved?"),
    ]
    manifest = b"".join(canonical_catalog_bytes(record) for record in records)
    dev_ids = b"q1\nq2\nq3\n"
    blank = build_measure_opportunity_review_workbook(
        catalog,
        manifest,
        dev_ids,
        expected_dev_a_count=3,
        expected_frame_count=3,
    )
    rows = _rows(blank)
    rows[0]["decision"] = "mapped"
    rows[0]["measure_ids_json"] = '["measure-db_a-one"]'
    rows[1]["decision"] = "none"
    rows[2]["decision"] = "ambiguous"
    rows[2]["measure_ids_json"] = '["measure-db_a-one","measure-db_a-two"]'
    adjudicated = _encode_rows(rows)
    instructions = b"exact agent instructions\n"
    prospective_proposal = b"exact prospective amendment\n"
    prospective_approval = _prospective_approval(prospective_proposal)
    provenance = _provenance(
        blank,
        adjudicated,
        instructions,
        prospective_proposal,
        prospective_approval,
    )
    corrective_proposal = b"exact observed-workflow amendment\n"
    corrective_approval = canonical_catalog_bytes(
        build_observed_opportunity_amendment_approval_record(
            corrective_proposal,
            provenance_bytes=provenance,
            adjudicated_workbook_bytes=adjudicated,
            approved_by="operator",
            approved_at="2026-09-01T21:00:00Z",
        )
    )
    output_adoption = canonical_catalog_bytes(
        build_opportunity_output_adoption_record(
            source_workbook_bytes=blank,
            adjudicated_workbook_bytes=adjudicated,
            instructions_bytes=instructions,
            prospective_approval_record_bytes=prospective_approval,
            corrective_proposal_bytes=corrective_proposal,
            corrective_approval_record_bytes=corrective_approval,
            provenance_bytes=provenance,
            adopted_by="operator",
            adopted_at="2026-09-01T21:00:00Z",
        )
    )
    return {
        "accepted_catalog_bytes": catalog,
        "public_manifest_bytes": manifest,
        "dev_a_ids_bytes": dev_ids,
        "source_workbook_bytes": blank,
        "adjudicated_workbook_bytes": adjudicated,
        "instructions_bytes": instructions,
        "prospective_proposal_bytes": prospective_proposal,
        "prospective_approval_record_bytes": prospective_approval,
        "corrective_proposal_bytes": corrective_proposal,
        "corrective_approval_record_bytes": corrective_approval,
        "provenance_bytes": provenance,
        "output_adoption_record_bytes": output_adoption,
    }


def _materialize(inputs: dict[str, bytes]) -> dict[str, object]:
    return materialize_agent_adjudicated_measure_opportunity_map(
        **inputs,
        expected_dev_a_count=3,
        expected_frame_count=3,
    )


def test_agent_map_materializes_null_time_and_exact_approval_chain() -> None:
    inputs = _fixture()

    artifact = _materialize(inputs)

    assert artifact["kind"] == "public-evidence-measure-opportunity-map"
    assert artifact["map_version"] == "r2-public-evidence-measure-opportunity-map-v1"
    assert artifact["adjudication"] == {
        "adjudicator": {
            "interface": "Codex",
            "model_family": "GPT-5",
            "product": "ChatGPT Work",
            "reasoning_effort": None,
            "reasoning_effort_status": "runtime_managed_not_exposed",
        },
        "status": "agent_adjudicated",
    }
    assert artifact["summary"] == {
        "active_review_seconds": None,
        "ambiguous_candidate_assignments": 2,
        "ambiguous_question_count": 1,
        "eligible_question_count": 3,
        "mapped_measure_assignments": 1,
        "mapped_question_count": 1,
        "none_question_count": 1,
        "opportunity_question_count": 1,
    }
    decisions = artifact["decisions"]
    assert isinstance(decisions, list)
    assert all(item["active_review_seconds"] is None for item in decisions)
    assert artifact["source"]["provenance_sha256"] == _sha256(
        inputs["provenance_bytes"]
    )
    encoded = canonical_catalog_bytes(artifact)
    assert b"How many things" not in encoded
    assert b"eligible_measure_options_json" not in encoded

    validated = validate_agent_adjudicated_measure_opportunity_map(
        encoded,
        **inputs,
        expected_dev_a_count=3,
        expected_frame_count=3,
    )
    assert validated == artifact


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("immutable", "immutable review column"),
        ("active_time", "blank for agent adjudication"),
        ("unknown_measure", "unknown measure"),
        ("instructions", "instruction contract hash"),
        ("prospective_approval", "prospective approval"),
        ("corrective_approval", "corrective approval"),
        ("provenance", "provenance"),
        ("output_adoption", "output adoption"),
    ],
)
def test_agent_map_rejects_artifact_and_approval_chain_drift(
    mutation: str,
    message: str,
) -> None:
    inputs = _fixture()
    if mutation in {"immutable", "active_time", "unknown_measure"}:
        rows = _rows(inputs["adjudicated_workbook_bytes"])
        if mutation == "immutable":
            rows[0]["database"] = "other"
        elif mutation == "active_time":
            rows[0]["active_review_seconds"] = "0"
        else:
            rows[0]["measure_ids_json"] = '["unknown"]'
        inputs["adjudicated_workbook_bytes"] = _encode_rows(rows)
    elif mutation == "instructions":
        inputs["instructions_bytes"] += b"changed\n"
    else:
        key = {
            "corrective_approval": "corrective_approval_record_bytes",
            "output_adoption": "output_adoption_record_bytes",
            "prospective_approval": "prospective_approval_record_bytes",
            "provenance": "provenance_bytes",
        }[mutation]
        value = json.loads(inputs[key])
        if mutation == "prospective_approval":
            value["proposal_sha256"] = "0" * 64
        elif mutation == "corrective_approval":
            value["observed_output_sha256"] = "0" * 64
        elif mutation == "provenance":
            value["adjudicator"]["model_family"] = "other"
        else:
            value["adjudicated_workbook_sha256"] = "0" * 64
        inputs[key] = canonical_catalog_bytes(value)

    with pytest.raises(MeasureOpportunityMapError, match=message):
        _materialize(inputs)


def test_agent_map_validation_rejects_changed_frozen_artifact() -> None:
    inputs = _fixture()
    artifact = _materialize(inputs)
    artifact["summary"]["mapped_question_count"] = 2

    with pytest.raises(MeasureOpportunityMapError, match="does not reproduce"):
        validate_agent_adjudicated_measure_opportunity_map(
            canonical_catalog_bytes(artifact),
            **inputs,
            expected_dev_a_count=3,
            expected_frame_count=3,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("shape", "provenance shape"),
        ("identity", "provenance identity"),
        ("boundary", "information boundary"),
        ("limitations", "limitations"),
        ("source_shape", "source shape"),
        ("proposal", "prospective amendment"),
        ("approval", "prospective approval"),
        ("blank", "blank workbook"),
        ("output", "observed output"),
        ("basis", "provenance basis"),
        ("summary", "provenance summary"),
        ("validation", "provenance validation"),
        ("workflow", "provenance workflow"),
        ("manifest", "provenance hash"),
    ],
)
def test_agent_map_rejects_false_or_drifted_provenance_claims(
    mutation: str,
    message: str,
) -> None:
    inputs = _fixture()
    provenance = json.loads(inputs["provenance_bytes"])
    if mutation == "shape":
        provenance["extra"] = True
    elif mutation == "identity":
        provenance["kind"] = "other"
    elif mutation == "boundary":
        provenance["information_boundary"]["web_browsing_used"] = True
    elif mutation == "limitations":
        provenance["limitations"] = []
    elif mutation == "source_shape":
        provenance["source"]["extra"] = True
    elif mutation == "proposal":
        provenance["source"]["approved_prospective_amendment_sha256"] = "0" * 64
    elif mutation == "approval":
        provenance["source"]["operator_approval_record_sha256"] = "0" * 64
    elif mutation == "blank":
        provenance["source"]["blank_workbook_sha256"] = "0" * 64
    elif mutation == "output":
        provenance["source"]["observed_output_sha256"] = "0" * 64
    elif mutation == "basis":
        provenance["source"]["provenance_basis"] = "other"
    elif mutation == "summary":
        provenance["summary"]["mapped"] = 0
    elif mutation == "validation":
        provenance["validation"]["mechanical_status"] = "failed"
    elif mutation == "workflow":
        provenance["workflow"]["tokens"] = 1
    else:
        provenance["manifest"]["artifact_sha256"] = "0" * 64
    inputs["provenance_bytes"] = canonical_catalog_bytes(provenance)
    inputs["corrective_approval_record_bytes"] = canonical_catalog_bytes(
        build_observed_opportunity_amendment_approval_record(
            inputs["corrective_proposal_bytes"],
            provenance_bytes=inputs["provenance_bytes"],
            adjudicated_workbook_bytes=inputs["adjudicated_workbook_bytes"],
            approved_by="operator",
            approved_at="2026-09-01T21:00:00Z",
        )
    )
    inputs["output_adoption_record_bytes"] = canonical_catalog_bytes(
        build_opportunity_output_adoption_record(
            source_workbook_bytes=inputs["source_workbook_bytes"],
            adjudicated_workbook_bytes=inputs["adjudicated_workbook_bytes"],
            instructions_bytes=inputs["instructions_bytes"],
            prospective_approval_record_bytes=inputs[
                "prospective_approval_record_bytes"
            ],
            corrective_proposal_bytes=inputs["corrective_proposal_bytes"],
            corrective_approval_record_bytes=inputs["corrective_approval_record_bytes"],
            provenance_bytes=inputs["provenance_bytes"],
            adopted_by="operator",
            adopted_at="2026-09-01T21:00:00Z",
        )
    )

    with pytest.raises(MeasureOpportunityMapError, match=message):
        _materialize(inputs)


def test_real_observed_approval_records_regenerate_byte_identically() -> None:
    root = REPOSITORY_ROOT / "experiments/r2-public-evidence-measures"
    corrective_proposal = (
        REPOSITORY_ROOT
        / "docs/protocol-amendment-observed-opportunity-adjudication-proposal.md"
    ).read_bytes()
    provenance = (
        root / "measure-opportunity-agent-adjudication-provenance-v1.json"
    ).read_bytes()
    adjudicated = (
        root / "measure-opportunity-review-workbook-v1-agent-adjudicated.csv"
    ).read_bytes()
    corrective_observed = (
        root / "measure-opportunity-observed-adjudication-amendment-approval-v1.json"
    ).read_bytes()
    corrective_expected = canonical_catalog_bytes(
        build_observed_opportunity_amendment_approval_record(
            corrective_proposal,
            provenance_bytes=provenance,
            adjudicated_workbook_bytes=adjudicated,
            approved_by="sjarmak (repository operator)",
            approved_at="2026-09-01T21:37:51Z",
        )
    )
    assert corrective_expected == corrective_observed

    output_observed = (
        root / "measure-opportunity-agent-adjudication-output-adoption-v1.json"
    ).read_bytes()
    output_expected = canonical_catalog_bytes(
        build_opportunity_output_adoption_record(
            source_workbook_bytes=(
                root / "measure-opportunity-review-workbook-v1.csv"
            ).read_bytes(),
            adjudicated_workbook_bytes=adjudicated,
            instructions_bytes=(
                root / "measure-opportunity-agent-adjudication-instructions-v1.md"
            ).read_bytes(),
            prospective_approval_record_bytes=(
                root
                / "measure-opportunity-agent-adjudication-amendment-approval-v1.json"
            ).read_bytes(),
            corrective_proposal_bytes=corrective_proposal,
            corrective_approval_record_bytes=corrective_observed,
            provenance_bytes=provenance,
            adopted_by="sjarmak (repository operator)",
            adopted_at="2026-09-01T21:37:51Z",
        )
    )
    assert output_expected == output_observed


def test_real_adopted_agent_map_regenerates_byte_identically() -> None:
    root = REPOSITORY_ROOT / "experiments/r2-public-evidence-measures"
    content = (root / "measure-opportunity-map-v1.json").read_bytes()
    inputs = {
        "accepted_catalog_bytes": (
            root / "public-evidence-measure-catalog-v1.json"
        ).read_bytes(),
        "public_manifest_bytes": (
            REPOSITORY_ROOT / "data/manifests/eligible_questions.jsonl"
        ).read_bytes(),
        "dev_a_ids_bytes": (
            REPOSITORY_ROOT / "data/manifests/dev_a_ids.txt"
        ).read_bytes(),
        "source_workbook_bytes": (
            root / "measure-opportunity-review-workbook-v1.csv"
        ).read_bytes(),
        "adjudicated_workbook_bytes": (
            root / "measure-opportunity-review-workbook-v1-agent-adjudicated.csv"
        ).read_bytes(),
        "instructions_bytes": (
            root / "measure-opportunity-agent-adjudication-instructions-v1.md"
        ).read_bytes(),
        "prospective_proposal_bytes": (
            REPOSITORY_ROOT
            / "docs/protocol-amendment-opportunity-agent-adjudication-proposal.md"
        ).read_bytes(),
        "prospective_approval_record_bytes": (
            root / "measure-opportunity-agent-adjudication-amendment-approval-v1.json"
        ).read_bytes(),
        "corrective_proposal_bytes": (
            REPOSITORY_ROOT
            / "docs/protocol-amendment-observed-opportunity-adjudication-proposal.md"
        ).read_bytes(),
        "corrective_approval_record_bytes": (
            root
            / "measure-opportunity-observed-adjudication-amendment-approval-v1.json"
        ).read_bytes(),
        "provenance_bytes": (
            root / "measure-opportunity-agent-adjudication-provenance-v1.json"
        ).read_bytes(),
        "output_adoption_record_bytes": (
            root / "measure-opportunity-agent-adjudication-output-adoption-v1.json"
        ).read_bytes(),
    }

    artifact = validate_agent_adjudicated_measure_opportunity_map(content, **inputs)

    assert artifact["summary"] == {
        "active_review_seconds": None,
        "ambiguous_candidate_assignments": 3,
        "ambiguous_question_count": 1,
        "eligible_question_count": 136,
        "mapped_measure_assignments": 48,
        "mapped_question_count": 45,
        "none_question_count": 90,
        "opportunity_question_count": 45,
    }
    assert _sha256(content) == (
        "b834ebb7e2a033a85c0befc6eeba5949d40b71f5c3643da2ddb5f35c66afe279"
    )
    assert (root / "measure-opportunity-map-v1.json").stat().st_mode & 0o777 == 0o600
    assert b'"question"' not in content
    assert b"normal_query" not in content

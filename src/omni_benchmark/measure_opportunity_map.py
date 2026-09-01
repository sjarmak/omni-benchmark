"""Analysis-only R2 dev-A question-to-measure opportunity-map review."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .content_policy import ContentPolicy
from .direct_question_loader import (
    DirectQuestionLoadError,
    _ids,
    _public_records,
)
from .measure_review_catalog import canonical_catalog_bytes
from .protected_fields import ProtectedFieldError, reject_protected_fields


class MeasureOpportunityMapError(ValueError):
    """Raised when the analysis-only opportunity map is not reproducible."""


EXPECTED_DEV_A_COUNT = 154
EXPECTED_FRAME_COUNT = 136
OPPORTUNITY_REVIEW_COLUMNS = (
    "accepted_catalog_sha256",
    "public_manifest_sha256",
    "public_record_sha256",
    "question_sha256",
    "instance_id",
    "database",
    "question",
    "eligible_measure_options_json",
    "decision",
    "measure_ids_json",
    "active_review_seconds",
)

_REVIEW_COLUMNS = frozenset({"active_review_seconds", "decision", "measure_ids_json"})
_DECISIONS = frozenset({"ambiguous", "mapped", "none"})
_ACCEPTED_CATALOG_KEYS = frozenset(
    {
        "accepted_candidates",
        "catalog_version",
        "generator",
        "kind",
        "manifest",
        "schema_version",
        "source",
        "summary",
    }
)
_MAX_WORKBOOK_BYTES = 16_000_000
_FINAL_FORBIDDEN_KEYS = frozenset(
    {"eligible_measure_options_json", "normal_query", "question"}
)
_ACCEPTED_CATALOG_PATH = (
    "experiments/r2-public-evidence-measures/public-evidence-measure-catalog-v1.json"
)
_DEV_A_IDS_PATH = "data/manifests/dev_a_ids.txt"
_PUBLIC_MANIFEST_PATH = "data/manifests/eligible_questions.jsonl"
_SOURCE_WORKBOOK_PATH = (
    "experiments/r2-public-evidence-measures/measure-opportunity-review-workbook-v1.csv"
)
_ADJUDICATED_WORKBOOK_PATH = (
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-review-workbook-v1-agent-adjudicated.csv"
)
_INSTRUCTIONS_PATH = (
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-agent-adjudication-instructions-v1.md"
)
_PROSPECTIVE_PROPOSAL_PATH = (
    "docs/protocol-amendment-opportunity-agent-adjudication-proposal.md"
)
_PROSPECTIVE_APPROVAL_PATH = (
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-agent-adjudication-amendment-approval-v1.json"
)
_CORRECTIVE_PROPOSAL_PATH = (
    "docs/protocol-amendment-observed-opportunity-adjudication-proposal.md"
)
_CORRECTIVE_APPROVAL_PATH = (
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-observed-adjudication-amendment-approval-v1.json"
)
_PROVENANCE_PATH = (
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-agent-adjudication-provenance-v1.json"
)
_OUTPUT_ADOPTION_PATH = (
    "experiments/r2-public-evidence-measures/"
    "measure-opportunity-agent-adjudication-output-adoption-v1.json"
)
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_AGENT_ADJUDICATOR = {
    "interface": "Codex",
    "model_family": "GPT-5",
    "product": "ChatGPT Work",
    "reasoning_effort": None,
    "reasoning_effort_status": "runtime_managed_not_exposed",
}
_AGENT_INFORMATION_BOUNDARY = {
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
}
_AGENT_LIMITATIONS = [
    "exact_model_not_exposed",
    "reasoning_effort_not_exposed",
    "run_preceded_exact_protocol_approval",
    "no_shared_transcript_or_session_timestamps",
    "instruction_delivery_not_independently_authenticated",
    "semantic_decisions_not_independently_revalidated",
]
_AGENT_LOCAL_TOOLS = [
    "python_csv_parsing",
    "python_json_parsing",
    "file_generation",
    "validation",
    "sha256_calculation",
]


def build_observed_opportunity_amendment_approval_record(
    proposal_bytes: bytes,
    *,
    provenance_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    approved_by: str,
    approved_at: str,
) -> dict[str, Any]:
    """Bind operator approval to the observed-workflow correction and output."""
    _required_bytes(proposal_bytes, "corrective proposal")
    _required_bytes(provenance_bytes, "opportunity provenance")
    _required_bytes(adjudicated_workbook_bytes, "adjudicated workbook")
    return {
        "approved_at": _utc_second(approved_at, "approved_at"),
        "approved_by": _text(approved_by, "approved_by"),
        "decision": "approved",
        "kind": (
            "r2-public-evidence-measures-observed-opportunity-"
            "adjudication-amendment-approval"
        ),
        "observed_output_sha256": _sha256(adjudicated_workbook_bytes),
        "proposal_git_blob": _git_blob_hash(proposal_bytes),
        "proposal_sha256": _sha256(proposal_bytes),
        "provenance_sha256": _sha256(provenance_bytes),
        "schema_version": 1,
    }


def build_opportunity_output_adoption_record(
    *,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    instructions_bytes: bytes,
    prospective_approval_record_bytes: bytes,
    corrective_proposal_bytes: bytes,
    corrective_approval_record_bytes: bytes,
    provenance_bytes: bytes,
    adopted_by: str,
    adopted_at: str,
) -> dict[str, Any]:
    """Bind artifact-level adoption to every observed adjudication input."""
    inputs = {
        "blank workbook": source_workbook_bytes,
        "adjudicated workbook": adjudicated_workbook_bytes,
        "instruction contract": instructions_bytes,
        "prospective approval record": prospective_approval_record_bytes,
        "corrective proposal": corrective_proposal_bytes,
        "corrective approval record": corrective_approval_record_bytes,
        "opportunity provenance": provenance_bytes,
    }
    for label, content in inputs.items():
        _required_bytes(content, label)
    return {
        "adjudicated_workbook_sha256": _sha256(adjudicated_workbook_bytes),
        "adopted_at": _utc_second(adopted_at, "adopted_at"),
        "adopted_by": _text(adopted_by, "adopted_by"),
        "blank_workbook_sha256": _sha256(source_workbook_bytes),
        "corrective_amendment_approval_sha256": _sha256(
            corrective_approval_record_bytes
        ),
        "corrective_proposal_sha256": _sha256(corrective_proposal_bytes),
        "decision": "adopted",
        "instruction_contract_sha256": _sha256(instructions_bytes),
        "kind": (
            "r2-public-evidence-measures-opportunity-adjudication-output-adoption"
        ),
        "prospective_amendment_approval_sha256": _sha256(
            prospective_approval_record_bytes
        ),
        "provenance_sha256": _sha256(provenance_bytes),
        "schema_version": 1,
    }


def build_measure_opportunity_review_workbook(
    accepted_catalog_bytes: bytes,
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    *,
    expected_dev_a_count: int = EXPECTED_DEV_A_COUNT,
    expected_frame_count: int = EXPECTED_FRAME_COUNT,
) -> bytes:
    """Build the deterministic human-review packet after catalog freeze."""
    scope = _review_scope(
        accepted_catalog_bytes,
        public_manifest_bytes,
        dev_a_ids_bytes,
        expected_dev_a_count=expected_dev_a_count,
        expected_frame_count=expected_frame_count,
    )
    rows = [
        _review_row(
            instance_id,
            scope["records"][instance_id],
            scope["options_by_database"],
            accepted_catalog_sha256=_sha256(accepted_catalog_bytes),
            public_manifest_sha256=_sha256(public_manifest_bytes),
        )
        for instance_id in scope["frame_ids"]
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(OPPORTUNITY_REVIEW_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    content = output.getvalue().encode()
    if len(content) > _MAX_WORKBOOK_BYTES:
        raise MeasureOpportunityMapError("opportunity review workbook is too large")
    return content


def materialize_measure_opportunity_map(
    accepted_catalog_bytes: bytes,
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    workbook_bytes: bytes,
    *,
    expected_dev_a_count: int = EXPECTED_DEV_A_COUNT,
    expected_frame_count: int = EXPECTED_FRAME_COUNT,
) -> dict[str, Any]:
    """Validate a complete review and emit the question-text-free map."""
    blank = build_measure_opportunity_review_workbook(
        accepted_catalog_bytes,
        public_manifest_bytes,
        dev_a_ids_bytes,
        expected_dev_a_count=expected_dev_a_count,
        expected_frame_count=expected_frame_count,
    )
    expected_rows = _workbook_rows(blank)
    observed_rows = _workbook_rows(workbook_bytes)
    catalog = _accepted_catalog(accepted_catalog_bytes)
    decisions = _validated_decisions(
        expected_rows,
        observed_rows,
        global_measure_ids={
            candidate["measure_id"] for candidate in catalog["accepted_candidates"]
        },
    )
    decision_counts = Counter(item["decision"] for item in decisions)
    mapped_assignments = sum(
        len(item["measure_ids"]) for item in decisions if item["decision"] == "mapped"
    )
    ambiguous_assignments = sum(
        len(item["measure_ids"])
        for item in decisions
        if item["decision"] == "ambiguous"
    )
    artifact: dict[str, Any] = {
        "decisions": decisions,
        "kind": "public-evidence-measure-opportunity-map",
        "map_version": "r2-public-evidence-measure-opportunity-map-v1",
        "schema_version": 1,
        "source": {
            "accepted_catalog_path": _ACCEPTED_CATALOG_PATH,
            "accepted_catalog_sha256": _sha256(accepted_catalog_bytes),
            "dev_a_ids_path": _DEV_A_IDS_PATH,
            "dev_a_ids_sha256": _sha256(dev_a_ids_bytes),
            "public_manifest_path": _PUBLIC_MANIFEST_PATH,
            "public_manifest_sha256": _sha256(public_manifest_bytes),
            "review_workbook_sha256": _sha256(workbook_bytes),
        },
        "summary": {
            "active_review_seconds": math.fsum(
                item["active_review_seconds"] for item in decisions
            ),
            "ambiguous_candidate_assignments": ambiguous_assignments,
            "ambiguous_question_count": decision_counts["ambiguous"],
            "eligible_question_count": len(decisions),
            "mapped_measure_assignments": mapped_assignments,
            "mapped_question_count": decision_counts["mapped"],
            "none_question_count": decision_counts["none"],
            "opportunity_question_count": decision_counts["mapped"],
        },
    }
    artifact["manifest"] = {
        "ordered_instance_ids": [item["instance_id"] for item in decisions]
    }
    artifact["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    _reject_final_content(artifact)
    return artifact


def validate_measure_opportunity_map(
    content: bytes,
    accepted_catalog_bytes: bytes,
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    workbook_bytes: bytes,
    *,
    expected_dev_a_count: int = EXPECTED_DEV_A_COUNT,
    expected_frame_count: int = EXPECTED_FRAME_COUNT,
) -> dict[str, Any]:
    """Regenerate a frozen map from the exact review and public inputs."""
    expected = materialize_measure_opportunity_map(
        accepted_catalog_bytes,
        public_manifest_bytes,
        dev_a_ids_bytes,
        workbook_bytes,
        expected_dev_a_count=expected_dev_a_count,
        expected_frame_count=expected_frame_count,
    )
    if canonical_catalog_bytes(expected) != content:
        raise MeasureOpportunityMapError(
            "opportunity map does not reproduce from the frozen review"
        )
    return expected


def materialize_agent_adjudicated_measure_opportunity_map(
    accepted_catalog_bytes: bytes,
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    instructions_bytes: bytes,
    prospective_proposal_bytes: bytes,
    prospective_approval_record_bytes: bytes,
    corrective_proposal_bytes: bytes,
    corrective_approval_record_bytes: bytes,
    provenance_bytes: bytes,
    output_adoption_record_bytes: bytes,
    *,
    expected_dev_a_count: int = EXPECTED_DEV_A_COUNT,
    expected_frame_count: int = EXPECTED_FRAME_COUNT,
) -> dict[str, Any]:
    """Authenticate and materialize one adopted agent opportunity review."""
    blank = build_measure_opportunity_review_workbook(
        accepted_catalog_bytes,
        public_manifest_bytes,
        dev_a_ids_bytes,
        expected_dev_a_count=expected_dev_a_count,
        expected_frame_count=expected_frame_count,
    )
    if source_workbook_bytes != blank:
        raise MeasureOpportunityMapError(
            "source opportunity workbook does not reproduce exactly"
        )
    catalog = _accepted_catalog(accepted_catalog_bytes)
    decisions = _validated_agent_decisions(
        _workbook_rows(source_workbook_bytes),
        _workbook_rows(adjudicated_workbook_bytes),
        global_measure_ids={
            candidate["measure_id"] for candidate in catalog["accepted_candidates"]
        },
    )
    prospective_approval = _validated_opportunity_approval(
        prospective_proposal_bytes,
        prospective_approval_record_bytes,
        expected_kind=(
            "r2-public-evidence-measures-opportunity-agent-"
            "adjudication-amendment-approval"
        ),
        label="prospective approval",
    )
    corrective_approval = _validated_opportunity_approval(
        corrective_proposal_bytes,
        corrective_approval_record_bytes,
        expected_kind=(
            "r2-public-evidence-measures-observed-opportunity-"
            "adjudication-amendment-approval"
        ),
        label="corrective approval",
        expected_bindings={
            "observed_output_sha256": _sha256(adjudicated_workbook_bytes),
            "provenance_sha256": _sha256(provenance_bytes),
        },
    )
    provenance = _validated_opportunity_provenance(
        provenance_bytes,
        source_workbook_bytes=source_workbook_bytes,
        adjudicated_workbook_bytes=adjudicated_workbook_bytes,
        instructions_bytes=instructions_bytes,
        prospective_proposal_bytes=prospective_proposal_bytes,
        prospective_approval_record_bytes=prospective_approval_record_bytes,
    )
    _validated_output_adoption(
        output_adoption_record_bytes,
        source_workbook_bytes=source_workbook_bytes,
        adjudicated_workbook_bytes=adjudicated_workbook_bytes,
        instructions_bytes=instructions_bytes,
        prospective_approval_record_bytes=prospective_approval_record_bytes,
        corrective_proposal_bytes=corrective_proposal_bytes,
        corrective_approval_record_bytes=corrective_approval_record_bytes,
        provenance_bytes=provenance_bytes,
    )
    decision_counts = Counter(item["decision"] for item in decisions)
    mapped_assignments = sum(
        len(item["measure_ids"]) for item in decisions if item["decision"] == "mapped"
    )
    ambiguous_assignments = sum(
        len(item["measure_ids"])
        for item in decisions
        if item["decision"] == "ambiguous"
    )
    artifact: dict[str, Any] = {
        "adjudication": {
            "adjudicator": copy.deepcopy(provenance["adjudicator"]),
            "status": "agent_adjudicated",
        },
        "decisions": decisions,
        "kind": "public-evidence-measure-opportunity-map",
        "map_version": "r2-public-evidence-measure-opportunity-map-v1",
        "schema_version": 1,
        "source": {
            "accepted_catalog_path": _ACCEPTED_CATALOG_PATH,
            "accepted_catalog_sha256": _sha256(accepted_catalog_bytes),
            "adjudicated_workbook_path": _ADJUDICATED_WORKBOOK_PATH,
            "adjudicated_workbook_sha256": _sha256(adjudicated_workbook_bytes),
            "corrective_approval_record_path": _CORRECTIVE_APPROVAL_PATH,
            "corrective_approval_record_sha256": _sha256(
                corrective_approval_record_bytes
            ),
            "corrective_proposal_git_blob": corrective_approval["proposal_git_blob"],
            "corrective_proposal_path": _CORRECTIVE_PROPOSAL_PATH,
            "corrective_proposal_sha256": corrective_approval["proposal_sha256"],
            "dev_a_ids_path": _DEV_A_IDS_PATH,
            "dev_a_ids_sha256": _sha256(dev_a_ids_bytes),
            "instructions_path": _INSTRUCTIONS_PATH,
            "instructions_sha256": _sha256(instructions_bytes),
            "output_adoption_record_path": _OUTPUT_ADOPTION_PATH,
            "output_adoption_record_sha256": _sha256(output_adoption_record_bytes),
            "prospective_approval_record_path": _PROSPECTIVE_APPROVAL_PATH,
            "prospective_approval_record_sha256": _sha256(
                prospective_approval_record_bytes
            ),
            "prospective_proposal_git_blob": prospective_approval["proposal_git_blob"],
            "prospective_proposal_path": _PROSPECTIVE_PROPOSAL_PATH,
            "prospective_proposal_sha256": prospective_approval["proposal_sha256"],
            "provenance_path": _PROVENANCE_PATH,
            "provenance_sha256": _sha256(provenance_bytes),
            "public_manifest_path": _PUBLIC_MANIFEST_PATH,
            "public_manifest_sha256": _sha256(public_manifest_bytes),
            "source_workbook_path": _SOURCE_WORKBOOK_PATH,
            "source_workbook_sha256": _sha256(source_workbook_bytes),
        },
        "summary": {
            "active_review_seconds": None,
            "ambiguous_candidate_assignments": ambiguous_assignments,
            "ambiguous_question_count": decision_counts["ambiguous"],
            "eligible_question_count": len(decisions),
            "mapped_measure_assignments": mapped_assignments,
            "mapped_question_count": decision_counts["mapped"],
            "none_question_count": decision_counts["none"],
            "opportunity_question_count": decision_counts["mapped"],
        },
    }
    artifact["manifest"] = {
        "ordered_instance_ids": [item["instance_id"] for item in decisions]
    }
    artifact["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    _reject_final_content(artifact)
    return artifact


def validate_agent_adjudicated_measure_opportunity_map(
    content: bytes,
    accepted_catalog_bytes: bytes,
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    instructions_bytes: bytes,
    prospective_proposal_bytes: bytes,
    prospective_approval_record_bytes: bytes,
    corrective_proposal_bytes: bytes,
    corrective_approval_record_bytes: bytes,
    provenance_bytes: bytes,
    output_adoption_record_bytes: bytes,
    *,
    expected_dev_a_count: int = EXPECTED_DEV_A_COUNT,
    expected_frame_count: int = EXPECTED_FRAME_COUNT,
) -> dict[str, Any]:
    """Regenerate an adopted agent map from its complete authenticated chain."""
    expected = materialize_agent_adjudicated_measure_opportunity_map(
        accepted_catalog_bytes,
        public_manifest_bytes,
        dev_a_ids_bytes,
        source_workbook_bytes,
        adjudicated_workbook_bytes,
        instructions_bytes,
        prospective_proposal_bytes,
        prospective_approval_record_bytes,
        corrective_proposal_bytes,
        corrective_approval_record_bytes,
        provenance_bytes,
        output_adoption_record_bytes,
        expected_dev_a_count=expected_dev_a_count,
        expected_frame_count=expected_frame_count,
    )
    if canonical_catalog_bytes(expected) != content:
        raise MeasureOpportunityMapError(
            "opportunity map does not reproduce from the adopted agent review"
        )
    return expected


def _validated_opportunity_approval(
    proposal_bytes: bytes,
    approval_record_bytes: bytes,
    *,
    expected_kind: str,
    label: str,
    expected_bindings: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _required_bytes(proposal_bytes, f"{label} proposal")
    record = _json_object(approval_record_bytes, f"{label} record")
    bindings = dict(expected_bindings or {})
    expected_keys = {
        "approved_at",
        "approved_by",
        "decision",
        "kind",
        "proposal_git_blob",
        "proposal_sha256",
        "schema_version",
        *bindings,
    }
    if canonical_catalog_bytes(record) != approval_record_bytes:
        raise MeasureOpportunityMapError(f"{label} record is not canonical")
    if (
        set(record) != expected_keys
        or record.get("decision") != "approved"
        or record.get("kind") != expected_kind
        or record.get("schema_version") != 1
    ):
        raise MeasureOpportunityMapError(f"exact {label} record is required")
    _text(record.get("approved_by"), f"{label} approved_by")
    _utc_second(record.get("approved_at"), f"{label} approved_at")
    if record.get("proposal_sha256") != _sha256(proposal_bytes):
        raise MeasureOpportunityMapError(f"{label} proposal hash is invalid")
    if record.get("proposal_git_blob") != _git_blob_hash(proposal_bytes):
        raise MeasureOpportunityMapError(f"{label} proposal Git blob is invalid")
    for field, expected in bindings.items():
        if record.get(field) != expected:
            raise MeasureOpportunityMapError(f"{label} {field} binding is invalid")
    return record


def _validated_output_adoption(
    content: bytes,
    *,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    instructions_bytes: bytes,
    prospective_approval_record_bytes: bytes,
    corrective_proposal_bytes: bytes,
    corrective_approval_record_bytes: bytes,
    provenance_bytes: bytes,
) -> dict[str, Any]:
    record = _json_object(content, "output adoption record")
    if canonical_catalog_bytes(record) != content:
        raise MeasureOpportunityMapError("output adoption record is not canonical")
    expected_keys = {
        "adjudicated_workbook_sha256",
        "adopted_at",
        "adopted_by",
        "blank_workbook_sha256",
        "corrective_amendment_approval_sha256",
        "corrective_proposal_sha256",
        "decision",
        "instruction_contract_sha256",
        "kind",
        "prospective_amendment_approval_sha256",
        "provenance_sha256",
        "schema_version",
    }
    if (
        set(record) != expected_keys
        or record.get("kind")
        != "r2-public-evidence-measures-opportunity-adjudication-output-adoption"
        or record.get("decision") != "adopted"
        or record.get("schema_version") != 1
    ):
        raise MeasureOpportunityMapError("exact output adoption record is required")
    adopted_by = _text(record.get("adopted_by"), "output adoption adopted_by")
    adopted_at = _utc_second(record.get("adopted_at"), "output adoption adopted_at")
    expected = build_opportunity_output_adoption_record(
        source_workbook_bytes=source_workbook_bytes,
        adjudicated_workbook_bytes=adjudicated_workbook_bytes,
        instructions_bytes=instructions_bytes,
        prospective_approval_record_bytes=prospective_approval_record_bytes,
        corrective_proposal_bytes=corrective_proposal_bytes,
        corrective_approval_record_bytes=corrective_approval_record_bytes,
        provenance_bytes=provenance_bytes,
        adopted_by=adopted_by,
        adopted_at=adopted_at,
    )
    if record != expected:
        raise MeasureOpportunityMapError(
            "output adoption record does not bind the exact adjudication chain"
        )
    return record


def _validated_opportunity_provenance(
    content: bytes,
    *,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    instructions_bytes: bytes,
    prospective_proposal_bytes: bytes,
    prospective_approval_record_bytes: bytes,
) -> dict[str, Any]:
    record = _json_object(content, "opportunity provenance")
    if canonical_catalog_bytes(record) != content:
        raise MeasureOpportunityMapError("opportunity provenance is not canonical")
    if set(record) != {
        "adjudicator",
        "information_boundary",
        "kind",
        "limitations",
        "manifest",
        "schema_version",
        "source",
        "summary",
        "validation",
        "workflow",
    }:
        raise MeasureOpportunityMapError("opportunity provenance shape is invalid")
    if (
        record.get("kind") != "r2-measure-opportunity-agent-adjudication-provenance"
        or record.get("schema_version") != 1
    ):
        raise MeasureOpportunityMapError("opportunity provenance identity is invalid")
    if record.get("adjudicator") != _AGENT_ADJUDICATOR:
        raise MeasureOpportunityMapError(
            "opportunity provenance adjudicator is invalid"
        )
    if record.get("information_boundary") != _AGENT_INFORMATION_BOUNDARY:
        raise MeasureOpportunityMapError(
            "opportunity provenance information boundary is invalid"
        )
    if record.get("limitations") != _AGENT_LIMITATIONS:
        raise MeasureOpportunityMapError(
            "opportunity provenance limitations are invalid"
        )
    source = _mapping(record.get("source"), "opportunity provenance source")
    if set(source) != {
        "approved_prospective_amendment_sha256",
        "blank_workbook_sha256",
        "instruction_contract_path",
        "instruction_contract_sha256",
        "observed_output_path",
        "observed_output_sha256",
        "operator_approval_record_sha256",
        "provenance_basis",
    }:
        raise MeasureOpportunityMapError(
            "opportunity provenance source shape is invalid"
        )
    if source.get("approved_prospective_amendment_sha256") != _sha256(
        prospective_proposal_bytes
    ):
        raise MeasureOpportunityMapError(
            "opportunity provenance prospective amendment hash is invalid"
        )
    if source.get("operator_approval_record_sha256") != _sha256(
        prospective_approval_record_bytes
    ):
        raise MeasureOpportunityMapError(
            "opportunity provenance prospective approval hash is invalid"
        )
    if source.get("blank_workbook_sha256") != _sha256(source_workbook_bytes):
        raise MeasureOpportunityMapError(
            "opportunity provenance blank workbook hash is invalid"
        )
    if source.get("instruction_contract_path") != _INSTRUCTIONS_PATH or source.get(
        "instruction_contract_sha256"
    ) != _sha256(instructions_bytes):
        raise MeasureOpportunityMapError("instruction contract hash is invalid")
    if source.get("observed_output_path") != _ADJUDICATED_WORKBOOK_PATH or source.get(
        "observed_output_sha256"
    ) != _sha256(adjudicated_workbook_bytes):
        raise MeasureOpportunityMapError(
            "opportunity provenance observed output is invalid"
        )
    if source.get("provenance_basis") != (
        "operator-supplied verbatim agent summary in approval turn"
    ):
        raise MeasureOpportunityMapError("opportunity provenance basis is invalid")

    rows = _workbook_rows(adjudicated_workbook_bytes)
    counts = Counter(row["decision"].strip() for row in rows)
    selected_count = sum(
        len(_selected_measure_ids(row["measure_ids_json"])) for row in rows
    )
    ambiguous_ids = [
        row["instance_id"] for row in rows if row["decision"].strip() == "ambiguous"
    ]
    if record.get("summary") != {
        "ambiguous": counts["ambiguous"],
        "ambiguous_instance_ids": ambiguous_ids,
        "mapped": counts["mapped"],
        "none": counts["none"],
        "reviewed_rows": len(rows),
        "selected_measure_assignments": selected_count,
    }:
        raise MeasureOpportunityMapError("opportunity provenance summary is invalid")
    if record.get("validation") != {
        "active_review_seconds_all_blank": True,
        "decision_contract_valid": True,
        "immutable_cells_match_blank_workbook": True,
        "mechanical_status": "passed",
        "row_count": len(rows),
        "selected_ids_same_row_sorted_unique": True,
    }:
        raise MeasureOpportunityMapError("opportunity provenance validation is invalid")
    if record.get("workflow") != {
        "active_review_seconds": None,
        "cost_usd": None,
        "elapsed_wall_clock_seconds": None,
        "input_files": ["measure-opportunity-review-workbook-v1.csv"],
        "local_tools": _AGENT_LOCAL_TOOLS,
        "tokens": None,
    }:
        raise MeasureOpportunityMapError("opportunity provenance workflow is invalid")
    manifest = _mapping(record.get("manifest"), "opportunity provenance manifest")
    digest_source = copy.deepcopy(record)
    digest_source["manifest"].pop("artifact_sha256", None)
    if manifest != {"artifact_sha256": _sha256(canonical_catalog_bytes(digest_source))}:
        raise MeasureOpportunityMapError("opportunity provenance hash is invalid")
    return record


def _review_scope(
    accepted_catalog_bytes: bytes,
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    *,
    expected_dev_a_count: int,
    expected_frame_count: int,
) -> dict[str, Any]:
    if type(expected_dev_a_count) is not int or expected_dev_a_count <= 0:
        raise MeasureOpportunityMapError("expected dev-A count is invalid")
    if type(expected_frame_count) is not int or expected_frame_count <= 0:
        raise MeasureOpportunityMapError("expected eligible frame count is invalid")
    catalog = _accepted_catalog(accepted_catalog_bytes)
    try:
        records = _public_records(public_manifest_bytes, ContentPolicy(()))
        dev_a_ids = _ids(dev_a_ids_bytes, "dev-A")
    except DirectQuestionLoadError as error:
        raise MeasureOpportunityMapError(str(error)) from error
    if len(dev_a_ids) != expected_dev_a_count:
        raise MeasureOpportunityMapError("committed dev-A count is invalid")
    if not dev_a_ids.issubset(records):
        raise MeasureOpportunityMapError(
            "every committed dev-A ID must exist in the public manifest"
        )
    databases = set(catalog["generator"]["databases"])
    frame_ids = sorted(
        instance_id
        for instance_id in dev_a_ids
        if records[instance_id]["selected_database"] in databases
    )
    if len(frame_ids) != expected_frame_count:
        raise MeasureOpportunityMapError("eligible frame count is invalid")
    options_by_database = _measure_options(catalog)
    if set(options_by_database) != databases:
        raise MeasureOpportunityMapError(
            "every eligible database must have accepted measure options"
        )
    return {
        "frame_ids": frame_ids,
        "options_by_database": options_by_database,
        "records": records,
    }


def _accepted_catalog(content: bytes) -> dict[str, Any]:
    catalog = _json_object(content, "accepted measure catalog")
    try:
        reject_protected_fields(catalog)
    except ProtectedFieldError as error:
        raise MeasureOpportunityMapError(str(error)) from error
    if canonical_catalog_bytes(catalog) != content:
        raise MeasureOpportunityMapError("accepted measure catalog is not canonical")
    if set(catalog) != _ACCEPTED_CATALOG_KEYS:
        raise MeasureOpportunityMapError("accepted measure catalog shape is invalid")
    if (
        catalog.get("kind") != "public-evidence-measure-catalog"
        or catalog.get("catalog_version") != "public-evidence-measure-catalog-v1"
        or catalog.get("schema_version") != 1
    ):
        raise MeasureOpportunityMapError("accepted measure catalog identity is invalid")
    manifest = _mapping(catalog.get("manifest"), "accepted catalog manifest")
    stored_digest = manifest.get("artifact_sha256")
    digest_source = copy.deepcopy(catalog)
    digest_source["manifest"].pop("artifact_sha256", None)
    if stored_digest != _sha256(canonical_catalog_bytes(digest_source)):
        raise MeasureOpportunityMapError("accepted measure catalog hash is invalid")
    candidates = catalog.get("accepted_candidates")
    generator = _mapping(catalog.get("generator"), "accepted catalog generator")
    databases = generator.get("databases")
    if (
        not isinstance(candidates, list)
        or not isinstance(databases, list)
        or any(not isinstance(item, str) or not item for item in databases)
        or databases != sorted(databases)
        or len(databases) != len(set(databases))
        or generator.get("database_count") != len(databases)
    ):
        raise MeasureOpportunityMapError("accepted measure inventory is invalid")
    candidate_ids: list[str] = []
    measure_ids: list[str] = []
    candidate_databases: set[str] = set()
    for raw_candidate in candidates:
        candidate = _mapping(raw_candidate, "accepted measure candidate")
        if "review" in candidate:
            raise MeasureOpportunityMapError(
                "accepted measure candidate cannot retain review state"
            )
        candidate_ids.append(_text(candidate.get("candidate_id"), "candidate ID"))
        measure_ids.append(_text(candidate.get("measure_id"), "measure ID"))
        candidate_databases.add(_text(candidate.get("database"), "database"))
    if (
        candidate_ids != sorted(candidate_ids)
        or len(candidate_ids) != len(set(candidate_ids))
        or len(measure_ids) != len(set(measure_ids))
        or manifest.get("ordered_candidate_ids") != candidate_ids
        or manifest.get("ordered_measure_ids") != measure_ids
        or candidate_databases != set(databases)
    ):
        raise MeasureOpportunityMapError(
            "accepted measure catalog membership is invalid"
        )
    summary = _mapping(catalog.get("summary"), "accepted catalog summary")
    if (
        summary.get("accepted_candidate_count") != len(candidates)
        or summary.get("accepted_database_count") != len(databases)
        or summary.get("accepted_databases") != databases
    ):
        raise MeasureOpportunityMapError("accepted measure catalog summary is invalid")
    return catalog


def _measure_options(catalog: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    options: dict[str, list[dict[str, str]]] = {}
    for raw_candidate in catalog["accepted_candidates"]:
        candidate = _mapping(raw_candidate, "accepted measure candidate")
        database = _text(candidate.get("database"), "database")
        measure = _mapping(candidate.get("measure"), "measure")
        definition = _mapping(measure.get("definition"), "measure definition")
        evidence = _mapping(candidate.get("evidence"), "measure evidence")
        view = _mapping(candidate.get("view"), "measure view")
        options.setdefault(database, []).append(
            {
                "description": _text(
                    definition.get("description"), "measure description"
                ),
                "identity_field_stable_id": _text(
                    evidence.get("identity_field_stable_id"),
                    "identity field stable ID",
                ),
                "label": _text(definition.get("label"), "measure label"),
                "measure_id": _text(candidate.get("measure_id"), "measure ID"),
                "measure_name": _text(measure.get("name"), "measure name"),
                "view_name": _text(view.get("view_name"), "view name"),
            }
        )
    for database_options in options.values():
        database_options.sort(key=lambda item: item["measure_id"])
    return dict(sorted(options.items()))


def _review_row(
    instance_id: str,
    record: Mapping[str, Any],
    options_by_database: Mapping[str, list[dict[str, str]]],
    *,
    accepted_catalog_sha256: str,
    public_manifest_sha256: str,
) -> dict[str, str]:
    database = record["selected_database"]
    question = record["query"]
    return {
        "accepted_catalog_sha256": accepted_catalog_sha256,
        "public_manifest_sha256": public_manifest_sha256,
        "public_record_sha256": _sha256(canonical_catalog_bytes(record)),
        "question_sha256": _sha256(question.encode()),
        "instance_id": instance_id,
        "database": database,
        "question": question,
        "eligible_measure_options_json": _canonical_cell(options_by_database[database]),
        "decision": "",
        "measure_ids_json": "[]",
        "active_review_seconds": "",
    }


def _workbook_rows(content: bytes) -> list[dict[str, str]]:
    if not content or len(content) > _MAX_WORKBOOK_BYTES or b"\x00" in content:
        raise MeasureOpportunityMapError("opportunity review workbook size is invalid")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as error:
        raise MeasureOpportunityMapError(
            "opportunity review workbook must be UTF-8"
        ) from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != OPPORTUNITY_REVIEW_COLUMNS:
        raise MeasureOpportunityMapError(
            "opportunity review workbook columns are invalid"
        )
    rows = list(reader)
    if any(set(row) != set(OPPORTUNITY_REVIEW_COLUMNS) for row in rows):
        raise MeasureOpportunityMapError(
            "opportunity review workbook contains extra columns"
        )
    return rows


def _validated_decisions(
    expected_rows: list[dict[str, str]],
    observed_rows: list[dict[str, str]],
    *,
    global_measure_ids: set[str],
) -> list[dict[str, Any]]:
    expected_ids = [row["instance_id"] for row in expected_rows]
    observed_ids = [row["instance_id"] for row in observed_rows]
    if observed_ids != expected_ids or len(observed_ids) != len(set(observed_ids)):
        raise MeasureOpportunityMapError(
            "opportunity review must contain every eligible ID exactly once and sorted"
        )
    decisions: list[dict[str, Any]] = []
    for expected, observed in zip(expected_rows, observed_rows, strict=True):
        for column in OPPORTUNITY_REVIEW_COLUMNS:
            if column not in _REVIEW_COLUMNS and observed[column] != expected[column]:
                raise MeasureOpportunityMapError(
                    f"immutable review column {column} changed"
                )
        decision = observed["decision"].strip()
        seconds_text = observed["active_review_seconds"].strip()
        if not decision or not seconds_text:
            raise MeasureOpportunityMapError(
                "every opportunity row must have complete review fields"
            )
        if decision not in _DECISIONS:
            raise MeasureOpportunityMapError("opportunity decision is invalid")
        measure_ids = _selected_measure_ids(observed["measure_ids_json"])
        unknown = set(measure_ids).difference(global_measure_ids)
        if unknown:
            raise MeasureOpportunityMapError(
                "opportunity review contains unknown measure"
            )
        allowed_ids = {item["measure_id"] for item in _measure_id_options(expected)}
        if not set(measure_ids).issubset(allowed_ids):
            raise MeasureOpportunityMapError(
                "mapped measures must belong to the question database"
            )
        if decision == "mapped" and not measure_ids:
            raise MeasureOpportunityMapError(
                "mapped decision must identify at least one measure"
            )
        if decision == "none" and measure_ids:
            raise MeasureOpportunityMapError("none decision cannot identify a measure")
        seconds = _review_seconds(seconds_text)
        decisions.append(
            {
                "active_review_seconds": seconds,
                "database": expected["database"],
                "decision": decision,
                "instance_id": expected["instance_id"],
                "measure_ids": measure_ids,
                "public_record_sha256": expected["public_record_sha256"],
                "question_sha256": expected["question_sha256"],
            }
        )
    return decisions


def _validated_agent_decisions(
    expected_rows: list[dict[str, str]],
    observed_rows: list[dict[str, str]],
    *,
    global_measure_ids: set[str],
) -> list[dict[str, Any]]:
    expected_ids = [row["instance_id"] for row in expected_rows]
    observed_ids = [row["instance_id"] for row in observed_rows]
    if observed_ids != expected_ids or len(observed_ids) != len(set(observed_ids)):
        raise MeasureOpportunityMapError(
            "agent opportunity review must contain every eligible ID exactly once "
            "and sorted"
        )
    decisions: list[dict[str, Any]] = []
    for expected, observed in zip(expected_rows, observed_rows, strict=True):
        for column in OPPORTUNITY_REVIEW_COLUMNS:
            if column not in _REVIEW_COLUMNS and observed[column] != expected[column]:
                raise MeasureOpportunityMapError(
                    f"immutable review column {column} changed"
                )
        decision = observed["decision"].strip()
        if decision not in _DECISIONS:
            raise MeasureOpportunityMapError("opportunity decision is invalid")
        if observed["active_review_seconds"].strip():
            raise MeasureOpportunityMapError(
                "active review seconds must remain blank for agent adjudication"
            )
        measure_ids = _selected_measure_ids(observed["measure_ids_json"])
        if set(measure_ids).difference(global_measure_ids):
            raise MeasureOpportunityMapError(
                "opportunity review contains unknown measure"
            )
        allowed_ids = {item["measure_id"] for item in _measure_id_options(expected)}
        if not set(measure_ids).issubset(allowed_ids):
            raise MeasureOpportunityMapError(
                "mapped measures must belong to the question database"
            )
        if decision == "mapped" and not measure_ids:
            raise MeasureOpportunityMapError(
                "mapped decision must identify at least one measure"
            )
        if decision == "none" and measure_ids:
            raise MeasureOpportunityMapError("none decision cannot identify a measure")
        decisions.append(
            {
                "active_review_seconds": None,
                "database": expected["database"],
                "decision": decision,
                "instance_id": expected["instance_id"],
                "measure_ids": measure_ids,
                "public_record_sha256": expected["public_record_sha256"],
                "question_sha256": expected["question_sha256"],
            }
        )
    return decisions


def _measure_id_options(row: Mapping[str, str]) -> list[dict[str, str]]:
    try:
        value = json.loads(row["eligible_measure_options_json"])
    except json.JSONDecodeError as error:
        raise MeasureOpportunityMapError(
            "eligible measure options are invalid"
        ) from error
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("measure_id"), str)
        for item in value
    ):
        raise MeasureOpportunityMapError("eligible measure options are invalid")
    return value


def _selected_measure_ids(content: str) -> list[str]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        raise MeasureOpportunityMapError("measure IDs must be valid JSON") from error
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise MeasureOpportunityMapError("measure IDs must be an array of strings")
    if value != sorted(value) or len(value) != len(set(value)):
        raise MeasureOpportunityMapError("measure IDs must be unique and sorted")
    return value


def _review_seconds(content: str) -> float:
    try:
        value = Decimal(content)
    except InvalidOperation as error:
        raise MeasureOpportunityMapError("active review seconds is invalid") from error
    if not value.is_finite() or value < 0:
        raise MeasureOpportunityMapError(
            "active review seconds must be finite and nonnegative"
        )
    seconds = float(value)
    if not math.isfinite(seconds):
        raise MeasureOpportunityMapError(
            "active review seconds must be finite and nonnegative"
        )
    return seconds


def _reject_final_content(value: object) -> None:
    try:
        reject_protected_fields(value)
    except ProtectedFieldError as error:
        raise MeasureOpportunityMapError(str(error)) from error
    found = _find_final_forbidden_key(value)
    if found is not None:
        raise MeasureOpportunityMapError(
            f"question text field {found} is forbidden in the final map"
        )


def _find_final_forbidden_key(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).casefold() in _FINAL_FORBIDDEN_KEYS:
                return str(key)
            found = _find_final_forbidden_key(nested)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            found = _find_final_forbidden_key(nested)
            if found is not None:
                return found
    return None


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    if (
        not isinstance(content, bytes)
        or not content
        or len(content) > _MAX_WORKBOOK_BYTES
    ):
        raise MeasureOpportunityMapError(f"{label} size is invalid")
    try:
        value = json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda constant: _reject_nonfinite(constant),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MeasureOpportunityMapError(f"{label} must be valid JSON") from error
    if not isinstance(value, dict):
        raise MeasureOpportunityMapError(f"{label} must be an object")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MeasureOpportunityMapError(f"duplicate JSON field {key}")
        result[key] = value
    return result


def _reject_nonfinite(constant: str) -> None:
    raise MeasureOpportunityMapError("JSON must contain finite values")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise MeasureOpportunityMapError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MeasureOpportunityMapError(f"{label} must be non-empty text")
    return value


def _required_bytes(value: object, label: str) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > _MAX_WORKBOOK_BYTES:
        raise MeasureOpportunityMapError(f"{label} is invalid")
    return value


def _utc_second(value: object, label: str) -> str:
    text = _text(value, label)
    if not _TIMESTAMP.fullmatch(text):
        raise MeasureOpportunityMapError(f"{label} must be a UTC second timestamp")
    return text


def _canonical_cell(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git_blob_hash(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324

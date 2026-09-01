"""Blinded human-review workbook and decision validation for R2 measures."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import secrets
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .hkb_io import HKBFileSafetyError, prepare_safe_parent
from .measure_review_catalog import canonical_catalog_bytes
from .protected_fields import ProtectedFieldError, reject_protected_fields


class MeasureReviewError(ValueError):
    """Raised when a blinded measure review artifact is invalid."""


ACCEPT_REASON_CODES = frozenset(
    {
        "mechanical_binding_corrected",
        "public_identity_and_binding_confirmed",
    }
)
REJECT_REASON_CODES = frozenset(
    {
        "binding_mismatch",
        "duplicate_measure_name_conflict",
        "identity_not_semantically_unique",
        "not_an_entity",
        "public_evidence_insufficient",
    }
)
DEFER_REASON_CODES = frozenset(
    {
        "needs_domain_authority",
        "needs_grain_authority",
        "reviewer_uncertain",
    }
)
REASON_CODES_BY_DECISION = {
    "accept": ACCEPT_REASON_CODES,
    "defer": DEFER_REASON_CODES,
    "reject": REJECT_REASON_CODES,
}

REVIEW_COLUMNS = (
    "source_catalog_file_sha256",
    "source_catalog_sha256",
    "candidate_payload_sha256",
    "candidate_id",
    "measure_id",
    "database",
    "candidate_class",
    "view_name",
    "view_file_name",
    "measure_name",
    "aggregate_type",
    "sql",
    "inline_equivalent_signature_json",
    "public_evidence_json",
    "proposed_omni_yaml",
    "decision",
    "reason_code",
    "active_review_seconds",
    "binding_correction",
)

_REVIEW_COLUMNS = frozenset(REVIEW_COLUMNS[-4:])
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_FRACTIONAL_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
_CHATGPT_SHARE_URL = re.compile(
    r"^https://chatgpt\.com/share/[0-9a-f]{8}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_FIELD_REFERENCE = re.compile(
    r"^\$\{(?P<view>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<field>[A-Za-z_][A-Za-z0-9_]*)\}$"
)
_FORBIDDEN_REVIEW_KEYS = frozenset(
    {
        "correctness",
        "instance_id",
        "outcome",
        "question",
        "question_id",
        "question_path",
    }
)
_BLANK_REVIEW = {
    "active_review_seconds": None,
    "binding_correction": None,
    "decision": None,
    "reason_code": None,
    "status": "pending",
}
_CORRECTION_KEYS = frozenset(
    {"corrected_sql", "justification", "source_field_stable_id"}
)


def build_measure_review_workbook(catalog_bytes: bytes) -> bytes:
    """Create a deterministic CSV with immutable evidence and blank review cells."""
    catalog = _validated_catalog(catalog_bytes)
    source_file_hash = _sha256(catalog_bytes)
    source_catalog_hash = catalog["manifest"]["catalog_sha256"]
    rows = [
        _candidate_row(candidate, source_file_hash, source_catalog_hash)
        for candidate in catalog["candidates"]
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(REVIEW_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    content = output.getvalue().encode()
    _reject_forbidden_value(content.decode())
    return content


def build_protocol_approval_record(
    proposal_bytes: bytes,
    *,
    approved_by: str,
    approved_at: str,
) -> dict[str, Any]:
    """Bind an explicit human approval record to one exact proposal blob."""
    approver = _nonempty_text(approved_by, "approved_by")
    timestamp = _nonempty_text(approved_at, "approved_at")
    if not _TIMESTAMP.fullmatch(timestamp):
        raise MeasureReviewError("approved_at must be a UTC second timestamp")
    if not proposal_bytes:
        raise MeasureReviewError("proposal must not be empty")
    return {
        "approved_at": timestamp,
        "approved_by": approver,
        "decision": "approved",
        "kind": "r2-public-evidence-measures-protocol-approval",
        "proposal_git_blob": _git_blob_hash(proposal_bytes),
        "proposal_sha256": _sha256(proposal_bytes),
        "schema_version": 1,
    }


def build_protocol_amendment_approval_record(
    proposal_bytes: bytes,
    *,
    provenance_bytes: bytes,
    approved_by: str,
    approved_at: str,
) -> dict[str, Any]:
    """Bind approval to the exact amendment and adopted provenance artifact."""
    if not isinstance(provenance_bytes, bytes) or not provenance_bytes:
        raise MeasureReviewError("agent adjudication provenance must not be empty")
    record = build_protocol_approval_record(
        proposal_bytes,
        approved_by=approved_by,
        approved_at=approved_at,
    )
    record["kind"] = "r2-public-evidence-measures-agent-adjudication-amendment-approval"
    record["provenance_sha256"] = _sha256(provenance_bytes)
    return record


def build_agent_adjudication_provenance(
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    *,
    transcript_extract_bytes: bytes,
    transcript_extract_path: str,
    source_url: str,
    retrieved_at: str,
    started_at: str,
    completed_at: str,
    product: str,
    model: str,
    reasoning_effort: str,
    user_instruction_messages: int,
    assistant_text_messages: int,
    tool_call_messages: int,
    correction_rounds: int,
) -> dict[str, Any]:
    """Normalize the bounded provenance of one observed agent adjudication."""
    if (
        not isinstance(transcript_extract_bytes, bytes)
        or not transcript_extract_bytes
        or len(transcript_extract_bytes) > 256_000
        or b"\x00" in transcript_extract_bytes
    ):
        raise MeasureReviewError("agent transcript extract is invalid")
    extract_path = _nonempty_text(
        transcript_extract_path, "agent transcript extract path"
    )
    extract_parts = Path(extract_path).parts
    if (
        Path(extract_path).is_absolute()
        or ".." in extract_parts
        or not extract_parts
        or any(part in {"", "."} for part in extract_parts)
    ):
        raise MeasureReviewError("agent transcript extract path is invalid")
    if not _CHATGPT_SHARE_URL.fullmatch(
        _nonempty_text(source_url, "agent adjudication source URL")
    ):
        raise MeasureReviewError("agent adjudication source URL is invalid")
    _timestamp(retrieved_at, "retrieved_at", fractional=False)
    started = _timestamp(started_at, "started_at", fractional=True)
    completed = _timestamp(completed_at, "completed_at", fractional=True)
    if completed <= started:
        raise MeasureReviewError("agent adjudication timestamps are out of order")
    metrics = {
        "assistant_text_messages": assistant_text_messages,
        "correction_rounds": correction_rounds,
        "tool_call_messages": tool_call_messages,
        "user_instruction_messages": user_instruction_messages,
    }
    for name, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MeasureReviewError(f"{name} must be a nonnegative integer")

    source_rows = _review_rows(source_workbook_bytes)
    adjudicated_rows = _review_rows(adjudicated_workbook_bytes)
    if len(source_rows) != len(adjudicated_rows):
        raise MeasureReviewError("agent adjudication workbook row count changed")
    source_by_id = _unique_rows(source_rows, "source adjudication workbook")
    adjudicated_by_id = _unique_rows(adjudicated_rows, "agent adjudication workbook")
    if set(source_by_id) != set(adjudicated_by_id):
        raise MeasureReviewError("agent adjudication workbook membership changed")
    for candidate_id in sorted(source_by_id):
        source_row = source_by_id[candidate_id]
        adjudicated_row = adjudicated_by_id[candidate_id]
        if any(source_row[column].strip() for column in _REVIEW_COLUMNS):
            raise MeasureReviewError("source adjudication workbook is not blank")
        _validate_immutable_cells(source_row, adjudicated_row)
        _agent_packet_decision(adjudicated_row)

    counts = Counter(row["decision"].strip() for row in adjudicated_rows)
    artifact: dict[str, Any] = {
        "adjudication_rule": _agent_adjudication_rule(),
        "adjudicator": {
            "model": _nonempty_text(model, "agent adjudication model"),
            "product": _nonempty_text(product, "agent adjudication product"),
            "reasoning_effort": _nonempty_text(
                reasoning_effort, "agent adjudication reasoning effort"
            ),
        },
        "information_boundary": _agent_information_boundary(),
        "kind": "public-evidence-measure-agent-adjudication-provenance",
        "limitations": [
            "observational_workflow_not_preregistered",
            "packet_evidence_only_not_independent_source_revalidation",
            "proposed_yaml_was_deterministically_generated_not_agent_authored",
            "raw_shared_page_bytes_are_dynamic",
        ],
        "schema_version": 1,
        "source": {
            "adjudicated_workbook_sha256": _sha256(adjudicated_workbook_bytes),
            "retrieved_at": retrieved_at,
            "share_url": source_url,
            "source_workbook_sha256": _sha256(source_workbook_bytes),
            "transcript_extract_path": extract_path,
            "transcript_extract_sha256": _sha256(transcript_extract_bytes),
        },
        "summary": {
            "accept": counts["accept"],
            "adjudicated_candidates": len(adjudicated_rows),
            "binding_corrections": sum(
                bool(row["binding_correction"].strip()) for row in adjudicated_rows
            ),
            "defer": counts["defer"],
            "reject": counts["reject"],
        },
        "workflow": {
            "assistant_text_messages": assistant_text_messages,
            "completed_at": completed_at,
            "correction_rounds": correction_rounds,
            "cost_usd": None,
            "elapsed_wall_clock_seconds": (completed - started).total_seconds(),
            "human_active_seconds": None,
            "started_at": started_at,
            "tokens": None,
            "tool_call_messages": tool_call_messages,
            "user_instruction_messages": user_instruction_messages,
        },
    }
    artifact["manifest"] = {
        "artifact_sha256": _sha256(canonical_catalog_bytes(artifact))
    }
    return artifact


def materialize_measure_review_decisions(
    catalog_bytes: bytes,
    workbook_bytes: bytes,
    proposal_bytes: bytes,
    approval_record_bytes: bytes,
) -> dict[str, Any]:
    """Validate a complete review and return a separate immutable decision record."""
    approval = _validated_approval(proposal_bytes, approval_record_bytes)
    catalog = _validated_catalog(catalog_bytes)
    expected_rows = {
        candidate["candidate_id"]: _candidate_row(
            candidate,
            _sha256(catalog_bytes),
            catalog["manifest"]["catalog_sha256"],
        )
        for candidate in catalog["candidates"]
    }
    observed_rows = _review_rows(workbook_bytes)
    observed_by_id: dict[str, dict[str, str]] = {}
    for row in observed_rows:
        candidate_id = row["candidate_id"]
        if candidate_id in observed_by_id:
            raise MeasureReviewError(f"duplicate candidate row {candidate_id}")
        observed_by_id[candidate_id] = row
    missing = sorted(set(expected_rows) - set(observed_by_id))
    extra = sorted(set(observed_by_id) - set(expected_rows))
    if missing:
        raise MeasureReviewError("missing candidate rows from complete review")
    if extra:
        raise MeasureReviewError("review contains unknown candidate rows")

    candidate_index = {item["candidate_id"]: item for item in catalog["candidates"]}
    decisions: list[dict[str, Any]] = []
    for candidate_id in sorted(expected_rows):
        expected = expected_rows[candidate_id]
        observed = observed_by_id[candidate_id]
        for column in REVIEW_COLUMNS:
            if column in _REVIEW_COLUMNS:
                continue
            if observed[column] != expected[column]:
                raise MeasureReviewError(
                    f"immutable candidate column {column} was edited"
                )
        decisions.append(_decision_record(candidate_index[candidate_id], observed))

    counts = Counter(item["decision"] for item in decisions)
    total_seconds = math.fsum(item["active_review_seconds"] for item in decisions)
    artifact: dict[str, Any] = {
        "decisions": decisions,
        "kind": "public-evidence-measure-review-decisions",
        "reason_code_policy": {
            decision: sorted(reasons)
            for decision, reasons in sorted(REASON_CODES_BY_DECISION.items())
        },
        "schema_version": 1,
        "source": {
            "approval_record_sha256": _sha256(approval_record_bytes),
            "catalog_file_sha256": _sha256(catalog_bytes),
            "catalog_sha256": catalog["manifest"]["catalog_sha256"],
            "proposal_git_blob": approval["proposal_git_blob"],
            "proposal_sha256": approval["proposal_sha256"],
            "workbook_file_sha256": _sha256(workbook_bytes),
        },
        "summary": {
            "accept": counts["accept"],
            "active_review_seconds": total_seconds,
            "binding_corrections": sum(
                item["binding_correction"] is not None for item in decisions
            ),
            "defer": counts["defer"],
            "reject": counts["reject"],
            "reviewed_candidates": len(decisions),
        },
    }
    artifact["manifest"] = {
        "artifact_sha256": _sha256(canonical_catalog_bytes(artifact)),
        "ordered_candidate_ids": [item["candidate_id"] for item in decisions],
    }
    return artifact


def materialize_measure_agent_adjudication(
    catalog_bytes: bytes,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    provenance_bytes: bytes,
    transcript_extract_bytes: bytes,
    base_proposal_bytes: bytes,
    base_approval_record_bytes: bytes,
    amendment_proposal_bytes: bytes,
    amendment_approval_record_bytes: bytes,
) -> dict[str, Any]:
    """Validate the adopted agent packet adjudication under both approvals."""
    base_approval = _validated_approval(
        base_proposal_bytes,
        base_approval_record_bytes,
    )
    amendment_approval = _validated_approval(
        amendment_proposal_bytes,
        amendment_approval_record_bytes,
        expected_kind=(
            "r2-public-evidence-measures-agent-adjudication-amendment-approval"
        ),
        label="amendment",
        expected_bindings={"provenance_sha256": _sha256(provenance_bytes)},
    )
    provenance = _validated_agent_provenance(
        provenance_bytes,
        source_workbook_bytes,
        adjudicated_workbook_bytes,
        transcript_extract_bytes,
    )
    catalog = _validated_catalog(catalog_bytes)
    expected_rows = {
        candidate["candidate_id"]: _candidate_row(
            candidate,
            _sha256(catalog_bytes),
            catalog["manifest"]["catalog_sha256"],
        )
        for candidate in catalog["candidates"]
    }
    source_by_id = _unique_rows(
        _review_rows(source_workbook_bytes),
        "source adjudication workbook",
    )
    adjudicated_by_id = _unique_rows(
        _review_rows(adjudicated_workbook_bytes),
        "agent adjudication workbook",
    )
    for rows in (source_by_id, adjudicated_by_id):
        missing = sorted(set(expected_rows) - set(rows))
        extra = sorted(set(rows) - set(expected_rows))
        if missing:
            raise MeasureReviewError(
                "missing candidate rows from complete adjudication"
            )
        if extra:
            raise MeasureReviewError("adjudication contains unknown candidate rows")

    candidate_index = {item["candidate_id"]: item for item in catalog["candidates"]}
    decisions: list[dict[str, Any]] = []
    for candidate_id in sorted(expected_rows):
        expected = expected_rows[candidate_id]
        source = source_by_id[candidate_id]
        observed = adjudicated_by_id[candidate_id]
        for column in REVIEW_COLUMNS:
            if column in _REVIEW_COLUMNS:
                if source[column].strip():
                    raise MeasureReviewError(
                        "source adjudication workbook review cells are not blank"
                    )
                continue
            if (
                source[column] != expected[column]
                or observed[column] != expected[column]
            ):
                raise MeasureReviewError(
                    f"immutable candidate column {column} was edited"
                )
        decision, reason = _agent_packet_decision(observed)
        decisions.append(
            {
                "active_review_seconds": None,
                "binding_correction": None,
                "candidate_id": candidate_id,
                "correction_status": "not_applicable",
                "decision": decision,
                "measure_id": candidate_index[candidate_id]["measure_id"],
                "reason_code": reason,
                "status": "agent_adjudicated",
            }
        )

    counts = Counter(item["decision"] for item in decisions)
    artifact: dict[str, Any] = {
        "adjudication_rule": copy.deepcopy(provenance["adjudication_rule"]),
        "adjudicator": copy.deepcopy(provenance["adjudicator"]),
        "decisions": decisions,
        "information_boundary": copy.deepcopy(provenance["information_boundary"]),
        "kind": "public-evidence-measure-agent-adjudication-decisions",
        "reason_code_policy": {
            decision: sorted(reasons)
            for decision, reasons in sorted(REASON_CODES_BY_DECISION.items())
        },
        "schema_version": 1,
        "source": {
            "adjudicated_workbook_sha256": _sha256(adjudicated_workbook_bytes),
            "amendment_approval_record_sha256": _sha256(
                amendment_approval_record_bytes
            ),
            "amendment_proposal_git_blob": amendment_approval["proposal_git_blob"],
            "amendment_proposal_sha256": amendment_approval["proposal_sha256"],
            "base_approval_record_sha256": _sha256(base_approval_record_bytes),
            "base_proposal_git_blob": base_approval["proposal_git_blob"],
            "base_proposal_sha256": base_approval["proposal_sha256"],
            "catalog_file_sha256": _sha256(catalog_bytes),
            "catalog_sha256": catalog["manifest"]["catalog_sha256"],
            "provenance_sha256": _sha256(provenance_bytes),
            "source_workbook_sha256": _sha256(source_workbook_bytes),
            "transcript_extract_sha256": _sha256(transcript_extract_bytes),
        },
        "summary": {
            "accept": counts["accept"],
            "active_review_seconds": None,
            "adjudicated_candidates": len(decisions),
            "agent_elapsed_wall_clock_seconds": provenance["workflow"][
                "elapsed_wall_clock_seconds"
            ],
            "binding_corrections": 0,
            "defer": counts["defer"],
            "reject": counts["reject"],
        },
    }
    artifact["manifest"] = {
        "artifact_sha256": _sha256(canonical_catalog_bytes(artifact)),
        "ordered_candidate_ids": [item["candidate_id"] for item in decisions],
    }
    return artifact


def write_review_artifact(destination: Path, content: bytes) -> None:
    """Publish one review artifact append-only with owner-only permissions."""
    if not isinstance(content, bytes) or not content:
        raise MeasureReviewError("review artifact content must not be empty")
    try:
        prepare_safe_parent(destination)
        parent_descriptor = os.open(
            destination.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except (HKBFileSafetyError, OSError) as error:
        raise MeasureReviewError("review artifact parent is unsafe") from error

    temporary = f".{destination.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_descriptor,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary,
                destination.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            raise MeasureReviewError(
                f"{destination.name} already exists; refusing overwrite"
            ) from error
        os.fsync(parent_descriptor)
    except MeasureReviewError:
        raise
    except OSError as error:
        raise MeasureReviewError(
            "review artifact could not be written safely"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        finally:
            os.close(parent_descriptor)


def _validated_catalog(content: bytes) -> dict[str, Any]:
    catalog = _json_object(content, "measure candidate catalog")
    _reject_forbidden_value(catalog)
    if catalog.get("kind") != "public-evidence-measure-review-catalog":
        raise MeasureReviewError("measure candidate catalog kind is invalid")
    if catalog.get("schema_version") != 1:
        raise MeasureReviewError("measure candidate catalog schema is invalid")
    if canonical_catalog_bytes(catalog) != content:
        raise MeasureReviewError("measure candidate catalog is not canonical")
    manifest = catalog.get("manifest")
    candidates = catalog.get("candidates")
    if not isinstance(manifest, dict) or not isinstance(candidates, list):
        raise MeasureReviewError("measure candidate catalog shape is invalid")
    stored_digest = manifest.get("catalog_sha256")
    digest_source = copy.deepcopy(catalog)
    digest_source["manifest"].pop("catalog_sha256", None)
    if stored_digest != _sha256(canonical_catalog_bytes(digest_source)):
        raise MeasureReviewError("measure candidate catalog hash is invalid")
    if manifest.get("candidate_count") != len(candidates):
        raise MeasureReviewError("measure candidate count is invalid")
    identities: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise MeasureReviewError("measure candidate must be an object")
        candidate_id = _nonempty_text(candidate.get("candidate_id"), "candidate_id")
        identities.append(candidate_id)
        if candidate.get("review") != _BLANK_REVIEW:
            raise MeasureReviewError("source candidate review must remain blank")
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise MeasureReviewError("measure candidate IDs must be unique and sorted")
    if manifest.get("ordered_candidate_ids") != identities:
        raise MeasureReviewError("measure candidate manifest order is invalid")
    return catalog


def _candidate_row(
    candidate: Mapping[str, Any],
    source_file_hash: str,
    source_catalog_hash: str,
) -> dict[str, str]:
    view = _object(candidate.get("view"), "candidate view")
    measure = _object(candidate.get("measure"), "candidate measure")
    definition = _object(measure.get("definition"), "measure definition")
    evidence = _object(candidate.get("evidence"), "candidate evidence")
    signature = _object(
        candidate.get("inline_equivalent_signature"),
        "inline equivalent signature",
    )
    return {
        "active_review_seconds": "",
        "aggregate_type": _nonempty_text(
            definition.get("aggregate_type"), "aggregate_type"
        ),
        "binding_correction": "",
        "candidate_class": _nonempty_text(
            candidate.get("candidate_class"), "candidate_class"
        ),
        "candidate_id": _nonempty_text(candidate.get("candidate_id"), "candidate_id"),
        "candidate_payload_sha256": _sha256(canonical_catalog_bytes(candidate)),
        "database": _nonempty_text(candidate.get("database"), "database"),
        "decision": "",
        "inline_equivalent_signature_json": _canonical_cell(signature),
        "measure_id": _nonempty_text(candidate.get("measure_id"), "measure_id"),
        "measure_name": _nonempty_text(measure.get("name"), "measure name"),
        "proposed_omni_yaml": _nonempty_text(
            candidate.get("proposed_omni_yaml"), "proposed Omni YAML"
        ),
        "public_evidence_json": _canonical_cell(evidence),
        "reason_code": "",
        "source_catalog_file_sha256": source_file_hash,
        "source_catalog_sha256": source_catalog_hash,
        "sql": _nonempty_text(definition.get("sql"), "measure SQL"),
        "view_file_name": _nonempty_text(view.get("file_name"), "view file name"),
        "view_name": _nonempty_text(view.get("view_name"), "view name"),
    }


def _review_rows(content: bytes) -> list[dict[str, str]]:
    if not content or len(content) > 16_000_000 or b"\x00" in content:
        raise MeasureReviewError("review workbook size is invalid")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as error:
        raise MeasureReviewError("review workbook is not UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != list(REVIEW_COLUMNS):
        raise MeasureReviewError("review workbook header is invalid")
    rows: list[dict[str, str]] = []
    try:
        for raw in reader:
            if None in raw or any(value is None for value in raw.values()):
                raise MeasureReviewError("review workbook row shape is invalid")
            rows.append(dict(raw))
    except csv.Error as error:
        raise MeasureReviewError("review workbook CSV is invalid") from error
    return rows


def _unique_rows(
    rows: Sequence[Mapping[str, str]], label: str
) -> dict[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for row in rows:
        candidate_id = row["candidate_id"]
        if candidate_id in result:
            raise MeasureReviewError(f"duplicate candidate row in {label}")
        result[candidate_id] = row
    return result


def _validate_immutable_cells(
    source: Mapping[str, str], observed: Mapping[str, str]
) -> None:
    for column in REVIEW_COLUMNS:
        if column in _REVIEW_COLUMNS:
            continue
        if source[column] != observed[column]:
            raise MeasureReviewError(f"immutable candidate column {column} was edited")


def _agent_packet_decision(row: Mapping[str, str]) -> tuple[str, str]:
    if row["active_review_seconds"].strip():
        raise MeasureReviewError(
            "active_review_seconds must remain blank for agent adjudication"
        )
    if row["binding_correction"].strip():
        raise MeasureReviewError(
            "binding_correction must remain blank for the recovered adjudication rule"
        )
    decision = row["decision"].strip()
    reason = row["reason_code"].strip()
    evidence = _json_object(row["public_evidence_json"].encode(), "public evidence")
    reference = _FIELD_REFERENCE.fullmatch(row["sql"].strip())
    stable_id = evidence.get("identity_field_stable_id")
    binding_matches = (
        row["candidate_class"] == "entity_count"
        and reference is not None
        and evidence.get("identity_kind") == "primary_key"
        and isinstance(stable_id, str)
        and bool(stable_id)
        and reference.group("view") == row["view_name"]
        and _compact_identifier(reference.group("field"))
        == _compact_identifier(stable_id.rsplit(":", 1)[-1])
    )
    if not binding_matches or (
        decision,
        reason,
    ) != ("accept", "public_identity_and_binding_confirmed"):
        raise MeasureReviewError(
            "decision does not match the recovered adjudication rule"
        )
    return decision, reason


def _compact_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _agent_adjudication_rule() -> dict[str, object]:
    return {
        "accepted_decision": "accept",
        "accepted_reason_code": "public_identity_and_binding_confirmed",
        "field_comparison": "lowercase_ascii_alphanumeric_compaction",
        "required_candidate_class": "entity_count",
        "required_identity_kind": "primary_key",
        "requires_view_name_match": True,
        "unmatched_disposition": "needs_review_in_observed_trace",
        "version": "chatgpt_packet_pk_binding_v1",
    }


def _agent_information_boundary() -> dict[str, bool]:
    return {
        "benchmark_jsonl_accessed": False,
        "protected_or_gold_accessed": False,
        "public_dataset_landing_page_opened": True,
        "question_fields_accessed": False,
        "underlying_source_artifacts_loaded": False,
    }


def _decision_record(
    candidate: Mapping[str, Any], row: Mapping[str, str]
) -> dict[str, Any]:
    decision = row["decision"].strip()
    reason = row["reason_code"].strip()
    if not decision or not reason or not row["active_review_seconds"].strip():
        raise MeasureReviewError("complete review fields are required")
    if decision not in REASON_CODES_BY_DECISION:
        raise MeasureReviewError("review decision is invalid")
    if reason not in REASON_CODES_BY_DECISION[decision]:
        raise MeasureReviewError("reason_code is incompatible with decision")
    try:
        seconds_decimal = Decimal(row["active_review_seconds"].strip())
    except InvalidOperation as error:
        raise MeasureReviewError("active_review_seconds is invalid") from error
    if not seconds_decimal.is_finite() or seconds_decimal < 0:
        raise MeasureReviewError("active_review_seconds must be finite and nonnegative")
    seconds = float(seconds_decimal)
    if not math.isfinite(seconds):
        raise MeasureReviewError("active_review_seconds must be finite and nonnegative")

    raw_correction = row["binding_correction"].strip()
    if reason == "mechanical_binding_corrected":
        correction = _validated_correction(raw_correction, candidate)
        correction_status = "requires_public_evidence_validation"
    else:
        if raw_correction:
            raise MeasureReviewError(
                "binding correction requires mechanical_binding_corrected reason"
            )
        correction = None
        correction_status = "not_applicable"
    return {
        "active_review_seconds": seconds,
        "binding_correction": correction,
        "candidate_id": candidate["candidate_id"],
        "correction_status": correction_status,
        "decision": decision,
        "measure_id": candidate["measure_id"],
        "reason_code": reason,
        "status": "reviewed",
    }


def _validated_correction(content: str, candidate: Mapping[str, Any]) -> dict[str, str]:
    if not content:
        raise MeasureReviewError("binding correction is required")
    try:
        correction = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MeasureReviewError("binding correction must be valid JSON") from error
    if not isinstance(correction, dict) or set(correction) != _CORRECTION_KEYS:
        raise MeasureReviewError("binding correction fields are invalid")
    source_id = _nonempty_text(
        correction.get("source_field_stable_id"),
        "binding correction source_field_stable_id",
    )
    signature = _object(
        candidate.get("inline_equivalent_signature"),
        "inline equivalent signature",
    )
    source_ids = signature.get("source_field_stable_ids")
    if not isinstance(source_ids, list) or source_ids != [source_id]:
        raise MeasureReviewError("binding correction changes the source field")
    corrected_sql = _nonempty_text(
        correction.get("corrected_sql"), "binding correction corrected_sql"
    )
    reference = _FIELD_REFERENCE.fullmatch(corrected_sql)
    view = _object(candidate.get("view"), "candidate view")
    if reference is None or reference.group("view") != view.get("view_name"):
        raise MeasureReviewError("binding correction must remain in the same view")
    justification = _nonempty_text(
        correction.get("justification"), "binding correction justification"
    )
    if len(justification) > 500:
        raise MeasureReviewError("binding correction justification is too long")
    return {
        "corrected_sql": corrected_sql,
        "justification": justification,
        "source_field_stable_id": source_id,
    }


def _validated_approval(
    proposal_bytes: bytes,
    approval_record_bytes: bytes,
    *,
    expected_kind: str = "r2-public-evidence-measures-protocol-approval",
    label: str = "proposal",
    expected_bindings: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    record = _json_object(approval_record_bytes, "protocol approval record")
    expected_keys = {
        "approved_at",
        "approved_by",
        "decision",
        "kind",
        "proposal_git_blob",
        "proposal_sha256",
        "schema_version",
    }
    bindings = dict(expected_bindings or {})
    expected_keys.update(bindings)
    required_message = f"an exact approved {label} record is required"
    if set(record) != expected_keys or record.get("decision") != "approved":
        raise MeasureReviewError(required_message)
    if record.get("kind") != expected_kind or record.get("schema_version") != 1:
        raise MeasureReviewError(required_message)
    _nonempty_text(record.get("approved_by"), "approval approved_by")
    approved_at = _nonempty_text(record.get("approved_at"), "approval approved_at")
    if not _TIMESTAMP.fullmatch(approved_at):
        raise MeasureReviewError("approval timestamp is invalid")
    if record.get("proposal_sha256") != _sha256(proposal_bytes):
        raise MeasureReviewError(f"{label} hash does not match approval")
    if record.get("proposal_git_blob") != _git_blob_hash(proposal_bytes):
        raise MeasureReviewError(f"{label} Git blob does not match approval")
    for field, value in bindings.items():
        if record.get(field) != value:
            display = field.removesuffix("_sha256").replace("_", " ")
            raise MeasureReviewError(f"{display} hash does not match approval")
    return record


def _validated_agent_provenance(
    content: bytes,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    transcript_extract_bytes: bytes,
) -> dict[str, Any]:
    record = _json_object(content, "agent adjudication provenance")
    _reject_forbidden_value(record)
    if canonical_catalog_bytes(record) != content:
        raise MeasureReviewError("agent adjudication provenance is not canonical")
    if set(record) != {
        "adjudication_rule",
        "adjudicator",
        "information_boundary",
        "kind",
        "limitations",
        "manifest",
        "schema_version",
        "source",
        "summary",
        "workflow",
    }:
        raise MeasureReviewError("agent adjudication provenance shape is invalid")
    if (
        record.get("kind") != "public-evidence-measure-agent-adjudication-provenance"
        or record.get("schema_version") != 1
    ):
        raise MeasureReviewError("agent adjudication provenance identity is invalid")
    if record.get("adjudicator") != {
        "model": "GPT-5.6 sol",
        "product": "ChatGPT",
        "reasoning_effort": "High",
    }:
        raise MeasureReviewError("agent adjudicator identity is invalid")
    if record.get("information_boundary") != _agent_information_boundary():
        raise MeasureReviewError("agent adjudication information boundary is invalid")
    if record.get("adjudication_rule") != _agent_adjudication_rule():
        raise MeasureReviewError("agent adjudication rule is invalid")
    if record.get("limitations") != [
        "observational_workflow_not_preregistered",
        "packet_evidence_only_not_independent_source_revalidation",
        "proposed_yaml_was_deterministically_generated_not_agent_authored",
        "raw_shared_page_bytes_are_dynamic",
    ]:
        raise MeasureReviewError("agent adjudication limitations are invalid")
    source = _object(record.get("source"), "agent adjudication source")
    if set(source) != {
        "adjudicated_workbook_sha256",
        "retrieved_at",
        "share_url",
        "source_workbook_sha256",
        "transcript_extract_path",
        "transcript_extract_sha256",
    }:
        raise MeasureReviewError("agent adjudication source shape is invalid")
    if source.get("source_workbook_sha256") != _sha256(source_workbook_bytes):
        raise MeasureReviewError("agent adjudication source workbook hash is invalid")
    if source.get("adjudicated_workbook_sha256") != _sha256(adjudicated_workbook_bytes):
        raise MeasureReviewError("agent adjudication output workbook hash is invalid")
    if source.get("transcript_extract_sha256") != _sha256(transcript_extract_bytes):
        raise MeasureReviewError("agent transcript extract hash is invalid")
    extract_path = _nonempty_text(
        source.get("transcript_extract_path"), "agent transcript extract path"
    )
    if Path(extract_path).is_absolute() or ".." in Path(extract_path).parts:
        raise MeasureReviewError("agent transcript extract path is invalid")
    share_url = _nonempty_text(source.get("share_url"), "agent share URL")
    if not _CHATGPT_SHARE_URL.fullmatch(share_url):
        raise MeasureReviewError("agent share URL is invalid")
    _timestamp(
        _nonempty_text(source.get("retrieved_at"), "agent retrieved_at"),
        "retrieved_at",
        fractional=False,
    )
    rows = _review_rows(adjudicated_workbook_bytes)
    counts = Counter(row["decision"].strip() for row in rows)
    if record.get("summary") != {
        "accept": counts["accept"],
        "adjudicated_candidates": len(rows),
        "binding_corrections": sum(
            bool(row["binding_correction"].strip()) for row in rows
        ),
        "defer": counts["defer"],
        "reject": counts["reject"],
    }:
        raise MeasureReviewError("agent adjudication summary is invalid")
    workflow = _object(record.get("workflow"), "agent adjudication workflow")
    if set(workflow) != {
        "assistant_text_messages",
        "completed_at",
        "correction_rounds",
        "cost_usd",
        "elapsed_wall_clock_seconds",
        "human_active_seconds",
        "started_at",
        "tokens",
        "tool_call_messages",
        "user_instruction_messages",
    }:
        raise MeasureReviewError("agent adjudication workflow shape is invalid")
    started = _timestamp(
        _nonempty_text(workflow.get("started_at"), "agent started_at"),
        "started_at",
        fractional=True,
    )
    completed = _timestamp(
        _nonempty_text(workflow.get("completed_at"), "agent completed_at"),
        "completed_at",
        fractional=True,
    )
    elapsed = workflow.get("elapsed_wall_clock_seconds")
    if (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, (int, float))
        or not math.isfinite(elapsed)
        or elapsed != (completed - started).total_seconds()
    ):
        raise MeasureReviewError("agent elapsed wall-clock time is invalid")
    for field in (
        "assistant_text_messages",
        "correction_rounds",
        "tool_call_messages",
        "user_instruction_messages",
    ):
        value = workflow.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise MeasureReviewError(f"agent {field} is invalid")
    for field in ("cost_usd", "human_active_seconds", "tokens"):
        if workflow.get(field, object()) is not None:
            raise MeasureReviewError(f"agent {field} must be unavailable")
    manifest = _object(record.get("manifest"), "agent provenance manifest")
    digest_source = copy.deepcopy(record)
    digest_source.pop("manifest", None)
    if manifest != {"artifact_sha256": _sha256(canonical_catalog_bytes(digest_source))}:
        raise MeasureReviewError("agent adjudication provenance hash is invalid")
    return record


def _timestamp(value: str, label: str, *, fractional: bool) -> datetime:
    pattern = _FRACTIONAL_TIMESTAMP if fractional else _TIMESTAMP
    if not pattern.fullmatch(value):
        raise MeasureReviewError(f"{label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise MeasureReviewError(f"{label} timestamp is invalid") from error
    if parsed.tzinfo != timezone.utc:
        raise MeasureReviewError(f"{label} timestamp is invalid")
    return parsed


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    if not content or len(content) > 16_000_000:
        raise MeasureReviewError(f"{label} size is invalid")
    try:
        value = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MeasureReviewError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise MeasureReviewError(f"{label} must be an object")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MeasureReviewError(f"duplicate JSON field {key}")
        result[key] = value
    return result


def _reject_forbidden_value(value: object) -> None:
    try:
        reject_protected_fields(value)
    except ProtectedFieldError as error:
        raise MeasureReviewError(str(error)) from error
    found = _find_forbidden_key(value)
    if found is not None:
        raise MeasureReviewError(f"forbidden review field {found}")


def _find_forbidden_key(value: object) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold()
            if normalized in _FORBIDDEN_REVIEW_KEYS:
                return str(key)
            found = _find_forbidden_key(nested)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            found = _find_forbidden_key(nested)
            if found is not None:
                return found
    return None


def _canonical_cell(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise MeasureReviewError(f"{label} must be an object")
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MeasureReviewError(f"{label} must be non-empty text")
    return value


def _git_blob_hash(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()  # noqa: S324


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

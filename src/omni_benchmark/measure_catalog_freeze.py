"""Freeze the accepted R2 public-evidence measure catalog before question access."""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .measure_catalog_review import (
    MeasureReviewError,
    _reject_forbidden_value,
    _validated_catalog,
    materialize_measure_agent_adjudication,
)
from .measure_review_catalog import canonical_catalog_bytes


class AcceptedMeasureCatalogError(ValueError):
    """Raised when the accepted measure catalog cannot be frozen exactly."""


_CATALOG_VERSION = "public-evidence-measure-catalog-v1"
_DATABASE_SUMMARY_KEYS = frozenset(
    {"candidate_count", "database", "input_files", "screened", "screening"}
)
_INPUT_FILE_KEYS = frozenset({"path", "sha256"})


def build_accepted_measure_catalog(
    catalog_bytes: bytes,
    *,
    decisions_bytes: bytes,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    provenance_bytes: bytes,
    transcript_extract_bytes: bytes,
    base_proposal_bytes: bytes,
    base_approval_record_bytes: bytes,
    amendment_proposal_bytes: bytes,
    amendment_approval_record_bytes: bytes,
) -> dict[str, Any]:
    """Build the deterministic pre-question freeze from the exact approved chain."""
    try:
        catalog = _validated_catalog(catalog_bytes)
        regenerated_decisions = materialize_measure_agent_adjudication(
            catalog_bytes,
            source_workbook_bytes,
            adjudicated_workbook_bytes,
            provenance_bytes,
            transcript_extract_bytes,
            base_proposal_bytes,
            base_approval_record_bytes,
            amendment_proposal_bytes,
            amendment_approval_record_bytes,
        )
    except MeasureReviewError as error:
        raise AcceptedMeasureCatalogError(str(error)) from error
    if canonical_catalog_bytes(regenerated_decisions) != decisions_bytes:
        raise AcceptedMeasureCatalogError(
            "decision artifact does not reproduce from the approved adjudication chain"
        )

    candidate_by_id = {
        candidate["candidate_id"]: candidate for candidate in catalog["candidates"]
    }
    accepted_candidates: list[dict[str, Any]] = []
    for decision in regenerated_decisions["decisions"]:
        if decision["decision"] != "accept":
            continue
        candidate = copy.deepcopy(candidate_by_id[decision["candidate_id"]])
        if candidate.get("measure_id") != decision["measure_id"]:
            raise AcceptedMeasureCatalogError(
                "accepted decision measure identity does not match the candidate"
            )
        review = candidate.pop("review", None)
        if review != {
            "active_review_seconds": None,
            "binding_correction": None,
            "decision": None,
            "reason_code": None,
            "status": "pending",
        }:
            raise AcceptedMeasureCatalogError(
                "accepted candidate source review record is invalid"
            )
        accepted_candidates.append(candidate)

    accepted_ids = [item["candidate_id"] for item in accepted_candidates]
    if accepted_ids != sorted(accepted_ids) or len(accepted_ids) != len(
        set(accepted_ids)
    ):
        raise AcceptedMeasureCatalogError(
            "accepted candidate IDs must be unique and sorted"
        )
    measure_ids = [item["measure_id"] for item in accepted_candidates]
    if len(measure_ids) != len(set(measure_ids)):
        raise AcceptedMeasureCatalogError("accepted measure IDs must be unique")

    generator = _generator_record(catalog)
    class_counts = Counter(item["candidate_class"] for item in accepted_candidates)
    database_counts = Counter(item["database"] for item in accepted_candidates)
    accepted_databases = sorted(database_counts)
    source = copy.deepcopy(regenerated_decisions["source"])
    source["decision_artifact_sha256"] = _sha256(decisions_bytes)
    artifact: dict[str, Any] = {
        "accepted_candidates": accepted_candidates,
        "catalog_version": _CATALOG_VERSION,
        "generator": generator,
        "kind": "public-evidence-measure-catalog",
        "schema_version": 1,
        "source": source,
        "summary": {
            "accepted_candidate_count": len(accepted_candidates),
            "accepted_database_count": len(accepted_databases),
            "accepted_databases": accepted_databases,
            "candidate_count_by_class": dict(sorted(class_counts.items())),
            "measure_count_by_database": dict(sorted(database_counts.items())),
        },
    }
    artifact["manifest"] = {
        "ordered_candidate_ids": accepted_ids,
        "ordered_measure_ids": measure_ids,
    }
    artifact["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    _reject_forbidden_value(artifact)
    return artifact


def validate_accepted_measure_catalog(
    content: bytes,
    catalog_bytes: bytes,
    *,
    decisions_bytes: bytes,
    source_workbook_bytes: bytes,
    adjudicated_workbook_bytes: bytes,
    provenance_bytes: bytes,
    transcript_extract_bytes: bytes,
    base_proposal_bytes: bytes,
    base_approval_record_bytes: bytes,
    amendment_proposal_bytes: bytes,
    amendment_approval_record_bytes: bytes,
) -> dict[str, Any]:
    """Authenticate a frozen catalog by regenerating it from the approved chain."""
    expected = build_accepted_measure_catalog(
        catalog_bytes,
        decisions_bytes=decisions_bytes,
        source_workbook_bytes=source_workbook_bytes,
        adjudicated_workbook_bytes=adjudicated_workbook_bytes,
        provenance_bytes=provenance_bytes,
        transcript_extract_bytes=transcript_extract_bytes,
        base_proposal_bytes=base_proposal_bytes,
        base_approval_record_bytes=base_approval_record_bytes,
        amendment_proposal_bytes=amendment_proposal_bytes,
        amendment_approval_record_bytes=amendment_approval_record_bytes,
    )
    if canonical_catalog_bytes(expected) != content:
        raise AcceptedMeasureCatalogError(
            "accepted measure catalog does not reproduce from the approved chain"
        )
    return expected


def _generator_record(catalog: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _object(catalog.get("manifest"), "candidate catalog manifest")
    databases = manifest.get("databases")
    summaries = catalog.get("database_summaries")
    if (
        not isinstance(databases, list)
        or any(not isinstance(item, str) or not item for item in databases)
        or databases != sorted(databases)
        or len(databases) != len(set(databases))
        or manifest.get("database_count") != len(databases)
        or not isinstance(summaries, list)
    ):
        raise AcceptedMeasureCatalogError(
            "candidate catalog database inventory is invalid"
        )
    summary_databases: list[str] = []
    input_by_path: dict[str, str] = {}
    candidate_counts = Counter(item["database"] for item in catalog["candidates"])
    for raw_summary in summaries:
        summary = _object(raw_summary, "candidate database summary")
        if set(summary) != _DATABASE_SUMMARY_KEYS:
            raise AcceptedMeasureCatalogError(
                "candidate database summary shape is invalid"
            )
        database = _text(summary.get("database"), "candidate summary database")
        summary_databases.append(database)
        if summary.get("candidate_count") != candidate_counts[database]:
            raise AcceptedMeasureCatalogError(
                "candidate database summary count is invalid"
            )
        input_files = summary.get("input_files")
        if not isinstance(input_files, list):
            raise AcceptedMeasureCatalogError(
                "candidate generator input inventory is invalid"
            )
        normalized: list[tuple[str, str]] = []
        for raw_input in input_files:
            item = _object(raw_input, "candidate generator input")
            if set(item) != _INPUT_FILE_KEYS:
                raise AcceptedMeasureCatalogError(
                    "candidate generator input shape is invalid"
                )
            path = _relative_path(item.get("path"))
            digest = _digest(item.get("sha256"), "candidate generator input SHA-256")
            previous = input_by_path.setdefault(path, digest)
            if previous != digest:
                raise AcceptedMeasureCatalogError(
                    "candidate generator input path has conflicting hashes"
                )
            normalized.append((path, digest))
        if normalized != sorted(normalized):
            raise AcceptedMeasureCatalogError(
                "candidate generator inputs must be sorted"
            )
    if summary_databases != databases:
        raise AcceptedMeasureCatalogError(
            "candidate database summaries do not match the manifest"
        )
    return {
        "database_count": len(databases),
        "databases": databases,
        "input_files": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(input_by_path.items())
        ],
        "version": _text(catalog.get("generator_version"), "generator version"),
    }


def _object(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AcceptedMeasureCatalogError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcceptedMeasureCatalogError(f"{label} must be non-empty text")
    return value


def _digest(value: object, label: str) -> str:
    digest = _text(value, label)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise AcceptedMeasureCatalogError(f"{label} is invalid")
    return digest


def _relative_path(value: object) -> str:
    path = _text(value, "candidate generator input path")
    parts = Path(path).parts
    if (
        Path(path).is_absolute()
        or not parts
        or ".." in parts
        or any(part in {"", "."} for part in parts)
    ):
        raise AcceptedMeasureCatalogError("candidate generator input path is invalid")
    return path


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

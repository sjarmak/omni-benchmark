"""Validation for sanitized taxonomy and dev-B guardian receipts."""

from __future__ import annotations

import hmac
import json
import re
import subprocess
import tempfile
from pathlib import Path

from .autoresearch_config import (
    MANDATORY_FORBIDDEN_FIELDS,
    AutoresearchConfig,
    AutoresearchError,
    _display_path,
    _find_forbidden,
    _require_string,
    _resolve_inside,
    _sha256_bytes,
)

TAXONOMY_FIELDS = frozenset({"categories"})
TAXONOMY_CATEGORY_FIELDS = frozenset({"name", "count", "primary_source"})
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
OPENSSL_TIMEOUT_SECONDS = 10
MAX_RECEIPT_BYTES = 64 * 1024
MAX_PUBLIC_KEY_BYTES = 64 * 1024
MAX_SIGNATURE_BYTES = 1024 * 1024


def validate_taxonomy(
    path: Path,
    expected_count: int,
    *,
    forbidden_fields: frozenset[str] = MANDATORY_FORBIDDEN_FIELDS,
) -> str:
    """Validate a non-private aggregate failure taxonomy and return its hash."""
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AutoresearchError("taxonomy must be valid JSON") from error
    forbidden = _find_forbidden(value, forbidden_fields | MANDATORY_FORBIDDEN_FIELDS)
    if forbidden is not None:
        raise AutoresearchError("taxonomy contains a forbidden field")
    if not isinstance(value, dict) or set(value) != TAXONOMY_FIELDS:
        raise AutoresearchError("taxonomy has an invalid schema")
    if not isinstance(value["categories"], list):
        raise AutoresearchError("taxonomy categories must be an array")
    categories = value["categories"]
    if not categories:
        raise AutoresearchError("taxonomy categories must not be empty")
    names: set[str] = set()
    total = 0
    for category in categories:
        if not isinstance(category, dict) or set(category) != TAXONOMY_CATEGORY_FIELDS:
            raise AutoresearchError("taxonomy category has an invalid schema")
        name = category.get("name")
        count = category.get("count")
        source = category.get("primary_source")
        if not isinstance(name, str) or not name.strip():
            raise AutoresearchError("taxonomy category name must be non-empty")
        if name in names:
            raise AutoresearchError("taxonomy category names must be unique")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise AutoresearchError("taxonomy category count must be non-negative")
        if not isinstance(source, str) or not source.strip():
            raise AutoresearchError("taxonomy primary_source must be non-empty")
        names.add(name)
        total += count
    if total > expected_count:
        raise AutoresearchError("taxonomy counts exceed the training partition")
    return _sha256_bytes(raw)


def _read_bounded(path: Path, description: str, maximum: int) -> bytes:
    try:
        value = path.read_bytes()
    except OSError as error:
        raise AutoresearchError(f"cannot read {description}") from error
    if not value or len(value) > maximum:
        raise AutoresearchError(f"{description} has an invalid size")
    return value


def _verify_detached_signature(
    payload: bytes,
    signature: bytes,
    public_key: bytes,
) -> None:
    try:
        with tempfile.TemporaryDirectory(prefix="omni-guardian-verify-") as directory:
            temporary = Path(directory)
            public_key_path = temporary / "guardian-public.pem"
            signature_path = temporary / "receipt.sig"
            public_key_path.write_bytes(public_key)
            signature_path.write_bytes(signature)
            completed = subprocess.run(
                [
                    "openssl",
                    "dgst",
                    "-sha256",
                    "-verify",
                    str(public_key_path),
                    "-signature",
                    str(signature_path),
                ],
                input=payload,
                capture_output=True,
                check=False,
                timeout=OPENSSL_TIMEOUT_SECONDS,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise AutoresearchError(
            "guardian signature verification unavailable"
        ) from error
    if completed.returncode != 0:
        raise AutoresearchError("guardian signature verification failed")


def validate_dev_b_receipt(
    config: AutoresearchConfig,
    path: Path,
    *,
    candidate_run_sha256: str,
    signature_path: Path,
    public_key_path: Path,
    expected_public_key_sha256: str,
) -> dict[str, object]:
    """Validate a guardian-issued aggregate receipt without per-question outcomes."""
    receipt_path = _resolve_inside(config.workspace, path, "dev-B guardian receipt")
    resolved_signature_path = _resolve_inside(
        config.workspace, signature_path, "dev-B guardian signature"
    )
    if SHA256_PATTERN.fullmatch(expected_public_key_sha256) is None:
        raise AutoresearchError("guardian public-key pin must be a SHA-256 digest")
    resolved_public_key_path = Path(public_key_path).resolve(strict=False)
    raw = _read_bounded(receipt_path, "dev-B guardian receipt", MAX_RECEIPT_BYTES)
    signature = _read_bounded(
        resolved_signature_path, "dev-B guardian signature", MAX_SIGNATURE_BYTES
    )
    public_key = _read_bounded(
        resolved_public_key_path, "guardian public key", MAX_PUBLIC_KEY_BYTES
    )
    public_key_sha256 = _sha256_bytes(public_key)
    if not hmac.compare_digest(public_key_sha256, expected_public_key_sha256):
        raise AutoresearchError("guardian public key does not match the pinned SHA-256")
    _verify_detached_signature(raw, signature, public_key)
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AutoresearchError("cannot read valid dev-B guardian receipt") from error
    required = {
        "schema_version",
        "kind",
        "receipt_id",
        "guardian",
        "created_at",
        "candidate_run_sha256",
        "outputs_sha256",
        "scorer_version",
        "question_count",
        "correct_count",
        "wrong_answer_count",
        "refused_or_error_count",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise AutoresearchError("dev-B guardian receipt has an invalid schema")
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["kind"] != "dev-b-checkpoint-receipt"
    ):
        raise AutoresearchError("dev-B guardian receipt has an invalid version or kind")
    for field in ("receipt_id", "guardian", "created_at", "scorer_version"):
        _require_string(value[field], field)
    for field in ("candidate_run_sha256", "outputs_sha256"):
        digest = value[field]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise AutoresearchError(f"dev-B receipt {field} must be a SHA-256 digest")
    if value["candidate_run_sha256"] != candidate_run_sha256:
        raise AutoresearchError("dev-B receipt does not match the checkpoint candidate")
    if type(value["question_count"]) is not int or value["question_count"] < 0:
        raise AutoresearchError(
            "dev-B receipt question_count must be a non-negative integer"
        )
    counts = (
        value["correct_count"],
        value["wrong_answer_count"],
        value["refused_or_error_count"],
    )
    if any(
        isinstance(count, bool) or not isinstance(count, int) or count < 0
        for count in counts
    ):
        raise AutoresearchError(
            "dev-B receipt outcome counts must be non-negative integers"
        )
    if (
        value["question_count"] != config.expected_dev_b_count
        or sum(counts) != value["question_count"]
    ):
        raise AutoresearchError("dev-B receipt counts must exactly cover dev-B")
    return {
        **value,
        "path": _display_path(receipt_path, config.workspace),
        "receipt_sha256": _sha256_bytes(raw),
        "signature_path": _display_path(resolved_signature_path, config.workspace),
        "signature_sha256": _sha256_bytes(signature),
        "signature_verified": True,
        "guardian_public_key_sha256": public_key_sha256,
    }

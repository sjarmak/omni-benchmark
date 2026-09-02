"""Append-only failure-taxonomy labels stored as JSONL under experiments/labels."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .custody import SplitIds, assert_dev_a_instance
from .generation_rows import ReaderError, instance_of_attempt_id
from .taxonomy import TaxonomyError, validate_category


class LabelError(ValueError):
    """Raised when a label record is malformed or violates the ledger rules."""


LABEL_ID_INPUTS: tuple[str, ...] = (
    "pass_id",
    "attempt_id",
    "generation_record_sha256",
    "labeler",
    "taxonomy_version",
    "created_at",
)

REQUIRED_LINE_KEYS: frozenset[str] = frozenset(
    {
        "attempt_id",
        "generation_record_sha256",
        "taxonomy_version",
        "category",
        "labeler",
        "rationale",
        "created_at",
    }
)
OPTIONAL_LINE_KEYS: frozenset[str] = frozenset({"label_id", "pass_id"})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LABELER_RE = re.compile(r"^(human|model):\S+$")
_PASS_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class LabelRecord:
    label_id: str
    attempt_id: str
    generation_record_sha256: str
    taxonomy_version: str
    category: str
    labeler: str
    rationale: str
    created_at: str
    pass_id: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    def to_line(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False) + "\n"


def compute_label_id(values: Mapping[str, str]) -> str:
    """Deterministic identifier so re-reading a ledger line yields the same row."""
    payload = json.dumps([values[name] for name in LABEL_ID_INPUTS], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_pass_id(pass_id: str) -> str:
    if not isinstance(pass_id, str) or not _PASS_ID_RE.match(pass_id):
        raise LabelError(
            f"pass_id {pass_id!r} must be a file stem matching {_PASS_ID_RE.pattern}"
        )
    return pass_id


def _require_text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LabelError(f"{name} must be a non-empty string")
    return value


def _validate_created_at(value: object) -> str:
    text = _require_text("created_at", value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise LabelError(f"created_at {text!r} is not ISO-8601: {error}") from error
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise LabelError(f"created_at {text!r} must carry an explicit UTC offset")
    return text


def build_label_record(
    record_fields: Mapping[str, object], pass_id: str
) -> LabelRecord:
    """Validate raw field values and derive the label identifier."""
    if not isinstance(record_fields, Mapping):
        raise LabelError("label record must be a JSON object")
    validate_pass_id(pass_id)
    keys = set(record_fields)
    unknown = sorted(keys - REQUIRED_LINE_KEYS - OPTIONAL_LINE_KEYS)
    if unknown:
        raise LabelError(f"unknown label keys: {', '.join(unknown)}")
    missing = sorted(REQUIRED_LINE_KEYS - keys)
    if missing:
        raise LabelError(f"missing label keys: {', '.join(missing)}")
    values = _validated_values(record_fields, pass_id)
    label_id = compute_label_id(values)
    declared = record_fields.get("label_id")
    if declared is not None and declared != label_id:
        raise LabelError(
            f"label_id {declared!r} does not match the derived value {label_id}"
        )
    return LabelRecord(label_id=label_id, **values)


def _validated_values(
    record_fields: Mapping[str, object], pass_id: str
) -> dict[str, str]:
    declared_pass = record_fields.get("pass_id")
    if declared_pass is not None and declared_pass != pass_id:
        raise LabelError(f"pass_id {declared_pass!r} does not match {pass_id!r}")
    sha = _require_text(
        "generation_record_sha256", record_fields["generation_record_sha256"]
    )
    if not _SHA256_RE.match(sha):
        raise LabelError("generation_record_sha256 must be 64 lowercase hex characters")
    labeler = _require_text("labeler", record_fields["labeler"])
    if not _LABELER_RE.match(labeler):
        raise LabelError(
            f"labeler {labeler!r} must be 'human:<name>' or 'model:<name>'"
        )
    version = _require_text("taxonomy_version", record_fields["taxonomy_version"])
    category = _require_text("category", record_fields["category"])
    try:
        validate_category(version, category)
    except TaxonomyError as error:
        raise LabelError(str(error)) from error
    return {
        "attempt_id": _validate_attempt_id(record_fields["attempt_id"]),
        "generation_record_sha256": sha,
        "taxonomy_version": version,
        "category": category,
        "labeler": labeler,
        "rationale": _require_text("rationale", record_fields["rationale"]),
        "created_at": _validate_created_at(record_fields["created_at"]),
        "pass_id": pass_id,
    }


def _validate_attempt_id(value: object) -> str:
    attempt_id = _require_text("attempt_id", value)
    try:
        instance_of_attempt_id(attempt_id, "attempt_id")
    except ReaderError as error:
        raise LabelError(str(error)) from error
    return attempt_id


def instance_of_label(record: LabelRecord) -> str:
    """The instance the label's attempt ran against."""
    return instance_of_attempt_id(record.attempt_id, f"label {record.label_id}")


def parse_label_line(line: str, pass_id: str) -> LabelRecord:
    """Parse one JSONL ledger line belonging to ``pass_id``."""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError as error:
        raise LabelError(f"label line is not valid JSON: {error}") from error
    return build_label_record(payload, pass_id)


def iter_label_records(labels_dir: Path) -> Iterator[LabelRecord]:
    """Yield every record from ``labels_dir/*.jsonl`` in sorted file and line order."""
    if not labels_dir.is_dir():
        raise LabelError(f"labels directory {labels_dir} does not exist")
    for path in sorted(labels_dir.glob("*.jsonl")):
        pass_id = validate_pass_id(path.stem)
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                raise LabelError(f"{path}:{number}: blank line in label ledger")
            try:
                yield parse_label_line(line, pass_id)
            except LabelError as error:
                raise LabelError(f"{path}:{number}: {error}") from error


def append_label(
    labels_dir: Path,
    pass_id: str,
    record_fields: Mapping[str, object],
    *,
    split: SplitIds,
) -> LabelRecord:
    """Append one validated dev-A record to ``labels_dir/<pass_id>.jsonl``.

    Raises :class:`CustodyViolation` before writing when the attempt's instance
    is outside the dev-A split, so the ledger never carries such a line.
    """
    if not labels_dir.is_dir():
        raise LabelError(f"labels directory {labels_dir} does not exist")
    record = build_label_record(record_fields, pass_id)
    assert_dev_a_instance(instance_of_label(record), split, f"label {record.label_id}")
    path = labels_dir / f"{pass_id}.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.to_line())
    return record

"""Pure readers turning committed public artifacts into telemetry rows.

Nothing here touches a database. Each reader returns a :class:`SourceBatch`
carrying its rows, the records it set aside with a reason, and the sha256 of
every manifest it read. Run-tree readers live in :mod:`run_readers`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..custody import CustodyError, read_id_file
from .arms import ArmMapping, read_arms
from .custody import (
    DEV_A_IDS_FILENAME,
    DEV_B_IDS_FILENAME,
    TEST_IDS_FILENAME,
    SplitIds,
    assert_dev_a_instance,
    reject_forbidden_fields,
)
from .generation_rows import ReaderError, parse_json_object, parse_timestamp
from .labels import instance_of_label, iter_label_records
from .rows import Row
from .run_readers import read_dev_a
from .sealed_readers import read_sealed
from .sources import BatchBuilder, ReleasedQuestion, SourceBatch, load_json_object

QUESTIONS_FILENAME = "eligible_questions.jsonl"
PARTITION_ID_FILES = MappingProxyType(
    {
        "dev-a": DEV_A_IDS_FILENAME,
        "dev-b": DEV_B_IDS_FILENAME,
        "test": TEST_IDS_FILENAME,
    }
)
DEPLOYMENT_CLAIM_KIND = "public-omni-semantic-deployment-claim"
DEPLOYMENT_RECORD_KIND = "public-omni-semantic-deployment"
_DEPLOYMENT_TEXT_COLUMNS = (
    "connection_id",
    "branch_id",
    "branch_name",
    "failure_stage",
    "failure_detail",
)

__all__ = [
    "ArmMapping",
    "QuestionRelease",
    "ReleasedQuestion",
    "SourceBatch",
    "read_arms",
    "read_deployments",
    "read_dev_a",
    "read_labels",
    "read_questions",
    "read_sealed",
]


@dataclass(frozen=True)
class QuestionRelease:
    """Question rows plus the per-instance database and partition other readers need."""

    batch: SourceBatch
    questions: Mapping[str, ReleasedQuestion]


def read_questions(manifests_dir: Path, *, repo_root: Path) -> QuestionRelease:
    """Public question fields from the eligible release, partitioned by ID file."""
    builder = BatchBuilder("questions", repo_root)
    partitions = _partition_by_instance(manifests_dir, builder)
    path = manifests_dir / QUESTIONS_FILENAME
    builder.manifest(path)
    questions: dict[str, ReleasedQuestion] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        context = f"{path}:{number}"
        record = _question_record(line, context)
        instance_id = record["instance_id"]
        if instance_id in questions:
            raise ReaderError(f"{context}: duplicate instance_id {instance_id!r}")
        partition = partitions.get(instance_id)
        if partition is None:
            raise ReaderError(f"{context}: {instance_id!r} is in no partition ID file")
        questions[instance_id] = ReleasedQuestion(
            record["selected_database"], partition
        )
        builder.add(_question_row(record, partition, context))
    return QuestionRelease(builder.freeze(), MappingProxyType(questions))


def _partition_by_instance(
    manifests_dir: Path, builder: BatchBuilder
) -> dict[str, str]:
    partitions: dict[str, str] = {}
    for partition, filename in PARTITION_ID_FILES.items():
        path = manifests_dir / filename
        builder.manifest(path)
        try:
            ids = read_id_file(path)
        except CustodyError as error:
            raise ReaderError(f"{path}: {error}") from error
        for instance_id in ids:
            if instance_id in partitions:
                raise ReaderError(
                    f"{path}: {instance_id!r} is in more than one partition"
                )
            partitions[instance_id] = partition
    return partitions


def _question_record(line: str, context: str) -> dict[str, Any]:
    record = parse_json_object(line, "question record", context)
    reject_forbidden_fields(record, context)
    for key in ("instance_id", "selected_database", "query"):
        if not isinstance(record.get(key), str) or not record[key]:
            raise ReaderError(f"{context}: {key} must be a non-empty string")
    return record


def _question_row(record: Mapping[str, Any], partition: str, context: str) -> Row:
    high_level = record.get("high_level")
    if high_level is not None and not isinstance(high_level, bool):
        raise ReaderError(f"{context}: high_level must be a boolean or null")
    return Row(
        "question",
        {
            "instance_id": record["instance_id"],
            "database": record["selected_database"],
            "partition": partition,
            "category": record.get("category"),
            "high_level": high_level,
            "question": record["query"],
            "public_fields": dict(record),
        },
    )


def read_deployments(deployments_dir: Path, *, repo_root: Path) -> SourceBatch:
    """One row per claimed semantic-model deployment and database."""
    builder = BatchBuilder("deployments", repo_root)
    for directory in sorted(deployments_dir.iterdir()):
        if not directory.is_dir():
            builder.drop("deployments_entry_not_a_directory")
            continue
        claims = sorted(directory.glob("*.claim"))
        if len(claims) != 1:
            raise ReaderError(
                f"{directory}: expected exactly one .claim file, found {len(claims)}"
            )
        builder.manifest(claims[0])
        claim = load_json_object(claims[0])
        if claim.get("kind") != DEPLOYMENT_CLAIM_KIND:
            builder.drop(f"deployment_directory_skipped:{claim.get('kind')}")
            continue
        loaded = _deployment_rows(builder, directory, claim, claims[0])
        claimed = claim.get("databases")
        if not isinstance(claimed, list) or not set(loaded) <= set(claimed):
            raise ReaderError(f"{claims[0]}: records name databases the claim does not")
        unrecorded = set(claimed) - set(loaded)
        if unrecorded:
            builder.drop("deployment_claimed_database_without_record", len(unrecorded))
    return builder.freeze()


def _deployment_rows(
    builder: BatchBuilder, directory: Path, claim: Mapping[str, Any], claim_path: Path
) -> list[str]:
    loaded: list[str] = []
    for path in sorted(directory.glob("*.json")):
        record = load_json_object(path)
        kind = record.get("kind")
        if kind != DEPLOYMENT_RECORD_KIND:
            builder.drop(f"deployment_record_skipped:{kind}")
            continue
        if record.get("run_id") != claim.get("run_id"):
            raise ReaderError(f"{path}: run_id disagrees with {claim_path}")
        database = record.get("database")
        if not isinstance(database, str) or not database:
            raise ReaderError(f"{path}: database must be a non-empty string")
        values: dict[str, Any] = {
            "deployment_id": record["run_id"],
            "database": database,
            "file_count": record.get("file_count"),
            "file_sha256": record.get("file_sha256"),
        }
        for column in _DEPLOYMENT_TEXT_COLUMNS:
            value = record.get(column)
            if value is not None and not isinstance(value, str):
                raise ReaderError(f"{path}: {column} must be text")
            values[column] = value
        if values["file_count"] is not None and not isinstance(
            values["file_count"], int
        ):
            raise ReaderError(f"{path}: file_count must be an integer")
        builder.add(Row("deployment", values))
        loaded.append(database)
    return loaded


def read_labels(
    labels_dir: Path,
    *,
    repo_root: Path,
    split: SplitIds,
    attempt_keys: frozenset[tuple[str, str]],
) -> SourceBatch:
    """Every append-only label ledger line as an ``attempt_label`` row.

    A label naming an instance outside dev-A is a custody violation. A label
    whose ``(attempt_id, generation_record_sha256)`` is not among the loaded
    attempts is set aside with a counted reason: the ledger is append-only, so
    a mistyped line is superseded by a later one rather than edited away.
    """
    builder = BatchBuilder("labels", repo_root)
    for path in sorted(labels_dir.glob("*.jsonl")):
        builder.manifest(path)
    for record in iter_label_records(labels_dir):
        context = f"label {record.label_id}"
        assert_dev_a_instance(instance_of_label(record), split, context)
        if (record.attempt_id, record.generation_record_sha256) not in attempt_keys:
            builder.drop("label_attempt_not_loaded")
            continue
        values = record.to_dict()
        values["created_at"] = parse_timestamp(record.created_at, context)
        builder.add(Row("attempt_label", values))
    return builder.freeze()

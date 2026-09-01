"""Freeze a deterministic public-identity-only paired schedule for R2."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .measure_catalog_review import MeasureReviewError, write_review_artifact
from .measure_review_catalog import canonical_catalog_bytes
from .protected_fields import ProtectedFieldError, reject_protected_fields


class R2PairedScheduleError(ValueError):
    """Raised when the R2 paired schedule cannot be reproduced safely."""


CONTROL_CONDITION = "R2-C5B"
TREATMENT_CONDITION = "R2-M1"
SCHEDULE_SEED = "omni-livesqlbench-large-v1-r2-measures-schedule-v1"
EXPECTED_DEV_A_COUNT = 154
EXPECTED_PAIR_COUNT = 136
EXPECTED_ATTEMPT_COUNT = EXPECTED_PAIR_COUNT * 2
EXPECTED_DATABASE_COUNT = 16

_ALGORITHM_NAME = "r2_database_round_robin_paired_v1"
_KIND = "r2-public-evidence-measures-paired-schedule"
_SCHEDULE_VERSION = "r2-public-evidence-measures-paired-schedule-v1"
_TARGET_KIND = "r2-public-evidence-measure-targets"
_TARGET_KEYS = frozenset({"databases", "kind", "schema_version"})
_SAFE_DATABASE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SOURCE_PATHS = {
    "dev_a_ids": "data/manifests/dev_a_ids.txt",
    "development_split_metadata": "data/manifests/development_split_metadata.json",
    "public_manifest": "data/manifests/eligible_questions.jsonl",
    "target_configuration": (
        "config/conditions/r2-public-evidence-measure-databases-v1.json"
    ),
}
_MAX_PUBLIC_MANIFEST_BYTES = 64_000_000
_MAX_DEV_A_IDS_BYTES = 2_000_000
_MAX_METADATA_BYTES = 4_000_000
_MAX_TARGET_BYTES = 128_000
_MAX_SCHEDULE_BYTES = 16_000_000


def build_r2_paired_schedule(
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    split_metadata_bytes: bytes,
    target_config_bytes: bytes,
    *,
    seed: str = SCHEDULE_SEED,
    expected_dev_a_count: int = EXPECTED_DEV_A_COUNT,
    expected_pair_count: int = EXPECTED_PAIR_COUNT,
    expected_database_count: int = EXPECTED_DATABASE_COUNT,
) -> dict[str, Any]:
    """Build the exact paired order without using question content or outcomes."""
    _positive_int(expected_dev_a_count, "expected dev-A count")
    _positive_int(expected_pair_count, "expected pair count")
    _positive_int(expected_database_count, "expected database count")
    if expected_pair_count % 2:
        raise R2PairedScheduleError("pair count must be even for exact arm balance")
    if not isinstance(seed, str) or not seed or seed.strip() != seed:
        raise R2PairedScheduleError("schedule seed is invalid")

    targets = _target_databases(target_config_bytes, expected_database_count)
    public_records = _public_identities(public_manifest_bytes)
    dev_a_ids = _dev_a_id_values(dev_a_ids_bytes)
    if not set(dev_a_ids).issubset(public_records):
        raise R2PairedScheduleError("every dev-A ID must exist in the public manifest")
    if dev_a_ids != tuple(sorted(dev_a_ids)):
        raise R2PairedScheduleError("dev-A IDs must be sorted")
    _validate_split_metadata(
        split_metadata_bytes,
        public_manifest_bytes,
        dev_a_ids_bytes,
        expected_dev_a_count,
    )
    if len(dev_a_ids) != expected_dev_a_count:
        raise R2PairedScheduleError("dev-A count does not match the expected count")

    by_database: dict[str, list[str]] = {database: [] for database in targets}
    for instance_id in dev_a_ids:
        database = public_records[instance_id]
        if database in by_database:
            by_database[database].append(instance_id)
    empty = [database for database, values in by_database.items() if not values]
    if empty:
        raise R2PairedScheduleError(
            f"target database {empty[0]} has no eligible dev-A questions"
        )
    actual_pair_count = sum(len(values) for values in by_database.values())
    if actual_pair_count != expected_pair_count:
        raise R2PairedScheduleError(
            "eligible dev-A pair count does not match the expected pair count"
        )

    database_order = sorted(
        targets, key=lambda value: _order_key(seed, "database", value)
    )
    question_order = {
        database: sorted(
            values,
            key=lambda value: _order_key(seed, "question", database, value),
        )
        for database, values in by_database.items()
    }
    first_conditions = _first_condition_assignments(seed, by_database)

    pairs: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    pair_position = 0
    for database_round in range(1, max(map(len, question_order.values())) + 1):
        for database in database_order:
            ordered_ids = question_order[database]
            if database_round > len(ordered_ids):
                continue
            instance_id = ordered_ids[database_round - 1]
            pair_position += 1
            first_condition = first_conditions[instance_id]
            second_condition = _other_condition(first_condition)
            pair_id = _stable_id(
                "r2pair", seed, database, instance_id, str(pair_position)
            )
            pair = {
                "database": database,
                "database_round": database_round,
                "first_condition": first_condition,
                "instance_id": instance_id,
                "pair_id": pair_id,
                "pair_position": pair_position,
                "second_condition": second_condition,
            }
            pairs.append(pair)
            for within_pair_position, condition in enumerate(
                (first_condition, second_condition), start=1
            ):
                attempt_position = len(attempts) + 1
                attempts.append(
                    {
                        "attempt_id": _stable_id(
                            "r2attempt",
                            seed,
                            pair_id,
                            condition,
                            str(within_pair_position),
                        ),
                        "attempt_position": attempt_position,
                        "condition": condition,
                        "database": database,
                        "instance_id": instance_id,
                        "pair_id": pair_id,
                        "pair_position": pair_position,
                        "repetition": 1,
                        "within_pair_position": within_pair_position,
                    }
                )

    condition_attempt_counts = Counter(item["condition"] for item in attempts)
    first_condition_counts = Counter(item["first_condition"] for item in pairs)
    first_by_database: dict[str, Counter[str]] = defaultdict(Counter)
    for pair in pairs:
        first_by_database[pair["database"]][pair["first_condition"]] += 1
    pair_count_by_database = {
        database: len(by_database[database]) for database in sorted(by_database)
    }
    artifact: dict[str, Any] = {
        "algorithm": {
            "database_order": "sha256",
            "first_arm_balance": "within_database_then_global",
            "name": _ALGORITHM_NAME,
            "pair_adjacency": True,
            "question_order_within_database": "sha256",
            "seed": seed,
        },
        "attempts": attempts,
        "information_boundary": {
            "correctness_used": False,
            "hidden_annotations_used": False,
            "opportunity_map_used": False,
            "question_text_used": False,
            "sealed_test_used": False,
        },
        "kind": _KIND,
        "pairs": pairs,
        "schedule_version": _SCHEDULE_VERSION,
        "schema_version": 1,
        "source": {
            "dev_a_ids": {
                "path": _SOURCE_PATHS["dev_a_ids"],
                "sha256": _sha256(dev_a_ids_bytes),
            },
            "development_split_metadata": {
                "path": _SOURCE_PATHS["development_split_metadata"],
                "sha256": _sha256(split_metadata_bytes),
            },
            "public_manifest": {
                "path": _SOURCE_PATHS["public_manifest"],
                "sha256": _sha256(public_manifest_bytes),
            },
            "target_configuration": {
                "path": _SOURCE_PATHS["target_configuration"],
                "sha256": _sha256(target_config_bytes),
            },
        },
        "summary": {
            "attempt_count": len(attempts),
            "condition_attempt_counts": _condition_counts(condition_attempt_counts),
            "database_count": len(by_database),
            "dev_a_count": len(dev_a_ids),
            "first_condition_counts": _condition_counts(first_condition_counts),
            "first_condition_counts_by_database": {
                database: _condition_counts(first_by_database[database])
                for database in sorted(by_database)
            },
            "pair_count": len(pairs),
            "pair_count_by_database": pair_count_by_database,
        },
    }
    artifact["manifest"] = {
        "ordered_attempt_ids": [item["attempt_id"] for item in attempts],
        "ordered_pair_ids": [item["pair_id"] for item in pairs],
    }
    artifact["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    _assert_schedule_invariants(artifact, expected_pair_count)
    return artifact


def validate_r2_paired_schedule(
    content: bytes,
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    split_metadata_bytes: bytes,
    target_config_bytes: bytes,
    *,
    seed: str = SCHEDULE_SEED,
    expected_dev_a_count: int = EXPECTED_DEV_A_COUNT,
    expected_pair_count: int = EXPECTED_PAIR_COUNT,
    expected_database_count: int = EXPECTED_DATABASE_COUNT,
) -> dict[str, Any]:
    """Regenerate the schedule and reject any changed frozen content."""
    observed = _json_object(content, "paired schedule", _MAX_SCHEDULE_BYTES)
    expected = build_r2_paired_schedule(
        public_manifest_bytes,
        dev_a_ids_bytes,
        split_metadata_bytes,
        target_config_bytes,
        seed=seed,
        expected_dev_a_count=expected_dev_a_count,
        expected_pair_count=expected_pair_count,
        expected_database_count=expected_database_count,
    )
    if canonical_catalog_bytes(observed) != canonical_catalog_bytes(expected):
        raise R2PairedScheduleError(
            "paired schedule does not reproduce from the frozen public inputs"
        )
    if content != canonical_catalog_bytes(observed):
        raise R2PairedScheduleError("paired schedule is not canonical JSON")
    return expected


def write_r2_paired_schedule(destination: Path, schedule: Mapping[str, object]) -> None:
    """Publish a canonical schedule append-only with mode 0600."""
    if not isinstance(schedule, Mapping):
        raise R2PairedScheduleError("paired schedule must be an object")
    try:
        content = canonical_catalog_bytes(schedule)
        write_review_artifact(destination, content)
    except (MeasureReviewError, TypeError, ValueError) as error:
        raise R2PairedScheduleError(str(error)) from error


def _first_condition_assignments(
    seed: str, by_database: Mapping[str, Sequence[str]]
) -> dict[str, str]:
    odd_databases = sorted(
        (database for database, values in by_database.items() if len(values) % 2),
        key=lambda value: _order_key(seed, "odd-extra", value),
    )
    if len(odd_databases) % 2:
        raise R2PairedScheduleError(
            "odd database strata cannot produce exact global arm balance"
        )
    control_extra = set(odd_databases[: len(odd_databases) // 2])
    result: dict[str, str] = {}
    for database, instance_ids in by_database.items():
        ordered = sorted(
            instance_ids,
            key=lambda value: _order_key(seed, "first-arm", database, value),
        )
        control_count = len(ordered) // 2 + int(database in control_extra)
        for index, instance_id in enumerate(ordered):
            result[instance_id] = (
                CONTROL_CONDITION if index < control_count else TREATMENT_CONDITION
            )
    return result


def _target_databases(content: bytes, expected_count: int) -> tuple[str, ...]:
    value = _json_object(content, "target configuration", _MAX_TARGET_BYTES)
    if set(value) != _TARGET_KEYS:
        raise R2PairedScheduleError("target configuration shape is invalid")
    if value.get("kind") != _TARGET_KIND or value.get("schema_version") != 1:
        raise R2PairedScheduleError("target configuration identity is invalid")
    databases = value.get("databases")
    if not isinstance(databases, list) or any(
        not isinstance(item, str) or not _SAFE_DATABASE.fullmatch(item)
        for item in databases
    ):
        raise R2PairedScheduleError("target databases must be safe names")
    if databases != sorted(databases) or len(databases) != len(set(databases)):
        raise R2PairedScheduleError("target databases must be unique and sorted")
    if len(databases) != expected_count:
        raise R2PairedScheduleError("target database count is invalid")
    return tuple(databases)


def _public_identities(content: bytes) -> dict[str, str]:
    if (
        not isinstance(content, bytes)
        or not content
        or len(content) > _MAX_PUBLIC_MANIFEST_BYTES
    ):
        raise R2PairedScheduleError("public manifest size is invalid")
    lines = content.splitlines(keepends=True)
    if not lines or any(not line.endswith(b"\n") for line in lines):
        raise R2PairedScheduleError("public manifest must be newline-terminated")
    result: dict[str, str] = {}
    for line_number, raw in enumerate(lines, start=1):
        try:
            value = json.loads(raw, object_pairs_hook=_strict_object)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise R2PairedScheduleError(
                f"public manifest line {line_number} is not valid JSON"
            ) from error
        if not isinstance(value, Mapping):
            raise R2PairedScheduleError("public manifest record must be an object")
        _reject_protected(value, "public manifest")
        instance_id = _text(value.get("instance_id"), "public instance_id")
        database = _text(value.get("selected_database"), "public database")
        if instance_id in result:
            raise R2PairedScheduleError(
                f"public manifest contains duplicate instance_id {instance_id}"
            )
        # Deliberately retain only public identity and database membership.
        result[instance_id] = database
    return result


def _dev_a_id_values(content: bytes) -> tuple[str, ...]:
    if (
        not isinstance(content, bytes)
        or not content
        or len(content) > _MAX_DEV_A_IDS_BYTES
    ):
        raise R2PairedScheduleError("dev-A IDs size is invalid")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise R2PairedScheduleError("dev-A IDs are invalid UTF-8") from error
    if not text.endswith("\n") or "\r" in text:
        raise R2PairedScheduleError("dev-A IDs must be newline-terminated")
    values = tuple(text.splitlines())
    if any(not value or value.strip() != value for value in values):
        raise R2PairedScheduleError("dev-A ID is invalid")
    if len(values) != len(set(values)):
        raise R2PairedScheduleError("dev-A IDs contain a duplicate")
    return values


def _validate_split_metadata(
    content: bytes,
    public_manifest_bytes: bytes,
    dev_a_ids_bytes: bytes,
    expected_dev_a_count: int,
) -> None:
    metadata = _json_object(content, "development split metadata", _MAX_METADATA_BYTES)
    _reject_protected(metadata, "development split metadata")
    if metadata.get("schema_version") != 1:
        raise R2PairedScheduleError("development split metadata identity is invalid")
    counts = _mapping(metadata.get("counts"), "development split counts")
    if counts.get("dev_a") != expected_dev_a_count:
        raise R2PairedScheduleError("development split dev-A count is invalid")
    manifest = _mapping(metadata.get("manifest"), "development split manifest")
    if manifest.get("file") != "eligible_questions.jsonl":
        raise R2PairedScheduleError("development split public manifest path is invalid")
    if manifest.get("sha256") != _sha256(public_manifest_bytes):
        raise R2PairedScheduleError("development split public manifest hash is invalid")
    artifacts = _mapping(metadata.get("artifacts"), "development split artifacts")
    dev_a = _mapping(artifacts.get("dev_a_ids"), "development split dev-A IDs")
    if dev_a.get("file") != "dev_a_ids.txt":
        raise R2PairedScheduleError("development split dev-A ID path is invalid")
    if dev_a.get("sha256") != _sha256(dev_a_ids_bytes):
        raise R2PairedScheduleError("development split dev-A ID hash is invalid")
    source = _mapping(metadata.get("source"), "development split source")
    _text(source.get("dataset"), "development split dataset")
    _text(source.get("revision"), "development split revision")


def _assert_schedule_invariants(
    artifact: Mapping[str, object], expected_pair_count: int
) -> None:
    pairs = artifact["pairs"]
    attempts = artifact["attempts"]
    if not isinstance(pairs, list) or not isinstance(attempts, list):
        raise R2PairedScheduleError("internal schedule shape is invalid")
    if len(pairs) != expected_pair_count or len(attempts) != expected_pair_count * 2:
        raise R2PairedScheduleError("internal schedule count invariant failed")
    instance_ids = [item["instance_id"] for item in pairs]
    pair_ids = [item["pair_id"] for item in pairs]
    attempt_ids = [item["attempt_id"] for item in attempts]
    if len(instance_ids) != len(set(instance_ids)):
        raise R2PairedScheduleError("internal schedule repeats an instance")
    if len(pair_ids) != len(set(pair_ids)) or len(attempt_ids) != len(set(attempt_ids)):
        raise R2PairedScheduleError("internal schedule identity collision")
    first_counts = Counter(item["first_condition"] for item in pairs)
    if first_counts != Counter(
        {
            CONTROL_CONDITION: expected_pair_count // 2,
            TREATMENT_CONDITION: expected_pair_count // 2,
        }
    ):
        raise R2PairedScheduleError("internal schedule global arm balance failed")
    per_database: dict[str, Counter[str]] = defaultdict(Counter)
    for pair in pairs:
        per_database[pair["database"]][pair["first_condition"]] += 1
    if any(
        abs(counts[CONTROL_CONDITION] - counts[TREATMENT_CONDITION]) > 1
        for counts in per_database.values()
    ):
        raise R2PairedScheduleError("internal schedule database arm balance failed")
    for index, pair in enumerate(pairs):
        first, second = attempts[index * 2 : index * 2 + 2]
        if (
            first["pair_id"] != pair["pair_id"]
            or second["pair_id"] != pair["pair_id"]
            or first["condition"] != pair["first_condition"]
            or second["condition"] != pair["second_condition"]
            or first["within_pair_position"] != 1
            or second["within_pair_position"] != 2
        ):
            raise R2PairedScheduleError("internal schedule pair adjacency failed")


def _condition_counts(counts: Mapping[str, int]) -> dict[str, int]:
    return {
        CONTROL_CONDITION: counts.get(CONTROL_CONDITION, 0),
        TREATMENT_CONDITION: counts.get(TREATMENT_CONDITION, 0),
    }


def _order_key(seed: str, domain: str, *parts: str) -> bytes:
    framed = [domain, seed, *parts]
    payload = b"".join(
        len(item.encode("utf-8")).to_bytes(4, "big") + item.encode("utf-8")
        for item in framed
    )
    return hashlib.sha256(payload).digest()


def _stable_id(prefix: str, seed: str, *parts: str) -> str:
    return f"{prefix}-{_order_key(seed, prefix, *parts).hex()[:24]}"


def _other_condition(condition: str) -> str:
    if condition == CONTROL_CONDITION:
        return TREATMENT_CONDITION
    if condition == TREATMENT_CONDITION:
        return CONTROL_CONDITION
    raise R2PairedScheduleError("condition is invalid")


def _json_object(content: bytes, label: str, maximum_bytes: int) -> dict[str, Any]:
    if not isinstance(content, bytes) or not content or len(content) > maximum_bytes:
        raise R2PairedScheduleError(f"{label} size is invalid")
    try:
        value = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise R2PairedScheduleError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise R2PairedScheduleError(f"{label} must be an object")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise R2PairedScheduleError(f"duplicate JSON field {key}")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise R2PairedScheduleError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise R2PairedScheduleError(f"{label} is invalid")
    return value


def _positive_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise R2PairedScheduleError(f"{label} is invalid")


def _reject_protected(value: object, label: str) -> None:
    try:
        reject_protected_fields(value)
    except ProtectedFieldError as error:
        raise R2PairedScheduleError(f"{label} contains a protected field") from error


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

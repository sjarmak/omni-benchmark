"""Validate public LiveSQLBench data and create the preregistered split."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DATASET_NAME = "birdsql/livesqlbench-large-v1"
ELIGIBLE_CATEGORY = "Query"
DEFAULT_SPLIT_SEED = "omni-livesqlbench-large-v1-split-v1"
DEFAULT_DEVELOPMENT_SPLIT_SEED = "omni-livesqlbench-large-v1-development-split-v1"
PRIVATE_FIELDS = ("sol_sql", "external_knowledge", "test_cases")
REQUIRED_FIELDS = frozenset(
    {
        "instance_id",
        "selected_database",
        "query",
        "normal_query",
        "preprocess_sql",
        "clean_up_sqls",
        *PRIVATE_FIELDS,
        "category",
        "high_level",
        "conditions",
    }
)
PUBLIC_MANIFEST_FIELDS = (
    "instance_id",
    "selected_database",
    "query",
    "normal_query",
    "preprocess_sql",
    "clean_up_sqls",
    "category",
    "high_level",
    "conditions",
)


class PublicDataError(ValueError):
    """Raised when the public benchmark source violates its expected schema."""


class SplitError(ValueError):
    """Raised when a deterministic split cannot be safely produced."""


def _canonical_json(value: Any, *, pretty: bool) -> bytes:
    if pretty:
        text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    else:
        text = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
    return (text + "\n").encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _require_nonempty_string(
    record: Mapping[str, Any], field: str, line_number: int
) -> None:
    value = record[field]
    if not isinstance(value, str) or not value:
        raise PublicDataError(f"line {line_number}: {field} must be a non-empty string")


def _validate_string_list(
    record: Mapping[str, Any], field: str, line_number: int
) -> None:
    value = record[field]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise PublicDataError(f"line {line_number}: {field} must be a list of strings")


def _validate_record(record: Any, line_number: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise PublicDataError(f"line {line_number}: record must be a JSON object")
    missing = sorted(REQUIRED_FIELDS - record.keys())
    if missing:
        raise PublicDataError(
            f"line {line_number}: missing fields: {', '.join(missing)}"
        )
    unknown = sorted(record.keys() - REQUIRED_FIELDS)
    if unknown:
        raise PublicDataError(
            f"line {line_number}: unknown fields: {', '.join(unknown)}"
        )

    for field in ("instance_id", "selected_database", "query", "normal_query"):
        _require_nonempty_string(record, field, line_number)
    for field in ("preprocess_sql", "clean_up_sqls"):
        _validate_string_list(record, field, line_number)
    for field in PRIVATE_FIELDS:
        if record[field] != []:
            raise PublicDataError(
                f"line {line_number}: private field {field} must be empty"
            )
    if record["category"] not in {"Query", "Management"}:
        raise PublicDataError(
            f"line {line_number}: category must be Query or Management"
        )
    if not isinstance(record["high_level"], bool):
        raise PublicDataError(f"line {line_number}: high_level must be a boolean")

    conditions = record["conditions"]
    if not isinstance(conditions, dict) or set(conditions) != {
        "decimal",
        "distinct",
        "order",
    }:
        raise PublicDataError(
            f"line {line_number}: conditions must contain decimal, distinct, and order"
        )
    decimal = conditions["decimal"]
    if not isinstance(decimal, int) or isinstance(decimal, bool):
        raise PublicDataError(
            f"line {line_number}: conditions.decimal must be an integer"
        )
    for field in ("distinct", "order"):
        if not isinstance(conditions[field], bool):
            raise PublicDataError(
                f"line {line_number}: conditions.{field} must be a boolean"
            )

    return {**record, "source_index": line_number}


def _read_source_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise PublicDataError(f"cannot read public source {path}: {error}") from error


def _parse_public_records(content: bytes, source_name: str) -> list[dict[str, Any]]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise PublicDataError(
            f"cannot decode public source {source_name}: {error}"
        ) from error
    if not lines:
        raise PublicDataError(f"public source {source_name} contains no records")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise PublicDataError(f"line {line_number}: blank JSONL record")
        try:
            raw_record = json.loads(line)
        except json.JSONDecodeError as error:
            raise PublicDataError(
                f"line {line_number} is not valid JSON: {error.msg}"
            ) from error
        record = _validate_record(raw_record, line_number)
        instance_id = record["instance_id"]
        if instance_id in seen_ids:
            raise PublicDataError(
                f"line {line_number}: duplicate instance_id {instance_id}"
            )
        seen_ids.add(instance_id)
        records.append(record)
    return records


def read_public_records(source_path: Path | str) -> list[dict[str, Any]]:
    """Read and validate a pinned public JSONL without accepting private labels."""

    path = Path(source_path)
    return _parse_public_records(_read_source_bytes(path), str(path))


def _manifest_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{field: record[field] for field in PUBLIC_MANIFEST_FIELDS},
        "source_index": record["source_index"],
    }


def prepare_public_manifest(
    source_path: Path | str,
    output_dir: Path | str,
    *,
    source_commit: str,
) -> dict[str, Any]:
    """Create a public-only eligible manifest and its provenance metadata."""

    source = Path(source_path)
    destination = Path(output_dir)
    manifest_path = destination / "eligible_questions.jsonl"
    try:
        if source.resolve() == manifest_path.resolve():
            raise PublicDataError("output would overwrite input public source")
    except OSError as error:
        raise PublicDataError(f"cannot resolve input/output paths: {error}") from error
    if not isinstance(source_commit, str) or not source_commit:
        raise PublicDataError("source_commit must be a non-empty string")

    source_bytes = _read_source_bytes(source)
    records = _parse_public_records(source_bytes, str(source))
    eligible = sorted(
        (
            _manifest_record(record)
            for record in records
            if record["category"] == ELIGIBLE_CATEGORY
        ),
        key=lambda record: record["instance_id"],
    )
    if not eligible:
        raise PublicDataError("public source contains no eligible Query records")

    manifest_bytes = b"".join(
        _canonical_json(record, pretty=False) for record in eligible
    )
    categories = dict(sorted(Counter(record["category"] for record in records).items()))
    databases = dict(
        sorted(Counter(record["selected_database"] for record in eligible).items())
    )
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "source": {
            "dataset": DATASET_NAME,
            "file": source.name,
            "revision": source_commit,
            "sha256": _sha256(source_bytes),
        },
        "manifest": {
            "file": manifest_path.name,
            "sha256": _sha256(manifest_bytes),
        },
        "counts": {
            "source": len(records),
            "eligible": len(eligible),
            "excluded": len(records) - len(eligible),
        },
        "categories": categories,
        "databases": databases,
        "eligibility": {"category": ELIGIBLE_CATEGORY},
        "private_field_policy": {field: "required_empty" for field in PRIVATE_FIELDS},
    }

    destination.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)
    (destination / "manifest_metadata.json").write_bytes(
        _canonical_json(metadata, pretty=True)
    )
    return metadata


def _read_split_metadata(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SplitError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise SplitError(f"{path.name} must contain a JSON object")
    return value


def _parse_manifest(content: bytes) -> list[dict[str, Any]]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise SplitError(f"cannot read eligible manifest: {error}") from error
    if not lines:
        raise SplitError("eligible manifest is empty")

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise SplitError(
                f"manifest line {line_number} is not valid JSON"
            ) from error
        if not isinstance(record, dict):
            raise SplitError(f"manifest line {line_number} must be an object")
        instance_id = record.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise SplitError(f"manifest line {line_number} has invalid instance_id")
        if instance_id in seen:
            raise SplitError(f"manifest contains duplicate instance_id {instance_id}")
        if (
            not isinstance(record.get("selected_database"), str)
            or not record["selected_database"]
        ):
            raise SplitError(
                f"manifest line {line_number} has invalid selected_database"
            )
        if not isinstance(record.get("high_level"), bool):
            raise SplitError(f"manifest line {line_number} has invalid high_level")
        conditions = record.get("conditions")
        if not isinstance(conditions, dict):
            raise SplitError(f"manifest line {line_number} has invalid conditions")
        seen.add(instance_id)
        records.append(record)
    return records


def _allocate_proportionally(
    counts: Mapping[Any, int], allocation: int
) -> dict[Any, int]:
    total = sum(counts.values())
    if allocation < 0 or allocation > total or total == 0:
        raise SplitError("proportional allocation is outside the available population")
    quotas = {key: Fraction(allocation * count, total) for key, count in counts.items()}
    allocated = {
        key: quota.numerator // quota.denominator for key, quota in quotas.items()
    }
    remaining = allocation - sum(allocated.values())
    ranked = sorted(
        counts,
        key=lambda key: (-(quotas[key] - allocated[key]), str(key)),
    )
    for key in ranked[:remaining]:
        allocated[key] += 1
    return allocated


def _keyed_order(record: Mapping[str, Any], seed: str) -> tuple[str, str]:
    material = "\0".join(
        (
            seed,
            record["selected_database"],
            "true" if record["high_level"] else "false",
            record["instance_id"],
        )
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest(), record["instance_id"]


def _condition_distribution(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    selected = list(records)
    high_level = Counter(str(record["high_level"]).lower() for record in selected)
    decimal = Counter(str(record["conditions"]["decimal"]) for record in selected)
    distinct = Counter(
        str(record["conditions"]["distinct"]).lower() for record in selected
    )
    order = Counter(str(record["conditions"]["order"]).lower() for record in selected)
    return {
        "count": len(selected),
        "high_level": dict(sorted(high_level.items())),
        "conditions": {
            "decimal": dict(sorted(decimal.items(), key=lambda item: int(item[0]))),
            "distinct": dict(sorted(distinct.items())),
            "order": dict(sorted(order.items())),
        },
    }


def _ids_bytes(ids: Iterable[str]) -> bytes:
    return "".join(f"{instance_id}\n" for instance_id in sorted(ids)).encode("utf-8")


def _read_ids_artifact(path: Path) -> tuple[bytes, set[str]]:
    try:
        content = path.read_bytes()
        text = content.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise SplitError(f"cannot read {path.name}: {error}") from error
    lines = text.splitlines()
    if not lines or any(not item for item in lines):
        raise SplitError(f"{path.name} must contain non-empty IDs")
    if len(lines) != len(set(lines)):
        raise SplitError(f"{path.name} contains a duplicate ID")
    return content, set(lines)


def _load_split_inputs(
    directory: Path,
) -> tuple[Path, bytes, list[dict[str, Any]], dict[str, Any]]:
    manifest_path = directory / "eligible_questions.jsonl"
    try:
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        raise SplitError(f"cannot read eligible manifest: {error}") from error
    records = _parse_manifest(manifest_bytes)
    metadata = _read_split_metadata(directory / "manifest_metadata.json")
    expected_hash = metadata.get("manifest", {}).get("sha256")
    if expected_hash != _sha256(manifest_bytes):
        raise SplitError("manifest SHA-256 does not match manifest_metadata.json")
    return manifest_path, manifest_bytes, records, metadata


def _select_test_ids(
    by_database: Mapping[str, list[dict[str, Any]]], test_size: int, seed: str
) -> set[str]:
    database_test_counts = _allocate_proportionally(
        {database: len(records) for database, records in by_database.items()}, test_size
    )
    selected: set[str] = set()
    for database, database_records in sorted(by_database.items()):
        strata = {
            high_level: [
                record
                for record in database_records
                if record["high_level"] is high_level
            ]
            for high_level in (False, True)
        }
        nonempty_counts = {key: len(value) for key, value in strata.items() if value}
        stratum_test_counts = _allocate_proportionally(
            nonempty_counts, database_test_counts[database]
        )
        for high_level, count in stratum_test_counts.items():
            ordered = sorted(
                strata[high_level], key=lambda record: _keyed_order(record, seed)
            )
            selected.update(record["instance_id"] for record in ordered[:count])
    return selected


def _database_distributions(
    by_database: Mapping[str, list[dict[str, Any]]],
    train_ids: set[str],
    test_ids: set[str],
) -> dict[str, Any]:
    distributions: dict[str, Any] = {}
    for database, database_records in sorted(by_database.items()):
        database_train = [
            record for record in database_records if record["instance_id"] in train_ids
        ]
        database_test = [
            record for record in database_records if record["instance_id"] in test_ids
        ]
        distributions[database] = {
            "eligible": len(database_records),
            "train": len(database_train),
            "test": len(database_test),
            "high_level": {
                "eligible": sum(record["high_level"] for record in database_records),
                "train": sum(record["high_level"] for record in database_train),
                "test": sum(record["high_level"] for record in database_test),
            },
        }
    return distributions


def _build_split_metadata(
    *,
    manifest_path: Path,
    manifest_bytes: bytes,
    manifest_metadata: Mapping[str, Any],
    records: list[dict[str, Any]],
    train_ids: set[str],
    test_ids: set[str],
    seed: str,
    train_bytes: bytes,
    test_bytes: bytes,
    by_database: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    records_by_id = {record["instance_id"]: record for record in records}
    return {
        "schema_version": 1,
        "source": manifest_metadata.get("source"),
        "manifest": {"file": manifest_path.name, "sha256": _sha256(manifest_bytes)},
        "algorithm": {
            "name": "database_high_level_sha256_v1",
            "seed": seed,
            "unit": "analytical_question",
            "database_allocation": "Hamilton largest remainder",
            "within_database_stratum": "high_level",
            "within_stratum_order": "SHA-256(seed, database, high_level, instance_id)",
        },
        "counts": {"train": len(train_ids), "test": len(test_ids)},
        "artifacts": {
            "train_ids": {"file": "train_ids.txt", "sha256": _sha256(train_bytes)},
            "test_ids": {"file": "test_ids.txt", "sha256": _sha256(test_bytes)},
        },
        "distributions": {
            "overall": {
                "eligible": _condition_distribution(records),
                "train": _condition_distribution(
                    records_by_id[item] for item in train_ids
                ),
                "test": _condition_distribution(
                    records_by_id[item] for item in test_ids
                ),
            },
            "by_database": _database_distributions(by_database, train_ids, test_ids),
        },
    }


def create_split(
    manifest_dir: Path | str,
    *,
    train_size: int,
    test_size: int,
    seed: str,
) -> dict[str, Any]:
    """Create a database-first, high-level-balanced, keyed SHA-256 split."""

    if not isinstance(seed, str) or not seed:
        raise SplitError("seed must be a non-empty string")
    directory = Path(manifest_dir)
    manifest_path, manifest_bytes, records, manifest_metadata = _load_split_inputs(
        directory
    )
    if train_size + test_size != len(records):
        raise SplitError("train_size + test_size must equal manifest count")
    if (train_size, test_size) != (231, 101):
        raise SplitError("train_size must be 231 and test_size must be 101")

    by_database: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_database[record["selected_database"]].append(record)
    test_ids = _select_test_ids(by_database, test_size, seed)
    all_ids = {record["instance_id"] for record in records}
    train_ids = all_ids - test_ids
    if len(train_ids) != train_size or len(test_ids) != test_size:
        raise SplitError("internal split cardinality invariant failed")

    train_bytes = _ids_bytes(train_ids)
    test_bytes = _ids_bytes(test_ids)
    split_metadata = _build_split_metadata(
        manifest_path=manifest_path,
        manifest_bytes=manifest_bytes,
        manifest_metadata=manifest_metadata,
        records=records,
        train_ids=train_ids,
        test_ids=test_ids,
        seed=seed,
        train_bytes=train_bytes,
        test_bytes=test_bytes,
        by_database=by_database,
    )
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "train_ids.txt").write_bytes(train_bytes)
    (directory / "test_ids.txt").write_bytes(test_bytes)
    (directory / "split_metadata.json").write_bytes(
        _canonical_json(split_metadata, pretty=True)
    )
    return split_metadata


def _development_database_distributions(
    by_database: Mapping[str, list[dict[str, Any]]],
    dev_a_ids: set[str],
    dev_b_ids: set[str],
) -> dict[str, Any]:
    distributions: dict[str, Any] = {}
    for database, database_records in sorted(by_database.items()):
        dev_a_records = [
            record for record in database_records if record["instance_id"] in dev_a_ids
        ]
        dev_b_records = [
            record for record in database_records if record["instance_id"] in dev_b_ids
        ]
        distributions[database] = {
            "development": len(database_records),
            "dev_a": len(dev_a_records),
            "dev_b": len(dev_b_records),
            "high_level": {
                "development": sum(record["high_level"] for record in database_records),
                "dev_a": sum(record["high_level"] for record in dev_a_records),
                "dev_b": sum(record["high_level"] for record in dev_b_records),
            },
        }
    return distributions


def _order_balance_diagnostic(
    development_records: list[dict[str, Any]],
    dev_b_records: list[dict[str, Any]],
) -> dict[str, Any]:
    development_counts = Counter(
        str(record["conditions"]["order"]).lower() for record in development_records
    )
    dev_b_counts = Counter(
        str(record["conditions"]["order"]).lower() for record in dev_b_records
    )
    dev_b_size = len(dev_b_records)
    development_size = len(development_records)
    return {
        value: {
            "expected_dev_b": development_counts[value] * dev_b_size / development_size,
            "actual_dev_b": dev_b_counts[value],
            "absolute_deviation": abs(
                dev_b_counts[value]
                - development_counts[value] * dev_b_size / development_size
            ),
        }
        for value in ("false", "true")
    }


def _validate_outer_split(
    directory: Path,
    records: list[dict[str, Any]],
) -> tuple[bytes, set[str]]:
    train_bytes, train_ids = _read_ids_artifact(directory / "train_ids.txt")
    _, test_ids = _read_ids_artifact(directory / "test_ids.txt")
    split_metadata = _read_split_metadata(directory / "split_metadata.json")
    train_artifact = split_metadata.get("artifacts", {}).get("train_ids", {})
    if train_artifact.get("sha256") != _sha256(train_bytes):
        raise SplitError("train_ids.txt SHA-256 does not match split_metadata.json")
    all_ids = {record["instance_id"] for record in records}
    if train_ids & test_ids or train_ids | test_ids != all_ids:
        raise SplitError(
            "outer train/test ID artifacts are not disjoint and exhaustive"
        )
    if len(train_ids) != 231:
        raise SplitError("train_ids.txt must contain 231 development IDs")
    return train_bytes, train_ids


def create_development_split(
    manifest_dir: Path | str,
    *,
    dev_a_size: int,
    dev_b_size: int,
    seed: str,
) -> dict[str, Any]:
    """Split the frozen development partition into optimization and validation sets."""

    if not isinstance(seed, str) or not seed:
        raise SplitError("seed must be a non-empty string")
    directory = Path(manifest_dir)
    manifest_path, manifest_bytes, records, manifest_metadata = _load_split_inputs(
        directory
    )
    train_bytes, development_ids = _validate_outer_split(directory, records)
    if dev_a_size + dev_b_size != len(development_ids):
        raise SplitError(
            "dev_a_size + dev_b_size must equal the development partition count"
        )
    if (dev_a_size, dev_b_size) != (154, 77):
        raise SplitError("dev_a_size must be 154 and dev_b_size must be 77")

    development_records = [
        record for record in records if record["instance_id"] in development_ids
    ]
    by_database: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in development_records:
        by_database[record["selected_database"]].append(record)
    dev_b_ids = _select_test_ids(by_database, dev_b_size, seed)
    dev_a_ids = development_ids - dev_b_ids
    if len(dev_a_ids) != dev_a_size or len(dev_b_ids) != dev_b_size:
        raise SplitError("internal development split cardinality invariant failed")

    records_by_id = {record["instance_id"]: record for record in records}
    dev_a_records = [records_by_id[instance_id] for instance_id in dev_a_ids]
    dev_b_records = [records_by_id[instance_id] for instance_id in dev_b_ids]
    dev_a_bytes = _ids_bytes(dev_a_ids)
    dev_b_bytes = _ids_bytes(dev_b_ids)
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "source": manifest_metadata.get("source"),
        "manifest": {"file": manifest_path.name, "sha256": _sha256(manifest_bytes)},
        "source_partition": {
            "file": "train_ids.txt",
            "sha256": _sha256(train_bytes),
        },
        "algorithm": {
            "name": "development_database_high_level_sha256_v1",
            "seed": seed,
            "unit": "analytical_question",
            "primary_strata": ["selected_database", "high_level"],
            "database_allocation": "Hamilton largest remainder",
            "within_database_stratum": "high_level",
            "within_stratum_order": (
                "SHA-256(seed, database, high_level, instance_id)"
            ),
        },
        "counts": {
            "development": len(development_ids),
            "dev_a": len(dev_a_ids),
            "dev_b": len(dev_b_ids),
        },
        "artifacts": {
            "dev_a_ids": {"file": "dev_a_ids.txt", "sha256": _sha256(dev_a_bytes)},
            "dev_b_ids": {"file": "dev_b_ids.txt", "sha256": _sha256(dev_b_bytes)},
        },
        "distributions": {
            "overall": {
                "development": _condition_distribution(development_records),
                "dev_a": _condition_distribution(dev_a_records),
                "dev_b": _condition_distribution(dev_b_records),
            },
            "by_database": _development_database_distributions(
                by_database, dev_a_ids, dev_b_ids
            ),
        },
        "balance_diagnostics": {
            "conditions": {
                "order": _order_balance_diagnostic(development_records, dev_b_records)
            }
        },
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dev_a_ids.txt").write_bytes(dev_a_bytes)
    (directory / "dev_b_ids.txt").write_bytes(dev_b_bytes)
    (directory / "development_split_metadata.json").write_bytes(
        _canonical_json(metadata, pretty=True)
    )
    return metadata


def prepare_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and prepare public benchmark records"
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    metadata = prepare_public_manifest(
        args.input, args.output_dir, source_commit=args.source_commit
    )
    print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    return 0


def split_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create the preregistered question split"
    )
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument(
        "--seed",
        default=DEFAULT_SPLIT_SEED,
        help=f"deterministic split seed (default: {DEFAULT_SPLIT_SEED})",
    )
    parser.add_argument("--train-size", required=True, type=int)
    parser.add_argument("--test-size", required=True, type=int)
    args = parser.parse_args(argv)
    metadata = create_split(
        args.manifest_dir,
        train_size=args.train_size,
        test_size=args.test_size,
        seed=args.seed,
    )
    print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    return 0


def development_split_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Split development questions into optimization and validation sets"
    )
    parser.add_argument("--manifest-dir", required=True, type=Path)
    parser.add_argument(
        "--seed",
        default=DEFAULT_DEVELOPMENT_SPLIT_SEED,
        help=(
            "deterministic development split seed "
            f"(default: {DEFAULT_DEVELOPMENT_SPLIT_SEED})"
        ),
    )
    parser.add_argument("--dev-a-size", required=True, type=int)
    parser.add_argument("--dev-b-size", required=True, type=int)
    args = parser.parse_args(argv)
    metadata = create_development_split(
        args.manifest_dir,
        dev_a_size=args.dev_a_size,
        dev_b_size=args.dev_b_size,
        seed=args.seed,
    )
    print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    return 0

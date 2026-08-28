"""Prespecified public-only C1 schema-retrieval sensitivity arm."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping

from .baseline_batch import (
    BaselineAttempt,
    BaselineBatchError,
    BaselineSchedule,
    _parse_baseline_exclusions,
)
from .direct_public_search import MAX_SCHEMA_MATCHES, MAX_SCHEMA_PAYLOAD_BYTES
from .omni_probe_preflight import OmniProbePreflightError, committed_spec

DEFAULT_C1_RETRIEVAL_SENSITIVITY_SEED = "omni-livesqlbench-c1-retrieval-sensitivity-v1"
SENSITIVITY_QUESTION_COUNT = 20
SOURCE_BASELINE_COMMIT = "5be315e44bea7ee1a39500380dcbc4c05976dd3e"
SENSITIVITY_RUN_ID = "c1-retrieval-sensitivity-v1"
SENSITIVITY_OUTPUT_ROOT = Path(
    "experiments/autoresearch/raw/c1-retrieval-sensitivity-v1"
)
SENSITIVITY_MINIMUM_REMAINING_SECONDS = 1200
SENSITIVITY_LEGACY_BATCH_CAPACITY_USD = Decimal("1000000.000000")

_ELIGIBLE_PATH = Path("data/manifests/eligible_questions.jsonl")
_TRAIN_IDS_PATH = Path("data/manifests/train_ids.txt")
_EXCLUSIONS_PATH = Path("config/conditions/public-baseline-exclusions-v1.json")
_CONFIG_PATH = Path("config/conditions/c1-retrieval-sensitivity-v1.json")
_IDS_PATH = Path("data/manifests/c1_retrieval_sensitivity_ids.txt")
_METADATA_PATH = Path("data/manifests/c1_retrieval_sensitivity_metadata.json")
_PRESERVED_PATHS = {
    "c1_condition": Path("config/conditions/c1-direct-sql-v1.json"),
    "database_targets": Path("config/conditions/direct-database-targets-v1.json"),
    "direct_instructions": Path("config/instructions/direct-sql-v1.json"),
    "direct_prompt": Path("config/prompts/direct-sql-v1.txt"),
    "direct_runtime": Path("config/conditions/direct-runtime-v1.json"),
}


class C1RetrievalSensitivityError(BaselineBatchError):
    """Invalid or non-reproducible C1 retrieval sensitivity input."""


def validate_c1_retrieval_sensitivity_invocation(
    *,
    run_id: str,
    output_root: Path | None,
    cost_ceiling_usd: str,
    execute_live: bool,
    remaining_wall_clock_seconds: float | None,
    attempt_cost_ceiling_usd: float | None,
) -> None:
    """Bind the arm namespace and admit live launch only with enough time."""
    if run_id != SENSITIVITY_RUN_ID:
        raise C1RetrievalSensitivityError("sensitivity run ID is not the fixed ID")
    if output_root != SENSITIVITY_OUTPUT_ROOT:
        raise C1RetrievalSensitivityError(
            "sensitivity output root is not the fixed namespace"
        )
    try:
        supplied_capacity = Decimal(cost_ceiling_usd)
    except (InvalidOperation, TypeError) as error:
        raise C1RetrievalSensitivityError(
            "sensitivity legacy batch capacity is invalid"
        ) from error
    if supplied_capacity != SENSITIVITY_LEGACY_BATCH_CAPACITY_USD:
        raise C1RetrievalSensitivityError(
            "sensitivity requires the nonbinding legacy batch capacity"
        )
    if not execute_live:
        return
    if attempt_cost_ceiling_usd != 12.0:
        raise C1RetrievalSensitivityError(
            "sensitivity must preserve the evaluated-system attempt maximum"
        )
    if (
        isinstance(remaining_wall_clock_seconds, bool)
        or not isinstance(remaining_wall_clock_seconds, (int, float))
        or not math.isfinite(remaining_wall_clock_seconds)
        or remaining_wall_clock_seconds <= SENSITIVITY_MINIMUM_REMAINING_SECONDS
    ):
        raise C1RetrievalSensitivityError(
            "sensitivity launch requires projected full-arm time plus margin"
        )


def create_c1_retrieval_sensitivity_subset(workspace: Path) -> dict[str, Any]:
    """Regenerate the fixed 20-question public subset and diagnostics."""
    root = Path(workspace)
    configuration = _load_configuration((root / _CONFIG_PATH).read_bytes())
    ids_bytes, metadata = _build_selection(
        (root / _ELIGIBLE_PATH).read_bytes(),
        (root / _TRAIN_IDS_PATH).read_bytes(),
        (root / _EXCLUSIONS_PATH).read_bytes(),
        configuration,
    )
    manifest_directory = root / "data/manifests"
    manifest_directory.mkdir(parents=True, exist_ok=True)
    (root / _IDS_PATH).write_bytes(ids_bytes)
    (root / _METADATA_PATH).write_bytes(_canonical_json(metadata, pretty=True))
    return metadata


def load_committed_c1_retrieval_sensitivity_schedule(
    workspace: Path, commit: str, *, run_id: str
) -> BaselineSchedule:
    """Load the commit-bound C1-only schedule after deterministic regeneration."""
    try:
        root = Path(workspace).resolve(strict=True)
        eligible = committed_spec(root, commit, _ELIGIBLE_PATH)
        train = committed_spec(root, commit, _TRAIN_IDS_PATH)
        exclusions = committed_spec(root, commit, _EXCLUSIONS_PATH)
        configuration_spec = committed_spec(root, commit, _CONFIG_PATH)
        ids_spec = committed_spec(root, commit, _IDS_PATH)
        metadata_spec = committed_spec(root, commit, _METADATA_PATH)
        configuration = _load_configuration(configuration_spec.content)
        preserved_specs = {
            name: committed_spec(root, commit, path)
            for name, path in _PRESERVED_PATHS.items()
        }
        if {
            name: spec.sha256 for name, spec in preserved_specs.items()
        } != configuration["preserved_artifact_sha256"]:
            raise C1RetrievalSensitivityError(
                "sensitivity arm changed a preserved C1 artifact"
            )
        expected_ids, expected_metadata = _build_selection(
            eligible.content,
            train.content,
            exclusions.content,
            configuration,
        )
        if ids_spec.content != expected_ids:
            raise C1RetrievalSensitivityError(
                "committed sensitivity IDs do not regenerate"
            )
        if metadata_spec.content != _canonical_json(expected_metadata, pretty=True):
            raise C1RetrievalSensitivityError(
                "committed sensitivity metadata does not regenerate"
            )
        selection_ids = _parse_ids(
            ids_spec.content, expected=SENSITIVITY_QUESTION_COUNT
        )
        records = _parse_public_manifest(eligible.content)
        parsed_exclusions = _parse_baseline_exclusions(exclusions.content)
    except C1RetrievalSensitivityError:
        raise
    except (
        OSError,
        UnicodeError,
        OmniProbePreflightError,
        json.JSONDecodeError,
    ) as error:
        raise C1RetrievalSensitivityError(
            "committed C1 retrieval sensitivity inputs are unavailable"
        ) from error

    records_by_id = {record["instance_id"]: record for record in records}
    attempts = tuple(
        BaselineAttempt(
            condition="C1",
            database=records_by_id[instance_id]["selected_database"],
            instance_id=instance_id,
            repetition=1,
            run_id=run_id,
        )
        for instance_id in selection_ids
    )
    if len({attempt.database for attempt in attempts}) != 16:
        raise C1RetrievalSensitivityError(
            "C1 retrieval sensitivity must span 16 databases"
        )
    return BaselineSchedule(
        attempts=attempts,
        eligible_manifest_sha256=eligible.sha256,
        source_commit=commit,
        train_ids_sha256=ids_spec.sha256,
        exclusion_manifest_sha256=exclusions.sha256,
        exclusions=parsed_exclusions,
    )


def _build_selection(
    eligible_bytes: bytes,
    train_bytes: bytes,
    exclusion_bytes: bytes,
    configuration: Mapping[str, Any],
) -> tuple[bytes, dict[str, Any]]:
    records = _parse_public_manifest(eligible_bytes)
    train_ids = set(_parse_ids(train_bytes, expected=231))
    records_by_id = {record["instance_id"]: record for record in records}
    if not train_ids.issubset(records_by_id):
        raise C1RetrievalSensitivityError(
            "training IDs are missing from the public manifest"
        )
    exclusions = _parse_baseline_exclusions(exclusion_bytes)
    excluded_databases = {item.database for item in exclusions}
    if len(excluded_databases) != 2:
        raise C1RetrievalSensitivityError(
            "sensitivity arm requires the two frozen baseline exclusions"
        )
    candidates = [
        records_by_id[instance_id]
        for instance_id in train_ids
        if records_by_id[instance_id]["selected_database"] not in excluded_databases
    ]
    by_database: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in candidates:
        by_database[record["selected_database"]].append(record)
    if len(by_database) != 16:
        raise C1RetrievalSensitivityError(
            "sensitivity candidates must span 16 databases"
        )

    database_targets = _allocate_database_targets(
        {database: len(values) for database, values in by_database.items()},
        SENSITIVITY_QUESTION_COUNT,
    )
    selected: list[dict[str, Any]] = []
    for database, database_records in sorted(by_database.items()):
        strata = {
            value: [
                record for record in database_records if record["high_level"] is value
            ]
            for value in (False, True)
        }
        counts = {key: len(values) for key, values in strata.items() if values}
        targets = _allocate_proportionally(counts, database_targets[database])
        for high_level, count in sorted(targets.items()):
            ordered = sorted(
                strata[high_level],
                key=lambda record: _keyed_order(
                    record, DEFAULT_C1_RETRIEVAL_SENSITIVITY_SEED
                ),
            )
            selected.extend(ordered[:count])
    if len(selected) != SENSITIVITY_QUESTION_COUNT:
        raise C1RetrievalSensitivityError("sensitivity selection has the wrong size")

    ids_bytes = _ids_bytes(record["instance_id"] for record in selected)
    metadata = {
        "algorithm": {
            "database_allocation": (
                "one-per-database minimum then quota-remainder allocation"
            ),
            "name": "database_high_level_sha256_sensitivity_v1",
            "seed": DEFAULT_C1_RETRIEVAL_SENSITIVITY_SEED,
            "unit": "public_development_question",
            "within_database_stratum": "high_level",
            "within_stratum_order": (
                "SHA-256(seed, database, high_level, instance_id)"
            ),
        },
        "artifacts": {
            "selected_ids": {
                "file": _IDS_PATH.name,
                "sha256": _sha256(ids_bytes),
            }
        },
        "counts": {
            "candidate_databases": len(by_database),
            "candidate_questions": len(candidates),
            "selected_databases": len(
                {record["selected_database"] for record in selected}
            ),
            "selected_questions": len(selected),
        },
        "distributions": {
            "by_database": {
                database: {
                    "candidate": len(database_records),
                    "candidate_high_level": sum(
                        record["high_level"] for record in database_records
                    ),
                    "selected": sum(
                        record["selected_database"] == database for record in selected
                    ),
                    "selected_high_level": sum(
                        record["selected_database"] == database and record["high_level"]
                        for record in selected
                    ),
                }
                for database, database_records in sorted(by_database.items())
            },
            "overall": {
                "candidate": _distribution(candidates),
                "selected": _distribution(selected),
            },
        },
        "excluded_databases": sorted(excluded_databases),
        "kind": "c1-retrieval-sensitivity-subset",
        "schema_version": 1,
        "source": {
            "eligible_manifest": {
                "file": _ELIGIBLE_PATH.name,
                "sha256": _sha256(eligible_bytes),
            },
            "public_baseline_exclusions": {
                "file": _EXCLUSIONS_PATH.name,
                "sha256": _sha256(exclusion_bytes),
            },
            "source_baseline_commit": configuration["source_baseline_commit"],
            "train_ids": {
                "file": _TRAIN_IDS_PATH.name,
                "sha256": _sha256(train_bytes),
            },
        },
    }
    return ids_bytes, metadata


def _load_configuration(content: bytes) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise C1RetrievalSensitivityError(
            "C1 retrieval sensitivity configuration is invalid"
        ) from error
    expected = {
        "baseline_max_schema_matches": 4,
        "condition": "C1",
        "kind": "c1-schema-retrieval-sensitivity",
        "launch_margin_seconds": 600,
        "legacy_batch_capacity_usd": "1000000.000000",
        "maximum_schema_payload_bytes": 64 * 1024,
        "minimum_remaining_wall_clock_seconds": (SENSITIVITY_MINIMUM_REMAINING_SECONDS),
        "notional_maximum_cost_usd": "240.000000",
        "output_root": SENSITIVITY_OUTPUT_ROOT.as_posix(),
        "preserved_artifact_sha256": {
            "c1_condition": (
                "59e3aaabcb75d5080c956c8c52d923f6dec4b754507299c37b9c1b7857fb9b1c"
            ),
            "database_targets": (
                "1eeaec61d5f2f871b01f85d865d345a368ee0b137310d5d0700f07244487434a"
            ),
            "direct_instructions": (
                "0729cd488f90031c0bb196436ac1d59cb303c0f1e8b46a207c94b690548c3d0e"
            ),
            "direct_prompt": (
                "6ab836dd048ff99665d24fabd4de351c8a393a602bac07e5889bb10a29037e57"
            ),
            "direct_runtime": (
                "21cfc382ae24020d4a85c11de752dc2a1c59578ce07f9bccc98647f7eafca2d4"
            ),
        },
        "preserved_budget_id": "direct-sql-public-baseline-v1",
        "question_count": SENSITIVITY_QUESTION_COUNT,
        "projected_full_arm_wall_clock_seconds": 600,
        "remaining_wall_clock_rule": "strictly_greater_than_minimum",
        "run_id": SENSITIVITY_RUN_ID,
        "schema_version": 1,
        "sensitivity_max_schema_matches": 8,
        "source_baseline_commit": SOURCE_BASELINE_COMMIT,
    }
    if value != expected:
        raise C1RetrievalSensitivityError(
            "C1 retrieval sensitivity configuration is invalid"
        )
    if (
        MAX_SCHEMA_MATCHES != value["sensitivity_max_schema_matches"]
        or MAX_SCHEMA_PAYLOAD_BYTES != value["maximum_schema_payload_bytes"]
    ):
        raise C1RetrievalSensitivityError(
            "runtime schema retrieval does not match sensitivity configuration"
        )
    return value


def _parse_public_manifest(content: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in content.decode("utf-8").splitlines():
        value = json.loads(line)
        if (
            not isinstance(value, dict)
            or value.get("category") != "Query"
            or not isinstance(value.get("instance_id"), str)
            or not isinstance(value.get("selected_database"), str)
            or not isinstance(value.get("high_level"), bool)
            or not isinstance(value.get("conditions"), dict)
            or value["instance_id"] in seen
        ):
            raise C1RetrievalSensitivityError("public manifest is invalid")
        seen.add(value["instance_id"])
        records.append(value)
    if not records:
        raise C1RetrievalSensitivityError("public manifest is empty")
    return records


def _parse_ids(content: bytes, *, expected: int) -> tuple[str, ...]:
    ids = tuple(content.decode("utf-8").splitlines())
    if (
        len(ids) != expected
        or len(set(ids)) != len(ids)
        or any(not item for item in ids)
    ):
        raise C1RetrievalSensitivityError("public ID artifact is invalid")
    return ids


def _allocate_database_targets(
    counts: Mapping[str, int], allocation: int
) -> dict[str, int]:
    if allocation < len(counts) or allocation > sum(counts.values()):
        raise C1RetrievalSensitivityError("database allocation is infeasible")
    total = sum(counts.values())
    quotas = {
        database: Fraction(allocation * count, total)
        for database, count in counts.items()
    }
    allocated = {database: 1 for database in counts}
    remaining = allocation - len(allocated)
    ranked = sorted(
        counts,
        key=lambda database: (-(quotas[database] - allocated[database]), database),
    )
    while remaining:
        progressed = False
        for database in ranked:
            if allocated[database] >= counts[database]:
                continue
            allocated[database] += 1
            remaining -= 1
            progressed = True
            if not remaining:
                break
        if not progressed:
            raise C1RetrievalSensitivityError("database allocation is infeasible")
    return allocated


def _allocate_proportionally(
    counts: Mapping[bool, int], allocation: int
) -> dict[bool, int]:
    total = sum(counts.values())
    if not counts or allocation < 0 or allocation > total:
        raise C1RetrievalSensitivityError("high-level allocation is infeasible")
    quotas = {key: Fraction(allocation * count, total) for key, count in counts.items()}
    allocated = {
        key: quota.numerator // quota.denominator for key, quota in quotas.items()
    }
    remaining = allocation - sum(allocated.values())
    for key in sorted(
        counts, key=lambda item: (-(quotas[item] - allocated[item]), item)
    )[:remaining]:
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
    ).encode()
    return hashlib.sha256(material).hexdigest(), record["instance_id"]


def _distribution(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = tuple(records)
    return {
        "conditions": {
            "decimal": dict(
                sorted(
                    Counter(
                        str(record["conditions"]["decimal"]) for record in values
                    ).items(),
                    key=lambda item: int(item[0]),
                )
            ),
            "distinct": dict(
                sorted(
                    Counter(
                        str(record["conditions"]["distinct"]).lower()
                        for record in values
                    ).items()
                )
            ),
            "order": dict(
                sorted(
                    Counter(
                        str(record["conditions"]["order"]).lower() for record in values
                    ).items()
                )
            ),
        },
        "count": len(values),
        "high_level": dict(
            sorted(
                Counter(str(record["high_level"]).lower() for record in values).items()
            )
        ),
    }


def _ids_bytes(ids: Iterable[str]) -> bytes:
    return "".join(f"{instance_id}\n" for instance_id in sorted(ids)).encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: Any, *, pretty: bool) -> bytes:
    options = {"ensure_ascii": False, "sort_keys": True}
    text = (
        json.dumps(value, indent=2, **options)
        if pretty
        else json.dumps(value, separators=(",", ":"), **options)
    )
    return (text + "\n").encode()

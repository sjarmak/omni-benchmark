"""Deterministically derive the public-only C4 product and paired-analysis arms."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")


class C4BaselineArmError(ValueError):
    """Raised when the public arm specification or source data is inconsistent."""


@dataclass(frozen=True, slots=True)
class DeploymentReference:
    claim_path: Path
    claim_sha256: str
    record_sha256: tuple[tuple[str, str], ...]
    record_root: Path
    run_id: str


@dataclass(frozen=True, slots=True)
class C4BaselineArmSpec:
    databases: tuple[str, ...]
    deployment: DeploymentReference
    eligible_manifest_path: Path
    full_ids_path: Path
    metadata_path: Path
    paired_databases: tuple[str, ...]
    paired_ids_path: Path
    paired_target_count: int
    seed: None
    target_count: int
    train_ids_path: Path


@dataclass(frozen=True, slots=True)
class RenderedC4BaselineArm:
    full_ids: tuple[str, ...]
    full_ids_bytes: bytes
    metadata_bytes: bytes
    paired_ids: tuple[str, ...]
    paired_ids_bytes: bytes
    spec: C4BaselineArmSpec


def render_c4_baseline_arm(workspace: Path, spec_path: Path) -> RenderedC4BaselineArm:
    """Render both arms from public manifest rows without outcome information."""
    root = workspace.resolve(strict=True)
    spec_bytes = _read(root, spec_path)
    spec = parse_c4_baseline_arm_spec(spec_bytes)
    train_bytes = _read(root, spec.train_ids_path)
    eligible_bytes = _read(root, spec.eligible_manifest_path)
    train_ids = _parse_train_ids(train_bytes)
    records = _parse_eligible(eligible_bytes)
    missing = tuple(
        instance_id for instance_id in train_ids if instance_id not in records
    )
    if missing:
        raise C4BaselineArmError("train IDs are absent from the eligible manifest")

    full_ids = _ordered_ids(train_ids, records, spec.databases)
    paired_ids = _ordered_ids(train_ids, records, spec.paired_databases)
    if len(full_ids) != spec.target_count:
        raise C4BaselineArmError("C4 product arm count differs from the specification")
    if len(paired_ids) != spec.paired_target_count:
        raise C4BaselineArmError("C4 paired arm count differs from the specification")
    if not set(paired_ids).issubset(full_ids):
        raise C4BaselineArmError("paired arm must be a subset of the product arm")

    full_bytes = _ids_bytes(full_ids)
    paired_bytes = _ids_bytes(paired_ids)
    metadata = {
        "allocation": _allocation(full_ids, records, spec.databases),
        "databases": list(spec.databases),
        "full_ids_sha256": _sha256(full_bytes),
        "kind": "public-c4-baseline-arm-metadata",
        "ordering": "selected_database_then_train_manifest_order",
        "paired_allocation": _allocation(paired_ids, records, spec.paired_databases),
        "paired_databases": list(spec.paired_databases),
        "paired_ids_sha256": _sha256(paired_bytes),
        "paired_selected_count": len(paired_ids),
        "schema_version": 1,
        "seed": None,
        "selected_count": len(full_ids),
        "selection": "all_public_train_questions_for_selected_databases",
        "source": {
            "eligible_manifest_path": spec.eligible_manifest_path.as_posix(),
            "eligible_manifest_sha256": _sha256(eligible_bytes),
            "spec_path": spec_path.as_posix(),
            "spec_sha256": _sha256(spec_bytes),
            "train_ids_path": spec.train_ids_path.as_posix(),
            "train_ids_sha256": _sha256(train_bytes),
        },
    }
    return RenderedC4BaselineArm(
        full_ids=full_ids,
        full_ids_bytes=full_bytes,
        metadata_bytes=_canonical_json(metadata),
        paired_ids=paired_ids,
        paired_ids_bytes=paired_bytes,
        spec=spec,
    )


def write_c4_baseline_arm(workspace: Path, spec_path: Path) -> RenderedC4BaselineArm:
    """Write regenerated public artifacts at paths fixed by the specification."""
    rendered = render_c4_baseline_arm(workspace, spec_path)
    root = workspace.resolve(strict=True)
    for path, content in (
        (rendered.spec.full_ids_path, rendered.full_ids_bytes),
        (rendered.spec.paired_ids_path, rendered.paired_ids_bytes),
        (rendered.spec.metadata_path, rendered.metadata_bytes),
    ):
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return rendered


def parse_c4_baseline_arm_spec(content: bytes) -> C4BaselineArmSpec:
    """Parse the exact public C4 arm and frozen deployment-reference schema."""
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise C4BaselineArmError("C4 arm specification is invalid") from error
    expected = {
        "databases",
        "deployment",
        "eligible_manifest_path",
        "full_ids_path",
        "kind",
        "metadata_path",
        "ordering",
        "paired_databases",
        "paired_ids_path",
        "paired_target_count",
        "schema_version",
        "seed",
        "selection",
        "target_count",
        "train_ids_path",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("kind") != "public-c4-baseline-arm"
        or value.get("schema_version") != 1
        or value.get("seed") is not None
        or value.get("selection") != "all_public_train_questions_for_selected_databases"
        or value.get("ordering") != "selected_database_then_train_manifest_order"
    ):
        raise C4BaselineArmError("C4 arm specification is unsupported")
    databases = _databases(value["databases"], "databases")
    paired = _databases(value["paired_databases"], "paired databases")
    if not set(paired).issubset(databases):
        raise C4BaselineArmError("paired databases must be a subset")
    deployment = _deployment(value["deployment"])
    if tuple(database for database, _ in deployment.record_sha256) != databases:
        raise C4BaselineArmError(
            "deployment record digests must cover the selected databases"
        )
    target = _positive_count(value["target_count"], "target count")
    paired_target = _positive_count(value["paired_target_count"], "paired target count")
    return C4BaselineArmSpec(
        databases=databases,
        deployment=deployment,
        eligible_manifest_path=_relative_path(
            value["eligible_manifest_path"], "eligible manifest path"
        ),
        full_ids_path=_relative_path(value["full_ids_path"], "full IDs path"),
        metadata_path=_relative_path(value["metadata_path"], "metadata path"),
        paired_databases=paired,
        paired_ids_path=_relative_path(value["paired_ids_path"], "paired IDs path"),
        paired_target_count=paired_target,
        seed=None,
        target_count=target,
        train_ids_path=_relative_path(value["train_ids_path"], "train IDs path"),
    )


def _deployment(value: object) -> DeploymentReference:
    if not isinstance(value, dict) or set(value) != {
        "claim_path",
        "claim_sha256",
        "record_sha256",
        "record_root",
        "run_id",
    }:
        raise C4BaselineArmError("deployment reference is invalid")
    digest = value["claim_sha256"]
    record_digests = value["record_sha256"]
    run_id = value["run_id"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise C4BaselineArmError("deployment claim digest is invalid")
    if not isinstance(run_id, str) or _IDENTIFIER.fullmatch(run_id) is None:
        raise C4BaselineArmError("deployment run ID is invalid")
    if not isinstance(record_digests, dict) or not record_digests:
        raise C4BaselineArmError("deployment record digests are invalid")
    parsed_record_digests = tuple(sorted(record_digests.items()))
    if any(
        not isinstance(database, str)
        or _IDENTIFIER.fullmatch(database) is None
        or not isinstance(record_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", record_digest) is None
        for database, record_digest in parsed_record_digests
    ):
        raise C4BaselineArmError("deployment record digests are invalid")
    return DeploymentReference(
        claim_path=_relative_path(value["claim_path"], "deployment claim path"),
        claim_sha256=digest,
        record_sha256=parsed_record_digests,
        record_root=_relative_path(value["record_root"], "deployment record root"),
        run_id=run_id,
    )


def _databases(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise C4BaselineArmError(f"{name} are invalid")
    selected = tuple(value)
    if (
        any(
            not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None
            for item in selected
        )
        or tuple(sorted(set(selected))) != selected
    ):
        raise C4BaselineArmError(f"{name} must be unique and sorted")
    return selected


def _positive_count(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise C4BaselineArmError(f"{name} is invalid")
    return value


def _relative_path(value: object, name: str) -> Path:
    if not isinstance(value, str):
        raise C4BaselineArmError(f"{name} is invalid")
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise C4BaselineArmError(f"{name} must be repository-relative")
    return path


def _read(root: Path, path: Path) -> bytes:
    try:
        candidate = (root / path).resolve(strict=True)
        if not candidate.is_relative_to(root) or not candidate.is_file():
            raise OSError
        return candidate.read_bytes()
    except OSError as error:
        raise C4BaselineArmError(f"public source is unavailable: {path}") from error


def _parse_train_ids(content: bytes) -> tuple[str, ...]:
    values = tuple(content.decode("utf-8").splitlines())
    if (
        len(values) != 231
        or len(set(values)) != len(values)
        or any(_IDENTIFIER.fullmatch(value) is None for value in values)
    ):
        raise C4BaselineArmError("train IDs are invalid")
    return values


def _parse_eligible(content: bytes) -> dict[str, tuple[str, bool]]:
    records: dict[str, tuple[str, bool]] = {}
    try:
        for line in content.decode("utf-8").splitlines():
            value = json.loads(line)
            instance_id = value["instance_id"]
            database = value["selected_database"]
            high_level = value["high_level"]
            if (
                value.get("category") != "Query"
                or not isinstance(instance_id, str)
                or not isinstance(database, str)
                or type(high_level) is not bool
                or instance_id in records
            ):
                raise C4BaselineArmError("eligible manifest row is invalid")
            records[instance_id] = (database, high_level)
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
        raise C4BaselineArmError("eligible manifest is invalid") from error
    return records


def _ordered_ids(
    train_ids: tuple[str, ...],
    records: Mapping[str, tuple[str, bool]],
    databases: tuple[str, ...],
) -> tuple[str, ...]:
    source_order = {instance_id: index for index, instance_id in enumerate(train_ids)}
    selected = [
        instance_id for instance_id in train_ids if records[instance_id][0] in databases
    ]
    return tuple(
        sorted(
            selected,
            key=lambda instance_id: (
                records[instance_id][0],
                source_order[instance_id],
            ),
        )
    )


def _allocation(
    ids: tuple[str, ...],
    records: Mapping[str, tuple[str, bool]],
    databases: tuple[str, ...],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for database in databases:
        positions = [
            index
            for index, instance_id in enumerate(ids, start=1)
            if records[instance_id][0] == database
        ]
        levels = Counter(
            records[instance_id][1]
            for instance_id in ids
            if records[instance_id][0] == database
        )
        result.append(
            {
                "database": database,
                "first_ordinal": min(positions),
                "high_level": {
                    "false": levels[False],
                    "true": levels[True],
                },
                "last_ordinal": max(positions),
                "selected_count": len(positions),
            }
        )
    return result


def _ids_bytes(ids: tuple[str, ...]) -> bytes:
    return ("\n".join(ids) + "\n").encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode()


def c4_baseline_arm_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path("config/conditions/c4-public-baseline-arm-v1.json"),
    )
    arguments = parser.parse_args(argv)
    rendered = write_c4_baseline_arm(arguments.workspace, arguments.spec)
    print(
        json.dumps(
            {
                "full_count": len(rendered.full_ids),
                "full_ids_sha256": _sha256(rendered.full_ids_bytes),
                "paired_count": len(rendered.paired_ids),
                "paired_ids_sha256": _sha256(rendered.paired_ids_bytes),
            },
            sort_keys=True,
        )
    )
    return 0

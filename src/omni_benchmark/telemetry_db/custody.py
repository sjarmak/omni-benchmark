"""Custody gates applied to every value before it reaches the telemetry database."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..autoresearch_config import MANDATORY_FORBIDDEN_FIELDS, _find_forbidden
from ..custody import CustodyError, read_id_file

FORBIDDEN_FIELDS = MANDATORY_FORBIDDEN_FIELDS
TEST_IDS_FILENAME = "test_ids.txt"
DEV_A_IDS_FILENAME = "dev_a_ids.txt"
DEV_B_IDS_FILENAME = "dev_b_ids.txt"


class CustodyViolation(ValueError):
    """Raised when a load would carry hidden or sealed benchmark material."""


@dataclass(frozen=True)
class SplitIds:
    """Public instance IDs of the two splits the loader may name per attempt."""

    dev_a: frozenset[str]
    test: frozenset[str]


def reject_forbidden_fields(value: Any, context: str) -> None:
    """Raise CustodyViolation when a forbidden key appears at any nesting depth."""
    found = _find_forbidden(value, FORBIDDEN_FIELDS)
    if found is not None:
        raise CustodyViolation(f"{context}: forbidden field {found!r} is present")


def _read_ids(path: Path, label: str) -> frozenset[str]:
    try:
        ids = read_id_file(path)
    except CustodyError as error:
        raise CustodyViolation(
            f"cannot load {label} IDs from {path}: {error}"
        ) from error
    return frozenset(ids)


def load_test_ids(manifests_dir: Path) -> frozenset[str]:
    """Read the sealed test instance IDs; the IDs themselves are public."""
    return _read_ids(Path(manifests_dir) / TEST_IDS_FILENAME, "test")


def load_split_ids(manifests_dir: Path) -> SplitIds:
    """Read the dev-A and test ID files, which must not overlap."""
    split = SplitIds(
        dev_a=_read_ids(Path(manifests_dir) / DEV_A_IDS_FILENAME, "dev-A"),
        test=load_test_ids(manifests_dir),
    )
    overlap = sorted(split.dev_a & split.test)
    if overlap:
        raise CustodyViolation(
            f"{manifests_dir}: instances in both dev-A and test splits: {overlap}"
        )
    return split


def assert_not_test_instance(
    instance_id: str, test_ids: frozenset[str], context: str
) -> None:
    """Raise CustodyViolation when the instance belongs to the sealed test split."""
    if instance_id in test_ids:
        raise CustodyViolation(
            f"{context}: instance {instance_id!r} is in the sealed test split"
        )


def assert_dev_a_instance(instance_id: str, split: SplitIds, context: str) -> None:
    """Raise CustodyViolation unless the instance is in the dev-A split."""
    assert_not_test_instance(instance_id, split.test, context)
    if instance_id not in split.dev_a:
        raise CustodyViolation(
            f"{context}: instance {instance_id!r} is not in the dev-A split"
        )

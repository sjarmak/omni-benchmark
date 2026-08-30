"""Generate the sealed trial schedule from committed identity-only inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .autoresearch_config import AutoresearchError, _write_exclusive
from .content_policy import ContentPolicy
from .freeze_b import (
    CONDITIONS,
    QUESTION_COUNT,
    SCHEDULE_ALGORITHM,
    expected_test_output_count,
    schedule_sha256,
)
from .freeze_b_record import (
    FreezeBRecordError,
    _committed_input,
    _current_exact_commit,
    _relative_path,
    _repository_root,
    _verify_runtime_sources,
)

TEST_IDS_PATH = "data/manifests/test_ids.txt"
ATTEMPT_NAMESPACE = "sealed"
MIN_REPETITION_BLOCK_GAP = 98
MAX_TEST_IDS_BYTES = 64 * 1024

_SEED = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}")
_INSTANCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")
_DOMAIN = b"omni-livesqlbench-large-v1-sealed-schedule-v1"


class FreezeBScheduleError(RuntimeError):
    """Raised when the identity-only sealed schedule cannot be created safely."""


@dataclass(frozen=True)
class FreezeBScheduleResult:
    """Non-sensitive metadata for one exclusively written sealed schedule."""

    path: Path
    system_commit: str
    question_count: int
    attempt_count: int
    test_ids_sha256: str
    schedule_sha256: str
    file_sha256: str


def generate_freeze_b_schedule(
    workspace: Path,
    *,
    system_commit: str,
    seed: str,
    destination: Path,
    test_ids_path: Path = Path(TEST_IDS_PATH),
    question_count: int = QUESTION_COUNT,
) -> FreezeBScheduleResult:
    """Write one deterministic schedule without reading question content or labels."""
    try:
        root = _repository_root(workspace)
        commit = _current_exact_commit(root, system_commit)
        _verify_runtime_sources(root, commit)
        ids_relative = _relative_path(test_ids_path, "test IDs path")
        committed_ids = _committed_input(
            root,
            commit,
            ids_relative,
            maximum_bytes=MAX_TEST_IDS_BYTES,
        )
        instance_ids, records, content = _schedule_components(
            committed_ids.content, seed, question_count=question_count
        )
        destination_path = Path(_relative_path(destination, "destination path"))
        output = _write_exclusive(destination_path, content, workspace=root)
    except (FreezeBRecordError, AutoresearchError) as error:
        raise FreezeBScheduleError(str(error)) from error
    attempt_ids = tuple(str(record["attempt_id"]) for record in records)
    return FreezeBScheduleResult(
        path=output,
        system_commit=commit,
        question_count=len(instance_ids),
        attempt_count=len(records),
        test_ids_sha256=committed_ids.sha256,
        schedule_sha256=schedule_sha256(attempt_ids),
        file_sha256=hashlib.sha256(content).hexdigest(),
    )


def expected_schedule_bytes(
    committed_test_ids: bytes,
    seed: str,
    *,
    question_count: int = QUESTION_COUNT,
) -> bytes:
    """Return the canonical registered schedule for one committed ID blob and seed."""
    return _schedule_components(
        committed_test_ids, seed, question_count=question_count
    )[2]


def _schedule_components(
    committed_test_ids: bytes,
    seed: str,
    *,
    question_count: int = QUESTION_COUNT,
) -> tuple[tuple[str, ...], tuple[dict[str, object], ...], bytes]:
    approved_seed = _approved_seed(seed)
    instance_ids = _committed_test_ids(committed_test_ids, question_count)
    records = _ordered_records(instance_ids, approved_seed)
    content = b"".join(_canonical_bytes(record) for record in records)
    return instance_ids, records, content


def _approved_seed(value: object) -> str:
    if (
        not isinstance(value, str)
        or _SEED.fullmatch(value) is None
        or not ContentPolicy.from_environment(os.environ).identifier_is_safe(value)
    ):
        raise FreezeBScheduleError("schedule seed is invalid")
    return value


def _committed_test_ids(content: bytes, question_count: int) -> tuple[str, ...]:
    lines = content.splitlines(keepends=True)
    if not lines or any(not line.endswith(b"\n") or line == b"\n" for line in lines):
        raise FreezeBScheduleError(
            "committed test identities must be non-empty and newline-terminated"
        )
    try:
        instance_ids = tuple(line[:-1].decode("utf-8") for line in lines)
    except UnicodeDecodeError as error:
        raise FreezeBScheduleError(
            "committed test identities must be valid UTF-8"
        ) from error
    policy = ContentPolicy.from_environment(os.environ)
    if any(
        _INSTANCE_ID.fullmatch(instance_id) is None
        or not policy.identifier_is_safe(instance_id)
        for instance_id in instance_ids
    ):
        raise FreezeBScheduleError("committed test identity is invalid")
    if type(question_count) is not int or question_count <= 0:
        raise FreezeBScheduleError("question_count must be a positive integer")
    if len(instance_ids) != question_count:
        raise FreezeBScheduleError(
            f"committed test manifest must contain exactly {question_count} IDs"
        )
    if len(set(instance_ids)) != len(instance_ids):
        raise FreezeBScheduleError("committed test manifest contains a duplicate ID")
    if tuple(sorted(instance_ids)) != instance_ids:
        raise FreezeBScheduleError("committed test identities must be sorted")
    return instance_ids


def _ordered_records(
    instance_ids: tuple[str, ...], seed: str
) -> tuple[dict[str, object], ...]:
    question_count = len(instance_ids)
    offsets = (0, (question_count + 2) // 3, (2 * question_count) // 3)
    question_order = sorted(
        instance_ids,
        key=lambda instance_id: _order_key(seed, "question", instance_id),
    )
    records: list[dict[str, object]] = []
    for position in range(question_count):
        for repetition, offset in enumerate(offsets, start=1):
            instance_id = question_order[(position + offset) % question_count]
            condition_order = sorted(
                CONDITIONS,
                key=lambda condition: _order_key(
                    seed,
                    "condition",
                    instance_id,
                    str(repetition),
                    condition,
                ),
            )
            records.extend(
                {
                    "attempt_id": (
                        f"{ATTEMPT_NAMESPACE}:{instance_id}:{condition}:{repetition}"
                    ),
                    "condition": condition,
                    "instance_id": instance_id,
                    "repetition": repetition,
                }
                for condition in condition_order
            )
    if len(records) != expected_test_output_count(question_count):
        raise FreezeBScheduleError("sealed schedule construction is incomplete")
    return tuple(records)


def _order_key(seed: str, *parts: str) -> bytes:
    digest = hashlib.sha256()
    digest.update(_DOMAIN)
    digest.update(b"\0")
    digest.update(seed.encode("utf-8"))
    for part in parts:
        digest.update(b"\0")
        digest.update(part.encode("utf-8"))
    return digest.digest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate the identity-only Freeze-B schedule from the exact committed "
            f"{TEST_IDS_PATH} manifest using {SCHEDULE_ALGORITHM}"
        )
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--test-ids", type=Path, default=Path(TEST_IDS_PATH))
    parser.add_argument("--question-count", type=int, default=QUESTION_COUNT)
    return parser


def schedule_main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = generate_freeze_b_schedule(
        arguments.workspace,
        system_commit=arguments.system_commit,
        seed=arguments.seed,
        destination=arguments.destination,
        test_ids_path=arguments.test_ids,
        question_count=arguments.question_count,
    )
    print(
        json.dumps(
            {
                "attempt_count": result.attempt_count,
                "question_count": result.question_count,
                "schedule_file_sha256": result.file_sha256,
                "schedule_sha256": result.schedule_sha256,
                "system_commit": result.system_commit,
                "test_ids_sha256": result.test_ids_sha256,
            },
            sort_keys=True,
        )
    )
    return 0

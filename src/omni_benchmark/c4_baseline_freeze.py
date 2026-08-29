"""Freeze one complete public C4 arm without reading correctness labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .artifact_store import MAX_ARTIFACT_BYTES
from .autoresearch_config import AutoresearchError, _write_exclusive
from .baseline_batch import (
    BaselineBatchError,
    BaselineSchedule,
    ImmutableAttemptRepository,
    c4_public_baseline_schedule,
    load_committed_baseline_schedule,
)
from .run_quarantine import is_quarantined_run


RAW_ROOT = Path("experiments/autoresearch/raw")
STATE_ROOT = Path("experiments/autoresearch/state")
SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_C4_ARTIFACT_NAMES = frozenset(
    {
        "answer.result.json",
        "attempt.trace.jsonl",
        "generation.jsonl",
        "response-shape.json",
        "run.json",
    }
)


class C4BaselineFreezeError(RuntimeError):
    """Safe failure before a C4 run can be treated as scoreable evidence."""


def c4_baseline_freeze_entrypoint() -> int:
    """Run the CLI without exposing artifact content or a traceback."""
    try:
        return c4_baseline_freeze_main()
    except C4BaselineFreezeError as error:
        print(f"C4 baseline freeze failed: {error}", file=sys.stderr)
    except Exception:
        print("C4 baseline freeze failed: internal freeze error", file=sys.stderr)
    return 1


def c4_baseline_freeze_main(argv: Sequence[str] | None = None) -> int:
    """Derive the committed arm, verify its identity, and freeze it."""
    arguments = _parser().parse_args(argv)
    root = _workspace(arguments.workspace)
    try:
        full_schedule = load_committed_baseline_schedule(
            root, arguments.system_commit, run_id=arguments.run_id
        )
        schedule = c4_public_baseline_schedule(
            root, arguments.system_commit, full_schedule
        )
    except BaselineBatchError as error:
        raise C4BaselineFreezeError(str(error)) from error
    if (
        len(schedule.attempts) != 129
        or len({attempt.database for attempt in schedule.attempts}) != 10
        or schedule.sha256 != arguments.expected_schedule_sha256
    ):
        raise C4BaselineFreezeError("committed C4 schedule identity is invalid")
    receipt = freeze_c4_baseline_selection(
        root,
        schedule=schedule,
        output_root=arguments.output_root,
        destination=arguments.destination,
        expected_execution_plan_sha256=arguments.expected_execution_plan_sha256,
        expected_deployment_sha256=arguments.expected_deployment_sha256,
    )
    print(json.dumps(receipt, allow_nan=False, separators=(",", ":"), sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-schedule-sha256", required=True)
    parser.add_argument("--expected-execution-plan-sha256", required=True)
    parser.add_argument("--expected-deployment-sha256", required=True)
    return parser


def freeze_c4_baseline_selection(
    workspace: Path,
    *,
    schedule: BaselineSchedule,
    output_root: Path,
    destination: Path,
    expected_execution_plan_sha256: str,
    expected_deployment_sha256: str,
) -> dict[str, Any]:
    """Reconcile and freeze every scheduled C4 attempt exactly once."""
    root = _workspace(workspace)
    run_id = _validate_identity(
        schedule,
        output_root=Path(output_root),
        destination=Path(destination),
    )
    execution_plan_sha256 = _digest(
        expected_execution_plan_sha256, "execution-plan SHA-256"
    )
    deployment_sha256 = _digest(expected_deployment_sha256, "deployment SHA-256")
    repository = ImmutableAttemptRepository(root, Path(output_root))
    observations = []
    entries = []
    attempt_roots: set[Path] = set()
    try:
        for attempt in schedule.attempts:
            observation = repository.reconcile(
                attempt, expected_commit=schedule.source_commit
            )
            if observation is None:
                raise C4BaselineFreezeError("C4 baseline schedule is incomplete")
            attempt_root = repository.attempt_root(attempt)
            attempt_roots.add(attempt_root.relative_to(root / output_root))
            generation = _private_digest(attempt_root / "generation.jsonl")
            run_manifest = _private_digest(attempt_root / "run.json")
            entries.append(
                {
                    "attempt_id": attempt.attempt_id,
                    "condition": "C4",
                    "database": attempt.database,
                    "generation_sha256": generation,
                    "instance_id": attempt.instance_id,
                    "repetition": 1,
                    "run_manifest_sha256": run_manifest,
                }
            )
            observations.append(observation)
    except BaselineBatchError as error:
        raise C4BaselineFreezeError(str(error)) from error

    file_count, inventory_sha256 = _artifact_inventory(
        root / output_root, attempt_roots
    )
    outcomes = Counter(item.generation_outcome for item in observations)
    payload = {
        "artifact_file_count": file_count,
        "artifact_inventory_sha256": inventory_sha256,
        "counts": {
            "answered": outcomes["answered"],
            "attempts": len(entries),
            "databases": len({item.attempt.database for item in observations}),
            "errored": outcomes["errored"],
            "refused": outcomes["refused"],
        },
        "deployment_sha256": deployment_sha256,
        "eligible_manifest_sha256": schedule.eligible_manifest_sha256,
        "entries": entries,
        "execution_plan_sha256": execution_plan_sha256,
        "kind": "public-c4-baseline-freeze",
        "output_root": Path(output_root).as_posix(),
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "source_commit": schedule.source_commit,
        "source_schedule_sha256": schedule.sha256,
        "train_ids_sha256": schedule.train_ids_sha256,
    }
    content = _canonical_json(payload)
    try:
        stored = _write_exclusive(root / destination, content, workspace=root)
    except AutoresearchError as error:
        raise C4BaselineFreezeError(str(error)) from error
    return {
        "artifact_file_count": file_count,
        "attempt_count": len(entries),
        "database_count": payload["counts"]["databases"],
        "path": stored.relative_to(root).as_posix(),
        "run_id": run_id,
        "selection_sha256": hashlib.sha256(content).hexdigest(),
        "source_schedule_sha256": schedule.sha256,
    }


def _validate_identity(
    schedule: BaselineSchedule, *, output_root: Path, destination: Path
) -> str:
    if not isinstance(schedule, BaselineSchedule):
        raise C4BaselineFreezeError("C4 baseline schedule is invalid")
    run_ids = {attempt.run_id for attempt in schedule.attempts}
    if len(run_ids) != 1 or any(
        attempt.condition != "C4" for attempt in schedule.attempts
    ):
        raise C4BaselineFreezeError("freeze requires one exact C4-only schedule")
    run_id = next(iter(run_ids))
    if is_quarantined_run(run_id):
        raise C4BaselineFreezeError("C4 baseline run is quarantined and non-scoreable")
    if output_root != RAW_ROOT / run_id:
        raise C4BaselineFreezeError("C4 output root does not match the run identity")
    expected_destination = STATE_ROOT / f"{run_id}-freeze.json"
    if destination != expected_destination:
        raise C4BaselineFreezeError(
            "C4 freeze destination does not match the run identity"
        )
    return run_id


def _artifact_inventory(root: Path, attempt_roots: set[Path]) -> tuple[int, str]:
    try:
        root_metadata = root.lstat()
    except OSError as error:
        raise C4BaselineFreezeError("C4 artifact root is unavailable") from error
    if root.is_symlink() or not stat.S_ISDIR(root_metadata.st_mode):
        raise C4BaselineFreezeError("C4 artifact root is not a regular directory")

    allowed_directories = {Path(".")}
    for attempt_root in attempt_roots:
        for parent in (attempt_root.parent.parent, attempt_root.parent, attempt_root):
            allowed_directories.add(parent)

    inventory: list[dict[str, object]] = []
    try:
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            relative_current = current_path.relative_to(root)
            if relative_current not in allowed_directories:
                raise C4BaselineFreezeError(
                    "C4 artifact tree contains an unexpected directory"
                )
            for name in directories:
                child = current_path / name
                metadata = child.lstat()
                relative = child.relative_to(root)
                if (
                    child.is_symlink()
                    or not stat.S_ISDIR(metadata.st_mode)
                    or relative not in allowed_directories
                ):
                    raise C4BaselineFreezeError(
                        "C4 artifact tree contains an unexpected directory"
                    )
            for name in files:
                path = current_path / name
                relative = path.relative_to(root)
                if (
                    relative.parent not in attempt_roots
                    or name not in _C4_ARTIFACT_NAMES
                ):
                    raise C4BaselineFreezeError(
                        "C4 artifact tree contains an unexpected file"
                    )
                digest, size = _private_file_identity(path)
                inventory.append(
                    {"path": relative.as_posix(), "sha256": digest, "size_bytes": size}
                )
    except C4BaselineFreezeError:
        raise
    except (OSError, ValueError) as error:
        raise C4BaselineFreezeError("cannot inventory C4 artifacts") from error
    inventory.sort(key=lambda item: str(item["path"]))
    return len(inventory), hashlib.sha256(_canonical_json(inventory)).hexdigest()


def _private_digest(path: Path) -> str:
    return _private_file_identity(path)[0]


def _private_file_identity(path: Path) -> tuple[str, int]:
    descriptor: int | None = None
    try:
        path_metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(path_metadata.st_mode):
            raise C4BaselineFreezeError("C4 artifact is not a private regular file")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or metadata.st_size < 1
            or metadata.st_size > MAX_ARTIFACT_BYTES
        ):
            raise C4BaselineFreezeError("C4 artifact is not a private regular file")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest(), metadata.st_size
    except C4BaselineFreezeError:
        raise
    except OSError as error:
        raise C4BaselineFreezeError("cannot read C4 artifact") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _workspace(value: Path) -> Path:
    try:
        return Path(value).resolve(strict=True)
    except OSError as error:
        raise C4BaselineFreezeError("workspace is unavailable") from error


def _digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise C4BaselineFreezeError(f"{description} is invalid")
    return value


def _canonical_json(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise C4BaselineFreezeError("C4 freeze contains invalid JSON") from error

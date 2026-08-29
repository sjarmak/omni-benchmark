"""Record Freeze B from exact committed, public-only provenance inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .autoresearch_config import AutoresearchError, _write_exclusive
from .content_policy import ContentPolicy
from .freeze_b import (
    CONDITIONS,
    EXPECTED_TEST_OUTPUTS,
    REPETITIONS,
    SCHEDULE_ALGORITHM,
    FreezeBError,
    FreezeBManifest,
    schedule_sha256,
)
from .scoring import scorer_metadata

INPUT_KIND = "freeze-b-input"
INPUT_SCHEMA_VERSION = 1
MAX_SPEC_BYTES = 1024 * 1024
MAX_SCHEDULE_BYTES = 4 * 1024 * 1024
MAX_FROZEN_FILE_BYTES = 64 * 1024 * 1024
MAX_RUNTIME_SOURCE_BYTES = 4 * 1024 * 1024

_COMMIT = re.compile(r"[0-9a-f]{40}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")
_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@+~-]{0,511}")
_INPUT_FIELDS = frozenset(
    {
        "conditions",
        "database",
        "freeze_a_commit",
        "frozen_files",
        "kind",
        "schedule",
        "schema_version",
    }
)
_DATABASE_FIELDS = frozenset(
    {"libpq_version", "postgresql_version", "snapshot_manifest_path"}
)
_SCHEDULE_FIELDS = frozenset({"algorithm", "path", "seed"})
_CONDITION_FIELDS = frozenset(
    {
        "budget_id",
        "condition",
        "harness_config_path",
        "instructions_path",
        "model",
        "model_config_id",
        "prompt_path",
        "provider",
        "runtime_policy_path",
        "semantic_model_path",
        "semantic_model_ref",
    }
)
_SCHEDULE_RECORD_FIELDS = frozenset(
    {"attempt_id", "condition", "instance_id", "repetition"}
)


class FreezeBRecordError(RuntimeError):
    """Raised when exact committed inputs cannot produce a safe Freeze B."""


@dataclass(frozen=True)
class FreezeBRecordResult:
    """Public result metadata for one exclusively written Freeze B."""

    manifest: FreezeBManifest
    path: Path
    frozen_file_count: int
    schedule_attempt_count: int


@dataclass(frozen=True)
class _CommittedInput:
    content: bytes
    sha256: str


def record_freeze_b(
    workspace: Path,
    *,
    system_commit: str,
    input_spec_path: Path,
    recorded_at: str,
    destination: Path,
) -> FreezeBRecordResult:
    """Derive and exclusively write one Freeze B from the current exact commit."""
    root = _repository_root(workspace)
    commit = _current_exact_commit(root, system_commit)
    _verify_runtime_sources(root, commit)
    spec_relative = _relative_path(input_spec_path, "input spec path")
    spec_input = _committed_input(
        root, commit, spec_relative, maximum_bytes=MAX_SPEC_BYTES
    )
    spec = _input_spec(spec_input.content)
    freeze_a_commit = _ancestor_commit(root, spec["freeze_a_commit"], commit)
    frozen_paths = _frozen_paths(spec["frozen_files"])
    if spec_relative not in frozen_paths:
        raise FreezeBRecordError("frozen_files must include the input spec path")
    schedule = _mapping(spec["schedule"], _SCHEDULE_FIELDS, "schedule")
    if schedule["algorithm"] != SCHEDULE_ALGORITHM:
        raise FreezeBRecordError("schedule algorithm does not match the frozen policy")
    schedule_path = _relative_path(schedule["path"], "schedule path")
    if schedule_path not in frozen_paths:
        raise FreezeBRecordError("frozen_files must include the schedule path")
    from .freeze_b_schedule import (
        TEST_IDS_PATH,
        FreezeBScheduleError,
        expected_schedule_bytes,
    )

    if TEST_IDS_PATH not in frozen_paths:
        raise FreezeBRecordError("frozen_files must include the committed test IDs")
    committed = {
        path: _committed_input(
            root,
            commit,
            path,
            maximum_bytes=(
                MAX_SCHEDULE_BYTES if path == schedule_path else MAX_FROZEN_FILE_BYTES
            ),
        )
        for path in frozen_paths
    }
    try:
        registered_schedule = expected_schedule_bytes(
            committed[TEST_IDS_PATH].content, schedule["seed"]
        )
    except FreezeBScheduleError as error:
        raise FreezeBRecordError(str(error)) from error
    if committed[schedule_path].content != registered_schedule:
        raise FreezeBRecordError(
            "schedule does not match the registered algorithm, seed, and test IDs"
        )
    attempt_ids = _schedule_attempt_ids(committed[schedule_path].content)
    database, snapshot_path = _database(spec["database"])
    if snapshot_path not in committed:
        raise FreezeBRecordError(
            "frozen_files must include the database snapshot manifest path"
        )
    conditions = _conditions(spec["conditions"], committed)
    manifest_value = {
        "conditions": conditions,
        "database": {
            "libpq_version": database["libpq_version"],
            "postgresql_version": database["postgresql_version"],
            "snapshot_manifest_sha256": committed[snapshot_path].sha256,
        },
        "expected_test_outputs": EXPECTED_TEST_OUTPUTS,
        "freeze_a_commit": freeze_a_commit,
        "frozen_files": {path: committed[path].sha256 for path in sorted(committed)},
        "kind": "freeze-b-manifest",
        "question_count": 101,
        "recorded_at": recorded_at,
        "repetitions": REPETITIONS,
        "schedule": {
            "algorithm": SCHEDULE_ALGORITHM,
            "seed": schedule["seed"],
            "sha256": schedule_sha256(attempt_ids),
        },
        "schema_version": 1,
        "scorer": {"metadata": scorer_metadata(), "source_commit": commit},
        "system_commit": commit,
    }
    try:
        manifest = FreezeBManifest.from_dict(manifest_value)
    except FreezeBError as error:
        raise FreezeBRecordError(str(error)) from error
    try:
        destination_path = Path(_relative_path(destination, "destination path"))
        output = _write_exclusive(
            destination_path, manifest.canonical_bytes(), workspace=root
        )
    except AutoresearchError as error:
        raise FreezeBRecordError(str(error)) from error
    return FreezeBRecordResult(
        manifest=manifest,
        path=output,
        frozen_file_count=len(committed),
        schedule_attempt_count=len(attempt_ids),
    )


def _repository_root(workspace: Path) -> Path:
    absolute = workspace.absolute()
    try:
        supplied = workspace.resolve(strict=True)
    except OSError as error:
        raise FreezeBRecordError("workspace must be an existing repository") from error
    if absolute != supplied or workspace.is_symlink() or not supplied.is_dir():
        raise FreezeBRecordError("workspace must be a non-symlink directory")
    top_level = Path(_git_text(supplied, "rev-parse", "--show-toplevel"))
    try:
        resolved_top = top_level.resolve(strict=True)
    except OSError as error:
        raise FreezeBRecordError("cannot resolve repository root") from error
    if resolved_top != supplied:
        raise FreezeBRecordError("workspace must be the repository root")
    return supplied


def _current_exact_commit(workspace: Path, supplied: str) -> str:
    if not isinstance(supplied, str) or _COMMIT.fullmatch(supplied) is None:
        raise FreezeBRecordError("system commit must be a full lowercase commit hash")
    resolved = _git_text(workspace, "rev-parse", f"{supplied}^{{commit}}")
    if resolved != supplied:
        raise FreezeBRecordError("system commit is not canonical")
    if _git_text(workspace, "rev-parse", "HEAD") != supplied:
        raise FreezeBRecordError("system commit must equal current HEAD")
    return supplied


def _ancestor_commit(workspace: Path, supplied: object, descendant: str) -> str:
    if not isinstance(supplied, str) or _COMMIT.fullmatch(supplied) is None:
        raise FreezeBRecordError("freeze_a_commit must be a full lowercase commit hash")
    resolved = _git_text(workspace, "rev-parse", f"{supplied}^{{commit}}")
    if resolved != supplied:
        raise FreezeBRecordError("freeze_a_commit is not canonical")
    result = subprocess.run(
        [
            "git",
            "-C",
            str(workspace),
            "merge-base",
            "--is-ancestor",
            supplied,
            descendant,
        ],
        check=False,
        capture_output=True,
        env=_git_environment(),
    )
    if result.returncode != 0:
        raise FreezeBRecordError("freeze_a_commit must be an ancestor of system commit")
    return supplied


def _verify_runtime_sources(workspace: Path, commit: str) -> None:
    from . import freeze_b_schedule

    sources = {
        "src/omni_benchmark/autoresearch_config.py": Path(
            _write_exclusive.__code__.co_filename
        ),
        "src/omni_benchmark/content_policy.py": Path(
            ContentPolicy.from_environment.__func__.__code__.co_filename
        ),
        "src/omni_benchmark/freeze_b.py": Path(
            FreezeBManifest.from_dict.__func__.__code__.co_filename
        ),
        "src/omni_benchmark/freeze_b_record.py": Path(__file__),
        "src/omni_benchmark/freeze_b_schedule.py": Path(freeze_b_schedule.__file__),
        "src/omni_benchmark/scoring.py": Path(scorer_metadata.__code__.co_filename),
    }
    for relative, loaded_path in sources.items():
        committed = _committed_input(
            workspace,
            commit,
            relative,
            maximum_bytes=MAX_RUNTIME_SOURCE_BYTES,
        )
        if (
            hashlib.sha256(_runtime_source_bytes(loaded_path)).hexdigest()
            != committed.sha256
        ):
            raise FreezeBRecordError(
                "recorder runtime source does not match the system commit"
            )


def _runtime_source_bytes(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise FreezeBRecordError("recorder runtime source must be a regular file")
        if metadata.st_size > MAX_RUNTIME_SOURCE_BYTES:
            raise FreezeBRecordError("recorder runtime source exceeds the byte limit")
        content = path.read_bytes()
    except FreezeBRecordError:
        raise
    except OSError as error:
        raise FreezeBRecordError("cannot read recorder runtime source") from error
    if len(content) != metadata.st_size:
        raise FreezeBRecordError("recorder runtime source changed while reading")
    return content


def _committed_input(
    workspace: Path,
    commit: str,
    path: str,
    *,
    maximum_bytes: int,
) -> _CommittedInput:
    entry = _git_bytes(workspace, "ls-tree", "-z", commit, "--", path)
    if not entry or not entry.endswith(b"\0") or entry.count(b"\0") != 1:
        raise FreezeBRecordError(f"{path} must be a committed regular file")
    metadata, separator, raw_path = entry[:-1].partition(b"\t")
    parts = metadata.split()
    if (
        not separator
        or len(parts) != 3
        or parts[0] not in {b"100644", b"100755"}
        or parts[1] != b"blob"
        or raw_path.decode("utf-8", errors="strict") != path
    ):
        raise FreezeBRecordError(f"{path} must be a committed regular file")
    object_id = parts[2].decode("ascii")
    size_text = _git_text(workspace, "cat-file", "-s", object_id)
    try:
        size = int(size_text)
    except ValueError as error:
        raise FreezeBRecordError(
            "git returned an invalid committed file size"
        ) from error
    if size > maximum_bytes:
        raise FreezeBRecordError(f"{path} exceeds the committed file byte limit")
    content = _git_bytes(workspace, "cat-file", "blob", object_id)
    if len(content) != size:
        raise FreezeBRecordError(f"{path} changed while reading the commit")
    return _CommittedInput(
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _input_spec(content: bytes) -> Mapping[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise FreezeBRecordError("input spec must be UTF-8 JSON") from error
    spec = _mapping(value, _INPUT_FIELDS, "input spec")
    if (
        spec["kind"] != INPUT_KIND
        or type(spec["schema_version"]) is not int
        or spec["schema_version"] != INPUT_SCHEMA_VERSION
    ):
        raise FreezeBRecordError("input spec kind or schema_version is invalid")
    return spec


def _frozen_paths(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise FreezeBRecordError("frozen_files must be a non-empty array")
    paths = tuple(_relative_path(path, "frozen file path") for path in value)
    if len(set(paths)) != len(paths):
        raise FreezeBRecordError("frozen_files contains a duplicate path")
    return paths


def _database(value: object) -> tuple[Mapping[str, Any], str]:
    database = _mapping(value, _DATABASE_FIELDS, "database")
    snapshot_path = _relative_path(
        database["snapshot_manifest_path"], "database snapshot manifest path"
    )
    return database, snapshot_path


def _conditions(
    value: object,
    committed: Mapping[str, _CommittedInput],
) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) != len(CONDITIONS):
        raise FreezeBRecordError("input spec must contain exactly four conditions")
    output: list[dict[str, object]] = []
    for expected, raw in zip(CONDITIONS, value, strict=True):
        item = _mapping(raw, _CONDITION_FIELDS, "condition")
        if item["condition"] != expected:
            raise FreezeBRecordError("condition order must be C1, C2, C3, C4")
        paths = {
            field: _relative_path(item[field], f"{expected} {field}")
            for field in (
                "harness_config_path",
                "instructions_path",
                "prompt_path",
                "runtime_policy_path",
            )
        }
        semantic_path_value = item["semantic_model_path"]
        if semantic_path_value is None:
            semantic_path = None
        else:
            semantic_path = _relative_path(
                semantic_path_value, f"{expected} semantic_model_path"
            )
        if expected == "C1" and semantic_path is not None:
            raise FreezeBRecordError("C1 semantic_model_path must be null")
        if expected in {"C3", "C4"} and semantic_path is None:
            raise FreezeBRecordError(f"{expected} semantic_model_path is required")
        output.append(
            {
                "budget_id": item["budget_id"],
                "condition": expected,
                "harness_config_sha256": _digest_for(
                    committed, paths["harness_config_path"]
                ),
                "instructions_sha256": _digest_for(
                    committed, paths["instructions_path"]
                ),
                "model": item["model"],
                "model_config_id": item["model_config_id"],
                "prompt_sha256": _digest_for(committed, paths["prompt_path"]),
                "provider": item["provider"],
                "runtime_policy_sha256": _digest_for(
                    committed, paths["runtime_policy_path"]
                ),
                "semantic_model_ref": item["semantic_model_ref"],
                "semantic_model_sha256": (
                    None
                    if semantic_path is None
                    else _digest_for(committed, semantic_path)
                ),
            }
        )
    return output


def _digest_for(committed: Mapping[str, _CommittedInput], path: str) -> str:
    value = committed.get(path)
    if value is None:
        raise FreezeBRecordError(
            "frozen_files must include every condition provenance path"
        )
    return value.sha256


def _schedule_attempt_ids(content: bytes) -> tuple[str, ...]:
    records: list[tuple[str, str, int, str]] = []
    for line_number, raw_line in enumerate(content.splitlines(keepends=True), start=1):
        if not raw_line.endswith(b"\n") or not raw_line.strip():
            raise FreezeBRecordError(
                "schedule must be canonical newline-terminated JSONL"
            )
        try:
            value = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FreezeBRecordError(
                f"schedule line {line_number} is invalid JSON"
            ) from error
        record = _mapping(value, _SCHEDULE_RECORD_FIELDS, "schedule record")
        canonical = (
            json.dumps(
                record, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            + "\n"
        ).encode("utf-8")
        if canonical != raw_line:
            raise FreezeBRecordError("schedule must use canonical JSONL encoding")
        attempt_id = _identifier(record["attempt_id"], "schedule attempt_id")
        instance_id = _identifier(record["instance_id"], "schedule instance_id")
        condition = record["condition"]
        repetition = record["repetition"]
        if condition not in CONDITIONS:
            raise FreezeBRecordError("schedule condition is invalid")
        if type(repetition) is not int or repetition not in range(1, REPETITIONS + 1):
            raise FreezeBRecordError("schedule repetition is invalid")
        if not attempt_id.endswith(f":{instance_id}:{condition}:{repetition}"):
            raise FreezeBRecordError("schedule attempt identity is inconsistent")
        records.append((instance_id, condition, repetition, attempt_id))
    if len(records) != EXPECTED_TEST_OUTPUTS:
        raise FreezeBRecordError("schedule must contain exactly 1,212 attempts")
    attempt_ids = tuple(record[3] for record in records)
    if len(set(attempt_ids)) != len(attempt_ids):
        raise FreezeBRecordError("schedule contains a duplicate attempt_id")
    combinations = Counter((record[0], record[1], record[2]) for record in records)
    instances = {record[0] for record in records}
    if len(instances) != 101 or any(count != 1 for count in combinations.values()):
        raise FreezeBRecordError("schedule must contain 101 complete question blocks")
    expected = {
        (instance, condition, repetition)
        for instance in instances
        for condition in CONDITIONS
        for repetition in range(1, REPETITIONS + 1)
    }
    if set(combinations) != expected:
        raise FreezeBRecordError(
            "schedule is missing a condition/repetition combination"
        )
    return attempt_ids


def _relative_path(value: object, description: str) -> str:
    if not isinstance(value, (str, Path)):
        raise FreezeBRecordError(f"{description} is invalid")
    raw = value.as_posix() if isinstance(value, Path) else value
    path = PurePosixPath(raw)
    if (
        not raw
        or _PATH.fullmatch(raw) is None
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in raw
        or str(path) != raw
    ):
        raise FreezeBRecordError(f"{description} is invalid")
    if not ContentPolicy.from_environment(os.environ).identifier_is_safe(raw):
        raise FreezeBRecordError(f"{description} is invalid")
    return raw


def _identifier(value: object, description: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise FreezeBRecordError(f"{description} is invalid")
    return value


def _mapping(
    value: object, fields: frozenset[str], description: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise FreezeBRecordError(f"{description} must use the exact schema")
    return value


def _git_text(workspace: Path, *arguments: str) -> str:
    return _git_bytes(workspace, *arguments).decode("utf-8").strip()


def _git_bytes(workspace: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        check=False,
        capture_output=True,
        env=_git_environment(),
    )
    if result.returncode != 0:
        raise FreezeBRecordError("git could not resolve the committed Freeze B input")
    return result.stdout


def _git_environment() -> dict[str, str]:
    """Ignore caller-supplied Git repository/object/config redirections."""
    return {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record Freeze B from exact committed public provenance"
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--input-spec", type=Path, required=True)
    parser.add_argument("--recorded-at", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    return parser


def record_main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = record_freeze_b(
        arguments.workspace,
        system_commit=arguments.system_commit,
        input_spec_path=arguments.input_spec,
        recorded_at=arguments.recorded_at,
        destination=arguments.destination,
    )
    print(
        json.dumps(
            {
                "freeze_b_sha256": result.manifest.sha256(),
                "frozen_file_count": result.frozen_file_count,
                "schedule_attempt_count": result.schedule_attempt_count,
                "system_commit": result.manifest.system_commit,
            },
            sort_keys=True,
        )
    )
    return 0

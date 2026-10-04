import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess
from typing import TextIO


SCHEMA_VERSION = 1
LEDGER_NAME = "stage-ledger.jsonl"


class DriverError(ValueError):
    pass


@dataclass(frozen=True)
class Stage:
    name: str
    argv: tuple[str, ...]
    outputs: tuple[str, ...]


@dataclass(frozen=True)
class Manifest:
    series_id: str
    mode: str
    stages: tuple[Stage, ...]


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise DriverError("duplicate JSON keys")
    return result


def _keys(value: object, keys: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise DriverError(f"expected exactly these keys: {sorted(keys)}")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise DriverError("expected a nonempty string without NUL")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DriverError("expected a string array")
    return tuple(_text(item) for item in value)


def parse_manifest(content: str) -> Manifest:
    try:
        data = json.loads(content, object_pairs_hook=_object)
    except json.JSONDecodeError as error:
        raise DriverError("invalid manifest JSON") from error
    data = _keys(data, {"schema_version", "series_id", "mode", "stages"})
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] != SCHEMA_VERSION
    ):
        raise DriverError("unsupported manifest schema_version")
    series_id = _text(data["series_id"])
    if data["mode"] not in ("dry", "live"):
        raise DriverError("mode must be dry or live")
    if not isinstance(data["stages"], list) or not data["stages"]:
        raise DriverError("stages must be a nonempty array")
    stages = tuple(_stage(value) for value in data["stages"])
    if len({stage.name for stage in stages}) != len(stages):
        raise DriverError("duplicate stage names")
    return Manifest(series_id, data["mode"], stages)


def _stage(value: object) -> Stage:
    data = _keys(value, {"name", "argv", "outputs"})
    argv = _strings(data["argv"])
    if not argv:
        raise DriverError("argv must not be empty")
    return Stage(_text(data["name"]), argv, _strings(data["outputs"]))


def _write_exclusive(path: Path, content: bytes) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
    except FileExistsError as error:
        raise DriverError(f"{path} already exists; refusing overwrite") from error
    except OSError as error:
        raise DriverError(f"exclusive materialization failed: {path}") from error


def _binding(manifest: Manifest) -> str:
    data = {
        "schema_version": SCHEMA_VERSION,
        "series_id": manifest.series_id,
        "mode": manifest.mode,
        "cwd": str(Path.cwd()),
        "stages": [
            {"name": stage.name, "argv": stage.argv, "outputs": stage.outputs}
            for stage in manifest.stages
        ],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _record(
    stage: Stage,
    binding: str,
    event: str,
    exit_code: int | None,
    error_type: str | None = None,
) -> dict:
    return {
        "manifest_sha256": binding,
        "stage": stage.name,
        "event": event,
        "exit_code": exit_code,
        "error_type": error_type,
        "outputs": [str(Path(output).absolute()) for output in stage.outputs],
    }


def _validate_record(row: object, stages: dict[str, Stage], binding: str) -> dict:
    row = _keys(
        row, {"manifest_sha256", "stage", "event", "exit_code", "error_type", "outputs"}
    )
    if row["manifest_sha256"] != binding:
        raise DriverError("ledger does not match manifest")
    name = _text(row["stage"])
    if name not in stages or row["event"] not in ("start", "end"):
        raise DriverError("invalid ledger stage or event")
    if row["exit_code"] is not None and type(row["exit_code"]) is not int:
        raise DriverError("invalid ledger exit code")
    if row["error_type"] is not None:
        _text(row["error_type"])
    expected = _record(
        stages[name], binding, row["event"], row["exit_code"], row["error_type"]
    )
    if row != expected:
        raise DriverError("invalid ledger outputs")
    if row["event"] == "start":
        if row["exit_code"] is not None or row["error_type"] is not None:
            raise DriverError("invalid start record")
    elif (row["exit_code"] is None) == (row["error_type"] is None):
        raise DriverError("end record requires an exit code or error type")
    return row


def _read_ledger(
    stream: TextIO, manifest: Manifest, binding: str, created: bool
) -> dict:
    stream.seek(0)
    lines = stream.readlines()
    if not lines and not created:
        raise DriverError("existing ledger is empty")
    latest = {}
    stages = {stage.name: stage for stage in manifest.stages}
    for line in lines:
        try:
            row = json.loads(line, object_pairs_hook=_object)
        except json.JSONDecodeError as error:
            raise DriverError("invalid ledger JSON") from error
        if not line.endswith("\n"):
            raise DriverError("ledger is truncated")
        row = _validate_record(row, stages, binding)
        if (
            row["event"] == "end"
            and latest.get(row["stage"], {}).get("event") != "start"
        ):
            raise DriverError("end record has no start")
        latest = {**latest, row["stage"]: row}
    return latest


def _append(stream: TextIO, row: dict) -> None:
    stream.write(json.dumps(row, sort_keys=True) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def _execute(
    manifest: Manifest,
    stream: TextIO,
    binding: str,
    latest: dict,
    runner: Callable[[tuple[str, ...]], CompletedProcess],
    start: int,
) -> int:
    for stage in manifest.stages[start:]:
        previous = latest.get(stage.name, {})
        if (
            previous.get("event") == "end"
            and previous.get("exit_code") == 0
            and previous.get("error_type") is None
            and all(Path(output).exists() for output in stage.outputs)
        ):
            continue
        _append(stream, _record(stage, binding, "start", None))
        try:
            result = runner(stage.argv)
            if type(result.returncode) is not int:
                raise DriverError("runner returned a noninteger exit code")
        except BaseException as error:
            _append(stream, _record(stage, binding, "end", None, type(error).__name__))
            raise
        _append(stream, _record(stage, binding, "end", result.returncode))
        if result.returncode != 0:
            return result.returncode
    return 0


def run_stages(
    manifest: Manifest,
    state_root: Path,
    runner: Callable[[tuple[str, ...]], CompletedProcess],
    from_stage: str | None = None,
) -> int:
    names = tuple(stage.name for stage in manifest.stages)
    if from_stage is not None and from_stage not in names:
        raise DriverError(f"unknown stage: {from_stage}")
    start = names.index(from_stage) if from_stage is not None else 0
    path = state_root / LEDGER_NAME
    created = not path.exists()
    if created:
        _write_exclusive(path, b"")
    descriptor = os.open(path, os.O_RDWR | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "a+", encoding="utf-8") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise DriverError("ledger must be a regular file")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise DriverError("ledger is in use") from error
        binding = _binding(manifest)
        latest = _read_ledger(stream, manifest, binding, created)
        return _execute(manifest, stream, binding, latest, runner, start)

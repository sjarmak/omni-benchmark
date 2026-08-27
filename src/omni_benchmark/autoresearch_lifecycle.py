"""Append-only baseline, checkpoint, and optimization-stop lifecycle state."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .autoresearch_config import (
    NAME_PATTERN,
    AutoresearchConfig,
    AutoresearchError,
    _canonical_bytes,
    _display_path,
    _open_confined_parent,
    _public_view_content,
    _read_confined_private_bytes,
    _read_json,
    _require_commit,
    _require_string,
    _resolve_inside,
    _sha256_bytes,
    _utc_timestamp,
    _write_exclusive,
)
from .autoresearch_guardian import validate_dev_b_receipt, validate_taxonomy
from .autoresearch_runs import validate_baseline_outputs, validate_run
from .run_manifest import MAX_MANIFEST_BYTES


def create_baseline(
    config: AutoresearchConfig,
    *,
    run_path: Path,
    git_commit: str,
    run_manifest_path: Path | None = None,
    run_manifest_sha256: str | None = None,
) -> Path:
    """Freeze public-only complete-train outputs exactly once before supervision."""
    _require_active(config)
    if any(
        path.exists()
        for path in (
            config.baseline_path,
            config.baseline_outputs_path,
            config.baseline_run_manifest_path,
        )
    ):
        raise AutoresearchError("baseline already exists; refusing overwrite")
    run = validate_baseline_outputs(
        config,
        run_path,
        manifest_path=run_manifest_path,
        expected_manifest_sha256=run_manifest_sha256,
    )
    try:
        output_bytes = run.path.read_bytes()
    except OSError as error:
        raise AutoresearchError("cannot preserve baseline outputs") from error
    _write_exclusive(
        config.baseline_outputs_path, output_bytes, workspace=config.workspace
    )
    if run.run_manifest_path is not None:
        manifest_bytes = _read_confined_private_bytes(
            config.workspace,
            run.run_manifest_path,
            "baseline run manifest",
            maximum_bytes=MAX_MANIFEST_BYTES,
        )
        if _sha256_bytes(manifest_bytes) != run.run_manifest_sha256:
            raise AutoresearchError("baseline run manifest changed after validation")
        _write_exclusive(
            config.baseline_run_manifest_path,
            manifest_bytes,
            workspace=config.workspace,
        )
    preserved_run = validate_baseline_outputs(
        config,
        config.baseline_outputs_path,
        manifest_path=(
            None if run.run_manifest_path is None else config.baseline_run_manifest_path
        ),
        expected_manifest_sha256=run.run_manifest_sha256,
    )
    manifest = {
        "config_sha256": config.config_sha256,
        "created_at": _utc_timestamp(),
        "git_commit": _require_commit(git_commit),
        "kind": "baseline",
        "run": preserved_run.as_manifest(config.workspace),
        "schema_version": 2,
    }
    return _write_exclusive(
        config.baseline_path, _canonical_bytes(manifest), workspace=config.workspace
    )


def _event_digest(event_without_digest: Mapping[str, Any]) -> str:
    return _sha256_bytes(_canonical_bytes(event_without_digest))


def _parse_ledger(raw: bytes) -> list[dict[str, Any]]:
    if not raw:
        return []
    events: list[dict[str, Any]] = []
    expected_previous: str | None = None
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        try:
            event = json.loads(raw_line)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise AutoresearchError(
                f"ledger line {line_number} is invalid JSON"
            ) from error
        if not isinstance(event, dict):
            raise AutoresearchError(f"ledger line {line_number} must be an object")
        recorded_digest = event.get("event_sha256")
        if not isinstance(recorded_digest, str):
            raise AutoresearchError("ledger hash is missing")
        content = {key: value for key, value in event.items() if key != "event_sha256"}
        if content.get("previous_event_sha256") != expected_previous:
            raise AutoresearchError("ledger hash chain is invalid")
        if _event_digest(content) != recorded_digest:
            raise AutoresearchError("ledger hash does not match event content")
        expected_previous = recorded_digest
        events.append(event)
    return events


LedgerCheck = Callable[[Sequence[dict[str, Any]]], None]


def _ledger_anchor_path(
    config: AutoresearchConfig, index: int, event_sha256: str
) -> Path:
    return config.state_dir / "ledger_anchors" / f"{index:08d}-{event_sha256}.json"


def _verify_ledger_anchors(
    config: AutoresearchConfig, events: Sequence[dict[str, Any]]
) -> None:
    directory = config.state_dir / "ledger_anchors"
    markers = sorted(directory.glob("*.json")) if directory.exists() else []
    if len(markers) != len(events):
        raise AutoresearchError("ledger anchor count does not match ledger history")
    for index, (event, marker_path) in enumerate(zip(events, markers), start=1):
        expected_path = _ledger_anchor_path(config, index, event["event_sha256"])
        marker = _read_json(marker_path, "ledger anchor")
        if marker_path != expected_path or marker != {
            "event": event.get("event"),
            "event_index": index,
            "event_sha256": event["event_sha256"],
            "kind": "ledger-anchor",
            "schema_version": 1,
        }:
            raise AutoresearchError("ledger anchor does not match ledger history")


def _write_ledger_anchor(
    config: AutoresearchConfig, index: int, event: Mapping[str, Any]
) -> None:
    marker = {
        "event": event.get("event"),
        "event_index": index,
        "event_sha256": event["event_sha256"],
        "kind": "ledger-anchor",
        "schema_version": 1,
    }
    _write_exclusive(
        _ledger_anchor_path(config, index, event["event_sha256"]),
        _canonical_bytes(marker),
        workspace=config.workspace,
    )


def _append_event(
    config: AutoresearchConfig,
    payload: Mapping[str, Any],
    check: LedgerCheck,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    event_path = config.ledger_path if path is None else path
    parent_descriptor, _ = _open_confined_parent(config.workspace, event_path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            event_path.name,
            os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_descriptor,
        )
        with os.fdopen(descriptor, "a+b", buffering=0) as handle:
            descriptor = None
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            events = _parse_ledger(handle.read())
            if event_path == config.ledger_path:
                _verify_ledger_anchors(config, events)
            check(events)
            previous = events[-1]["event_sha256"] if events else None
            content = {**payload, "previous_event_sha256": previous}
            event = {**content, "event_sha256": _event_digest(content)}
            handle.seek(0, os.SEEK_END)
            handle.write(_canonical_bytes(event))
            handle.flush()
            os.fsync(handle.fileno())
            if event_path == config.ledger_path:
                _write_ledger_anchor(config, len(events) + 1, event)
            os.fsync(parent_descriptor)
            return event
    except AutoresearchError:
        raise
    except OSError as error:
        raise AutoresearchError("cannot append experiment ledger") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)


def _read_chained_events(
    config: AutoresearchConfig, path: Path
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    parent_descriptor, _ = _open_confined_parent(config.workspace, path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_descriptor,
        )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            return _parse_ledger(handle.read())
    except OSError as error:
        raise AutoresearchError(
            "append-only artifact must remain inside workspace"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)


def _require_baseline(config: AutoresearchConfig) -> None:
    if not config.baseline_path.is_file():
        raise AutoresearchError("baseline must be frozen before optimization")
    baseline = _read_json(config.baseline_path, "baseline manifest")
    _verify_committed_baseline_manifest(config)
    expected_fields = {
        "config_sha256",
        "created_at",
        "git_commit",
        "kind",
        "run",
        "schema_version",
    }
    if not isinstance(baseline, dict) or set(baseline) != expected_fields:
        raise AutoresearchError("baseline manifest is invalid")
    if (
        baseline["kind"] != "baseline"
        or baseline["schema_version"] != 2
        or baseline["config_sha256"] != config.config_sha256
    ):
        raise AutoresearchError("baseline manifest does not match this configuration")
    run = baseline["run"]
    expected_run_fields = {
        "path",
        "question_count",
        "run_manifest_path",
        "run_manifest_sha256",
        "scored",
        "sha256",
        "scope",
    }
    manifest_reference_valid = isinstance(run, dict) and (
        (
            run.get("run_manifest_path") is None
            and run.get("run_manifest_sha256") is None
        )
        or (
            run.get("run_manifest_path")
            == _display_path(config.baseline_run_manifest_path, config.workspace)
            and isinstance(run.get("run_manifest_sha256"), str)
        )
    )
    if (
        not isinstance(run, dict)
        or set(run) != expected_run_fields
        or run["path"] != _display_path(config.baseline_outputs_path, config.workspace)
        or run["question_count"] != config.expected_train_count
        or run["scored"] is not False
        or run["scope"] != "train"
        or not manifest_reference_valid
    ):
        raise AutoresearchError("baseline manifest run reference is invalid")
    preserved = validate_baseline_outputs(
        config,
        config.baseline_outputs_path,
        manifest_path=(
            None
            if run["run_manifest_path"] is None
            else config.workspace / run["run_manifest_path"]
        ),
        expected_manifest_sha256=run["run_manifest_sha256"],
    )
    if preserved.sha256 != run["sha256"]:
        raise AutoresearchError("baseline output artifact changed after it was frozen")


def _verify_committed_baseline_manifest(config: AutoresearchConfig) -> None:
    if not (config.workspace / ".git").exists():
        return
    commit = config.baseline_commit
    if commit is None or re.fullmatch(r"[0-9a-f]{40,64}", commit) is None:
        raise AutoresearchError(
            "a full externally recorded baseline commit is required"
        )
    relative = config.baseline_path.relative_to(config.workspace).as_posix()
    try:
        canonical = subprocess.run(
            ["git", "-C", str(config.workspace), "rev-parse", f"{commit}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        committed = subprocess.run(
            ["git", "-C", str(config.workspace), "show", f"{commit}:{relative}"],
            check=True,
            capture_output=True,
        ).stdout
        current = config.baseline_path.read_bytes()
    except (OSError, subprocess.CalledProcessError) as error:
        raise AutoresearchError("baseline manifest is not committed") from error
    if canonical != commit or committed != current:
        raise AutoresearchError(
            "baseline manifest must match the externally recorded baseline commit"
        )


def _require_active(config: AutoresearchConfig) -> None:
    if config.stop_path.exists() or config.stop_anchor_path.exists():
        raise AutoresearchError("optimization has stopped; state changes are forbidden")
    events = _read_chained_events(config, config.ledger_path)
    _verify_ledger_anchors(config, events)


def _ledger_head(config: AutoresearchConfig) -> str:
    try:
        raw = config.ledger_path.read_bytes()
    except OSError as error:
        raise AutoresearchError(
            "checkpoint requires a non-empty experiment ledger"
        ) from error
    events = _parse_ledger(raw)
    if not events:
        raise AutoresearchError("checkpoint requires a non-empty experiment ledger")
    return events[-1]["event_sha256"]


def create_checkpoint(
    config: AutoresearchConfig,
    *,
    name: str,
    run_path: Path,
    score_path: Path | None = None,
    score_sha256: str | None = None,
    run_manifest_path: Path | None = None,
    run_manifest_sha256: str | None = None,
    dev_b_receipt_path: Path,
    dev_b_signature_path: Path,
    guardian_public_key_path: Path,
    taxonomy_path: Path,
    git_commit: str,
) -> Path:
    """Freeze one optimization checkpoint with full-train and taxonomy hashes."""
    _require_active(config)
    if not isinstance(name, str) or NAME_PATTERN.fullmatch(name) is None:
        raise AutoresearchError("checkpoint name contains unsafe characters")
    checkpoint_path = config.state_dir / "checkpoints" / f"{name}.json"
    if checkpoint_path.exists():
        raise AutoresearchError(
            f"{checkpoint_path.name} already exists; refusing overwrite"
        )
    run = validate_run(
        config,
        run_path,
        scope="dev-a",
        score_path=score_path,
        expected_score_sha256=score_sha256,
        manifest_path=run_manifest_path,
        expected_manifest_sha256=run_manifest_sha256,
    )
    if config.guardian_public_key_sha256 is None:
        raise AutoresearchError(
            "dev-B guardian key must be provisioned in the Freeze-A configuration"
        )
    dev_b_receipt = validate_dev_b_receipt(
        config,
        dev_b_receipt_path,
        candidate_run_sha256=run.sha256,
        signature_path=dev_b_signature_path,
        public_key_path=guardian_public_key_path,
        expected_public_key_sha256=config.guardian_public_key_sha256,
    )
    taxonomy = _resolve_inside(
        config.workspace, Path(taxonomy_path), "failure taxonomy"
    )
    try:
        taxonomy_sha256 = validate_taxonomy(
            taxonomy,
            config.expected_dev_a_count,
            forbidden_fields=config.forbidden_fields,
        )
    except OSError as error:
        raise AutoresearchError("cannot read failure taxonomy") from error
    evaluation_number = _allocate_dev_b_evaluation(
        config, name=name, receipt=dev_b_receipt, git_commit=git_commit
    )
    dev_b_view = (
        config.state_dir / "checkpoints" / name / "public_dev_b_questions.jsonl"
    )
    _write_exclusive(
        dev_b_view,
        _public_view_content(config, config.dev_b_ids),
        workspace=config.workspace,
    )
    manifest = {
        "config_sha256": config.config_sha256,
        "created_at": _utc_timestamp(),
        "git_commit": _require_commit(git_commit),
        "kind": "checkpoint",
        "dev_b_evaluation_number": evaluation_number,
        "dev_b_public_view_path": _display_path(dev_b_view, config.workspace),
        "dev_b_receipt": dev_b_receipt,
        "ledger_head_sha256": _ledger_head(config),
        "name": name,
        "run": run.as_manifest(config.workspace),
        "schema_version": 1,
        "taxonomy_path": _display_path(taxonomy, config.workspace),
        "taxonomy_sha256": taxonomy_sha256,
    }
    return _write_exclusive(
        checkpoint_path, _canonical_bytes(manifest), workspace=config.workspace
    )


def _allocate_dev_b_evaluation(
    config: AutoresearchConfig,
    *,
    name: str,
    receipt: Mapping[str, Any],
    git_commit: str,
) -> int:
    directory = config.state_dir / "dev_b_evaluations"
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".counter.lock"
    try:
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            history = _load_dev_b_history(config, directory)
            _verify_committed_dev_b_history(config, history)
            if any(
                marker["receipt_id"] == receipt["receipt_id"]
                or marker["receipt_sha256"] == receipt["receipt_sha256"]
                or marker["outputs_sha256"] == receipt["outputs_sha256"]
                for _, _, marker in history
            ):
                raise AutoresearchError("dev-B guardian receipt was already consumed")
            number = len(history) + 1
            if number > config.dev_b_max_evaluations:
                raise AutoresearchError("dev-B evaluation budget is exhausted")
            marker = {
                "checkpoint": name,
                "created_at": _utc_timestamp(),
                "evaluation_number": number,
                "git_commit": _require_commit(git_commit),
                "kind": "dev-b-evaluation",
                "receipt_id": receipt["receipt_id"],
                "receipt_sha256": receipt["receipt_sha256"],
                "outputs_sha256": receipt["outputs_sha256"],
                "schema_version": 1,
            }
            _write_exclusive(
                directory / f"{number:04d}.json",
                _canonical_bytes(marker),
                workspace=config.workspace,
            )
            return number
    except AutoresearchError:
        raise
    except OSError as error:
        raise AutoresearchError("cannot allocate dev-B evaluation") from error


def _load_dev_b_history(
    config: AutoresearchConfig, directory: Path
) -> list[tuple[Path, Path, dict[str, Any]]]:
    marker_paths = sorted(directory.glob("[0-9][0-9][0-9][0-9].json"))
    checkpoint_directory = config.state_dir / "checkpoints"
    checkpoint_paths = (
        sorted(checkpoint_directory.glob("*.json"))
        if checkpoint_directory.exists()
        else []
    )
    checkpoints: dict[int, tuple[Path, dict[str, Any]]] = {}
    for path in checkpoint_paths:
        checkpoint = _read_json(path, "checkpoint manifest")
        number = checkpoint.get("dev_b_evaluation_number")
        if (
            checkpoint.get("kind") != "checkpoint"
            or isinstance(number, bool)
            or not isinstance(number, int)
            or number < 1
            or number in checkpoints
        ):
            raise AutoresearchError("dev-B evaluation history is inconsistent")
        checkpoints[number] = (path, checkpoint)
    expected_numbers = list(range(1, len(marker_paths) + 1))
    if sorted(checkpoints) != expected_numbers:
        raise AutoresearchError("dev-B evaluation history is inconsistent")
    history: list[tuple[Path, Path, dict[str, Any]]] = []
    for number, marker_path in enumerate(marker_paths, start=1):
        if marker_path.name != f"{number:04d}.json":
            raise AutoresearchError("dev-B evaluation history is inconsistent")
        marker = _read_json(marker_path, "dev-B evaluation marker")
        checkpoint_path, checkpoint = checkpoints[number]
        receipt = checkpoint.get("dev_b_receipt")
        if not isinstance(receipt, dict) or not _dev_b_entry_matches(
            number, marker, checkpoint, receipt
        ):
            raise AutoresearchError("dev-B evaluation history is inconsistent")
        history.append((marker_path, checkpoint_path, marker))
    return history


def _dev_b_entry_matches(
    number: int,
    marker: object,
    checkpoint: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> bool:
    return isinstance(marker, dict) and marker == {
        "checkpoint": checkpoint.get("name"),
        "created_at": marker.get("created_at"),
        "evaluation_number": number,
        "git_commit": checkpoint.get("git_commit"),
        "kind": "dev-b-evaluation",
        "outputs_sha256": receipt.get("outputs_sha256"),
        "receipt_id": receipt.get("receipt_id"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "schema_version": 1,
    }


def _verify_committed_dev_b_history(
    config: AutoresearchConfig,
    history: Sequence[tuple[Path, Path, Mapping[str, Any]]],
) -> None:
    repository = _git_repository_root(config.workspace)
    if repository is None:
        return
    current_paths = {
        path.resolve().relative_to(repository).as_posix()
        for marker_path, checkpoint_path, _ in history
        for path in (marker_path, checkpoint_path)
    }
    committed_paths = _committed_dev_b_paths(config, repository)
    if current_paths != committed_paths:
        raise AutoresearchError(
            "prior dev-B evaluation history must be committed before another checkpoint"
        )
    for relative_path in sorted(current_paths):
        committed = _git_show(repository, relative_path)
        current = (repository / relative_path).read_bytes()
        if committed != current:
            raise AutoresearchError(
                "prior dev-B evaluation history differs from the committed anchor"
            )


def _git_repository_root(workspace: Path) -> Path | None:
    completed = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return Path(completed.stdout.strip()).resolve()


def _committed_dev_b_paths(config: AutoresearchConfig, repository: Path) -> set[str]:
    checkpoint_directory = (config.state_dir / "checkpoints").relative_to(repository)
    marker_directory = (config.state_dir / "dev_b_evaluations").relative_to(repository)
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "ls-tree",
            "-r",
            "--name-only",
            "HEAD",
            "--",
            checkpoint_directory.as_posix(),
            marker_directory.as_posix(),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise AutoresearchError("cannot verify committed dev-B evaluation history")
    checkpoint_pattern = re.compile(
        rf"{re.escape(checkpoint_directory.as_posix())}/[^/]+\.json"
    )
    marker_pattern = re.compile(
        rf"{re.escape(marker_directory.as_posix())}/[0-9]{{4}}\.json"
    )
    return {
        path
        for path in completed.stdout.splitlines()
        if checkpoint_pattern.fullmatch(path) or marker_pattern.fullmatch(path)
    }


def _git_show(repository: Path, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), "show", f"HEAD:{relative_path}"],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AutoresearchError("cannot read committed dev-B evaluation history")
    return completed.stdout


def stop_optimization(
    config: AutoresearchConfig,
    *,
    reason: str,
    rationale: str,
    git_commit: str,
) -> Path:
    """Permanently terminate development optimization before sealed evaluation."""
    _require_baseline(config)
    if config.stop_path.exists() or config.stop_anchor_path.exists():
        raise AutoresearchError("optimization stop already exists")
    manifest = {
        "config_sha256": config.config_sha256,
        "created_at": _utc_timestamp(),
        "git_commit": _require_commit(git_commit),
        "kind": "optimization-stop",
        "ledger_head_sha256": (
            _ledger_head(config) if config.ledger_path.exists() else None
        ),
        "rationale": _require_string(rationale, "rationale"),
        "reason": _require_string(reason, "reason"),
        "schema_version": 1,
    }
    content = _canonical_bytes(manifest)
    _write_exclusive(config.stop_anchor_path, content, workspace=config.workspace)
    return _write_exclusive(config.stop_path, content, workspace=config.workspace)

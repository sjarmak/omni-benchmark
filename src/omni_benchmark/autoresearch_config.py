"""Configuration, path custody, and public development views."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import stat
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Sequence

DECISIONS = frozenset({"KEEP", "REVERT", "INCONCLUSIVE", "INVESTIGATE", "ARCHIVE"})
OUTCOMES = frozenset({"correct", "wrong_answer", "refused_or_error"})
MANDATORY_FORBIDDEN_FIELDS = frozenset(
    {
        "sol_sql",
        "gold_sql",
        "test_cases",
        "external_knowledge",
        "test_correctness",
        "gold_result",
        "expected_result",
        "oracle_sql",
        "oracle_hint",
    }
)
OPTIMIZATION_SURFACES = frozenset(
    {"textual", "structural", "human_research_controlled"}
)
GENERALITY_SCOPES = {
    "question_specific": 0,
    "benchmark_specific": 1,
    "database_specific_legitimate": 2,
    "database_family": 3,
    "cross_database_general": 4,
}
TUNING_ACTORS = frozenset({"autonomous_agent", "human", "human_agent_collaboration"})
REQUIRED_CONFIG_FIELDS = frozenset(
    {
        "expected_train_count",
        "expected_dev_a_count",
        "expected_dev_b_count",
        "dev_a_ids_path",
        "dev_b_ids_path",
        "dev_b_max_evaluations",
        "forbidden_fields",
        "guardian_public_key_sha256",
        "ledger_path",
        "public_manifest_path",
        "state_dir",
        "test_ids_path",
        "train_ids_path",
    }
)
REQUIRED_RUN_FIELDS = frozenset(
    {
        "attempt_id",
        "condition",
        "cost_source",
        "database_query_count",
        "failure_origin",
        "finished_at",
        "generation_outcome",
        "instance_id",
        "model",
        "partition",
        "question",
        "outcome",
        "repetition",
        "retry_count",
        "run_id",
        "started_at",
        "terminal_failure_class",
        "telemetry_unavailable",
        "tool_call_count",
        "tool_calls_by_name",
        "token_source",
        "trace_captured",
        "trace_degraded_reason",
        "trace_path",
        "trace_schema_version",
        "trace_sha256",
        "trace_truncated",
        "validation_attempt_count",
        "latency_ms",
        "cost_usd",
        "token_usage",
        "harness_failure",
        "semantic_objects",
    }
)
EXPERIMENT_TEXT_FIELDS = (
    "hypothesis",
    "intervention",
    "affected_class",
    "mechanism",
    "predicted_direction",
    "regression_risk",
    "subsystem",
    "generality_rationale",
)
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


class AutoresearchError(ValueError):
    """Raised when an optimization artifact violates the custody protocol."""


@dataclass(frozen=True)
class AutoresearchConfig:
    """Resolved, validated paths and policy values for one workspace."""

    workspace: Path
    config_path: Path
    config_sha256: str
    freeze_a_commit: str | None
    baseline_commit: str | None
    guardian_public_key_sha256: str | None
    score_artifact_required: bool
    run_manifest_required: bool
    expected_train_count: int
    expected_dev_a_count: int
    expected_dev_b_count: int
    dev_b_max_evaluations: int
    train_ids: tuple[str, ...]
    train_id_set: frozenset[str]
    dev_a_ids: tuple[str, ...]
    dev_a_id_set: frozenset[str]
    dev_b_ids: tuple[str, ...]
    dev_b_id_set: frozenset[str]
    test_ids: tuple[str, ...]
    test_id_set: frozenset[str]
    forbidden_fields: frozenset[str]
    public_manifest_path: Path
    state_dir: Path
    ledger_path: Path

    @property
    def baseline_path(self) -> Path:
        return self.state_dir / "baseline.json"

    @property
    def baseline_outputs_path(self) -> Path:
        return (
            self.workspace
            / "experiments"
            / "autoresearch"
            / "raw"
            / "baseline_outputs.jsonl"
        )

    @property
    def baseline_run_manifest_path(self) -> Path:
        return (
            self.workspace
            / "experiments"
            / "autoresearch"
            / "raw"
            / "baseline"
            / "run.json"
        )

    @property
    def public_dev_a_path(self) -> Path:
        return self.state_dir / "public_dev_a_questions.jsonl"

    @property
    def regression_suite_path(self) -> Path:
        return self.state_dir / "regression_suite.jsonl"

    @property
    def candidate_registry_path(self) -> Path:
        return self.state_dir / "candidates.jsonl"

    @property
    def stop_path(self) -> Path:
        return self.state_dir / "STOP.json"

    @property
    def stop_anchor_path(self) -> Path:
        return self.state_dir / "OPTIMIZATION_STOPPED.anchor.json"


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _display_path(path: Path, workspace: Path) -> str:
    return path.relative_to(workspace).as_posix()


def _resolve_inside(workspace: Path, path: Path | str, description: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(workspace)
    except (OSError, ValueError) as error:
        raise AutoresearchError(
            f"{description} must resolve inside workspace"
        ) from error
    return resolved


def _unresolved_inside(workspace: Path, path: Path | str, description: str) -> Path:
    """Confine a path lexically while preserving its final no-follow component."""
    resolved_workspace = workspace.resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = resolved_workspace / candidate
    try:
        relative = candidate.relative_to(resolved_workspace)
    except ValueError as error:
        raise AutoresearchError(
            f"{description} must resolve inside workspace"
        ) from error
    if not relative.parts or ".." in relative.parts:
        raise AutoresearchError(f"{description} must resolve inside workspace")
    return resolved_workspace / relative


def _read_json(path: Path, description: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AutoresearchError(f"cannot read valid {description} JSON") from error


def _read_ids(path: Path) -> tuple[str, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise AutoresearchError("cannot read train ID manifest") from error
    if not lines:
        raise AutoresearchError("train ID manifest is empty")
    seen: set[str] = set()
    for line_number, instance_id in enumerate(lines, start=1):
        if not instance_id:
            raise AutoresearchError(f"blank train ID at line {line_number}")
        if instance_id in seen:
            raise AutoresearchError(f"duplicate train ID at line {line_number}")
        seen.add(instance_id)
    return tuple(lines)


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AutoresearchError(f"{name} must be a non-empty string")
    return value


def _require_commit(value: str) -> str:
    if not isinstance(value, str) or COMMIT_PATTERN.fullmatch(value) is None:
        raise AutoresearchError("git_commit must be a full lowercase hexadecimal hash")
    return value


def load_config(
    path: Path,
    *,
    workspace: Path,
    freeze_a_commit: str | None = None,
    baseline_commit: str | None = None,
) -> AutoresearchConfig:
    """Load path-confined autoresearch configuration and committed train IDs."""
    try:
        resolved_workspace = Path(workspace).resolve(strict=True)
    except OSError as error:
        raise AutoresearchError("workspace does not exist") from error
    resolved_config = _resolve_inside(
        resolved_workspace, Path(path), "autoresearch config"
    )
    if resolved_config != resolved_workspace / "config" / "autoresearch.json":
        raise AutoresearchError("autoresearch config must use the canonical path")
    try:
        raw_config = resolved_config.read_bytes()
        value = json.loads(raw_config)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AutoresearchError("cannot read valid autoresearch config JSON") from error
    if not isinstance(value, dict):
        raise AutoresearchError("autoresearch config must be a JSON object")
    missing = REQUIRED_CONFIG_FIELDS - value.keys()
    if missing:
        raise AutoresearchError("autoresearch config is missing required fields")

    count_fields = (
        "expected_train_count",
        "expected_dev_a_count",
        "expected_dev_b_count",
        "dev_b_max_evaluations",
    )
    counts: dict[str, int] = {}
    for field in count_fields:
        count_value = value[field]
        if (
            isinstance(count_value, bool)
            or not isinstance(count_value, int)
            or count_value <= 0
        ):
            raise AutoresearchError(f"{field} must be a positive integer")
        counts[field] = count_value
    if counts["dev_b_max_evaluations"] > 10:
        raise AutoresearchError("dev_b_max_evaluations must not exceed 10")
    guardian_pin_value = value["guardian_public_key_sha256"]
    guardian_public_key_sha256: str | None
    if guardian_pin_value == "UNPROVISIONED":
        if freeze_a_commit is not None:
            raise AutoresearchError(
                "dev-B guardian key must be provisioned before Freeze A"
            )
        guardian_public_key_sha256 = None
    elif (
        isinstance(guardian_pin_value, str)
        and re.fullmatch(r"[0-9a-f]{64}", guardian_pin_value) is not None
    ):
        guardian_public_key_sha256 = guardian_pin_value
    else:
        raise AutoresearchError(
            "guardian_public_key_sha256 must be a SHA-256 digest or UNPROVISIONED"
        )
    forbidden = value["forbidden_fields"]
    if (
        not isinstance(forbidden, list)
        or not forbidden
        or any(not isinstance(field, str) or not field for field in forbidden)
        or len(set(forbidden)) != len(forbidden)
    ):
        raise AutoresearchError(
            "forbidden_fields must contain unique non-empty strings"
        )

    train_ids_path = _resolve_inside(
        resolved_workspace, value["train_ids_path"], "train ID manifest"
    )
    dev_a_ids_path = _resolve_inside(
        resolved_workspace, value["dev_a_ids_path"], "dev-A ID manifest"
    )
    dev_b_ids_path = _resolve_inside(
        resolved_workspace, value["dev_b_ids_path"], "dev-B ID manifest"
    )
    test_ids_path = _resolve_inside(
        resolved_workspace, value["test_ids_path"], "test ID manifest"
    )
    public_manifest_path = _resolve_inside(
        resolved_workspace, value["public_manifest_path"], "public manifest"
    )
    state_dir = _resolve_inside(
        resolved_workspace, value["state_dir"], "state directory"
    )
    ledger_path = _resolve_inside(
        resolved_workspace, value["ledger_path"], "experiment ledger"
    )
    train_ids = _read_ids(train_ids_path)
    dev_a_ids = _read_ids(dev_a_ids_path)
    dev_b_ids = _read_ids(dev_b_ids_path)
    test_ids = _read_ids(test_ids_path)
    if len(train_ids) != counts["expected_train_count"]:
        raise AutoresearchError(
            "train ID manifest count does not match expected_train_count"
        )
    if len(dev_a_ids) != counts["expected_dev_a_count"]:
        raise AutoresearchError("dev-A ID count does not match expected_dev_a_count")
    if len(dev_b_ids) != counts["expected_dev_b_count"]:
        raise AutoresearchError("dev-B ID count does not match expected_dev_b_count")
    if set(dev_a_ids) & set(dev_b_ids) or set(dev_a_ids) | set(dev_b_ids) != set(
        train_ids
    ):
        raise AutoresearchError("dev-A and dev-B must exactly partition the train IDs")
    if set(train_ids) & set(test_ids):
        raise AutoresearchError("train and test IDs must be disjoint")
    canonical_paths = {
        "train_ids_path": "data/manifests/train_ids.txt",
        "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
        "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
        "test_ids_path": "data/manifests/test_ids.txt",
        "public_manifest_path": "data/manifests/eligible_questions.jsonl",
        "state_dir": "experiments/autoresearch/state",
        "ledger_path": "experiments/autoresearch/ledger.jsonl",
    }
    if any(value.get(field) != expected for field, expected in canonical_paths.items()):
        raise AutoresearchError(
            "autoresearch config paths must match the canonical layout"
        )
    _verify_committed_freeze_a_files(
        resolved_workspace,
        (
            resolved_config,
            train_ids_path,
            dev_a_ids_path,
            dev_b_ids_path,
            test_ids_path,
            public_manifest_path,
            resolved_workspace / "data" / "manifests" / "manifest_metadata.json",
            resolved_workspace / "data" / "manifests" / "split_metadata.json",
            resolved_workspace
            / "data"
            / "manifests"
            / "development_split_metadata.json",
        ),
        freeze_a_commit=freeze_a_commit,
    )
    configured_decisions = value.get("decisions")
    if configured_decisions is not None and (
        not isinstance(configured_decisions, list)
        or set(configured_decisions) != DECISIONS
    ):
        raise AutoresearchError("configured decisions do not match the protocol")
    trace_policy = value.get("trace_policy", {})
    if not isinstance(trace_policy, dict):
        raise AutoresearchError("trace_policy must be an object")
    score_artifact_required = trace_policy.get(
        "generation_and_scoring_records_are_immutable_and_separate", False
    )
    if not isinstance(score_artifact_required, bool):
        raise AutoresearchError(
            "generation/scoring separation policy must be a boolean"
        )
    run_manifest_required = trace_policy.get("scaled_runs_require_run_manifest", False)
    if not isinstance(run_manifest_required, bool):
        raise AutoresearchError("run-manifest policy must be a boolean")
    return AutoresearchConfig(
        workspace=resolved_workspace,
        config_path=resolved_config,
        config_sha256=_sha256_bytes(raw_config),
        freeze_a_commit=freeze_a_commit,
        baseline_commit=baseline_commit,
        guardian_public_key_sha256=guardian_public_key_sha256,
        score_artifact_required=score_artifact_required,
        run_manifest_required=run_manifest_required,
        expected_train_count=counts["expected_train_count"],
        expected_dev_a_count=counts["expected_dev_a_count"],
        expected_dev_b_count=counts["expected_dev_b_count"],
        dev_b_max_evaluations=counts["dev_b_max_evaluations"],
        train_ids=train_ids,
        train_id_set=frozenset(train_ids),
        dev_a_ids=dev_a_ids,
        dev_a_id_set=frozenset(dev_a_ids),
        dev_b_ids=dev_b_ids,
        dev_b_id_set=frozenset(dev_b_ids),
        test_ids=test_ids,
        test_id_set=frozenset(test_ids),
        forbidden_fields=frozenset(forbidden) | MANDATORY_FORBIDDEN_FIELDS,
        public_manifest_path=public_manifest_path,
        state_dir=state_dir,
        ledger_path=ledger_path,
    )


def _verify_committed_freeze_a_files(
    workspace: Path,
    paths: Sequence[Path],
    *,
    freeze_a_commit: str | None,
) -> None:
    if not (workspace / ".git").exists():
        return
    if freeze_a_commit is None or COMMIT_PATTERN.fullmatch(freeze_a_commit) is None:
        raise AutoresearchError(
            "a full externally recorded Freeze-A commit is required"
        )
    try:
        canonical_commit = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "rev-parse",
                f"{freeze_a_commit}^{{commit}}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise AutoresearchError("Freeze-A commit is not available in git") from error
    if canonical_commit != freeze_a_commit:
        raise AutoresearchError("Freeze-A commit must be the full canonical hash")
    for path in paths:
        relative = path.relative_to(workspace).as_posix()
        try:
            completed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(workspace),
                    "show",
                    f"{freeze_a_commit}:{relative}",
                ],
                check=True,
                capture_output=True,
            )
            current = path.read_bytes()
        except (OSError, subprocess.CalledProcessError) as error:
            raise AutoresearchError(
                "Freeze-A configuration and manifests must be committed"
            ) from error
        if completed.stdout != current:
            raise AutoresearchError(
                "Freeze-A configuration and manifests must match the recorded commit"
            )


def _find_forbidden(value: Any, forbidden_fields: frozenset[str]) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in forbidden_fields:
                return key
            found = _find_forbidden(nested, forbidden_fields)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_forbidden(nested, forbidden_fields)
            if found is not None:
                return found
    return None


def _consume_jsonl(
    handle: BinaryIO, description: str
) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for line_number, raw_line in enumerate(handle, start=1):
        digest.update(raw_line)
        if not raw_line.strip():
            raise AutoresearchError(
                f"{description} contains a blank line at {line_number}"
            )
        try:
            value = json.loads(raw_line)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise AutoresearchError(
                f"{description} line {line_number} is invalid JSON"
            ) from error
        if not isinstance(value, dict):
            raise AutoresearchError(
                f"{description} line {line_number} must be an object"
            )
        records.append(value)
    if not records:
        raise AutoresearchError(f"{description} is empty")
    return records, digest.hexdigest()


def _read_jsonl(path: Path, description: str) -> tuple[list[dict[str, Any]], str]:
    try:
        with path.open("rb") as handle:
            return _consume_jsonl(handle, description)
    except AutoresearchError:
        raise
    except OSError as error:
        raise AutoresearchError(f"cannot read {description}") from error


def _read_confined_jsonl(
    workspace: Path, path: Path, description: str
) -> tuple[list[dict[str, Any]], str]:
    parent_descriptor, _ = _open_confined_parent(workspace, path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_descriptor,
        )
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            return _consume_jsonl(handle, description)
    except AutoresearchError:
        raise
    except OSError as error:
        raise AutoresearchError(f"cannot read {description}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)


def _read_confined_private_jsonl(
    workspace: Path,
    path: Path,
    description: str,
    *,
    maximum_bytes: int,
) -> tuple[list[dict[str, Any]], str]:
    """Read private JSONL while enforcing the same file boundary as sidecars."""
    content = _read_confined_private_bytes(
        workspace,
        path,
        description,
        maximum_bytes=maximum_bytes,
    )
    return _consume_jsonl(io.BytesIO(content), description)


def _read_confined_private_bytes(
    workspace: Path,
    path: Path,
    description: str,
    *,
    maximum_bytes: int,
) -> bytes:
    """Read one private regular file through a no-follow descriptor boundary."""
    parent_descriptor, _ = _open_confined_parent(workspace, path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_descriptor,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise AutoresearchError(f"{description} must be a single-link regular file")
        if metadata.st_uid != os.getuid():
            raise AutoresearchError(f"{description} must be owned by the current user")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise AutoresearchError(f"{description} must have mode 0600")
        if metadata.st_size > maximum_bytes:
            raise AutoresearchError(f"{description} exceeds the byte limit")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            content = handle.read(maximum_bytes + 1)
        if len(content) > maximum_bytes:
            raise AutoresearchError(f"{description} exceeds the byte limit")
        return content
    except AutoresearchError:
        raise
    except OSError as error:
        raise AutoresearchError(f"cannot read {description}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)


def _open_confined_parent(workspace: Path, path: Path) -> tuple[int, Path]:
    resolved_workspace = workspace.resolve(strict=True)
    confined_path = _unresolved_inside(resolved_workspace, path, "artifact path")
    relative_parent = confined_path.relative_to(resolved_workspace).parent
    descriptor: int | None = os.open(
        resolved_workspace,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        for component in relative_parent.parts:
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        opened_parent = Path(f"/proc/self/fd/{descriptor}").resolve(strict=True)
        opened_parent.relative_to(resolved_workspace)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise AutoresearchError("artifact parent must be an owned directory")
    except AutoresearchError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except (OSError, ValueError) as error:
        if descriptor is not None:
            os.close(descriptor)
        raise AutoresearchError(
            "artifact parent must remain inside workspace"
        ) from error
    return descriptor, opened_parent / confined_path.name


def _write_exclusive(path: Path, content: bytes, *, workspace: Path) -> Path:
    parent_descriptor, destination = _open_confined_parent(workspace, path)
    temporary_name = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor: int | None = None
    try:
        try:
            os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise AutoresearchError(f"{path.name} already exists; refusing overwrite")
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_descriptor,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary_name,
                path.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            raise AutoresearchError(
                f"{path.name} already exists; refusing overwrite"
            ) from error
        os.fsync(parent_descriptor)
    except AutoresearchError:
        raise
    except OSError as error:
        raise AutoresearchError(
            f"cannot create immutable artifact {path.name}"
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=parent_descriptor)
        except FileNotFoundError:
            pass
        os.close(parent_descriptor)
    return destination


def _public_records_by_id(config: AutoresearchConfig) -> dict[str, dict[str, Any]]:
    records, _ = _read_jsonl(config.public_manifest_path, "public question manifest")
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        forbidden = _find_forbidden(record, config.forbidden_fields)
        if forbidden is not None:
            raise AutoresearchError("public manifest contains a forbidden field")
        instance_id = record.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            raise AutoresearchError("public manifest has an invalid instance_id")
        if instance_id in by_id:
            raise AutoresearchError("public manifest contains a duplicate instance_id")
        by_id[instance_id] = record
    return by_id


def _public_view_content(
    config: AutoresearchConfig, instance_ids: Sequence[str]
) -> bytes:
    by_id = _public_records_by_id(config)
    missing = set(instance_ids) - by_id.keys()
    if missing:
        raise AutoresearchError(
            "public manifest is missing committed development questions"
        )
    return b"".join(
        _canonical_bytes(by_id[instance_id]) for instance_id in instance_ids
    )


def create_public_dev_a_view(config: AutoresearchConfig) -> Path:
    """Materialize only public dev-A records for routine optimization."""
    if config.stop_path.exists() or config.stop_anchor_path.exists():
        raise AutoresearchError("optimization has stopped; state changes are forbidden")
    return _write_exclusive(
        config.public_dev_a_path,
        _public_view_content(config, config.dev_a_ids),
        workspace=config.workspace,
    )

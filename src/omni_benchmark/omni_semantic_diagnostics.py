"""Bounded read-only diagnostics for failed public Omni semantic deployments."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from .omni_result_adapter import OmniResultContractError, reject_forbidden_keys
from .omni_semantic_deploy_cli import OmniDeploymentCli, committed_bundle_plan
from .omni_semantic_deployment import OmniSemanticDeploymentPlan

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_SOURCE_SCHEMA_VERSIONS = frozenset({1, 2})
_MAX_SOURCE_BYTES = 1024 * 1024
_MAX_DIAGNOSTIC_BYTES = 1024 * 1024
_MAX_ISSUES = 512
_MAX_DEPTH = 12
_MAX_NODES = 10_000
_MAX_KEY_CHARACTERS = 256
_MAX_STRING_CHARACTERS = 16_384
_SECRET_KEY_PARTS = (
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "privatekey",
    "secret",
    "token",
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|github_pat)-?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:postgres(?:ql)?|https?)://[^\s/:@]+:[^\s@]+@", re.IGNORECASE),
)


class PublicValidatorDiagnosticError(RuntimeError):
    """Raised when a public validator diagnostic cannot proceed safely."""


class ValidatorClient(Protocol):
    """The read-only product boundary used by this diagnostic."""

    def validate(self, model_id: str, branch_id: str) -> object: ...


@dataclass(frozen=True)
class _SourceDeployment:
    database: str
    run_id: str
    source_commit: str
    manifest_sha256: str
    model_id: str
    branch_id: str
    issue_count: int
    record_sha256: str


@dataclass(frozen=True)
class PublicValidatorDiagnostic:
    """One append-only secret-rejecting public validator observation."""

    database: str
    run_id: str
    observed_at: str
    source_deployment_run_id: str
    source_deployment_record_sha256: str
    source_commit: str
    manifest_sha256: str
    model_id: str
    branch_id: str
    source_issue_count: int
    observed_issue_count: int | None
    issues: list[Any] | None
    issues_sha256: str | None
    status: str
    failure_detail: str | None

    def to_json(self) -> str:
        return (
            json.dumps(
                {
                    "kind": "public-omni-validator-diagnostic",
                    "schema_version": 1,
                    **asdict(self),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )


ClientFactory = Callable[[str], ValidatorClient]
PlanLoader = Callable[[Path, str, str], OmniSemanticDeploymentPlan]


def diagnostic_main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    plan_loader: PlanLoader | None = None,
    observed_at: Callable[[], str] | None = None,
) -> int:
    """Capture exact validator payloads without modifying product resources."""
    arguments = _parser().parse_args(argv)
    if not arguments.execute_live_validation:
        raise PublicValidatorDiagnosticError(
            "live validation requires explicit acknowledgement"
        )
    databases = tuple(arguments.database)
    if len(databases) != len(set(databases)):
        raise PublicValidatorDiagnosticError("duplicate database selection")
    for database in databases:
        _require_safe_id(database, "database")
    _require_safe_id(arguments.source_run_id, "source run ID")
    _require_safe_id(arguments.run_id, "run ID")
    workspace = arguments.workspace.resolve(strict=True)
    source_root = arguments.source_deployment_root.resolve(strict=True)
    load_plan = committed_bundle_plan if plan_loader is None else plan_loader
    sources = tuple(
        _load_source_deployment(
            source_root=source_root,
            source_run_id=arguments.source_run_id,
            database=database,
            workspace=workspace,
            plan_loader=load_plan,
        )
        for database in databases
    )
    commits = {source.source_commit for source in sources}
    if len(commits) != 1:
        raise PublicValidatorDiagnosticError(
            "source deployment records do not share one source commit"
        )
    _claim_run(
        arguments.output_root,
        arguments.run_id,
        arguments.source_run_id,
        sources,
    )
    client = (
        OmniDeploymentCli(
            arguments.profile,
            minimum_request_interval_seconds=arguments.minimum_request_interval_seconds,
        )
        if client_factory is None
        else client_factory(arguments.profile)
    )
    now = (
        datetime.now().astimezone().isoformat(timespec="seconds")
        if observed_at is None
        else observed_at()
    )
    records: list[PublicValidatorDiagnostic] = []
    for source in sources:
        record = _capture_one(
            source=source,
            diagnostic_run_id=arguments.run_id,
            observed_at=now,
            client=client,
        )
        records.append(record)
        path = _write_record(arguments.output_root, record)
        print(
            _compact_json(
                {
                    "database": record.database,
                    "observed_issue_count": record.observed_issue_count,
                    "record": str(path),
                    "status": record.status,
                }
            )
        )
    captured = sum(record.status == "captured" for record in records)
    print(
        _compact_json(
            {
                "captured": captured,
                "run_id": arguments.run_id,
                "total": len(records),
            }
        )
    )
    return 0 if captured == len(records) else 1


def _load_source_deployment(
    *,
    source_root: Path,
    source_run_id: str,
    database: str,
    workspace: Path,
    plan_loader: PlanLoader,
) -> _SourceDeployment:
    path = source_root / f"{source_run_id}.{database}.json"
    try:
        content = _read_regular_file(path)
        value = json.loads(content)
    except PublicValidatorDiagnosticError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicValidatorDiagnosticError(
            "source deployment record could not be read"
        ) from error
    if not isinstance(value, dict):
        raise PublicValidatorDiagnosticError(
            "source deployment record must be an object"
        )
    if (
        value.get("kind") != "public-omni-semantic-deployment"
        or value.get("schema_version") not in _SOURCE_SCHEMA_VERSIONS
    ):
        raise PublicValidatorDiagnosticError("source deployment schema is invalid")
    if value.get("database") != database or value.get("run_id") != source_run_id:
        raise PublicValidatorDiagnosticError(
            "source deployment identity does not match"
        )
    if (
        value.get("status") != "failed"
        or value.get("failure_stage") != "validation"
        or value.get("readback_verified") is not False
    ):
        raise PublicValidatorDiagnosticError(
            "source must be a failed validation record"
        )
    source_commit = value.get("source_commit")
    manifest_sha256 = value.get("manifest_sha256")
    model_id = value.get("model_id")
    branch_id = value.get("branch_id")
    issue_count = value.get("validation_issue_count")
    if not isinstance(source_commit, str) or _HEX_40.fullmatch(source_commit) is None:
        raise PublicValidatorDiagnosticError("source commit is invalid")
    if (
        not isinstance(manifest_sha256, str)
        or _HEX_64.fullmatch(manifest_sha256) is None
    ):
        raise PublicValidatorDiagnosticError("source manifest is invalid")
    if not all(isinstance(value, str) and value for value in (model_id, branch_id)):
        raise PublicValidatorDiagnosticError("source model and branch IDs are required")
    if (
        isinstance(issue_count, bool)
        or not isinstance(issue_count, int)
        or issue_count <= 0
    ):
        raise PublicValidatorDiagnosticError("source requires a positive issue count")
    plan = plan_loader(workspace, source_commit, database)
    if plan.manifest_sha256 != manifest_sha256:
        raise PublicValidatorDiagnosticError(
            "source deployment manifest does not match committed bundle"
        )
    return _SourceDeployment(
        database=database,
        run_id=source_run_id,
        source_commit=source_commit,
        manifest_sha256=manifest_sha256,
        model_id=model_id,
        branch_id=branch_id,
        issue_count=issue_count,
        record_sha256=hashlib.sha256(content).hexdigest(),
    )


def _capture_one(
    *,
    source: _SourceDeployment,
    diagnostic_run_id: str,
    observed_at: str,
    client: ValidatorClient,
) -> PublicValidatorDiagnostic:
    try:
        raw_issues = client.validate(source.model_id, source.branch_id)
    except Exception as error:  # Product failures are durable without response data.
        return _record(
            source,
            diagnostic_run_id,
            observed_at,
            status="product_error",
            failure_detail=f"product validation request failed: {type(error).__name__}",
        )
    try:
        issues = _sanitize_issues(raw_issues)
    except PublicValidatorDiagnosticError:
        return _record(
            source,
            diagnostic_run_id,
            observed_at,
            status="rejected",
            failure_detail="validator payload rejected",
        )
    serialized = _compact_json(issues)
    observed_count = len(issues)
    status = "captured" if observed_count == source.issue_count else "drifted"
    return _record(
        source,
        diagnostic_run_id,
        observed_at,
        status=status,
        failure_detail=(
            None
            if status == "captured"
            else "validator issue count differs from source deployment"
        ),
        observed_count=observed_count,
        issues=issues,
        issues_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
    )


def _record(
    source: _SourceDeployment,
    diagnostic_run_id: str,
    observed_at: str,
    *,
    status: str,
    failure_detail: str | None,
    observed_count: int | None = None,
    issues: list[Any] | None = None,
    issues_sha256: str | None = None,
) -> PublicValidatorDiagnostic:
    return PublicValidatorDiagnostic(
        database=source.database,
        run_id=diagnostic_run_id,
        observed_at=observed_at,
        source_deployment_run_id=source.run_id,
        source_deployment_record_sha256=source.record_sha256,
        source_commit=source.source_commit,
        manifest_sha256=source.manifest_sha256,
        model_id=source.model_id,
        branch_id=source.branch_id,
        source_issue_count=source.issue_count,
        observed_issue_count=observed_count,
        issues=issues,
        issues_sha256=issues_sha256,
        status=status,
        failure_detail=failure_detail,
    )


def _sanitize_issues(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise PublicValidatorDiagnosticError("validator response must be an array")
    if len(value) > _MAX_ISSUES:
        raise PublicValidatorDiagnosticError("validator response has too many issues")
    try:
        reject_forbidden_keys(value)
    except OmniResultContractError as error:
        raise PublicValidatorDiagnosticError(
            "validator response is forbidden"
        ) from error
    node_count = [0]
    sanitized = _sanitize_value(value, depth=0, node_count=node_count)
    assert isinstance(sanitized, list)
    if len(_compact_json(sanitized).encode("utf-8")) > _MAX_DIAGNOSTIC_BYTES:
        raise PublicValidatorDiagnosticError("validator response is too large")
    return sanitized


def _sanitize_value(value: object, *, depth: int, node_count: list[int]) -> Any:
    node_count[0] += 1
    if depth > _MAX_DEPTH or node_count[0] > _MAX_NODES:
        raise PublicValidatorDiagnosticError("validator response is too complex")
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PublicValidatorDiagnosticError("validator response is non-finite")
        return value
    if isinstance(value, str):
        if len(value) > _MAX_STRING_CHARACTERS or any(
            pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS
        ):
            raise PublicValidatorDiagnosticError("validator string is unsafe")
        return value
    if isinstance(value, list):
        return [
            _sanitize_value(item, depth=depth + 1, node_count=node_count)
            for item in value
        ]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str) or len(key) > _MAX_KEY_CHARACTERS:
                raise PublicValidatorDiagnosticError("validator key is invalid")
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                raise PublicValidatorDiagnosticError("validator key is secret-bearing")
            result[key] = _sanitize_value(
                nested, depth=depth + 1, node_count=node_count
            )
        return result
    raise PublicValidatorDiagnosticError("validator response is not JSON-compatible")


def _claim_run(
    output_root: Path,
    run_id: str,
    source_run_id: str,
    sources: tuple[_SourceDeployment, ...],
) -> Path:
    if output_root.exists():
        metadata = output_root.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or output_root.is_symlink():
            raise PublicValidatorDiagnosticError("diagnostic run could not be claimed")
    try:
        for source in sources:
            if _record_path(output_root, run_id, source.database).exists():
                raise PublicValidatorDiagnosticError(
                    f"diagnostic record already exists for {source.database}"
                )
        output_root.mkdir(parents=True, exist_ok=True)
        path = output_root / f"{run_id}.claim"
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            payload = _compact_json(
                {
                    "databases": sorted(source.database for source in sources),
                    "kind": "public-omni-validator-diagnostic-claim",
                    "run_id": run_id,
                    "schema_version": 1,
                    "source_commit": sources[0].source_commit,
                    "source_deployment_run_id": source_run_id,
                }
            )
            os.write(descriptor, f"{payload}\n".encode("utf-8"))
        finally:
            os.close(descriptor)
        return path
    except FileExistsError as error:
        raise PublicValidatorDiagnosticError(
            "diagnostic run is already claimed"
        ) from error
    except PublicValidatorDiagnosticError:
        raise
    except OSError as error:
        raise PublicValidatorDiagnosticError(
            "diagnostic run could not be claimed"
        ) from error


def _write_record(root: Path, record: PublicValidatorDiagnostic) -> Path:
    path = _record_path(root, record.run_id, record.database)
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(descriptor, record.to_json().encode("utf-8"))
        finally:
            os.close(descriptor)
        return path
    except FileExistsError as error:
        raise PublicValidatorDiagnosticError(
            f"diagnostic record already exists for {record.database}"
        ) from error
    except OSError as error:
        raise PublicValidatorDiagnosticError(
            "diagnostic record could not be written"
        ) from error


def _record_path(root: Path, run_id: str, database: str) -> Path:
    _require_safe_id(run_id, "run ID")
    _require_safe_id(database, "database")
    return root / f"{run_id}.{database}.json"


def _read_regular_file(path: Path) -> bytes:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise PublicValidatorDiagnosticError(
                    "source deployment record must be a regular file"
                )
            if metadata.st_size > _MAX_SOURCE_BYTES:
                raise PublicValidatorDiagnosticError(
                    "source deployment record is too large"
                )
            chunks: list[bytes] = []
            remaining = metadata.st_size + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            if len(content) > _MAX_SOURCE_BYTES:
                raise PublicValidatorDiagnosticError(
                    "source deployment record is too large"
                )
            return content
        finally:
            os.close(descriptor)
    except PublicValidatorDiagnosticError:
        raise
    except OSError as error:
        raise PublicValidatorDiagnosticError(
            "source deployment record could not be read"
        ) from error


def _require_safe_id(value: str, description: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise PublicValidatorDiagnosticError(f"{description} is invalid")


def _request_interval(value: str) -> float:
    try:
        interval = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("request interval must be numeric") from error
    if not math.isfinite(interval) or interval < 0 or interval > 60:
        raise argparse.ArgumentTypeError("request interval is outside safe bounds")
    return interval


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-deployment-root", type=Path, required=True)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--database", action="append", required=True)
    parser.add_argument(
        "--minimum-request-interval-seconds",
        type=_request_interval,
        default=1.25,
    )
    parser.add_argument("--execute-live-validation", action="store_true")
    return parser


def _compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)

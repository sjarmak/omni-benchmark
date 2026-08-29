"""Live, isolated deployment of authenticated public Omni semantic bundles."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .omni_semantic_deployment import (
    OmniSemanticDeploymentError,
    OmniSemanticDeploymentPlan,
    build_semantic_deployment_plan,
    semantic_deployment_sha256,
    verify_semantic_deployment_readback,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
_AUTO_EXTENSION_FILES = frozenset({"model", "relationships"})
_ARCHAEOLOGY_DATABASE = "archeology_scan_large"
_READBACK_RETRY_DELAYS_SECONDS = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)


class SemanticDeploymentClient(Protocol):
    """The narrow product boundary required by one public deployment."""

    def ensure_shared_model(
        self, connection_id: str, name: str
    ) -> tuple[str, bool]: ...

    def ensure_branch(self, model_id: str, name: str) -> tuple[str, bool]: ...

    def upload_yaml(
        self, model_id: str, branch_id: str, path: str, content: str
    ) -> None: ...

    def validate(self, model_id: str, branch_id: str) -> object: ...

    def readback(self, model_id: str, branch_id: str) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class DeploymentRecord:
    """Secret-free terminal status for one database deployment attempt."""

    database: str
    run_id: str
    observed_at: str
    source_commit: str
    connection_id: str | None
    model_id: str | None
    branch_id: str | None
    model_name: str
    branch_name: str
    manifest_sha256: str
    file_sha256: Mapping[str, str]
    semantic_model_sha256: str | None
    file_count: int
    uploaded_file_count: int
    validation_issue_count: int | None
    readback_file_count: int
    readback_verified: bool
    status: str
    failure_stage: str | None
    failure_detail: str | None

    def to_json(self) -> str:
        """Render the canonical append-only record."""
        return (
            json.dumps(
                {
                    "kind": "public-omni-semantic-deployment",
                    "schema_version": 2,
                    **asdict(self),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )


class _StageFailure(RuntimeError):
    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(detail)
        self.stage = stage


def isolated_model_name(database: str) -> str:
    """Return the stable isolated shared-model name for a public baseline."""
    _require_safe_id(database, "database")
    if database == _ARCHAEOLOGY_DATABASE:
        return "livesqlbench-archeology-public-baseline-20260828"
    return f"livesqlbench-{database}-public-baseline-20260828"


def isolated_branch_name(database: str) -> str:
    """Return the stable isolated branch name for a public baseline."""
    _require_safe_id(database, "database")
    if database == _ARCHAEOLOGY_DATABASE:
        return "livesqlbench-archeology-public-baseline-v1"
    return f"livesqlbench-{database}-public-baseline-v1"


def deploy_public_bundle(
    *,
    bundle_root: Path,
    connection_id: str,
    client: SemanticDeploymentClient,
    run_id: str,
    source_commit: str,
    observed_at: str,
    readback_sleep: Callable[[float], None] = time.sleep,
) -> DeploymentRecord:
    """Authenticate and deploy one public bundle."""
    plan = build_semantic_deployment_plan(bundle_root)
    return deploy_public_plan(
        plan=plan,
        connection_id=connection_id,
        client=client,
        run_id=run_id,
        source_commit=source_commit,
        observed_at=observed_at,
        readback_sleep=readback_sleep,
    )


def deploy_public_plan(
    *,
    plan: OmniSemanticDeploymentPlan,
    connection_id: str,
    client: SemanticDeploymentClient,
    run_id: str,
    source_commit: str,
    observed_at: str,
    model_name: str | None = None,
    branch_name: str | None = None,
    readback_sleep: Callable[[float], None] = time.sleep,
) -> DeploymentRecord:
    """Deploy an authenticated immutable plan and retain terminal product failures."""
    if model_name is None:
        model_name = isolated_model_name(plan.database)
    else:
        _require_safe_id(model_name, "model name")
    if branch_name is None:
        branch_name = isolated_branch_name(plan.database)
    else:
        _require_safe_id(branch_name, "branch name")
    file_sha256 = {item.remote_path: item.sha256 for item in plan.files}
    model_id: str | None = None
    branch_id: str | None = None
    uploaded = 0
    validation_count: int | None = None
    readback_count = 0
    try:
        model_id, model_created = client.ensure_shared_model(connection_id, model_name)
        branch_id, branch_created = client.ensure_branch(model_id, branch_name)
        if not model_created and not branch_created:
            validation_count = _validation_issue_count(
                client.validate(model_id, branch_id)
            )
            if validation_count == 0:
                try:
                    readback_count, semantic_model_sha256 = _observe_exact_readback(
                        plan=plan,
                        client=client,
                        model_id=model_id,
                        branch_id=branch_id,
                        sleep=readback_sleep,
                    )
                    return _record(
                        plan=plan,
                        connection_id=connection_id,
                        model_id=model_id,
                        branch_id=branch_id,
                        model_name=model_name,
                        branch_name=branch_name,
                        run_id=run_id,
                        source_commit=source_commit,
                        observed_at=observed_at,
                        file_sha256=file_sha256,
                        uploaded=0,
                        validation_count=validation_count,
                        readback_count=readback_count,
                        semantic_model_sha256=semantic_model_sha256,
                    )
                except (OmniSemanticDeploymentError, _StageFailure):
                    pass
        for item in plan.files:
            try:
                content = item.content.decode("utf-8")
            except UnicodeError as error:
                raise _StageFailure("upload", "bundle file is not UTF-8") from error
            client.upload_yaml(model_id, branch_id, item.remote_path, content)
            uploaded += 1
        validation_count = _validation_issue_count(client.validate(model_id, branch_id))
        if validation_count:
            raise _StageFailure(
                "validation", f"validator returned {validation_count} issue(s)"
            )
        readback_count, semantic_model_sha256 = _observe_exact_readback(
            plan=plan,
            client=client,
            model_id=model_id,
            branch_id=branch_id,
            sleep=readback_sleep,
        )
        return _record(
            plan=plan,
            connection_id=connection_id,
            model_id=model_id,
            branch_id=branch_id,
            model_name=model_name,
            branch_name=branch_name,
            run_id=run_id,
            source_commit=source_commit,
            observed_at=observed_at,
            file_sha256=file_sha256,
            uploaded=uploaded,
            validation_count=validation_count,
            readback_count=readback_count,
            semantic_model_sha256=semantic_model_sha256,
        )
    except _StageFailure as error:
        stage, detail = error.stage, str(error)
    except OmniSemanticDeploymentError as error:
        stage, detail = "readback", str(error)
    except Exception as error:  # Boundary errors must become durable per-DB statuses.
        stage, detail = "product_api", type(error).__name__
    return _record(
        plan=plan,
        connection_id=connection_id,
        model_id=model_id,
        branch_id=branch_id,
        model_name=model_name,
        branch_name=branch_name,
        run_id=run_id,
        source_commit=source_commit,
        observed_at=observed_at,
        file_sha256=file_sha256,
        uploaded=uploaded,
        validation_count=validation_count,
        readback_count=readback_count,
        semantic_model_sha256=None,
        status="failed",
        failure_stage=stage,
        failure_detail=detail,
    )


def bundle_preflight_failure_record(
    *,
    database: str,
    run_id: str,
    source_commit: str,
    observed_at: str,
    detail: str,
) -> DeploymentRecord:
    """Represent an invalid committed bundle as an explicit per-database blocker."""
    return DeploymentRecord(
        database=database,
        run_id=run_id,
        observed_at=observed_at,
        source_commit=source_commit,
        connection_id=None,
        model_id=None,
        branch_id=None,
        model_name=isolated_model_name(database),
        branch_name=isolated_branch_name(database),
        manifest_sha256="",
        file_sha256={},
        semantic_model_sha256=None,
        file_count=0,
        uploaded_file_count=0,
        validation_issue_count=None,
        readback_file_count=0,
        readback_verified=False,
        status="failed",
        failure_stage="bundle_preflight",
        failure_detail=detail,
    )


def write_deployment_record(root: Path, record: DeploymentRecord) -> Path:
    """Create one mode-0600 status record without replacing prior evidence."""
    path = deployment_record_path(root, record.run_id, record.database)
    root.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, record.to_json().encode("utf-8"))
    finally:
        os.close(descriptor)
    return path


def deployment_record_path(root: Path, run_id: str, database: str) -> Path:
    """Validate one append-only status identity before any product mutation."""
    _require_safe_id(run_id, "run_id")
    _require_safe_id(database, "database")
    return root / f"{run_id}.{database}.json"


def _verify_readback(
    plan: OmniSemanticDeploymentPlan, readback: Mapping[str, str]
) -> tuple[int, str]:
    if not isinstance(readback, Mapping):
        raise _StageFailure("readback", "readback files must be a mapping")
    expected = {item.remote_path for item in plan.files}
    actual = set(readback)
    unexpected = actual - expected - _AUTO_EXTENSION_FILES
    if unexpected:
        raise _StageFailure("readback", "isolated branch contains unexpected files")
    selected = {path: readback[path] for path in expected if path in readback}
    verify_semantic_deployment_readback(plan, selected)
    return len(selected), semantic_deployment_sha256(plan)


def _observe_exact_readback(
    *,
    plan: OmniSemanticDeploymentPlan,
    client: SemanticDeploymentClient,
    model_id: str,
    branch_id: str,
    sleep: Callable[[float], None],
    retry_delays: Sequence[float] = _READBACK_RETRY_DELAYS_SECONDS,
) -> tuple[int, str]:
    first_mismatch: OmniSemanticDeploymentError | None = None
    for delay in (*retry_delays, None):
        try:
            return _verify_readback(plan, client.readback(model_id, branch_id))
        except OmniSemanticDeploymentError as error:
            if not _is_retryable_readback_mismatch(error):
                raise
            if first_mismatch is None:
                first_mismatch = error
            if delay is None:
                raise OmniSemanticDeploymentError(
                    "readback did not converge after "
                    f"{len(retry_delays) + 1} observations: {first_mismatch}"
                ) from error
            sleep(delay)
    raise AssertionError("readback observation loop did not terminate")


def _is_retryable_readback_mismatch(error: OmniSemanticDeploymentError) -> bool:
    detail = str(error)
    return detail == "readback path set does not match plan" or detail.startswith(
        "readback semantic content differs for "
    )


def _validation_issue_count(value: object) -> int:
    if not isinstance(value, list):
        raise _StageFailure("validation", "validator response must be an array")
    return len(value)


def _record(
    *,
    plan: OmniSemanticDeploymentPlan,
    connection_id: str,
    model_id: str | None,
    branch_id: str | None,
    model_name: str,
    branch_name: str,
    run_id: str,
    source_commit: str,
    observed_at: str,
    file_sha256: Mapping[str, str],
    uploaded: int,
    validation_count: int | None,
    readback_count: int,
    semantic_model_sha256: str | None,
    status: str = "verified",
    failure_stage: str | None = None,
    failure_detail: str | None = None,
) -> DeploymentRecord:
    return DeploymentRecord(
        database=plan.database,
        run_id=run_id,
        observed_at=observed_at,
        source_commit=source_commit,
        connection_id=connection_id,
        model_id=model_id,
        branch_id=branch_id,
        model_name=model_name,
        branch_name=branch_name,
        manifest_sha256=plan.manifest_sha256,
        file_sha256=dict(file_sha256),
        semantic_model_sha256=semantic_model_sha256,
        file_count=len(plan.files),
        uploaded_file_count=uploaded,
        validation_issue_count=validation_count,
        readback_file_count=readback_count,
        readback_verified=status == "verified",
        status=status,
        failure_stage=failure_stage,
        failure_detail=failure_detail,
    )


def _require_safe_id(value: str, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a bounded identifier")

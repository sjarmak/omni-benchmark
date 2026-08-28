from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from omni_benchmark.omni_semantic_deploy_live import (
    DeploymentRecord,
    deploy_public_bundle,
    isolated_branch_name,
    isolated_model_name,
    write_deployment_record,
)


DATABASE = "sample_large"
VIEW_NAME = f"{DATABASE}.public__events.view"
VIEW_PATH = f"{DATABASE}.public/events.view"
TOPIC_NAME = "events_semantics.topic"
VIEW = """label: Events
catalog: sample_large
schema: public
table_name: events
dimensions:
  public_metric:
    sql: ${amount} * 2
"""
TOPIC = """base_view: sample_large_public__events
label: Events
fields: [sample_large_public__events.*]
joins: {}
"""


def _bundle(tmp_path: Path) -> Path:
    root = tmp_path / DATABASE / "bundle"
    root.mkdir(parents=True)
    files = {VIEW_NAME: VIEW.encode(), TOPIC_NAME: TOPIC.encode()}
    for name, content in files.items():
        (root / name).write_bytes(content)
    manifest = {
        "database": DATABASE,
        "files": [
            {
                "file": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for name, content in files.items()
        ],
        "kind": "public-omni-semantic-bundle",
        "schema_version": 1,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    return root


def _readback() -> dict[str, str]:
    return {
        "model": "{}\n",
        "relationships": "[]\n",
        VIEW_PATH: """# Reference this view as sample_large_public__events
dimensions:
  public_metric:
    sql: ${amount} * 2
label: Events
""",
        TOPIC_NAME: """joins: {}
fields: [sample_large_public__events.*]
label: Events
base_view: sample_large_public__events
""",
    }


class FakeDeploymentClient:
    def __init__(
        self,
        *,
        existing: bool,
        readbacks: list[dict[str, str]] | None = None,
        validation: object = None,
    ) -> None:
        self.existing = existing
        self.readbacks = list(readbacks or [_readback()])
        self.validation = [] if validation is None else validation
        self.uploads: list[tuple[str, str, str, str]] = []
        self.created_models: list[tuple[str, str]] = []
        self.created_branches: list[tuple[str, str]] = []

    def ensure_shared_model(self, connection_id: str, name: str) -> tuple[str, bool]:
        if not self.existing:
            self.created_models.append((connection_id, name))
        return "model-id", not self.existing

    def ensure_branch(self, model_id: str, name: str) -> tuple[str, bool]:
        if not self.existing:
            self.created_branches.append((model_id, name))
        return "branch-id", not self.existing

    def upload_yaml(
        self, model_id: str, branch_id: str, path: str, content: str
    ) -> None:
        self.uploads.append((model_id, branch_id, path, content))

    def validate(self, model_id: str, branch_id: str) -> object:
        return self.validation

    def readback(self, model_id: str, branch_id: str) -> dict[str, str]:
        if len(self.readbacks) > 1:
            return self.readbacks.pop(0)
        return self.readbacks[0]


def test_existing_exact_branch_is_verified_without_reupload(tmp_path: Path) -> None:
    client = FakeDeploymentClient(existing=True)

    record = deploy_public_bundle(
        bundle_root=_bundle(tmp_path),
        connection_id="connection-id",
        client=client,
        run_id="deployment-1",
        source_commit="a" * 40,
        observed_at="2026-08-28T12:00:00-04:00",
    )

    assert record.status == "verified"
    assert record.uploaded_file_count == 0
    assert record.readback_verified is True
    assert record.validation_issue_count == 0
    assert client.uploads == []
    assert record.file_sha256 == {
        TOPIC_NAME: hashlib.sha256(TOPIC.encode()).hexdigest(),
        VIEW_PATH: hashlib.sha256(VIEW.encode()).hexdigest(),
    }


def test_new_branch_uploads_all_files_then_requires_exact_readback(
    tmp_path: Path,
) -> None:
    client = FakeDeploymentClient(existing=False)

    record = deploy_public_bundle(
        bundle_root=_bundle(tmp_path),
        connection_id="connection-id",
        client=client,
        run_id="deployment-1",
        source_commit="b" * 40,
        observed_at="2026-08-28T12:00:00-04:00",
    )

    assert record.status == "verified"
    assert record.uploaded_file_count == 2
    assert {upload[2] for upload in client.uploads} == {VIEW_PATH, TOPIC_NAME}
    assert client.created_models == [("connection-id", isolated_model_name(DATABASE))]
    assert client.created_branches == [("model-id", isolated_branch_name(DATABASE))]


def test_partial_existing_branch_is_repaired_but_unexpected_files_fail_closed(
    tmp_path: Path,
) -> None:
    initial = {"model": "{}\n", "relationships": "[]\n"}
    final = {**_readback(), "unrelated.topic": "label: Unexpected\n"}
    client = FakeDeploymentClient(existing=True, readbacks=[initial, final])

    record = deploy_public_bundle(
        bundle_root=_bundle(tmp_path),
        connection_id="connection-id",
        client=client,
        run_id="deployment-1",
        source_commit="c" * 40,
        observed_at="2026-08-28T12:00:00-04:00",
    )

    assert record.status == "failed"
    assert record.failure_stage == "readback"
    assert record.readback_verified is False
    assert record.uploaded_file_count == 2


def test_validation_issues_are_preserved_as_failure_not_raised(tmp_path: Path) -> None:
    client = FakeDeploymentClient(existing=False, validation=[{"type": "bad_sql"}])

    record = deploy_public_bundle(
        bundle_root=_bundle(tmp_path),
        connection_id="connection-id",
        client=client,
        run_id="deployment-1",
        source_commit="d" * 40,
        observed_at="2026-08-28T12:00:00-04:00",
    )

    assert record.status == "failed"
    assert record.failure_stage == "validation"
    assert record.validation_issue_count == 1
    assert record.readback_verified is False


def test_malformed_validation_response_is_a_durable_validation_failure(
    tmp_path: Path,
) -> None:
    client = FakeDeploymentClient(existing=False, validation={"issues": []})

    record = deploy_public_bundle(
        bundle_root=_bundle(tmp_path),
        connection_id="connection-id",
        client=client,
        run_id="deployment-1",
        source_commit="d" * 40,
        observed_at="2026-08-28T12:00:00-04:00",
    )

    assert record.status == "failed"
    assert record.failure_stage == "validation"
    assert record.failure_detail == "validator response must be an array"


def test_deployment_status_is_secret_free_exclusive_and_non_overwriting(
    tmp_path: Path,
) -> None:
    client = FakeDeploymentClient(existing=False)
    record = deploy_public_bundle(
        bundle_root=_bundle(tmp_path),
        connection_id="connection-id",
        client=client,
        run_id="deployment-1",
        source_commit="e" * 40,
        observed_at="2026-08-28T12:00:00-04:00",
    )

    path = write_deployment_record(tmp_path / "records", record)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["database"] == DATABASE
    assert payload["connection_id"] == "connection-id"
    assert "credential" not in path.read_text(encoding="utf-8").lower()
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_deployment_record(tmp_path / "records", record)


def test_record_rejects_unsafe_identifiers_before_path_construction(
    tmp_path: Path,
) -> None:
    record = DeploymentRecord(
        database=DATABASE,
        run_id="deployment-1",
        observed_at="2026-08-28T12:00:00-04:00",
        source_commit="f" * 40,
        connection_id="connection-id",
        model_id="model-id",
        branch_id="branch-id",
        model_name=isolated_model_name(DATABASE),
        branch_name=isolated_branch_name(DATABASE),
        manifest_sha256="0" * 64,
        file_sha256={},
        file_count=0,
        uploaded_file_count=0,
        validation_issue_count=0,
        readback_file_count=0,
        readback_verified=False,
        status="failed",
        failure_stage="setup",
        failure_detail="invalid fixture",
    )

    with pytest.raises(ValueError, match="run_id"):
        write_deployment_record(
            tmp_path / "records", replace(record, run_id="../escape")
        )

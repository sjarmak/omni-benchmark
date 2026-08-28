from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from omni_benchmark.omni_semantic_deploy_cli import (
    OmniDeploymentCli,
    OmniDeploymentCliError,
    _claim_deployment_run,
    _connection_map,
    _git_commit,
    _model_map,
    _working_bundle_inventory,
    deployment_main,
)


def _bundle(workspace: Path, database: str, *, canary: bool = False) -> Path:
    root = (
        workspace / "semantic_models/public_bundle"
        if canary
        else workspace / "semantic_models/public_baseline" / database / "bundle"
    )
    root.mkdir(parents=True)
    topic_name = f"{database}_semantics.topic"
    topic = (
        f"base_view: {database}_public__events\n"
        f"label: {database}\nfields: [{database}_public__events.*]\njoins: {{}}\n"
    ).encode()
    (root / topic_name).write_bytes(topic)
    manifest = {
        "database": database,
        "files": [
            {
                "file": topic_name,
                "sha256": hashlib.sha256(topic).hexdigest(),
                "size_bytes": len(topic),
            }
        ],
        "kind": "public-omni-semantic-bundle",
        "schema_version": 1,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def _commit_fixture(workspace: Path, message: str = "fixture") -> str:
    if not (workspace / ".git").is_dir():
        subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=workspace,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Fixture"], cwd=workspace, check=True
        )
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", message], cwd=workspace, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class FakeBatchClient:
    def __init__(
        self, databases: tuple[str, ...], *, failing_database: str | None = None
    ) -> None:
        self.databases = databases
        self.failing_database = failing_database
        self.uploaded: dict[str, dict[str, str]] = {}
        self.connection_calls = 0

    def connection_ids(self, requested: tuple[str, ...]) -> dict[str, str]:
        self.connection_calls += 1
        assert set(requested) <= set(self.databases)
        return {database: f"connection-{database}" for database in requested}

    def ensure_shared_model(self, connection_id: str, name: str) -> tuple[str, bool]:
        return f"model-{connection_id}", True

    def ensure_branch(self, model_id: str, name: str) -> tuple[str, bool]:
        return f"branch-{model_id}", True

    def upload_yaml(
        self, model_id: str, branch_id: str, path: str, content: str
    ) -> None:
        self.uploaded[branch_id] = {**self.uploaded.get(branch_id, {}), path: content}

    def validate(self, model_id: str, branch_id: str) -> object:
        if self.failing_database and self.failing_database in model_id:
            return [{"type": "bad_sql"}]
        return []

    def readback(self, model_id: str, branch_id: str) -> dict[str, str]:
        return {
            "model": "{}\n",
            "relationships": "[]\n",
            **self.uploaded[branch_id],
        }


def test_batch_cli_discovers_canary_and_fanout_bundles_and_writes_statuses(
    tmp_path: Path,
) -> None:
    _bundle(tmp_path, "archeology_scan_large", canary=True)
    _bundle(tmp_path, "sample_large")
    fake = FakeBatchClient(("archeology_scan_large", "sample_large"))
    output = tmp_path / "deployments"

    exit_code = deployment_main(
        [
            "--workspace",
            str(tmp_path),
            "--output-root",
            str(output),
            "--run-id",
            "public-v1",
            "--profile",
            "benchmark-infra",
            "--max-workers",
            "2",
            "--execute-live-deployment",
        ],
        client_factory=lambda _profile: fake,
        commit_observer=lambda _workspace: "a" * 40,
        bundle_loader=_working_bundle_inventory,
    )

    assert exit_code == 0
    records = [json.loads(path.read_text()) for path in sorted(output.glob("*.json"))]
    assert {record["database"] for record in records} == {
        "archeology_scan_large",
        "sample_large",
    }
    assert {record["status"] for record in records} == {"verified"}


def test_batch_cli_can_select_one_database_without_touching_others(
    tmp_path: Path,
) -> None:
    _bundle(tmp_path, "archeology_scan_large", canary=True)
    _bundle(tmp_path, "sample_large")
    fake = FakeBatchClient(("archeology_scan_large", "sample_large"))

    exit_code = deployment_main(
        [
            "--workspace",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "deployments"),
            "--run-id",
            "selected-v1",
            "--profile",
            "benchmark-infra",
            "--database",
            "sample_large",
            "--execute-live-deployment",
        ],
        client_factory=lambda _profile: fake,
        commit_observer=lambda _workspace: "b" * 40,
        bundle_loader=_working_bundle_inventory,
    )

    assert exit_code == 0
    records = list((tmp_path / "deployments").glob("*.json"))
    assert len(records) == 1
    assert json.loads(records[0].read_text())["database"] == "sample_large"


def test_batch_deploys_the_authenticated_snapshot_observed_before_product_access(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path, "sample_large")
    topic_path = bundle / "sample_large_semantics.topic"
    original = topic_path.read_text(encoding="utf-8")
    _commit_fixture(tmp_path, "original")
    changed = original.replace("label: sample_large", "label: changed")

    def observe_new_commit(workspace: Path) -> str:
        topic_path.write_text(changed, encoding="utf-8")
        manifest_path = bundle / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"][0]["sha256"] = hashlib.sha256(changed.encode()).hexdigest()
        manifest["files"][0]["size_bytes"] = len(changed.encode())
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return _commit_fixture(workspace, "updated")

    fake = FakeBatchClient(("sample_large",))

    exit_code = deployment_main(
        [
            "--workspace",
            str(tmp_path),
            "--output-root",
            str(tmp_path / "deployments"),
            "--run-id",
            "snapshot-v1",
            "--profile",
            "benchmark-infra",
            "--database",
            "sample_large",
            "--execute-live-deployment",
        ],
        client_factory=lambda _profile: fake,
        commit_observer=observe_new_commit,
    )

    assert exit_code == 0
    uploaded = next(iter(fake.uploaded.values()))["sample_large_semantics.topic"]
    assert uploaded == changed


def test_batch_preserves_a_failure_without_abandoning_other_databases(
    tmp_path: Path,
) -> None:
    _bundle(tmp_path, "archeology_scan_large", canary=True)
    _bundle(tmp_path, "sample_large")
    fake = FakeBatchClient(
        ("archeology_scan_large", "sample_large"), failing_database="sample_large"
    )
    output = tmp_path / "deployments"

    exit_code = deployment_main(
        [
            "--workspace",
            str(tmp_path),
            "--output-root",
            str(output),
            "--run-id",
            "mixed-v1",
            "--profile",
            "benchmark-infra",
            "--max-workers",
            "2",
            "--execute-live-deployment",
        ],
        client_factory=lambda _profile: fake,
        commit_observer=lambda _workspace: "a" * 40,
        bundle_loader=_working_bundle_inventory,
    )

    assert exit_code == 1
    records = [json.loads(path.read_text()) for path in sorted(output.glob("*.json"))]
    assert {record["database"]: record["status"] for record in records} == {
        "archeology_scan_large": "verified",
        "sample_large": "failed",
    }


def test_malformed_bundle_is_a_per_database_blocker_without_aborting_fanout(
    tmp_path: Path,
) -> None:
    _bundle(tmp_path, "sample_large")
    broken = _bundle(tmp_path, "broken_large")
    (broken / "manifest.json").write_text("not-json", encoding="utf-8")
    fake = FakeBatchClient(("sample_large", "broken_large"))
    output = tmp_path / "deployments"

    exit_code = deployment_main(
        [
            "--workspace",
            str(tmp_path),
            "--output-root",
            str(output),
            "--run-id",
            "preflight-v1",
            "--profile",
            "benchmark-infra",
            "--execute-live-deployment",
        ],
        client_factory=lambda _profile: fake,
        commit_observer=lambda _workspace: "a" * 40,
        bundle_loader=_working_bundle_inventory,
    )

    assert exit_code == 1
    records = [json.loads(path.read_text()) for path in sorted(output.glob("*.json"))]
    assert {record["database"]: record["status"] for record in records} == {
        "broken_large": "failed",
        "sample_large": "verified",
    }
    broken_record = next(
        record for record in records if record["database"] == "broken_large"
    )
    assert broken_record["failure_stage"] == "bundle_preflight"
    assert fake.connection_calls == 1


def test_recursive_parser_failure_is_a_per_database_blocker(tmp_path: Path) -> None:
    _bundle(tmp_path, "sample_large")
    broken = _bundle(tmp_path, "broken_large")
    topic_path = broken / "broken_large_semantics.topic"
    content = (
        "root:\n" + "".join("  " * (index + 1) + "-\n" for index in range(1500))
    ).encode()
    topic_path.write_bytes(content)
    manifest_path = broken / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = hashlib.sha256(content).hexdigest()
    manifest["files"][0]["size_bytes"] = len(content)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    plans, failures = _working_bundle_inventory(tmp_path, "a" * 40)

    assert set(plans) == {"sample_large"}
    assert failures == {"broken_large": "bundle parser recursion limit exceeded"}


def test_duplicate_selection_and_existing_status_fail_before_product_access(
    tmp_path: Path,
) -> None:
    _bundle(tmp_path, "sample_large")
    fake = FakeBatchClient(("sample_large",))
    common = [
        "--workspace",
        str(tmp_path),
        "--output-root",
        str(tmp_path / "deployments"),
        "--run-id",
        "duplicate-v1",
        "--profile",
        "benchmark-infra",
        "--execute-live-deployment",
    ]
    with pytest.raises(OmniDeploymentCliError, match="duplicate database"):
        deployment_main(
            [*common, "--database", "sample_large", "--database", "sample_large"],
            client_factory=lambda _profile: fake,
            commit_observer=lambda _workspace: "a" * 40,
            bundle_loader=_working_bundle_inventory,
        )
    assert fake.connection_calls == 0

    output = tmp_path / "deployments"
    output.mkdir()
    (output / "duplicate-v1.sample_large.json").write_text("{}\n")
    with pytest.raises(OmniDeploymentCliError, match="already exists"):
        deployment_main(
            [*common, "--database", "sample_large"],
            client_factory=lambda _profile: fake,
            commit_observer=lambda _workspace: "a" * 40,
            bundle_loader=_working_bundle_inventory,
        )
    assert fake.connection_calls == 0


def test_run_claim_is_atomic_and_output_root_must_be_writable_before_product_access(
    tmp_path: Path,
) -> None:
    output = tmp_path / "deployments"
    with ThreadPoolExecutor(max_workers=2) as executor:
        attempts = [
            executor.submit(
                _claim_deployment_run,
                output,
                "claim-v1",
                ("sample_large",),
                "a" * 40,
            )
            for _ in range(2)
        ]
    outcomes: list[str] = []
    for attempt in attempts:
        try:
            outcomes.append(str(attempt.result()))
        except OmniDeploymentCliError as error:
            outcomes.append(str(error))
    assert sum("claim-v1.claim" in outcome for outcome in outcomes) == 1
    assert sum("already claimed" in outcome for outcome in outcomes) == 1

    workspace = tmp_path / "workspace"
    _bundle(workspace, "sample_large")
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("occupied", encoding="utf-8")
    fake = FakeBatchClient(("sample_large",))
    with pytest.raises(OmniDeploymentCliError, match="could not be claimed"):
        deployment_main(
            [
                "--workspace",
                str(workspace),
                "--output-root",
                str(invalid_root),
                "--run-id",
                "invalid-root-v1",
                "--profile",
                "benchmark-infra",
                "--database",
                "sample_large",
                "--execute-live-deployment",
            ],
            client_factory=lambda _profile: fake,
            commit_observer=lambda _workspace: "a" * 40,
            bundle_loader=_working_bundle_inventory,
        )
    assert fake.connection_calls == 0


def test_live_cli_uses_profile_and_json_stdin_without_credential_arguments() -> None:
    calls: list[tuple[tuple[str, ...], str | None]] = []
    responses = iter(
        [
            {
                "connections": [
                    {
                        "id": "connection-id",
                        "name": "LiveSQLBench sample_large",
                    }
                ]
            },
            {"records": []},
            {"id": "model-id"},
            {"id": "branch-id"},
            {},
            [],
            {
                "files": {
                    "model": "{}\n",
                    "relationships": "[]\n",
                    "sample.topic": "label: Sample\n",
                }
            },
        ]
    )

    def runner(
        arguments: tuple[str, ...],
        environment: dict[str, str],
        stdin: str | None,
        timeout: float,
    ) -> tuple[int, str, str]:
        calls.append((arguments, stdin))
        return 0, json.dumps(next(responses)), ""

    client = OmniDeploymentCli(
        "benchmark-infra",
        runner=runner,
        environment={"PATH": "/usr/bin", "HOME": "/tmp/profile"},
    )

    assert client.connection_ids(("sample_large",)) == {"sample_large": "connection-id"}
    assert client.ensure_shared_model("connection-id", "model-name") == (
        "model-id",
        True,
    )
    assert client.ensure_branch("model-id", "branch-name") == ("branch-id", True)
    client.upload_yaml("model-id", "branch-id", "sample.topic", "label: Sample\n")
    assert client.validate("model-id", "branch-id") == []
    assert client.readback("model-id", "branch-id")["sample.topic"]

    flattened = " ".join(part for call, _stdin in calls for part in call)
    assert "benchmark-infra" in flattened
    assert "token" not in flattened.lower()
    create_body = json.loads(calls[2][1] or "{}")
    assert create_body == {
        "connectionId": "connection-id",
        "modelKind": "SHARED",
        "modelName": "model-name",
    }


def test_live_cli_reuses_exact_existing_model_and_branch() -> None:
    calls: list[tuple[str, ...]] = []
    responses = iter(
        [
            {
                "records": [
                    {
                        "connectionId": "connection-id",
                        "name": "model-name",
                        "id": "model-id",
                        "branches": [{"name": "branch-name", "id": "branch-id"}],
                    }
                ]
            }
        ]
    )

    def runner(
        arguments: tuple[str, ...],
        environment: dict[str, str],
        stdin: str | None,
        timeout: float,
    ) -> tuple[int, str, str]:
        calls.append(arguments)
        return 0, json.dumps(next(responses)), ""

    client = OmniDeploymentCli(
        "benchmark-infra",
        runner=runner,
        environment={"PATH": "/usr/bin", "HOME": "/tmp/profile"},
    )

    assert client.ensure_shared_model("connection-id", "model-name") == (
        "model-id",
        False,
    )
    assert client.ensure_branch("model-id", "branch-name") == ("branch-id", False)
    assert len(calls) == 1


def test_same_model_identity_is_created_once_under_concurrency() -> None:
    create_calls = 0
    create_started = threading.Event()
    release_create = threading.Event()

    def runner(
        arguments: tuple[str, ...],
        environment: dict[str, str],
        stdin: str | None,
        timeout: float,
    ) -> tuple[int, str, str]:
        nonlocal create_calls
        if "list" in arguments:
            return 0, json.dumps({"records": []}), ""
        create_calls += 1
        create_started.set()
        assert release_create.wait(timeout=2)
        return 0, json.dumps({"id": "model-id"}), ""

    client = OmniDeploymentCli(
        "benchmark-infra", runner=runner, environment={"PATH": "/usr/bin"}
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.ensure_shared_model, "connection-id", "model")
        assert create_started.wait(timeout=2)
        second = executor.submit(client.ensure_shared_model, "connection-id", "model")
        release_create.set()
        assert first.result() == ("model-id", True)
        assert second.result() == ("model-id", False)
    assert create_calls == 1


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ({}, "connection list"),
        ({"connections": [{"name": "LiveSQLBench sample_large"}]}, "ID"),
        (
            {
                "connections": [
                    {"name": "LiveSQLBench sample_large", "id": "one"},
                    {"name": "LiveSQLBench sample_large", "id": "two"},
                ]
            },
            "duplicate",
        ),
    ],
)
def test_connection_response_validation_fails_closed(
    response: dict[str, object], message: str
) -> None:
    with pytest.raises(OmniDeploymentCliError, match=message):
        _connection_map(response)


def test_model_response_parser_preserves_branch_identity() -> None:
    parsed = _model_map(
        {
            "records": [
                {
                    "connectionId": "connection-id",
                    "name": "model-name",
                    "id": "model-id",
                    "branches": [{"name": "branch-name", "id": "branch-id"}],
                },
                {"name": None, "id": "ignored"},
            ]
        }
    )

    assert parsed == {
        ("connection-id", "model-name"): (
            "model-id",
            {"branch-name": "branch-id"},
        )
    }


def test_model_response_parser_rejects_duplicate_remote_identities() -> None:
    duplicate_models = {
        "records": [
            {"connectionId": "c", "name": "m", "id": "one"},
            {"connectionId": "c", "name": "m", "id": "two"},
        ]
    }
    with pytest.raises(OmniDeploymentCliError, match="duplicate shared model"):
        _model_map(duplicate_models)

    duplicate_branches = {
        "records": [
            {
                "connectionId": "c",
                "name": "m",
                "id": "one",
                "branches": [
                    {"name": "b", "id": "one"},
                    {"name": "b", "id": "two"},
                ],
            }
        ]
    }
    with pytest.raises(OmniDeploymentCliError, match="duplicate model branch"):
        _model_map(duplicate_branches)


def test_cli_boundary_reports_nonzero_and_malformed_responses_without_stderr() -> None:
    def failed_runner(
        arguments: tuple[str, ...],
        environment: dict[str, str],
        stdin: str | None,
        timeout: float,
    ) -> tuple[int, str, str]:
        return 1, "", "secret-like provider detail"

    client = OmniDeploymentCli(
        "benchmark-infra",
        runner=failed_runner,
        environment={"PATH": "/usr/bin"},
    )
    with pytest.raises(OmniDeploymentCliError, match="request failed") as error:
        client.connection_ids(("sample_large",))
    assert "secret-like" not in str(error.value)

    malformed = OmniDeploymentCli(
        "benchmark-infra",
        runner=lambda *_args: (0, "not-json", ""),
        environment={"PATH": "/usr/bin"},
    )
    with pytest.raises(OmniDeploymentCliError, match="valid JSON"):
        malformed.connection_ids(("sample_large",))


def test_cli_requires_explicit_live_acknowledgement(tmp_path: Path) -> None:
    with pytest.raises(OmniDeploymentCliError, match="explicit acknowledgement"):
        deployment_main(
            [
                "--workspace",
                str(tmp_path),
                "--output-root",
                str(tmp_path / "out"),
                "--run-id",
                "run-1",
                "--profile",
                "benchmark-infra",
            ]
        )


def test_source_commit_rejects_dirty_public_bundle_bytes(tmp_path: Path) -> None:
    _bundle(tmp_path, "sample_large")
    _commit_fixture(tmp_path)

    assert len(_git_commit(tmp_path)) == 40
    topic = next((tmp_path / "semantic_models").rglob("*.topic"))
    topic.write_text(topic.read_text() + "description: changed\n", encoding="utf-8")

    with pytest.raises(OmniDeploymentCliError, match="bundle tree"):
        _git_commit(tmp_path)


def test_script_shim_exposes_help() -> None:
    script = Path(__file__).parents[1] / "scripts/deploy_public_semantic_bundles.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert completed.returncode == 0
    assert "execute-live-deployment" in completed.stdout

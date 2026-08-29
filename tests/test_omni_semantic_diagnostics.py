from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from omni_benchmark.omni_semantic_diagnostics import (
    PublicValidatorDiagnosticError,
    diagnostic_main,
)


DATABASE = "sample_large"
SOURCE_RUN_ID = "public-baseline-v6-20260828"
SOURCE_COMMIT = "a" * 40
MANIFEST_SHA256 = "b" * 64


def _source_record(root: Path, **changes: object) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    value = {
        "branch_id": "branch-id",
        "database": DATABASE,
        "failure_stage": "validation",
        "kind": "public-omni-semantic-deployment",
        "manifest_sha256": MANIFEST_SHA256,
        "model_id": "model-id",
        "readback_verified": False,
        "run_id": SOURCE_RUN_ID,
        "schema_version": 1,
        "source_commit": SOURCE_COMMIT,
        "status": "failed",
        "validation_issue_count": 2,
        **changes,
    }
    path = root / f"{SOURCE_RUN_ID}.{DATABASE}.json"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    return path


class FakeValidationClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def validate(self, model_id: str, branch_id: str) -> object:
        self.calls.append((model_id, branch_id))
        return self.response


def _arguments(tmp_path: Path) -> list[str]:
    return [
        "--workspace",
        str(tmp_path),
        "--source-deployment-root",
        str(tmp_path / "source"),
        "--source-run-id",
        SOURCE_RUN_ID,
        "--output-root",
        str(tmp_path / "diagnostics"),
        "--run-id",
        "public-validator-diagnostics-v1",
        "--profile",
        "benchmark-infra",
        "--database",
        DATABASE,
    ]


def _plan_loader(_workspace: Path, commit: str, database: str) -> object:
    assert commit == SOURCE_COMMIT
    assert database == DATABASE
    return SimpleNamespace(manifest_sha256=MANIFEST_SHA256)


def test_diagnostic_is_dry_by_default_before_source_or_client_access(
    tmp_path: Path,
) -> None:
    clients: list[object] = []

    with pytest.raises(
        PublicValidatorDiagnosticError, match="explicit acknowledgement"
    ):
        diagnostic_main(
            _arguments(tmp_path),
            client_factory=lambda _profile: clients.append(object()),
            plan_loader=_plan_loader,
        )

    assert clients == []
    assert not (tmp_path / "diagnostics").exists()


def test_exact_failed_deployment_identity_is_validated_before_read_only_request(
    tmp_path: Path,
) -> None:
    source_path = _source_record(tmp_path / "source")
    client = FakeValidationClient(
        [
            {"severity": "error", "message": "unknown field one"},
            {"severity": "error", "message": "unknown field two"},
        ]
    )

    exit_code = diagnostic_main(
        [*_arguments(tmp_path), "--execute-live-validation"],
        client_factory=lambda profile: client if profile == "benchmark-infra" else None,
        plan_loader=_plan_loader,
        observed_at=lambda: "2026-08-29T10:00:00-04:00",
    )

    assert exit_code == 0
    assert client.calls == [("model-id", "branch-id")]
    output = tmp_path / "diagnostics"
    record_path = output / "public-validator-diagnostics-v1.sample_large.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["kind"] == "public-omni-validator-diagnostic"
    assert (
        record["source_deployment_record_sha256"]
        == hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
    assert record["source_commit"] == SOURCE_COMMIT
    assert record["manifest_sha256"] == MANIFEST_SHA256
    assert record["source_issue_count"] == 2
    assert record["observed_issue_count"] == 2
    assert record["status"] == "captured"
    assert record["issues"][0]["message"] == "unknown field one"
    assert len(record["issues_sha256"]) == 64
    assert record_path.stat().st_mode & 0o777 == 0o600
    claim = json.loads(
        (output / "public-validator-diagnostics-v1.claim").read_text(encoding="utf-8")
    )
    assert claim["databases"] == [DATABASE]
    assert claim["source_deployment_run_id"] == SOURCE_RUN_ID


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": "verified"}, "failed validation record"),
        ({"failure_stage": "product_api"}, "failed validation record"),
        ({"manifest_sha256": "c" * 64}, "manifest"),
        ({"model_id": None}, "model and branch"),
        ({"validation_issue_count": 0}, "positive issue count"),
        ({"schema_version": 3}, "schema"),
    ],
)
def test_source_identity_failures_happen_before_client_construction(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    _source_record(tmp_path / "source", **changes)
    clients: list[object] = []

    with pytest.raises(PublicValidatorDiagnosticError, match=message):
        diagnostic_main(
            [*_arguments(tmp_path), "--execute-live-validation"],
            client_factory=lambda _profile: clients.append(object()),
            plan_loader=_plan_loader,
        )

    assert clients == []
    assert not (tmp_path / "diagnostics").exists()


@pytest.mark.parametrize(
    "response",
    [
        {"issues": []},
        [{"authorization": "Bearer very-secret"}],
        [{"message": "Bearer abcdefghijklmnopqrstuvwxyz"}],
        [{"gold_sql": "select 1"}],
        [{"message": "x" * 20000}],
    ],
)
def test_unsafe_validator_payload_is_rejected_without_persisting_it(
    tmp_path: Path, response: object
) -> None:
    _source_record(tmp_path / "source")
    client = FakeValidationClient(response)

    exit_code = diagnostic_main(
        [*_arguments(tmp_path), "--execute-live-validation"],
        client_factory=lambda _profile: client,
        plan_loader=_plan_loader,
    )

    assert exit_code == 1
    record_path = (
        tmp_path / "diagnostics" / "public-validator-diagnostics-v1.sample_large.json"
    )
    text = record_path.read_text(encoding="utf-8")
    record = json.loads(text)
    assert record["status"] == "rejected"
    assert record["issues"] is None
    assert record["issues_sha256"] is None
    assert "very-secret" not in text
    assert "select 1" not in text
    assert "Bearer abc" not in text


def test_issue_count_drift_is_preserved_but_not_reported_as_captured(
    tmp_path: Path,
) -> None:
    _source_record(tmp_path / "source")
    client = FakeValidationClient([{"message": "only one remains"}])

    exit_code = diagnostic_main(
        [*_arguments(tmp_path), "--execute-live-validation"],
        client_factory=lambda _profile: client,
        plan_loader=_plan_loader,
    )

    assert exit_code == 1
    record = json.loads(
        (
            tmp_path
            / "diagnostics"
            / "public-validator-diagnostics-v1.sample_large.json"
        ).read_text(encoding="utf-8")
    )
    assert record["status"] == "drifted"
    assert record["source_issue_count"] == 2
    assert record["observed_issue_count"] == 1
    assert record["issues"] == [{"message": "only one remains"}]


def test_duplicate_database_and_existing_claim_fail_before_client_access(
    tmp_path: Path,
) -> None:
    _source_record(tmp_path / "source")
    clients: list[object] = []
    arguments = [*_arguments(tmp_path), "--execute-live-validation"]

    with pytest.raises(PublicValidatorDiagnosticError, match="duplicate database"):
        diagnostic_main(
            [*arguments, "--database", DATABASE],
            client_factory=lambda _profile: clients.append(object()),
            plan_loader=_plan_loader,
        )

    output = tmp_path / "diagnostics"
    output.mkdir()
    (output / "public-validator-diagnostics-v1.claim").write_text("{}\n")
    with pytest.raises(PublicValidatorDiagnosticError, match="already claimed"):
        diagnostic_main(
            arguments,
            client_factory=lambda _profile: clients.append(object()),
            plan_loader=_plan_loader,
        )

    assert clients == []


def test_source_symlink_and_output_root_symlink_are_rejected(
    tmp_path: Path,
) -> None:
    real_source = _source_record(tmp_path / "real-source")
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / real_source.name).symlink_to(real_source)

    with pytest.raises(PublicValidatorDiagnosticError, match="could not be read"):
        diagnostic_main(
            [*_arguments(tmp_path), "--execute-live-validation"],
            client_factory=lambda _profile: FakeValidationClient([]),
            plan_loader=_plan_loader,
        )

    (source_root / real_source.name).unlink()
    (source_root / real_source.name).write_bytes(real_source.read_bytes())
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    (tmp_path / "diagnostics").symlink_to(real_output, target_is_directory=True)
    with pytest.raises(PublicValidatorDiagnosticError, match="could not be claimed"):
        diagnostic_main(
            [*_arguments(tmp_path), "--execute-live-validation"],
            client_factory=lambda _profile: FakeValidationClient([]),
            plan_loader=_plan_loader,
        )

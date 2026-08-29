from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.baseline_batch import (
    BaselineBatchError,
    c4_public_baseline_schedule,
    load_committed_baseline_schedule,
)
from omni_benchmark.baseline_batch_live import (
    DeploymentTarget,
    verify_derived_deployment_gate,
)
from omni_benchmark.baseline_batch_cli import (
    _deployment_targets_sha256,
    baseline_batch_main,
)
from omni_benchmark.c4_baseline_arm import render_c4_baseline_arm


ROOT = Path(__file__).resolve().parents[1]
SPEC = Path("config/conditions/c4-public-baseline-arm-v1.json")
C4_DATABASES = (
    "archeology_scan_large",
    "cross_border_large",
    "cybermarket_pattern_large",
    "disaster_relief_large",
    "exchange_traded_funds_large",
    "fake_account_large",
    "labor_certification_applications_large",
    "museum_artifact_large",
    "planets_data_large",
    "polar_equipment_large",
    "residential_data_large",
    "reverse_logistics_large",
    "robot_fault_prediction_large",
    "solar_panel_large",
    "sports_events_large",
    "virtual_idol_large",
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _git(workspace: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(workspace), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _fixture_repo(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "repo"
    paths = (
        SPEC,
        Path("config/conditions/dev-a-scorer-conformance-exclusions-v1.json"),
        Path("data/manifests/train_ids.txt"),
        Path("data/manifests/dev_a_ids.txt"),
        Path("data/manifests/eligible_questions.jsonl"),
        Path("data/manifests/c4_public_baseline_ids.txt"),
        Path("data/manifests/c4_paired_analysis_ids.txt"),
        Path("data/manifests/c4_public_baseline_metadata.json"),
    )
    deployment = ROOT / "experiments/deployments/public-baseline-v13"
    for source in paths:
        destination = workspace / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, destination)
    shutil.copytree(
        deployment,
        workspace / "experiments/deployments/public-baseline-v13",
    )
    for path in (workspace / "experiments/deployments/public-baseline-v13").iterdir():
        path.chmod(0o600)
    shutil.copytree(
        ROOT / "semantic_models/public_bundle",
        workspace / "semantic_models/public_bundle",
    )
    for database in C4_DATABASES[1:]:
        shutil.copytree(
            ROOT / "semantic_models/public_baseline" / database / "bundle",
            workspace / "semantic_models/public_baseline" / database / "bundle",
        )
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "fixture")
    return workspace, _git(workspace, "rev-parse", "HEAD")


def _private_e02_deployment_gate(workspace: Path, source_commit: str) -> Path:
    source = workspace / "experiments/deployments/public-baseline-v13"
    destination = workspace / "experiments/private-e02-deployment"
    shutil.copytree(source, destination)
    for path in destination.iterdir():
        if path.suffix == ".json" or path.suffix == ".claim":
            value = json.loads(path.read_text(encoding="utf-8"))
            value["source_commit"] = source_commit
        if path.suffix == ".json":
            value["schema_version"] = 2
            value["status"] = "verified"
            value["validation_issue_count"] = 0
            value["readback_verified"] = True
            value["semantic_model_sha256"] = hashlib.sha256(
                value["database"].encode()
            ).hexdigest()
        if path.suffix in {".json", ".claim"}:
            path.write_text(
                json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
                encoding="utf-8",
            )
        path.chmod(0o600)
    return destination


def test_public_c4_arm_regenerates_byte_identically() -> None:
    rendered = render_c4_baseline_arm(ROOT, SPEC)

    assert len(rendered.full_ids) == 204
    assert len(rendered.paired_ids) == 108
    assert rendered.full_ids_bytes == (ROOT / rendered.spec.full_ids_path).read_bytes()
    assert (
        rendered.paired_ids_bytes == (ROOT / rendered.spec.paired_ids_path).read_bytes()
    )
    assert rendered.metadata_bytes == (ROOT / rendered.spec.metadata_path).read_bytes()

    metadata = json.loads(rendered.metadata_bytes)
    assert metadata["source"]["eligible_manifest_sha256"] == _sha256(
        (ROOT / "data/manifests/eligible_questions.jsonl").read_bytes()
    )
    assert metadata["source"]["train_ids_sha256"] == _sha256(
        (ROOT / "data/manifests/train_ids.txt").read_bytes()
    )
    assert sum(item["selected_count"] for item in metadata["allocation"]) == 204
    assert sum(item["selected_count"] for item in metadata["paired_allocation"]) == 108


def test_committed_schedule_selects_only_c4_in_committed_arm_order(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    full = load_committed_baseline_schedule(workspace, commit, run_id="c4-arm-v1")
    selected = c4_public_baseline_schedule(workspace, commit, full)
    expected_ids = tuple(
        (workspace / "data/manifests/c4_public_baseline_ids.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert len(selected.attempts) == 204
    assert tuple(item.instance_id for item in selected.attempts) == expected_ids
    assert {item.condition for item in selected.attempts} == {"C4"}
    assert len({item.database for item in selected.attempts}) == 16


def test_derived_gate_rejects_any_changed_selected_record(
    tmp_path: Path,
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    record = (
        workspace
        / "experiments/deployments/public-baseline-v13"
        / "public-baseline-v13-20260829.cross_border_large.json"
    )
    value = json.loads(record.read_text(encoding="utf-8"))
    value["status"] = "failed"
    record.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "mutate record")
    commit = _git(workspace, "rev-parse", "HEAD")

    with pytest.raises(BaselineBatchError, match="record digest changed"):
        verify_derived_deployment_gate(
            workspace,
            commit,
            SPEC,
            {"cross_border_large"},
        )


def test_derived_gate_rejects_a_verified_record_with_changed_target(
    tmp_path: Path,
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    record = (
        workspace
        / "experiments/deployments/public-baseline-v13"
        / "public-baseline-v13-20260829.cross_border_large.json"
    )
    value = json.loads(record.read_text(encoding="utf-8"))
    value["branch_id"] = "different-but-well-formed-branch-id"
    record.write_text(
        json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "mutate deployment target")
    commit = _git(workspace, "rev-parse", "HEAD")

    with pytest.raises(BaselineBatchError, match="record digest changed"):
        verify_derived_deployment_gate(
            workspace,
            commit,
            SPEC,
            {"cross_border_large"},
        )


def test_derived_gate_resolves_all_sixteen_verified_targets(tmp_path: Path) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    targets = verify_derived_deployment_gate(
        workspace,
        commit,
        SPEC,
        set(C4_DATABASES),
    )

    assert len(targets) == 16
    assert all(target.branch_id and target.model_id for target in targets.values())
    assert all(len(target.semantic_model_sha256) == 64 for target in targets.values())


def test_current_compiler_outputs_match_the_v13_gate(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    targets = verify_derived_deployment_gate(
        workspace,
        commit,
        SPEC,
        set(C4_DATABASES),
    )

    assert len(targets) == 16


def test_c4_approval_deployment_identity_binds_semantic_content() -> None:
    first = {
        "database": DeploymentTarget(
            branch_id="branch-id",
            model_id="model-id",
            semantic_model_sha256="a" * 64,
        )
    }
    changed_content = {
        "database": DeploymentTarget(
            branch_id="branch-id",
            model_id="model-id",
            semantic_model_sha256="b" * 64,
        )
    }

    assert _deployment_targets_sha256(first) != _deployment_targets_sha256(
        changed_content
    )


def test_c4_dry_run_accepts_current_sixteen_database_deployment_spec(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    assert (
        baseline_batch_main(
            [
                "--workspace",
                str(workspace),
                "--system-commit",
                commit,
                "--run-id",
                "public-c4-baseline-v1",
                "--observed-attempt-cost-usd",
                "0.7275655",
                "--cost-ceiling-usd",
                "560",
                "--dry-run-c4-baseline",
                "--freeze-a-commit",
                "7d39ee107338da1ce10e2553a4290e64bfc2f892",
                "--output-root",
                "experiments/autoresearch/raw/public-c4-baseline-v1",
                "--observed-condition-cost",
                "C4=0.7275655",
                "--maximum-wall-clock-seconds",
                "21600",
            ]
        )
        == 0
    )


def test_c4_dry_run_rejects_a_nonpositive_wall_clock_bound(tmp_path: Path) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    with pytest.raises(
        BaselineBatchError, match="maximum wall-clock seconds must be positive"
    ):
        baseline_batch_main(
            [
                "--workspace",
                str(workspace),
                "--system-commit",
                commit,
                "--run-id",
                "public-c4-baseline-v1",
                "--observed-attempt-cost-usd",
                "0.7275655",
                "--cost-ceiling-usd",
                "560",
                "--dry-run-c4-baseline",
                "--freeze-a-commit",
                "7d39ee107338da1ce10e2553a4290e64bfc2f892",
                "--output-root",
                "experiments/autoresearch/raw/public-c4-baseline-v1",
                "--observed-condition-cost",
                "C4=0.7275655",
                "--maximum-wall-clock-seconds",
                "-1",
            ]
        )


def test_e02_dry_run_projects_exact_full_dev_a_c4_experiment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    deployment_root = _private_e02_deployment_gate(workspace, commit)
    monkeypatch.setattr(
        "omni_benchmark.baseline_batch_cli.verify_deployment_gate",
        lambda _root, _run_id, databases, **kwargs: {
            database: DeploymentTarget(
                branch_id=f"branch-{index}",
                model_id=f"model-{index}",
                semantic_model_sha256=hashlib.sha256(database.encode()).hexdigest(),
            )
            for index, database in enumerate(sorted(databases))
        },
    )

    result = baseline_batch_main(
        [
            "--workspace",
            str(workspace),
            "--system-commit",
            commit,
            "--run-id",
            "e02-dev-a-v1",
            "--observed-attempt-cost-usd",
            "0.7275655",
            "--cost-ceiling-usd",
            "700",
            "--dry-run-e02-dev-a-experiment",
            "--freeze-a-commit",
            "7d39ee107338da1ce10e2553a4290e64bfc2f892",
            "--output-root",
            "experiments/autoresearch/raw/e02-dev-a-v1",
            "--deployment-root",
            str(deployment_root),
            "--deployment-run-id",
            "public-baseline-v13-20260829",
            "--observed-condition-cost",
            "C4=0.7275655",
            "--maximum-wall-clock-seconds",
            "21600",
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution_plan"]["attempt_count"] == 136
    assert {item["condition"] for item in output["execution_plan"]["attempts"]} == {
        "C4"
    }
    assert output["deployment_target_count"] == 16
    assert output["schedule_identity"]["scheduled_attempt_count"] == 154
    assert output["schedule_identity"]["unscorable_attempt_count"] == 18
    assert output["cost_role"] == "telemetry_only_not_an_operational_stop"


def test_e02_dry_run_rejects_deployment_from_another_system_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    deployment_root = _private_e02_deployment_gate(workspace, "f" * 40)

    def reject_source(*args, expected_source_commit=None, **kwargs):
        assert expected_source_commit == commit
        raise BaselineBatchError("deployment record source commit changed")

    monkeypatch.setattr(
        "omni_benchmark.baseline_batch_cli.verify_deployment_gate", reject_source
    )

    with pytest.raises(BaselineBatchError, match="source commit"):
        baseline_batch_main(
            [
                "--workspace",
                str(workspace),
                "--system-commit",
                commit,
                "--run-id",
                "e02-dev-a-v1",
                "--observed-attempt-cost-usd",
                "0.7275655",
                "--cost-ceiling-usd",
                "700",
                "--dry-run-e02-dev-a-experiment",
                "--freeze-a-commit",
                "7d39ee107338da1ce10e2553a4290e64bfc2f892",
                "--output-root",
                "experiments/autoresearch/raw/e02-dev-a-v1",
                "--deployment-root",
                str(deployment_root),
                "--deployment-run-id",
                "public-baseline-v13-20260829",
                "--observed-condition-cost",
                "C4=0.7275655",
                "--maximum-wall-clock-seconds",
                "21600",
            ]
        )


def test_live_e02_generation_requires_a_separate_fresh_human_receipt(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    with pytest.raises(BaselineBatchError, match="human approval receipt"):
        baseline_batch_main(
            [
                "--workspace",
                str(workspace),
                "--system-commit",
                commit,
                "--run-id",
                "e02-dev-a-unapproved",
                "--observed-attempt-cost-usd",
                "0.7275655",
                "--cost-ceiling-usd",
                "700",
                "--execute-live-e02-dev-a-experiment",
                "--freeze-a-commit",
                "7d39ee107338da1ce10e2553a4290e64bfc2f892",
                "--output-root",
                "experiments/autoresearch/raw/e02-dev-a-unapproved",
                "--deployment-root",
                str(workspace / "experiments/deployments/public-baseline-v13"),
                "--deployment-run-id",
                "public-baseline-v13-20260829",
                "--observed-condition-cost",
                "C4=0.7275655",
                "--maximum-wall-clock-seconds",
                "21600",
                "--attempt-cost-ceiling-usd",
                "7",
            ]
        )


def test_live_c4_production_requires_fresh_human_approval_before_dispatch(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    with pytest.raises(BaselineBatchError, match="human approval receipt"):
        baseline_batch_main(
            [
                "--workspace",
                str(workspace),
                "--system-commit",
                commit,
                "--run-id",
                "public-c4-baseline-unapproved-test",
                "--observed-attempt-cost-usd",
                "0.7275655",
                "--cost-ceiling-usd",
                "560",
                "--execute-live-c4-baseline",
                "--freeze-a-commit",
                "7d39ee107338da1ce10e2553a4290e64bfc2f892",
                "--output-root",
                "experiments/autoresearch/raw/public-c4-baseline-unapproved-test",
                "--observed-condition-cost",
                "C4=0.7275655",
                "--maximum-wall-clock-seconds",
                "21600",
                "--attempt-cost-ceiling-usd",
                "7",
            ]
        )


def test_live_c4_rejects_missing_omni_environment_before_approval_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    receipt = tmp_path / "unused-approval.json"
    for name in ("OMNI_API_TOKEN", "OMNI_BASE_URL", "OMNI_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "omni_benchmark.baseline_batch_cli.verify_derived_deployment_gate",
        lambda _workspace, _commit, _spec, databases: {
            database: DeploymentTarget(
                branch_id=f"branch-{index}",
                model_id=f"model-{index}",
                semantic_model_sha256=hashlib.sha256(database.encode()).hexdigest(),
            )
            for index, database in enumerate(sorted(databases))
        },
    )

    with pytest.raises(BaselineBatchError, match="OMNI_BASE_URL must be set"):
        baseline_batch_main(
            [
                "--workspace",
                str(workspace),
                "--system-commit",
                commit,
                "--run-id",
                "public-c4-baseline-environment-preflight-test",
                "--observed-attempt-cost-usd",
                "0.7275655",
                "--cost-ceiling-usd",
                "560",
                "--execute-live-c4-baseline",
                "--freeze-a-commit",
                "7d39ee107338da1ce10e2553a4290e64bfc2f892",
                "--output-root",
                (
                    "experiments/autoresearch/raw/"
                    "public-c4-baseline-environment-preflight-test"
                ),
                "--observed-condition-cost",
                "C4=0.7275655",
                "--maximum-wall-clock-seconds",
                "21600",
                "--attempt-cost-ceiling-usd",
                "7",
                "--human-approval-receipt",
                str(receipt),
            ]
        )

    assert not receipt.exists()
    assert not (workspace / "experiments/approvals").exists()
    assert not (workspace / "experiments/autoresearch/raw").exists()

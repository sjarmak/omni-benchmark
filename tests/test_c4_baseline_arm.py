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
    "residential_data_large",
    "reverse_logistics_large",
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
        Path("data/manifests/train_ids.txt"),
        Path("data/manifests/eligible_questions.jsonl"),
        Path("data/manifests/c4_public_baseline_ids.txt"),
        Path("data/manifests/c4_paired_analysis_ids.txt"),
        Path("data/manifests/c4_public_baseline_metadata.json"),
    )
    deployment = ROOT / "experiments/deployments/public-baseline-v6"
    for source in paths:
        destination = workspace / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / source, destination)
    shutil.copytree(
        deployment,
        workspace / "experiments/deployments/public-baseline-v6",
    )
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


def test_public_c4_arm_regenerates_byte_identically() -> None:
    rendered = render_c4_baseline_arm(ROOT, SPEC)

    assert len(rendered.full_ids) == 129
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
    assert sum(item["selected_count"] for item in metadata["allocation"]) == 129
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

    assert len(selected.attempts) == 129
    assert tuple(item.instance_id for item in selected.attempts) == expected_ids
    assert {item.condition for item in selected.attempts} == {"C4"}
    assert len({item.database for item in selected.attempts}) == 10


def test_derived_gate_rejects_any_changed_selected_record(
    tmp_path: Path,
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    record = (
        workspace
        / "experiments/deployments/public-baseline-v6"
        / "public-baseline-v6-20260828.cross_border_large.json"
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
        / "experiments/deployments/public-baseline-v6"
        / "public-baseline-v6-20260828.cross_border_large.json"
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


def test_derived_gate_resolves_all_ten_verified_targets(tmp_path: Path) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    targets = verify_derived_deployment_gate(
        workspace,
        commit,
        SPEC,
        {
            "archeology_scan_large",
            "cross_border_large",
            "cybermarket_pattern_large",
            "disaster_relief_large",
            "exchange_traded_funds_large",
            "fake_account_large",
            "labor_certification_applications_large",
            "museum_artifact_large",
            "residential_data_large",
            "reverse_logistics_large",
        },
    )

    assert len(targets) == 10
    assert all(target.branch_id and target.model_id for target in targets.values())
    assert all(len(target.semantic_model_sha256) == 64 for target in targets.values())


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


def test_c4_dry_run_projects_exact_product_arm_without_direct_credentials(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    result = baseline_batch_main(
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

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution_plan"]["attempt_count"] == 129
    assert {item["condition"] for item in output["execution_plan"]["attempts"]} == {
        "C4"
    }
    assert output["execution_plan"]["claude_oauth_slot_count"] == 0
    assert output["cost_role"] == "telemetry_only_not_an_operational_stop"
    assert output["operational_stop"] == {
        "maximum_wall_clock_seconds": 21600.0,
        "policy": "finish_started_database_condition_blocks",
    }


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
                "public-c4-baseline-v2",
                "--observed-attempt-cost-usd",
                "0.7275655",
                "--cost-ceiling-usd",
                "560",
                "--execute-live-c4-baseline",
                "--freeze-a-commit",
                "7d39ee107338da1ce10e2553a4290e64bfc2f892",
                "--output-root",
                "experiments/autoresearch/raw/public-c4-baseline-v2",
                "--observed-condition-cost",
                "C4=0.7275655",
                "--maximum-wall-clock-seconds",
                "21600",
                "--attempt-cost-ceiling-usd",
                "7",
            ]
        )

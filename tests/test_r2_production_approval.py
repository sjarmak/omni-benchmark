"""Exact, single-use approval for the paired R2 development series."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from omni_benchmark.r2_production_approval import (
    R2ProductionApprovalError,
    consume_r2_production_approval,
    validate_r2_production_approval,
)


NOW = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)


def _binding() -> dict[str, object]:
    return {
        "attempt_count": 272,
        "balanced_ai_settings_sha256": "1" * 64,
        "budget_id": "r2-budget-v1",
        "budget_policy_sha256": "2" * 64,
        "bundle_set_sha256": "3" * 64,
        "conditions": ["R2-C5B", "R2-M1"],
        "deployment_run_ids": {
            "R2-C5B": "r2-c5b-deployment-v1",
            "R2-M1": "r2-m1-deployment-v1",
        },
        "deployment_sha256": {"R2-C5B": "4" * 64, "R2-M1": "5" * 64},
        "execution_plan_sha256": "6" * 64,
        "finalization_root": "runs/r2-finalized-v1",
        "freeze_a_commit": "7" * 40,
        "maximum_concurrency": 1,
        "maximum_wall_clock_seconds": 43200,
        "opportunity_map_artifact_sha256": "8" * 64,
        "opportunity_map_sha256": "9" * 64,
        "output_root": "runs/r2-v1",
        "projected_arm_cost_usd": {"R2-C5B": "10", "R2-M1": "11"},
        "projected_total_cost_usd": "21",
        "run_ids": {"R2-C5B": "r2-c5b-v1", "R2-M1": "r2-m1-v1"},
        "runtime_sources_sha256": "a" * 64,
        "schedule_sha256": "b" * 64,
        "series_id": "r2-public-evidence-measures-v1",
        "source_cleanup_bead_id": "omni-benchmark-ei0.10.16",
        "source_cleanup_closed_at": "2026-09-01T19:00:00Z",
        "system_commit": "c" * 40,
    }


def _receipt(path: Path, **changes: object) -> bytes:
    value: dict[str, object] = {
        "approved_at": "2026-09-01T19:59:30Z",
        "binding": _binding(),
        "decision_bead_id": "omni-benchmark-r2-action-1",
        "expires_at": "2026-09-01T20:59:30Z",
        "kind": "r2-paired-series-standing-approval",
        "nonce": "d" * 64,
        "schema_version": 1,
    }
    value.update(changes)
    content = (
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()
    path.write_bytes(content)
    path.chmod(0o600)
    return content


def _decision(
    _workspace: Path, decision_id: str, content: bytes
) -> tuple[dict[str, object], tuple[str, ...]]:
    assert decision_id == "omni-benchmark-r2-action-1"
    return (
        {
            "close_reason": "Responded",
            "closed_at": "2026-09-01T19:59:30Z",
            "id": decision_id,
            "issue_type": "decision",
            "labels": ["human"],
            "status": "closed",
        },
        ("Response: " + content.decode().strip(),),
    )


def test_current_receipt_binds_the_complete_paired_action(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)

    approval = validate_r2_production_approval(
        tmp_path,
        path,
        _binding(),
        now=NOW,
        decision_loader=lambda workspace, decision_id: _decision(
            workspace, decision_id, content
        ),
    )

    assert approval.binding == _binding()
    assert approval.receipt_sha256 == hashlib.sha256(content).hexdigest()
    assert approval.expires_at == datetime(2026, 9, 1, 20, 59, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"kind": "c4-production-human-approval"}, "schema"),
        ({"expires_at": "2026-09-01T20:00:00Z"}, "expired"),
        ({"expires_at": "2026-09-03T20:00:00Z"}, "validity"),
        ({"nonce": "short"}, "schema"),
    ],
)
def test_stale_or_wrong_receipt_fails_closed(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path, **change)

    with pytest.raises(R2ProductionApprovalError, match=message):
        validate_r2_production_approval(
            tmp_path,
            path,
            _binding(),
            now=NOW,
            decision_loader=lambda workspace, decision_id: _decision(
                workspace, decision_id, content
            ),
        )


def test_substituted_binding_and_noncanonical_receipt_are_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)
    changed = _binding()
    changed["opportunity_map_sha256"] = "f" * 64
    with pytest.raises(R2ProductionApprovalError, match="does not match"):
        validate_r2_production_approval(
            tmp_path,
            path,
            changed,
            now=NOW,
            decision_loader=lambda workspace, decision_id: _decision(
                workspace, decision_id, content
            ),
        )

    value = json.loads(content)
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    with pytest.raises(R2ProductionApprovalError, match="canonical"):
        validate_r2_production_approval(
            tmp_path,
            path,
            _binding(),
            now=NOW,
            decision_loader=lambda workspace, decision_id: _decision(
                workspace, decision_id, path.read_bytes()
            ),
        )


def test_decision_must_authenticate_one_exact_response(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    _receipt(path)

    with pytest.raises(R2ProductionApprovalError, match="decision"):
        validate_r2_production_approval(
            tmp_path,
            path,
            _binding(),
            now=NOW,
            decision_loader=lambda _workspace, decision_id: (
                {
                    "close_reason": "Completed",
                    "closed_at": "2026-09-01T19:59:30Z",
                    "id": decision_id,
                    "issue_type": "task",
                    "labels": [],
                    "status": "closed",
                },
                (),
            ),
        )


def test_consumption_is_confined_exclusive_and_single_use(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)
    approval = validate_r2_production_approval(
        tmp_path,
        path,
        _binding(),
        now=NOW,
        decision_loader=lambda workspace, decision_id: _decision(
            workspace, decision_id, content
        ),
    )

    private_root = tmp_path / "experiments" / "approvals"
    private_root.mkdir(parents=True)
    (tmp_path / "experiments").chmod(0o777)
    private_root.chmod(0o777)
    marker = consume_r2_production_approval(
        tmp_path,
        Path("experiments/approvals/r2-paired"),
        approval,
        now=NOW,
    )
    assert marker.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "experiments").stat().st_mode & 0o777 == 0o700
    assert private_root.stat().st_mode & 0o777 == 0o700
    assert marker.parent.stat().st_mode & 0o777 == 0o700
    value = json.loads(marker.read_text(encoding="utf-8"))
    assert value["receipt_sha256"] == approval.receipt_sha256
    assert value["binding"] == _binding()
    with pytest.raises(R2ProductionApprovalError, match="already consumed"):
        consume_r2_production_approval(
            tmp_path,
            Path("experiments/approvals/r2-paired"),
            approval,
            now=NOW,
        )
    with pytest.raises(R2ProductionApprovalError, match="confined"):
        consume_r2_production_approval(tmp_path, Path("../outside"), approval, now=NOW)


def test_consumption_rechecks_expiry_after_authorization(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)
    approval = validate_r2_production_approval(
        tmp_path,
        path,
        _binding(),
        now=NOW,
        decision_loader=lambda workspace, decision_id: _decision(
            workspace, decision_id, content
        ),
    )

    with pytest.raises(R2ProductionApprovalError, match="expired"):
        consume_r2_production_approval(
            tmp_path,
            Path("experiments/approvals/expired"),
            approval,
            now=NOW + timedelta(hours=2),
        )


def test_receipt_uses_one_bounded_nofollow_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _self: pytest.fail("receipt path must not be reopened after metadata"),
    )

    approval = validate_r2_production_approval(
        tmp_path,
        path,
        _binding(),
        now=NOW,
        decision_loader=lambda workspace, decision_id: _decision(
            workspace, decision_id, content
        ),
    )

    assert approval.receipt_sha256 == hashlib.sha256(content).hexdigest()


def test_receipt_requires_private_regular_bytes_and_aware_clock(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)
    path.chmod(0o644)
    with pytest.raises(R2ProductionApprovalError, match="unsafe"):
        validate_r2_production_approval(tmp_path, path, _binding(), now=NOW)
    path.chmod(0o600)
    with pytest.raises(R2ProductionApprovalError, match="timezone-aware"):
        validate_r2_production_approval(
            tmp_path,
            path,
            _binding(),
            now=datetime(2026, 9, 1, 20, 0),
            decision_loader=lambda workspace, decision_id: _decision(
                workspace, decision_id, content
            ),
        )

    hardlink = tmp_path / "hardlink.json"
    hardlink.hardlink_to(path)
    with pytest.raises(R2ProductionApprovalError, match="unsafe"):
        validate_r2_production_approval(tmp_path, path, _binding(), now=NOW)


def test_consumption_rejects_symlinked_directory_component(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)
    approval = validate_r2_production_approval(
        tmp_path,
        path,
        _binding(),
        now=NOW,
        decision_loader=lambda workspace, decision_id: _decision(
            workspace, decision_id, content
        ),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "experiments").symlink_to(outside, target_is_directory=True)

    with pytest.raises(R2ProductionApprovalError, match="confined"):
        consume_r2_production_approval(
            tmp_path,
            Path("experiments/approvals/r2-paired"),
            approval,
            now=NOW,
        )


def test_duplicate_or_nonfinite_json_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    path.write_text('{"approved_at":"x","approved_at":"y"}\n', encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(R2ProductionApprovalError, match="duplicate"):
        validate_r2_production_approval(tmp_path, path, _binding(), now=NOW)
    path.write_text('{"approved_at":NaN}\n', encoding="utf-8")
    with pytest.raises(R2ProductionApprovalError, match="constant"):
        validate_r2_production_approval(tmp_path, path, _binding(), now=NOW)


def test_default_beads_loader_accepts_bounded_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)
    issue, comments = _decision(tmp_path, "omni-benchmark-r2-action-1", content)
    responses = iter(
        (
            SimpleNamespace(returncode=0, stdout=json.dumps([issue]).encode()),
            SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"text": comments[0]}]).encode(),
            ),
        )
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("OMNI_API_TOKEN", "must-not-reach-bd")
    monkeypatch.setenv("DOLTHUB_TOKEN", "must-not-reach-local-bd")

    def run(*_args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(
        "omni_benchmark.r2_production_approval.subprocess.run",
        run,
    )

    approval = validate_r2_production_approval(tmp_path, path, _binding(), now=NOW)

    assert approval.decision_bead_id == "omni-benchmark-r2-action-1"
    assert len(calls) == 2
    for call in calls:
        environment = call["env"]
        assert isinstance(environment, dict)
        assert "OMNI_API_TOKEN" not in environment
        assert "DOLTHUB_TOKEN" not in environment
        assert "PATH" in environment

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from omni_benchmark.c4_production_approval import (
    C4ProductionApprovalError,
    consume_c4_production_approval,
    validate_c4_production_approval,
)


NOW = datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)
BINDING = {
    "condition": "C4",
    "deployment_sha256": "a" * 64,
    "execution_plan_sha256": "b" * 64,
    "output_root": "experiments/autoresearch/raw/public-c4-baseline-v2",
    "run_id": "public-c4-baseline-v2",
    "schedule_sha256": "c" * 64,
    "system_commit": "d" * 40,
}


def _receipt(path: Path, **changes: object) -> bytes:
    value = {
        "approved_at": "2026-08-28T19:55:00Z",
        "binding": BINDING,
        "decision_bead_id": "omni-benchmark-approval-1",
        "expires_at": "2026-08-28T20:30:00Z",
        "kind": "c4-production-human-approval",
        "nonce": "e" * 64,
        "schema_version": 1,
        **changes,
    }
    content = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()
    path.write_bytes(content)
    return content


def _decision(_workspace: Path, decision_id: str) -> tuple[dict, tuple[str, ...]]:
    assert decision_id == "omni-benchmark-approval-1"
    return (
        {
            "close_reason": "Responded",
            "closed_at": "2026-08-28T19:55:00Z",
            "id": decision_id,
            "issue_type": "decision",
            "labels": ["human"],
            "status": "closed",
        },
        (),
    )


def test_current_human_receipt_binds_exact_production_identity(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)

    def decision(workspace: Path, decision_id: str):
        issue, _ = _decision(workspace, decision_id)
        return issue, ("Response: " + content.decode().strip(),)

    approval = validate_c4_production_approval(
        tmp_path, path, BINDING, now=NOW, decision_loader=decision
    )

    assert approval.binding == BINDING
    assert approval.receipt_sha256


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"expires_at": "2026-08-28T19:59:59Z"}, "expired"),
        ({"binding": {**BINDING, "run_id": "replacement"}}, "binding"),
    ],
)
def test_stale_or_wrong_approval_fails_closed(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path, **changes)

    def decision(workspace: Path, decision_id: str):
        issue, _ = _decision(workspace, decision_id)
        return issue, ("Response: " + content.decode().strip(),)

    with pytest.raises(C4ProductionApprovalError, match=message):
        validate_c4_production_approval(
            tmp_path, path, BINDING, now=NOW, decision_loader=decision
        )


def test_unanswered_decision_or_forged_receipt_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    _receipt(path)

    with pytest.raises(C4ProductionApprovalError, match="human decision"):
        validate_c4_production_approval(
            tmp_path, path, BINDING, now=NOW, decision_loader=_decision
        )


def test_multiple_response_comments_cannot_expand_a_closed_decision(
    tmp_path: Path,
) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)

    def decision(workspace: Path, decision_id: str):
        issue, _ = _decision(workspace, decision_id)
        response = "Response: " + content.decode().strip()
        return issue, (response, response)

    with pytest.raises(C4ProductionApprovalError, match="human decision"):
        validate_c4_production_approval(
            tmp_path, path, BINDING, now=NOW, decision_loader=decision
        )


def test_approval_consumption_is_exclusive_and_single_use(tmp_path: Path) -> None:
    path = tmp_path / "approval.json"
    content = _receipt(path)

    def decision(workspace: Path, decision_id: str):
        issue, _ = _decision(workspace, decision_id)
        return issue, ("Response: " + content.decode().strip(),)

    approval = validate_c4_production_approval(
        tmp_path, path, BINDING, now=NOW, decision_loader=decision
    )
    first = consume_c4_production_approval(
        tmp_path, Path("experiments/approvals/c4"), approval
    )

    assert first.stat().st_mode & 0o777 == 0o600
    with pytest.raises(C4ProductionApprovalError, match="already consumed"):
        consume_c4_production_approval(
            tmp_path, Path("experiments/approvals/c4"), approval
        )


def test_consumption_root_cannot_escape_through_a_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "experiments").symlink_to(outside, target_is_directory=True)
    approval = type(
        "Approval",
        (),
        {
            "binding": BINDING,
            "decision_bead_id": "omni-benchmark-approval-1",
            "nonce": "e" * 64,
            "receipt_sha256": "f" * 64,
        },
    )()

    with pytest.raises(C4ProductionApprovalError, match="not confined"):
        consume_c4_production_approval(
            tmp_path, Path("experiments/approvals/c4"), approval
        )
    assert not (outside / "approvals").exists()

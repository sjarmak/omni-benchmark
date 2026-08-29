from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from omni_benchmark.sealed_production_approval import (
    SealedProductionApprovalError,
    consume_sealed_production_approval,
    validate_sealed_production_approval,
)


NOW = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
BINDING = {
    "attempt_count": 1_212,
    "conditions": ["C1", "C2", "C3", "C4"],
    "control_commit": "a" * 40,
    "cost_ceiling_usd": "1200.000000",
    "freeze_b_sha256": "b" * 64,
    "maximum_concurrency": 3,
    "maximum_wall_clock_seconds": 43200,
    "output_root": "runs/sealed-final-v1",
    "plan_sha256": "c" * 64,
    "policy_sha256": "d" * 64,
    "run_id": "sealed-final-v1",
    "runtime_sources_sha256": "e" * 64,
    "schedule_sha256": "f" * 64,
    "system_commit": "1" * 40,
}


def _receipt(path: Path, **changes: object) -> bytes:
    value = {
        "approved_at": "2026-08-29T07:55:00Z",
        "binding": BINDING,
        "decision_bead_id": "omni-benchmark-sealed-approval-1",
        "expires_at": "2026-08-29T08:30:00Z",
        "kind": "sealed-production-human-approval",
        "nonce": "2" * 64,
        "schema_version": 1,
        **changes,
    }
    content = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()
    path.write_bytes(content)
    path.chmod(0o600)
    return content


def _issue(decision_id: str) -> dict[str, object]:
    return {
        "close_reason": "Responded",
        "closed_at": "2026-08-29T07:55:00Z",
        "id": decision_id,
        "issue_type": "decision",
        "labels": ["human"],
        "status": "closed",
    }


def _validated(tmp_path: Path, **changes: object):  # type: ignore[no-untyped-def]
    path = tmp_path / "sealed-approval.json"
    content = _receipt(path, **changes)

    def decision(_workspace: Path, decision_id: str):
        return _issue(decision_id), ("Response: " + content.decode().strip(),)

    return validate_sealed_production_approval(
        tmp_path,
        path,
        BINDING,
        now=NOW,
        decision_loader=decision,
    )


def test_exact_current_human_receipt_binds_sealed_dispatch(tmp_path: Path) -> None:
    approval = _validated(tmp_path)

    assert approval.binding == BINDING
    assert approval.decision_bead_id == "omni-benchmark-sealed-approval-1"
    assert len(approval.receipt_sha256) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"expires_at": "2026-08-29T07:59:59Z"}, "expired"),
        ({"approved_at": "2026-08-29T08:01:00Z"}, "expired"),
        ({"expires_at": "2026-08-29T09:00:01Z"}, "window"),
        ({"binding": {**BINDING, "run_id": "other"}}, "binding"),
        ({"binding": {**BINDING, "attempt_count": True}}, "schema"),
        ({"binding": {**BINDING, "conditions": ["C1", "C2"]}}, "schema"),
        ({"binding": {**BINDING, "output_root": "../escape"}}, "schema"),
        ({"binding": {**BINDING, "output_root": 7}}, "schema"),
        ({"binding": {**BINDING, "cost_ceiling_usd": "NaN"}}, "schema"),
        ({"binding": {**BINDING, "cost_ceiling_usd": "1E+999"}}, "schema"),
    ],
)
def test_stale_malformed_or_wrong_binding_fails(
    tmp_path: Path, changes: dict[str, object], message: str
) -> None:
    path = tmp_path / "sealed-approval.json"
    content = _receipt(path, **changes)

    def decision(_workspace: Path, decision_id: str):
        return _issue(decision_id), ("Response: " + content.decode().strip(),)

    with pytest.raises(SealedProductionApprovalError, match=message):
        validate_sealed_production_approval(
            tmp_path,
            path,
            BINDING,
            now=NOW,
            decision_loader=decision,
        )


def test_unanswered_or_multiple_response_comments_fail(tmp_path: Path) -> None:
    path = tmp_path / "sealed-approval.json"
    content = _receipt(path)

    def unanswered(_workspace: Path, decision_id: str):
        return _issue(decision_id), ()

    with pytest.raises(SealedProductionApprovalError, match="decision"):
        validate_sealed_production_approval(
            tmp_path,
            path,
            BINDING,
            now=NOW,
            decision_loader=unanswered,
        )

    def duplicated(_workspace: Path, decision_id: str):
        response = "Response: " + content.decode().strip()
        return _issue(decision_id), (response, response)

    with pytest.raises(SealedProductionApprovalError, match="decision"):
        validate_sealed_production_approval(
            tmp_path,
            path,
            BINDING,
            now=NOW,
            decision_loader=duplicated,
        )


def test_receipt_requires_private_regular_canonical_unique_json(tmp_path: Path) -> None:
    path = tmp_path / "sealed-approval.json"
    content = _receipt(path)
    path.chmod(0o644)

    with pytest.raises(SealedProductionApprovalError, match="private"):
        validate_sealed_production_approval(tmp_path, path, BINDING, now=NOW)

    path.chmod(0o600)
    path.write_text(json.dumps(json.loads(content), indent=2) + "\n")
    with pytest.raises(SealedProductionApprovalError, match="canonical"):
        validate_sealed_production_approval(tmp_path, path, BINDING, now=NOW)

    path.write_text('{"kind":"x","kind":"y"}\n')
    with pytest.raises(SealedProductionApprovalError, match="duplicate"):
        validate_sealed_production_approval(tmp_path, path, BINDING, now=NOW)


def test_consumption_is_private_exclusive_and_single_use(tmp_path: Path) -> None:
    approval = _validated(tmp_path)

    first = consume_sealed_production_approval(
        tmp_path, Path("runs/approvals/sealed-production"), approval
    )

    assert first.stat().st_mode & 0o777 == 0o600
    marker = json.loads(first.read_text())
    assert marker["receipt_sha256"] == approval.receipt_sha256
    assert marker["binding"] == BINDING
    with pytest.raises(SealedProductionApprovalError, match="already consumed"):
        consume_sealed_production_approval(
            tmp_path, Path("runs/approvals/sealed-production"), approval
        )


def test_consumption_root_cannot_escape_or_follow_symlink(tmp_path: Path) -> None:
    approval = _validated(tmp_path)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "runs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(SealedProductionApprovalError, match="confined"):
        consume_sealed_production_approval(
            tmp_path, Path("runs/approvals/sealed-production"), approval
        )

    with pytest.raises(SealedProductionApprovalError, match="confined"):
        consume_sealed_production_approval(tmp_path, Path("../escape"), approval)
    assert list(outside.iterdir()) == []


def test_schema_clock_timestamp_and_json_failures_are_sanitized(tmp_path: Path) -> None:
    path = tmp_path / "sealed-approval.json"
    path.write_text("{}\n")
    path.chmod(0o600)
    with pytest.raises(SealedProductionApprovalError, match="schema"):
        validate_sealed_production_approval(tmp_path, path, BINDING, now=NOW)

    _receipt(path, kind="wrong")
    with pytest.raises(SealedProductionApprovalError, match="schema"):
        validate_sealed_production_approval(tmp_path, path, BINDING, now=NOW)

    content = _receipt(path)

    def decision(_workspace: Path, decision_id: str):
        return _issue(decision_id), ("Response: " + content.decode().strip(),)

    with pytest.raises(SealedProductionApprovalError, match="clock"):
        validate_sealed_production_approval(
            tmp_path,
            path,
            BINDING,
            now=datetime(2026, 8, 29, 8, 0),
            decision_loader=decision,
        )

    _receipt(path, approved_at="not-a-time")
    with pytest.raises(SealedProductionApprovalError, match="approved_at"):
        validate_sealed_production_approval(tmp_path, path, BINDING, now=NOW)

    path.write_bytes(b"not-json\n")
    with pytest.raises(SealedProductionApprovalError, match="invalid JSON"):
        validate_sealed_production_approval(tmp_path, path, BINDING, now=NOW)


def test_unavailable_receipt_and_mutated_approval_fail(tmp_path: Path) -> None:
    with pytest.raises(SealedProductionApprovalError, match="unavailable"):
        validate_sealed_production_approval(
            tmp_path, tmp_path / "absent.json", BINDING, now=NOW
        )

    with pytest.raises(SealedProductionApprovalError, match="invalid"):
        consume_sealed_production_approval(
            tmp_path,
            Path("runs/approvals/sealed-production"),
            object(),  # type: ignore[arg-type]
        )

    approval = _validated(tmp_path)
    forged = replace(approval, nonce="bad")
    with pytest.raises(SealedProductionApprovalError, match="invalid"):
        consume_sealed_production_approval(
            tmp_path, Path("runs/approvals/sealed-production"), forged
        )

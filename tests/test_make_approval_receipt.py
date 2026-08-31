"""The generated receipt must satisfy the validator that gates live dispatch."""

from __future__ import annotations

import hashlib
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from omni_benchmark.c4_production_approval import (
    C4ProductionApprovalError,
    validate_c4_production_approval,
)

_MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "make_approval_receipt.py"
)
_SPEC = importlib.util.spec_from_file_location("make_approval_receipt", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
receipts = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(receipts)

BINDING = {
    "condition": "C4",
    "deployment_sha256": "a" * 64,
    "execution_plan_sha256": "b" * 64,
    "output_root": "runs/c5-dev-a-generation-v1",
    "run_id": "c5-dev-a-generation-v1",
    "schedule_sha256": "c" * 64,
    "system_commit": "3a7e52b549a233c93fff3397f7551500de96807d",
}
DECISION_ID = "omni-benchmark-czf"


def _write(tmp_path: Path, receipt: dict[str, object]) -> Path:
    path = tmp_path / "receipt.json"
    path.write_bytes(receipts.canonical_json(receipt))
    return path


def _loader(receipt: dict[str, object], *, closed_at: datetime):
    response = "Response: " + receipts.canonical_json(receipt).decode().strip()

    def load(_root: Path, decision_id: str):
        issue = {
            "id": decision_id,
            "issue_type": "decision",
            "status": "closed",
            "close_reason": "Responded",
            "labels": ["human", "c5"],
            "closed_at": closed_at.isoformat().replace("+00:00", "Z"),
        }
        return issue, (response,)

    return load


def test_generated_receipt_authenticates(tmp_path: Path) -> None:
    approved = datetime.now(timezone.utc)
    receipt = receipts.build_receipt(
        BINDING,
        decision_bead_id=DECISION_ID,
        approved_at=approved,
        validity=timedelta(hours=1),
        nonce="d" * 64,
    )
    path = _write(tmp_path, receipt)
    approval = validate_c4_production_approval(
        tmp_path,
        path,
        BINDING,
        now=approved + timedelta(seconds=5),
        decision_loader=_loader(receipt, closed_at=approved),
    )
    assert approval.decision_bead_id == DECISION_ID
    assert approval.binding == BINDING
    assert approval.receipt_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_canonical_form_matches_the_validator(tmp_path: Path) -> None:
    """A receipt that is not byte-canonical is rejected, so ours must be exact."""
    receipt = receipts.build_receipt(
        BINDING,
        decision_bead_id=DECISION_ID,
        approved_at=datetime.now(timezone.utc),
        validity=timedelta(hours=1),
        nonce="d" * 64,
    )
    assert receipts.canonical_json(receipt).endswith(b"}\n")
    assert b", " not in receipts.canonical_json(receipt)


def test_binding_mismatch_is_rejected(tmp_path: Path) -> None:
    approved = datetime.now(timezone.utc)
    receipt = receipts.build_receipt(
        BINDING,
        decision_bead_id=DECISION_ID,
        approved_at=approved,
        validity=timedelta(hours=1),
        nonce="d" * 64,
    )
    path = _write(tmp_path, receipt)
    other = {**BINDING, "run_id": "c5-dev-a-generation-v2"}
    with pytest.raises(C4ProductionApprovalError):
        validate_c4_production_approval(
            tmp_path,
            path,
            other,
            now=approved + timedelta(seconds=5),
            decision_loader=_loader(receipt, closed_at=approved),
        )


def test_late_close_is_rejected(tmp_path: Path) -> None:
    """The 60-second window between approved_at and the close is enforced."""
    approved = datetime.now(timezone.utc)
    receipt = receipts.build_receipt(
        BINDING,
        decision_bead_id=DECISION_ID,
        approved_at=approved,
        validity=timedelta(hours=1),
        nonce="d" * 64,
    )
    path = _write(tmp_path, receipt)
    with pytest.raises(C4ProductionApprovalError):
        validate_c4_production_approval(
            tmp_path,
            path,
            BINDING,
            now=approved + timedelta(seconds=5),
            decision_loader=_loader(receipt, closed_at=approved + timedelta(minutes=3)),
        )


def test_validity_window_is_bounded() -> None:
    with pytest.raises(receipts.ReceiptError):
        receipts.build_receipt(
            BINDING,
            decision_bead_id=DECISION_ID,
            approved_at=datetime.now(timezone.utc),
            validity=timedelta(hours=48),
            nonce="d" * 64,
        )

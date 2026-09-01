"""Canonical receipt materialization for a fully preflighted R2 binding."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from omni_benchmark.r2_receipt_cli import (
    R2ReceiptError,
    build_r2_receipt,
    materialize_r2_receipt,
)
import omni_benchmark.r2_receipt_cli as receipt_cli


NOW = datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc)


def _binding() -> dict[str, object]:
    return {
        "attempt_count": 272,
        "execution_plan_sha256": "a" * 64,
        "series_id": "r2-public-evidence-measures-v1",
        "system_commit": "b" * 40,
    }


def test_receipt_is_canonical_and_exactly_binds_preflight() -> None:
    receipt = build_r2_receipt(
        _binding(),
        decision_bead_id="omni-benchmark-r2-action-1",
        approved_at=NOW,
        validity=timedelta(hours=1),
        nonce="c" * 64,
    )
    assert receipt["binding"] == _binding()
    assert receipt["kind"] == "r2-paired-series-standing-approval"
    assert receipt["approved_at"] == "2026-09-01T20:00:00Z"
    assert receipt["expires_at"] == "2026-09-01T21:00:00Z"


@pytest.mark.parametrize(
    ("decision", "validity", "nonce"),
    [
        ("bad id!", timedelta(hours=1), "c" * 64),
        ("decision", timedelta(0), "c" * 64),
        ("decision", timedelta(hours=25), "c" * 64),
        ("decision", timedelta(hours=1), "short"),
    ],
)
def test_receipt_rejects_invalid_authorization_identity(
    decision: str, validity: timedelta, nonce: str
) -> None:
    with pytest.raises(R2ReceiptError):
        build_r2_receipt(
            _binding(),
            decision_bead_id=decision,
            approved_at=NOW,
            validity=validity,
            nonce=nonce,
        )


def test_materialization_is_private_exclusive_and_writes_exact_response(
    tmp_path: Path,
) -> None:
    receipt = build_r2_receipt(
        _binding(),
        decision_bead_id="omni-benchmark-r2-action-1",
        approved_at=NOW,
        validity=timedelta(hours=1),
        nonce="c" * 64,
    )
    receipt_path = tmp_path / "approval.json"
    response_path = tmp_path / "response.txt"

    digest = materialize_r2_receipt(receipt_path, response_path, receipt)

    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert response_path.stat().st_mode & 0o777 == 0o600
    content = receipt_path.read_bytes()
    assert content.endswith(b"\n")
    assert json.loads(content) == receipt
    assert response_path.read_text(encoding="utf-8") == (
        "Response: " + content.decode().strip() + "\n"
    )
    assert len(digest) == 64
    with pytest.raises(R2ReceiptError, match="absent"):
        materialize_r2_receipt(receipt_path, response_path, receipt)


def test_main_recomputes_binding_before_materializing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    namespace = SimpleNamespace(
        budget_id="r2-budget-v1",
        control_deployment_root=Path("experiments/deployments/control"),
        decision_bead_id="omni-benchmark-r2-action-1",
        freeze_a_commit="c" * 40,
        maximum_wall_clock_seconds=100,
        receipt_path=tmp_path / "approval.json",
        response_path=tmp_path / "response.txt",
        treatment_deployment_root=Path("experiments/deployments/treatment"),
        validity=timedelta(hours=1),
        workspace=tmp_path,
    )
    monkeypatch.setattr(
        receipt_cli,
        "_parser",
        lambda: SimpleNamespace(parse_args=lambda _argv: namespace),
    )
    monkeypatch.setattr(receipt_cli, "_load_execution_plan", lambda _: object())
    monkeypatch.setattr(
        receipt_cli,
        "prepare_r2_dispatch_inputs",
        lambda **_: SimpleNamespace(binding=_binding()),
    )
    monkeypatch.setattr(receipt_cli.secrets, "token_hex", lambda _: "c" * 64)

    assert receipt_cli.main([]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["receipt_path"] == str(namespace.receipt_path)
    assert len(output["receipt_sha256"]) == 64


def test_entrypoint_sanitizes_unexpected_receipt_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        receipt_cli,
        "main",
        lambda: (_ for _ in ()).throw(RuntimeError("Bearer secret")),
    )
    assert receipt_cli.entrypoint() == 1
    error = capsys.readouterr().err
    assert "Bearer secret" not in error
    assert "internal error" in error

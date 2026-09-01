"""Materialize one canonical standing-authorization receipt for paired R2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .r2_dispatch import R2DispatchPolicy, prepare_r2_dispatch_inputs
from .r2_dispatch_cli import _add_common_arguments, _load_execution_plan
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION
from .r2_production_approval import canonical_r2_approval_json


_DECISION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAXIMUM_VALIDITY = timedelta(hours=24)


class R2ReceiptError(ValueError):
    """Raised when an exact R2 receipt cannot be safely materialized."""


def build_r2_receipt(
    binding: Mapping[str, object],
    *,
    decision_bead_id: str,
    approved_at: datetime,
    validity: timedelta,
    nonce: str,
) -> dict[str, Any]:
    """Build the exact object consumed by the R2 approval validator."""
    if approved_at.tzinfo is None:
        raise R2ReceiptError("approved_at must be timezone-aware")
    if validity <= timedelta(0) or validity > _MAXIMUM_VALIDITY:
        raise R2ReceiptError("validity must be positive and at most 24 hours")
    if _DECISION_ID.fullmatch(decision_bead_id) is None:
        raise R2ReceiptError("decision Beads identity is invalid")
    if _SHA256.fullmatch(nonce) is None:
        raise R2ReceiptError("receipt nonce is invalid")
    try:
        canonical_binding = json.loads(canonical_r2_approval_json(binding))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise R2ReceiptError("receipt binding is invalid") from error
    if not isinstance(canonical_binding, dict):
        raise R2ReceiptError("receipt binding is invalid")
    return {
        "approved_at": _iso(approved_at),
        "binding": canonical_binding,
        "decision_bead_id": decision_bead_id,
        "expires_at": _iso(approved_at + validity),
        "kind": "r2-paired-series-standing-approval",
        "nonce": nonce,
        "schema_version": 1,
    }


def materialize_r2_receipt(
    receipt_path: Path,
    response_path: Path,
    receipt: Mapping[str, object],
) -> str:
    """Write private receipt and exact Beads response with exclusive creation."""
    content = canonical_r2_approval_json(receipt)
    response = ("Response: " + content.decode("utf-8").strip() + "\n").encode()
    if (
        receipt_path == response_path
        or receipt_path.exists()
        or receipt_path.is_symlink()
        or response_path.exists()
        or response_path.is_symlink()
    ):
        raise R2ReceiptError("receipt and response paths must be absent")
    _write_exclusive(receipt_path, content)
    try:
        _write_exclusive(response_path, response)
    except Exception:
        # The receipt is deliberately preserved if the response write fails.
        raise
    return hashlib.sha256(content).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Recompute every non-receipt gate, then materialize the exact bytes."""
    arguments = _parser().parse_args(argv)
    plan = _load_execution_plan(arguments)
    policy = R2DispatchPolicy.create(
        budget_id=arguments.budget_id,
        freeze_a_commit=arguments.freeze_a_commit,
        maximum_wall_clock_seconds=arguments.maximum_wall_clock_seconds,
    )
    inputs = prepare_r2_dispatch_inputs(
        workspace=arguments.workspace,
        plan=plan,
        policy=policy,
        deployment_roots={
            CONTROL_CONDITION: arguments.control_deployment_root,
            TREATMENT_CONDITION: arguments.treatment_deployment_root,
        },
    )
    receipt = build_r2_receipt(
        inputs.binding,
        decision_bead_id=arguments.decision_bead_id,
        approved_at=datetime.now(timezone.utc),
        validity=arguments.validity,
        nonce=secrets.token_hex(32),
    )
    digest = materialize_r2_receipt(
        arguments.receipt_path,
        arguments.response_path,
        receipt,
    )
    print(
        json.dumps(
            {
                "expires_at": receipt["expires_at"],
                "receipt_path": str(arguments.receipt_path),
                "receipt_sha256": digest,
                "response_path": str(arguments.response_path),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def entrypoint() -> int:
    try:
        return main()
    except Exception as error:
        if isinstance(error, R2ReceiptError):
            print(f"R2 receipt failed: {error}", file=sys.stderr)
        else:
            print("R2 receipt failed: internal error", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    _add_common_arguments(parser)
    parser.add_argument("--decision-bead-id", required=True)
    parser.add_argument(
        "--validity-hours", dest="validity", type=_validity, default="1"
    )
    parser.add_argument("--receipt-path", type=Path, required=True)
    parser.add_argument("--response-path", type=Path, required=True)
    return parser


def _validity(value: str) -> timedelta:
    try:
        selected = timedelta(hours=float(value))
    except ValueError as error:
        raise argparse.ArgumentTypeError("validity must be numeric") from error
    if selected <= timedelta(0) or selected > _MAXIMUM_VALIDITY:
        raise argparse.ArgumentTypeError("validity must be within (0, 24] hours")
    return selected


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _write_exclusive(path: Path, content: bytes) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
    except FileExistsError as error:
        raise R2ReceiptError("receipt and response paths must be absent") from error
    except OSError as error:
        raise R2ReceiptError("receipt materialization failed") from error

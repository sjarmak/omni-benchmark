#!/usr/bin/env python3
"""Emit a canonical C4 production approval receipt and the command that answers it.

The receipt is authenticated by validate_c4_production_approval against a Beads
decision that a human closes. This script only assembles the bytes; it never
creates, closes, or comments on the decision, because the comment is the human
attestation the control exists to record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from omni_benchmark.baseline_batch import (
    c4_dev_a_experiment_schedule,
    load_committed_baseline_schedule,
)
from omni_benchmark.baseline_batch_cli import _deployment_targets_sha256
from omni_benchmark.baseline_batch_live import (
    build_execution_plan,
    verify_deployment_gate,
)

RECEIPT_KIND = "c4-production-human-approval"
MAXIMUM_VALIDITY = timedelta(hours=24)


class ReceiptError(ValueError):
    """Raised when the receipt cannot be assembled from verified inputs."""


def canonical_json(value: object) -> bytes:
    """Match c4_production_approval._canonical_json byte for byte."""
    return (
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def compute_binding(
    workspace: Path,
    *,
    system_commit: str,
    freeze_a_commit: str,
    run_id: str,
    output_root: Path,
    deployment_root: Path,
    deployment_run_id: str,
) -> dict[str, str]:
    """Derive the dispatch binding from the same functions the dispatcher uses."""
    full = load_committed_baseline_schedule(workspace, system_commit, run_id=run_id)
    schedule = c4_dev_a_experiment_schedule(workspace, system_commit, full)
    plan = build_execution_plan(
        schedule,
        workspace=workspace,
        output_root=output_root,
        claude_config_directories=(),
        freeze_a_commit=freeze_a_commit,
    )
    targets = verify_deployment_gate(
        deployment_root,
        deployment_run_id,
        {attempt.database for attempt in schedule.attempts},
        expected_source_commit=system_commit,
    )
    return {
        "condition": "C4",
        "deployment_sha256": _deployment_targets_sha256(targets),
        "execution_plan_sha256": plan.sha256,
        "output_root": output_root.as_posix(),
        "run_id": run_id,
        "schedule_sha256": schedule.sha256,
        "system_commit": system_commit,
    }


def build_receipt(
    binding: Mapping[str, str],
    *,
    decision_bead_id: str,
    approved_at: datetime,
    validity: timedelta,
    nonce: str,
) -> dict[str, Any]:
    """Assemble the receipt object the validator accepts."""
    if approved_at.tzinfo is None:
        raise ReceiptError("approved_at must be timezone-aware")
    if validity <= timedelta(0) or validity > MAXIMUM_VALIDITY:
        raise ReceiptError("validity must be positive and at most 24 hours")
    return {
        "approved_at": _iso(approved_at),
        "binding": dict(binding),
        "decision_bead_id": decision_bead_id,
        "expires_at": _iso(approved_at + validity),
        "kind": RECEIPT_KIND,
        "nonce": nonce,
        "schema_version": 1,
    }


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_hours(value: str) -> timedelta:
    hours = float(value)
    if hours <= 0 or hours > 24:
        raise argparse.ArgumentTypeError("validity must be within (0, 24] hours")
    return timedelta(hours=hours)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--freeze-a-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--deployment-root", type=Path, required=True)
    parser.add_argument("--deployment-run-id", required=True)
    parser.add_argument("--decision-bead-id", required=True)
    parser.add_argument("--validity-hours", type=_positive_hours, default="1")
    parser.add_argument("--receipt-path", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    workspace = arguments.workspace.resolve(strict=True)
    binding = compute_binding(
        workspace,
        system_commit=arguments.system_commit,
        freeze_a_commit=arguments.freeze_a_commit,
        run_id=arguments.run_id,
        output_root=arguments.output_root,
        deployment_root=arguments.deployment_root,
        deployment_run_id=arguments.deployment_run_id,
    )
    receipt = build_receipt(
        binding,
        decision_bead_id=arguments.decision_bead_id,
        approved_at=datetime.now(timezone.utc),
        validity=arguments.validity_hours,
        nonce=secrets.token_hex(32),
    )
    content = canonical_json(receipt)
    if arguments.receipt_path.exists() or arguments.receipt_path.is_symlink():
        raise ReceiptError("receipt path must be absent; receipts are single use")
    arguments.receipt_path.write_bytes(content)
    arguments.receipt_path.chmod(0o600)

    text = content.decode("utf-8").strip()
    print(f"receipt written: {arguments.receipt_path}")
    print(f"receipt sha256:  {hashlib.sha256(content).hexdigest()}")
    print(f"expires:         {receipt['expires_at']}")
    print()
    print("The decision comment and the close must land within 60 seconds of")
    print(f"approved_at ({receipt['approved_at']}). Run both as one command:")
    print()
    print(
        f"  bd comment {arguments.decision_bead_id} "
        f"--body-file {arguments.receipt_path.with_suffix('.response.txt')} && \\"
    )
    print(f"  bd close {arguments.decision_bead_id} --reason Responded")
    response_path = arguments.receipt_path.with_suffix(".response.txt")
    response_path.write_text(f"Response: {text}\n", encoding="utf-8")
    print()
    print(f"response body written: {response_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReceiptError, ValueError) as error:
        print(f"receipt assembly failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

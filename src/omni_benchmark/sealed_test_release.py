"""Freeze-B-bound human-custody release of the frozen sealed test labels."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .custody import CustodyError, ReleaseReport, _release_selected_records
from .freeze_b_control import FreezeBControlError, load_freeze_b_control
from .sealed_evaluation_cli import _require_exact_control_checkout
from .sealed_execution_plan import (
    SealedExecutionPlanError,
    load_sealed_execution_plan,
)

SEALED_RELEASE_PATH = Path("data/private/test/labels.jsonl")


class SealedTestReleaseError(RuntimeError):
    """Sanitized failure while projecting the private held-out release."""


def release_sealed_test_records(
    workspace: Path,
    *,
    source: Path,
    destination: Path,
    expected_source_sha256: str,
    control_commit: str,
    system_commit: str,
    freeze_b_path: Path,
    schedule_path: Path,
    public_manifest_path: Path,
) -> ReleaseReport:
    """Project test membership only after authenticating the Freeze-B control."""
    root = Path(workspace).resolve(strict=True)
    selected = Path(destination)
    if selected != SEALED_RELEASE_PATH:
        raise SealedTestReleaseError(
            "sealed test release destination must use the canonical private path"
        )
    try:
        plan = load_sealed_execution_plan(
            root,
            control_commit=control_commit,
            system_commit=system_commit,
            freeze_b_path=freeze_b_path,
            schedule_path=schedule_path,
            public_manifest_path=public_manifest_path,
        )
        control = load_freeze_b_control(
            root,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=freeze_b_path,
        )
    except (FreezeBControlError, SealedExecutionPlanError) as error:
        raise SealedTestReleaseError("Freeze-B control is invalid") from error
    if (
        plan.freeze_b_sha256 != control.manifest.sha256()
        or plan.system_commit != control.manifest.system_commit
        or plan.question_count != control.manifest.question_count
    ):
        raise SealedTestReleaseError("sealed plan does not match Freeze B")
    test_ids = tuple(dict.fromkeys(attempt.instance_id for attempt in plan.attempts))
    if len(test_ids) != plan.question_count:
        raise SealedTestReleaseError("sealed test membership is incomplete")
    try:
        report = _release_selected_records(
            source=source,
            destination=selected,
            train_ids=test_ids,
            workspace=root,
            expected_source_sha256=expected_source_sha256,
        )
    except CustodyError as error:
        raise SealedTestReleaseError(str(error)) from error
    if report.released_count != plan.question_count:
        raise SealedTestReleaseError("sealed test release count is invalid")
    return report


def sealed_test_release_entrypoint() -> int:
    """Run the extractor without exposing a traceback or private values."""
    try:
        return sealed_test_release_main()
    except SealedTestReleaseError as error:
        print(f"sealed test release failed: {error}", file=sys.stderr)
    except Exception:
        print("sealed test release failed: internal custody error", file=sys.stderr)
    return 1


def sealed_test_release_main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if not arguments.release_sealed_test:
        raise SealedTestReleaseError(
            "sealed test release requires explicit execution acknowledgement"
        )
    workspace = arguments.workspace.resolve(strict=True)
    _require_exact_control_checkout(workspace, arguments.control_commit)
    report = release_sealed_test_records(
        workspace,
        source=arguments.source,
        destination=arguments.destination,
        expected_source_sha256=arguments.expected_source_sha256,
        control_commit=arguments.control_commit,
        system_commit=arguments.system_commit,
        freeze_b_path=arguments.freeze_b,
        schedule_path=arguments.schedule,
        public_manifest_path=arguments.public_manifest,
    )
    print(json.dumps(report.as_dict(), separators=(",", ":"), sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=SEALED_RELEASE_PATH)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--control-commit", required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--freeze-b", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--public-manifest", type=Path, required=True)
    parser.add_argument("--release-sealed-test", action="store_true")
    return parser

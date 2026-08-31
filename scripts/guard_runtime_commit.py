#!/usr/bin/env python3
"""Hold the workspace at one commit for the duration of a live generation.

omni_probe_preflight.verify_system_commit re-checks, on every attempt, that HEAD
equals the run's system commit and that no runtime path is dirty. A commit,
checkout, rebase, or stray edit mid-flight therefore fails every remaining
attempt. This guard asserts the condition before dispatch and, with --watch,
keeps asserting it so a violation is seen immediately rather than 130 attempts
later.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

RUNTIME_PATHS = ("src", "scripts", "pyproject.toml", "uv.lock")


class GuardError(RuntimeError):
    """Raised when the workspace is not pinned to the expected commit."""


def _git(workspace: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(workspace), *arguments),
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise GuardError(f"git {' '.join(arguments)} failed")
    return completed.stdout.decode("utf-8", "replace").strip()


def head_commit(workspace: Path) -> str:
    return _git(workspace, "rev-parse", "HEAD")


def dirty_runtime_paths(workspace: Path) -> tuple[str, ...]:
    output = _git(
        workspace,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        *RUNTIME_PATHS,
    )
    return tuple(line for line in output.splitlines() if line.strip())


def assert_pinned(workspace: Path, expected_commit: str) -> None:
    """Raise unless HEAD is the expected commit and runtime paths are clean."""
    observed = head_commit(workspace)
    if observed != expected_commit:
        raise GuardError(
            f"HEAD is {observed}, expected {expected_commit}; "
            "every attempt would fail its system-commit preflight"
        )
    dirty = dirty_runtime_paths(workspace)
    if dirty:
        raise GuardError(
            "runtime paths are dirty, which fails preflight: " + "; ".join(dirty)
        )


def _record(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=15.0)
    parser.add_argument("--violation-record", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    workspace = arguments.workspace.resolve(strict=True)
    assert_pinned(workspace, arguments.system_commit)
    print(f"pinned at {arguments.system_commit}; runtime paths clean")
    if not arguments.watch:
        return 0
    print(f"watching every {arguments.interval_seconds}s; Ctrl-C to stop")
    while True:
        time.sleep(arguments.interval_seconds)
        try:
            assert_pinned(workspace, arguments.system_commit)
        except GuardError as error:
            payload = {
                "detail": str(error),
                "expected_commit": arguments.system_commit,
                "kind": "runtime-commit-guard-violation",
                "observed_at": datetime.now(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "schema_version": 1,
            }
            if arguments.violation_record is not None:
                _record(arguments.violation_record, payload)
            print(f"GUARD VIOLATION: {error}", file=sys.stderr)
            print(
                "stop the batch; in-flight attempts will fail preflight",
                file=sys.stderr,
            )
            return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GuardError as error:
        print(f"guard failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error

"""CLI boundary for result-only recovery of one frozen C4 selection."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .c4_result_recovery import C4RecoveryError, recover_c4_selection


def c4_result_recovery_entrypoint() -> int:
    """Run without exposing provider or artifact content in a traceback."""
    try:
        return c4_result_recovery_main()
    except C4RecoveryError as error:
        print(f"C4 result recovery failed: {error}", file=sys.stderr)
    except Exception:
        print("C4 result recovery failed: internal recovery error", file=sys.stderr)
    return 1


def c4_result_recovery_main(argv: Sequence[str] | None = None) -> int:
    """Recover hash-bound infrastructure failures and print an aggregate receipt."""
    arguments = _parser().parse_args(argv)
    receipt = recover_c4_selection(
        arguments.workspace,
        artifact_workspace=arguments.artifact_workspace,
        selection_path=arguments.selection,
        expected_selection_sha256=arguments.expected_selection_sha256,
        deployment_workspace=arguments.deployment_workspace,
        deployment_root=arguments.deployment_root,
        deployment_run_id=arguments.deployment_run_id,
        output_root=arguments.output_root,
        profile=arguments.profile,
        expected_source_failures=arguments.expected_source_failures,
    )
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--artifact-workspace", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--expected-selection-sha256", required=True)
    parser.add_argument("--deployment-workspace", type=Path, required=True)
    parser.add_argument("--deployment-root", type=Path, required=True)
    parser.add_argument("--deployment-run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--expected-source-failures", type=int, required=True)
    return parser

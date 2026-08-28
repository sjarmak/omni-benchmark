"""Print the public baseline schedule and uniform cost scenario without execution."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .baseline_batch import (
    BASELINE_CONDITIONS,
    load_committed_baseline_schedule,
    project_baseline_cost,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--observed-attempt-cost-usd", required=True)
    parser.add_argument("--cost-ceiling-usd", required=True)
    return parser


def baseline_batch_main(argv: Sequence[str] | None = None) -> int:
    """Emit a secret-free projection; authenticated execution is deliberately absent."""
    arguments = _parser().parse_args(argv)
    schedule = load_committed_baseline_schedule(
        arguments.workspace,
        arguments.system_commit,
        run_id=arguments.run_id,
    )
    projection = project_baseline_cost(
        schedule,
        observed_attempt_cost_usd=arguments.observed_attempt_cost_usd,
        cost_ceiling_usd=arguments.cost_ceiling_usd,
    )
    output = {
        **projection.as_dict(),
        "conditions": list(BASELINE_CONDITIONS),
        "database_count": len({attempt.database for attempt in schedule.attempts}),
        "eligible_manifest_sha256": schedule.eligible_manifest_sha256,
        "live_execution": "disabled_pending_d045_replay",
        "projection_basis": (
            "one_observed_failed_C1_attempt_applied_uniformly_for_capacity_planning"
        ),
        "run_id": arguments.run_id,
        "schedule_sha256": schedule.sha256,
        "source_commit": schedule.source_commit,
        "train_ids_sha256": schedule.train_ids_sha256,
    }
    print(json.dumps(output, allow_nan=False, sort_keys=True))
    return 0

"""Fail-closed registry for baseline runs excluded from scoring."""

from __future__ import annotations


QUARANTINED_RUN_IDS = frozenset(
    {
        "public-c4-baseline-v1-20260828",
        "public-c4-baseline-v2",
    }
)


def is_quarantined_run(run_id: object) -> bool:
    """Return whether a run is committed as non-scoreable."""
    return isinstance(run_id, str) and run_id in QUARANTINED_RUN_IDS


def quarantined_attempt(attempt_id: object) -> bool:
    """Return whether an attempt belongs to a quarantined run."""
    return (
        isinstance(attempt_id, str)
        and attempt_id.partition(":")[0] in QUARANTINED_RUN_IDS
    )

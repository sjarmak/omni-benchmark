"""Exact-Git E02 candidate inventory for production deployment."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from omni_benchmark.e02_candidate import (
    E02CandidateError,
    load_committed_e02_candidate,
)


ROOT = Path(__file__).resolve().parents[1]


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_exact_committed_e02_candidate_reproduces_all_deployment_plans() -> None:
    candidate = load_committed_e02_candidate(ROOT, _head())

    assert candidate.source_commit == _head()
    assert candidate.candidate_set_sha256 == (
        "0111ce62001d6bb6f796a3912830529b8fae263353e62dd06111768c3147c3b8"
    )
    assert len(candidate.plans) == 18
    assert sum(len(plan.files) for plan in candidate.plans.values()) == 272
    assert candidate.relationship_count == 91
    assert all(plan.database == database for database, plan in candidate.plans.items())


def test_e02_candidate_rejects_a_noncanonical_commit() -> None:
    with pytest.raises(E02CandidateError, match="commit"):
        load_committed_e02_candidate(ROOT, "HEAD")

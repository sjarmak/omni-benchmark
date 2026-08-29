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
        "b24302d6c8d8466e52b3f4483d3d4da7d7470d14e418ae767cd11fb80236297e"
    )
    assert len(candidate.plans) == 18
    assert sum(len(plan.files) for plan in candidate.plans.values()) == 272
    assert candidate.relationship_count == 91
    assert all(plan.database == database for database, plan in candidate.plans.items())


def test_e02_candidate_rejects_a_noncanonical_commit() -> None:
    with pytest.raises(E02CandidateError, match="commit"):
        load_committed_e02_candidate(ROOT, "HEAD")

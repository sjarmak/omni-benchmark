"""Exact-Git E02 candidate inventory for production deployment."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from omni_benchmark.e02_candidate import (
    E02CandidateError,
    load_committed_c5_candidate,
    load_committed_c5_plan,
    load_committed_e02_candidate,
)
from omni_benchmark.omni_semantic_deployment import semantic_deployment_sha256


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
        "12c4e1a8cab38f0f47e14b5c553c87c800ca07f27bae568171f1d7caaf7589a7"
    )
    assert len(candidate.plans) == 18
    assert sum(len(plan.files) for plan in candidate.plans.values()) == 272
    assert candidate.relationship_count == 91
    assert all(plan.database == database for database, plan in candidate.plans.items())


def test_c5_single_database_load_reproduces_the_full_candidates_plan() -> None:
    commit = _head()
    database = "planets_data_large"

    targeted = load_committed_c5_plan(ROOT, commit, database)
    full = load_committed_c5_candidate(ROOT, commit).plans[database]

    assert semantic_deployment_sha256(targeted) == semantic_deployment_sha256(full)
    assert targeted.manifest_sha256 == full.manifest_sha256


def test_c5_single_database_load_rejects_a_database_outside_the_candidate() -> None:
    with pytest.raises(E02CandidateError, match="not in the candidate"):
        load_committed_c5_plan(ROOT, _head(), "absent_large")


def test_e02_candidate_rejects_a_noncanonical_commit() -> None:
    with pytest.raises(E02CandidateError, match="commit"):
        load_committed_e02_candidate(ROOT, "HEAD")

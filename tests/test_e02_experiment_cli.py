"""Dry-default, receipt-gated E02 deployment boundary."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.e02_experiment_cli import (
    E02ExperimentError,
    _e02_deployment_identity,
    e02_experiment_main,
    validate_c4_baseline_freeze,
)


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_SHA256 = "db811d6ec553d3b82e42ba3bbd9bafe7ca528a695836a33d6f1aff0b60c5b074"


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _arguments() -> list[str]:
    return [
        "--workspace",
        str(ROOT),
        "--system-commit",
        _head(),
        "--run-id",
        "e02-dev-a-deployment-v1",
        "--output-root",
        "experiments/deployments/e02-dev-a-v1",
        "--expected-candidate-set-sha256",
        CANDIDATE_SHA256,
        "--baseline-freeze",
        "experiments/autoresearch/state/public-c4-baseline-v4-freeze.json",
        "--expected-baseline-selection-sha256",
        "b" * 64,
    ]


def test_dry_e02_plan_is_exact_public_and_provider_inert(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = e02_experiment_main(
        _arguments(), baseline_validator=lambda *_args: "b" * 64
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["candidate_set_sha256"] == CANDIDATE_SHA256
    assert output["baseline_selection_sha256"] == "b" * 64
    assert output["database_count"] == 18
    assert output["file_count"] == 272
    assert output["relationship_count"] == 91
    assert output["schedule_attempt_count"] == 136
    assert output["live_execution"] == "not_started"
    assert output["approval_binding"]["condition"] == "C4"
    assert len(output["approval_binding"]["execution_plan_sha256"]) == 64


def test_e02_uses_candidate_specific_remote_identity() -> None:
    model, branch = _e02_deployment_identity("sample_large")

    assert model == "livesqlbench-sample_large-e02-relationships-v1"
    assert branch == model
    assert "public-baseline" not in model


def test_live_e02_deployment_requires_a_fresh_receipt_before_product_access() -> None:
    called = False

    def forbidden_client(_profile: str) -> object:
        nonlocal called
        called = True
        raise AssertionError("client must not be constructed")

    with pytest.raises(E02ExperimentError, match="human approval receipt"):
        e02_experiment_main(
            [*_arguments(), "--execute-live-deployment", "--profile", "fixture"],
            client_factory=forbidden_client,
            baseline_validator=lambda *_args: "b" * 64,
        )

    assert called is False


def test_exact_receipt_is_consumed_before_deployment_construction() -> None:
    events: list[str] = []
    approval = object()

    def validate(*_args: object) -> object:
        events.append("validated")
        return approval

    def consume(*args: object) -> Path:
        assert args[-1] is approval
        events.append("consumed")
        return ROOT / "synthetic-consumption.json"

    def deploy(*_args: object, **_kwargs: object) -> int:
        events.append("deployment-constructed")
        return 0

    result = e02_experiment_main(
        [
            *_arguments(),
            "--execute-live-deployment",
            "--profile",
            "fixture",
            "--human-approval-receipt",
            "/tmp/synthetic-e02-approval.json",
        ],
        approval_validator=validate,
        approval_consumer=consume,
        deployment_runner=deploy,
        baseline_validator=lambda *_args: "b" * 64,
    )

    assert result == 0
    assert events == ["validated", "consumed", "deployment-constructed"]


def test_candidate_hash_mismatch_fails_before_any_live_boundary() -> None:
    arguments = _arguments()
    arguments[arguments.index(CANDIDATE_SHA256)] = "a" * 64
    with pytest.raises(E02ExperimentError, match="candidate set"):
        e02_experiment_main(
            arguments,
            baseline_validator=lambda *_args: "b" * 64,
        )


def test_missing_c4_baseline_freeze_blocks_e02_plan() -> None:
    with pytest.raises(E02ExperimentError, match="baseline freeze"):
        e02_experiment_main(_arguments())


def _baseline_freeze(workspace: Path, content: bytes) -> tuple[Path, str]:
    relative = Path("experiments/autoresearch/state/public-c4-baseline-v4-freeze.json")
    target = workspace / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    target.chmod(0o600)
    return relative, hashlib.sha256(content).hexdigest()


def test_baseline_freeze_validator_accepts_exact_private_public_freeze(
    tmp_path: Path,
) -> None:
    content = json.dumps(
        {
            "counts": {"attempts": 129, "databases": 10},
            "entries": [{} for _ in range(129)],
            "kind": "public-c4-baseline-freeze",
            "schema_version": 1,
        },
        separators=(",", ":"),
    ).encode()
    relative, digest = _baseline_freeze(tmp_path, content)

    assert validate_c4_baseline_freeze(tmp_path, relative, digest) == digest


def test_baseline_freeze_validator_rejects_duplicate_keys(tmp_path: Path) -> None:
    content = (
        b'{"kind":"public-c4-baseline-freeze","kind":"public-c4-baseline-freeze",'
        b'"schema_version":1,"entries":['
        + b",".join(b"{}" for _ in range(129))
        + b'],"counts":{"attempts":129,"databases":10}}'
    )
    relative, digest = _baseline_freeze(tmp_path, content)

    with pytest.raises(E02ExperimentError, match="baseline freeze is invalid"):
        validate_c4_baseline_freeze(tmp_path, relative, digest)


def test_baseline_freeze_validator_rejects_symlink(tmp_path: Path) -> None:
    content = b"{}"
    private = tmp_path / "private-freeze.json"
    private.write_bytes(content)
    private.chmod(0o600)
    relative = Path("experiments/autoresearch/state/public-c4-baseline-v4-freeze.json")
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    os.symlink(private, target)

    with pytest.raises(E02ExperimentError, match="not a private file"):
        validate_c4_baseline_freeze(
            tmp_path, relative, hashlib.sha256(content).hexdigest()
        )

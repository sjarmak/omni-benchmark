"""Aggregate-only custody boundary for complete dev-A gold conformance."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.dev_a_gold_conformance import (
    DevAGoldConformanceError,
    load_dev_a_gold_conformance_receipt,
    prepare_dev_a_gold_conformance_plan,
    publish_dev_a_gold_conformance,
    score_dev_a_gold_conformance,
)
from omni_benchmark.dev_a_gold_conformance_cli import (
    dev_a_gold_conformance_entrypoint,
    dev_a_gold_conformance_main,
)
from omni_benchmark.scoring import (
    OFFICIAL_SOFT_EX_VERSION,
    SENSITIVITY_SCORER_VERSION,
)
from omni_benchmark.sealed_scoring import (
    FailureClass,
    ScoringMode,
    SealedScoringResult,
)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def _workspace(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "workspace"
    root.mkdir()
    _write(root / ".gitignore", b"data/private/\nexperiments/autoresearch/\n", 0o644)
    _write(
        root / "config/autoresearch.json",
        _canonical(
            {
                "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
                "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
                "public_manifest_path": "data/manifests/eligible_questions.jsonl",
                "test_ids_path": "data/manifests/test_ids.txt",
                "train_ids_path": "data/manifests/train_ids.txt",
            }
        ),
        0o644,
    )
    ids = tuple(f"dev-a-{index:03d}" for index in range(154))
    records = tuple(
        {
            "category": "Query",
            "clean_up_sqls": [],
            "conditions": {"decimal": 2, "distinct": False, "order": False},
            "high_level": False,
            "instance_id": instance_id,
            "normal_query": f"Question {index}",
            "preprocess_sql": [],
            "query": f"Question {index}",
            "selected_database": f"database_{index % 18}",
            "source_index": index,
        }
        for index, instance_id in enumerate(ids)
    )
    _write(
        root / "data/manifests/eligible_questions.jsonl",
        b"".join(_canonical(record) for record in records),
        0o644,
    )
    ids_content = ("\n".join(ids) + "\n").encode()
    _write(root / "data/manifests/dev_a_ids.txt", ids_content, 0o644)
    _write(root / "data/manifests/dev_b_ids.txt", b"dev-b-001\n", 0o644)
    _write(root / "data/manifests/train_ids.txt", ids_content + b"dev-b-001\n", 0o644)
    _write(root / "data/manifests/test_ids.txt", b"test-001\n", 0o644)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.test"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "freeze"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    release = b"".join(
        _canonical(
            {
                "external_knowledge": [],
                "instance_id": instance_id,
                "sol_sql": ["SELECT 1"],
                "test_cases": [],
            }
        )
        for instance_id in ids
    )
    _write(root / "data/private/dev-a/labels.jsonl", release)
    return root, commit, hashlib.sha256(release).hexdigest()


def _result(
    mode: ScoringMode,
    *,
    outcome: str | None,
    failure: FailureClass | None = None,
) -> SealedScoringResult:
    return SealedScoringResult(
        scorer_identity=(
            "official_soft_ex" if mode is ScoringMode.OFFICIAL else "sensitivity"
        ),
        scorer_version=(
            OFFICIAL_SOFT_EX_VERSION
            if mode is ScoringMode.OFFICIAL
            else SENSITIVITY_SCORER_VERSION
        ),
        outcome=outcome,  # type: ignore[arg-type]
        failure_origin=("benchmark_infrastructure" if failure else None),
        failure_class=failure,
    )


def test_complete_plan_uses_exact_154_release_without_candidate_artifacts(
    tmp_path: Path,
) -> None:
    workspace, commit, release_sha256 = _workspace(tmp_path)

    plan = prepare_dev_a_gold_conformance_plan(
        workspace,
        freeze_a_commit=commit,
        expected_release_sha256=release_sha256,
    )

    assert plan.question_count == 154
    assert plan.release_sha256 == release_sha256
    assert "SELECT" not in repr(plan)
    assert not (workspace / "experiments/autoresearch/raw").exists()


def test_conformance_publishes_only_aggregate_private_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, commit, release_sha256 = _workspace(tmp_path)
    plan = prepare_dev_a_gold_conformance_plan(
        workspace,
        freeze_a_commit=commit,
        expected_release_sha256=release_sha256,
    )
    calls = 0

    def score(
        _case: object, mode: ScoringMode, _provider: object
    ) -> SealedScoringResult:
        nonlocal calls
        calls += 1
        if calls in {1, 155}:
            return _result(
                mode, outcome=None, failure=FailureClass.GOLD_STATEMENT_ERROR
            )
        return _result(mode, outcome="wrong_answer")

    monkeypatch.setattr("omni_benchmark.dev_a_gold_conformance.score_query", score)
    result = score_dev_a_gold_conformance(plan, object())
    destination = Path("experiments/autoresearch/state/dev-a-gold-conformance-v1.json")
    receipt = publish_dev_a_gold_conformance(
        workspace, destination=destination, plan=plan, result=result
    )

    assert calls == 308
    assert receipt["official_scoreable_questions"] == 153
    assert receipt["sensitivity_scoreable_questions"] == 153
    path = workspace / destination
    content = path.read_bytes()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert b"dev-a-000" not in content
    assert b"SELECT" not in content
    assert b"gold_sql" not in content
    assert load_dev_a_gold_conformance_receipt(
        workspace,
        destination,
        expected_sha256=receipt["receipt_sha256"],
        freeze_a_commit=commit,
        release_sha256=release_sha256,
        dev_a_ids_sha256=plan.dev_a_ids_sha256,
    ) == (153, 153)
    noncanonical = Path(
        "experiments/autoresearch/state/dev-a-gold-conformance-noncanonical.json"
    )
    noncanonical_content = json.dumps(json.loads(content), indent=2).encode()
    _write(workspace / noncanonical, noncanonical_content)
    with pytest.raises(DevAGoldConformanceError, match="canonical"):
        load_dev_a_gold_conformance_receipt(
            workspace,
            noncanonical,
            expected_sha256=hashlib.sha256(noncanonical_content).hexdigest(),
            freeze_a_commit=commit,
            release_sha256=release_sha256,
            dev_a_ids_sha256=plan.dev_a_ids_sha256,
        )
    with pytest.raises(DevAGoldConformanceError, match="already exists"):
        publish_dev_a_gold_conformance(
            workspace, destination=destination, plan=plan, result=result
        )


def test_unexpected_gold_failure_aborts_without_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, commit, release_sha256 = _workspace(tmp_path)
    plan = prepare_dev_a_gold_conformance_plan(
        workspace,
        freeze_a_commit=commit,
        expected_release_sha256=release_sha256,
    )
    monkeypatch.setattr(
        "omni_benchmark.dev_a_gold_conformance.score_query",
        lambda _case, mode, _provider: _result(
            mode, outcome=None, failure=FailureClass.DATABASE_ACQUIRE_FAILED
        ),
    )

    with pytest.raises(DevAGoldConformanceError, match="infrastructure failure"):
        score_dev_a_gold_conformance(plan, object())

    assert not (workspace / "experiments/autoresearch/state").exists()


def test_conformance_cli_requires_in_memory_dsn_before_gold_access(
    tmp_path: Path,
) -> None:
    with pytest.raises(DevAGoldConformanceError, match="SCORER_ADMIN_DSN"):
        dev_a_gold_conformance_main(
            [
                "--workspace",
                str(tmp_path),
                "--freeze-a-commit",
                "a" * 40,
                "--expected-release-sha256",
                "b" * 64,
                "--destination",
                "experiments/autoresearch/state/dev-a-gold-conformance-v1.json",
                "--execute-gold-conformance",
            ],
            environment={},
        )


def test_conformance_entrypoint_sanitizes_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed() -> int:
        raise RuntimeError("gold SQL must not print")

    monkeypatch.setattr(
        "omni_benchmark.dev_a_gold_conformance_cli.dev_a_gold_conformance_main",
        failed,
    )

    assert dev_a_gold_conformance_entrypoint() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "dev-A gold conformance failed: internal scorer error\n"

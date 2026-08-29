"""Custody and execution boundaries for frozen-baseline dev-A scoring."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.dev_a_baseline_scoring import (
    DevABaselineScoringError,
    prepare_dev_a_baseline_plan,
    publish_dev_a_baseline_results,
    require_scoreable_question_counts,
    score_dev_a_baseline_plan,
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


SHA256_ZERO = "0" * 64


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _write(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(mode)


def _public_record(instance_id: str, database: str) -> dict[str, object]:
    return {
        "category": "Query",
        "clean_up_sqls": [],
        "conditions": {"decimal": 2, "distinct": False, "order": False},
        "high_level": False,
        "instance_id": instance_id,
        "normal_query": f"Question {instance_id}",
        "preprocess_sql": [],
        "query": f"Question {instance_id}",
        "selected_database": database,
        "source_index": 1,
    }


def _run_manifest(
    *, generation_sha256: str, condition: str, commit: str
) -> dict[str, object]:
    return {
        "budget_id": "direct-default",
        "cli_versions": {"claude": "fixture"},
        "condition": condition,
        "controllable_seed": None,
        "finished_at": "2026-08-29T00:00:01Z",
        "generation_sha256": generation_sha256,
        "git_commit": commit,
        "harness_config_sha256": SHA256_ZERO,
        "instructions_sha256": SHA256_ZERO,
        "model": "fixture-model",
        "model_config_id": "fixture-config",
        "prompt_sha256": SHA256_ZERO,
        "provider": "fixture-provider",
        "repetition": 1,
        "schema_version": 1,
        "scope": "train",
        "semantic_model_ref": "none",
        "semantic_model_sha256": None,
        "software_versions": {"omni-benchmark": "fixture"},
        "started_at": "2026-08-29T00:00:00Z",
    }


def _initialize_workspace(tmp_path: Path) -> tuple[Path, str, str, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write(
        workspace / ".gitignore",
        b"data/private/\nexperiments/autoresearch/\n",
        mode=0o644,
    )
    _write(
        workspace / "config/autoresearch.json",
        _canonical(
            {
                "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
                "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
                "public_manifest_path": "data/manifests/eligible_questions.jsonl",
                "test_ids_path": "data/manifests/test_ids.txt",
                "train_ids_path": "data/manifests/train_ids.txt",
            }
        ),
        mode=0o644,
    )
    public_records = (
        _public_record("dev-a-1", "fixture_large"),
        _public_record("dev-a-2", "fixture_large"),
        _public_record("dev-b-1", "fixture_large"),
    )
    _write(
        workspace / "data/manifests/eligible_questions.jsonl",
        b"".join(_canonical(record) for record in public_records),
        mode=0o644,
    )
    _write(
        workspace / "data/manifests/dev_a_ids.txt", b"dev-a-1\ndev-a-2\n", mode=0o644
    )
    _write(workspace / "data/manifests/dev_b_ids.txt", b"dev-b-1\n", mode=0o644)
    _write(
        workspace / "data/manifests/train_ids.txt",
        b"dev-a-1\ndev-a-2\ndev-b-1\n",
        mode=0o644,
    )
    _write(workspace / "data/manifests/test_ids.txt", b"test-1\n", mode=0o644)
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.test"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=workspace, check=True)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "freeze"], cwd=workspace, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    entries: list[dict[str, object]] = []
    for instance_id in ("dev-a-1", "dev-a-2", "dev-b-1"):
        for condition in ("C1", "C2", "C3"):
            run_id = "fixture-baseline"
            attempt_id = f"{run_id}:{instance_id}:{condition}:1"
            generation = _canonical(
                {
                    "attempt_id": attempt_id,
                    "condition": condition,
                    "generated_sql": "SELECT 2",
                    "generation_outcome": "answered",
                    "instance_id": instance_id,
                    "partition": "train",
                    "question": f"Question {instance_id}",
                    "repetition": 1,
                    "run_id": run_id,
                }
            )
            generation_sha256 = hashlib.sha256(generation).hexdigest()
            run = _canonical(
                _run_manifest(
                    generation_sha256=generation_sha256,
                    condition=condition,
                    commit=commit,
                )
            )
            run_sha256 = hashlib.sha256(run).hexdigest()
            # Foreign dev-B generation deliberately stays absent. Preparation must
            # intersect membership before it opens generation artifacts.
            if instance_id.startswith("dev-a"):
                root = (
                    workspace
                    / "experiments/autoresearch/raw"
                    / run_id
                    / "fixture_large"
                    / condition.lower()
                    / f"{instance_id}-r1"
                )
                _write(root / "generation.jsonl", generation)
                _write(root / "run.json", run)
            entries.append(
                {
                    "condition": condition,
                    "database": "fixture_large",
                    "disposition": "preserved",
                    "generation_sha256": generation_sha256,
                    "instance_id": instance_id,
                    "original_action": "preserve",
                    "repetition": 1,
                    "run_manifest_sha256": run_sha256,
                    "selected_attempt_id": attempt_id,
                    "trial_key": f"{instance_id}:{condition}:1",
                }
            )
    selection = {
        "continuation_manifest_sha256": SHA256_ZERO,
        "continuation_run_id": "fixture-continuation",
        "counts": {"continuation": 0, "preserved": 9, "total": 9},
        "entries": entries,
        "exclusion_manifest_sha256": SHA256_ZERO,
        "kind": "public-direct-baseline-freeze",
        "original_run_id": "fixture-baseline",
        "schema_version": 1,
        "source_commit": commit,
        "source_schedule_sha256": SHA256_ZERO,
    }
    selection_bytes = _canonical(selection)
    _write(
        workspace
        / "experiments/autoresearch/state/public-direct-baseline-freeze-v1.json",
        selection_bytes,
    )
    release = b"".join(
        _canonical(
            {
                "external_knowledge": [],
                "instance_id": instance_id,
                "sol_sql": ["SELECT 1"],
                "test_cases": [],
            }
        )
        for instance_id in ("dev-a-1", "dev-a-2")
    )
    _write(workspace / "data/private/dev-a/labels.jsonl", release)
    return (
        workspace,
        commit,
        hashlib.sha256(selection_bytes).hexdigest(),
        hashlib.sha256(release).hexdigest(),
    )


def _install_c4_selection(workspace: Path, commit: str) -> tuple[Path, str]:
    run_id = "public-c4-baseline-v4"
    entries: list[dict[str, object]] = []
    for instance_id in ("dev-a-1", "dev-a-2", "dev-b-1"):
        attempt_id = f"{run_id}:{instance_id}:C4:1"
        result = _canonical(
            {
                "columns": ["answer"],
                "rows": [[{"type": "decimal", "value": "2"}]],
                "schema_version": 1,
                "truncated": False,
            }
        )
        result_sha256 = hashlib.sha256(result).hexdigest()
        result_path = (
            Path("experiments/autoresearch/raw")
            / run_id
            / "fixture_large/c4"
            / f"{instance_id}-r1/answer.result.json"
        )
        generation = _canonical(
            {
                "actual_result_hash": result_sha256,
                "actual_result_status": "complete",
                "attempt_id": attempt_id,
                "condition": "C4",
                "execution_status": "complete",
                "failure_origin": None,
                "generated_query": "fixture semantic query",
                "generated_sql": None,
                "generation_outcome": "answered",
                "instance_id": instance_id,
                "partition": "train",
                "question": f"Question {instance_id}",
                "repetition": 1,
                "result_artifact_path": result_path.as_posix(),
                "result_artifact_schema_version": 1,
                "result_artifact_sha256": result_sha256,
                "run_id": run_id,
                "terminal_failure_class": None,
            }
        )
        generation_sha256 = hashlib.sha256(generation).hexdigest()
        run = _canonical(
            _run_manifest(
                generation_sha256=generation_sha256,
                condition="C4",
                commit=commit,
            )
        )
        if instance_id.startswith("dev-a"):
            root = (
                workspace
                / "experiments/autoresearch/raw"
                / run_id
                / "fixture_large/c4"
                / f"{instance_id}-r1"
            )
            _write(root / "answer.result.json", result)
            _write(root / "generation.jsonl", generation)
            _write(root / "run.json", run)
        entries.append(
            {
                "attempt_id": attempt_id,
                "condition": "C4",
                "database": "fixture_large",
                "generation_sha256": generation_sha256,
                "instance_id": instance_id,
                "repetition": 1,
                "run_manifest_sha256": hashlib.sha256(run).hexdigest(),
            }
        )
    selection = {
        "artifact_file_count": 10,
        "artifact_inventory_sha256": "1" * 64,
        "counts": {
            "answered": 3,
            "attempts": 3,
            "databases": 1,
            "errored": 0,
            "refused": 0,
        },
        "deployment_sha256": "2" * 64,
        "eligible_manifest_sha256": "3" * 64,
        "entries": entries,
        "execution_plan_sha256": "4" * 64,
        "kind": "public-c4-baseline-freeze",
        "output_root": f"experiments/autoresearch/raw/{run_id}",
        "run_id": run_id,
        "schema_version": 1,
        "source_commit": commit,
        "source_schedule_sha256": "5" * 64,
        "train_ids_sha256": "6" * 64,
    }
    content = _canonical(selection)
    path = Path(f"experiments/autoresearch/state/{run_id}-freeze.json")
    _write(workspace / path, content)
    return path, hashlib.sha256(content).hexdigest()


def test_prepare_intersects_dev_a_before_opening_foreign_attempts(
    tmp_path: Path,
) -> None:
    workspace, commit, selection_sha256, release_sha256 = _initialize_workspace(
        tmp_path
    )

    plan = prepare_dev_a_baseline_plan(
        workspace,
        freeze_a_commit=commit,
        expected_selection_sha256=selection_sha256,
        expected_release_sha256=release_sha256,
    )

    assert plan.released_question_count == 2
    assert plan.selected_question_count == 2
    assert plan.unrepresented_question_count == 0
    assert len(plan.attempts) == 6
    assert {attempt.condition for attempt in plan.attempts} == {"C1", "C2", "C3"}
    assert all("dev-b-1" not in attempt.attempt_id for attempt in plan.attempts)
    assert "SELECT 1" not in repr(plan)


def test_prepare_and_publish_accept_exact_c4_freeze_without_weakening_direct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit, direct_sha256, release_sha256 = _initialize_workspace(tmp_path)
    selection_path, c4_sha256 = _install_c4_selection(workspace, commit)

    c4_plan = prepare_dev_a_baseline_plan(
        workspace,
        freeze_a_commit=commit,
        selection_path=selection_path,
        expected_selection_sha256=c4_sha256,
        expected_release_sha256=release_sha256,
    )
    direct_plan = prepare_dev_a_baseline_plan(
        workspace,
        freeze_a_commit=commit,
        expected_selection_sha256=direct_sha256,
        expected_release_sha256=release_sha256,
    )

    assert len(c4_plan.attempts) == 2
    assert {attempt.condition for attempt in c4_plan.attempts} == {"C4"}
    assert all(attempt.candidate_rows == ((2,),) for attempt in c4_plan.attempts)
    assert len(direct_plan.attempts) == 6

    monkeypatch.setattr(
        "omni_benchmark.dev_a_baseline_scoring.score_query",
        lambda case, mode, provider: _scoring_result(mode, outcome="correct"),
    )
    monkeypatch.setattr(
        "omni_benchmark.dev_a_baseline_scoring.score_precomputed_result",
        lambda case, rows, mode, provider: _scoring_result(mode, outcome="correct"),
    )
    results = score_dev_a_baseline_plan(c4_plan, object())
    receipt = publish_dev_a_baseline_results(
        workspace,
        output_root=Path("experiments/autoresearch/raw/c4-score-fixture"),
        plan=c4_plan,
        results=results,
        environment={},
    )
    assert receipt["official"]["by_condition"] == {
        "C4": {
            "correct": 2,
            "refused_or_error": 0,
            "scheduled_attempts": 2,
            "scoreable_attempts": 2,
            "unscorable_attempts": 0,
            "wrong_answer": 0,
        }
    }


def test_prepare_accepts_exact_e02_dev_a_c4_freeze(tmp_path: Path) -> None:
    workspace, commit, _, release_sha256 = _initialize_workspace(tmp_path)
    selection_path, _ = _install_c4_selection(workspace, commit)
    selection = json.loads((workspace / selection_path).read_text())
    selection["kind"] = "e02-dev-a-c4-freeze"
    content = _canonical(selection)
    _write(workspace / selection_path, content)

    plan = prepare_dev_a_baseline_plan(
        workspace,
        freeze_a_commit=commit,
        selection_path=selection_path,
        expected_selection_sha256=hashlib.sha256(content).hexdigest(),
        expected_release_sha256=release_sha256,
    )

    assert len(plan.attempts) == 2
    assert {attempt.condition for attempt in plan.attempts} == {"C4"}


def test_prepare_keeps_c4_artifacts_separate_from_private_release(
    tmp_path: Path,
) -> None:
    custody_workspace, commit, _, release_sha256 = _initialize_workspace(tmp_path)
    selection_path, c4_sha256 = _install_c4_selection(custody_workspace, commit)
    artifact_workspace = tmp_path / "artifact-workspace"
    artifact_workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=artifact_workspace, check=True)
    (custody_workspace / "experiments").rename(artifact_workspace / "experiments")

    assert not (artifact_workspace / "data/private/dev-a/labels.jsonl").exists()
    assert not (custody_workspace / selection_path).exists()
    plan = prepare_dev_a_baseline_plan(
        custody_workspace,
        artifact_workspace=artifact_workspace,
        freeze_a_commit=commit,
        selection_path=selection_path,
        expected_selection_sha256=c4_sha256,
        expected_release_sha256=release_sha256,
    )

    assert len(plan.attempts) == 2
    assert {attempt.condition for attempt in plan.attempts} == {"C4"}


def test_c4_result_artifact_mutation_fails_before_scoring(tmp_path: Path) -> None:
    workspace, commit, _, release_sha256 = _initialize_workspace(tmp_path)
    selection_path, c4_sha256 = _install_c4_selection(workspace, commit)
    result = (
        workspace
        / "experiments/autoresearch/raw/public-c4-baseline-v4"
        / "fixture_large/c4/dev-a-1-r1/answer.result.json"
    )
    result.write_bytes(result.read_bytes().replace(b'"2"', b'"3"'))
    result.chmod(0o600)

    with pytest.raises(DevABaselineScoringError, match="does not match"):
        prepare_dev_a_baseline_plan(
            workspace,
            freeze_a_commit=commit,
            selection_path=selection_path,
            expected_selection_sha256=c4_sha256,
            expected_release_sha256=release_sha256,
        )


def test_c4_stateful_case_fails_during_preparation_before_any_database(
    tmp_path: Path,
) -> None:
    workspace, _, _, release_sha256 = _initialize_workspace(tmp_path)
    manifest = workspace / "data/manifests/eligible_questions.jsonl"
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    records[0]["preprocess_sql"] = ["CREATE TEMP VIEW forbidden AS SELECT 1"]
    _write(manifest, b"".join(_canonical(record) for record in records), mode=0o644)
    subprocess.run(["git", "add", str(manifest)], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "stateful public fixture"], cwd=workspace, check=True
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    selection_path, c4_sha256 = _install_c4_selection(workspace, commit)

    with pytest.raises(DevABaselineScoringError, match="stateless"):
        prepare_dev_a_baseline_plan(
            workspace,
            freeze_a_commit=commit,
            selection_path=selection_path,
            expected_selection_sha256=c4_sha256,
            expected_release_sha256=release_sha256,
        )


def test_release_hash_fails_before_private_records_are_parsed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit, selection_sha256, _ = _initialize_workspace(tmp_path)
    parsed = False

    def forbidden_loader(*args: object, **kwargs: object) -> object:
        nonlocal parsed
        parsed = True
        raise AssertionError("private loader must not run")

    monkeypatch.setattr(
        "omni_benchmark.dev_a_baseline_scoring.load_dev_a_records",
        forbidden_loader,
    )

    with pytest.raises(DevABaselineScoringError, match="release SHA-256"):
        prepare_dev_a_baseline_plan(
            workspace,
            freeze_a_commit=commit,
            expected_selection_sha256=selection_sha256,
            expected_release_sha256="f" * 64,
        )

    assert not parsed


def test_all_cases_validate_before_first_database_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit, selection_sha256, release_sha256 = _initialize_workspace(
        tmp_path
    )
    plan = prepare_dev_a_baseline_plan(
        workspace,
        freeze_a_commit=commit,
        expected_selection_sha256=selection_sha256,
        expected_release_sha256=release_sha256,
    )
    invalid_case = object.__new__(type(plan.attempts[-1].case))
    object.__setattr__(invalid_case, "database", "fixture_large")
    object.__setattr__(invalid_case, "candidate_sql", ("SELECT 1",))
    object.__setattr__(invalid_case, "gold_sql", ("SELECT 1",))
    object.__setattr__(invalid_case, "preprocess_sql", ())
    object.__setattr__(invalid_case, "cleanup_sql", ())
    object.__setattr__(invalid_case, "conditions", {"decimal": True, "order": False})
    object.__setattr__(plan.attempts[-1], "case", invalid_case)

    class Provider:
        acquired = 0

        def acquire(self, database: str) -> object:
            self.acquired += 1
            raise AssertionError("provider must not be touched")

    provider = Provider()
    with pytest.raises(DevABaselineScoringError, match="invalid scoring input"):
        score_dev_a_baseline_plan(plan, provider)
    assert provider.acquired == 0


def _scoring_result(
    mode: ScoringMode,
    *,
    outcome: str | None,
    failure_class: FailureClass | None = None,
    failure_origin: str | None = None,
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
        failure_origin=failure_origin,  # type: ignore[arg-type]
        failure_class=failure_class,
        rerun_eligible=failure_class is FailureClass.DATABASE_ACQUIRE_FAILED,
    )


def test_gold_conformance_is_frozen_before_candidate_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit, selection_sha256, release_sha256 = _initialize_workspace(
        tmp_path
    )
    plan = prepare_dev_a_baseline_plan(
        workspace,
        freeze_a_commit=commit,
        expected_selection_sha256=selection_sha256,
        expected_release_sha256=release_sha256,
    )
    conformance_calls: list[ScoringMode] = []
    candidate_calls: list[ScoringMode] = []

    def score(case: object, mode: ScoringMode, provider: object) -> SealedScoringResult:
        candidate_sql = getattr(case, "candidate_sql")
        if candidate_sql == "SELECT 1":
            conformance_calls.append(mode)
            question_index = (len(conformance_calls) - 1) // 2
            if question_index == 0:
                return _scoring_result(mode, outcome="wrong_answer")
            failure = (
                FailureClass.GOLD_STATEMENT_ERROR
                if mode is ScoringMode.OFFICIAL
                else FailureClass.GOLD_RESULT_OVERFLOW
            )
            return _scoring_result(
                mode,
                outcome=None,
                failure_class=failure,
                failure_origin="benchmark_infrastructure",
            )
        assert len(conformance_calls) == 4
        candidate_calls.append(mode)
        return _scoring_result(mode, outcome="correct")

    monkeypatch.setattr("omni_benchmark.dev_a_baseline_scoring.score_query", score)

    results = score_dev_a_baseline_plan(plan, object())

    assert conformance_calls == [
        ScoringMode.OFFICIAL,
        ScoringMode.SENSITIVITY,
        ScoringMode.OFFICIAL,
        ScoringMode.SENSITIVITY,
    ]
    assert len(candidate_calls) == 6
    assert results.scoreable_question_count(ScoringMode.OFFICIAL) == 1
    assert results.scoreable_question_count(ScoringMode.SENSITIVITY) == 1
    require_scoreable_question_counts(results, official=1, sensitivity=1)
    with pytest.raises(DevABaselineScoringError, match="authorized denominator"):
        require_scoreable_question_counts(results, official=2, sensitivity=1)

    output_root = Path("experiments/autoresearch/raw/unscorable-score-fixture")
    receipt = publish_dev_a_baseline_results(
        workspace,
        output_root=output_root,
        plan=plan,
        results=results,
        environment={},
    )
    assert receipt["official"]["scheduled_attempts"] == 6
    assert receipt["official"]["scoreable_attempts"] == 3
    assert receipt["official"]["unscorable_attempts"] == 3
    assert receipt["official"]["scoreable_questions"] == 1
    assert receipt["official"]["unscorable_questions"] == 1
    official = json.loads((workspace / output_root / "official.score.json").read_text())
    assert len(official["attempts"]) == 6
    assert [record["status"] for record in official["attempts"]].count(
        "unscorable"
    ) == 3
    assert {
        record["failure_category"]
        for record in official["attempts"]
        if record["status"] == "unscorable"
    } == {"gold_statement_error"}


def test_publish_is_sql_free_hash_bound_and_exclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit, selection_sha256, release_sha256 = _initialize_workspace(
        tmp_path
    )
    plan = prepare_dev_a_baseline_plan(
        workspace,
        freeze_a_commit=commit,
        expected_selection_sha256=selection_sha256,
        expected_release_sha256=release_sha256,
    )

    def correct(
        case: object, mode: ScoringMode, provider: object
    ) -> SealedScoringResult:
        return _scoring_result(mode, outcome="correct")

    monkeypatch.setattr("omni_benchmark.dev_a_baseline_scoring.score_query", correct)
    results = score_dev_a_baseline_plan(plan, object())
    output_root = Path("experiments/autoresearch/raw/frozen-dev-a-score-fixture")
    receipt = publish_dev_a_baseline_results(
        workspace,
        output_root=output_root,
        plan=plan,
        results=results,
        environment={},
    )

    assert receipt["selection_sha256"] == selection_sha256
    assert receipt["release_sha256"] == release_sha256
    assert receipt["coverage"]["attempts"] == 6
    assert receipt["official"]["scoreable_attempts"] == 6
    assert receipt["official"]["unscorable_attempts"] == 0
    assert receipt["official"]["correct"] == 6
    root = workspace / output_root
    rendered = b"".join(path.read_bytes() for path in sorted(root.iterdir()))
    for forbidden in (
        b"SELECT 1",
        b"sol_sql",
        b"gold_sql",
        b"test_cases",
        b"external_knowledge",
        b"expected_result",
    ):
        assert forbidden not in rendered
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in root.iterdir())
    with pytest.raises(DevABaselineScoringError, match="must not already exist"):
        publish_dev_a_baseline_results(
            workspace,
            output_root=output_root,
            plan=plan,
            results=results,
            environment={},
        )


def test_infrastructure_failure_cannot_be_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, commit, selection_sha256, release_sha256 = _initialize_workspace(
        tmp_path
    )
    plan = prepare_dev_a_baseline_plan(
        workspace,
        freeze_a_commit=commit,
        expected_selection_sha256=selection_sha256,
        expected_release_sha256=release_sha256,
    )

    def failed(
        case: object, mode: ScoringMode, provider: object
    ) -> SealedScoringResult:
        return _scoring_result(
            mode,
            outcome=None,
            failure_origin="benchmark_infrastructure",
            failure_class=FailureClass.DATABASE_ACQUIRE_FAILED,
        )

    monkeypatch.setattr("omni_benchmark.dev_a_baseline_scoring.score_query", failed)
    with pytest.raises(DevABaselineScoringError, match="infrastructure failure"):
        score_dev_a_baseline_plan(plan, object())
    assert not (
        workspace / "experiments/autoresearch/raw/frozen-dev-a-score-fixture"
    ).exists()

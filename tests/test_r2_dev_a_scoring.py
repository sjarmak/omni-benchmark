"""R2 adapter for the unchanged frozen dev-A scorers."""

from __future__ import annotations

import hashlib
import json
import subprocess
import copy
from decimal import Decimal
from pathlib import Path

import pytest

from omni_benchmark.autoresearch_metrics import ValidatedGenerationOutputs
from omni_benchmark.dev_a_baseline_scoring import (
    DevAAttemptResult,
    DevABaselinePlan,
    DevABaselineResults,
    ModeAttemptScore,
    PreparedDevAAttempt,
)
from omni_benchmark.r2_dev_a_scoring import (
    R2DevAScoringError,
    R2DevAScoringPlan,
    prepare_r2_dev_a_scoring_plan,
    publish_r2_dev_a_results,
)
from omni_benchmark.r2_execution import (
    R2ExecutionPlan,
    R2PlannedAttempt,
    finalize_r2_generations,
    write_r2_attempt_artifacts,
)
from omni_benchmark.r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION
from omni_benchmark.scoring import (
    OFFICIAL_SOFT_EX_VERSION,
)
from omni_benchmark.sealed_scoring import (
    FailureClass,
    SealedQueryCase,
    SealedScoringResult,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _result(identity: str, version: str, outcome: str) -> SealedScoringResult:
    return SealedScoringResult(
        scorer_identity=identity,
        scorer_version=version,
        outcome=outcome,
    )


def test_publish_binds_each_arm_and_preserves_unscorable_status(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    artifacts.mkdir()
    (workspace / ".gitignore").write_text("experiments/autoresearch/\n")
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)

    prepared = []
    generations = {}
    for condition, attempt_id in (
        (CONTROL_CONDITION, "r2attempt-control"),
        (TREATMENT_CONDITION, "r2attempt-treatment"),
    ):
        record = _canonical(
            {
                "attempt_id": attempt_id,
                "condition": condition,
                "instance_id": "q1",
            }
        )
        relative = Path("experiments/autoresearch/raw/finalized") / (
            "control.jsonl" if condition == CONTROL_CONDITION else "treatment.jsonl"
        )
        path = artifacts / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(record)
        digest = hashlib.sha256(record).hexdigest()
        generations[condition] = ValidatedGenerationOutputs(
            path=path,
            sha256=digest,
            question_count=1,
            scope="dev-a",
            condition=condition,
            run_id=f"run-{condition.lower()}",
            repetition=1,
        )
        prepared.append(
            PreparedDevAAttempt(
                attempt_id=attempt_id,
                condition=condition,
                generation_sha256=digest,
                generation_record_sha256=digest,
                question_key=hashlib.sha256(b"q1").hexdigest(),
                case=SealedQueryCase(
                    database="fixture_large",
                    candidate_sql=(),
                    gold_sql="SELECT 1",
                ),
                candidate_rows=((1,),),
            )
        )

    baseline = DevABaselinePlan(
        selection_sha256="a" * 64,
        release_sha256="b" * 64,
        dev_a_ids_sha256="c" * 64,
        freeze_a_commit="d" * 40,
        released_question_count=1,
        selected_question_count=1,
        unrepresented_question_count=0,
        attempts=tuple(prepared),
        scheduled_question_count=1,
    )
    results = DevABaselineResults(
        attempts=(
            DevAAttemptResult(
                attempt=prepared[0],
                official=ModeAttemptScore(
                    result=_result(
                        "official_soft_ex", OFFICIAL_SOFT_EX_VERSION, "correct"
                    )
                ),
                sensitivity=ModeAttemptScore(
                    unscorable_failure=FailureClass.GOLD_STATEMENT_ERROR
                ),
            ),
            DevAAttemptResult(
                attempt=prepared[1],
                official=ModeAttemptScore(
                    result=_result(
                        "official_soft_ex", OFFICIAL_SOFT_EX_VERSION, "wrong_answer"
                    )
                ),
                sensitivity=ModeAttemptScore(
                    unscorable_failure=FailureClass.GOLD_STATEMENT_ERROR
                ),
            ),
        )
    )
    plan = R2DevAScoringPlan(
        baseline=baseline,
        finalization_sha256="a" * 64,
        generations=generations,
    )

    receipt = publish_r2_dev_a_results(
        workspace,
        artifact_workspace=artifacts,
        output_root=Path("experiments/autoresearch/raw/r2-score"),
        plan=plan,
        results=results,
    )

    assert receipt["coverage"] == {
        "released_questions": 1,
        "scheduled_attempts": 2,
        "scheduled_questions": 1,
    }
    official = json.loads(
        (
            workspace / receipt["artifacts"]["official"][CONTROL_CONDITION]["path"]
        ).read_bytes()
    )
    sensitivity = json.loads(
        (
            workspace / receipt["artifacts"]["sensitivity"][CONTROL_CONDITION]["path"]
        ).read_bytes()
    )
    assert official["schema_version"] == "r2-score-artifact-v2"
    assert official["attempts"][0]["status"] == "scored"
    assert official["generation"]["sha256"] == generations[CONTROL_CONDITION].sha256
    assert sensitivity["attempts"][0] == {
        "attempt_id": "r2attempt-control",
        "failure_category": "gold_statement_error",
        "generation_record_sha256": generations[CONTROL_CONDITION].sha256,
        "status": "unscorable",
    }
    rendered = json.dumps(receipt) + json.dumps(official) + json.dumps(sensitivity)
    assert "SELECT 1" not in rendered

    with pytest.raises(R2DevAScoringError, match="plan is invalid"):
        publish_r2_dev_a_results(
            workspace,
            artifact_workspace=artifacts,
            output_root=Path("experiments/autoresearch/raw/r2-score-invalid"),
            plan=object(),  # type: ignore[arg-type]
            results=results,
        )

    incomplete = R2DevAScoringPlan(
        baseline=baseline,
        finalization_sha256="a" * 64,
        generations={CONTROL_CONDITION: generations[CONTROL_CONDITION]},
    )
    with pytest.raises(R2DevAScoringError, match="arm coverage"):
        publish_r2_dev_a_results(
            workspace,
            artifact_workspace=artifacts,
            output_root=Path("experiments/autoresearch/raw/r2-score-incomplete"),
            plan=incomplete,
            results=results,
        )

    control_path = generations[CONTROL_CONDITION].path
    control_path.write_bytes(control_path.read_bytes() + b" ")
    with pytest.raises(R2DevAScoringError, match="changed after validation"):
        publish_r2_dev_a_results(
            workspace,
            artifact_workspace=artifacts,
            output_root=Path("experiments/autoresearch/raw/r2-score-mutated"),
            plan=plan,
            results=results,
        )


def test_prepare_validates_complete_finalization_before_attaching_dev_a_gold(
    tmp_path: Path,
) -> None:
    custody = tmp_path / "custody"
    artifacts = tmp_path / "artifacts"
    custody.mkdir()
    artifacts.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=artifacts, check=True)
    (custody / "config").mkdir()
    (custody / "data/manifests").mkdir(parents=True)
    (custody / "config/autoresearch.json").write_bytes(
        _canonical(
            {
                "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
                "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
                "public_manifest_path": "data/manifests/eligible_questions.jsonl",
                "test_ids_path": "data/manifests/test_ids.txt",
                "train_ids_path": "data/manifests/train_ids.txt",
            }
        )
    )
    public = []
    for index, instance_id in enumerate(("q1", "q2"), start=1):
        public.append(
            {
                "category": "Query",
                "clean_up_sqls": [],
                "conditions": {"decimal": 2, "distinct": False, "order": False},
                "high_level": False,
                "instance_id": instance_id,
                "normal_query": f"Question {index}",
                "preprocess_sql": [],
                "query": f"Question {index}",
                "selected_database": "fixture_large",
                "source_index": index,
            }
        )
    (custody / "data/manifests/eligible_questions.jsonl").write_bytes(
        b"".join(_canonical(record) for record in public)
    )
    (custody / "data/manifests/dev_a_ids.txt").write_text("q1\nq2\n")
    (custody / "data/manifests/dev_b_ids.txt").write_text("")
    (custody / "data/manifests/test_ids.txt").write_text("test-1\n")
    (custody / "data/manifests/train_ids.txt").write_text("q1\nq2\n")
    subprocess.run(["git", "init", "-q"], cwd=custody, check=True)
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.test"],
        cwd=custody,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=custody, check=True)
    subprocess.run(["git", "add", "."], cwd=custody, check=True)
    subprocess.run(["git", "commit", "-qm", "freeze"], cwd=custody, check=True)
    freeze_a = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=custody,
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
        for instance_id in ("q1", "q2")
    )
    release_path = custody / "data/private/dev-a/labels.jsonl"
    release_path.parent.mkdir(parents=True)
    release_path.write_bytes(release)
    release_path.chmod(0o600)

    attempts = []
    position = 0
    for instance_id in ("q1", "q2"):
        for condition in (CONTROL_CONDITION, TREATMENT_CONDITION):
            position += 1
            attempt_id = f"r2attempt-{instance_id}-{condition.lower()}"
            attempts.append(
                R2PlannedAttempt(
                    attempt_id=attempt_id,
                    attempt_position=position,
                    condition=condition,
                    database="fixture_large",
                    deployment_identity=f"deployment-{condition.lower()}",
                    deployment_run_id=f"deployment-run-{condition.lower()}-v1",
                    instance_id=instance_id,
                    output_root=Path("experiments/autoresearch/raw/r2")
                    / condition.lower()
                    / "fixture_large"
                    / f"{position:03d}-{attempt_id}",
                    pair_id=f"pair-{instance_id}",
                    pair_position=position // 2,
                    repetition=1,
                    run_id=f"run-{condition.lower()}",
                    semantic_model_sha256=str(position) * 64,
                    within_pair_position=1 if condition == CONTROL_CONDITION else 2,
                )
            )
    plan = R2ExecutionPlan(
        attempts=tuple(attempts),
        balanced_ai_settings_sha256="1" * 64,
        budget_policy_sha256="2" * 64,
        bundle_manifest_sha256="3" * 64,
        bundle_set_sha256="4" * 64,
        harness_config_sha256="5" * 64,
        instructions_sha256="6" * 64,
        output_root=Path("experiments/autoresearch/raw/r2"),
        projected_arm_cost_usd={CONTROL_CONDITION: "1.00", TREATMENT_CONDITION: "1.00"},
        projected_total_cost_usd="2.00",
        prompt_sha256="7" * 64,
        schedule_sha256="8" * 64,
        system_commit="9" * 40,
    )
    for attempt in attempts:
        result = _canonical(
            {
                "columns": ["answer"],
                "rows": [[{"type": "decimal", "value": "1"}]],
                "schema_version": 1,
                "truncated": False,
            }
        )
        result_path = artifacts / attempt.output_root / "answer.result.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_bytes(result)
        result_path.chmod(0o600)
        digest = hashlib.sha256(result).hexdigest()
        write_r2_attempt_artifacts(
            artifacts,
            plan=plan,
            attempt_id=attempt.attempt_id,
            record={
                "actual_result_hash": digest,
                "actual_result_status": "complete",
                "attempt_id": attempt.attempt_id,
                "condition": attempt.condition,
                "cost_unavailable_reason": "provider_did_not_report_cost",
                "cost_usd": None,
                "database": attempt.database,
                "execution_status": "complete",
                "failure_origin": None,
                "generated_query": '{"userEditedSQL":"SELECT 1"}',
                "generation_outcome": "answered",
                "harness_failure": None,
                "instance_id": attempt.instance_id,
                "latency_ms": 1.0,
                "partition": "dev-a",
                "query_unavailable_reason": None,
                "repetition": 1,
                "result_artifact_path": (
                    attempt.output_root / "answer.result.json"
                ).as_posix(),
                "result_artifact_schema_version": 1,
                "result_artifact_sha256": digest,
                "run_id": attempt.run_id,
                "terminal_failure_class": None,
            },
        )
    finalized = finalize_r2_generations(
        artifacts,
        plan=plan,
        destination=Path("experiments/autoresearch/raw/r2-finalized"),
    )

    prepared = prepare_r2_dev_a_scoring_plan(
        custody,
        artifact_workspace=artifacts,
        execution_plan=plan,
        finalization_root=Path("experiments/autoresearch/raw/r2-finalized"),
        expected_finalization_sha256=finalized.manifest_sha256,
        freeze_a_commit=freeze_a,
        expected_release_sha256=hashlib.sha256(release).hexdigest(),
        expected_pair_count=2,
    )

    assert len(prepared.baseline.attempts) == 4
    assert prepared.baseline.selected_question_count == 2
    assert prepared.baseline.released_question_count == 2
    assert all(
        item.candidate_rows == ((Decimal("1"),),) for item in prepared.baseline.attempts
    )
    assert prepared.generations[CONTROL_CONDITION].sha256 == finalized.control_sha256
    assert (
        prepared.generations[TREATMENT_CONDITION].sha256 == finalized.treatment_sha256
    )

    with pytest.raises(R2DevAScoringError, match="pair count is invalid"):
        prepare_r2_dev_a_scoring_plan(
            custody,
            artifact_workspace=artifacts,
            execution_plan=plan,
            finalization_root=Path("experiments/autoresearch/raw/r2-finalized"),
            expected_finalization_sha256=finalized.manifest_sha256,
            freeze_a_commit=freeze_a,
            expected_release_sha256=hashlib.sha256(release).hexdigest(),
            expected_pair_count=0,
        )
    with pytest.raises(R2DevAScoringError, match="execution plan is incomplete"):
        prepare_r2_dev_a_scoring_plan(
            custody,
            artifact_workspace=artifacts,
            execution_plan=plan,
            finalization_root=Path("experiments/autoresearch/raw/r2-finalized"),
            expected_finalization_sha256=finalized.manifest_sha256,
            freeze_a_commit=freeze_a,
            expected_release_sha256=hashlib.sha256(release).hexdigest(),
            expected_pair_count=1,
        )
    with pytest.raises(R2DevAScoringError, match="expected hash"):
        prepare_r2_dev_a_scoring_plan(
            custody,
            artifact_workspace=artifacts,
            execution_plan=plan,
            finalization_root=Path("experiments/autoresearch/raw/r2-finalized"),
            expected_finalization_sha256="0" * 64,
            freeze_a_commit=freeze_a,
            expected_release_sha256=hashlib.sha256(release).hexdigest(),
            expected_pair_count=2,
        )
    with pytest.raises(R2DevAScoringError, match="release does not match"):
        prepare_r2_dev_a_scoring_plan(
            custody,
            artifact_workspace=artifacts,
            execution_plan=plan,
            finalization_root=Path("experiments/autoresearch/raw/r2-finalized"),
            expected_finalization_sha256=finalized.manifest_sha256,
            freeze_a_commit=freeze_a,
            expected_release_sha256="0" * 64,
            expected_pair_count=2,
        )


def test_r2_scoring_freeze_binds_adapter_and_policy() -> None:
    path = (
        REPOSITORY_ROOT
        / "experiments/r2-public-evidence-measures/r2-dev-a-scoring-freeze-v1.json"
    )
    content = path.read_bytes()
    value = json.loads(content)

    assert content == _canonical(value)
    assert value["kind"] == "r2-dev-a-scoring-freeze"
    assert value["schema_version"] == 1
    assert value["pins"] == {
        "dev_a_gold_conformance_sha256": (
            "d9387e4b64c8d5160648b149374c0b9f9365438e350399d788cfd3db3d0fc6e5"
        ),
        "expected_official_scoreable_questions": 136,
        "expected_sensitivity_scoreable_questions": 135,
        "finalization_sha256": (
            "e7dd135656cdb15375edc62107369ca8d191facda2f8921343da57bd5ba443ac"
        ),
        "official_scorer_version": OFFICIAL_SOFT_EX_VERSION,
        "sensitivity_scorer_version": "omni-multiset-decimal-v1",
    }
    assert value["policy"] == {
        "artifact_schema": "r2-score-artifact-v2",
        "candidate_input": "immutable_precomputed_omni_result_or_terminal_no_answer",
        "correctness_output": "sql_free_hash_bound_three_state_or_unscorable",
        "finalization_validation": "rebuild_all_attempts_before_private_release",
        "gold_scope": "dev_a_only",
        "scorer_semantics": "unchanged_frozen_implementations",
        "unscorable_policy": "preserve_gold_failure_and_exclude_from_denominator",
    }
    for item in value["files"]:
        file_content = (REPOSITORY_ROOT / item["path"]).read_bytes()
        assert item == {
            "path": item["path"],
            "sha256": hashlib.sha256(file_content).hexdigest(),
            "size_bytes": len(file_content),
        }
    digest_source = copy.deepcopy(value)
    digest_source["manifest"].pop("artifact_sha256")
    assert (
        value["manifest"]["artifact_sha256"]
        == hashlib.sha256(_canonical(digest_source)).hexdigest()
    )

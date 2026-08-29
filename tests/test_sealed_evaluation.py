"""Production loading and custody ordering for the final sealed evaluator."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from omni_benchmark.sealed_cohort_finalization import finalize_sealed_cohort
from omni_benchmark.sealed_evaluation import (
    SealedEvaluationError,
    _rename_noreplace,
    load_sealed_output_batch,
    prepare_sealed_evaluation_plan,
    publish_sealed_evaluation,
    score_sealed_evaluation,
)
from omni_benchmark.sealed_generation_staging import (
    SealedAttemptRepository,
    prepare_sealed_attempt,
)
from tests.execution_fixtures import SyntheticIsolationProvider
from tests.test_sealed_cohort_finalization import CLI, SOFTWARE, _questions
from tests.test_sealed_generation_staging import _plan, _record, _workspace


def test_atomic_directory_publish_never_replaces_existing_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.mkdir()
    destination.mkdir()

    with pytest.raises(FileExistsError):
        _rename_noreplace(source, destination)

    assert source.is_dir()
    assert destination.is_dir()


def _complete_batch(workspace: Path):  # type: ignore[no-untyped-def]
    plan, freeze = _plan()
    questions = _questions()
    repository = SealedAttemptRepository(workspace, Path("runs/sealed-attempts"))
    for planned in plan.attempts:
        prepared = prepare_sealed_attempt(
            plan=plan,
            freeze_b=freeze,
            attempt_id=planned.attempt_id,
            question=questions[planned.instance_id],
        )
        record = _record(prepared, output=f"SELECT '{planned.instance_id}'")
        if planned.condition == "C4":
            record.update(
                {
                    "failure_origin": "evaluated_system",
                    "generated_query": None,
                    "generation_outcome": "errored",
                    "terminal_failure_class": "omni_job_terminal_failure",
                }
            )
        repository.stage(prepared, record)
    for condition in ("C1", "C2", "C3", "C4"):
        for repetition in (1, 2, 3):
            finalize_sealed_cohort(
                workspace=workspace,
                output_root=Path("runs/sealed-cohorts"),
                plan=plan,
                freeze_b=freeze,
                attempt_repository=repository,
                condition=condition,
                repetition=repetition,
                questions=questions,
                software_versions=SOFTWARE,
                cli_versions=CLI,
                started_at="2026-08-29T07:00:00Z",
                finished_at="2026-08-29T07:00:01Z",
            )
    return plan, freeze, questions


def test_load_exact_twelve_cohorts_before_private_custody(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, questions = _complete_batch(workspace)

    batch = load_sealed_output_batch(
        workspace,
        output_root=Path("runs/sealed-cohorts"),
        plan=plan,
        freeze_b=freeze,
        questions=questions,
    )

    assert len(batch.attempts) == 1_212
    assert len(batch.cohorts) == 12
    assert batch.freeze_b_sha256 == freeze.sha256()
    assert repr(batch).count("SELECT") == 0
    assert {
        attempt.no_answer_failure
        for attempt in batch.attempts
        if attempt.condition == "C4"
    }


def test_partial_or_changed_cohort_fails_closed(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, questions = _complete_batch(workspace)
    missing = workspace / "runs/sealed-cohorts/c4-r3/run.json"
    missing.unlink()

    with pytest.raises(SealedEvaluationError, match="cohort"):
        load_sealed_output_batch(
            workspace,
            output_root=Path("runs/sealed-cohorts"),
            plan=plan,
            freeze_b=freeze,
            questions=questions,
        )


def _private_release(workspace: Path, *, foreign: bool = False) -> tuple[Path, str]:
    destination = workspace / "data/private/test/labels.jsonl"
    destination.parent.mkdir(parents=True)
    records = [
        {
            "external_knowledge": [],
            "instance_id": f"q-{question:03d}",
            "sol_sql": [f"SELECT 'q-{question:03d}'"],
            "test_cases": [],
        }
        for question in range(1, 102)
    ]
    if foreign:
        records.append(
            {
                "external_knowledge": [],
                "instance_id": "dev-a-foreign",
                "sol_sql": ["PRIVATE FOREIGN SQL"],
                "test_cases": [],
            }
        )
    content = b"".join(
        (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode()
        for record in records
    )
    destination.write_bytes(content)
    os.chmod(destination, 0o600)
    return destination.relative_to(workspace), hashlib.sha256(content).hexdigest()


def _public_records(plan) -> dict[str, dict[str, object]]:  # type: ignore[no-untyped-def]
    by_id = {}
    for attempt in plan.attempts:
        by_id.setdefault(
            attempt.instance_id,
            {
                "clean_up_sqls": [],
                "conditions": {"decimal": -1, "order": False},
                "preprocess_sql": [],
                "selected_database": attempt.database,
            },
        )
    return by_id


def test_exact_test_release_rejects_foreign_membership_without_leaking_id(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, questions = _complete_batch(workspace)
    batch = load_sealed_output_batch(
        workspace,
        output_root=Path("runs/sealed-cohorts"),
        plan=plan,
        freeze_b=freeze,
        questions=questions,
    )
    release, digest = _private_release(workspace, foreign=True)

    with pytest.raises(SealedEvaluationError) as caught:
        prepare_sealed_evaluation_plan(
            workspace,
            batch=batch,
            release_path=release,
            expected_release_sha256=digest,
            public_records=_public_records(plan),
        )

    assert "dev-a-foreign" not in str(caught.value)
    assert "PRIVATE FOREIGN SQL" not in str(caught.value)


def test_score_freezes_gold_then_returns_complete_sql_free_results(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, questions = _complete_batch(workspace)
    batch = load_sealed_output_batch(
        workspace,
        output_root=Path("runs/sealed-cohorts"),
        plan=plan,
        freeze_b=freeze,
        questions=questions,
    )
    release, digest = _private_release(workspace)
    scoring_plan = prepare_sealed_evaluation_plan(
        workspace,
        batch=batch,
        release_path=release,
        expected_release_sha256=digest,
        public_records=_public_records(plan),
    )
    responses = {
        **{
            f"SELECT 'q-{question:03d}'": [(f"q-{question:03d}",)]
            for question in range(1, 102)
        },
        "SELECT 1": [(1,)],
    }
    provider = SyntheticIsolationProvider(responses)

    results = score_sealed_evaluation(scoring_plan, provider)

    assert len(results) == 1_212
    assert all("SELECT" not in repr(result) for result in results)
    assert sum(result.official.result is not None for result in results) == 1_212
    assert (
        sum(
            result.official.result is not None
            and result.official.result.outcome == "refused_or_error"
            for result in results
        )
        == 303
    )

    summary = publish_sealed_evaluation(
        workspace,
        output_root=Path("runs/sealed-score-final"),
        plan=scoring_plan,
        results=results,
    )
    files = [
        path
        for path in (workspace / "runs/sealed-score-final").rglob("*")
        if path.is_file()
    ]
    assert len(files) == 27
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in files)
    assert set(summary) == {
        "official_aggregate_sha256",
        "output_root",
        "receipt_sha256",
        "sensitivity_aggregate_sha256",
    }
    receipt = workspace / "runs/sealed-score-final/receipt.json"
    assert "q-001" not in receipt.read_text(encoding="utf-8")
    with pytest.raises(SealedEvaluationError, match="exists"):
        publish_sealed_evaluation(
            workspace,
            output_root=Path("runs/sealed-score-final"),
            plan=scoring_plan,
            results=results,
        )

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from omni_benchmark.freeze_b import FreezeBManifest, schedule_sha256
from omni_benchmark.scoring import scorer_metadata
from omni_benchmark.sealed_execution_plan import (
    SealedExecutionPlan,
    SealedPlannedAttempt,
)
from omni_benchmark.sealed_generation_staging import (
    SealedAttemptRepository,
    SealedGenerationStagingError,
    prepare_sealed_attempt,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
COMMIT = "e" * 40
CONTROL = "f" * 40


def _condition(condition: str) -> dict[str, object]:
    return {
        "budget_id": "sealed-default-v1",
        "condition": condition,
        "harness_config_sha256": hashlib.sha256(
            f"harness:{condition}".encode()
        ).hexdigest(),
        "instructions_sha256": SHA_A,
        "model": "managed-standard",
        "model_config_id": "frozen-final-v1",
        "prompt_sha256": SHA_B,
        "provider": "aws-bedrock",
        "runtime_policy_sha256": SHA_C,
        "semantic_model_ref": "none" if condition == "C1" else "export:final-v1",
        "semantic_model_sha256": None if condition == "C1" else SHA_D,
    }


def _attempts() -> tuple[SealedPlannedAttempt, ...]:
    return tuple(
        SealedPlannedAttempt(
            attempt_id=f"sealed:q-{question:03d}:{condition}:{repetition}",
            cohort_id=f"sealed-{condition.lower()}-r{repetition}",
            condition=condition,
            database=f"db-{((question - 1) % 7) + 1}",
            instance_id=f"q-{question:03d}",
            repetition=repetition,
            question_sha256=hashlib.sha256(
                f"Public synthetic question {question}?".encode()
            ).hexdigest(),
        )
        for question in range(1, 102)
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    )


def _freeze(attempts: tuple[SealedPlannedAttempt, ...]) -> FreezeBManifest:
    return FreezeBManifest.from_dict(
        {
            "conditions": [_condition(value) for value in ("C1", "C2", "C3", "C4")],
            "database": {
                "libpq_version": "18.6",
                "postgresql_version": "18.6",
                "snapshot_manifest_sha256": SHA_A,
            },
            "expected_test_outputs": 1_212,
            "freeze_a_commit": "1" * 40,
            "frozen_files": {
                "data/final-schedule.jsonl": SHA_A,
                "data/manifests/eligible_questions.jsonl": SHA_B,
                "data/manifests/test_ids.txt": SHA_C,
            },
            "kind": "freeze-b-manifest",
            "question_count": 101,
            "recorded_at": "2026-08-29T07:00:00Z",
            "repetitions": 3,
            "schedule": {
                "algorithm": "committed_block_interleaved_v1",
                "seed": "human-supplied-final-seed",
                "sha256": schedule_sha256(
                    tuple(attempt.attempt_id for attempt in attempts)
                ),
            },
            "schema_version": 1,
            "scorer": {"metadata": scorer_metadata(), "source_commit": COMMIT},
            "system_commit": COMMIT,
        }
    )


def _plan() -> tuple[SealedExecutionPlan, FreezeBManifest]:
    attempts = _attempts()
    freeze = _freeze(attempts)
    return (
        SealedExecutionPlan(
            attempts=attempts,
            control_commit=CONTROL,
            system_commit=COMMIT,
            freeze_b_sha256=freeze.sha256(),
            schedule_sha256=freeze.schedule_sha256,
            schedule_file_sha256=SHA_A,
            test_ids_sha256=SHA_C,
            public_manifest_sha256=SHA_B,
        ),
        freeze,
    )


def _prepared(*, condition: str = "C1", repetition: int = 1, question: int = 1):  # type: ignore[no-untyped-def]
    plan, freeze = _plan()
    return prepare_sealed_attempt(
        plan=plan,
        freeze_b=freeze,
        attempt_id=f"sealed:q-{question:03d}:{condition}:{repetition}",
        question=f"Public synthetic question {question}?",
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return workspace


def _record(prepared, *, output: str = "SELECT 1") -> dict[str, object]:  # type: ignore[no-untyped-def]
    direct = prepared.condition != "C4"
    return {
        "attempt_id": prepared.attempt_id,
        "condition": prepared.condition,
        "failure_origin": None,
        "generated_query": None if direct else output,
        "generated_sql": output if direct else None,
        "generation_outcome": "answered",
        "instance_id": prepared.instance_id,
        "latency_ms": 10.0,
        "partition": "test",
        "question": prepared.question,
        "repetition": prepared.repetition,
        "run_id": prepared.cohort_id,
        "terminal_failure_class": None,
    }


def test_prepare_binds_every_condition_repetition_and_hides_question_from_repr() -> (
    None
):
    plan, freeze = _plan()

    prepared = tuple(
        prepare_sealed_attempt(
            plan=plan,
            freeze_b=freeze,
            attempt_id=f"sealed:q-001:{condition}:{repetition}",
            question="Public synthetic question 1?",
        )
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    )

    assert len(prepared) == 12
    assert {value.condition for value in prepared} == {"C1", "C2", "C3", "C4"}
    assert {value.repetition for value in prepared} == {1, 2, 3}
    assert all(value.plan_sha256 == plan.sha256 for value in prepared)
    assert all(value.freeze_b_sha256 == freeze.sha256() for value in prepared)
    assert all(value.system_commit == COMMIT for value in prepared)
    assert all(value.control_commit == CONTROL for value in prepared)
    assert all(
        value.condition_binding.condition == value.condition for value in prepared
    )
    assert "Public synthetic question" not in repr(prepared[0])
    assert prepared[-1].condition_binding.semantic_model_sha256 == SHA_D


@pytest.mark.parametrize(
    "case",
    ["question", "unknown", "freeze", "schedule", "order", "public", "system"],
)
def test_prepare_rejects_substitution(case: str) -> None:
    plan, freeze = _plan()
    attempt_id = "sealed:q-001:C1:1"
    question = "Public synthetic question 1?"
    if case == "question":
        question = "Substituted question"
    elif case == "unknown":
        attempt_id = "sealed:q-999:C1:1"
    elif case == "freeze":
        plan = replace(plan, freeze_b_sha256=SHA_A)
    elif case == "schedule":
        plan = replace(plan, schedule_sha256=SHA_A)
    elif case == "order":
        plan = replace(plan, attempts=tuple(reversed(plan.attempts)))
    elif case == "public":
        plan = replace(plan, public_manifest_sha256=SHA_D)
    else:
        plan = replace(plan, system_commit="9" * 40)

    with pytest.raises(SealedGenerationStagingError):
        prepare_sealed_attempt(
            plan=plan,
            freeze_b=freeze,
            attempt_id=attempt_id,
            question=question,
        )


@pytest.mark.parametrize("condition", ["C1", "C2", "C3", "C4"])
def test_stage_and_reconcile_one_atomic_private_envelope(
    tmp_path: Path, condition: str
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared(condition=condition, repetition=3)
    repository = SealedAttemptRepository(workspace, Path("runs/sealed-final"))

    staged = repository.stage(prepared, _record(prepared))
    reconciled = repository.reconcile(prepared)

    assert staged.already_present is False
    assert reconciled is not None
    assert reconciled.candidate_sql == "SELECT 1"
    assert reconciled.generation_record_sha256 == staged.generation_record_sha256
    assert reconciled.envelope_sha256 == staged.envelope_sha256
    assert reconciled.prepared == prepared
    assert os.stat(staged.path, follow_symlinks=False).st_mode & 0o777 == 0o600
    assert len(list(staged.path.parent.iterdir())) == 1
    public = json.dumps(staged.public_summary(), sort_keys=True)
    assert "SELECT 1" not in public
    assert "Public synthetic" not in public
    assert "q-001" not in public
    assert "correct" not in public


def test_identical_stage_is_idempotent_without_rewrite(tmp_path: Path) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared(condition="C2", repetition=2)
    record = _record(prepared)
    first = repository.stage(prepared, record)
    original_stat = first.path.stat()

    second = repository.stage(prepared, dict(record))

    assert second.already_present is True
    assert second.envelope_sha256 == first.envelope_sha256
    assert second.path.stat().st_ino == original_stat.st_ino
    assert second.path.stat().st_mtime_ns == original_stat.st_mtime_ns


def test_conflicting_replay_fails_without_overwrite(tmp_path: Path) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared()
    first = repository.stage(prepared, _record(prepared))
    original = first.path.read_bytes()

    with pytest.raises(SealedGenerationStagingError, match="conflicting"):
        repository.stage(prepared, _record(prepared, output="SELECT 2"))

    assert first.path.read_bytes() == original


def test_absent_attempt_reconciles_to_none(tmp_path: Path) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )

    assert repository.reconcile(_prepared()) is None


@pytest.mark.parametrize("field", ["gold_sql", "test_cases", "correctness", "outcome"])
def test_protected_or_scored_field_fails_before_write(
    tmp_path: Path, field: str
) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared()
    record = _record(prepared)
    record["nested"] = {field: "forbidden"}

    with pytest.raises(SealedGenerationStagingError, match="protected|scored"):
        repository.stage(prepared, record)

    assert not repository.attempt_path(prepared).exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("attempt_id", "sealed:q-002:C1:1"),
        ("condition", "C2"),
        ("instance_id", "q-002"),
        ("partition", "dev-a"),
        ("repetition", 2),
        ("run_id", "sealed-c1-r2"),
        ("question", "Substituted question"),
    ],
)
def test_generation_identity_substitution_fails(
    tmp_path: Path, field: str, value: object
) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared()
    record = _record(prepared)
    record[field] = value

    with pytest.raises(SealedGenerationStagingError, match="identity"):
        repository.stage(prepared, record)


@pytest.mark.parametrize(
    "case",
    ["bad_outcome", "answered_failure", "missing_output", "two_outputs", "wrong_lane"],
)
def test_generation_outcome_and_candidate_output_must_be_consistent(
    tmp_path: Path, case: str
) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared(condition="C4" if case == "wrong_lane" else "C1")
    record = _record(prepared)
    if case == "bad_outcome":
        record["generation_outcome"] = "correct"
    elif case == "answered_failure":
        record["terminal_failure_class"] = "provider_error"
    elif case == "missing_output":
        record["generated_sql"] = None
    elif case == "two_outputs":
        record["generated_query"] = "SELECT 2"
    else:
        record["generated_query"] = None
        record["generated_sql"] = "SELECT 1"

    with pytest.raises(SealedGenerationStagingError, match="outcome|candidate"):
        repository.stage(prepared, record)


def test_refused_attempt_may_have_no_candidate_sql(tmp_path: Path) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared(condition="C3")
    record = _record(prepared)
    record.update(
        {
            "failure_origin": "evaluated_system",
            "generated_sql": None,
            "generation_outcome": "refused",
            "terminal_failure_class": "turn_limit_without_query",
        }
    )

    staged = repository.stage(prepared, record)

    assert staged.candidate_sql is None


def test_infrastructure_failure_remains_unstaged_for_governed_retry(
    tmp_path: Path,
) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared(condition="C3")
    record = _record(prepared)
    record.update(
        {
            "failure_origin": "benchmark_infrastructure",
            "generated_sql": None,
            "generation_outcome": "errored",
            "terminal_failure_class": "database_infrastructure_error",
        }
    )

    with pytest.raises(SealedGenerationStagingError, match="infrastructure failure"):
        repository.stage(prepared, record)

    assert repository.reconcile(prepared) is None


def test_boolean_repetition_cannot_alias_integer_identity(tmp_path: Path) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared()
    record = _record(prepared)
    record["repetition"] = True

    with pytest.raises(SealedGenerationStagingError, match="identity"):
        repository.stage(prepared, record)


def test_cross_plan_reconciliation_fails(tmp_path: Path) -> None:
    repository = SealedAttemptRepository(
        _workspace(tmp_path), Path("runs/sealed-final")
    )
    prepared = _prepared()
    repository.stage(prepared, _record(prepared))
    changed = replace(prepared, plan_sha256="9" * 64)

    with pytest.raises(SealedGenerationStagingError, match="binding"):
        repository.reconcile(changed)


@pytest.mark.parametrize(
    "change",
    [
        {"database": "db/../../escape"},
        {"instance_id": "q/../../escape"},
        {"condition_binding": replace(_prepared().condition_binding, model="other")},
        {"_authorization": "0" * 64},
    ],
)
def test_forged_prepared_authority_cannot_select_paths_or_condition(
    tmp_path: Path, change: dict[str, object]
) -> None:
    workspace = _workspace(tmp_path)
    repository = SealedAttemptRepository(workspace, Path("runs/sealed-final"))
    forged = replace(_prepared(), **change)

    with pytest.raises(SealedGenerationStagingError, match="binding"):
        repository.stage(forged, _record(forged))

    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "case",
    ["symlink_root", "symlink_attempt", "tampered", "noncanonical", "extra_file"],
)
def test_repository_fails_closed_on_unsafe_or_mutated_state(
    tmp_path: Path, case: str
) -> None:
    workspace = _workspace(tmp_path)
    prepared = _prepared()
    if case == "symlink_root":
        (workspace / "elsewhere").mkdir()
        (workspace / "runs").symlink_to(workspace / "elsewhere")
        with pytest.raises(SealedGenerationStagingError, match="symlink"):
            SealedAttemptRepository(workspace, Path("runs/sealed-final"))
        return
    repository = SealedAttemptRepository(workspace, Path("runs/sealed-final"))
    staged = repository.stage(prepared, _record(prepared))
    if case == "symlink_attempt":
        target = workspace / "target.json"
        target.write_bytes(staged.path.read_bytes())
        staged.path.unlink()
        staged.path.symlink_to(target)
    elif case == "tampered":
        staged.path.write_text("{}\n", encoding="utf-8")
    elif case == "noncanonical":
        value = json.loads(staged.path.read_text())
        staged.path.write_text(json.dumps(value, indent=2) + "\n")
    else:
        extra = staged.path.parent / "partial.tmp"
        extra.write_text("partial")

    with pytest.raises(
        SealedGenerationStagingError, match="invalid|private|canonical|incomplete"
    ):
        repository.reconcile(prepared)


@pytest.mark.parametrize(
    "output_root", [Path("/tmp/sealed"), Path("../sealed"), Path("data/sealed")]
)
def test_repository_requires_confined_ignored_raw_root(
    tmp_path: Path, output_root: Path
) -> None:
    with pytest.raises(SealedGenerationStagingError, match="root"):
        SealedAttemptRepository(_workspace(tmp_path), output_root)

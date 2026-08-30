from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

import omni_benchmark.sealed_cohort_finalization as cohort_module
from omni_benchmark.artifact_store import ArtifactStore, ArtifactStoreError
from omni_benchmark.sealed_cohort_finalization import (
    SealedCohortFinalizationError,
    finalize_sealed_cohort,
)
from omni_benchmark.sealed_generation_staging import (
    SealedAttemptRepository,
    prepare_sealed_attempt,
)
from tests.test_sealed_generation_staging import _plan, _record, _workspace


SOFTWARE = {"omni-benchmark": "0.1.0", "python": "3.11.15"}
CLI = {"synthetic": "1.0.0"}


def _questions(question_count: int = 101) -> dict[str, str]:
    return {
        f"q-{question:03d}": f"Public synthetic question {question}?"
        for question in range(1, question_count + 1)
    }


def _stage(
    workspace: Path, *, condition: str, repetition: int
) -> tuple[object, object, SealedAttemptRepository]:
    plan, freeze = _plan()
    repository = SealedAttemptRepository(workspace, Path("runs/sealed-attempts"))
    questions = _questions()
    for planned in plan.attempts:
        if (planned.condition, planned.repetition) != (condition, repetition):
            continue
        prepared = prepare_sealed_attempt(
            plan=plan,
            freeze_b=freeze,
            attempt_id=planned.attempt_id,
            question=questions[planned.instance_id],
        )
        repository.stage(
            prepared, _record(prepared, output=f"SELECT '{planned.instance_id}'")
        )
    return plan, freeze, repository


def _finalize(
    workspace: Path,
    plan: object,
    freeze: object,
    repository: SealedAttemptRepository,
    *,
    condition: str = "C1",
    repetition: int = 1,
    questions: dict[str, str] | None = None,
):  # type: ignore[no-untyped-def]
    return finalize_sealed_cohort(
        workspace=workspace,
        output_root=Path("runs/sealed-cohorts"),
        plan=plan,
        freeze_b=freeze,
        attempt_repository=repository,
        condition=condition,
        repetition=repetition,
        questions=_questions() if questions is None else questions,
        software_versions=SOFTWARE,
        cli_versions=CLI,
        started_at="2026-08-29T07:00:00Z",
        finished_at="2026-08-29T07:00:01Z",
    )


@pytest.mark.parametrize(
    ("condition", "repetition"),
    [
        (condition, repetition)
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    ],
)
def test_finalize_exact_cohort_in_frozen_schedule_order(
    tmp_path: Path, condition: str, repetition: int
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, repository = _stage(
        workspace, condition=condition, repetition=repetition
    )

    result = _finalize(
        workspace,
        plan,
        freeze,
        repository,
        condition=condition,
        repetition=repetition,
    )

    expected = tuple(
        attempt
        for attempt in plan.attempts
        if (attempt.condition, attempt.repetition) == (condition, repetition)
    )
    records = [
        json.loads(line) for line in result.generation_path.read_bytes().splitlines()
    ]
    assert [record["attempt_id"] for record in records] == [
        attempt.attempt_id for attempt in expected
    ]
    assert result.attempt_count == 101
    assert result.run_manifest.condition == condition
    assert result.run_manifest.repetition == repetition
    assert result.run_manifest.generation_sha256 == result.generation_sha256
    assert result.run_manifest.freeze_b_sha256 == freeze.sha256()
    assert result.run_manifest.schedule_sha256 == freeze.schedule_sha256
    assert result.run_manifest.system_commit == freeze.system_commit
    assert (
        result.run_manifest_path.read_bytes() == result.run_manifest.canonical_bytes()
    )
    assert (
        os.stat(result.generation_path, follow_symlinks=False).st_mode & 0o777 == 0o600
    )
    public = json.dumps(result.public_summary(), sort_keys=True)
    assert "SELECT" not in public
    assert "Public synthetic" not in public
    assert "q-001" not in public


def test_identical_finalization_reconciles_without_rewrite(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, repository = _stage(workspace, condition="C2", repetition=2)
    first = _finalize(workspace, plan, freeze, repository, condition="C2", repetition=2)
    generation_stat = first.generation_path.stat()
    manifest_stat = first.run_manifest_path.stat()

    second = _finalize(
        workspace, plan, freeze, repository, condition="C2", repetition=2
    )

    assert second.already_present is True
    assert second.generation_path.stat().st_ino == generation_stat.st_ino
    assert second.generation_path.stat().st_mtime_ns == generation_stat.st_mtime_ns
    assert second.run_manifest_path.stat().st_ino == manifest_stat.st_ino


def test_missing_staged_attempt_blocks_finalization(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, repository = _stage(workspace, condition="C1", repetition=1)
    planned = next(
        attempt
        for attempt in plan.attempts
        if (attempt.condition, attempt.repetition) == ("C1", 1)
    )
    prepared = prepare_sealed_attempt(
        plan=plan,
        freeze_b=freeze,
        attempt_id=planned.attempt_id,
        question=_questions()[planned.instance_id],
    )
    repository.attempt_path(prepared).unlink()
    repository.attempt_path(prepared).parent.rmdir()

    with pytest.raises(SealedCohortFinalizationError, match="incomplete"):
        _finalize(workspace, plan, freeze, repository)


@pytest.mark.parametrize("case", ["missing", "extra", "changed"])
def test_question_set_must_match_exact_cohort(tmp_path: Path, case: str) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, repository = _stage(workspace, condition="C1", repetition=1)
    questions = _questions()
    if case == "missing":
        questions.pop("q-001")
    elif case == "extra":
        questions["q-999"] = "Extra question"
    else:
        questions["q-001"] = "Changed question"

    with pytest.raises(SealedCohortFinalizationError, match="question"):
        _finalize(workspace, plan, freeze, repository, questions=questions)


@pytest.mark.parametrize("case", ["plan", "cohort", "timestamp", "version"])
def test_cross_binding_or_invalid_metadata_fails(tmp_path: Path, case: str) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, repository = _stage(workspace, condition="C1", repetition=1)
    arguments = {
        "workspace": workspace,
        "output_root": Path("runs/sealed-cohorts"),
        "plan": plan,
        "freeze_b": freeze,
        "attempt_repository": repository,
        "condition": "C1",
        "repetition": 1,
        "questions": _questions(),
        "software_versions": SOFTWARE,
        "cli_versions": CLI,
        "started_at": "2026-08-29T07:00:00Z",
        "finished_at": "2026-08-29T07:00:01Z",
    }
    if case == "plan":
        arguments["plan"] = replace(plan, control_commit="9" * 40)
    elif case == "cohort":
        arguments["condition"] = "C2"
    elif case == "timestamp":
        arguments["finished_at"] = "2026-08-29T06:00:00Z"
    else:
        arguments["cli_versions"] = {"bad version": "x"}

    with pytest.raises(SealedCohortFinalizationError):
        finalize_sealed_cohort(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "case", ["conflict", "partial", "symlink", "permissions", "protected"]
)
def test_existing_or_staged_mutation_fails_closed(tmp_path: Path, case: str) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, repository = _stage(workspace, condition="C1", repetition=1)
    result = _finalize(workspace, plan, freeze, repository)
    if case == "conflict":
        result.generation_path.write_text("{}\n", encoding="utf-8")
    elif case == "partial":
        result.run_manifest_path.unlink()
    elif case == "symlink":
        target = workspace / "target.json"
        target.write_bytes(result.run_manifest_path.read_bytes())
        result.run_manifest_path.unlink()
        result.run_manifest_path.symlink_to(target)
    elif case == "permissions":
        result.generation_path.parent.chmod(0o755)
    else:
        planned = next(
            attempt
            for attempt in plan.attempts
            if (attempt.condition, attempt.repetition) == ("C1", 1)
        )
        prepared = prepare_sealed_attempt(
            plan=plan,
            freeze_b=freeze,
            attempt_id=planned.attempt_id,
            question=_questions()[planned.instance_id],
        )
        path = repository.attempt_path(prepared)
        envelope = json.loads(path.read_text())
        envelope["generation_record"]["nested"] = {"gold_sql": "SELECT hidden"}
        path.write_text(
            json.dumps(envelope, separators=(",", ":"), sort_keys=True) + "\n"
        )

    with pytest.raises(
        SealedCohortFinalizationError, match="conflict|incomplete|invalid"
    ):
        _finalize(workspace, plan, freeze, repository)


def test_failed_second_write_removes_private_temporary_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, repository = _stage(workspace, condition="C1", repetition=1)
    original = ArtifactStore.write_bytes

    def fail_manifest_write(self: ArtifactStore, relative_path: Path, content: bytes):  # type: ignore[no-untyped-def]
        if relative_path == Path(cohort_module.RUN_MANIFEST_FILENAME):
            raise ArtifactStoreError("synthetic second-write failure")
        return original(self, relative_path, content)

    monkeypatch.setattr(ArtifactStore, "write_bytes", fail_manifest_write)

    with pytest.raises(SealedCohortFinalizationError, match="atomically"):
        _finalize(workspace, plan, freeze, repository)

    output_root = workspace / "runs/sealed-cohorts"
    assert output_root.is_dir()
    assert list(output_root.iterdir()) == []


@pytest.mark.parametrize(
    "root", [Path("/tmp/cohorts"), Path("../cohorts"), Path("data/cohorts")]
)
def test_output_root_must_be_confined_and_ignored(tmp_path: Path, root: Path) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze, repository = _stage(workspace, condition="C1", repetition=1)

    with pytest.raises(SealedCohortFinalizationError, match="root"):
        finalize_sealed_cohort(
            workspace=workspace,
            output_root=root,
            plan=plan,
            freeze_b=freeze,
            attempt_repository=repository,
            condition="C1",
            repetition=1,
            questions=_questions(),
            software_versions=SOFTWARE,
            cli_versions=CLI,
            started_at="2026-08-29T07:00:00Z",
            finished_at="2026-08-29T07:00:01Z",
        )

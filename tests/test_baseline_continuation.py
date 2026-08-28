from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from omni_benchmark.baseline_batch import (
    BaselineAttempt,
    BaselineBatchError,
    BaselineSchedule,
    ImmutableAttemptRepository,
)
from omni_benchmark.baseline_continuation import (
    ContinuationAuthorization,
    build_continuation_manifest,
    continuation_schedule,
    load_continuation_manifest,
    reconcile_continuation,
    write_continuation_manifest,
)
from omni_benchmark.run_manifest import RunManifest

COMMIT = "5be315e44bea7ee1a39500380dcbc4c05976dd3e"
SHA256 = "a" * 64


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _schedule(run_id: str = "original-run") -> BaselineSchedule:
    attempts = tuple(
        BaselineAttempt(
            condition=condition,
            database="sample_large",
            instance_id=f"question_{index}",
            repetition=1,
            run_id=run_id,
        )
        for index, condition in enumerate(("C1", "C2", "C3", "C1", "C2"), 1)
    )
    return BaselineSchedule(
        attempts=attempts,
        eligible_manifest_sha256="b" * 64,
        source_commit=COMMIT,
        train_ids_sha256="c" * 64,
    )


def _write_attempt(
    repository: ImmutableAttemptRepository,
    attempt: BaselineAttempt,
    *,
    outcome: str,
    failure_class: str | None,
    failure_origin: str | None,
    started_at: str,
    finished_at: str,
    manifest_commit: str = COMMIT,
) -> None:
    record = {
        "attempt_id": attempt.attempt_id,
        "condition": attempt.condition,
        "cost_usd": 0.25,
        "database_query_count": 1,
        "failure_origin": failure_origin,
        "finished_at": finished_at,
        "generation_outcome": outcome,
        "instance_id": attempt.instance_id,
        "latency_ms": 100.0,
        "partition": "train",
        "repetition": attempt.repetition,
        "retry_count": 0,
        "run_id": attempt.run_id,
        "started_at": started_at,
        "terminal_failure_class": failure_class,
        "token_usage": {
            "input_tokens": 10,
            "output_tokens": 2,
            "total_tokens": 12,
        },
        "tool_call_count": 2,
        "validation_attempt_count": 0,
    }
    generation = _canonical_json(record)
    manifest = RunManifest.from_dict(
        {
            "budget_id": "synthetic-public-baseline",
            "cli_versions": {"synthetic": "1.0.0"},
            "condition": attempt.condition,
            "controllable_seed": None,
            "finished_at": finished_at,
            "generation_sha256": hashlib.sha256(generation).hexdigest(),
            "git_commit": manifest_commit,
            "harness_config_sha256": SHA256,
            "instructions_sha256": SHA256,
            "model": "synthetic-model",
            "model_config_id": "synthetic-config",
            "prompt_sha256": SHA256,
            "provider": "synthetic",
            "repetition": attempt.repetition,
            "schema_version": 2,
            "scope": "train",
            "semantic_model_ref": "public-only:synthetic",
            "semantic_model_sha256": None,
            "software_versions": {"omni-benchmark": "0.1.0"},
            "started_at": started_at,
        },
        environment={},
    )
    root = repository.attempt_root(attempt)
    root.mkdir(parents=True, mode=0o700)
    os.chmod(root, 0o700)
    for name, content in (
        ("generation.jsonl", generation),
        ("run.json", manifest.canonical_bytes()),
    ):
        path = root / name
        path.write_bytes(content)
        os.chmod(path, 0o600)


def _authorization(expected: int = 1) -> ContinuationAuthorization:
    return ContinuationAuthorization(
        authorization_id="D-055-oauth-rotation-window",
        expected_invalidated_attempts=expected,
        finished_at_start="2026-08-28T18:20:46Z",
        finished_at_end="2026-08-28T18:26:20Z",
        terminal_failure_class="model_setup_error",
    )


def _source(tmp_path: Path) -> tuple[BaselineSchedule, ImmutableAttemptRepository]:
    workspace = tmp_path / "source"
    workspace.mkdir()
    schedule = _schedule()
    repository = ImmutableAttemptRepository(
        workspace,
        Path("experiments/autoresearch/raw/original-run"),
    )
    before = ("2026-08-28T18:10:00Z", "2026-08-28T18:10:02Z")
    during = ("2026-08-28T18:20:43.980Z", "2026-08-28T18:20:46.914Z")
    after = ("2026-08-28T18:27:00Z", "2026-08-28T18:27:02Z")
    _write_attempt(
        repository,
        schedule.attempts[0],
        outcome="answered",
        failure_class=None,
        failure_origin=None,
        started_at=before[0],
        finished_at=before[1],
    )
    _write_attempt(
        repository,
        schedule.attempts[1],
        outcome="refused",
        failure_class="no_answer_insufficient_context",
        failure_origin="evaluated_system",
        started_at=during[0],
        finished_at=during[1],
    )
    _write_attempt(
        repository,
        schedule.attempts[2],
        outcome="errored",
        failure_class="model_setup_error",
        failure_origin="evaluated_system",
        started_at=during[0],
        finished_at=during[1],
    )
    _write_attempt(
        repository,
        schedule.attempts[3],
        outcome="errored",
        failure_class="model_setup_error",
        failure_origin="evaluated_system",
        started_at=after[0],
        finished_at=after[1],
    )
    return schedule, repository


def test_plan_reruns_only_authorized_infrastructure_and_never_attempted_trials(
    tmp_path: Path,
) -> None:
    schedule, repository = _source(tmp_path)

    manifest = build_continuation_manifest(
        schedule,
        repository=repository,
        continuation_run_id="continuation-run",
        authorization=_authorization(),
    )

    assert manifest.counts == {
        "never_attempted": 1,
        "preserved": 3,
        "rerun_infrastructure": 1,
        "source_schedule": 5,
    }
    assert [entry.action for entry in manifest.entries] == [
        "preserve",
        "preserve",
        "rerun_infrastructure",
        "preserve",
        "never_attempted",
    ]
    rerun = manifest.entries[2]
    assert rerun.predecessor is not None
    assert rerun.predecessor.recorded_failure_origin == "evaluated_system"
    assert rerun.predecessor.adjudicated_failure_origin == "benchmark_infrastructure"
    assert rerun.continuation_attempt_id == "continuation-run:question_3:C3:1"
    assert len(rerun.predecessor.generation_sha256) == 64
    assert len(rerun.predecessor.run_manifest_sha256) == 64


def test_plan_rejects_an_incorrect_authorized_incident_count(tmp_path: Path) -> None:
    schedule, repository = _source(tmp_path)

    with pytest.raises(BaselineBatchError, match="invalidated attempt count"):
        build_continuation_manifest(
            schedule,
            repository=repository,
            continuation_run_id="continuation-run",
            authorization=_authorization(expected=2),
        )


def test_continuation_schedule_has_fresh_identity_and_exact_trial_coverage(
    tmp_path: Path,
) -> None:
    source, repository = _source(tmp_path)
    manifest = build_continuation_manifest(
        source,
        repository=repository,
        continuation_run_id="continuation-run",
        authorization=_authorization(),
    )

    continuation = continuation_schedule(source, manifest)

    assert len(continuation.attempts) == 2
    assert {attempt.instance_id for attempt in continuation.attempts} == {
        "question_3",
        "question_5",
    }
    assert {attempt.run_id for attempt in continuation.attempts} == {"continuation-run"}
    assert not {
        "original-run:question_3:C3:1",
        "original-run:question_5:C2:1",
    }.intersection(attempt.attempt_id for attempt in continuation.attempts)
    assert len({entry.trial_key for entry in manifest.entries}) == len(source.attempts)


def test_manifest_round_trip_is_canonical_private_and_hash_bound(
    tmp_path: Path,
) -> None:
    source, repository = _source(tmp_path)
    manifest = build_continuation_manifest(
        source,
        repository=repository,
        continuation_run_id="continuation-run",
        authorization=_authorization(),
    )
    path = tmp_path / "continuation.json"

    digest = write_continuation_manifest(path, manifest)
    loaded = load_continuation_manifest(path, expected_sha256=digest)

    assert loaded == manifest
    assert digest == manifest.sha256
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_continuation_manifest(path, manifest)
    with pytest.raises(BaselineBatchError, match="SHA-256"):
        load_continuation_manifest(path, expected_sha256="f" * 64)


def test_reconciliation_preserves_source_and_requires_every_fresh_attempt(
    tmp_path: Path,
) -> None:
    source, source_repository = _source(tmp_path)
    manifest = build_continuation_manifest(
        source,
        repository=source_repository,
        continuation_run_id="continuation-run",
        authorization=_authorization(),
    )
    continuation = continuation_schedule(source, manifest)
    continuation_workspace = tmp_path / "continuation"
    continuation_workspace.mkdir()
    continuation_repository = ImmutableAttemptRepository(
        continuation_workspace,
        Path("experiments/autoresearch/raw/continuation-run"),
    )

    incomplete = reconcile_continuation(
        source,
        manifest,
        source_repository=source_repository,
        continuation_repository=continuation_repository,
    )
    assert incomplete.complete is False
    assert incomplete.preserved_attempts == 3
    assert incomplete.missing_continuation_attempts == 2

    for attempt in continuation.attempts:
        _write_attempt(
            continuation_repository,
            attempt,
            outcome="answered",
            failure_class=None,
            failure_origin=None,
            started_at="2026-08-28T19:00:00Z",
            finished_at="2026-08-28T19:00:01Z",
        )

    complete = reconcile_continuation(
        source,
        manifest,
        source_repository=source_repository,
        continuation_repository=continuation_repository,
    )
    assert complete.complete is True
    assert complete.source_schedule_attempts == 5
    assert complete.preserved_attempts == 3
    assert complete.completed_continuation_attempts == 2
    assert complete.missing_continuation_attempts == 0
    assert complete.reconciled_trial_count == 5


def test_source_artifact_mutation_invalidates_the_continuation_plan(
    tmp_path: Path,
) -> None:
    source, source_repository = _source(tmp_path)
    manifest = build_continuation_manifest(
        source,
        repository=source_repository,
        continuation_run_id="continuation-run",
        authorization=_authorization(),
    )
    path = source_repository.attempt_root(source.attempts[0]) / "generation.jsonl"
    content = path.read_bytes()
    path.unlink()
    path.write_bytes(content + b"\n")
    os.chmod(path, 0o600)

    with pytest.raises(BaselineBatchError, match="source artifact"):
        reconcile_continuation(
            source,
            manifest,
            source_repository=source_repository,
            continuation_repository=source_repository,
        )

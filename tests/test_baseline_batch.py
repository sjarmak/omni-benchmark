from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

import omni_benchmark.baseline_batch_cli as baseline_batch_cli
from omni_benchmark.baseline_batch import (
    BASELINE_CONDITIONS,
    BaselineAttempt,
    BaselineBatchError,
    BaselineSchedule,
    BatchBudget,
    ImmutableAttemptRepository,
    direct_only_baseline_schedule,
    load_committed_baseline_schedule,
    project_baseline_cost,
    run_baseline_batch,
)
from omni_benchmark.baseline_batch_cli import baseline_batch_main
from omni_benchmark.baseline_batch_live import direct_concurrency_canary_schedule
from omni_benchmark.run_manifest import RunManifest

COMMIT_SHA = "a" * 40
SHA256 = "b" * 64


def test_live_child_environment_preserves_bytecode_suppression_only() -> None:
    environment = baseline_batch_cli._child_environment(
        {
            "PATH": "/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "UNAPPROVED_VALUE": "must-not-pass",
        }
    )

    assert environment == {"PATH": "/bin", "PYTHONDONTWRITEBYTECODE": "1"}


def _git(workspace: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(workspace), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _schedule_repo(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "repo"
    manifests = workspace / "data/manifests"
    manifests.mkdir(parents=True)
    ids = tuple(f"public_{index:03d}" for index in range(231))
    (manifests / "train_ids.txt").write_text("\n".join(ids) + "\n")
    rows = [
        {
            "category": "Query",
            "instance_id": instance_id,
            "query": f"Public question {index}",
            "selected_database": f"database_{index % 18:02d}",
        }
        for index, instance_id in enumerate(ids)
    ]
    (manifests / "eligible_questions.jsonl").write_text(
        "".join(
            json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"
            for row in rows
        )
    )
    (workspace / ".gitignore").write_text("experiments/autoresearch/raw/\n")
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "public schedule inputs")
    return workspace, _git(workspace, "rev-parse", "HEAD")


def _small_schedule(
    *, databases: int = 2, attempts_per_database: int = 4
) -> BaselineSchedule:
    attempts = tuple(
        BaselineAttempt(
            condition=BASELINE_CONDITIONS[index % len(BASELINE_CONDITIONS)],
            database=f"database_{database}",
            instance_id=f"question_{database}_{index}",
            repetition=1,
            run_id="public-baseline-v1",
        )
        for index in range(attempts_per_database)
        for database in range(databases)
    )
    return BaselineSchedule(
        attempts=attempts,
        eligible_manifest_sha256="c" * 64,
        source_commit=COMMIT_SHA,
        train_ids_sha256="d" * 64,
    )


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


def _write_attempt(
    root: Path,
    attempt: BaselineAttempt,
    *,
    cost_usd: float | None = 0.25,
    generation_outcome: str = "answered",
    latency_ms: float = 100.0,
    manifest_commit: str = COMMIT_SHA,
    terminal_failure_class: str | None = None,
) -> None:
    root.mkdir(parents=True, mode=0o700)
    os.chmod(root, 0o700)
    record = {
        "attempt_id": attempt.attempt_id,
        "condition": attempt.condition,
        "cost_usd": cost_usd,
        "database_query_count": 1,
        "generation_outcome": generation_outcome,
        "instance_id": attempt.instance_id,
        "latency_ms": latency_ms,
        "partition": "train",
        "repetition": attempt.repetition,
        "retry_count": 0,
        "run_id": attempt.run_id,
        "terminal_failure_class": terminal_failure_class,
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
            "finished_at": "2026-08-28T12:00:01Z",
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
            "started_at": "2026-08-28T12:00:00Z",
        },
        environment={},
    ).as_dict()
    for name, content in (
        ("generation.jsonl", generation),
        ("run.json", _canonical_json(manifest)),
    ):
        path = root / name
        path.write_bytes(content)
        os.chmod(path, 0o600)


def _executor(
    outcome_by_condition: dict[str, tuple[str, str | None]] | None = None,
    *,
    cost_usd: float | None = 0.25,
):
    outcomes = outcome_by_condition or {}

    def execute(attempt: BaselineAttempt, root: Path) -> None:
        outcome, failure = outcomes.get(attempt.condition, ("answered", None))
        _write_attempt(
            root,
            attempt,
            cost_usd=cost_usd,
            generation_outcome=outcome,
            terminal_failure_class=failure,
        )

    return execute


def test_committed_public_schedule_covers_all_231_questions_and_four_conditions(
    tmp_path: Path,
) -> None:
    workspace, commit = _schedule_repo(tmp_path)

    schedule = load_committed_baseline_schedule(
        workspace, commit, run_id="public-baseline-v1"
    )

    assert len(schedule.attempts) == 924
    assert len({attempt.instance_id for attempt in schedule.attempts}) == 231
    assert len({attempt.database for attempt in schedule.attempts}) == 18
    assert Counter(attempt.condition for attempt in schedule.attempts) == {
        condition: 231 for condition in BASELINE_CONDITIONS
    }
    assert len(schedule.sha256) == 64
    assert schedule.source_commit == commit
    assert not hasattr(schedule.attempts[0], "question")


def test_cost_projection_is_explicit_and_bound_to_the_full_schedule() -> None:
    projection = project_baseline_cost(
        _small_schedule(databases=18, attempts_per_database=1),
        observed_attempt_cost_usd="1.7398935",
        cost_ceiling_usd="40.00",
    )

    assert projection.attempt_count == 18
    assert projection.projected_cost_usd == "31.318083"
    assert projection.cost_ceiling_usd == "40.000000"
    assert projection.projected_over_ceiling is False
    assert projection.method == "uniform_observed_attempt_scenario"


def test_direct_only_baseline_is_fixed_to_all_231_questions_and_c1_c3(
    tmp_path: Path,
) -> None:
    workspace, commit = _schedule_repo(tmp_path)
    full = load_committed_baseline_schedule(
        workspace, commit, run_id="public-baseline-v1"
    )

    direct = direct_only_baseline_schedule(full)

    assert len(direct.attempts) == 693
    assert len({attempt.instance_id for attempt in direct.attempts}) == 231
    assert len({attempt.database for attempt in direct.attempts}) == 18
    assert {attempt.condition for attempt in direct.attempts} == {"C1", "C2", "C3"}


def test_concurrency_canary_is_fixed_to_four_public_train_ids_and_c1_c3() -> None:
    identities = (
        ("archeology_scan_3", "archeology_scan_large"),
        ("cross_border_1", "cross_border_large"),
        ("fake_account_1", "fake_account_large"),
        ("solar_panel_1", "solar_panel_large"),
    )
    full = BaselineSchedule(
        attempts=tuple(
            BaselineAttempt(
                condition=condition,
                database=database,
                instance_id=instance_id,
                repetition=1,
                run_id="public-baseline-v1",
            )
            for instance_id, database in identities
            for condition in BASELINE_CONDITIONS
        ),
        eligible_manifest_sha256="a" * 64,
        source_commit=COMMIT_SHA,
        train_ids_sha256="b" * 64,
    )

    canary = direct_concurrency_canary_schedule(full)

    assert len(canary.attempts) == 12
    assert tuple(dict.fromkeys(item.instance_id for item in canary.attempts)) == tuple(
        instance_id for instance_id, _ in identities
    )
    assert {item.condition for item in canary.attempts} == {"C1", "C2", "C3"}
    assert len({item.database for item in canary.attempts}) == 4


def test_scheduler_serializes_each_database_while_using_cross_database_parallelism(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    schedule = _small_schedule(databases=3, attempts_per_database=4)
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
    )
    lock = threading.Lock()
    active_databases: Counter[str] = Counter()
    maximum_parallel = 0
    outcomes = {
        "C1": ("answered", None),
        "C2": ("refused", "agent_refusal"),
        "C3": ("errored", "model_infrastructure_error"),
        "C4": ("answered", None),
    }

    def execute(attempt: BaselineAttempt, root: Path) -> None:
        nonlocal maximum_parallel
        with lock:
            active_databases[attempt.database] += 1
            assert active_databases[attempt.database] == 1
            maximum_parallel = max(maximum_parallel, sum(active_databases.values()))
        time.sleep(0.01)
        outcome, failure = outcomes[attempt.condition]
        _write_attempt(
            root,
            attempt,
            generation_outcome=outcome,
            terminal_failure_class=failure,
        )
        with lock:
            active_databases[attempt.database] -= 1

    report = run_baseline_batch(
        schedule,
        repository=repository,
        executor=execute,
        maximum_concurrency=3,
        budget=BatchBudget(cost_ceiling_usd=100, attempt_cost_ceiling_usd=1),
    )

    assert report.status == "complete"
    assert report.maximum_observed_concurrency == 3
    assert maximum_parallel == 3
    assert report.outcome_counts == {"answered": 6, "errored": 3, "refused": 3}
    assert report.failure_classes_by_condition["C2"] == {"agent_refusal": 3}
    assert report.failure_classes_by_condition["C3"] == {
        "model_infrastructure_error": 3
    }
    assert report.telemetry.total_cost_usd == pytest.approx(3.0)
    assert report.telemetry.median_latency_ms == 100.0


def test_resume_skips_only_fully_reconciled_immutable_attempts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    schedule = _small_schedule(databases=2, attempts_per_database=2)
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
    )
    completed = schedule.attempts[0]
    _write_attempt(repository.attempt_root(completed), completed)
    executed: list[str] = []

    def execute(attempt: BaselineAttempt, root: Path) -> None:
        executed.append(attempt.attempt_id)
        _write_attempt(root, attempt)

    report = run_baseline_batch(
        schedule,
        repository=repository,
        executor=execute,
        maximum_concurrency=2,
        budget=BatchBudget(cost_ceiling_usd=10, attempt_cost_ceiling_usd=1),
    )

    assert report.reconciled_before_run == 1
    assert report.completed_this_run == 3
    assert completed.attempt_id not in executed
    assert report.remaining_attempts == 0


def test_existing_incomplete_attempt_fails_closed_instead_of_rerunning(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    schedule = _small_schedule(databases=1, attempts_per_database=1)
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
    )
    repository.attempt_root(schedule.attempts[0]).mkdir(parents=True)
    called = False

    def execute(_: BaselineAttempt, __: Path) -> None:
        nonlocal called
        called = True

    with pytest.raises(BaselineBatchError, match="incomplete or invalid"):
        run_baseline_batch(
            schedule,
            repository=repository,
            executor=execute,
            maximum_concurrency=1,
            budget=BatchBudget(cost_ceiling_usd=10, attempt_cost_ceiling_usd=1),
        )

    assert called is False


def test_repository_rejects_symlinked_output_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    (workspace / "experiments/autoresearch").mkdir(parents=True)
    outside.mkdir()
    (workspace / "experiments/autoresearch/raw").symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(BaselineBatchError, match="symlink"):
        ImmutableAttemptRepository(
            workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
        )


def test_existing_attempt_from_another_system_commit_fails_reconciliation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    schedule = _small_schedule(databases=1, attempts_per_database=1)
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
    )
    attempt = schedule.attempts[0]
    _write_attempt(
        repository.attempt_root(attempt),
        attempt,
        manifest_commit="e" * 40,
    )

    with pytest.raises(BaselineBatchError, match="incomplete or invalid"):
        run_baseline_batch(
            schedule,
            repository=repository,
            executor=_executor(),
            maximum_concurrency=1,
            budget=BatchBudget(cost_ceiling_usd=10, attempt_cost_ceiling_usd=1),
        )


def test_budget_reservation_stops_before_launching_unaffordable_attempts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    schedule = _small_schedule(databases=4, attempts_per_database=1)
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
    )

    report = run_baseline_batch(
        schedule,
        repository=repository,
        executor=_executor(cost_usd=0.6),
        maximum_concurrency=2,
        budget=BatchBudget(cost_ceiling_usd=2, attempt_cost_ceiling_usd=1),
    )

    assert report.status == "budget_stopped"
    assert report.completed_this_run == 2
    assert report.remaining_attempts == 2
    assert report.telemetry.total_cost_usd == pytest.approx(1.2)
    assert report.budget_stop_reason == "next_attempt_reservation_exceeds_ceiling"


@pytest.mark.parametrize("cost_usd", [None, 1.01])
def test_hard_budget_fails_closed_on_unobservable_or_over_reservation_cost(
    tmp_path: Path, cost_usd: float | None
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    schedule = _small_schedule(databases=1, attempts_per_database=1)
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
    )

    with pytest.raises(BaselineBatchError, match="hard budget"):
        run_baseline_batch(
            schedule,
            repository=repository,
            executor=_executor(cost_usd=cost_usd),
            maximum_concurrency=1,
            budget=BatchBudget(cost_ceiling_usd=10, attempt_cost_ceiling_usd=1),
        )


def test_explicit_c4_reservation_preserves_hard_budget_when_cost_is_unobservable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    attempt = BaselineAttempt(
        condition="C4",
        database="database_1",
        instance_id="question_1",
        repetition=1,
        run_id="public-baseline-v1",
    )
    schedule = BaselineSchedule(
        attempts=(attempt,),
        eligible_manifest_sha256="c" * 64,
        source_commit=COMMIT_SHA,
        train_ids_sha256="d" * 64,
    )
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
    )

    report = run_baseline_batch(
        schedule,
        repository=repository,
        executor=_executor(cost_usd=None),
        maximum_concurrency=1,
        budget=BatchBudget(
            cost_ceiling_usd=10,
            attempt_cost_ceiling_usd=1,
            unobservable_cost_reservation_conditions=frozenset({"C4"}),
        ),
    )

    assert report.status == "complete"
    assert report.budget_charge_usd == 1.0
    assert report.telemetry.total_cost_usd is None


def test_projection_cli_is_non_authenticated_and_exposes_no_scoring_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, commit = _schedule_repo(tmp_path)

    result = baseline_batch_main(
        [
            "--workspace",
            str(workspace),
            "--system-commit",
            commit,
            "--run-id",
            "public-baseline-v1",
            "--observed-attempt-cost-usd",
            "1.7398935",
            "--cost-ceiling-usd",
            "2000",
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["attempt_count"] == 924
    assert output["database_count"] == 18
    assert output["projected_cost_usd"] == "1607.661594"
    assert output["live_execution"] == "disabled_pending_d045_replay"
    encoded = json.dumps(output, sort_keys=True)
    assert "correct" not in encoded
    assert "external_knowledge" not in encoded
    assert "gold" not in encoded


def test_dry_run_cli_emits_full_plan_and_successful_canary_cost_range(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, commit = _schedule_repo(tmp_path)

    result = baseline_batch_main(
        [
            "--workspace",
            str(workspace),
            "--system-commit",
            commit,
            "--run-id",
            "public-baseline-v1",
            "--observed-attempt-cost-usd",
            "1.7398935",
            "--cost-ceiling-usd",
            "2000",
            "--dry-run-execution-plan",
            "--freeze-a-commit",
            "f" * 40,
            "--output-root",
            "experiments/autoresearch/raw/public-baseline-v1",
            "--claude-config-dir",
            "/outside/claude-1",
            "--observed-condition-cost",
            "C1=0.214778",
            "--observed-condition-cost",
            "C2=0.6084515",
            "--observed-condition-cost",
            "C3=0.7275655",
        ]
    )

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution_plan"]["attempt_count"] == 924
    assert output["successful_canary_cost_scenario"] == {
        "full_cost_high_scenario_usd": "526.301276",
        "full_cost_low_scenario_usd": "407.847363",
        "method": "condition_specific_successful_canary_scenario",
        "observed_condition_cost_usd": {
            "C1": "0.214778",
            "C2": "0.608452",
            "C3": "0.727566",
        },
        "observed_condition_subtotal_usd": "358.233645",
        "unobserved_conditions": ["C4"],
    }
    assert output["live_execution"] == "not_started"


def test_live_cli_refuses_to_dispatch_before_complete_deployment_gate(
    tmp_path: Path,
) -> None:
    workspace, commit = _schedule_repo(tmp_path)

    with pytest.raises(BaselineBatchError, match="private execution input"):
        baseline_batch_main(
            [
                "--workspace",
                str(workspace),
                "--system-commit",
                commit,
                "--run-id",
                "public-baseline-v1",
                "--observed-attempt-cost-usd",
                "1.7398935",
                "--cost-ceiling-usd",
                "2000",
                "--execute-live-baseline",
                "--freeze-a-commit",
                "f" * 40,
                "--output-root",
                "experiments/autoresearch/raw/public-baseline-v1",
                "--claude-config-dir",
                "/outside/claude-1",
                "--deployment-root",
                str(tmp_path / "missing-deployments"),
                "--deployment-run-id",
                "deploy-v1",
                "--database-environment-dir",
                str(tmp_path / "missing-environments"),
                "--attempt-cost-ceiling-usd",
                "1",
                "--maximum-concurrency",
                "4",
                "--observed-condition-cost",
                "C1=0.214778",
                "--observed-condition-cost",
                "C2=0.6084515",
                "--observed-condition-cost",
                "C3=0.7275655",
            ]
        )


def test_fixed_direct_live_mode_does_not_require_c4_deployment_gate(
    tmp_path: Path,
) -> None:
    workspace, commit = _schedule_repo(tmp_path)

    with pytest.raises((BaselineBatchError, FileNotFoundError), match="environment"):
        baseline_batch_main(
            [
                "--workspace",
                str(workspace),
                "--system-commit",
                commit,
                "--run-id",
                "public-baseline-v1",
                "--observed-attempt-cost-usd",
                "1.7398935",
                "--cost-ceiling-usd",
                "2000",
                "--execute-live-direct-baseline",
                "--freeze-a-commit",
                "f" * 40,
                "--output-root",
                "experiments/autoresearch/raw/public-baseline-v1",
                "--claude-config-dir",
                "/outside/claude-1",
                "--database-environment-dir",
                str(tmp_path / "missing-environments"),
                "--attempt-cost-ceiling-usd",
                "1",
                "--maximum-concurrency",
                "4",
                "--observed-condition-cost",
                "C1=0.214778",
                "--observed-condition-cost",
                "C2=0.6084515",
                "--observed-condition-cost",
                "C3=0.7275655",
            ]
        )

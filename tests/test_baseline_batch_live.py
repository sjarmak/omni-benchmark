from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import omni_benchmark.baseline_batch_live as batch_live
from omni_benchmark.baseline_batch import (
    BaselineAttempt,
    BaselineBatchError,
    BaselineSchedule,
    BatchBudget,
    ImmutableAttemptRepository,
    run_baseline_batch,
)
from omni_benchmark.baseline_batch_live import (
    DatabaseEnvironmentDirectory,
    DeploymentTarget,
    LiveBaselineDispatcher,
    build_execution_plan,
    c4_concurrency_canary_schedule,
    project_condition_cost_scenario,
    verify_deployment_gate,
)

from tests.test_baseline_batch import COMMIT_SHA, _write_attempt


def _schedule() -> BaselineSchedule:
    attempts = tuple(
        BaselineAttempt(
            condition=condition,
            database=database,
            instance_id=f"question_{database}_{condition.lower()}",
            repetition=1,
            run_id="public-baseline-v1",
        )
        for database in ("database_1", "database_2")
        for condition in ("C1", "C2", "C3", "C4")
    )
    return BaselineSchedule(
        attempts=attempts,
        eligible_manifest_sha256="a" * 64,
        source_commit=COMMIT_SHA,
        train_ids_sha256="b" * 64,
    )


def _private_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def test_successful_canary_cost_scenario_preserves_unobserved_c4_range() -> None:
    projection = project_condition_cost_scenario(
        _schedule(),
        observed_condition_cost_usd={
            "C1": "0.214778",
            "C2": "0.6084515",
            "C3": "0.7275655",
        },
    )

    assert projection.observed_condition_subtotal_usd == "3.101590"
    assert projection.unobserved_conditions == ("C4",)
    assert projection.full_cost_low_scenario_usd == "3.531146"
    assert projection.full_cost_high_scenario_usd == "4.556721"
    assert projection.method == "condition_specific_successful_canary_scenario"


def test_dry_run_plan_reuses_single_attempt_entrypoints_without_secret_values(
    tmp_path: Path,
) -> None:
    plan = build_execution_plan(
        _schedule(),
        workspace=tmp_path,
        output_root=Path("experiments/autoresearch/raw/public-baseline-v1"),
        claude_config_directories=(Path("/outside/claude-1"),),
        freeze_a_commit="f" * 40,
    )

    assert len(plan.attempts) == 8
    direct = plan.attempts[0]
    governed = next(item for item in plan.attempts if item.condition == "C4")
    assert direct.entrypoint == "scripts/baseline_direct_attempt.py"
    assert governed.entrypoint == "scripts/baseline_omni_attempt.py"
    assert "PGPASSWORD" not in " ".join(direct.command)
    assert "OMNI_API_TOKEN" not in " ".join(governed.command)
    assert direct.output_root.endswith("database_1/c1/question_database_1_c1-r1")
    assert len(plan.sha256) == 64


def test_execution_plan_rejects_duplicate_resolved_oauth_slots(tmp_path: Path) -> None:
    profile = tmp_path / "oauth"
    profile.mkdir()
    alias = tmp_path / "oauth-alias"
    alias.symlink_to(profile, target_is_directory=True)

    with pytest.raises(BaselineBatchError, match="OAuth slots must be distinct"):
        build_execution_plan(
            _schedule(),
            workspace=tmp_path,
            output_root=Path("experiments/autoresearch/raw/public-baseline-v1"),
            claude_config_directories=(profile, alias),
            freeze_a_commit="f" * 40,
        )


def test_database_environments_are_external_private_and_never_materialized_in_plan(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    root = tmp_path / "database-environments"
    root.mkdir(mode=0o700)
    _private_json(
        root / "database_1.json",
        {
            "PGDATABASE": "neondb",
            "PGHOST": "db.example",
            "PGPASSWORD": "private-password",
            "PGPORT": "5432",
            "PGSSLMODE": "require",
            "PGUSER": "reader",
        },
    )

    source = DatabaseEnvironmentDirectory(workspace, root)
    environment = source.for_database("database_1")

    assert environment["PGPASSWORD"] == "private-password"
    assert environment["PGSSLROOTCERT"] == "/etc/ssl/certs/ca-certificates.crt"
    assert "private-password" not in repr(source)


def test_deployment_gate_requires_one_verified_record_for_every_scheduled_database(
    tmp_path: Path,
) -> None:
    root = tmp_path / "deployments"
    root.mkdir(mode=0o700)
    source_commit = "c" * 40
    _private_json(
        root / "deploy-v1.claim",
        {
            "databases": ["database_1", "database_2"],
            "kind": "public-omni-semantic-deployment-claim",
            "run_id": "deploy-v1",
            "schema_version": 1,
            "source_commit": source_commit,
        },
    )
    _private_json(
        root / "deploy-v1.database_1.json",
        {
            "branch_id": "branch-1",
            "database": "database_1",
            "kind": "public-omni-semantic-deployment",
            "model_id": "model-1",
            "readback_verified": True,
            "run_id": "deploy-v1",
            "schema_version": 2,
            "semantic_model_sha256": "d" * 64,
            "source_commit": source_commit,
            "status": "verified",
            "validation_issue_count": 0,
        },
    )

    with pytest.raises(BaselineBatchError, match="exact database coverage"):
        verify_deployment_gate(root, "deploy-v1", {"database_1", "database_2"})


def test_deployment_gate_binds_verified_semantic_content_digest(tmp_path: Path) -> None:
    root = tmp_path / "deployments"
    root.mkdir(mode=0o700)
    source_commit = "c" * 40
    _private_json(
        root / "deploy-v1.claim",
        {
            "databases": ["database_1"],
            "kind": "public-omni-semantic-deployment-claim",
            "run_id": "deploy-v1",
            "schema_version": 1,
            "source_commit": source_commit,
        },
    )
    _private_json(
        root / "deploy-v1.database_1.json",
        {
            "branch_id": "branch-1",
            "database": "database_1",
            "kind": "public-omni-semantic-deployment",
            "model_id": "model-1",
            "readback_verified": True,
            "run_id": "deploy-v1",
            "schema_version": 2,
            "semantic_model_sha256": "d" * 64,
            "source_commit": source_commit,
            "status": "verified",
            "validation_issue_count": 0,
        },
    )

    targets = verify_deployment_gate(root, "deploy-v1", {"database_1"})

    assert targets == {
        "database_1": DeploymentTarget(
            branch_id="branch-1",
            model_id="model-1",
            semantic_model_sha256="d" * 64,
        )
    }


def test_c4_dispatch_passes_content_and_budget_binding_to_child(tmp_path: Path) -> None:
    attempt = BaselineAttempt(
        condition="C4",
        database="database_1",
        instance_id="question_1",
        repetition=1,
        run_id="c4-baseline-v1",
    )
    schedule = BaselineSchedule(
        attempts=(attempt,),
        eligible_manifest_sha256="a" * 64,
        source_commit=COMMIT_SHA,
        train_ids_sha256="b" * 64,
    )
    plan = build_execution_plan(
        schedule,
        workspace=tmp_path,
        output_root=Path("experiments/autoresearch/raw/c4-baseline-v1"),
        claude_config_directories=(tmp_path / "unused-claude",),
        freeze_a_commit="f" * 40,
    )
    budget = BatchBudget(
        cost_ceiling_usd=100,
        attempt_cost_ceiling_usd=7,
        unobservable_cost_reservation_conditions=frozenset({"C4"}),
    )
    observed: dict[str, str] = {}

    def runner(command, environment, _timeout):
        observed.update(environment)
        root = tmp_path / command[command.index("--output-root") + 1]
        _write_attempt(
            root,
            attempt,
            cost_usd=None,
            cost_reservation_usd=7.0,
            budget_policy_sha256=budget.sha256,
            cost_unavailable_reason="omni_job_api_does_not_expose_cost",
        )
        return batch_live.SubprocessOutcome(returncode=0, stdout=b"{}\n", stderr=b"")

    dispatcher = LiveBaselineDispatcher(
        plan,
        database_environments=None,
        common_environment={"OMNI_BASE_URL": "https://example.test"},
        runner=runner,
        timeout_seconds=10,
        semantic_candidate_kind="e02",
        deployment_targets={
            "database_1": DeploymentTarget(
                branch_id="branch-1",
                model_id="model-1",
                semantic_model_sha256="d" * 64,
            )
        },
        c4_budget=budget,
    )

    report = run_baseline_batch(
        schedule,
        repository=ImmutableAttemptRepository(
            tmp_path, Path("experiments/autoresearch/raw/c4-baseline-v1")
        ),
        executor=dispatcher,
        maximum_concurrency=1,
        budget=budget,
    )

    assert report.budget_charge_usd == 7.0
    assert observed["OMNI_SEMANTIC_MODEL_SHA256"] == "d" * 64
    assert observed["OMNI_COST_RESERVATION_USD"] == "7.000000"
    assert observed["OMNI_BUDGET_POLICY_SHA256"] == budget.sha256
    assert observed["OMNI_SEMANTIC_CANDIDATE_KIND"] == "e02"


def test_dispatcher_runs_direct_subprocesses_with_database_specific_environment(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environment_root = tmp_path / "database-environments"
    environment_root.mkdir(mode=0o700)
    for index in (1, 2):
        _private_json(
            environment_root / f"database_{index}.json",
            {
                "PGDATABASE": "neondb",
                "PGHOST": f"db-{index}.example",
                "PGPASSWORD": f"private-{index}",
                "PGPORT": "5432",
                "PGSSLMODE": "require",
                "PGUSER": "reader",
            },
        )
    schedule = BaselineSchedule(
        attempts=tuple(
            attempt for attempt in _schedule().attempts if attempt.condition != "C4"
        ),
        eligible_manifest_sha256="a" * 64,
        source_commit=COMMIT_SHA,
        train_ids_sha256="b" * 64,
    )
    repository = ImmutableAttemptRepository(
        workspace, Path("experiments/autoresearch/raw/public-baseline-v1")
    )
    observed: list[tuple[tuple[str, ...], str]] = []

    def runner(
        command: tuple[str, ...], environment: dict[str, str], _: float
    ) -> batch_live.SubprocessOutcome:
        output_index = command.index("--output-root") + 1
        condition = command[command.index("--condition") + 1]
        instance_id = command[command.index("--instance-id") + 1]
        attempt = next(
            item
            for item in schedule.attempts
            if item.condition == condition and item.instance_id == instance_id
        )
        observed.append((command, environment["PGHOST"]))
        _write_attempt(workspace / command[output_index], attempt, cost_usd=0.2)
        return batch_live.SubprocessOutcome(returncode=0, stdout=b"{}\n", stderr=b"")

    plan = build_execution_plan(
        schedule,
        workspace=workspace,
        output_root=Path("experiments/autoresearch/raw/public-baseline-v1"),
        claude_config_directories=(tmp_path / "claude-1", tmp_path / "claude-2"),
        freeze_a_commit="f" * 40,
    )
    dispatcher = LiveBaselineDispatcher(
        plan,
        database_environments=DatabaseEnvironmentDirectory(workspace, environment_root),
        common_environment={"PATH": os.environ["PATH"]},
        runner=runner,
        timeout_seconds=10,
    )

    report = run_baseline_batch(
        schedule,
        repository=repository,
        executor=dispatcher,
        maximum_concurrency=2,
        budget=BatchBudget(cost_ceiling_usd=10, attempt_cost_ceiling_usd=1),
    )

    assert report.status == "complete"
    assert report.completed_this_run == 6
    assert {host for _, host in observed} == {"db-1.example", "db-2.example"}
    assert all("private-" not in " ".join(command) for command, _ in observed)


def test_dispatcher_refuses_c4_until_the_verified_deployment_gate_is_attached(
    tmp_path: Path,
) -> None:
    schedule = _schedule()
    plan = build_execution_plan(
        schedule,
        workspace=tmp_path,
        output_root=Path("experiments/autoresearch/raw/public-baseline-v1"),
        claude_config_directories=(tmp_path / "claude-1",),
        freeze_a_commit="f" * 40,
    )
    dispatcher = LiveBaselineDispatcher(
        plan,
        database_environments=None,
        common_environment={},
        runner=lambda *_: batch_live.SubprocessOutcome(
            returncode=0, stdout=b"{}\n", stderr=b""
        ),
        timeout_seconds=10,
    )
    c4 = next(attempt for attempt in schedule.attempts if attempt.condition == "C4")
    planned = next(item for item in plan.attempts if item.attempt_id == c4.attempt_id)

    with pytest.raises(BaselineBatchError, match="deployment gate"):
        dispatcher(c4, tmp_path / planned.output_root)


def test_c4_concurrency_canary_selects_one_attempt_from_first_five_blocks() -> None:
    schedule = BaselineSchedule(
        attempts=tuple(
            BaselineAttempt(
                condition="C4",
                database=f"database_{database}",
                instance_id=f"question_{database}_{index}",
                repetition=1,
                run_id="c4-canary-v1",
            )
            for database in range(10)
            for index in range(2)
        ),
        eligible_manifest_sha256="a" * 64,
        source_commit=COMMIT_SHA,
        train_ids_sha256="b" * 64,
    )

    canary = c4_concurrency_canary_schedule(schedule)

    assert len(canary.attempts) == 5
    assert tuple(item.database for item in canary.attempts) == tuple(
        f"database_{index}" for index in range(5)
    )
    assert all(item.instance_id.endswith("_0") for item in canary.attempts)


def test_failed_child_keeps_final_root_resumable_and_preserves_safe_diagnostic(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environment_root = tmp_path / "database-environments"
    environment_root.mkdir(mode=0o700)
    _private_json(
        environment_root / "database_1.json",
        {
            "PGDATABASE": "neondb",
            "PGHOST": "db.example",
            "PGPASSWORD": "private-password",
            "PGPORT": "5432",
            "PGSSLMODE": "require",
            "PGUSER": "reader",
        },
    )
    attempt = BaselineAttempt(
        condition="C1",
        database="database_1",
        instance_id="question_1",
        repetition=1,
        run_id="public-baseline-v1",
    )
    schedule = BaselineSchedule(
        attempts=(attempt,),
        eligible_manifest_sha256="a" * 64,
        source_commit=COMMIT_SHA,
        train_ids_sha256="b" * 64,
    )
    output_root = Path("experiments/autoresearch/raw/public-baseline-v1")
    plan = build_execution_plan(
        schedule,
        workspace=workspace,
        output_root=output_root,
        claude_config_directories=(tmp_path / "claude-1",),
        freeze_a_commit="f" * 40,
    )
    repository = ImmutableAttemptRepository(workspace, output_root)

    failed = LiveBaselineDispatcher(
        plan,
        database_environments=DatabaseEnvironmentDirectory(workspace, environment_root),
        common_environment={"PATH": os.environ["PATH"]},
        runner=lambda *_: batch_live.SubprocessOutcome(
            returncode=2,
            stdout=b"",
            stderr=b"PGPASSWORD=private-password transient preflight failure",
        ),
        timeout_seconds=10,
    )

    with pytest.raises(BaselineBatchError, match="attempt executor failed"):
        run_baseline_batch(
            schedule,
            repository=repository,
            executor=failed,
            maximum_concurrency=1,
            budget=BatchBudget(cost_ceiling_usd=10, attempt_cost_ceiling_usd=1),
        )

    assert not repository.attempt_root(attempt).exists()
    diagnostics = tuple(
        repository.attempt_root(attempt).parent.glob(".failed-*/failure.json")
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].stat().st_mode & 0o777 == 0o600
    diagnostic = diagnostics[0].read_text(encoding="utf-8")
    assert "private-password" not in diagnostic
    assert "[REDACTED]" in diagnostic

    def successful_runner(
        command: tuple[str, ...], _environment: dict[str, str], _timeout: float
    ) -> batch_live.SubprocessOutcome:
        staged_root = workspace / command[command.index("--output-root") + 1]
        _write_attempt(staged_root, attempt, cost_usd=0.2)
        return batch_live.SubprocessOutcome(returncode=0, stdout=b"{}\n", stderr=b"")

    succeeded = LiveBaselineDispatcher(
        plan,
        database_environments=DatabaseEnvironmentDirectory(workspace, environment_root),
        common_environment={"PATH": os.environ["PATH"]},
        runner=successful_runner,
        timeout_seconds=10,
    )
    report = run_baseline_batch(
        schedule,
        repository=repository,
        executor=succeeded,
        maximum_concurrency=1,
        budget=BatchBudget(cost_ceiling_usd=10, attempt_cost_ceiling_usd=1),
    )

    assert report.status == "complete"
    assert repository.attempt_root(attempt).is_dir()

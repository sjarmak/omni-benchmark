from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.c1_retrieval_sensitivity import (
    DEFAULT_C1_RETRIEVAL_SENSITIVITY_SEED,
    SENSITIVITY_QUESTION_COUNT,
    SENSITIVITY_LEGACY_BATCH_CAPACITY_USD,
    SENSITIVITY_OUTPUT_ROOT,
    SENSITIVITY_RUN_ID,
    C1RetrievalSensitivityError,
    create_c1_retrieval_sensitivity_subset,
    load_committed_c1_retrieval_sensitivity_schedule,
    validate_c1_retrieval_sensitivity_invocation,
)
from omni_benchmark.baseline_batch import (
    AttemptObservation,
    BatchBudget,
    run_baseline_batch,
)
from omni_benchmark.baseline_batch_cli import baseline_batch_main
from omni_benchmark.direct_public_search import (
    MAX_SCHEMA_MATCHES,
    MAX_SCHEMA_PAYLOAD_BYTES,
)


BASELINE_COMMIT = "5be315e44bea7ee1a39500380dcbc4c05976dd3e"


def _git(workspace: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(workspace), *arguments),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _copy_public_inputs(source: Path, destination: Path) -> None:
    (destination / "data/manifests").mkdir(parents=True)
    (destination / "config/conditions").mkdir(parents=True)
    for relative in (
        "data/manifests/eligible_questions.jsonl",
        "data/manifests/train_ids.txt",
        "config/conditions/public-baseline-exclusions-v1.json",
        "config/conditions/c1-retrieval-sensitivity-v1.json",
        "config/conditions/c1-direct-sql-v1.json",
        "config/conditions/direct-database-targets-v1.json",
        "config/conditions/direct-runtime-v1.json",
        "config/instructions/direct-sql-v1.json",
        "config/prompts/direct-sql-v1.txt",
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)


def test_frozen_subset_regenerates_byte_identically(tmp_path: Path) -> None:
    workspace = Path(__file__).resolve().parents[1]
    _copy_public_inputs(workspace, tmp_path)

    metadata = create_c1_retrieval_sensitivity_subset(tmp_path)

    assert metadata["algorithm"]["seed"] == DEFAULT_C1_RETRIEVAL_SENSITIVITY_SEED
    assert metadata["counts"] == {
        "candidate_databases": 16,
        "candidate_questions": 210,
        "selected_databases": 16,
        "selected_questions": SENSITIVITY_QUESTION_COUNT,
    }
    for name in (
        "c1_retrieval_sensitivity_ids.txt",
        "c1_retrieval_sensitivity_metadata.json",
    ):
        assert (tmp_path / "data/manifests" / name).read_bytes() == (
            workspace / "data/manifests" / name
        ).read_bytes()


def test_subset_spans_all_nonexcluded_databases_and_balances_high_level() -> None:
    workspace = Path(__file__).resolve().parents[1]
    selected_ids = set(
        (workspace / "data/manifests/c1_retrieval_sensitivity_ids.txt")
        .read_text()
        .splitlines()
    )
    train_ids = set(
        (workspace / "data/manifests/train_ids.txt").read_text().splitlines()
    )
    test_ids = set((workspace / "data/manifests/test_ids.txt").read_text().splitlines())
    metadata = json.loads(
        (
            workspace / "data/manifests/c1_retrieval_sensitivity_metadata.json"
        ).read_text()
    )

    assert metadata["excluded_databases"] == [
        "archeology_scan_large",
        "cybermarket_pattern_large",
    ]
    assert metadata["counts"]["selected_questions"] == 20
    assert metadata["counts"]["selected_databases"] == 16
    assert selected_ids <= train_ids
    assert selected_ids.isdisjoint(test_ids)
    assert all(
        distribution["selected"] >= 1
        for distribution in metadata["distributions"]["by_database"].values()
    )
    assert set(metadata["distributions"]["overall"]) == {"candidate", "selected"}


def test_sensitivity_changes_only_schema_match_cap() -> None:
    workspace = Path(__file__).resolve().parents[1]
    configuration = json.loads(
        (workspace / "config/conditions/c1-retrieval-sensitivity-v1.json").read_text()
    )

    assert configuration == {
        "baseline_max_schema_matches": 4,
        "condition": "C1",
        "kind": "c1-schema-retrieval-sensitivity",
        "launch_margin_seconds": 600,
        "legacy_batch_capacity_usd": "1000000.000000",
        "maximum_schema_payload_bytes": 65536,
        "minimum_remaining_wall_clock_seconds": 1200,
        "notional_maximum_cost_usd": "240.000000",
        "output_root": "experiments/autoresearch/raw/c1-retrieval-sensitivity-v1",
        "preserved_artifact_sha256": {
            "c1_condition": (
                "59e3aaabcb75d5080c956c8c52d923f6dec4b754507299c37b9c1b7857fb9b1c"
            ),
            "database_targets": (
                "1eeaec61d5f2f871b01f85d865d345a368ee0b137310d5d0700f07244487434a"
            ),
            "direct_instructions": (
                "0729cd488f90031c0bb196436ac1d59cb303c0f1e8b46a207c94b690548c3d0e"
            ),
            "direct_prompt": (
                "6ab836dd048ff99665d24fabd4de351c8a393a602bac07e5889bb10a29037e57"
            ),
            "direct_runtime": (
                "21cfc382ae24020d4a85c11de752dc2a1c59578ce07f9bccc98647f7eafca2d4"
            ),
        },
        "preserved_budget_id": "direct-sql-public-baseline-v1",
        "question_count": 20,
        "projected_full_arm_wall_clock_seconds": 600,
        "remaining_wall_clock_rule": "strictly_greater_than_minimum",
        "run_id": "c1-retrieval-sensitivity-v1",
        "schema_version": 1,
        "sensitivity_max_schema_matches": 8,
        "source_baseline_commit": BASELINE_COMMIT,
    }
    assert MAX_SCHEMA_MATCHES == configuration["sensitivity_max_schema_matches"]
    assert MAX_SCHEMA_PAYLOAD_BYTES == configuration["maximum_schema_payload_bytes"]


def test_committed_loader_binds_public_subset_and_c1_only(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1]
    _copy_public_inputs(source, tmp_path)
    create_c1_retrieval_sensitivity_subset(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "sensitivity inputs")
    commit = _git(tmp_path, "rev-parse", "HEAD")

    schedule = load_committed_c1_retrieval_sensitivity_schedule(
        tmp_path, commit, run_id="c1-retrieval-sensitivity-v1"
    )

    assert len(schedule.attempts) == 20
    assert {attempt.condition for attempt in schedule.attempts} == {"C1"}
    assert len({attempt.database for attempt in schedule.attempts}) == 16
    assert [item.database for item in schedule.exclusions] == [
        "archeology_scan_large",
        "cybermarket_pattern_large",
    ]


def test_sensitivity_runner_builds_exact_twenty_attempt_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = Path(__file__).resolve().parents[1]
    _copy_public_inputs(source, tmp_path)
    create_c1_retrieval_sensitivity_subset(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "sensitivity inputs")
    commit = _git(tmp_path, "rev-parse", "HEAD")

    exit_code = baseline_batch_main(
        [
            "--workspace",
            str(tmp_path),
            "--system-commit",
            commit,
            "--run-id",
            "c1-retrieval-sensitivity-v1",
            "--observed-attempt-cost-usd",
            "2.19",
            "--cost-ceiling-usd",
            "1000000",
            "--c1-retrieval-sensitivity",
            "--dry-run-execution-plan",
            "--freeze-a-commit",
            "a" * 40,
            "--output-root",
            "experiments/autoresearch/raw/c1-retrieval-sensitivity-v1",
            "--claude-config-dir",
            "/profiles/claude-3",
            "--observed-condition-cost",
            "C1=2.19",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["schedule_identity"]["attempt_count"] == 20
    assert output["schedule_identity"]["database_count"] == 16
    assert {
        attempt["condition"] for attempt in output["execution_plan"]["attempts"]
    } == {"C1"}
    assert (
        output["successful_canary_cost_scenario"]["observed_condition_subtotal_usd"]
        == "43.800000"
    )


@pytest.mark.parametrize(
    ("run_id", "output_root", "capacity", "message"),
    [
        ("canonical-baseline", SENSITIVITY_OUTPUT_ROOT, "1000000", "run ID"),
        (
            SENSITIVITY_RUN_ID,
            Path("experiments/autoresearch/raw/canonical-baseline"),
            "1000000",
            "output root",
        ),
        (SENSITIVITY_RUN_ID, SENSITIVITY_OUTPUT_ROOT, "240", "nonbinding"),
    ],
)
def test_sensitivity_invocation_rejects_namespace_or_notional_cap(
    run_id: str, output_root: Path, capacity: str, message: str
) -> None:
    with pytest.raises(C1RetrievalSensitivityError, match=message):
        validate_c1_retrieval_sensitivity_invocation(
            run_id=run_id,
            output_root=output_root,
            cost_ceiling_usd=capacity,
            execute_live=False,
            remaining_wall_clock_seconds=None,
            attempt_cost_ceiling_usd=None,
        )


def test_live_sensitivity_requires_full_arm_wall_clock_and_attempt_maximum() -> None:
    common = {
        "run_id": SENSITIVITY_RUN_ID,
        "output_root": SENSITIVITY_OUTPUT_ROOT,
        "cost_ceiling_usd": str(SENSITIVITY_LEGACY_BATCH_CAPACITY_USD),
        "execute_live": True,
    }
    with pytest.raises(C1RetrievalSensitivityError, match="full-arm time"):
        validate_c1_retrieval_sensitivity_invocation(
            **common,
            remaining_wall_clock_seconds=1200,
            attempt_cost_ceiling_usd=12.0,
        )
    with pytest.raises(C1RetrievalSensitivityError, match="attempt maximum"):
        validate_c1_retrieval_sensitivity_invocation(
            **common,
            remaining_wall_clock_seconds=1201,
            attempt_cost_ceiling_usd=11.0,
        )
    validate_c1_retrieval_sensitivity_invocation(
        **common,
        remaining_wall_clock_seconds=1201,
        attempt_cost_ceiling_usd=12.0,
    )


def test_nonbinding_capacity_completes_all_twenty_maximum_cost_attempts(
    tmp_path: Path,
) -> None:
    source = Path(__file__).resolve().parents[1]
    _copy_public_inputs(source, tmp_path)
    create_c1_retrieval_sensitivity_subset(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "sensitivity inputs")
    commit = _git(tmp_path, "rev-parse", "HEAD")
    schedule = load_committed_c1_retrieval_sensitivity_schedule(
        tmp_path, commit, run_id=SENSITIVITY_RUN_ID
    )

    class Repository:
        def __init__(self) -> None:
            self.observations: dict[str, AttemptObservation] = {}

        def attempt_root(self, attempt):  # type: ignore[no-untyped-def]
            return tmp_path / attempt.attempt_id

        def reconcile(self, attempt, *, expected_commit):  # type: ignore[no-untyped-def]
            assert expected_commit == commit
            return self.observations.get(attempt.attempt_id)

    repository = Repository()

    def execute(attempt, _root):  # type: ignore[no-untyped-def]
        repository.observations[attempt.attempt_id] = AttemptObservation(
            attempt=attempt,
            cost_usd=12.0,
            database_query_count=1,
            failure_origin=None,
            generation_outcome="answered",
            latency_ms=100.0,
            retry_count=0,
            terminal_failure_class=None,
            token_count=100,
            tool_call_count=1,
            validation_attempt_count=0,
        )

    report = run_baseline_batch(
        schedule,
        repository=repository,  # type: ignore[arg-type]
        executor=execute,
        maximum_concurrency=3,
        budget=BatchBudget(
            cost_ceiling_usd=float(SENSITIVITY_LEGACY_BATCH_CAPACITY_USD),
            attempt_cost_ceiling_usd=12.0,
        ),
    )

    assert report.completed_this_run == 20
    assert report.remaining_attempts == 0
    assert report.budget_stop_reason is None


def test_committed_loader_rejects_tampered_selection_metadata(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1]
    _copy_public_inputs(source, tmp_path)
    create_c1_retrieval_sensitivity_subset(tmp_path)
    metadata_path = tmp_path / "data/manifests/c1_retrieval_sensitivity_metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["algorithm"]["seed"] = "outcome-selected-seed"
    metadata_path.write_text(json.dumps(metadata, sort_keys=True) + "\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "tampered sensitivity inputs")
    commit = _git(tmp_path, "rev-parse", "HEAD")

    with pytest.raises(C1RetrievalSensitivityError, match="metadata"):
        load_committed_c1_retrieval_sensitivity_schedule(
            tmp_path, commit, run_id="c1-retrieval-sensitivity-v1"
        )

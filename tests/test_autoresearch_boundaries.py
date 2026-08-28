from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import omni_benchmark.autoresearch_runs as autoresearch_runs

from omni_benchmark.autoresearch import (
    AutoresearchError,
    create_baseline,
    create_public_dev_a_view,
    load_config,
    validate_generation_outputs,
    validate_run,
)
from omni_benchmark.score_artifacts import create_score_artifact


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in values),
        encoding="utf-8",
    )
    path.chmod(0o600)


def public_question(instance_id: str) -> dict[str, object]:
    return {
        "instance_id": instance_id,
        "query": f"Question for {instance_id}",
        "selected_database": "safe_database",
        "category": "Query",
        "conditions": {"order": False},
    }


def run_record(
    instance_id: str,
    *,
    outcome: str,
    partition: str = "dev-a",
    latency_ms: float = 100,
    cost_usd: float | None = 0.01,
) -> dict[str, object]:
    finished_at = (
        (
            datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
            + timedelta(milliseconds=latency_ms)
        )
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {
        "attempt_id": f"run-1:{instance_id}:C4:1",
        "condition": "C4",
        "database_query_count": 1,
        "failure_origin": None,
        "finished_at": finished_at,
        "generation_outcome": "answered",
        "instance_id": instance_id,
        "model": {
            "provider": "test-provider",
            "name": "test-model",
            "version": "test-version",
        },
        "partition": partition,
        "question": f"Question for {instance_id}",
        "outcome": outcome,
        "repetition": 1,
        "retry_count": 0,
        "run_id": "run-1",
        "started_at": "2026-08-27T12:00:00Z",
        "terminal_failure_class": None,
        "telemetry_unavailable": [],
        "tool_call_count": 1,
        "tool_calls_by_name": [{"name": "query", "count": 1}],
        "token_source": "provider_reported",
        "cost_source": "provider_reported",
        "trace_captured": False,
        "trace_degraded_reason": "synthetic fixture has no raw trace",
        "trace_path": None,
        "trace_schema_version": None,
        "trace_sha256": None,
        "trace_truncated": False,
        "validation_attempt_count": 1,
        "generated_query": f"SELECT '{instance_id}'",
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "token_usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
        "harness_failure": None,
        "semantic_objects": ["topic.safe"],
    }


def unscored_record(instance_id: str, *, partition: str = "train") -> dict[str, object]:
    return {
        key: value
        for key, value in run_record(
            instance_id, outcome="correct", partition=partition
        ).items()
        if key != "outcome"
    }


@pytest.fixture
def configured_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    manifests = workspace / "data" / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "train_ids.txt").write_text(
        "train_1\ntrain_2\ndev_b_1\n", encoding="utf-8"
    )
    (manifests / "dev_a_ids.txt").write_text("train_1\ntrain_2\n", encoding="utf-8")
    (manifests / "dev_b_ids.txt").write_text("dev_b_1\n", encoding="utf-8")
    (manifests / "test_ids.txt").write_text("test_1\n", encoding="utf-8")
    write_jsonl(
        manifests / "eligible_questions.jsonl",
        [
            public_question("train_1"),
            public_question("test_1"),
            public_question("train_2"),
            public_question("dev_b_1"),
        ],
    )
    for name in (
        "manifest_metadata.json",
        "split_metadata.json",
        "development_split_metadata.json",
    ):
        write_json(manifests / name, {"fixture": True})
    config_path = workspace / "config" / "autoresearch.json"
    write_json(
        config_path,
        {
            "expected_train_count": 3,
            "expected_dev_a_count": 2,
            "expected_dev_b_count": 1,
            "dev_b_max_evaluations": 2,
            "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
            "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
            "test_ids_path": "data/manifests/test_ids.txt",
            "forbidden_fields": [
                "sol_sql",
                "gold_sql",
                "test_cases",
                "external_knowledge",
                "test_correctness",
                "gold_result",
                "expected_result",
            ],
            "guardian_public_key_sha256": "a" * 64,
            "ledger_path": "experiments/autoresearch/ledger.jsonl",
            "public_manifest_path": "data/manifests/eligible_questions.jsonl",
            "state_dir": "experiments/autoresearch/state",
            "train_ids_path": "data/manifests/train_ids.txt",
            "policy_notes": {"selection": "human/model supplied, never inferred"},
        },
    )
    return workspace, config_path


def load_fixture_config(configured_workspace: tuple[Path, Path]):
    workspace, config_path = configured_workspace
    return load_config(config_path, workspace=workspace)


def write_full_run(
    workspace: Path,
    name: str,
    outcomes: tuple[str, str],
    *,
    latency: tuple[float, float] = (100, 200),
    cost: tuple[float | None, float | None] = (0.01, 0.02),
) -> Path:
    path = workspace / "runs" / f"{name}.jsonl"
    write_jsonl(
        path,
        [
            run_record(
                "train_1", outcome=outcomes[0], latency_ms=latency[0], cost_usd=cost[0]
            ),
            run_record(
                "train_2", outcome=outcomes[1], latency_ms=latency[1], cost_usd=cost[1]
            ),
        ],
    )
    return path


def baseline_for(config, workspace: Path) -> Path:
    run = workspace / "runs" / "baseline-all-train.jsonl"
    write_jsonl(
        run,
        [
            unscored_record("train_1"),
            unscored_record("train_2"),
            unscored_record("dev_b_1"),
        ],
    )
    return create_baseline(config, run_path=run, git_commit="a" * 40)


def test_public_run_validator_rejects_direct_dev_b_access(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    path = workspace / "runs" / "dev-b.jsonl"
    write_jsonl(
        path,
        [run_record("dev_b_1", outcome="correct", partition="dev-b")],
    )

    with pytest.raises(AutoresearchError, match="dev-B runs require checkpoint"):
        validate_run(load_fixture_config(configured_workspace), path, scope="dev-b")


def test_config_rejects_dev_b_budget_above_protocol_maximum(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, config_path = configured_workspace
    value = json.loads(config_path.read_text(encoding="utf-8"))
    value["dev_b_max_evaluations"] = 11
    write_json(config_path, value)

    with pytest.raises(AutoresearchError, match="must not exceed 10"):
        load_config(config_path, workspace=workspace)


def test_config_rejects_train_test_overlap_and_noncanonical_path(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, config_path = configured_workspace
    (workspace / "data" / "manifests" / "test_ids.txt").write_text(
        "train_1\n", encoding="utf-8"
    )
    with pytest.raises(AutoresearchError, match="train and test IDs"):
        load_config(config_path, workspace=workspace)

    alternate = workspace / "config" / "alternate.json"
    alternate.write_bytes(config_path.read_bytes())
    with pytest.raises(AutoresearchError, match="canonical path"):
        load_config(alternate, workspace=workspace)


def test_config_rejects_freeze_a_manifest_that_differs_from_head(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, config_path = configured_workspace
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "add", "config", "data/manifests"], cwd=workspace, check=True
    )
    subprocess.run(
        ["git", "commit", "-qm", "test: freeze protocol"], cwd=workspace, check=True
    )
    freeze_a_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert (
        load_config(
            config_path, workspace=workspace, freeze_a_commit=freeze_a_commit
        ).expected_dev_a_count
        == 2
    )

    (workspace / "data" / "manifests" / "dev_a_ids.txt").write_text(
        "train_2\ntrain_1\n", encoding="utf-8"
    )
    with pytest.raises(AutoresearchError, match="must match the recorded commit"):
        load_config(config_path, workspace=workspace, freeze_a_commit=freeze_a_commit)


def proposal_fields() -> dict[str, object]:
    return {
        "experiment_id": "exp-001",
        "parent": "baseline",
        "hypothesis": "Recursive dependencies are incompletely represented.",
        "intervention": "Materialize every dependency edge before semantic compilation.",
        "affected_class": "hierarchical knowledge dependency",
        "mechanism": "Preserve the public HKB dependency graph mechanically.",
        "predicted_direction": "Increase correctness for dependency-bearing metrics.",
        "regression_risk": "Cycles could reject otherwise usable definitions.",
        "subsystem": "HKB transformation",
        "generality_rationale": "The rule applies to every database and definition.",
        "evaluation_subset": ["train_1"],
        "condition": "C4",
        "content_provenance": "Public schema and HKB transformed at commit a.",
        "intervention_provenance": "Reusable transformer source diff at commit b.",
        "tuning_actor": "human_agent_collaboration",
        "tuning_effort": "one prespecified mechanism and one full dev-A run",
        "optimization_surface": "structural",
        "candidate_generation_method": "Deterministic transformer source change.",
        "generality_scope": "cross_database_general",
        "candidate_variants": [],
    }


def test_public_dev_a_view_contains_only_routine_questions_and_is_immutable(
    configured_workspace: tuple[Path, Path],
) -> None:
    config = load_fixture_config(configured_workspace)

    destination = create_public_dev_a_view(config)
    records = [json.loads(line) for line in destination.read_text().splitlines()]

    assert [record["instance_id"] for record in records] == ["train_1", "train_2"]
    assert all("test_1" not in json.dumps(record) for record in records)
    assert all("dev_b_1" not in json.dumps(record) for record in records)
    with pytest.raises(AutoresearchError, match="already exists"):
        create_public_dev_a_view(config)


def test_public_dev_a_view_rejects_nested_hidden_fields(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    manifest = workspace / "data" / "manifests" / "eligible_questions.jsonl"
    records = [public_question("train_1"), public_question("train_2")]
    records[1]["metadata"] = {"external_knowledge": ["DO-NOT-EXPOSE"]}
    write_jsonl(manifest, records)

    with pytest.raises(AutoresearchError, match="forbidden field") as error:
        create_public_dev_a_view(load_fixture_config(configured_workspace))

    assert "DO-NOT-EXPOSE" not in str(error.value)


def test_config_rejects_paths_outside_workspace_and_bad_types(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, config_path = configured_workspace
    value = json.loads(config_path.read_text())
    value["state_dir"] = "../escape"
    write_json(config_path, value)
    with pytest.raises(AutoresearchError, match="inside workspace"):
        load_config(config_path, workspace=workspace)

    value["state_dir"] = "experiments/state"
    value["expected_train_count"] = True
    write_json(config_path, value)
    with pytest.raises(AutoresearchError, match="expected_train_count"):
        load_config(config_path, workspace=workspace)


def test_validate_run_computes_metrics_for_exact_train_partition(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run_path = write_full_run(
        workspace,
        "candidate",
        ("correct", "wrong_answer"),
        latency=(75, 125),
        cost=(0.02, 0.03),
    )

    run = validate_run(config, run_path)

    assert run.accuracy == 0.5
    assert run.correct_ids == frozenset({"train_1"})
    assert run.wrong_answer_rate == 0.5
    assert run.refused_or_error_rate == 0
    assert run.mean_latency_ms == 100
    assert run.median_latency_ms == 100
    assert run.iqr_latency_ms == 25
    assert run.total_cost_usd == pytest.approx(0.05)
    assert run.total_tokens == 30
    assert run.tokens_per_correct == 30
    assert run.total_tool_calls == 2
    assert run.tool_calls_per_attempt == 1
    assert run.tool_calls_per_correct == 2
    assert run.total_database_queries == 2
    assert run.database_queries_per_correct == 2
    assert run.sha256 == hashlib.sha256(run_path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([run_record("train_1", outcome="correct")], "exactly 2"),
        (
            [
                run_record("train_1", outcome="correct"),
                run_record("train_1", outcome="wrong_answer"),
            ],
            "duplicate instance_id",
        ),
        (
            [
                run_record("train_1", outcome="correct"),
                run_record("dev_b_1", outcome="wrong_answer"),
            ],
            "outside the dev-a partition",
        ),
    ],
)
def test_validate_run_rejects_incomplete_duplicate_and_foreign_ids(
    configured_workspace: tuple[Path, Path],
    records: list[dict[str, object]],
    message: str,
) -> None:
    workspace, _ = configured_workspace
    path = workspace / "runs" / "invalid.jsonl"
    write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match=message):
        validate_run(load_fixture_config(configured_workspace), path)


def test_validate_run_rejects_mixed_conditions_runs_repetitions_and_attempt_ids(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    base = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    mutations = (
        ("condition", "C1", "one condition"),
        ("run_id", "other-run", "one condition"),
        ("repetition", 2, "one condition"),
        ("attempt_id", base[0]["attempt_id"], "duplicate attempt_id"),
    )
    for field, value, message in mutations:
        records = [dict(base[0]), dict(base[1])]
        records[1][field] = value
        path = workspace / "runs" / f"mixed-{field}.jsonl"
        write_jsonl(path, records)
        with pytest.raises(AutoresearchError, match=message):
            validate_run(load_fixture_config(configured_workspace), path)


def test_validate_run_recursively_rejects_hidden_or_test_score_fields(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    records = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    records[0]["diagnostics"] = {"gold_sql": "DO-NOT-LEAK"}
    path = workspace / "runs" / "hidden.jsonl"
    write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="forbidden field") as error:
        validate_run(load_fixture_config(configured_workspace), path)

    assert "DO-NOT-LEAK" not in str(error.value)


def test_validate_run_rejects_unregistered_trace_fields_without_echoing_content(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    records = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    records[0]["oracle_hint"] = "DO-NOT-LEAK"
    path = workspace / "runs" / "unknown.jsonl"
    write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="forbidden field") as error:
        validate_run(load_fixture_config(configured_workspace), path)

    assert "DO-NOT-LEAK" not in str(error.value)


def test_unscored_dev_a_generation_is_validated_separately_from_scoring(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    records = [unscored_record("train_1"), unscored_record("train_2")]
    for record in records:
        record["partition"] = "dev-a"
    path = workspace / "runs" / "unscored-dev-a.jsonl"
    write_jsonl(path, records)

    generation = validate_generation_outputs(
        load_fixture_config(configured_workspace), path, scope="dev-a"
    )

    assert generation.question_count == 2
    assert generation.scope == "dev-a"
    assert generation.condition == "C4"


def test_protocol_required_scoring_joins_only_a_bound_separate_artifact(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, config_path = configured_workspace
    config_value = json.loads(config_path.read_text(encoding="utf-8"))
    config_value["trace_policy"] = {
        "generation_and_scoring_records_are_immutable_and_separate": True
    }
    write_json(config_path, config_value)
    config = load_fixture_config(configured_workspace)
    records = [unscored_record("train_1"), unscored_record("train_2")]
    for record in records:
        record["partition"] = "dev-a"
    path = workspace / "runs" / "separate-generation.jsonl"
    write_jsonl(path, records)
    generation = validate_generation_outputs(config, path, scope="dev-a")
    scores = create_score_artifact(
        workspace,
        generation=generation,
        destination=Path("runs/separate-scores.json"),
        scorer_identity="official_soft_ex",
        scorer_version="test-v1",
        scores=[
            {"attempt_id": records[0]["attempt_id"], "outcome": "correct"},
            {"attempt_id": records[1]["attempt_id"], "outcome": "wrong_answer"},
        ],
    )

    with pytest.raises(AutoresearchError, match="score artifact path and hash"):
        validate_run(config, path)

    run = validate_run(
        config,
        path,
        score_path=scores.path,
        expected_score_sha256=scores.sha256,
    )

    assert run.accuracy == 0.5
    assert run.generation_sha256 == generation.sha256
    assert run.score_sha256 == scores.sha256
    assert run.score_path == scores.path
    assert run.sha256 not in {generation.sha256, scores.sha256}


@pytest.mark.parametrize(
    ("generation_outcome", "score_outcome", "message"),
    [
        ("refused", "correct", "answered scored outcomes require"),
        ("answered", "refused_or_error", "requires generation_outcome refused"),
    ],
)
def test_separate_scores_must_match_generation_terminal_state(
    configured_workspace: tuple[Path, Path],
    generation_outcome: str,
    score_outcome: str,
    message: str,
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    records = [unscored_record("train_1"), unscored_record("train_2")]
    for record in records:
        record["partition"] = "dev-a"
    records[0]["generation_outcome"] = generation_outcome
    if generation_outcome == "refused":
        for record in records:
            record["condition"] = "C1"
            record["attempt_id"] = record["attempt_id"].replace(":C4:", ":C1:")
        records[0]["failure_origin"] = "evaluated_system"
        records[0]["terminal_failure_class"] = "agent_refusal"
        records[0]["harness_failure"] = None
    path = workspace / "runs" / f"{generation_outcome}-generation.jsonl"
    write_jsonl(path, records)
    generation = validate_generation_outputs(config, path, scope="dev-a")
    scores = create_score_artifact(
        workspace,
        generation=generation,
        destination=Path(f"runs/{generation_outcome}-scores.json"),
        scorer_identity="official_soft_ex",
        scorer_version="test-v1",
        scores=[
            {"attempt_id": records[0]["attempt_id"], "outcome": score_outcome},
            {"attempt_id": records[1]["attempt_id"], "outcome": "correct"},
        ],
    )

    with pytest.raises(AutoresearchError, match=message):
        validate_run(
            config,
            path,
            score_path=scores.path,
            expected_score_sha256=scores.sha256,
        )


def test_scored_generation_detects_mutation_between_binding_and_summary(
    configured_workspace: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    records = [unscored_record("train_1"), unscored_record("train_2")]
    for record in records:
        record["partition"] = "dev-a"
    path = workspace / "runs" / "toctou-generation.jsonl"
    write_jsonl(path, records)
    generation = validate_generation_outputs(config, path, scope="dev-a")
    scores = create_score_artifact(
        workspace,
        generation=generation,
        destination=Path("runs/toctou-scores.json"),
        scorer_identity="official_soft_ex",
        scorer_version="test-v1",
        scores=[
            {"attempt_id": record["attempt_id"], "outcome": "correct"}
            for record in records
        ],
    )
    validate_score = autoresearch_runs.validate_score_artifact

    def mutate_after_score_validation(*args, **kwargs):
        validated = validate_score(*args, **kwargs)
        mutated = [dict(record) for record in records]
        mutated[0]["generated_query"] = "SELECT 99"
        write_jsonl(path, mutated)
        return validated

    monkeypatch.setattr(
        autoresearch_runs,
        "validate_score_artifact",
        mutate_after_score_validation,
    )

    with pytest.raises(AutoresearchError, match="generation artifact changed"):
        validate_run(
            config,
            path,
            score_path=scores.path,
            expected_score_sha256=scores.sha256,
        )


def test_unscored_generation_cannot_open_dev_b(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    path = workspace / "runs" / "dev-b.jsonl"
    record = unscored_record("dev_b_1")
    record["partition"] = "dev-b"
    write_jsonl(path, [record])

    with pytest.raises(AutoresearchError, match="dev-B generation requires"):
        validate_generation_outputs(
            load_fixture_config(configured_workspace), path, scope="dev-b"
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("partition", "test", "partition must be dev-a"),
        ("outcome", "unknown", "outcome"),
        ("latency_ms", -1, "latency_ms"),
        ("cost_usd", -0.01, "cost_usd"),
        ("semantic_objects", [1], "semantic_objects"),
    ],
)
def test_validate_run_rejects_invalid_artifact_fields(
    configured_workspace: tuple[Path, Path],
    field: str,
    value: object,
    message: str,
) -> None:
    workspace, _ = configured_workspace
    records = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    records[0][field] = value
    path = workspace / "runs" / "bad-field.jsonl"
    write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match=message):
        validate_run(load_fixture_config(configured_workspace), path)

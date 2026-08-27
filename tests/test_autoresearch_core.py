from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from omni_benchmark.autoresearch import (
    AutoresearchError,
    add_regression_case,
    create_baseline,
    decide_experiment,
    guard_intervention_text,
    load_config,
    propose_experiment,
    read_pareto_frontier,
    validate_generation_outputs,
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
    condition: str = "C4",
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
        "attempt_id": f"run-1:{instance_id}:{condition}:1",
        "condition": condition,
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


def test_baseline_is_full_train_hashed_and_cannot_be_redefined(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run = workspace / "runs" / "baseline.jsonl"
    write_jsonl(
        run,
        [
            unscored_record("train_1"),
            unscored_record("train_2"),
            unscored_record("dev_b_1"),
        ],
    )

    manifest_path = create_baseline(config, run_path=run, git_commit="a" * 40)
    manifest = json.loads(manifest_path.read_text())

    assert manifest["kind"] == "baseline"
    assert manifest["git_commit"] == "a" * 40
    assert manifest["run"]["scored"] is False
    assert "accuracy" not in manifest["run"]
    assert manifest["run"]["question_count"] == 3
    assert manifest["run"]["scope"] == "train"
    assert manifest["run"]["sha256"] == hashlib.sha256(run.read_bytes()).hexdigest()
    with pytest.raises(AutoresearchError, match="already exists"):
        create_baseline(config, run_path=run, git_commit="b" * 40)


def test_baseline_rejects_scored_outcomes(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run = workspace / "runs" / "invalid-scored-baseline.jsonl"
    write_jsonl(
        run,
        [
            run_record("train_1", outcome="correct", partition="train"),
            unscored_record("train_2"),
            unscored_record("dev_b_1"),
        ],
    )

    with pytest.raises(AutoresearchError, match="must not contain outcome"):
        create_baseline(config, run_path=run, git_commit="a" * 40)


def test_proposal_subset_rejects_dev_b_ids(
    configured_workspace: tuple[Path, Path],
) -> None:
    config = load_fixture_config(configured_workspace)
    baseline_for(config, config.workspace)
    fields = proposal_fields()
    fields["evaluation_subset"] = ["dev_b_1"]

    with pytest.raises(AutoresearchError, match="only dev-A IDs"):
        propose_experiment(config, **fields)


def test_experiment_lifecycle_records_lineage_and_computed_deltas(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    before = write_full_run(
        workspace, "before", ("correct", "wrong_answer"), latency=(100, 200)
    )
    after = write_full_run(
        workspace,
        "after",
        ("wrong_answer", "correct"),
        latency=(90, 110),
        cost=(0.005, 0.015),
    )
    baseline_for(config, workspace)

    proposal = propose_experiment(config, **proposal_fields())
    add_regression_case(
        config,
        instance_id="train_2",
        capability="recursive dependency compilation",
        rationale="Representative of the reusable dependency capability.",
        source_experiment="exp-001",
    )
    decision = decide_experiment(
        config,
        experiment_id="exp-001",
        decision="KEEP",
        before_run_path=before,
        after_run_path=after,
        git_commit="b" * 40,
        rationale="The reusable intervention exchanges one failure without net accuracy gain.",
        complexity_impact="One deterministic graph traversal; no runtime branch.",
        production_relevance="Applies to ordinary semantic-model compilation.",
        complexity_score=1,
        special_case_count=0,
        stability_rate=1.0,
        unexpected_observations="One previously correct question regressed.",
        follow_up_hypotheses=[
            "Constrain recursive expansion to reachable definitions."
        ],
    )

    assert proposal["event"] == "proposal"
    assert decision["event"] == "decision"
    assert decision["parent"] == "baseline"
    assert decision["condition"] == "C4"
    assert decision["content_provenance"]
    assert decision["intervention_provenance"]
    assert decision["tuning_actor"]
    assert decision["tuning_effort"]
    assert decision["regression_suite_evidence"][0]["preserved"] is True
    assert decision["pareto"]["status"] == "non_dominated"
    assert decision["metrics"]["accuracy_delta"] == 0
    assert decision["metrics"]["fixed_questions"] == ["train_2"]
    assert decision["metrics"]["regressed_questions"] == ["train_1"]
    assert decision["metrics"]["mean_latency_delta_ms"] == -50
    assert decision["metrics"]["total_cost_delta_usd"] == pytest.approx(-0.01)
    assert decision["metrics"]["outcome_transitions"] == {
        "correct->wrong_answer": 1,
        "wrong_answer->correct": 1,
    }
    assert decision["metrics"]["wrong_answer_rate_delta"] == 0
    assert decision["metrics"]["refused_or_error_rate_delta"] == 0
    events = [json.loads(line) for line in config.ledger_path.read_text().splitlines()]
    assert [event["event"] for event in events] == ["proposal", "decision"]
    assert events[1]["previous_event_sha256"] == events[0]["event_sha256"]
    assert [
        candidate["experiment_id"] for candidate in read_pareto_frontier(config)
    ] == ["exp-001"]

    dominated_before = write_full_run(
        workspace, "dominated-before", ("correct", "correct")
    )
    dominated_after = write_full_run(
        workspace,
        "dominated-after",
        ("wrong_answer", "correct"),
        latency=(900, 1100),
        cost=(0.1, 0.1),
    )
    child = proposal_fields()
    child.update({"experiment_id": "exp-002", "parent": "exp-001"})
    propose_experiment(config, **child)
    with pytest.raises(AutoresearchError, match="dominated candidate"):
        decide_experiment(
            config,
            experiment_id="exp-002",
            decision="KEEP",
            before_run_path=dominated_before,
            after_run_path=dominated_after,
            git_commit="c" * 40,
            rationale="Candidate is intentionally dominated.",
            complexity_impact="More complex.",
            production_relevance="General.",
            complexity_score=2,
            special_case_count=0,
            stability_rate=1,
            unexpected_observations="None.",
            follow_up_hypotheses=[],
        )


def test_decision_ledger_consumes_separate_hash_bound_score_artifacts(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, config_path = configured_workspace
    config_value = json.loads(config_path.read_text(encoding="utf-8"))
    config_value["trace_policy"] = {
        "generation_and_scoring_records_are_immutable_and_separate": True
    }
    write_json(config_path, config_value)
    config = load_fixture_config(configured_workspace)

    def scored_generation(name: str, outcomes: tuple[str, str]):
        path = workspace / "runs" / f"{name}.jsonl"
        records = [
            unscored_record("train_1", partition="dev-a"),
            unscored_record("train_2", partition="dev-a"),
        ]
        write_jsonl(path, records)
        generation = validate_generation_outputs(config, path, scope="dev-a")
        score = create_score_artifact(
            workspace,
            generation=generation,
            destination=Path(f"runs/{name}-scores.json"),
            scorer_identity="official_soft_ex",
            scorer_version="test-v1",
            scores=[
                {"attempt_id": records[index]["attempt_id"], "outcome": outcome}
                for index, outcome in enumerate(outcomes)
            ],
        )
        return generation, score

    before_generation, before_score = scored_generation(
        "separate-before", ("correct", "wrong_answer")
    )
    after_generation, after_score = scored_generation(
        "separate-after", ("correct", "correct")
    )
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    add_regression_case(
        config,
        instance_id="train_2",
        capability="separate score integration",
        rationale="Representative fixed capability.",
        source_experiment="exp-001",
    )

    decision = decide_experiment(
        config,
        experiment_id="exp-001",
        decision="KEEP",
        before_run_path=before_generation.path,
        before_score_path=before_score.path,
        before_score_sha256=before_score.sha256,
        after_run_path=after_generation.path,
        after_score_path=after_score.path,
        after_score_sha256=after_score.sha256,
        git_commit="b" * 40,
        rationale="The bound score demonstrates a reusable improvement.",
        complexity_impact="No runtime complexity.",
        production_relevance="Preserves generation/scoring separation.",
        complexity_score=0,
        special_case_count=0,
        stability_rate=1,
        unexpected_observations="None.",
        follow_up_hypotheses=[],
    )

    assert decision["before_run"]["score_sha256"] == before_score.sha256
    assert decision["after_run"]["score_sha256"] == after_score.sha256
    assert decision["metrics"]["accuracy_delta"] == 0.5


def test_pareto_candidates_are_compared_within_condition(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    before = write_full_run(workspace, "condition-before", ("correct", "wrong_answer"))
    after = write_full_run(workspace, "condition-after", ("correct", "correct"))
    baseline_for(config, workspace)

    c4 = proposal_fields()
    propose_experiment(config, **c4)
    add_regression_case(
        config,
        instance_id="train_2",
        capability="C4 dependency capability",
        rationale="Representative governed capability.",
        source_experiment="exp-001",
    )
    decide_experiment(
        config,
        experiment_id="exp-001",
        decision="KEEP",
        before_run_path=before,
        after_run_path=after,
        git_commit="b" * 40,
        rationale="Governed candidate.",
        complexity_impact="Small.",
        production_relevance="General.",
        complexity_score=1,
        special_case_count=0,
        stability_rate=1,
        unexpected_observations="None.",
        follow_up_hypotheses=[],
    )

    c1 = proposal_fields()
    c1.update({"experiment_id": "exp-c1", "condition": "C1"})
    propose_experiment(config, **c1)
    add_regression_case(
        config,
        instance_id="train_2",
        capability="C1 SQL capability",
        rationale="Representative direct-SQL capability.",
        source_experiment="exp-c1",
    )
    c1_before = workspace / "runs" / "condition-c1-before.jsonl"
    write_jsonl(
        c1_before,
        [
            run_record("train_1", outcome="correct", condition="C1"),
            run_record("train_2", outcome="correct", condition="C1"),
        ],
    )
    decision = decide_experiment(
        config,
        experiment_id="exp-c1",
        decision="KEEP",
        before_run_path=c1_before,
        after_run_path=c1_before,
        git_commit="c" * 40,
        rationale="Competent C1 candidate retained independently.",
        complexity_impact="Small.",
        production_relevance="Comparator competence.",
        complexity_score=2,
        special_case_count=0,
        stability_rate=1,
        unexpected_observations="None.",
        follow_up_hypotheses=[],
    )

    assert decision["condition"] == "C1"
    assert {item["condition"] for item in read_pareto_frontier(config)} == {"C1", "C4"}


def test_decision_requires_proposal_and_rejects_second_decision(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run = write_full_run(workspace, "run", ("correct", "wrong_answer"))
    baseline_for(config, workspace)

    with pytest.raises(AutoresearchError, match="proposal must be recorded first"):
        decide_experiment(
            config,
            experiment_id="missing",
            decision="REVERT",
            before_run_path=run,
            after_run_path=run,
            git_commit="b" * 40,
            rationale="No proposal exists.",
            complexity_impact="No change.",
            production_relevance="Not established.",
            complexity_score=1,
            special_case_count=0,
            stability_rate=1,
            unexpected_observations="None.",
            follow_up_hypotheses=[],
        )

    propose_experiment(config, **proposal_fields())
    kwargs = {
        "experiment_id": "exp-001",
        "decision": "INVESTIGATE",
        "before_run_path": run,
        "after_run_path": run,
        "git_commit": "b" * 40,
        "rationale": "The evidence is inconclusive.",
        "complexity_impact": "One additional transformation rule.",
        "production_relevance": "Potentially reusable but not established.",
        "complexity_score": 1,
        "special_case_count": 0,
        "stability_rate": 1,
        "unexpected_observations": "None.",
        "follow_up_hypotheses": [],
    }
    decide_experiment(config, **kwargs)
    with pytest.raises(AutoresearchError, match="already has a decision"):
        decide_experiment(config, **kwargs)


def test_proposal_requires_baseline_existing_parent_and_unique_id(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    fields = proposal_fields()
    with pytest.raises(AutoresearchError, match="baseline must be frozen"):
        propose_experiment(config, **fields)

    baseline_for(config, workspace)
    fields["parent"] = "not-existing"
    with pytest.raises(
        AutoresearchError, match="parent must be baseline or an existing candidate"
    ):
        propose_experiment(config, **fields)

    fields["parent"] = "baseline"
    propose_experiment(config, **fields)
    with pytest.raises(AutoresearchError, match="already exists"):
        propose_experiment(config, **fields)


def test_proposal_surface_and_generality_guards(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    baseline_for(config, workspace)
    fields = proposal_fields()
    fields["optimization_surface"] = "human_research_controlled"
    fields["tuning_actor"] = "autonomous_agent"
    with pytest.raises(AutoresearchError, match="human-research-controlled"):
        propose_experiment(config, **fields)

    fields["optimization_surface"] = "textual"
    fields["generality_scope"] = "question_specific"
    fields["tuning_actor"] = "human_agent_collaboration"
    with pytest.raises(AutoresearchError, match="question_specific"):
        propose_experiment(config, **fields)

    fields["generality_scope"] = "cross_database_general"
    fields["candidate_variants"] = [{"patch": "if train_1 then use metric X"}]
    with pytest.raises(AutoresearchError, match="benchmark instance ID"):
        propose_experiment(config, **fields)


def test_branching_parent_may_be_an_undecided_existing_candidate(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    child = proposal_fields()
    child["experiment_id"] = "exp-branch"
    child["parent"] = "exp-001"

    assert propose_experiment(config, **child)["parent"] == "exp-001"


def test_regression_suite_is_dev_a_only_append_only_and_required_for_keep(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    before = write_full_run(workspace, "before", ("correct", "wrong_answer"))
    after = write_full_run(workspace, "after", ("correct", "correct"))
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    with pytest.raises(AutoresearchError, match="regression suite"):
        decide_experiment(
            config,
            experiment_id="exp-001",
            decision="KEEP",
            before_run_path=before,
            after_run_path=after,
            git_commit="b" * 40,
            rationale="Gain.",
            complexity_impact="Small.",
            production_relevance="General.",
            complexity_score=1,
            special_case_count=0,
            stability_rate=1,
            unexpected_observations="None.",
            follow_up_hypotheses=[],
        )
    with pytest.raises(AutoresearchError, match="dev-A"):
        add_regression_case(
            config,
            instance_id="dev_b_1",
            capability="forbidden oracle",
            rationale="Must reject.",
            source_experiment="exp-001",
        )
    add_regression_case(
        config,
        instance_id="train_2",
        capability="dependency compilation",
        rationale="Representative reusable case.",
        source_experiment="exp-001",
    )
    with pytest.raises(AutoresearchError, match="already exists"):
        add_regression_case(
            config,
            instance_id="train_2",
            capability="duplicate",
            rationale="Must reject.",
            source_experiment="exp-001",
        )


def test_guard_flags_exact_question_ids_without_prefix_false_positive() -> None:
    guard_intervention_text("Support train_10 generically.", {"train_1"})

    with pytest.raises(AutoresearchError, match="benchmark instance ID"):
        guard_intervention_text("if train_1 then choose metric X", {"train_1"})

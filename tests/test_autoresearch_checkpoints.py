from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from omni_benchmark.autoresearch import (
    AutoresearchError,
    add_regression_case,
    create_baseline,
    create_checkpoint,
    decide_experiment,
    load_config,
    propose_experiment,
    stop_optimization,
)


def test_lifecycle_exports_remain_ledger_compatible() -> None:
    """The split keeps legacy imports as direct aliases, not behavior wrappers."""
    from omni_benchmark import autoresearch_ledger, autoresearch_lifecycle

    assert autoresearch_ledger.create_baseline is autoresearch_lifecycle.create_baseline
    assert (
        autoresearch_ledger.create_checkpoint
        is autoresearch_lifecycle.create_checkpoint
    )
    assert (
        autoresearch_ledger.stop_optimization
        is autoresearch_lifecycle.stop_optimization
    )


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


def _ensure_guardian_key(workspace: Path) -> tuple[Path, Path]:
    private_key = workspace.parent / "guardian-private.pem"
    public_key = workspace / "experiments" / "autoresearch" / "guardian-public.pem"
    if private_key.exists():
        return private_key, public_key
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            str(private_key),
        ],
        check=True,
        capture_output=True,
    )
    public_key.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(private_key),
            "-pubout",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    return private_key, public_key


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
    _, guardian_public_key = _ensure_guardian_key(workspace)
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
            "guardian_public_key_sha256": hashlib.sha256(
                guardian_public_key.read_bytes()
            ).hexdigest(),
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


@dataclass(frozen=True)
class GuardianReceipt:
    receipt: Path
    signature: Path
    public_key: Path
    public_key_sha256: str


def _guardian_arguments(receipt: GuardianReceipt) -> dict[str, object]:
    return {
        "dev_b_receipt_path": receipt.receipt,
        "dev_b_signature_path": receipt.signature,
        "guardian_public_key_path": receipt.public_key,
    }


def write_dev_b_receipt(workspace: Path, candidate: Path, name: str) -> GuardianReceipt:
    path = (
        workspace
        / "experiments"
        / "autoresearch"
        / "guardian_receipts"
        / f"{name}.json"
    )
    write_json(
        path,
        {
            "schema_version": 1,
            "kind": "dev-b-checkpoint-receipt",
            "receipt_id": name,
            "guardian": "synthetic-test-guardian",
            "created_at": "2026-08-27T12:00:00Z",
            "candidate_run_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            "outputs_sha256": hashlib.sha256(name.encode()).hexdigest(),
            "scorer_version": "synthetic-test-scorer-v1",
            "question_count": 1,
            "correct_count": 1,
            "wrong_answer_count": 0,
            "refused_or_error_count": 0,
        },
    )
    private_key, public_key = _ensure_guardian_key(workspace)
    signature = path.with_suffix(".sig")
    subprocess.run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(signature),
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return GuardianReceipt(
        receipt=path,
        signature=signature,
        public_key=public_key,
        public_key_sha256=hashlib.sha256(public_key.read_bytes()).hexdigest(),
    )


def test_checkpoint_records_full_train_taxonomy_and_ledger_head(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run = write_full_run(workspace, "checkpoint", ("correct", "wrong_answer"))
    dev_b_receipt = write_dev_b_receipt(workspace, run, "checkpoint-1")
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    taxonomy = workspace / "analysis" / "taxonomy.json"
    write_json(
        taxonomy,
        {
            "categories": [
                {
                    "name": "failed dependency resolution",
                    "count": 1,
                    "primary_source": "semantic model",
                }
            ]
        },
    )

    path = create_checkpoint(
        config,
        name="checkpoint-1",
        run_path=run,
        **_guardian_arguments(dev_b_receipt),
        taxonomy_path=taxonomy,
        git_commit="b" * 40,
    )
    checkpoint = json.loads(path.read_text())

    assert checkpoint["run"]["question_count"] == 2
    assert checkpoint["run"]["scope"] == "dev-a"
    assert checkpoint["dev_b_receipt"]["question_count"] == 1
    assert "correct_ids" not in checkpoint["dev_b_receipt"]
    assert checkpoint["dev_b_evaluation_number"] == 1
    assert (config.state_dir / "dev_b_evaluations" / "0001.json").is_file()
    dev_b_view = Path(workspace / checkpoint["dev_b_public_view_path"])
    assert [
        json.loads(line)["instance_id"] for line in dev_b_view.read_text().splitlines()
    ] == ["dev_b_1"]
    assert (
        checkpoint["taxonomy_sha256"]
        == hashlib.sha256(taxonomy.read_bytes()).hexdigest()
    )
    assert checkpoint["ledger_head_sha256"]
    with pytest.raises(AutoresearchError, match="already exists"):
        create_checkpoint(
            config,
            name="checkpoint-1",
            run_path=run,
            **_guardian_arguments(dev_b_receipt),
            taxonomy_path=taxonomy,
            git_commit="c" * 40,
        )


@pytest.mark.parametrize(
    "taxonomy",
    [
        {"categories": []},
        {"categories": [{"name": "x", "count": -1, "primary_source": "model"}]},
        {
            "categories": [
                {"name": "same", "count": 1, "primary_source": "model"},
                {"name": "same", "count": 1, "primary_source": "harness"},
            ]
        },
    ],
)
def test_checkpoint_rejects_invalid_supplied_taxonomy(
    configured_workspace: tuple[Path, Path], taxonomy: dict[str, object]
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run = write_full_run(workspace, "run", ("correct", "wrong_answer"))
    dev_b_receipt = write_dev_b_receipt(workspace, run, "bad")
    path = workspace / "analysis" / "taxonomy.json"
    write_json(path, taxonomy)

    with pytest.raises(AutoresearchError, match="taxonomy"):
        create_checkpoint(
            config,
            name="bad",
            run_path=run,
            **_guardian_arguments(dev_b_receipt),
            taxonomy_path=path,
            git_commit="a" * 40,
        )


def test_checkpoint_enforces_the_immutable_dev_b_evaluation_budget(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, config_path = configured_workspace
    config_value = json.loads(config_path.read_text())
    config_value["dev_b_max_evaluations"] = 1
    write_json(config_path, config_value)
    config = load_fixture_config(configured_workspace)
    run = write_full_run(workspace, "dev-a", ("correct", "wrong_answer"))
    first_receipt = write_dev_b_receipt(workspace, run, "checkpoint-1")
    second_receipt = write_dev_b_receipt(workspace, run, "checkpoint-2")
    taxonomy = workspace / "analysis" / "taxonomy.json"
    write_json(
        taxonomy,
        {"categories": [{"name": "join", "count": 1, "primary_source": "model"}]},
    )
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    create_checkpoint(
        config,
        name="checkpoint-1",
        run_path=run,
        **_guardian_arguments(first_receipt),
        taxonomy_path=taxonomy,
        git_commit="b" * 40,
    )

    with pytest.raises(AutoresearchError, match="budget is exhausted"):
        create_checkpoint(
            config,
            name="checkpoint-2",
            run_path=run,
            **_guardian_arguments(second_receipt),
            taxonomy_path=taxonomy,
            git_commit="c" * 40,
        )


def test_checkpoint_rejects_replayed_guardian_receipt(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run = write_full_run(workspace, "replay", ("correct", "wrong_answer"))
    receipt = write_dev_b_receipt(workspace, run, "single-receipt")
    taxonomy = workspace / "analysis" / "taxonomy.json"
    write_json(
        taxonomy,
        {"categories": [{"name": "join", "count": 1, "primary_source": "model"}]},
    )
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    create_checkpoint(
        config,
        name="checkpoint-1",
        run_path=run,
        **_guardian_arguments(receipt),
        taxonomy_path=taxonomy,
        git_commit="b" * 40,
    )

    with pytest.raises(AutoresearchError, match="already consumed"):
        create_checkpoint(
            config,
            name="checkpoint-2",
            run_path=run,
            **_guardian_arguments(receipt),
            taxonomy_path=taxonomy,
            git_commit="c" * 40,
        )


def test_checkpoint_rejects_replay_after_allocation_marker_is_deleted(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run = write_full_run(workspace, "marker-deletion", ("correct", "wrong_answer"))
    receipt = write_dev_b_receipt(workspace, run, "single-receipt")
    taxonomy = workspace / "analysis" / "taxonomy.json"
    write_json(
        taxonomy,
        {"categories": [{"name": "join", "count": 1, "primary_source": "model"}]},
    )
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    create_checkpoint(
        config,
        name="checkpoint-1",
        run_path=run,
        **_guardian_arguments(receipt),
        taxonomy_path=taxonomy,
        git_commit="b" * 40,
    )
    (config.state_dir / "dev_b_evaluations" / "0001.json").unlink()

    with pytest.raises(AutoresearchError, match="dev-B evaluation history"):
        create_checkpoint(
            config,
            name="checkpoint-2",
            run_path=run,
            **_guardian_arguments(receipt),
            taxonomy_path=taxonomy,
            git_commit="c" * 40,
        )


def test_stop_is_immutable_and_blocks_new_proposals(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    baseline_for(config, workspace)

    path = stop_optimization(
        config,
        reason="further gains require benchmark-specific special casing",
        rationale="Remaining failures cannot support reusable interventions.",
        git_commit="c" * 40,
    )

    assert json.loads(path.read_text())["kind"] == "optimization-stop"
    with pytest.raises(AutoresearchError, match="optimization has stopped"):
        propose_experiment(config, **proposal_fields())
    with pytest.raises(AutoresearchError, match="already exists"):
        stop_optimization(
            config,
            reason="duplicate",
            rationale="Must not rewrite history.",
            git_commit="d" * 40,
        )


def test_stop_blocks_decisions_regressions_and_checkpoints(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    run = write_full_run(workspace, "stopped", ("correct", "wrong_answer"))
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    stop_optimization(
        config,
        reason="final candidate selected",
        rationale="The development loop is closed.",
        git_commit="c" * 40,
    )

    with pytest.raises(AutoresearchError, match="optimization has stopped"):
        add_regression_case(
            config,
            instance_id="train_1",
            capability="late mutation",
            rationale="Must be rejected.",
            source_experiment="exp-001",
        )
    with pytest.raises(AutoresearchError, match="optimization has stopped"):
        decide_experiment(
            config,
            experiment_id="exp-001",
            decision="REVERT",
            before_run_path=run,
            after_run_path=run,
            git_commit="d" * 40,
            rationale="Late decision.",
            complexity_impact="None.",
            production_relevance="None.",
            complexity_score=0,
            special_case_count=0,
            stability_rate=1,
            unexpected_observations="None.",
            follow_up_hypotheses=[],
        )
    with pytest.raises(AutoresearchError, match="optimization has stopped"):
        create_checkpoint(
            config,
            name="late-checkpoint",
            run_path=run,
            dev_b_receipt_path=workspace / "missing-receipt.json",
            dev_b_signature_path=workspace / "missing-receipt.sig",
            guardian_public_key_path=workspace / "missing-public-key.pem",
            taxonomy_path=workspace / "missing-taxonomy.json",
            git_commit="d" * 40,
        )


def test_ledger_symlink_cannot_redirect_append_outside_workspace(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    baseline_for(config, workspace)
    outside = workspace.parent / "outside-ledger.jsonl"
    outside.write_text("sentinel\n", encoding="utf-8")
    config.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    config.ledger_path.symlink_to(outside)

    with pytest.raises(AutoresearchError, match="inside workspace"):
        propose_experiment(config, **proposal_fields())

    assert outside.read_text(encoding="utf-8") == "sentinel\n"


def test_tampered_ledger_is_rejected(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    config = load_fixture_config(configured_workspace)
    baseline_for(config, workspace)
    propose_experiment(config, **proposal_fields())
    event = json.loads(config.ledger_path.read_text())
    event["hypothesis"] = "tampered"
    write_json(config.ledger_path, event)

    fields = proposal_fields()
    fields["experiment_id"] = "exp-002"
    with pytest.raises(AutoresearchError, match="ledger hash"):
        propose_experiment(config, **fields)

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.autoresearch import (
    AutoresearchError,
    create_baseline,
    decide_experiment,
    load_config,
    propose_experiment,
    validate_generation_outputs,
)
from omni_benchmark.run_manifest import RunManifest, read_bound_run_manifest

from .test_autoresearch_boundaries import (
    public_question,
    run_record,
    unscored_record,
    write_jsonl,
)


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    manifests = workspace / "data" / "manifests"
    manifests.mkdir(parents=True)
    (manifests / "train_ids.txt").write_text("dev_a_1\ndev_b_1\n", encoding="utf-8")
    (manifests / "dev_a_ids.txt").write_text("dev_a_1\n", encoding="utf-8")
    (manifests / "dev_b_ids.txt").write_text("dev_b_1\n", encoding="utf-8")
    (manifests / "test_ids.txt").write_text("test_1\n", encoding="utf-8")
    write_jsonl(
        manifests / "eligible_questions.jsonl",
        [
            public_question("dev_a_1"),
            public_question("dev_b_1"),
            public_question("test_1"),
        ],
    )
    for name in (
        "manifest_metadata.json",
        "split_metadata.json",
        "development_split_metadata.json",
    ):
        (manifests / name).write_text('{"fixture":true}\n', encoding="utf-8")
    config_path = workspace / "config" / "autoresearch.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
                "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
                "dev_b_max_evaluations": 2,
                "expected_dev_a_count": 1,
                "expected_dev_b_count": 1,
                "expected_train_count": 2,
                "forbidden_fields": ["gold_sql", "external_knowledge"],
                "guardian_public_key_sha256": "a" * 64,
                "ledger_path": "experiments/autoresearch/ledger.jsonl",
                "public_manifest_path": "data/manifests/eligible_questions.jsonl",
                "state_dir": "experiments/autoresearch/state",
                "test_ids_path": "data/manifests/test_ids.txt",
                "trace_policy": {"scaled_runs_require_run_manifest": True},
                "train_ids_path": "data/manifests/train_ids.txt",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return workspace, config_path


def _bundle(tmp_path: Path) -> tuple[object, Path, Path, str]:
    workspace, config_path = _workspace(tmp_path)
    config = load_config(config_path, workspace=workspace)
    generation_path = workspace / "runs" / "candidate" / "generation.jsonl"
    record = unscored_record("dev_a_1", partition="dev-a")
    record["attempt_id"] = "candidate:dev_a_1:C4:1"
    record["run_id"] = "candidate"
    write_jsonl(generation_path, [record])
    stored_path, stored_sha256 = _store_manifest(
        workspace,
        generation_path,
        [record],
        scope="dev-a",
        name="candidate",
    )
    return config, generation_path, stored_path, stored_sha256


def _store_manifest(
    workspace: Path,
    generation_path: Path,
    records: list[dict[str, object]],
    *,
    scope: str,
    name: str,
) -> tuple[Path, str]:
    generation_sha256 = hashlib.sha256(generation_path.read_bytes()).hexdigest()
    manifest = RunManifest.from_dict(
        {
            "budget_id": "standard-v1",
            "cli_versions": {"omni": "1.1.2"},
            "condition": "C4",
            "controllable_seed": None,
            "finished_at": max(str(record["finished_at"]) for record in records),
            "generation_sha256": generation_sha256,
            "git_commit": "e" * 40,
            "harness_config_sha256": "b" * 64,
            "instructions_sha256": "c" * 64,
            "model": "test-model",
            "model_config_id": "test-config",
            "prompt_sha256": "d" * 64,
            "provider": "test-provider",
            "repetition": 1,
            "schema_version": 2,
            "semantic_model_ref": "branch:test-model-v1",
            "semantic_model_sha256": None,
            "scope": scope,
            "software_versions": {"omni-benchmark": "0.1.0"},
            "started_at": min(str(record["started_at"]) for record in records),
        }
    )
    stored = ArtifactStore(workspace, Path(f"runs/{name}")).write_json(
        Path("run.json"), manifest.as_dict()
    )
    return stored.path, stored.sha256


def _create_required_baseline(config: object, workspace: Path) -> Path:
    records = [unscored_record("dev_a_1"), unscored_record("dev_b_1")]
    for record in records:
        record["run_id"] = "baseline"
        record["attempt_id"] = f"baseline:{record['instance_id']}:C4:1"
    generation_path = workspace / "runs" / "baseline-source" / "generation.jsonl"
    write_jsonl(generation_path, records)
    manifest_path, manifest_sha256 = _store_manifest(
        workspace,
        generation_path,
        records,
        scope="train",
        name="baseline-source",
    )
    return create_baseline(
        config,  # type: ignore[arg-type]
        run_path=generation_path,
        run_manifest_path=manifest_path,
        run_manifest_sha256=manifest_sha256,
        git_commit="e" * 40,
    )


def test_required_manifest_is_bound_to_generation(tmp_path: Path) -> None:
    config, generation_path, manifest_path, manifest_sha256 = _bundle(tmp_path)

    generation = validate_generation_outputs(
        config,
        generation_path,
        scope="dev-a",
        manifest_path=manifest_path,
        expected_manifest_sha256=manifest_sha256,
    )

    assert generation.run_manifest_path == manifest_path
    assert generation.run_manifest_sha256 == manifest_sha256


def test_dev_b_checkpoint_generation_accepts_bound_manifest(tmp_path: Path) -> None:
    workspace, _ = _workspace(tmp_path)
    generation_path = workspace / "runs" / "dev-b-candidate" / "generation.jsonl"
    record = unscored_record("dev_b_1", partition="dev-b")
    record["attempt_id"] = "checkpoint:dev_b_1:C4:1"
    record["run_id"] = "checkpoint"
    write_jsonl(generation_path, [record])
    manifest_path, manifest_sha256 = _store_manifest(
        workspace,
        generation_path,
        [record],
        scope="dev-b",
        name="dev-b-candidate",
    )

    manifest = read_bound_run_manifest(
        workspace,
        manifest_path.relative_to(workspace),
        expected_sha256=manifest_sha256,
        generation_sha256=hashlib.sha256(generation_path.read_bytes()).hexdigest(),
        condition="C4",
        scope="dev-b",
        repetition=1,
        provider=str(record["model"]["provider"]),  # type: ignore[index]
        model=str(record["model"]["name"]),  # type: ignore[index]
        started_at=str(record["started_at"]),
        finished_at=str(record["finished_at"]),
    )

    assert manifest.scope == "dev-b"


def test_required_manifest_cannot_be_omitted(tmp_path: Path) -> None:
    config, generation_path, _, _ = _bundle(tmp_path)

    with pytest.raises(AutoresearchError, match="run manifest path and hash"):
        validate_generation_outputs(config, generation_path, scope="dev-a")


def test_required_manifest_rejects_substitution(tmp_path: Path) -> None:
    config, generation_path, manifest_path, _ = _bundle(tmp_path)

    with pytest.raises(AutoresearchError, match="expected SHA-256"):
        validate_generation_outputs(
            config,
            generation_path,
            scope="dev-a",
            manifest_path=manifest_path,
            expected_manifest_sha256="f" * 64,
        )


def test_baseline_preserves_and_revalidates_run_manifest(tmp_path: Path) -> None:
    workspace, config_path = _workspace(tmp_path)
    config = load_config(config_path, workspace=workspace)

    baseline_path = _create_required_baseline(config, workspace)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    assert baseline["run"]["run_manifest_path"] == (
        "experiments/autoresearch/raw/baseline/run.json"
    )
    assert (
        baseline["run"]["run_manifest_sha256"]
        == hashlib.sha256(config.baseline_run_manifest_path.read_bytes()).hexdigest()
    )


def test_decision_evidence_preserves_before_and_after_manifest_binding(
    tmp_path: Path,
) -> None:
    workspace, config_path = _workspace(tmp_path)
    config = load_config(config_path, workspace=workspace)
    _create_required_baseline(config, workspace)
    propose_experiment(
        config,
        experiment_id="exp-manifest",
        parent="baseline",
        hypothesis="A reusable semantic dependency is missing.",
        intervention="Materialize every declared dependency edge.",
        affected_class="dependency",
        mechanism="Mechanical graph traversal.",
        predicted_direction="Increase correctness.",
        regression_risk="Cycles may be rejected.",
        subsystem="transformer",
        generality_rationale="Applies to every database.",
        condition="C4",
        content_provenance="public_hkb",
        intervention_provenance="generic_modeling_improvement",
        tuning_actor="human_agent_collaboration",
        tuning_effort="one controlled candidate",
        optimization_surface="structural",
        candidate_generation_method="trace_guided",
        generality_scope="cross_database_general",
    )
    records = [run_record("dev_a_1", outcome="correct")]
    records[0]["run_id"] = "candidate"
    records[0]["attempt_id"] = "candidate:dev_a_1:C4:1"
    generation_path = workspace / "runs" / "candidate" / "scored.jsonl"
    write_jsonl(generation_path, records)
    manifest_path, manifest_sha256 = _store_manifest(
        workspace,
        generation_path,
        records,
        scope="dev-a",
        name="candidate",
    )

    event = decide_experiment(
        config,
        experiment_id="exp-manifest",
        decision="INCONCLUSIVE",
        before_run_path=generation_path,
        before_run_manifest_path=manifest_path,
        before_run_manifest_sha256=manifest_sha256,
        after_run_path=generation_path,
        after_run_manifest_path=manifest_path,
        after_run_manifest_sha256=manifest_sha256,
        git_commit="e" * 40,
        rationale="No measurable change in this control comparison.",
        complexity_impact="none",
        production_relevance="control-plane verification",
        complexity_score=0,
        special_case_count=0,
        stability_rate=1,
        unexpected_observations="none",
        follow_up_hypotheses=(),
    )

    assert event["before_run"]["run_manifest_sha256"] == manifest_sha256
    assert event["after_run"]["run_manifest_sha256"] == manifest_sha256

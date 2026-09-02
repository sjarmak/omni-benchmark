"""Question, deployment, arm, and label readers over the synthetic artifact tree."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from omni_benchmark.telemetry_db import (
    CustodyViolation,
    ReaderError,
    read_arms,
    read_deployments,
    read_labels,
)
from omni_benchmark.telemetry_db.labels import append_label, build_label_record
from omni_benchmark.telemetry_db.loader import Sources

from .telemetry_db_helpers import (
    DEV_B_INSTANCE,
    QUESTIONS,
    SHA,
    SPLIT,
    TEST_INSTANCE,
    _dump_json,
    _label_fields,
    _release,
    build_tree,
)


@pytest.fixture
def sources(tmp_path: Path) -> Sources:
    return build_tree(tmp_path)


def test_read_questions_partitions_public_fields(sources: Sources) -> None:
    release = _release(sources)
    rows = {r.values["instance_id"]: r.values for r in release.batch.rows["question"]}
    assert set(rows) == {q[0] for q in QUESTIONS}
    assert rows["alpha_large_Q1"]["partition"] == "dev-a"
    assert rows["beta_large_Q3"]["partition"] == "dev-b"
    assert rows[TEST_INSTANCE]["partition"] == "test"
    assert rows["alpha_large_Q1"]["high_level"] is True
    assert rows["beta_large_Q2"]["high_level"] is False
    assert rows["beta_large_Q2"]["public_fields"]["conditions"] == {"decimal": 2}
    assert release.questions[DEV_B_INSTANCE].database == "beta_large"
    assert release.questions[DEV_B_INSTANCE].partition == "dev-b"
    assert "data/manifests/eligible_questions.jsonl" in release.batch.manifests
    assert "data/manifests/test_ids.txt" in release.batch.manifests


def test_read_questions_rejects_forbidden_and_unpartitioned(sources: Sources) -> None:
    path = sources.manifests_dir / "eligible_questions.jsonl"
    original = path.read_text(encoding="utf-8")
    path.write_text(
        original
        + json.dumps(
            {
                "instance_id": "x",
                "selected_database": "d",
                "query": "q",
                "sol_sql": "SELECT",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(CustodyViolation, match="sol_sql"):
        _release(sources)
    path.write_text(
        original
        + json.dumps({"instance_id": "x", "selected_database": "d", "query": "q"})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ReaderError, match="no partition"):
        _release(sources)
    path.write_text(original + "not json\n", encoding="utf-8")
    with pytest.raises(ReaderError, match="invalid JSON"):
        _release(sources)
    path.write_text(
        original.replace('"high_level": true', '"high_level": "true"'),
        encoding="utf-8",
    )
    with pytest.raises(ReaderError, match="high_level must be a boolean or null"):
        _release(sources)
    path.write_text(original + "[]\n", encoding="utf-8")
    with pytest.raises(ReaderError, match="not an object"):
        _release(sources)
    path.write_text(original + original.splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(ReaderError, match="duplicate instance_id"):
        _release(sources)
    (sources.manifests_dir / "dev_b_ids.txt").write_text(
        "alpha_large_Q1\n", encoding="utf-8"
    )
    with pytest.raises(ReaderError, match="more than one partition"):
        _release(sources)
    (sources.manifests_dir / "dev_b_ids.txt").unlink()
    with pytest.raises(FileNotFoundError):
        _release(sources)


def test_read_deployments(sources: Sources) -> None:
    batch = read_deployments(sources.deployments_dir, repo_root=sources.repo_root)
    rows = [r.values for r in batch.rows["deployment"]]
    assert len(rows) == 1
    assert rows[0]["deployment_id"] == "dep-v1" and rows[0]["file_sha256"] == {
        "topic.yaml": SHA
    }
    assert rows[0]["branch_name"] == "livesqlbench-alpha" and rows[0]["file_count"] == 3
    assert dict(batch.dropped) == {
        "deployment_claimed_database_without_record": 1,
        "deployment_directory_skipped:public-omni-validator-diagnostic-claim": 1,
        "deployments_entry_not_a_directory": 1,
    }
    assert "experiments/deployments/dep-v1/dep-v1.claim" in batch.manifests


def test_read_deployments_rejects_malformed_directories(sources: Sources) -> None:
    record_path = sources.deployments_dir / "dep-v1" / "dep-v1.alpha_large.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    _dump_json(record_path, {**record, "database": "gamma_large"})
    with pytest.raises(ReaderError, match="claim does not"):
        read_deployments(sources.deployments_dir, repo_root=sources.repo_root)
    _dump_json(record_path, {**record, "run_id": "other"})
    with pytest.raises(ReaderError, match="run_id disagrees"):
        read_deployments(sources.deployments_dir, repo_root=sources.repo_root)
    _dump_json(record_path, {**record, "file_count": "3"})
    with pytest.raises(ReaderError, match="file_count"):
        read_deployments(sources.deployments_dir, repo_root=sources.repo_root)
    _dump_json(record_path, {**record, "branch_id": 7})
    with pytest.raises(ReaderError, match="branch_id must be text"):
        read_deployments(sources.deployments_dir, repo_root=sources.repo_root)
    _dump_json(record_path, {**record, "database": ""})
    with pytest.raises(ReaderError, match="database must be"):
        read_deployments(sources.deployments_dir, repo_root=sources.repo_root)
    _dump_json(record_path, record)
    _dump_json(sources.deployments_dir / "dep-v1" / "extra.claim", {})
    with pytest.raises(ReaderError, match="exactly one .claim"):
        read_deployments(sources.deployments_dir, repo_root=sources.repo_root)


def test_read_arms_validates_entries(tmp_path: Path) -> None:
    path = tmp_path / "arms.json"
    _dump_json(
        path, {"schema_version": 1, "runs": {"r": {"arm": None, "canonical": True}}}
    )
    mapping = read_arms(path)
    assert mapping.arm_for("r", "C2") == "C2" and mapping.canonical("r") is True
    assert (
        mapping.arm_for("other", "C1") == "C1" and mapping.canonical("other") is False
    )
    for runs, match in (
        ({"r": {"arm": "", "canonical": True}}, "non-empty string"),
        ({"r": {"arm": "C5", "canonical": "yes"}}, "boolean"),
        ({"r": {"arm": "C5"}}, "exactly keys"),
        ([], "keyed by run_id"),
    ):
        _dump_json(path, {"schema_version": 1, "runs": runs})
        with pytest.raises(ReaderError, match=match):
            read_arms(path)
    _dump_json(path, {"schema_version": 2, "runs": {}})
    with pytest.raises(ReaderError, match="schema_version"):
        read_arms(path)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ReaderError, match="expected a JSON object"):
        read_arms(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ReaderError, match="cannot parse"):
        read_arms(path)


def _labels(sources: Sources, attempt_keys: frozenset[tuple[str, str]]):
    return read_labels(
        sources.labels_dir,
        repo_root=sources.repo_root,
        split=SPLIT,
        attempt_keys=attempt_keys,
    )


def test_read_labels_parses_created_at_and_drops_unloaded_attempts(
    sources: Sources,
) -> None:
    labels_dir = sources.labels_dir
    attempt_id = "direct-run:alpha_large_Q1:C1:1"
    assert _labels(sources, frozenset()).count("attempt_label") == 0
    record = append_label(labels_dir, "pass-1", _label_fields(attempt_id), split=SPLIT)
    orphan = append_label(
        labels_dir, "pass-1", _label_fields(attempt_id, "1" * 64), split=SPLIT
    )
    assert orphan.label_id != record.label_id
    batch = _labels(sources, frozenset({(attempt_id, SHA)}))
    (row,) = batch.rows["attempt_label"]
    assert row.values["label_id"] == record.label_id
    assert row.values["created_at"] == datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    assert dict(batch.dropped) == {"label_attempt_not_loaded": 1}
    assert "experiments/labels/pass-1.jsonl" in batch.manifests


@pytest.mark.parametrize(
    ("instance", "match"),
    [(TEST_INSTANCE, "sealed test split"), (DEV_B_INSTANCE, "not in the dev-A split")],
)
def test_read_labels_refuses_instances_outside_dev_a(
    sources: Sources, instance: str, match: str
) -> None:
    attempt_id = f"direct-run:{instance}:C1:1"
    with pytest.raises(CustodyViolation, match=match):
        append_label(
            sources.labels_dir, "pass-1", _label_fields(attempt_id), split=SPLIT
        )
    assert not (sources.labels_dir / "pass-1.jsonl").exists()
    record = build_label_record(_label_fields(attempt_id), "pass-1")
    (sources.labels_dir / "pass-1.jsonl").write_text(record.to_line(), encoding="utf-8")
    with pytest.raises(CustodyViolation, match=match):
        _labels(sources, frozenset({(attempt_id, SHA)}))

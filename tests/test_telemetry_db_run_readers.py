"""Dev-A and sealed cohort readers over the synthetic artifact tree."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.telemetry_db import (
    CustodyViolation,
    ReaderError,
    load_split_ids,
    read_arms,
    read_dev_a,
    read_sealed,
)
from omni_benchmark.telemetry_db.loader import Sources
from omni_benchmark.telemetry_db.run_readers import time_span

from .telemetry_db_helpers import (
    DEV_B_INSTANCE,
    SEALED_NAME,
    SHA,
    TEST_INSTANCE,
    _dump_json,
    _dump_jsonl,
    _release,
    aggregate,
    build_tree,
    generation_record,
    run_json,
    score_artifact,
    score_entry,
    trace_events,
    write_attempt_dir,
)


@pytest.fixture
def sources(tmp_path: Path) -> Sources:
    return build_tree(tmp_path)


def _dev_a(sources: Sources):
    release = _release(sources)
    return read_dev_a(
        sources.raw_dir,
        repo_root=sources.repo_root,
        arms=read_arms(sources.arms_path),
        split=load_split_ids(sources.manifests_dir),
        questions=release.questions,
    )


def _attempts(sources: Sources) -> dict[str, dict[str, Any]]:
    return {r.values["attempt_id"]: r.values for r in _dev_a(sources).rows["attempt"]}


def test_read_dev_a_attempt_rows_carry_the_generation_fields(sources: Sources) -> None:
    attempts = _attempts(sources)
    assert len(attempts) == 5
    c5 = attempts["c5-run:alpha_large_Q1:C4:1"]
    assert (c5["condition"], c5["arm"], c5["database"]) == ("C4", "C5", "alpha_large")
    assert attempts["c4-run:alpha_large_Q1:C4:1"]["arm"] == "C4"
    assert attempts["unmapped-run:beta_large_Q2:C3:1"]["arm"] == "C3"
    direct = attempts["direct-run:alpha_large_Q1:C1:1"]
    assert direct["latency_ms"] == 5000.4
    assert direct["partition"] == "dev-a"
    assert direct["cost_usd"] == Decimal("0.0123")
    assert direct["started_at"] == datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
    assert (
        direct["artifact_dir"]
        == "experiments/autoresearch/raw/direct-run/alpha_large/C1/alpha_large_Q1-r1"
    )
    assert direct["generation_record"]["question"] == "How many rows?"
    assert attempts["direct-run:beta_large_Q2:C2:1"]["execution_status"] is None


def test_read_dev_a_score_rows_join_both_scorers(sources: Sources) -> None:
    batch = _dev_a(sources)
    scores = {
        (r.values["attempt_id"], r.values["scorer"]): r.values
        for r in batch.rows["score"]
    }
    assert len(scores) == 5
    assert (
        scores[("direct-run:alpha_large_Q1:C1:1", "official_soft_ex")]["outcome"]
        == "correct"
    )
    assert (
        scores[("direct-run:alpha_large_Q1:C1:1", "sensitivity")]["outcome"]
        == "wrong_answer"
    )
    unscorable = scores[("direct-run:beta_large_Q2:C2:1", "official_soft_ex")]
    assert (
        unscorable["outcome"],
        unscorable["status"],
        unscorable["failure_category"],
    ) == (None, "unscorable", "no_result")
    assert (
        scores[("c5-run:alpha_large_Q1:C4:1", "official_soft_ex")]["scorer_version"]
        == "official_soft_ex-v1"
    )


def test_read_dev_a_joins_a_score_entry_for_an_opaque_attempt_id(
    sources: Sources,
) -> None:
    attempt_id = "r2attempt-0123456789abcdef01234567"
    record = generation_record(
        "opaque-run", "alpha_large_Q1", "C1", attempt_id=attempt_id
    )
    sha = write_attempt_dir(
        sources.raw_dir / "opaque-run" / "alpha_large" / "C1" / "alpha_large_Q1-r1",
        record,
        run_json=run_json("C1"),
        trace=trace_events(1),
    )
    _dump_json(
        sources.raw_dir / "opaque-run-scores-v1" / "official.score.json",
        score_artifact("official_soft_ex", [score_entry(attempt_id, sha)]),
    )
    batch = _dev_a(sources)
    attempt = {r.values["attempt_id"]: r.values for r in batch.rows["attempt"]}
    assert attempt[attempt_id]["instance_id"] == "alpha_large_Q1"
    scores = {
        (r.values["attempt_id"], r.values["scorer"]): r.values
        for r in batch.rows["score"]
    }
    assert scores[(attempt_id, "official_soft_ex")]["outcome"] == "correct"


def test_read_dev_a_reads_a_score_directory_without_a_version_suffix(
    sources: Sources,
) -> None:
    attempt = _attempts(sources)["c4-run:alpha_large_Q1:C4:1"]
    reason = "run_directory_without_generation_records"
    before = _dev_a(sources).dropped.get(reason, 0)
    _dump_json(
        sources.raw_dir / "later-run-scores" / "sensitivity.score.json",
        score_artifact(
            "sensitivity",
            [
                score_entry(
                    attempt["attempt_id"],
                    attempt["generation_record_sha256"],
                    "wrong_answer",
                )
            ],
        ),
    )
    batch = _dev_a(sources)
    scores = {
        (r.values["attempt_id"], r.values["scorer"]): r.values
        for r in batch.rows["score"]
    }
    assert scores[("c4-run:alpha_large_Q1:C4:1", "sensitivity")]["outcome"] == (
        "wrong_answer"
    )
    assert batch.dropped.get(reason, 0) == before


def test_read_dev_a_trace_and_action_evidence_rows(sources: Sources) -> None:
    batch = _dev_a(sources)
    traces = [r.values for r in batch.rows["trace_event"]]
    assert len(traces) == 5
    first = next(
        t
        for t in traces
        if t["attempt_id"] == "direct-run:alpha_large_Q1:C1:1" and t["seq"] == 1
    )
    assert first["duration_ms"] == 25.2 and first["tool_name"] == "sql_probe"
    assert first["timestamp"] == datetime(2026, 8, 30, 10, 0, 1, tzinfo=timezone.utc)
    actions = [r.values for r in batch.rows["action_evidence"]]
    assert len(actions) == 1 and actions[0]["retrieved_public_ids"] == ["alpha.t1"]


def test_read_dev_a_run_rows_record_manifests_and_ambiguity(sources: Sources) -> None:
    batch = _dev_a(sources)
    runs = {r.values["run_id"]: r.values for r in batch.rows["run"]}
    assert set(runs) == {"direct-run", "c4-run", "c5-run", "unmapped-run"}
    assert (
        runs["c5-run"]["arm"] == "C5"
        and runs["c5-run"]["manifest"]["arm"]["canonical"] is True
    )
    assert runs["c5-run"]["semantic_model_ref"] == "deployment:c5-run"
    assert runs["c5-run"]["system_commit"] == "a" * 40
    assert runs["direct-run"]["condition"] is None
    assert runs["direct-run"]["manifest"]["ambiguous_fields"]["condition"] == [
        "C1",
        "C2",
    ]
    assert runs["direct-run"]["question_count"] == 2
    assert runs["direct-run"]["partition"] == "dev-a"
    assert runs["direct-run"]["finished_at"] == datetime(
        2026, 8, 30, 10, 0, 5, tzinfo=timezone.utc
    )
    assert runs["unmapped-run"]["scope"] is None
    assert runs["unmapped-run"]["manifest"]["attempts_without_run_json"] == 1


def test_read_dev_a_dropped_tallies_and_arm_notes(sources: Sources) -> None:
    batch = _dev_a(sources)
    assert dict(batch.dropped) == {
        "attempt_directory_without_run_json": 1,
        "duplicate_identical_score_entry": 1,
        "failure_only_attempt_directory": 1,
        "raw_entry_not_a_run_directory": 1,
        "run_directory_without_generation_records": 1,
        "trace_not_captured": 1,
    }
    assert batch.notes["arms"]["c5-run"] == {
        "arms": ["C5"],
        "canonical": True,
        "mapped": True,
        "attempts": 1,
        "directories": ["c5-run"],
    }
    assert batch.notes["arms"]["unmapped-run"]["canonical"] is False
    assert (
        "experiments/autoresearch/raw/c4-run-scores-v2/official.score.json"
        in batch.manifests
    )


def test_read_dev_a_score_conflict_raises(sources: Sources) -> None:
    path = sources.raw_dir / "c4-run-scores-v2" / "official.score.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["attempts"][2]["outcome"] = "wrong_answer"
    _dump_json(path, artifact)
    with pytest.raises(ReaderError, match="conflicts"):
        _dev_a(sources)


@pytest.mark.parametrize(
    ("entry", "error", "match"),
    [
        (
            {
                "attempt_id": f"direct-run:{TEST_INSTANCE}:C1:1",
                "generation_record_sha256": SHA,
                "status": "scored",
            },
            CustodyViolation,
            "sealed test split",
        ),
        (
            {
                "attempt_id": f"direct-run:{DEV_B_INSTANCE}:C1:1",
                "generation_record_sha256": SHA,
                "status": "scored",
            },
            CustodyViolation,
            "not in the dev-A split",
        ),
        (
            {
                "attempt_id": "direct-run:alpha_large_Q1:C1:2",
                "generation_record_sha256": SHA,
                "status": "scored",
            },
            ReaderError,
            "no generation record",
        ),
        (
            {"attempt_id": "bad:id", "generation_record_sha256": SHA},
            ReaderError,
            "malformed",
        ),
        (
            {"attempt_id": 3, "generation_record_sha256": SHA},
            ReaderError,
            "must be text",
        ),
        ("not an object", ReaderError, "expected an object"),
    ],
)
def test_read_dev_a_rejects_bad_score_entries(
    sources: Sources, entry: Any, error: type[Exception], match: str
) -> None:
    path = sources.raw_dir / "direct-run-scores-v1" / "sensitivity.score.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["attempts"].append(entry)
    _dump_json(path, artifact)
    with pytest.raises(error, match=match):
        _dev_a(sources)


def test_read_dev_a_score_attempt_id_must_match_record(sources: Sources) -> None:
    path = sources.raw_dir / "direct-run-scores-v1" / "sensitivity.score.json"
    artifact = json.loads(path.read_text(encoding="utf-8"))
    artifact["attempts"][0]["attempt_id"] = "direct-run:alpha_large_Q1:C1:2"
    _dump_json(path, artifact)
    with pytest.raises(ReaderError, match="does not match"):
        _dev_a(sources)
    _dump_json(path, {"scorer": {}, "attempts": []})
    with pytest.raises(ReaderError, match="scorer.identity"):
        _dev_a(sources)
    _dump_json(path, {"scorer": {"identity": "sensitivity"}, "attempts": {}})
    with pytest.raises(ReaderError, match="attempts must be a list"):
        _dev_a(sources)


def test_read_dev_a_missing_or_altered_trace_raises(sources: Sources) -> None:
    trace = (
        sources.raw_dir
        / "c4-run"
        / "alpha_large"
        / "C4"
        / "alpha_large_Q1-r1"
        / "attempt.trace.jsonl"
    )
    trace.write_text(trace.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ReaderError, match="sha256 differs"):
        _dev_a(sources)
    trace.unlink()
    with pytest.raises(ReaderError, match="trace_captured but"):
        _dev_a(sources)


def test_read_dev_a_counts_duplicate_records_and_unknown_instances(
    sources: Sources,
) -> None:
    source = sources.raw_dir / "c4-run" / "alpha_large" / "C4" / "alpha_large_Q1-r1"
    copy = sources.raw_dir / "c4-run-copy" / "alpha_large" / "C4" / "alpha_large_Q1-r1"
    copy.mkdir(parents=True)
    for name in ("generation.jsonl", "attempt.trace.jsonl", "run.json"):
        (copy / name).write_bytes((source / name).read_bytes())
    stranger = generation_record("stranger-run", "gamma_large_Q9", "C1")
    write_attempt_dir(
        sources.raw_dir / "stranger-run" / "gamma_large" / "C1" / "gamma_large_Q9-r1",
        stranger,
        trace=trace_events(1),
    )
    dev_a_ids = sources.manifests_dir / "dev_a_ids.txt"
    dev_a_ids.write_text(
        dev_a_ids.read_text(encoding="utf-8") + "gamma_large_Q9\n", encoding="utf-8"
    )
    batch = _dev_a(sources)
    assert batch.dropped["duplicate_generation_record"] == 1
    assert batch.dropped["attempt_instance_absent_from_question_release"] == 1
    assert not any(r.values["run_id"] == "stranger-run" for r in batch.rows["attempt"])
    assert "stranger-run" not in {r.values["run_id"] for r in batch.rows["run"]}
    assert batch.notes["arms"]["c4-run"]["directories"] == ["c4-run"]


def test_read_dev_a_never_emits_attempts_outside_dev_a(sources: Sources) -> None:
    """A dev-B record beside dev-A records leaves no row in any table."""
    dev_b = generation_record("direct-run", DEV_B_INSTANCE, "C1")
    write_attempt_dir(
        sources.raw_dir / "direct-run" / "beta_large" / "C1" / f"{DEV_B_INSTANCE}-r1",
        dev_b,
        run_json=run_json("C1"),
        trace=trace_events(1),
        actions=[{"trace_seq": 0, "tool_name": "sql_probe"}],
    )
    sealed = generation_record("direct-run", TEST_INSTANCE, "C1", partition="test")
    write_attempt_dir(
        sources.raw_dir / "direct-run" / "alpha_large" / "C1" / f"{TEST_INSTANCE}-r1",
        sealed,
        run_json=run_json("C1"),
        trace=trace_events(1),
    )
    batch = _dev_a(sources)
    assert batch.dropped["attempt_instance_not_dev_a"] == 2
    for table in ("attempt", "trace_event", "action_evidence", "score"):
        assert not any(
            DEV_B_INSTANCE in r.values["attempt_id"]
            or TEST_INSTANCE in r.values["attempt_id"]
            for r in batch.rows[table]
        )
    direct = next(r for r in batch.rows["run"] if r.values["run_id"] == "direct-run")
    assert direct.values["question_count"] == 2
    assert batch.notes["arms"]["direct-run"]["attempts"] == 2


def test_read_dev_a_run_without_finish_timestamps(sources: Sources) -> None:
    path = (
        sources.raw_dir
        / "unmapped-run"
        / "beta_large"
        / "C3"
        / "beta_large_Q2-r1"
        / "generation.jsonl"
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    _dump_jsonl(path, [{**record, "finished_at": None}])
    batch = _dev_a(sources)
    run = next(r for r in batch.rows["run"] if r.values["run_id"] == "unmapped-run")
    assert run.values["finished_at"] is None
    assert run.values["started_at"] == datetime(2026, 8, 30, 10, tzinfo=timezone.utc)
    assert time_span([], "c") == (None, None)
    assert time_span([{"started_at": None, "finished_at": None}], "c") == (None, None)


def _sealed(sources: Sources):
    release = _release(sources)
    return read_sealed(
        sources.sealed_dir, repo_root=sources.repo_root, questions=release.questions
    )


def test_read_sealed_attempt_rows_without_per_attempt_scores(sources: Sources) -> None:
    batch = _sealed(sources)
    assert "score" not in batch.rows
    attempts = {r.values["attempt_id"]: r.values for r in batch.rows["attempt"]}
    assert set(attempts) == {
        f"sealed:{TEST_INSTANCE}:C1:1",
        f"sealed:{TEST_INSTANCE}:C4:1",
    }
    c1 = attempts[f"sealed:{TEST_INSTANCE}:C1:1"]
    assert (c1["run_id"], c1["partition"], c1["arm"], c1["database"]) == (
        "sealed-c1-r1",
        "test",
        "C1",
        "alpha_large",
    )
    assert c1["artifact_dir"] == (
        f"runs/preserved/{SEALED_NAME}/captures/alpha_large/C1/{TEST_INSTANCE}-r1"
        "/capture-1"
    )
    assert (sources.repo_root / c1["artifact_dir"] / "attempt.trace.jsonl").is_file()


def test_read_sealed_trace_and_action_evidence_rows(sources: Sources) -> None:
    batch = _sealed(sources)
    assert len(batch.rows["trace_event"]) == 4
    assert len(batch.rows["action_evidence"]) == 1


def test_read_sealed_run_rows_carry_the_cohort_manifest(sources: Sources) -> None:
    batch = _sealed(sources)
    runs = {r.values["cohort_id"]: r.values for r in batch.rows["run"]}
    assert runs["c4-r1"]["run_id"] == "sealed-c4-r1"
    assert runs["c4-r1"]["partition"] == "test"
    assert runs["c4-r1"]["model_version"] == "v9"
    assert runs["c4-r1"]["system_commit"] == "c" * 40
    assert runs["c4-r1"]["started_at"] == datetime(2026, 8, 31, tzinfo=timezone.utc)
    assert runs["c4-r1"]["manifest"]["run_json"]["kind"] == "sealed-run-manifest"


def test_read_sealed_aggregate_rows(sources: Sources) -> None:
    batch = _sealed(sources)
    aggregates = {
        (r.values["scorer"], r.values["condition"]): r.values
        for r in batch.rows["sealed_aggregate"]
    }
    assert set(aggregates) == {
        ("official_soft_ex", "C1"),
        ("official_soft_ex", "C4"),
        ("sensitivity", "C1"),
        ("sensitivity", "C4"),
    }
    official_c4 = aggregates[("official_soft_ex", "C4")]
    assert (
        official_c4["run_id"],
        official_c4["correct"],
        official_c4["scoreable_attempts"],
    ) == (SEALED_NAME, 4, 6)
    assert official_c4["mean_accuracy"] == Decimal("0.5")
    assert official_c4["report"]["scorer"]["identity"] == "official_soft_ex"


def test_read_sealed_dropped_tallies_and_manifests(sources: Sources) -> None:
    batch = _sealed(sources)
    assert dict(batch.dropped) == {"score_entry_not_a_scorer_directory": 1}
    assert (
        f"runs/preserved/{SEALED_NAME}/score/sensitivity/aggregate.json"
        in batch.manifests
    )
    assert f"runs/preserved/{SEALED_NAME}/cohorts/c1-r1/run.json" in batch.manifests
    assert (
        (sources.sealed_dir / "score" / "sensitivity" / "c1-r1.score.json")
        .read_bytes()
        .startswith(b"\xff")
    )


def test_read_sealed_drops_instances_absent_from_the_release(sources: Sources) -> None:
    generation = sources.sealed_dir / "cohorts" / "c1-r1" / "generation.jsonl"
    record = json.loads(generation.read_text(encoding="utf-8"))
    stranger = {
        **record,
        "attempt_id": "sealed:gamma_large_Q9:C1:1",
        "instance_id": "gamma_large_Q9",
    }
    _dump_jsonl(generation, [record, stranger])
    manifest_path = sources.sealed_dir / "cohorts" / "c1-r1" / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _dump_json(manifest_path, {**manifest, "question_count": 2})
    batch = _sealed(sources)
    assert batch.dropped["attempt_instance_absent_from_question_release"] == 1
    assert "sealed:gamma_large_Q9:C1:1" not in {
        r.values["attempt_id"] for r in batch.rows["attempt"]
    }


def test_read_sealed_rejects_inconsistent_cohorts(sources: Sources) -> None:
    manifest_path = sources.sealed_dir / "cohorts" / "c1-r1" / "run.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _dump_json(manifest_path, {**manifest, "question_count": 2})
    with pytest.raises(ReaderError, match="question_count"):
        _sealed(sources)
    _dump_json(manifest_path, {**manifest, "condition": "C2"})
    with pytest.raises(ReaderError, match="condition disagrees"):
        _sealed(sources)
    _dump_json(manifest_path, {**manifest, "kind": "other"})
    with pytest.raises(ReaderError, match="kind is not"):
        _sealed(sources)
    _dump_json(manifest_path, manifest)
    generation = sources.sealed_dir / "cohorts" / "c1-r1" / "generation.jsonl"
    record = json.loads(generation.read_text(encoding="utf-8"))
    _dump_jsonl(generation, [record, {**record, "run_id": "other"}])
    with pytest.raises(ReaderError, match="several run_ids"):
        _sealed(sources)
    _dump_jsonl(generation, [{**record, "trace_path": "elsewhere/attempt.trace.jsonl"}])
    with pytest.raises(ReaderError, match="captures/"):
        _sealed(sources)
    _dump_jsonl(generation, [{**record, "trace_path": None}])
    with pytest.raises(ReaderError, match="trace_path must be text"):
        _sealed(sources)
    generation.write_text("", encoding="utf-8")
    with pytest.raises(ReaderError, match="no generation records"):
        _sealed(sources)


def test_read_sealed_rejects_bad_aggregates_and_layout(sources: Sources) -> None:
    path = sources.sealed_dir / "score" / "sensitivity" / "aggregate.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["report"]["conditions"]["C1"]["pass_3_rate"]
    _dump_json(path, payload)
    with pytest.raises(ReaderError, match="missing"):
        _sealed(sources)
    payload["report"]["conditions"]["C1"] = []
    _dump_json(path, payload)
    with pytest.raises(ReaderError, match="expected an object"):
        _sealed(sources)
    payload["report"] = {}
    _dump_json(path, payload)
    with pytest.raises(ReaderError, match="report.conditions"):
        _sealed(sources)
    _dump_json(path, {**aggregate("sensitivity"), "kind": "x"})
    with pytest.raises(ReaderError, match="kind is not"):
        _sealed(sources)
    (sources.sealed_dir / "cohorts" / "note.txt").write_text("x", encoding="utf-8")
    _dump_json(path, aggregate("sensitivity"))
    assert _sealed(sources).dropped["cohorts_entry_not_a_directory"] == 1
    import shutil

    shutil.rmtree(sources.sealed_dir / "score")
    with pytest.raises(ReaderError, match="score directory is absent"):
        _sealed(sources)
    shutil.rmtree(sources.sealed_dir / "cohorts")
    with pytest.raises(ReaderError, match="cohorts directory is absent"):
        _sealed(sources)

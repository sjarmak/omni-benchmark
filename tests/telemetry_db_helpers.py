"""Synthetic artifact tree that mirrors the committed layout, shared by the reader tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from omni_benchmark.telemetry_db import SplitIds, read_questions
from omni_benchmark.telemetry_db.loader import Sources
from omni_benchmark.telemetry_db.sealed_readers import SEALED_RUN_ID
from omni_benchmark.telemetry_db.taxonomy import TAXONOMY_VERSION

TEST_INSTANCE = "alpha_large_T1"
DEV_B_INSTANCE = "beta_large_Q3"
SEALED_NAME = SEALED_RUN_ID
QUESTIONS = (
    ("alpha_large_Q1", "alpha_large", "dev-a"),
    ("beta_large_Q2", "beta_large", "dev-a"),
    (DEV_B_INSTANCE, "beta_large", "dev-b"),
    (TEST_INSTANCE, "alpha_large", "test"),
)
SHA = "0" * 64
SPLIT = SplitIds(
    dev_a=frozenset({"alpha_large_Q1", "beta_large_Q2"}),
    test=frozenset({TEST_INSTANCE}),
)


def _dump_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8"
    )


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def trace_events(count: int) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "trace-event-v2",
            "seq": seq,
            "timestamp": f"2026-08-30T10:00:0{seq}Z",
            "component": "agent",
            "event_type": "tool_call" if seq else "model_turn",
            "tool_name": "sql_probe" if seq else None,
            "status": "ok",
            "failure_class": None,
            "duration_ms": 12.6 * (seq + 1),
            "elapsed_ms": 100.0,
            "input_tokens": 10 + seq,
            "output_tokens": 3,
            "model": "claude",
            "provider": "anthropic",
            "retry_delta": 0,
            "tool_call_delta": 1 if seq else 0,
            "database_query_delta": 1 if seq else 0,
            "validation_attempt_delta": 0,
            "metadata_sha256": SHA,
        }
        for seq in range(count)
    ]


#: Every generation-record field that does not depend on a call argument.
GENERATION_BASE: dict[str, Any] = {
    "question": "How many rows?",
    "started_at": "2026-08-30T10:00:00Z",
    "finished_at": "2026-08-30T10:00:05Z",
    "latency_ms": 5000.4,
    "model": {"name": "claude", "provider": "anthropic", "version": "v9"},
    "token_usage": {"input_tokens": 120, "output_tokens": 40, "total_tokens": 160},
    "token_source": "provider_reported",
    "cost_usd": 0.0123,
    "cost_source": "derived",
    "cost_unavailable_reason": None,
    "generation_outcome": "answered",
    "execution_status": "ok",
    "failure_origin": None,
    "terminal_failure_class": None,
    "harness_failure": None,
    "generated_sql": "SELECT 1",
    "generated_query": None,
    "query_unavailable_reason": None,
    "tool_call_count": 1,
    "tool_calls_by_name": [{"count": 1, "name": "sql_probe"}],
    "database_query_count": 1,
    "retry_count": 0,
    "validation_attempt_count": 1,
    "actual_result_status": "captured",
    "actual_result_hash": SHA,
    "trace_truncated": False,
    "trace_degraded_reason": None,
    "trace_schema_version": "trace-event-v2",
    "telemetry_unavailable": [],
}


def generation_record(
    run_id: str,
    instance: str,
    condition: str,
    repetition: int = 1,
    *,
    attempt_prefix: str | None = None,
    partition: str = "train",
    trace_sha256: str | None = None,
    trace_captured: bool = True,
    **overrides: Any,
) -> dict[str, Any]:
    prefix = attempt_prefix or run_id
    return {
        **GENERATION_BASE,
        "attempt_id": f"{prefix}:{instance}:{condition}:{repetition}",
        "run_id": run_id,
        "instance_id": instance,
        "condition": condition,
        "repetition": repetition,
        "partition": partition,
        "trace_captured": trace_captured,
        "trace_sha256": trace_sha256,
        **overrides,
    }


def write_attempt_dir(
    directory: Path,
    record: dict[str, Any],
    *,
    run_json: dict[str, Any] | None = None,
    trace: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
) -> str:
    """Write one attempt directory; returns the generation record sha256."""
    directory.mkdir(parents=True, exist_ok=True)
    if trace is not None:
        trace_path = directory / "attempt.trace.jsonl"
        _dump_jsonl(trace_path, trace)
        record = {
            **record,
            "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        }
    if actions is not None:
        _dump_json(
            directory / "attempt.action-evidence.json",
            {"kind": "direct-action-evidence", "records": actions},
        )
    if run_json is not None:
        _dump_json(directory / "run.json", run_json)
    line = json.dumps(record, sort_keys=True) + "\n"
    (directory / "generation.jsonl").write_bytes(line.encode("utf-8"))
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def run_json(condition: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "condition": condition,
        "git_commit": "a" * 40,
        "scope": "dev-a",
        "semantic_model_ref": "deployment:dep-v1",
        "semantic_model_sha256": "b" * 64,
        "model": "claude",
        "provider": "anthropic",
        "schema_version": 2,
    }
    return {**base, **overrides}


def score_artifact(identity: str, entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "dev-a-frozen-baseline-score-v2",
        "scorer": {"identity": identity, "version": f"{identity}-v1"},
        "attempts": entries,
    }


def score_entry(
    attempt_id: str, sha: str, outcome: str | None = "correct"
) -> dict[str, Any]:
    entry = {
        "attempt_id": attempt_id,
        "generation_record_sha256": sha,
        "status": "scored",
    }
    if outcome is None:
        return {**entry, "status": "unscorable", "failure_category": "no_result"}
    return {**entry, "outcome": outcome}


def aggregate(identity: str) -> dict[str, Any]:
    block = {
        "correct": 3,
        "wrong_answer": 2,
        "refused_or_error": 1,
        "mean_accuracy": 0.5,
        "pass_3_rate": 0.25,
        "wrong_rate": 0.3333,
        "refused_or_error_rate": 0.1667,
        "error_rate": 0.1667,
        "correctness_flip_rate": 0.5,
        "scoreable_attempts": 6,
    }
    return {
        "kind": "sealed-aggregate-result",
        "schema_version": 1,
        "report": {
            "scorer": {"identity": identity, "version": f"{identity}-v1"},
            "question_count": 2,
            "conditions": {"C1": block, "C4": {**block, "correct": 4}},
        },
    }


def build_manifests(root: Path) -> None:
    manifests = root / "data" / "manifests"
    manifests.mkdir(parents=True)
    _dump_jsonl(
        manifests / "eligible_questions.jsonl",
        [
            {
                "instance_id": instance,
                "selected_database": database,
                "query": f"Question for {instance}",
                "category": "Query",
                "high_level": instance.endswith("Q1"),
                "conditions": {"decimal": 2},
            }
            for instance, database, _ in QUESTIONS
        ],
    )
    for partition, filename in (
        ("dev-a", "dev_a_ids.txt"),
        ("dev-b", "dev_b_ids.txt"),
        ("test", "test_ids.txt"),
    ):
        ids = [instance for instance, _, part in QUESTIONS if part == partition]
        (manifests / filename).write_text(
            "".join(f"{i}\n" for i in ids), encoding="utf-8"
        )


def build_arms(root: Path) -> None:
    _dump_json(
        root / "config" / "telemetry_db" / "arms.json",
        {
            "schema_version": 1,
            "runs": {
                "direct-run": {"arm": None, "canonical": True},
                "c5-run": {"arm": "C5", "canonical": True},
            },
        },
    )


def _write_direct_run(raw: Path) -> dict[str, str]:
    """The two-condition ``direct-run``: one traced attempt and one untraced."""
    shas: dict[str, str] = {}
    direct = generation_record("direct-run", "alpha_large_Q1", "C1")
    shas[direct["attempt_id"]] = write_attempt_dir(
        raw / "direct-run" / "alpha_large" / "C1" / "alpha_large_Q1-r1",
        direct,
        run_json=run_json("C1"),
        trace=trace_events(2),
        actions=[
            {
                "trace_seq": 1,
                "tool_name": "sql_probe",
                "retrieval_query": None,
                "retrieved_public_ids": ["alpha.t1"],
                "exploratory_sql": "SELECT 1",
            }
        ],
    )
    untraced = generation_record(
        "direct-run",
        "beta_large_Q2",
        "C2",
        trace_captured=False,
        generation_outcome="error",
    )
    del untraced["execution_status"]
    shas[untraced["attempt_id"]] = write_attempt_dir(
        raw / "direct-run" / "beta_large" / "C2" / "beta_large_Q2-r1",
        untraced,
        run_json=run_json("C2"),
    )
    return shas


def _write_c4_c5_runs(raw: Path) -> dict[str, str]:
    """The C4 pair whose arm is only distinguishable through ``arms.json``."""
    shas: dict[str, str] = {}
    for run_id in ("c4-run", "c5-run"):
        record = generation_record(run_id, "alpha_large_Q1", "C4", generated_sql=None)
        shas[record["attempt_id"]] = write_attempt_dir(
            raw / run_id / "alpha_large" / "C4" / "alpha_large_Q1-r1",
            record,
            run_json=run_json("C4", semantic_model_ref=f"deployment:{run_id}"),
            trace=trace_events(1),
        )
    return shas


def _write_score_artifacts(raw: Path, shas: dict[str, str]) -> None:
    """Both frozen scorers over ``direct-run``, plus the C4/C5 official artifact."""
    direct_scores = raw / "direct-run-scores-v1"
    q1, q2 = "direct-run:alpha_large_Q1:C1:1", "direct-run:beta_large_Q2:C2:1"
    _dump_json(
        direct_scores / "official.score.json",
        score_artifact(
            "official_soft_ex",
            [score_entry(q1, shas[q1]), score_entry(q2, shas[q2], None)],
        ),
    )
    _dump_json(
        direct_scores / "sensitivity.score.json",
        score_artifact("sensitivity", [score_entry(q1, shas[q1], "wrong_answer")]),
    )
    c4, c5 = "c4-run:alpha_large_Q1:C4:1", "c5-run:alpha_large_Q1:C4:1"
    _dump_json(
        raw / "c4-run-scores-v2" / "official.score.json",
        score_artifact(
            "official_soft_ex",
            [
                score_entry(c4, shas[c4], "wrong_answer"),
                score_entry(c5, shas[c5]),
                score_entry(q1, shas[q1]),
            ],
        ),
    )


def build_dev_a(root: Path) -> dict[str, str]:
    """Four runs and two score artifacts; returns attempt_id -> record sha."""
    raw = root / "experiments" / "autoresearch" / "raw"
    shas = {**_write_direct_run(raw), **_write_c4_c5_runs(raw)}
    unmapped = generation_record("unmapped-run", "beta_large_Q2", "C3")
    shas[unmapped["attempt_id"]] = write_attempt_dir(
        raw / "unmapped-run" / "beta_large" / "C3" / "beta_large_Q2-r1",
        unmapped,
        trace=trace_events(1),
    )
    _dump_json(
        raw / "broken-run" / "beta_large" / "C1" / "beta_large_Q2-r1" / "failure.json",
        {"x": 1},
    )
    (raw / ".preservation-manifests").mkdir()
    _write_score_artifacts(raw, shas)
    return shas


def build_deployments(root: Path) -> None:
    deployments = root / "experiments" / "deployments"
    _dump_json(
        deployments / "dep-v1" / "dep-v1.claim",
        {
            "kind": "public-omni-semantic-deployment-claim",
            "run_id": "dep-v1",
            "databases": ["alpha_large", "beta_large"],
        },
    )
    _dump_json(
        deployments / "dep-v1" / "dep-v1.alpha_large.json",
        {
            "kind": "public-omni-semantic-deployment",
            "run_id": "dep-v1",
            "database": "alpha_large",
            "connection_id": "conn-1",
            "branch_id": "branch-1",
            "branch_name": "livesqlbench-alpha",
            "file_count": 3,
            "failure_stage": None,
            "failure_detail": None,
            "file_sha256": {"topic.yaml": SHA},
        },
    )
    _dump_json(
        deployments / "diag-v1" / "diag-v1.claim",
        {
            "kind": "public-omni-validator-diagnostic-claim",
            "run_id": "diag-v1",
            "databases": [],
        },
    )
    _dump_json(deployments / "corrections.json", {"kind": "correction"})


def sealed_run_manifest(condition: str) -> dict[str, Any]:
    return {
        "kind": "sealed-run-manifest",
        "condition": condition,
        "repetition": 1,
        "scope": "test",
        "model": "claude",
        "provider": "anthropic",
        "question_count": 1,
        "system_commit": "c" * 40,
        "semantic_model_ref": "deployment:dep-v1",
        "semantic_model_sha256": "b" * 64,
        "started_at": "2026-08-31T00:00:00Z",
        "finished_at": "2026-08-31T01:00:00Z",
    }


def build_sealed(root: Path) -> None:
    sealed = root / "runs" / "preserved" / SEALED_NAME
    for cohort, condition in (("c1-r1", "C1"), ("c4-r1", "C4")):
        capture = (
            sealed
            / "captures"
            / "alpha_large"
            / condition
            / f"{TEST_INSTANCE}-r1"
            / "capture-1"
        )
        trace_path = capture / "attempt.trace.jsonl"
        _dump_jsonl(trace_path, trace_events(2))
        if condition == "C1":
            _dump_json(
                capture / "attempt.action-evidence.json",
                {
                    "kind": "direct-action-evidence",
                    "records": [{"trace_seq": 1, "tool_name": "sql_probe"}],
                },
            )
        record = generation_record(
            f"sealed-{cohort}",
            TEST_INSTANCE,
            condition,
            attempt_prefix="sealed",
            partition="test",
            trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
            trace_path=f"runs/{SEALED_NAME}/captures/alpha_large/{condition}/{TEST_INSTANCE}-r1/capture-1/attempt.trace.jsonl",
        )
        _dump_jsonl(sealed / "cohorts" / cohort / "generation.jsonl", [record])
        _dump_json(
            sealed / "cohorts" / cohort / "run.json", sealed_run_manifest(condition)
        )
    for identity in ("official_soft_ex", "sensitivity"):
        _dump_json(sealed / "score" / identity / "aggregate.json", aggregate(identity))
        (sealed / "score" / identity / "c1-r1.score.json").write_bytes(
            b"\xff never parsed"
        )
    _dump_json(sealed / "score" / "receipt.json", {"kind": "receipt"})


def build_tree(tmp_path: Path) -> Sources:
    root = tmp_path / "repo"
    build_manifests(root)
    build_arms(root)
    build_dev_a(root)
    build_deployments(root)
    build_sealed(root)
    (root / "experiments" / "labels").mkdir()
    return Sources(repo_root=root)


def _release(sources: Sources):
    return read_questions(sources.manifests_dir, repo_root=sources.repo_root)


def _label_fields(attempt_id: str, sha: str = SHA) -> dict[str, str]:
    return {
        "attempt_id": attempt_id,
        "generation_record_sha256": sha,
        "taxonomy_version": TAXONOMY_VERSION,
        "category": "relationship_join",
        "labeler": "human:tester",
        "rationale": "Joined on the wrong key.",
        "created_at": "2026-09-01T12:00:00Z",
    }

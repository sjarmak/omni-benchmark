"""Loader plan, custody guards, and an idempotent double load into Postgres."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import MappingProxyType
from typing import Any

import psycopg
import pytest
from psycopg import sql

from omni_benchmark.telemetry_db import (
    SCHEMA_NAME,
    CustodyViolation,
    LoaderError,
    Row,
    Sources,
    SplitIds,
    collect,
    load_all,
)
from omni_benchmark.telemetry_db.labels import append_label, build_label_record
from omni_benchmark.telemetry_db.loader import (
    LOADER_VERSION,
    TABLE_LOAD_ORDER,
    _guard_custody,
    _merge_rows,
)
from omni_benchmark.telemetry_db.sources import SourceBatch
from tests.telemetry_db_helpers import (
    DEV_B_INSTANCE,
    SEALED_NAME,
    SHA,
    SPLIT,
    TEST_INSTANCE,
    _label_fields,
    build_tree,
    generation_record,
    run_json,
    trace_events,
    write_attempt_dir,
)

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "load_telemetry_db.py"
EXPECTED_COUNTS = {
    "question": 4,
    "deployment": 1,
    "run": 6,
    "attempt": 7,
    "score": 5,
    "trace_event": 9,
    "action_evidence": 2,
    "sealed_aggregate": 4,
    "attempt_label": 0,
    "credit_period": 1,
    "arm_cost": 2,
}
DIRECT_ATTEMPT = "direct-run:alpha_large_Q1:C1:1"


@pytest.fixture
def sources(tmp_path: Path) -> Sources:
    return build_tree(tmp_path)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t"]
        + list(arguments),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit_everything(root: Path) -> str:
    """Turn the synthetic tree into a repository with one commit; returns HEAD."""
    if not (root / ".git").is_dir():
        _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "--allow-empty", "-m", "snapshot")
    return _git(root, "rev-parse", "HEAD")


def _batch(source: str, rows: tuple[Row, ...]) -> SourceBatch:
    grouped: dict[str, list[Row]] = {}
    for row in rows:
        grouped.setdefault(row.table, []).append(row)
    return SourceBatch(
        source=source,
        rows=MappingProxyType({t: tuple(r) for t, r in grouped.items()}),
        dropped=MappingProxyType({}),
        manifests=MappingProxyType({}),
        notes=MappingProxyType({}),
    )


def _question(instance: str, **values: Any) -> Row:
    return Row(
        "question", {"instance_id": instance, "database": "alpha_large", **values}
    )


def test_collect_reads_every_source_without_a_database(sources: Sources) -> None:
    plan = collect(sources)
    assert plan.row_counts == EXPECTED_COUNTS
    assert list(plan.row_counts) == list(TABLE_LOAD_ORDER)
    assert plan.custody == {
        "rows_scanned_for_forbidden_fields": sum(EXPECTED_COUNTS.values()),
        "score_rows_checked_against_split": 5,
        "label_rows_checked_against_split": 0,
        "attempt_rows_checked_against_split": 7,
        "dev_a_id_count": 2,
        "test_id_count": 1,
        "duplicate_rows_collapsed": 0,
        "attempts_outside_dev_a_dropped": 0,
    }
    assert set(plan.dropped) == {"deployments", "dev-a", "sealed"}
    assert plan.notes["dev-a"]["arms"]["c5-run"]["arms"] == ["C5"]
    assert "config/telemetry_db/arms.json" in plan.manifests
    assert (
        f"runs/preserved/{SEALED_NAME}/score/official_soft_ex/aggregate.json"
        in plan.manifests
    )
    assert "experiments/deployments/dep-v1/dep-v1.claim" in plan.manifests
    sealed_attempts = [
        r for r in plan.rows["attempt"] if r.values["partition"] == "test"
    ]
    assert len(sealed_attempts) == 2
    assert not any(
        r.values["attempt_id"].startswith("sealed:") for r in plan.rows["score"]
    )


def test_collect_keeps_dev_b_out_and_counts_it(sources: Sources) -> None:
    dev_b = generation_record("direct-run", DEV_B_INSTANCE, "C1")
    sha = write_attempt_dir(
        sources.raw_dir / "direct-run" / "beta_large" / "C1" / f"{DEV_B_INSTANCE}-r1",
        dev_b,
        run_json=run_json("C1"),
        trace=trace_events(1),
    )
    plan = collect(sources)
    assert plan.row_counts == EXPECTED_COUNTS
    assert plan.custody["attempts_outside_dev_a_dropped"] == 1
    assert plan.dropped["dev-a"]["attempt_instance_not_dev_a"] == 1
    assert not any(
        DEV_B_INSTANCE in r.values["attempt_id"]
        for table in ("attempt", "trace_event", "score")
        for r in plan.rows[table]
    )
    assert not any(
        DEV_B_INSTANCE in r.values["instance_id"] for r in plan.rows["attempt"]
    )
    assert sha not in {
        r.values["generation_record_sha256"] for r in plan.rows["attempt"]
    }


def test_collect_joins_labels_to_loaded_attempts(sources: Sources) -> None:
    attempt_sha = next(
        r.values["generation_record_sha256"]
        for r in collect(sources).rows["attempt"]
        if r.values["attempt_id"] == DIRECT_ATTEMPT
    )
    kept = append_label(
        sources.labels_dir,
        "pass-1",
        _label_fields(DIRECT_ATTEMPT, attempt_sha),
        split=SPLIT,
    )
    append_label(
        sources.labels_dir, "pass-1", _label_fields(DIRECT_ATTEMPT, SHA), split=SPLIT
    )
    plan = collect(sources)
    assert plan.row_counts["attempt_label"] == 1
    assert plan.rows["attempt_label"][0].values["label_id"] == kept.label_id
    assert plan.dropped["labels"] == {"label_attempt_not_loaded": 1}
    assert plan.custody["label_rows_checked_against_split"] == 1
    sealed_label = build_label_record(
        _label_fields(f"sealed:{TEST_INSTANCE}:C1:1", attempt_sha), "pass-2"
    )
    (sources.labels_dir / "pass-2.jsonl").write_text(
        sealed_label.to_line(), encoding="utf-8"
    )
    with pytest.raises(CustodyViolation, match="sealed test split"):
        collect(sources)


def test_collect_honours_source_switches(sources: Sources) -> None:
    without_dev_a = collect(Sources(sources.repo_root, include_dev_a=False))
    assert without_dev_a.row_counts["score"] == 0
    assert without_dev_a.row_counts["attempt"] == 2
    assert "dev-a" not in without_dev_a.notes
    without_sealed = collect(Sources(sources.repo_root, include_sealed=False))
    assert without_sealed.row_counts["sealed_aggregate"] == 0
    assert without_sealed.row_counts["attempt"] == 5


def test_merge_rows_collapses_identical_and_rejects_conflicts() -> None:
    first = _batch("a", (_question("q1", category="Query"),))
    twin = _batch("b", (_question("q1", category="Query"),))
    rows, collapsed = _merge_rows([first, twin])
    assert collapsed == 1 and len(rows["question"]) == 1
    conflicting = _batch("c", (_question("q1", category="Other"),))
    with pytest.raises(LoaderError, match="conflicts with an earlier source"):
        _merge_rows([first, conflicting])
    with pytest.raises(LoaderError, match="not loadable"):
        _merge_rows([_batch("d", (Row("load_run", {"load_id": "x"}),))])


def _keyed(table: str, attempt_id: str, **values: Any) -> Row:
    return Row(
        table,
        {"attempt_id": attempt_id, "generation_record_sha256": SHA, **values},
    )


@pytest.mark.parametrize(
    ("table", "instance", "match"),
    [
        ("score", TEST_INSTANCE, "sealed test split"),
        ("score", DEV_B_INSTANCE, "not in the dev-A split"),
        ("attempt_label", TEST_INSTANCE, "sealed test split"),
        ("attempt_label", DEV_B_INSTANCE, "not in the dev-A split"),
        ("attempt", DEV_B_INSTANCE, "neither the dev-A nor the sealed test split"),
    ],
)
def test_guard_custody_refuses_rows_outside_their_split(
    table: str, instance: str, match: str
) -> None:
    extra = {
        "attempt": {"instance_id": instance},
        "score": {"scorer": "official_soft_ex"},
        "attempt_label": {"label_id": "l1"},
    }[table]
    row = _keyed(table, f"run:{instance}:C1:1", **extra)
    with pytest.raises(CustodyViolation, match=match):
        _guard_custody({table: (row,)}, SPLIT)


def test_guard_custody_resolves_an_opaque_attempt_id_through_its_attempt() -> None:
    opaque = "r2attempt-0123456789abcdef01234567"
    score = _keyed("score", opaque, scorer="official_soft_ex")
    with pytest.raises(LoaderError, match="names no loaded attempt"):
        _guard_custody({"score": (score,)}, SPLIT)
    outside = _keyed("attempt", opaque, instance_id=DEV_B_INSTANCE)
    with pytest.raises(CustodyViolation, match="not in the dev-A split"):
        _guard_custody({"attempt": (outside,), "score": (score,)}, SPLIT)
    inside = _keyed("attempt", opaque, instance_id="alpha_large_Q1")
    tally = _guard_custody({"attempt": (inside,), "score": (score,)}, SPLIT)
    assert tally["score_rows_checked_against_split"] == 1


def test_guard_custody_ties_labels_to_attempts_and_scans_values() -> None:
    attempt = _keyed("attempt", DIRECT_ATTEMPT, instance_id="alpha_large_Q1")
    label = _keyed("attempt_label", DIRECT_ATTEMPT, label_id="l1")
    with pytest.raises(LoaderError, match="names no loaded attempt"):
        _guard_custody({"attempt_label": (label,)}, SPLIT)
    tally = _guard_custody({"attempt": (attempt,), "attempt_label": (label,)}, SPLIT)
    assert tally["label_rows_checked_against_split"] == 1
    assert tally["attempt_rows_checked_against_split"] == 1
    sealed = _keyed(
        "attempt", f"sealed:{TEST_INSTANCE}:C1:1", instance_id=TEST_INSTANCE
    )
    assert (
        _guard_custody({"attempt": (sealed,)}, SPLIT)[
            "score_rows_checked_against_split"
        ]
        == 0
    )
    hidden = _question("q1", public_fields={"nested": [{"gold_result": 1}]})
    with pytest.raises(CustodyViolation, match="gold_result"):
        _guard_custody({"question": (hidden,)}, SPLIT)
    tally = _guard_custody(
        {"question": (_question("q1"),)}, SplitIds(frozenset(), frozenset({"t"}))
    )
    assert tally["rows_scanned_for_forbidden_fields"] == 1
    assert (tally["dev_a_id_count"], tally["test_id_count"]) == (0, 1)


class _FailingConnection:
    def __init__(self) -> None:
        self.rolled_back = False
        self.committed = False

    def cursor(self) -> Any:
        raise psycopg.OperationalError("connection lost")

    def rollback(self) -> None:
        self.rolled_back = True

    def commit(self) -> None:
        self.committed = True


def test_load_all_rolls_back_and_validates_load_id(sources: Sources) -> None:
    conn = _FailingConnection()
    with pytest.raises(psycopg.OperationalError):
        load_all(sources, conn, "load-1", "f" * 40)
    assert conn.rolled_back and not conn.committed
    with pytest.raises(LoaderError, match="load_id"):
        load_all(sources, conn, "", "f" * 40)


def _table_counts(conn: psycopg.Connection) -> dict[str, int]:
    counts = {}
    for table in TABLE_LOAD_ORDER:
        query = sql.SQL("SELECT count(*) FROM {}").format(
            sql.Identifier(SCHEMA_NAME, table)
        )
        counts[table] = conn.execute(query).fetchone()[0]
    return counts


def _assert_load_run_rows(conn: Any) -> None:
    load_runs = conn.execute(
        "SELECT load_id, row_counts, loader_version, system_commit, source_manifests "
        "FROM telemetry.load_run ORDER BY load_id"
    ).fetchall()
    assert [row[0] for row in load_runs] == ["load-1", "load-2"]
    assert load_runs[0][1]["tables"] == EXPECTED_COUNTS
    assert load_runs[0][1]["custody"]["attempt_rows_checked_against_split"] == 7
    assert load_runs[0][1]["system_commit_verified"] is True
    assert load_runs[0][2] == LOADER_VERSION and load_runs[0][3] == "f" * 40
    assert "config/telemetry_db/arms.json" in load_runs[0][4]


def _assert_attempt_scored_rows(conn: Any) -> None:
    scored = conn.execute(
        "SELECT arm, official_outcome, sensitivity_outcome, run_semantic_model_ref "
        "FROM telemetry.attempt_scored WHERE attempt_id = %s",
        ("direct-run:alpha_large_Q1:C1:1",),
    ).fetchone()
    assert scored == ("C1", "correct", "wrong_answer", "deployment:dep-v1")
    c5 = conn.execute(
        "SELECT condition, arm, official_outcome FROM telemetry.attempt_scored "
        "WHERE attempt_id = %s",
        ("c5-run:alpha_large_Q1:C4:1",),
    ).fetchone()
    assert c5 == ("C4", "C5", "correct")
    sealed = conn.execute(
        "SELECT count(*) FROM telemetry.attempt_scored "
        "WHERE partition = 'test' AND official_outcome IS NOT NULL"
    ).fetchone()
    assert sealed == (0,)


def _assert_sealed_aggregate_rows(conn: Any) -> None:
    aggregate = conn.execute(
        "SELECT correct, mean_accuracy FROM telemetry.sealed_aggregate "
        "WHERE scorer = 'official_soft_ex' AND condition = 'C4'"
    ).fetchone()
    assert aggregate[0] == 4 and float(aggregate[1]) == 0.5


def _assert_attempt_and_question_rows(conn: Any) -> None:
    assert conn.execute(
        "SELECT latency_ms, partition FROM telemetry.attempt WHERE attempt_id = %s",
        (DIRECT_ATTEMPT,),
    ).fetchone() == (5000.4, "dev-a")
    assert conn.execute(
        "SELECT high_level FROM telemetry.question WHERE instance_id = %s",
        ("alpha_large_Q1",),
    ).fetchone() == (True,)


def test_load_all_twice_is_idempotent(
    sources: Sources, throwaway_database: str
) -> None:
    with psycopg.connect(throwaway_database) as conn:
        first = load_all(sources, conn, "load-1", "f" * 40)
        assert dict(first.row_counts) == EXPECTED_COUNTS
        assert _table_counts(conn) == EXPECTED_COUNTS
        second = load_all(sources, conn, "load-2", "f" * 40)
        assert dict(second.row_counts) == EXPECTED_COUNTS
        assert _table_counts(conn) == EXPECTED_COUNTS
        _assert_load_run_rows(conn)
        _assert_attempt_scored_rows(conn)
        _assert_sealed_aggregate_rows(conn)
        _assert_attempt_and_question_rows(conn)
        unverified = load_all(sources, conn, "load-3", None)
        assert unverified.row_counts["attempt"] == EXPECTED_COUNTS["attempt"]
        assert conn.execute(
            "SELECT system_commit, row_counts->'system_commit_verified' "
            "FROM telemetry.load_run WHERE load_id = 'load-3'"
        ).fetchone() == (None, False)


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("load_telemetry_db", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cli_dry_run_prints_counts_without_connecting(
    sources: Sources,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script()

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("dry run must not connect")

    monkeypatch.setattr(script.psycopg, "connect", refuse)
    code = script.main(
        ["--dry-run", "--load-id", "dry-1", "--repo-root", str(sources.repo_root)]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["row_counts"] == EXPECTED_COUNTS
    assert summary["custody"]["attempts_outside_dev_a_dropped"] == 0
    assert summary["arms"]["c5-run"]["canonical"] is True
    assert summary["dropped"]["sealed"] == {"score_entry_not_a_scorer_directory": 1}
    assert summary["manifests_hashed"] == len(collect(sources).manifests)


def test_cli_requires_a_connection_string(
    sources: Sources, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = _load_script()
    monkeypatch.delenv(script.DSN_ENV, raising=False)
    with pytest.raises(SystemExit, match="no connection string"):
        script.main(["--load-id", "x", "--repo-root", str(sources.repo_root)])


def test_resolve_system_commit_binds_head_to_a_clean_runtime_tree(
    sources: Sources, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _load_script()
    root = sources.repo_root

    def resolve(explicit: str | None = None, *, allow_dirty_tree: bool = False):
        return script.resolve_system_commit(
            root, explicit, allow_dirty_tree=allow_dirty_tree
        )

    with pytest.raises(SystemExit, match="git status failed"):
        resolve()
    _git(root, "init", "-q")
    with pytest.raises(SystemExit, match="config/telemetry_db/arms.json"):
        resolve()
    with pytest.raises(SystemExit, match="git rev-parse failed"):
        resolve(allow_dirty_tree=True)
    head = _commit_everything(root)
    assert resolve() == head and resolve(head) == head
    assert script.dirty_runtime_paths(root) == ()
    with pytest.raises(SystemExit, match=f"{'e' * 40} is not HEAD {head}"):
        resolve("e" * 40)
    (root / "experiments" / "labels" / "pass-9.jsonl").write_text("", encoding="utf-8")
    assert resolve() == head
    (root / "src").mkdir()
    (root / "src" / "patched.py").write_text("x = 1\n", encoding="utf-8")
    assert script.dirty_runtime_paths(root) == ("src/patched.py",)
    with pytest.raises(SystemExit, match="commit or pass --allow-dirty-tree"):
        resolve()
    capsys.readouterr()
    assert resolve(allow_dirty_tree=True) is None
    assert "src/patched.py" in capsys.readouterr().err


def test_cli_loads_with_env_dsn(
    sources: Sources,
    throwaway_database: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script()
    monkeypatch.setenv(script.DSN_ENV, throwaway_database)
    head = _commit_everything(sources.repo_root)
    common = ["--repo-root", str(sources.repo_root), "--skip-sealed"]
    code = script.main(["--load-id", "cli-1", "--system-commit", head, *common])
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["load_id"] == "cli-1"
    assert summary["system_commit"] == head
    assert summary["upserted"]["sealed_aggregate"] == 0
    assert summary["upserted"]["attempt"] == 5
    (sources.repo_root / "config" / "telemetry_db" / "note.txt").write_text(
        "x", encoding="utf-8"
    )
    with pytest.raises(SystemExit, match="config/telemetry_db/note.txt"):
        script.main(["--load-id", "cli-2", *common])
    assert script.main(["--load-id", "cli-2", "--allow-dirty-tree", *common]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["system_commit"] is None
    assert "config/telemetry_db/note.txt" in captured.err
    with psycopg.connect(throwaway_database) as conn:
        assert conn.execute(
            "SELECT load_id, system_commit, row_counts->'system_commit_verified' "
            "FROM telemetry.load_run ORDER BY load_id"
        ).fetchall() == [("cli-1", head, True), ("cli-2", None, False)]

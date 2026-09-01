"""Cover the corrected governed query-path classifier.

Schema 1 of this analyzer published a mechanism claim built on two fields that
cannot carry it: ``rewriteSql``, which Omni sets by default on every query that
carries authored SQL, and ``join_via_map``, which a submitted query never
populates. The tests that matter here are the ones that would have caught that:
a constant field must not decide the classification, and the shapes the analyzer
reports must be the ones that vary in the records.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "experiments/analysis/governed_query_path_tally.py"


def _load_module() -> Any:
    specification = importlib.util.spec_from_file_location(
        "governed_query_path_tally", MODULE_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tally() -> Any:
    return _load_module()


def _write_arm(root: Path, queries: list[dict[str, Any] | None]) -> Path:
    """Write one arm's generation records, mirroring the nested run layout."""
    destination = root / "db" / "c4" / "q-r1"
    destination.mkdir(parents=True)
    lines = [
        json.dumps({"generated_query": json.dumps(query) if query else None})
        for query in queries
    ]
    (destination / "generation.jsonl").write_text("\n".join(lines) + "\n")
    return root


def test_constant_rewrite_sql_does_not_decide_the_classification(tally: Any) -> None:
    """The regression that produced the published error.

    Both queries carry ``rewriteSql`` true and an empty ``join_via_map`` -- the
    shape of every governed record we hold. Schema 1 put both in ``rewrite`` and
    reported zero composed. They must now separate on what actually differs.
    """
    scoped = tally.classify_query(
        {
            "rewriteSql": True,
            "join_via_map": {},
            "join_paths_from_topic_name": "orders",
            "userEditedSQL": "SELECT ${orders.id} FROM ${orders}",
        }
    )
    unscoped = tally.classify_query(
        {
            "rewriteSql": True,
            "join_via_map": {},
            "join_paths_from_topic_name": "",
            "userEditedSQL": "SELECT id FROM public.orders",
        }
    )

    assert scoped["topic_scoped"] is True
    assert unscoped["topic_scoped"] is False
    assert scoped["qualified_token_present"] is True
    assert unscoped["qualified_token_present"] is False
    assert unscoped["bare_table_from"] is True


def test_qualified_tokens_are_distinguished_from_bare_ones(tally: Any) -> None:
    """``${view.field}`` resolves through the model; a bare ``${topic}`` does not."""
    bare = tally.classify_query({"userEditedSQL": "SELECT 1 FROM ${orders}"})
    qualified = tally.classify_query(
        {"userEditedSQL": "SELECT ${orders.total} FROM ${orders}"}
    )

    assert bare["semantic_token_present"] is True
    assert bare["qualified_token_present"] is False
    assert qualified["qualified_token_present"] is True
    assert qualified["semantic_token_count"] == 2


def test_inline_aggregate_over_token_is_the_missing_measure_signal(
    tally: Any,
) -> None:
    """An aggregate wrapping a field reference means no measure was available."""
    hand_rolled = tally.classify_query(
        {"userEditedSQL": "SELECT SUM(${orders.total}) FROM ${orders}"}
    )
    distinct = tally.classify_query(
        {"userEditedSQL": "SELECT COUNT(DISTINCT ${orders.id}) FROM ${orders}"}
    )
    measure = tally.classify_query(
        {"userEditedSQL": "SELECT ${orders.total_revenue} FROM ${orders}"}
    )

    assert hand_rolled["inline_aggregate_over_token"] is True
    assert distinct["inline_aggregate_over_token"] is True
    assert measure["inline_aggregate_over_token"] is False


def test_bare_table_from_detects_reaching_outside_the_model(tally: Any) -> None:
    templated = tally.classify_query({"userEditedSQL": "SELECT 1 FROM ${orders}"})
    quoted = tally.classify_query({"userEditedSQL": 'SELECT 1 FROM "public"."orders"'})
    mixed = tally.classify_query(
        {"userEditedSQL": "SELECT 1 FROM ${orders} JOIN raw_events ON TRUE"}
    )

    assert templated["bare_table_from"] is False
    assert quoted["bare_table_from"] is True
    assert mixed["bare_table_from"] is False, "a JOIN is not a FROM clause"


def test_shapes_are_counted_independently_not_bucketed(
    tally: Any, tmp_path: Path
) -> None:
    """Co-occurring shapes must each be counted, not collapsed into one bucket."""
    root = _write_arm(
        tmp_path / "arm",
        [
            {
                "join_paths_from_topic_name": "orders",
                "userEditedSQL": "SELECT SUM(${orders.total}) FROM ${orders}",
            },
            {
                "join_paths_from_topic_name": "",
                "userEditedSQL": "SELECT id FROM public.orders",
            },
        ],
    )
    counts = tally.tally_arm(root)

    assert counts["attempts"] == 2
    assert counts["user_edited_sql"] == 2
    assert counts["topic_scoped"] == 1
    assert counts["user_edited_sql_and_topic_scoped"] == 1
    assert counts["inline_aggregate_over_token"] == 1
    assert counts["bare_table_from"] == 1
    assert counts["semantic_token_total"] == 2


def test_unparseable_records_are_excluded_from_the_denominator(
    tally: Any, tmp_path: Path
) -> None:
    root = _write_arm(
        tmp_path / "arm",
        [None, {"userEditedSQL": "SELECT ${orders.id} FROM ${orders}"}],
    )
    summary = tally.summarize_arm(tally.tally_arm(root))

    assert summary["attempts"] == 2
    assert summary["no_semantic_query"] == 1
    assert summary["parseable_attempts"] == 1
    assert summary["shares_of_parseable_percent"]["user_edited_sql"] == 100.0


def test_empty_arm_raises_rather_than_reporting_zero(
    tally: Any, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(tally.QueryPathTallyError, match="no generation records"):
        tally.tally_arm(empty)


def test_output_refuses_to_overwrite_a_committed_artifact(
    tally: Any, tmp_path: Path
) -> None:
    """Evidence artifacts are append-only; a rerun must not clobber v1."""
    _write_arm(tmp_path / "arm", [{"userEditedSQL": "SELECT ${orders.id}"}])
    existing = tmp_path / "existing.json"
    existing.write_text("{}\n")

    with pytest.raises(tally.QueryPathTallyError, match="refusing overwrite"):
        tally.main(
            [
                "--workspace",
                str(tmp_path),
                "--arm",
                "arm=arm",
                "--output",
                "existing.json",
            ]
        )


def test_report_declares_schema_two_and_supersession(
    tally: Any, tmp_path: Path
) -> None:
    _write_arm(tmp_path / "arm", [{"userEditedSQL": "SELECT ${orders.id}"}])
    assert (
        tally.main(
            ["--workspace", str(tmp_path), "--arm", "arm=arm", "--output", "out.json"]
        )
        == 0
    )
    report = json.loads((tmp_path / "out.json").read_text())

    assert report["schema_version"] == 2
    assert report["supersedes"] == "governed-query-path-tally-v1.json"
    assert "rewrite_share_of_parseable_percent" not in report["arms"]["arm"]


def test_analyzer_emits_no_sql_text(tally: Any, tmp_path: Path) -> None:
    """Custody: the report carries counts, never the SQL it measured."""
    secret = "SELECT ${orders.customer_ssn} FROM ${orders}"
    _write_arm(tmp_path / "arm", [{"userEditedSQL": secret}])
    tally.main(
        ["--workspace", str(tmp_path), "--arm", "arm=arm", "--output", "out.json"]
    )

    content = (tmp_path / "out.json").read_text()
    assert "customer_ssn" not in content
    assert "SELECT" not in content

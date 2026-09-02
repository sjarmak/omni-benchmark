from __future__ import annotations

from pathlib import Path

import pytest

from omni_benchmark.autoresearch_config import MANDATORY_FORBIDDEN_FIELDS
from omni_benchmark.telemetry_db import (
    FORBIDDEN_FIELDS,
    CustodyViolation,
    SplitIds,
    assert_dev_a_instance,
    assert_not_test_instance,
    load_split_ids,
    load_test_ids,
    reject_forbidden_fields,
)

REPO_MANIFESTS = Path(__file__).resolve().parents[1] / "data" / "manifests"
CONTRACT_FORBIDDEN_FIELDS = frozenset(
    {
        "sol_sql",
        "gold_sql",
        "test_cases",
        "external_knowledge",
        "test_correctness",
        "gold_result",
        "expected_result",
    }
)


def test_forbidden_fields_cover_the_schema_contract_via_shared_constant() -> None:
    assert FORBIDDEN_FIELDS is MANDATORY_FORBIDDEN_FIELDS
    assert CONTRACT_FORBIDDEN_FIELDS <= FORBIDDEN_FIELDS


@pytest.mark.parametrize("field", sorted(CONTRACT_FORBIDDEN_FIELDS))
def test_reject_forbidden_fields_at_every_depth(field: str) -> None:
    nested = {"attempt": {"trace": [{"ok": 1}, {"payload": {field: "x"}}]}}
    with pytest.raises(CustodyViolation, match=f"attempt 7: forbidden field '{field}'"):
        reject_forbidden_fields(nested, "attempt 7")
    with pytest.raises(CustodyViolation, match=f"forbidden field '{field}'"):
        reject_forbidden_fields([[{field: None}]], "list")
    with pytest.raises(CustodyViolation):
        reject_forbidden_fields({field: {}}, "top")


def test_reject_forbidden_fields_accepts_public_values() -> None:
    reject_forbidden_fields(
        {
            "instance_id": "q1",
            "question": "How many?",
            "conditions": {"order": False},
            "trace": [{"tool_name": "sql", "sql_text": "select gold_sql from t"}],
        },
        "question q1",
    )
    reject_forbidden_fields("sol_sql", "scalar")
    reject_forbidden_fields(None, "none")
    reject_forbidden_fields([], "empty")


def test_load_test_ids_reads_the_manifest_directory(tmp_path: Path) -> None:
    (tmp_path / "test_ids.txt").write_text("q_a\nq_b\nq_c\n", encoding="utf-8")
    ids = load_test_ids(tmp_path)
    assert ids == frozenset({"q_a", "q_b", "q_c"})
    assert isinstance(ids, frozenset)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "cannot load test IDs"),
        ("", "empty"),
        ("q_a\n\nq_b\n", "blank ID at line 2"),
        ("q_a\nq_a\n", "duplicate ID at line 2"),
    ],
)
def test_load_test_ids_rejects_ambiguous_manifests(
    tmp_path: Path, content: str | None, message: str
) -> None:
    if content is not None:
        (tmp_path / "test_ids.txt").write_text(content, encoding="utf-8")
    with pytest.raises(CustodyViolation, match=message):
        load_test_ids(tmp_path)


def test_load_test_ids_reads_the_committed_sealed_split() -> None:
    ids = load_test_ids(REPO_MANIFESTS)
    assert len(ids) == 101
    assert all(isinstance(item, str) and item for item in ids)


def test_assert_not_test_instance_refuses_sealed_ids_only() -> None:
    test_ids = frozenset({"sealed_1", "sealed_2"})
    assert_not_test_instance("dev_1", test_ids, "score")
    assert_not_test_instance("sealed_1", frozenset(), "score")
    with pytest.raises(
        CustodyViolation, match="score row: instance 'sealed_2' is in the sealed"
    ):
        assert_not_test_instance("sealed_2", test_ids, "score row")


def test_load_split_ids_reads_both_files_and_refuses_overlap(tmp_path: Path) -> None:
    (tmp_path / "test_ids.txt").write_text("t_1\nt_2\n", encoding="utf-8")
    with pytest.raises(CustodyViolation, match="cannot load dev-A IDs"):
        load_split_ids(tmp_path)
    (tmp_path / "dev_a_ids.txt").write_text("a_1\na_2\na_3\n", encoding="utf-8")
    split = load_split_ids(tmp_path)
    assert split == SplitIds(
        dev_a=frozenset({"a_1", "a_2", "a_3"}), test=frozenset({"t_1", "t_2"})
    )
    (tmp_path / "dev_a_ids.txt").write_text("a_1\nt_2\n", encoding="utf-8")
    with pytest.raises(
        CustodyViolation, match=r"both dev-A and test splits: \['t_2'\]"
    ):
        load_split_ids(tmp_path)


def test_load_split_ids_reads_the_committed_manifests() -> None:
    split = load_split_ids(REPO_MANIFESTS)
    assert (len(split.dev_a), len(split.test)) == (154, 101)
    assert not split.dev_a & split.test


def test_assert_dev_a_instance_admits_dev_a_only() -> None:
    split = SplitIds(dev_a=frozenset({"a_1"}), test=frozenset({"t_1"}))
    assert_dev_a_instance("a_1", split, "score row")
    with pytest.raises(CustodyViolation, match="'t_1' is in the sealed test split"):
        assert_dev_a_instance("t_1", split, "score row")
    with pytest.raises(
        CustodyViolation, match="label 9: instance 'b_1' is not in the dev-A split"
    ):
        assert_dev_a_instance("b_1", split, "label 9")

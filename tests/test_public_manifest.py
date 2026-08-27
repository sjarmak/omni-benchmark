from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.split import (
    PublicDataError,
    prepare_public_manifest,
    read_public_records,
)

from .helpers import public_record, write_jsonl


def test_prepare_filters_management_and_emits_only_public_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    output = tmp_path / "manifests"
    write_jsonl(
        source,
        [
            public_record("query_2", high_level=True),
            public_record("management_1", category="Management"),
            public_record("query_1"),
        ],
    )

    metadata = prepare_public_manifest(source, output, source_commit="abc123")

    lines = (
        (output / "eligible_questions.jsonl").read_text(encoding="utf-8").splitlines()
    )
    manifest = [json.loads(line) for line in lines]
    assert [record["instance_id"] for record in manifest] == ["query_1", "query_2"]
    assert manifest[0]["source_index"] == 3
    assert manifest[1]["source_index"] == 1
    assert set(manifest[0]) == {
        "category",
        "clean_up_sqls",
        "conditions",
        "high_level",
        "instance_id",
        "normal_query",
        "preprocess_sql",
        "query",
        "selected_database",
        "source_index",
    }
    assert metadata["counts"] == {"eligible": 2, "excluded": 1, "source": 3}
    assert metadata["categories"] == {"Management": 1, "Query": 2}
    assert metadata["source"]["revision"] == "abc123"
    assert (
        metadata["source"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "private_field", ["sol_sql", "external_knowledge", "test_cases"]
)
def test_read_rejects_nonempty_private_fields(
    tmp_path: Path, private_field: str
) -> None:
    source = tmp_path / "source.jsonl"
    record = public_record("query_1")
    record[private_field] = ["hidden"]
    write_jsonl(source, [record])

    with pytest.raises(
        PublicDataError, match=rf"line 1.*{private_field}.*must be empty"
    ):
        read_public_records(source)


def test_read_rejects_duplicate_instance_ids_even_if_one_is_management(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    write_jsonl(
        source,
        [public_record("duplicate"), public_record("duplicate", category="Management")],
    )

    with pytest.raises(PublicDataError, match="line 2.*duplicate instance_id"):
        read_public_records(source)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row.pop("query"), "missing fields: query"),
        (
            lambda row: row.update(instance_id=""),
            "instance_id must be a non-empty string",
        ),
        (lambda row: row.update(high_level=1), "high_level must be a boolean"),
        (
            lambda row: row.update(category="SELECT"),
            "category must be Query or Management",
        ),
        (
            lambda row: row.update(
                conditions={"decimal": True, "distinct": False, "order": False}
            ),
            "conditions.decimal must be an integer",
        ),
        (
            lambda row: row.update(
                conditions={"decimal": -1, "distinct": "false", "order": False}
            ),
            "conditions.distinct must be a boolean",
        ),
    ],
)
def test_read_rejects_invalid_public_schema(
    tmp_path: Path, mutate, message: str
) -> None:
    source = tmp_path / "source.jsonl"
    record = public_record("query_1")
    mutate(record)
    write_jsonl(source, [record])

    with pytest.raises(PublicDataError, match=message):
        read_public_records(source)


def test_read_rejects_empty_and_malformed_jsonl(tmp_path: Path) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text('{"instance_id":\n', encoding="utf-8")

    with pytest.raises(PublicDataError, match="contains no records"):
        read_public_records(empty)
    with pytest.raises(PublicDataError, match="line 1 is not valid JSON"):
        read_public_records(malformed)


def test_prepare_is_byte_deterministic_and_handles_unicode(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    write_jsonl(source, [public_record("unicode_🧪")])
    first = tmp_path / "first"
    second = tmp_path / "second"

    prepare_public_manifest(source, first, source_commit="fixed")
    prepare_public_manifest(source, second, source_commit="fixed")

    assert (first / "eligible_questions.jsonl").read_bytes() == (
        second / "eligible_questions.jsonl"
    ).read_bytes()
    assert (first / "manifest_metadata.json").read_bytes() == (
        second / "manifest_metadata.json"
    ).read_bytes()
    assert "🧪" in (first / "eligible_questions.jsonl").read_text(encoding="utf-8")


def test_prepare_refuses_to_overwrite_source_file(tmp_path: Path) -> None:
    source = tmp_path / "eligible_questions.jsonl"
    write_jsonl(source, [public_record("query_1")])

    with pytest.raises(PublicDataError, match="output would overwrite input"):
        prepare_public_manifest(source, tmp_path, source_commit="fixed")

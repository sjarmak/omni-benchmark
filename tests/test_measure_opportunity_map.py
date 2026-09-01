from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import pytest

from omni_benchmark.measure_catalog_review import MeasureReviewError
from omni_benchmark.measure_opportunity_map import (
    OPPORTUNITY_REVIEW_COLUMNS,
    MeasureOpportunityMapError,
    build_measure_opportunity_review_workbook,
    materialize_measure_opportunity_map,
    validate_measure_opportunity_map,
)
from omni_benchmark.measure_opportunity_map_cli import main
from omni_benchmark.measure_review_catalog import canonical_catalog_bytes

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _candidate(database: str, suffix: str) -> dict[str, object]:
    field_id = f"{database}:column:things_{suffix}:id"
    return {
        "candidate_class": "entity_count",
        "candidate_id": f"candidate-{database}-{suffix}",
        "database": database,
        "evidence": {
            "identity_field_stable_id": field_id,
            "identity_kind": "primary_key",
            "public_records": [],
            "table_stable_id": f"{database}:table:things_{suffix}",
        },
        "inline_equivalent_signature": {
            "aggregate_type": "count_distinct",
            "source_field_stable_ids": [field_id],
        },
        "measure": {
            "definition": {
                "aggregate_type": "count_distinct",
                "description": f"Count of distinct things {suffix}.",
                "label": f"Things {suffix} Count",
                "sql": f"${{{database}_public__things_{suffix}.id}}",
            },
            "name": "count",
        },
        "measure_id": f"measure-{database}-{suffix}",
        "proposed_omni_yaml": "measures: {}\n",
        "view": {
            "file_name": f"{database}.things_{suffix}.view",
            "table_stable_id": f"{database}:table:things_{suffix}",
            "view_name": f"{database}_public__things_{suffix}",
        },
    }


def _accepted_catalog_bytes() -> bytes:
    candidates = [
        _candidate("db_a", "one"),
        _candidate("db_a", "two"),
        _candidate("db_b", "three"),
    ]
    candidates.sort(key=lambda item: item["candidate_id"])
    candidate_ids = [str(item["candidate_id"]) for item in candidates]
    measure_ids = [str(item["measure_id"]) for item in candidates]
    artifact: dict[str, object] = {
        "accepted_candidates": candidates,
        "catalog_version": "public-evidence-measure-catalog-v1",
        "generator": {
            "database_count": 2,
            "databases": ["db_a", "db_b"],
            "input_files": [],
            "version": "r2-public-evidence-measure-candidates-v1",
        },
        "kind": "public-evidence-measure-catalog",
        "schema_version": 1,
        "source": {"decision_artifact_sha256": "1" * 64},
        "summary": {
            "accepted_candidate_count": 3,
            "accepted_database_count": 2,
            "accepted_databases": ["db_a", "db_b"],
            "candidate_count_by_class": {"entity_count": 3},
            "measure_count_by_database": {"db_a": 2, "db_b": 1},
        },
        "manifest": {
            "ordered_candidate_ids": candidate_ids,
            "ordered_measure_ids": measure_ids,
        },
    }
    manifest = artifact["manifest"]
    assert isinstance(manifest, dict)
    manifest["artifact_sha256"] = hashlib.sha256(
        canonical_catalog_bytes(artifact)
    ).hexdigest()
    return canonical_catalog_bytes(artifact)


def _record(instance_id: str, database: str) -> dict[str, object]:
    return {
        "category": "Query",
        "clean_up_sqls": [],
        "conditions": {"decimal": 2, "distinct": False, "order": True},
        "high_level": False,
        "instance_id": instance_id,
        "normal_query": f"Normal phrasing for {instance_id}",
        "preprocess_sql": [],
        "query": f"How many things are in {instance_id}?",
        "selected_database": database,
        "source_index": 1,
    }


def _manifest_bytes(records: list[dict[str, object]]) -> bytes:
    return b"".join(canonical_catalog_bytes(record) for record in records)


def _rows(workbook: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(workbook.decode(), newline="")))


def _encode_rows(rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=list(OPPORTUNITY_REVIEW_COLUMNS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def _fixture() -> tuple[bytes, bytes, bytes]:
    catalog = _accepted_catalog_bytes()
    manifest = _manifest_bytes(
        [
            _record("dev-a-1", "db_a"),
            _record("dev-a-excluded", "db_x"),
            _record("dev-b-1", "db_a"),
            _record("test-1", "db_a"),
        ]
    )
    dev_a_ids = b"dev-a-1\ndev-a-excluded\n"
    return catalog, manifest, dev_a_ids


def test_review_workbook_is_deterministic_and_scoped_before_review() -> None:
    catalog, manifest, dev_a_ids = _fixture()

    first = build_measure_opportunity_review_workbook(
        catalog,
        manifest,
        dev_a_ids,
        expected_dev_a_count=2,
        expected_frame_count=1,
    )
    second = build_measure_opportunity_review_workbook(
        catalog,
        manifest,
        dev_a_ids,
        expected_dev_a_count=2,
        expected_frame_count=1,
    )

    assert first == second
    rows = _rows(first)
    assert len(rows) == 1
    row = rows[0]
    assert row["instance_id"] == "dev-a-1"
    assert row["database"] == "db_a"
    assert row["question"] == "How many things are in dev-a-1?"
    assert row["decision"] == ""
    assert row["measure_ids_json"] == "[]"
    assert row["active_review_seconds"] == ""
    options = json.loads(row["eligible_measure_options_json"])
    assert [item["measure_id"] for item in options] == [
        "measure-db_a-one",
        "measure-db_a-two",
    ]
    assert b"dev-a-excluded" not in first
    assert b"dev-b-1" not in first
    assert b"test-1" not in first
    assert b"Normal phrasing" not in first


def test_materialized_map_excludes_question_text_and_binds_exact_review() -> None:
    catalog, manifest, dev_a_ids = _fixture()
    workbook = build_measure_opportunity_review_workbook(
        catalog,
        manifest,
        dev_a_ids,
        expected_dev_a_count=2,
        expected_frame_count=1,
    )
    rows = _rows(workbook)
    rows[0]["decision"] = "mapped"
    rows[0]["measure_ids_json"] = '["measure-db_a-one"]'
    rows[0]["active_review_seconds"] = "1.25"
    reviewed = _encode_rows(rows)

    artifact = materialize_measure_opportunity_map(
        catalog,
        manifest,
        dev_a_ids,
        reviewed,
        expected_dev_a_count=2,
        expected_frame_count=1,
    )

    assert artifact["kind"] == "public-evidence-measure-opportunity-map"
    assert artifact["map_version"] == "r2-public-evidence-measure-opportunity-map-v1"
    assert artifact["summary"] == {
        "active_review_seconds": 1.25,
        "ambiguous_candidate_assignments": 0,
        "ambiguous_question_count": 0,
        "eligible_question_count": 1,
        "mapped_measure_assignments": 1,
        "mapped_question_count": 1,
        "none_question_count": 0,
        "opportunity_question_count": 1,
    }
    assert artifact["decisions"] == [
        {
            "active_review_seconds": 1.25,
            "database": "db_a",
            "decision": "mapped",
            "instance_id": "dev-a-1",
            "measure_ids": ["measure-db_a-one"],
            "public_record_sha256": rows[0]["public_record_sha256"],
            "question_sha256": rows[0]["question_sha256"],
        }
    ]
    encoded = canonical_catalog_bytes(artifact)
    assert b"How many things" not in encoded
    assert b"normal_query" not in encoded
    assert (
        validate_measure_opportunity_map(
            encoded,
            catalog,
            manifest,
            dev_a_ids,
            reviewed,
            expected_dev_a_count=2,
            expected_frame_count=1,
        )
        == artifact
    )
    assert (
        artifact["source"]["review_workbook_sha256"]
        == hashlib.sha256(reviewed).hexdigest()
    )


def test_ambiguous_review_is_not_counted_as_an_opportunity() -> None:
    catalog, manifest, dev_a_ids = _fixture()
    workbook = build_measure_opportunity_review_workbook(
        catalog,
        manifest,
        dev_a_ids,
        expected_dev_a_count=2,
        expected_frame_count=1,
    )
    rows = _rows(workbook)
    rows[0]["decision"] = "ambiguous"
    rows[0]["measure_ids_json"] = '["measure-db_a-two"]'
    rows[0]["active_review_seconds"] = "2"

    artifact = materialize_measure_opportunity_map(
        catalog,
        manifest,
        dev_a_ids,
        _encode_rows(rows),
        expected_dev_a_count=2,
        expected_frame_count=1,
    )

    assert artifact["summary"]["ambiguous_question_count"] == 1
    assert artifact["summary"]["ambiguous_candidate_assignments"] == 1
    assert artifact["summary"]["mapped_question_count"] == 0
    assert artifact["summary"]["opportunity_question_count"] == 0


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("blank_decision", "complete review fields"),
        ("none_with_measure", "none decision"),
        ("mapped_without_measure", "mapped decision"),
        ("unknown_measure", "unknown measure"),
        ("duplicate_measure", "unique and sorted"),
        ("wrong_database", "question database"),
        ("negative_time", "finite and nonnegative"),
        ("nonfinite_time", "finite and nonnegative"),
        ("changed_question", "immutable review column"),
    ],
)
def test_materialization_rejects_invalid_or_changed_review(
    mutation: str,
    message: str,
) -> None:
    catalog, manifest, dev_a_ids = _fixture()
    workbook = build_measure_opportunity_review_workbook(
        catalog,
        manifest,
        dev_a_ids,
        expected_dev_a_count=2,
        expected_frame_count=1,
    )
    rows = _rows(workbook)
    rows[0]["decision"] = "none"
    rows[0]["active_review_seconds"] = "1"
    if mutation == "blank_decision":
        rows[0]["decision"] = ""
    elif mutation == "none_with_measure":
        rows[0]["measure_ids_json"] = '["measure-db_a-one"]'
    elif mutation == "mapped_without_measure":
        rows[0]["decision"] = "mapped"
    elif mutation == "unknown_measure":
        rows[0]["decision"] = "mapped"
        rows[0]["measure_ids_json"] = '["measure-unknown"]'
    elif mutation == "duplicate_measure":
        rows[0]["decision"] = "mapped"
        rows[0]["measure_ids_json"] = '["measure-db_a-one","measure-db_a-one"]'
    elif mutation == "wrong_database":
        rows[0]["decision"] = "mapped"
        rows[0]["measure_ids_json"] = '["measure-db_b-three"]'
    elif mutation == "negative_time":
        rows[0]["active_review_seconds"] = "-1"
    elif mutation == "nonfinite_time":
        rows[0]["active_review_seconds"] = "nan"
    else:
        rows[0]["question"] = "Changed"

    with pytest.raises(MeasureOpportunityMapError, match=message):
        materialize_measure_opportunity_map(
            catalog,
            manifest,
            dev_a_ids,
            _encode_rows(rows),
            expected_dev_a_count=2,
            expected_frame_count=1,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate_dev_a", "duplicate ID"),
        ("missing_dev_a", "must exist"),
        ("dev_a_count", "dev-A count"),
        ("frame_count", "eligible frame count"),
        ("catalog_hash", "catalog hash"),
    ],
)
def test_template_rejects_scope_or_catalog_drift(mutation: str, message: str) -> None:
    catalog, manifest, dev_a_ids = _fixture()
    expected_dev_a_count = 2
    expected_frame_count = 1
    if mutation == "duplicate_dev_a":
        dev_a_ids = b"dev-a-1\ndev-a-1\n"
    elif mutation == "missing_dev_a":
        dev_a_ids = b"dev-a-1\nmissing\n"
    elif mutation == "dev_a_count":
        expected_dev_a_count = 3
    elif mutation == "frame_count":
        expected_frame_count = 2
    else:
        value = json.loads(catalog)
        value["accepted_candidates"][0]["measure"]["definition"]["label"] = "Changed"
        catalog = canonical_catalog_bytes(value)

    with pytest.raises(MeasureOpportunityMapError, match=message):
        build_measure_opportunity_review_workbook(
            catalog,
            manifest,
            dev_a_ids,
            expected_dev_a_count=expected_dev_a_count,
            expected_frame_count=expected_frame_count,
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_materialization_rejects_missing_or_duplicate_question_rows(
    mutation: str,
) -> None:
    catalog, manifest, dev_a_ids = _fixture()
    workbook = build_measure_opportunity_review_workbook(
        catalog,
        manifest,
        dev_a_ids,
        expected_dev_a_count=2,
        expected_frame_count=1,
    )
    rows = _rows(workbook)
    rows[0]["decision"] = "none"
    rows[0]["active_review_seconds"] = "1"
    if mutation == "missing":
        rows = []
    else:
        rows.append(dict(rows[0]))

    with pytest.raises(MeasureOpportunityMapError, match="exactly once"):
        materialize_measure_opportunity_map(
            catalog,
            manifest,
            dev_a_ids,
            _encode_rows(rows),
            expected_dev_a_count=2,
            expected_frame_count=1,
        )


def test_template_rejects_protected_fields_before_packet_generation() -> None:
    catalog, manifest, dev_a_ids = _fixture()
    records = [json.loads(line) for line in manifest.splitlines()]
    records[0]["gold_sql"] = "SELECT protected"

    with pytest.raises(MeasureOpportunityMapError, match="forbidden field"):
        build_measure_opportunity_review_workbook(
            catalog,
            _manifest_bytes(records),
            dev_a_ids,
            expected_dev_a_count=2,
            expected_frame_count=1,
        )


def test_real_review_workbook_regenerates_byte_identically() -> None:
    experiment_root = REPOSITORY_ROOT / "experiments/r2-public-evidence-measures"
    catalog = (experiment_root / "public-evidence-measure-catalog-v1.json").read_bytes()
    manifest = (
        REPOSITORY_ROOT / "data/manifests/eligible_questions.jsonl"
    ).read_bytes()
    dev_a_path = REPOSITORY_ROOT / "data/manifests/dev_a_ids.txt"
    dev_a_ids = dev_a_path.read_bytes()
    path = experiment_root / "measure-opportunity-review-workbook-v1.csv"
    observed = path.read_bytes()

    regenerated = build_measure_opportunity_review_workbook(
        catalog,
        manifest,
        dev_a_ids,
    )

    assert regenerated == observed
    assert hashlib.sha256(observed).hexdigest() == (
        "5412b1b815df9cf0ca00b4fc673df2c8ca71ff1559cbb05bed0d4b6fa240d6ec"
    )
    assert path.stat().st_mode & 0o777 == 0o600
    rows = _rows(observed)
    row_ids = {row["instance_id"] for row in rows}
    dev_a_set = set(dev_a_ids.decode().splitlines())
    dev_b_set = set(
        (REPOSITORY_ROOT / "data/manifests/dev_b_ids.txt").read_text().splitlines()
    )
    test_set = set(
        (REPOSITORY_ROOT / "data/manifests/test_ids.txt").read_text().splitlines()
    )
    assert len(rows) == 136
    assert row_ids.issubset(dev_a_set)
    assert row_ids.isdisjoint(dev_b_set)
    assert row_ids.isdisjoint(test_set)
    assert all(row["decision"] == "" for row in rows)
    assert all(row["measure_ids_json"] == "[]" for row in rows)
    assert all(row["active_review_seconds"] == "" for row in rows)


def test_cli_round_trip_is_append_only_and_mode_0600(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog_bytes = _accepted_catalog_bytes()
    records = [
        _record(f"dev-a-{index:03d}", "db_a" if index < 136 else "db_x")
        for index in range(154)
    ]
    manifest_bytes = _manifest_bytes(records)
    dev_a_ids_bytes = "".join(f"dev-a-{index:03d}\n" for index in range(154)).encode()
    catalog = tmp_path / "accepted-catalog.json"
    manifest = tmp_path / "public-manifest.jsonl"
    dev_a_ids = tmp_path / "dev-a-ids.txt"
    workbook = tmp_path / "opportunity-review.csv"
    artifact = tmp_path / "opportunity-map.json"
    catalog.write_bytes(catalog_bytes)
    manifest.write_bytes(manifest_bytes)
    dev_a_ids.write_bytes(dev_a_ids_bytes)

    assert (
        main(
            [
                "template",
                "--accepted-catalog",
                str(catalog),
                "--public-manifest",
                str(manifest),
                "--dev-a-ids",
                str(dev_a_ids),
                "--output",
                str(workbook),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["eligible_question_count"] == 136
    assert workbook.stat().st_mode & 0o777 == 0o600
    rows = _rows(workbook.read_bytes())
    for row in rows:
        row["decision"] = "none"
        row["active_review_seconds"] = "1"
    reviewed = tmp_path / "opportunity-review-validated.csv"
    reviewed.write_bytes(_encode_rows(rows))

    assert (
        main(
            [
                "freeze",
                "--accepted-catalog",
                str(catalog),
                "--public-manifest",
                str(manifest),
                "--dev-a-ids",
                str(dev_a_ids),
                "--workbook",
                str(reviewed),
                "--output",
                str(artifact),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["eligible_question_count"] == 136
    assert report["none_question_count"] == 136
    assert artifact.stat().st_mode & 0o777 == 0o600
    with pytest.raises(MeasureReviewError, match="already exists"):
        main(
            [
                "freeze",
                "--accepted-catalog",
                str(catalog),
                "--public-manifest",
                str(manifest),
                "--dev-a-ids",
                str(dev_a_ids),
                "--workbook",
                str(reviewed),
                "--output",
                str(artifact),
            ]
        )

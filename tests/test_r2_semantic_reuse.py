from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

import omni_benchmark.r2_semantic_reuse_cli as reuse_cli
from omni_benchmark.measure_review_catalog import canonical_catalog_bytes
from omni_benchmark.r2_paired_schedule import build_r2_paired_schedule
from omni_benchmark.r2_semantic_reuse import (
    _Measure,
    _aggregate_matches,
    _lexical_sql,
    _sql_has_inline,
    _wilson_interval,
    R2SemanticReuseError,
    build_r2_semantic_reuse_report,
    validate_r2_semantic_reuse_report,
    write_r2_semantic_reuse_report,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _jsonl(records: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_catalog_bytes(record) for record in records)


def _candidate(
    measure_id: str,
    measure_name: str,
    source_field: str,
    aggregate_type: str,
) -> dict[str, Any]:
    definition = {
        "aggregate_type": aggregate_type,
        "description": f"Public {measure_name}.",
        "label": measure_name.replace("_", " ").title(),
        "sql": f"${{{source_field}}}",
    }
    return {
        "candidate_class": "entity_count",
        "candidate_id": f"candidate-{measure_id}",
        "database": "orders_large",
        "evidence": {
            "identity_field_stable_id": "orders:column:orders:id",
            "identity_kind": "primary_key",
            "public_records": [],
            "table_stable_id": "orders:table:orders",
        },
        "inline_equivalent_signature": {
            "aggregate_type": aggregate_type,
            "source_field_stable_ids": [
                f"orders:column:{source_field.replace('.', ':')}"
            ],
        },
        "measure": {"definition": definition, "name": measure_name},
        "measure_id": measure_id,
        "proposed_omni_yaml": "fixture",
        "view": {
            "file_name": "orders.view",
            "table_stable_id": "orders:table:orders",
            "view_name": "orders",
        },
    }


def _catalog_bytes() -> bytes:
    candidates = sorted(
        [
            _candidate("measure-count", "entity_count", "orders.id", "count_distinct"),
            _candidate("measure-sum", "total_amount", "orders.amount", "sum"),
        ],
        key=lambda item: item["candidate_id"],
    )
    artifact: dict[str, Any] = {
        "accepted_candidates": candidates,
        "catalog_version": "public-evidence-measure-catalog-v1",
        "generator": {
            "database_count": 1,
            "databases": ["orders_large"],
            "input_files": [],
            "version": "fixture-v1",
        },
        "kind": "public-evidence-measure-catalog",
        "manifest": {
            "ordered_candidate_ids": [item["candidate_id"] for item in candidates],
            "ordered_measure_ids": [item["measure_id"] for item in candidates],
        },
        "schema_version": 1,
        "source": {"decision_artifact_sha256": "1" * 64},
        "summary": {
            "accepted_candidate_count": 2,
            "accepted_database_count": 1,
            "accepted_databases": ["orders_large"],
            "candidate_count_by_class": {"entity_count": 2},
            "measure_count_by_database": {"orders_large": 2},
        },
    }
    artifact["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    return canonical_catalog_bytes(artifact)


def _schedule_bytes() -> bytes:
    ids = ["q1", "q2", "q3", "q4"]
    manifest = _jsonl(
        [
            {
                "instance_id": instance_id,
                "query": "Public fixture question.",
                "selected_database": "orders_large",
            }
            for instance_id in ids
        ]
    )
    dev_ids = "".join(f"{item}\n" for item in ids).encode()
    metadata = canonical_catalog_bytes(
        {
            "artifacts": {
                "dev_a_ids": {
                    "file": "dev_a_ids.txt",
                    "sha256": _sha256(dev_ids),
                }
            },
            "counts": {"dev_a": 4},
            "manifest": {
                "file": "eligible_questions.jsonl",
                "sha256": _sha256(manifest),
            },
            "schema_version": 1,
            "source": {"dataset": "fixture", "revision": "fixture-v1"},
        }
    )
    targets = canonical_catalog_bytes(
        {
            "databases": ["orders_large"],
            "kind": "r2-public-evidence-measure-targets",
            "schema_version": 1,
        }
    )
    schedule = build_r2_paired_schedule(
        manifest,
        dev_ids,
        metadata,
        targets,
        expected_dev_a_count=4,
        expected_pair_count=4,
        expected_database_count=1,
    )
    return canonical_catalog_bytes(schedule)


def _opportunity_bytes(catalog: bytes) -> bytes:
    decisions = [
        {
            "active_review_seconds": 1.0,
            "database": "orders_large",
            "decision": decision,
            "instance_id": instance_id,
            "measure_ids": measure_ids,
            "public_record_sha256": str(index) * 64,
            "question_sha256": str(index + 4) * 64,
        }
        for index, (instance_id, decision, measure_ids) in enumerate(
            [
                ("q1", "mapped", ["measure-count"]),
                ("q2", "mapped", ["measure-count"]),
                ("q3", "none", []),
                ("q4", "mapped", ["measure-sum"]),
            ],
            start=1,
        )
    ]
    artifact: dict[str, Any] = {
        "decisions": decisions,
        "kind": "public-evidence-measure-opportunity-map",
        "map_version": "r2-public-evidence-measure-opportunity-map-v1",
        "schema_version": 1,
        "source": {
            "accepted_catalog_path": (
                "experiments/r2-public-evidence-measures/"
                "public-evidence-measure-catalog-v1.json"
            ),
            "accepted_catalog_sha256": _sha256(catalog),
            "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
            "dev_a_ids_sha256": "a" * 64,
            "public_manifest_path": "data/manifests/eligible_questions.jsonl",
            "public_manifest_sha256": "b" * 64,
            "review_workbook_sha256": "c" * 64,
        },
        "summary": {
            "active_review_seconds": 4.0,
            "ambiguous_candidate_assignments": 0,
            "ambiguous_question_count": 0,
            "eligible_question_count": 4,
            "mapped_measure_assignments": 3,
            "mapped_question_count": 3,
            "none_question_count": 1,
            "opportunity_question_count": 3,
        },
    }
    artifact["manifest"] = {
        "ordered_instance_ids": [item["instance_id"] for item in decisions]
    }
    artifact["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    return canonical_catalog_bytes(artifact)


def _agent_opportunity_bytes(catalog: bytes) -> bytes:
    artifact = json.loads(_opportunity_bytes(catalog))
    artifact["adjudication"] = {
        "adjudicator": {
            "interface": "Codex",
            "model_family": "GPT-5",
            "product": "ChatGPT Work",
            "reasoning_effort": None,
            "reasoning_effort_status": "runtime_managed_not_exposed",
        },
        "status": "agent_adjudicated",
    }
    for decision in artifact["decisions"]:
        decision["active_review_seconds"] = None
    artifact["summary"]["active_review_seconds"] = None
    return _rehashed(artifact)


def _query(
    sql: str = "SELECT 1",
    *,
    fields: list[str] | None = None,
    calculations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "calculations": calculations or [],
        "fields": fields or [],
        "filters": {},
        "parsed": True,
        "pivots": [],
        "sorts": [],
        "userEditedSQL": sql,
    }


def _generation_bytes(
    schedule_bytes: bytes,
    condition: str,
    queries: dict[str, object],
    *,
    outcomes: dict[str, str] | None = None,
) -> bytes:
    schedule = json.loads(schedule_bytes)
    expected = [item for item in schedule["attempts"] if item["condition"] == condition]
    records = []
    for attempt in expected:
        instance_id = attempt["instance_id"]
        query = queries.get(instance_id, _query())
        generated_query = (
            query
            if isinstance(query, str) or query is None
            else json.dumps(query, separators=(",", ":"), sort_keys=True)
        )
        records.append(
            {
                "attempt_id": attempt["attempt_id"],
                "condition": condition,
                "generated_query": generated_query,
                "generation_outcome": (outcomes or {}).get(instance_id, "answered"),
                "instance_id": instance_id,
                "partition": "dev-a",
                "repetition": 1,
                "run_id": f"fixture-{condition.lower()}",
            }
        )
    return _jsonl(records)


def _inputs() -> dict[str, bytes]:
    catalog = _catalog_bytes()
    schedule = _schedule_bytes()
    control_queries = {
        "q1": _query("SELECT COUNT(DISTINCT ${orders.id}) FROM ${orders}"),
        "q2": _query("SELECT COUNT ( DISTINCT ${orders.id} ) FROM ${orders}"),
        "q3": _query("SELECT 1"),
        "q4": _query("SELECT ${orders.amount} FROM ${orders}"),
    }
    treatment_queries = {
        "q1": _query("SELECT ${orders.entity_count} FROM ${orders}"),
        "q2": _query(
            "SELECT ${orders.entity_count}, COUNT(DISTINCT ${orders.id}) FROM ${orders}"
        ),
        "q3": _query("SELECT 1"),
        "q4": _query("SELECT ${orders.total_amount} FROM ${orders}"),
    }
    return {
        "accepted_catalog_bytes": catalog,
        "opportunity_map_bytes": _opportunity_bytes(catalog),
        "schedule_bytes": schedule,
        "control_generation_bytes": _generation_bytes(
            schedule, "R2-C5B", control_queries
        ),
        "treatment_generation_bytes": _generation_bytes(
            schedule, "R2-M1", treatment_queries
        ),
    }


def _build(inputs: dict[str, bytes] | None = None) -> dict[str, Any]:
    values = inputs or _inputs()
    return build_r2_semantic_reuse_report(
        **values,
        expected_pair_count=4,
        expected_catalog_sha256=_sha256(values["accepted_catalog_bytes"]),
        expected_schedule_sha256=_sha256(values["schedule_bytes"]),
    )


def _rehashed(value: dict[str, Any]) -> bytes:
    value = copy.deepcopy(value)
    value["manifest"].pop("artifact_sha256", None)
    value["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(value))
    return canonical_catalog_bytes(value)


def test_report_classifies_primary_mechanism_and_itt_denominator() -> None:
    report = _build()

    assert report["kind"] == "r2-public-evidence-semantic-reuse-report"
    assert report["classifier_version"] == "r2_semantic_reuse_classifier_v1"
    assert report["summary"] == {
        "bridge_inline_equivalent_count": 2,
        "classification_counts": {
            "measure_reference_with_inline_recreation": 1,
            "measure_reference_without_bridge_inline": 1,
            "no_measure_reference": 0,
            "unresolved_both": 0,
            "unresolved_control": 0,
            "unresolved_treatment": 0,
            "verified_replacement": 1,
        },
        "opportunity_pair_count": 3,
        "parseable_sensitivity": {
            "denominator": 3,
            "rate": pytest.approx(1 / 3),
            "verified_replacement_count": 1,
            "wilson_95": report["summary"]["parseable_sensitivity"]["wilson_95"],
        },
        "scheduled_pair_count": 4,
        "treatment_inline_equivalent_count": 1,
        "treatment_measure_reference_count": 3,
        "unresolved_pair_count": 0,
        "verified_replacement_count": 1,
        "verified_replacement_rate": pytest.approx(1 / 3),
        "verified_replacement_wilson_95": report["summary"][
            "verified_replacement_wilson_95"
        ],
    }
    interval = report["summary"]["verified_replacement_wilson_95"]
    assert 0 < interval["lower"] < 1 / 3 < interval["upper"] < 1
    assert report["summary"]["parseable_sensitivity"]["wilson_95"] == interval


def test_report_accepts_null_time_only_for_agent_adjudicated_map() -> None:
    inputs = _inputs()
    inputs["opportunity_map_bytes"] = _agent_opportunity_bytes(
        inputs["accepted_catalog_bytes"]
    )

    assert _build(inputs)["summary"]["opportunity_pair_count"] == 3

    artifact = json.loads(inputs["opportunity_map_bytes"])
    artifact.pop("adjudication")
    inputs["opportunity_map_bytes"] = _rehashed(artifact)
    with pytest.raises(R2SemanticReuseError, match="review seconds"):
        _build(inputs)


def test_report_rejects_numeric_time_for_agent_adjudicated_map() -> None:
    inputs = _inputs()
    artifact = json.loads(_agent_opportunity_bytes(inputs["accepted_catalog_bytes"]))
    artifact["decisions"][0]["active_review_seconds"] = 0
    inputs["opportunity_map_bytes"] = _rehashed(artifact)

    with pytest.raises(R2SemanticReuseError, match="review seconds"):
        _build(inputs)


def test_report_is_aggregate_only_and_binds_exact_sources() -> None:
    inputs = _inputs()

    report = _build(inputs)

    assert report["source"] == {
        "accepted_catalog": {
            "path": (
                "experiments/r2-public-evidence-measures/"
                "public-evidence-measure-catalog-v1.json"
            ),
            "sha256": _sha256(inputs["accepted_catalog_bytes"]),
        },
        "control_generation": {
            "condition": "R2-C5B",
            "record_count": 4,
            "sha256": _sha256(inputs["control_generation_bytes"]),
        },
        "opportunity_map": {
            "path": (
                "experiments/r2-public-evidence-measures/"
                "measure-opportunity-map-v1.json"
            ),
            "sha256": _sha256(inputs["opportunity_map_bytes"]),
        },
        "paired_schedule": {
            "path": (
                "experiments/r2-public-evidence-measures/"
                "r2-paired-execution-schedule-v1.json"
            ),
            "sha256": _sha256(inputs["schedule_bytes"]),
        },
        "treatment_generation": {
            "condition": "R2-M1",
            "record_count": 4,
            "sha256": _sha256(inputs["treatment_generation_bytes"]),
        },
    }
    encoded = canonical_catalog_bytes(report)
    for forbidden in (
        b"q1",
        b"measure-count",
        b"instance_id",
        b"userEditedSQL",
        b"${orders",
        b'"correctness":',
        b'"outcome":',
        b'"result_value":',
    ):
        assert forbidden not in encoded
    assert len(report["manifest"]["classification_sha256"]) == 64


def test_structured_query_routes_detect_measure_and_inline_equivalent() -> None:
    inputs = _inputs()
    schedule = inputs["schedule_bytes"]
    aggregate = {
        "sql_expression": {
            "aggregate": {
                "distinct": True,
                "operands": [{"field_name": "orders.id", "type": "field"}],
                "operator": "SqlStdOperatorTable.COUNT",
                "type": "call",
            }
        }
    }
    control = {item: _query() for item in ("q1", "q2", "q3", "q4")}
    treatment = {item: _query() for item in ("q1", "q2", "q3", "q4")}
    control["q1"] = _query("", calculations=[aggregate])
    treatment["q1"] = _query("", fields=["orders.entity_count"])
    control["q2"] = _query("SELECT COUNT(DISTINCT ${orders.id})")
    treatment["q2"] = _query("SELECT 1")
    treatment["q4"] = _query("SELECT 1")
    inputs["control_generation_bytes"] = _generation_bytes(schedule, "R2-C5B", control)
    inputs["treatment_generation_bytes"] = _generation_bytes(
        schedule, "R2-M1", treatment
    )

    report = _build(inputs)

    assert report["summary"]["verified_replacement_count"] == 1
    assert report["summary"]["classification_counts"]["no_measure_reference"] == 2


@pytest.mark.parametrize(
    "treatment_query",
    [
        _query("", fields=["orders.entity_count"]),
        {
            **_query(""),
            "filters": {"orders": {"entity_count": {"type": "number"}}},
        },
        {**_query(""), "sorts": [{"column_name": "orders.entity_count"}]},
        _query(
            "",
            calculations=[{"sql_expression": {"field_name": "orders.entity_count"}}],
        ),
    ],
)
def test_execution_bearing_structured_measure_reference_routes(
    treatment_query: dict[str, Any],
) -> None:
    inputs = _inputs()
    schedule = inputs["schedule_bytes"]
    queries = {item: _query("SELECT 1") for item in ("q1", "q2", "q3", "q4")}
    queries["q1"] = treatment_query
    inputs["treatment_generation_bytes"] = _generation_bytes(schedule, "R2-M1", queries)

    report = _build(inputs)

    assert report["summary"]["treatment_measure_reference_count"] >= 1


def test_metadata_and_sql_literals_or_comments_do_not_count_as_references() -> None:
    inputs = _inputs()
    schedule = inputs["schedule_bytes"]
    queries = {item: _query("SELECT 1") for item in ("q1", "q2", "q3", "q4")}
    queries["q1"] = {
        **_query(
            "SELECT '${orders.entity_count}' AS literal -- ${orders.entity_count}\n"
            "FROM ${orders}"
        ),
        "metadata": {"orders": {"entity_count": {"label": "Count"}}},
    }
    inputs["treatment_generation_bytes"] = _generation_bytes(schedule, "R2-M1", queries)

    report = _build(inputs)

    assert report["summary"]["classification_counts"]["no_measure_reference"] >= 1


@pytest.mark.parametrize(
    ("condition", "expected_category"),
    [
        ("R2-C5B", "unresolved_control"),
        ("R2-M1", "unresolved_treatment"),
        ("both", "unresolved_both"),
    ],
)
def test_unparseable_or_errored_attempts_remain_in_primary_denominator(
    condition: str, expected_category: str
) -> None:
    inputs = _inputs()
    schedule = inputs["schedule_bytes"]
    normal = {item: _query("SELECT 1") for item in ("q1", "q2", "q3", "q4")}
    if condition in {"R2-C5B", "both"}:
        inputs["control_generation_bytes"] = _generation_bytes(
            schedule,
            "R2-C5B",
            normal,
            outcomes={"q1": "errored"},
        )
    if condition in {"R2-M1", "both"}:
        inputs["treatment_generation_bytes"] = _generation_bytes(
            schedule,
            "R2-M1",
            normal,
            outcomes={"q1": "errored"},
        )

    report = _build(inputs)

    assert report["summary"]["opportunity_pair_count"] == 3
    assert report["summary"]["unresolved_pair_count"] == 1
    assert report["summary"]["classification_counts"][expected_category] == 1
    assert report["summary"]["parseable_sensitivity"]["denominator"] == 2


def test_unclosed_sql_literal_is_unresolved_not_a_false_reference() -> None:
    inputs = _inputs()
    schedule = inputs["schedule_bytes"]
    queries = {item: _query() for item in ("q1", "q2", "q3", "q4")}
    queries["q1"] = _query("SELECT '${orders.entity_count}")
    inputs["treatment_generation_bytes"] = _generation_bytes(schedule, "R2-M1", queries)

    report = _build(inputs)

    assert report["summary"]["classification_counts"]["unresolved_treatment"] == 1


@pytest.mark.parametrize(
    ("aggregate_type", "sql", "operator", "distinct"),
    [
        ("sum", "SELECT SUM(${orders.amount})", "SqlStdOperatorTable.SUM", False),
        (
            "average",
            "SELECT AVERAGE ( ${orders.amount} )",
            "SqlStdOperatorTable.AVG",
            False,
        ),
        (
            "count_distinct",
            "SELECT COUNT(DISTINCT ${orders.amount})",
            "count_distinct",
            False,
        ),
    ],
)
def test_frozen_aggregate_forms_match_sql_and_structured_ast(
    aggregate_type: str, sql: str, operator: str, distinct: bool
) -> None:
    measure = _Measure(
        aggregate_type=aggregate_type,
        database="orders_large",
        measure_id="measure",
        measure_reference="orders.metric",
        source_reference="orders.amount",
    )
    node = {
        "distinct": distinct,
        "operands": [{"field_name": "orders.amount"}],
        "operator": operator,
    }

    assert _sql_has_inline(sql, measure)
    assert _aggregate_matches(node, measure)
    assert not _aggregate_matches({**node, "operands": []}, measure)
    assert not _aggregate_matches({**node, "operator": 1}, measure)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("SELECT 1 -- ${orders.metric}", "SELECT 1"),
        (
            "SELECT /* outer /* inner */ ${orders.metric} */ 1",
            "SELECT 1",
        ),
        ("SELECT 'it''s ${orders.metric}'", "SELECT"),
        ("SELECT 'a\\'b ${orders.metric}'", "SELECT"),
        ("SELECT $tag$${orders.metric}$tag$", "SELECT"),
        ("SELECT /* unclosed", None),
        ("SELECT $tag$unclosed", None),
    ],
)
def test_sql_lexer_excludes_nonexecuting_text_and_rejects_unclosed_regions(
    sql: str, expected: str | None
) -> None:
    observed = _lexical_sql(sql)
    if expected is None:
        assert observed is None
    else:
        assert observed is not None
        assert len(observed) == len(sql)
        assert "${orders.metric}" not in observed
        assert " ".join(observed.split()) == expected


@pytest.mark.parametrize(
    "query",
    [
        "not-json",
        None,
        {**_query(), "parsed": False},
        {**_query(), "userEditedSQL": 1},
        {**_query(), "fields": {}},
        {**_query(), "sorts": {}},
        {**_query(), "filters": []},
        {**_query(), "calculations": {}},
        _query("", calculations=[{"aggregate": "not-an-object"}]),
    ],
)
def test_malformed_query_surfaces_are_unresolved_sensitivity_exclusions(
    query: object,
) -> None:
    inputs = _inputs()
    schedule = inputs["schedule_bytes"]
    queries = {item: _query() for item in ("q1", "q2", "q3", "q4")}
    queries["q1"] = query
    inputs["treatment_generation_bytes"] = _generation_bytes(schedule, "R2-M1", queries)

    report = _build(inputs)

    assert report["summary"]["classification_counts"]["unresolved_treatment"] == 1
    assert report["summary"]["parseable_sensitivity"]["denominator"] == 2


def test_empty_parseable_sensitivity_has_no_rate_or_interval() -> None:
    inputs = _inputs()
    schedule = inputs["schedule_bytes"]
    outcomes = {"q1": "errored", "q2": "errored", "q4": "errored"}
    queries = {item: _query() for item in ("q1", "q2", "q3", "q4")}
    inputs["control_generation_bytes"] = _generation_bytes(
        schedule, "R2-C5B", queries, outcomes=outcomes
    )
    inputs["treatment_generation_bytes"] = _generation_bytes(
        schedule, "R2-M1", queries, outcomes=outcomes
    )

    report = _build(inputs)

    assert report["summary"]["parseable_sensitivity"] == {
        "denominator": 0,
        "rate": None,
        "verified_replacement_count": 0,
        "wilson_95": None,
    }
    assert _wilson_interval(0, 0) is None


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("catalog_hash", "accepted catalog hash"),
        ("schedule_hash", "paired schedule hash"),
        ("map_catalog", "opportunity map catalog hash"),
        ("map_digest", "opportunity map hash"),
        ("unknown_measure", "unknown measure"),
        ("wrong_database", "question database"),
        ("empty_opportunity", "no mapped opportunity"),
        ("missing_attempt", "complete scheduled arm"),
        ("duplicate_attempt", "duplicate attempt"),
        ("condition", "condition"),
        ("attempt_id", "attempt identity"),
        ("partition", "dev-a"),
        ("repetition", "repetition"),
        ("protected", "protected field"),
        ("scored", "scored field"),
        ("bad_jsonl", "valid JSON"),
        ("not_terminated", "newline-terminated"),
    ],
)
def test_classifier_rejects_drift_incomplete_evidence_and_forbidden_inputs(
    mutation: str, message: str
) -> None:
    inputs = _inputs()
    expected_catalog_sha256 = _sha256(inputs["accepted_catalog_bytes"])
    expected_schedule_sha256 = _sha256(inputs["schedule_bytes"])
    if mutation == "catalog_hash":
        expected_catalog_sha256 = "0" * 64
    elif mutation == "schedule_hash":
        expected_schedule_sha256 = "0" * 64
    elif mutation.startswith("map_") or mutation in {
        "unknown_measure",
        "wrong_database",
        "empty_opportunity",
    }:
        value = json.loads(inputs["opportunity_map_bytes"])
        if mutation == "map_catalog":
            value["source"]["accepted_catalog_sha256"] = "0" * 64
        elif mutation == "unknown_measure":
            value["decisions"][0]["measure_ids"] = ["unknown"]
        elif mutation == "wrong_database":
            value["decisions"][0]["database"] = "other_large"
        elif mutation == "empty_opportunity":
            for decision in value["decisions"]:
                decision["decision"] = "none"
                decision["measure_ids"] = []
            value["summary"]["mapped_question_count"] = 0
            value["summary"]["opportunity_question_count"] = 0
            value["summary"]["mapped_measure_assignments"] = 0
            value["summary"]["none_question_count"] = 4
        if mutation != "map_digest":
            inputs["opportunity_map_bytes"] = _rehashed(value)
        else:
            value["summary"]["active_review_seconds"] = 99
            inputs["opportunity_map_bytes"] = canonical_catalog_bytes(value)
    elif mutation in {"bad_jsonl", "not_terminated"}:
        inputs["control_generation_bytes"] = (
            b"not-json\n"
            if mutation == "bad_jsonl"
            else inputs["control_generation_bytes"].rstrip(b"\n")
        )
    else:
        records = [
            json.loads(line) for line in inputs["control_generation_bytes"].splitlines()
        ]
        if mutation == "missing_attempt":
            records.pop()
        elif mutation == "duplicate_attempt":
            records[-1] = copy.deepcopy(records[0])
        elif mutation == "condition":
            records[0]["condition"] = "R2-M1"
        elif mutation == "attempt_id":
            records[0]["attempt_id"] = "changed"
        elif mutation == "partition":
            records[0]["partition"] = "dev-b"
        elif mutation == "repetition":
            records[0]["repetition"] = 2
        elif mutation == "protected":
            records[0]["gold_sql"] = "SELECT 1"
        else:
            records[0]["outcome"] = "correct"
        inputs["control_generation_bytes"] = _jsonl(records)

    with pytest.raises(R2SemanticReuseError, match=message):
        build_r2_semantic_reuse_report(
            **inputs,
            expected_pair_count=4,
            expected_catalog_sha256=expected_catalog_sha256,
            expected_schedule_sha256=expected_schedule_sha256,
        )


def test_validator_rejects_changed_report_and_writer_is_append_only(
    tmp_path: Path,
) -> None:
    inputs = _inputs()
    report = _build(inputs)
    content = canonical_catalog_bytes(report)

    assert (
        validate_r2_semantic_reuse_report(
            content,
            **inputs,
            expected_pair_count=4,
            expected_catalog_sha256=_sha256(inputs["accepted_catalog_bytes"]),
            expected_schedule_sha256=_sha256(inputs["schedule_bytes"]),
        )
        == report
    )
    changed = copy.deepcopy(report)
    changed["summary"]["verified_replacement_count"] = 2
    with pytest.raises(R2SemanticReuseError, match="does not reproduce"):
        validate_r2_semantic_reuse_report(
            canonical_catalog_bytes(changed),
            **inputs,
            expected_pair_count=4,
            expected_catalog_sha256=_sha256(inputs["accepted_catalog_bytes"]),
            expected_schedule_sha256=_sha256(inputs["schedule_bytes"]),
        )

    destination = tmp_path / "report.json"
    write_r2_semantic_reuse_report(destination, report)
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.read_bytes() == content
    with pytest.raises(R2SemanticReuseError, match="already exists"):
        write_r2_semantic_reuse_report(destination, report)


def test_cli_writes_and_reports_only_bounded_aggregate_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = _inputs()
    paths: dict[str, Path] = {}
    for name, content in inputs.items():
        path = tmp_path / name
        path.write_bytes(content)
        paths[name] = path
    output = tmp_path / "report.json"

    result = reuse_cli.main(
        [
            "--accepted-catalog",
            str(paths["accepted_catalog_bytes"]),
            "--opportunity-map",
            str(paths["opportunity_map_bytes"]),
            "--paired-schedule",
            str(paths["schedule_bytes"]),
            "--control-generation",
            str(paths["control_generation_bytes"]),
            "--treatment-generation",
            str(paths["treatment_generation_bytes"]),
            "--output",
            str(output),
            "--expected-pair-count",
            "4",
            "--expected-catalog-sha256",
            _sha256(inputs["accepted_catalog_bytes"]),
            "--expected-schedule-sha256",
            _sha256(inputs["schedule_bytes"]),
        ]
    )

    assert result == 0
    assert output.stat().st_mode & 0o777 == 0o600
    report = validate_r2_semantic_reuse_report(
        output.read_bytes(),
        **inputs,
        expected_pair_count=4,
        expected_catalog_sha256=_sha256(inputs["accepted_catalog_bytes"]),
        expected_schedule_sha256=_sha256(inputs["schedule_bytes"]),
    )
    assert json.loads(capsys.readouterr().out) == {
        "artifact_sha256": report["manifest"]["artifact_sha256"],
        "opportunity_pair_count": 3,
        "output": str(output),
        "unresolved_pair_count": 0,
        "verified_replacement_count": 1,
        "verified_replacement_rate": pytest.approx(1 / 3),
    }


def test_classifier_freeze_manifest_binds_exact_policy_code_and_fixtures() -> None:
    path = (
        REPOSITORY_ROOT / "experiments/r2-public-evidence-measures/"
        "r2-semantic-reuse-classifier-freeze-v2.json"
    )
    content = path.read_bytes()
    value = json.loads(content)

    assert content == canonical_catalog_bytes(value)
    assert value["kind"] == "r2-semantic-reuse-classifier-freeze"
    assert value["schema_version"] == 1
    assert value["classifier_version"] == "r2_semantic_reuse_classifier_v1"
    assert value["pins"] == {
        "accepted_catalog_sha256": (
            "2d2f9c15bc5f5271db924fa4377b41c26a0e61bcec221ed31d10b3365358039a"
        ),
        "opportunity_map_sha256": (
            "b834ebb7e2a033a85c0befc6eeba5949d40b71f5c3643da2ddb5f35c66afe279"
        ),
        "paired_schedule_sha256": (
            "8498c35e062dd893d1f20eda503bb65c95603b94c5fdd5fa2a87a8c7ccc27bda"
        ),
    }
    assert value["policy"] == {
        "aggregate_forms": ["average", "count_distinct", "sum"],
        "classifier": "deterministic_exact_structure_and_lexical_match",
        "denominator": "all_mapped_scheduled_pairs",
        "interval": "wilson_95_two_sided",
        "llm_adjudication": "prohibited",
        "opportunity_review_time": ("null_only_for_exact_agent_adjudication_identity"),
        "parseable_pairs": "labeled_sensitivity_only",
        "unresolved_primary_value": "not_verified_replacement",
    }
    assert value["supersedes"] == {
        "internal_artifact_sha256": (
            "b96fc524c07ed924dcd8ade478a67fc3afcdc46122a70d8b9976d0e2f7061a78"
        ),
        "path": (
            "experiments/r2-public-evidence-measures/"
            "r2-semantic-reuse-classifier-freeze-v1.json"
        ),
        "sha256": ("465dcb0f69efab75146e8cd180a68ea85da3ad8472ce05fe8bf36a8109d345c1"),
    }
    files = value["files"]
    assert [item["path"] for item in files] == [
        "src/omni_benchmark/r2_semantic_reuse.py",
        "src/omni_benchmark/r2_semantic_reuse_cli.py",
        "tests/test_r2_semantic_reuse.py",
    ]
    for item in files:
        file_content = (REPOSITORY_ROOT / item["path"]).read_bytes()
        assert item == {
            "path": item["path"],
            "sha256": _sha256(file_content),
            "size_bytes": len(file_content),
        }
    digest_source = copy.deepcopy(value)
    digest_source["manifest"].pop("artifact_sha256")
    assert value["manifest"] == {
        "artifact_sha256": _sha256(canonical_catalog_bytes(digest_source))
    }

"""Frozen aggregate analysis for the paired R2 measures study."""

from __future__ import annotations

import copy
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.measure_review_catalog import canonical_catalog_bytes
from omni_benchmark.r2_paired_outcomes import (
    ANALYSIS_VERSION,
    BOOTSTRAP_REPLICATES,
    BOOTSTRAP_SEED,
    R2PairedOutcomeError,
    build_r2_paired_outcome_report,
    validate_r2_paired_outcome_report,
    write_r2_paired_outcome_report,
)
from omni_benchmark.r2_paired_outcomes_cli import main
from omni_benchmark.r2_paired_schedule import (
    CONTROL_CONDITION,
    TREATMENT_CONDITION,
    build_r2_paired_schedule,
)
from omni_benchmark.scoring import (
    OFFICIAL_SOFT_EX_VERSION,
    SENSITIVITY_SCORER_VERSION,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _jsonl(records: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_catalog_bytes(record) for record in records)


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


def _generation_bytes(
    schedule_bytes: bytes,
    condition: str,
    *,
    costs: dict[str, float | None] | None = None,
    outcomes: dict[str, str] | None = None,
) -> bytes:
    schedule = json.loads(schedule_bytes)
    selected = [item for item in schedule["attempts"] if item["condition"] == condition]
    records = []
    for index, attempt in enumerate(selected, start=1):
        instance_id = attempt["instance_id"]
        generation_outcome = (outcomes or {}).get(instance_id, "answered")
        cost = (costs or {}).get(instance_id, float(index))
        records.append(
            {
                "attempt_id": attempt["attempt_id"],
                "condition": condition,
                "cost_unavailable_reason": (
                    None if cost is not None else "credit_usage_unavailable"
                ),
                "cost_usd": cost,
                "database_query_count": index,
                "generated_query": '{"parsed":true,"userEditedSQL":"SELECT 1"}',
                "generation_outcome": generation_outcome,
                "instance_id": instance_id,
                "latency_ms": float(index * 100),
                "partition": "dev-a",
                "repetition": 1,
                "run_id": f"fixture-{condition.lower()}",
                "terminal_failure_class": (
                    None
                    if generation_outcome == "answered"
                    else "response_contract_error"
                ),
                "token_usage": {
                    "input_tokens": index * 10,
                    "output_tokens": index * 2,
                    "total_tokens": index * 12,
                },
                "tool_call_count": index + 1,
                "validation_attempt_count": index - 1,
            }
        )
    return _jsonl(records)


def _score_bytes(
    generation_bytes: bytes,
    outcomes: dict[str, str],
    *,
    identity: str,
    version: str,
    path: str,
) -> bytes:
    records = generation_bytes.splitlines(keepends=True)
    attempts = []
    for raw in records:
        record = json.loads(raw)
        outcome = outcomes[record["instance_id"]]
        score: dict[str, Any] = {
            "attempt_id": record["attempt_id"],
            "generation_record_sha256": _sha256(raw),
            "outcome": outcome,
        }
        if outcome == "refused_or_error":
            score["failure_category"] = "agent_refusal"
        attempts.append(score)
    return canonical_catalog_bytes(
        {
            "attempts": attempts,
            "generation": {"path": path, "sha256": _sha256(generation_bytes)},
            "schema_version": "score-artifact-v1",
            "scorer": {"identity": identity, "version": version},
        }
    )


def _inputs() -> dict[str, bytes]:
    schedule = _schedule_bytes()
    control = _generation_bytes(
        schedule,
        CONTROL_CONDITION,
        outcomes={"q4": "errored"},
    )
    treatment = _generation_bytes(schedule, TREATMENT_CONDITION)
    official_control = {
        "q1": "correct",
        "q2": "wrong_answer",
        "q3": "correct",
        "q4": "refused_or_error",
    }
    official_treatment = {
        "q1": "correct",
        "q2": "correct",
        "q3": "wrong_answer",
        "q4": "correct",
    }
    sensitivity_control = {
        "q1": "correct",
        "q2": "correct",
        "q3": "wrong_answer",
        "q4": "refused_or_error",
    }
    sensitivity_treatment = {
        "q1": "correct",
        "q2": "correct",
        "q3": "correct",
        "q4": "wrong_answer",
    }
    return {
        "schedule_bytes": schedule,
        "control_generation_bytes": control,
        "treatment_generation_bytes": treatment,
        "control_official_score_bytes": _score_bytes(
            control,
            official_control,
            identity="official_soft_ex",
            version=OFFICIAL_SOFT_EX_VERSION,
            path="runs/r2-control/generation.jsonl",
        ),
        "control_sensitivity_score_bytes": _score_bytes(
            control,
            sensitivity_control,
            identity="sensitivity",
            version=SENSITIVITY_SCORER_VERSION,
            path="runs/r2-control/generation.jsonl",
        ),
        "treatment_official_score_bytes": _score_bytes(
            treatment,
            official_treatment,
            identity="official_soft_ex",
            version=OFFICIAL_SOFT_EX_VERSION,
            path="runs/r2-treatment/generation.jsonl",
        ),
        "treatment_sensitivity_score_bytes": _score_bytes(
            treatment,
            sensitivity_treatment,
            identity="sensitivity",
            version=SENSITIVITY_SCORER_VERSION,
            path="runs/r2-treatment/generation.jsonl",
        ),
    }


def _build(
    inputs: dict[str, bytes] | None = None,
    *,
    expected_schedule_sha256: str | None = None,
) -> dict[str, Any]:
    values = inputs or _inputs()
    return build_r2_paired_outcome_report(
        **values,
        expected_pair_count=4,
        expected_schedule_sha256=(
            expected_schedule_sha256 or _sha256(values["schedule_bytes"])
        ),
    )


def test_report_contains_fixed_paired_secondary_endpoints() -> None:
    report = _build()

    assert report["kind"] == "r2-public-evidence-paired-outcome-report"
    assert report["analysis_version"] == ANALYSIS_VERSION
    assert report["bootstrap"] == {
        "ci_level": 0.95,
        "interval": "percentile_nearest_rank",
        "replicates": BOOTSTRAP_REPLICATES,
        "sampler": "sha256_modulo_question_count_v1",
        "seed": BOOTSTRAP_SEED,
    }
    official = report["scorers"]["official_soft_ex"]
    assert official["arms"][CONTROL_CONDITION]["accuracy"] == pytest.approx(0.5)
    assert official["arms"][TREATMENT_CONDITION]["accuracy"] == pytest.approx(0.75)
    assert official["paired_accuracy"]["estimate"] == pytest.approx(0.25)
    assert official["paired_accuracy"]["discordant_gains"] == 2
    assert official["paired_accuracy"]["discordant_losses"] == 1
    assert official["paired_accuracy"]["pair_count"] == 4
    assert official["arms"][CONTROL_CONDITION][
        "cost_per_correct_attempt"
    ] == pytest.approx(5.0)
    assert report["paired_cost"]["estimate"] == pytest.approx(0.0)
    assert report["paired_cost"]["status"] == "complete"


def test_report_counts_generation_reliability_and_complete_telemetry() -> None:
    report = _build()
    control = report["generation"][CONTROL_CONDITION]

    assert control["scheduled_attempts"] == 4
    assert control["generation_outcomes"] == {
        "answered": 3,
        "errored": 1,
        "refused": 0,
    }
    assert control["terminal_failure_classes"] == {"response_contract_error": 1}
    assert control["result_contract_failure_count"] == 1
    assert control["telemetry"] == {
        "cost_observed_attempts": 4,
        "cost_per_answered_attempt": pytest.approx(10 / 3),
        "cost_per_scheduled_attempt": pytest.approx(2.5),
        "cost_unavailable_count": 0,
        "database_query_count": 10,
        "iqr_latency_ms": pytest.approx(150.0),
        "median_latency_ms": pytest.approx(250.0),
        "token_count": 120,
        "tool_call_count": 14,
        "total_cost_usd": pytest.approx(10.0),
        "validation_attempt_count": 6,
    }


def test_bootstrap_is_deterministic_and_uses_fixed_seed() -> None:
    first = _build()
    second = _build()

    assert canonical_catalog_bytes(first) == canonical_catalog_bytes(second)
    interval = first["scorers"]["official_soft_ex"]["paired_accuracy"]
    assert interval["lower"] <= interval["estimate"] <= interval["upper"]
    assert first["manifest"]["artifact_sha256"] == second["manifest"]["artifact_sha256"]


def test_report_is_aggregate_only_and_binds_every_input() -> None:
    inputs = _inputs()
    report = _build(inputs)
    rendered = json.dumps(report, sort_keys=True)

    for identity in ("q1", "q2", "q3", "q4", "r2attempt-", "SELECT 1"):
        assert identity not in rendered
    assert report["information_boundary"] == {
        "emits_attempt_level_outcomes": False,
        "emits_question_level_outcomes": False,
        "hidden_annotations_used": False,
        "question_text_used": False,
        "result_values_used": False,
        "sealed_test_used": False,
    }
    assert report["source"]["paired_schedule"]["sha256"] == _sha256(
        inputs["schedule_bytes"]
    )
    assert report["source"]["generations"][CONTROL_CONDITION]["sha256"] == _sha256(
        inputs["control_generation_bytes"]
    )
    assert report["source"]["score_artifacts"]["official_soft_ex"][TREATMENT_CONDITION][
        "sha256"
    ] == _sha256(inputs["treatment_official_score_bytes"])


def test_incomplete_cost_propagates_null_without_dropping_pairs() -> None:
    inputs = _inputs()
    schedule = inputs["schedule_bytes"]
    treatment = _generation_bytes(
        schedule,
        TREATMENT_CONDITION,
        costs={"q2": None},
    )
    inputs["treatment_generation_bytes"] = treatment
    for key, identity, version in (
        (
            "treatment_official_score_bytes",
            "official_soft_ex",
            OFFICIAL_SOFT_EX_VERSION,
        ),
        (
            "treatment_sensitivity_score_bytes",
            "sensitivity",
            SENSITIVITY_SCORER_VERSION,
        ),
    ):
        old = json.loads(inputs[key])
        outcomes = {
            attempt["attempt_id"]: attempt["outcome"] for attempt in old["attempts"]
        }
        records = treatment.splitlines(keepends=True)
        attempts = []
        for raw in records:
            record = json.loads(raw)
            attempts.append(
                {
                    "attempt_id": record["attempt_id"],
                    "generation_record_sha256": _sha256(raw),
                    "outcome": outcomes[record["attempt_id"]],
                }
            )
        inputs[key] = canonical_catalog_bytes(
            {
                "attempts": attempts,
                "generation": {
                    "path": old["generation"]["path"],
                    "sha256": _sha256(treatment),
                },
                "schema_version": "score-artifact-v1",
                "scorer": {"identity": identity, "version": version},
            }
        )

    report = _build(inputs)

    telemetry = report["generation"][TREATMENT_CONDITION]["telemetry"]
    assert telemetry["cost_observed_attempts"] == 3
    assert telemetry["cost_unavailable_count"] == 1
    assert telemetry["total_cost_usd"] is None
    assert telemetry["cost_per_scheduled_attempt"] is None
    assert report["paired_cost"] == {
        "complete_pair_count": 3,
        "estimate": None,
        "lower": None,
        "pair_count": 4,
        "status": "unavailable_incomplete_cost",
        "upper": None,
    }
    for scorer in report["scorers"].values():
        assert scorer["arms"][TREATMENT_CONDITION]["cost_per_correct_attempt"] is None


@pytest.mark.parametrize(
    ("key", "message"),
    [
        ("control_generation_bytes", "generation attempt identity"),
        ("control_official_score_bytes", "score artifact"),
        ("schedule_bytes", "schedule hash"),
    ],
)
def test_exact_input_bindings_reject_mutation(key: str, message: str) -> None:
    inputs = _inputs()
    expected_schedule_sha256 = _sha256(inputs["schedule_bytes"])
    if key == "control_generation_bytes":
        records = inputs[key].splitlines(keepends=True)
        changed = json.loads(records[0])
        changed["attempt_id"] = "unexpected"
        inputs[key] = canonical_catalog_bytes(changed) + b"".join(records[1:])
    elif key == "control_official_score_bytes":
        score = json.loads(inputs[key])
        score["attempts"][0]["generation_record_sha256"] = "f" * 64
        inputs[key] = canonical_catalog_bytes(score)
    else:
        schedule = json.loads(inputs[key])
        schedule["schedule_version"] = "changed"
        inputs[key] = canonical_catalog_bytes(schedule)

    with pytest.raises(R2PairedOutcomeError, match=message):
        _build(inputs, expected_schedule_sha256=expected_schedule_sha256)


def test_rejects_wrong_scorer_duplicate_score_and_noncanonical_json() -> None:
    inputs = _inputs()
    score = json.loads(inputs["control_official_score_bytes"])
    score["scorer"]["version"] = "wrong"
    inputs["control_official_score_bytes"] = canonical_catalog_bytes(score)
    with pytest.raises(R2PairedOutcomeError, match="frozen scorer"):
        _build(inputs)

    inputs = _inputs()
    score = json.loads(inputs["control_official_score_bytes"])
    score["attempts"][1] = copy.deepcopy(score["attempts"][0])
    inputs["control_official_score_bytes"] = canonical_catalog_bytes(score)
    with pytest.raises(R2PairedOutcomeError, match="duplicate score attempt"):
        _build(inputs)

    inputs = _inputs()
    score = json.loads(inputs["control_official_score_bytes"])
    inputs["control_official_score_bytes"] = json.dumps(score, indent=2).encode()
    with pytest.raises(R2PairedOutcomeError, match="canonical JSON"):
        _build(inputs)


def test_rejects_incomplete_score_and_invalid_generation_telemetry() -> None:
    inputs = _inputs()
    score = json.loads(inputs["treatment_sensitivity_score_bytes"])
    score["attempts"].pop()
    inputs["treatment_sensitivity_score_bytes"] = canonical_catalog_bytes(score)
    with pytest.raises(R2PairedOutcomeError, match="complete scheduled arm"):
        _build(inputs)

    inputs = _inputs()
    records = inputs["control_generation_bytes"].splitlines(keepends=True)
    changed = json.loads(records[0])
    changed["latency_ms"] = -1
    inputs["control_generation_bytes"] = canonical_catalog_bytes(changed) + b"".join(
        records[1:]
    )
    with pytest.raises(R2PairedOutcomeError, match="latency_ms"):
        _build(inputs)


def test_rejects_protected_or_scored_generation_fields() -> None:
    for field in ("gold_sql", "outcome"):
        inputs = _inputs()
        records = inputs["control_generation_bytes"].splitlines(keepends=True)
        changed = json.loads(records[0])
        changed[field] = "forbidden"
        inputs["control_generation_bytes"] = canonical_catalog_bytes(
            changed
        ) + b"".join(records[1:])
        with pytest.raises(R2PairedOutcomeError, match="protected|scored field"):
            _build(inputs)


def test_validate_reproduces_exact_report_and_rejects_changed_output() -> None:
    inputs = _inputs()
    report = _build(inputs)
    content = canonical_catalog_bytes(report)

    assert (
        validate_r2_paired_outcome_report(
            content,
            **inputs,
            expected_pair_count=4,
            expected_schedule_sha256=_sha256(inputs["schedule_bytes"]),
        )
        == report
    )
    changed = copy.deepcopy(report)
    changed["paired_cost"]["estimate"] = 99
    changed["manifest"].pop("artifact_sha256")
    changed["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(changed))
    with pytest.raises(R2PairedOutcomeError, match="does not reproduce"):
        validate_r2_paired_outcome_report(
            canonical_catalog_bytes(changed),
            **inputs,
            expected_pair_count=4,
            expected_schedule_sha256=_sha256(inputs["schedule_bytes"]),
        )


def test_write_is_mode_0600_append_only(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    report = _build()

    write_r2_paired_outcome_report(output, report)

    assert output.read_bytes() == canonical_catalog_bytes(report)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(R2PairedOutcomeError, match="exists"):
        write_r2_paired_outcome_report(output, report)


def test_cli_reads_bounded_files_and_prints_aggregate_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = _inputs()
    paths: dict[str, Path] = {}
    for name, content in inputs.items():
        path = tmp_path / name
        path.write_bytes(content)
        paths[name] = path
    output = tmp_path / "report.json"

    assert (
        main(
            [
                "--paired-schedule",
                str(paths["schedule_bytes"]),
                "--control-generation",
                str(paths["control_generation_bytes"]),
                "--treatment-generation",
                str(paths["treatment_generation_bytes"]),
                "--control-official-score",
                str(paths["control_official_score_bytes"]),
                "--control-sensitivity-score",
                str(paths["control_sensitivity_score_bytes"]),
                "--treatment-official-score",
                str(paths["treatment_official_score_bytes"]),
                "--treatment-sensitivity-score",
                str(paths["treatment_sensitivity_score_bytes"]),
                "--output",
                str(output),
                "--expected-pair-count",
                "4",
                "--expected-schedule-sha256",
                _sha256(inputs["schedule_bytes"]),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == {
        "artifact_sha256",
        "official_accuracy_delta",
        "output",
        "pair_count",
        "sensitivity_accuracy_delta",
    }
    assert output.exists()


def test_cli_rejects_symlink_input(tmp_path: Path) -> None:
    target = tmp_path / "schedule.json"
    target.write_bytes(_schedule_bytes())
    link = tmp_path / "schedule-link.json"
    link.symlink_to(target)

    with pytest.raises(R2PairedOutcomeError, match="regular.*file"):
        main(
            [
                "--paired-schedule",
                str(link),
                "--control-generation",
                str(target),
                "--treatment-generation",
                str(target),
                "--control-official-score",
                str(target),
                "--control-sensitivity-score",
                str(target),
                "--treatment-official-score",
                str(target),
                "--treatment-sensitivity-score",
                str(target),
                "--output",
                str(tmp_path / "output.json"),
            ]
        )


def test_analysis_freeze_manifest_binds_exact_policy_code_and_fixtures() -> None:
    path = (
        REPOSITORY_ROOT / "experiments/r2-public-evidence-measures/"
        "r2-paired-outcome-analysis-freeze-v1.json"
    )
    content = path.read_bytes()
    value = json.loads(content)

    assert content == canonical_catalog_bytes(value)
    assert value["kind"] == "r2-paired-outcome-analysis-freeze"
    assert value["schema_version"] == 1
    assert value["analysis_version"] == ANALYSIS_VERSION
    assert value["pins"] == {
        "official_scorer_version": OFFICIAL_SOFT_EX_VERSION,
        "paired_schedule_sha256": (
            "8498c35e062dd893d1f20eda503bb65c95603b94c5fdd5fa2a87a8c7ccc27bda"
        ),
        "sensitivity_scorer_version": SENSITIVITY_SCORER_VERSION,
    }
    assert value["policy"] == {
        "accuracy_denominator": "all_scheduled_pairs",
        "bootstrap_interval": "percentile_nearest_rank_95",
        "bootstrap_replicates": 10_000,
        "bootstrap_sampler": "sha256_modulo_question_count_v1",
        "bootstrap_seed": BOOTSTRAP_SEED,
        "cost_completeness": "all_scheduled_attempts_or_null",
        "cost_contrast": "treatment_minus_control_complete_pairs_only",
        "efficiency_claims": "require_comparable_output_coverage",
        "output": "aggregate_only_no_question_or_attempt_outcomes",
        "result_contract_failure_classes": [
            "response_contract_error",
            "result_contract_error",
            "unsupported_semantic_result_type",
        ],
        "scorers": "both_frozen_always_reported",
    }
    files = value["files"]
    assert [item["path"] for item in files] == [
        "src/omni_benchmark/r2_paired_outcomes.py",
        "src/omni_benchmark/r2_paired_outcomes_cli.py",
        "tests/test_r2_paired_outcomes.py",
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

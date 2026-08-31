from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


def _analysis_module():
    path = (
        Path(__file__).parents[1]
        / "experiments"
        / "analysis"
        / "e02_partial_diagnostic.py"
    )
    spec = importlib.util.spec_from_file_location("e02_partial_diagnostic", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _entry(attempt_id: str, outcome: str) -> dict[str, object]:
    _, instance_id, _, repetition = attempt_id.split(":")
    return {
        "attempt_id": attempt_id,
        "condition": "C4",
        "database": "alpha" if instance_id != "q3" else "beta",
        "generation_outcome": outcome,
        "generation_record_sha256": "a" * 64,
        "generation_sha256": "b" * 64,
        "instance_id": instance_id,
        "repetition": int(repetition),
        "run_manifest_sha256": "d" * 64,
    }


def _selection() -> dict[str, object]:
    entries = [
        _entry("e02:q1:C4:1", "answered"),
        _entry("e02:q2:C4:1", "errored"),
        _entry("e02:q3:C4:1", "errored"),
    ]
    return {
        "schema_version": "e02-dev-a-c4-freeze-v1",
        "run_id": "e02",
        "entries": entries,
        "scheduled_entries": [
            {
                key: entry[key]
                for key in (
                    "attempt_id",
                    "condition",
                    "database",
                    "instance_id",
                    "repetition",
                )
            }
            for entry in entries
        ],
        "counts": {
            "answerable_attempts": 3,
            "attempts": 3,
            "answered": 1,
            "databases": 2,
            "errored": 2,
            "refused": 0,
            "scheduled_attempts": 3,
            "scheduled_databases": 2,
            "unscorable_attempts": 0,
        },
    }


def _generations() -> dict[str, dict[str, object]]:
    return {
        "e02:q1:C4:1": {"generation_outcome": "answered"},
        "e02:q2:C4:1": {
            "generation_outcome": "errored",
            "failure_origin": "benchmark_infrastructure",
            "terminal_failure_class": "unsupported_semantic_result_type",
            "generated_query": {"fields": ["safe_field"]},
        },
        "e02:q3:C4:1": {
            "generation_outcome": "errored",
            "failure_origin": "benchmark_infrastructure",
            "terminal_failure_class": "adapter_transport_error",
        },
    }


def _score(run_id: str, outcomes: list[object]) -> dict[str, object]:
    question_ids = ("q1", "q2", "q3")[: len(outcomes)]
    return {
        "attempts": [
            {
                "attempt_id": f"{run_id}:{question_id}:C4:1",
                "outcome": outcome,
            }
            for question_id, outcome in zip(question_ids, outcomes, strict=True)
        ]
    }


def test_derive_answered_selection_is_non_mutating_and_classifies_failures() -> None:
    module = _analysis_module()
    source = _selection()
    original = copy.deepcopy(source)

    derived, classification = module.derive_answered_selection(source, _generations())

    assert source == original
    assert [entry["attempt_id"] for entry in derived["entries"]] == ["e02:q1:C4:1"]
    assert derived["counts"] == {
        "answerable_attempts": 1,
        "attempts": 1,
        "answered": 1,
        "databases": 1,
        "errored": 0,
        "refused": 0,
        "scheduled_attempts": 3,
        "scheduled_databases": 2,
        "unscorable_attempts": 2,
    }
    assert {
        key: value for key, value in classification.items() if not key.startswith("_")
    } == {
        "answered": 1,
        "failure_strata": {
            "adapter_transport_error": {"count": 1, "saved_query": 0},
            "unsupported_semantic_result_type": {"count": 1, "saved_query": 1},
        },
        "frozen_attempts": 3,
        "scheduled_attempts": 3,
    }
    assert classification["_failure_strata_by_identity"] == {
        "q2:C4:1": "unsupported_semantic_result_type",
        "q3:C4:1": "adapter_transport_error",
    }


def test_summary_is_matched_and_reports_missingness_bounds() -> None:
    module = _analysis_module()
    source = _selection()
    derived, classification = module.derive_answered_selection(source, _generations())
    e02_scores = {
        "official_soft_ex": _score("e02", ["correct"]),
        "sensitivity": _score("e02", ["correct"]),
    }
    baseline_scores = {
        "official_soft_ex": _score("c4", ["wrong_answer", "correct", "wrong_answer"]),
        "sensitivity": _score("c4", ["wrong_answer", "correct", "wrong_answer"]),
    }

    report = module.summarize_diagnostic(
        source_selection=source,
        diagnostic_selection=derived,
        classification=classification,
        e02_scores=e02_scores,
        baseline_scores=baseline_scores,
        full_scoreable_denominators={"official_soft_ex": 3, "sensitivity": 3},
        provenance={"source_selection_sha256": "c" * 64},
    )

    official = report["scorers"]["official_soft_ex"]
    assert official["captured_subset"] == {
        "attempts": 1,
        "baseline_accuracy": 0.0,
        "baseline_correct": 0,
        "e02_accuracy": 1.0,
        "e02_correct": 1,
        "paired_difference": 1.0,
        "scoreable_attempts": 1,
        "unscorable_attempts": 0,
    }
    assert official["transition_counts"] == {"wrong_answer": {"correct": 1}}
    assert official["missingness_baseline_outcomes"] == {
        "adapter_transport_error": {"wrong_answer": 1},
        "unsupported_semantic_result_type": {"correct": 1},
    }
    bounds = official["full_frame_bounds"]
    assert bounds["denominator"] == 3
    assert bounds["known_correct"] == 1
    assert bounds["logical_lower_accuracy"] == pytest.approx(1 / 3)
    assert bounds["logical_upper_accuracy"] == 1.0
    assert bounds["transport_only_upper_accuracy"] == pytest.approx(2 / 3)
    assert bounds["unresolved_scoreable_attempts"] == 2
    assert report["formal_status"] == "INCONCLUSIVE"


def test_report_is_aggregate_only_and_rejects_unmatched_baseline() -> None:
    module = _analysis_module()
    source = _selection()
    derived, classification = module.derive_answered_selection(source, _generations())
    e02_scores = {
        "official_soft_ex": _score("e02", ["correct"]),
        "sensitivity": _score("e02", ["correct"]),
    }
    baseline_scores = {
        "official_soft_ex": _score("c4", ["wrong_answer", "correct", "wrong_answer"]),
        "sensitivity": _score("c4", ["wrong_answer", "correct", "wrong_answer"]),
    }
    report = module.summarize_diagnostic(
        source_selection=source,
        diagnostic_selection=derived,
        classification=classification,
        e02_scores=e02_scores,
        baseline_scores=baseline_scores,
        full_scoreable_denominators={"official_soft_ex": 3, "sensitivity": 3},
        provenance={"source_selection_sha256": "c" * 64},
    )
    serialized = json.dumps(report, sort_keys=True)
    for forbidden in (
        "attempt_id",
        "instance_id",
        "question",
        "generated_sql",
        "generated_query",
        "gold",
        "rows",
        "safe_field",
    ):
        assert forbidden not in serialized

    baseline_scores["official_soft_ex"]["attempts"].pop()
    with pytest.raises(module.DiagnosticError, match="baseline identities"):
        module.summarize_diagnostic(
            source_selection=source,
            diagnostic_selection=derived,
            classification=classification,
            e02_scores=e02_scores,
            baseline_scores=baseline_scores,
            full_scoreable_denominators={"official_soft_ex": 3, "sensitivity": 3},
            provenance={"source_selection_sha256": "c" * 64},
        )

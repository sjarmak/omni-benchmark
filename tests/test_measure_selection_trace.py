from __future__ import annotations

import copy

import pytest

from omni_benchmark.measure_selection_trace import (
    FALLBACK_REASON_CODES,
    MEASURE_POLICIES,
    METRIC_PATHS,
    QUERY_PATHS,
    REJECTED_REASON_CODES,
    RETRIEVAL_STATUSES,
    SELECTED_REASON_CODES,
    MeasureSelectionTraceError,
    build_measure_selection_acceptance_report,
    validate_measure_selection_trace,
)


def _decision(
    measure_id: str,
    decision: str,
    reason_code: str,
    *,
    detail: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "decision": decision,
        "measure_id": measure_id,
        "reason_code": reason_code,
    }
    if detail is not None:
        value["detail"] = detail
    return value


def _trace(attempt_id: str = "q1", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "attempt_id": attempt_id,
        "fallback_reason_code": None,
        "inline_equivalent_measure_ids": [],
        "measure_decisions": [_decision("m1", "selected", "exact_semantic_match")],
        "measure_policy": "prefer_measures",
        "metric_path": "governed_measure",
        "query_path": "semantic_query",
        "retrieval_status": "candidates_found",
        "schema_version": 1,
    }
    value.update(changes)
    return value


def test_validates_typed_trace_and_allows_unscored_detail() -> None:
    trace = _trace(
        measure_decisions=[
            _decision(
                "m1",
                "selected",
                "exact_semantic_match",
                detail="Human-readable diagnostic, never a scored value.",
            ),
            _decision("m2", "rejected", "lower_ranked_exact_match"),
        ]
    )

    assert validate_measure_selection_trace(trace) == trace


@pytest.mark.parametrize("measure_policy", sorted(MEASURE_POLICIES))
def test_accepts_every_measure_policy(measure_policy: str) -> None:
    validate_measure_selection_trace(_trace(measure_policy=measure_policy))


@pytest.mark.parametrize("query_path", sorted(QUERY_PATHS - {"no_query"}))
def test_accepts_every_executable_query_path(query_path: str) -> None:
    validate_measure_selection_trace(_trace(query_path=query_path))


def test_accepts_no_query_path() -> None:
    validate_measure_selection_trace(
        _trace(
            fallback_reason_code="no_query",
            measure_decisions=[],
            metric_path="unknown",
            query_path="no_query",
            retrieval_status="not_attempted",
        )
    )


@pytest.mark.parametrize("reason_code", sorted(SELECTED_REASON_CODES))
def test_accepts_every_selected_reason(reason_code: str) -> None:
    validate_measure_selection_trace(
        _trace(measure_decisions=[_decision("m1", "selected", reason_code)])
    )


@pytest.mark.parametrize("reason_code", sorted(REJECTED_REASON_CODES))
def test_accepts_every_rejected_reason(reason_code: str) -> None:
    validate_measure_selection_trace(
        _trace(
            fallback_reason_code="inline_allowed_by_policy",
            measure_decisions=[_decision("m1", "rejected", reason_code)],
            metric_path="inline",
        )
    )


@pytest.mark.parametrize("fallback_reason", sorted(FALLBACK_REASON_CODES))
def test_accepts_every_fallback_reason(fallback_reason: str) -> None:
    if fallback_reason == "no_query":
        trace = _trace(
            fallback_reason_code=fallback_reason,
            measure_decisions=[],
            metric_path="unknown",
            query_path="no_query",
            retrieval_status="not_attempted",
        )
    else:
        trace = _trace(
            fallback_reason_code=fallback_reason,
            measure_decisions=[_decision("m1", "rejected", "unsupported_query_shape")],
            metric_path="inline",
        )
    validate_measure_selection_trace(trace)


def test_accepts_every_metric_and_retrieval_state() -> None:
    traces = {
        "governed_measure": _trace(),
        "mixed": _trace(
            fallback_reason_code="partial_measure_coverage",
            inline_equivalent_measure_ids=["m1"],
            metric_path="mixed",
        ),
        "inline": _trace(
            fallback_reason_code="no_measure_candidate",
            measure_decisions=[],
            metric_path="inline",
            retrieval_status="no_candidates",
        ),
        "not_applicable": _trace(
            measure_decisions=[],
            metric_path="not_applicable",
            retrieval_status="not_applicable",
        ),
        "unknown": _trace(
            fallback_reason_code="retrieval_failed",
            measure_decisions=[],
            metric_path="unknown",
            query_path="no_query",
            retrieval_status="failed",
        ),
    }

    assert set(traces) == METRIC_PATHS
    assert {trace["retrieval_status"] for trace in traces.values()} == (
        RETRIEVAL_STATUSES - {"not_attempted"}
    )
    for trace in traces.values():
        validate_measure_selection_trace(trace)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("measure_policy", "sometimes"),
        ("metric_path", "mostly_composed"),
        ("query_path", "custom_sqlish"),
        ("retrieval_status", "maybe"),
        ("fallback_reason_code", "because the model felt like it"),
    ],
)
def test_rejects_free_form_values_in_scored_enum_fields(field: str, value: str) -> None:
    trace = _trace()
    trace[field] = value

    with pytest.raises(MeasureSelectionTraceError, match=field):
        validate_measure_selection_trace(trace)


@pytest.mark.parametrize(
    "decision",
    [
        _decision("m1", "maybe", "exact_semantic_match"),
        _decision("m1", "selected", "grain_mismatch"),
        _decision("m1", "rejected", "exact_semantic_match"),
        _decision("m1", "rejected", "free form explanation"),
    ],
)
def test_decision_and_reason_code_are_required_compatible_enums(
    decision: dict[str, object],
) -> None:
    with pytest.raises(MeasureSelectionTraceError, match="decision|reason_code"):
        validate_measure_selection_trace(_trace(measure_decisions=[decision]))


@pytest.mark.parametrize(
    "trace",
    [
        _trace(retrieval_status="no_candidates"),
        _trace(measure_decisions=[]),
        _trace(metric_path="governed_measure", inline_equivalent_measure_ids=["m1"]),
        _trace(metric_path="inline"),
        _trace(
            metric_path="mixed",
            inline_equivalent_measure_ids=["m1"],
            fallback_reason_code=None,
        ),
        _trace(
            query_path="no_query",
            metric_path="governed_measure",
        ),
    ],
)
def test_rejects_internally_inconsistent_trace(trace: dict[str, object]) -> None:
    with pytest.raises(MeasureSelectionTraceError):
        validate_measure_selection_trace(trace)


def test_acceptance_report_separates_retrieval_selection_composition_and_policy() -> (
    None
):
    traces = [
        _trace("q1"),
        _trace(
            "q2",
            fallback_reason_code="candidate_aggregation_mismatch",
            measure_decisions=[_decision("m2", "rejected", "aggregation_mismatch")],
            metric_path="inline",
            query_path="templated_sql",
        ),
        _trace(
            "q3",
            fallback_reason_code="no_measure_candidate",
            inline_equivalent_measure_ids=["m3"],
            measure_decisions=[],
            metric_path="inline",
            query_path="physical_sql",
            retrieval_status="no_candidates",
        ),
        _trace(
            "q4",
            fallback_reason_code=None,
            measure_decisions=[],
            measure_policy="allow_inline",
            metric_path="not_applicable",
            query_path="templated_sql",
            retrieval_status="not_applicable",
        ),
    ]
    report = build_measure_selection_acceptance_report(
        traces,
        {
            "q1": ["m1"],
            "q2": ["m2"],
            "q3": ["m3"],
            "q4": [],
        },
    )

    assert report["summary"] == {
        "attempt_count": 4,
        "governed_measure_opportunity_count": 1,
        "governed_measure_opportunity_rate": 1 / 3,
        "inline_fallback_opportunity_count": 2,
        "mapped_measure_selected_count": 1,
        "mapped_measure_selected_rate": 1 / 3,
        "opportunity_count": 3,
        "policy_violation_count": 0,
        "retrieved_opportunity_count": 2,
        "retrieved_opportunity_rate": 2 / 3,
    }
    assert report["decision_reason_counts"] == {
        "rejected": {"aggregation_mismatch": 1},
        "selected": {"exact_semantic_match": 1},
    }
    assert report["fallback_reason_counts"] == {
        "candidate_aggregation_mismatch": 1,
        "no_measure_candidate": 1,
    }
    assert report["information_boundary"] == {
        "emits_attempt_ids": False,
        "free_form_detail_scored": False,
        "hidden_annotations_used": False,
        "question_text_used": False,
        "result_values_used": False,
        "sealed_test_used": False,
    }


def test_require_policy_records_violation_instead_of_discarding_fallback() -> None:
    report = build_measure_selection_acceptance_report(
        [
            _trace(
                measure_policy="require_measures",
                metric_path="inline",
                measure_decisions=[
                    _decision("m1", "rejected", "unsupported_query_shape")
                ],
                fallback_reason_code="unsupported_query_shape",
            )
        ],
        {"q1": ["m1"]},
    )

    assert report["summary"]["policy_violation_count"] == 1


def test_free_form_detail_cannot_change_acceptance_metrics() -> None:
    first = _trace(
        measure_decisions=[
            _decision("m1", "selected", "exact_semantic_match", detail="first")
        ]
    )
    second = copy.deepcopy(first)
    second["measure_decisions"][0]["detail"] = "contradictory prose"

    assert build_measure_selection_acceptance_report(
        [first], {"q1": ["m1"]}
    ) == build_measure_selection_acceptance_report([second], {"q1": ["m1"]})


@pytest.mark.parametrize(
    "mutation",
    [
        lambda traces, opportunities: traces.append(copy.deepcopy(traces[0])),
        lambda traces, opportunities: opportunities.__setitem__("missing", ["m1"]),
        lambda traces, opportunities: opportunities.__setitem__("q1", ["m1", "m1"]),
        lambda traces, opportunities: traces[0].__setitem__("gold_sql", "forbidden"),
    ],
)
def test_rejects_duplicate_misaligned_or_protected_inputs(mutation) -> None:
    traces = [_trace()]
    opportunities = {"q1": ["m1"]}
    mutation(traces, opportunities)

    with pytest.raises(MeasureSelectionTraceError):
        build_measure_selection_acceptance_report(traces, opportunities)

# Proposed Omni measure-selection trace contract

Status: product proposal and benchmark acceptance contract, version 1. This is
not documentation of a currently observed Omni API response.

## Product decision this contract enables

R2 published 812 conservative entity-count measures. Across 45 question-blind
mapped opportunities, the treatment referenced a measure 11 times but produced
zero verified semantic replacements. The current job record cannot distinguish
five materially different causes:

1. measure retrieval was never attempted;
2. retrieval found no candidate;
3. a candidate was retrieved and rejected for a semantic reason;
4. a candidate was selected but the query still recreated metric logic inline;
5. policy allowed or required a fallback.

Those states lead to different engineering decisions. This contract makes them
typed and separately measurable. It deliberately does not infer them from SQL or
from free-form agent prose.

Omni already documents measures as reusable aggregations and recommends
`aggregate_type` when a standard aggregation fits because it enables additional
semantic optimizations. It also recommends inspecting selected fields, filters,
and SQL while tuning AI answers. This proposal adds the missing machine-readable
decision trace between those two surfaces:

- <https://docs.omni.co/modeling/measures>
- <https://docs.omni.co/guides/ai/improve-ai-answer-quality>

## Required response shape

Every terminal governed job returns one trace object. All fields below are
required, including fields whose value is `null` or an empty array.

```json
{
  "schema_version": 1,
  "attempt_id": "stable-job-or-query-id",
  "measure_policy": "prefer_measures",
  "retrieval_status": "candidates_found",
  "measure_decisions": [
    {
      "measure_id": "stable-model-measure-id",
      "decision": "selected",
      "reason_code": "exact_semantic_match",
      "detail": "Optional human-readable diagnostic"
    }
  ],
  "query_path": "semantic_query",
  "metric_path": "governed_measure",
  "inline_equivalent_measure_ids": [],
  "fallback_reason_code": null
}
```

`attempt_id` and `measure_id` must be immutable within a model revision. The job
must also carry that immutable model revision through the existing provenance
surface; a field name alone is not a stable measure identity.

## Closed scored vocabularies

Free-form `detail` is optional, capped, and diagnostic only. It must never change
an acceptance metric. Every scored field is a closed enum.

### `measure_policy`

- `allow_inline`: governed measures and inline metric logic are both permitted.
- `prefer_measures`: select an exact compatible governed measure when available;
  a typed fallback is allowed.
- `require_measures`: a metric-bearing query may complete only through compatible
  governed measures. Otherwise it returns a typed policy failure.

### `retrieval_status`

- `not_applicable`
- `not_attempted`
- `no_candidates`
- `candidates_found`
- `failed`

Only `candidates_found` may carry `measure_decisions`, and it must carry at least
one. All other states require an empty decision array.

### `decision` and compatible `reason_code`

`decision` is required and is exactly `selected` or `rejected`.

Selected reason codes:

- `exact_semantic_match`
- `user_named_measure`
- `policy_required_best_match`
- `composed_metric_dependency`

Rejected reason codes:

- `lower_ranked_exact_match`
- `ambiguous_match`
- `semantic_mismatch`
- `grain_mismatch`
- `filter_mismatch`
- `aggregation_mismatch`
- `unavailable_in_topic`
- `access_denied`
- `unsupported_query_shape`

A selected decision with a rejection reason, or a rejected decision with a
selection reason, is schema-invalid. A new reason requires a schema-versioned
contract change; it does not silently become free-form text.

### `query_path`

- `semantic_query`: the semantic query object determines the executable query.
- `templated_sql`: authored SQL uses model-resolved references.
- `physical_sql`: authored SQL names a physical relation directly.
- `no_query`: no executable query was produced.

### `metric_path`

- `governed_measure`: selected governed measures supply all metric logic.
- `mixed`: at least one governed measure is selected and equivalent metric logic
  also remains inline.
- `inline`: metric logic is authored inline and no governed measure is selected.
- `not_applicable`: the request has no metric-selection decision.
- `unknown`: no defensible metric-path classification is available.

`governed_measure` requires at least one selected measure, no inline-equivalent
IDs, and no fallback. `mixed` requires a selected measure, at least one
inline-equivalent ID, and a typed fallback. `inline` permits no selected measure
and requires a typed fallback. `no_query` requires `metric_path: unknown`.

### `fallback_reason_code`

The value is `null` when no fallback occurred. Otherwise it is one of:

- `no_measure_candidate`
- `candidate_ambiguous`
- `candidate_grain_mismatch`
- `candidate_filter_mismatch`
- `candidate_aggregation_mismatch`
- `candidate_unavailable_in_topic`
- `candidate_access_denied`
- `unsupported_query_shape`
- `retrieval_failed`
- `inline_allowed_by_policy`
- `partial_measure_coverage`
- `user_requested_sql`
- `no_query`
- `unknown`

## Failure behavior

Trace production is part of the job result contract, not best-effort telemetry.
A terminal job with a missing or invalid trace is a trace-contract failure. Under
`require_measures`, `mixed`, `inline`, `unknown`, and `no_query` are recorded as
policy violations rather than discarded from the denominator. Access-denied
candidates may be reported by stable opaque identity, but the trace must not
expose inaccessible field contents or business metadata.

## Acceptance measurements

The reference validator and aggregate oracle live in
`src/omni_benchmark/measure_selection_trace.py`. They report no attempt IDs,
question text, SQL, results, gold, or correctness.

| Metric | Denominator | Engineering decision |
| --- | --- | --- |
| Trace coverage and schema-valid rate | Every terminal governed job | Whether the product surface is reliable enough for attribution |
| Candidate-retrieval rate | Frozen mapped opportunities | Improve model metadata/retrieval when low |
| Mapped-measure selection rate | Frozen mapped opportunities | Improve ranking and semantic compatibility when retrieval is healthy but selection is low |
| Governed-measure rate | Frozen mapped opportunities | Improve query composition when selection is healthy but governed use is low |
| Inline-fallback rate and reason distribution | Frozen mapped opportunities | Prioritize missing metric classes or planner limitations |
| `require_measures` policy violations | Every metric-bearing job under that policy | Release blocker for enforcement semantics |

Selection and governed use remain mechanism endpoints. Correctness, reliability,
latency, and cost are separate downstream endpoints and must not be substituted
for them. A correctness gain without a governed-measure gain does not establish
semantic reuse; R2 already demonstrated why this separation matters.

## R2-compatible evaluation

For a future instrumented bridge/treatment series, bind the trace evaluator to
the already-frozen 45-opportunity map and report intention-to-treat counts with
Wilson intervals. The historical R2 baseline remains 0/45 verified replacements
and is never relabeled from this new telemetry. A new series gets new run IDs and
must freeze its product version, model revision, trace schema version, schedule,
and analysis before generation.

No dev-B or sealed-test input is required to validate this contract. No live run
is authorized by this document.

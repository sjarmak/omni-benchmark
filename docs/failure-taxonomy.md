# Living failure taxonomy

Status: frozen C4 dev-A baseline scored. Of 136 scoreable attempts, 9 are
correct, 93 wrong, and 34 refused or ended in an evaluated-system error. The
aggregate structural diagnostic below is hash-bound to that score and the
immutable generation records; it emits no question identity, SQL, result value,
gold, or hidden annotation. Public-only compiler dispositions remain
representation evidence and must not be reported as answer failures. Sealed
C1-C4 scoring is also complete, but its aggregate-only custody boundary cannot
revise the development mechanism ranking or localize per-question causes.

## Current top three observed risk mechanisms

1. **Relationship, aggregation, and grain composition.** Public-only fan-out
   deferred 491/1,036 definitions cross-grain. In the C4 baseline, counting
   distinct base relations and excluding CTE references and aliased self-joins,
   parseable wrong answers average 1.826 relations and parseable errors 2.000,
   versus 1.333 for correct answers; multi-relation queries occur in 41/92
   parseable wrong answers and 19/32 parseable errors, versus 2/9 correct
   answers. A looser count that admits CTE references, aliased self-joins, and
   subquery sources roughly doubles the separation (2.620 and 2.875 versus
   1.667, with 50/92 and 20/32 multi-relation) and is the upper bound rather
   than the estimate. Direction and ordering are the same under both counts.
2. **Semantic result-contract reliability.** Thirty-four attempts are explicit
   evaluated-system failures. Thirty-two still contain parseable governed SQL;
   most failed because the governed result exposed an unsupported/unknown type,
   not because no query was generated. These are evaluated-system outcomes, not
   benchmark infrastructure to retry away. Causal ownership is bounded rather
   than open: a missing type declaration on our compiled model can reach at most
   6 of the 31 unknown-type failures, and 24 of the 31 select no compiled field
   of any kind, so they lie outside anything a compile-time declaration could fix.
   Ownership of those 24 remains unresolved between the authored model and Omni's
   planning/result contract.
3. **Representation, discoverability, and reasoning remain conflated within 93
   wrong answers.** Aggregate query shape alone cannot tell whether knowledge
   was absent, inaccessible, misinterpreted, or correctly available but reasoned
   over incorrectly. The first intervention therefore targets the already-
   preregistered general relationship surface; later diagnosis must use dev-A
   only and preserve this mechanism ladder.

The highest-information relationship experiment, E02, is now terminal. It
changed one general mechanism across 91 relationships and 67 source topics. On
117 captured answers it moved official accuracy from matched C4's 9/117 to
11/117, but 14 result-contract failures and five no-query transport failures
prevented the exact full-dev-A comparison. The fixed decision is INCONCLUSIVE;
the directional subset does not establish causality or support promotion.

Every checkpoint also preserves the terminal failure vector. A move from
`wrong_answer` to `refused_or_error` is recorded separately from an accuracy
change so validation and safety behavior are not collapsed into one failure bin.

## Pre-execution representation evidence — D-043

These are HKB transformation dispositions, not question outcomes:

| Disposition | Count | Share | Current interpretation |
| --- | ---: | ---: | --- |
| Compiled | 179 | 17.3% | Safely executable under the current no-join public compiler |
| Context only | 183 | 17.7% | Discoverable semantics without an executable derived object |
| Deferred cross-grain | 491 | 47.4% | Missing explicit identity, cardinality, relationship, or aggregation contract |
| Unsupported | 183 | 17.7% | Missing source/type/semantic capability or dependent unsupported definition |

The distribution spans all 17 non-canary databases. It elevates relationship,
grain, and aggregation fidelity as the leading pre-baseline mechanism to test,
while preserving retrieval, compilation, validation, and model reasoning as
distinct downstream hypotheses.

## HKB-linked mechanism ladder

For a failed development question whose offline annotation references HKB
knowledge, classify the earliest supported failure point:

1. required knowledge absent from the semantic model;
2. knowledge present but dependency graph wrong;
3. knowledge represented correctly but not retrieved;
4. knowledge retrieved but misinterpreted;
5. semantic representation correct but compilation failed;
6. generated query or result failed to reach a scoreable answer at the
   validation or result-contract stage;
7. model reasoning failed despite a correct, available representation.

Hidden `external_knowledge` IDs stay in offline diagnosis. This document records
aggregate classifications and non-private references, never hidden content.

## Candidate taxonomy

| Category | Definition | Count / prevalence | Representative examples | Affected databases | Suspected mechanism | Experiments attempted | Status | Product implication |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HKB absent/mistransformed | Required public business definition is missing or semantically wrong in Omni | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | Transformation coverage or interpretation | None | Not measured under the permitted evidence boundary | Semantic-model authoring/automation |
| HKB dependency | Nodes exist but prerequisite edges, recursion, grain, or composition are wrong | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | Dependency compiler | None | Not measured under the permitted evidence boundary | Hierarchical metric composition |
| Retrieval/discoverability | Correct modeled object is not surfaced/selected | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | Topic/context/retrieval behavior | None | Not measured under the permitted evidence boundary | Agent discoverability and debugging |
| Retrieved but misinterpreted | Correct object is selected but agent uses it incorrectly | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | Model reasoning or description ambiguity | None | Not measured under the permitted evidence boundary | Description quality / reasoning support |
| Relationship/join | Wrong or missing join path, cardinality, or entity relationship | Join present in 41/92 parseable wrong and 18/32 parseable error attempts, versus 2/9 correct; E02's captured subset moved +1.7 points official but remained INCONCLUSIVE | Identity-free aggregate only | 16-database eligible frame | Model relationship representation/planning | E02 terminal | Directional, unresolved | Relationship authoring and guardrails |
| Metric/aggregation/grain | Wrong measure, aggregation, grouping, or grain | Aggregate present in 58/92 parseable wrong and 22/32 parseable error attempts, versus 5/9 correct; descriptive, non-exclusive | Identity-free aggregate only | 16-database eligible frame | Measure translation or reasoning | None | Observed hypothesis | Metric semantics and compiler checks |
| Time semantics | Wrong period, boundary, timezone, or comparison window | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | Temporal modeling/planning | None | Not measured under the permitted evidence boundary | First-class time semantics |
| Filter/value/alias | Wrong business filter, value interpretation, synonym, or alias | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | HKB translation/retrieval/model reasoning | None | Not measured under the permitted evidence boundary | Search and semantic authoring ergonomics |
| Semantic compilation | Intended semantic query is correct but compiled SQL is wrong/unsupported | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | Omni compiler | None | Not measured under the permitted evidence boundary | Compiler correctness/coverage |
| Validation/retry | A generated query or result fails to reach a scoreable answer at the validation or result-contract stage | 34/136 evaluated-system failures; 32 retain parseable governed SQL | Identity-free aggregate only | 16-database eligible frame | Authored-model and Omni result-contract ownership unresolved | D-155 recovery; D-168–D-170 classification/fallback | Measured baseline | Validation observability and recovery |
| Direct reasoning | Required representation and tools are correct/available but reasoning fails | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | Model planning/reasoning | None | Not measured under the permitted evidence boundary | Agent workflow/model routing |
| Refusal/error | System returns no usable answer after its allowed retry policy | Sealed scorer disposition: C1 90/267, C2 73/267, C3 102/267, C4 38/267. Resource limits, meaning our own per-turn spend cap plus provider throttling, account for 46/88 C1, 46/69 C2, 38/98 C3, and 0/38 C4 non-answers | Identity-free aggregate only | Matched 16-database sealed frame | Mixed model, context, contract, and infrastructure mechanisms; the resource-limit share is apparatus and provider rather than the evaluated system | D-051 diagnostic plus sealed aggregate and the bounded reanalysis | Measured aggregate prevalence and bounded reassignment | Reliability, refusal observability, and safe-failure reporting |
| Scorer/data ambiguity | System result may be reasonable but benchmark comparison or question is anomalous | Not measured | Aggregate evidence cannot localize individual failures | 16-database eligible frame | Benchmark/evaluator | None | Not measured under the permitted evidence boundary | Evaluation limitation, not presumed product defect |

## Checkpoint update template

At each major checkpoint append:

- run/checkpoint ID and commit;
- total correct, wrong, and refused/errored;
- category counts and changed definitions;
- top three remaining sources of failure;
- fixed and newly exposed mechanisms;
- experiments linked to each category;
- product findings created or updated;
- highest-information next experiment.

## 2026-08-30 checkpoint — C4 development baseline (scored)

**Run/checkpoint ID and commit.** C4 development baseline, dev-A frame (154
scheduled, 136 scoreable), scored at commit `f0e387157a42257036caeade9274f8fea754f261`
("score governed C4 development baseline"). Official score artifact SHA-256
`57d45346de0a98384207d350f163dfcf812e677cf3719b4a3008b5e0f3f222d8`; aggregate
receipt SHA-256 `0296753e8fcbf826a99ed2f86088ecdfb61981db8dea47d93e7871cef2690a78`;
frozen mechanical selection SHA-256
`256145c13cfae7142d92f108b4ee9dd93e658a44cafb683e5aec90170b8315cc`.

**Totals.** Official scorer: 9 correct, 93 wrong, 34 refused/system-error of
136 scoreable (9/136, 6.6%). Sensitivity scorer: 9 correct, 93 wrong, 33
refused/system-error of 135 scoreable (9/135, 6.7%; one additional attempt
exceeded the fixed normalization limit).

**Category prevalence by mechanism, this checkpoint:**

| Category | Count / prevalence | Denominator |
| --- | ---: | --- |
| Correct | 9 | 136 scoreable |
| Wrong, parseable SQL | 92 | 93 wrong (1 did not parse) |
| Refused/system-error | 34 | 136 scoreable; 32 retain parseable governed SQL |
| Relationship/join present | 2 correct, 41 wrong, 18 error | 9 / 92 / 32 parseable |
| Multi-relation queries (base relations) | 2 correct, 41 wrong, 19 error | 9 / 92 / 32 parseable; mean relations 1.333 / 1.826 / 2.000 |
| Multi-relation queries (upper bound, incl. CTEs and self-joins) | 2 correct, 50 wrong, 20 error | 9 / 92 / 32 parseable; mean relations 1.667 / 2.620 / 2.875 |

**Top three remaining mechanisms:**

1. Relationship, aggregation, and grain composition — wrong and error answers
   carry more relations than correct ones. Excluding CTE references and aliased
   self-joins, the means are 1.826 and 2.000 versus 1.333, and 41/92 wrong and
   19/32 error attempts are multi-relation versus 2/9 correct. A looser count
   admitting CTEs, self-joins, and subquery sources gives 2.620 and 2.875 versus
   1.667 with 50/92 and 20/32 multi-relation; that is an upper bound, and
   direction and ordering hold under both. Join-presence figures
   are unaffected. Evidence: RESULTS.md §5 structural diagnostic, recomputed in
   [c4-mechanism-measurements.md](c4-mechanism-measurements.md); PF-009
   (491/1,036 public HKB definitions deferred cross-grain).
2. Result-adapter typing on the governed result contract — 31 of 34
   evaluated-system failures return an `UNKNOWN` planner type on a selected
   field rather than a missing query. The remaining three are two persistent
   plan rejections and one completed job with no parseable query. Note that
   "32 of 34 carry parseable generated SQL" is a separate count over a
   different subset and is not this number. Evidence: D-155 recovery
   classification, corrected against the manifest in
   [c4-mechanism-measurements.md](c4-mechanism-measurements.md); PF-014
   (query-plan summary vs. selected-field type mismatch, `UNKNOWN` on a field
   the JSON endpoint actually returns).
3. Capture-contract fragility on completed/no-query and preview-mismatch jobs,
   distinct from true infrastructure loss — 11 of the original 45 capture gaps
   were recoverable by single-shot replay of an already-generated query, with
   general adapter fixes adding boolean support and typed-null/empty-string
   handling. Evidence: D-155; PF-010 (truncated results unscorable); PF-013
   (preview-label rows and timestamp-free failure actions misclassified as
   harness failures).

**Fixed and newly exposed mechanisms this checkpoint** (operational recoveries
under exact-receipt custody during C4 dev-A generation, none touching question
content, all logged 2026-08-28 onward):

- OAuth lease identity requires zero attached sessions and token headroom
  beyond run duration; a non-quiescent or insufficient-headroom lease is the
  failure mechanism, not credential copying itself (D-057).
- Source-tree bytecode differed across Python hash seeds between dispatcher
  worktrees, stalling C4 dispatch before provider contact (D-149).
- Runtime semantic drift (a stale/obsolete view) stopped 2 of 16 C4 targets
  before question dispatch; resolved by redeploying from the unchanged
  committed bundle and resuming the same run identity (D-150, D-151).
- Pre-answer Omni rate limiting (HTTP 429) during authenticated readback,
  resolved by reducing dispatch concurrency (D-152).

**Experiments linked to each category.** Relationship/join and
metric/aggregation: E02 completed one immutable run and is INCONCLUSIVE because
19 infrastructure capture losses prevent the fixed full-frame comparison.
Validation/retry: D-155 recovery plus D-168-D-170 classification/fallback
(measured baseline). HKB absent/mistransformed, HKB dependency,
retrieval/discoverability, retrieved-but-misinterpreted, time semantics,
filter/value/alias, semantic compilation, direct reasoning, and scorer/data
ambiguity remain unmeasured; no experiment changed their status this
checkpoint.

**Product findings created or updated in this window:** PF-009 (grain
contracts), PF-010 (truncated results), PF-011 (physical/semantic identity
divergence), PF-013 (preview/action envelope), PF-014 (query-plan field/type
contract).

**Highest-information next experiment.** Unchanged from the baseline analysis:
E02's conservative PK/unique-backed many-to-one relationship candidate (91
relationships, 16 databases, 67 source topics) was run once and is terminal;
its incomplete full-frame capture prevents promotion.

## 2026-08-30 checkpoint — sealed C1--C4 comparison

The sealed run contains 89 questions, three repetitions, and 267 scoreable
attempts per condition. The table below is the official-compatible aggregate;
it contains no question identity, SQL, rows, annotations, or per-question
correctness.

| Condition | Correct | Wrong | Refused/error | Raw generation errors | Pass³ | Correctness flips |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 27 | 150 | 90 | 50 | 6 | 6 |
| C2 | 59 | 135 | 73 | 53 | 14 | 12 |
| C3 | 23 | 142 | 102 | 43 | 4 | 6 |
| C4 | 23 | 206 | 38 | 38 | 6 | 4 |

`Refused/error` is the scorer's three-state disposition. Raw generation errors
are the narrower count whose generation outcome is `errored`; refusals are not
included. Pass³ counts questions correct in all three repetitions, while a flip
is correct in only one or two. Every condition has 267 scoreable attempts and
89 questions in these denominators.

C2 is the strongest accuracy condition and also reaches 14 all-three-pass
questions. C4 has fewer refused/error outcomes than the direct conditions but
converts that completion advantage mainly into wrong answers: 206 of 267. Its
38 terminal classes are 32 unsupported semantic result types, four response-
contract errors, and two Omni job terminal failures. Those are measured
dispositions, not a causal allocation between the authored semantic model and
the product's planning/result contract. For the raw direct-condition terminal
outcomes, C1 records 38 insufficient-context, 33 model-budget, 13
model-rate-limit, and four database errors; C2 records 31 model-budget, 16
insufficient-context, 15 rate-limit, three database, two identity, one SQL, and
one turn-limit outcome; C3 records 55 insufficient-context, 22 model-budget, 16
rate-limit, two database, one identity, one SQL, and one turn-limit outcome.
These are terminal dispositions, not per-question causal findings.

Two of those classes do not belong to the evaluated system at all.
`model_budget_error` is the harness's own `--max-budget-usd 1.0` per-turn cap,
set in `config/conditions/direct-runtime-v1.json` and passed to the direct CLI;
it fires when our spend limit is reached, not when a provider limit is. It is
apparatus. `model_rate_limit_error` is provider throttling. Together they account
for 46 of C1's 88 non-answers, 46 of C2's 69, 38 of C3's 98, and none of C4's 38.
So more than half of C1's non-answers and two thirds of C2's are attributable to
the measurement setup or the provider rather than to the condition under test.
The direct conditions absorb this cost and the governed condition does not, which
means the raw refusal comparison between them is not measuring the same thing on
both sides. RESULTS.md §6 bounds how much this could move each contrast; the
short answer is that it moves C4 further behind, never ahead.

The sealed aggregate supports reliability and condition-level interpretation,
not per-question mechanism attribution. It cannot determine which individual
wrong answers arose from absent knowledge, retrieval, interpretation,
compilation, or reasoning. E02 remains the one preregistered dev-A mechanism
contrast. Its terminal failure vector and captured-answer diagnostic follow;
they do not change the sealed result or support held-out optimization.

## 2026-08-30 checkpoint — E02 captured-answer diagnostic

The immutable E02 generation froze 117 answers and 19 infrastructure capture
failures. An offline no-rerun diagnostic applied both frozen scorers to the
captured answers and compared frozen C4 on exactly the same coordinates.

| Scorer | E02 captured | Matched C4 | Difference | Full-frame logical bounds |
| --- | ---: | ---: | ---: | ---: |
| Official Soft EX | 11/117 (9.4%) | 9/117 (7.7%) | +1.7 points | 11/136–30/136 (8.1%–22.1%) |
| Sensitivity | 10/116 (8.6%) | 9/116 (7.8%) | +0.9 points | 10/135–29/135 (7.4%–21.5%) |

Official transitions contain four gains to correct and two regressions from
correct. The unresolved stratum is 14 saved queries with unsupported result
types plus five transport failures with no saved query. Treating the 14 contract
failures as failures and only the five transport losses as potentially correct
gives an official upper bound of 16/136 (11.8%). This localizes the dominant E02
evaluation bottleneck to result capture, but does not establish that
relationships improve accuracy. E02 remains INCONCLUSIVE and no further model
attempt is permitted for the MVP.

### Reconciling E02's failure classes with C4's

The two arms are reported in different vocabularies at different stages, and the
counts do not line up the way an adjacent reading suggests. This section states
the correspondence so a reader does not compare across stages by accident.

C4 has two taxonomies, not one. At capture time it recorded 45 failures over 136
attempts: 34 unsupported semantic result types, 10 response-contract failures,
and 1 adapter transport failure. Append-only recovery v5 then replayed those and
converted 11 into typed results, leaving 34 terminal, relabeled by
recovery-time reason as 31 `omni_unknown_result_type`, 2 `omni_query_plan_rejected`,
and 1 `omni_completed_job_contract_invalid`. The widely cited "34 of 136" is the
post-recovery figure.

E02 has one taxonomy, and it is the capture-time one: a closed preregistered pair
of `unsupported_semantic_result_type` (14) and `adapter_transport_error` (5), 19
in all over the same 136-attempt frame.

Three consequences follow.

**The correct alignment is 45 against 19, both at capture time.** Comparing C4's
34 against E02's 19 crosses a recovery boundary. E02's post-recovery count does
not exist: its recovery invocation aborted before writing any artifact, because
the first transport record it reached carried no generated semantic query and the
recovery boundary refuses to invent one. The 14 replayable records were never
replayed. Logically the E02 terminal count lies somewhere in [5, 19], but nothing
measures it, and C4's own 34-of-45 conversion rate cannot be used to estimate it
because the per-attempt mapping from capture label to final class is not
derivable from the published aggregates.

**`unsupported_semantic_result_type` and `omni_unknown_result_type` are not the
same label.** They share a code path: both originate in the closed
seven-member `SUPPORTED_OMNI_RESULT_TYPES` check, and E02 runs as a C4-condition
run with a different bundle. But the capture label fires on any type outside the
seven and does not record which one was seen, while `omni_unknown_result_type` is
the strictly narrower literal test for `UNKNOWN`, evaluated against a *fresh
replay plan* rather than the original attempt. The C4 class is a recovery-time
property; the E02 class is a capture-time one.

**`adapter_transport_error` is a distinct fourth thing, present in both arms.**
It is a provider failure before any response, so no query is saved. It is not
C4's "completed job with no parseable query" class, which arises from a
response-contract source, and it is not the plan-rejection class, which can only
be assigned during a replay E02 never reached. C4 recorded 1 at capture time;
E02 recorded 5.

One further vocabulary caution: the sealed C4 arm's 38 non-answers are reported
elsewhere in this document as 32 unsupported semantic result types, 4
response-contract errors, and 2 terminal job failures. Those are capture-time
labels, not the A/B/C recovery classes, and the sealed arm has no recovery pass
of its own.

Stable artifact locations and preservation hashes are indexed in
[`evidence-index.md`](evidence-index.md).

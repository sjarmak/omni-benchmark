# Living failure taxonomy

Status: frozen C4 dev-A baseline scored. Of 136 scoreable attempts, 9 are
correct, 93 wrong, and 34 refused or ended in an evaluated-system error. The
aggregate structural diagnostic below is hash-bound to that score and the
immutable generation records; it emits no question identity, SQL, result value,
gold, or hidden annotation. Public-only compiler dispositions remain
representation evidence and must not be reported as answer failures.

## Current top three observed risk mechanisms

1. **Relationship, aggregation, and grain composition.** Public-only fan-out
   deferred 491/1,036 definitions cross-grain. In the C4 baseline, parseable
   wrong answers average 2.620 relations and parseable errors 2.875, versus
   1.667 for correct answers. Multi-relation queries occur in 50/92 parseable
   wrong answers and 20/32 parseable errors, versus 2/9 correct answers.
2. **Semantic result-contract reliability.** Thirty-four attempts are explicit
   evaluated-system failures. Thirty-two still contain parseable governed SQL;
   most failed because the governed result exposed an unsupported/unknown type,
   not because no query was generated. This is a product capability limit, not
   benchmark infrastructure to retry away.
3. **Representation, discoverability, and reasoning remain conflated within 93
   wrong answers.** Aggregate query shape alone cannot tell whether knowledge
   was absent, inaccessible, misinterpreted, or correctly available but reasoned
   over incorrectly. The first intervention therefore targets the already-
   preregistered general relationship surface; later diagnosis must use dev-A
   only and preserve this mechanism ladder.

The highest-information next experiment is E02's conservative PK/unique-backed
many-to-one relationship candidate. It changes one general mechanism, covers 91
relationships across 67 source topics, and has an exact full-dev-A comparison
path. A KEEP still requires the complete eligible dev-A frame and regression
accounting; these aggregates do not establish causality by themselves.

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
6. compiled query correct but validation/harness changed the outcome;
7. model reasoning failed despite a correct, available representation.

Hidden `external_knowledge` IDs stay in offline diagnosis. This document records
aggregate classifications and non-private references, never hidden content.

## Candidate taxonomy

| Category | Definition | Count / prevalence | Representative examples | Affected databases | Suspected mechanism | Experiments attempted | Status | Product implication |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HKB absent/mistransformed | Required public business definition is missing or semantically wrong in Omni | Not measured | Await baseline | Await baseline | Transformation coverage or interpretation | None | Unmeasured | Semantic-model authoring/automation |
| HKB dependency | Nodes exist but prerequisite edges, recursion, grain, or composition are wrong | Not measured | Await baseline | Await baseline | Dependency compiler | None | Unmeasured | Hierarchical metric composition |
| Retrieval/discoverability | Correct modeled object is not surfaced/selected | Not measured | Await baseline | Await baseline | Topic/context/retrieval behavior | None | Unmeasured | Agent discoverability and debugging |
| Retrieved but misinterpreted | Correct object is selected but agent uses it incorrectly | Not measured | Await baseline | Await baseline | Model reasoning or description ambiguity | None | Unmeasured | Description quality / reasoning support |
| Relationship/join | Wrong or missing join path, cardinality, or entity relationship | Join present in 41/92 parseable wrong and 18/32 parseable error attempts, versus 2/9 correct; descriptive, non-exclusive | Identity-free aggregate only | 16-database eligible frame | Model relationship representation/planning | E02 selected next | Observed hypothesis | Relationship authoring and guardrails |
| Metric/aggregation/grain | Wrong measure, aggregation, grouping, or grain | Aggregate present in 58/92 parseable wrong and 22/32 parseable error attempts, versus 5/9 correct; descriptive, non-exclusive | Identity-free aggregate only | 16-database eligible frame | Measure translation or reasoning | None | Observed hypothesis | Metric semantics and compiler checks |
| Time semantics | Wrong period, boundary, timezone, or comparison window | Not measured | Await baseline | Await baseline | Temporal modeling/planning | None | Unmeasured | First-class time semantics |
| Filter/value/alias | Wrong business filter, value interpretation, synonym, or alias | Not measured | Await baseline | Await baseline | HKB translation/retrieval/model reasoning | None | Unmeasured | Search and semantic authoring ergonomics |
| Semantic compilation | Intended semantic query is correct but compiled SQL is wrong/unsupported | Not measured | Await baseline | Await baseline | Omni compiler | None | Unmeasured | Compiler correctness/coverage |
| Validation/retry | A viable answer is rejected, corrupted, or not recovered | 34/136 evaluated-system failures; 32 retain parseable governed SQL | Identity-free aggregate only | 16-database eligible frame | Omni result types and query/result contract | D-155 recovery; D-168–D-170 classification/fallback | Measured baseline | Validation observability and recovery |
| Direct reasoning | Required representation and tools are correct/available but reasoning fails | Not measured | Await baseline | Await baseline | Model planning/reasoning | None | Unmeasured | Agent workflow/model routing |
| Refusal/error | System returns no usable answer after its allowed retry policy | Public diagnostics: 3/4 sampled fake-account C1 attempts refused across immutable runs; auth4 proof: 1/12 refused and 0 errored | `fake_account_1` changed from refusal to answer across runs; `fake_account_3`, `_5`, and `cross_border_1:C3` refused | fake_account_large, cross_border_large | Stochastic/content-sensitive model behavior; infrastructure errors remain separate | D-051 refusal-scope diagnostic and auth4 proof | Measured pre-baseline; full prevalence pending | Reliability, refusal observability, and safe-failure reporting |
| Scorer/data ambiguity | System result may be reasonable but benchmark comparison or question is anomalous | Not measured | Await baseline | Await baseline | Benchmark/evaluator | None | Unmeasured | Evaluation limitation, not presumed product defect |

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
| Multi-relation queries | 2 correct, 50 wrong, 20 error | 9 / 92 / 32 parseable; mean relations 1.667 / 2.620 / 2.875 |

**Top three remaining mechanisms:**

1. Relationship, aggregation, and grain composition — wrong and error answers
   carry more relations than correct ones (mean 2.620 and 2.875 vs 1.667), and
   50/92 wrong and 20/32 error attempts are multi-relation versus 2/9 correct.
   Those figures count CTE references, aliased self-joins, and subquery sources,
   so they are an upper bound. Excluding CTEs and self-joins, the means become
   1.826 and 2.000 vs 1.333 and multi-relation counts become 41/92 and 19/32;
   direction and ordering hold, magnitude roughly halves. Join-presence figures
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
metric/aggregation: E02 selected as the first bounded candidate, not yet run.
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
relationships, 16 databases, 67 source topics), run on the full eligible dev-A
frame with regression accounting before promotion.

Next taxonomy update is due at the sealed or optimization checkpoint, per
`omni-benchmark-1mh`.

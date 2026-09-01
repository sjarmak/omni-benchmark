# What Breaks When Business Knowledge Becomes a Semantic Layer

> **Corrected 2026-08-31 (D-211).** This document describes the governed query
> path as a "raw-SQL rewrite path" taken on every attempt, with `join_via_map`
> empty as evidence that no query composed. That reading does not survive
> remeasurement. `rewriteSql` is Omni's documented default for any query carrying
> `userEditedSQL`, so it is true on all 661 parseable governed attempts and
> discriminates nothing; `join_via_map` is populated on topic readback, not on
> query submission, so its count of zero measured a field this pathway never
> sets. The authored SQL references the deployed model through `${view.field}`
> templating on 660 of 661 attempts, and most attempts also take the model's join
> scope through `join_paths_from_topic_name` (69.6% dev-A C4, 98.5% C5). What the
> model never supplied is the metric: an aggregate hand-written over a field
> reference appears on 34.1% of dev-A C4 and 38.1% of C5, which is Omni's
> documented signal for a topic with no measure. Corrected counts:
> [`governed-query-path-tally-v2.json`](../experiments/analysis/governed-query-path-tally-v2.json).
> The text below is left as the record of what was measured and published.

**Findings from an independent evaluation of Omni on LiveSQLBench Large-v1**

> **Superseded, 2026-08-30.** This working draft predates sealed scoring and
> contains deliberately unresolved slots plus an obsolete optimized-held-out
> plan. It must not be used as a result or submission artifact. The sole current
> primary report is [`RESULTS.md`](../RESULTS.md); unique mechanism prose is
> retained here only as drafting history.
>
> **Further superseded, 2026-08-31, on one substantive point.** This draft
> predates the C5 arm and nowhere mentions it. It explains the raw-SQL rewrite
> fallback by saying the conservative compiler deferred so much that no composed
> path existed for cross-table access. C5 tested that explanation and it does not
> hold. C5 published a view for every table and a join for every qualifying
> foreign key, and the rewrite rate stayed at 100% (134 of 134 parseable
> attempts). Wherever this draft says an absent join path *left* the agent with
> no choice, read it as describing what the model could express, not as the cause
> of what the agent selected. The two are separate, and only the first is
> explained by compilation coverage.

Draft v2, 2026-08-30. At the time of drafting, held-out numbers had not been
released; every unavailable value below was a typed slot, not an estimate. See
[Slot register](#slot-register) for the historical fill-in design.

Supporting material: [`manuscript/main.pdf`](../manuscript/main.pdf) carries the
preregistered protocol, custody design, and statistical plan. This report is the
primary artifact; the protocol paper explains how it was constrained.

---

## The question, and why it is hard to answer

An analytical agent that queries governed business objects should beat one that
writes SQL against a raw schema. That claim is easy to state and hard to check,
because a semantic layer changes three things at once. It changes what knowledge is *available* at runtime, how that
knowledge is *represented*, and whether the query path is *enforced*. A single
before-and-after comparison cannot say which of the three did the work, and prior
public comparisons in this space change all three simultaneously.

This study separates them. Four conditions run the same 89 previously unseen
analytical questions against the same read-only PostgreSQL databases, and each
condition adds exactly one thing to the one below it.

| Condition | Available at runtime | Query path |
| --- | --- | --- |
| C1 | Public schema only | Direct SQL |
| C2 | Public schema plus searchable business knowledge | Direct SQL |
| C3 | Public schema plus a searchable Omni semantic model | Direct SQL |
| C4 | Omni semantic model | Omni agent emits SQL through the product's rewrite path over model-resolved field references |

C2 minus C1 isolates access to business knowledge. C3 minus C2 isolates its
structuring into semantic objects. C4 minus C3 is the governed path, and it is a
system-level contrast rather than an isolated causal estimate of enforcement,
because C4 is a composite production system whose internal model routing is not
fully observable.

The fourth row was written as "Production-governed Omni" before the governed
queries were measured, and it has been corrected here. Omni's agent took the
product's raw-SQL rewrite path on all 135 governed development queries, and the
deployed model declared no join path and no measure for a planner to compile.
That is the study's most consequential negative result about its own design, it
is developed in Finding 5, and it means C4 minus C3 compares two agent-authored
SQL conditions rather than a compiled-query condition against a direct-SQL one.

The benchmark is LiveSQLBench Large-v1: 480 public instances over 18 PostgreSQL
databases, of which the 332 `Query` tasks are eligible. Each database ships a
hierarchical knowledge base (HKB) of natural-language business definitions. A
deterministic split, computed from public metadata alone, assigned 231 questions
to development and 101 to a sealed held-out set. The development partition
divides further into 154 adaptive questions (dev-A) and 77 metered validation
questions (dev-B).

What follows leads with what the study learned. The design, custody, and scoring
machinery are compressed into one section near the end, with pointers.

---

## Finding 1: Grain contracts, not vocabulary, are the binding constraint

Before any hidden label was released, the public HKB for all 18 databases was
transformed into Omni semantic objects by a compiler with one rule: never guess.
A definition compiles only when its grain, inputs, and identity are defensible
from public schema and public text. Everything else is recorded with an explicit
reason.

The reconnaissance came first, and it reframed the problem. The 1,090 HKB
definitions are not a flat glossary. They form a dependency graph with 945
declared direct edges. 560 entries depend on at least one other entry, 344 edges
point at another derived entry, every one of the 18 databases contains a
multi-hop chain, and the longest chain spans six edges. A naive import that
indexes each definition as an independent string has already lost part of the
business logic before an agent sees a question.

Against that graph, the conservative compiler produced this:

| Disposition | Definitions | Share |
| --- | ---: | ---: |
| Compiled to an executable object | 193 | 17.7% |
| Retained as searchable context only | 193 | 17.7% |
| Deferred, crosses an unresolved grain | 511 | 46.9% |
| Unsupported | 193 | 17.7% |
| **Total** | **1,090** | **100.0%** |

Nearly half of all business definitions could not be made executable, and the
reason was almost never that the language was vague. Across the 17-database
fan-out the three dominant loss codes were `cardinality_unknown` (398),
`aggregation_unspecified` (314), and `cross_grain_no_identity` (308). The
definitions say what the business means. They do not say at what grain the metric
lives, which entity owns it, how many rows on the far side of a relationship a
row can match, or what happens when the metric is aggregated across that
relationship. Those four contracts are exactly what governance is supposed to
enforce, and they are exactly what the source material omits.

The pattern is domain-shaped. Databases full of row-local physical or sensor
readings, planets and solar panels, compiled comparatively well. Residential and
reverse-logistics models retained useful prose but compiled no HKB definition
safely under the same rules.

Guessing would have inflated apparent coverage. It would also have destroyed the
thing being tested, because a join invented by an importer is not a governed
join. The compiler's refusal to guess is itself the finding.

This measures transformation coverage, not answer correctness. A deferred
definition may never be needed for any question, and a compiled one can still be
retrieved or interpreted wrongly.

**Product consequence.** An HKB-import workflow needs first-class metric grain,
entity identity, relationship cardinality, and aggregation contracts as
declarable fields, plus a dry run that names, for each definition it could not
govern, the specific contract that was missing. Without that report the user
chooses between silently guessed semantics and a large pile of prose with
uncertain agent discovery. Recorded as
[PF-009](product-findings.md#pf-009-missing-grain-contracts-dominate-public-only-hkb-translation).

---

## Finding 2: On development questions, searchable prose beat compiled structure

The frozen direct-SQL baseline produced 630 attempts over 210 development
questions on 16 databases. Its exact dev-A intersection contains 420 attempts
over 140 of the 154 dev-A questions; 122 per condition were scoreable under the
official scorer after reference-SQL conformance.

| Condition | Correct | Wrong | Refused or error | Official | Sensitivity |
| --- | ---: | ---: | ---: | ---: | ---: |
| C1 raw schema | 9 | 80 | 33 | 9/122 (7.4%) | 9/121 (7.4%) |
| C2 searchable raw HKB | 29 | 91 | 2 | 29/122 (23.8%) | 28/121 (23.1%) |
| C3 searchable exported model | 16 | 74 | 32 | 16/122 (13.1%) | 14/121 (11.6%) |
| **All direct** | **54** | **245** | **67** | **54/366 (14.8%)** | **51/363 (14.0%)** |

Two things stand out. Making business knowledge searchable more than tripled
accuracy over raw schema alone. Structuring that same knowledge into semantic
objects then gave back roughly half the gain. Both frozen scorers preserve the
ordering, so this is not a normalization artifact.

The completion rates sharpen it. On the 16-database frame, C2 completed 97.9% of
attempts against 75.9% for C1 and 74.8% for C3. C2 was not just more accurate, it
was dramatically more likely to return anything at all. That is a reliability
result as much as an accuracy result, and it is where most of the C2 advantage
lives: 91 of C2's 122 scoreable attempts still returned a wrong answer.
Completion does not substitute for correctness.

The governed condition ran on its own fixed frame. C4 scheduled all 154 dev-A
questions; 136 were answerable, and it completed every one of them. Under the
official scorer: 9 correct, 93 wrong, 34 refused or system-error, giving 9/136
(6.6%). The sensitivity scorer retained 135 scoreable attempts with the same 9
correct and 93 wrong, giving 9/135 (6.7%).

Because C4's denominator is broader, an aggregate-only alignment to the 122
questions scoreable in all four conditions was computed without releasing any
per-question identity. On that common frame C4 is 5 correct, 83 wrong, 34 refused
or error, or 5/122 (4.1%), against C1's 7.4%, C2's 23.8%, and C3's 13.1%. The
paired C1/C4 table holds 3 questions correct in both, 2 correct only in C4, 6
correct only in C1, and 111 correct in neither, a descriptive C4 minus C1
difference of -3.3 percentage points. C4's low development result is therefore
not an artifact of its wider denominator.

These are development numbers on an adaptively reusable partition. They are
exploratory, and they are not the held-out estimate. What they do establish is
the shape of the problem the held-out run will measure: on this benchmark, the
value of business knowledge showed up when it was searchable, and structuring it
under the no-guess compiler did not recover that value.

---

## Finding 3: A quarter of governed attempts never reached a scoreable result

This is the result with the clearest product action, and it is invisible in an
accuracy number.

Of 136 answerable governed attempts, 34 ended in a refused or system-contract
outcome rather than a scoreable result. That is 25.0% of the frame and 3.8 times
the size of the entire correct set. The governed system was not silent on those
questions. In the identity-free structural aggregate, 32 of the 34 carried a
fully parseable governed query: the agent selected a topic, planned a semantic
query, and the query was then rejected by a contract downstream of generation.

Thirty-one of the 34 share one mechanism. The query plan reported `UNKNOWN` for a
selected field's type, and the evaluation fails closed on `UNKNOWN` rather than
inferring a type from returned values, because value-based inference silently
changes comparison and aggregation semantics under a result-set scorer. The
remaining three break down as one completed job carrying no parseable query and
two persistent plan rejections after transport noise was excluded.

| Class | Count | Scoring disposition | Attribution |
| --- | ---: | --- | --- |
| A. Plan reported `UNKNOWN` for a selected field | 31 | Counts against the evaluated system | Unresolved, see below |
| B. Job completed with no parseable query | 1 | Counts against the evaluated system | Product |
| C. Persistent plan rejection | 2 | Counts against the evaluated system | Product, after retry exclusion |
| D. Recovered by replaying the already-generated query | 11 | Scored as answers, not in the 34 | This evaluation's capture path, corrected |

The scoring disposition column says which side absorbs the attempt for scoring
purposes. It is not an attribution of cause, and the two should not be read as
the same claim. The eleven class-D attempts were converted into typed results by
re-executing a query the system had already written, with no question
resubmission and no model reasoning rerun; that recovery is why the terminal
count is 34 rather than 45.

**Attribution for the 31 is genuinely unresolved, and this report does not
assign it.** The compiled semantic bundles declare no output type on any field,
physical or derived, although the compiler computes a value kind for every one of
them in the same loop that serializes the field document without it. The product
therefore had to infer the type of an expression it was never told about, and it
also accepted and validated every one of those bundles without reporting a
missing type. The type contract between a programmatic model author and a
semantic layer is not written down anywhere either side can point to, and that
under-specified interface is the reportable finding.

> **What the 34 do and do not support.** They support: a quarter of governed
> attempts did not reach a scoreable result; 31 of them share one mechanism, an
> `UNKNOWN` selected-field type; the mechanism sits at a contract between a
> programmatically authored model and the product's query planner that neither
> side currently specifies. They do not support: that C4 would have scored higher
> (no conversion has been performed and no converted attempt has been scored);
> that Omni's semantic layer is defective (the compiled bundles declare no output
> type on any field, and the compiler computes one it does not emit); that this
> evaluation's harness caused the failures (the product accepted and validated
> every bundle without reporting a missing type, returned values through its
> execution endpoint for a field its planner typed as `UNKNOWN`, and has never
> been tested against a bundle that declares a type); or that the 34 are unique
> to the governed path.

That last point deserves its own numbers, because it is the comparison a
skeptical reader will ask for. On the 122 questions scoreable in all four
conditions, the non-answer rates are 27.9% for C4, 27.0% for C1, and 26.2% for
C3. Only C2, at 1.6%, is different. Failing to produce a scoreable answer roughly
a quarter of the time is not a property unique to the governed path on this
benchmark. The mechanisms differ, and that limits the comparison: C4's are result
contract failures, while C1's and C3's include budget exhaustion and refusals
that the frozen generation contract cannot decompose. Equal rates are evidence
against "the governed path uniquely fails to answer". They are not evidence that
the two paths are equally reliable.

Excluding non-answers symmetrically, each condition against its own scoreable
subset, gives C1 10.1%, C2 24.2%, C3 17.8%, and C4 5.7%. The ordering does not
move.

Two further consequences follow, and the second matters more than the first.

The direct accuracy cost is bounded. Of 136 attempts, 102 reached a scored answer
at an ambient correct rate of 8.8%, a figure that is identical under both frozen
scorers. If all 34 converted and scored at that ambient rate, C4 would be 8.8% on
136 and 5.7% on 122, closing 1.6 of the 19.7 points separating C4 from C2. The
ambient rate is more likely an upper bound than a central estimate for that
subset: counting distinct base relations, error queries averaged 2.000 against
1.826 for wrong answers and 1.333 for correct ones, and if relation count tracks
difficulty the converted attempts would score below ambient rather than at it.

The measurement cost is larger than the accuracy cost. Every modeling
intervention on this frame is evaluated on 102 informative attempts instead of
136, because a contract failure occurs downstream of whatever the intervention
changed. Accuracy is bounded above by 102/136, or 75%, for any modeling change.
That ceiling is a property of the measurement, not of the system's answer
quality. A change that fixes three questions inside the error class and breaks one
elsewhere is currently indistinguishable from a change that does nothing.

The product cost lands on any machine consumer. Six product findings in this
family were recorded during the run: opaque schema-refresh failures
([PF-001](product-findings.md#pf-001-schema-refresh-failures-lack-actionable-diagnostics-in-the-cliapi)),
no structured refusal outcome
([PF-008](product-findings.md#pf-008-governed-ai-jobs-do-not-expose-a-structured-refusal-outcome)),
truncated results that are observable but not scoreable
([PF-010](product-findings.md#pf-010-truncated-governed-results-are-observable-but-not-execution-scorable)),
presentation-control rows serialized into CSV data payloads alongside
timestamp-free failure actions
([PF-013](product-findings.md#pf-013-governed-job-previews-mix-data-rows-with-presentation-control-records)),
and query plans that conflate selected output fields with dependency metadata
while reporting `UNKNOWN` for a field the JSON endpoint returns values for
([PF-014](product-findings.md#pf-014-query-plan-summaries-conflate-output-and-dependency-field-metadata)).
A seventh, [PF-006](product-findings.md#pf-006-unformatted-json-results-still-stringify-numeric-measures),
records a planner-generated `count` measure returning as a JSON string, a field
this evaluation's compiler never authored. Each was caught by an evaluator that
fails closed. An integration that failed open would have ingested preview labels
as business data, or scored a truncated table as an answer.

Two of the three offline checks that would settle the attribution have since been
run, and they move the disputed surface rather than resolving the attribution.
Of the 130 field references the 31 failing attempts select, 8 are compiled
derived dimensions and 15 are compiled physical ones; 24 of the 31 attempts
select no compiled bundle field at all. A declared output type therefore cannot
reach most of this class, because there is no compiled field in those queries for
a declaration to attach to. The second check explains why: the fields the planner
is asked to type are the output columns of SQL the agent wrote, not a projection
over declared model fields. What remains unrun is the third check, publishing one
field with an explicit declared type to an isolated public branch, and it is now
worth less, because it reaches at most 7 of the 31 either way. The mechanism
statement the evidence supports is that the planner reported `UNKNOWN` for output
columns of agent-authored SQL that the semantic model does not define, and the
evaluation fails closed on `UNKNOWN`. Neither side specifies what a result
contract over rewritten SQL guarantees, and that under-specified interface is
still the reportable finding. Full argument, both readings, and the code paths
involved are in [`docs/c4-failure-attribution.md`](c4-failure-attribution.md) and
[`docs/c4-mechanism-measurements.md`](c4-mechanism-measurements.md).

## Finding 4: Tool payload bounds are part of the agent contract

The first end-to-end attempt on the direct comparator never reached SQL. It
called schema inspection, received all 51 tables of the target database, and the
next model turn exhausted its budget: 173,365 tokens, $1.74, no answer.

Whole-database inspection was replaced with deterministic query-directed search
over the same committed public schema. The model must supply a non-empty query,
and the tool returns at most four matching tables within a 64 KiB payload. All
three direct conditions share the contract.

The first bounded attempt then failed differently and usefully. A generic secret
heuristic rejected canonical public foreign-key identifiers as if they were
credentials, terminating the attempt at 1,585 tokens. A typed, fail-closed
validation rule fixed that boundary while retaining the credential checks. The
next canary answered in 33,445 tokens at $0.21 with a complete trace.

| Stage | Terminal state | Tokens | Cost | Latency |
| --- | --- | ---: | ---: | ---: |
| Whole-schema | Budget error | 173,365 | $1.7399 | 26.0 s |
| First bounded | Public-ID validation error | 1,585 | $0.0177 | 3.0 s |
| Bounded, after fix | Answered | 33,445 | $0.2148 | 40.9 s |

That table is a single question on a single database, and the two-orders-of-
magnitude reading of it is wrong. Both of the first two rows are failures, and
comparing 170K-before-failing against 1.6K-before-failing is not a like-for-like
ratio. At full scale across 518 completed captures, the shipped system runs a
median of 127,310 to 198,968 input tokens per attempt by condition and costs
about $1.68 per attempt, with mean condition costs of $1.48, $1.71, and $1.84.
Budget exhaustion fell to 17 of 518 attempts (3.3%).

What the intervention actually bought is structural rather than statistical. The
payload bound holds by construction for every question and every database,
enforced in code and bound into per-attempt action evidence. Large turns still
occur, with 12 of 518 attempts (2.3%) reaching a single turn as large as the
original canary's, but they arrive from accumulated conversation rather than from
one tool call dumping a schema. The hard bound and the observed end-to-end cost
are two separate claims, and they are reported separately here for that reason.

A later attempt on a different question in the same database reached five
four-table searches, spent $7.49, and still ended in budget exhaustion. Narrowing
the window to two tables cut it to four searches and $4.32, and it still returned
no answer. A cheaper failure is not evidence for a smaller window, so the change
was reverted and that database was excluded under the predeclared rule.

**Product consequence.** A semantically valid tool call can make a system
unusable by consuming the remaining inference budget. Schema and semantic search
should be query-directed, bounded, and observable, with per-call context volume
in telemetry and typed public provenance identifiers so that safety filters do
not reject legitimate semantic metadata.

---

## Finding 5: Wrong answers are structurally heavier than right ones

An identity-free structural pass parsed every scored query without exposing
question identity, SQL text, result values, or hidden annotations. All 299
correct-or-wrong direct records parsed.

Wrong answers used more relations than correct ones in every direct condition:
3.16 against 2.00 in C1, 3.28 against 2.48 in C2, 3.04 against 1.81 in C3.
Windowing and deduplication were fragile in a way that jumps out of the counts,
with 30 of 31 window-query attempts and 25 of 28 `DISTINCT` attempts wrong. Join
presence and aggregate presence, taken alone, had wrong rates similar to their
absence. The signal is narrower than "joins are hard": it tracks how many
relations a single query has to reconcile at once.

The governed condition reproduced the direction on its own frame. Counting
distinct base relations, correct C4 queries averaged 1.333; wrong answers
averaged 1.826 and errors 2.000. Multi-relation queries appeared in 2 of 9
correct, 41 of 92 parseable wrong, and 19 of 32 parseable error attempts. Joins
appeared in 2 of 9, 41 of 92, and 18 of 32. A looser count admitting CTE
references, aliased self-joins, and subquery sources gives means of 1.667, 2.620,
and 2.875 with multi-relation counts of 2 of 9, 50 of 92, and 20 of 32; it is an
upper bound on the separation, not a second estimate of it.

Three qualifications constrain what those governed numbers mean, and they are
load-bearing. C4 records store no separately compiled SQL, so the aggregates are
computed from the SQL carried on each governed semantic query. The deployed
topics declare no joins and no measures, so multi-relation and aggregate presence
in those queries do not originate in the deployed model's declared structure. The
relation count also counts CTE references, aliased self-joins, and subquery
sources, which makes multi-relation prevalence an upper bound on genuine
cross-table access rather than a measurement of it.

That third point has a consequence worth stating plainly, and the check that
resolves it has now been run. All 135 governed semantic queries in the frozen
development baseline carry
`rewriteSql: true` with agent-authored SQL, none declares a join path, and
`join_via_map` is empty on every one of them. The governed path is an agent
writing SQL with the semantic model available as a resolved field vocabulary,
not a planner composing declared objects. That narrows what C4's result says
about enforcement.

The path was Omni's choice, not a configuration this evaluation could set. The
submitted job carries a model identifier, the bare question, and a branch
identifier, and the product exposes no mode flag; the agent's own instructions
are not observable. For cross-table questions there was also nothing else to
choose. The conservative compiler of Finding 1 deferred 46.9% of definitions as
cross-grain, so the deployed topics publish empty joins and no measures, and 62
of the 133 parseable queries reach two or more distinct non-CTE sources that no
declared join path could have connected.

The semantic layer is not absent from those queries. It is used on the way in and
barely at all on the way out: 109 of 135 attempts reference at least one compiled
dimension and 39 reference an HKB-backed derived one, while of 518 selected field
references only 75 are compiled, 97 attempts select none, and no attempt selects
compiled fields exclusively. That asymmetry is the same shape as Finding 3's
contract failures, and it is why the planner was asked to type columns the model
never declared. Full measurement in
[`docs/c4-query-path-disclosure.md`](c4-query-path-disclosure.md); the earlier
open question is [`docs/c4-failure-attribution.md`](c4-failure-attribution.md) §4.

The analysis is descriptive and non-exclusive. It does not establish that
relationships caused the failures, and aggregate query shape cannot distinguish a
question whose knowledge was absent from one whose knowledge was present,
retrieved, and then reasoned over incorrectly. What it does is rank the
relationship, grain, and dependency surface as the most prevalent structural
correlate of failure in both the direct and governed paths, which is what
selected the first optimization candidate.

The query-path measurement upgrades that selection from a correlation to a named
mechanism. E02 declares FK-backed relationships, which is precisely the ingredient
whose absence left the rewrite path as the only route to cross-table access. It
is now a direct test of whether a model that can express a join changes the path
Omni's agent takes. Whether it does is being measured, not assumed: E02's topics
still declare no measures, so the agent may keep rewriting in order to aggregate.

---

## The failure mechanism ladder

Aggregate structure ranks mechanisms. It does not attribute a specific failure.
Attribution uses a fixed ladder, and a failure is assigned to the *earliest*
supported point on it:

1. required knowledge absent from the semantic model;
2. knowledge present but the dependency graph is wrong;
3. knowledge represented correctly but not retrieved;
4. knowledge retrieved but misinterpreted;
5. semantic representation correct but compilation failed;
6. compiled query correct but validation or the harness altered the outcome;
7. model reasoning failed despite a correct, available representation.

The ordering is the point. Without it, a retrieval miss or a compilation defect
gets recorded as a reasoning failure, and the resulting product action is to
change the model when the correct action is to change the importer. Rung 6 is
where the 34 contract failures of Finding 3 land, and reading them as rung 7
would have been the single most expensive misdiagnosis available in this study.

Hidden knowledge identifiers stay in offline diagnosis. The published taxonomy
records aggregate classifications and non-private references only.

---

## Telemetry: what the contract records, and what it refuses to record

The telemetry design carried more of this study's findings than the accuracy
numbers did, and three of its rules did the work.

**Null is never zero.** Any unobserved count is `null` and must be named in an
explicit `telemetry_unavailable` list. Token and cost values separately declare
whether they are `provider_reported`, `derived`, or `unavailable`. A zero default
for an unobserved retry count would have silently asserted that the production
system never retried.

**Correctness lives in a separate record.** The pre-score generation envelope is
immutable and contains no correctness. Scoring emits a distinct artifact bound to
the generation file's hash and to every attempt record's hash; it cannot copy or
alter the prompt, query, result, or telemetry. Joined correctness must agree with
the generation record's terminal state.

**Non-answers are not one bucket.** The generation record separates `answered`,
`refused`, and `errored`, and preserves the terminal failure origin and class.
The official benchmark's combined `refused_or_error` outcome is retained for
comparability, but it is never the only summary. That distinction is what
surfaced Finding 3: an accuracy metric alone reports 34 attempts as not-correct,
which is true and useless.

Cost and failure telemetry are reported as co-outcomes rather than equalized
across conditions. Pre-treatment resources are matched where meaningful. Actual
tokens, tool calls, database queries, retries, latency, and cost are measured,
because an intervention that leaves accuracy flat while converting confident
wrong answers into safe refusals has done something a product team needs to know
about.

One gap is a product limitation rather than a design choice. The pinned Omni job
contract exposes `COMPLETE`, `FAILED`, and `CANCELLED` with no distinct refusal
state and no machine-readable refusal reason. Classifying refusals from response
prose was available and was deliberately not used. C4's refusal rate is therefore
reported as unavailable rather than pending, and that is
[PF-008](product-findings.md#pf-008-governed-ai-jobs-do-not-expose-a-structured-refusal-outcome).

---

## Held-out results

Every value in this section is a slot. The untuned sealed generation covers 1,068
scheduled attempts: four conditions by three repetitions over the matched
89-question frame. A separately frozen optimized C4 arm runs on the same
membership. Custody releases permitted aggregates only after both arms have
completed generation.

### Primary endpoints

| Endpoint | Estimate | 95% interval |
| --- | ---: | ---: |
| C4 mean one-shot execution accuracy | SLOT_C4_MEAN_ACCURACY | SLOT_C4_MEAN_ACCURACY_CI |
| C4 repetition-one execution accuracy | SLOT_C4_REP1_ACCURACY | SLOT_C4_REP1_ACCURACY_CI |
| Paired C4 minus C1 difference | SLOT_C4_MINUS_C1_DIFF | SLOT_C4_MINUS_C1_CI |

### Four-condition matrix, official scorer

| Condition | Mean accuracy | Wrong rate | Error rate | Pass-cubed | Correctness flips |
| --- | ---: | ---: | ---: | ---: | ---: |
| C1 | SLOT_C1_MEAN_ACCURACY | SLOT_C1_WRONG_RATE | SLOT_C1_ERROR_RATE | SLOT_C1_PASS3 | SLOT_C1_FLIPS |
| C2 | SLOT_C2_MEAN_ACCURACY | SLOT_C2_WRONG_RATE | SLOT_C2_ERROR_RATE | SLOT_C2_PASS3 | SLOT_C2_FLIPS |
| C3 | SLOT_C3_MEAN_ACCURACY | SLOT_C3_WRONG_RATE | SLOT_C3_ERROR_RATE | SLOT_C3_PASS3 | SLOT_C3_FLIPS |
| C4 | SLOT_C4_MEAN_ACCURACY | SLOT_C4_WRONG_RATE | SLOT_C4_ERROR_RATE | SLOT_C4_PASS3 | SLOT_C4_FLIPS |

Content-refusal rate and insufficient-context rate are **unavailable**, not
pending. The frozen generation contract cannot distinguish them for C4, and no
prose heuristic will be used to manufacture the distinction.

### Sensitivity scorer

| Condition | Mean accuracy |
| --- | ---: |
| C1 | SLOT_C1_SENSITIVITY_ACCURACY |
| C2 | SLOT_C2_SENSITIVITY_ACCURACY |
| C3 | SLOT_C3_SENSITIVITY_ACCURACY |
| C4 | SLOT_C4_SENSITIVITY_ACCURACY |

### Exploratory rung contrasts

| Contrast | Paired difference | Holm-adjusted p | What it isolates |
| --- | ---: | ---: | --- |
| C2 minus C1 | SLOT_C2_MINUS_C1_DIFF | SLOT_C2_MINUS_C1_HOLM_P | Access to business knowledge |
| C3 minus C2 | SLOT_C3_MINUS_C2_DIFF | SLOT_C3_MINUS_C2_HOLM_P | Structuring that knowledge |
| C4 minus C3 | SLOT_C4_MINUS_C3_DIFF | SLOT_C4_MINUS_C3_HOLM_P | Governed system against direct SQL; two agent-authored SQL paths differing in agent, dialect, surface, and execution contract, not query composition |

### Optimization demonstration

The untuned mechanical baseline and one dev-A-optimized candidate are separate
arms with different freeze times. This report keeps the preregistered baseline
comparison separate from the later optimization demonstration.

E02 is the named contrast, and the query-path measurement gives it a mechanism to
test. Declaring FK-backed relationships supplies the join paths whose absence left
Omni's agent with no compiled route to cross-table access. The demonstration asks
whether a model that can express a join changes the path the agent takes and
whether that changes accuracy. Neither is assumed here, and E02's topics still
declare no measures, so aggregation may continue to arrive as rewritten SQL.

| Item | Value |
| --- | --- |
| Optimized candidate identity | SLOT_OPTIMIZED_C4_CANDIDATE_ID |
| Optimized candidate freeze commit | SLOT_OPTIMIZED_C4_FREEZE_COMMIT |
| Optimized C4 mean accuracy | SLOT_OPTIMIZED_C4_MEAN_ACCURACY |
| Optimized minus untuned C4 | SLOT_OPTIMIZED_C4_MINUS_BASELINE_DIFF |
| E02 dev-A accuracy | SLOT_E02_DEVA_ACCURACY |
| E02 dev-A decision | SLOT_E02_DEVA_DECISION |
| E02 questions fixed | SLOT_E02_DEVA_FIXED |
| E02 questions regressed | SLOT_E02_DEVA_REGRESSED |
| E02 terminal error-count change | SLOT_E02_DEVA_ERROR_DELTA |

Both frozen scorers are reported for every arm. Neither was selected or modified
after seeing a result.

---

## What we recommend to the product team

Five recommendations follow from development evidence that is already final. Each
names the finding it comes from.

**1. Make grain contracts explicit and inspectable.** Model import and AI-facing
authoring should represent metric grain, entity identity, relationship
cardinality, and aggregation semantics as declared fields rather than as prose to
be inferred. Ship a dry run that shows which definitions cannot be governed and
which specific contract is missing for each. Finding 1: 511 of 1,090 definitions
deferred, with three loss codes accounting for the bulk of them.

**2. Treat retrieval payloads as part of the agent contract.** Schema and
semantic search should be query-directed, bounded, and observable, with context
volume per tool call in telemetry and typed public provenance identifiers so that
safety filters do not reject legitimate semantic metadata. Finding 4: one
unbounded schema call ended an attempt before it wrote a line of SQL.

**3. Separate why an agent did not answer.** A content refusal, an explicit
statement that the schema is insufficient, budget exhaustion, and infrastructure
failure imply four different product actions. Retain those raw states even when a
report also groups them. Finding 3 and PF-008: today they collapse into one
terminal state, and the collapse hides the largest single failure class in the
governed run.

**4. Expose relationship coverage before deployment.** Public schema contained
1,049 conservative primary-key or unique-backed relationships. The bounded
modeled candidate could expose 91 of them across 16 databases and 67 source
topics. A model author needs a dry-run view of accepted, deferred, and
unreachable relationships before deciding whether a semantic model has enough
structure to answer governed queries at all. Findings 1 and 5.

**5. Make semantic result contracts total, typed, and diagnosable at authoring
time.** Planning and execution should expose a stable representation for unknown,
boolean, temporal, and null values, should separate selected output fields from
dependency metadata, and should not report `UNKNOWN` for a field the JSON
execution endpoint can return. Where an output type cannot be resolved, model
validation should say so at publish time, naming the field and the reason, rather
than accepting the model and surfacing an untyped value on a later user query.
Model import should also document whether a programmatic author is expected to
declare an output type for a derived field, since neither validation nor readback
currently indicates that one is required. The contract that most needs writing
down is the one over rewritten SQL: when the agent authors the query, most of the
columns the planner must type are expressions the semantic model never declared,
and nothing states what the planner guarantees for them. Finding 3: 31 of 34
terminal failures were an `UNKNOWN` selected-field type, on models the product had
already accepted and validated without objection.

---

## How the study was run

**Split and freeze.** A deterministic split over public metadata assigned 231
development and 101 held-out questions, with every database in both partitions
and the public `high_level` distribution preserved. Development divides into 154
dev-A and 77 dev-B. Freeze A committed the population, both splits, the custody
rules, the C1 to C4 definitions, both scorers, and the statistical plan before
any hidden label was released. Freeze B committed the final system before any
held-out generation.

**Scoring.** Two versioned scorers were frozen before gold-driven development and
both are reported. The official comparator reproduces the public LiveSQLBench
evaluator at commit `e15cd221`, including its lossy behavior: comment stripping,
a regex removal of standalone `DISTINCT`, `ROUND` collapse, two-decimal
normalization, and set comparison that discards duplicate multiplicity. That
behavior is reproduced deliberately for comparability and is not corrected. A
separately named sensitivity scorer leaves authored SQL unchanged, compares
unordered results as multisets, honors the public decimal metadata, and preserves
null, boolean, and temporal distinctions. Full semantics in
[`docs/scoring.md`](scoring.md).

**Conditions.** C1 to C3 share one pinned direct-SQL scaffold, the same bounded
retrieval primitive, the same read-only attested database transport, and the same
budgets and retry ceilings. C4 preserves Omni's production-managed workflow,
because production fidelity outranks forcing model parity. The C4 harness sends
the bare question and reads back whatever query object the product returns; it
sets no mode flag and never rewrites, augments, or strips that object. Complete
condition disclosure, including the measured governed query path and where parity
is not achieved, is in
[`docs/harness-disclosure.md`](harness-disclosure.md).

**Custody, compressed.** Hidden dev-A annotations are offline diagnostic input:
they may shape how a reusable system is built and may never become
question-specific runtime input. Dev-B stays behind a guardian boundary that
returns only signed, replay-resistant aggregate receipts, metered to a hard
maximum of ten checkpoints. Held-out gold reaches a sealed evaluator only after
Freeze B. State artifacts are append-only and refuse overwrite; the control plane
verifies configuration against a recorded commit through Git objects rather than
through the working tree. That machinery determines whether these numbers can be
trusted. It is not the contribution, and the full design is in
[`EVALUATION_PROTOCOL.md`](../EVALUATION_PROTOCOL.md) and
[`docs/methodology.md`](methodology.md).

**Statistics.** Intervals are 95% question-clustered percentile bootstrap with
10,000 deterministic draws under a committed seed and an exact nearest-rank
convention. The primary C4 minus C1 contrast is unadjusted; the exploratory rung
family carries Holm correction at familywise alpha 0.05. Repetition-one McNemar
tests are sensitivity analyses only.

**What the executed system is.** The frozen untuned candidate is the mechanical
public-only transformation plus general compiler corrections driven by the Omni
validator: structured-leaf extraction operators, negative-scale numeric literals,
physical identity collapse, case normalization, alias handling. Every one carries
content provenance `public schema` and intervention provenance `generic product
improvement`. None carries content provenance `development gold` or intervention
provenance `dev-A failure`. The two provenance axes were preregistered so that
this claim is checkable rather than asserted. The untuned system receives no
question-level supervision and must not be described as tuned.

**Why the optimization phase was nearly lost.** Five semantic deployment
identities and five C4 run identities were spent before any governed accuracy
existed, and none of the ten produced a scored result. A custody protocol built
to protect measurements was being applied to zero-contamination infrastructure
passes, so every general compiler fix cost a full single-use human authorization
cycle. Authorization was retiered by contamination risk rather than by liveness,
and a bounded optimization demonstration was restored before any sealed
correctness was released. Both the cut and the restoration are recorded with
their dates in [`docs/protocol-diff.md`](protocol-diff.md), because the
alternative reading, that optimization was abandoned after C3 underperformed C2,
is available to a reader and deserves an answer from the contemporaneous ledger
rather than from this narrative.

---

## Limitations

**The held-out frame is 89 of 101 questions on 16 of 18 databases.** Before any
sealed generation, label release, or outcome access, the executed population was
reduced from the committed 101-question split to the 89 questions on the 16
databases with verified governed deployments. All four conditions and all three
repetitions use identical membership, so the comparisons remain paired, but the
estimand is narrower: performance on 16 officially loadable databases, not on all
18 in Large-v1. The 12 excluded questions are a scope deviation and may not be
read as model failures, gold failures, or condition-specific missingness. The
decision used public split membership by database and public loader evidence
only.

**The exclusion traces to an upstream loader defect, and reproducing it was the
correct choice.** The pinned official Linux loader matches dump filenames exactly
and skips on a miss. Its table list for `mental_healths_large` spells an entry
`Facilities`; the archive ships `facilities.sql`. The loader warns and moves on.
The result is 21 of 55 declared tables loaded there and 20 of 57 in
`organ_transplant_large`, leaving 34 and 37 tables absent from the official
reference database. Reference SQL for the affected questions fails in the
official environment exactly as it fails here. An earlier investigation concluded
this was a local provisioning defect and was wrong; it compared the archive
against the restore order without reading the loader that consumes both.
Restoring the omitted files would break comparability with published
LiveSQLBench results, so the defect is reproduced and disclosed rather than
patched. Eighteen dev-A questions (nine per database) and 12 held-out questions
are affected. Across all 18 databases, 71 tables are skipped over a case variant
present in the archive, and one is absent under any spelling.

**Development results are adaptively reusable, not held-out.** The C1 to C3
figures cover 140 of 154 dev-A questions at generation time and 122
official-scoreable questions per condition after reference-SQL conformance. C4's
9/136 uses its own full answerable frame. The raw gap between those percentages
is not a matched or paired contrast; the aligned 122-question comparison reported
in Finding 2 is. None of it is evidence about unseen questions.

**C4 is a composite production system.** Unless its underlying model and resource
settings can be matched exactly, C4 minus C3 is a system-level comparison and not
an isolated estimate of the effect of enforcement. Two public probes reported
Bedrock `claude-opus-5`, but stage and model stability across scaled runs remains
unproven, and an aggregate model label must not be presented as exact parity when
internal routing is opaque.

**The 34 governed contract failures are not attributed.** The compiled bundles
declare no output type on any field, and the product validated them without
objection and later reported `UNKNOWN` for a selected field's type at query
planning time. Whether declaring the type at compile time changes the outcome has
not been tested. Both the accuracy and the contract-failure rate reported for C4
carry this ambiguity, and no corrected C4 accuracy exists, because no
intervention has converted a single one of those attempts.

**The C4 structural aggregates rest on query text, not on declared model
structure.** Relation counts, join presence, and aggregate presence are computed
from the SQL carried on each governed semantic query, because C4 records store no
separate compiled SQL. The deployed topics declare no joins and no measures. The
relation count includes CTE references, aliased self-joins, and subquery sources,
so multi-relation prevalence is an upper bound on cross-table access. These
aggregates support the descriptive claims made for them here and no stronger
claim about how the governed path composed its queries.

**This study does not isolate semantic-layer query composition, and no achievable
parity would make it do so.** The governed condition was preregistered to
contrast a compiled query path against direct SQL. It did not exercise one. Every
governed query took Omni's raw-SQL rewrite path, and the deployed model declared
no join path and no measure for a planner to compile, so C4 minus C3 does not
differ on who composes the query or on join and aggregation semantics. What it
still differs on is the agent, the resolution of field references at rewrite
time, the accessible surface, and the execution contract. This is separate from
the composite-system limitation above: matching C4's model exactly would not
restore the composition contrast. Every number reported for C4 stands; the claim
attached to it is narrower than the design intended.

**Accuracy on the governed frame is bounded above by 102/136, or 75%, for any
modeling change,** because a contract failure occurs downstream of the semantic
query an intervention would alter. That is a property of the measurement, not of
the system's answer quality.

**The direct baseline excludes two databases.** `archeology_scan_large`
repeatedly failed to return a usable direct answer across distinct retrieval
settings, and `cybermarket_pattern_large` was excluded after its first immutable
launch failed read-only privilege attestation. Both exclusions are fixed in a
committed artifact and predate outcome access. C1 to C3 development behavior is
therefore estimated on 16 databases.

**Transformation coverage is not correctness.** Finding 1 measures what the
compiler could govern. A deferred definition may be irrelevant to every question,
and a compiled one can still be retrieved or interpreted wrongly.

**Single-question sequences are not population estimates.** Finding 4's canary
table is one question on one database. The full-scale cost figures are the
population claim; the canary is the mechanism.

**The four-table schema window is an unvalidated scaffold choice.** A 20-question
sensitivity arm varying only the match cap from four to eight was frozen with
fixed membership and deferred from the MVP critical path without execution.

**Structural analysis is descriptive.** Relation counts correlate with failure in
both paths. They do not establish causality and cannot place a failure on the
mechanism ladder.

**Execution equivalence is the authority.** AI Hub diagnostics and judge outcomes
explain behavior; they do not replace result-set scoring, and disagreement
between them is recorded as a product finding rather than resolved in favor of
either.

**No placeholder is a result.** Every `SLOT_` token in this document is
unavailable. It is not small, not zero, and not projected.

---

## Slot register

Each slot, the artifact that supplies it, and its denominator. A fill-in pass
should resolve every token in this table and no others.

| Slot | Source artifact | Denominator |
| --- | --- | --- |
| SLOT_C4_MEAN_ACCURACY | Sealed custody official aggregate receipt, untuned arm | 267 C4 trials (89 questions by 3 repetitions) |
| SLOT_C4_MEAN_ACCURACY_CI | Same receipt, question-clustered bootstrap block | 89 clustered questions |
| SLOT_C4_REP1_ACCURACY | Same receipt, repetition-one partition | 89 C4 repetition-one trials |
| SLOT_C4_REP1_ACCURACY_CI | Same receipt, repetition-one bootstrap block | 89 clustered questions |
| SLOT_C4_MINUS_C1_DIFF | Sealed paired-contrast block, primary endpoint | 89 paired questions by 3 repetitions |
| SLOT_C4_MINUS_C1_CI | Same block, question-clustered bootstrap | 89 clustered questions |
| SLOT_C1_MEAN_ACCURACY, SLOT_C2_MEAN_ACCURACY, SLOT_C3_MEAN_ACCURACY | Sealed official aggregate receipt, per condition | 267 trials per condition |
| SLOT_C1_WRONG_RATE, SLOT_C2_WRONG_RATE, SLOT_C3_WRONG_RATE, SLOT_C4_WRONG_RATE | Same receipt, three-state outcome counts | 267 trials per condition |
| SLOT_C1_ERROR_RATE, SLOT_C2_ERROR_RATE, SLOT_C3_ERROR_RATE, SLOT_C4_ERROR_RATE | Same receipt, `refused_or_error` counts | 267 trials per condition |
| SLOT_C1_PASS3, SLOT_C2_PASS3, SLOT_C3_PASS3, SLOT_C4_PASS3 | Sealed three-run reliability block | 89 questions per condition |
| SLOT_C1_FLIPS, SLOT_C2_FLIPS, SLOT_C3_FLIPS, SLOT_C4_FLIPS | Same reliability block, correctness-flip counts | 89 questions per condition |
| SLOT_C1_SENSITIVITY_ACCURACY, SLOT_C2_SENSITIVITY_ACCURACY, SLOT_C3_SENSITIVITY_ACCURACY, SLOT_C4_SENSITIVITY_ACCURACY | Sealed sensitivity aggregate receipt | Trials retained by the sensitivity scorer per condition, reported with the receipt |
| SLOT_C2_MINUS_C1_DIFF, SLOT_C3_MINUS_C2_DIFF, SLOT_C4_MINUS_C3_DIFF | Sealed exploratory rung block | 89 paired questions by 3 repetitions per contrast |
| SLOT_C2_MINUS_C1_HOLM_P, SLOT_C3_MINUS_C2_HOLM_P, SLOT_C4_MINUS_C3_HOLM_P | Same block, Holm correction at familywise alpha 0.05 | Family of three exploratory contrasts |
| SLOT_OPTIMIZED_C4_CANDIDATE_ID | Optimized-candidate freeze manifest | Identity, no denominator |
| SLOT_OPTIMIZED_C4_FREEZE_COMMIT | Optimized-candidate freeze manifest | Identity, no denominator |
| SLOT_OPTIMIZED_C4_MEAN_ACCURACY | Sealed official aggregate receipt, optimized arm | 267 optimized-C4 trials on the same 89-question frame |
| SLOT_OPTIMIZED_C4_MINUS_BASELINE_DIFF | Sealed paired block across the two C4 arms | 89 paired questions by 3 repetitions |
| SLOT_E02_DEVA_ACCURACY | E02 dev-A score artifact under generation identity `e02-dev-a-v2` | 136 answerable dev-A questions |
| SLOT_E02_DEVA_DECISION | E02 experiment decision record, KEEP or REVERT | Categorical, no denominator |
| SLOT_E02_DEVA_FIXED, SLOT_E02_DEVA_REGRESSED | E02 regression-accounting block | Frozen baseline-correct dev-A set |
| SLOT_E02_DEVA_ERROR_DELTA | E02 terminal-failure-vector block | 136 answerable dev-A questions |

---

## Reproducibility and supporting material

The repository preserves the public manifest and deterministic split, public HKB
and schema inputs with their hashes, the transformation artifacts, condition
disclosure, the telemetry contract, the full experiment ledger, and both frozen
scorers. Private gold and hidden annotations are outside the repository.

The untuned baseline system is frozen at commit
`8b0c7393d564d9ecc2c2f84ba7446d610c1a0a6d`, with direct-child control commit
`94cc0d9483c944d7dc13ed651c8fc2ef077f33ab` and Freeze-B manifest SHA-256
`e1c9f1967422822c848c18a17ba759d4e4fbc7f21aa0fe3ae1045b9236ae4730`. The frozen
mechanical selection is SHA-256
`256145c13cfae7142d92f108b4ee9dd93e658a44cafb683e5aec90170b8315cc`. The C4
development recovery manifest, which accounts for all 45 original capture
failures as 11 result-only replays and 34 evaluated-system failures, is SHA-256
`5d6ff474f30d3de6d703ad5c6c59373fe8093515eabb83473bdb352c4f30fd9f`. The optimized
candidate's freeze identity is SLOT_OPTIMIZED_C4_FREEZE_COMMIT.

| Reading for | Document |
| --- | --- |
| Preregistered design, custody, freeze plan | [`EVALUATION_PROTOCOL.md`](../EVALUATION_PROTOCOL.md) |
| Scorer semantics, both frozen versions | [`docs/scoring.md`](scoring.md) |
| Condition scaffolds and telemetry contract | [`docs/harness-disclosure.md`](harness-disclosure.md) |
| HKB source boundary and dependency topology | [`docs/hkb-semantic-baseline.md`](hkb-semantic-baseline.md) |
| Mechanism ladder and category prevalence | [`docs/failure-taxonomy.md`](failure-taxonomy.md) |
| Product findings ledger, PF-001 through PF-014 | [`docs/product-findings.md`](product-findings.md) |
| Contract-failure reliability family | [`docs/c4-reliability-intervention-family.md`](c4-reliability-intervention-family.md) |
| Protocol amendments and their dates | [`docs/protocol-diff.md`](protocol-diff.md) |
| Contemporaneous decision ledger | [`docs/research-log.md`](research-log.md) |
| Full protocol paper | [`manuscript/main.pdf`](../manuscript/main.pdf) |

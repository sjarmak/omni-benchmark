# Omni on LiveSQLBench Large-v1: Accuracy, Reliability, and Product Findings

## Results report

> **Status, 2026-08-31.** The primary C1-C4 held-out evaluation is complete and
> frozen; its numbers are final and nothing since has changed them. A mechanism
> analysis, C5, has since run on development data to test the interpretation of
> the observed C4 behavior. It does not alter, rerun, or reopen the sealed
> evaluation and makes no held-out claim; it refines the product-level
> explanation of the result. C5 was registered after the
> sealed aggregates became visible, which is recorded in D-197 and is exactly
> why it is confined to dev-A. Design:
> [`docs/c5-tuned-governed-condition.md`](docs/c5-tuned-governed-condition.md).
> Trajectory across all experiments:
> [`docs/experiment-trajectory.md`](docs/experiment-trajectory.md).
>
> The C1-C4 baseline was scored on the matched 89-question held-out frame under
> both frozen scorers. Only identity-free aggregates left custody. E01 is an
> audited baseline no-op; E02 is INCONCLUSIVE because five transport failures
> captured no semantic query; E05 is INCONCLUSIVE by its own stopping rule and
> consumed no live attempt. Section 5 carries those results, section 6 the
> held-out numbers, section 9 the limitations.

## Contents

The executive summary and section 6 carry the result. Sections 1-5 carry the
design and the development trajectory; sections 7-8 carry the product reading;
sections 9-10 carry the limits and the reproduction path.

1. [Research question](#1-research-question)
2. [Experimental design](#2-experimental-design)
3. [Public-only baseline construction](#3-public-only-baseline-construction)
4. [First end-to-end vertical slice](#4-first-end-to-end-vertical-slice)
5. [Baseline and development trajectory](#5-baseline-and-development-trajectory)
6. [Held-out results](#6-held-out-results)
7. [Product recommendations](#7-product-recommendations)
8. [What this suggests for an ongoing evaluation program](#8-what-this-suggests-for-an-ongoing-evaluation-program)
9. [Limitations](#9-limitations)
10. [Reproducibility](#10-reproducibility)

## Executive summary

This study evaluates Omni on LiveSQLBench Large-v1 and separates three questions:
whether business knowledge helps an analytical agent, what is lost when that
knowledge becomes an executable semantic model, and what Omni's governed runtime
actually does with that model. The benchmark contributes 332 eligible analytical
tasks: 231 development questions, split into 154 dev-A and 77 metered dev-B, and
an original sealed split of 101. The frozen candidate received no question-level
supervision and consumed no metered checkpoint. Four conditions separate access
to raw schema, business knowledge, structured semantic knowledge, and governed
execution.

**Headline held-out result, on the pre-outcome matched frame.** Official mean
accuracy was 10.1% for C1, 22.1% for C2, 8.6% for C3, and 8.6% for C4; corrected
sensitivity was 10.1%, 19.5%, 8.6%, and 9.7%. This comparison covers 89 of the
original 101 held-out questions, on the 16 databases with verified C4
deployments. The frame was narrowed before any sealed generation, label release,
or outcome access because the pinned official loader left required tables
unavailable in the other two databases: it builds each dump path as
`<declared table>.sql` and matches filenames exactly, so where the declared
table names are mixed or upper case and the archive files are lowercase it
skips them silently. That is 34 of 55 tables in `mental_healths_large` and 37 of
57 in `organ_transplant_large`. Gold SQL for those databases then references
tables that never loaded, both frozen scorers record `gold_statement_error`, and
all 18 of their dev-A questions are unscorable under either scorer. The defect
is upstream, not ours; the same bug was fixed twice in the Base loader. Filed
2026-08-29 as
[bird-bench/livesqlbench#10](https://github.com/bird-bench/livesqlbench/issues/10),
with the full audit in
[`docs/livesqlbench-upstream-loader-report-draft.md`](docs/livesqlbench-upstream-loader-report-draft.md). All four conditions and all three repetitions use
the same 89 questions; the result estimates performance on those 16 deployable
databases, not the full 18-database benchmark.

The product interpretation is not that business semantics failed to matter. On
this benchmark, C2 shows that searchable business knowledge mattered: it improved
the direct comparator by 12.0 percentage points under the official scorer. The
loss occurred in translation and execution. Only 17.7% of the 1,090 public HKB
definitions compiled into executable objects, while 46.9% were deferred across
an unresolved grain. The deployed C4 model consequently declared no joins or
measures, and Omni's production agent wrote the SQL itself over model-resolved
field references. The product opportunity is to preserve useful business semantics
as executable grain, relationship, and aggregation contracts, then make the
governed runtime use them.

The sealed comparison and development evidence support seven findings:

1. Grain and relationship contracts were the main recorded obstacle to
   converting business knowledge into executable semantic objects. Across all
   1,090 definitions, 193 (17.7%) compiled, 193 (17.7%)
   were retained as searchable context, 511 (46.9%) were deferred because they
   crossed an unresolved grain, and 193 (17.7%) were unsupported. The most
   common recorded losses in the 17-database fan-out were unknown cardinality,
   unspecified aggregation, and missing cross-grain identity.

2. Searchable raw business knowledge produced the strongest direct-SQL
   development baseline. Official accuracy on 122 scoreable dev-A questions was
   7.4% for C1, 23.8% for C2, and 13.1% for C3. The sensitivity scorer preserved
   that ordering. Governed C4 separately scored 9/136 (6.6%), with 34 explicit
   refused/system-error outcomes. These are exploratory development results.

3. Wrong answers dominate the direct baseline. Across the three conditions, 245
   of 366 scoreable attempts were wrong, 67 refused or errored, and 54 were
   correct. Wrong SQL used more relations on average in every condition, while
   30 of 31 window-query attempts and 25 of 28 distinct-query attempts were
   wrong. Join or aggregate presence alone did not separate correct from wrong
   answers. Governed C4 showed the same directional relationship: parseable
   correct queries averaged 1.67 relations, compared with 2.62 for wrong answers
   and 2.88 for system-error outcomes. This is descriptive rather than causal.

4. Bounded schema retrieval made the direct comparator runnable and established
   a hard payload limit. The schema tool now returns at most four tables and 64
   KiB per call, compared with a 51-table response on the original canary. The
   direct development baseline averaged $1.48 to $1.84 per attempt across
   C1-C3. The hard payload bound and observed end-to-end cost are separate
   measurements. On the sealed frame, C4 used 3.9 times C1's median tokens, 1.5
   times its latency, and 2.3 times its tool calls without an accuracy gain.

5. The governed path exposed a distinct evaluated-system reliability surface.
   Thirty-four of 136 scoreable C4 attempts failed to reach a scoreable answer
   at the validation or result-contract stage rather than ending in a result
   mismatch: 31 on an unknown selected-field type, 2 on a persistent plan
   rejection, and 1 on a completed job carrying no parseable query. Causal
   ownership is partly bounded rather than wholly unresolved. A missing type
   declaration on our compiled model can account for at most 6 of the 31, and
   that ceiling is generous: it counts an attempt whenever a single compiled
   derived dimension appears anywhere in its selected set, and none selects them
   exclusively, so the true value lies in [0, 6]. Widening from derived to any
   compiled field at all reaches only 7 of 31. The remaining 24 select only
   query-local aliases, undeclared schema columns, invented names, and Omni's
   count built-in, which no compile-time declaration can type. What is genuinely
   unresolved is the interface between the authored model and Omni's planning and
   result contract for those 24. Eleven
   additional capture gaps were recoverable by replaying only an
   already-generated semantic query; question-level model reasoning was never
   rerun.

6. The governed condition did not compile metrics from the semantic model. Omni's
   production agent authored the SQL on every attempt that produced an
   inspectable query: 661 of 661 parseable governed queries across six arms carry
   agent-authored `userEditedSQL`. On the development baseline that is 135 of 135;
   on the sealed frame it is 261 of 261. That SQL is not raw table SQL. It
   references the deployed model through `${view.field}` templating on 660 of the
   661, so field-level definitions resolve, and most attempts also take the
   model's join scope through `join_paths_from_topic_name`: 94 of 135 on dev-A C4,
   132 of 134 on C5, 48, 53, and 48 across the three sealed repetitions. What the
   model never supplied is the aggregation. An aggregate hand-written over a field
   reference, which Omni documents as the signal that a topic lacks the measure a
   metric needs, appears on 34.1% of dev-A C4 attempts and 38.1% of C5; a `FROM`
   naming a physical table rather than a model reference appears on 26.0% to
   33.0% across arms. The deployed C4 topics publish no joins and no measures,
   because the conservative compiler deferred 46.9% of definitions as cross-grain.
   C5 later published a join for every qualifying foreign key, which raised topic
   scoping from 69.6% to 98.5% and left the hand-written-aggregate rate flat,
   consistent with the missing measures rather than the missing joins being the
   binding constraint. The study can no longer claim that C4 minus C3 isolates
   semantic-layer query composition.

   > **Corrected 2026-08-31 (D-211).** This paragraph previously read "661 of 661
   > parseable attempts on the raw-SQL rewrite path, zero composed". That claim
   > rested on `rewriteSql`, which Omni sets by default on any query carrying
   > authored SQL and which is therefore true on every attempt, and on
   > `join_via_map`, which a submitted query never populates. Remeasurement with
   > the fields that do vary produced the description above.

7. On the matched 89-question, 16-database held-out frame, the comparison
   supports the value of searchable raw business knowledge but not the governed
   mechanical system. Official mean accuracy is
   10.1% for C1, 22.1% for C2, 8.6% for C3, and 8.6% for C4; corrected
   sensitivity gives 10.1%, 19.5%, 8.6%, and 9.7%. C2−C1 is +12.0 percentage
   points (95% interval 5.6 to 18.7) under the official scorer and +9.4 points
   (3.4 to 15.7) under sensitivity. C4−C1 is -1.5 points (-7.1 to 4.1) and
   -0.4 points (-6.4 to 5.6), respectively. Thus the positive result is
   access to searchable HKB context; C4 does not improve on direct-only C1.

## 1. Research question

The primary question is:

> Given a modeled database, how accurately does production-governed Omni answer
> previously unseen analytical questions?

The primary comparison is governed Omni against the frozen direct-SQL
comparator on the same sealed questions. Three additional contrasts help explain any
difference:

| Condition | Information available at runtime | Query path |
| --- | --- | --- |
| C1 | Public schema | Direct SQL |
| C2 | Public schema and searchable HKB | Direct SQL |
| C3 | Public schema and searchable Omni model | Direct SQL |
| C4 | Omni semantic model | Omni agent authors SQL over model-resolved field references, with join scope from the model on most attempts |

**What "production-governed Omni" turned out to mean.** C4 was preregistered as
the governed condition against three direct-SQL comparators. Measured on the
frozen development baseline, the governed path is also an agent authoring SQL.
All 135 semantic queries carry agent-authored SQL in `userEditedSQL`, written in
Omni's `${view.field}` reference syntax so the model resolves the fields; the
deployed model publishes no joins and no measures, so no compiled cross-table or
aggregate path existed to take. The choice of path was
Omni's own: the harness posts only a model identifier, the bare question, and a
branch identifier, and exposes no mode flag. The semantic layer still does work,
as a field vocabulary Omni resolves at rewrite time, including HKB-backed derived
definitions on 39 of 135 attempts. It does not compose the query. Full
measurement is in [`docs/c4-query-path-disclosure.md`](docs/c4-query-path-disclosure.md).

C2−C1 tests the value associated with making business knowledge available.
C3−C2 tests the value associated with structuring that knowledge. C4−C3 is a
system-level, scaffold-conditional comparison unless model and runtime parity
can genuinely isolate enforcement. The direct conditions use one pinned Claude
OAuth scaffold, while C4 preserves Omni's production-managed workflow and may
use a composite model system. Read C4−C3 with the measured query path in view:
it compares two agent-authored SQL conditions that differ in agent, SQL dialect,
accessible surface, and execution contract. It does not compare a compiled-query
condition against a direct-SQL one, and it does not separate join or aggregation
semantics, because in neither arm does a semantic layer resolve a join path or
compile a measure.

## 2. Experimental design

The pinned public benchmark has 480 instances across 18 PostgreSQL databases.
We excluded 148 `Management` tasks and retained all 332 `Query` tasks. A
deterministic split, based only on public metadata and stratified primarily by
database and `high_level`, assigned 231 questions to development and 101 to the
sealed final evaluation. Every database appears in both partitions.

The 231 development questions are split into dev-A (154) and dev-B (77). The
protocol permits repeated use of dev-A and metered dev-B checkpoints. No
supervised intervention was promoted into the sealed system and dev-B remains
unconsumed. All four frozen baseline conditions produced three independent,
interleaved attempts for each of the 89 selected questions before any sealed
correctness was released. The later scoring-order deviation leaves E02 as a
pre-specified dev-A mechanism contrast only; there is no optimized held-out arm.

The official Large-v1 Linux loader skips 34 declared tables in
`mental_healths_large` and 37 in `organ_transplant_large` because their archive
filenames differ in capitalization. The committed dev-A split assigns nine
questions to each database, and their reference SQL cannot run in the official
environment. The fixed development frame therefore schedules all 154 questions,
reports those 18 as scorer-conformance exclusions, and evaluates C4 on all 136
answerable questions. The exclusion identities and public-only
derivation are bound in
[`dev-a-scorer-conformance-exclusions-v1.json`](config/conditions/dev-a-scorer-conformance-exclusions-v1.json).

Two database exclusions apply only to the public C1−C3 baseline-generation
frame. `archeology_scan_large` repeatedly failed to return a usable direct
answer across distinct retrieval settings; `cybermarket_pattern_large` was
excluded after its first immutable launch failed read-only privilege
attestation, even though the external credential was subsequently repaired.
The resulting direct baseline contains 630 attempts over 210 development
questions and 16 databases. Both exclusions are fixed in
[`public-baseline-exclusions-v1.json`](config/conditions/public-baseline-exclusions-v1.json)
and will be reported as scope limitations. Their records stay outside the wrong
answer and missing-row categories.

C4 development generation is budgeted and scheduled separately from this
direct arm. It schedules all 154 dev-A questions across all 18 databases;
reporting requires complete coverage of the fixed 136 answerable questions.
Condition comparisons use only matched question/database coverage.

The same loader defect prevents an honest mechanical C4 deployment for the two
affected databases in the sealed arm. Before Freeze B, sealed generation, or
label release, the final frame was amended to the 89 held-out questions on the
16 databases with verified C4 deployments. All four conditions and all three
repetitions use that exact membership, for 1,068 scheduled attempts. The 12
excluded questions are a public-loader scope deviation, not system failures or
missing outcomes. This narrows the held-out estimand from all 18 benchmark
databases to the 16 deployable databases without using question content,
labels, or correctness.

The complete preregistration, custody rules, scorer definitions, and condition
disclosure are in [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md),
[docs/scoring.md](docs/scoring.md), and
[docs/harness-disclosure.md](docs/harness-disclosure.md).

## 3. Public-only baseline construction

Before using hidden development labels, we transformed only public schema,
column metadata, and the hierarchical knowledge base into deterministic Omni
artifacts. The HKB forms a dependency graph. Its 1,090 entries
declare 945 direct dependency edges; 560 entries depend on at least one other
entry, and 344 edges point to another derived entry. Every database contains a
multi-hop dependency, and the longest chain spans six edges. A transformation
that indexes each definition independently therefore loses part of the public
business logic before an agent sees a question.

Every knowledge node received exactly one disposition:

- `compile`: a defensible same-table, same-grain scalar definition;
- `context_only`: useful semantic text with one exact field target but no safe
  executable object;
- `defer_cross_grain`: a definition requiring unresolved identity,
  relationship, cardinality, aggregation, temporal, or ordering semantics; or
- `unsupported`: missing, ambiguous, or currently non-representable inputs.

This conservative rule is intentional. Guessing a join or aggregation would
increase apparent model coverage while weakening the governance claim the
benchmark is meant to test. Mapping and bundle artifacts preserve their public
content provenance, modeling-intervention provenance, validation status, and
content hashes.

### Finding 1: missing grain contracts dominate HKB translation

Experiment [D-043](docs/research-log.md#2026-08-28--d-043-preserve-cross-database-hkb-representability-as-baseline-evidence)
applied the canary's no-guess classification discipline to all 17 remaining
databases. Combining those records with the 54-node canary gives the complete
18-database picture below.

| Disposition | Definitions | Share |
| --- | ---: | ---: |
| Compiled | 193 | 17.7% |
| Context only | 193 | 17.7% |
| Deferred cross-grain | 511 | 46.9% |
| Unsupported | 193 | 17.7% |
| **Total** | **1,090** | **100.0%** |

**What the 17.7% is a property of.** It is a joint property of the knowledge
base and the compilation rule, and it is not a claim that 82.3% of business
knowledge is uncompilable in principle. The compiler used here refuses to emit
any object whose grain, entity identity, cardinality, or aggregation the source
does not state. The public HKB states those contracts for 193 definitions. For
the rest it describes the business meaning without the structural facts an
executable object needs, which is why the leading loss codes are
`cardinality_unknown`, `aggregation_unspecified`, and `cross_grain_no_identity`
rather than anything about vocabulary. A more permissive compiler would emit
more objects by inferring the missing joins and aggregations, and those
inferences are exactly what a semantic layer exists to prevent an author from
making silently. A human modeler with domain access could supply the missing
contracts and raise the number; nothing in this study measures how far. So
17.7% should be read as the share of definitions whose contracts are explicit
enough to compile without guessing, under a documented no-guess rule, not as a
ceiling on the knowledge base.

Within the 17-database fan-out, the three most frequent loss codes were
`cardinality_unknown` (398), `aggregation_unspecified` (314), and
`cross_grain_no_identity` (308). Domains
with many row-local physical or sensor definitions, such as planets and solar
panels, compiled comparatively well. Residential and reverse-logistics models
retained useful context but compiled no HKB definitions safely under the same
rules.

This establishes transformation coverage only. The benchmark relevance of
deferred definitions and the compensating value of searchable context remain
unknown until scored runs.

The product implication is concrete: an HKB-import workflow needs first-class
metric grain, entity identity, relationship/cardinality, and aggregation
contracts. A useful compiler dry run should also explain why each definition
was compiled, retained as context, deferred, or rejected. Without that report,
users choose between silently guessed semantics and large amounts of prose with
uncertain agent discovery.

The deterministic fan-out artifacts and review corrections landed in commits
`d3f84f6ea5d15b247e3d1ffba739cd220289e72a` and
`dcdd1a08a3d45a4a14978fe39f66542938fa5f32`. The detailed product record is
[PF-009](docs/product-findings.md#pf-009-missing-grain-contracts-dominate-public-only-hkb-translation).

## 4. First end-to-end vertical slice

We tested one public dev-A question on `archeology_scan_large` before scaling.
The slice validated that each condition could generate an answer, preserve a
trace, reach its read-only database, and produce an artifact compatible with the
frozen evaluation path. Correctness remained uninspected.

### Finding 2: bounded schema discovery exposed a scaffold-sensitivity risk

The initial C1 attempt passed public-question, database-parity, read-only,
model-identity, and first-turn gates. Its first schema inspection returned all
51 tables. The next model turn exceeded its budget before producing SQL.

Experiment [D-045](docs/research-log.md#2026-08-28--d-045-bound-direct-schema-discovery-before-raising-budget)
replaced whole-database inspection with deterministic query-directed search over
the same committed public schema. The model must supply a non-empty query; the
tool returns at most four matching tables within a 64 KiB payload. The same
retrieval contract is shared by C1−C3.

| Stage | Terminal state | Tokens | Cost | Latency | DB queries |
| --- | --- | ---: | ---: | ---: | ---: |
| Whole-schema C1 | Budget error | 173,365 | $1.7398935 | 26.0 s | 0 |
| First bounded diagnostic | Public-ID validation error | 1,585 | $0.017715 | 3.0 s | 0 |
| Reviewed bounded C1 canary | Answered | 33,445 | $0.214778 | 40.9 s | 2 |

The first bounded attempt exposed a second defect and returned no answer. A
generic secret heuristic rejected canonical public foreign-key IDs. A typed,
fail-closed validation rule fixed that boundary while retaining the credential
checks. The subsequent immutable canary reached SQL and produced a complete
trace. This sequence preserves the failed intermediate experiment and prevents
the full change from being attributed to retrieval alone.

The evidence supports three limited conclusions:

- the original failure came from unbounded scaffold context;
- bounded retrieval reduced the diagnostic context and cost enough to expose
  the next failure mechanism; and
- after the independent identifier fix, the direct comparator completed the
  same public integration slice.

The four-match value remains unvalidated. A later attempt on a
different archeology question reached five four-table searches, consumed
$7.49, and ended in `model_budget_error`. Reducing the window to two tables cut
that attempt to four searches and $4.32, but it still returned no answer. The
cheaper failure provided no evidence for adopting the smaller window, so the
change was reverted. Archeology was then excluded under the predeclared rule.

This sequence establishes a payload bound on one question and database. It
provides no execution-accuracy estimate or population cost ratio. D-054 froze a
20-question public-development sensitivity subset spanning all 16 included
databases. That arm changes only the match cap from four to eight and preserves the 64 KiB
per-call ceiling. It was deferred from the MVP critical path before execution;
membership remains fixed without reference to question-level outcomes.

The product lesson is broader than this comparator. Tool payload bounds are
part of agent quality: a semantically valid tool call can still make the system
unusable if it consumes the remaining inference budget. Tooling should expose
query-directed schema search, payload estimates, and typed provenance rather
than treating all identifiers as untrusted free text. The relevant commits are
`2b72244de9fefa4d4f7329ba159f571a8242da79` (bounded retrieval) and
`50ebc31075f742fba4e7d4bbc6fc4da0b15d53ce` (typed public relationship IDs).

## 5. Baseline and development trajectory

The condensed research path, including the experiments that returned nothing, is
[`docs/experiment-trajectory.md`](docs/experiment-trajectory.md); the
contemporaneous ledger is [`docs/research-log.md`](docs/research-log.md).

The 630-attempt C1-C3 baseline was frozen by content hash before the train-only
release. Its exact dev-A intersection contains 420 attempts over 140 of the 154
dev-A questions. Fourteen questions have no baseline output and were left
missing. Gold conformance left 122 questions per condition scoreable under the
official scorer; the other 18 failed because the official loader omitted tables
required by the benchmark reference SQL. The sensitivity scorer retained 121
questions per condition because one additional result exceeded its fixed
normalization limit.

| Condition | Correct | Wrong | Refused/error | Official accuracy | Sensitivity accuracy |
| --- | ---: | ---: | ---: | ---: | ---: |
| C1: raw schema | 9 | 80 | 33 | 9/122 (7.4%) | 9/121 (7.4%) |
| C2: searchable raw HKB | 29 | 91 | 2 | 29/122 (23.8%) | 28/121 (23.1%) |
| C3: searchable exported model | 16 | 74 | 32 | 16/122 (13.1%) | 14/121 (11.6%) |
| **All direct conditions** | **54** | **245** | **67** | **54/366 (14.8%)** | **51/363 (14.0%)** |

C2 also had the highest capture-level completion rate on the 16-database frame:
97.9%, compared with 75.9% for C1 and 74.8% for C3. Scoring changes the size of
that apparent advantage. Ninety-one of C2's 122 scoreable attempts returned a
wrong result, so completion cannot stand in for correctness.

The governed C4 arm uses the full fixed 154-question schedule rather than the
direct arm's 140-question represented frame. Under the official scorer, 136
questions were scoreable: 9 correct, 93 wrong, and 34 refused or
system-error, for 9/136 (6.6%) accuracy. The sensitivity scorer retained 135
scoreable questions and the same 9 correct and 93 wrong outcomes, for 9/135
(6.7%); 33 were refused or system-error.

An aggregate-only alignment to the 122 questions scoreable in all four
conditions gives C4 5 correct, 83 wrong, and 34 refused or system-error, or
5/122 (4.1%). On that same frame, C1 is 9/122 (7.4%), C2 is 29/122 (23.8%),
and C3 is 16/122 (13.1%). The paired C1/C4 table contains 3 questions correct
in both, 2 correct only in C4, 6 correct only in C1, and 111 correct in neither,
for a descriptive C4-C1 difference of -3.3 percentage points. These are
exploratory development contrasts, not held-out estimates, but they establish
that C4's low result is not an artifact of its broader scoreable denominator.
No question identity, SQL, row value, annotation, or per-question label left
custody during this alignment.

The failure diagnostic then examined SQL structure without exposing question
identities, SQL text, result values, or hidden annotations. All 299 correct-or-
wrong records parsed. Wrong answers used more relations on average in every
condition: 3.16 versus 2.00 in C1, 3.28 versus 2.48 in C2, and 3.04 versus 1.81
in C3. Windows, `DISTINCT`, and nesting were fragile, but join and aggregate
presence alone had similar wrong rates to their absence. This supports
relationship, grain, and dependency handling as the next mechanism family;
causality and question-specific fixes remain unresolved.

<details>
<summary>How the structural figures were computed, and what they overcount</summary>

C4's structural figures are computed from the semantic query's `userEditedSQL`
because `generated_sql` is `null` for every C4 attempt. That SQL is
agent-authored in Omni's dialect, so these figures describe agent-written queries
in both C4 and C1-C3 rather than a compiled path against authored ones. The
relation count also includes CTE references, aliased self-joins, and subquery
sources, which makes multi-relation prevalence an upper bound on genuine
cross-table access.

</details>

The same identity-free analysis covered all 136 governed C4 outcomes. All 9
correct queries parsed, as did 92 of 93 wrong answers and 32 of 34 explicit
system errors. Correct queries averaged 1.67 relations, versus 2.62 for wrong
answers and 2.88 for errors. Multi-relation queries appeared in 2/9 correct,
50/92 wrong, and 20/32 error cases; joins appeared in 2/9, 41/92, and 18/32.
These associations do not establish that relationships caused the failures.

The query-path measurement changes the standing of the intervention they
selected. E02 declares FK-backed relationships, which is the ingredient whose
absence left agent-authored joins as the only route to cross-table access. E02 is
therefore a direct test of that mechanism rather than a candidate chosen from a
structural correlation. Whether it is sufficient to move governed queries toward
composition is still being measured: its topics declare no measures, so the agent
must continue to write SQL in order to aggregate.

Later trace diagnosis uses the earliest supported failure point in a fixed
mechanism ladder: required knowledge absent, dependency graph wrong, retrieval
miss, interpretation error, compilation failure, validation or adapter
alteration, then residual model reasoning. This order prevents a retrieval or
compilation defect from being counted as a reasoning failure. The structural
analysis above does not assign ladder categories and cannot distinguish which
stage caused any particular wrong answer.

Four intervention families were fixed before the optimization phase was first cut
and later restored to the MVP before sealed correctness release:
same-grain
dependency composition (E01), FK-backed grain relationships (E02), bounded
semantic descriptions (E03), and a broad HKB-context negative control (E04).
Their reusable changes and promotion rules are recorded in
[`planned-dev-a-interventions-v1.json`](experiments/planned-dev-a-interventions-v1.json).

| Experiment | Evidence completed | Decision | Remaining gate |
| --- | --- | --- | --- |
| E01: same-grain dependencies | The frozen baseline already has 48 dependency-bearing elements, 70 executable dependency edges, and depth three | Inconclusive; already baseline | No further E01 contrast |
| E02: FK-backed relationships | 1,049 public FKs pass the conservative contract; the bounded artifact emits 91 relationships across 16 databases and 67 source topics, with zero metric-disposition changes; deployment v7 verified all 16 targets with exact readback; its fixed dev-A generation froze 117 answers and 19 capture-infrastructure failures | INCONCLUSIVE: five genuine transport failures contain no semantic query to replay, so the preregistered complete-136 score cannot be produced without a new model attempt | Stop; no promotion, rerun, or further experiment |
| E03: bounded descriptions | Prespecified only | Not run | Out of MVP scope after the scoring-order deviation |
| E04: broad HKB context | Prespecified negative control only | Not run | Out of MVP scope after the scoring-order deviation |
| E05: typed output fields | Registered against the 31 `UNKNOWN`-type contract failures; the preregistered precondition needed 16 of 31 attempts to select a compiled semantic field, and the measured ceiling is 6 of 31 | INCONCLUSIVE by its own stopping rule | Closed; consumed no live attempt |
| C5: docs-idiomatic tuned governed Omni | Registered 2026-08-30 under D-197, after sealed aggregates were visible. Widened view surface, full FK join graph, complete HKB port to `ai_context`. Public inputs only | Complete on dev-A: 18/136 (13.2%) against frozen C4's 9/136 (6.6%) on the identical frame, at 32% fewer median tokens; topic scoping rose to 132/134 while hand-written aggregates held at 38.1% | Development-only mechanism analysis; no held-out claim is available to it. Supports PF-016 and narrows the C4 interpretation |

The no-rerun E02 diagnostic preserves that formal decision while extracting the
usable evidence. Both frozen scorers were applied offline to the 117 captured
answers; no model answer was regenerated. Official E02 accuracy was 11/117
(9.4%) versus 9/117 (7.7%) for frozen C4 on those same coordinates, a +1.7-point
paired difference. Sensitivity was 10/116 (8.6%) versus 9/116 (7.8%), +0.9
points. Official transitions were four gains to correct and two regressions
from correct. The missing 19 coordinates comprise 14 saved queries rejected by
the result-type capture contract and five transport failures with no saved
query. Full-frame official bounds are 11/136 (8.1%) if all missing outcomes are
wrong and 30/136 (22.1%) if all are correct; treating the 14 contract failures
as failures and only the five transport losses as unresolved gives an upper
bound of 16/136 (11.8%). These wide, mechanism-dependent bounds and the small
number of correctness transitions support further study, not a claim that E02
improved accuracy. The aggregate artifact is
[`e02-partial-diagnostic-v1.json`](experiments/analysis/e02-partial-diagnostic-v1.json).

A fifth family, E05, was registered later against the 31 `UNKNOWN`-type contract
failures: declare explicit output types on compiled semantic fields. Its
preregistered precondition required at least 16 of those 31 attempts to select a
compiled derived field. Measured offline on the immutable generation records, the
ceiling is 6 of 31, and 24 of 31 select no compiled bundle field of any kind, so
no declaration on a compiled field can reach them. E05 is recorded INCONCLUSIVE
by its own stopping rule and consumed no live attempt.

<details>
<summary>Deployment sequence and artifact hashes</summary>

The deployment sequence preserved each failed pass rather than retrying it away.
Earlier records exposed sports identity errors, scientific-literal compilation
failures in planets, and exact-readback identity differences in polar. General
compiler and readback corrections addressed those mechanisms without adding a
database name, question, or hidden label to any rule. The final public-only v13
pass then validated and exactly read back all 16 answerable database bundles in
one current evidence set, with zero terminal or record-write failures. The two
fixed official-loader blockers remain explicit rather than fabricated as empty
models. The C4 plan binds that exact 16-deployment evidence set and retains all
154 scheduled identities, of which 136 are executable.

The corrected E02 artifact has candidate-set SHA-256
`12c4e1a8cab38f0f47e14b5c553c87c800ca07f27bae568171f1d7caaf7589a7`.
Public deployment v7 verified and exactly read back all 16 selected targets with
zero validation issues. The post-score correction only generalized endpoint
publication for public-schema relationships and did not use held-out outcomes;
it is not a promoted candidate. Its historical artifacts remain immutable.
The public C4 baseline evaluates the frozen mechanical baseline. Its immutable
selection SHA-256 is
`256145c13cfae7142d92f108b4ee9dd93e658a44cafb683e5aec90170b8315cc`.
An append-only recovery manifest accounts for all 45 original capture failures:
11 result-only replays and 34 explicit evaluated-system failures, SHA-256
`5d6ff474f30d3de6d703ad5c6c59373fe8093515eabb83473bdb352c4f30fd9f`.
The official aggregate receipt SHA-256 is
`0296753e8fcbf826a99ed2f86088ecdfb61981db8dea47d93e7871cef2690a78`.
Dev-B remains unconsumed.

</details>

### C5: the mechanism analysis

The query-path measurement leaves one question the frozen evidence cannot
answer. C4's low result is consistent with two very different explanations: the
governed path does not help on this benchmark, or the governed path was never
exercised because the model we could compile was too thin to compose against.
Those imply opposite product conclusions.

C5 separates them. It deploys Omni the way its own documentation prescribes,
from public inputs only: a view for every public table (47 to 63 per database
rather than the baseline's 6 to 11), a join for every foreign key that passes
the same conservative cardinality rule, and the complete public HKB ported into
`ai_context` at field, topic, and model level, with dependency chains inlined
prerequisite-first. Phase 1 declares no measures; a measures phase is proposed
under bead `omni-benchmark-w5x` and needs its own authorization.

**What "docs-idiomatic" does and does not cover.** C5 implements the structural
half of Omni's documented AI guidance: full view coverage, the FK join graph, and
`ai_context` at field, topic, and model level. It omits the rest of the documented
AI-optimization surface, and the omissions are not incidental. It publishes no
measures, which is the single key Omni's documentation ties most directly to the
behavior C5 was built to test, and it sets none of `ai_fields`, `synonyms`,
`sample_values`, `all_values`, `sample_queries`, or `ai_chat_topics`. C5 is
therefore a lower bound on what Omni's documented workflow reaches, not a ceiling,
and no result here should be read as the best the product can do when modeled
fully.

The headline contrast is C5 against C2 on their question
intersection, which asks how much of C2's demonstrated knowledge value governed
Omni delivers when the semantic model actually carries that knowledge.

Three things constrain what C5 can claim. It was registered on 2026-08-30 under
D-197, after the sealed aggregates were visible, so it is a dev-A condition and
no held-out claim is available to it; this is recorded rather than concealed,
and it is the reason C5 is confined to development data. Its design provenance
is the mechanism measurements above plus Omni's public documentation, not any
per-question outcome, and no question content, gold, or hidden annotation enters
any C5 artifact. It reports both frozen scorers, without selection, on a single
generation that is never rerun for a wrong answer.

#### What C5 measured

The single 136-attempt dev-A generation completed on 2026-08-31 under run
`c5-dev-a-v4`, bound to system commit `487c4dc4` and deployment
`c5-dev-a-deployment-v8` (16 of 16 databases verified). Both frozen scorers ran
on it, and both are reported.

On the identical 136-attempt governed frame, C5 doubles C4:

| Arm | Official Soft EX | Sensitivity |
| --- | --- | --- |
| C4, frozen governed baseline | 9 / 136 (6.6%) | 9 / 135 (6.7%) |
| C5, docs-idiomatic governed | 18 / 136 (13.2%) | 16 / 135 (11.9%) |

Terminal generation failures fell from 34 to 26. Both figures are post-recovery
and therefore comparable: C4's 34 is what remained after append-only recovery v5
replayed its 45 capture failures and converted 11 into typed results, and C5's 26
is what remained after the same hash-pinned recovery pass, which retrieved zero
recoverable sidecars. All 26 were classified `evaluated_system_failure`, so every
one counts against C5 as a candidate execution error rather than being set aside
as infrastructure.

The five conditions have never shared a question set: the direct arms were
frozen over 18 databases and the governed arms over the 16 with verified
deployments, and the direct freeze is itself missing 14 dev-A questions. On the
122-question intersection where all five can be compared directly:

| Condition | Official Soft EX | Sensitivity |
| --- | --- | --- |
| C1, raw schema, direct | 9 / 122 (7.4%) | 9 / 121 (7.4%) |
| C2, schema plus knowledge, direct | 29 / 122 (23.8%) | 28 / 121 (23.1%) |
| C3, schema plus retrieval, direct | 16 / 122 (13.1%) | 14 / 121 (11.6%) |
| C4, governed, sparse compiled model | 5 / 122 (4.1%) | 6 / 121 (5.0%) |
| C5, governed, docs-idiomatic | 13 / 122 (10.7%) | 12 / 121 (9.9%) |

Aggregate artifact:
[`experiments/analysis/c5-matched-122-comparison-v1.json`](experiments/analysis/c5-matched-122-comparison-v1.json).

#### Reading the result

C5 answers the question it was registered to answer. C4's low result was not a
property of the governed path as such. Deploying the same product the way its
documentation prescribes moves the governed arm from 4.1% to 10.7% on the
matched frame, a 2.6x change, and from below the raw-schema floor to above it.
C4 scored under C1; C5 scores over it. That is the first governed condition in
this evaluation to clear the floor.

It does not close the gap. C2 remains at 23.8% on the same questions, and C5
recovers about a third of the distance from C4 to C2: 8 of the 24 correct
answers that separate them under the official scorer, which is 33%, and 6 of 22
under the sensitivity scorer, which is 27%. The knowledge that helps a
model most on this benchmark is still worth more when handed to it directly than
when compiled into a semantic model and reached through the governed path.

C5 is also cheaper. Across the 136 matched attempts, median total tokens fell
from 583,188 to 396,884, median tool calls from 7 to 3, median database queries
from 2 to 1, and median latency from 50.6s to 32.5s. Accuracy and cost moved in
the same favorable direction, which is the signature of a model that made the
task easier rather than one that spent more effort on it.

The mechanism readout constrains the interpretation, and it separates two things
the first analysis merged. C5 did move the model's involvement: topic scoping,
measured by a non-empty `join_paths_from_topic_name`, rose from 94 of 135 dev-A
C4 attempts (69.6%) to 132 of 134 (98.5%). Publishing the full join graph made
the agent take the model's join scope on nearly every query. What C5 did not move
is metric composition. All 134 parseable C5 attempts return agent-authored
`userEditedSQL`, as do all 135 dev-A C4 and all 131 captured E02 attempts, 661 of
661 across six governed arms including the three sealed C4 repetitions. On 38.1%
of C5 attempts that SQL wraps an aggregate around a `${view.field}` reference
rather than naming a model measure, against 34.1% on dev-A C4, a rate the widened
model left essentially unchanged. Omni documents that shape as the signal that a
topic lacks the measure the metric needs, and neither C4 nor C5 defines measures.
Counts are tallied by
[`experiments/analysis/governed_query_path_tally.py`](experiments/analysis/governed_query_path_tally.py)
into
[`governed-query-path-tally-v2.json`](experiments/analysis/governed-query-path-tally-v2.json).

So C5's accuracy gain did not come from the semantic layer composing metrics. It
came from a widened view surface and ported knowledge that made the SQL the agent
writes anyway land on the right columns more often, with the model supplying
field resolution throughout and join scope on nearly every attempt.

> **Corrected 2026-08-31 (D-211).** This section previously reported "661 of 661
> parseable attempts on the rewrite path and zero composed" and concluded that
> C5's gain "did not come from the model using the semantic layer's join
> facilities". Both statements came from a classifier that tested `rewriteSql`,
> which is Omni's default for any query carrying authored SQL and is therefore
> constant, and `join_via_map`, which a submitted query never populates. The
> field that records join scope, `join_paths_from_topic_name`, was not read. C5
> did raise it from 69.6% to 98.5%.

Design and implementation map:
[`docs/c5-tuned-governed-condition.md`](docs/c5-tuned-governed-condition.md).

## 6. Held-out results

The frozen untuned comparison covers 89 held-out questions and 1,068 scheduled
attempts: four conditions, three repetitions, identical membership. The scorer
published both preregistered policies in one atomic run. This section uses only
the identity-free aggregates; no question identity, SQL, row, annotation, or
per-question correctness left custody.

**† C4 is not a valid measure of governed semantic composition.** Every sealed C4
attempt that produced an inspectable semantic query returned agent-authored SQL
rather than a metric composed from the model: 261 of 261 parseable queries, 88 of 89 in repetition one, 87 in repetition two, and 86 in repetition
three, with the remaining 6 of 267 attempts producing no query to inspect. Every
C4 row below therefore measures an agent writing SQL by hand with the semantic
model as context, at governed-path latency and cost.
See [`docs/c4-query-path-disclosure.md`](docs/c4-query-path-disclosure.md) and
[PF-016](docs/product-findings.md#pf-016-the-sql-authoring-pathway-is-not-surfaced-and-it-is-the-most-permissive-route).

### Primary endpoints

| Scorer | Endpoint | Estimate | 95% interval |
| --- | --- | ---: | ---: |
| Official-compatible Soft EX | C4 mean one-shot execution accuracy † | 8.6% | 3.7%–14.6% |
| Official-compatible Soft EX | C4 repetition-one execution accuracy † | 7.9% | 3.4%–13.5% |
| Official-compatible Soft EX | C4−C1 paired accuracy difference † | -1.5% | -7.1%–4.1% |
| Corrected multiset sensitivity | C4 mean one-shot execution accuracy † | 9.7% | 4.5%–15.7% |
| Corrected multiset sensitivity | C4 repetition-one execution accuracy † | 9.0% | 3.4%–15.7% |
| Corrected multiset sensitivity | C4−C1 paired accuracy difference † | -0.4% | -6.4%–5.6% |

### Four-condition matrix

| Scorer | Condition | Mean accuracy | Wrong rate | Refused/error | Error rate | Pass³ | Correctness flips |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Official-compatible Soft EX | C1 | 10.1% | 56.2% | 33.7% | 18.7% | 6.7% | 6 |
| Official-compatible Soft EX | C2 | 22.1% | 50.6% | 27.3% | 19.9% | 15.7% | 12 |
| Official-compatible Soft EX | C3 | 8.6% | 53.2% | 38.2% | 16.1% | 4.5% | 6 |
| Official-compatible Soft EX | C4 † | 8.6% | 77.2% | 14.2% | 14.2% | 6.7% | 4 |
| Corrected multiset sensitivity | C1 | 10.1% | 56.9% | 33.0% | 18.7% | 6.7% | 6 |
| Corrected multiset sensitivity | C2 | 19.5% | 54.7% | 25.8% | 19.9% | 14.6% | 10 |
| Corrected multiset sensitivity | C3 | 8.6% | 54.7% | 36.7% | 16.1% | 4.5% | 6 |
| Corrected multiset sensitivity | C4 † | 9.7% | 76.0% | 14.2% | 14.2% | 7.9% | 4 |

`Refused/error` is the scorer's third outcome among the 267 scoreable attempts
per condition; it complements correct and wrong. `Error rate` is narrower: the
share of all 267 scheduled generations whose raw terminal outcome was
`errored`, rather than `answered` or `refused`. Pass³ is the share of the 89
questions answered correctly in all three repetitions. Correctness flips count
questions correct in only one or two repetitions. These columns therefore
measure different reliability properties and should not be added together.

The frozen generation contract does not distinguish content refusal from
insufficient context, so those two rates are unavailable rather than inferred.

### Efficiency and operational reliability

The same 1,068 immutable attempts preserve provider-reported token usage where
available, end-to-end latency, tool activity, and terminal state. These are
workload measurements of each complete condition, not estimates of the semantic
layer's isolated causal cost. Dollar cost is available for the C1-C3 provider
surface and unavailable for C4's raw Omni job endpoint; unavailable does not
mean zero.

| Condition | Answered | Raw error | Raw refusal | Median latency, s (Tukey IQR) | Median tokens (Tukey IQR) | Median tool calls | Median DB queries | Mean cost/attempt | Total cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 67.0% | 18.7% | 14.2% | 33.4 (19.6-48.5) | 147.6k (63.9k-288.2k) | 3 | 1 | $1.43 | $381.28 |
| C2 | 74.2% | 19.9% | 6.0% | 44.0 (27.6-60.4) | 256.8k (137.8k-371.2k) | 4 | 2 | $1.90 | $506.66 |
| C3 | 63.3% | 16.1% | 20.6% | 39.2 (23.5-68.6) | 195.3k (89.1k-429.4k) | 3 | 2 | $1.84 | $491.70 |
| C4 | 85.8% | 14.2% | unavailable | 51.1 (39.8-91.6) | 580.8k (410.1k-1,029.3k) | 7 | 2 | unavailable | unavailable |

Latency coverage is complete. Token, tool-call, and database-query coverage is
267/267 for C1-C3 and 265/267 for C4. Provider-reported cost coverage is
267/267 for C1-C3 and 0/267 for C4. C4 therefore used 3.9 times C1's median
tokens, 1.5 times its median latency, and 2.3 times its median tool calls. Most
of the difference was input-token volume: median input/output tokens were
145.8k/2.0k for C1 and 580.0k/3.0k for C4. This larger workload did not produce
an accuracy improvement. It is a product-level efficiency result, but scaffold,
agent, and execution-path differences prevent attributing all of the overhead
to semantic enforcement.

Errors were also more expensive than answers. Median observed total tokens for
answered versus errored attempts were 134k versus 335k in C1, 249k versus 367k
in C2, 195k versus 403k in C3, and 574k versus 815k in C4. C4 error latency was
87.5 seconds versus 50.5 seconds for answered attempts; its error-token median
uses the 36 of 38 errors with token telemetry. Model version, retry count, and
validation-attempt count are unavailable for all 267 C4 attempts. Model
identity is mostly but not entirely stable: 264 of the 267 sealed C4 attempts
resolve to `claude-opus-5` on `bedrock`, one to a `claude-opus-5` plus
`claude-sonnet-5` composite, and two to `managed-unobservable`. All 267
attempts in each of C1, C2, and C3 resolve to a single identity, so the mix is
a governed-path property rather than something the harness does to every arm.
That mix is too small to move the accuracy result, and it is recorded because
attributing any governed-versus-direct difference to model capability assumes a
fixed model the governed path does not guarantee (PF-015). The product
opportunity is therefore not only reducing failures, but detecting terminal
contract and unsupported-result failures earlier in an already costly execution
path.

Model parity between the arms is claimed only at the level of the requested
model name. The direct arms reach `claude-opus-5` through the Claude Code
adapter on an OAuth provider surface; C4 reaches it through Omni's managed
selection on Bedrock. Neither path reports a model version, so two runs cannot
be shown to have used the same weights, and the `C4-C3` contrast stays
scaffold-conditional rather than a model-controlled comparison.

The deterministic aggregate is
[`experiments/analysis/sealed-telemetry-summary-v2.json`](experiments/analysis/sealed-telemetry-summary-v2.json),
with file SHA-256
`d87e6cd3d05b9eea7c372eca51804a890d4e62925c3cd3f205a90a4fcb7e5a90`. It
publishes the identity counts above per condition; v1 is the same summary
without the model-identity whitelist and is retained as the prior record.

### What the governed path costs

Omni bills AI work in credits, one credit to the dollar, and exposes them at
`POST /api/v1/ai/credit-usage/users`. That endpoint reports one cumulative
number per user per billing period. It carries no per-job attribution, which is
why every C4 attempt records `cost_usd` as unavailable rather than a figure.

The benchmark identity used 635.30 credits in August 2026, the period covering
every governed run reported here. Attempt records account for 703 Omni-routed
attempts; the account shows 929 AI conversations in the same period, so 226
belong to deployment validation, probes, dry runs, and traffic unrelated to the
benchmark. Charging the whole period to the recorded attempts gives an upper
bound of $0.90 per governed attempt. Scaling by conversation share gives $0.68.
Both are derived from a counter with no per-job resolution, so they bound the
figure rather than measure it. The reading is preserved before the period
rollover in
[`experiments/analysis/omni-credit-usage-2026-08.json`](experiments/analysis/omni-credit-usage-2026-08.json),
with the attribution in
[`experiments/analysis/omni-credit-spend-breakdown-2026-08.json`](experiments/analysis/omni-credit-spend-breakdown-2026-08.json).

That bound inverts the efficiency table's reading. C4 used 3.9 times C1's
median tokens and cost roughly half as much per attempt, because the arms bill
on different surfaces: Omni reaches `claude-opus-5` through Bedrock with prompt
caching, at a blended $1.39 per million input tokens across 456.5M input tokens,
while the direct arms bill through the Claude Code OAuth surface. Token volume
and dollar cost are not interchangeable across these conditions.

| Condition | Official Soft EX | Cost per attempt | Cost per correct answer |
| --- | ---: | ---: | ---: |
| C1: raw schema | 10.1% | $1.43 measured | $14.16 |
| **C2: raw schema + searchable HKB** | **22.1%** | **$1.90 measured** | **$8.60** |
| C3: exported semantic model | 8.6% | $1.84 measured | $21.40 |
| C4: governed Omni | 8.6% | $0.68-$0.90 derived | $7.95-$10.51 |

Accuracy alone ranks C4 last with C3. Cost per correct answer does not: the
governed path lands with C2 and ahead of both direct-SQL arms that carry a
semantic model. That is a weaker claim than it looks, because the C4 dollar
figure is a bound rather than a measurement and the pricing surfaces differ, but
it is the direction the evidence points, and an accuracy-only reading misses it.

#### Why the governed path is expensive in tokens

Median output is under 3,000 tokens against median input of 580,000, a ratio
near 200 to 1. Credits track input almost exactly. That input is not the
question. It is the agent re-reading context across tool calls, and which tool
it reaches for is the whole story.

| Tool calls per attempt | C4 | C5 |
| --- | ---: | ---: |
| `search_information_schema` | 2.78 | 0.02 |
| `generate_query` | 2.94 | 1.65 |
| `search_model` | 2.22 | 1.85 |
| Database queries executed | 2.94 | 1.65 |

C4's compiled model was too thin to answer from, so the agent fell back to
scanning the raw information schema nearly three times per question and
regenerated its query nearly three times. C5 publishes every table, every
foreign key that passes the cardinality rule, and the complete knowledge port
into `ai_context`. The fallback drops by two orders of magnitude, and with it
32% of input tokens, 36% of latency, 57% of tool calls, and 44% of executed
database queries, while accuracy doubles on the identical frame.

| Matched dev-A frame | C4 | C5 |
| --- | ---: | ---: |
| Official Soft EX | 6.6% | 13.2% |
| Median input tokens | 580,012 | 395,240 |
| Median latency, s | 50.7 | 32.5 |
| Cost per correct answer | $10.36-$13.69 | $3.52-$4.66 |

A complete semantic model is not only more accurate here. It is cheaper per
question and cheaper again per correct answer, because it stops the agent
falling back to the raw schema. The sparse model paid twice, once in tokens
spent rediscovering structure the model should have carried, and once in the
answers it still got wrong. Per-attempt cost stays derived rather than measured
until the credit-delta instrumentation in `omni-benchmark-tx0` lands. The full
audit is
[`experiments/analysis/omni-cost-trace-audit-2026-08.json`](experiments/analysis/omni-cost-trace-audit-2026-08.json).

### Exploratory contrasts

| Scorer | Contrast | Difference | 95% interval | Gains | Losses |
| --- | --- | ---: | ---: | ---: | ---: |
| Official-compatible Soft EX | C2−C1 | 12.0% | 5.6%–18.7% | 37 | 5 |
| Official-compatible Soft EX | C3−C2 | -13.5% | -20.6%–-7.1% | 4 | 40 |
| Official-compatible Soft EX | C4−C1 † | -1.5% | -7.1%–4.1% | 10 | 14 |
| Official-compatible Soft EX | C4−C3 | 0.0% | -4.9%–4.9% | 10 | 10 |
| Corrected multiset sensitivity | C2−C1 | 9.4% | 3.4%–15.7% | 30 | 5 |
| Corrected multiset sensitivity | C3−C2 | -10.9% | -17.6%–-4.9% | 4 | 33 |
| Corrected multiset sensitivity | C4−C1 | -0.4% | -6.4%–5.6% | 13 | 14 |
| Corrected multiset sensitivity | C4−C3 | 1.1% | -4.1%–6.7% | 13 | 10 |

Intervals are deterministic 95% held-out-item-clustered percentile bootstrap
intervals with 10,000 replicates. Both frozen scorers are reported without
post-result selection. The strongest held-out contrast is C2−C1: searchable HKB
context improves the direct comparator. C3 loses that advantage after the HKB
is converted into the bounded structured model, and C4 does not recover it.

### Preregistered significance tests

The preregistered inference is the exact two-sided binomial McNemar test on
repetition one only, where the 89 questions are independent. It is reported as a
sensitivity check on the interval estimates above, not as a second headline.
Naïve McNemar must not be applied to the 267 correlated attempts. C4−C1 is the
primary contrast and is reported unadjusted; Holm correction at familywise alpha
0.05 covers the three-rung exploratory family {C2−C1, C3−C2, C4−C3}.

| Scorer | Contrast | Gains | Losses | Exact two-sided p | Holm-adjusted p |
| --- | --- | ---: | ---: | ---: | ---: |
| Official-compatible Soft EX | C4−C1 † (primary, unadjusted) | 3 | 6 | 0.508 | — |
| Official-compatible Soft EX | C2−C1 | 11 | 1 | 0.0063 | 0.0127 |
| Official-compatible Soft EX | C3−C2 | 0 | 14 | 0.00012 | 0.00037 |
| Official-compatible Soft EX | C4−C3 | 3 | 2 | 1.000 | 1.000 |
| Corrected multiset sensitivity | C4−C1 (primary, unadjusted) | 4 | 6 | 0.754 | — |
| Corrected multiset sensitivity | C2−C1 | 8 | 1 | 0.0391 | 0.0781 |
| Corrected multiset sensitivity | C3−C2 | 0 | 11 | 0.00098 | 0.0029 |
| Corrected multiset sensitivity | C4−C3 | 4 | 2 | 0.688 | 0.688 |

Gains and losses here are discordant pairs on the 89 repetition-one questions, so
they are smaller than the three-repetition counts in the interval table above and
are not comparable to them.

Two conclusions survive Holm correction under both scorers, and they point in
opposite directions: adding searchable business knowledge to the direct
comparator helps, and converting that knowledge into the bounded structured model
loses the gain. C3−C2 is the sharpest result in the study, with zero discordant
gains against 14 losses under the official scorer. The C2−C1 gain clears the
threshold under the official scorer and does not under the sensitivity scorer
(Holm-adjusted 0.078), which is a real disagreement between the two frozen
scorers and is reported as such rather than resolved after the fact. Neither
governed contrast, C4−C1 or C4−C3, is distinguishable from no difference under
either scorer; with 5 to 10 discordant pairs these tests have very little power,
so this is an absence of evidence and not evidence of equivalence.

### What this frame could and could not have detected

The exact McNemar test conditions on the discordant pairs, so its power is set by
how many there are and not by the 89 questions. Below six discordant pairs the
test has no rejection region at all: no split of five can reach p ≤ 0.05, because
the most extreme possible outcome gives 2 × (1/32) = 0.0625. A contrast at five
pairs is not underpowered, it is unfalsifiable, and the official C4−C3 contrast
is exactly that case.

| Scorer | Contrast | Discordant pairs | Smallest detectable favor rate at 80% power |
| --- | --- | ---: | ---: |
| Official-compatible Soft EX | C2−C1 | 12 | 0.870 |
| Official-compatible Soft EX | C3−C2 | 14 | 0.889 |
| Official-compatible Soft EX | C4−C1 † | 9 | 0.908 |
| Official-compatible Soft EX | C4−C3 | 5 | no rejection region exists |
| Corrected multiset sensitivity | C2−C1 | 9 | 0.908 |
| Corrected multiset sensitivity | C3−C2 | 11 | 0.925 |
| Corrected multiset sensitivity | C4−C1 | 10 | 0.917 |
| Corrected multiset sensitivity | C4−C3 | 6 | 0.964 |

The favor rate is the probability that a discordant pair falls to the better arm.
A rate of 0.870 means the test had an 80% chance of detecting an effect only if
roughly seven of every eight questions where the two arms disagreed went the same
way. Effects smaller than that were invisible to this frame. The rate does not
fall monotonically as pairs are added, because the rejection region is discrete:
at 12 pairs the test rejects on 2 or fewer out of 12, and at 14 pairs still on 2
or fewer out of 14, which is a stricter requirement.

The practical consequence is that the two null governed contrasts carry almost no
information. Reading C4−C1 or C4−C3 as evidence that the conditions perform
alike is not supported. A frame that could resolve a five-point difference in the
governed arm needs either many more questions or far fewer infrastructure
failures eating the answered denominator.

### Infrastructure-bounded reanalysis

Every attempt that never produced an answer is scored as not correct. That is the
right default for a benchmark, but it mixes three different things: the system
answered and got it wrong, our harness got in the way, or the model provider did.
The counts are large enough to matter, so this section bounds how much of the
result they could explain. It is a post-hoc reanalysis of the frozen artifacts,
reported beside the preregistered numbers and never in place of them.

Terminal failure classes across the 1,068 sealed attempts:

| Terminal class | C1 | C2 | C3 | C4 | Reading |
| --- | ---: | ---: | ---: | ---: | --- |
| `none` (answered) | 179 | 198 | 169 | 229 | scored normally |
| `model_budget_error` | 33 | 31 | 22 | 0 | our own per-turn spend cap |
| `no_answer_insufficient_context` | 38 | 16 | 55 | 0 | the system's own result |
| `model_rate_limit_error` | 13 | 15 | 16 | 0 | provider throttling |
| `database_statement_error` | 4 | 3 | 2 | 0 | the system's own result |
| `unsupported_semantic_result_type` | 0 | 0 | 0 | 32 | closed result-type set in our adapter |
| `response_contract_error` | 0 | 0 | 0 | 4 | contract mismatch at the boundary |
| `omni_job_terminal_failure` | 0 | 0 | 0 | 2 | the governed system's own failure |
| `model_identity_mismatch` | 0 | 2 | 1 | 0 | provider served a different model |
| `sql_not_admitted` | 0 | 1 | 1 | 0 | our admission check rejected the SQL |
| `turn_limit_exhausted` | 0 | 1 | 1 | 0 | the system's own result |

`model_budget_error` is the harness's `--max-budget-usd 1.0` per-turn cap, not a
provider limit, so it counts as apparatus. Two classes are genuinely arguable:
`unsupported_semantic_result_type` fires on a closed seven-member set in our
result adapter, but a governed system that returns a type the adapter never
supported is also revealing something about its contract. Rather than pick, every
bound below is computed under both readings. The primary reading treats the
closed type set and the SQL admission check as apparatus; the alternate treats
them as the system's own result. `omni_job_terminal_failure` and
`no_answer_insufficient_context` are the system's own result under both.

Three imputation rules, applied only to attempts the reading assigns to apparatus
or provider. Failures that belong to the system stay counted as wrong under every
rule, because they are results about the system.

- **As scored** is the frozen result: every non-answer is wrong.
- **Neutral** credits each reassignable attempt at that arm's accuracy among its
  answered attempts, which is what you would expect had it run.
- **Charitable** credits every reassignable attempt as correct. It is a ceiling,
  not a plausible value.

| Scorer | Condition | Answered | Reassignable (primary) | As scored | Neutral | Charitable |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Official-compatible Soft EX | C1 | 179 | 46 | 10.1% | 12.7% | 27.3% |
| Official-compatible Soft EX | C2 | 198 | 49 | 22.1% | 27.6% | 40.4% |
| Official-compatible Soft EX | C3 | 169 | 40 | 8.6% | 10.6% | 23.6% |
| Official-compatible Soft EX | C4 | 229 | 32 | 8.6% | 9.8% | 20.6% |
| Corrected multiset sensitivity | C1 | 179 | 46 | 10.1% | 12.7% | 27.3% |
| Corrected multiset sensitivity | C2 | 198 | 49 | 19.5% | 24.3% | 37.8% |
| Corrected multiset sensitivity | C3 | 169 | 40 | 8.6% | 10.7% | 23.6% |
| Corrected multiset sensitivity | C4 | 229 | 32 | 9.7% | 11.1% | 21.7% |

The contrasts are what the reanalysis was built to settle, and they hold:

| Contrast | Official as scored | Official neutral | Official charitable | Sensitivity as scored | Sensitivity neutral | Sensitivity charitable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C2−C1 | 12.0% | 14.9% | 13.1% | 9.4% | 11.6% | 10.5% |
| C3−C2 | -13.5% | -16.9% | -16.9% | -10.9% | -13.6% | -14.2% |
| C4−C1 † | -1.5% | -2.9% | -6.7% | -0.4% | -1.6% | -5.6% |
| C4−C3 | 0.0% | -0.8% | -3.0% | 1.1% | 0.4% | -1.9% |

Three conclusions follow, and all four combinations of rule and reading were
checked before stating them.

**The governed null is robust and the frozen numbers are conservative in C4's
favor.** C4−C1 is negative under every rule, every reading, and both scorers, and
crediting infrastructure failures moves C4 further behind rather than ahead. C4
had the highest answered rate of any condition, 229 of 267, so it has the least
to gain from imputation. Its as-scored result is not an artifact of infrastructure
loss.

**C2−C1 survives on the point estimate but not on Holm significance under the
charitable rule**, where its adjusted p rises to 0.083 under the official scorer
and 0.287 under the sensitivity scorer. The direction never reverses. Read it as
a real but not comfortably resolved gain.

**C3−C2 survives every rule and both scorers**, with Holm-adjusted p of 0.0026
and 0.0216 under the charitable rule. It remains the sharpest finding in the
study: converting searchable business knowledge into the bounded structured model
loses the gain that knowledge provided.

The clustering assumption was also checked. The preregistered interval clusters on
questions, but the 89 questions sit on only 16 databases, and questions sharing a
database share a schema, a loader, and a failure surface. Resampling databases
instead of questions gives:

| Scorer | Condition | Question-clustered | Database-clustered |
| --- | --- | ---: | ---: |
| Official-compatible Soft EX | C1 | 10.1% [4.9%, 16.1%] | 10.1% [3.0%, 18.5%] |
| Official-compatible Soft EX | C2 | 22.1% [14.6%, 30.0%] | 22.1% [14.8%, 29.5%] |
| Official-compatible Soft EX | C3 | 8.6% [3.8%, 14.2%] | 8.6% [2.2%, 16.3%] |
| Official-compatible Soft EX | C4 | 8.6% [3.8%, 14.6%] | 8.6% [3.8%, 13.9%] |
| Corrected multiset sensitivity | C1 | 10.1% [4.9%, 16.1%] | 10.1% [3.0%, 18.5%] |
| Corrected multiset sensitivity | C2 | 19.5% [12.4%, 27.3%] | 19.5% [12.2%, 26.7%] |
| Corrected multiset sensitivity | C3 | 8.6% [3.8%, 14.2%] | 8.6% [2.2%, 16.3%] |
| Corrected multiset sensitivity | C4 | 9.7% [4.5%, 15.7%] | 9.7% [4.9%, 14.9%] |

Switching cluster level does not simply widen the intervals. C1 and C3 widen,
which is what 16 clusters instead of 89 would predict. C2 and C4 narrow slightly.
Both arms hold their accuracy fairly evenly across databases, so grouping their
questions by database removes more within-cluster variation than it loses in
cluster count. Either way no conclusion changes sign or significance, and the
preregistered question-clustered interval stands. The database-clustered column
is a post-hoc robustness probe; 16 clusters is few enough that it should not
replace the preregistered one.

The question-clustered column is recomputed from the committed matrix rather than
copied. It reproduces the frozen aggregate's published C4 interval of 8.6%
[3.75%, 14.61%] exactly, which is what licenses reading the other rows, since the
frozen aggregate publishes this interval only for the C4 primary endpoints.

The reanalysis is deterministic and reproduces from committed artifacts:

```bash
uv run python experiments/analysis/sealed_bounded_reanalysis.py \
  --matrix experiments/analysis/sealed-correctness-matrix-v1.json \
  --output experiments/analysis/sealed-bounded-reanalysis-v1.json
```

It reads
[`sealed-correctness-matrix-v1.json`](experiments/analysis/sealed-correctness-matrix-v1.json)
(SHA-256 `cc173544c8ea041d1945ea8a5c27fac06bc5c11061e9afb7efaa8278a658c269`),
the identity-free 89 × 4 × 3 outcome matrix, and writes
[`sealed-bounded-reanalysis-v1.json`](experiments/analysis/sealed-bounded-reanalysis-v1.json)
(SHA-256 `def321a2f46f7f43b356a2cd24edfc4fe3835fff90aad496ed9d09d5cb6e4d5c`). The
matrix carries no question text, no SQL, no gold, and no identifier; it commits
the per-question outcomes so an outside reader can recompute every headline
number in this section without the sealed run tree.

### Optimization-scope limitation

The untuned arm was scored before E02 dev-A execution completed, contrary to the
ordering in the later lean optimization extension. E02 had already been
selected and preregistered as a relationship-path mechanism contrast, and its
general compiler change predates these results. Its fixed dev-A generation is
complete and frozen. Fourteen unsupported-result captures retained a semantic
query, but five genuine transport failures did not; the hash-bound recovery
path therefore could not produce a complete 136-question score. The fixed
coverage rule resolves E02 as INCONCLUSIVE, and no correctness estimate is
claimed.
The sealed aggregates may not drive a new intervention edit, dev-B checkpoint,
promotion decision, or optimized held-out arm. A correction required
by public validator evidence subsequently generalized publication of
already-normalized relationship endpoints; it used no outcome evidence and
changed no experiment choice. The MVP therefore reports a valid frozen C1−C4
held-out comparison and a separate pre-specified dev-A optimization experiment;
it does not claim held-out improvement from tuning.

## 7. Product recommendations

The development evidence supports five immediate recommendations:

1. **Make grain contracts explicit and inspectable.** Model import and AI-facing
   authoring should represent metric grain, entity identity, relationship
   cardinality, and aggregation semantics directly. A dry run should show which
   definitions cannot be governed and why.
2. **Treat retrieval payloads as part of the agent contract.** Schema and
   semantic search tools should be query-directed, bounded, and observable.
   Telemetry should identify context volume per tool call and use typed public
   provenance IDs so safety filters do not reject legitimate semantic metadata.
3. **Separate why an agent did not answer.** A content-based refusal, an explicit
   statement that available schema is insufficient, model-budget exhaustion,
   and infrastructure failure imply different product actions. Omni and
   comparator telemetry should retain those raw states even when a report also
   groups them into broader reliability categories.
4. **Expose relationship coverage before deployment.** Public schema contained
   1,049 conservative PK- or unique-backed relationships, while the bounded
   modeled candidate could expose 91 across 16 databases. A model author needs a
   dry-run view of accepted, deferred, and unreachable relationships before
   deciding whether the semantic model has enough structure for governed
   queries.
5. **Make semantic result contracts total and typed.** Production planning and
   execution should expose a stable representation for unknown, Boolean,
   temporal, and null values. An unsupported planner type should be a visible
   product outcome, not an adapter exception that obscures whether the governed
   query itself succeeded. The contract that needs writing down is the one over
   rewritten SQL: when the agent authors the query, neither side currently
   specifies what the planner guarantees about the type of an output column the
   semantic model never declared.

The direct and C4 development baselines associate these mechanisms with
failures. On the matched 89-question, 16-database held-out frame, the comparison
supports the value of searchable raw HKB context, but it does not show an
accuracy gain for the frozen governed system.
The detailed product handoff is in
[`docs/product-findings.md`](docs/product-findings.md); supporting mechanism
evidence is in [`docs/failure-taxonomy.md`](docs/failure-taxonomy.md), the
[`C4 query-path disclosure`](docs/c4-query-path-disclosure.md), and the
[`E02 join-path assessment`](docs/e02-join-path-assessment.md).

## 8. What this suggests for an ongoing evaluation program

The most consequential conclusion of this study is not the score. It is that
**"agent accuracy with a semantic layer" is not measurable as a single number.**
C4 scored 8.6%, and that figure turned out to be nearly uninformative on its
own, because it silently confounds three properties that move independently:

1. **Semantic-model quality.** How much available business knowledge became
   governed, executable structure. Measured here: 17.7% of 1,090 definitions.
2. **Whether the runtime exercised that model.** Whether the governed path
   composed the query or the agent authored SQL over model-resolved references.
   Measured here: the latter for metric logic, on 661 of 661 parseable attempts
   across six governed arms, with the model supplying field resolution throughout
   and join scope on most attempts.
3. **End-to-end answer correctness.** The number that gets quoted.

A system can fail on any one of these while looking healthy on the others, and
one accuracy figure cannot say which. Every substantive finding in this report
came from separating them, using offline forensics on raw job records rather
than any product surface. Six durable consequences follow, none of which depends
on this particular benchmark:

- **A benchmark portfolio rather than a benchmark.** SQL accuracy is one axis.
  Semantic-model construction quality, governed-query behavior, robustness under
  schema and knowledge drift, and customer-representative workloads are separate
  axes that will not move together.
- **Failure attribution as infrastructure.** Modeling, retrieval, planning,
  semantic compilation, rewrite, transport, execution, and scorer failures should
  be distinguishable from telemetry by construction. Here they were not: 34 of
  136 C4 attempts failed before producing a scoreable answer, and ownership among
  the authored model, agent planning, and the result contract is still
  unresolved.
- **Continuous product evaluation.** Regression suites bound separately to the
  semantic layer, the agent, and the harness, so a change in one is not read as a
  change in another.
- **Semantic-model diagnostics as a product surface.** Grain, cardinality,
  aggregation, identity, and relationship coverage should be measurable
  properties a model author sees before deploying, not quantities a researcher
  reconstructs afterward.
- **A closed loop.** Evaluation finding, product hypothesis, targeted experiment,
  shipped change, regression measurement. E02 and C5 are the first two turns of
  that loop, executed by hand.
- **An explicit rule for the boundary.** When is retrievable business knowledge
  sufficient, and when must knowledge become executable governance? C2 against
  C3 is direct evidence that the answer is not always governance, and the product
  has no way to express the distinction today.

## 9. Limitations

- D-043 measures transformation coverage, not question correctness. A deferred
  definition may never be needed, and a compiled definition may still be
  retrieved or interpreted incorrectly.
- D-045 is a single-question integration sequence. Its token and cost changes
  should not be treated as population estimates.
- The reported accuracy covers 140 of 154 dev-A questions at generation time and
  122 official-scoreable questions per condition after reference-SQL
  conformance. These adaptively reusable development results are neither a full
  dev-A estimate nor held-out evidence.
- Eighteen dev-A questions are unscorable in the official Large-v1 environment,
  not system failures. The evaluation schedules and reports them but excludes
  them from the fixed 136-question C4 promotion denominator. Loading the omitted
  archive files would break comparability with the official environment.
- The executed held-out frame contains 89 of the original 101 sealed questions.
  It excludes the 12 questions on the same two loader-blocked databases before
  any sealed generation or outcome access. The held-out result therefore
  estimates performance on the 16 deployable databases, not all 18 benchmark
  databases.
- The public direct baseline excludes archeology and cybermarket and therefore
  estimates C1−C3 behavior on 16 databases, not the full 18-database population.
  Any comparison to a broader C4 arm must use matched coverage or disclose the
  mismatch.
- The four-table schema window is a comparator scaffold choice. D-054 fixes a
  20-question sensitivity arm, but the MVP deferral leaves that arm unexecuted.
- C4 is a composite production system. Unless its underlying model and resource
  settings can be matched exactly, C4−C3 is a system-level comparison rather
  than an isolated estimate of semantic enforcement.
- The governed condition did not exercise semantic query composition, so this
  study does not isolate it. Every governed query took Omni's raw-SQL rewrite
  path, and the deployed model declared no join path and no measure for a planner
  to compile. C4−C3 differs on the agent, on field resolution at rewrite time, on
  the accessible surface, and on the execution contract, and not on who composes
  the query or on join and aggregation semantics. This limitation is independent
  of the model-parity limitation above and is not removed by achieving parity.
- C4's structural aggregates are computed from the SQL text carried on each
  governed semantic query, because `generated_sql` is `null` for all 136
  attempts. They describe agent-written queries in every condition and support no
  claim about how the governed path composed its queries.
- C4 development accuracy is 9/136 on its full answerable frame, while the
  direct C1-C3 percentages use a 122-question intersection. Their raw difference
  is not a matched or paired development contrast.
- Execution equivalence remains the benchmark authority. AI Hub diagnostics and
  judge outcomes can explain behavior but do not replace result-set scoring.
- E02 passed public deployment validation and exact readback on all 16 selected
  targets, completed its sole 136-attempt dev-A generation, and froze the exact
  output. Five genuine transport failures captured no semantic query, so the
  preregistered complete-136 scoring gate cannot be met without another model
  attempt and E02 is INCONCLUSIVE. Its declared
  FK-backed relationships are the ingredient whose absence forced the agent to
  author its own joins, which makes it a direct test of that mechanism; it is not yet
  evidence that the mechanism improves correctness, and its topics
  declare no measures, so aggregation may still be rewritten rather than
  compiled. The mechanical baseline received no question-level supervision.
  Because held-out aggregates are now visible, E02 cannot be rerun or promoted
  into a sealed successor. Dev-B remains unconsumed.
- The scoring-order deviation prevents a held-out claim about optimization. It
  does not alter the frozen untuned comparison because every generation was
  complete before release and both scorers were published together.
- C5 is a development-only mechanism analysis registered after the sealed
  aggregates were visible. It cannot alter the frozen held-out numbers, cannot
  be promoted into a sealed successor, and its dev-A contrasts are exploratory.
  A favorable C5 result would refine the explanation of C4's behavior; it would
  not establish held-out improvement from the governed path.

## 10. Reproducibility

The repository preserves the public manifest and deterministic split, public
HKB/schema inputs and hashes, transformation artifacts, condition disclosure,
telemetry contracts, experiment history, and two frozen scorers. Private gold
and hidden annotations remain outside the repository. See
[README.md](README.md) for reproduction commands and
[docs/evidence-index.md](docs/evidence-index.md) for the stable evidence map and
[manuscript/main.tex](manuscript/main.tex) for the portable supporting protocol
source; [`manuscript/build.sh`](manuscript/build.sh) produces its pinned PDF.
The untuned baseline system is frozen at successor commit
`8b0c7393d564d9ecc2c2f84ba7446d610c1a0a6d`; its direct-child control commit is
`94cc0d9483c944d7dc13ed651c8fc2ef077f33ab`, and the Freeze-B manifest SHA-256
is `e1c9f1967422822c848c18a17ba759d4e4fbc7f21aa0fe3ae1045b9236ae4730`.
Scoring used correction-forward system
`0a5aee423b4a0d5bb396b3d9764f8e9e24f31254`, control
`fe4660df8dacdca07da310ddfda4158b82895ba9`, and Freeze-B v10 SHA-256
`ff10083bf70d82bd483d12e98751d9bf7f5d4236c42fac3ba921405d87953a05`
while preserving the generation binding above. The correctness-free scoring
receipt SHA-256 is
`534e28b954d4d13dfdd9100fc6a184fba3eb3720d8cd7cf7d43c92713cb258f7`.
No optimized held-out candidate is constructed after the sealed result.
The deferred D-054 comparator sensitivity subset, allocation diagnostics,
preserved-artifact hashes, and notional cost/time projection remain supporting
artifacts; observed provider dollars remain telemetry rather than a
run-selection rule.

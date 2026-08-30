# Omni on LiveSQLBench Large-v1: Accuracy, Reliability, and Product Findings

## Results report

> **Status — 2026-08-30:** The immutable C1-C4 untuned baseline is complete and
> scored on the matched 89-question held-out frame under both frozen scorers.
> Only identity-free aggregates have left custody; no per-question correctness,
> SQL, row, or test annotation was opened. E01 is an audited baseline no-op, and
> E02 remains the pre-specified dev-A mechanism contrast selected before sealed
> scoring. Because sealed aggregates became visible before E02 completed, it
> cannot now be promoted into a held-out optimized arm; no intervention edit or
> dev-B checkpoint may use these results. Before any sealed outcome existed, the
> original 101-question frame was narrowed to the matched 89 questions
> on the 16 databases with verified C4 deployments. The fixed E02 dev-A
> schedule still lists all 154 questions; 18 benchmark-invalid questions are
> preregistered as
> unscorable, leaving 136 answerable questions for C4 evaluation. All 16
> answerable baseline and E02 database bundles have current immutable
> validation and exact-readback evidence sets. C4 completed all 136 executable
> attempts: 9 were correct, 93 wrong, and 34 refused or ended in a
> system-contract error under the official scorer.

## Executive summary

This study evaluates Omni on LiveSQLBench Large-v1 and separates three questions:
whether business knowledge helps an analytical agent, what is lost when that
knowledge becomes an executable semantic model, and what Omni's governed runtime
actually does with that model. The benchmark contributes 332 eligible analytical
tasks: 231 development questions and an original sealed split of 101 questions.
The development partition is further divided into 154 development questions and
77 metered validation questions. The protocol permits supervised reuse. The
frozen mechanical candidate received no question-level supervision and consumed
no metered checkpoint. E02 is the final experiment: a pre-specified dev-A
mechanism contrast that cannot become a held-out optimized arm after the
scoring-order deviation. Four baseline systems separate access to raw schema,
business knowledge, structured semantic knowledge, and governed execution.

**Headline held-out result, on the pre-outcome matched frame.** Official mean
accuracy was 10.1% for C1, 22.1% for C2, 8.6% for C3, and 8.6% for C4; corrected
sensitivity was 10.1%, 19.5%, 8.6%, and 9.7%. This comparison covers 89 of the
original 101 held-out questions, on the 16 databases with verified C4
deployments. The frame was narrowed before any sealed generation, label release,
or outcome access because the official loader left required tables unavailable
in the other two databases. All four conditions and all three repetitions use
the same 89 questions; the result estimates performance on those 16 deployable
databases, not the full 18-database benchmark.

The product interpretation is not that business semantics failed to matter. On
this benchmark, C2 shows that searchable business knowledge mattered: it improved
the direct comparator by 12.0 percentage points under the official scorer. The
loss occurred in translation and execution. Only 17.7% of the 1,090 public HKB
definitions compiled into executable objects, while 46.9% were deferred across
an unresolved grain. The deployed C4 model consequently declared no joins or
measures, and Omni's production agent fell back to agent-written SQL through the
rewrite path. The product opportunity is to preserve useful business semantics
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
   mismatch. Causal ownership remains unresolved between the authored model,
   agent behavior, and Omni's planning/result contract. Eleven
   additional capture gaps were recoverable by replaying only an
   already-generated semantic query; question-level model reasoning was never
   rerun.

6. The governed condition did not compile queries from the semantic model. Omni's
   production agent took the product's raw-SQL rewrite path on every attempt:
   all 135 governed semantic queries carry `rewriteSql: true` with agent-authored
   SQL, and none declares a join path. The harness cannot select that path, and
   for cross-table questions no other path existed, because the conservative
   compiler deferred 46.9% of definitions as cross-grain and the deployed topics
   therefore publish empty joins and no measures. The semantic layer still did
   work as a field vocabulary that Omni resolved at rewrite time, on 109 of 135
   attempts. It did not compose the query. The study can no longer claim that
   C4 minus C3 isolates semantic-layer query composition.

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
| C4 | Omni semantic model | Omni agent emits SQL through the product's rewrite path over model-resolved field references |

**What "production-governed Omni" turned out to mean.** C4 was preregistered as
the governed condition against three direct-SQL comparators. Measured on the
frozen development baseline, the governed path is also an agent authoring SQL.
All 135 semantic queries set `rewriteSql: true` with hand-authored SQL, and none
declares a join path; the deployed model publishes no joins and no measures, so
no compiled cross-table or aggregate path existed to take. The choice of path was
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

C4's structural figures are computed from the semantic query's `userEditedSQL`
because `generated_sql` is `null` for every C4 attempt. That SQL is
agent-authored in Omni's dialect, so these figures describe agent-written queries
in both C4 and C1-C3 rather than a compiled path against authored ones. The
relation count also includes CTE references, aliased self-joins, and subquery
sources, which makes multi-relation prevalence an upper bound on genuine
cross-table access.

The same identity-free analysis covered all 136 governed C4 outcomes. All 9
correct queries parsed, as did 92 of 93 wrong answers and 32 of 34 explicit
system errors. Correct queries averaged 1.67 relations, versus 2.62 for wrong
answers and 2.88 for errors. Multi-relation queries appeared in 2/9 correct,
50/92 wrong, and 20/32 error cases; joins appeared in 2/9, 41/92, and 18/32.
These associations do not establish that relationships caused the failures.

The query-path measurement changes the standing of the intervention they
selected. E02 declares FK-backed relationships, which is the ingredient whose
absence left the rewrite path as the only route to cross-table access. E02 is
therefore a direct test of that mechanism rather than a candidate chosen from a
structural correlation. Whether it is sufficient to move governed queries off the
rewrite path is still being measured: its topics declare no measures, so the
agent may continue to rewrite in order to aggregate.

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
| E02: FK-backed relationships | 1,049 public FKs pass the conservative contract; the bounded artifact emits 91 relationships across 16 databases and 67 source topics, with zero metric-disposition changes; deployment v5 verified all 16 targets with exact readback | Pre-specified dev-A mechanism contrast; no held-out promotion permitted after sealed scoring | Run its fixed eligible dev-A evaluation unchanged |
| E03: bounded descriptions | Prespecified only | Not run | Out of MVP scope after the scoring-order deviation |
| E04: broad HKB context | Prespecified negative control only | Not run | Out of MVP scope after the scoring-order deviation |

A fifth family, E05, was registered later against the 31 `UNKNOWN`-type contract
failures: declare explicit output types on compiled semantic fields. Its
preregistered precondition required at least 16 of those 31 attempts to select a
compiled derived field. Measured offline on the immutable generation records, the
ceiling is 6 of 31, and 24 of 31 select no compiled bundle field of any kind, so
no declaration on a compiled field can reach them. E05 is recorded INCONCLUSIVE
by its own stopping rule and consumed no live attempt.

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
Public deployment v5 verified and exactly read back all 16 selected targets with
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

## 6. Held-out results

The frozen untuned comparison covers 89 held-out questions and 1,068 scheduled
attempts: four conditions, three repetitions, identical membership. The scorer
published both preregistered policies in one atomic run. This section uses only
the identity-free aggregates; no question identity, SQL, row, annotation, or
per-question correctness left custody.

### Primary endpoints

| Scorer | Endpoint | Estimate | 95% interval |
| --- | --- | ---: | ---: |
| Official-compatible Soft EX | C4 mean one-shot execution accuracy | 8.6% | 3.7%–14.6% |
| Official-compatible Soft EX | C4 repetition-one execution accuracy | 7.9% | 3.4%–13.5% |
| Official-compatible Soft EX | C4−C1 paired accuracy difference | -1.5% | -7.1%–4.1% |
| Corrected multiset sensitivity | C4 mean one-shot execution accuracy | 9.7% | 4.5%–15.7% |
| Corrected multiset sensitivity | C4 repetition-one execution accuracy | 9.0% | 3.4%–15.7% |
| Corrected multiset sensitivity | C4−C1 paired accuracy difference | -0.4% | -6.4%–5.6% |

### Four-condition matrix

| Scorer | Condition | Mean accuracy | Wrong rate | Refused/error | Error rate | Pass³ | Correctness flips |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Official-compatible Soft EX | C1 | 10.1% | 56.2% | 33.7% | 18.7% | 6.7% | 6 |
| Official-compatible Soft EX | C2 | 22.1% | 50.6% | 27.3% | 19.9% | 15.7% | 12 |
| Official-compatible Soft EX | C3 | 8.6% | 53.2% | 38.2% | 16.1% | 4.5% | 6 |
| Official-compatible Soft EX | C4 | 8.6% | 77.2% | 14.2% | 14.2% | 6.7% | 4 |
| Corrected multiset sensitivity | C1 | 10.1% | 56.9% | 33.0% | 18.7% | 6.7% | 6 |
| Corrected multiset sensitivity | C2 | 19.5% | 54.7% | 25.8% | 19.9% | 14.6% | 10 |
| Corrected multiset sensitivity | C3 | 8.6% | 54.7% | 36.7% | 16.1% | 4.5% | 6 |
| Corrected multiset sensitivity | C4 | 9.7% | 76.0% | 14.2% | 14.2% | 7.9% | 4 |

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
validation-attempt count are unavailable for all 267 C4 attempts. The product
opportunity is therefore not only reducing failures, but detecting terminal
contract and unsupported-result failures earlier in an already costly execution
path.
The deterministic aggregate is
[`experiments/analysis/sealed-telemetry-summary-v1.json`](experiments/analysis/sealed-telemetry-summary-v1.json),
with file SHA-256
`7a614d6c861d4d2a982501ea8c89b2817820d965671caf800cc155759be481a8`.

### Exploratory contrasts

| Scorer | Contrast | Difference | 95% interval | Gains | Losses |
| --- | --- | ---: | ---: | ---: | ---: |
| Official-compatible Soft EX | C2−C1 | 12.0% | 5.6%–18.7% | 37 | 5 |
| Official-compatible Soft EX | C3−C2 | -13.5% | -20.6%–-7.1% | 4 | 40 |
| Official-compatible Soft EX | C4−C1 | -1.5% | -7.1%–4.1% | 10 | 14 |
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

### Optimization-scope limitation

The untuned arm was scored before E02 dev-A execution completed, contrary to the
ordering in the later lean optimization extension. E02 had already been
selected and preregistered as a relationship-path mechanism contrast, and its
general compiler change predates these results. It may still be executed on
dev-A, but the sealed aggregates may not drive a new intervention edit, dev-B
checkpoint, promotion decision, or optimized held-out arm. A correction required
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

## 8. Limitations

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
  targets and was selected as the first bounded dev-A candidate, but it has not
  yet been evaluated. Its declared FK-backed relationships are the ingredient whose
  absence forced the governed rewrite path, which makes it a direct test of that
  mechanism; it is not yet evidence that the mechanism moves, and its topics
  declare no measures, so aggregation may still be rewritten rather than
  compiled. The mechanical baseline received no question-level supervision.
  Because held-out aggregates are now visible, E02 may only run unchanged on
  dev-A and cannot be promoted into a sealed successor. Dev-B remains
  unconsumed.
- The scoring-order deviation prevents a held-out claim about optimization. It
  does not alter the frozen untuned comparison because every generation was
  complete before release and both scorers were published together.

## 9. Reproducibility

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

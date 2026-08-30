# Does an Enforced Semantic Layer Improve Analytical Question Answering?

## Results report

> **Status — 2026-08-29:** The immutable C1-C3 public baseline has been scored on
> its exact dev-A intersection. E01 is an audited baseline no-op, and the E02
> relationship artifact is locally authenticated but was neither deployed nor
> evaluated. The optimization phase is closed: no intervention was promoted, no
> dev-B checkpoint will be consumed, and the frozen mechanical baseline is the
> final candidate. The C4 development baseline is complete and scored. Freeze B
> is recorded and validated; the sealed run and its custody scoring are pending.
> Every **Pending** entry below carries no numeric value. The original 101
> held-out questions and their labels remain sealed. Before any sealed outcome
> existed, the final evaluation frame was narrowed to the matched 89 questions
> on the 16 databases with verified C4 deployments. All 154 dev-A questions
> remain scheduled; 18 fixed benchmark-invalid questions are preregistered as
> unscorable, leaving 136 answerable questions for C4 evaluation. All 16
> answerable database bundles have one current immutable validation and
> exact-readback evidence set. C4 completed all 136 executable attempts: 9 were
> correct, 93 wrong, and 34 refused or ended in a system-contract error under
> the official scorer.

## Executive summary

This study asks whether an analytical agent becomes more accurate when business
knowledge is represented and enforced through Omni's semantic layer instead of
being left to direct SQL generation. It starts from 332 analytical tasks in
LiveSQLBench Large-v1: 231 development questions and an original sealed split of
101 questions. The executed held-out comparison uses the matched 89-question
subset described below. The development partition is further divided into 154
development questions and 77 metered validation questions. The protocol
permitted supervised reuse, but the executed final candidate receives no
question-level supervision and consumes no metered checkpoint. Four systems
separate access to raw schema, business knowledge, structured semantic
knowledge, and governed execution.

The primary sealed results remain pending. Development evidence now supports
five findings:

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
   refused/system-error outcomes. These are exploratory development results;
   the sealed comparison has not run.

3. Wrong answers dominate the direct baseline. Across the three conditions, 245
   of 366 scoreable attempts were wrong, 67 refused or errored, and 54 were
   correct. Wrong SQL used more relations on average in every condition, while
   30 of 31 window-query attempts and 25 of 28 distinct-query attempts were
   wrong. Join or aggregate presence alone did not separate correct from wrong
   answers.

4. Bounded schema retrieval made the direct comparator runnable and established
   a hard payload limit. The schema tool now returns at most four tables and 64
   KiB per call, compared with a 51-table response on the original canary. Full
   baseline telemetry averaged $1.48 to $1.84 per attempt across C1-C3. The hard
   payload bound and observed end-to-end cost are separate measurements.

5. The governed semantic path exposed a distinct product-reliability failure
   surface. Thirty-four of 136 scoreable C4 attempts ended in a semantic-layer
   or system-contract failure rather than a scored result mismatch. Eleven
   additional capture gaps were recoverable by replaying only an
   already-generated semantic query; question-level model reasoning was never
   rerun.

The sealed evaluation will test whether the frozen mechanical semantic layer
improves governed execution on the held-out comparison.

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
| C4 | Omni semantic model | Production-governed Omni |

C2−C1 tests the value associated with making business knowledge available.
C3−C2 tests the value associated with structuring that knowledge. C4−C3 is a
system-level, scaffold-conditional comparison unless model and runtime parity
can genuinely isolate enforcement. The direct conditions use one pinned Claude
OAuth scaffold, while C4 preserves Omni's production-managed workflow and may
use a composite model system.

## 2. Experimental design

The pinned public benchmark has 480 instances across 18 PostgreSQL databases.
We excluded 148 `Management` tasks and retained all 332 `Query` tasks. A
deterministic split, based only on public metadata and stratified primarily by
database and `high_level`, assigned 231 questions to development and 101 to the
sealed final evaluation. Every database appears in both partitions.

The 231 development questions are split into dev-A (154) and dev-B (77). The
protocol permits repeated use of dev-A and metered dev-B checkpoints. For the
executed study, no supervised intervention is promoted and dev-B remains
unconsumed by decision. The held-out set is inaccessible to development. All
four frozen conditions will produce three independent, interleaved attempts for
each of the 89 selected questions before any test output is scored.

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

Later trace diagnosis uses the earliest supported failure point in a fixed
mechanism ladder: required knowledge absent, dependency graph wrong, retrieval
miss, interpretation error, compilation failure, validation or adapter
alteration, then residual model reasoning. This order prevents a retrieval or
compilation defect from being counted as a reasoning failure. The structural
analysis above does not assign ladder categories; aggregate prevalence remains
pending until the permitted diagnostic process supplies enough evidence.

Four intervention families were fixed before the optimization phase was cut:
same-grain
dependency composition (E01), FK-backed grain relationships (E02), bounded
semantic descriptions (E03), and a broad HKB-context negative control (E04).
Their reusable changes and promotion rules are recorded in
[`planned-dev-a-interventions-v1.json`](experiments/planned-dev-a-interventions-v1.json).

| Experiment | Evidence completed | Decision | Remaining gate |
| --- | --- | --- | --- |
| E01: same-grain dependencies | The frozen baseline already has 48 dependency-bearing elements, 70 executable dependency edges, and depth three | Inconclusive; already baseline | No further E01 contrast |
| E02: FK-backed relationships | 1,049 public FKs pass the conservative contract; the bounded artifact emits 91 relationships across 16 databases and 67 source topics, with zero metric-disposition changes | Preserve as offline evidence; not promoted | None; deployment and evaluation were cut |
| E03: bounded descriptions | Prespecified only | Not run | None; optimization phase closed |
| E04: broad HKB context | Prespecified negative control only | Not run | None; optimization phase closed |

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

The separate offline E02 artifact has candidate-set SHA-256
`db811d6ec553d3b82e42ba3bbd9bafe7ca528a695836a33d6f1aff0b60c5b074`.
It publishes and authenticates locally, but it is not the final candidate and
will not be deployed or evaluated. Its historical artifacts remain immutable.
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

All entries in this section remain pending until all 1,068 sealed generations
have completed and the sealed scorer releases permitted aggregate results. The
final C1−C4 configurations are already frozen.

### Primary endpoints

| Endpoint | Estimate | 95% interval |
| --- | ---: | ---: |
| C4 mean one-shot execution accuracy | **Pending** | **Pending** |
| C4 repetition-one execution accuracy | **Pending** | **Pending** |
| C4−C1 paired accuracy difference | **Pending** | **Pending** |

### Four-condition matrix

| Condition | Mean accuracy | Wrong rate | Content-refusal rate | Insufficient-context rate | Error rate | Pass³ | Correctness flips |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | **Pending** | **Pending** | Unavailable | Unavailable | **Pending** | **Pending** | **Pending** |
| C2 | **Pending** | **Pending** | Unavailable | Unavailable | **Pending** | **Pending** | **Pending** |
| C3 | **Pending** | **Pending** | Unavailable | Unavailable | **Pending** | **Pending** | **Pending** |
| C4 | **Pending** | **Pending** | Unavailable | Unavailable | **Pending** | **Pending** | **Pending** |

The frozen generation contract does not distinguish content refusal from
insufficient context, so those two rates are unavailable rather than pending.

### Exploratory contrasts

| Contrast | Paired difference | Interpretation |
| --- | ---: | --- |
| C2−C1 | **Pending** | Association with adding searchable business knowledge |
| C3−C2 | **Pending** | Association with structured semantic representation |
| C4−C3 | **Pending** | Governed-system contrast; causal scope depends on achieved model parity |

Both the official-compatible Soft EX score and the preregistered corrected
multiset sensitivity score will be reported. Neither scorer will be selected or
changed in response to the held-out result.

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
   query itself succeeded.

The direct and C4 development baselines associate these mechanisms with
failures. The held-out evaluation will determine the frozen system's final
comparative result.

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
- C4 development accuracy is 9/136 on its full answerable frame, while the
  direct C1-C3 percentages use a 122-question intersection. Their raw difference
  is not a matched or paired development contrast.
- Execution equivalence remains the benchmark authority. AI Hub diagnostics and
  judge outcomes can explain behavior but do not replace result-set scoring.
- E02 passed deterministic local publication checks only and is retained as
  offline evidence. It was not promoted, deployed, or evaluated; the executed
  final candidate receives no question-level supervision, and dev-B is
  intentionally unconsumed.
- Held-out accuracy, reliability, and confirmatory condition conclusions are
  pending. No placeholder in this report should be interpreted as a result.

## 9. Reproducibility

The repository preserves the public manifest and deterministic split, public
HKB/schema inputs and hashes, transformation artifacts, condition disclosure,
telemetry contracts, experiment history, and two frozen scorers. Private gold
and hidden annotations remain outside the repository. See
[README.md](README.md) for reproduction commands and
[manuscript/main.pdf](manuscript/main.pdf) for the supporting protocol paper.
The final system is frozen at commit
`d8d1a9335fe2107157f8ef0814f99e80ffd7ef1e`; its direct-child control commit is
`079e4ce8399b3c29545c60753e5e2da6e68ca582`, and the Freeze-B manifest SHA-256
is `902fb1be70fd20fb193a8f302b25d5c68a7d6a37b78db6124d84868b92151a80`.
The C1 sensitivity subset, allocation diagnostics, preserved-artifact hashes,
and notional cost/time projection are committed separately from its future raw
run artifacts; OAuth dollars remain telemetry rather than a run-selection
rule.

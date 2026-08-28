# Does an Enforced Semantic Layer Improve Analytical Question Answering?

## Results report

> **Status — 2026-08-28:** Public-only modeling and the first four-condition
> integration slice are complete. Development and sealed-test accuracy have not
> yet been computed. Tables marked **Pending** are deliberate placeholders, not
> zeroes. The 101 held-out questions and their labels remain sealed.

## Executive summary

This study asks whether an analytical agent becomes more accurate when business
knowledge is represented and enforced through Omni's semantic layer instead of
being left to direct SQL generation. We evaluate 332 analytical tasks from
LiveSQLBench Large-v1: 231 development questions and 101 sealed questions. The
development partition is further divided into 154 adaptively reused questions
and 77 metered validation questions. Four systems separate access to raw schema,
business knowledge, structured semantic knowledge, and governed execution.

The headline execution results are pending. Two findings already emerged from
building and validating the public-only baseline:

1. **Grain and relationship contracts, not scalar expression syntax, were the
   main obstacle to converting business knowledge into executable semantic
   objects.** Across 1,036 definitions in the 17 databases beyond the initial
   canary, 179 (17.3%) compiled, 183 (17.7%) were retained as searchable context,
   491 (47.4%) were deferred because they crossed an unresolved grain, and 183
   (17.7%) were unsupported. The most common recorded losses were unknown
   cardinality, unspecified aggregation, and missing cross-grain identity.

2. **The direct-SQL scaffold initially failed because schema discovery was
   unbounded.** On one public canary, returning all 51 tables caused a failed
   attempt to consume 173,365 tokens and $1.7398935 before issuing any database
   query. Query-directed retrieval capped at four tables reduced the next
   diagnostic attempt to 1,585 tokens and $0.017715, revealing a separate public
   identifier-validation defect. After that defect was corrected, the frozen C1
   canary reached SQL execution at 33,445 tokens and $0.214778. This is one
   integration case, not an accuracy estimate, but it demonstrates that scaffold
   design can dominate whether an otherwise competent comparator completes at
   all.

These early results already narrow the product question. Supplying definitions
is not enough if their grain cannot be represented safely, and offering a tool
is not enough if one valid call exhausts the model's context or budget. The
remaining evaluation tests whether correcting those problems translates into
execution accuracy on unseen questions.

## 1. Research question

The primary question is:

> Given a modeled database, how accurately does production-governed Omni answer
> previously unseen analytical questions?

The primary comparison is governed Omni against a competent direct-SQL agent on
the same sealed questions. Three additional contrasts help explain any
difference:

| Condition | Information available at runtime | Query path |
| --- | --- | --- |
| C1 | Public schema | Direct SQL |
| C2 | Public schema and searchable HKB | Direct SQL |
| C3 | Public schema and searchable Omni model | Direct SQL |
| C4 | Omni semantic model | Production-governed Omni |

C2−C1 tests the value associated with making business knowledge available.
C3−C2 tests the value associated with structuring that knowledge. C4−C3 is
reported as a system-level, scaffold-conditional comparison unless model and
harness parity can genuinely isolate enforcement.

## 2. Experimental design

The pinned public benchmark has 480 instances across 18 PostgreSQL databases.
We excluded 148 `Management` tasks and retained all 332 `Query` tasks. A
deterministic split, based only on public metadata and stratified primarily by
database and `high_level`, assigned 231 questions to development and 101 to the
sealed final evaluation. Every database appears in both partitions.

The 231 development questions are split into dev-A (154) and dev-B (77). System
development may repeatedly use dev-A. Dev-B remains an internal generalization
gate with a hard maximum of ten checkpoint evaluations, but it is deliberately
reserved and unconsumed in the same-day execution described here. The final 101-
question set is inaccessible to development. All four frozen conditions will
produce three independent, interleaved attempts per sealed question before any
test output is scored.

The complete preregistration, custody rules, scorer definitions, and condition
disclosure are in [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md),
[docs/scoring.md](docs/scoring.md), and
[docs/harness-disclosure.md](docs/harness-disclosure.md).

## 3. Public-only baseline construction

Before using hidden development labels, we transformed only public schema,
column metadata, and the hierarchical knowledge base into deterministic Omni
artifacts. Every knowledge node received exactly one disposition:

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
databases.

| Disposition | Definitions | Share |
| --- | ---: | ---: |
| Compiled | 179 | 17.3% |
| Context only | 183 | 17.7% |
| Deferred cross-grain | 491 | 47.4% |
| Unsupported | 183 | 17.7% |
| **Total** | **1,036** | **100.0%** |

The three most frequent loss codes were `cardinality_unknown` (398),
`aggregation_unspecified` (314), and `cross_grain_no_identity` (308). Domains
with many row-local physical or sensor definitions, such as planets and solar
panels, compiled comparatively well. Residential and reverse-logistics models
retained useful context but compiled no HKB definitions safely under the same
rules.

This supports a **representation** conclusion, not an answer-accuracy
conclusion. The transformation has not yet shown which deferred definitions are
needed by benchmark questions or whether searchable context compensates for
their absence. Those questions require scored development runs.

The product implication is concrete: an HKB-import workflow needs first-class
metric grain, entity identity, relationship/cardinality, and aggregation
contracts. A useful compiler dry run should also explain why each definition
was compiled, retained as context, deferred, or rejected. Otherwise users must
choose between silently guessed semantics and large amounts of prose that the
agent may or may not discover.

The deterministic artifacts and review corrections landed in commits
`d3f84f6ea5d15b247e3d1ffba739cd220289e72a` and
`dcdd1a08a3d45a4a14978fe39f66542938fa5f32`. The detailed product record is
[PF-009](docs/product-findings.md#pf-009-missing-grain-contracts-dominate-public-only-hkb-translation).

## 4. First end-to-end vertical slice

We tested one public dev-A question on `archeology_scan_large` before scaling.
The purpose was integration validation, not correctness measurement: prove that
each condition could generate an answer, preserve a trace, reach its read-only
database, and produce an artifact compatible with the frozen evaluation path.
No correctness result was inspected.

### Finding 2: bounded schema discovery fixed a cost-driven direct-SQL failure

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

The first bounded attempt did not answer: it exposed a second defect in which a
generic secret heuristic rejected canonical public foreign-key IDs. A typed,
fail-closed validation rule fixed that boundary without weakening credential
checks. The subsequent immutable canary reached SQL and produced a complete
trace. This sequence matters because it preserves the failed intermediate
experiment instead of attributing the entire improvement to retrieval alone.

The evidence supports three limited conclusions:

- the original failure was caused by unbounded scaffold context rather than an
  inability to inspect the relevant schema;
- bounded retrieval reduced the diagnostic context and cost enough to expose
  the next failure mechanism; and
- after the independent identifier fix, the direct comparator completed the
  same public integration slice.

It does **not** establish that bounded retrieval improves execution accuracy,
nor that the cost ratios generalize beyond this one question and database.
Scaled telemetry will test both.

The product lesson is broader than this comparator. Tool payload bounds are
part of agent quality: a semantically valid tool call can still make the system
unusable if it consumes the remaining inference budget. Tooling should expose
query-directed schema search, payload estimates, and typed provenance rather
than treating all identifiers as untrusted free text. The relevant commits are
`2b72244de9fefa4d4f7329ba159f571a8242da79` (bounded retrieval) and
`50ebc31075f742fba4e7d4bbc6fc4da0b15d53ce` (typed public relationship IDs).

## 5. Baseline and optimization trajectory

The public-only baseline will be preserved before hidden dev-A supervision is
used. Subsequent changes will be evaluated through the existing research loop:
observe a recurring failure, state a mechanism, make the smallest reusable
intervention, and measure targeted and global regressions on dev-A. Dev-B is
kept in reserve rather than consumed during this same-day optimization cycle.

| Stage | Accuracy | Wrong answer | Refused | Errored | Median latency | Tokens/correct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Public-only baseline, dev-A | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| Final candidate, dev-A | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| dev-B internal validation | **Reserved; not consumed** | — | — | — | — | — |

Meaningful kept, reverted, and inconclusive interventions will be summarized
here from the append-only [experiment ledger](experiments/experiments.csv) and
the contemporaneous [research log](docs/research-log.md). A flat accuracy result
will still be reported when it changes confident errors into explicit refusals
or materially changes cost and reliability.

## 6. Held-out results

All entries in this section remain pending until the final C1−C4 configurations
are frozen, all 1,212 sealed generations have completed, and the sealed scorer
releases permitted aggregate results.

### Primary endpoints

| Endpoint | Estimate | 95% interval |
| --- | ---: | ---: |
| C4 mean one-shot execution accuracy | **Pending** | **Pending** |
| C4 repetition-one execution accuracy | **Pending** | **Pending** |
| C4−C1 paired accuracy difference | **Pending** | **Pending** |

### Four-condition matrix

| Condition | Mean accuracy | Wrong-answer rate | Refusal rate | Error rate | Pass³ | Correctness flips |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| C2 | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| C3 | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| C4 | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |

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

The pre-scoring evidence supports two immediate recommendations:

1. **Make grain contracts explicit and inspectable.** Model import and AI-facing
   authoring should represent metric grain, entity identity, relationship
   cardinality, and aggregation semantics directly. A dry run should show which
   definitions cannot be governed and why.
2. **Treat retrieval payloads as part of the agent contract.** Schema and
   semantic search tools should be query-directed, bounded, and observable.
   Telemetry should identify context volume per tool call and use typed public
   provenance IDs so safety filters do not reject legitimate semantic metadata.

These recommendations remain provisional with respect to answer accuracy. The
scored baseline and supervised experiments will determine how often each issue
causes a wrong answer, refusal, or product error, and whether the proposed fixes
generalize beyond the canary.

## 8. Limitations

- D-043 measures transformation coverage, not question correctness. A deferred
  definition may never be needed, and a compiled definition may still be
  retrieved or interpreted incorrectly.
- D-045 is a single-question integration sequence. Its token and cost changes
  should not be treated as population estimates.
- C4 is a composite production system. Unless its underlying model and resource
  settings can be matched exactly, C4−C3 is a system-level comparison rather
  than an isolated estimate of semantic enforcement.
- Execution equivalence remains the benchmark authority. AI Hub diagnostics and
  judge outcomes can explain behavior but do not replace result-set scoring.
- Held-out accuracy, reliability, and condition-level conclusions are pending;
  no placeholder in this report should be interpreted as a result.

## 9. Reproducibility

The repository preserves the public manifest and deterministic split, public
HKB/schema inputs and hashes, transformation artifacts, condition disclosure,
telemetry contracts, experiment history, and two frozen scorers. Private gold
and hidden annotations remain outside the repository. See
[README.md](README.md) for reproduction commands and
[manuscript/main.pdf](manuscript/main.pdf) for the supporting protocol paper.

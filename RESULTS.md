# Does an Enforced Semantic Layer Improve Analytical Question Answering?

## Results report

> **Status — 2026-08-28:** Public-only modeling and the first four-condition
> integration slice are complete; immutable baseline generation is underway.
> Development and sealed-test accuracy have not yet been computed. Tables marked
> **Pending** are deliberate placeholders, not zeroes. The 101 held-out questions
> and their labels remain sealed.

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
   objects.** Across all 1,090 definitions, 193 (17.7%) compiled, 193 (17.7%)
   were retained as searchable context, 511 (46.9%) were deferred because they
   crossed an unresolved grain, and 193 (17.7%) were unsupported. The most
   common recorded losses in the 17-database fan-out were unknown cardinality,
   unspecified aggregation, and missing cross-grain identity.

2. **Schema retrieval made the direct comparator viable, but it remained an
   experimental variable rather than a solved detail.** On one public canary,
   returning all 51 tables caused a failed attempt to consume 173,365 tokens and
   $1.7398935 before issuing any database query. Query-directed retrieval capped
   at four tables enabled a reviewed C1 canary to reach SQL execution at 33,445
   tokens and $0.214778. Later archeology attempts still exhausted the model
   budget or returned no answer, so that database was excluded from the scaled
   direct baseline under a predeclared disposition rule. A separate 20-question,
   16-database sensitivity arm now tests whether the four-table window itself
   drives insufficient-context outcomes.

These early results already narrow the product question. Supplying definitions
is not enough if their grain cannot be represented safely, and offering a tool
is not enough if one valid call exhausts the model's context or budget. The
remaining evaluation tests whether correcting those problems translates into
execution accuracy on unseen questions.

## 1. Research question

The primary question is:

> Given a modeled database, how accurately does production-governed Omni answer
> previously unseen analytical questions?

The primary comparison is governed Omni against a reasonably tuned direct-SQL
agent on the same sealed questions. Three additional contrasts help explain any
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
harness parity can genuinely isolate enforcement. This wording is deliberate:
the direct conditions use one pinned Claude OAuth scaffold, while C4 preserves
Omni's production-managed workflow and may use a composite model system.

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

Two database exclusions apply only to the public C1−C3 baseline-generation
frame. `archeology_scan_large` repeatedly failed to return a usable direct
answer across distinct retrieval settings; `cybermarket_pattern_large` was
excluded after its first immutable launch failed read-only privilege
attestation, even though the external credential was subsequently repaired.
The resulting direct baseline contains 630 attempts over 210 development
questions and 16 databases. Both exclusions are fixed in
[`public-baseline-exclusions-v1.json`](config/conditions/public-baseline-exclusions-v1.json)
and will be reported as scope limitations, not silently treated as wrong
answers or missing rows.

C4 development generation is budgeted and scheduled separately from this
direct arm. Its question subset must be stratified and committed before launch,
and condition comparisons will use only matched question/database coverage.
This development-scope choice does not change the preregistered sealed-test
population or permit result-dependent C4 sampling.

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

The deterministic fan-out artifacts and review corrections landed in commits
`d3f84f6ea5d15b247e3d1ffba739cd220289e72a` and
`dcdd1a08a3d45a4a14978fe39f66542938fa5f32`. The detailed product record is
[PF-009](docs/product-findings.md#pf-009-missing-grain-contracts-dominate-public-only-hkb-translation).

## 4. First end-to-end vertical slice

We tested one public dev-A question on `archeology_scan_large` before scaling.
The purpose was integration validation, not correctness measurement: prove that
each condition could generate an answer, preserve a trace, reach its read-only
database, and produce an artifact compatible with the frozen evaluation path.
No correctness result was inspected.

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

It does not show that four matches is the correct bound. A later attempt on a
different archeology question reached five four-table searches, consumed
$7.49, and ended in `model_budget_error`. Reducing the window to two tables cut
that attempt to four searches and $4.32, but it still returned no answer. The
cheaper failure was not evidence for adopting the smaller window, so the change
was reverted. Archeology was then excluded under the predeclared rule rather
than repeatedly tuned.

It does **not** establish that bounded retrieval improves execution accuracy,
nor that the cost ratios generalize beyond this one question and database.
Scaled telemetry will test both. D-054 additionally freezes a 20-question
public-development subset spanning all 16 included databases. It changes only
the match cap from four to eight, preserves the 64 KiB per-call ceiling and all
other C1 artifacts, and compares insufficient-context rates once the canonical
baseline releases the OAuth profiles. Membership was fixed without consulting
question-level outcomes.

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

| Stage | Accuracy | Wrong answer | Content refusal | Insufficient-context no answer | Errored | Median latency | Tokens/correct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Public-only baseline, dev-A | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| Final candidate, dev-A | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| dev-B internal validation | **Reserved; not consumed** | — | — | — | — | — | — |

Meaningful kept, reverted, and inconclusive interventions will be summarized
here from the append-only [experiment ledger](experiments/experiments.csv) and
the contemporaneous [research log](docs/research-log.md). A flat accuracy result
will still be reported when it changes confident errors into explicit refusals
or materially changes cost and reliability.

Before baseline completion, we limited supervised work to four prespecified
families: same-grain dependency composition, FK-backed grain relationships,
bounded semantic descriptions, and an intentionally broad HKB-context negative
control. Their exact changes, full-dev-A gates, regression rules, and stopping
criteria are recorded in
[`planned-dev-a-interventions-v1.json`](experiments/planned-dev-a-interventions-v1.json).
The plan was based on aggregate public representability evidence, not on current
question-level baseline outcomes. C4 is the promotion condition; C3 provides a
matched diagnostic and cannot offset a C4 regression.

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

| Condition | Mean accuracy | Wrong rate | Content-refusal rate | Insufficient-context rate | Error rate | Pass³ | Correctness flips |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| C2 | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| C3 | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |
| C4 | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** | **Pending** |

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

The pre-scoring evidence supports three immediate recommendations:

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
- The public direct baseline excludes archeology and cybermarket and therefore
  estimates C1−C3 behavior on 16 databases, not the full 18-database population.
  Any comparison to a broader C4 arm must use matched coverage or disclose the
  mismatch.
- The four-table schema window is a comparator scaffold choice. D-054 measures
  its sensitivity on 20 fixed questions, but that arm is still too small to
  identify modest database-specific effects.
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
The C1 sensitivity subset, allocation diagnostics, preserved-artifact hashes,
and notional cost/time projection are committed separately from its future raw
run artifacts; OAuth dollars remain telemetry rather than a run-selection
rule.

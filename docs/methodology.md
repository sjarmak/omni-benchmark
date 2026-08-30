# Methodology and preregistered analysis plan

Status: pre-gold, protocol version 2 (Freeze A frozen by this commit).

This document operationalizes [the custody protocol](../EVALUATION_PROTOCOL.md)
and the machine-readable preregistration in `config/preregistration.json`. If a
later narrative conflicts with either frozen artifact, the earlier committed
protocol and configuration govern. Deviations must be timestamped and explained;
they may not be silently edited into the original plan.

## Research questions and experimental hierarchy

### Primary question

Given an established semantic model for a database, how accurately does the
production-governed Omni system answer analytical questions it has not seen
during development?

The estimand is question-level generalization within a modeled database:

```text
known database + public schema/HKB + frozen semantic model and harness
                                -> previously unseen question
                                -> execution-result correctness
```

All 18 databases occur in both partitions. Full public schema, column meanings,
HKB, and public question text are available during development. The held-out
unit is the question, not the database or business knowledge. This matches the
product setting in which a team models its data once and users ask an open-ended
stream of new questions.

### Secondary question: transformation portability

Within the development partition only, leave-one-database-out (LOODO)
experiments estimate whether general HKB-to-Omni transformation rules transfer
to a new domain:

1. use train outcomes from 17 databases to develop general transformation rules;
2. apply those rules to the held-out database's public schema, column meanings,
   and HKB without using any question-driven evidence from that database;
3. score the resulting system on that database's development questions;
4. rotate across all 18 databases.

Each fold must be built from provenance that excludes the held-out database's
train outcomes. Report pooled question accuracy and the macro-average across 18
database accuracies, then compare the portable state with the later database-
specific refined state. LOODO is a development-set study, not a second test set
or the headline claim. Report each fold's question count and modeling effort. If
the held-out database receives human/manual modeling, describe the result as
transformation portability—not full zero-shot database generalization.

### Explanatory architectural ablation

Four frozen conditions decompose access to knowledge, its representation, and
its enforcement:

| Condition | Knowledge | Representation | Enforcement |
| --- | --- | --- | --- |
| C1 Raw SQL | Public schema | Raw schema | None |
| C2 HKB-reference SQL | Public schema and HKB | Searchable raw HKB | Optional |
| C3 Omni-model SQL | Public schema and HKB | Searchable exported Omni semantic model | Optional |
| C4 Governed Omni | Public schema and HKB | Omni semantic model | Production harness governs the accessible surface and resolves model field references; measured on the development baseline it performs no query compilation |

The C4 enforcement cell previously read "production harness enforces semantic
compilation/validation". That is falsified by measurement. All 135 governed
semantic queries in the frozen development baseline carry `rewriteSql: true`
with agent-authored SQL, and none declares a join path. The deployed topics emit
`"joins": {}` and publish no measures, so the model declares no join path and no
aggregate for a planner to compile. What the production harness enforces is the
accessible surface and the resolution of `${view.field}` references against the
deployed model, not query composition. Measurement and disclosure language:
[`c4-query-path-disclosure.md`](c4-query-path-disclosure.md).

C2 and C3 receive reasonable programmatic discovery/search; neither is made to
ingest an approximately 84K-token context blob in one prompt. Match exogenous
resources while preserving architectural differences. The design is motivated
by Omni's claim that optional semantic definitions differ from enforced semantic
compilation, but this experiment will test rather than assume that claim. The
executed baseline tests it and finds that the governed condition did not exercise
semantic compilation at all. See
[Omni's published benchmark](https://omni.co/blog/benchmarking-omnis-agentic-analytics-harness).

## Population and deterministic split

Eligibility uses only public metadata from pinned LiveSQLBench Large-v1 revision
`a418e108d5cbb4cf9b783a928eff5e924ad2460d`:

- include all 332 records with `category == "Query"`;
- exclude all 148 records with `category == "Management"`.

The split is 231 development questions and 101 held-out questions. Algorithm
version 1 uses committed seed `omni-livesqlbench-large-v1-split-v1`. It allocates
test counts across `selected_database` with Hamilton largest remainder, then
balances public `high_level` within each database and orders each stratum by
SHA-256 of seed, database, `high_level`, and `instance_id`. Public `conditions`
distributions are audited after allocation but are not crossed into sparse
strata. Difficulty is not used because `difficulty_tier` is absent from the
pinned public JSONL.

The authoritative artifacts are
`data/manifests/eligible_questions.jsonl`, `train_ids.txt`, `test_ids.txt`,
`manifest_metadata.json`, and `split_metadata.json`. The eligible manifest hash
is `ed8a7b3f55e893e05a9e602b34b39509ca29a30798afd63fd9a521f5ffbc7d0e`;
train/test ID hashes are respectively
`ecdd1e4cd425e41970d3d4e96d7c3cb044cb78d94e34621d320e3d542a5d1c46`
and `c7d4eb1aff3e9be9ffa015adcae96bb9294adf138870db24cdfbed811a9de76f`.
Their pre-gold commit, not this prose, is authoritative. Tests must establish
that IDs are unique, train and test are disjoint, their union is the 332-record
eligible manifest, counts are 231/101, all 18 databases appear in both,
regeneration is byte-identical, and no protected field has entered a committed
artifact.

The 231 development questions are further split with committed seed
`omni-livesqlbench-large-v1-development-split-v1` into 154 `dev-A` optimization
questions and 77 `dev-B` checkpoint questions. The internal split uses the same
database-first, `high_level`-balanced approach and audits `conditions`, especially
`order`, after allocation. `dev-A` is the repeated adaptive surface. `dev-B` is
consulted only at explicit checkpoints, with an immutable counter and a protocol
maximum of ten evaluations. Membership never changes based on outcomes.

## Information boundaries and gold custody

The governing rule is:

> Hidden training annotations may influence how a reusable system is built, but
> may never become question-specific runtime inputs.

| Information | Development | Runtime | Held-out model development |
| --- | --- | --- | --- |
| Public schema, column meanings, HKB, and questions | Allowed | Allowed | Frozen |
| Hidden dev-A SQL, test cases, and knowledge IDs | Offline scoring/diagnosis only | Prohibited | Frozen |
| Hidden dev-B SQL, test cases, and knowledge IDs | Guardian only; aggregate signed receipts enter development | Prohibited | Frozen |
| Hidden test SQL, test cases, and knowledge IDs | Prohibited | Prohibited | Sealed evaluator only |

The untouched private attachment remains under human custody outside both the
repository and agent-accessible workspace. The custodian computes its SHA-256
without printing or parsing content into the workspace. Only after the split
commit exists may a deterministic user-run extractor release only the 154 dev-A
records into a gitignored private directory. That extractor must bind the
canonical dev-A manifest and development-split metadata to Freeze A, reject all
other IDs, and never emit hidden fields in logs. Dev-B labels remain with the
guardian; development receives only signed aggregate checkpoint outcomes.

The complete private source never enters the development workspace, including
after freeze. A dedicated sealed evaluator receives it for final scoring,
selects the committed 101 IDs internally, and emits only the minimum result
contract needed for analysis: trial identity, binary correctness, system-failure
status, and non-sensitive aggregate/subgroup diagnostics. It must not emit gold
SQL, hidden knowledge IDs, test-case bodies, or unredacted gold results.

If the attachment format was not publicly specified well enough to prebuild a
correct extractor, the adapter may be implemented after the split commit. This
does not weaken split integrity, provided structural validation remains under
human custody and no held-out content is exposed.

## Reproducible experiment lifecycle

### Stage 0: public-only construction

Before hidden train labels are released:

1. pin and hash the public dataset, HKB, column meanings, schema, database dumps,
   evaluator, and software environment;
2. deterministically build the eligible manifest and 231/101 split;
3. provision and fingerprint database copies;
4. mechanically transform public semantic inputs into Omni;
5. validate the transformed models structurally;
6. freeze that transformation revision and semantic artifacts;
7. generate and preserve baseline outputs on the 231 development questions.

The unscored generated outputs are the pre-supervision baseline. After the
dev-A-only release, score its dev-A outputs locally; score its dev-B outputs
through the guardian and retain only the signed aggregate receipt. Do not modify
or regenerate either output set. This separates mechanical transformation
quality from supervised refinement.

### Stage 1: development baseline and failure analysis

Freeze common direct-SQL harness behavior for C1-C3, then establish reasonable
train baselines for all four conditions. Capture per-question SQL or governed
query artifact, result, correctness, latency, token/cost information when
observable, errors, retries, tool trajectory, condition, and configuration
hashes. Every attempt is `correct`, `wrong_answer`, or `refused_or_error`. Do not
reduce the run to one accuracy value.

Dev-A `external_knowledge` IDs are privileged diagnostic-oracle metadata. After
a run they may answer questions such as whether required HKB nodes exist in the
compiled model, whether their dependencies resolved, and whether the agent could
reach them. They may not select HKB entries or runtime context for that question.
Question-level dev-B annotations remain unavailable.

### Stage 2: evaluation-driven agentic optimization on dev-A

Every meaningful intervention creates an append-only experiment record before
its result is interpreted. The record includes:

- experiment ID and timestamp;
- hypothesis and predicted failure class;
- observed failure/mechanism and optimization surface (`textual`, `structural`,
  or `human_research_controlled`);
- candidate-generation method, exact change, generality scope, and separate
  content/intervention provenance;
- code, semantic-model, prompt, and configuration commits/hashes;
- `dev-A` result before and after, regression-suite outcome, fixed/regressed IDs,
  and affected subgroup counts;
- `dev-B` result and monotonic checkpoint count only when checkpointed;
- latency/cost changes where observable;
- failure classes added, removed, or unchanged;
- conclusion: keep, revert, investigate, or archive;
- deviations, negative results, and follow-up questions.

Prefer one controlled intervention at a time and the smallest reusable change
before architectural escalation. Textual surfaces may compare multiple
trace-informed candidates; structural surfaces use mechanism hypotheses,
targeted tests, then complete `dev-A` regression evaluation. Protocol, split,
custody, endpoints, scorer choice, and supervision legitimacy are human-
controlled surfaces and cannot be autonomously optimized from scores.

The optimizer receives rich sanitized traces: question, three-state outcome,
actual-result hash, failure category, public HKB nodes, semantic objects
available/retrieved, generated query, compiler/validator/execution behavior, and
prior experiments. Hidden development annotations remain inside offline
diagnosis and never become runtime or ordinary trace fields.

Accepted capability fixes add representative `dev-A` cases to an append-only
regression suite. Candidates form branching lineage rather than a single newest-
winner chain. Maintain a small Pareto set across accuracy, confidently wrong and
refusal/error rates, regressions, cost, latency, complexity, special cases,
stability, and generality; do not invent a weighted scalar. Promote few branches
to `dev-B`. A dev-A gain that regresses dev-B is evidence of overfitting, not a
prompt to tune on individual dev-B failures.

Do not erase failed or regressing experiments. All four conditions receive
enough train development and effort accounting to be credible comparators;
C1-C3 must not remain first-pass baselines while C4 is extensively tuned.

### Freeze A and Stage 3: Freeze B

Freeze A precedes all hidden development labels and commits the population,
outer and internal splits, custody/information rules, condition definitions,
official and sensitivity scorers, endpoints/statistics, repeat/rerun policy,
post-hoc audits, and ledger schema. It does not freeze the final system.

Stage 3 is Freeze B after development and before any held-out scoring. Freeze B
commits together:

Freeze together:

- transformation code, source-to-semantic provenance, and all semantic models;
- Topics, relationships, retrieval/search indices, descriptions, and examples;
- all prompts/system instructions and tool descriptions that are accessible;
- C1-C4 harness configurations;
- provider/model/tier identifiers and reasoning/sampling settings where exposed;
- tool, token, time, and retry budgets;
- failure ownership and infrastructure-rerun rules;
- database snapshot identifiers and parity fingerprints;
- scorer/evaluator revision and conformance-test results;
- deterministic trial schedule and its seed.

The Freeze B manifest records the git commit and content hashes. No test generation
begins until every condition and analysis rule is frozen.

### Stage 4: sealed generation and scoring

Run 4 conditions x 101 questions x 3 repetitions = 1,212 trials. A committed,
deterministic block-interleaved permutation covers question, condition, and
repetition while separating repetitions of the same question. Repetition labels
are assigned before scheduling; "first attempt" means preregistered repetition
1, not whichever result is most favorable or completes first.

Generate and durably store all 1,212 frozen outputs before scoring any against
test gold. Only then may the sealed evaluator execute gold and emit results.
Nothing learned from held-out outcomes may change a semantic model, prompt,
harness, tool, retry policy, or condition. A later test-informed system is a new
exploratory study and cannot replace the untouched result.

## HKB-to-semantic-layer method

### Provenance-first intermediate representation

Use a canonical intermediate representation between public LiveSQLBench files
and Omni rather than compiling natural-language files directly into ad hoc model
edits. This boundary has three purposes: deterministic parsing, a portable LOODO
transformation surface, and auditability when Omni cannot express a rule exactly.

For every source object, preserve:

- database, source file hash, source record/field path, and stable source ID;
- original text/type and parsed schema/column identity;
- HKB prerequisite edges, with both `-1` and `[]` normalized as no dependency;
- intended semantic role and any required grain, aggregation, filter, join, time,
  or JSON-path behavior;
- compiled Omni object IDs and model revision;
- transformation class: mechanical, interpreted, or explicit exception;
- validation status and any loss/ambiguity note.

Resolve the HKB as a directed prerequisite graph. Because all 18 databases have
multi-hop paths, compilation must be dependency-aware and fail visibly on a
cycle, dangling reference, unsupported expression, or ambiguous binding. It may
not silently paste an unresolved formula into generic context and call it
governed.

### Transformation classes

**Mechanical/generalizable transformations** include parsing DDL, keys, types,
column meanings, nested JSON meanings, HKB IDs/types/edges, unambiguous field
bindings, literal aliases, and dependency ordering.

**Interpretive transformations** include choosing measure versus dimension,
aggregation grain, join ownership/path, time semantics, business filters, and
mapping a natural-language formula to a supported Omni expression. Each requires
written rationale and train-only validation.

**Benchmark-specific exceptions** are allowed only when the public source cannot
be represented by a general rule. They are keyed to a public database/HKB object,
never a question ID, and remain countable and auditable. A large or growing
exception count is itself a scalability/product finding.

Potential product objects include modeled relationships, dimensions, measures,
derived fields, aliases/synonyms, field/Topic/global AI context, filters, time
semantics, and sample queries. Their exact use is an experiment, not assumed in
advance. Unsupported HKB behavior must be logged rather than approximated
silently.

### Gold-derived examples

Sample queries are a legitimate product capability but a high-risk supervision
channel. They must encode reusable patterns rather than benchmark question-to-
gold pairs, contain no question IDs or verbatim question/gold mapping, and have
an experiment record and source rationale. Report their number and provenance.
If they materially affect train accuracy, run a with/without ablation before
freeze.

## Condition parity and interpretation

C1-C3 use one pinned, capable direct-SQL model and a common harness. Match
question wording, schema/data snapshot, query execution access, search/tool-call
budget, time/token budget, retry policy, and scorer. C2 receives raw HKB through
searchable discovery; C3 receives the exported Omni model through an equivalent
search interface. Neither receives hidden knowledge IDs.

C4 remains the actual production-default Omni system, including its production
query-rewrite and validation behavior. Production fidelity takes
precedence over forcing model parity. Omni currently documents AWS Bedrock as
its default managed provider and a three-tier model system, with some model
selection not directly configurable under Bedrock; see the official
[model-provider documentation](https://docs.omni.co/ai/settings/model-providers).

The measured query path narrows the contrast further, independently of model
parity. Both arms have an agent authoring SQL, so C4-C3 does not separate a
compiled-query condition from a direct-SQL one. It separates two agent-authored
SQL conditions differing in agent, SQL dialect, accessible surface, and execution
contract.

Before test results exist, classify C4-C3 as one of:

- **approximate controlled architectural contrast** if the same underlying
  model/version and relevant settings are actually matched, still subject to
  remaining system differences; or
- **production-system contrast** if exact model parity is unavailable or C4 is
  a composite multi-model workflow.

In the second case, C4-C3 must not be described as the causal effect of
enforcement. C2-C1 and C3-C2 remain the cleaner direct-agent contrasts. C2 is
an important substantive result: it estimates how much a competent direct-SQL
agent gains simply from access to missing business semantics. Prior
semantic-context evidence bears on C2-C1, not on the distinct C3-C2 question of
structured executable representation.

## Generation artifact contract

The exact condition-level scaffold is disclosed in `docs/harness-disclosure.md`.
Each immutable generation artifact includes, when the system exposes it:

- experiment/run/trial ID, question ID, database, condition, and repetition;
- schedule position, request/response timestamps, and elapsed latency;
- freeze commit plus prompt, model, semantic-model, tool, and configuration
  hashes;
- provider/model identifier or observable Omni tier;
- generated SQL or governed query plan/field selection, execution status, and a
  normalized result hash;
- tool trajectory, tool/database-query counts, retry and validation counts,
  token use/source, cost/source, and trace coverage/degraded reason;
- no-answer/error class and raw non-secret diagnostic logs;
- a raw private trace hash/reference. A separate immutable scoring record adds
  scorer revision and the three-state correctness outcome after labels exist.

Unavailable telemetry is null and explicitly identified; it is never silently
coerced to zero. For each intervention and condition, analyze accuracy,
confidently-wrong rate, refusal/error rate, median/IQR tokens and latency, tokens
and calls per correct answer, database queries, retries, validation, and terminal
failure vectors. These are co-outcomes rather than fairness constraints.

Private gold SQL, hidden knowledge IDs, test-case bodies, credentials, browser
storage state, and raw secret-bearing API traffic are forbidden. Reuse the
credential discipline demonstrated in `~/gas-city-observability`: materialized
Omni browser state is a live secret, is written mode `0600`, is gitignored, and
must be removed after use. Its parity workflow also motivates separate checks
for direct database, SQL-through-Omni, and governed Topic results; a successful
connection is not evidence that semantic definitions agree.

## Scoring and evaluator conformance

The correctness unit is one question-condition-repetition. Success is binary
equivalence under the pinned official Query scorer, which executes predicted and
gold SQL and compares normalized result sets. Do not substitute SQL string match,
LLM judgment, or a hand-authored rubric.

Because the official Soft EX code has consequential behavior around `ROUND`,
`DISTINCT`, ordering, decimals, duplicates, empty results, timestamps, JSON, row
caps, and multi-statement SQL, a sealed adapter must pass a public oracle
conformance suite against the pinned evaluator. If C4 does not expose executable
SQL, any result-set adapter must prove equivalence on those cases before it is
allowed into the freeze. An unverified approximation is a product/evaluation
blocker, not a reason to change the metric invisibly.

Report execution errors, system timeouts, no-answer outcomes, and scorer
infrastructure failures separately even though system-owned failures count as
incorrect.

Freeze A pins two outputs. Official Soft EX reproduces the public evaluator at
commit `e15cd221267e06fabfaf6a3d4a69308280ce9a7c`, including its lossy set,
empty-result, two-decimal, `DISTINCT`, and `ROUND` behavior. The corrected
sensitivity scorer executes authored SQL without those semantic rewrites, uses
multisets for unordered tasks, preserves duplicates, accepts equal empty sets,
honors public decimal metadata, normalizes nulls deterministically, and preserves
order/multiplicity on ordered tasks. Both are reported; neither is selected from
the final outcomes.

## Endpoints and statistical analysis

### Primary product-performance endpoint

**C4 mean one-shot execution accuracy across three sealed repetitions.** This is
estimated from 303 question-repetition attempts with question-clustered
uncertainty. Report C4 repetition-one accuracy separately for intuitive
production interpretation. There is no majority-vote, best-of-three, or
selective-retry score.

### Primary comparative endpoint

**C4 - C1 paired execution-accuracy difference.** Pair attempts within question
and repetition and cluster inference by question. This is the main system-level
comparison between reasonably developed systems.

### Exploratory mechanistic contrasts

Report C2 - C1, C3 - C2, and C4 - C3 as paired exploratory evidence with effect
sizes, transition counts, and uncertainty. Do not overclaim modest rung effects.
If C3/C4 models or harnesses differ materially, C4 - C3 is a system-level
contrast, not a causal estimate of enforcement. Repetition-one McNemar analyses
are reported as sensitivity checks; do not apply naïve McNemar to 303 correlated
observations.

All primary and exploratory intervals use a prespecified 95% question-clustered
percentile bootstrap with 10,000 replicates. The point estimator is the mean of
the relevant binary attempt outcomes; a paired contrast is the mean within-trial
accuracy difference. Each draw samples 101 question clusters with replacement
and retains all three repetitions and relevant paired conditions for each drawn
question. Bootstrap replicate `b` and draw position `j` select index
`SHA256(seed || NUL || b || NUL || j) mod 101`, with questions ordered by
ascending `instance_id` and committed seed
`omni-livesqlbench-large-v1-analysis-v1`. The seed is UTF-8; `b` and `j` are
zero-based unpadded ASCII decimal integers; the full digest is interpreted as an
unsigned big-endian integer. For percentile `p`, nearest rank is
`sorted_values[max(0, ceil(p * 10000) - 1)]`; use `p=0.025` and `p=0.975`.
Repetition-one sensitivity tests use the exact two-sided binomial McNemar test
on discordant question pairs. The primary comparative `C4-C1` sensitivity test
is reported unadjusted. Holm correction at familywise alpha 0.05 covers the
exploratory mechanistic family `C2-C1`, `C3-C2`, and `C4-C3`. These p-values do
not replace effect sizes or intervals and do not promote exploratory rung
contrasts.

Statistical significance is supplementary to effect size and failure transitions.
With 101 questions, small deltas will be imprecise and must not be promoted based
on p-values alone.

### Reliability and descriptive secondary outcomes

Use all three repetitions to report:

- accuracy per repetition and three-run mean, without converting either into the
  sole view;
- per-question 3/3 (`pass^3`), 2/3, 1/3, and 0/3 correctness;
- correctness-flip rate;
- normalized result-set agreement across repetitions;
- wrong-answer rate, refusal/error rate, and refusal/error stability;
- latency and cost distributions;
- SQL-text variation as a diagnostic only.

Correctness stability and answer stability are separate: the same wrong answer
three times is stable but incorrect, while different SQL that returns the same
correct result can be outcome-reliable. Resample questions as clusters, retaining
all condition/repetition outcomes for each sampled question, for reliability and
repeated-run bootstrap intervals.

### Subgroups and improvement reporting

Prespecified descriptive subgroups are database, public `high_level`, and public
`conditions` values with adequate cell size. Report baseline versus final train
accuracy, held-out accuracy by subgroup, absolute improvement, and relative
improvement only when the baseline denominator is nonzero. Rare cells and
per-database test estimates are descriptive; do not mine them for significance.

Report median and interquartile range for latency/cost alongside totals and cost
per correct answer. Cost comparisons require equivalent output accounting; a
cheaper condition that fails to answer is not automatically more efficient.

## Failure taxonomy and ownership

Build the taxonomy from train evidence rather than forcing every failure into a
prewritten list. Start with these candidate categories:

- wrong field/entity or schema navigation;
- missing, mistranslated, or unretrieved business knowledge;
- HKB dependency resolution;
- join path or relationship;
- metric definition, aggregation, or grain;
- time window/calendar semantics;
- filter/value interpretation;
- JSON-path or type behavior;
- unsupported semantic-layer expression;
- query compilation/generated SQL;
- database execution/timeout;
- correct intent but incorrect compilation;
- question ambiguity or benchmark/data issue;
- harness, retrieval, authentication, or scorer infrastructure.

For each important class, record count, denominator, representative non-private
train examples, detection evidence, and primary ownership: model, semantic model,
harness, Omni product, database/environment, evaluator, or benchmark. Ownership
is a causal hypothesis and may change only with evidence. Product issues belong
in the append-only `docs/product-findings.md` ledger with severity, frequency,
minimal reproduction, expected/actual behavior, impact, suggested change, and
whether an experiment supports the remedy.

## Retry and infrastructure policy

The evaluated system's normal retry policy is part of the frozen system.
Exhausting it, returning no answer, producing invalid SQL, or timing out inside
the agent/harness is incorrect. A rate limit or 5xx is system-owned when the
frozen production boundary owns recovery from it.

A trial may be rerun only for a mechanically demonstrated failure outside the
evaluated system, such as sealed-evaluator process failure, benchmark database
unavailability, or transport failure before the evaluated service accepted the
request. Preserve the original attempt, append the rerun reason and evidence,
retain the same trial identity, and never inspect correctness before deciding.
Infrastructure ownership rules are frozen before generation.

## Reporting and reproducibility

The final report will separate:

1. public-only mechanical baseline;
2. train-supervised experiment history, including regressions and dead ends;
3. LOODO portability results on development data;
4. final frozen held-out primary result and explanatory condition matrix;
5. reliability, failure, cost, latency, product, and limitation analyses.

Every table must be derivable from preserved machine-readable artifacts. Record
public/private source hashes, split commit, freeze commit, evaluator commit,
database fingerprints, model/config identifiers, generation timestamps, and
analysis code revision. Never commit secrets, private gold, or raw generated data
that violates the custody contract.

## Preregistered limitations

- The primary result is unseen-question, not unseen-database, generalization.
- The final semantic system uses question-level supervision from 154 dev-A
  questions plus limited aggregate dev-B checkpoint feedback and is not
  zero-shot.
- Public benchmark exposure may affect model contamination despite the benchmark
  maintainers' design claim.
- A 101-question test has useful descriptive resolution but limited power for
  small paired differences and small subgroups.
- Soft EX is the benchmark metric, with known normalization blind spots; it is
  not complete semantic equivalence.
- When C4's underlying models cannot be matched, C4-C3 is confounded and remains
  a system-level comparison.
- Three repetitions characterize some stochastic instability but do not fully
  identify provider or temporal variance.
- Any mismatch between Omni's connected database and the scorer snapshot can
  invalidate correctness comparisons.
- Manual interpretive mappings and benchmark-specific exceptions weaken claims
  of automatic semantic-model scalability and must be counted.

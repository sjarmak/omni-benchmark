# LiveSQLBench Large-v1 evaluation protocol

Status: pre-gold preregistration, version 2 (Freeze A frozen by this commit).

This protocol governs the Omni evaluation on LiveSQLBench Large-v1. It was
written using only the benchmark's public questions, schemas, column meanings,
hierarchical knowledge bases (HKBs), and public evaluator code. No private gold
SQL, hidden knowledge annotations, or hidden test cases were available when the
split and this protocol were created.

## Research questions and estimands

The primary estimand is question-level generalization within a modeled database:

> Given an existing semantic model for a database, how accurately does Omni
> answer previously unseen analytical questions, and do semantic-model and
> harness improvements developed on other questions generalize to those unseen
> questions?

The unit of holdout is the analytical question, not the database or public
business knowledge. Public schemas and complete public HKBs for all 18 databases
are available during model construction. Database-specific semantic-model
changes may use that database's training outcomes.

A secondary leave-one-database-out analysis is confined to the development
partition. It estimates how well general HKB-to-Omni transformation rules transfer
to a database whose questions were excluded from rule development. It is not the
headline test.

## Eligibility and split

The public release contains 480 tasks. Eligibility is determined only by the
public `category` field:

- Include all 332 records where `category == "Query"`.
- Exclude all 148 records where `category == "Management"`.

The deterministic split contains 231 development questions and 101 held-out
questions. Every database appears in both partitions. Allocation is
database-first and preserves the public `high_level` distribution where feasible
without constructing sparse, question-determining strata. Other public condition
fields are reported, not optimized after membership is selected.

The committed split artifacts record the source revision, source SHA-256, split
seed, algorithm version, record IDs, and subgroup counts. Train and test IDs are
disjoint and exhaustive over the eligible manifest.

The 231-question development partition is deterministically divided, using a
second committed seed, into 154 optimization questions (`dev-A`) and 77 internal
validation questions (`dev-B`). The internal allocation again balances
`selected_database` first and public `high_level` second, then audits public
`conditions` marginals, especially `order`. `dev-A` and `dev-B` are disjoint and
exhaust the 231 development IDs. `difficulty_tier` is not used because it is not
present in the pinned Large-v1 rows.

Autoresearch may repeatedly observe and score only `dev-A`. `dev-B` outcomes are
available only through explicit, counted checkpoint evaluations. The intended
total is five to ten meaningful `dev-B` checks over the project; ten is a hard
maximum under protocol version 2. Membership is never changed in response to
checkpoint results.

## Information tiers

| Information | Development use | Runtime use | Held-out development |
| --- | --- | --- | --- |
| Public schema, HKB, column meanings, and questions | Allowed | Allowed | Frozen |
| Hidden dev-A SQL, test cases, and knowledge IDs | Offline supervision only | Prohibited | Frozen |
| Hidden dev-B SQL, test cases, and knowledge IDs | Guardian only; signed aggregate checkpoint outcomes enter development | Prohibited | Frozen |
| Hidden test SQL, test cases, and knowledge IDs | Prohibited | Prohibited | Sealed evaluator only |

The core rule is: hidden training annotations may influence how a reusable system
is built, but may never become question-specific runtime inputs.

Dev-A `external_knowledge` IDs are privileged diagnostic-oracle metadata. They
may be used after a prediction to test whether required public HKB nodes were
represented, whether dependencies compiled, and whether the system could reach
them. They may not select runtime context. Gold SQL and test cases may score and
diagnose dev-A failures, but may not be injected into the evaluated question.
Question-level dev-B labels and annotations never enter development.

Question-ID rules, hidden-ID retrieval hints, and question-specific gold-derived
transformations are prohibited. Semantic changes must be reusable definitions,
database-level modeling, transformation rules, or general harness behavior.

If sample queries are evaluated, each must encode a reusable pattern rather than
a benchmark question-to-gold pair. Each addition requires an experiment entry,
rationale, provenance, and count. Material use requires an ablation.

## Gold custody

The complete private attachment remains under human custody outside the repository
and outside the agent-accessible workspace. Its SHA-256 is computed without
displaying or parsing its contents and is recorded as provenance.

After the split commit exists, a deterministic user-run extraction step may read
the private source and emit only the 154 dev-A records into
`data/private/dev-a/`, which is ignored by git. The extractor verifies the
canonical `dev_a_ids.txt` and its development-split metadata against the Freeze A
commit. Development tooling must not accept a complete private file and must
reject records outside the committed dev-A IDs. Logs may contain IDs, hashes,
counts, status codes, and aggregate scores; they must not contain hidden SQL,
hidden knowledge IDs, or test-case bodies.

Dev-B checkpoint correctness stays behind a separate guardian boundary. The
guardian signs aggregate receipts with a private key outside agent scope. The
corresponding public-key SHA-256 is part of the Freeze-A-protected autoresearch
configuration and cannot be supplied or changed by a checkpoint caller. Receipt
IDs, receipt hashes, and output hashes are single-use. Each consumption is
recorded in both an immutable checkpoint manifest and a numbered allocation
marker. Before another dev-B checkpoint, those records must agree byte-for-byte
and be present in the current git commit. The externally recorded commit hash is
the rollback anchor; deleting or editing either local record fails closed.

Before Freeze A, the human custodian creates an RSA signing key on a host or
storage location not mounted into any agent environment and sends development
only the lowercase SHA-256 of the PEM public-key bytes. Run the following in that
external shell; `guardian_dir` is a real directory in the custodian's home, not a
literal placeholder path:

```bash
guardian_dir="$HOME/omni-benchmark-guardian"
umask 077
install -d -m 700 "$guardian_dir"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -out "$guardian_dir/private.pem"
openssl pkey -in "$guardian_dir/private.pem" -pubout \
  -out "$guardian_dir/public.pem"
sha256sum "$guardian_dir/public.pem"
```

Only the final digest replaces `UNPROVISIONED` in
`config/autoresearch.json`. The private key and its containing path are never
entered into an agent prompt, repository file, shell transcript available to an
agent, or development environment.

The untouched private source never enters the normal workspace, including after
the final evaluation. A dedicated sealed evaluator receives it only after the
system freeze, selects the 101 committed test IDs internally, executes scoring,
and emits permitted outcomes and aggregate diagnostics without emitting gold
content.

If the delivered attachment format differs from the official public integration
contract, a format adapter may be added after the split commit. That adapter may
be validated structurally under human custody; it may not reveal held-out fields
to development.

## Baseline and supervised development

Before hidden training annotations are released, preserve a public-only baseline:

1. deterministically transform public schema, column meanings, and HKB into Omni;
2. validate the resulting model structurally;
3. freeze the mechanical transformation revision and semantic-model artifacts;
4. generate baseline outputs on the 231 public training questions;
5. only then release dev-A annotations and request the first sealed dev-B
   aggregate checkpoint for scoring.

This separates initial transformation quality from improvement obtained through
supervised development. The final system receives question-level supervision
from 154 dev-A questions and a limited number of aggregate dev-B checkpoint
outcomes spanning the other 77; it must not be described as zero-shot.

> **Post-Freeze-A amendment, 2026-08-29.** The supervised development phase was
> cut before it ran. No dev-A-supervised intervention is promoted and no dev-B
> checkpoint is consumed, so the sentence above no longer describes the executed
> study. The final system is the frozen mechanical baseline transformation plus
> general compiler corrections whose content provenance is public schema and
> whose intervention provenance is generic product improvement. Dev-A outcomes
> were used for diagnosis and reporting only and never modified a runtime
> artifact; the two provenance axes below make that checkable. The executed
> system therefore receives no question-level supervision. Reason, and the
> reason it cannot bias the primary contrast, are recorded in
> [`docs/protocol-diff.md`](docs/protocol-diff.md).

The baseline is generated once across all 231 development questions before any
hidden label is released or scored. Its dev-A outputs are scored locally after
the dev-A-only release; its dev-B outputs are scored by the guardian and return
only a signed aggregate checkpoint receipt. Routine adaptive optimization uses
only `dev-A`; `dev-B` is consulted only at registered checkpoints. The
public-only baseline may not be regenerated retrospectively.

## Semantic-model and intervention provenance

Every meaningful modeled object and intervention preserves two independent
provenance axes.

**Content provenance** records the information represented: public schema,
public column metadata, public HKB, development gold SQL, development gold
result, development `external_knowledge`, or human/general modeling inference.

**Intervention provenance** records why and how the object changed: mechanical
baseline transformation, `dev-A` failure, hidden knowledge-coverage diagnosis,
post-run development-gold inspection, generic product/modeling improvement, or
manual database-level refinement.

These axes are not collapsed. If a `dev-A` failure reveals that a public HKB
definition was transformed incorrectly, its content provenance remains `HKB`
while its intervention provenance is `train-supervised diagnosis`. Provenance is
included in semantic manifests, experiment decisions, checkpoints, and final
artifacts. Hidden content itself is never copied into a runtime artifact.

## Frozen conditions

All four conditions are reasonably developed on training data, frozen together,
and evaluated in the same sealed event.

| Condition | Knowledge | Representation | Enforcement |
| --- | --- | --- | --- |
| C1 Raw SQL | Public schema | Raw schema | None |
| C2 HKB-reference SQL | Public schema and HKB | Searchable raw HKB | Optional |
| C3 Omni-model SQL | Public schema and HKB | Searchable exported Omni semantic model | Optional |
| C4 Governed Omni | Public schema and HKB | Omni semantic model | Enforced production harness (governs surface and field resolution; see `docs/c4-query-path-disclosure.md` for the measured query path) |

C2 and C3 receive reasonable, comparable programmatic search access. Neither is
required to ingest a complete large export in one prompt. C1-C3 use one pinned
direct-SQL model and harness. They match question wording, database, execution
access, budgets, retries, and scorer.

C4 uses the production-default Omni configuration. Production fidelity outranks
forcing model parity. If the exact C4 model or models can be observed and invoked
independently, C1-C3 match them. Otherwise, provider, observable model tiers and
IDs, reasoning settings, and retries are recorded and the interpretation is
conservative:

- with model parity, C4-C3 is an approximate architectural contrast, subject to
  remaining system differences;
- without model parity, C4-C3 is only a production-system comparison and must not
  be called the causal effect of enforcement.

Measured on the frozen development baseline, C4's governed queries were composed
as SQL by the production agent through the product's rewrite path over a model
declaring no joins and no measures. C4-C3 therefore does not separate a compiled
query path from a direct-SQL one, and model parity does not restore that
separation. It separates two agent-authored SQL conditions differing in agent,
SQL dialect, accessible surface, and execution contract. See
`docs/c4-query-path-disclosure.md`.

C2-C1 and C3-C2 remain the controlled direct-agent contrasts. C2 is a
substantive condition, not merely a bridge: business semantics supplied as
searchable context may account for a material part of the total C4-C1 gap.
Semantic-context evidence informs C2-C1 only; it is not evidence for C3-C2.

Pre-treatment resources are matched where meaningful: database snapshot,
credentials/permissions, public information, task specification, model identity
when possible, reasoning/token ceilings, and retry ceilings. Post-treatment
behavior—actual tool calls, tokens consumed, latency, and SQL-query count—is not
artificially equalized; it is measured as an outcome.

All conditions receive reasonable development rather than leaving C1-C3 as
straw comparators. Per condition, record prompt revisions, training evaluations,
major interventions, approximate human/agent effort, and the actor or automation
that performed the work. Exact equal person-hours are not required.

## Endpoints and prespecified contrasts

Two primary perspectives are declared before Freeze A:

- **Product performance:** C4 one-shot success probability, estimated by mean
  execution accuracy across all three independent sealed repetitions. Report a
  question-clustered interval and report C4 repetition-one accuracy separately
  for intuitive production interpretation. No voting or selection occurs.
- **Comparative performance:** the paired C4 - C1 execution-accuracy difference
  on the same sealed question-repetition trials, with questions as the clustering
  unit. This is a system-level contrast between reasonably developed systems.

The rung contrasts C2 - C1, C3 - C2, and C4 - C3 are prespecified exploratory
mechanistic evidence. Report paired deltas, discordant transitions, and
uncertainty, but do not promote modest differences based on significance. If C3
and C4 lack model/system parity, C4 - C3 is explicitly a system-level comparison,
not an isolated causal estimate of enforcement.

Intervals are fixed at 95% and use 10,000 question-clustered percentile bootstrap
replicates. Each sampled question retains all three repetitions and the paired
conditions required by the estimator. Sampling uses the committed
`sha256_modulo_question_count_v1` algorithm and seed
`omni-livesqlbench-large-v1-analysis-v1`; nearest-rank 2.5th and 97.5th
percentiles form the interval. Questions are sorted by `instance_id`; each draw
hashes the UTF-8 seed, a NUL byte, the zero-based replicate as unpadded ASCII, a
NUL byte, and the zero-based draw as unpadded ASCII. The full SHA-256 is an
unsigned big-endian integer modulo the question count. Nearest rank is
`sorted[max(0, ceil(p * 10000) - 1)]`. Repetition-one exact two-sided McNemar
tests are reported only as sensitivity analyses. `C4-C1` is unadjusted; Holm
correction at familywise alpha 0.05 applies to the exploratory family `C2-C1`,
`C3-C2`, and `C4-C3`. The executable configuration is
`config/preregistration.json`.

Every scored attempt has exactly one operational outcome: `correct`,
`wrong_answer`, or `refused_or_error`; the immutable pre-score generation record
separately records `answered`, `refused`, or `errored`. Execution accuracy remains
the benchmark metric, while
wrong-answer and refusal/error rates are reported separately. A confident wrong
answer and a safe failure-to-answer both miss the benchmark, but are not treated
as operationally equivalent in interpretation.

## Repetitions and reliability

Each condition runs three independent repetitions on every test question, for
1,212 frozen outputs. Mean one-shot accuracy across all three repetitions is the
product-performance endpoint; repetition one is also reported as the intuitive
single-invocation view. There is no majority vote or best-of-three score.

All outputs are generated before any output is scored against test gold. Trial
order is a committed deterministic block-interleaved permutation over question,
condition, and repetition, with repetitions of one question separated. Each trial
records timestamps and observable model identifiers.

## Telemetry and scaffold disclosure

Every attempt follows the normalized generation/score contract in
`docs/harness-disclosure.md`. Where observable, capture input/output/total
tokens, provider/model/version, cost, tool and database-query counts, wall-clock
duration, retries, validation attempts, generation outcome, terminal failure
origin/class, generated query, semantic objects, and compiler/validation/
execution trace references. Missing telemetry is null with a declared source or
degraded reason, never zero by default.

These are co-outcomes. Conditions receive matched pre-run resources where
meaningful, but actual tokens, calls, queries, retries, latency, and cost are
measured rather than equalized. Each major intervention reports whether it
increased correctness, reduced confident errors, converted wrong answers into
refusals, or only shifted the failure mode. A flat accuracy result can therefore
remain product-relevant.

No protocol claim assumes that scaffold effects dominate accuracy. Condition
results are conditional on the disclosed harness. Unless C3/C4 truly isolate
enforcement with model parity, C4-C3 remains scaffold-conditional and
system-level; effects may appear in error type, cost, retries, or reliability
rather than aggregate accuracy.

The three-run reliability analysis reports:

- mean one-shot and per-run accuracy, including repetition one;
- question-level 3/3 (`pass^3`), 2/3, 1/3, and 0/3 correctness;
- correctness flips separately from result-set changes;
- refusal/error rate and refusal/error stability;
- latency and cost distributions;
- question-clustered bootstrap confidence intervals.

SQL-text variation is diagnostic only. Identical wrong answers are stable but
incorrect; different SQL producing the same correct result is result-reliable.

## Frozen scoring policies and sensitivity analyses

Two versioned scorers are frozen before gold-driven development. The official
result is LiveSQLBench-compatible Soft EX pinned to public evaluator commit
`e15cd221267e06fabfaf6a3d4a69308280ce9a7c`. Its published behavior includes SQL
rewrites for comments, standalone `DISTINCT`, and `ROUND`; two-decimal result
normalization; ordered-list comparison when `conditions.order` is true; set
comparison otherwise; and failure when either result is empty. These behaviors
are reproduced for benchmark comparability even where they are lossy.

A separately named corrected sensitivity scorer uses unordered multisets rather
than sets, preserves duplicate rows, honors public decimal metadata, treats two
empty results as equal, defines null normalization, respects ordered tasks, and
does not silently erase `DISTINCT`/`ROUND` semantics. Both scores are reported;
neither is selected after observing results. Pure result comparison and SQL
execution/rewrite behavior are versioned separately and must pass public
conformance fixtures before Freeze B.

After final scoring, a sealed post-hoc audit normalizes development and test gold
SQL into structural templates, reports overlap prevalence, and—if sample size
permits—reports test accuracy on non-overlapping templates. This audit cannot
change the split, primary result, or development system.

Suspicious or condition-discordant items may enter a preregistered post-freeze
gold-quality adjudication. Condition identity is blinded where practical. The
original official score remains intact; any adjudicated result is labeled a
separate sensitivity analysis and never silently replaces benchmark truth.

## Official HKB-access protocol

The public LiveSQLBench-Agent exposes database-level tools to list all external
knowledge names, retrieve a named definition, or retrieve all definitions. Its
public agent instruction tells the model to discover relevant knowledge; it does
not pass hidden question-specific `external_knowledge` IDs as oracle hints. Our
default C2-C4 access policy matches that distinction: database-level HKB is
available, hidden ID selection is not. Any later official-leaderboard comparator
is reported separately and cannot alter the primary experiment.

## Failure and rerun policy

The evaluated system's normal production retry policy is frozen. Exhausting it,
returning no answer, generating invalid SQL, or timing out inside the agent or
harness counts as an incorrect system outcome.

A trial may be rerun only when failure is demonstrably outside the evaluated
system, such as sealed-evaluator process failure, benchmark database unavailability,
or network failure before the evaluated service accepted the request. A rerun
keeps the same trial identity and appends a reason and both attempt records. Rate
limits, 5xx responses, and timeouts are classified in advance according to which
system owns the retry boundary; they are not reclassified after scoring.

## Freeze A, Freeze B, and final scoring

**Freeze A (pre-gold protocol freeze)** commits the eligible population, outer
231/101 split, internal 154/77 split, custody/information rules, C1-C4 definitions,
both scoring policies, repetition/order/failure rules, endpoints/statistics,
unblinding/adjudication policies, ledger schema, and dev-B guardian public-key
pin. Its commit hash is recorded before any hidden development label is released.
Freeze A intentionally does not freeze the final system.

Recording uses two commits to avoid a self-referential hash. Commit A contains
the complete frozen protocol and real guardian digest. Commit B adds only
`experiments/freeze-a.json`, whose exact schema is: `schema_version` = 1,
`kind` = `freeze-a-record`, full lowercase `freeze_a_commit`, RFC3339 UTC
`recorded_at`, `guardian_public_key_sha256`, and SHA-256 values for
`eligible_questions.jsonl`, `split_metadata.json`,
`development_split_metadata.json`, `config/preregistration.json`, and
`EVALUATION_PROTOCOL.md` as stored in Commit A. Commit B is completed before any
hidden development label is released. The metadata file is intentionally absent
until Commit A exists; a placeholder hash is prohibited.

**Freeze B (pre-test system freeze)** occurs after all `dev-A` optimization and
permitted `dev-B` checkpoints, but before test generation or scoring. It commits
and hashes:

- semantic models and HKB transformation code;
- all four harness configurations and prompts;
- topic/retrieval configuration and allowed tools;
- model/provider information and budgets;
- retry and failure-classification policy;
- database snapshot identifiers;
- trial schedule and evaluator version.

The Freeze B manifest records the git commit. All 1,212 generations then complete,
followed by sealed scoring. No held-out result may feed a semantic-model, harness,
prompt, retrieval, or retry change. An invalidated run may be repeated only for a
predefined infrastructure reason, which is documented before replacement.

## Train-only autoresearch extension

The optimization workflow in
[`docs/autoresearch.md`](docs/autoresearch.md) operationalizes evaluation-driven
development without changing this protocol's estimand, information tiers, custody
boundary, endpoints, or freeze rule. It adds an immutable baseline, a
proposal-before-change experiment lifecycle, exact-dev-A acceptance gates,
append-only decisions, checkpoint provenance, a question-ID guard, and an
irreversible development stop state.

Autoresearch has routine access only to public `dev-A` questions and separately
loaded `dev-A` outcomes. Hidden development annotations remain offline diagnostic
inputs and are never placed in a runtime request or ordinary run artifact. A
`KEEP` decision requires a complete 154-question `dev-A` evaluation and an
explicit generality/regression/complexity rationale; aggregate accuracy alone is
insufficient. `dev-B` is available only through immutable, counted checkpoint
events, never after every intervention. Once a final candidate is selected and
the four conditions reach Freeze B, autoresearch terminates before any held-out
generation is scored.

> **Post-Freeze-A amendment, 2026-08-29.** This extension was never executed.
> The optimization phase is cut from the study: E01 was audited and found already
> present in the baseline (inconclusive), E02 was compiled and hash-bound but
> never evaluated, no experiment reached a KEEP or REVERT decision, no checkpoint
> was consumed, and the final candidate is the baseline. The section is retained
> as the preregistered design so the deviation is legible against it.

Optimization is evaluation-driven system improvement, not scalar hill climbing.
Each experiment declares a textual, structural, or human/research-controlled
surface, records a mechanism hypothesis, consumes rich sanitized traces, checks
an append-only dev-A regression suite, and retains branch/Pareto provenance when
tradeoffs are non-dominated. Protocol, split, custody, endpoint, scorer, and
supervision-legitimacy decisions remain human-controlled regardless of scores.

The machine-readable ledger supports quantitative analysis. The append-only
`docs/research-log.md` separately records observations, beliefs, alternatives,
results, interpretation, and product implications while context is fresh.
`docs/failure-taxonomy.md` is updated at baselines/checkpoints with category
prevalence and the top three remaining mechanisms; `docs/product-findings.md`
captures customer-relevant behavior as soon as evidence exists. Framework names
are implementation details, not the final research narrative.

## Provenance

Public dataset: <https://huggingface.co/datasets/birdsql/livesqlbench-large-v1>

Official benchmark harness: <https://github.com/bird-bench/livesqlbench>

Omni comparison motivating the ablation:
<https://omni.co/blog/benchmarking-omnis-agentic-analytics-harness>

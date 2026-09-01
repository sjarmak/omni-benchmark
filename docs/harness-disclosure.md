# Harness and scaffold disclosure

Status: frozen for Freeze A. The sentences below are the state as recorded at
freeze time, including "no scaled baseline has been launched and no private label
has been accessed" and the treatment of unknown values as blockers for the
condition-specific telemetry smoke test rather than values to infer or fill
retrospectively. Scaled generation has since run to completion. Statements
falsified by later measurement are marked in place and answered in the addenda at
the end of this document; the frozen text itself is not rewritten. No private
label has been accessed at any point.

Freeze A remains the historical protocol state recorded at commit
`7d39ee107338da1ce10e2553a4290e64bfc2f892` (metadata record commit
`7720cc4da3369484f5076422147822efba76d387`). Later human-directed protocol
amendments, including the AI Hub diagnostic boundary below, are prospective
addenda and do not rewrite that historical commit.

Measured results are conditional on these evaluated harnesses. Published
controlled studies do not support assuming either that scaffold effects are
negligible or that they dominate model effects across tasks. Accordingly,
`C4-C3` is a scaffold-conditional/system-level comparison unless the final
implementations actually isolate governed enforcement with model parity.

## Condition disclosure

| Property | C1 raw-schema SQL | C2 HKB-reference SQL | C3 Omni-model-reference SQL | C4 governed Omni |
| --- | --- | --- | --- | --- |
| Intended role | Competent direct-SQL baseline | Direct SQL with searchable business knowledge | Direct SQL with searchable structured semantic model | Production-default governed product |
| Provider/model/version | Claude Code adapter 2.1.250 through `anthropic_claude_code_oauth`, requesting `claude-opus-5`; all 267 sealed attempts realized that one identity | Same as C1 | Same as C1 | Managed production selection. Across the 267 sealed attempts, 264 realized Bedrock `claude-opus-5`, one a `claude-opus-5`/`claude-sonnet-5` composite, and two `managed-unobservable`. No arm reports a model version, so weight-level parity between runs is unverifiable (PF-015) |
| System instructions | Operative provider system prompt is code-bound; committed `direct-sql-v1.json` is non-operative policy metadata | Same operative provider prompt and condition-specific tool schema | Same operative provider prompt and condition-specific tool schema | Production agent instructions; export only if observable and permitted |
| Available tools | Schema discovery, database query/execute, bounded error recovery | C1 plus database-level HKB search/get | C1 plus exported semantic-model search/get | Production Omni agent tools and governed query workflow |
| Knowledge at runtime | Public schema/column metadata | Public schema plus database-level HKB; no hidden knowledge IDs | Public schema plus Omni model derived from public schema/HKB; no hidden knowledge IDs | Same public knowledge encoded in the governed model; no hidden knowledge IDs |
| Retrieval/context | Query-directed search over committed public tables/columns/relationships; maximum four tables and 64 KiB per result | Same bounded schema search plus public HKB search via unweighted SQLite FTS5 BM25 with canonical-order ties; neither is a whole-file prompt dump | Same bounded schema search plus the same retrieval algorithm over the searchable Omni semantic export | Production Omni discovery behavior |
| Database access | Direct read-only benchmark database | Same | Same | Through Omni connection/governed query path |
| Planning/orchestration | Direct agent, frozen after train-only tuning | Same base harness | Same base harness | Production composite workflow; stages disclosed when observable |
| Retry behavior | Harness retry ceiling 0; provider-internal retry events are observed in the trace when exposed | Same | Same | Production-default retries; observed rather than artificially matched after treatment |
| Compiler/query path | Agent emits SQL | Agent emits SQL | Agent emits SQL | Omni's production agent emits SQL through the product's raw-SQL rewrite path. All 135 development-baseline semantic queries carry `rewriteSql: true` with agent-authored SQL in `userEditedSQL`; none declares a join path. The SQL is written in Omni's `${view.field}` reference syntax over compiled views and resolved by Omni against the deployed model. `generated_sql` is recorded as `null` by design; the executed SQL is the semantic query's `userEditedSQL` |
| Validation | Database execution/error handling only | Same | Same | Production validation behavior included |
| Token/time ceilings | Claude Code 2.1.250 exposes no supported input/output-token ceiling; each turn is limited to 120 seconds, USD 1 provider cost, and 12 total turns | Same | Same | Production defaults where immutable; disclose any mismatch |
| Current implementation state | Public context, pinned provider, attested PostgreSQL, bounded retrieval, capture, publisher, committed database bindings, and executable driver pass synthetic/adversarial tests and an exact-commit authenticated smoke | Same, including live searchable public HKB and dependency-closure provenance | Same, including live searchable exported-model objects | Isolated public archeology model validation, 14/14 semantic readback, governed query execution, and AI Hub diagnostic inspection pass; the exact-commit capture rerun preserved full telemetry on its deliberately unscoreable truncated result; scorer-type parity remains pending (superseded 2026-08-31, see [Addendum: result-type parity is closed](#addendum-2026-08-31-result-type-parity-is-closed)) |

Exact prompts, tool manifests, model identifiers, configuration hashes, retry
ceilings, and version fingerprints are Freeze B artifacts. C1-C3 must be made
reasonably competent, but perfect laboratory parity must not block the primary
C4 research work.

### Governed query path, measured (disclosure addendum, 2026-08-30)

This section and the C4 "Compiler/query path" cell above are a post-Freeze-B
disclosure correction. The previous cell read "Semantic query/objects compiled
through Omni; generated SQL captured only if exposed", and both halves are
falsified by measurement on the frozen development baseline. Nothing measured
changes; the description of what was measured does. The corresponding deviation
record is in [`protocol-diff.md`](protocol-diff.md).

The C4 condition is labeled `"semantic_enforcement": "governed"`. That label
describes name resolution and the accessible surface, not query compilation.
Every governed query in the frozen development baseline was composed as SQL by
Omni's own agent and rewritten by the product: all 135 semantic queries carry
`rewriteSql: true` and `aiGenerated: true`, and `join_via_map` is empty on all
135.

**The rewrite path is Omni's choice, not a harness setting.** The benchmark
cannot select it, request it, or suppress it. `OmniCliClient.submit_job`
(`src/omni_benchmark/omni_cli.py:193-208`) posts a body of exactly four keys:
`modelId`, `progressWebhookEnabled: false`, `prompt`, and `branchId`. The prompt
is `config/prompts/c4-user-prompt-v1.txt`, the single token `{question}`. There
is no mode flag, no path selector, and no SQL hint. The strings `rewriteSql`,
`userEditedSQL`, `join_via_map`, and `aiGenerated` appear nowhere under `src/`;
they occur only in offline analyzers that read those fields back out of Omni's
response. `config/instructions/c4-managed-instructions-v1.json` records
`"managed_agent_instructions": "not_exposed_by_omni"`, so the benchmark neither
supplies nor observes the agent's operative instructions. The harness passes
Omni's returned query object back verbatim: `parse_omni_job_result`
(`src/omni_benchmark/omni_result_adapter.py:78-100`) lifts the `query` object off
the job's `generate_query` action and `omni_capture.py:221-229` replays that same
object, with the only mutation being the `modelId` set by `_query_with_model`.

**No non-rewrite path was available for cross-table access.**
`_topic_document` (`src/omni_benchmark/semantic_bundle.py:630-645`) emits
`"joins": {}` on every deployed topic, the deployed baseline carries
`joins_generated: False`, and the bundles publish dimensions with no measures. A
query compiled from the declared model can therefore neither traverse a join path
nor compile an aggregate from a declared measure. For the 62 of 133 parseable
attempts that reference two or more distinct non-CTE sources, rewrite was the
only path the deployed model left open. The 71 remaining parseable single-source
attempts took it as well, which the artifacts held cannot explain and which is a
product-internal decision the benchmark cannot observe.

**What the semantic layer did contribute.** It supplied a resolved field
vocabulary rather than a compiled query. Of 135 attempts, 134 use `${...}`
reference syntax, 126 name a compiled view identifier, 109 reference at least one
compiled dimension, and 39 reference at least one HKB-backed derived dimension
that Omni expands at rewrite time. On the output side the picture inverts: of 518
selected field references, 75 are compiled bundle fields, 97 attempts select no
compiled field at all, and 0 attempts select exclusively compiled fields. The
model is used heavily on the way in and barely at all on the way out. That
asymmetry left the planner with output columns the deployed model does not
define, and it is consistent with all 31 `UNKNOWN`-type terminal failures.

The same configuration, prompt, and model deployment are hash-bound into the
sealed arm (`sealed_omni_factory.py:33-35`,
`config/sealed-omni-semantic-model-set-v1.json`), so the sealed arm is expected
to show the same path. That is a prediction from committed configuration; the
sealed records have not been read. Full measurement, evidence boundary, and
consequences for interpretation are in
[`c4-query-path-disclosure.md`](c4-query-path-disclosure.md) and
[`c4-mechanism-measurements.md`](c4-mechanism-measurements.md).

### C5 removes the "no compiled path existed" explanation (addendum, 2026-08-31)

The paragraph above says rewrite was the only path the deployed model left open
for cross-table access, because every C4 topic carried `"joins": {}`. C5 removes
that explanation. It runs under the same C4 condition scaffold, the same prompt,
and the same four-key job body, but deploys a view for every public table and a
join for every foreign key that passes the conservative cardinality contract, so
a compiled cross-table path existed on most topics.

The rewrite rate did not move. All 134 parseable C5 attempts carry `rewriteSql`,
none declares a join through the model, and `join_via_map` is empty on all 134.
Counted across six governed arms (three sealed C4 repetitions, dev-A C4, E02, and
C5), the total is 661 of 661 parseable attempts on the rewrite path and zero
composed:
[`../experiments/analysis/governed-query-path-tally-v1.json`](../experiments/analysis/governed-query-path-tally-v1.json),
regenerable from
[`../experiments/analysis/governed_query_path_tally.py`](../experiments/analysis/governed_query_path_tally.py).

So the narrow reading, that the product compiles when the model supports it, no
longer fits the join case. What remains open is the measure case: C5 phase 1
publishes no measures, so an aggregate question still has no compiled
expression. Separating that from an unconditional rewrite is the phase-2
question tracked in bead `omni-benchmark-w5x` and recorded as
[PF-016](product-findings.md). C5's accuracy rose while the path stayed fixed,
which is the evidence that the semantic model contributed vocabulary and context
rather than composition.

For C1-C3, `config/instructions/direct-sql-v1.json` is validated and hash-bound
as fixed policy metadata, but its `adapter_instruction` text is not sent to the
model. The operative instructions are the provider adapter's code-bound system
prompt plus the condition-specific tool schemas. The only runtime user message
is the exact committed public question. This distinction prevents the metadata
hash from being misreported as an evaluated prompt treatment.

C1-C3 use the same query-directed schema-retrieval scaffold. The model chooses
each query; no hidden annotation selects context. Schema search ranks complete
committed public table records and returns at most four tables and 64 KiB,
shrinking deterministically with no complete-schema fallback. C2 and C3 add
condition-specific knowledge retrieval through the same mechanical search
primitive. The adapter indexes the condition's committed public records in an
in-memory SQLite FTS5 table, uses the built-in unweighted BM25 rank, and breaks
equal ranks by canonical input order.
This is a narrow deterministic-ranking exception: it replaces the earlier
hand-weighted phrase heuristic without introducing semantic policy in the
harness. C2 tool results expose selected direct and dependency-closure IDs in
`retrieved_hkb_stable_ids` as public provenance. The normalized
`semantic_objects` field remains C3-only; C2 IDs remain public HKB provenance
rather than being relabeled as semantic-model objects.

Each development run is required to have one exact-schema private `run.json`
binding the immutable generation SHA, harness/config and prompt/instruction SHAs,
git commit, condition, scope, repetition/seed, software and CLI versions,
model/provider identifiers, explicit semantic-model branch/revision identity,
an exported semantic-model content hash when available, budgets, and timestamps.
The schema keeps managed LLM identity distinct from Omni semantic-model identity;
an opaque production model is recorded as opaque rather than mislabeled with the
semantic model ID. The reader rejects non-development scopes, noncanonical
content, unknown fields, secrets, and unsafe files. Generation validation,
experiment decisions, checkpoints, the four-condition smoke gate, and the C4
contract probe require or emit this binding. A smoke gate accepts four separate
condition bundles so a manifest can never ambiguously describe a mixed-condition
generation file.

The semantic-model content hash may be null for the pre-auth contract smoke,
where the claim is limited to exercising a named model or branch. It is mandatory
at Freeze B: C3/C4 final runs must bind either a content-addressed model export or
an immutable Omni revision. A mutable branch identifier is not treated as model
content identity.

Correctness lives in a separate minimal score artifact bound to both the
generation-file SHA and every attempt record SHA; it cannot copy or alter the
prompt, query, result, or telemetry. The Freeze A configuration requires this
separation in experiment decisions and checkpoints; inline scored generation
records are a legacy test fixture path, not an allowed production workflow.

## Per-attempt telemetry contract

The normalized generation envelope is immutable and contains no correctness
before scoring. It records:

- run/attempt ID, condition, repetition, partition, start/end timestamps;
- provider/model/version, token counts and their source, cost and its source;
- wall-clock latency, tool calls, database queries, retries, and validation
  attempts;
- generation outcome (`answered`, `refused`, or `errored`), terminal failure
  origin/class, generated SQL/query, semantic objects, and fixed compiler,
  validation, and execution statuses;
- a relative path, schema version, and SHA-256 for the ordered raw trace, or an
  explicit degraded reason when trace capture is unavailable.

Unobserved counts are `null` and must be named in `telemetry_unavailable`; they
are never encoded as zero. Token values declare `provider_reported`, `derived`,
or `unavailable`; cost values declare those three or `credit_usage_delta`, the
bracketed measurement described in the 2026-08-31 cost addendum below. Scoring produces a separate
record with `correct`, `wrong_answer`, or `refused_or_error`; it does not mutate
the generation record. Raw traces and generated SQL live only under ignored
run roots. Committed artifacts contain hashes and permitted summaries.

The official `refused_or_error` score remains available for benchmark
compatibility, but analysis does not use it as the only non-answer summary.
Validated runs retain separate raw `refused` and `errored` ID sets, counts,
rates, and experiment-to-experiment transitions. C1-C3 can emit both outcomes
from structured direct-agent events. The pinned C4 job contract currently has no
structured refusal state, so C4 records observable terminal/transport/contract
failures as errors and reports refusal observability as unavailable rather than
classifying prose heuristically.

Complete token reports contain non-null input/output/total counts that reconcile.
Attempt latency must match its start/end timestamps. Refused or errored attempts
carry a `failure_origin` and a terminal failure class. The origin is assigned by
rule, not determined from evidence: `_failure_ownership` in `omni_attempt.py`
labels `omni_job_terminal_failure` as `evaluated_system` and every other class as
`benchmark_infrastructure`. That rule is deliberately conservative, since it
never credits the evaluated system with a failure it might not own, but it means
the field records a policy rather than a diagnosis. Sealed C4 `failure_origin`
values are therefore `benchmark_infrastructure` for 36 of the 38 non-answers and
`evaluated_system` for the remaining 2. Anything finer, in particular whether an
`unsupported_semantic_result_type` reflects our closed type set or the governed
system's contract, has to be argued from the class and not read off this field.
See the bounded reanalysis in RESULTS.md §6, which computes every result under
both readings rather than resolving the question here. Complete, untruncated
`trace-event-v2` traces reconcile token, tool-call, database-query, retry, and
validation totals to the attempt envelope; truncated traces carry an explicit
degraded reason. A count remains null if the provider does not expose enough
event data to reconcile it.

The C1-C3 capture core owns tool dispatch rather than trusting provider-reported
tool totals. Each capture writes an immutable receipt binding the attempt ID,
question digest, condition, provider/model, maximum turns, generated-SQL digest,
trace, private action-evidence sidecar, result, and artifact-root identity. The
bounded sidecar retains each model-authored public retrieval query, the stable
schema, HKB, or semantic-object IDs actually returned when available, and every admitted
exploratory `execute_sql` statement. Record digests bind these actions to exact
trace sequence numbers. It excludes provider raw responses, result bodies,
credentials, and hidden annotations; final generated SQL remains in the
generation record. Publication revalidates those bindings, the condition-specific
capability surface, Query-only SQL admission, lifecycle, failure-specific
database-query deltas, strict finite and non-negative telemetry, and the
prospective run manifest before writing either `generation.jsonl` or `run.json`.
An attested direct database transport must prove read-only role state and lack of
non-system function-execution privileges before the first model turn.
The public-context, model-provider, and PostgreSQL adapters now pass synthetic
and adversarial contract tests. Direct database identity is assembled from the
exact committed format-v2 public inventory and an exact-coverage, credential-free
sidecar containing only logical name, physical database name, and a target
SHA-256. The sidecar is SHA-bound to the inventory bytes; the live transport
still independently reattests the role, physical database, server, schema,
content, and connection target. Live execution requires a clean commit containing
both artifacts and runtime credentials supplied outside the repository.

The production-agent contract probe uses the installed Omni CLI with argument
arrays and JSON stdin. The committed C4 specification pins both the exact CLI
version and executable SHA-256; the probe resolves PATH once, verifies that
owned non-writable executable, and reuses the resolved absolute path for version
observation and authenticated requests. It forwards only the minimum authentication environment,
projects provider responses into type/shape metadata, hashes the response bodies,
and writes private artifacts exclusively under ignored roots. It does not persist
identity responses, headers, cookies, or session state. It does persist the
selected analytical result as a normalized, hash-bound private sidecar because
execution scoring requires the actual row multiset.
Before constructing the authenticated client, it verifies the selected public
dev-A question and split artifacts byte-for-byte against the externally recorded
Freeze A commit. It also requires a clean tracked system revision and hashes the
committed harness, prompt, and instruction specifications before constructing
the client. Invalid run metadata therefore fails before an authenticated call.

The clean-worktree scan detects accidental tracked, untracked, or current-runtime
bytecode contamination. Because Python imports the probe before that scan runs,
it is not represented as a sandbox against a malicious local operator. The
evaluation threat model assumes a non-adversarial execution host and relies on
the committed system revision, exact run-spec blobs, binary hash, and immutable
artifacts for auditability. Frozen runs should be launched from a freshly
materialized committed tree or installed artifact to minimize pre-import drift.

The pinned Omni CLI's embedded production API contract exposes chronological
job actions. A `generate_query` action contains the executed semantic query,
CSV result, total row count, status, and truncation flag. The C4 adapter selects
the last successful query action only after validating every query action against
the required contract. The CSV is used for status, truncation, and row-count
integrity checks, not as the scoring value: CSV would erase number, boolean, and
null types. The adapter reruns the selected semantic query through Omni's query
endpoint with raw JSON results, formatting disabled, cache disabled, and the same
semantic-model branch, then preserves those JSON values without coercion in the
hash-bound result sidecar. It never guesses SQL from prose.

`response_contract_error` is broader than "unrecognized completed response". In
`omni_capture.py` it is the terminal class for any `OmniCaptureError` or
`OmniResultContractError` raised while capturing a job, and it is also the class
recorded when a provider response is rejected outright and replaced by a
`forbidden-provider-response` digest. So it covers a malformed or unexpected
result envelope, a capture-time failure to observe the job at all, and a response
refused on content grounds before it was read. All three end the attempt with no
answer and are recovery-eligible, but they are different events, and the class
alone does not say which one occurred. The four sealed C4 attempts carrying this
class have not been separated further, because doing so means reading per-attempt
capture material.

Raw JSON preserves JSON primitive distinctions in the envelope, but the first
live semantic canary showed that it does not necessarily preserve semantic field
types: with `formatResults:false`, a count measure was returned as a JSON string
while the grouping field remained a boolean. Dates and timestamps may also be
strings. The adapter does not heuristically coerce strings. Before scaled
execution, scorer parity must prove consistent predicted/gold normalization or
the capture path must adopt a result transport with authoritative field-type
metadata. This is now an observed scale blocker, not only a theoretical
limitation. (Superseded 2026-08-31: the capture path adopted the second option.
See [Addendum: result-type parity is
closed](#addendum-2026-08-31-result-type-parity-is-closed).)

The API exposes query actions clearly enough to count governed database queries.
The additional raw-JSON semantic-query replay is evaluator-side result transport:
its trace event and latency are retained, but it is excluded from the evaluated
system's `database_query_count`, just as scorer/gold execution is excluded.
Provider `queryCount` must be at least the number of structurally successful
`generate_query` actions or the count is rejected as contradictory.
It does not establish that every action is a model tool call or expose the full
production validation/retry internals. The first public AI Hub job did provide
authoritative job-level model/provider token buckets, tool-call and tool-error
counts, query count, and total/LLM/query durations. Those fields should now be
captured when present. Cost, retry count, and validation-attempt count remained
unavailable and must stay null. Reduced action-type counts remain diagnostic
response-shape metadata unless they reconcile to the job-level totals.

For composite C4 workflows, raw capture should preserve stage/component model
and usage where Omni exposes them. An aggregate model label must not be presented
as exact model parity when internal routing is opaque.

## Reference implementation audit

The local CodeScaleBench, EnterpriseBench, and codeprobe implementations were
reviewed for trace-capture patterns. Two patterns carry forward into condition
adapters: prefer the provider's authoritative terminal/stream usage source and
record that source explicitly; persist reduced, whitelisted action metadata and
hashes rather than raw response bodies. The current Omni schema is stronger for
this experiment because it reconciles unavailable telemetry, SQL/result
artifacts, and separately bound correctness labels.

A generalized incremental trace recorder is deferred. The current exclusive,
size-bounded JSONL writer is sufficient for the one-question smoke gate. If a
live condition produces long or streaming traces, adopt bounded incremental
append with a durable truncation marker before scaled execution. Do not copy raw
conversation/tool payloads into the benchmark artifacts merely to gain richer
traces.

## Capture verification gate

Before any 231-question baseline or expensive experiment:

1. Run one public unscored smoke attempt through each implemented condition.
2. Validate its normalized generation envelope.
3. Verify captured trace hashes and redaction, or record an explicit degraded
   reason for fields the product/provider does not expose.
4. Confirm system database-query counts exclude scorer/gold execution.
5. Confirm evaluated-system retries are distinct from benchmark-infrastructure
   reruns.
6. Record coverage by field and condition in this document.

Current gate result: **four-condition capture gate passed**. The bound
`archeology_scan_3` bundles used common run ID `archeology-vertical-v1`,
repetition one, and complete trace capture. C1-C3 ran at exact system commit
`50ebc31075f742fba4e7d4bbc6fc4da0b15d53ce`; all three answered and executed
against the attested read-only database. Their observed telemetry was:

| Condition | Total tokens | Cost (USD) | Latency (ms) | Tool calls | Database queries |
| --- | ---: | ---: | ---: | ---: | ---: |
| C1 | 33,445 | 0.214778 | 40,918.244 | 2 | 2 |
| C2 | 81,838 | 0.6084515 | 31,067.570 | 3 | 2 |
| C3 | 104,625 | 0.7275655 | 43,197.973 | 4 | 2 |

All three reported zero harness retries and zero validation attempts. The
exact-commit public C4 rerun at `dd8e7b1` preserved Bedrock
`claude-opus-5`, 247,676 input tokens, 1,110 output tokens, three tool calls, one
governed database query, and 29,338.859 ms latency while retaining the truncated
result as an unscored `response_contract_error`. Its generation SHA-256 is
`86814a6b5264cacc49d0ade910416b6521e4ab26f561819bfaa3701346914494` and its
trace SHA-256 is
`b9243d2a9f6e0d74d36b858282db79ee2fea482ee2b317f18826bd8d2ba4114d`.
The validated smoke bundle binds generation hashes
`45cd4c26df5fc57ee20aff267bca0e4c3e7238fc5278d024f5a58cb5d403be4e`,
`810a2d827d91b9deaa4ff5972bd50b534a094d9ab5e17352b9a0b2a08dfda23d`,
`f1c8ab9c97d5a15df5030ebc0661803aa274fe7123bca0bd8995b8af43bcc46c`,
and `86814a6b5264cacc49d0ade910416b6521e4ab26f561819bfaa3701346914494`
for C1-C4 respectively. Scorer/result-type parity remains a separate execution
gate; capture no longer blocks scaled public-only generation. (Superseded
2026-08-31: that gate is closed. See [Addendum: result-type parity is
closed](#addendum-2026-08-31-result-type-parity-is-closed).)

## AI Hub diagnostic boundary

For C4, Omni AI Hub is the preferred product-native surface for inspecting
sessions and running small branch comparisons when it provides useful signal.
It is not the correctness authority and does not replace external `dev-A`,
guardian-gated `dev-B`, or sealed test scoring. Preserve both AI Hub judge output
and LiveSQLBench execution outcomes when available; disagreement is a product
finding rather than a reason to overwrite either result. The live canary will
inventory AI Hub telemetry against the attempt contract before scaled runs. See
[`ai-hub-role.md`](ai-hub-role.md).

## Derived co-outcomes

Report accuracy, confidently-wrong rate, refusal/error rate, tokens per correct
answer, median/IQR tokens, median/IQR latency, tool calls per attempt/correct,
database queries per attempt/correct, retry/validation distributions, telemetry
coverage, and terminal failure vectors by condition. Operational numerators
include every valid attempt; comparative views use matched question-condition-
repetition populations. These are measured outcomes, not resource-equality
constraints.

For the public-only governed baseline, the executable product arm is the 129
train questions on the ten databases whose frozen C4 semantic deployment has
zero validator issues and exact attested readback. The separately committed
108-question, eight-database intersection is the paired C1--C4 analysis
population. C4 admits at most five concurrent database-condition blocks.
Wall-clock stopping is applied only at block boundaries: already-started
database/C4 blocks finish, while unstarted blocks remain resumable. Managed C4
dollar cost is recorded when observable but does not select or truncate the arm.

## Addendum 2026-08-31: result-type parity is closed

This addendum is prospective. The Freeze A text above is left as recorded, and
three of its statements are marked in place as superseded by this section: the
C4 "Current implementation state" cell, the "observed scale blocker" paragraph in
the reference-implementation audit, and the "separate execution gate" sentence in
the capture verification gate. No measured value, scorer version, artifact hash,
or protocol surface changes here; only the description of a gate that has since
closed.

**What closed it.** The typed result path landed on 2026-08-29 and takes Omni's
plan-only response as the sole type authority. `_planned_data_types`
(`src/omni_benchmark/omni_result_adapter.py`) requires a `PLANNED` status, empty
`missing_fields` and `invalid_calculations`, and exact ordered agreement between
the model job's fields and the semantic query's fields. `_typed_cell` converts
strictly by declared `data_type` and never infers a type from how a string looks,
which is what the live canary had shown to be unsafe: a count measure came back
as a JSON string while its grouping field stayed boolean. Typed cells persist in
the hash-bound sidecar and decode through `decode_result_artifact_rows` into
Python values that reach the same frozen normalizers as the Psycopg-typed gold
rows. Parity is therefore structural rather than asserted; the capture path
adopted a transport with authoritative field-type metadata, which is the second
of the two options the superseded paragraph named.

**Evidence it holds end to end.** C4 dev-A scoring completed over 154 scheduled
questions: 136 scoreable, 18 fixed unscorable, 9 correct, 93 wrong, 34 refused or
system error. The official artifact is SHA-256
`57d45346de0a98384207d350f163dfcf812e677cf3719b4a3008b5e0f3f222d8`; the
sensitivity artifact is
`af333cc78bde8827dfd5f6b092b5c319492ba7554c9c18ed40710ca26d6d4251`, reporting 9
correct, 93 wrong, and 33 refused or system error over 135 scoreable attempts.

**Unknown planner types fail closed, and that is a policy with a measured cost.**
`SUPPORTED_OMNI_RESULT_TYPES` is a closed set of seven: `BOOLEAN`, `DATE`,
`JSON`, `NUMBER`, `STRING`, `TIMESTAMP`, `YESNO`. Any other declared type raises
`OmniUnsupportedResultTypeError` and the attempt becomes an evaluated-system
failure rather than being coerced. On dev-A this is not free. Append-only
recovery v5 (manifest SHA-256
`5d6ff474f30d3de6d703ad5c6c59373fe8093515eabb83473bdb352c4f30fd9f`) replayed the
45 capture failures without regenerating any answer: 11 yielded typed results and
34 remained terminal. Of those 34, aggregate-only classification attributes 31 to
an unknown planner result type, 1 to a completed job with no parseable query, and
2 to a persistent plan rejection. Thirty-two of the 34 still carry parseable
governed SQL, so generation succeeded and the result contract failed downstream.
This depresses C4 accuracy by construction and is disclosed as a deliberate
fail-closed choice, not as an open gate.

## Addendum 2026-08-31: governed cost from bracketed credit usage

The pinned Omni job contract exposes no cost. Neither `ai job-status` nor `ai
job-result` carries one, so every governed attempt through the sealed C1-C4 run
recorded `cost_usd: null`, `cost_source: "unavailable"`, and
`cost_unavailable_reason: "omni_job_api_does_not_expose_cost"`. That remains true
of the job API and is not superseded here.

Spend is readable elsewhere. `POST /api/v1/ai/credit-usage/users` (`omni ai
credit-usage-users-read`) returns one cumulative credit total per membership id
for the current billing period, with the period's own bounds; one credit is one
US dollar. August 2026 read 635.297481375 credits for membership
`595a871e-...`, captured in `experiments/analysis/omni-credit-usage-2026-08.json`.

A cumulative counter is not a per-attempt cost, so `omni_credit_cost.py` measures
one attempt as the difference between a read taken immediately before the job is
submitted and a read taken immediately after it terminates. A measured bracket
records the delta with `cost_source: "credit_usage_delta"`. The mechanism is
opt-in: with no `OMNI_COST_BRACKET_LEASE_DIR` configured, the attempt record is
what it was before, unchanged field for field.

Three conditions have to hold for a delta to mean anything, and each is enforced
in code rather than assumed:

- **Sole consumer and serialization.** Any other spend on the identity inside the
  bracket lands in the same counter. The bracket takes an exclusive advisory lease
  on the membership id for its whole duration and refuses to launch without one, so
  a second harness attempt on that identity fails rather than producing two
  unattributable deltas. A bracketed arm must therefore be scheduled serially.
- **Period boundary.** The counter resets at the UTC month boundary. A pair of
  reads that disagree about the period bounds records
  `cost_unavailable_reason: "credit_usage_period_rollover"` rather than a negative
  or truncated number; a counter that moved backwards within one period records
  `"credit_usage_nonmonotonic"`.
- **Read failure.** A failed pre-read refuses the launch, before any spend. A
  failed post-read keeps the attempt and records
  `"credit_usage_read_failed"`, which is distinct from the job-API case above, so
  the two are separable in analysis.

Two limits remain and are not closed by the lease. The lease binds harness
processes only: a browser session or any other client spending on the same
identity inside the bracket is undetectable and would inflate the delta, so a
bracketed arm requires an identity that is otherwise idle. And the endpoint
reports whole-account credits, not per-job attribution, so the delta is a
measurement of what the account spent during the attempt rather than a figure the
provider attributes to that attempt.

Cost is not backfilled for C1-C4. The counter is cumulative and those attempts are
past, so no read taken now can recover their individual cost, and the rerun policy
forbids re-running a trial to collect it. Their cost column stays unavailable.

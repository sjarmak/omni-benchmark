# Harness and scaffold disclosure

Status: frozen for Freeze A. No scaled baseline has been launched and no private
label has been accessed. Unknown values below are blockers for the condition-specific
telemetry smoke test, not values to infer or fill retrospectively.

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
| Provider/model/version | Claude Code adapter 2.1.250 through `anthropic_claude_code_oauth`, requesting `claude-opus-5`; realized model telemetry is recorded per attempt | Same as C1 | Same as C1 | Managed production selection; two public C4 probes reported Bedrock `claude-opus-5`, but stage/model stability across scaled runs remains unproven |
| System instructions | Operative provider system prompt is code-bound; committed `direct-sql-v1.json` is non-operative policy metadata | Same operative provider prompt and condition-specific tool schema | Same operative provider prompt and condition-specific tool schema | Production agent instructions; export only if observable and permitted |
| Available tools | Schema discovery, database query/execute, bounded error recovery | C1 plus database-level HKB search/get | C1 plus exported semantic-model search/get | Production Omni agent tools and governed query workflow |
| Knowledge at runtime | Public schema/column metadata | Public schema plus database-level HKB; no hidden knowledge IDs | Public schema plus Omni model derived from public schema/HKB; no hidden knowledge IDs | Same public knowledge encoded in the governed model; no hidden knowledge IDs |
| Retrieval/context | Query-directed search over committed public tables/columns/relationships; maximum four tables and 64 KiB per result | Same bounded schema search plus public HKB search via unweighted SQLite FTS5 BM25 with canonical-order ties; neither is a whole-file prompt dump | Same bounded schema search plus the same retrieval algorithm over the searchable Omni semantic export | Production Omni discovery behavior |
| Database access | Direct read-only benchmark database | Same | Same | Through Omni connection/governed query path |
| Planning/orchestration | Direct agent, frozen after train-only tuning | Same base harness | Same base harness | Production composite workflow; stages disclosed when observable |
| Retry behavior | Harness retry ceiling 0; provider-internal retry events are observed in the trace when exposed | Same | Same | Production-default retries; observed rather than artificially matched after treatment |
| Compiler/query path | Agent emits SQL | Agent emits SQL | Agent emits SQL | Semantic query/objects compiled through Omni; generated SQL captured only if exposed |
| Validation | Database execution/error handling only | Same | Same | Production validation behavior included |
| Token/time ceilings | Claude Code 2.1.250 exposes no supported input/output-token ceiling; each turn is limited to 120 seconds, USD 1 provider cost, and 12 total turns | Same | Same | Production defaults where immutable; disclose any mismatch |
| Current implementation state | Public context, pinned provider, attested PostgreSQL, capture, publisher, committed database bindings, and executable driver pass synthetic/adversarial tests; the first authenticated live smoke reached schema discovery but exposed an unbounded-context budget failure, and the bounded replacement awaits immutable replay | Same, including searchable public HKB and dependency-closure provenance | Same, including searchable exported-model objects | Isolated public archeology model validation, 14/14 semantic readback, governed query execution, and AI Hub diagnostic inspection pass; the exact-commit capture rerun preserved full telemetry on its deliberately unscoreable truncated result; scorer-type parity remains pending |

Exact prompts, tool manifests, model identifiers, configuration hashes, retry
ceilings, and version fingerprints are Freeze B artifacts. C1-C3 must be made
reasonably competent, but perfect laboratory parity must not block the primary
C4 research work.

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
are never encoded as zero. Token/cost values separately declare
`provider_reported`, `derived`, or `unavailable`. Scoring produces a separate
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
identify the evaluated-system origin and a terminal failure class. Complete,
untruncated `trace-event-v2` traces reconcile token, tool-call, database-query,
retry, and validation totals to the attempt envelope; truncated traces carry an
explicit degraded reason. A count remains null if the provider does not expose
enough event data to reconcile it.

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
hash-bound result sidecar. It records unrecognized completed responses as
`response_contract_error` and never guesses SQL from prose.

Raw JSON preserves JSON primitive distinctions in the envelope, but the first
live semantic canary showed that it does not necessarily preserve semantic field
types: with `formatResults:false`, a count measure was returned as a JSON string
while the grouping field remained a boolean. Dates and timestamps may also be
strings. The adapter does not heuristically coerce strings. Before scaled
execution, scorer parity must prove consistent predicted/gold normalization or
the capture path must adopt a result transport with authoritative field-type
metadata. This is now an observed scale blocker, not only a theoretical
limitation.

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

Current gate result: **C4 capture sub-gate passed; four-condition gate not yet
passed**. The exact-commit public C4 rerun at `dd8e7b1` preserved Bedrock
`claude-opus-5`, 247,676 input tokens, 1,110 output tokens, three tool calls, one
governed database query, and 29,338.859 ms latency while retaining the truncated
result as an unscored `response_contract_error`. Its generation SHA-256 is
`86814a6b5264cacc49d0ade910416b6521e4ab26f561819bfaa3701346914494` and its
trace SHA-256 is
`b9243d2a9f6e0d74d36b858282db79ee2fea482ee2b317f18826bd8d2ba4114d`.
The C1-C3 executable driver and capture/publisher core now pass synthetic and
adversarial tests, but their authenticated live attempts and typed-result scorer
parity remain pending. No four-condition live smoke bundle has passed the
complete telemetry gate; scaled runs remain blocked until it does.

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

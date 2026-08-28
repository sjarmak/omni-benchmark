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
| Provider/model/version | Pending adapter selection; pin one capable model across C1-C3 | Same as C1 | Same as C1 | Managed production selection; exact stage/model observability pending instance inspection |
| System instructions | Frozen direct-SQL task contract; exact text pending | C1 plus HKB discovery instructions | C1 plus Omni-model discovery instructions | Production agent instructions; export only if observable and permitted |
| Available tools | Schema discovery, database query/execute, bounded error recovery | C1 plus database-level HKB search/get | C1 plus exported semantic-model search/get | Production Omni agent tools and governed query workflow |
| Knowledge at runtime | Public schema/column metadata | Public schema plus database-level HKB; no hidden knowledge IDs | Public schema plus Omni model derived from public schema/HKB; no hidden knowledge IDs | Same public knowledge encoded in the governed model; no hidden knowledge IDs |
| Retrieval/context | Pending common direct-agent adapter | Searchable HKB, not a whole-file prompt dump | Equivalent searchable semantic export | Production Omni discovery behavior |
| Database access | Direct read-only benchmark database | Same | Same | Through Omni connection/governed query path |
| Planning/orchestration | Direct agent, frozen after train-only tuning | Same base harness | Same base harness | Production composite workflow; stages disclosed when observable |
| Retry behavior | Pending; matched ceiling across C1-C3 | Same | Same | Production-default retries; observed rather than artificially matched after treatment |
| Compiler/query path | Agent emits SQL | Agent emits SQL | Agent emits SQL | Semantic query/objects compiled through Omni; generated SQL captured only if exposed |
| Validation | Database execution/error handling only | Same | Same | Production validation behavior included |
| Token/time ceilings | Pending; matched across C1-C3 | Same | Same | Production defaults where immutable; disclose any mismatch |
| Current implementation state | Provider-neutral capture/publisher core passes synthetic and adversarial contract tests; public context, provider, and live database adapters pending | Same core; searchable public HKB adapter pending | Same core; searchable exported-model adapter pending | Complete unscored attempt producer and strict production-response adapter pass synthetic contract tests; Omni CLI 1.1.2 executable bytes are SHA-256 pinned; authenticated live smoke pending |

Exact prompts, tool manifests, model identifiers, configuration hashes, retry
ceilings, and version fingerprints are Freeze B artifacts. C1-C3 must be made
reasonably competent, but perfect laboratory parity must not block the primary
C4 research work.

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
trace, result, and artifact-root identity. Publication revalidates those bindings,
the condition-specific capability surface, Query-only SQL admission, lifecycle,
failure-specific database-query deltas, strict finite and non-negative telemetry,
and the prospective run manifest before writing either `generation.jsonl` or
`run.json`. An attested direct database transport must prove read-only role state
and lack of non-system function-execution privileges before the first model turn.
The live public-context, model-provider, and PostgreSQL adapters remain pending;
this core therefore supports synthetic contract evaluation but not a baseline
accuracy run yet.

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

Raw JSON preserves JSON number, boolean, null, string, array, and object types,
but the transport represents dates and timestamps as strings. The adapter does
not heuristically coerce ISO-looking strings. Before scaled execution, scorer
parity must either normalize both predicted and gold transports consistently or
the capture path must adopt Omni's Arrow result stream for date/time type tags.
This limitation is explicit rather than hidden behind inferred types.

The API exposes query actions clearly enough to count governed database queries;
the additional raw-JSON semantic-query execution is also counted as an adapter
database query and included in attempt latency.
It does not establish that every action is a model tool call or expose the full
production validation/retry internals. Accordingly, `database_query_count` is
recorded for successful C4 attempts, while tool-call, validation-attempt, retry,
token, and cost fields remain null and explicitly unavailable until a live
response proves a more authoritative source. Reduced action-type counts are
diagnostic response-shape metadata, not mislabeled tool counts.

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

Current gate result: **not yet passed**. The C4 transport, strict result adapter,
complete attempt envelope, run manifest, and secure capture boundary pass
synthetic/adversarial tests. The shared C1-C3 capture/publisher core also passes
synthetic and adversarial tests, but its public-context, provider, and live
database adapters are not connected. No live authenticated C4 response has been
inspected. Scaled runs remain blocked until four separately manifested smoke
bundles validate together.

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

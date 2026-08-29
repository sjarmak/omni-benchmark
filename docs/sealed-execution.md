# Sealed PostgreSQL execution

Status: public/synthetic conformance implementation. No hidden label was used to
build or test this adapter.

This layer joins the frozen pure comparators in `omni_benchmark.scoring` to
PostgreSQL without making the development workspace a gold-package reader. The
package deliberately contains no attachment parser. A dedicated evaluator must
construct evaluator-only `SealedGoldRecord` values inside the custody boundary
after Freeze B.

## Execution contract

`omni_benchmark.postgres_execution` uses Psycopg's typed DB-API transport and
reproduces the public LiveSQLBench Query execution behavior:

- set a 60-second PostgreSQL statement timeout before every statement;
- independently arm a client-side cancellation timer that candidate SQL cannot
  disable by changing PostgreSQL settings;
- execute a string containing semicolon-separated statements as one driver call;
- advance Psycopg 3 to the final result set, matching the pinned Psycopg 2
  evaluator's last-result behavior;
- execute explicit statement lists in order and retain only the last result;
- commit each successful statement and roll back a failed statement;
- fetch 10,001 rows, transport at most the first 10,000, and mark overflow;
- preserve Psycopg values such as `Decimal`, dates, JSON, booleans, and nulls for
  the frozen comparators rather than converting them through CSV.

Driver errors are reduced to a SQLSTATE-aware class without retaining SQL or the
driver message. SQLSTATE `57014` is a query timeout, SQLSTATE class `08` and
client connection errors are infrastructure failures, and other database errors
are statement failures. A rollback, cursor-creation, or cursor-close failure is
infrastructure-owned because the evaluator can no longer establish clean state.

The timeout override exists only for bounded public conformance tests. It cannot
exceed the preregistered 60-second ceiling; final evaluation uses the default.

Before any isolate is acquired, candidate SQL is parsed with the pinned
PostgreSQL dialect and admitted only when every top-level statement is a query.
Transaction control, utility commands, DDL/DML, and nested DML are rejected.
Query-call forms with cluster/session side effects are also rejected, including
`set_config`, session random-seed mutation, large-object mutation, and sequence
mutation. Anonymous `pg_*` functions are denied as a class because PostgreSQL
includes non-transactional WAL, notification, advisory-lock, and administrative
functions that remain effective in a read-only transaction. Unsupported syntax
is rejected without allowing the parser to log the SQL source. Multiple
admitted query statements remain supported for official last-result
compatibility.

## Per-scorer lifecycle

Every scorer gets two fresh disposable database clones so candidate-side state
can never affect gold execution:

1. acquire candidate and gold clones from the same pristine template;
2. run trusted `preprocess_sql` independently on both clones;
3. run candidate SQL as a restricted role in read-only transactions;
4. run gold SQL as the same restricted role on the untouched gold clone;
5. run trusted `clean_up_sql` independently on both clones;
6. destroy/reset and release both clones.

Reset and release run even if evaluation or cleanup raises. There is no scorer
retry. The outer sealed runner may repeat a trial only when the returned failure
is mechanically classified as benchmark infrastructure under the preregistered
rule.

The official policy first executes the authored candidate once, reproducing the
public runner's error-detection pass. It then rewrites candidate and gold SQL
with the frozen comment/`DISTINCT`/`ROUND` rules, executes both, and applies
official Soft EX. This means the candidate is executed twice, as it is upstream.

The sensitivity policy executes candidate and gold SQL once each without SQL
rewriting and applies the frozen multiset/decimal comparator. It is run on a
different pristine clone so official scoring cannot affect it.

The public evaluator uses one database for candidate and gold within a scorer.
The sealed adapter deliberately hardens that lifecycle with independent clones
and read-only scoring connections. This preserves Query-task results while
preventing candidate DDL/DML from changing the answer used as ground truth.
The official scorer preserves the public evaluator's lossy 10,000-row prefix
comparison and records explicit candidate/gold overflow diagnostics. The
sensitivity scorer rejects overflow rather than silently accepting equal
truncated prefixes.

## Outcome and retry ownership

The SQL-free `SealedScoringResult` has an optional three-state score:

- `correct` and `wrong_answer` are normal completed answers;
- `refused_or_error` covers candidate syntax/runtime errors, candidate query
  timeouts, and no query after the evaluated system exhausts its own policy;
- a `None` outcome is a benchmark-infrastructure failure and is not allowed into
  a score artifact.

Candidate statements with no result set are evaluated-system failures. Candidate
overflow is also an evaluated-system failure for sensitivity scoring. A valid
empty `SELECT` remains distinct and can be scored by the sensitivity comparator.
Gold no-result and sensitivity-overflow states are deterministic evaluator
failures and are not rerunnable. Only a closed allowlist of plausibly transient
database acquire/connect/state failures is rerun-eligible. `as_score_record()`
transports only the attempt ID, three-state outcome, and optional failure
category into the existing hash-bound score-artifact API. SQL and result rows
never cross that interface.

## Generate-then-score gate

`omni_benchmark.sealed_batch.score_completed_generation` validates all inputs
before acquiring any database:

- the exact-schema Freeze B manifest fixes the system commit, scorer metadata,
  database snapshot and versions, four condition configurations, and ordered
  schedule hash;
- C1 has no semantic-model content hash, while C3 and C4 require one;
- twelve test-only run manifests cover C1-C4 and repetitions 1-3, and each
  matches the frozen system, schedule, configuration, and semantic-model hash;
- the committed schedule has exactly 1,212 unique attempt IDs and matches its
  Freeze B digest;
- the frozen generation has exactly that attempt set, with 101 records bound to
  each run manifest and matching generation, run-manifest, and record hashes;
- the sealed gold records have exactly that attempt set.

Provenance failures occur before the gold collection is read. Only after all
bindings pass does the evaluator validate the gold records and score attempts,
in committed schedule order, under both policies. This is the mechanical
boundary behind “generate all 1,212 outputs before scoring any.” The final
evaluator should pass each policy's score records to `create_score_artifact`,
which preserves generation-file and per-record hash bindings. An infrastructure
failure blocks score-artifact materialization until the preregistered rerun
procedure resolves it.

## Recording Freeze B

`sealed_tools/record_freeze_b.py` creates the manifest only from Git objects at
the exact current 40-character system commit. It does not read the working-tree
versions of declared files. The committed input specification names every
frozen file, the database snapshot manifest, condition-specific harness,
runtime-policy, prompt, instruction, and semantic-model provenance files, plus
the externally supplied schedule seed and schedule path. C3 and C4 require a
semantic-model file; C1 forbids one.

The schedule is canonical JSONL with exactly these identity-only fields:
`attempt_id`, `condition`, `instance_id`, and `repetition`. It contains all 101
committed test identities exactly once under each of C1-C4 and repetitions 1-3.
`sealed_tools/generate_freeze_b_schedule.py` constructs it from the exact Git
blob at `data/manifests/test_ids.txt` and a human-supplied seed. It never reads
question content or labels and prints no seed or identity.

The registered `committed_block_interleaved_v1` algorithm orders questions by a
domain-separated SHA-256 of the seed and identity. At each of 101 positions it
emits one four-condition block for each repetition, using question-order offsets
0, 34, and 67 and a separately domain-separated condition order. Thus each
question's repetitions are at least 98 four-attempt blocks apart. Repetition is
assigned before scheduling; completion order never changes its label.

After final-candidate selection, first commit the complete candidate and the
schedule generator. The human then supplies the schedule seed. From that exact
checkout, create the schedule once:

```bash
uv run python sealed_tools/generate_freeze_b_schedule.py \
  --workspace "$PWD" \
  --system-commit "<full-current-commit>" \
  --seed "<human-supplied-seed>" \
  --destination data/final-schedule.jsonl
```

Commit the schedule together with `config/freeze-b-input.json`, which records
the same seed and includes both the schedule and committed test-ID manifest in
`frozen_files`. The generator refuses overwrite and writes mode-0600 canonical
JSONL. Its public summary contains only the system commit, hashes, and counts.

From the resulting exact checkout, run the one-time recorder:

```bash
uv run python sealed_tools/record_freeze_b.py \
  --workspace "$PWD" \
  --system-commit "<full-system-commit>" \
  --input-spec config/freeze-b-input.json \
  --recorded-at "<RFC3339-UTC>" \
  --destination experiments/freeze-b.json
```

The destination and any symlinked parent fail closed; an existing destination
is never overwritten. A successful invocation writes canonical mode-0600 JSON
and prints only the system commit, Freeze-B SHA-256, frozen-file count, and
schedule-attempt count. Before writing, it reproduces the schedule byte-for-byte
from the committed test IDs and seed; a hand-reordered but structurally complete
matrix fails. It also proves that Freeze A is an ancestor, rejects Git symlinks
and uncommitted paths, and binds the loaded generator, recorder, content-policy,
scorer, and Freeze-B sources to the system commit.

The record cannot be part of the system commit it names without a hash
self-reference. Use the exact two-commit boundary:

1. `S` is the frozen system commit containing the schedule, input specification,
   code, configuration, and semantic artifacts.
2. Run the recorder at `S`.
3. Create direct child `F` by adding only `experiments/freeze-b.json`; do not
   change, delete, or rename any other path.
4. From the checkout at `F`, validate the boundary before planning generation:

```bash
uv run python sealed_tools/validate_freeze_b_control.py \
  --workspace "$PWD" \
  --control-commit "<full-F-commit>" \
  --system-commit "<full-S-commit>" \
  --manifest experiments/freeze-b.json
```

The validator reads both commits through Git objects. It requires `F` to be the
current, direct, non-merge child of `S`; their diff must be exactly one added,
non-executable regular manifest blob. It validates canonical Freeze B, requires
the manifest and scorer to name `S`, and binds its loaded critical sources to
`S`. Dirty working-tree substitutions do not affect the result. The command
prints hashes and counts only. Neither tool chooses a seed, creates a candidate,
or begins held-out generation.

## Planning sealed generation

After validating the `S` → `F` boundary, construct the generation plan without
executing an attempt:

```bash
uv run python sealed_tools/plan_sealed_generation.py \
  --workspace "$PWD" \
  --control-commit "<full-F-commit>" \
  --system-commit "<full-S-commit>" \
  --freeze-b experiments/freeze-b.json \
  --schedule data/final-schedule.jsonl \
  --public-manifest data/manifests/eligible_questions.jsonl
```

The planner reads only Git objects: Freeze B from `F`, then the registered
schedule, committed test identities, and public eligible-question manifest from
`S`. All three public inputs must have their exact SHA-256 recorded in Freeze B.
The schedule must reproduce byte-for-byte from the human seed and committed test
identities. Public records are recursively rejected if a protected field appears
before the planner interprets their identity, database, or question fields.

The in-memory plan contains only attempt and cohort identities, condition,
repetition, database, and a SHA-256 of the public question. Its CLI prints only
hashes and aggregate counts—never the seed, question text, or test identities.
It requires all 1,212 unique coordinates and the twelve 101-attempt condition ×
repetition cohorts, and binds its own loaded source to `S`. This command neither
authorizes nor performs held-out generation; dispatch remains a separately
authorized post-Freeze-B operation.

### Prepared attempts and private staging

`omni_benchmark.sealed_generation_staging` is the offline handoff between the
validated plan and a future authorized dispatcher. `prepare_sealed_attempt`
selects exactly one plan row, verifies the complete ordered plan and its three
public frozen-file bindings against Freeze B, verifies the public question by
SHA-256, and binds the matching frozen condition configuration. The resulting
in-memory authority includes question text for execution but excludes it from
representations and public summaries.

After a condition adapter completes an evaluated-system attempt, the sealed
repository stores one canonical `attempt.json` envelope beneath an ignored
mode-0700 run root. The single mode-0600 file contains the private generation
record plus a SQL-free binding to the plan, Freeze B, schedule, system/control
commits, condition, repetition, database, and question digest. Recursive
protected/scored-field checks and sensitive-content checks run before the
exclusive write.

Resume is reconciliation, not overwrite: an identical envelope is recognized
without changing the file, while a conflict, symlink, partial directory,
noncanonical encoding, or binding mismatch blocks the attempt. A benchmark-
infrastructure failure is not accepted as a completed staged generation, leaving
any retry to the protocol's separately governed path. The staging layer does not
dispatch, contact a provider, emit a run manifest, score, or read gold.

### Cohort finalization

`omni_benchmark.sealed_cohort_finalization` turns staged attempts into the exact
twelve generation/run pairs expected by the sealed batch gate. For one condition
and repetition, it selects the 101 plan rows in committed schedule order,
re-prepares each row from the exact public question, and reconciles its private
attempt envelope. Any missing, conflicting, cross-plan, or invalid attempt blocks
the whole cohort.

The finalizer concatenates the 101 canonical generation records in schedule
order, derives the generation SHA-256, derives the cohort start/finish bounds
from those records, and constructs `SealedRunManifest` exclusively from the
matching Freeze-B condition plus explicit software/CLI versions. It writes
`generation.jsonl` and `run.json` as mode-0600 files in a temporary mode-0700
directory, then atomically renames the complete directory into place. Failed
temporary writes are removed; an existing destination is accepted only when
both files are byte-identical to the recomputed outputs.

Finalization is offline and per-cohort. It neither decides whether an attempt may
run nor accesses gold or correctness. Scoring remains blocked until all twelve
cohorts exist and the separate batch gate validates all 1,212 records.

### Production authorization

Sealed generation has a receipt type separate from the public C4 baseline gate.
The canonical, mode-0600 receipt binds exactly one decision response to the
frozen system/control commits, Freeze-B/plan/schedule hashes, all four
conditions, 1,212 attempts, output root, runtime-source-set hash, complete
concurrency/wall/cost policy hash, and explicit cost ceiling. Its validity window
is at most one hour.

`validate_sealed_production_approval` authenticates the byte-identical receipt
against one closed human Beads decision. `consume_sealed_production_approval`
then writes one exclusive private marker under a confined ignored run root.
Replay, expiration, binding substitution, noncanonical or nonprivate receipts,
duplicate response comments, and symlinked consumption roots fail closed. The
receipt is not a gold/scoring authorization and must be consumed before any live
adapter is constructed.

### No-score dispatcher

`omni_benchmark.sealed_dispatch` separates production generation into a
read-only preflight and a single authority-consuming execution step. Preflight
validates the exact Freeze-B plan, public question hashes, canonical dispatch
policy, and loaded runtime-source bytes at frozen system commit `S`; reconciles
every immutable attempt envelope; and authenticates the human receipt. It does
not create the output root or construct an adapter.

Execution first proves staged state has not changed since preflight and that the
complete pending per-condition reservation fits the approved cost ceiling. It
then consumes the receipt exactly once and constructs one adapter per condition.
Each adapter must expose the complete matching `FreezeBCondition` identity before
any attempt is called. A bounded worker pool enforces at most one in-flight
attempt per database and stops admitting work at the approved wall deadline.
Completed evaluated-system outcomes are staged atomically; infrastructure
exceptions are not staged and a resume requires a fresh receipt. Once all 1,212
attempts reconcile, the dispatcher emits the twelve condition × repetition
cohorts through the offline finalizer. No correctness or score enters this API.

The dispatch policy includes maximum concurrency, maximum wall seconds, an exact
total cost ceiling, positive per-condition reservations, and software/CLI
versions used by final manifests. Its canonical SHA-256 is receipt-bound. The
runtime-source digest is an ordered manifest of committed source paths and their
Git-blob digests; any loaded/committed byte mismatch fails before approval
consumption. The final source list must be expanded to the concrete direct and
Omni adapter dependencies before recording Freeze B.

The command boundary is intentionally dry by default:

```bash
uv run python sealed_tools/dispatch_sealed_generation.py \
  --workspace "$PWD" \
  --control-commit "<full-F-commit>" \
  --system-commit "<full-S-commit>" \
  --freeze-b experiments/freeze-b.json \
  --schedule data/final-schedule.jsonl \
  --public-manifest data/manifests/eligible_questions.jsonl \
  --policy config/sealed-dispatch-v1.json \
  --receipt "/path/to/private/sealed-approval.json" \
  --output-root runs/sealed-final-v1 \
  --run-id sealed-final-v1
```

The policy is loaded from its exact Git object at `S`, must be canonical JSON,
and must have its file SHA-256 in Freeze B. Working-tree substitutions are
ignored. The dry command performs the complete read-only preflight and prints
only hashes/counts with `live_execution=not_started`; it does not consume the
receipt. Production execution additionally requires
`--execute-sealed-generation` and a compiled concrete-adapter builder. Until
the C1-C3/C4 adapters are complete, the checked-in script refuses that flag
before receipt consumption.

### Sealed C4 capture adapter

`SealedOmniConditionAdapter` is the sealed-only projection boundary over the
existing `OmniProbeResult` contract. It is constructed after receipt consumption
with the exact C4 `FreezeBCondition`, dispatch policy, private capture root, and
a production probe runner. Each invocation receives only an opaque
`SealedPreparedAttempt`, creates a unique mode-0700 ignored sidecar directory,
and passes a mode-0600 `ArtifactStore` to the runner.

The adapter constructs provenance from Freeze B and the dispatch policy, then
rewrites only the generation identity to the exact sealed attempt/cohort and
`partition=test`. It preserves the raw public question in the record while the
production runner may render the separately frozen C4 prompt for submission.
An Omni terminal job failure is an evaluated-system outcome and remains a valid
unscored generation. Transport, polling, response-contract, or other benchmark-
infrastructure outcomes remain unstaged for the separately governed incident
path. The adapter contains no scoring or correctness interface.

### Sealed direct capture adapter

`SealedDirectConditionAdapter` is the C1-C3 production boundary. It does not use
or widen `DirectDevelopmentScope`, `DirectQuestionIdentity`, or
`load_committed_direct_question`; those remain restricted to train/dev-A/dev-B.
Instead, an opaque `SealedPreparedAttempt` mints a distinct test-only runtime
binding that carries the exact plan, Freeze-B, schedule, condition, question,
database, model, context, budget, and system/control commit identities.

After dispatcher approval consumption, an injected dependency factory must
exact-match live transports and public tools to that binding. The adapter then
reuses the direct tool/capture loop under a sealed HMAC authority, writes a
separate canonical sealed receipt in a unique private sidecar directory, and
projects an unscored `partition=test` record for immutable staging. Refusals and
evaluated-system failures are retained; benchmark-infrastructure failures are
not staged. No sealed direct API reads gold, correctness, or test annotations.

Production adapter paths are not inferred from filenames. The builder reloads
`config/freeze-b-input.json` and every path it names from Git at `S`, requires
the complete frozen-path set and blob digests to match Freeze B, and regenerates
the four ordered condition identities plus database snapshot identity. Dirty
working-tree copies are ignored. This read-only specification loader does not
inspect environment credentials or construct a transport.

The direct production factory is inert before sealed approval consumption. For
each C1-C3 attempt it selects the Claude lease assigned to that frozen
repetition, reads only the matching mode-0600 external database environment,
and owns fresh mode-0700 HOME/TMP/work directories for the capture lifetime. It
then exact-checks committed runtime/context/database identities, pinned CLI
identity, and Freeze B before constructing the Claude and attested read-only
PostgreSQL transports. Context exit removes the ephemeral runtime tree on both
success and failure; it never refreshes, repairs, copies, or mutates the lease.

The C4 production factory is likewise provider-inert before an approved
attempt executes. It reloads the C4 condition, prompt, and managed instructions
from the system commit; exact-compares their identities, the pinned Omni CLI,
and a verified all-database deployment gate with Freeze B; and selects one
explicit branch/model/semantic-model target by the attempt's public database.
Only inside adapter execution does it load the existing Omni environment,
overlay the frozen target and budget identities, authenticate, submit the
unchanged public question template, and start a private capture. Provider and
capture errors remain benchmark-infrastructure failures and do not become
sealed generation records.

The deployment gate is an immutable input to this factory, not an inference
from mutable environment state. The top-level sealed builder must construct it
from the separately verified post-E02 deployment evidence and require exact
coverage of every database scheduled for C4 before dispatch.

## Psycopg template connector

`PsycopgTemplateIsolationProvider` is the concrete PostgreSQL 18 connector. It
requires separate in-memory admin and execution connection strings plus a
database-to-template mapping. Both strings must name explicit, distinct roles.
Only the admin role creates/drops clones and runs trusted setup/cleanup; generated
candidate and gold SQL always use the restricted execution role with both a
connection-level read-only default and transaction-level read-only enforcement.
Those settings are defense in depth, not the security boundary: before returning
a scoring connection the provider attests the live role, including role
attributes/memberships, database ownership and CREATE/TEMP, schema CREATE,
table/column/sequence mutation privileges, and user-function execution. The
clone's database ACL is hardened before connection. Any unsafe privilege fails
closed. The provider creates randomly named single-use clones with safely quoted
identifiers, uses `ClientCursor` for Psycopg 2-compatible simple-query behavior,
terminates clone connections during reset, and drops each clone. Connection
strings are excluded from object representations and errors are sanitized.
If clone creation has an ambiguous acknowledgement or ACL hardening fails, the
provider performs a compensating `DROP DATABASE IF EXISTS` so a full evaluation
cannot accumulate orphan databases.

Psycopg and its binary package are pinned to 3.3.4 in the lockfile. Final Freeze
B metadata must also record PostgreSQL server and libpq versions.

## Conformance evidence

The normal suite uses only synthetic/public fixtures and covers preprocessing,
cleanup, raw candidate detection, both SQL rewrite transports, ordered statement
execution, semicolon batches, final-result selection, row cap, empty results,
server and client-enforced timeouts, query-only candidate admission, database
failures, cleanup/reset, compensating clone cleanup, exact batch gating,
score-record transport, and SQL-free representations.

`tests/test_postgres_execution_live.py` is an opt-in PostgreSQL oracle for an
explicitly disposable public or synthetic server. The main test uses the first
three variables. The adversarial role-admission test additionally uses the last
two. Admin and execution DSNs must name distinct roles:

```text
OMNI_BENCHMARK_LIVE_POSTGRES_DSN
OMNI_BENCHMARK_LIVE_POSTGRES_EXECUTION_DSN
OMNI_BENCHMARK_LIVE_TEMPLATE_DATABASE
OMNI_BENCHMARK_LIVE_POSTGRES_UNSAFE_EXECUTION_DSN
OMNI_BENCHMARK_LIVE_POSTGRES_UNSAFE_TEMPLATE_DATABASE
```

It creates disposable clones and verifies a real server timeout,
semicolon-batch final result, 10,000-row overflow signal, read-only enforcement,
credential separation, both known read-only bypass payloads under a hardened
role, client cancellation after a query disables the server timeout, rejection
of the exact `ALTER ROLE`, large-object, `set_config`, logical-WAL-message, and
advisory-lock candidate payloads,
rejection of a role with an effective UPDATE grant, and pristine state after
reset. It does not print connection strings. Both tests passed against a separate
local PostgreSQL 18 container on 2026-08-28; that container was removed
immediately afterward and the active benchmark-infrastructure canary was not
touched.

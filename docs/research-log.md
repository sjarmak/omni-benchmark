# Research decision log

This is the chronological, human-readable account of what we believed, why we
acted, what happened, and how our understanding changed. It complements the
machine-readable experiment ledger; it does not replace run artifacts. Entries
are append-only. Private SQL, hidden annotations, test-case bodies, credentials,
and sealed outcomes are prohibited.

## 2026-08-27 — D-001: Use the downloaded Large-v1 rows as the population authority

### Observation

The actual pinned JSONL contains 480 unique instances. Its public `category`
field contains 332 `Query` tasks and 148 `Management` tasks. Contrary to the
dataset-card description, the rows do not contain `difficulty_tier`.

### Hypothesis

Filtering by the observed `category` field is the least ambiguous and most
reproducible way to implement the assignment's request to skip CRUD work.

### Decision

Define the benchmark population as the 332 `Query` tasks across 18 databases.
Do not use undocumented/invented difficulty values.

### Rationale

The alternative—reconstructing CRUD status from question text or SQL intent—
would introduce semantic judgment and possible leakage without improving the
product question.

### Intervention

Added strict public-source validation and the eligible manifest generator in
`omni_benchmark.split`. Provenance: `config/preregistration.json`; commit: Freeze
A pending; affected subsystem: dataset preparation.

### Result

The committed candidate manifest contains 332 questions and no protected field
content. The excluded population is exactly 148 Management tasks.

### Interpretation

The public release itself, not prose about a nearby release, must govern counts
and available stratification fields.

### Outcome

KEEP

### Product implication

None yet; this is evaluation integrity rather than an Omni behavior.

### Next step

Freeze the deterministic question-level partitions before receiving gold.

## 2026-08-27 — D-002: Hold out questions, not databases

### Observation

Omni's product claim concerns repeated questions against an established semantic
model. A database-level test would conflate cold-start modeling, relationship
inference, transformation portability, and question answering.

### Hypothesis

A question-level holdout across all databases will more directly measure whether
semantic-model and harness improvements generalize to unseen analytical requests
in the intended product setting.

### Decision

Create a deterministic 231-development / 101-test split, stratified first by
database and balanced by public `high_level`. Keep all 18 databases in both.
Reserve leave-one-database-out work as a secondary development-only study.

### Rationale

This isolates the main product estimand. The alternative database holdout remains
useful for transformation portability but would make the headline result harder
to interpret.

### Intervention

Added deterministic split code, IDs, metadata, allocation diagnostics, and
regeneration tests. Experiment ID: not applicable (protocol decision); commit:
Freeze A pending; configuration: `config/preregistration.json`.

### Result

The split is exactly 231/101, disjoint and exhaustive. Every database occurs in
both partitions. Train/test ID SHA-256 values are recorded in
`docs/methodology.md`.

### Interpretation

The primary claim is unseen-question generalization on modeled databases, not
unseen-domain performance.

### Outcome

KEEP

### Product implication

This aligns evaluation with how customers normally deploy Omni: model once, ask
many new questions.

### Next step

Enforce hard label custody and preserve a public-only semantic baseline.

## 2026-08-27 — D-003: Use hard custody rather than process-only discipline

### Observation

Autonomous agents routinely search and summarize available files. Keeping the
full gold package in the workspace would create an avoidable accidental-leakage
risk even if code paths intended to filter it.

### Hypothesis

A human-custody boundary plus a train-only release tool will make the no-test-
leakage claim auditable at low operational cost.

### Decision

Keep the untouched private package outside agent scope. After Freeze A, release
only the 231 development records to `data/private/`; never release held-out
hidden fields to development, including after final scoring.

### Rationale

A process-only seal was simpler, but technical isolation better protects against
accidental contamination and strengthens the final narrative.

### Intervention

Added the human-run custody tool, committed-ID verification, path confinement,
mode-0600 atomic output, exact field projection, and train-only immutable loader.
Commit: Freeze A pending; affected subsystem: private-label release.

### Result

Focused custody tests cover foreign IDs, missing/duplicate records, hidden-value
error redaction, overwrite refusal, source placement, path/symlink escape, file
mode, and exact output fields. No private data has been accessed.

### Interpretation

The development environment can receive legitimate supervision without ever
holding hidden test labels.

### Outcome

KEEP

### Product implication

None directly; the pattern is useful for trustworthy internal agent evaluation.

### Next step

Record Freeze A before the custodian releases development labels.

## 2026-08-27 — D-004: Add an internal checkpoint holdout for adaptive optimization

### Observation

Repeatedly accepting changes on all 231 development questions would make the
development score increasingly optimistic and provide no internal signal of
overfitting before the one-time final test.

### Hypothesis

Using 154 questions for adaptation and 77 only at a few checkpoints will reveal
whether accumulated improvements transfer without consuming the final test.

### Decision

Split development deterministically into `dev-A` (154) and `dev-B` (77). Routine
optimization sees only dev-A. Dev-B is a metered checkpoint gate with a maximum
of ten consultations and no question-level reactive tuning.

### Rationale

The alternative—cross-validation or repeated full-development optimization—adds
either substantial cost or weak overfitting control. A single internal gate is
simple enough for the hiring task.

### Intervention

Added `make_dev_split.py`, internal ID manifests, metadata, allocation audits,
and regeneration tests. Commit: Freeze A pending; configuration:
`config/preregistration.json`; affected subsystem: experimental partitioning.

### Result

The internal split is exactly 154/77, disjoint and exhaustive over the outer
development set, with all 18 databases in both. Database/`high_level`
proportional deviations are below one record. The `order` marginal was audited,
not optimized: expected dev-B false/true was 32/45 and actual was 37/40. We did
not search seeds to make diagnostics look better.

### Interpretation

The split is representative enough for a checkpoint gate while retaining an
auditable, non-gamed construction.

### Outcome

KEEP

### Product implication

None directly; it makes later product conclusions less likely to be train-set
artifacts.

### Next step

Make autoresearch operations dev-A-only and dev-B access explicit and counted.

## 2026-08-27 — D-005: Optimize mechanisms and product learning, not a scalar score

### Observation

A loop that keeps every aggregate accuracy increase can trade recurring failure
classes, safety, cost, or complexity invisibly. Textual changes and structural
harness changes also need different search tactics.

### Hypothesis

Rich traces, mechanism-level hypotheses, a dev-A regression suite, branching
candidate lineage, and a small non-dominated candidate set will produce more
general improvements and clearer product explanations than scalar hill climbing.

### Decision

Classify textual, structural, and human-controlled surfaces. Require rich safe
traces and generality labels; keep protocol/custody/scoring choices outside
autonomous optimization. Use multi-candidate search only on valuable textual
surfaces and small targeted experiments on structural surfaces.

### Rationale

Installing a general optimizer or building a broad framework was considered and
deferred. The benchmark needs interpretable improvements, not optimizer theater.

### Intervention

Extended `config/autoresearch.json`, `docs/autoresearch.md`, and the train-only
control-plane contract. Commit: Freeze A pending; affected subsystem:
experiment orchestration.

### Result

The policy/schema work is in progress. There are no model-run results yet, so no
claim about accuracy or failure prevalence is justified.

### Interpretation

Methodology is now a guardrail. The next information gain must come from building
and running the public-only Omni baseline, not adding more generic framework.

### Outcome

FOLLOW UP

### Product implication

The eventual trace needs to distinguish authoring, discoverability, reasoning,
compilation, validation, and observability problems so recommendations map to
real product surfaces.

### Next step

Finish the minimum Freeze A controls, then prioritize the mechanical HKB-to-Omni
baseline and full dev-A traces.

## 2026-08-27 — D-006: Refocus on the hiring-task research story

### Observation

The protocol had become rigorous enough that additional methodology risked
delaying the evidence the assignment actually values: baseline behavior,
meaningful interventions, negative results, and product implications.

### Hypothesis

Freezing the existing safeguards and moving quickly to real system traces will
increase research/product insight per unit time without weakening the test.

### Decision

Complete only pre-gold items that protect leakage, detect overfitting, isolate an
important mechanism, or materially increase confidence. Defer publication-grade
infrastructure that does not meet those tests. Keep C1-C4 competent, but do not
let perfect comparator parity block C4 learning.

### Rationale

The alternative was to continue expanding generalized evaluation machinery. It
would produce less evidence about Omni within the project boundary.

### Intervention

Added this contemporaneous research log and a living failure taxonomy. Commit:
Freeze A pending; affected subsystem: research process.

### Result

No benchmark outcomes exist yet. The current top three items are explicitly
pre-baseline risk hypotheses, not observed failure classes.

### Interpretation

The coherent narrative begins with an honest baseline. Infrastructure is now in
service of that narrative rather than the main artifact.

### Outcome

KEEP

### Product implication

Product findings will be logged only when connected to reproducible behavior and,
where possible, measured outcomes.

### Next step

Build the public-only HKB transformation and run the first complete baseline.

## 2026-08-27 — D-007: Make cost, failure mode, and scaffold observable

### Observation

Aggregate accuracy cannot show whether governance reduces confident errors,
converts them to explicit failures, or changes the cost of a correct answer. The
initial run schema also allowed arbitrary nested diagnostic maps and treated the
pre-supervision baseline as if correctness labels already existed.

### Hypothesis

An immutable generation envelope, separate score record, and private ordered
trace reference will preserve the product-relevant behavior without weakening
label custody. Explicit unavailable/source metadata will prevent opaque systems
from looking artificially efficient.

### Decision

Require full observable cost/failure telemetry for every attempt; distinguish
generation outcome from correctness; remove arbitrary diagnostic objects; add a
condition-by-condition harness disclosure; and block scaled runs until one
public telemetry smoke attempt per condition passes. Keep three sealed
repetitions rather than expanding to five before runtime/cost evidence exists.

### Rationale

Local patterns in Codeprobe, EnterpriseBench, and CodeScaleBench all favored a
normalized attempt record plus raw trace sidecar and explicit degraded capture.
Installing a generalized telemetry framework was considered and deferred. The
small contract directly protects the planned baseline and enables the product
analysis requested by the assignment.

### Intervention

Expanded the run validator and aggregate metrics; separated unscored baseline
outputs from later scoring; added fixed compiler/validation/execution fields,
trace hashes, source/coverage semantics, raw-run ignore rules, and
`docs/harness-disclosure.md`. Experiment ID: protocol/control-plane D-007;
commit: Freeze A pending; affected subsystem: evaluation harness and telemetry.

### Result

Synthetic validation now rejects inconsistent token totals, undeclared missing
counts, invalid model/condition metadata, and unreasoned missing traces. No Omni
condition has yet produced a smoke trace, so capture capability and any accuracy,
cost, or failure-rate effect remain unmeasured.

### Interpretation

The next useful evidence is not another protocol feature. It is the four public
smoke attempts, followed by the mechanically generated public-only baseline.
The harness must disclose opacity rather than fabricate parity or zero usage.

### Outcome

KEEP

### Product implication

If C4 exposes only aggregate or partial stage telemetry, that is itself an
observability limitation relevant to debugging governed analytics. It becomes a
product finding only after the instance behavior is reproduced and measured.

### Next step

Connect the four condition adapters, complete the telemetry smoke gate, then
run and preserve the public-only 231-question generation baseline.

## 2026-08-27 — D-008: Fail closed on baseline, telemetry, and checkpoint provenance

### Observation

Adversarial review found that a content hash alone did not stop the ignored
baseline output from being overwritten, incomplete provider telemetry could look
valid, and an unsigned dev-B aggregate receipt could be fabricated or replayed.
These were control-plane defects discovered before any private label release or
scaled run.

### Hypothesis

Preserving an exclusive baseline copy and revalidating its hash, reconciling
attempt envelopes to timestamps/traces, and requiring guardian signatures will
turn those silent integrity failures into explicit errors without adding runtime
behavior to the evaluated agents.

### Decision

Harden the existing narrow control plane rather than add a generalized
evaluation framework. Bind protocol inputs to the externally recorded Freeze A
commit, preserve and re-hash the baseline copy, require explicit failure
provenance, authenticate dev-B receipts with an externally held key, and reject
receipt/output replay.

### Rationale

Each change protects custody or the credibility of a named co-outcome. Broader
framework work was deferred because it would not produce Omni product evidence.
The signed-receipt boundary also keeps checkpoint correctness outside the
development agent while allowing aggregate generalization checks.

### Intervention

Updated `autoresearch_config`, `autoresearch_runs`, `autoresearch_guardian`,
`autoresearch_ledger`, and custody tooling. Added adversarial tests for commit
binding, raw-run confinement, baseline tampering, timestamp/token/trace
consistency, missing failure ownership, forbidden taxonomy content, invalid
signatures, unpinned keys, and receipt replay. Experiment ID: control-plane
D-008; commit: Freeze A pending.

### Result

All current synthetic tests pass. The validator now rejects the reviewed
failure cases before any score is accepted. This result establishes control-
plane behavior only; it does not change or estimate Omni accuracy, latency, or
cost.

### Interpretation

The most important pre-baseline risks were accidental ambiguity and mutable
evidence, not a missing optimizer. Those paths now fail visibly. The remaining
blocker is execution integration: a four-condition public telemetry smoke run,
then the mechanical HKB-to-Omni baseline.

### Outcome

KEEP

### Product implication

None yet for Omni. If production C4 cannot expose the fields needed to satisfy
the attempt contract, the resulting explicit degraded-capture record may become
an evidence-backed observability finding after the smoke run.

### Next step

Provision the external guardian key pin, record Freeze A, connect C1-C4, and run
the public telemetry smoke gate before any 231-question execution.

## 2026-08-27 — D-009: Anchor dev-B receipt consumption to committed history

### Observation

Independent adversarial review deleted only the first dev-B allocation marker
while leaving its checkpoint manifest intact. The same valid signed receipt
could then be consumed under a second checkpoint name, resetting the local
counter and bypassing replay protection.

### Hypothesis

Treating the marker as the sole history source made append-only behavior a file-
system convention rather than an auditable invariant. Cross-checking the marker
against the independently written checkpoint manifest, then requiring prior
history in git before the next consultation, should make accidental or agentic
rollback visible.

### Decision

Keep the existing signed-guardian design and add the smallest missing invariant.
Do not introduce a remote database or generalized transparency service. The
external record of each git commit remains the project-level rollback anchor.

### Rationale

The bug affected custody credibility directly and had a deterministic
reproduction. Dual local records catch partial deletion; committed-prefix
verification catches deletion or editing of both after a checkpoint is
recorded. A hostile actor who can rewrite both git history and the externally
recorded hash is outside this development harness's threat model.

### Intervention

The checkpoint allocator now validates a one-to-one, sequential mapping between
`state/checkpoints/*.json` and `state/dev_b_evaluations/*.json`, reconciles the
checkpoint name, commit, receipt ID/hash, and output hash, and requires every
prior pair to match `HEAD` before allocating another evaluation. Experiment ID:
control-plane D-009; commit: Freeze A pending.

### Result

The exact exploit is now a regression test: after creating checkpoint 1 and
deleting `0001.json`, receipt replay for checkpoint 2 fails with an inconsistent-
history error. The full suite passes 179 tests with 84.20% branch-aware coverage;
Ruff, formatting, and package build pass. No benchmark labels or Omni outcomes
were involved.

### Interpretation

Cryptographic authenticity and monotonic consumption are separate properties.
Signing proved who issued a receipt; committed dual history is what proves that
the development process already spent it.

### Outcome

KEEP

### Product implication

None for Omni yet. This is evaluation-governance infrastructure, retained only
because it protects the limited dev-B generalization gate.

### Next step

Complete independent review, provision the externally held guardian public-key
pin, and record Freeze A before any private training-label release.

## 2026-08-27 — D-010: Prove the telemetry boundary before scaling execution

### Observation

The normalized attempt schema described the required cost and failure telemetry,
but no production adapter yet proved that an opaque Omni job response could be
captured without leaking credentials or inventing unavailable metrics. Review of
CodeScaleBench, EnterpriseBench, codeprobe, and the existing gas-city Omni tools
also exposed two concrete risks: mutable/copy-based score records and raw response
capture that could retain credentials or result values.

### Hypothesis

A narrow `job-submit`/`job-status`/`job-result` adapter with least-privilege
authentication, response projection, immutable private artifacts, and exact
trace reconciliation can establish what C4 exposes without changing the product
workflow or accessing benchmark labels.

### Decision

Implement and adversarially test the capture boundary before any paid or scaled
run. Reuse the existing run envelope rather than build a general agent framework.
Keep provider values out of the contract-probe artifact; preserve normalized
result rows only in a separate private sidecar when later execution scoring
requires them.

### Rationale

This directly protects the held-out evaluation and determines whether the desired
product telemetry is actually observable. It also avoids treating an absent token,
retry, validation, database-query, or tool-call count as zero. Building C1-C3 or
the semantic transformation first would risk expensive runs with unverifiable
evidence.

### Intervention

Added shared write-side redaction, a least-privilege Omni CLI boundary, an
exclusive mode-0600 artifact store beneath mode-0700 ignored roots, a
`trace-event-v2` tool-call reconciliation field, exact public-question checks,
opaque-result sidecar binding, and a public dev-A-only authenticated probe entry
point. Experiment ID: control-plane D-010; commit: Freeze A pending.

### Result

The focused boundary suite passes 81 synthetic tests. Planted credentials are
excluded from child environments, errors, response-shape artifacts, and trace
artifacts. The probe persists response type/shape and hashes, not result values or
identity data. It rejects non-dev-A IDs and cannot run without an explicit
authenticated-smoke acknowledgement. No real Omni call or benchmark label was
used, so product-level telemetry coverage remains unmeasured.

### Interpretation

The capture format is now testable independently of the product response. The
remaining high-information step is a single authenticated public dev-A probe to
learn which C4 fields are observable, followed by equivalent C1-C3 smoke records.
Unknown C4 fields will be disclosed as unavailable rather than inferred.

### Outcome

KEEP

### Product implication

None yet. If the live job contract omits compiled query, stage model, token,
retry, or validation information, that becomes an observability finding only
after the public smoke reproduction is preserved.

### Next step

Complete adversarial review, obtain the external guardian public-key digest for
Freeze A, then run the one-question authenticated C4 contract probe and connect
the direct-SQL comparator adapter.

## 2026-08-27 — D-011: Green unit tests did not prove a safe capture boundary

### Observation

An independent adversarial pass reproduced four failures after D-010's initial
focused suite was green: mode-0664 and hardlinked run/trace files could validate;
bare and camelCase API-key fields escaped classification; URL userinfo entered
CLI arguments and a credential-shaped prompt entered stdin; and successful Omni
responses were sanitized in memory, changing a legitimate SQL predicate before
the scorer could observe it.

### Hypothesis

The implementation had conflated two different policies: redact untrusted
diagnostic text before persistence, versus preserve successful analytical output
exactly and fail closed only when it contains actual credential material. It also
secured the writer but not every reader, leaving hand-created artifacts able to
bypass file invariants.

### Decision

Treat all four reproductions as blockers. Require private single-link files at
validation time, recognize normalized sensitive key names, apply the content
policy to the raw-byte writer, reject credential-bearing origins/prompts before
invocation, and stop rewriting successful provider responses. Keep projection at
the trace/result persistence boundary.

### Rationale

This preserves scientific fidelity and custody simultaneously. Returning
redacted SQL could produce a false benchmark failure; accepting unsafe artifacts
could leak the same SQL or credentials. A single blanket sanitizer cannot satisfy
both requirements.

### Intervention

Separated diagnostic redaction from persisted-value checks, added camelCase key
normalization, strengthened URL and prompt validation, made question text a
required exact public-manifest field, and routed run/trace reads through the
private mode/ownership/link-count/size boundary. Added the exact adversarial
reproductions as regression tests. Experiment ID: control-plane D-011; commit:
Freeze A pending.

### Result

The 47 focused content, artifact, CLI, and run-hardening tests pass, including
token-shaped query rejection, raw-byte secret rejection, public-question binding,
unsafe run rejection, and trace hardlink rejection. The full suite excluding the
still-in-progress immutable score-binding track passes 258 tests. Independent
probe rerun is pending; no live Omni call or benchmark label was used.

### Interpretation

Writer-only security and a green happy-path suite were insufficient. The durable
design rule is now: project/redact diagnostics, preserve analytical payloads,
fail closed on actual credential material, and verify filesystem invariants again
when consuming artifacts.

### Outcome

KEEP

### Product implication

None for Omni. This is a harness-integrity failure caught before product
measurement. It does, however, establish the evidence standard required before
calling missing C4 telemetry an Omni observability finding.

### Next step

Require the independent adversarial probes to pass, then run the public C4
contract probe once external authentication and the Freeze A guardian pin are
available.

## 2026-08-27 — D-012: Integrate failure telemetry and bound scoring before scale

### Observation

The second independent review found that three green components did not yet make
a complete evidence path. Submit/status/result exceptions and polling exhaustion
could terminate without a persisted failure trace; the separate score artifact
was not wired into experiment decisions or checkpoints; and a score could label
a refused generation as correct (or an answered generation as refused). During
an adversarial failure, the content-policy dataclass representation also exposed
captured environment-secret values in local test output.

### Hypothesis

If every invocation finalizes one trace, the ledger accepts only a score artifact
cryptographically bound to the unchanged generation, and joined labels are
revalidated against the generation terminal state, then scaled runs cannot hide
system failures or silently collapse generation and correctness. Suppressing the
secret-bearing field from object representations should close the observed local
logging path without weakening exact-value detection.

### Decision

Treat these as pre-scale blockers rather than defer them to analysis. Preserve
successful provider payloads exactly, but fail closed on unsafe persisted
artifacts. Require the separate score path and expected SHA in the production
Freeze A configuration, experiment decision path, and checkpoint path. Make the
capture object explicitly single-use and return a finalized failure trace for
each evaluated-system exception.

### Rationale

These changes protect named evidence: terminal failure rates, immutable
correctness, and custody of credentials. They are smaller and more valuable than
adding another optimization framework. Alternatives such as mutating generation
records with scores or logging raw exception payloads were rejected because they
would weaken both scientific fidelity and secret handling.

### Intervention

Added failure finalization to the Omni job capture adapter; hid exact secret
values from content-policy representations; expanded whole-record secret checks;
made trace sequence and result-sidecar schema types exact; allowed legitimate
duplicate result column labels; joined bound score artifacts in the run validator;
and passed score paths/hashes through experiment decisions, CLI commands, and
checkpoints. Experiment ID: control-plane D-012; commit: Freeze A pending;
affected subsystem: telemetry, private artifacts, and experiment ledger.

### Result

The complete synthetic suite passes 290 tests with 85.23% branch coverage. New
regressions reject both directions of terminal-state/score mismatch, live-secret
material anywhere in persisted records, non-integer trace sequences, unsafe
result metadata, and generation/score mutation. The focused independent review
is still completing. No authenticated Omni request, private benchmark label, or
held-out result was accessed. The affected environment credentials were reported
for precautionary rotation; their values were not written to repository files or
artifacts.

### Interpretation

Telemetry completeness is an end-to-end property, not a schema property. A safe
writer, a valid generation file, and a valid score file were insufficient until
the control plane enforced their relationship and all exception paths produced
evidence. The baseline can proceed only after a live public smoke attempt proves
which fields Omni actually exposes.

### Outcome

KEEP

### Product implication

None for Omni yet. The failure was in the evaluation harness. The trace contract
now makes it possible to distinguish future Omni observability gaps from missing
capture implementation.

### Next step

Finish independent security/review gates, provision the guardian public-key
digest, record Freeze A, then run one authenticated public dev-A C4 probe before
any scaled baseline.

## 2026-08-27 — D-013: Adversarially close the remaining evidence-boundary gaps

### Observation

Further active probes found contradictions that aggregate schema tests had not
covered: non-finite cost/latency values, unavailable telemetry paired with event
deltas, terminal trace states inconsistent with the attempt envelope, final-path
symlinks, a generation/score time-of-check race, an unpinned custody release,
credential components echoed without their full connection URI, and result
sidecars whose column labels could identify secrets or hidden benchmark fields.

### Hypothesis

The evidence path would fail closed if each boundary verified both directions of
its invariants: availability against events, trace terminal state against the
envelope, score binding against a second generation read, unresolved paths
against private-file rules, and result columns against both secret and custody
policies.

### Decision

Fix these as Freeze A blockers. Do not use a live benchmark or authenticated Omni
request to test them; preserve each synthetic reproduction as a regression. Keep
the complete attempt producer and run-manifest integration as a separate
pre-baseline smoke gate rather than claiming the current schema alone is ready
for scale.

### Rationale

Every issue could either leak protected material or corrupt a named co-outcome.
The changes are local policy and validation fixes, not new benchmark machinery.
Deferring them would make later accuracy, refusal, cost, and failure analyses
unreliable.

### Intervention

Added finite-number checks; bidirectional trace/envelope reconciliation; exact
terminal failure-class checks; symlink-safe confined reads; a second-read
generation hash check; pre-read guardian-pin verification; bounded job IDs;
connection/proxy URI userinfo redaction in raw and percent-decoded forms; and
sensitive/forbidden result-column rejection. Experiment ID: control-plane D-013;
commit: Freeze A pending; affected subsystem: custody, telemetry, and scoring.

### Result

The complete synthetic suite passes 337 tests with 85.33% branch coverage.
Ruff, format, diff, build, and staged gitleaks gates pass. One independent review
reran the full gates successfully, and the independent security rerun reported no
remaining blocker, high, or medium findings after 217 focused tests and active
adversarial probes.
No authenticated Omni request, private benchmark label, or held-out outcome was
accessed.

### Interpretation

Rich traces are valuable only when their cross-artifact invariants are enforced.
The strongest reusable lesson from this sequence is to validate the full
evidence relationship, not merely each JSON shape. The current implementation is
synthetically hardened, but scaled baseline readiness still requires a live
public smoke record from each condition and a manifest-bound complete attempt
producer (`omni-benchmark-dih.5.4`).

### Outcome

KEEP

### Product implication

None for Omni yet. These were evaluation-harness defects. They prevent us from
misclassifying missing or contradictory capture as a product failure once live
C4 traces are available.

### Next step

Obtain the external guardian public-key digest, record Freeze A, then integrate
the run manifest and execute the four public smoke attempts before any scaled
baseline.

## 2026-08-27 — D-014: Bind production Omni answers to explicit query actions

### Observation

The secure C4 transport could submit, poll, and inspect response shapes, but it
did not yet produce the same complete generation envelope required of scaled
runs. Treating a terminal `COMPLETE` state as an answer would also be unsafe:
the evaluator needs an exact result set, and a provider can complete with an
unrecognized, failed, or truncated query action.

### Hypothesis

If C4 consumes only Omni's documented query-action result contract, normalizes
the selected CSV into a hash-bound private sidecar, and fails closed on any
ambiguous result, then one production invocation can become a reproducible,
scoreable attempt without retaining raw provider payloads. Binding that attempt
to a condition-specific `run.json` should close the provenance path from system
commit through later scoring.

### Decision

Use the final successful `generate_query` action as the C4 analytical result.
Require an untruncated CSV, a nonempty header, consistent row widths, and exact
agreement between parsed rows, `totalRowCount`, and `hasResults`. Preserve row
multiplicity. Record unrecognized completed responses as evaluated-system
contract errors; never infer SQL or rows from the final prose answer.

Count `generate_query` actions as database queries because the API defines them
as query generation and execution. Do not call all Omni actions tool calls or
claim full validation/retry counts: the API does not establish those quantities
as complete. Keep those fields null and explicitly unavailable until a live
trace exposes an authoritative source.

### Rationale

Parsing the natural-language answer would create a second, unverifiable answer
extraction model. Persisting the raw job response would retain unnecessary
messages and identifiers. Labeling every action as a tool call would create
precise-looking but unsupported telemetry. The strict adapter preserves the one
payload scoring needs while making missing product observability visible.

### Intervention

Added a strict Omni job-result adapter, normalized private result sidecars,
complete C4 generation envelopes for both answered and terminal-failure paths,
committed C4 harness/prompt/instruction specifications, pre-auth system-commit
and metadata checks, and a canonical `run.json` bound to the generation hash.
Changed the telemetry smoke gate from one mixed JSONL file to four separately
manifested C1-C4 bundles. Experiment ID: control-plane D-014; commit: Freeze A
pending; affected subsystem: C4 production adapter, telemetry, and run
provenance.

### Result

The synthetic suite passes 372 tests with 85.77% branch coverage. It verifies
successful governed results, duplicate-row preservation, empty results, terminal
failures, transport failures, unknown complete contracts, truncation, ragged
CSV, row-count mismatch, safe receipts, pre-auth split/commit/metadata guards,
and manifest revalidation. The four-bundle smoke gate independently rejects
condition substitution and unmatched question/run/repetition identities. No
authenticated Omni call, private benchmark label, or held-out outcome was
accessed.

### Interpretation

The production job API appears sufficient for execution-result scoring and
semantic-query provenance, but not yet for complete internal cost/tool/validation
telemetry. That distinction is more informative than either claiming full
observability or discarding operational telemetry entirely. A live public smoke
run is still required before classifying the missing fields as an Omni product
gap rather than an adapter limitation.

### Outcome

KEEP

### Product implication

Potential observability opportunity, pending live confirmation: the production
result API makes governed query/results auditable, but experimenters and
customers may not be able to attribute cost, model routing, tool use, retries,
or validation behavior from the same job artifact.

### Next step

Provision the guardian key and Freeze A commit, load and fingerprint the public
benchmark databases, then run one matched public dev-A smoke question through
all four connected conditions before any baseline-scale generation.

## 2026-08-27 — D-015: Reject CSV scoring and bind the executed C4 system

### Observation

Adversarial review invalidated part of D-014. Omni's job result exposes CSV, but
CSV converts numbers, booleans, and nulls into strings; the frozen scorers do not
treat those values as interchangeable. The same review showed that the adapter
accepted incomplete action objects, authenticated before validating all artifact
destinations, trusted a caller-supplied CLI version, did not reject untracked
runtime code, and omitted the selected Omni branch from run provenance.

### Hypothesis

The C4 attempt can be made scoreable and reproducible if the job payload is used
only to select and validate an executed semantic query, that query is rerun through
Omni's unformatted raw-JSON result path on the same branch, and every local
artifact/configuration/provenance check completes before client construction.

### Decision

Withdraw D-014's claim that normalized CSV is a valid scoring payload. Keep CSV
only as contract evidence for status, truncation, and row counts. Use raw JSON as
the authoritative C4 sidecar, preserve JSON values without inference, and count
the additional semantic-query execution as an adapter database query. Record the
managed LLM as unobservable rather than conflating it with Omni's semantic-model
ID. Require a new output root for every attempt.

### Rationale

Heuristic CSV coercion could improve apparent benchmark accuracy while changing
the evaluated values. Raw JSON preserves the distinctions needed for ordinary
numeric, boolean, null, and nested values. A separate semantic-model reference in
`run.json` makes branch changes auditable, while pre-auth checks prevent an
expensive request from producing a partial or falsely attributed attempt.

The remaining transport limitation is explicit: JSON represents dates and
timestamps as strings. We deliberately do not infer types from ISO-looking text.
Arrow capture is deferred until a public smoke shows that date/time type fidelity
is needed or scorer-side transport parity cannot normalize both sides
consistently.

### Intervention

Added strict validation of every official job action and query result; recursive
forbidden-field rejection before serialization; fixed raw-JSON query execution
with formatting and cache disabled; honest database-query accounting; atomic
new-root creation; clean tracked-and-untracked runtime checks; committed Git-blob
spec validation; direct Omni CLI version observation; applied polling controls;
and run-manifest schema v2 with explicit semantic-model reference and optional
snapshot hash. Experiment ID: control-plane D-015; commit: Freeze A pending;
affected subsystem: C4 production adapter, custody, telemetry, and provenance.

### Result

The combined C4/run-manifest integration gate passes 152 tests. It covers typed
numbers, booleans, nulls and nested values; deliberate ISO-date string handling;
malformed earlier query actions; hidden annotation keys nested inside semantic
queries; typed-rerun failures; output collisions; untracked runtime source;
non-blob and worktree-mutated specs; fabricated CLI versions; branch binding;
complete failure attempts; and cross-condition manifest validation. Ruff,
formatting, diff, and package-build gates pass. Two full-suite failures currently
belong to the independently owned public-database provisioning lane and are
recorded on its bead; no C4-focused test fails. Independent combined code and
security reviews are in progress. No authenticated request or private benchmark
label was accessed.

### Interpretation

The original result-extraction path was wrong despite passing broad schema tests.
The correction changes the adapter architecture, not merely validation wording:
job actions establish governed intent, while a typed query transport establishes
the scoring result. Provenance must identify both the production scaffold and the
semantic-model revision that actually executed.

### Outcome

KEEP

### Product implication

Potential observability/API opportunity, not yet an evidence-backed product
finding: a governed job exposes an executed semantic query and display CSV, but a
benchmark-grade consumer must perform another query to obtain raw typed JSON and
still lacks explicit date/time type tags without Arrow. A single result artifact
that exposes typed rows plus model/validation/retry provenance would reduce cost
and make governed analytical answers easier to audit. Live-smoke evidence is
required before promoting this to `product-findings.md`.

### Next step

Complete independent review, obtain the guardian public-key digest, record Freeze
A, and run one public dev-A C4 smoke against the provisioned canary before any
scaled baseline.

## 2026-08-27 — D-016: Pin the executing CLI and narrow the provenance claim

### Observation

Active adversarial review reproduced a same-version executable substitution: a
wrapper placed first on `PATH` could report `omni version 1.1.2` and fabricate
runtime JSON while satisfying the existing version-only provenance check. The
review also found that deserializing an ignored `.pyc` with `marshal` was unsafe,
and that a semantic-model branch name identifies mutable state rather than its
contents.

### Hypothesis

If the committed C4 condition pins the CLI's exact bytes as well as its version,
and the adapter resolves that executable once for both observation and execution,
then a PATH substitution cannot masquerade as the frozen C4 harness. Mechanical
bytecode comparison can retain accidental-contamination detection without parsing
untrusted bytecode. Final semantic-model provenance requires a separate immutable
snapshot at Freeze B.

### Decision

Pin Omni CLI `1.1.2` and its SHA-256 in the C4 condition. Resolve PATH once,
require a regular owned non-writable executable with the expected digest, and
reuse its absolute path. Compare its reported version to the committed value.
Replace `marshal` loading with compiler-output byte comparison. Describe the
worktree scan as contamination detection under a non-adversarial host assumption,
not as a sandbox. Permit a null semantic-model hash only for the contract smoke;
require an immutable model revision or export hash for Freeze B.

### Rationale

A version string is not a content identity. Conversely, building a hostile-host
sandbox would add substantial machinery without protecting the benchmark's main
accidental-leakage threat. The narrower claim is both accurate and sufficient:
exact committed inputs and executable bytes are auditable, while the local host
is trusted. Separating branch identity from a later content hash prevents the
pre-auth smoke from overstating what it proves.

### Intervention

Extended `c4-production-v1.json` and its strict parser with `omni_cli_version`
and `omni_cli_sha256`; added fail-closed executable resolution and hashing;
recorded both values in `run.json`; added same-version-wrapper and version-drift
regressions; removed unsafe bytecode deserialization; split the remaining
oversized C4/run-manifest functions. Experiment ID: control-plane D-016; commit:
Freeze A pending; affected subsystem: C4 runtime provenance and maintainability.

### Result

The 168-test focused C4 gate passes. The complete suite passes 461 tests with one
explicit public-Postgres integration skip and 85.41% branch coverage. Ruff,
formatting, diff, and package-build gates pass. The same-version unpinned wrapper
now fails before version execution, client construction, or authentication. No
authenticated request or private benchmark label was accessed. Independent final
security rerun remains in progress.

### Interpretation

The original version-only check was inadequate even though its synthetic tests
passed. Reproducibility needs content identity at every mutable execution layer:
binary now, semantic-model contents at Freeze B. The worktree check remains useful
for accidental drift, but its threat model must be stated rather than implied.

### Outcome

KEEP

### Product implication

No direct Omni product conclusion follows from this local harness hardening. It
does identify a reproducibility need for external evaluators: an immutable Omni
model revision or content-addressed export would make governed runs easier to
attribute than a mutable branch identifier.

### Next step

Complete independent code/security review, provision the guardian digest, and
record Freeze A. Before Freeze B, bind every frozen C3/C4 run to the exported
semantic-model content hash tracked by `omni-benchmark-dih.5.4.1`.

## 2026-08-27 — D-017: Move question redaction ahead of authentication

### Observation

The final security rerun constructed a synthetic collision between the public
question text and the live token value. Although the artifact writer eventually
rejected the question as sensitive, the adapter had already constructed and
authenticated the client. With the real client, `submit_job` would still reject
locally, but `whoami` would already have crossed the authenticated boundary.

### Hypothesis

The local preflight is complete only if it applies the same content policy to the
rendered public question before creating the output root, observing the CLI, or
constructing the client.

### Decision

Validate the rendered question against the live environment's content policy as
part of `_prevalidate_local_run`. Keep the later client and artifact checks as
defense in depth.

### Rationale

Public provenance does not guarantee that text cannot accidentally equal a live
credential. The correct invariant is temporal: every locally knowable rejection
must happen before authentication, regardless of how unlikely the collision is.

### Intervention

Added a pre-auth question-safety gate and a regression that asserts no output
root, version observer, or client construction occurs. Experiment ID:
control-plane D-017; commit: Freeze A pending; affected subsystem: C4 content
policy and authentication ordering.

### Result

The regression failed before the change by reaching the complete synthetic C4
workflow and then failing at artifact persistence. It passes after the change.
Independent code and security reviews approve the final scope with no remaining
critical, high, medium, or low findings. The final complete suite passes 462
tests with one explicit public-Postgres integration skip and 85.41% branch
coverage; Ruff, formatting, diff, dependency, and secret-pattern gates pass. No
authenticated real request or private benchmark label was accessed.

### Interpretation

The pre-auth boundary is now enforced as an ordering property rather than as a
collection of eventual validators. The failed first run was useful: persistence
safety alone did not prove that rejected content had stayed local.

### Outcome

KEEP

### Product implication

None for Omni itself. This is a harness sequencing lesson: safe serialization
and safe authenticated execution are separate properties and should be tested
independently.

### Next step

Obtain the externally generated guardian public-key digest and record Freeze A.
Then run the public connected smoke and begin the mechanical HKB baseline.

## 2026-08-27 — D-018: Make the preregistered analysis executable

### Observation

A requirement-level Freeze-A audit found that the split bytes were reproducible
but only the inner dev-A/dev-B regeneration was locked by a committed test. It
also found outcome-sensitive degrees of freedom in the phrase
"question-clustered bootstrap": confidence level, replicate count, sampler,
rank convention, and McNemar family were unspecified. Separately, scorer review
showed that the pinned upstream `DISTINCT` regex unintentionally preserves some
queries containing a later `JOIN ... ON`, while the documentation described the
intended behavior categorically.

### Hypothesis

Byte-identical outer regeneration plus a machine-readable statistical plan with
fully specified sampling bytes and ranks will make Freeze A reproducible without
adding publication-oriented machinery. A conformance fixture should preserve the
upstream SQL-rewrite quirk rather than silently correcting it.

### Decision

Lock both split stages in one committed regression. Use a 95%, 10,000-replicate
question-clustered percentile bootstrap with a deterministic SHA-256 sampler and
nearest-rank convention. Report repetition-one exact McNemar only as sensitivity:
unadjusted for primary `C4-C1`, Holm-corrected across the three exploratory rung
contrasts. Document the two-commit Freeze-A hash record and upstream `DISTINCT`
quirk exactly.

### Rationale

These choices remove discretion after results without changing the split or
expanding the main research question. The primary comparative endpoint should not
be folded into the multiplicity family defined for exploratory mechanistic
contrasts.

### Intervention

Extended the committed-manifest test to regenerate outer and inner splits from
the public manifest; added exact statistical configuration and mechanics to the
preregistration/protocol/methodology; added the `JOIN ... ON` SQL-rewrite fixture;
and specified `experiments/freeze-a.json` as a post-freeze metadata commit rather
than a self-referential placeholder. Experiment ID: control-plane D-018; commit:
Freeze A pending; affected subsystem: split auditability, statistical analysis,
and scorer disclosure.

### Result

All six outer/inner ID and diagnostic artifacts regenerate byte-for-byte with no
membership change. The 19 focused committed-manifest and scorer tests pass;
Ruff, formatting, and diff checks pass. Independent scorer review found no
remaining issue after 5,000 randomized public-evaluator comparisons and the new
conformance fixture. No private label or outcome was accessed.

### Interpretation

The design itself was sound, but prose-level statistical intent was not yet an
executable preregistration. The fix is deliberately small: exact deterministic
choices and one regression, not a generalized statistics framework.

### Outcome

KEEP

### Product implication

None directly. This strengthens the credibility of any later product comparison
by ensuring uncertainty calculations cannot be selected after seeing outcomes.

### Next step

Obtain the guardian public-key digest, switch pending status markers to frozen,
create Freeze-A Commit A, then record its hash in Commit B before any train-label
release.

## 2026-08-27 — D-019: Keep dev-B labels behind the guardian

### Decision / experiment

Replace the development-label extractor's 231-record release with a canonical
154-record dev-A-only release.

### Observation

The nested development protocol treated dev-B as a metered generalization gate,
but the user-run custody tool still released every development label into the
ordinary agent-readable workspace. Signed aggregate dev-B receipts therefore
did not form a real boundary: development could bypass them by opening the local
77 dev-B records. This contradicted the later hard-custody amendment even though
the 101-question final test remained sealed.

### Hypothesis

Binding extraction to the committed `dev_a_ids.txt` and
`development_split_metadata.json` will make routine optimization technically
dev-A-only while retaining an all-231 public, unscored baseline. Dev-B can then
measure checkpoint generalization without exposing per-question outcomes.

### Decision

Supersede D-003's 231-record local release before Freeze A. Release only dev-A
labels locally; keep dev-B labels with the external guardian and allow only
signed aggregate checkpoint receipts into development. Preserve D-003 as the
historical decision rather than rewriting it.

### Rationale

A process-only dev-B restriction would be difficult to defend while an
autonomous agent could read the labels directly. The dev-A-only extractor is a
small change that makes the implemented boundary match the intended nested
development design. Keeping all 231 public questions in baseline generation
preserves the pre-supervision measurement without weakening custody.

### Intervention

Changed the custody CLI to accept only the canonical `--dev-a-ids` manifest,
verify its Freeze-A blob and development-split metadata binding, and filter every
other record before validating hidden-field shape. Removed the public arbitrary-
ID release helper, made the verifier return IDs parsed from immutable Freeze-A
`git show` bytes rather than reopening the worktree manifest, updated the
information tiers and baseline-scoring procedure, and added documentation and
manifest-swap regressions. Experiment ID: control-plane D-019; commit: Freeze A
pending; affected subsystem: private-label custody. Change type: general
evaluation-system integrity.

### Result

The six updated CLI regressions failed before implementation because the old
`--train-ids` interface was still required. Independent security review then
reproduced a high-severity time-of-check/time-of-use race: swapping the worktree
manifest after verification released a dev-B fixture. The new regression failed
on that behavior and passes after release selection was bound to committed
bytes. All 41 custody tests now pass. A malformed dev-B record is ignored using
only its public membership key, and neither its hidden marker nor a held-out
marker enters the output. The README and governing protocol now prescribe the
same dev-A-only command. No private label or gold file was accessed.

### Interpretation

The original outer 231/101 seal was intact, but the nested dev-A/dev-B gate was
not technically enforced. Custody must follow the finest partition used for
adaptive decision-making, not merely the outer train/test partition. A committed
path check is insufficient when security-sensitive bytes are reopened from a
mutable worktree after verification.

### Outcome

KEEP

### Product implication

None for Omni itself. For agent-evaluation tooling, access control must be
aligned with checkpoint semantics; signed receipts do not add protection when
the underlying labels are readable by the optimizer.

### Next step

Provision the guardian public-key digest, run independent code/security review
and full exact-tree gates, then create Freeze A Commit A and its separate hash
record before any dev-A label release.

## 2026-08-27 — D-020: Record the pre-gold protocol freeze

### Decision / experiment

Freeze the eligible population, nested partitions, custody boundary, scorers,
conditions, endpoints, and optimization controls before any private label enters
development.

### Observation

The public-only protocol candidate had passed broad tests, but the git index was
stale and the dev-B guardian digest was not yet provisioned. Independent custody
review then found both the 231-label release contradiction and a manifest
time-of-check/time-of-use race. Those issues made an earlier commit scientifically
unsafe even though the outer 101-question test partition remained untouched.

### Hypothesis

A commit containing the real guardian digest, dev-A-only extraction, immutable
committed-ID selection, deterministic splits, and frozen analysis/scoring rules
will form an auditable pre-gold boundary. A second non-self-referential record can
bind that commit and its protected artifacts without altering them.

### Decision

Declare commit `7d39ee107338da1ce10e2553a4290e64bfc2f892` Freeze A Commit A.
Record its hashes separately before any dev-A label release. Keep database
infrastructure, the supporting manuscript, Beads export, and local OS metadata
outside this commit because they are not part of the frozen protocol payload.

### Rationale

The exact committed tree—not the larger shared worktree—is the reproducible
experimental state. Separating mutable infrastructure work prevents an unrelated
Neon lane from contaminating the protocol freeze, while the two-commit record
avoids a self-referential hash.

### Intervention

Pinned the externally generated guardian public-key digest, changed status
markers to frozen, explicitly staged 96 protocol/harness files, and verified the
result through a detached worktree created from the staged git tree. Added
`experiments/freeze-a.json` with Commit A and SHA-256 values computed from
`git show` bytes. Experiment ID: control-plane D-020; affected subsystem:
pre-gold experimental freeze. Change type: general evaluation-system integrity.

### Result

The exact Commit A tree passes 426 tests with 85.81% branch coverage, Ruff lint
and formatting, and a package build. It contains no excluded database-lane or
manuscript files, no unstaged tracked bytes, and no non-test secret-pattern
matches. Synthetic connection-string fixtures caused the deliberately broad
all-file scan to alert; a reviewed scan excluding those test fixtures found no
candidate secret. Post-commit `load_config` verification succeeds against the
full Commit A hash and committed guardian digest. Independent final code and
security reviews approve the custody change after the race regression. No
private label, gold SQL, hidden test case, or hidden knowledge annotation was
accessed.

### Interpretation

Freeze A now proves split integrity and development-label custody rather than
merely describing them. The most important review finding was not statistical:
security-sensitive evaluation metadata must be consumed from the same immutable
bytes that were verified.

### Outcome

KEEP

### Product implication

None for Omni yet. For evaluation harnesses, immutable content identity and
access-boundary observability are prerequisites for credible adaptive research.

### Next step

Commit the Freeze A record, then begin only public-data work: provision the
database canary, build the provenance-preserving HKB intermediate
representation, and generate the immutable public-only baseline outputs before
the human custodian releases dev-A labels.

## 2026-08-27 — D-021: Preserve the HKB as a strict dependency graph before semantic interpretation

### Decision / experiment

Create a public-only, deterministic HKB intermediate representation before
attempting any HKB-to-Omni semantic mapping.

### Observation

The 18 pinned public HKB files contain 1,090 natural-language definitions and
945 dependency edges. Source reconnaissance found 28 edges pointing to a higher
numeric ID, nonzero and gapped ID sequences, three duplicate knowledge names
within a database, seven CRLF files, nine files without a final newline, and
intentional Unicode and whitespace. The official reference agent's convenience
loader keys definitions by name and omits dependency/type information from its
agent-facing output, which would lose material source structure for this study.

### Hypothesis

A strict ID-keyed DAG representation will preserve the hierarchical business
knowledge needed for later semantic compilation while exposing ambiguity rather
than forcing premature measure/dimension decisions. Hash-binding source and
output bytes will make the mechanical baseline reproducible across machines.

### Decision

Use `<database>:hkb:<id>` as stable identity, parse the exact public six-field
schema, normalize only `-1` and `[]` as no dependency, resolve the complete graph
before output, and leave semantic representability unassessed. Reject duplicate
JSON keys, extra/protected fields, duplicate IDs/edges, dangling references,
self-edges, and cycles. Do not use knowledge names as keys and do not translate
natural-language formulas in this stage.

### Rationale

This is the smallest boundary that preserves what makes LiveSQLBench relevant
to Omni: business definitions compose. Directly emitting Omni YAML would mix
deterministic source handling with interpretive modeling decisions and make
LODO portability and provenance harder to audit. Reusing the official loader
would silently overwrite the three same-name definitions and flatten the graph.

### Intervention

Added a pinned 18-file public source inventory; bounded, verified-before-publish
source acquisition; no-follow regular-file reads; an immutable parser and
dependency compiler; contamination-rejecting deterministic per-database JSONL
and hash-bound manifest generation; a thin CLI; committed public IR artifacts;
and focused unit/integration tests. Experiment ID: public
baseline D-021; commit: this experiment commit; affected subsystem: HKB transformation. Change
type: general system improvement. Content provenance: public HKB. Intervention
provenance: mechanical baseline transformation.

### Result

The real build reproduces 18 databases, 1,090 definitions, 430 calculation
rules, 462 domain rules, 198 value illustrations, 509 `-1` sentinels, 21 empty
lists, 560 dependent definitions, 945 edges, and maximum depth 6. Synthetic
tests cover forward references, gapped IDs, duplicate names, CRLF/no-final-
newline input, Unicode/whitespace, malformed/private fields, graph corruption,
source hash/OID mismatch, path traversal, symlinked sources and outputs,
preexisting output contamination, deterministic regeneration, and output hash
binding. No private label, hidden annotation, benchmark question, or gold SQL
was accessed.

### Interpretation

The public HKB is structurally clean but cannot safely be treated as a flat
name-to-description dictionary. Dependency preservation is a necessary input to
the semantic-layer experiment; semantic interpretation remains the next—and
scientifically interesting—stage.

### Outcome

KEEP

### Product implication

For semantic-model import workflows generally, source identity and dependency
lineage should survive modeling. A UI or API that represents only display names
and descriptions can silently collapse distinct business concepts or hide
composition depth before an agent ever queries them. This is a design
implication from public structure, not yet a measured Omni product finding.

### Next step

Compile one public database's schema, column meanings, and HKB IR into a
conservative Omni extension bundle with explicit representability/loss records;
validate it locally and on an isolated Omni branch before fan-out.

## 2026-08-27 — D-022: Pin schema semantics before compiling Omni objects

### Decision / experiment

Add the official schema and column-meaning corpus to the public-only source
boundary before attempting the canary HKB-to-Omni compilation.

### Observation

The first canary has 54 HKB definitions, but its 51 tables include 14 JSONB
columns whose nested field names are not recoverable from the PostgreSQL catalog
alone. The previously committed HKB IR preserved business-definition lineage but
the repository did not yet pin the official `*_column_meaning_base.json` or
`*_schema.txt` objects. Catalog names alone could not support a defensible,
reproducible binding from several HKB definitions to nested fields.

### Hypothesis

Hash-pinning the official public DDL and column descriptions will make semantic
bindings reproducible and distinguish source semantics from later interpretive
mapping decisions. Excluding the public example rows embedded in the schema text
will retain necessary type and constraint information without adding accidental
value exemplars to the modeled baseline.

### Decision

Pin both public source kinds for every database at the same revision as the HKB,
require exact database-set parity, and verify the complete download before
publication. Use only DDL and column meanings in later compilation; do not expose
the schema files' example-row sections to the compiler or evaluated agents.

### Rationale

Compiling the canary immediately from catalog names would force undocumented
semantic guesses, while hand-copying only the fields needed by the canary would
make the source boundary selective. The complete 18-database inventory is small,
general, and required eventually. Parsing or modeling all 18 databases remains
deferred until one canary proves the representation contract.

### Intervention

Added a strict 36-object inventory, a bounded hash/OID-verifying downloader, a
row-separating structural inspection command, a thin CLI, artifact and
acquisition tests, and source-boundary documentation. An adversarial review
found that the shared nested-file publisher could overwrite an early database
before rejecting a later invalid destination; a RED regression reproduced the
mixed output and the publisher now preflights every child before replacing any
file. A second adversarial pass found that source files were no-follow and
bounded while the caller-selected inventory was not; shared HKB/schema inventory
reads now reject symlinks, nonregular files, inputs over one MiB, and excessive
structured-description depth. A final path audit reproduced an intermediate-
parent symlink escape and a canonical-source FIFO hang; the shared reader now
walks every absolute component through held no-follow directory descriptors and
opens final inputs nonblocking before checking that they are regular files.
Experiment ID: public baseline D-022; commit: this experiment commit; affected subsystem:
public semantic-source acquisition. Change type: general system improvement.
Content provenance: public schema and public column metadata. Intervention
provenance: mechanical baseline transformation.

### Result

The real fetch verified 6,003,364 bytes across 36 objects at revision
`a418e108d5cbb4cf9b783a928eff5e924ad2460d`. The corpus contains 971 DDL table
blocks, 17,749 top-level column descriptions, 212 structured JSON/JSONB
descriptions, 1,008 immediate structured fields, and 1,925 leaf descriptions at
maximum depth 3. All 18 database names match both the HKB inventory and
eligible-question population. Exact-size hash corruption, Git-OID mismatch,
late-source failure, and late-destination rejection are covered by regressions.
The final exact staged-tree gate passes 493 tests with 85.82% branch coverage,
Ruff lint/format, and package build. The larger shared worktree also passes 534
tests with one database canary integration test explicitly environment-gated.
Independent correctness, security, and
simplification reviews approve the lane after actively reproducing and closing
the partial-publication, symlink-parent, FIFO, and recursive-input failures.
No question text, private label, hidden annotation, or gold SQL was accessed.

### Interpretation

The semantic-model problem is not only HKB translation: column semantics and
nested-field identity are separate public inputs that must remain traceable.
The source corpus also contains public sample rows, so “public schema access”
must be operationally narrowed to DDL rather than treating the source file as an
undifferentiated prompt artifact.

### Outcome

KEEP

### Product implication

Semantic import tooling needs field-level provenance, especially for structured
columns that are opaque to warehouse catalogs. A model object should distinguish
metadata imported from a source description from an interpretation introduced
by the model author or transformation system.

### Next step

Compile a row-free, case-preserving schema/column intermediate representation
for the canary, then map that IR and the HKB dependency graph into a conservative
Omni extension with explicit representability and loss records.

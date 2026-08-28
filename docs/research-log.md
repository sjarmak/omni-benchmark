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
reproducible way to enforce the study's exclusion of CRUD work.

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
simple enough for this study.

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

## 2026-08-27 — D-006: Refocus on the research and product story

### Observation

The protocol had become rigorous enough that additional methodology risked
delaying the evidence the project requires: baseline behavior,
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
analysis required by the research questions.

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

## 2026-08-27 — D-023: Separate mechanical schema extraction from semantic interpretation

### Decision / experiment

Compile one row-free public schema IR before authoring any Omni objects or
binding HKB definitions to fields.

### Observation

The canary DDL contains quoted identifiers, composite keys, foreign keys,
defaults with casts and commas, and nested JSONB columns. A table counter was
enough for source reconnaissance but could not safely drive relationship or
field generation. The source files also interleave each DDL statement with
example rows that are outside the chosen baseline information boundary.

### Hypothesis

A real PostgreSQL parser behind an exact row-section splitter will preserve the
mechanical schema faithfully while preventing source examples or modeling
judgment from entering the semantic baseline unnoticed.

### Decision

Emit only table, column, structured-leaf, and declared-foreign-key records. Keep
primary and unique keys on table records. Bind the output to the public schema,
column meanings, and companion HKB IR, but defer every HKB-to-schema mapping to
a separate interpretive artifact.

### Rationale

A custom DDL grammar was rejected because defaults, constraints, and quoted
identifiers make comma/line splitting brittle. `pglast` was considered because
it wraps PostgreSQL's parser, but SQLGlot 30.17 parsed all 51 canary statements,
has a permissive MIT license, and provides the needed PostgreSQL AST without a
native dependency. Direct Omni YAML generation was deferred because it would
mix source extraction with choices about grain, formulas, and representability.

### Intervention

Pinned SQLGlot 30.17.0; added strict DDL/example-row separation, PostgreSQL AST
extraction, PostgreSQL-resolved identifier identity with source spelling and
quote-state provenance, typed JSON paths, PK/FK resolution, hash-bound
provenance, deterministic publication, a CLI build command, and a committed
canary IR. Experiment ID: public baseline D-023; affected subsystem:
schema-to-semantic transformation. Change type: general system improvement.
Content provenance: public schema and column metadata. Intervention provenance:
mechanical baseline transformation.

### Result

The committed canary IR contains 51 tables, 959 columns, 92 structured leaves,
51 primary keys, and 77 foreign keys across 1,179 records. Its JSONL SHA-256 is
`e2044dc11b055e08046153de8c9cec9d121f037391d5b757c8cd071dd607162f`.
Independent generation into two directories is byte-identical. Adversarial
tests put SQL-looking text and protected-key names in the example-row section;
none entered the output. The real canary counts, exact quoted identifiers,
relationship targets, companion HKB hash, and output hash are regression-tested.
No benchmark question text or hidden label was accessed.

### Interpretation

The public source data now has a reproducible boundary suitable for semantic
modeling. Any later join, metric, or HKB binding can be reviewed as an explicit
interpretation rather than being mistaken for extracted source truth.

### Outcome

KEEP

### Product implication

Semantic-model import needs a provenance boundary between warehouse facts and
model-author choices. This is an import/modeling principle, not yet an observed
Omni runtime finding.

### Next step

Create the reviewed HKB-to-schema mapping and loss manifest, then compile the
representable same-grain subset into an isolated Omni branch.

## 2026-08-27 — D-024: Require explicit grain before compiling HKB definitions

### Decision / experiment

Classify all 54 canary HKB nodes by public-only representability before emitting
derived fields.

### Observation

The HKB dependency graph composes definitions across point-cloud, mesh,
environment, registration, scan, processing, site, equipment, and conservation
tables. The public schema does not declare a shared scan/session identity across
the measurement tables. Several tables share project, person, site, or equipment
keys, but those paths can produce many-to-many fanout rather than a defensible
analytic grain.

### Hypothesis

Compiling every syntactically expressible HKB formula would create plausible but
semantically unsafe fields. A conservative classification should isolate a
useful same-row baseline and make the missing contracts visible.

### Decision

Compile only same-row dependency closures in the first canary model. Preserve
value illustrations as descriptions or synonyms. Mark cross-grain definitions
as ambiguous until a mapping specifies target grain, relationship path,
cardinality, deduplication/preaggregation, and zero/multiple-match behavior.
Keep missing or underspecified definitions explicitly unsupported.

### Rationale

One all-purpose Topic and inferred joins were considered and rejected because
they could silently change metric meaning. This project is testing semantic
governance; emitting unsafe joins merely to increase apparent knowledge coverage
would contradict that premise.

### Intervention

Performed a public-only node-by-node reconnaissance against the HKB IR, DDL, and
column meanings. No Omni model was changed in this step. Affected subsystem:
HKB-to-schema mapping policy. Change type: general modeling safeguard. Content
provenance: public HKB, schema, and column metadata. Intervention provenance:
human/general modeling inference.

### Result

The initial classification is 14 mechanically representable same-grain nodes,
10 context-only value illustrations, 20 cross-grain ambiguous nodes, and 10
currently unsupported nodes. The largest blocker is missing shared measurement
identity. Other blockers include a missing scan-duration field, unspecified
rarity/status mappings, source/HKB vocabulary mismatches, unit-bearing free text,
and entity-level existence/aggregation semantics. Dependency metadata also omits
concepts referenced in the prose of two definitions, so the dependency list
cannot be treated as a complete executable plan.

### Interpretation

Dependency preservation is necessary but not sufficient. Grain is the central
semantic contract for this canary, and honest non-representation is safer than
an executable formula on an invented join path.

### Outcome

KEEP

### Product implication

An HKB-import workflow should surface representability and grain conflicts
instead of maximizing imported-object count. This is a pre-runtime product
hypothesis to test during Omni upload and query planning, not yet evidence of an
Omni agent failure.

### Next step

Encode the classification and exact source bindings in a reviewable mapping/loss
artifact, then generate grain-focused Topics for the same-row subset.

## 2026-08-27 — D-025: Use AI Hub for diagnosis, not benchmark truth

### Decision / experiment

Define Omni AI Hub's role before the first authenticated C4 canary run.

### Observation

AI Hub provides the product-native workflow for governed-agent session
inspection, prompt sets, accuracy-judge evals, and branch comparison. The
LiveSQLBench study, however, defines correctness by executed result-set parity
under external custody and scoring. Conflating those evaluators would make the
benchmark dependent on a product judge with a different objective.

### Hypothesis

Using AI Hub for rapid mechanism diagnosis while retaining independent execution
correctness will improve both iteration speed and product insight. Preserved
judge/execution disagreements may reveal observability, validator, or evaluation
gaps that a single scoring surface would hide.

### Decision

Use AI Hub where useful to inspect representative C4 failures, compare isolated
branches, and run small failure-class prompt sets. Do not mirror all `dev-A` in
AI Hub, expose hidden annotations, or promote a change solely from its judge.
Promising candidates must pass external `dev-A` and regression gates; `dev-B`
usage remains checkpoint-only.

### Rationale

Ignoring the native workflow would reduce production fidelity and miss a core
product question: can an Omni user see and fix the failure? Making AI Hub the
benchmark judge would weaken the independent execution claim. The two-surface
design retains both advantages without rebuilding unnecessary parallel tooling.

### Intervention

Added the AI Hub responsibility boundary, preferred C4 loop, eval-set provenance
requirements, first-live-run telemetry inventory, and product-learning matrix.
Bead: `omni-benchmark-dih.13`; affected subsystem: C4 diagnosis and product
evaluation. Change type: general evaluation/product workflow. No model or
experimental condition changed.

### Result

Documentation now names external execution as authoritative and treats AI Hub
outcomes as diagnostic evidence. No authenticated AI Hub session or eval has run;
the live comparison remains gated on the isolated public-only canary model and
database connection.

### Interpretation

The benchmark can evaluate both Omni's governed system and the workflow customers
use to improve it, without allowing a native judge to redefine correctness.

### Outcome

FOLLOW UP

### Product implication

The first canary will test whether AI Hub exposes enough context, retrieval,
compiler, validation, and telemetry evidence to move from a wrong result to a
reusable fix—and whether its judge agrees with execution-based correctness.

### Next step

After isolated upload/read-back, run one representative C4 question, inventory
AI Hub visibility against the trace contract, and record the first evidence-backed
product finding or explicit observability gap.

## 2026-08-27 — D-026: Make HKB representability explicit before Omni compilation

### Decision / experiment

Create a complete public-only HKB-to-schema mapping/loss artifact for the canary
before generating any Omni semantic objects.

### Observation

Fourteen of the 54 public HKB nodes have a plausible same-table representation,
and ten value illustrations can enrich existing field context. The other 30
definitions either span tables without a declared shared analytic identity or
contain missing, inconsistent, redundant, or underspecified semantics. Declared
foreign keys do not supply the grain, cardinality, deduplication, or zero/many
behavior required to compile those definitions safely.

### Hypothesis

If every HKB node receives one hash-bound disposition with exact schema inputs,
dependency handling, loss reason, and provenance, the first semantic model can
be useful without silently inventing cross-grain answers. The loss distribution
will also identify whether the main import bottleneck is expression support or
missing modeling contracts.

### Decision

Represent all 54 nodes exactly once as one of: compile a same-grain semantic
field, attach public context to a source field, defer pending a cross-grain
contract, or reject as currently unsupported. Keep formula compilation separate
from this classification so Omni syntax choices cannot change the source-level
representability record.

### Rationale

Compiling every parseable formula would maximize object count while obscuring
fanout and aggregation risk. Compiling nothing would avoid risk but fail to test
the semantic-layer premise. A complete mapping/loss ledger makes the boundary
reviewable and preserves the evidence needed to improve the transformer later.

### Intervention

Added a deterministic validator, reviewed 54-record mapping specification, and
hash-bound expanded mapping artifact. Each record binds the public HKB node,
exact public schema stable IDs, dependency mode, intended representation, loss
codes, relationship requirements, generality, and content/intervention
provenance. Bead:
`omni-benchmark-dih.12`; affected subsystem: HKB-to-semantic transformation.
Change type: general transformation method plus legitimate database modeling.

### Result

All 54 HKB nodes are classified exactly once: 14 `compile`, 10 `context_only`,
20 `defer_cross_grain`, and 10 `unsupported`. The expanded mapping SHA-256 is
`a54234cf768619bd15260a87ff3cd55765d006eaa4bd20bc05fd427ed24eeae6`.
The artifact records two omitted dependencies (H16→H29 and H42→H12), one
redundant dependency (H52→H26), exact/medium-confidence schema bindings, and
the grain/cardinality/aggregation contracts needed before deferred definitions
could be compiled. It regenerates byte-for-byte from the reviewed spec and the
committed public HKB/schema IRs. No question text, gold SQL, hidden annotation,
or development outcome is an input.

### Interpretation

The main canary bottleneck is not formula syntax. It is absent analytical grain
and relationship semantics: declared entity foreign keys do not identify which
point-cloud, mesh, registration, scan, environment, and processing rows belong
to the same acquisition. This supports a conservative first model containing
the 14 same-grain fields and 10 context annotations while preserving the other
30 definitions as explicit losses.

### Outcome

KEEP

### Product implication

Semantic-model import should expose unsafe or unrepresentable business knowledge
as a first-class result instead of silently dropping it or emitting a plausible
field. The live Omni canary will determine whether the product can preserve and
surface these distinctions during authoring and agent diagnosis.

### Next step

Compile only the approved same-grain/context subset into a local Omni extension,
validate it, then upload/read it back on an isolated canary branch.

## 2026-08-28 — D-027: Require dependency-bound formulas before live upload

### Decision / experiment

Strengthen the public semantic compiler, commit the canary bundle, and begin the
isolated Omni upload sequence.

### Observation

Final review found that dependency order alone did not prove that a compiled
formula used its declared HKB dependencies. The ECCS definition declared both
ESI and Optimal Scanning Conditions but reconstructed the latter from ESI. The
publication boundary also hash-bound the mapping manifest without checking its
public-only/no-hidden validation claims.

### Hypothesis

If executable formulas must reference exactly their non-redundant compiled HKB
dependencies, the bundle will preserve composition rather than merely preserve
ordering. If the upstream manifest's trust assertions are verified explicitly,
the bundle cannot relabel a failed or hidden-input mapping as public-only.

### Decision

Add fail-closed dependency-reference and upstream-manifest validation before any
live upload. Treat redundant dependencies recorded by the mapping audit as
non-executable edges. Do not weaken the custody boundary because the private gold
attachment has arrived; it remains unopened and undownloaded.

### Rationale

Dependency composition is central to the benchmark's semantic-layer question.
Uploading an artifact that only appeared compositional would make later product
behavior uninterpretable. The changes are reusable compiler contracts rather
than question- or benchmark-answer-specific fixes.

### Intervention

The compiler now rejects missing and undeclared derived-semantic references,
validates the upstream mapping schema/version/public-only state and provenance
fields, and expresses ECCS through the modeled Optimal Scanning Conditions
field. Bead: `omni-benchmark-dih.12`; commit: `4622f0f`; affected subsystem:
public HKB-to-Omni compilation. Change type: general system improvement plus
legitimate database modeling.

### Result

Exactly 14 derived fields and 10 context annotations regenerate byte-for-byte;
all 11 executable dependency edges are present and ordered. Full gates passed:
663 tests, one explicit public-PostgreSQL integration skip, 84.90% branch
coverage, lint/format/build/secret scan, and independent code, security, and
simplification reviews. The bundle-manifest SHA-256 is
`ba441ace28dc730508bf8de1771b18a61e83eec5050f8d44a4643bc83cfbe76d`.

The isolated Omni schema-model record was then created. Both its default hard
refresh and a public-only soft refresh failed; the status API exposed only
`FAILED`. Shared-model creation could not proceed because the schema model was
not usable. No shared model or branch was created, and no existing model was
modified.

### Interpretation

The local public-only baseline is now strong enough for product validation. The
current blocker is live connection/schema-refresh integration, not semantic
bundle compilation. The lack of a diagnostic error from the refresh status
surface is itself an early workflow-observability finding, but not evidence about
agent accuracy.

### Outcome

FOLLOW UP

### Product implication

Model authors need actionable schema-refresh failures—especially when setting up
least-privilege production connections. A terminal status without a cause makes
credential, permission, network, and introspection failures indistinguishable.

### Next step

Have the infrastructure lane verify the Omni-stored reader connectivity after
active restores complete, then retry one schema refresh. Once it succeeds,
create the isolated shared model/branch, upload, validate, read back, and run the
public-only canary.

## 2026-08-28 — D-028: Harden sealed scoring before private data exists

### Decision / experiment

Implement and adversarially review the PostgreSQL execution boundary using only
public and synthetic fixtures.

### Observation

The frozen result comparators did not yet define a safe database lifecycle for
generated SQL, official-versus-sensitivity row caps, independent candidate/gold
state, or the generate-all-before-score seal. Initial implementation reviews
found several ways a superficially correct evaluator could produce invalid or
unsafe results.

### Hypothesis

A disposable-clone lifecycle with restricted execution identities, explicit
query admission, exact official compatibility, and immutable aggregate artifacts
can score private records later without exposing labels or allowing candidate SQL
to affect the gold execution.

### Decision

Build the live adapter now, but test only against synthetic fixtures and a
separate disposable PostgreSQL 18 container. Treat security and correctness
review failures as blockers rather than deferring them to Freeze B.

### Rationale

The gold package is available by email but remains unopened. This is the best
time to test the sealed boundary: any accidental dependency on hidden data is
impossible, and evaluator behavior can still be corrected without observing a
benchmark outcome.

### Intervention

Added typed PostgreSQL execution, independent candidate/gold template clones,
restricted-role attestation, fail-closed Query-only admission, client-owned
timeouts, official and sensitivity scorer transports, closed failure taxonomy,
transient-only reruns, complete-batch prevalidation, and an exact 1,212-output
generation gate. Bead: `omni-benchmark-dih.10`; commit: `0c6f46a`; affected
subsystem: sealed evaluation and scoring. Change type: general system
improvement.

### Result

The first reviews blocked the implementation because candidate SQL ran with
administrative credentials, candidate and gold could share mutated state, no
result was conflated with an empty result, 10,000-row prefix truncation could
hide unequal tails, artifacts could expose rows or arbitrary failure text, and
late invalid batch records were discovered only after thousands of isolate
acquisitions. A later review showed that transaction read-only settings were not
a security boundary because a role could alter its own session or identity. The
next review caught an incorrect attempt to make the official scorer safer by
changing its truncation semantics, which would have broken benchmark
comparability. A final operational review found ambiguous clone creation could
leave an orphan database.

Each finding received an adversarial regression and a narrower fix. Final gates:
730 tests passed, three explicit opt-in skips, 85.15% branch coverage, two live
PostgreSQL 18 checks, lint/format/build/secret/dependency scans, and independent
code and security approval with no remaining findings.

### Interpretation

Evaluator correctness is part of the experiment, not plumbing. “Run both SQL
queries and compare rows” was insufficient: isolation, privilege boundaries,
overflow policy, failure ownership, artifact redaction, and compatibility each
changed what result could legitimately be reported. Keeping official and
sensitivity policies separately named preserves both comparability and a safer
robustness analysis.

### Outcome

KEEP

### Product implication

This is primarily benchmark infrastructure, not an Omni product finding. It does
reinforce that governed analytical systems should expose whether a failure came
from query admission, execution, validation, infrastructure, or comparison; a
single incorrect/error bucket would hide materially different operator actions.

### Next step

Bind the evaluator and scorer versions into Freeze B. Until then, keep the gold
attachment outside the workspace and continue the public-only C4 baseline once
the Omni connection refresh succeeds.

## 2026-08-28 — D-029: Build one traceable direct-SQL spine for C1–C3

### Decision / experiment

Implement the missing C1–C3 attempt producer as a shared provider-neutral,
harness-owned tool loop before selecting a live model adapter.

### Observation

The frozen validation, telemetry, manifest, custody, and sealed-scoring layers
already accept all four conditions, but only C4 can produce a real attempt. A
focused audit found that C1–C3 exist only as protocol concepts and synthetic
records. The local reference harnesses show that authoritative stream usage,
partial-output recovery, immutable publication, and trace-derived tool counts
are reusable patterns; none supplies the full SQL/query/retry/validation
contract needed here.

### Hypothesis

If one small harness owns condition-specific tool dispatch, Query-only SQL
admission, read-only execution, and trace accounting, C1–C3 can become competent
comparators without duplicating the scorer or trusting provider-reported tool
totals. Keeping the provider boundary replaceable should let us choose a pinned
Claude or Codex OAuth transport from live evidence rather than baking one CLI
into the experiment core.

### Decision

Add a shared direct-SQL capture and attempt layer for C1–C3. C1 may access only
schema and database tools; C2 adds the public database-level HKB; C3 instead adds
the exported Omni semantic model as optional reference. The harness will reject
unauthorized tools structurally, derive operational counts from actual dispatch,
and preserve null rather than inventing zero when provider telemetry is absent.
Do not refactor the working C4 path, alter the protocol, or build a generalized
optimizer framework.

### Rationale

This is the smallest change that unlocks the four-condition smoke gate and
later baseline runs. It also protects the intended ablation: C1–C3 share one
execution scaffold while differing only in the preregistered semantic resources.
Alternatives considered were opaque adapters that self-report aggregate traces,
which weaken auditability, and adopting a full agent SDK, which adds cost and
surface area before it solves a demonstrated problem.

### Intervention

Bead `omni-benchmark-dih.5.4.2`; optimization surface: structural harness;
candidate-generation method: trace-contract and reference-implementation audit;
change type: general system improvement. The first slice is test-first and owns
only SQL admission, direct capture, direct attempt serialization, and focused
synthetic tests. Live provider and public context adapters follow as separate
changes.

### Result

The provider-neutral core now emits a condition-bound trace, capture receipt,
typed result sidecar, normalized attempt, and run manifest. The harness exposes
only the preregistered tools for each condition, shares Query-only SQL admission
with the scorer, requires an independently attested read-only database transport,
and binds every published artifact to the exact attempt, question, condition,
provider/model, turn ceiling, SQL, and artifact root.

The implementation did not pass review on the first attempt. Independent reviews
found valid cross-attempt artifact substitution, premature turn-limit claims,
non-finite and negative telemetry, fabricated failure classifications and usage,
and a late manifest-validation path that could strand an immutable partial run.
Each finding received an adversarial regression and a minimal fix. The final full
suite passes 823 tests with three opt-in integration skips and 84.97% branch
coverage; the final affected suite passes 150 tests. Ruff, formatting, diff,
package-build, independent code review, independent security review, and a scoped
secret scan pass. No private package, benchmark labels, question outcomes, or
hidden annotations were accessed. The user confirmed that the gold attachment
remains unopened and undownloaded outside the workspace.

### Interpretation

A traceable comparator requires more than recording what the harness says it
did. Publication must independently reconcile lifecycle, capability, counts,
telemetry, and artifact identity against the configured attempt. The adversarial
review trajectory materially strengthened the audit claim without changing the
experimental conditions or adding benchmark-specific behavior.

### Outcome

KEEP

### Product implication

Not yet an Omni product finding. This comparator instrumentation is necessary to
distinguish gains from business knowledge, semantic representation, and governed
production behavior without treating unobservable scaffold differences as
negligible.

### Next step

Commit the reviewed core, then add committed public context providers and a
restricted Claude transport. Run one unscored `archeology_scan_3` C1/C2/C3
canary after the direct Neon reader credentials are available outside git.

## 2026-08-28 — D-030: Prefer a restricted Claude transport for direct comparators

### Decision / experiment

Audit the installed Claude and Codex OAuth CLIs as candidate transports for the
shared C1–C3 direct-SQL harness without making a model call.

### Observation

Both CLIs expose structured JSONL usage events, but their isolation surfaces are
not equivalent. Claude Code 2.1.250 can run in restricted mode with only an
explicit MCP allowlist while retaining OAuth. The installed Codex CLI does not
expose a verified way to remove shell execution while retaining MCP tools, and
the convenient `codex` launcher on this host is a Gas City wrapper that injects
unrelated configuration. Reference traces also showed that repeated Claude
assistant events can duplicate per-message usage, so truncated-stream token
recovery must deduplicate message identities rather than sum events naively.

### Hypothesis

A pinned restricted Claude CLI with a private per-slot configuration directory
and credentials held outside the model-visible tool server will give C1–C3 the
same capable model and tool loop without exposing shell, filesystem, database
credentials, or ambient project customizations. Terminal provider usage should
make cost and token telemetry more complete than the current alternatives.

### Decision

Use the exact Claude Code 2.1.250 binary as the first live C1–C3 adapter candidate,
subject to one public-only canary. Pin its binary hash, model identifier, effort,
turn limit, structured output schema, MCP inventory, and advertised tool surface.
Use a scrubbed environment and per-slot OAuth state; keep database credentials in
the supervised tool server. Do not use fallback models, session continuation,
ambient skills/hooks, or the host's Codex wrapper. This is a provisional
transport choice, not a claim that Claude is more accurate.

### Rationale

The deciding factor is credential and capability isolation, not expected model
score. The direct comparator must be competent without gaining access to hidden
files or unrelated tools. Building a new containerized Codex credential broker
would not improve the core research evidence enough to justify delaying the
baseline.

### Intervention

Read-only audit of installed CLI help, binary identities, EnterpriseBench
invocation patterns, and codeprobe OAuth/telemetry handling. Bead:
`omni-benchmark-dih.5.4.2`; optimization surface: structural harness; change type:
general system improvement. No provider call or repository runtime change was
made.

### Result

The candidate binary is
`/home/ds/.local/share/claude/versions/2.1.250`, SHA-256
`2be252a00ac56e704d7fbf7e5e9ef1243584093334a861945238a0c27e84bdac`.
The canary must still verify restricted MCP access, the exact advertised tool
set, structured output, observed model identity, terminal usage/cost fields,
timeout recovery, and per-slot OAuth concurrency. No accuracy or cost result
exists yet.

### Interpretation

Harness parity is not just a prompt/model choice. Credential placement,
model-visible tools, retry ceilings, and telemetry semantics are part of the
evaluated scaffold and must be disclosed even when C1–C3 share one model.

### Outcome

FOLLOW UP

### Product implication

This is comparator infrastructure rather than an Omni product finding. It
reinforces why C4−C3 remains a system-level, scaffold-conditional comparison
unless Omni exposes enough of its managed model and tool workflow to establish
true parity.

### Next step

Add the committed condition/configuration and public-context adapters, then test
the restricted transport against recorded provider envelopes. The first live
call remains one unscored public canary; scaled context and concurrency decisions
will use its observed cost, token, tool-surface, and latency evidence.

## 2026-08-28 — D-031: Bind every direct attempt to one runtime identity

### Decision / experiment

Replace the direct comparator's independent question, database, context,
provider, model, and budget labels with one frozen end-to-end runtime binding.

### Observation

The public context, restricted Claude transport, and attested PostgreSQL
transport each passed their local contract tests, but an adversarial integration
review showed that their identities were not preserved through capture and
publication. A valid attempt could be produced with an arbitrary question,
substituted condition callback, wrong audited database, or provider/model labels
that did not match the realized Claude transport. The same review found four
independent issues: PostgreSQL TLS modes without hostname verification, accepted
positive web-search telemetry, a path verification-to-execution race, and
result-adaptation errors mislabeled as database infrastructure failures.

### Hypothesis

A small immutable value constructed from committed public inputs, exact adapter
identities, and fixed budgets will make substitution mechanically detectable
without coupling the core harness to the current Neon or Omni inventory formats.
Keeping TLS, web-search, executable pinning, and failure taxonomy as separate
local fixes should preserve experimental interpretability and reduce migration
risk.

### Decision

Introduce `DirectRuntimeBinding` from five exact components: committed question,
public semantic context, database target/fingerprints, realized model adapter,
and budget. Remove free runtime question/provider/model/callback labels from the
capture path. Context, model, and database adapters must expose immutable
identities that exactly match the binding before work begins and at their use
boundaries. Carry the full binding and its canonical digest through the probe,
receipt, attempt publisher, and generation artifact.

The core remains inventory-agnostic: a later preflight translates a committed
database record into a generic content-addressed database identity. The
development question loader supports only train, dev-A, and dev-B; test remains
outside this capability. Local security fixes land before the cross-cutting
migration.

### Rationale

Adding more pairwise string comparisons was considered and rejected because it
would preserve multiple sources of truth. Making capture parse the Neon inventory
was rejected because it couples benchmark mechanics to a mutable provider shape.
Treating the adapters as locally trustworthy was rejected because the published
receipt would still overstate what actually ran. One canonical binding keeps the
mechanism small and gives the sealed publisher an independently recomputable
claim.

### Intervention

Bead `omni-benchmark-dih.5.4.2.4`; optimization surface: structural harness and
evaluation custody; candidate-generation method: adversarial security review plus
independent architecture review; change type: general system improvement. This
decision changes no benchmark split, endpoint, scorer, or supervision policy.

### Result

Pending implementation. The exploit cases are preserved as required regression
tests. No live provider/database call, private package, hidden annotation, gold
answer, or correctness result was accessed.

### Interpretation

Local provenance is not end-to-end provenance. A trustworthy attempt must prove
that the committed question, semantic representation, physical data target,
model process, and budgets all refer to the same invocation.

### Outcome

FOLLOW UP

### Product implication

This is primarily benchmark-harness hardening. The analogous product opportunity
is a native run identity that links an Omni agent session to the exact model
revision, semantic-model revision, connection target, validation path, and
result artifact without requiring external reconstruction.

### Next step

Land the four independent local fixes, implement the binding and committed
development-question loader, then migrate capture and publication before any live
C1-C3 canary.

## 2026-08-28 — D-032: Make direct-attempt preparation a dev-A-only capability

### Decision / experiment

Replace caller-asserted direct-comparator dependencies with one committed,
dev-A-only preparation capability, and adversarially review it before any live
comparator call.

### Observation

The first integrated security review did not approve the implementation. It
demonstrated four distinct boundary failures: an untracked runtime file could be
attributed to the recorded commit; an artifact store from another workspace was
accepted; mutable Claude timeout/runner and PostgreSQL connector state could
change after authorization; and the ordinary per-question factory could select
`train` or `dev-b`, bypassing the checkpoint control plane. The review also
showed that a test-only arbitrary-authority mint was shipped in the production
module.

Separately, the committed database-identity loader cannot yet run against the
real inventory. The infrastructure-owned inventory is still an uncommitted
format-v2 artifact and lacks the credential-free physical-database and
connection-target digest required to authenticate a live target.

### Hypothesis

A single dev-A-only factory that verifies clean executing source, workspace,
store, committed question/context/database inputs, and transport execution state
will close the accidental-leakage and provenance gaps without adding benchmark
policy to the model-facing harness.

### Decision

Ordinary direct attempts are restricted to `dev-a`. The one-time 231-question
public baseline and guardian-controlled dev-B checkpoints will require separate,
metered orchestration capabilities; they are not aliases of the ordinary
per-question factory. The production module no longer contains an arbitrary
test mint. Tests exercise the committed factory with external adapters patched
only inside the test suite.

Transport authorization now covers not only model/database object and method
identity, but the mutable state that can change execution: Claude configuration
and runner, plus PostgreSQL connector, connection configuration, attestation,
and database identity. These values are rechecked around external boundaries.

### Rationale

Relying on the final publisher to detect a mislabeled run was rejected because
the model or database call would already have occurred. Treating dev-B as an
ordinary development scope was rejected because it would make the guardian an
optional convention. Keeping the arbitrary test mint was rejected because it
made the production capture capability indistinguishable from a synthetic one.

### Intervention

Bead `omni-benchmark-dih.5.4.2.4`; optimization surface: benchmark harness and
custody mechanism; change type: general system improvement. Primary modules are
`direct_prepared_attempt.py`, `direct_database_loader.py`, the restricted Claude
and PostgreSQL transports, and the direct capture/publisher contracts.

### Result

The first security review was a failed gate and no commit was made. After the
intervention, 309 focused adversarial and integration tests pass. The complete
suite before the final follow-up review passed 1,103 tests with three explicit
live-integration skips and 85.06% branch coverage. The follow-up independent
review is pending. No live comparator invocation, hidden annotation, private
gold package, or correctness result was accessed.

### Interpretation

Content-addressing inputs is insufficient when the code, output root, or mutable
transport state can diverge after the hash is recorded. Development-partition
custody is likewise a capability-design problem, not merely a naming
convention.

### Outcome

FOLLOW UP

### Product implication

An Omni-native immutable run identity should bind the semantic revision,
connection target, agent/model stages, budgets, validation path, and artifacts.
For evaluation workflows, access to checkpoint sets should be represented as a
separate auditable capability rather than another scope string accepted by the
same runner.

### Next step

Require the follow-up security/code/simplification reviews to reproduce the
original exploits, then commit the direct runtime checkpoint. Coordinate the
credential-free inventory extension with the database-infrastructure lane before
the first live C1-C3 canary.

## 2026-08-28 — D-033: Treat product validation as the semantic compiler gate

### Decision / experiment

Upload the byte-authenticated public archeology bundle to one isolated Omni
branch and require product-native validation before any semantic query or AI Hub
inspection.

### Observation

All 14 local bundle files matched commit `4622f0f` and manifest SHA-256
`ba441ace28dc730508bf8de1771b18a61e83eec5050f8d44a4643bc83cfbe76d`.
The files uploaded successfully, but Omni validation rejected the 29 executable
dimensions. It also revealed that flat local names such as
`archeology_scan_large.public__pointcloud.view` create a new logical view rather
than extending the schema-model file
`archeology_scan_large.public/pointcloud.view`. PostgreSQL JSON extraction with
`->>` was rejected by Omni's SQL parser, and dependent expressions then failed
validation as well.

### Hypothesis

The semantic content is not the immediate failure. The deployment mapping is
targeting the wrong model path, and the dialect-specific JSON leaf expressions
need Omni's documented `DO NOT PARSE` escape while ordinary derived expressions
remain parser-validated. Correcting those two mechanical compiler/deployment
rules should make the same public definitions validate without weakening checks
for general expressions.

### Decision

Stop before query generation or AI inspection. Test the narrow JSON-parser
hypothesis on the isolated branch, then encode the successful rule with tests and
regenerate a new committed public-only bundle. Do not use `DO NOT PARSE` for all
fields and do not proceed with a partially valid model.

### Rationale

Suppressing validation globally would hide genuine expression errors. Removing
the executable fields would make the canary pass while defeating the research
question. A one-class parser exception plus an explicit local-to-Omni deployment
path is the smallest reusable intervention that distinguishes representation
failure from content failure.

### Intervention

Bead `omni-benchmark-dih.12`; optimization surface: HKB-to-semantic-model
compiler and deployment adapter; change type: general system improvement.
External scope remains the authorized isolated archeology branch only.

### Result

IN PROGRESS. Initial validation produced 29 `unparseable_sql` errors; no query,
AI Hub evaluation, benchmark correctness judgment, hidden annotation, or gold
data was used.

### Interpretation

Local syntactic validation was necessary but not sufficient. Omni model path
identity and product-dialect parsing are part of semantic compilation and must be
verified against the running product before scaling to 18 databases.

### Outcome

FOLLOW UP

### Product implication

The validation errors precisely identify each affected field, but the API does
not explain that the uploaded filename created a parallel logical view instead
of extending the schema view. A deployment-time warning for near-duplicate view
names or non-extending files would prevent a subtle class of apparently
successful model uploads.

### Next step

Verify the narrow parser exception on one view, then implement and regression-test
the deployment mapping and semantic compiler rule before repeating full branch
validation.

## 2026-08-28 — D-034: Freeze topic joins explicitly

### Decision / experiment

Require semantic readback, not only zero validation errors, before accepting the
public-only Omni branch.

### Observation

All seven corrected view extensions uploaded to schema-model paths and full model
validation returned zero issues. Semantic readback matched the pointcloud view,
but the pointcloud topic did not match its source artifact: Omni inserted joins
to `personnel` and `projects`. Omni documentation states that newly created
topics include joinable many-to-one and one-to-one tables by default. The local
topic selected only base-view fields and claimed that it modeled no cross-table
joins, but it did not explicitly declare an empty `joins` map.

### Hypothesis

An explicit `joins: {}` is required to freeze a generated single-view topic.
If so, adding this mechanical property to every no-join topic should prevent
product defaults from expanding the semantic surface while preserving the
existing field curation and AI context.

### Decision

Test the empty map on the isolated pointcloud topic before changing the compiler.
Do not accept zero model-validation errors as evidence of exact semantic
readback, and do not weaken the comparison to ignore product-added joins.

### Rationale

The joins are not necessarily invalid, but they contradict the preregistered
conservative no-join baseline and introduce unreviewed relationship semantics.
Readback is the only gate that revealed the difference.

### Intervention

Bead `omni-benchmark-dih.12`; optimization surface: topic generation and product
deployment semantics; change type: general system improvement. The diagnostic
uses only the authorized isolated public archeology branch.

### Result

IN PROGRESS. Product validation is clean, but 1/1 inspected topic readbacks has
unrequested joins. No AI call, benchmark question, correctness judgment, hidden
annotation, or gold data was used.

### Interpretation

A semantically valid model can still differ materially from its source bundle.
Generated semantic models need content readback that covers inferred product
defaults, not just YAML checksums and validator status.

### Outcome

FOLLOW UP

### Product implication

Automatic join inclusion is convenient for interactive modeling but risky for
programmatic/governed model generation. The upload/readback workflow should make
inferred topic joins explicit or offer a freeze-defaults mode.

### Next step

Test `joins: {}` on pointcloud, then encode and validate the rule across all
seven public-only topics if it suppresses the inferred joins.

## 2026-08-28 — D-035: Accept the public-only governed canary

### Decision / experiment

Complete the authorized archeology C4 canary only after compiler fixes, exact
semantic readback, one governed query, and one unscored AI Hub diagnostic.

### Observation

The explicit empty join map suppressed Omni's default topic expansion. The
corrected bundle at commit `dc05b6b7ea61d256d54e4077a97884297ffa57a4`
and manifest SHA-256
`761371f4eebef183cdf54cbbd5f146ebb67652ebcf72aeb6623eb79f70390802`
uploaded to the isolated branch. Product validation returned zero issues, and
all 14 artifacts matched semantic readback after only two documented Omni
normalizations: YAML formatting/comments and removal of inherited
catalog/schema/table keys from schema-view extensions.

### Hypothesis

If the public HKB definitions are genuinely executable through the semantic
layer, a topic query should compile and execute the deepest modeled pointcloud
boolean without reconstructing its formula, and the production agent should
select that same field when explicitly asked to use it.

### Decision

Use `is_premium_quality_scan`, which depends on multiple modeled fields, for the
single read-only semantic query and AI Hub diagnostic. Do not judge benchmark
correctness or run a benchmark question.

### Rationale

A base-column count would prove connection health but not semantic composition.
The chosen field tests JSON leaf extraction, recursive same-grain dependencies,
topic discoverability, semantic compilation, database execution, and production
agent selection in one small public canary.

### Intervention

Bead `omni-benchmark-dih.12`; branch
`a1adff15-282b-4c35-be59-123fa6ed681b` of isolated model
`c947be84-92d4-418d-8f80-4a7d9ce1f181`; optimization surfaces: semantic
compiler, topic generation, governed query path, and AI Hub observability;
change type: general system improvement plus legitimate database modeling.

### Result

KEEP. The governed semantic query grouped 697 pointcloud rows into 680 false and
17 true values and issued no raw SQL. This is an execution canary, not a
correctness score. The first request was rejected before query execution because
the CLI request schema advertised cache values that the live endpoint did not
accept; replacing `disabled` with the live value `SkipCache` produced the one
executed canary.

The AI Hub job completed with one successful `generate_query` action and one
`summarize` action. Its generated query selected exactly
`is_premium_quality_scan` and `count` through `pointcloud_semantics`, returned
two rows without truncation, and did not reconstruct the metric. The response
exposed Bedrock model `claude-opus-5`, one tool call, one database query, total
duration 7,233 ms, LLM duration 6,302 ms, query duration 352 ms, 4 input tokens,
250 output tokens, 79,585 cache-read tokens, and 80,087 cache-write tokens. It
did not expose cost, retries, or validation-attempt counts. The response body
SHA-256 was
`960cfbeba89022944bba2fcbd569a8948b521d4bc8c388d8fc1b92ab066b781d`;
the product retains the underlying AI Hub session. No gold, hidden annotation,
test outcome, or AI judge was used.

### Interpretation

The mechanical public-only transformation can produce an executable governed
semantic chain, but local compilation was insufficient: three product-specific
details had to be learned from the canary—schema-model file paths,
dialect-parser escape syntax, and explicit suppression of default joins. AI Hub
provides substantially more model/cost telemetry than the earlier synthetic C4
contract assumed, but it still leaves important retry/validation fields opaque.

### Outcome

KEEP

### Product implication

The native workflow can expose the selected semantic query, topic, model/provider,
token buckets, tool count, query count, and timings. That is useful for C4
diagnosis. The same run also exposed three integration gaps worth product
feedback: silent near-duplicate view paths, implicit topic joins, and drift
between the CLI request schema and live cache enum. Additionally, the supposedly
unformatted JSON semantic-query response represented the count as a string,
which matters for execution-result scoring and typed downstream consumers.

### Next step

Commit the pure deployment/readback adapter and canary documentation, update the
C4 trace contract with the telemetry fields now observed, then use the same
public-only gate before any multi-database bundle fan-out or scaled baseline.

## 2026-08-28 — D-036: Land the direct comparator and move isolation to the driver

### Decision / experiment

Commit the reviewed C1–C3 runtime checkpoint, then resolve the remaining
invocation-isolation and cross-condition parity concerns in the required
executable driver rather than adding another identity layer.

### Observation

The direct-SQL implementation, condition configurations, database target
bindings, and tests were complete but uncommitted and had no executable entry
point. Independent review found no credential or SQL-admission blocker. It did
find that caller-owned Claude working and temporary directories could affect
behavior without appearing in the persisted model identity, and that parity was
recorded per attempt but not yet enforced across the C1–C3 matrix.

### Hypothesis

A driver that creates fresh empty private work and scratch directories for every
attempt and loads one committed model/budget/retry policy for all three direct
conditions will remove the practical contamination path and enforce comparator
parity without expanding the control plane.

### Decision

Land the current library and tests. Require the driver and public canary to prove
per-attempt directory isolation and C1–C3 model/budget parity before any scaled
run. Do not add another attestation or replay-protection layer. Do not add tests
solely to satisfy an alternate per-module coverage denominator: the repository's
branch-enabled suite remains the governing coverage check.

### Rationale

The observed risk occurs at invocation construction, which the missing driver
must own. Fixing it there is smaller and easier to audit than threading another
digest through every artifact. It also advances the actual blocker: producing a
real, traceable comparator attempt.

### Intervention

Committed the direct runtime, C1–C3 configurations, all-18 target sidecar, trace
contracts, and tests in `459d3ce`. Added the driver constraints to Bead
`omni-benchmark-dih.5.4.2.5`. Change type: general system integration; affected
surface: direct-comparator execution harness.

### Result

The independent code gate reported 442 focused tests and 1,218 full-suite tests
passing, with 84.85% repository branch coverage. The independent security gate
reported 241 adversarial tests passing and no critical or high-severity finding.
Ruff, formatting, whitespace, and staged secret scans passed. No model call,
gold data, hidden annotation, or correctness result was accessed.

### Interpretation

The comparator library is now reproducible from Git, but it is not yet a runnable
benchmark condition. The next evidence must be an actual canary, not more control
plane code.

### Outcome

KEEP / FOLLOW UP

### Product implication

Behaviorally relevant agent workspace state should be visible in run provenance,
or the product should guarantee a clean invocation environment. Otherwise two
apparently identical runs can inherit different instructions.

### Next step

Add the smallest C1–C3 driver, run one committed public dev-A question through
all four conditions, and close the capture verification gate.

## 2026-08-28 — D-037: Preserve C4 telemetry when the governed result cannot be scored

### Decision / experiment

Run the first manifest-bound C4 attempt on the archeology vertical slice and
repair only capture defects that the live product response exposes.

### Observation

The public `archeology_scan_3` dev-A question completed in Omni, but the final
`generate_query` action reported a truncated result. The preregistered policy
correctly classified the attempt as an evaluated-system
`response_contract_error`; no correctness score was computed. The immutable
generation SHA-256 was
`2aea0701b27015645f367303feda0586d78e1e1e0befb6b611ba0fffbd158517`.

The same job exposed Bedrock `claude-opus-5`, 6 ordinary input tokens, 161,357
cache-read tokens, 86,137 cache-write tokens, 1,083 output tokens, three tool
calls, and one database query. The adapter discarded those fields because it
validated result scoreability before preserving job-level telemetry. Two
pre-auth launches also showed that Python bytecode created during process
startup can trip the clean-runtime check; running from the committed worktree
with bytecode writes disabled avoided that host-contamination interaction
without changing the harness.

### Hypothesis

Job metrics are independent of whether the generated result is scoreable. If
the adapter captures and reconciles those metrics before applying truncation and
result-shape rules, failed C4 attempts will remain diagnosable without weakening
the scoring boundary.

### Decision

Preserve a strict whitelist of model/provider, provider token buckets, tool
calls, and query count before scoreability validation. Keep truncation as an
error. Aggregate ordinary, cache-read, and cache-write tokens into the normalized
input-token count so the existing `input + output = total` invariant represents
all provider-reported token consumption; retain the source as
`provider_reported`. Keep cost, retries, and validation attempts unavailable.

Raw generation telemetry must also retain `refused` separately from `errored`.
The first implementation assumed that C4 exposed a structured `DENIED` terminal
state. Independent review of the pinned Omni CLI contract falsified that
assumption: the product job schema exposes only `COMPLETE`, `FAILED`, and
`CANCELLED`. C4 therefore records failed, cancelled, transport, contract, and
truncation outcomes as `errored` and leaves refusal observability unavailable.
It does not infer refusal from response prose. C1-C3 retain their separate,
structured direct-agent refusal outcome.

### Rationale

This change directly improves failure diagnosis on the critical path. It does
not add a new control layer, relax result validation, or introduce semantic
heuristics. The structured-signal requirement prevents a benchmark harness from
silently reclassifying natural-language content.

### Intervention

Bead `omni-benchmark-dih.5.4.4`; optimization surface: C4 capture and
observability; change type: general system improvement. Added live-shape
regressions for truncated results with metrics, provider/action query-count
reconciliation, and end-to-end summary preservation of the raw
refused-versus-errored distinction.

### Result

The pre-change tests failed because `OmniProbeResult` and the
generation envelope had no observed model/token fields. A second RED test proved
that validated run summaries discarded the raw refusal/error distinction; a
third proved that a contradictory provider `queryCount` could under-report a
successful query action. The fixes pass 165 focused tests and the 1,227-test
repository suite (three explicit live-integration skips). Independent code,
security/custody, and simplification reviews approved the final implementation,
committed as `dd8e7b1`. The exact-commit live rerun preserved the unscored
`response_contract_error` while retaining Bedrock `claude-opus-5`, 247,676 input
tokens, 1,110 output tokens, three tool calls, one governed database query, and
29,338.859 ms latency. Its generation SHA-256 is
`86814a6b5264cacc49d0ade910416b6521e4ab26f561819bfaa3701346914494` and its
trace SHA-256 is
`b9243d2a9f6e0d74d36b858282db79ee2fea482ee2b317f18826bd8d2ba4114d`.
No gold, hidden annotation, test outcome, or AI judge was accessed.

### Interpretation

The first real benchmark-shaped C4 question exposed two distinct facts: the
system can produce a governed semantic query yet still fail the benchmark
contract through truncation, and product telemetry remains valuable on that
failure path. It also exposed an observability limit: the external harness can
distinguish errors from refusals only when the evaluated system supplies a
structured refusal signal. Accuracy or a combined non-answer rate alone would
hide these mechanisms.

### Outcome

KEEP

### Product implication

AI Hub already exposes enough data to diagnose expensive or tool-heavy failed
runs, but downstream integrations need a stable structured failure/refusal
signal and scoreable-result status independent from telemetry availability.

### Next step

Run the same public question through C1-C3, then verify typed-result scorer
parity and the four-condition capture bundle before baseline generation.

## 2026-08-28: Public-repository dotfile hygiene

### Hypothesis

Explicitly ignoring common machine-local dot caches, environment-manager state,
notebook checkpoints, and operating-system metadata will prevent accidental
publication without hiding intentional public automation configuration.

### Classification

Repository-hygiene intervention; general system improvement. This does not
change a benchmark condition, runtime input, scorer, split, protocol, or custody
surface.

### Decision

Extend the existing category-specific rules. Do not use a blanket `.*` rule:
the tracked `.agents`, `.beads`, `.claude`, `.codex`, and `.cursor` trees are
intentional project configuration, while `.env.example` is the public setup
template. Keep `.beads/issues.jsonl` visible as the public passive issue export;
only the live Dolt store, credentials, locks, backups, and sync state remain
private.

### Result

PASS. `git check-ignore --no-index` accepted representative paths for every new
rule and rejected every intentional public dot-path tested, including
`.beads/issues.jsonl`, `.beads/config.yaml`, the agent-tool configuration trees,
`.env.example`, and both public `.gitignore` files. `git diff --check` also
passed. The passive Beads export is now visible to Git; the separate Dolt remote
still needs to be configured independently because ignore rules do not control
Beads synchronization.

## 2026-08-28 — D-038: Add the smallest executable C1-C3 vertical-slice driver

### Decision / experiment

Turn the reviewed direct-comparator library into one executable public dev-A
attempt before adding any new semantic or custody machinery.

### Observation

The C1-C3 preparation, model, database, capture, and publication components each
passed focused tests, but no command composed them. This blocked the archeology
vertical slice and left the common retry/time/model policy as prose rather than
an executable condition constraint.

### Hypothesis

A thin driver that loads one exact committed C1-C3 runtime policy, creates a
fresh private invocation environment, and delegates to the existing pipeline
will unblock live attempts without duplicating condition logic or weakening
custody.

### Decision

Implement only the executable composition and its shared runtime policy. Keep
scope hardcoded to public `dev-A`; pass no hidden fields; keep C1-C3 outcome
states as `answered`, `refused`, or `errored`; and defer all broader runner
abstractions until the live product slice supplies evidence that they are
needed.

### Rationale

This is the shortest path to evidence about whether the tested abstractions work
against Claude, Neon, and the real artifact contract. It also resolves the two
pending direct-condition disclosure items: zero harness retries and a common
12-turn, 120-second-per-turn policy with provider token ceilings explicitly
unavailable.

### Intervention

Bead `omni-benchmark-dih.5.4.2.5`; optimization surface: comparator execution
harness; change type: general system integration. Added
`scripts/direct_probe.py`, a strict committed runtime policy, private ephemeral
runtime directories, a safe receipt, and end-to-end composition tests.

### Result

Eight driver tests and 416 direct/Claude tests pass. Driver-local branch coverage
is 80%; Ruff, formatting, and whitespace checks pass. Independent code,
security/custody, and simplification reviews approved the implementation. The
authenticated archeology attempts remain pending. No model call, gold data,
hidden annotation, or correctness result was accessed.

### Interpretation

The direct comparator now has one auditable execution path rather than a set of
uninvoked libraries. The real test is the live archeology attempt: any failure
there should be diagnosed as a product/harness integration issue before the
system is scaled.

### Outcome

FOLLOW UP

### Product implication

Comparator reliability depends on making provider runtime state and budgets
explicit at invocation time. A reusable agent-evaluation product should expose
these as first-class run configuration and telemetry rather than external
wrapper conventions.

### Next step

Commit the reviewed driver, run C1-C3 on the same public archeology question,
then verify parity, scoring transport, and failure traces before any 18-database
fan-out.

## 2026-08-28 — D-039: Optimize the remaining work for a results-ready evaluation

### Decision / experiment

Treat a submission-ready result today as the planning constraint while preserving
every existing custody, split, baseline, freeze, and sealed-evaluation boundary.

### Observation

The protocol, scorers, database infrastructure, and condition adapters are
sufficiently developed, but no database has yet completed the full generation →
typed result → scorer → outcome-artifact path. More methodological machinery
would not improve the immediate evidence.

### Hypothesis

Concentrating work on the archeology vertical slice, while mechanically building
the remaining public-only semantic bundles in parallel, will surface real
integration/product failures sooner and make the all-database baseline possible
without weakening the experiment.

### Decision

Make Bead `omni-benchmark-ei0` the results-ready critical path. Keep the
archeology C1-C4 canary, database parity, and scorer transport as the primary
lane. Run the 17-database mechanical mapping fan-out independently under Bead
tree `omni-benchmark-786`. After the baseline, run only enough supervised
experiments to establish a useful failure taxonomy, a kept improvement, a
failed/reverted intervention, transfer evidence, and product findings before
Freeze B.

### Rationale

The vertical slice distinguishes integration defects from benchmark/modeling
failures. The fan-out is the longest-lead public-only prerequisite and does not
depend on gold or the capture gate. Work that does neither is deferred.

### Intervention

Execution prioritization only; no benchmark condition, endpoint, split, scorer,
or custody rule changed. Deferred first under pressure: LODO, elaborate template
audit/adjudication/statistics, perfect comparator parity, optimizer-framework
integration, and protocol-paper polish.

### Result

IN PROGRESS. C4 capture passes on an unscored truncated archeology attempt;
C1-C3 have a reviewed executable driver but no authenticated attempt yet;
archeology database parity passes; the frozen scorers pass offline tests but
have not yet consumed a live condition result. The semantic fan-out lane has
started separately.

### Interpretation

The first reliable scored vertical slice is the decision gate. Until it exists,
integration and failure observability dominate score optimization.

### Outcome

FOLLOW UP

### Product implication

The quality of Omni's development workflow is itself observable here: a useful
product should let an operator move from a governed failure to a typed,
externally verifiable result without building parallel diagnostic machinery.

### Next step

Commit and run the C1-C3 archeology probes, prove generation/scoring database
parity and typed scorer ingestion, then preserve the mechanical all-database
baseline as soon as the semantic bundles finish.

## 2026-08-28 — D-040: Repair direct Neon TLS trust without weakening verification

### Decision / experiment

Diagnose the first live C1 preflight failure before changing the model, query
harness, database privileges, or semantic inputs.

### Observation

The committed C1 driver reached the Neon transport but failed before any model
invocation with a sanitized PostgreSQL attestation error. Direct diagnostics
showed that Psycopg's bundled libpq rejected Neon's certificate when configured
with the special `sslrootcert=system` value. With the same `verify-full` hostname
policy and the canonical Linux CA bundle at
`/etc/ssl/certs/ca-certificates.crt`, the connection succeeded. The exact live
privilege attestation returned safe, and database, role, and PostgreSQL version
matched the committed archeology identity.

### Hypothesis

The failure is a trust-store compatibility issue in the bundled client, not a
database-parity or role-hardening defect. Allowing only the canonical immutable
OS CA path in addition to the `system` sentinel should restore the connection
without broadening trust or weakening hostname verification.

### Decision

Add a narrow compatibility path under Bead
`omni-benchmark-dih.5.4.2.5.1`. Continue to require `verify-full`; accept only
the literal `system` sentinel or the exact canonical CA-bundle path when it is a
regular file that is not group/world writable. Keep arbitrary, missing,
relative, custom, and symlinked roots rejected.

### Rationale

This change repairs an observed gate failure and generalizes to Psycopg/libpq
deployments using the standard Debian/Ubuntu trust bundle. Disabling certificate
or hostname checks would invalidate the database target boundary and was not
considered acceptable.

### Intervention

Optimization surface: direct database transport; change type: general system
integration. Added a RED test for the canonical OS trust bundle, then the minimal
root-certificate admission rule.

### Result

The RED test failed under the prior system-only policy. After the change and
review-driven test hardening, 61 direct PostgreSQL tests pass, including exact
canonical-path acceptance, non-following stat behavior, canonical symlink and
unsafe-mode rejection, stat failures, and the existing custom-path/adversarial
cases. The live archeology privilege attestation and exact runtime identity both
pass with the canonical bundle. An initial independent review raised a pre-open
TOCTOU concern and found that the positive test depended on the host filesystem.
The test was made host-independent and the missing fail-closed branches were
added. A second independent security review found no blocking issue under the
explicit unprivileged-process threat boundary: changing the literal trust path
or its root-owned, non-writable parent chain requires authority outside the
evaluated process. Ruff, formatting, and diff checks pass. The full C1 canary
remains pending; no model call, correctness label, hidden annotation, or gold
data was accessed.

### Interpretation

The preflight failure did not implicate Neon parity or role design. The strict
attestation was useful because it stopped the condition before an ambiguous
partial model attempt and made the transport defect locally reproducible. A
process-controlled certificate snapshot was considered and rejected as
disproportionate: it would add a new credential-like lifecycle and hardening
surface to defend against replacement of a root-owned system path by an actor
who already exceeds the benchmark threat model.

### Outcome

FOLLOW UP

### Product implication

Evaluation and product connectors should report TLS/trust failures separately
from privilege failures. The previous combined error preserved secrecy but made
an ordinary client trust-store mismatch look like a role-policy defect.

### Next step

Review and commit the narrow trust-store fix, rerun C1 from the exact commit,
then run C2/C3 and close the four-condition capture gate if their artifacts pass.

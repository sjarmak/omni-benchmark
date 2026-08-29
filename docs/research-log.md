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

## 2026-08-28 — D-041: Distinguish structured output from ambient Claude tools

### Decision / experiment

Diagnose the first live C1 model-transport failure using only structural init
telemetry before changing prompts, model settings, or comparator capabilities.

### Observation

The exact-commit C1 attempt passed Neon TLS, identity, and privilege preflight,
then ended in 620 ms as `model_tool_surface_error` with zero provider tokens,
zero tool calls, and zero database queries. A minimal isolated diagnostic against
the same pinned Claude Code 2.1.250 binary showed an init tool list containing
only `StructuredOutput` and no MCP servers. The CLI exposes this intrinsic
capability whenever `--json-schema` is used, even though `--tools ""`, restricted
mode, safe mode, and an empty strict MCP configuration are all active.

### Hypothesis

The transport contract is confusing the CLI's own schema-constrained response
mechanism with an ambient agent tool. Requiring exactly `StructuredOutput` while
continuing to reject every additional tool and MCP server should allow the
intended structured model transport without giving the model filesystem, shell,
web, or database capabilities.

### Decision

Treat `StructuredOutput` as part of the pinned adapter contract, not as an
evaluated tool. Require the exact singleton list rather than broadly allowing
provider-reported tools. Keep harness-owned schema and SQL actions outside the
Claude tool surface.

### Rationale

This is the smallest change that matches observed behavior and preserves the
security and interpretability boundary. Removing schema-constrained output would
weaken the action protocol; permitting arbitrary built-ins would invalidate the
direct comparator.

### Intervention

Experiment surface: structural harness compatibility; change type: general
system improvement; Bead `omni-benchmark-dih.5.4.2.5.2`. A RED test first proved
that the real singleton init surface was rejected. The validator now requires
exactly `StructuredOutput` plus an empty MCP list, and adversarial tests cover an
empty list, `Bash`, and `StructuredOutput` combined with `Bash`.

### Result

The RED test failed with the observed `tool_surface` category. After the minimal
change and review-driven coverage of duplicate, reordered, and attempted
`StructuredOutput` actions, all 50 Claude direct-transport tests pass. The
broader Claude/direct suite passes 428 tests. Independent review found no
blocking issue; Ruff, formatting, and diff checks are clean. An exact-commit
live rerun remains pending.

### Interpretation

The first live C1 failure was not model reasoning, authentication, or database
access. It exposed a mismatch between synthetic transport fixtures and the
pinned product CLI's real initialization contract. Capturing zero-token terminal
failure telemetry made that distinction immediate.

### Outcome

FOLLOW UP

### Product implication

Tool-surface observability needs to distinguish response-format machinery from
capabilities that can act on user data or external systems. Treating both as one
undifferentiated list produces false security failures and makes agent scaffolds
harder to audit.

### Next step

Review and commit the exact-surface contract, rerun C1 from a fresh immutable
worktree, then continue C2/C3 only if the live artifact passes capture checks.

## 2026-08-28 — D-042: Preserve provider failure class ahead of synthetic partial identity

### Decision / experiment

Diagnose the exact-commit C1 rerun's terminal failure before changing the
prompt, model, semantic inputs, or retry policy.

### Observation

The rerun passed database and Claude tool-surface preflight. Claude then
returned a terminal provider error stating that its OAuth session had expired
and could not be refreshed. The stream's init event identified the requested
model, but its provider-generated partial assistant event used the literal
model placeholder `<synthetic>`. The transport validated that placeholder
before classifying the terminal error, so the raw artifact recorded
`model_identity_mismatch` rather than the observed authentication failure.

### Hypothesis

Claude uses `<synthetic>` for provider-generated partial error messages that do
not represent a model invocation. If the init event still proves the pinned
model and the terminal result is explicitly an error, accepting only that exact
placeholder for partial failure telemetry will preserve the real auth/rate/
quota failure class without weakening successful model-identity enforcement.

### Decision

Add a focused transport compatibility experiment under Bead
`omni-benchmark-dih.5.4.2.5.4`. Keep init and successful-response model checks
strict. Classify a structured terminal provider error from its designated
error result before a synthetic partial placeholder can mask it. Persist only
the existing sanitized failure message and typed category.

### Rationale

This is the smallest reusable correction to the three-state and terminal
failure telemetry required by the capture gate. Reauthenticating alone would
hide the instrumentation defect and leave future expired-session attempts
misclassified.

### Intervention

Optimization surface: direct transport telemetry; change type: general system
integration. RED tests reproduced the live structured error and proved that
successful synthetic partial output remains invalid.

### Result

The RED test reproduced the live misclassification: the structured OAuth
failure was reported as `model_identity` while a successful synthetic partial
was already rejected. The implementation now admits the exact `<synthetic>`
partial placeholder only when the terminal result is explicitly an error and
classifies that result through the existing provider-failure taxonomy. It does
not retain the raw provider message. The successful synthetic case remains a
`model_identity` failure. Failure classification was extracted into a focused
module to keep the transport below the repository's 800-line limit. Review then
added a RED guard proving structured-output errors cannot be reclassified from
model-authored result text, plus a pinned-init-model failure case. All 54
transport tests and the 432-test Claude/direct suite pass; scoped coverage is
89.97%, and Ruff/format/diff/secret checks pass. Independent review found no
actionable issue. A live rerun remains pending.

### Interpretation

The hypothesis is supported in synthetic replay. The correction changes only
failure observability; it does not make an unauthenticated attempt successful
or relax the identity contract for any successful attempt. EnterpriseBench's
recent multi-account runner confirms the appropriate operational pattern:
select an isolated OAuth account as a capacity resource, stage only its private
credential material into the attempt environment, and keep account choice out
of the experimental treatment. The local capacity picker selected account 3;
no interactive login or raw token handling is needed.

### Outcome

FOLLOW UP

### Product implication

Provider scaffolds can emit synthetic bookkeeping messages during failures.
Observability should not attribute those to the evaluated model or let them
overwrite the actionable terminal failure class.

### Next step

Commit the reviewed correction and rerun the public-only C1 canary with the
capacity-selected isolated OAuth harness.

## 2026-08-28 — D-043: Preserve cross-database HKB representability as baseline evidence

_Last updated: 2026-08-28 11:02 EDT_

### Decision / experiment

Apply the reviewed public-only HKB-to-Omni transformation to the 17 databases
beyond the archeology canary before generating the 231-question baseline.

### Observation

The archeology canary compiled only 14 of 54 HKB nodes. Its deferred and
unsupported definitions appeared concentrated in cross-grain composition, but
one database could not establish whether that was a general transformation gap
or a domain-specific artifact.

### Hypothesis

Exact row-local definitions will often map safely into executable Omni fields,
while definitions that cross entities, grains, time windows, or ordered sets
will remain unsafe to compile until the semantic contract supplies explicit
relationship, cardinality, aggregation, and identity information.

### Decision

Run the same public-only classification discipline across every remaining
database. Preserve `context_only`, `defer_cross_grain`, and `unsupported` as
first-class results rather than guessing joins or hand-tuning against questions.

### Rationale

The full public-only baseline requires semantic artifacts for all 18 databases.
Fan-out also tests the transformation methodology itself and identifies product
gaps before expensive agent runs. Alternatives rejected were uploading only the
canary, treating every formula as free-form context, or inventing relationships
to raise the compile count.

### Intervention

Optimization surface: HKB-to-semantic-model transformation; change type:
general system improvement. Bead `omni-benchmark-786`. Generated hash-bound
schema IR, reviewed public-only mapping specifications, and deterministic Omni
bundles for all 17 non-canary databases. Agent-assisted public modeling
inference is explicit in provenance. Commits:
`d3f84f6ea5d15b247e3d1ffba739cd220289e72a` and
`dcdd1a08a3d45a4a14978fe39f66542938fa5f32`.

### Result

Across 1,036 HKB definitions, 179 (17.3%) compiled, 183 (17.7%) became
discoverable context, 491 (47.4%) were deferred cross-grain, and 183 (17.7%)
were unsupported. Per-database distributions are linked below as
compile/context/defer/unsupported:

| Public semantic artifact | Distribution |
| --- | ---: |
| [cross_border](../semantic_models/public_baseline/cross_border_large/) | 12 / 7 / 33 / 27 |
| [cybermarket_pattern](../semantic_models/public_baseline/cybermarket_pattern_large/) | 5 / 10 / 11 / 4 |
| [disaster_relief](../semantic_models/public_baseline/disaster_relief_large/) | 14 / 9 / 28 / 7 |
| [exchange_traded_funds](../semantic_models/public_baseline/exchange_traded_funds_large/) | 21 / 8 / 51 / 9 |
| [fake_account](../semantic_models/public_baseline/fake_account_large/) | 2 / 7 / 65 / 13 |
| [labor_certification_applications](../semantic_models/public_baseline/labor_certification_applications_large/) | 4 / 10 / 35 / 11 |
| [mental_healths](../semantic_models/public_baseline/mental_healths_large/) | 6 / 10 / 72 / 8 |
| [museum_artifact](../semantic_models/public_baseline/museum_artifact_large/) | 3 / 8 / 44 / 7 |
| [organ_transplant](../semantic_models/public_baseline/organ_transplant_large/) | 11 / 22 / 3 / 19 |
| [planets_data](../semantic_models/public_baseline/planets_data_large/) | 22 / 10 / 11 / 9 |
| [polar_equipment](../semantic_models/public_baseline/polar_equipment_large/) | 18 / 9 / 25 / 6 |
| [residential_data](../semantic_models/public_baseline/residential_data_large/) | 0 / 13 / 26 / 6 |
| [reverse_logistics](../semantic_models/public_baseline/reverse_logistics_large/) | 0 / 19 / 4 / 7 |
| [robot_fault_prediction](../semantic_models/public_baseline/robot_fault_prediction_large/) | 18 / 13 / 17 / 17 |
| [solar_panel](../semantic_models/public_baseline/solar_panel_large/) | 27 / 10 / 7 / 6 |
| [sports_events](../semantic_models/public_baseline/sports_events_large/) | 4 / 3 / 32 / 17 |
| [virtual_idol](../semantic_models/public_baseline/virtual_idol_large/) | 12 / 15 / 27 / 10 |

The most frequent loss codes were `cardinality_unknown` (398),
`aggregation_unspecified` (314), and `cross_grain_no_identity` (308). The full
repository suite passed 1,264 tests with three explicit live-integration skips
and 84.78% branch coverage. Independent review found and resolved a file-size
violation and non-scalar provenance error-contract defect before approval. No
questions, gold, hidden annotations, private data, or correctness outcomes were
used.

### Interpretation

The hypothesis is supported as a representation result, not yet as an answer-
accuracy result. Same-row sensor and physical definitions compiled readily in
solar and planets. Residential and reverse-logistics preserved useful context
but compiled no definitions safely. The dominant bottleneck is missing
grain/relationship/aggregation contracts, not scalar expression syntax.

### Outcome

KEEP

### Product implication

Automated semantic-model construction needs first-class grain, identity,
cardinality, and aggregation contracts, plus a dry-run explanation of why a
definition is context-only or unsafe to compile. Silently guessing those
contracts would make the semantic layer look more complete while weakening the
governance claim.

### Next step

Deploy the frozen public-only bundles through isolated Omni branches, preserve
the complete 231-question baseline outputs, and use execution traces to learn
which representation gaps actually become answer failures.

## 2026-08-28 — D-044: Adapt action variants to Claude's structured-output root

### Decision / experiment

Diagnose the first authenticated, exact-commit C1 attempt that reached the
capacity-selected OAuth account but terminated before inference.

### Observation

Commit `e695afa` passed the committed public-question gate, exact archeology
database identity/parity, read-only attestation, credential isolation, pinned
Claude binary identity, and tool-surface initialization. The provider returned
HTTP 400 in 784 ms with zero tokens, tool calls, or database queries. A bounded
replay of the same initial model turn identified the rejected contract:
Claude's `StructuredOutput` custom input schema does not accept `oneOf`,
`allOf`, or `anyOf` at its top level. A minimal scalar schema succeeded under
the same binary, model, account, and restrictions.

### Hypothesis

The action variants themselves are valid, but their placement is incompatible
with the provider adapter. Nesting the existing strict variant schema under one
required top-level `action` property should satisfy the provider's root-shape
constraint while preserving the full variant contract and deterministic local
validation after mechanical unwrapping.

### Decision

Test the narrow envelope adaptation under Bead
`omni-benchmark-dih.5.4.2.5.5`. Do not flatten the schema into a permissive set
of optional fields and do not weaken `validate_action`. Require exactly one
top-level `action` key from the provider, then validate its value against the
same local tool/answer/refusal rules as before.

### Rationale

This change directly unblocks baseline generation and isolates a provider
schema-compilation defect found by the vertical slice. A permissive flat schema
would move errors downstream and reduce generation guidance; changing the
action protocol itself would be broader than the observed incompatibility.

### Intervention

Optimization surface: model-transport compatibility; change type: general
system integration. A RED command-schema test required a composition-free
provider root with the existing variants nested beneath `action`. The transport
then mechanically unwraps only an exact one-key envelope before applying the
unchanged local action validator.

### Result

The RED test failed on the former top-level `oneOf`. After the adaptation, 58
focused transport/provider-compatibility tests and the 436-test Claude/direct
suite pass with 87.46% scoped branch coverage; Ruff and formatting pass.
Adversarial cases reject a missing, empty, extra-key, or double-wrapped envelope.
A bounded live replay using the
same pinned binary, model, account, public question, and C1 tool schema now
succeeds: Claude returned an `inspect_schema` action after 1,428 input and 98
output tokens, zero retries, and $0.01672. Independent review and the immutable
full-driver replay remain pending.

### Interpretation

The provider incompatibility was the causal zero-token failure. Preserving the
variant schema one level below the provider root restores inference without
loosening the harness-owned action contract.

### Outcome

FOLLOW UP

### Product implication

Semantic agent harnesses need an explicit adapter boundary between their
internal typed action protocol and each provider's supported JSON-Schema
dialect. Treating standard JSON Schema as uniformly portable caused a complete,
zero-token system failure that synthetic validation did not reveal.

### Next step

Implement and review the minimal nested envelope, then rerun C1 from a fresh
exact-commit worktree and artifact root.

## 2026-08-28 — D-045: Bound direct-schema discovery before raising budget

_Last updated: 2026-08-28 11:38 EDT_

### Decision / experiment

Replace the zero-argument, whole-database `inspect_schema` response shared by
C1–C3 with deterministic, query-directed public-schema retrieval.

### Observation

The immutable C1 archeology canary at commit `349e0bb` passed the public
question, database-identity, read-only, model-identity, and first-turn gates.
Claude then called `inspect_schema`. The tool returned all 51 tables; the next
turn consumed 169,995 input tokens and ended in `model_budget_error` before any
SQL or database query. Across the attempt, usage was 171,423 input and 1,942
output tokens, one tool call, zero database queries, 26.0 seconds, and
$1.7398935 provider-reported cost.

### Hypothesis

The failure is caused by unbounded scaffold context, not by the question or
database. Requiring a lexical schema query and returning a bounded set of
matching public tables, columns, and relationships should preserve legitimate
schema discovery while reducing context enough to complete the same one-shot
attempt within the frozen budget. The same tool and bounds should improve all
three direct comparators without changing their information hierarchy.

### Decision

Test the smallest shared retrieval change under Bead
`omni-benchmark-dih.5.4.2.5.6`. Keep committed-input identity and strict action
validation. Use deterministic public-schema search only; do not add
question-specific aliases or hidden inputs. Do not raise the cost ceiling as
the primary intervention.

### Rationale

Returning the entire schema makes a competent direct comparator needlessly
expensive and can make C1–C3 look weak for scaffold reasons. A bounded retrieval
surface directly unblocks the vertical slice and is interpretable as a general
harness correction. Raising the budget would permit the pathological behavior
and multiply baseline cost without testing its cause.

### Intervention

Optimization surface: structural harness/retrieval; change type: general system
improvement. Planned intervention: make `inspect_schema` require a non-empty
query, rank only committed public-schema records mechanically, and enforce a
small result/payload bound shared across C1–C3.

### Result

Commit `2b72244` implements the reviewed shared retrieval surface: the model
must provide a query; unweighted FTS5 ranks committed public table records; a
result contains at most four tables and 64 KiB; and the query plus returned
schema IDs are bound into action evidence. The 455-test direct/Claude suite
passed with 85.8% scoped branch coverage. Stress checks over all 18 public
schemas stayed within both payload and evidence-ID bounds.

The first exact-commit replay reduced the attempt from 173,365 total tokens and
$1.7398935 to 1,585 tokens and $0.017715. Latency fell from 26.0 to 3.0 seconds.
It then failed `forbidden_tool_payload` before a database query. Offline replay
of the exact public tool result isolated six legitimate foreign-key stable IDs
whose `foreign-key:sha256:...` text triggered a generic `KEY:<value>` secret
heuristic. The bounded result itself contained the four relevant tables and 75
public schema IDs.

### Interpretation

The main hypothesis is strongly supported for context size, latency, and cost;
end-to-end success remains unproven. The new failure is not a retrieval miss:
the required public tables survived the bound. It is a mismatch between a
provider/model identifier policy and the syntax of trusted public schema IDs.
That boundary should be corrected narrowly rather than weakening payload or
query secret scanning.

### Outcome

FOLLOW UP

### Product implication

Semantic-agent comparators need bounded schema discovery as a first-class
scaffold primitive. Tool availability alone is insufficient when a single
valid call can consume the entire inference budget. Provenance validation also
needs types appropriate to public semantic IDs; reusing provider-identifier
redaction can reject valid relationship identifiers and turn useful telemetry
into a terminal system error.

### Next step

Under Bead `omni-benchmark-dih.5.4.2.5.6.1`, add a RED case for the exact
foreign-key stable-ID form, preserve exact-secret and credential-shape
rejection, then replay C1 from a fresh immutable commit before releasing C2/C3.

## 2026-08-28 — D-045.1: Type the public foreign-key provenance exception

_Last updated: 2026-08-28 11:48 EDT_

### Decision / experiment

Permit only the canonical public foreign-key stable-ID form that was rejected
by action-evidence validation, without weakening the policy for other IDs.

### Observation

The exact `2b72244` replay's bounded public result was usable, but six IDs of
the form `<database>:foreign-key:sha256:<64 lowercase hex>` triggered the
generic `KEY:<value>` secret-assignment heuristic. The IDs are generated
mechanically by the committed public schema compiler and are not model input.

### Hypothesis

A typed exception matching the compiler's exact foreign-key identity grammar
will let the public schema result cross the evidence boundary while preserving
the existing credential and length checks for every other identifier.

### Decision

Keep `identifier_is_safe` as the default. Admit the foreign-key form only when
its database component is not a sensitive key name, its digest is canonical
lowercase SHA-256, and it contains no exact or known-shape credential value.

### Rationale

The first candidate replaced `identifier_is_safe` with `query_is_safe` for all
public IDs. Independent review demonstrated that this would also accept
`api_key=plainsecret` and `token:plainsecret`; that candidate was rejected
before commit. Changing the global redaction regex was also rejected because
it would weaken unrelated provider and diagnostic surfaces.

### Intervention

Optimization surface: action-evidence provenance validation; change type:
general system correction. Add a canonical foreign-key stable-ID recognizer at
the public-ID capability boundary and positive/negative regression cases.
Query and payload secret scanning remain unchanged.

### Result

The RED test reproduced the live failure. The typed implementation passes 463
direct/Claude tests with 83.68% scoped branch coverage, including exact-secret,
known credential-shape, generic credential-assignment, malformed digest,
sensitive database-prefix, uppercase-digest, and 257-character rejection.
Ruff, formatting, and diff checks pass. A clean-worktree independent Codex
review ran the full 1,296-test suite (five explicit environment-gated skips)
and approved the narrow change with no critical or high findings. Immutable
live replay remains pending.

### Interpretation

The review failure was useful: the failure mechanism called for a typed
provenance rule, not a more permissive generic content policy.

### Outcome

FOLLOW UP

### Product implication

Semantic provenance IDs benefit from typed validation separate from generic
provider identifiers. Otherwise syntactic collisions between relationship IDs
and credential redaction can make correct, public semantic context unusable.

### Next step

Commit the reviewed two-file correction and this contemporaneous record, then
rerun C1 from a new exact-commit worktree and never-reused artifact root. Release
C2/C3 only if C1 reaches SQL or produces a new evidenced failure.

## 2026-08-28 — D-045 closeout: Direct canary and four-condition capture gate

_Last updated: 2026-08-28 11:57 EDT_

### Decision / experiment

Replay C1 from reviewed commit `50ebc31`, release C2/C3 only after C1 reaches
SQL, then validate the existing four-condition telemetry gate on the same
public dev-A question.

### Observation

The prior exact-commit replay had established that retrieval cost collapsed but
had not proven end-to-end SQL execution. C1-C3 also lacked an authenticated
four-condition capture bundle with C4's common run identity.

### Hypothesis

If the typed provenance correction is sufficient, C1 should pass the same
bounded public context into SQL execution. The unchanged retrieval and capture
surfaces should then permit C2 and C3 to execute while preserving their added
HKB and semantic-reference tool use.

### Decision

Run the public `archeology_scan_3` canary only. Do not inspect correctness. Treat
provider/database invocation mistakes before model submission as benchmark
infrastructure corrections; never reuse an artifact root. The first successful
C1 diagnostic used a D-045-specific run ID, so issue one additional unscored C1
invocation with the preregistered common smoke run ID. This was required by the
capture gate and was not prompted by its answer.

### Rationale

This is the smallest vertical slice that proves generation, telemetry, database
execution, immutable publication, and cross-condition reconciliation before
scaled baseline work.

### Intervention

No semantic or prompt change after `50ebc31`. Run the frozen direct conditions
against the same attested read-only Neon mirror and validate them with the
existing C4 `dd8e7b1` bundle.

### Result

The first immutable C1 replay answered at 32,060 total tokens, $0.205594, one
schema tool call, one database query, zero retries, and 27.0 seconds. The common
run-identity bundles then produced:

| Condition | Outcome | Total tokens | Cost (USD) | Latency (s) | Tool calls | DB queries |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| C1 | Answered | 33,445 | 0.214778 | 40.9 | 2 | 2 |
| C2 | Answered | 81,838 | 0.6084515 | 31.1 | 3 | 2 |
| C3 | Answered | 104,625 | 0.7275655 | 43.2 | 4 | 2 |
| C4 | Errored: truncated result contract | 248,786 | Unavailable | 29.3 | 3 | 1 |

C1-C3 each reported zero harness retries and zero validation attempts. C2 used
both schema and HKB search; C3 used schema search and two semantic-model searches.
The existing C4 attempt retained its already documented
`response_contract_error`; it was not regenerated. The four-condition telemetry
smoke validator returned `status=validated`, common question/run/repetition,
and `trace_captured=true` for every condition.

### Interpretation

The D-045 mechanism is confirmed: unbounded schema discovery, rather than an
inherent inability to answer, caused the $1.74 failure. Bounded retrieval cut
the direct C1 path to roughly $0.21 while restoring SQL execution. Added
business/semantic reference tools substantially increased token cost on this
single canary; correctness is intentionally unknown until the immutable public
baseline is scored.

### Outcome

KEEP

### Product implication

Agent-tool payload bounds are part of model quality and cost behavior, not mere
infrastructure. Separately, C4's complete trace is usable for failure analysis,
but a truncated governed result cannot yet enter execution scoring without a
full-result adapter.

### Next step

Close the D-045 and direct-driver canary beads, preserve these immutable hashes,
finish isolated bundle deployment/readback, and wire the reviewed batch
orchestrator to live execution using observed successful-attempt costs rather
than the earlier $1.74 failure as its expected-cost assumption.

## 2026-08-28 — D-046: Recover scorer-faithful C4 results from governed queries

### Decision / experiment

Repair the smallest result-transport gap that prevents a completed governed Omni
query from becoming a scoreable execution artifact. Bead
`omni-benchmark-dih.5.4.3`; optimization surface: C4 execution/result adapter;
change type: general system integration.

### Observation

The exact-commit C4 vertical slice completed a governed semantic query, but its
agent-action CSV preview was marked truncated and the strict adapter stopped
before rerunning the semantic query. A new public-only live probe found two more
facts. First, the installed client currently rejects the committed
`cache:"disabled"` value and accepts `SkipCache`. Second,
`resultType:"json"` with formatting disabled returns Omni NUMBER fields as JSON
strings, including both a numeric dimension and a COUNT measure. The same query's
plan-only response exposes ordered field metadata with authoritative
`data_type: NUMBER` and performs no database execution.

### Hypothesis

The agent preview is sufficient to identify the selected semantic query even
when its display CSV is truncated. If the evaluator validates that query,
obtains authoritative column metadata through `planOnly`, reruns the query for
the complete rows, and converts values only according to declared Omni types,
then C4 can produce scorer-compatible typed artifacts without inferring types
from string appearance or weakening truncation checks on the final result.

### Decision

Keep the preview/truncation signal as product telemetry, but do not treat a
truncated preview as terminal when an independently rerunnable semantic query is
present. Require the full rerun's row count, columns, and result presence to
match the agent action. Use plan metadata as the only authority for typed
conversion; reject absent, ambiguous, contradictory, or unsupported metadata.
String fields that resemble numbers must remain strings. Use the live-supported
`SkipCache` spelling. The plan and full-result calls are evaluator-side result
transport and remain excluded from evaluated-system query counts.

### Rationale

This directly unblocks baseline scoring while preserving production C4
generation. It is smaller and more auditable than parsing values heuristically,
adding question-specific limits, or replacing Omni's governed workflow with raw
SQL. Plan-only metadata also avoids a second warehouse query solely to discover
types.

### Intervention

Planned TDD surface: truncated-preview validation, strict NDJSON plan parsing,
metadata-driven NUMBER/DATE/TIMESTAMP/YESNO/STRING conversion, string-lookalike
preservation, duplicate/ragged/ambiguous rejection, the current cache enum, and
end-to-end capture of a full result after a truncated preview.

### Result

Pending.

### Interpretation

Pending.

### Outcome

FOLLOW UP

### Product implication

Pending live validation. The current evidence already suggests that downstream
execution consumers need a stable full-result handle and authoritative result
type metadata independent of the AI-facing preview.

### Next step

Implement the failing contract tests, pass the focused and full gates, then run
one public count canary through Omni and the read-only Neon mirror to establish
typed scorer parity before scaled C4 generation.

## 2026-08-28 — D-047: Preserve the first 18-database deployment fan-out

### Decision / experiment

Deploy the committed public-only semantic bundles through the D-035 adapter in
one bounded, append-only fan-out. Bead `omni-benchmark-dih.17`; source commit
`5edb423d8eaa911cf8da467716ead287998acc30`; change type: general system
integration.

### Observation

The archeology canary proved upload, validation, and semantic readback for one
lowercase-schema database. It did not test connection setup or schema-view
identity across the remaining 17 databases.

### Hypothesis

The authenticated bundle mapping and readback projection would generalize
unchanged across all 18 isolated models. Any failure would be retained as a
per-database status rather than repaired by hand.

### Decision

Load bundle bytes from the exact recorded Git commit, deploy with four bounded
workers, preserve every terminal record, and stop after the first shared failure
mechanisms became clear. Do not update connection coordinates or regenerate
semantic bundles inside the deployment lane.

### Rationale

This was the smallest live experiment that could distinguish deployment-code,
connection, and mechanical-modeling failures without using benchmark questions
or hidden supervision.

### Intervention

The deployment runner snapshots `git archive <source_commit>`, authenticates
each manifest, creates only isolated `livesqlbench-*` resources, validates the
branch, and compares semantic readback. TDD and review covered duplicate
selection, append-only claims, malformed-bundle isolation, parser recursion,
unsafe archives, exact-commit binding, bounded concurrency, and credential-safe
failure capture.

### Result

INCONCLUSIVE as a scale deployment, but diagnostic. The immutable run retained
18 records plus its claim; their aggregate SHA-256 is
`57df58ee3ddf96de7dd240969a0bfa7cfab427f6cdc4dcc1b9a4b1e4545c3d75`.
Archeology verified 14/14 files with zero validation issues. Six bundles failed
preflight: five exposed case-sensitive physical table identities behind
normalized extension names, and residential used unqualified view filenames.
The other eleven failed before a shared-model ID was returned.

Read-only product inspection then confirmed that all 17 non-canary Omni
connections selected `neondb`, while the working canary selected
`archeology_scan_large`. On one representative connection, creating the
isolated schema-model record succeeded, its refresh ended `FAILED`, and shared
model creation remained unavailable. No shared model or branch was created for
that diagnostic.

### Interpretation

The hypothesis was false for two independent reasons. The canary adapter did
not cover case-sensitive schema-view identity, and connection creation did not
guarantee that the selected database matched the verified scorer mirror. These
are integration and mechanical-modeling failures, not evidence about agent
accuracy.

### Outcome

FOLLOW UP

### Product implication

Connection setup should validate the selected database and surface actionable
schema-refresh errors. Semantic-model tooling also needs an explicit distinction
between a physical table identity and its normalized Omni view/extension path.

### Next step

Resolve Beads `omni-benchmark-dih.17.1` and `.17.2`, then rerun under a new
append-only run ID and require zero validation issues plus exact readback before
the deployment records gate C4 baseline dispatch.

## 2026-08-28 — D-048: Time-box optimization after the public baseline

### Decision / experiment

Refocus the remaining work on a results-complete deliverable today without
weakening split, custody, baseline-preservation, or final-freeze boundaries.
Beads `omni-benchmark-dih.5.4.2.4.4.2.2`, `omni-benchmark-dih.17`, and
`omni-benchmark-dih.4`; change type: research execution decision.

### Observation

The four-condition capture gate passed, but C4 bundle deployment remained
blocked on 17 databases while the direct C1--C3 path was independently ready to
run. Serializing all baseline work behind the C4 product-integration failure
would leave available direct-run capacity idle. The methodology was already
sufficiently developed; the scarce resource was wall-clock execution and the
evidence needed for a coherent results narrative.

### Hypothesis

Launching C1--C3 after a small fixed concurrency proof, while correcting the
Omni connection and bundle-identity failures in parallel, will shorten the path
to the immutable public-only baseline without changing any evaluated system or
custody boundary. Observed attempts per minute will provide a defensible basis
for retaining three sealed repetitions or increasing to four.

### Decision

Run the full 231-question public-only baseline for C1--C3 immediately after the
prespecified public-canary concurrency slice passes; do not wait for D-047.
Run C4 as soon as all 18 isolated deployments pass validation and exact
readback. Keep the final sealed repetition count open until baseline throughput
is measured. After the baseline is committed, run only three or four registered
dev-A interventions with explicit hypotheses and full dev-A keep/revert
decisions. Preserve at least one negative result. Reserve dev-B without
consuming any checkpoint.

### Rationale

The conditions use separate execution paths, and the one-Neon-project-per-
database topology makes cross-database direct attempts independently
schedulable. This parallelization changes execution order, not the frozen
population, runtime information, scoring policy, or system definitions. A
bounded experiment count is enough to demonstrate disciplined product learning
without turning the project into an open-ended benchmark search.

### Intervention

Materialized 18 private read-only Neon environments outside the repository from
the committed public project and branch identifiers. Each environment is mode
`0600` under a mode-`0700` directory, selects the exact named benchmark
database, and uses `omni_benchmark_reader` with `verify-full`. No connection URL
or credential entered the repository or command output. The baseline runner is
being extended only with a fixed C1--C3 full-train mode and a fixed public-canary
concurrency proof. The primary public report was started concurrently at
[`RESULTS.md`](../RESULTS.md).

### Result

Pending concurrency proof and immutable public baseline.

### Interpretation

Pending.

### Outcome

FOLLOW UP

### Product implication

The first scale bottleneck is already product-relevant: correct database
restores existed and passed parity, but 17 Omni connections selected `neondb`
rather than the named databases. Connection root-cause and repair remain D-047
evidence rather than being hidden as setup noise.

### Next step

Report the fixed-slice attempts per minute, continue the resumable 693-attempt
C1--C3 run, finish D-047 in parallel, then freeze and commit the complete
231-question public-only baseline before requesting any gold release.

## 2026-08-28 — D-049: Repair connection targets and semantic-view identity

### Decision / experiment

Correct the two independent blockers exposed by D-047 without changing the
public semantic content or using benchmark questions. Beads
`omni-benchmark-dih.17.1` and `.17.2`; change type: general system integration.

### Observation

All 17 parity-verified direct targets named their benchmark database, while
safe Omni readback showed the corresponding connections selected `neondb`.
Separately, five bundles preserved mixed-case physical PostgreSQL table names
behind normalized Omni view filenames, and one bundle used flat view filenames.
The canary-derived deployment adapter incorrectly treated physical table and
logical extension identity as the same value.

### Hypothesis

Changing only each affected connection's selected database would restore
public schema generation. Separating authenticated logical extension paths from
physical `table_name`, while qualifying flat paths from authenticated
catalog/schema metadata, would make all mechanical bundles deployable without
altering their semantic definitions.

### Decision

Use the field-only connection PATCH already proven on archeology, require exact
readback, and refresh schema models in bounded batches. Change only the general
deployment identity rule: preserve manifest hashes and physical table names;
derive remote paths from normalized logical filenames plus authenticated
catalog/schema. Do not regenerate definitions or add database/question cases.

### Rationale

This directly tests both diagnosed mechanisms. It is smaller and more
interpretable than rewriting six bundle specifications, normalizing physical
PostgreSQL identifiers, or hand-editing model documents.

### Intervention

The 17 existing LiveSQLBench connections were changed from `neondb` to their
exact verified database names; no endpoint, role, credential, schema filter, or
shared/main model changed. Public schema models were refreshed in product-limited
batches. The adapter now accepts a normalized logical view filename whose
embedded physical table is case-sensitive, and maps a flat `.view` file using
its authenticated catalog/schema identity. Focused tests cover both classes and
retain catalog/schema/path-confusion rejection.

### Result

KEEP pending the new append-only deployment readback. All 17 connection
corrections round-tripped exactly; all 17 refresh jobs completed; each exposed
only `<database>.public`, and view counts matched the committed parity inventory
for all 17. Omni accepted at most five simultaneous refreshes in the first
batch and returned HTTP 429 for additional requests; bounded subsequent batches
completed. The corrected adapter builds authenticated plans for all 17 fan-out
bundles, including the 27 mixed-case physical identities and six flat views.
Fifty-five focused deployment tests pass and Ruff is clean.

### Interpretation

Both D-047 mechanisms were correct. The connection failure was configuration,
not database parity or grants. The bundle failure was an identity-modeling bug:
Omni's logical view identity is normalized independently of the exact physical
PostgreSQL table identity. Neither fix uses question evidence.

### Outcome

FOLLOW UP

### Product implication

Connection save/refresh needs selected-database validation and actionable error
status. Model import/export needs an explicit stable logical view identifier
separate from physical catalog/schema/table identity. The observed refresh
concurrency ceiling should be documented or returned with retry guidance for
bulk rollouts.

### Next step

Commit and independently review the adapter and secret-free correction receipt,
then rerun the 18-database deployment under a new immutable run ID and require
zero validator issues plus exact semantic readback before closing D-047.

## 2026-08-28 — D-050: Live validation separates field binding from rate limiting

### Decision / experiment

Rerun the full public-only deployment from the reviewed D-049 commit and retain
all terminal statuses before diagnosing failures. Beads `omni-benchmark-dih.17`
and `.17.3`; change type: general system integration.

### Observation

D-049 cleared exact connection selection and local bundle preflight, but only a
live branch upload could establish whether the compiled documents extended the
product-generated schema fields correctly.

### Hypothesis

The repaired logical/physical view mapping would allow all 18 branches to
validate and read back exactly.

### Decision

Run one new append-only four-worker fan-out from commit `81e3807`; preserve the
entire run even if a common product/compiler failure appears. Do not rewrite or
reuse the failed D-047 records.

### Rationale

The complete immutable run distinguishes local preflight, product API, upload,
validation, and readback stages without using benchmark questions or labels.

### Intervention

Created only isolated `livesqlbench-*` shared models/branches and uploaded the
committed public bundles through the reviewed adapter.

### Result

REVERT is not applicable because the run is evidence; the hypothesis was false.
Archeology again verified exactly. Seventeen records failed. Six branches
uploaded fully and reached validation with 4, 6, 15, 26, 5, and 11 issues.
Later attempts failed at the product API while Omni returned HTTP 429, including
for immediate read-only validator requests. The run contains 19 immutable files;
aggregate SHA-256 is
`d2ad129051422e786773125b679e980ecc90c1795c595a89f2fe254fbd813433`.

After the rate window cleared, validator payloads exposed two mechanical field
binding problems. Omni schema refresh normalized a physical field such as
`procComp` to `proc_comp`, while the compiler emitted/referenced `procComp`.
Separately, semantic aliases such as `route_complexity`, bound to public source
column `RouteComplex`, lacked explicit `${route_complex}` SQL, so Omni treated
the alias as a nonexistent physical column.

### Interpretation

View identity is fixed, but field identity has the same physical/logical
separation. The validator failures are compiler defects, while the later
product API failures are rate-limit effects. Treating both as one deployment
failure would have led to the wrong intervention.

### Outcome

FOLLOW UP

### Product implication

Model tooling needs stable normalized schema field identifiers and explicit
source bindings for aliases. Bulk model deployment also needs documented rate
limits or structured retry guidance; HTTP 429 otherwise obscures which models
have semantic defects versus transient infrastructure failures.

### Next step

Under Bead `omni-benchmark-dih.17.3`, mechanically normalize bound public field
identifiers, emit explicit alias SQL, regenerate deterministically, then retry
serially under a new append-only run ID.

## 2026-08-28 — D-051: Refusals are stochastic outcomes, not infrastructure retries

### Decision / experiment

Establish whether the repeated `fake_account_1` C1 refusal was database-wide,
then lock refusal accounting before the 231-question fan-out. Bead
`omni-benchmark-dih.5.4.2.4.4.2.2.1`; change type: evaluation policy evidence,
not a system intervention.

### Observation

`fake_account_1:C1` refused in two immutable canaries. A database-wide safety
block would invalidate a large comparator slice, while a question-sensitive
refusal is an evaluated-system reliability outcome.

### Hypothesis

If the behavior were database-wide, additional public `fake_account_large` C1
questions would also refuse consistently.

### Decision and rationale

Run three predeclared dev-A questions (`fake_account_2`, `_3`, and `_5`) once
through C1, without labels or correctness scoring. Refusals are thereafter
terminal `refused` outcomes: never selectively rerun, never relabeled as wrong
answers, and reported separately by condition and database. Report both
all-attempt execution success and answered-only accuracy.

### Intervention

No system change. The three attempts used the frozen direct harness at commit
`e1163753`, one proven OAuth profile each, and the exact public read-only mirror.

### Result

`fake_account_2` answered; `_3` and `_5` refused. The later auth4 proof also
answered `fake_account_1:C1`, after that same attempt had refused twice. The
auth4 four-database C1-C3 proof completed 12 attempts in 341.940 seconds
(2.106 attempts/minute): 11 answered, one refused (`cross_border_1:C3`), zero
errors, $16.799005, and 2,420,049 tokens. The three-question diagnostic digest
is `030c0b3898df2620cd1bb87ecce2238350604ff9ef928eb1d432560464c98174`.

### Interpretation

The hypothesis was wrong: refusal is neither universal to the database nor
deterministic for one question. It is a stochastic, content-sensitive system
behavior. The baseline must preserve it as a reliability/safety co-outcome.

### Outcome

KEEP

### Product implication

Direct analytical agents can intermittently refuse benign business-analysis
questions. Reliability analysis must distinguish safe no-answer behavior from
confidently wrong SQL and expose the reason a refusal occurred.

### Next step

Run the complete C1-C3 public baseline under the locked taxonomy and report
refusal counts/rates by condition and database before interpreting comparator
accuracy.

## 2026-08-28 — PLUMBING-001: Gold-free scoring rehearsal on real dev-A results

### Decision / experiment

Exercise both frozen result comparators and the immutable score-artifact boundary
before any private labels are released. Bead `omni-benchmark-dih.10.1`; change
type: general system integration.

### Observation

Real generation and `answer.result.json` artifacts existed, but no real captured
result had traversed normalization, comparison, score materialization, and score
validation. `experiments/experiments.csv` still contained only its header.

### Hypothesis

Two independent answered attempts for the same dev-A question would expose any
type-boundary or normalization mismatch before label release. Their agreement is
useful only as a plumbing oracle; it cannot establish benchmark correctness.

### Decision and rationale

Use two already-immutable `archeology_scan_3:C2` attempts. This question is in
dev-A. Both attempts were produced from public inputs, both have complete result
sidecars, and neither requires hidden annotations. Treat the second result as a
self-consistency reference, not as ground truth.

### Intervention

Added a narrow CLI that verifies the generation-to-result hash binding, decodes
typed rows, invokes both frozen comparison paths, creates an immutable score
artifact for each path, validates those artifacts, and emits a hash-bound
evidence receipt. The exact exercised command was:

```bash
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/gold_free_scoring_exercise.py \
  --workspace /tmp/omni-benchmark-gold-free-scoring \
  --left-generation /home/ds/projects/omni-benchmark/experiments/autoresearch/raw/c2-archeology-vertical-50ebc31/generation.jsonl \
  --left-result /home/ds/projects/omni-benchmark/experiments/autoresearch/raw/c2-archeology-vertical-50ebc31/answer.result.json \
  --right-generation /home/ds/projects/omni-benchmark/experiments/autoresearch/raw/public-baseline-v1-auth4/archeology_scan_large/c2/archeology_scan_3-r1/generation.jsonl \
  --right-result /home/ds/projects/omni-benchmark/experiments/autoresearch/raw/public-baseline-v1-auth4/archeology_scan_large/c2/archeology_scan_3-r1/answer.result.json \
  --output-root experiments/autoresearch/raw/gold-free-scoring-exercise-v1
```

### Result

Both paths agreed across 825 ordered rows:

- official-compatible Soft EX: agreement
- corrected sensitivity scorer: agreement

The left generation/result hashes are `810a2d827d91b9deaa4ff5972bd50b534a094d9ab5e17352b9a0b2a08dfda23d`
and `8a3a81ec5432cc6132025c863d50d8f8a4067d2cdfbd50210b7727587c3526e1`.
The right hashes are `dd598dcf1469f5fb57a0f46306a3e176a634bb3ddfe3aaa9ee19a50d7dd231cf`
and `e264f221c44061ab7565b17e8285d46281765e23efbb626dfa0323dfda299809`.
The immutable official and sensitivity score artifacts validated at hashes
`57b50dff24ec1ffbb3411a99f9e9d4d97b738726488f1121acc39c786bd824bf`
and `76d53626fd68b6a0d52906e2baf1cf2603f51cf61d922531456d836dcfc26d0a`.
The evidence receipt hash is
`6d4145491e4ae79ce435852f9c38ee36b99978a702fdd0d34f0177e4a0c35128`.
Its public, row-free tracked receipt is
`experiments/prelabel-scoring-exercise-v1.json` at hash
`08fa442069cd90c466d9f636a60cc663d74eb47a9e24eb871319952adfef2697`.
The first 48-column schema-valid evidence row was added to
`experiments/experiments.csv` as `PLUMBING-001`.

### Interpretation

The result boundary is operational. The two raw result hashes differ because
one attempt preserves a high-precision decimal tag while the other stores a
float, yet both frozen normalization policies compare them as equal under the
public two-decimal, ordered condition. The score schema's `correct` token means
self-consistency agreement only under the explicitly named gold-free scorer;
it must never be aggregated with benchmark correctness.

### Outcome

KEEP

### Product implication

Type-faithful result capture prevents serialization differences from becoming
false evaluator disagreements. The immutable scorer boundary can remain
independent from agent generation once the private evaluator supplies the true
reference results.

### Next step

After authorized label release, feed sealed reference results through the same
normalization and score-artifact boundary. Do not reuse the self-consistency
labels as correctness outcomes.
## 2026-08-28 — D-054: Prespecify a C1 schema-retrieval sensitivity arm

### Decision / experiment

Test whether C1's `no_answer_insufficient_context` rate is robust to the
schema-retrieval width. Bead
`omni-benchmark-dih.5.4.2.4.4.2.2.4`; change type: evaluation robustness check,
not a candidate system improvement.

### Observation

The running direct baseline surfaced early C1 no-answer outcomes attributed to
insufficient visible schema. A narrow retrieval tool and a genuinely limited
raw-schema agent imply opposite product conclusions, so the mechanism needs an
isolated check.

### Hypothesis

If the four-table schema window is materially causing the no-answer behavior,
raising only that window to eight tables should reduce
`no_answer_insufficient_context`. If the rate remains similar, the C1 result is
more robust to this scaffold choice.

### Decision

Before consulting question-level baseline outcomes, select a deterministic
20-question public-development subset across all 16 included databases,
stratified by database and public `high_level`. Run C1 once with
`MAX_SCHEMA_MATCHES=8`; hold the 64 KiB per-call payload ceiling, question,
model, prompt, instructions, budget, retries, database targets, execution, and
telemetry fixed. Use a separate immutable run ID and never selectively rerun.

### Rationale

Twenty attempts cover every included database while fitting beside the running
baseline. This directly distinguishes the retrieval-width explanation from the
raw-schema-capability explanation without modifying the baseline in flight.

### Intervention

The selected-ID artifact SHA-256 is
`201f51d8a678d776607da8e836003d139cb8ab2632bdbd34742a858cf372ab42`;
the allocation-metadata SHA-256 is
`fd3640e65ea2bb9c1c9fee3f04fa5a5eecc1b63be4ab191be55895be89056714`.
The isolated runner validates those artifacts from git and changes the schema
match cap from four to eight. At the observed $2.19 direct-attempt mean, the
point projection is $43.80; the 20-attempt, $12-per-attempt notional maximum is
$240. OAuth spend is telemetry, not a stopping rule. The legacy batch budget is
set to a mathematically nonbinding capacity; launch instead requires more than
1,200 seconds remaining, comprising a 600-second projection plus a 600-second
margin, and then runs all 20 attempts to completion.

### Result

The subset and runner are prepared but intentionally not launched while the
three authenticated comparator profiles are leased by the canonical baseline.
No question-level baseline outcome, hidden annotation, gold SQL, or test data
was used to select membership.

### Interpretation

No result is available yet. Both prespecified outcomes remain informative: a
flat insufficient-context rate supports C1 robustness, while a large reduction
identifies retrieval width as a comparator scaffold confound.

### Outcome

FOLLOW UP

### Product implication

Agent telemetry should make insufficient context distinguishable from content
refusal and expose what schema was retrieved. Otherwise a retrieval limit can
be misread as model capability or safety behavior.

### Next step

After the baseline releases the OAuth profiles, launch the fixed arm once and
compare `no_answer_insufficient_context`, cost, tokens, and database-query
counts against the same 20 C1 baseline attempts.

## 2026-08-28 — D-055: Limit supervised optimization to four mechanism tests

### Decision / experiment

Preregister the same-day dev-A intervention sequence before baseline scoring is
available. Bead `omni-benchmark-dih.4.2`; change type: research-plan freeze.

### Observation

Public representability evidence identifies two structural bottlenecks: only
193 of 1,090 HKB nodes compile, while 511 are deferred cross-grain, and the HKB
contains 945 declared dependency edges with chains up to depth six. Another 193
definitions remain searchable context, so discoverability is separable from
representability. D-045 and D-054 also show that context volume is a material
scaffold variable.

### Hypothesis

Four controlled experiments can distinguish the highest-value explanations:
same-grain dependency composition, missing safe relationship/grain contracts,
weak bounded descriptions, and the competing claim that simply exposing more
HKB text is sufficient.

### Decision

Freeze E01--E04 before consulting question-level baseline results. Every
promotion-eligible change must run on all 154 dev-A questions, preserve the
entire baseline-correct dev-A regression set, fix at least two net answers,
avoid a higher confidently-wrong rate, and remain within the preregistered cost
rule. C4 is the promotion condition; matched C3 results are diagnostic and may
not compensate for a C4 regression. Dev-B stays reserved and unconsumed. The
broad transitive-context arm is a benchmark-specific negative control and
cannot enter the final candidate even if its score rises.

### Rationale

This sequence covers structural, textual, and diagnostic surfaces without an
open-ended prompt search. It favors experiments that separate mechanisms and
produce product evidence over chasing the last training points.

### Intervention

The machine-readable plan is
`experiments/planned-dev-a-interventions-v1.json`. It records each observation,
hypothesis, exact reusable change, generality class, public-mechanism slice,
full-dev-A evaluation, regression check, and keep/revert rule. Question-ID
logic, hidden runtime annotations, gold lookups, near-verbatim examples, and
single-item semantic objects are prohibited.

### Result

Planning only; no intervention has run. Membership and intervention choice use
aggregate public mapping evidence, not current per-question attempt identities
or correctness.

### Interpretation

The experiment count is intentionally small. A failed intervention remains a
result: in particular, E04 can show whether exhaustive business context harms
precision or cost even if it occasionally recovers missing knowledge.

### Outcome

FOLLOW UP

### Product implication

The planned contrasts map directly to product surfaces: dependency-aware model
authoring, relationship/grain contracts, AI-facing semantic descriptions, and
bounded context selection.

### Next step

Freeze and score the public-only baseline, then execute E01--E04 in order unless
the stopping rule fires. Preserve every full-dev-A result and keep/revert
decision in the structured ledger.

## 2026-08-28 — D-056: Quarantine mutable OAuth state and preserve the interrupted baseline

### Decision / experiment

Classify the direct-baseline interruption and construct a deterministic
continuation without treating credential failures as evaluated-system outcomes.
Beads `omni-benchmark-ddy` and `omni-benchmark-6tm`; change type: benchmark
infrastructure recovery.

### Observation

At 14:20 EDT, credential-copy/rotation canaries rewrote the same Claude OAuth
profiles held by the running direct baseline. The next 95 artifacts, spanning
`2026-08-28T18:20:46Z` through `18:26:20Z`, all terminated as
`model_setup_error`. The apparent throughput increase was fast failure, not
faster inference. Active background sessions and independently writable copies
of refresh state made later one-shot validation results unstable.

### Hypothesis

OAuth refresh state behaves as a mutable lease. Refreshing, copying, or
validating one copy while another process holds the same identity can revoke or
supersede the other copy. A benchmark process therefore cannot safely repair
its own credentials, and a local expiry timestamp or one successful invocation
does not prove run-duration stability.

### Decision

Stop the direct lane. Preserve the 112 attempts completed before the incident;
authorize reruns only for the exact 95-attempt infrastructure window; never
rotate, refresh, copy back, or validation-test a credential while a benchmark or
background session may hold that identity. Future recovery requires a
human-owned canonical login followed by an exclusive, run-duration credential
lease. Authentication failure pauses the lane instead of triggering automated
repair.

### Rationale

Rerunning wrong answers, refusals, or normal evaluated-system failures would
violate the protocol. These 95 attempts are different: an external credential
mutation invalidated every trial in a bounded, contemporaneously recorded
window. Exact binding prevents the exception from becoming a general rerun
mechanism.

### Intervention

Commit `0541c5c` adds a deterministic continuation manifest and launcher. It is
hard-bound to the frozen direct-system commit, original run and schedule,
incident class/window/count, source artifacts, and expected manifest hash. Each
rerun receives fresh run and attempt provenance linked to its invalid
predecessor. The credential policy is recorded in `AGENTS.md`, `CLAUDE.md`, the
human decision queue, and Beads at commit `782a9d7`.

### Result

The continuation reconciles the original 630-trial schedule exactly once: 112
valid attempts preserved (89 answered and 23 insufficient-context outcomes),
95 authorized infrastructure reruns, and 423 never-attempted trials, producing
518 fresh attempts. Manifest SHA-256:
`751a2a7081958d3d35d051ca47d9f62481d3df082048c7644b125bc093179717`.
The implementation passed 1,416 tests with five environment skips, 84.46%
branch coverage, Ruff, and independent review. It has not been launched because
exclusive OAuth ownership is not yet proven.

### Interpretation

Credential rotation was the failure mechanism, not a remedy. Benchmark
reproducibility requires ownership and lifecycle isolation for OAuth state just
as it requires database and artifact isolation. Throughput diagnostics must
separate completed inference from fast setup failure.

### Outcome

KEEP

### Product implication

This is primarily a comparator-harness finding rather than evidence about Omni.
Long-running agent evaluations need a credential broker or exclusive identity
lease that exposes expiry and refresh ownership without cloning mutable OAuth
state.

### Next step

Keep the direct lane paused until three comparator identities demonstrate
stable repeated benchmark-transport invocations under exclusive ownership;
then execute the committed 518-attempt continuation exactly once.

## 2026-08-28 — D-057: Correct the OAuth lease mechanism from measurement

### Decision / experiment

Test whether an immutable copied OAuth profile is intrinsically incompatible
with Claude Code, or whether the incident instead requires source quiescence,
token headroom, and filesystem isolation. Bead `omni-benchmark-0e8`; change
type: infrastructure-mechanism correction.

### Observation

D-056 inferred that cloned refresh state was the architectural error. A
separate controlled account-1 lease test contradicted that inference. A new
0700 lease containing one 0600 credential file and minimal onboarding/account
configuration was pinned, mounted read-only, invoked successfully, and remained
byte-identical. The source credential also remained unchanged. Conversely, all
five canonical account configuration directories are mode 0775 and therefore
fail `validate_private_directory`; they could never have been passed directly
to the frozen transport. Accounts 3 and 4 also had attached sessions, making
their identities non-quiescent regardless of credential freshness.

### Hypothesis

An immutable lease is safe when its access token has more headroom than the
maximum run duration and no other process can refresh the same identity. The
failure mechanism is leasing a non-quiescent or insufficient-headroom identity,
not the mere presence of an unused refresh token in a read-only snapshot.

### Decision

Retract the benchmark-specific in-place refresh-broker proposal. Automate a
preflight that refreshes before freezing when necessary, requires zero attached
sessions, verifies token headroom beyond the run plus margin, creates a private
minimal lease, pins the committed Claude binary, and forbids every writer until
release. A general fleet broker remains useful only if it relinquishes the
leased identity for the entire benchmark run.

### Rationale

Refreshing underneath `verify_unchanged()` would deliberately violate the
identity invariant and could revoke the snapshotted access token. The measured
read-only lease preserves both reproducibility and authentication without that
race.

### Intervention

No benchmark code or credential was changed in this decision entry. Bead
`omni-benchmark-0e8` was rewritten around immutable lease preflight. One open
compatibility check remains: the successful lease canary used Claude CLI
2.1.251, while the frozen C1--C3 transport may pin 2.1.250 and its exact SHA.

### Result

One account-1 lease passed private-directory validation, resource pinning,
post-20-second identity verification, a completed read-only auth invocation,
post-run byte identity, and 30 seconds of idle stability. Accounts 3 and 4 were
not yet eligible because they had three and two attached sessions respectively.

### Interpretation

The earlier causal claim was too broad. Credential copying is hazardous only
when another holder may rotate the identity or the lease outlives its access
token. A frozen, adequately provisioned, exclusively owned lease is compatible
with the benchmark's immutable transport.

### Outcome

KEEP

### Product implication

Long-running OAuth evaluations need explicit lease headroom and ownership
telemetry. Automatic refresh is valuable for the shared fleet, but benchmark
workers need an observable handoff from mutable fleet state to a quiescent
immutable lease.

### Next step

Let the existing account-lane owner finish accounts 3 and 4. Before any direct
continuation, verify zero attached sessions, three sequential immutable
invocations per lease, exact frozen binary version/SHA compatibility, and token
headroom beyond the scheduled wall bound. Do not mutate credentials from this
workspace.

## D-071: The two failing databases were never fully restored, and the omission mechanism hid it

> **Retracted by D-072.** The conclusion below is wrong: the skipped tables are
> an upstream defect that the inventory reproduces on purpose, not a provisioning
> defect in this repository. The measurements stand; the diagnosis does not. Do
> not act on the fix described here.

### Hypothesis

D-070 concluded that the benchmark's own gold SQL does not execute on
`mental_healths_large` and `organ_transplant_large`, and `omni-benchmark-2j9`
was closed as refuted after live parity matched the committed fingerprints. The
leading remaining explanation was that the per-database read-only reader held
catalog access but lacked SELECT on data tables, which would fit catalog-only
success, uniform data-table failure across all three conditions, and a
catalog-based fingerprint that still matches. That hypothesis predicted a live
permission error and required a live diagnostic query to test.

### Result

The question resolved offline and the permission hypothesis is refuted. Two
earlier candidates fell first. No question in any of the 18 databases carries a
non-empty `preprocess_sql`, so no missing preparation step is involved. Both
committed schema files create unqualified public-schema tables and neither
`postgres_execution.py` nor `direct_sql_capture.py` sets `search_path`, so
schema qualification is not involved either.

Comparing declared tables in
`data/raw/livesqlbench-large-v1/schema/<db>/<db>_schema.txt` against
`verification.table_count` in `config/databases/livesqlbench-large-v1.json`
shows the two databases are truncated and the other sixteen are not:

| Database | Declared | Restored | Missing |
| --- | ---: | ---: | ---: |
| mental_healths_large | 55 | 21 | 34 |
| organ_transplant_large | 57 | 20 | 37 |
| other 16 databases | | | 0 |

The missing sets are exactly the recorded `scorer_omitted_tables` entries, 34
and 37. Case-insensitively every declared table has a dump file, 55 of 55 and 57
of 57. Case-sensitively none of the omitted names resolve, 0 of 34 and 0 of 37,
and each has a dump file differing only in capitalization: `Facilities` against
`facilities.sql`, `HLA_Info` against `hla_info.sql`.

`restore_database` in `database_postgres.py` builds each candidate as
`dump_root / f"{table}.sql"` and, for any table in `omitted_tables`, asserts the
candidate does not exist before skipping it. On a case-sensitive filesystem that
assertion passes for all 71 tables, so real data was dropped as a declared
omission instead of raising a restore failure. Both `scorer_omitted_tables` and
`scorer_continues_after_sql_error` date to `de7ed6d`.

Every downstream check passed because `verification.schema_sha256`,
`content_sha256`, `readonly_role_verified`, and `external_parity` were all
computed against the truncated state. D-068's classification work and 2j9's
parity check were each correct about what they compared; neither could have
detected a defect that the fingerprint itself encodes.

### Outcome

Filed as `omni-benchmark-39b`, which blocks `omni-benchmark-wk0` and therefore
`omni-benchmark-aez.7.1`. 18 dev-A questions are recoverable rather than
permanently lost, so the coverage frame `wk0` decides should be settled after
the repair, not against present numbers. The 54 `gold_statement_error` attempts
in the completed direct baseline were correctly classified and become
re-runnable under the protocol's rerun policy as a demonstrable failure outside
the evaluated system. Freeze B must not commit these two snapshot identifiers as
they stand, since the sealed split is stratified by database. No live query,
credential, lease, or remote action was required to reach this result.

The generalizable lesson is that a verification fingerprint computed after a
provisioning step can only confirm self-consistency, never completeness. The
declared-versus-restored reconciliation that found this took one comparison and
was never part of the provisioning gate. Step 5 of `39b` extends it to all 18
databases.

### Fix

`src/omni_benchmark/dump_coverage.py` now resolves a restore order against a
dump directory independently of the database client, so the same resolution can
be audited without a live connection. `index_dump_files` maps each casefolded
dump stem to its file and rejects two files differing only in capitalization.
`describe_dump_coverage` reports rather than raises, returning load paths in
restore order alongside missing tables, case mismatches, and contradicted
omissions. `restore_database` delegates to it and refuses any omission that a
dump file contradicts, naming both the table and the file.

The bead was filed asking that resolution reject capitalization-only mismatches.
That would have left the restore broken, because the mismatch is in the restore
order rather than in the dump: `facilities.sql` contains
`CREATE TABLE public.facilities`, and the schema file declares the table
unquoted and lower case. The filename is only a selector and the file carries
the authoritative identifier, so resolution is case-insensitive and the
strictness moved to where the data loss actually occurred.

`database_cli verify-dump-coverage` reports every inventory database and exits
non-zero when any is incomplete. Against the real upstream dumps it returns exit
code 1 with 71 contradicted omissions and zero genuinely missing files, confined
to the two known databases. The single omission on
`labor_certification_applications_large` is genuine, has no file under any
capitalization, and that database reports complete. No other database is
silently truncated.

Full suite 1,512 passed with three expected environment skips at 84.23% branch
coverage; the three touched modules are at 100%, 92%, and 89%. Clearing
`scorer_omitted_tables` was deliberately left undone: it changes a file whose
SHA-256 is pinned as `inventory_sha256` and verified against published run
sidecars, and it must land together with re-provisioning or the recorded
`verification.table_count` becomes inconsistent.

## D-072: D-071 was wrong. The missing tables are an upstream defect, and the omission mechanism reproduces it correctly

D-071 concluded that `mental_healths_large` and `organ_transplant_large` were
never fully restored because of a case-sensitive dump lookup in this repository,
and that the data was recoverable by fixing resolution. That conclusion is
refuted. The behavior is upstream's, the inventory reproduces it faithfully, and
the fix committed as `f5f756b` would have broken comparability with published
LiveSQLBench results.

### Hypothesis

If the case-sensitive lookup were a defect local to this repository, the pinned
official loader would resolve those dump files successfully on its own image, and
its reference database would contain all 55 and 57 tables.

### Result

It does not. `data/raw/livesqlbench-large-v1/init-databases_postgresql_large_v1.sh`
lines 118-127 load each table with an exact filename match and skip on a miss:

    for table in $tables; do
        local sql_file="${db_folder}/${table}.sql"
        if [[ -f "$sql_file" ]]; then
            psql -U root -d "${db_template}" -f "${sql_file}" ...
        else
            echo "Warning: SQL file ${sql_file} not found for table ${table}"
        fi
    done

Its table list for `mental_healths_large_template` spells the first entry
`Facilities`. The archive ships `facilities.sql` and no `Facilities.sql`. The
pinned image is Linux, so `[[ -f ]]` fails, the loader warns, and the table never
enters the reference database. The same holds for 34 tables there and 37 in
`organ_transplant_large`.

The arithmetic closes it. `mental_healths_large_template` holds 57 dump files, 21
of which carry capital letters. The committed `verification.table_count` is 21.
Those are exactly the files whose spelling matches the restore order, which is
exactly the set upstream loads. 55 declared minus 21 loaded is 34, which is the
committed `scorer_omitted_tables` list element for element. `organ_transplant_large`
gives 20 loaded against 57 declared and 37 omitted, and its recorded table_count
is 20.

So the restore was never truncated relative to its target. It reproduced the
official environment, which is what it was built to do.

`docs/database-setup.md` already recorded this and the investigation read past it:
"The pinned scorer script silently skips those paths. To reproduce that behavior
without weakening restore checks, the public inventory lists every scorer-omitted
table explicitly." The mechanism is deliberate, and it is the same principle as the
frozen Soft EX scorer that reproduces lossy behavior on purpose.

### What D-071 got wrong, and why

Three claims in D-071 are false and are retracted:

- "This is a provisioning defect in this repository, not an upstream benchmark
  defect." It is the reverse.
- "The data is present locally and fully recoverable." The bytes are in the
  archive, but the tables are not recoverable into a database that stays
  comparable to the scorer's.
- "Every downstream check passed because the verification fingerprints were
  computed after the truncated restore." The fingerprints match because they
  describe the correct database.

The error was method, not evidence. Every measurement in D-071 is reproducible and
still correct. What was never checked was the one artifact that defines the target:
the pinned upstream loader. The investigation compared the archive against the
restore order and inferred intent from the mismatch, when the script that consumes
both was sitting in `data/raw/` and answers the question directly. A finding about
whether behavior is a defect cannot rest on the behavior alone; it needs the
specification the behavior is supposed to meet.

Reading `docs/database-setup.md` before rewriting the code it describes would also
have caught it. The doc stated the intent plainly.

### Consequence for the evaluation

Twenty-seven dev-A questions, 14 on `mental_healths_large` and 13 on
`organ_transplant_large`, reference tables that do not exist in the official
reference database. Their gold SQL fails there as it fails here, which is what the
`gold_statement_error` classification on those attempts records. Ninety-six attempt
directories across C1, C2, and C3 cover them, and 92 hold no `answer.result.json`
at all.

These questions are not answerable by any system evaluated against the official
environment. They are not a deployment gap and no reruns will recover them. The
disposition is an exclusion record with the same evidence discipline as
`public-baseline-exclusions-v1.json`, and the finding belongs in the writeup as a
property of the benchmark.

The gold for those questions was presumably authored against a database where the
files did resolve, which suggests development on a case-insensitive filesystem. That
does not change what the official scorer does, and the protocol says to reproduce the
official scorer.

### Outcome

`f5f756b` is reverted in behavior. `restore_database` returns to exact-match
resolution, and the two databases are restorable again; under the reverted code they
were not, because it refused the correct configuration.

Kept in corrected form: `dump_coverage` and the `verify-dump-coverage` subcommand,
reframed from completeness to fidelity. They now check that `scorer_omitted_tables`
equals the set the official loader actually skips, and separate the two kinds of
skip. Against the real archive all 18 databases reproduce the official loader, exit
code 0: 71 tables skipped over a case variant present in the archive, and one on
`labor_certification_applications_large` absent under any spelling.

No inventory field was changed, no database was re-provisioned, and no attempt was
rerun. The `inventory_sha256` pin is untouched.

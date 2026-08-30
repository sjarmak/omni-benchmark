# Research decision log

This is the chronological, human-readable account of what we believed, why we
acted, what happened, and how our understanding changed. It complements the
machine-readable experiment ledger; it does not replace run artifacts. Entries
are append-only. Private SQL, hidden annotations, test-case bodies, credentials,
and sealed outcomes are prohibited.

### Canonical numbering after the 2026-08-29 lane reconciliation

The two development lanes assigned several different decisions the same number.
Both histories are retained here. To make every identifier unique without moving
main's D-140 decision, the branch-lane identifiers were remapped as follows:

- D-054 → D-121: product-native failure and truncated-preview records
- D-055 → D-132: selected output fields versus helper metadata
- D-056 → D-133: interrupted C4 baseline quarantine
- D-068 → D-134: mechanical system/infrastructure boundary
- D-069 → D-135: bounded-retrieval cost at full n
- D-070 → D-136: first scored dev-A accuracy
- D-071 → D-137: initial missing-database interpretation
- D-072 → D-138: corrected upstream-defect interpretation
- D-073 → D-139: corrected dev-A arithmetic

All other identifiers retain their lane number. References in this repository
use these canonical identifiers.

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

## 2026-08-28 — D-052: Freeze C4 baseline coverage after four diagnostic deployment runs

### Decision / experiment

Preserve the complete v3--v6 public-only deployment trajectory, accept the
largest exact-readback subset for the time-boxed C4 baseline, and stop semantic
deployment optimization before question generation. Bead
`omni-benchmark-dih.17`; change type: general system integration. Last updated:
2026-08-28 13:39 EDT.

### Observation

D-050 mixed semantic validation defects with request-rate failures. Subsequent
runs isolated three additional mechanisms: stale invalid branches needed a
corrected upload, the API required global request pacing even with one worker,
direct physical dimensions needed exact public-column SQL, and Omni readback
removed redundant direct-column SQL after accepting it.

### Hypothesis

Each general mechanical correction should remove its diagnosed failure class
without changing HKB definitions or benchmark-question behavior. If a paced,
content-addressed run still left substantial validator failures after those
classes were removed, continuing to optimize deployment would yield less
submission value than freezing the verified subset and measuring it.

### Decision

Run each correction under a new append-only run ID and preserve failures. Allow
readback equivalence only when the compiler-attested manifest proves the exact
view, semantic field, source-column stable ID, and identity SQL that Omni
stripped. Do not normalize authored, structured-leaf, or derived SQL. After v6,
freeze C4 baseline coverage at the ten databases with zero validator issues and
exact semantic readback. Do not tune the remaining eight before baseline.

### Rationale

The sequence tests one mechanism at a time and retains the negative results.
The cutoff favors an executable, interpretable baseline over broadening into
table availability, structured-field extraction, type coercion, or parser
exceptions without question-level evidence.

### Intervention

- `public-baseline-v3-20260828`, source `b5959dc`: re-upload corrected bundles
  to stale invalid branches, with no request pacing.
- `public-baseline-v4-20260828`, source `2713222`: serialize deployment and
  enforce a 1.25-second global minimum between product API request starts.
- `public-baseline-v5-20260828`, source `d359ae2`: bind direct physical fields to
  exact public-schema identifiers while leaving authored and derived SQL
  unchanged.
- `public-baseline-v6-20260828`, source `7c669e5`: attest those mechanical
  identity bindings in the bundle manifest and treat only Omni's omission of
  their redundant `sql` property as semantically equivalent on readback.

### Result

The v3 run verified 5/18 databases; 13 failed at the product API after request
rate exhaustion. Aggregate artifact SHA-256:
`c03c8f8a42c4e1206a7755100c0130d0a70583b8d1ec5b0ab76be1cf4853f729`.

The paced v4 run verified 9/18 and converted every remaining failure into a
stable validator result: 110 issues across nine databases, with no rate-limit
or product-API terminal failure. Aggregate artifact SHA-256:
`7b3679a1903ef32a33b425822b6843484ce9b8e23b8c3fb7490247302c7f94d7`.

The exact-column v5 run removed 24 validator issues: labor fell from five to
zero and polar from 29 to ten. It verified 7/18; cross-border, cybermarket, and
labor were validator-clean but failed strict readback because Omni removed the
now-redundant identity SQL. Eight databases retained 86 validation issues.
Aggregate artifact SHA-256:
`6bd7e7033801a20e18244db4fb55eae037d50b96cedca474f41550e97eb03525`.

The attested-readback v6 run verified 10/18 with no semantic regression. It
promoted exactly the three validator-clean readback failures and left the same
86 issues on the same eight databases: mental health 6, organ transplant 7,
planets 2, polar equipment 10, robot fault prediction 3, solar panel 26, sports
events 7, and virtual idol 25. Aggregate artifact SHA-256:
`f6b59ceac8d8a04d431d43d5d309fbb1be5451d0054b18ef07693d890dda8836`;
claim SHA-256:
`57575e40a15208391d67eb608d2efe213f673998a398cff8ee1e86ebbcd68319`.
The frozen verified subset is archeology, cross-border, cybermarket, disaster
relief, exchange-traded funds, fake account, labor certification, museum
artifact, residential data, and reverse logistics. Each immutable record binds
its exact model ID, branch ID, manifest SHA-256, source commit, validation count,
and readback state.

### Interpretation

The hypotheses were partially correct. Request pacing and direct-column binding
were general fixes with clean causal signatures. Exact byte-shaped readback was
too strict for a product that canonicalizes redundant identity SQL, but a broad
normalizer would have hidden real differences; compiler-attested equivalence
closed only the observed product rewrite. The unchanged residual vector shows
that the remaining eight databases have different representability or product
validation problems, not another instance of the repaired identity mechanism.

### Outcome

KEEP the three general fixes and the ten-database C4 baseline subset. DEFER the
eight residual validation classes until after the public-only baseline.

### Product implication

Omni model import/readback needs a documented canonical form or immutable
semantic revision hash so automation can distinguish safe product normalization
from drift. Bulk model workflows also need structured rate-limit guidance.
Validator issue classes successfully separated field-binding defects from
structured-field, table, type, and parser gaps, but those details currently
require external trace collection.

### Next step

Attach the reviewed v6 deployment gate to C4 baseline dispatch for only the ten
verified databases. Run no further semantic deployment optimization before the
baseline evidence and failure taxonomy are preserved.

## 2026-08-28 — D-053: Bind the partial-coverage C4 baseline before dispatch

### Decision / experiment

Define the public C4 product arm and matched comparator population before any
scaled question generation. Bead `omni-benchmark-aez`; change type: evaluation
execution. Last updated: 2026-08-28 14:07 EDT.

### Observation

The governed semantic deployment gate verifies ten databases, containing 129
of the 231 public training questions. Eight of those databases, containing 108
questions, also remain in the current direct C1--C3 baseline. C4 cost telemetry
is not observable, so a dollar-derived sample size would turn an unknown
co-outcome into an arbitrary experimental constraint. Omni permits five
concurrent jobs.

### Hypothesis

Running the complete 129-question verified C4 population will produce more
useful product evidence than randomly sampling it if a five-attempt throughput
canary shows the arm is operationally feasible. Keeping the 108-question
intersection as a separate committed analysis population preserves paired
C1--C4 comparisons without discarding valid C4 product evidence from archeology
and cybermarket.

### Decision

Select every public train ID from the ten verified databases. Use no random
seed and no outcome or hidden annotation. Order database blocks
lexicographically and preserve the source train-manifest order within each
block. Commit a second ID file for the eight-database paired intersection.
Reference the immutable v6 deployment claim and its ten verified records; do
not rewrite or relabel the original 18-record evidence.

Bound live execution by wall clock rather than dollars. Admit no more than five
database-condition blocks concurrently. Once the wall-clock boundary is
reached, finish every already-started database/C4 block before stopping, and do
not admit another block. Dollar cost remains telemetry only.

### Rationale

The product arm answers C4's primary performance question on every semantic
model that passed the preregistered deployment gate. The separate paired arm
keeps the comparative estimand explicit. Database-block stopping avoids an
arbitrary within-database truncation while allowing the run to resume from
immutable per-attempt artifacts.

### Intervention

Add a byte-regenerable public arm manifest, exact full and paired ID lists,
per-database and `high_level` allocation diagnostics, a C4-only batch selector,
a derived deployment verifier over committed v6 evidence, a five-attempt
throughput canary, and wall-clock block-boundary stopping in the existing
resumable scheduler.

### Result

Pre-launch identity only. The product arm contains 129 questions across ten
databases; the paired arm contains 108 questions across eight databases. Full
ID SHA-256: `ea6de0355419f912072b45ade4a7dda7b0f5b74a8b7a2020dc3534c66fbb9f05`.
Paired ID SHA-256:
`f27ab4ca2acda08b3df10279afa0c10bc7e838cccf11d83e223134f9ffcaf610`.
No question has been generated by this experiment yet.

### Interpretation

Pending the five-attempt public C4 throughput canary.

### Outcome

FOLLOW UP.

### Product implication

Omni's five-job limit and unobservable managed-model cost make throughput and
terminal behavior more actionable operational constraints than a fabricated
cost ceiling for this run. Cost remains valuable telemetry if the product
exposes it later.

### Next step

Commit and independently review the arm identity and dispatcher. Report the
notional cost scenario and exact launch path, then run the five-attempt canary
before deciding whether to dispatch all 129 attempts.

## 2026-08-28 — D-121: Adapt product-native failure and truncated-preview records

### Decision / experiment

Diagnose the uniform C4 capture-gate failure before dispatching the 129-question
arm. Change type: general system integration. Last updated: 2026-08-28 14:32
EDT.

### Observation

The first concurrency canary failed before authentication because its child
environment omitted the already-configured Omni origin. A fresh infrastructure
rerun then reached the origin but found that the existing OAuth session returned
HTTP 403. Both attempts stopped before question generation and retained five
immutable infrastructure diagnostics. After the human renewed OAuth, run
`public-c4-concurrency-canary-v3-20260828-1425` completed five product jobs at
concurrency five, but all five terminal artifacts were
`errored / response_contract_error`.

The completed jobs used 5,453,733 tokens, 63 tool calls, and 17 database queries.
Their median latency was 80.2 seconds and their full concurrent wall span was
175.3 seconds. Read-only retrieval of the five public canary job results showed
two concrete response-contract differences: four jobs contained product-native
`failure` actions without timestamps before later successful queries, and three
final truncated CSV previews embedded one-column section records such as
`# FIRST 63 ROWS:` among ordinary multi-column rows.

### Hypothesis

The governed queries completed, but the external capture adapter rejected two
documented product response shapes before it could rerun the final semantic
query for a complete typed result. Narrowly accepting the timestamp-free failure
record and stripping only exact control records from an explicitly truncated
preview should make all five preserved responses scoreable without relaxing
ordinary action timestamps or ragged CSV validation.

### Decision

Do not launch the 129-question arm. Write failing tests for both observed shapes,
make the smallest reusable result-adapter change, replay all five public-only
responses locally, independently review the fix, and require a fresh live
five-attempt canary before scale dispatch.

### Rationale

The five failures share the same adapter boundary but contain two structural
variants. Treating the entire response as trusted, dropping all failure actions,
or accepting arbitrary ragged CSV would conceal real contract problems. Exact
shape handling preserves fail-closed behavior while separating product query
failure/recovery from benchmark harness failure.

### Intervention

Accept a timestamp-free action only when its type is `failure`, `isError` is
true, its tool name is present, and its finite duration is non-negative. For an
explicitly truncated CSV preview only, remove exact `FIRST`, `SAMPLED ... FROM
MIDDLE`, and `LAST` section-control rows before validating the remaining row
shape. Untruncated and arbitrary ragged rows remain errors.

### Result

The two tests failed before the change and pass afterward. All five immutable
public canary job responses now parse locally: expected final row counts are
687, 5, 940, 10, and 178, with the original database-query counts 1, 3, 2, 5,
and 6. The broader result/capture/attempt-adapter suite passes 61 tests. Live
verification remains pending.

### Interpretation

The hypothesis is supported by preserved-response replay, not yet by a fresh
product run. The governed jobs were not model failures; strict external parsing
misclassified recoverable product-native action history and preview formatting
as terminal harness errors.

### Outcome

FOLLOW UP.

### Product implication

AI Hub makes query attempts and failures visible, but machine clients need a
stable action schema and explicit structured preview metadata. Formatting
section labels as CSV rows forces every downstream client to rediscover a UI
presentation convention, while failure actions omitting the timestamp required
by other action types complicate uniform trace processing.

### Next step

Commit the reviewed adapter fix and rerun a fresh immutable five-attempt C4
canary. Launch the 129-question arm only if capture verification passes.

## 2026-08-28 — D-132: Separate selected output fields from helper metadata

### Decision / experiment

Diagnose the two remaining response-contract failures in the fresh C4 capture
canary without treating valid evaluated-system failures as harness defects.
Change type: general system integration. Last updated: 2026-08-28 14:45 EDT.

### Observation

Run `public-c4-concurrency-canary-v4-20260828-1434` at commit `9526505`
captured three of five attempts successfully. Disaster relief and ETF both
completed a governed query, reached a `PLANNED` semantic query plan, and
returned JSON rows, but the adapter rejected their plan metadata as ambiguous.
The disaster plan selected three output fields while its summary also described
the helper field `damage_report`; the ETF plan selected four output fields while
its summary also described `platform_tier`.

The five jobs used 4,523,303 tokens, 60 tool calls, and 18 database queries over
a 113.8-second concurrent wall span. Read-only replay of the two preserved
public responses showed 240 complete disaster rows and 185 complete ETF rows.

### Hypothesis

Omni's plan summary is a dependency superset rather than an output schema. The
authoritative selected fields are the identical lists in the submitted semantic
query and `plan.query.model_job.fields`; requiring summary metadata for that
selected subset should admit helper dependencies without making column binding
ambiguous.

### Decision

Allow extra summary metadata only after proving that the query field list is
non-empty and unique, exactly matches the planned model-job field list, every
selected field has summary metadata, and the selected-field count matches the
returned column count. Do not infer a result type when the plan reports
`UNKNOWN`; preserve it as a distinct evaluated-system failure.

### Rationale

Dropping summary validation would weaken the type-faithful scorer boundary.
Conversely, requiring helper metadata to equal the selected output turns an
internal planning detail into a false harness error. A dedicated unsupported
type outcome distinguishes a product representability gap from malformed
capture while avoiding unsafe value-based type inference.

### Intervention

Validate selected fields against `plan.query.model_job.fields` and use only
their summary entries for type binding. Add
`unsupported_semantic_result_type / ERROR` for a selected
field whose plan type is not one of the supported authoritative result types.

### Result

RED/GREEN tests cover both mechanisms. Preserved-response replay now binds all
240 disaster rows and classifies the ETF `yield_to_expense_ratio` field as
`unsupported_semantic_result_type` because Omni reports its type as `UNKNOWN`.
No value coercion or inferred type was introduced. Live canary verification is
pending.

### Interpretation

The dependency-superset hypothesis explains the disaster failure. It also
revealed a separate semantic result-schema limitation for ETF rather than a
second instance of the same harness bug. A fresh canary may therefore produce
four captured answers and one explicit evaluated-system failure; that is a
valid capture-gate outcome if no generic response-contract error remains.

### Outcome

FOLLOW UP.

### Product implication

The production plan API should distinguish selected output fields from
dependency/helper fields and expose an authoritative executable output type for
every selected semantic field. Without both contracts, external consumers must
either reject otherwise valid governed results or guess how to coerce them.

### Next step

Independently review the narrow adapter change, commit it in the isolated C4
branch, and run a fresh immutable five-attempt canary. Launch the 129-question
arm only when remaining failures are explicitly classified evaluated-system
outcomes rather than capture or infrastructure errors.

## 2026-08-28 — D-133: Quarantine the interrupted C4 baseline arm

### Decision / experiment

Preserve the interrupted public-only C4 run as diagnostic evidence while
preventing it from entering any baseline or score artifact. Change type:
general system integrity. Experiment ID: `INFRA-C4-001`. Last updated:
2026-08-28 15:05 EDT.

### Observation

Run `public-c4-baseline-v1-20260828` stopped after persisting 11 generation
records: six answered and five ended with `adapter_transport_error`. Two
additional dispatcher artifacts record separate pre-attempt HTTP 429 failures
from `whoami`. No correctness result was observed and no gold data was
accessed. The five adapter transport records do not retain enough transport
detail to attribute their cause to authentication or to any more specific
mechanism; the adjacent dispatcher 429s are separate evidence, not proof that
all five shared that cause.

### Hypothesis

An incomplete, infrastructure-interrupted arm can be mistaken for a valid
baseline if its answered records are later gathered or its run ID is reused.
Content-hash quarantine plus fail-closed loader checks will preserve the raw
evidence without allowing that ambiguity.

### Decision

Mark the entire run non-scoreable. Preserve every raw artifact unchanged. Bind
the 11 generation records and two dispatcher failures by path and SHA-256 in a
committed quarantine manifest, and reject this run ID at baseline schedule,
generation-validation, and score-binding boundaries. Do not launch a
replacement from this task.

### Rationale

The six answers are useful operational evidence but do not form the registered
arm. Scoring a selectively completed subset would conflate infrastructure
survival with C4 performance. Deletion would instead erase the incident trail.
Quarantine preserves both facts.

### Intervention

Added
`experiments/quarantines/public-c4-baseline-v1-20260828.json`, a fail-closed
run registry, and loader checks in the baseline, autoresearch-generation, and
score-artifact paths. The structured ledger row is `INFRA-C4-001`.

### Result

The manifest records exactly six answered generations, five adapter transport
failures, and two dispatcher HTTP 429 failures. Its 13 entries bind the
preserved files by SHA-256. Focused tests demonstrate that both baseline
schedule loading and score-artifact creation reject the quarantined run ID.
No generation was rerun and no live Omni action occurred.

### Interpretation

The run is evidence about benchmark infrastructure behavior only. It provides
no accuracy evidence and cannot support a product conclusion about C4.

### Outcome

INCONCLUSIVE.

### Product implication

The distinction between a product-terminal failure and an observer/dispatcher
failure must survive into persisted telemetry. Without it, a benchmark can
silently penalize the evaluated system for its own control-plane interruption.

### Next step

Any future C4 launch requires a separately authorized run ID and its own gate.
The quarantined records remain immutable diagnostic history and must never be
promoted or scored.

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

## 2026-08-28 — D-058: Quarantine the unauthorized C4 production launch

### Decision / experiment

Stop and quarantine `public-c4-baseline-v1-20260828`; correct its failure-origin
accounting before any future governed production run. Beads
`omni-benchmark-aez.1` through `.3`; change type: benchmark-infrastructure
correction.

### Observation

The run produced six answered records and then five consecutive
`adapter_transport_error` records. The five traces reached `EXECUTING` and failed
at approximately the same 51-second wall across independent databases. They had
no captured 401, 403, 429, or HTTP status. Each nevertheless combined
`harness_failure=adapter_transport_error` with
`failure_origin=evaluated_system`. The launch also followed canary v6 without
the required human production-run authorization.

### Hypothesis

The shared timeout shape is an adapter transport failure outside the evaluated
system. Separately, C4 publication assigns every non-answer to the evaluated
system instead of distinguishing product-terminal failures from capture-harness
failures.

### Decision

Stop the run; preserve all records; make the run non-scoreable; reject any
record with non-null `harness_failure` and `failure_origin=evaluated_system`;
close the existing immutable deployment/cost/telemetry gap; and mechanically
require explicit human approval for a production C4 dispatch. Do not launch a
replacement run.

### Rationale

Charging adapter timeouts to Omni would corrupt the C4 result. The protocol
permits reruns only for demonstrable benchmark-infrastructure failures, and the
failed run cannot become an implicit authorization for its replacement.

### Intervention

The process was stopped. The original artifacts remain immutable. TDD work is
in progress under `omni-benchmark-aez.1`; quarantine and dispatch-gate work are
tracked separately so the correction does not silently broaden into new
methodology.

### Result

The run is excluded from scoring pending a committed quarantine artifact. No
correctness result, hidden annotation, or gold data was accessed. Two dispatcher
failures elsewhere in the run do contain HTTP 429 evidence, but that separate
evidence does not explain the five persisted generation-artifact timeouts.

### Interpretation

The earlier suggestion that all C4 failures were authentication-related was
unsupported. Failure origin must follow the captured mechanism, not the
condition being evaluated.

### Outcome

KEEP

### Product implication

This is primarily a benchmark-observability finding. Governed-system evidence
is only credible when product-terminal failures and adapter/capture failures are
separable in raw telemetry.

### Next step

Complete the classifier fix and quarantine, then resolve immutable deployment
identity and cost/telemetry attribution. A new C4 production run remains human
gated.

## 2026-08-28 — D-059: Diagnose the first immutable-lease canary failure

### Decision / experiment

Run a three-slot direct canary from exact commit
`5be315e44bea7ee1a39500380dcbc4c05976dd3e` using the three handed-off immutable
OAuth leases and the frozen Claude 2.1.250 transport. Bead
`omni-benchmark-0e8`; change type: comparator-infrastructure diagnosis.

### Observation

All three children failed before model invocation. The preflight reported
`bytecode differs from source` for three ignored `.pyc` files. The source tree
and commit were unchanged, and no generation record was created.

### Hypothesis

The integrity check compares complete compiled byte streams. Python hash
randomization can change the serialized ordering of unordered constants between
the parent and child interpreters, even when both compile identical source.
Parent-created bytecode therefore becomes a false source-drift signal in a
multi-process run.

### Decision

Classify the three records as benchmark-infrastructure preflight failures. Move
the ignored bytecode out of the exact worktree and relaunch the same canary with
`PYTHONDONTWRITEBYTECODE=1` inherited by parent and children. Do not modify or
revalidate OAuth credentials.

### Rationale

Disabling an ignored runtime cache preserves the frozen source and avoids a
nondeterministic artifact that is neither part of the committed system nor the
evaluated model. It is smaller and more interpretable than changing the frozen
transport during the canary.

### Intervention

The three failed records were preserved under run
`public-baseline-v1-lease-canary-20260828-1514`. Retry run
`public-baseline-v1-lease-canary-v2-20260828-1525` uses the same commit,
questions, profiles, concurrency, and budgets with bytecode writes disabled.

### Result

Pending.

### Interpretation

Pending.

### Outcome

FOLLOW UP

### Product implication

This is comparator harness behavior, not evidence about Omni or direct-SQL
answer quality. Runtime integrity gates should authenticate source content, not
nondeterministic interpreter caches.

### Next step

Inspect the retry artifacts without changing credentials. Only a successful
three-way canary can unblock the committed direct continuation.

## 2026-08-28 — D-060: Validate the leases, expose continuation runtime leakage

### Decision / experiment

Complete the exact frozen-transport lease canary, then launch the already
authorized deterministic continuation for the 95 invalidated and 423
never-attempted direct trials. Beads `omni-benchmark-0e8` and
`omni-benchmark-6tm`; change type: execution integration.

### Observation

With bytecode writes disabled, the three immutable leases completed the fixed
12-attempt concurrency canary with no infrastructure error. The subsequent
continuation stopped immediately on its first three dispatched children. Each
child executed the script in the exact `5be315e` worktree but imported
`omni_benchmark` from the parent continuation worktree, failing the runtime
ownership gate with `direct comparator runtime package does not belong to the
workspace`.

### Hypothesis

The continuation parent correctly needs its newer scheduling code, but its
Python import path leaks into child processes. Child execution must explicitly
resolve the package and script from the frozen execution workspace.

### Decision

Preserve the three failed diagnostics as benchmark-infrastructure failures. Do
not advance or skip them. TDD the child-process environment boundary in the
continuation launcher and relaunch only after focused/full tests and independent
review.

### Rationale

This is a deterministic isolation defect, not a credential or model failure.
Changing OAuth state or retrying unchanged would add noise without addressing
the mechanism.

### Intervention

Canary run `public-baseline-v1-lease-canary-v2-20260828-1525` inherited
`PYTHONDONTWRITEBYTECODE=1`. It completed all 12 scheduled attempts. Continuation
run `public-baseline-v1-direct-16db-continuation-1` then stopped with zero
generation records and three child diagnostics. A dedicated TDD lane owns the
runtime-path correction.

### Result

Canary: 11 answered, one `no_answer_insufficient_context`, zero infrastructure
failures, zero retries, maximum concurrency three, 2,161,895 tokens, 29 database
queries, 52 tool calls, and $15.5811165 measured notional cost. Continuation:
zero scoreable attempts; stopped before benchmark generation.

### Interpretation

The immutable OAuth leases are viable under the frozen transport. The remaining
blocker is process isolation in our continuation harness, not authentication.

### Outcome

FOLLOW UP

### Product implication

This is comparator infrastructure, not Omni evidence. Exact-commit claims must
bind the loaded runtime package, not only the child script path.

### Next step

Land and review the child import-path fix, then resume the same committed
continuation manifest without changing questions, conditions, credentials, or
system configuration. Schedule the long continuation within one immutable-token
window; the standing 19:00 EDT refresh boundary makes a pre-boundary full run
unsafe at observed throughput.

## 2026-08-28 — D-061: Bind continuation children to the frozen runtime

### Decision / experiment

Correct the continuation child-process import boundary exposed by D-060. Bead
`omni-benchmark-6tm.1`; change type: comparator infrastructure.

### Observation

The continuation parent imported its new scheduling implementation correctly,
but each child inherited that parent package path even though its script and
declared workspace pointed at the frozen `5be315e` execution worktree.

### Hypothesis

Giving child processes an explicit execution-workspace package path will let the
parent retain continuation-only code while making the evaluated attempt load
exactly the frozen comparator implementation.

### Decision

Set the child import boundary mechanically from `execution_workspace/src` and
verify both sides in a subprocess test. Keep the continuation manifest, system
commit, questions, and retry authorization unchanged.

### Rationale

The loaded runtime—not the script pathname alone—is the object the experiment
claims to freeze. The fix addresses the observed process-isolation failure
without changing evaluated behavior.

### Intervention

Commit `5748eba228bc8cca824ec94472a1b09da9b4c856` in the isolated continuation
worktree sets and tests the child environment. The test proves the parent loads
`baseline_continuation_cli.py` from the continuation worktree while the child
loads `direct_prepared_attempt.py` from the exact execution worktree.

### Result

Focused tests passed. The full suite passed 1,417 tests with five environment
skips and 84.46% branch coverage. Ruff passed, and independent review reported
no findings. No live attempt or credential was touched.

### Interpretation

The continuation harness can now preserve its control-plane additions without
contaminating the frozen evaluated runtime.

### Outcome

KEEP

### Product implication

This is evaluation infrastructure rather than Omni behavior. Reproducible agent
benchmarks need provenance for the modules actually loaded by subprocesses.

### Next step

Wait for the standing 19:00 EDT credential refresh, rebuild the immutable leases
while no attempt is active, run the bounded continuation canary, then launch the
same 518-attempt continuation within the fresh token window.

## 2026-08-28 — D-062: Resume the vanished direct-baseline dispatcher

### Decision / experiment

Diagnose the unexpected disappearance of the live
`public-baseline-v1-direct-16db-continuation-1` parent and, if the immutable
attempt repository is complete and consistent, resume the exact continuation
without changing its manifest, run identity, output root, evaluated commit,
conditions, questions, credentials, or budgets. Bead
`omni-benchmark-dih.5.4.2.4.4.2.2`; change type: execution infrastructure.

### Observation

The continuation parent and its `uv` wrapper disappeared after 20 complete
generation/run pairs had been captured. The process was not signaled by this
orchestrator and no lease was rebuilt, refreshed, validated, or mutated. Process
inspection found no remaining continuation child. The execution root contains no
incomplete attempt directory and no new failure diagnostic beyond the three
preserved D-060 runtime-path failures.

### Hypothesis

The launcher or owning session exited outside the evaluated system after the last
captured attempt boundary. Because dispatch is reconciled from immutable complete
attempt bundles, rerunning the exact command against the same root should preserve
the 20 captures and schedule only the remaining manifest entries.

### Decision

Treat the parent disappearance as benchmark-infrastructure interruption, not as
an evaluated-system result and not as authorization for a new run identity. First
record the interruption, then resume the same authorized continuation under a
durable launcher. Do not inspect answers or correctness and do not rebuild the
unchanged leases.

### Rationale

The protocol permits rerun for a demonstrable failure outside the evaluated
system. No attempt is selected based on its answer: repository reconciliation
mechanically preserves every complete bundle and retries only entries with no
immutable generation/run pair.

### Intervention

Exact reconciliation reported 20 completed continuation attempts, 498 missing,
112 preserved source attempts, 132 reconciled trials, and the unchanged manifest
and schedule identities. The same command was launched as durable user service
`omni-public-baseline-continuation-1.service` from control commit `5748eba`
against evaluated commit `5be315e`, with the three existing leases unchanged.

### Result

The service became active with exactly three frozen-worktree children. The first
post-resume immutable capture advanced the repository from 20 to 21, completed
normally with zero retry, and introduced no new infrastructure diagnostic.

### Interpretation

Immutable reconciliation behaved as intended: every existing complete attempt
was preserved and dispatch resumed from the next missing entry. A durable service
removes the owning-session lifetime failure without changing evaluated behavior.

### Outcome

FOLLOW UP

### Product implication

This is benchmark process-lifetime behavior, not evidence about Omni or the
direct-SQL agent. Long evaluations require a durable launcher plus explicit
attempt-boundary drain semantics.

### Next step

Monitor the sole service through completion, reconcile all 518 continuation
attempts, and freeze the public-only baseline before any train-label release.

## 2026-08-28 — D-063: Bind C4 semantic content and original budget policy

### Decision / experiment

Resolve the two C4-only provenance/accounting defects on bead
`omni-benchmark-dih.5.4.2.4.4.2.3` in the isolated worktree
`/tmp/omni-benchmark-c4-live-d9949d2`, without launching C4 or touching Omni,
credentials, labels, or the running direct baseline. Change type: general
evaluation infrastructure.

### Hypothesis

An authenticated semantic-plan digest plus an immediate branch re-read can bind
each C4 attempt to immutable deployed content even though the model and branch
IDs are mutable. Persisting the original reservation and budget-policy digest
should make null-cost resume deterministic and reject policy drift.

### Intervention

Added a canonical digest over authenticated deployment-plan semantics; schema-v2
deployment records retain it, while the immutable schema-v1 frozen records derive
the same identity only after their committed manifest and per-file hashes match
the exact committed bundles. C4 dispatch passes the database, semantic digest,
reservation, and budget-policy digest to the child. Before submitting an Omni
job, the child loads the exact system-commit bundle, re-reads the branch, and
requires semantic equality and the expected digest. C4 artifacts persist the
original reservation, policy digest, and explicit unavailable-cost reason;
reconciliation rejects drift instead of substituting the current ceiling.

### Result

The focused suite passed 107 tests. The full suite passed 1,429 tests with five
environment skips and 84.47% branch coverage; Ruff, formatting, and diff checks
passed. Existing frozen deployment records were not rewritten. No C4 attempt,
live Omni call, credential operation, gold/hidden/test/dev-B access, commit, or
push occurred.

### Outcome

KEEP, pending reviewed commit/integration from the isolated worktree.

### Next step

Integrate this prerequisite before any future C4 production authorization, then
rerun the combined suite. C4 remains quarantined.

## 2026-08-28 — D-064: Require a single-use human receipt for C4 production

### Decision / experiment

Implement bead `omni-benchmark-aez.3` only in the isolated worktree
`/tmp/omni-benchmark-c4-human-gate`. A technically passing canary must remain a
precondition, never production authority. Change type: evaluation control-plane
authorization.

### Hypothesis

A strict receipt recorded verbatim by the existing Beads human-decision flow,
bound to the exact production identity and consumed exclusively before dispatcher
construction, will make missing, stale, substituted, and replayed approvals fail
before any Omni call.

### Intervention

Added a canonical C4 production receipt bound to run ID, C4 condition, schedule
hash, system commit, output root, execution-plan hash, and deployment-target hash.
The gate requires one closed `human` decision with close reason `Responded` and
exactly one matching response comment, aligns its close time with `approved_at`,
limits validity to 24 hours, and writes a mode-0600 `O_EXCL` consumption marker
inside the workspace before constructing the live dispatcher. C4 concurrency
canaries do not consume or mint production authority.

### Result

Authorization-focused tests passed 15/15; the wider focused suite passed 45/45.
The full suite passed 1,430 tests with five environment skips and 84.31% branch
coverage; Ruff, formatting, and diff checks passed. No live run, Omni call,
credential access, label access, commit, or push occurred.

### Outcome

KEEP, pending reviewed commit/integration after D-063.

### Next step

Integrate D-063 first, resolve the small shared CLI seam, rerun combined gates,
and require a newly answered exact decision receipt before any production C4 run.

## 2026-08-28 — D-065: Freeze the reconciled direct baseline by content hash

### Decision / experiment

Add the smallest deterministic freeze artifact for the authorized direct
baseline reconstructed from its preserved source attempts and infrastructure
continuation. Bead `omni-benchmark-dih.5.4.2.4.4.2.2.5`; change type: general
evaluation infrastructure. Work only in a new isolated worktree based on the
live control commit; do not modify either active-run worktree.

### Observation

The continuation manifest partitions all 630 authorized trials and exact
reconciliation validates each present attempt, but its terminal output records
only aggregate counts. The 518 continuation-side generation/run hashes are not
yet bound into one immutable selection manifest. Counts alone are insufficient
evidence for the pre-label public-baseline freeze.

### Hypothesis

A deterministic manifest containing only each trial identity, disposition,
selected run identity, and revalidated generation/run SHA-256 values can freeze
the reconstructed baseline without copying run artifacts, reading correctness,
changing scoring, or adding a new protocol layer.

### Planned intervention

Extend the existing result-independent continuation reconciliation with a
complete-only freeze builder and canonical exclusive writer. Tests must first
show that incomplete coverage, substituted content, duplicate trials, unsafe
paths, and overwrite attempts fail closed. The live dispatcher remains untouched.

### Result

Implemented test-first in isolated worktree
`/tmp/omni-benchmark-direct-baseline-freeze`, based on live control commit
`5748eba`. The builder refuses incomplete reconciliation, revalidates every
selected generation and run manifest, binds both SHA-256 values plus immutable
trial/run identities, requires exactly 112 preserved and 518 continuation
selections, and writes canonical mode-0600 state with the existing confined
`O_EXCL` writer. The CLI accepts only the established source, continuation,
manifest, system commit, and exact state path; it has no provider or credential
path.

Focused continuation coverage passed (17 tests), the wider affected slice
passed (51 tests), Ruff and format checks passed, and the full isolated suite
passed (1,424 tests, 5 skipped, 84.45% branch coverage). A live negative check
at 146/518 continuation captures exited nonzero with `baseline freeze requires
complete reconciliation` and created no state artifact. No run artifact,
answer, correctness, lease, or live worktree was modified.

The sole continuation later exited cleanly with 518/518 artifacts and the same
three pre-resume infrastructure diagnostics. Result-independent reconciliation
then passed at 630/630 (112 preserved, 518 continuation, zero missing). After
exit, the ignored continuation tree was copied into durable workspace storage;
the source and copy both contained 2,959 files / 22,308,271 bytes and matched
normalized inventory SHA-256
`633283e18867b48be8e476f7bbdfd048e4ce8e4f4a846ebb32f65cceeb3ae57f`.
The exclusive freeze artifact
`experiments/autoresearch/state/public-direct-baseline-freeze-v1.json` is mode
`0600`, contains 630 unique trial and attempt selections, and has SHA-256
`04c75eb40c6a8bbb59af07358733b59a10d9b28787443d622fae5f31887bd725`.
Its forbidden/correctness-field scan is empty.

### Outcome

KEEP. The public-only direct baseline is immutable before label release. The
freeze implementation remains uncommitted in its isolated worktree because the
main worktree contains concurrent changes; integrate it deliberately rather
than committing the dirty tree. Human train-only dev-A release may now be
requested through the existing custody tool. No baseline output may be
regenerated retrospectively.

## 2026-08-28 — D-066: Failure-mode census separates the direct-SQL conditions before any scoring

### Observation

Mid-run census of the direct comparator continuation
`public-baseline-v1-direct-16db-continuation-1` at 201 of 518 captures. Counts
are terminal capture classes, not correctness; no gold has been opened.

| condition | n | no failure class | executable-SQL errors | refusals | budget | turn limit |
| --- | --- | --- | --- | --- | --- | --- |
| C1 raw schema | 68 | 32 (47.1%, CI 35-59) | 14 | 17 | 4 | 1 |
| C2 searchable raw HKB | 68 | 44 (64.7%, CI 53-76) | 22 | 2 | 0 | 0 |
| C3 searchable exported Omni model | 67 | 26 (38.8%, CI 27-50) | 9 | 23 | 4 | 5 |

C2 against C3 on the no-failure-class rate is z=3.01, two-sided p=0.0026. C1
against C3 is z=0.97, p=0.33. Of the 44 attempts that produced no SQL at all
(refusals plus budget exhaustion), 24 issued zero database queries.

### Hypothesis

The conditions differ in *how* they fail, not only in how often. C3 declines to
emit SQL where C2 emits SQL that the database rejects. If this holds to
completion, the exported semantic model is behaving conservatively: it withholds
an answer rather than guessing a join or a grain it cannot substantiate. That is
the same representability limit already recorded for HKB-to-semantic-object
compilation, appearing at runtime instead of at build time.

### Result

Provisional and not yet actionable. Three constraints on reading it. The census
measures answer *production*, and a condition can produce executable SQL that is
wrong, so the ordering here may not survive scoring. C4, the governed Omni
condition and the one carrying the preregistered primary contrasts, is absent
from this run entirely. And the C2/C3 separation is an exploratory rung-level
contrast under the preregistration, not a primary perspective.

An earlier reading of this same data was wrong and is withdrawn: from
model-budget errors alone I concluded C2 "avoids the failure". C2 avoids budget
exhaustion and refusals while carrying the most executable-SQL errors of any
condition. Tracking one failure class produced a conclusion the full census
reverses. The monitor now reports the whole distribution.

### Outcome

CONTINUE. No intervention mid-run. At completion, test whether the C2/C3 gap
holds across full condition arms, whether per-question failure counts track
schema breadth, and re-examine the failure taxonomy: under Soft EX a refusal and
a wrong answer both score zero, so C3's conservatism is not rewarded by the
frozen scorers even where it is the better engineering behavior. Whether
`no_answer_insufficient_context` belongs on the model-budget bead
(`omni-benchmark-dih.5.4.2.4.4.2.2.2`) or its own is a classification question
flagged for the human surface, not decided here.

## D-067: The preregistered clustering test does not confirm; the condition separation does

Date: 2026-08-28. Run `public-baseline-v1-direct-16db-continuation-1`, complete
at 518 of 518 captures across C1/C2/C3, 14 databases, $870 total
($1.68/attempt). No C4 arm in this run.

### Preregistered test

`experiments/analysis/budget_clustering_test.py`, registered 2026-08-28 22:00Z
at 220 captures, before the remaining attempts were observed. Statistic, null,
sample boundary, and threshold were fixed in that file and hashed
(`dac0aa86154453e02f6b528566ae0d010aaf18c1ac103e71d47cdfbd3e966994`).

```
holdout captures       298
questions in all 3      98
budget errors            4
questions failing >=2    1
permutation p       0.0407
verdict   NOT CONFIRMED at alpha=0.01
```

The post-hoc pattern that motivated it (budget exhaustion clustering by question
rather than by scaffold; P=0.0073 and P=0.0053 in the first 216 captures) does
not replicate on the confirmatory sample at the registered threshold. The
holdout carried 4 budget errors against 7 in the registered prefix, so the test
had less power than the registration assumed. That is a property of the test as
registered; the threshold was fixed in advance and is not moved now, and no
other statistic is substituted. The practical consequence is that there is no
confirmed evidence for locating the P0 fix at the question level, so the
scaffold-level fix on `omni-benchmark-dih.5.4.2.4.4.2.2.2` is not blocked.

### Failure census at full n

```
ok                               366   c1:112 c2:143 c3:111
no_answer_insufficient_context    80   c1:37  c2:3   c3:40
database_statement_error          48   c1:15  c2:23  c3:10
model_budget_error                17   c1:7   c2:3   c3:7
turn_limit_exhausted               7   c1:1          c3:6
```

Capture-level completion rate, meaning an answer was produced at all, not a
scored one:

| | C1 | C2 | C3 |
| --- | --- | --- | --- |
| all 518 | 65.1% | 83.1% | 63.8% |
| excluding the two broken databases (437) | 75.9% | 97.9% | 74.8% |

C1 vs C2 z=-3.82, C2 vs C3 z=4.07, C1 vs C3 p=0.80. Excluding the two databases
the separation widens (z=-5.57 and z=5.74) and C1 vs C3 stays indistinguishable
(p=0.84). D-066 therefore holds at full n and strengthens: the searchable raw
HKB separates from both the raw schema and the exported semantic model, while
raw schema and exported model do not separate from each other.

`database_statement_error` is 48 of 48 confined to `mental_healths_large` (24)
and `organ_transplant_large` (24), which complete 4/42 and 0/39. Those two
databases shift every absolute rate by roughly ten points and are the subject of
`omni-benchmark-2j9`. Whether their 81 attempts are `evaluated_system` failures
or infrastructure failures under the rerun policy is a human-controlled
classification, still not decided here.

63 of 518 attempts (12.2%) never issued a query at all: c1:32, c3:28, c2:3,
composed of 51 refusals and 12 budget exhaustions. The refusal is the dominant
never-queried mode, not budget exhaustion.

### Outcome

These are capture outcomes, not accuracy. Nothing here is scored; under Soft EX
a refusal and a wrong answer both score zero, so the C2 advantage in completion
does not transfer to accuracy without scoring. Next step is scoring this run
under both frozen scorers, with the two broken databases reported separately
rather than silently dropped.

## 2026-08-28 — D-068: Request the train-only release after baseline freeze

### Decision / experiment

Open human decision `omni-benchmark-ei0.1` only after the public-only baseline
freeze is complete. Change type: human-controlled custody action. The agent may
prepare the exact command and verify the repository-side destination is absent,
but may not locate, download, open, or name the external attachment path.

### Observation

The prerequisite now holds: the direct baseline has 630/630 reconciled trials
and immutable freeze SHA-256
`04c75eb40c6a8bbb59af07358733b59a10d9b28787443d622fae5f31887bd725`.
`data/private/dev-a/labels.jsonl` is absent. Freeze A records full commit
`7d39ee107338da1ce10e2553a4290e64bfc2f892`, and the existing extractor is
restricted to the canonical 154 dev-A IDs, an external source, and an exclusive
mode-0600 destination under `data/private/`.

### Hypothesis

A human running the existing release tool in a trusted external shell can
provide the minimum train-only supervision needed for the MVP without exposing
the full attachment, dev-B, test records, source path, or hidden content to an
agent transcript.

### Result

Decision `omni-benchmark-ei0.1` is open with the exact repository-side arguments
and safe response contract: report only success plus count/hash summary. No
source path was discovered or requested, and no private record was accessed.

### Outcome

AWAIT HUMAN. Do not start scored dev-A analysis until the custodian reports a
successful 154-record release. While waiting, only public/result-independent
work may continue.

## 2026-08-28 — D-069: Exact live parity refutes the two-database restore hypothesis

### Decision / experiment

Diagnose `omni-benchmark-2j9` without regenerating an attempt, reading an answer,
or changing a failure classification. Change type: public evaluation
infrastructure diagnosis. Recompute the established database fingerprint under
the read-only runtime environment and compare only committed hashes/counts;
separately audit the recorded runtime database bindings and fresh privilege
attestation.

### Observation

All 48 `database_statement_error` captures were concentrated in
`mental_healths_large` and `organ_transplant_large`, which suggested but did not
prove a failed restore. The protocol permits a rerun only after a demonstrable
failure outside the evaluated system, so distributional shape alone is not
sufficient evidence.

### Hypothesis

If either restore or connection target is defective, its live schema/content
fingerprint or recorded runtime identity will differ from the committed parity
evidence. Exact agreement would refute the infrastructure hypothesis and leave
the immutable attempts as recorded.

### Result

Both live databases match the committed PostgreSQL version, table count, row
count, schema SHA-256, and full content SHA-256 exactly:

- `mental_healths_large`: PostgreSQL `180006`, 21 tables, 33,582 rows, schema
  `d0758ce810a8bcc949121f55542e82e5a9fe2816bdd064a475f7d47643505a01`,
  content
  `4887ac64a13b2f164d50e55f64bf1e732e04adf9319e646680c98b836a0d3d89`;
- `organ_transplant_large`: PostgreSQL `180006`, 20 tables, 8,970 rows, schema
  `061cffb1893b6c4e770e93a27b86f96c3221037fded630af0cff5bde914f7111`,
  content
  `39d5fb50801f758c6aa085995d4110ed3bc85b03f709aec62fd33e03612fd176`.

All 42 mental-health and 39 organ-transplant capture receipts exactly match the
committed runtime database identity, with zero binding mismatches. Fresh
attestation confirms the execution role remains read-only and cannot execute
non-system functions. The first local diagnostic invocation failed safely
before remote access because its wrapper omitted the external environment; it
created no benchmark attempt or artifact. The corrected read-only diagnostic
produced the evidence above and persisted no row bodies or credentials.

### Outcome

REJECT the broken-restore hypothesis. No external infrastructure failure is
demonstrated, so the rerun policy does not authorize replacement attempts. Keep
the existing `evaluated_system` records unchanged; do not report the two
databases as broken or exclude them from primary results. Bead
`omni-benchmark-2j9` is closed with this evidence. This updates the interpretation
of D-066 without changing any scorer, classification field, or frozen output.

## D-134: The system/infrastructure boundary is mechanical, and the artifacts can be made to answer it

Date: 2026-08-28. Prompted by a question I had twice deferred to the human
surface: are the 81 attempts on `organ_transplant_large` and
`mental_healths_large` evaluated-system failures or infrastructure failures?
Deferring was wrong. The classification is defined in code and the evidence is in
the artifacts.

### The definition

`direct_capture_telemetry.failure_origin` is total and closed:

```python
if failure in {"database_identity_mismatch", "database_infrastructure_error"}:
    return "benchmark_infrastructure"
return "evaluated_system"
```

`database_infrastructure_error` is emitted when
`postgres_execution._execution_error` sees a SQLSTATE beginning `08` (connection
exception) or a `ConnectionError` / `OSError` / `TimeoutError`. SQLSTATE `57014`
becomes `database_timeout_error`. Every other SQLSTATE becomes
`database_statement_error`. The operative test is therefore: *did Postgres accept
the connection and answer?* If it answered and rejected the statement, the
outcome belongs to the evaluated system.

By that definition the 81 attempts are correctly labelled `evaluated_system`.
There is no misclassification bug. But the definition tests reachability, while
the protocol's rerun clause speaks of "benchmark database unavailability", and
those are not the same predicate. A database that connects and holds a catalog
but exposes no data tables is reachable and unavailable at once.

### The observation

`attempt.action-evidence.json` retains `exploratory_sql` keyed by `trace_seq`;
`attempt.trace.jsonl` retains per-`seq` `status` and `database_query_delta`.
Joining them classifies every executed query by outcome and by whether it touches
catalog relations or data tables. Successful data-table executions per database:

```
residential_data 73   virtual_idol 60   planets_data 51   labor_cert 44
reverse_logistics 39  solar_panel 36    sports_events 34  fake_account 32
robot_fault 21        museum_artifact 14 polar_equipment 6 cross_border 2
mental_healths 0      organ_transplant 0
```

Twelve databases return rows from real tables. The two suspects return none, ever
, across 39 and 42 attempts and all three conditions, while succeeding 45 and 23
times against `information_schema` / `pg_class` / `pg_namespace` /
`pg_attribute`. Every user table is zero-for-N: `transplant_matching` 0/46,
`clinical` 0/27, `assessmentbasics` 0/47, `encounters` 0/42. The models kept
proposing table names taken from the documented schema file, the behaviour
expected when an `information_schema` probe returns zero rows.

The environments connect and have nothing queryable behind them. This is an
absent or partial restore, or tables outside the connection's `search_path`. It
is not a capability difference between conditions, which would vary by condition
rather than being uniformly total.

I withdraw the weaker form of my earlier briefing claim in both directions: I
first asserted "broken environment" from a uniform failure rate, which was
under-evidenced, and then said the databases could not be at fault because 45
queries succeeded on `organ_transplant_large`. Both readings were wrong. The
successes are real and they are all catalog introspection.

### The gap that made this look like a judgement call

`direct_sql_capture.py:472` keeps only `error.kind` and discards the SQLSTATE
that produced it. So `42P01 undefined_table` (the table is not there) and a
genuine model SQL defect are the same value in every artifact, and
`failure_origin` is computed from that value alone. The reconstruction above
works, but a contract that forced a join across two files and a regex over SQL
text to recover a code the system already computed is not doing its job. Filed as
`omni-benchmark-bfb`, to be fixed before Freeze B commits the
failure-classification policy.

### The decisive comparison

The catalog-only result still left a model-defect explanation open: perhaps the
system invented table names. It did not. Comparing the names in executed queries
against the benchmark's own published schema
(`data/raw/livesqlbench-large-v1/schema/<db>/<db>_schema.txt`, the file that
feeds C1's provided context):

| | documented tables | refs in failed queries | refs in OK queries |
| --- | --- | --- | --- |
| `organ_transplant_large` | 37 | 168 across 11 tables | 0 |
| `mental_healths_large` | 34 | 230 across 9 tables | 0 |
| `planets_data_large` (control) | 29 | 0 | 122 across 7 tables |

On the two suspects every documented table the system touched was rejected, and
no documented table ever succeeded. On the control the relationship inverts
exactly: documented names appear only in successful queries. The system used the
names the benchmark publishes and the database rejected all of them while
answering catalog queries normally. The environment does not match its own
published schema, and no database access was required to establish it.

### Outcome

The classification question is not a matter of human judgement and should not
have been posed as one. What remains for the human surface is narrow and real:
`failure_origin`'s predicate is a frozen scoring surface, so widening it from
"the server answered" to "the server answered from a populated schema" is a
proposal, not a change I make. Recommendation is to fix the telemetry
(`omni-benchmark-bfb`), confirm the restore against the live databases
(`omni-benchmark-2j9`, one `information_schema.tables` query, credentials are
outside both worktrees), and until then report the 437-capture figures as primary
with the two databases stated separately rather than silently dropped.

## 2026-08-28 — D-070: Probe only the values-free dev-A shape before adapting the release

### Hypothesis

The first authorized train-only release failed before publication because the
delivered `external_knowledge` JSON shape differs from the integration
contract. Guessing a conversion from the validator message would risk a lossy
or over-broad adapter. A human-run probe can determine only the aggregate outer
type signature required for a minimal adapter without exposing hidden values or
foreign-partition structure to an agent.

### Intervention and boundary

Added `sealed_tools/probe_private_structure.py` and a custody-library probe. The
CLI verifies the full canonical Freeze-A commit, provisioned guardian pin, and
committed dev-A manifest before resolving the external source. It parses record
membership, inspects `external_knowledge` only for committed dev-A IDs, and
reports only source/inspected/ignored counts, aggregate JSON type signatures,
and the full-source SHA-256. It writes no artifact. It never emits source paths,
instance IDs, object keys, SQL, knowledge values, record bodies, or dev-B/test
field shapes. The existing array-of-strings release contract is unchanged.

This is benchmark-integration and custody infrastructure, not a system change.
No question-specific runtime input is introduced.

### Evidence

Tests preceded implementation. Focused custody tests pass 52/52, including
foreign-shape non-inspection, every JSON outer type, mixed/empty arrays, exact
dev-A membership, external-source enforcement, Freeze-A-before-source ordering,
safe output, and traceback/path/value suppression. The full repository suite is
1,456 passed with 3 explicit live-integration skips and 84.51% branch coverage.
Repository-wide Ruff check and format-check pass, as does `git diff --check`.

The human reported successful cleanup of the transferred source and directory
(`file=0`, `directory=0`); the train-only destination remains absent. No agent
accessed the source or hidden values.

### Outcome

Pause agents for a second human-only transfer and run only the structure probe.
After cleanup, the human may report the one-line aggregate JSON and probe status.
Implement the smallest lossless adapter only from that safe signature, retest,
and then issue a fresh release command. Do not rerun the release yet.

## 2026-08-28 — D-071: Bind a lossless integer-ID adapter to the probed source

### Observation

The human-run probe completed successfully and the remote source was removed
before agents resumed. Its permitted aggregate output covered all 480 records
and exactly 154 committed dev-A records. Of those dev-A records, 152 have
homogeneous integer `external_knowledge` arrays and 2 have empty arrays. The
reported full-source SHA-256 is
`be6433ea0687c37e2b6a901acbe000667d073da8dec2f08e79686995d2f8d5b1`.
No hidden value, record ID, object key, SQL, test case, path, dev-B shape, or test
shape entered agent scope.

### Hypothesis and intervention

JSON integer-to-decimal-string conversion is lossless for this ID field and is
the smallest adapter that restores the preregistered downstream string contract.
The release validator now preserves homogeneous string arrays unchanged,
converts homogeneous JSON integer arrays with exact `str(integer)` semantics,
and rejects mixed arrays, booleans, floats, nulls, and objects. Empty arrays stay
empty. No other private field is transformed.

The human release CLI now requires the probed source SHA-256 and compares it to
the bytes actually read before atomic publication. This prevents a different
attachment from silently entering the newly broadened structural path. Invalid
hash syntax fails before source resolution, and a valid-but-mismatched hash fails
before destination publication. Controlled release failures now emit one
sanitized line rather than a traceback.

This remains a post-Freeze-A format adapter explicitly permitted by the protocol.
It changes custody integration only, not split membership, scoring, runtime
inputs, or system behavior.

### Evidence and outcome

Tests preceded the adapter. The final focused custody suite passes 66/66,
covering exact large/negative/zero integer conversion, original string-array
compatibility, malformed and mixed fail-closed behavior, source-hash binding,
hash validation before source access, atomic mode-0600 publication, foreign
record exclusion, Freeze-A binding, and sanitized failures. The full repository
suite passes 1,469 tests with 3 explicit live-integration skips and 84.53% branch
coverage. Repository-wide Ruff check, format-check, and `git diff --check` pass.

The train-only destination is still absent. The next action is one human-only
transfer and the exact hash-bound release command in `docs/human-decisions.md`.
Expected safe counts are source 480, released 154, ignored 326. Agents remain
paused while the full source is present; C4 remains stopped and quarantined.

## D-135: What the bounded retrieval actually cost, measured at full n

Date: 2026-08-28. Prompted by an external stakeholder repeating the token
reduction from a progress email. The figure needed a denominator.

### The original measurement

At commit `349e0bb` the archeology canary called `inspect_schema`, received all
51 tables, and the following turn consumed 169,995 input tokens and terminated in
`model_budget_error` before any SQL. After the bounded retrieval landed at
`2b72244`, the exact-commit replay of the same task came in at 1,585 tokens and
$0.017715. Both figures are correct as recorded.

They do not form a like-for-like ratio. The replay terminated at
`forbidden_tool_payload` before issuing a database query, which the entry that
recorded it states directly: "end-to-end success remains unproven." The
comparison is 170K-before-failing against 1.6K-before-failing. Neither run
answered its question.

### Ground truth from the completed run

518 captures, all reporting token usage.

| | C1 | C2 | C3 |
| --- | --- | --- | --- |
| median input tokens | 127,310 | 198,968 | 152,976 |
| mean input tokens | 195,082 | 238,095 | 276,190 |
| p90 input tokens | 464,542 | 467,018 | 683,080 |
| mean cost | $1.48 | $1.71 | $1.84 |

Median 5 model turns per attempt, maximum 12. Successful attempts alone: median
135,910 input tokens, p90 448,661. Budget-exhausted attempts: median 619,092.

Cumulative attempt totals are not comparable to the canary's single turn, since
each turn resends context. The comparable quantity is the largest single turn per
attempt: median 61,892, p90 131,891, p99 184,543, max 193,879. Twelve attempts of
518 (2.3%) still reach a single turn as large as the canary's, but from
accumulated conversation rather than a schema dump.

### What the intervention did and did not do

It did not reduce a working attempt to 1,585 tokens; the shipped system runs
about $1.68 per attempt. What it did is structural and stronger than a statistic:
`inspect_schema` returns at most four tables and 64 KiB by construction, against
a previous whole-schema response of 51 tables. That bound is enforced in code and
bound into action evidence, so it holds regardless of question or database.
`model_budget_error` is now 17 of 518 (3.3%), against deterministic failure on
the canary.

### Outcome

The bounded-payload claim and the system-cost claim are separate and must be
reported separately, since the first is roughly two orders of magnitude and the
second is not. Tracked as `omni-benchmark-wes` so the write-up states the bound
with its actual limit and gives per-attempt cost alongside it.

## 2026-08-28 — D-072: Accept the exact dev-A release and preserve the remaining seal

The human ran the hash-bound release against the same source that produced the
values-free probe. The command exited 0 and reported source 480, released 154,
ignored 326, source SHA-256
`be6433ea0687c37e2b6a901acbe000667d073da8dec2f08e79686995d2f8d5b1`, and
output SHA-256
`34794127f6f34f5214eedf652b86d870fb2c4e8f67d364bbd8d333897acf2c3d`.
The human then removed the remote full source and dedicated directory; both
cleanup statuses were 0.

Agent-side verification used only the authorized extracted destination. It is a
regular file owned by the benchmark user, mode 0600, 168,496 bytes, and exactly
154 lines. Its SHA-256 equals the human-reported output hash. The custody loader
validated all records and proved exact set equality with the committed dev-A
manifest; therefore no dev-B or test record entered the release.

Human decision `omni-benchmark-ei0.1` is responded/closed, and format-adapter
task `omni-benchmark-ei0.2` is complete. The released file is now authorized
offline dev-A supervision. The complete attachment remains outside agent scope;
dev-B remains guardian-only and test remains sealed. Next, score the already
frozen public baseline without regenerating any attempt, then select only a
small MVP-focused dev-A experiment set.

## 2026-08-28 — D-073: Score the exact frozen-baseline/dev-A intersection

### Hypothesis and boundary

The immutable 630-attempt public-only baseline selection contains 420 attempts
covering 140 of the 154 committed dev-A questions, with one C1, C2, and C3
attempt for every represented question. Scoring that exact intersection will
establish the supervised baseline without regenerating an answer or filling the
14-question coverage gap after labels are visible. The gap will be reported as
coverage, not silently imputed.

The scoring input is bound to selection SHA-256
`04c75eb40c6a8bbb59af07358733b59a10d9b28787443d622fae5f31887bd725`
and dev-A release SHA-256
`34794127f6f34f5214eedf652b86d870fb2c4e8f67d364bbd8d333897acf2c3d`.
Only selection entries whose IDs are in the exact committed dev-A manifest are
opened. Every selected generation and run-manifest hash is verified before the
private release is parsed, and all 420 scorer cases are validated before the
first database clone is acquired. Foreign dev-B generation artifacts and all
test artifacts remain unopened.

Both frozen scorers will execute against independent disposable clones of the
existing public PostgreSQL 18.6 databases. No score artifact will be published
unless the complete paired run finishes without benchmark-infrastructure
failure. Outputs contain only attempt/hash bindings, three-state correctness,
the closed failure category when applicable, scorer identity/version, and
aggregate coverage. They contain no SQL, rows, test cases, external knowledge,
or hidden annotations. A wrong answer is a measurement and never authorizes a
rerun; any infrastructure failure will stop publication and be handled only
under the protocol's rerun rule.

### Pre-run evidence

Tests preceded implementation. Seven focused tests cover exact dev-A
intersection before artifact access, release-hash validation before private
parsing, complete-case validation before database acquisition, pinned scorer
identity, SQL-free hash-bound exclusive publication, infrastructure-failure
publication refusal, and environment-only connection strings. A public-only
isolation probe created, attested, reset, and dropped one disposable clone and
left zero score clones behind. Real preparation validated 420 attempts, 140
represented questions, and 14 unrepresented questions without emitting labels
or SQL. Full quality-gate and scored-run outcomes follow below.

### Infrastructure abort and authorized restart

The first scored invocation stopped closed before publication. The output root
remained absent and all disposable clones were removed. A gold-only conformance
check failed on the first public database under both scorers; the sanitized
driver diagnostic was SQLSTATE `42501` (insufficient privilege), not a gold-SQL
or model-answer defect. An aggregate public ACL audit then found that the local
scorer role could read all 51 archeology tables but zero tables in each of the
other 17 restored databases. The container had retained only its original
single-database canary provisioning.

Applied the repository's existing hardened read-only database policy to the
same dedicated scorer role across all 18 local public databases. This changed
only database/schema/table/sequence/function ACLs and default privileges; it did
not change rows or schema objects. Post-repair aggregate verification found
exact SELECT coverage in every database (938/938 public relations overall), and
the role retained its no-superuser/no-create/no-membership/default-read-only
attestation. The exact previously failing gold-self-check then passed under both
scorers, and clone cleanup again returned to zero.

This is a demonstrable benchmark-infrastructure failure outside the evaluated
system. No wrong-answer result was inspected, no score artifact existed, and no
model answer was regenerated. The protocol therefore permits one clean restart
against the corrected scorer ACL state.

### Deterministic gold limit and human-authorized coverage rule

The corrected restart also stopped closed before candidate correctness results
or score artifacts were published. A complete aggregate gold-phase audit of the
140 represented questions found 18 questions unscorable under both frozen
scorers: all nine represented questions in each of `mental_healths_large` and
`organ_transplant_large` fail with `gold_statement_error` / PostgreSQL `42P01`.
Sensitivity additionally has one `polar_equipment_large`
`gold_result_overflow`. This leaves 122 questions / 366 attempts scoreable for
official Soft EX and 121 / 363 for sensitivity.

Human decision `omni-benchmark-ei0.3.1` selected option A. The scorer now freezes
gold conformance across every represented question and both modes before any
candidate correctness execution. Only `gold_query_missing`, `gold_timeout`,
`gold_statement_error`, `gold_no_result`, and `gold_result_overflow` produce an
unscorable disposition; all database, preprocess, cleanup, candidate, and
scorer-policy failures continue to abort publication. Candidate SQL is not
executed for an unscorable mode/question pair. Both score artifacts retain all
420 attempt/hash bindings, distinguish `scored` from `unscorable`, and receipts
report scheduled/scoreable/unscorable attempts and question counts separately.
The command-line boundary refuses publication unless the frozen denominators
are exactly 122 official and 121 sensitivity. The identical evaluator-only rule
will apply later to sealed test without exposing identities or outcomes.

Tests were extended before implementation to require a full conformance sweep
before candidate calls, mode-specific skipping, exact denominator enforcement,
SQL-free immutable publication, and infrastructure-failure refusal. The focused
custody suite is 8/8 and Ruff passes. Full repository gates and the authorized
production scoring outcome follow below.

### Scorer-policy abort and closed-boundary repair

The first option-A production invocation completed gold conformance and then
failed closed during official candidate-result normalization with Python
`decimal.InvalidOperation`. The frozen official comparator can raise this for a
numeric value outside the active decimal context; the sealed lifecycle caught
`ScoringPolicyError` but not the standard-library decimal signal. This was a
benchmark scorer-boundary defect, not an evaluated-system correctness outcome.
The output root remained absent and clone cleanup returned to zero. No
per-question correctness was emitted or inspected.

The existing closed taxonomy already defines `scorer_policy_error` as a
benchmark-infrastructure result. A regression test now supplies an oversized
decimal through the synthetic sealed lifecycle and requires that exact class.
The lifecycle catches `decimal.InvalidOperation` at comparison only and maps it
to `scorer_policy_error`; it does not alter numeric normalization or correctness
semantics. The command entrypoint now also suppresses tracebacks and details for
any unexpected internal exception. Focused regressions are 2/2. The failed
batch's absent artifact and demonstrably external defect satisfy the rerun
policy only after an authorized repair actually removes the deterministic
failure and the full quality gates pass.

Further review before restart found that classification alone would reproduce
the same deterministic abort. The written frozen policy requires half-up
rounding for finite decimal values and states no 28-digit limit; the limit comes
only from Python's ambient decimal context. An operand-sized local context makes
the documented operation total for finite PostgreSQL numerics, and a proposed
general regression passed for both scorers. However, this changes executable
scorer behavior after dev-A release. The proposal was reverted from the working
implementation and human decision `omni-benchmark-ei0.3.2` now blocks restart:
authorize that contract-conformance repair while retaining scorer identities,
or retain exact implementation behavior and accept that dev-A scoring remains
blocked. No question identity, private value, or correctness was inspected.

The human selected option A. The finite-value regression was restored first and
reproduced `decimal.InvalidOperation` under the ambient context. The authorized
implementation sizes a temporary local decimal context from the operand's
coefficient and adjusted integer width, then performs the same half-up
quantization. Non-finite values remain on the existing path, and any decimal
signal that still escapes normalization is classified as `scorer_policy_error`.
Both frozen scorer identities are retained because the written semantic policy
is unchanged. The focused scorer/custody suite is 55/55; Ruff and formatting
pass. Full gates must pass before the authorized clean restart.

### Frozen baseline result

Full gates passed before restart: 1,480 tests passed, three explicit
integration-only tests skipped, branch coverage was 84.20%, and Ruff,
formatting, and diff checks passed. The single authorized clean restart exited
0 and atomically published the three mode-0600 artifacts under
`experiments/autoresearch/raw/public-direct-baseline-dev-a-scores-v1/`.

Official Soft EX retained all 420 scheduled attempts: 366 were scoreable across
122 questions and 54 were unscorable across 18 questions. Correct counts by
condition were C1 9/122 (7.4%), C2 29/122 (23.8%), and C3 16/122 (13.1%); overall
54/366 (14.8%). The remaining scoreable outcomes were 245 wrong answers and 67
refused/errors. Sensitivity retained the same 420 attempts: 363 scoreable across
121 questions and 57 unscorable across 19 questions. Correct counts were C1
9/121 (7.4%), C2 28/121 (23.1%), and C3 14/121 (11.6%); overall 51/363 (14.0%).
The remaining scoreable outcomes were 249 wrong answers and 63 refused/errors.

The official, sensitivity, and receipt SHA-256 values are respectively
`8eb81f50c2c6fcd4c7a3d6aacb82f2b2bb30f76b58622bf3e970962723021b04`,
`69ff59d002c60d9b6c9c6d9a330381a1f21975ba3b3622b29567c426f2f267df`, and
`b8faf76c60fc62d9df2b3f8d63e450e0e3aaddaf76a68dd60d030a40bf13fa3c`.
Independent verification confirmed exact receipt hash bindings, 420 unique
attempt records per scorer, exact authorized denominators and arithmetic,
mode-0600 regular files in a mode-0700 directory, no forbidden SQL/annotation/
row fields, and zero leftover score clones.

The baseline establishes a large C2 advantage over both C1 and C3 on the exact
frozen intersection, while the sensitivity scorer gives the same ordering and
similar magnitudes. This is the starting point for the deliberately small
dev-A experiment set; it does not authorize dev-B or sealed-test access.

## 2026-08-28 — D-074: Revalidate the two C4 prerequisites without reopening C4

**Hypothesis.** The two already-authorized C4 prerequisite implementations can
be made freeze-ready entirely in isolated worktrees, without contacting Omni or
reopening the quarantined C4 lane. The deployment lane should bind immutable
verified semantic content and the original cost reservation; the independent
human gate should fail before dispatcher construction unless a current,
single-use approval exactly matches the frozen run. This is a general
control-plane/provenance intervention, not a benchmark-question-specific one.

Both isolated implementations are full-suite green. The semantic-content and
cost-reservation lane passes 1,429 tests with five explicit integration skips.
The approval lane passes 1,430 tests with the same five skips. Focused approval
and C4-arm coverage passes 15/15, and both lanes pass Ruff, formatting, and diff
checks. No C4 job, Omni request, credential/lease operation, private-label
access, commit, push, or dirty-main mutation occurred.

A security regression exposed one fail-closed gap before integration: when the
approval directory's parent was a symlink, the first implementation rejected
the path only after `mkdir(parents=True)` had created a directory outside the
workspace. The RED test requires that no external directory be created. The
repair now walks and creates path components relative to directory descriptors
using `O_DIRECTORY|O_NOFOLLOW`, validates ownership and type, and creates the
single-use marker with `O_EXCL|O_NOFOLLOW` and mode 0600. The regression and
full suite pass.

The prerequisites are not yet frozen. They overlap at the baseline CLI seam,
and the approval lane was developed against the earlier lineage. Correct merge
order is semantic/cost first, then approval; the combined approval deployment
identity must additionally bind `semantic_model_sha256`. Under the repository's
conservative git policy, human decision `omni-benchmark-ei0.4.1` now asks only
for authority to create two scoped local commits and combine them in a fresh
clean integration worktree. It does not authorize a push or any C4 dispatch.

The human selected option A. The semantic-content/cost implementation became
local commit `d6337c1`; the approval implementation was then integrated as
`da84b4a` on the fresh clean branch `codex/c4-prerequisites-integrated`. The
shared CLI resolution constructs the persisted budget policy and requires the
approval before dispatcher construction. Its canonical deployment identity
now hashes each target's branch ID, model ID, and `semantic_model_sha256`. A new
focused regression first failed because the integrated digest helper did not
exist, then passed after that exact binding was implemented. The four combined
C4/control-plane suites pass 49/49. The full repository passes 1,438 tests with
five explicit integration skips and 84.33% branch coverage; Ruff, formatting,
and diff checks pass. Both prerequisite beads are closed. Nothing was pushed,
main's dirty code state was not used or overwritten, and C4 remains stopped
pending a separate fresh production authorization.

## 2026-08-28 — D-075: Prepare an exact C4 authority without dispatching C4

**Hypothesis.** A new public C4 run can be made human-authorizable without
reopening the quarantined lane during preparation by binding authority to a
fresh run/output identity and deriving every permitted hash from the clean
integrated prerequisite commit. Preparation must make no Omni request, create
no dispatcher, consume no receipt, and leave the output root absent. This is a
general control-plane intervention; it does not use benchmark labels or change
the evaluated system.

The fresh identity is `public-c4-baseline-v2` at system commit
`da84b4ae2305cba0f6b31a87f1545b2fdff8d29c`, with output root
`experiments/autoresearch/raw/public-c4-baseline-v2`. A public-only dry run
resolved 129 frozen attempts and ten verified deployment targets, reported
`live_execution=not_started`, and produced schedule SHA-256
`3dc74f45730079a5da635388a955b5a3c87059decc9cd57989a90c715bc0c12d` and
execution-plan SHA-256
`c7df1706cedc53256754b15942b357855c2e9163978641b2d0c45dac6c4bd59b`.
The canonical target map, including each semantic-content digest, hashes to
`d805eb6869201f28f928a5774263062302b29a5d8786fc3c1c120cb27f19df80`.

Human decision `omni-benchmark-ei0.4.2.1` now carries that exact binding and the
planned launch policy: concurrency three, 21,600-second wall bound with started
blocks completed, USD 7 per-attempt reservation, USD 560 telemetry ceiling,
and observed C4 cost basis USD 0.7275655. Because the receipt's `approved_at`
must be within one minute of the durable Beads response, a fixed JSON blob would
be operationally unsafe. A mode-0600 operator helper instead checks the clean
commit, absent output and receipt, and open exact decision; only an explicit
`--authorize` creates the one-hour canonical receipt, records the exact response,
and validates it without consumption or launch. Its SHA-256 and one-line command
are in `docs/human-decisions.md`.

The helper's no-authority check reports
`ready_not_authorized_not_launched`. Four focused receipt/gate tests pass. Final
checks confirm the receipt, output root, and consumption marker remain absent.
No C4/Omni/network, credential/lease, gold/dev-B/test-label, push, or dirty-main
code action occurred.

## 2026-08-28 — D-076: Run the one authorized public C4 v2 identity once

**Pre-launch hypothesis.** The quarantined v1 failure was public API observer
pressure at sustained concurrency five, not an evaluated-system answer defect.
Running the exact frozen 129-attempt arm at concurrency three should reduce that
pressure while leaving prompts, tools, deployment content, model behavior, and
answer eligibility unchanged. The run must stop rather than substitute an
identity or retry an evaluated answer if its existing Omni profile fails. This
is a general infrastructure pacing choice and not a benchmark-specific semantic
intervention.

Human decision `omni-benchmark-ei0.4.2.1` authenticated the canonical one-hour
receipt with SHA-256
`d9869dfc57a4c8fc1ef536644228fd6f858b841d18af5ccd3262bfbdd42e0ed2`.
Independent pre-launch validation matched the exact commit, run ID, output,
schedule, execution-plan, and semantic-content deployment hashes recorded in
D-075. The integrated worktree is clean; the v2 output root and single-use
consumption marker are absent; no competing C4 process exists. The existing
`benchmark-infra` Omni profile and its recorded HTTPS origin will be passed to
the child environment without login, refresh, validation canary, copying, or
other credential mutation. The authorized launch policy is concurrency three,
21,600-second wall bound with started database-condition blocks completed, USD
7 reservation per attempt, and USD 560 telemetry ceiling. No dev-B, test, gold,
or sealed correctness input is in scope.

### Closed infrastructure failure

The gate consumed the exact receipt, then the three initially staged children
all exited within seconds with the same stderr SHA-256 and sanitized Omni HTTP
403. The batch stopped on the first surfaced child failure. It produced three
mode-0600 child-failure diagnostics, zero generation artifacts, and zero
correctness results; no C4 process remains. This does not test the concurrency
hypothesis because authentication failed before governed execution. The spent
receipt and v2 output root are immutable and cannot authorize or host a retry.

While creating the follow-up human-login decision, an orchestration quoting bug
placed Markdown backticks inside a double-quoted shell command. The shell
interpreted the embedded text and started two unintended interactive `omni
config login` processes. Both were identified and terminated before any browser
flow completed; no agent supplied credentials or observed a success response.
This was itself a violation of the agent-side no-login boundary and is recorded
as a near-miss, not hidden as part of the original 403. `AGENTS.md` and
`CLAUDE.md` now prohibit interpolating backticks or `$()` into shell commands and
require file/stdin or literal-safe argument transport for Beads fields.

Human decision `omni-benchmark-ei0.4.2.2` now requests one canonical,
human-owned interactive login for the existing `benchmark-infra` profile after
all agent work stops. It explicitly forbids an agent validation call and does
not authorize a replacement run. After successful human recovery, v2 must be
quarantined and a separately bound v3 package prepared.

## 2026-08-28 — D-077: Quarantine the spent v2 identity before preparing v3

**Pre-change hypothesis.** A consumed authorization plus pre-answer child
failures must be excluded by the same mechanical registry as an interrupted
generation run; relying on the absence of generation files would allow a later
forged or misbound artifact to reuse the v2 identity. The smallest general fix
is to bind all three immutable child-failure diagnostics and the approval
consumption marker in a quarantine manifest, add the exact run ID to the closed
registry, and reuse the existing baseline/autoresearch/scorer rejection paths.
This is infrastructure provenance, not a semantic intervention.

Human decision `omni-benchmark-ei0.4.2.2` records that the canonical
`benchmark-infra` login completed successfully without an agent validation
request. The login does not authorize a run. Work proceeds only on v2
quarantine evidence in the isolated integration worktree; no Omni request,
credential operation, protected-label access, or v3 launch is permitted.

The RED quarantine test first failed because no v2 manifest existed. The
implementation adds `public-c4-baseline-v2` to the closed quarantine registry
and a schema-v1 manifest that binds all three child-failure paths and SHA-256
values, their common stderr hash and pre-answer `child_exit` class, the consumed
decision/receipt marker and its SHA-256, zero generation records, and explicit
false correctness/gold access. The existing baseline, autoresearch, and scorer
rejection paths now cover the v2 identity and forged v2 attempt IDs.

An existing approval-gate test had used the now-real v2 identifier as synthetic
input; the first full suite correctly failed earlier at the new quarantine
check. Its synthetic identity was renamed to a non-production test value rather
than weakening quarantine ordering. Focused quarantine/downstream checks pass
6/6, focused C4/quarantine checks pass 11/11, and the corrected full suite
passes 1,439 tests with five explicit integration skips and 84.33% branch
coverage. Ruff, formatting, and diff checks pass. Human decision
`omni-benchmark-aez.4.1` selected the scoped local-commit option. Commit
`f1efd00ae49824b6eb13e6655157f83a022004f3` contains exactly the quarantine
manifest, registry entry, and two related test files. The spent approval marker
and raw v2 diagnostics remain untracked; nothing was pushed.

## 2026-08-28 — D-078: Prepare an exact no-launch C4 v3 authority

**Hypothesis.** After mechanically quarantining v2, a fresh v3 authority can be
prepared from the new committed state without contacting Omni or weakening the
single-use production gate. The new package must bind the changed run identity
and commit-derived schedule/plan hashes, retain the unchanged authenticated
semantic deployment digest, and refuse authorization when any tracked state,
decision state, output identity, or receipt identity is unexpected. This is a
general control-plane intervention, not a benchmark-question-specific change.

The public-only dry run at commit
`f1efd00ae49824b6eb13e6655157f83a022004f3` resolved 129 attempts and ten
deployment targets and reported `live_execution=not_started`. The fresh run ID
is `public-c4-baseline-v3`, with output root
`experiments/autoresearch/raw/public-c4-baseline-v3`, schedule SHA-256
`d9f9ea201e77f9e57e9a7859a983571ed35d45d2802b815cb48b2e2f5ec063b3`,
execution-plan SHA-256
`a875a10f5e0597aed2a14187418cee008144d7f4c950f44bf7c9fb3a098b7876`, and
semantic deployment SHA-256
`d805eb6869201f28f928a5774263062302b29a5d8786fc3c1c120cb27f19df80`.
Human decision `omni-benchmark-ei0.4.2.3` carries the exact binding and planned
concurrency-three, 21,600-second, USD 7 reservation / USD 560 telemetry policy.

A RED helper test first failed because the v3 operator helper did not exist.
The mode-0600 helper now checks the exact worktree, branch, commit, tracked and
allowed-untracked state, open human decision, private approval directory, and
absent v3 receipt/output identity. It uses argument-vector subprocesses rather
than a shell, writes the canonical receipt with exclusive mode-0600 creation,
records its byte-identical Beads response, and locally validates the result
without consuming it. Its SHA-256 is
`e586c44d3ee2c341423f1cbdadf911c418b8e8f09246954b0f27c007f48bd565`.
The three focused helper tests pass, Ruff and format checks pass, and the
no-authority check reports `ready_not_authorized_not_launched`. The receipt,
v3 output root, and v3 consumption marker remain absent. No Omni/network,
credential/lease, protected-label, push, or dispatch action occurred.

## 2026-08-29 — D-079: Run the one authorized public C4 v3 identity once

**Pre-launch hypothesis.** The v2 failure occurred before governed execution
because the canonical Omni profile session was stale. After the human-owned
canonical login, the exact fresh v3 identity should cross authentication; the
already-frozen observer retry policy and concurrency-three pacing should then
allow the 129-attempt public C4 arm to complete without changing prompts,
semantic content, managed model behavior, or answer eligibility. Any new
pre-answer infrastructure failure must stop and be preserved rather than
triggering an identity substitution or answer-dependent rerun. This is a
general authentication/pacing hypothesis, not a semantic intervention.

Human decision `omni-benchmark-ei0.4.2.3` authenticated the canonical one-hour
receipt with SHA-256
`6f139bea9803a20d337bdb1ba1ee1325236c4b3953d181d75d5ed63b48136416`.
Independent local validation matched the exact commit, v3 run/output identity,
schedule, execution-plan, and semantic-deployment hashes recorded in D-078.
The integration branch is at the exact committed state with only the spent v2
approval marker untracked; the v3 output and consumption marker are absent;
no competing v3 process exists. The child environment will use only the
human-recovered `benchmark-infra` profile and previously recorded HTTPS origin,
without login, refresh, credential inspection, or validation canary. The exact
authorized launch policy remains concurrency three, a 21,600-second wall bound
that finishes started database-condition blocks, USD 7 per-attempt reservation,
and USD 560 C4 telemetry ceiling. No dev-B, test, gold, or sealed correctness
input is in scope.

### Closed infrastructure interruption

The gate consumed the exact receipt before dispatcher construction. The
human-recovered profile crossed authentication and the scheduler completed its
already-started blocks, publishing 18 immutable generation/run records before
one new pre-attempt `whoami` call returned sanitized Omni HTTP 429. The run then
stopped fail-closed with one mode-0600 dispatcher diagnostic and no remaining
process or staging directory. It contains 12 answered and six ordinary errored
generation outcomes, but no correctness was inspected. All 85 preserved files
are mode 0600, the aggregate inventory SHA-256 is
`a060042bc053dee03af7c67f7672ea95fc62ae37abadff1ccb788bd2dec65588`,
and the recursive forbidden-field count is zero. The dispatcher failure file
SHA-256 is
`8d29256298554263d16eb0e6dc079bfb79ca1af3f2ae8501ace2d5dfa2a9915c`;
its stderr SHA-256 is
`4d0716e29ee966ee9a2068052261c5e77382f980cc528945cc6f30f1303378bf`.

The pacing/authentication hypothesis is only partially supported: login fixed
the v2 403, but concurrency three did not prevent observer throttling. More
importantly, source inspection after the stop refuted the premise that the
observer retry policy was frozen in the exact run commit. The parent bead and
research log contained a **pre-change hypothesis**, but no retry implementation
or tests exist; pre-attempt `whoami` calls the CLI directly and treats HTTP 429
as terminal. No v3 rerun or replacement is authorized. Beads
`omni-benchmark-aez.5` and `omni-benchmark-aez.6` now track exact v3 quarantine
and a prospective bounded retry limited to idempotent `whoami`/job-status
observations. Any commit/freeze and production replacement require separate
human authority.

## 2026-08-29 — D-080: Bound retries to idempotent C4 observations

**Pre-change hypothesis.** The v3 interruption was caused by a transient HTTP
429 on the pre-attempt identity observation, not by an evaluated answer or a
semantic-system action. A strict deterministic retry schedule of 1, 2, and 4
seconds, applied only to idempotent `whoami` and job-status observations, should
absorb short observer throttles without changing job submission, generated
queries, result retrieval, planning, typed execution, answer eligibility, or
question-specific behavior. Exhaustion must remain terminal. Observer retry
count and wait time must be recorded separately from the evaluated system's
`retry_count`, which remains unavailable for C4. RED tests will first prove the
two permitted retry paths, strict exhaustion, non-429 single-shot behavior, and
single-shot behavior for every non-idempotent/evaluated operation. This is a
general infrastructure-control hypothesis. No Omni request, credential action,
protected-label access, commit, or production dispatch is authorized by this
development work.

**Result.** The RED suite first failed only on the absent observer-retry and
separate-telemetry contracts. The implementation retries sanitized HTTP 429
responses on `whoami` and job-status only, using the exact 1/2/4-second default
schedule and a maximum of three retries. It recognizes both textual and
JSON-shaped status diagnostics, emits an explicit bounded-exhaustion detail,
and leaves model `retry_count` null. Cumulative `observer_retry_count` and
`observer_retry_wait_ms` are carried separately into C4 generation telemetry;
the strict artifact validator rejects partial or inconsistent pairs. Tests
prove that non-429 observer failures and list/read, job submission, job-result,
plan, and typed-query operations remain single-shot. A first full gate exposed
only the repository's 800-line module-focus limit; moving the new validator to
the existing artifact-validation module resolved it without behavior change.
The final full gate passes 1,452 tests with five expected skips and 84.33%
branch coverage; Ruff, format, and diff checks pass. No Omni request,
credential/lease action, protected-label access, correctness inspection, or
production dispatch occurred.

## 2026-08-29 — D-081: Prepare exact no-launch public C4 v4 authority

**Preparation hypothesis.** With v3 quarantined and the bounded observer retry
committed, a fresh v4 identity at `ae08ec8a1d76111302af8af6d04ad73dc64ff8e6`
should resolve the same 129-question, ten-database public arm and unchanged
semantic deployment while changing schedule/execution-plan hashes to bind the
new run ID, output root, and system commit. A mode-0600 exact helper should fail
closed unless the branch, commit, clean tracked state, two prior immutable
consumption markers, open human decision, and absent v4 receipt/output all
match. Package preparation must not contact Omni or create/consume a receipt.

**Result.** The public-only dry run resolved 129 attempts and ten deployment
targets with `live_execution=not_started`. The exact hashes are schedule
`b58485722980f292180d3a3a8c956dc6bad37583e494dcc580ea49ac7338442d`,
execution plan
`5fab1f6967fc9e877aa333eaccd2ca9760f42646c93ad627d99b6b7c6da3d221`,
and unchanged deployment
`d805eb6869201f28f928a5774263062302b29a5d8786fc3c1c120cb27f19df80`.
Human decision `omni-benchmark-ei0.4.2.4` is open. The helper at
`/home/ds/.omni-benchmark-approvals/authorize-public-c4-baseline-v4.py` is mode
0600 with SHA-256
`67b214e91851b9dfecf946986a85845ccbebf20768f503e0aa124ae9a78a2f4c`.
Seven recomputed binding/state checks pass; Ruff and format checks pass; two
no-authority invocations report `ready_not_authorized_not_launched`. The v4
receipt, output, and consumption identities remain absent. No Omni request,
credential/lease action, protected-label access, correctness inspection,
receipt creation/consumption, push, or dispatch occurred.

## 2026-08-29 — D-082: Diagnose the dominant wrong-answer class without gold content

**Pre-analysis hypothesis and fixed diagnostic.** Official dev-A scoring shows
245 wrong answers among 366 scoreable direct-comparator attempts. The leading
general mechanism is likely structural query construction—relation selection,
join/grain handling, or aggregation—rather than inability to emit runnable SQL.
Before reading any question-level outcome, join the immutable official score
records to their hash-bound generation records and derive only SQL-shape
features: relation count, join count, aggregate functions, grouping, distinct,
windows, nesting, and filters. Report condition-stratified correct/wrong
aggregates and paired C1/C2/C3 outcome transitions; do not print question IDs,
SQL text, gold, values, or hidden annotations. The analysis may prioritize one
of preregistered E01--E03 only if the aggregate evidence matches its mechanism;
it cannot invent question-specific logic or change a human-controlled surface.
The scorer artifacts remain immutable, C4 is awaiting exact authority, and
dev-B/test are out of scope.

**Result.** The reproducible SQL-shape analyzer is
`experiments/analysis/wrong_answer_structure.py` at SHA-256
`fbd8c05818f0470607f09b58af767212bd2232e886637cae3d9085c8cbef3c27`;
its deterministic aggregate output SHA-256 is
`ce34aabad46026f122e21b7449549a4a751bc10650f01dfd3abbb43cb48eb0fc`.
Two focused tests pass and Ruff/format/diff checks are clean. It hash-verifies
the official score artifact, resolves only the two frozen baseline run roots,
verifies each generation-record digest, and emits no identifiers or SQL text.

All 299 correct-or-wrong SQL records parse. Of 122 fully scoreable questions,
61 are wrong in all three conditions and only nine are correct in all three;
13 are corrected by C2 while both C1 and C3 remain wrong/refused. Mean relation
count is consistently higher for wrong than correct SQL: C1 3.163 versus 2.000,
C2 3.275 versus 2.483, and C3 3.041 versus 1.812. Small complex-shape groups are
especially fragile: 30/31 window queries, 25/28 distinct queries, and 16/19
nested queries are wrong. Mere aggregation or join presence is not itself a
strong separator—aggregate-present and join-present wrong rates remain close to
their absent groups—so the evidence does not justify a simplistic “ban joins”
or “add aggregation” intervention. It instead supports the preregistered
relationship/grain/dependency family while leaving E01 versus E02 causality
unresolved. Preserve the E01-first order; use this result as a mechanism
diagnostic, not outcome-selected question logic. No gold content, hidden
annotation, result value, dev-B/test record, or C4 correctness was read.

## D-136: First scored accuracy on dev-A, and the scorer settles the database question

Date: 2026-08-29. Artifact `public-direct-baseline-dev-a-scores-v1`, both frozen
scorers over 420 dev-A attempts (140 selected questions of 154 released, 14
unrepresented, three direct conditions). No C4 arm: this is comparator baseline
only, and neither primary perspective is available yet.

### The two broken databases are a gold failure, not a system failure

54 attempts returned `status=unscorable` with
`failure_category=gold_statement_error`, and they are exactly `mental_healths`
(27) and `organ_transplant` (27). Nothing else in the partition is unscorable.
The benchmark's own reference SQL does not execute against those two databases.

This is independent of the D-134 reconstruction from action evidence and lands in
the same place by a different route: the environments reject the published table
names, and they reject the gold query too. The evaluated system was never the
variable. The classification question raised in D-134 is now moot for scoring,
because the scorer excludes these questions rather than counting them as wrong,
so the figures below rest on 122 clean questions per condition.

### Accuracy

Official Soft EX, correct over scoreable attempts, Wald 95%:

| | correct | rate | 95% CI | wrong | refused/error |
| --- | --- | --- | --- | --- | --- |
| C1 raw schema | 9/122 | 7.4% | [2.7, 12.0] | 80 | 33 |
| C2 searchable raw HKB | 29/122 | 23.8% | [16.2, 31.3] | 91 | 2 |
| C3 exported semantic model | 16/122 | 13.1% | [7.1, 19.1] | 74 | 32 |

C1 vs C2 z=-3.53 p=0.0004; C2 vs C3 z=+2.15 p=0.0319; C1 vs C3 z=-1.48 p=0.1395.

Sensitivity scorer (`omni-multiset-decimal-v1`) over 121 scoreable: C1 7.4%, C2
23.1%, C3 11.6%, with the same ordering and the same significant contrasts
(C1 vs C2 p=0.0007, C2 vs C3 p=0.0175, C1 vs C3 p=0.2731). The two frozen scorers
agree on the structure, which is the reason for reporting both.

### What changes from the capture-level reading

D-067 found C1 and C3 statistically indistinguishable on capture completion
(p=0.80, and p=0.84 excluding the broken databases). On accuracy C3 nearly
doubles C1 (16 against 9), though the contrast does not reach significance
(p=0.14). Completion and correctness are not the same ranking, which is the
concrete form of the warning recorded in D-066: under Soft EX a refusal and a
wrong answer both score zero, so a condition that refuses less is not thereby
more accurate.

C2's completion advantage was 97.9% against roughly 75%. Its accuracy advantage
is 23.8% against 7.4%, and 91 of its 122 attempts produce runnable SQL with wrong
results. The advantage is real and it is much smaller than completion suggested.

### The dominant outcome is a wrong answer

Across all scored attempts: 245 wrong, 67 refused or errored, 54 correct. The
direct comparators mostly answer, and mostly answer incorrectly. Absolute
accuracy of 7-24% means the interesting question for the write-up is why runnable
SQL returns wrong results, not why attempts fail to produce SQL. That reorients
the failure work: `omni-benchmark-dx3` (refusal) and
`omni-benchmark-dih.5.4.2.4.4.2.2.2` (budget) together cover 67 of 366 scored
attempts, while 245 sit in a class none of the open beads addresses.

### Outcome

File the wrong-answer class as its own investigation, since it is now the largest
by a factor of three and has no owner. Nothing here touches C4, so no primary
endpoint has been estimated and none of these contrasts is confirmatory: C2-C1
and C3-C2 are exploratory rung-level comparisons under the preregistration.

## 2026-08-29 — D-083: E01 is already part of the frozen baseline

### Pre-audit hypothesis

Before implementing E01, verify whether its proposed contrast exists. The
public semantic compiler may already topologically materialize acyclic,
same-grain HKB dependencies, preserve exact source provenance, and reject
missing, undeclared, cyclic, unresolved, and cross-grain dependency references.
If so, E01 cannot identify an intervention effect and must be recorded as a
no-op/inconclusive experiment rather than altered after baseline scoring.

Bead `omni-benchmark-ei0.4.3`; change class: experiment-integrity audit. The
audit is restricted to committed public HKB, schema, mapping, bundle, and
manifest artifacts. It may emit aggregate counts only and may not access
question-level outcomes, gold SQL or values, hidden annotations, dev-B/test,
Omni, or credential/lease state.

### Result

The hypothesis is confirmed. Commit `4622f0f`, which predates the E01--E04
preregistration, added fail-closed exact dependency-reference validation and
expressed dependent formulas through compiled semantic fields. The current
compiler also topologically orders dependency nodes and rejects cycles,
unresolved dependencies, non-compiled dependencies, and dependencies outside
the target table.

The reproducible public-only audit
`experiments/analysis/e01_baseline_collision.py` regenerated all 254 bundle
files across all 18 databases byte-for-byte. The frozen baseline contains 193
compiled elements, including 48 dependency-bearing elements and 70 executable
same-grain dependency edges; compiled dependency depth reaches three. Its
aggregate output SHA-256 is
`fa620c48856abf7a6acefa0ae09150522b0399c270d397c904d1ce66d7ee0a51`.
Two focused tests pass; Ruff, formatting, and diff checks are clean.

### Outcome

INCONCLUSIVE — ALREADY BASELINE. E01 has no baseline-versus-intervention
contrast and cannot be run honestly as written. Do not relabel the existing
mechanism as a new candidate, weaken its guardrails to manufacture a contrast,
or change the preregistered definition. Treat the baseline itself as evidence
that conservative same-grain dependency composition alone does not resolve the
observed accuracy gap, and advance to E02 in the frozen sequence.

### Product implication

Experiment registries should mechanically diff proposed intervention surfaces
against the frozen system before registration. A semantic-model provenance
view that explicitly enumerates already-active transformation mechanisms would
make no-op experiments easier to catch before evaluation begins.

## 2026-08-29 — D-084: Start E02 with a public relationship contract

### Pre-change hypothesis

A deterministic planner can safely identify a conservative subset of
cross-table relationships using public schema structure alone: accept a foreign
key only when its target columns exactly match a declared primary or unique key
and both source and target entity grains are explicit. Encode many-to-one
cardinality, nullable-source optionality, exact join columns, and public-schema
provenance. Defer non-unique targets, missing grains, unresolved references, and
all other ambiguous edges with explicit reasons instead of guessing.

Bead `omni-benchmark-ei0.4.4`; generality: cross-database/general;
optimization surface: structural relationship and grain modeling. RED tests
must cover primary and unique targets, composite-key order, source optionality,
unknown source grain, non-unique targets, determinism, and protected-field
rejection before implementation. The first artifact is a candidate relationship
contract only: it does not deploy to Omni or reclassify an HKB metric. A metric
may move out of `defer_cross_grain` only when the public HKB supplies the exact
required aggregation. No question-level outcome, gold SQL/value, hidden
annotation, dev-B/test, live-system, or credential/lease input is permitted.

### Result

The candidate contract is implemented without deployment. Across all 18 public
schema IRs, the deterministic inventory finds 1,228 declared foreign keys.
Exactly 1,049 target a declared primary/unique key and have resolvable source
and target entity grains; 179 target non-unique columns and remain explicitly
deferred. Of the eligible relationships, 281 require exactly one target and 768
permit zero or one because at least one source FK column is nullable. No public
schema contains a multi-column eligible FK.

The planner retains exact join columns and public-schema provenance, encodes
`many_to_one` cardinality and source optionality, and rejects or defers
protected fields, non-public provenance, unresolved/wrong-table columns,
unresolved grains, missing tables, non-unique targets, malformed column pairs,
and invalid nullability. It does not emit Omni files or change mapping
dispositions. Seven focused tests pass, and the repository-wide gate passes
1,491 tests with three expected skips and 84.18% branch coverage; Ruff,
formatting, and diff checks are clean. The deterministic aggregate inventory
SHA-256 is
`767754900926f760b7f1bb1e482d679789bd0eb0b30fdb7dfca2eae8f74aa45f`.

### Outcome

KEEP as an E02 prerequisite. Relationship structure is much less sparse than
the baseline semantic model suggests, but optionality is dominant and 179
declared edges fail the conservative uniqueness gate. The next E02 step may
compile only this accepted contract into an isolated candidate bundle and must
still leave every metric deferred unless its public HKB provides an explicit
aggregation contract.

## 2026-08-29 — D-085: Compile the bounded E02 relationship candidate

### Pre-change hypothesis

The first deployable E02 candidate should include only accepted public
relationship contracts whose source and target tables already have views in
the frozen semantic bundle. This bounds the candidate to 91 relationships
across 16 databases; the other two databases have no eligible modeled edge,
and no modeled source-target pair is duplicated. Emit Omni's documented global
relationship form using `always_left`, `many_to_one`, and explicit
`reversible: false`, then expose only direct outbound target views from each
source topic. Preserve exact public provenance in the bundle manifest.

Bead `omni-benchmark-ei0.4.5`; generality: cross-database/general;
optimization surface: relationship-aware semantic bundle compilation. The
existing baseline compiler must remain byte-identical; E02 is an opt-in
candidate compiler. RED tests must cover relationship SQL, direction,
cardinality, topic exposure, unmodeled-edge exclusion, deterministic manifest
provenance, and safe deployment-plan parsing of Omni's top-level relationship
sequence without relaxing the mapping-only contract for views and topics.
This step does not reclassify any HKB metric, deploy to Omni, inspect outcomes,
or access gold, hidden annotations, dev-B/test, or credential/lease state.

### Result

The opt-in compiler emits 91 deterministic global relationships across 16
databases and exposes them from 67 direct source topics. The 18 candidate
bundles contain 272 files including one explicit `relationships` sequence per
database. Every emitted edge uses `always_left`, `many_to_one`, and
`reversible: false`, with bounded equality predicates over exact modeled field
references. This matches Omni's documented global relationship schema and
cardinality semantics:
<https://docs.omni.co/modeling/relationships/index> and
<https://docs.omni.co/modeling/relationships/parameters/relationship-type>.

All baseline semantic elements remain byte-for-byte equal at the manifest
level (`metric_disposition_changes=0`); E02 adds relationship structure only.
The baseline compiler remains unchanged as the default path. Exact public
foreign-key provenance and source optionality stay in the candidate manifest.
A shared protected-field guard removes the prospective compiler import cycle
without weakening the existing `SemanticBundleError` boundary.

The deployment planner now recognizes only the exact `relationships` file name,
requires a top-level YAML sequence, rejects mappings or malformed entries,
permits only the fixed non-reversible many-to-one shape, and bounds `on_sql` to
one or more exact field-reference equalities. View and topic files remain
mapping-only. The deterministic aggregate candidate SHA-256 is
`cc1f3f81e9c387a3ce1358dddf17073fa0506bce0318f59a07bf7044002ed06a`.
The focused relationship/bundle/deployment suite passes 124 tests; the full
repository gate passes 1,497 tests with three expected skips and 84.17% branch
coverage; Ruff, formatting, and diff checks are clean.

### Outcome

KEEP as the frozen offline E02 candidate implementation. No bundle was written
to a production model, no Omni request was made, and no metric was promoted.
The next authorized experiment step is immutable candidate publication plus an
isolated public-only deployment/validation; accuracy evaluation still requires
the established C4 experiment authorization and full dev-A gate.

## 2026-08-29 — D-086: Hash-bind and locally authenticate E02 publication

### Pre-change hypothesis

The existing public bundle publication boundary can expose a separate opt-in
E02 build/publish API while retaining byte-identical baseline behavior. Both
paths must authenticate the same bundle spec, HKB IR, schema IR, mapping, and
mapping-manifest inputs; recursively reject protected fields; hash every output
file; refuse symlinked inputs and unsafe/existing destinations; and retain the
same source-provenance manifest. E02 output must additionally pass the strict
local deployment-plan parser, including its relationship sequence contract.

Bead `omni-benchmark-ei0.4.6`; change class: general publication integration.
RED tests must prove separate E02 build and publication, unchanged baseline
output, relationship-file hash binding, and deployment-plan acceptance. Then
build all 18 public candidates in ephemeral local directories and authenticate
them without any Omni request. No credential, deployment, scoring, outcome,
gold, hidden annotation, dev-B, or test action is permitted.

### Result

Separate `build_e02_bundle_artifacts` and `publish_e02_bundle_artifacts` APIs
now reuse the unchanged authentication, input-size, protected-field,
source-hash, exclusive-publication, and manifest boundaries. The existing
baseline build/publish API remains the default and its tests remain
byte-identical. E02 publication includes the exact `relationships` file in the
file manifest and SHA-binds it alongside every view and topic.

The reproducible ephemeral validator published all 18 public candidates, then
successfully rebuilt 18 strict deployment plans over 272 files and 91
relationships. Temporary outputs were destroyed on context exit. The aggregate
candidate-set SHA-256 is
`16ee2a02f994d3f90234e24366fe6ddefd041b3b0d2a7e63c001b4803a0fe6da`;
the canonical aggregate validation-output SHA-256 is
`658c71d8c7f6c93317790e5986d8530ec3caab671b1cb8586d9a945d896d6f72`.
Twelve focused publication tests pass. The full repository gate passes 1,500
tests with three expected skips and 84.18% branch coverage; Ruff, formatting,
and diff checks are clean.

### Outcome

KEEP. E02 is now reproducibly publishable and locally deployment-ready without
committing generated run artifacts or contacting Omni. The remaining boundary
is genuinely external: isolated candidate deployment/validation and later
full-dev-A evaluation require the appropriate live authority and stable
credential ownership. No such action occurred here.

## 2026-08-29 — D-087: Advance the results report without crossing the live gate

### Pre-edit hypothesis

The standalone results report can absorb the frozen direct dev-A baseline and
the completed E01/E02 offline trajectory now, while leaving C4, dev-B, and
sealed endpoints visibly pending. Doing so will shorten the post-evaluation
critical path and expose narrative gaps without turning development evidence
into a held-out claim.

The edit is restricted to already-recorded aggregate evidence. It may report
the immutable official and sensitivity denominators, condition-level counts,
SQL-shape aggregates, and public-only E01/E02 artifacts. It may not inspect or
report question identities, SQL text, result values, hidden annotations,
dev-B/test outcomes, C4 correctness, or any sealed result. The bounded schema
retrieval claim must remain separate from per-attempt token and cost telemetry.

### Planned outcome

Update `RESULTS.md` so its status, executive summary, baseline table,
experiment trajectory, recommendations, and limitations match the frozen
evidence as of D-086. Preserve explicit pending cells for every result that has
not passed its established custody or live-execution gate. Validate links,
arithmetic, prose, and the absence of accidental hidden-result claims before a
narrow commit.

### Result

Commit `c6073bc` updates only `RESULTS.md`. The report now gives the exact
official and sensitivity denominators and C1-C3 counts, separates capture
completion from accuracy, records the SQL-shape diagnostic, marks E01
inconclusive because it was already active, and records E02 as a locally
authenticated offline candidate. C4, dev-B, final-candidate, and sealed tables
remain pending. The schema-retrieval section distinguishes the four-table/64
KiB payload bound from the observed $1.48-$1.84 mean per-attempt costs.

All local Markdown link targets exist; the disposition and baseline arithmetic
recompute exactly; `git diff --check` passes; and the report SHA-256 is
`3206c66343ef999f5e9b1611625be7d20a3262772278a8aa8ff8a098da439d86`.
The edit used only existing aggregate/public evidence. No run artifact, private
record, question identity, SQL text, result value, hidden annotation, dev-B/test
record, credential, or live service was accessed.

### Outcome

KEEP. The primary report is materially closer to submission-ready and can be
filled forward after C4 and sealed evaluation without restructuring. Bead
`omni-benchmark-zjp` remains open because its held-out sections are still
blocked by the established live and custody gates.

## 2026-08-29 — D-088: Restore the report's mechanism context

### Pre-edit hypothesis

The results report still omits two public-method facts required by its durable
brief: the HKB's multi-hop dependency topology and the ordered failure-mechanism
ladder. Adding them will make the grain/relationship finding interpretable and
will show how later error attribution avoids collapsing every failure into model
reasoning.

Use only the aggregate public reconnaissance already recorded in
`docs/benchmark-notes.md` and the preregistered ladder in
`docs/failure-taxonomy.md`. Do not classify any question from hidden
annotations, access a private record, or imply that ladder prevalence has been
measured. Preserve every live and sealed placeholder.

### Result and outcome

KEEP in commit `8ebb05b`. Section 3 now records 1,090 public HKB entries, 945
dependency edges, 560 dependency-bearing entries, 344 edges into another
derived entry, multi-hop structure in 18/18 databases, and a maximum six-edge
chain. Section 5 states the fixed earliest-supported mechanism sequence from
absence through residual reasoning and explicitly leaves its prevalence
pending.

The final `RESULTS.md` SHA-256 is
`dd7e713778b74430408fa16c60bf7ef33657688ef0a6c3b21499b5afbdc2356f`.
Local links, aggregate arithmetic, prose review, and `git diff --check` pass.
No hidden annotation or private/run artifact was opened, and all live and sealed
gates remain unchanged.

## 2026-08-29 — D-089: Integrate E02 with the exact C4 control plane offline

### Pre-integration hypothesis and boundary

The already-reviewed E02 commits can be replayed onto exact public C4 v4 system
commit `ae08ec8a1d76111302af8af6d04ad73dc64ff8e6` in a new isolated worktree,
preserving the immutable deployment-content, budget, human-approval, quarantine,
and bounded-observer controls. The resulting branch should be ready for a
separately authorized post-baseline E02 deployment without replaying unrelated
main history.

Bead `omni-benchmark-ei0.4.7`; generality: cross-database experiment
integration. This step is offline only. It may compile, publish ephemerally, and
authenticate public candidate bundles, but it may not contact Omni, inspect or
alter credentials, consume an approval, deploy a model, launch a run, or access
gold, hidden annotations, dev-B, or test records.

### Result

Clean isolated branch `codex/e02-c4-integrated` at
`0fc539bf8d9889e922c79a6d83d0c158bdbaa797` descends directly from `ae08ec8`
through four scoped commits: `e41c366` (relationship contracts), `b26b624`
(bounded compiler), `9fc21c6` (authenticated publication), and `0fc539b`
(combined readback regression). Only the semantic deployment parser overlapped.
The resolution retains attested physical-field SQL restoration for view
readback while admitting only the fixed, bounded global relationship sequence.
A regression covers both mechanisms in the same deployment plan and passes
under normal and optimized Python execution.

The exact C4 approval, batch, live-dispatch, live-deployment, and quarantine
paths are byte-identical to `ae08ec8`, which remains an ancestor. The final
branch changes only the three E02 implementation/test surfaces plus the one
combined regression. Baseline committed-artifact regeneration stays green.

Public-only validation still finds 1,228 foreign keys, 1,049 conservative
contracts, 179 non-unique deferrals, 91 modeled relationships across 16
databases, 67 joined source topics, 272 files, and zero metric-disposition
changes. All 18 candidates publish ephemerally and authenticate. The integrated
candidate-set SHA-256 is
`c08ee8c10e4b2c26a142da5f36971dbb19488a827febf0514f5876e75b3a6f61`;
the canonical publication-validation output SHA-256 is
`d110586b0e163af9a4a7e6500aed2e3e9200e213198a96ad6905cfc27e736a16`.

Final gates pass: 1,469 tests, five explicit integration skips, 84.30% branch
coverage, Ruff, formatting, and diff checks. The worktree is clean. No live
request, credential action, approval consumption, deployment, run, protected
label, push, or main-worktree code mutation occurred.

### Outcome

KEEP. The post-baseline E02 experiment now has a clean, tested system branch.
This branch is not a launch authorization. Public C4 v4 must first complete and
freeze under its exact human receipt; E02 deployment and evaluation still need
a later, separately bound authorization package.

Main documentation commit `b3c7b03` updates only `RESULTS.md` to preserve both
the initial main-only candidate hash and the deployment-relevant integrated
candidate hash. The resulting report SHA-256 is
`599fa13bfc237aba7c07575a88ccbf2c4fa1ce1686b869f07f0fda6371553591`;
links, arithmetic, prose, and diff checks pass.

## 2026-08-29 — D-090: Bind sealed scoring to Freeze B before gold admission

### Decision / experiment

Close the mechanical gap between the preregistered Freeze B and the existing
generate-then-score gate using only public and synthetic fixtures. Change type:
general evaluation integrity. Bead: `omni-benchmark-dih.5.4.1.1`.

### Hypothesis

Requiring one canonical system freeze, twelve condition/repetition run
manifests, and per-generation provenance at the scoring boundary will prevent a
stale or substituted generation from being scored without expanding the
evaluator's access to hidden data.

### Intervention

Added exact-schema immutable Freeze B and sealed-run manifest types. Freeze B
records the final commit, frozen-file hashes, all four condition specifications,
non-null C3/C4 semantic-model hashes, scorer identity, database snapshot and
versions, and an externally supplied schedule seed and digest. The sealed batch
gate now reparses those manifests and verifies all 1,212 generations against the
ordered schedule and twelve run bindings before indexing the gold collection.

### Result

Forty focused synthetic tests cover canonicalization plus schedule, condition,
configuration, semantic-model, run-manifest, generation, and record-hash
tampering. A sentinel proves provenance failures occur before any gold access;
the database provider also remains untouched. The full suite passes with 1,501
tests, five expected skips, and 84.32% branch coverage. Ruff and diff checks are
clean. No schedule seed was chosen, no final manifest was instantiated, and no
private data, credentials, live service, or approval receipt was accessed.

### Interpretation

The implementation makes Freeze B enforceable at scoring time; it does not
perform the human-controlled freeze. Final candidate selection, the schedule
seed, actual content hashes, and sealed execution remain pending.

### Outcome

KEEP.

### Product implication

Evaluation provenance should be a required input to scoring, not an adjacent
document. Exact run-to-freeze bindings make results auditable without exposing
the underlying questions or answers.

### Next step

After candidate selection, create and commit the actual Freeze B manifest and
ordered schedule before starting any test generation.

## 2026-08-29 — D-091: Derive Freeze B from Git objects, not the working tree

### Decision / experiment

Add the smallest operator path needed to instantiate the already-defined
Freeze-B contract after final-candidate selection. Change type: general
evaluation integrity. Bead: `omni-benchmark-dih.5.4.1.2`.

### Hypothesis

If the recorder derives every content hash from the exact system commit and
validates the complete identity-only trial matrix before writing, then a dirty
working-tree substitution, stale configuration, or incomplete schedule cannot
silently enter the final freeze.

### Intervention

Added a committed-input specification and `sealed_tools/record_freeze_b.py`.
The recorder requires the exact current 40-character commit, verifies Freeze A
as an ancestor, accepts only regular Git blobs from bounded safe paths, and
derives condition, semantic-model, database-snapshot, and frozen-file SHA-256
values from those blobs. The schedule must be canonical JSONL containing all
101 identities under four conditions and three repetitions. Output creation is
exclusive, confined, no-follow, and mode 0600.

The security pass also strips inherited `GIT_*` variables from subprocesses and
requires the loaded recorder, scorer, content-policy, Freeze-B, and exclusive-
writer source bytes to match the system commit. The command reports hashes and
counts only; it does not print the seed or schedule identities.

### Result

Twenty-one focused tests pass with 81.47% branch coverage of the new module.
They cover dirty working-tree substitution, abbreviated/stale commits,
uncommitted and symlink Git entries, missing provenance, malformed schedule
matrices, Git-environment redirection, runtime-source substitution, symlinked
output parents, overwrite refusal, mode 0600, and the real script entry point.
The full suite passes 1,522 tests with five expected skips and 84.30% branch
coverage; Ruff, formatting, and diff checks pass.

No actual schedule seed, final input specification, Freeze-B manifest, or test
generation was created. No hidden data, live service, credentials, approval
receipt, or protected result was accessed.

### Interpretation

Freeze B can now be created reproducibly once the final candidate and
human-controlled seed exist. This removes hand-authored hashes from the sealed
critical path without moving candidate selection or schedule authority into the
agent.

### Outcome

KEEP.

### Product implication

An evaluation freeze should be derived from immutable source objects and should
bind the code performing the derivation. A manifest that merely repeats
operator-supplied hashes does not prove which system was evaluated.

### Next step

After the public C4 baseline and the authorized E02 dev-A experiment, select the
final candidate. Then commit the final schedule/specification with the human
seed and invoke the recorder exactly once before sealed generation.

## 2026-08-29 — D-092: Derive the sealed schedule from committed identities

### Decision / experiment

Remove the remaining hand-authored schedule step from the Freeze-B critical
path without choosing the human-controlled seed or reading test content. Change
type: general evaluation integrity. Bead: `omni-benchmark-dih.5.4.1.3`.

### Hypothesis

If the final 1,212-attempt order is deterministically derived from the exact Git
blob containing the 101 test identities and a later human-supplied seed, and the
Freeze-B recorder reproduces those bytes independently, then dirty-tree
substitution, missing trials, adjacent repetitions, and a structurally valid but
hand-reordered schedule cannot silently enter sealed execution.

### Intervention

Added `sealed_tools/generate_freeze_b_schedule.py` and a small identity-only
schedule module. `committed_block_interleaved_v1` first orders questions by a
domain-separated SHA-256 of the seed and identity. At each of 101 positions it
emits four-condition blocks for repetitions one through three using offsets 0,
34, and 67; condition order receives a separate domain. This yields exactly
1,212 unique attempts and keeps repetitions of one question at least 98 blocks
apart.

The generator requires the exact full current commit, reads only the committed
regular-file blob at `data/manifests/test_ids.txt`, strips inherited `GIT_*`
redirections, binds all loaded critical sources to that commit, and writes
canonical JSONL exclusively with mode 0600. Its summary exposes only hashes and
counts. The recorder now requires the committed test-ID manifest in
`frozen_files` and recomputes the complete schedule from its recorded seed; byte
inequality fails before Freeze B is written.

### Result

Ninety focused Freeze-B, recorder, schedule, and sealed-scoring tests pass. The
new schedule module has 97% branch coverage and the combined recorder/schedule
coverage is 84.28%. Adversarial cases cover dirty substitutions, abbreviated or
stale commits, malformed, duplicate, unsorted, wrong-count, symlinked, or
non-newline-terminated identity manifests, seed substitution, schedule
reordering, Git-environment redirection, runtime-source replacement, symlinked
output parents, overwrite refusal, mode 0600, and both CLI entry points.

The repository-wide gate passes 1,539 tests with five expected skips and 84.35%
branch coverage. Ruff, formatting, and diff checks pass. No actual seed, final
schedule, input specification, Freeze-B manifest, hidden field, protected
result, live service, credential, approval receipt, or test generation was
accessed or created.

### Interpretation

The final schedule is now reproducible and mechanically bound to the frozen
split identities while seed choice remains outside agent authority. This closes
the gap between a declared schedule algorithm and the exact order accepted by
the Freeze-B recorder.

### Outcome

KEEP.

### Product implication

For sealed evaluations, validating that a schedule has the right rows is weaker
than proving how those rows were ordered. Recomputing the order at the freeze
boundary makes randomization auditable without exposing question content.

### Next step

After C4 and the authorized E02 dev-A experiment, select the final candidate.
Then obtain the human seed, generate and commit the one schedule and Freeze-B
input specification, record Freeze B once, and begin sealed generation only
after the freeze record is committed.

## 2026-08-29 — D-093: Separate the frozen system from its control record

### Decision / experiment

Resolve the Freeze-B manifest's unavoidable Git self-reference before building
the sealed dispatcher. Change type: general evaluation integrity. Bead:
`omni-benchmark-ei0.5.1`.

### Hypothesis

If frozen system commit `S` is followed by direct control commit `F` that adds
only the canonical Freeze-B manifest, then the record can be committed before
held-out generation without changing any evaluated code, configuration,
schedule, or semantic artifact after the freeze.

### Intervention

Added `sealed_tools/validate_freeze_b_control.py` and an exact committed-record
loader. It requires `F` to be the current full commit and a direct non-merge
child of full commit `S`. The Git-object diff from `S` to `F` must be exactly one
added `100644` manifest blob; modified, deleted, renamed, executable, symlinked,
or additional paths fail. The loader reads the committed blob rather than the
working tree, enforces its byte limit and canonical Freeze-B schema, requires
both manifest and scorer source identities to equal `S`, and verifies all
loaded critical runtime sources against `S`.

### Result

One hundred five focused Freeze-B control, schedule, recorder, manifest, and
sealed-scoring tests pass with 86.95% combined branch coverage; the new control
module has 96% branch coverage. Tests cover dirty substitution, abbreviated,
stale, unavailable, or mismatched commits, non-direct ancestry, merge commits,
extra or modified paths, unsafe manifest paths, Git symlinks, executable blobs,
noncanonical and oversized JSON, runtime-source drift, inherited `GIT_*`
redirection, symlinked workspaces, and both CLI entry points.

The repository-wide gate passes 1,554 tests with five expected skips and 84.42%
branch coverage. Ruff, formatting, and diff checks pass. No real Freeze B,
schedule seed, test generation, hidden field, protected result, live service,
credential, approval receipt, or push was accessed or created.

### Interpretation

The committed control record is now an auditable envelope around an unchanged
frozen system rather than an impossible member of its own hash. A later sealed
dispatcher can load `F` while requiring every evaluated input and runtime source
to remain exactly `S`.

### Outcome

KEEP.

### Product implication

Content-addressed release manifests need an explicit control-plane commit
boundary. Requiring the control commit to be otherwise empty makes post-freeze
administration visible without silently changing the evaluated product.

### Next step

Build the no-execution sealed plan from validated `F`, frozen `S`, the committed
identity-only schedule, and the public eligible-question manifest. Then add the
separately human-authorized dispatcher without admitting gold or scoring during
generation.

## 2026-08-29 — D-094: Materialize the sealed plan without execution

### Decision / experiment

Build the exact sealed-generation plan before introducing any live dispatch
authority. Change type: general evaluation integrity. Bead:
`omni-benchmark-ei0.5.2`.

### Hypothesis

If a no-execution planner derives every attempt from the validated `S` → `F`
boundary and exact frozen public Git objects, then the later dispatcher can
receive a complete, content-addressed plan without widening ordinary test-scope
loaders or admitting gold, correctness, or question-specific runtime state.

### Intervention

Added `sealed_tools/plan_sealed_generation.py` and a sealed-only planner. It
loads canonical Freeze B from control commit `F`, requires `F` to be the current
otherwise-empty direct child of frozen system `S`, and reads the schedule, test
identities, and public eligible-question manifest from Git objects at `S`. Each
input must match its Freeze-B frozen-file digest. The schedule is independently
regenerated from the committed identities and human seed before its rows are
interpreted.

The public manifest is canonical JSONL with its exact public schema. Recursive
protected-field rejection runs before record interpretation. The resulting
in-memory plan retains attempt/cohort identity, condition, repetition, database,
and SHA-256 of public question text, but no question text. The CLI exposes only
hashes and aggregate counts. The planner binds its loaded source to `S` and does
not execute, authorize, contact a service, read gold, or create run artifacts.

### Result

Twenty synthetic TDD tests pass. They prove the exact 1,212-attempt order,
twelve 101-attempt cohorts, database mapping, question digests, deterministic
plan hash, and dirty-working-tree independence. Adversarial cases cover absent
or mismatched frozen digests, recursive protected fields, duplicate or missing
public identities, invalid database/question values, noncanonical manifests,
reordered/missing/duplicate/noncanonical schedules, Git symlinks, runtime-source
drift, stale control commits, and CLI disclosure.

### Interpretation

The sealed critical path now has a deterministic boundary between Freeze B and
future execution. A dispatcher can consume one already-validated plan rather
than rediscovering test membership or joining mutable working-tree inputs.

### Outcome

KEEP.

### Product implication

Held-out execution is safer when planning and execution are separate
capabilities. A hash-only planning surface provides an auditable handoff while
keeping live authority absent.

### Next step

Add the sealed-only prepared-attempt and immutable staging layer behind an exact
human production receipt. Keep generation separate from scoring and gold, and
prove the complete path with public/synthetic dry runs before any sealed launch.

## 2026-08-29 — D-095: Make sealed resume an immutable reconciliation

### Decision / experiment

Build the sealed-only prepared-attempt and private staging boundary before live
dispatch. Change type: general evaluation integrity. Bead:
`omni-benchmark-ei0.5.3`.

### Hypothesis

If each future generation is prepared from one validated plan row and persisted
as one atomic, Freeze-B-bound private envelope, then interrupted orchestration can
distinguish absent, identical, conflicting, and incomplete state without
answer-dependent reruns or weakening the dev-only attempt loaders.

### Intervention

Added an offline sealed preparation/staging module. Preparation verifies the
complete ordered plan, its schedule hash, the three required public frozen-file
digests, the exact Freeze B, public question hash, and matching condition
configuration. It mints a process-local opaque authority binding the plan,
system/control commits, condition, repetition, database, and question. Question
text is excluded from representations and public summaries.

Staging writes one canonical mode-0600 `attempt.json` beneath a confined,
gitignored mode-0700 run root. The envelope holds the private generation record
and a SQL-free binding digest. Recursive protected/scored-field rejection,
sensitive-content filtering, finite-JSON validation, identity and condition-lane
checks, no-follow metadata checks, and exclusive writes precede acceptance.
Identical replay reconciles without rewriting; conflicting, cross-plan,
symlinked, partial, or mutated state fails closed. Benchmark-infrastructure
failures remain unstaged so retry authority stays with the protocol.

### Result

Forty-seven synthetic staging tests and ninety combined planning/staging/freeze
tests pass; combined focused branch coverage is 83.63%, with 82% for the new
module. Cases cover all four conditions and all three repetitions, every binding
substitution, plan/order/public-input drift, protected and scored fields,
answered/refused/error consistency, condition-specific candidate transport,
boolean/integer ambiguity, opaque-authority forgery, path traversal, private
permissions, identical replay, conflict, noncanonical/tampered content,
symlinks, and partial directories.

The repository-wide gate passes 1,621 tests with five expected skips and 84.40%
branch coverage. Ruff, formatting, and diff checks pass. No real freeze, seed,
test generation, live service, credential, receipt, gold, protected outcome, or
score was accessed or created.

### Interpretation

The future dispatcher can now treat every attempt directory as a four-state
machine: absent, valid/complete, conflicting, or corrupt/incomplete. Only absence
is eligible for first execution; only an explicitly governed infrastructure
incident may authorize a rerun.

### Outcome

KEEP.

### Product implication

Durable agent evaluation needs atomic attempt state, not a best-effort collection
of sidecars. A single content-addressed envelope makes resume decisions local,
deterministic, and auditable.

### Next step

Build the separately production-authorized dispatcher adapters for C1-C3 and C4,
then finalize each complete 101-attempt cohort into one generation hash and one
Freeze-B-bound `SealedRunManifest`. Keep gold and scoring unreachable during the
entire generation phase.

## 2026-08-29 — D-096: Finalize sealed cohorts in schedule order

### Decision / experiment

Build the offline cohort aggregation and `SealedRunManifest` emission boundary
before adding live dispatcher authority. Change type: general evaluation
integrity. Bead: `omni-benchmark-ei0.5.4`.

### Hypothesis

If each condition/repetition cohort is recomputed from exactly 101 valid staged
attempts in committed schedule order and published through one atomic directory
rename, then completion order, partial writes, and stale artifacts cannot change
the generation hash or create an apparently complete run.

### Intervention

Added a cohort finalizer that verifies the exact question set, re-prepares and
reconciles each staged attempt, concatenates canonical generation records in
plan order, and derives start/finish timestamps from the records. It constructs
the run manifest from the matching Freeze-B condition, generation digest,
schedule/system/freeze identities, and explicit software/CLI versions.

The finalizer writes `generation.jsonl` and `run.json` into a fresh private
temporary directory and atomically renames the complete pair. Both files are
mode 0600 and the directory is mode 0700. Failed second writes remove the
temporary directory. Existing output is accepted without rewriting only when
both files match recomputed bytes; conflict, partial state, permission drift, or
symlinks fail closed.

### Result

Thirty cohort-finalization tests plus forty-nine staging tests pass. They cover
all twelve C1-C4 × repetition cohorts, exact 101-record order,
generation and run-manifest digests, question/plan/cohort drift, timestamp and
version validation, identical replay, conflict, partial output, protected-field
mutation, symlinks, permissions, unsafe roots, and cleanup after a synthetic
second-write failure. Focused finalization coverage is 87% branch coverage.

The repository-wide gate passes 1,653 tests with five expected skips and 84.45%
branch coverage. Ruff, formatting, and diff checks pass. No real freeze, seed,
test generation, live service, credential, receipt, gold, protected outcome, or
score was accessed or created.

### Interpretation

The sealed pipeline now has a deterministic offline path from validated Freeze B
through plan, per-attempt immutable state, and twelve batch-compatible run
manifests. Only the production-authorized condition adapters and top-level
orchestrator remain before a synthetic end-to-end dry run.

### Outcome

KEEP.

### Product implication

Final-run manifests should bind schedule-ordered content, not filesystem or job
completion order. Publishing a generation/manifest pair atomically makes the
meaning of “complete run” mechanically testable.

### Next step

Add the C1-C3 direct and C4 Omni sealed adapters behind one exact, single-use
production receipt and a top-level no-score orchestrator. Bind all loaded runtime
sources to frozen system `S`, preserve one-database-at-a-time isolation and hard
budget/wall controls, and exercise only synthetic/public dry runs until fresh
human authorization permits the real sealed launch.

## 2026-08-29 — D-097: Separate sealed production authority from C4 baseline authority

### Decision / experiment

Define the exact sealed-generation receipt before building the dispatcher.
Change type: general evaluation integrity. Bead: `omni-benchmark-ei0.5.5`.

### Hypothesis

If sealed generation requires a distinct single-use human response binding the
entire frozen plan, runtime, output, and resource policy, then earlier C4
baseline receipts or a generic approval cannot be replayed or broadened into
held-out execution authority.

### Intervention

Added strict validation and exclusive consumption for a canonical private sealed
production receipt. The binding fixes F/S, Freeze B, plan, schedule, runtime
source set, all four conditions, 1,212 attempts, run/output identity,
concurrency, wall bound, exact cost ceiling, and the hash of the complete policy.
The receipt must match the sole response on a closed human Beads decision, has a
maximum one-hour window, and can create only one consumption marker beneath an
ignored no-follow root.

### Result

Seventeen focused tests pass with 82% branch coverage. They cover current exact
approval, expiry/future and
overlong windows, every binding substitution class, boolean/integer ambiguity,
unsafe output paths, non-finite/extreme cost strings, unanswered or duplicate
responses, private/canonical/unique JSON, exclusive consumption, replay, and
symlink/path escape. No real receipt, human decision, consumption marker, live
call, test output, gold, or score was created.

The repository-wide gate passes 1,670 tests with five expected skips and 84.42%
branch coverage. Ruff, formatting, and diff checks pass.

### Interpretation

The final dispatcher can now have a narrower authority surface than either the
public baseline scheduler or the evaluator. Receipt validation remains
read-only; consumption is the single transition into authorized execution.

### Outcome

KEEP.

### Product implication

Production evaluation permissions should be capability-specific. Binding the
full resource policy as well as the target prevents an approval from silently
expanding concurrency, wall time, or cost.

### Next step

Build the synthetic-tested no-score orchestrator and condition adapters. Require
all runtime-source and plan preflight checks before consuming the receipt, and
consume it before constructing any live transport.

## 2026-08-29 — D-098: Gate sealed dispatch before adapter construction

### Decision / experiment

Implement the no-score dispatcher core against synthetic adapters before adding
any live condition transport. Change type: general evaluation integrity. Bead:
`omni-benchmark-ei0.5.5`.

### Hypothesis

If read-only preflight reconciles all planned state and validates the exact
runtime/plan/policy receipt before a single-use consumption transition, then no
receipt failure can create run state or contact an evaluated system. If the
executor reserves the complete pending cost and schedules at most one attempt
per database, bounded concurrency and restart safety can be proven independently
of provider behavior.

### Intervention

Added an immutable dispatch policy covering concurrency, wall clock, exact cost
ceiling, per-condition reservations, and software/CLI versions. Its canonical
hash is part of the human receipt. Runtime-source verification compares every
declared loaded source byte with the corresponding Git object at frozen system
commit `S` and hashes the ordered source manifest.

The read-only preflight re-prepares all 1,212 attempts from the frozen plan and
public questions, reconciles immutable staged envelopes, authenticates the exact
receipt, and returns a process-local capability. Execution rechecks that state,
admits the complete pending reservation before writing, consumes the receipt,
and only then constructs four adapters whose full condition identity must equal
Freeze B. A bounded worker pool allows at most one in-flight attempt per
database. Successful outputs stage before completion; infrastructure exceptions
remain unstaged and require a fresh receipt to resume. A complete run finalizes
all twelve cohorts. The module has no score or correctness interface.

### Result

Eight dispatcher tests pass. The synthetic end-to-end case executes all 1,212
C1-C4 attempts through fake adapters and emits twelve 101-record cohort/manifests.
Additional cases cover receipt/runtime substitution before writes, insufficient
cost admission before consumption, adapter-identity mismatch before calls,
wall-clock stop, receipt replay, infrastructure interruption plus fresh-receipt
resume, database isolation, concurrency bounds, and loaded-source substitution.

The dispatcher plus adjacent sealed-boundary suite passes 104 tests with 84.08%
dispatcher branch coverage. Ruff, formatting, and diff checks pass. No real
receipt was created or consumed, no provider was contacted, and no real test
generation, protected outcome, or score was accessed.

The repository-wide gate passes 1,678 tests with five expected skips and 84.42%
branch coverage.

### Interpretation

The orchestration state machine is now testable without importing a live
transport into its authority boundary. The remaining production work is to map
the already-frozen direct and Omni capture contracts into adapters, add a CLI
that defaults to read-only validation, and expand the runtime-source set to those
adapter dependencies before Freeze B.

### Outcome

KEEP.

### Product implication

An evaluation runner should treat authorization as a capability transition, not
as a boolean flag. Separating reconciliation from consumption makes both dry
validation and incident resume mechanically safe.

### Next step

Build synthetic-tested C1-C3 direct and C4 Omni adapters without weakening the
existing train/dev scope loaders. Then add the production CLI with a dry default,
an explicit execute acknowledgement, and the final exact runtime-source set.

## 2026-08-29 — D-099: Make sealed production command dry by default

### Decision / experiment

Add the final command boundary before concrete live adapters, leaving the
execute path deliberately unavailable until those adapters are compiled in.
Change type: general evaluation integrity. Bead: `omni-benchmark-ei0.5.5`.

### Hypothesis

If dispatch policy and public questions are reloaded from frozen Git objects and
the command defaults to the complete read-only preflight, operators can validate
the final package without consuming its receipt. Requiring both an explicit
execute acknowledgement and a concrete adapter builder prevents an incomplete
checkout from crossing the live boundary.

### Intervention

Added a strict canonical dispatch-policy loader. The policy file must be present
in Freeze B with the exact Git-object digest at `S`; dirty working-tree content
is ignored. Added a public-question loader that rechecks all 101 question texts,
database identities, and hashes against the 1,212-attempt plan and frozen public
manifest.

Added `sealed_tools/dispatch_sealed_generation.py`. It loads F/S, the plan,
public questions, and policy, then performs receipt-authenticated preflight and
prints only public hashes/counts. Without `--execute-sealed-generation` it cannot
consume the receipt. With that flag, the current script still fails closed before
consumption because concrete adapters are not yet installed. Both the CLI module
and entry script are now part of the runtime-source digest.

### Result

Thirty-three focused dispatch/CLI/plan tests pass at 84.46% combined branch
coverage. They include canonical committed-policy loading despite dirty
substitution, unfrozen/noncanonical rejection, exact frozen public-question
loading, dry-default behavior without adapter construction, and refusal of an
explicit execute when a builder is unavailable. Ruff and formatting checks pass.
No real receipt was consumed, no output root was created, and no provider was
contacted.

The repository-wide gate passes 1,683 tests with five expected skips and 84.40%
branch coverage.

### Interpretation

The operator-facing boundary now has a safe package-validation mode. The final
production-enabling change is mechanically narrow: provide exact direct/Omni
adapter factories and extend the frozen runtime-source list to their transitive
execution dependencies.

### Outcome

KEEP.

### Product implication

Dry-run should be the default semantics of production evaluation tooling, not a
separate best-effort command. The identical parser and preflight should guard
both inspection and execution.

### Next step

Implement sealed-only C1-C3 and C4 adapters over the existing capture contracts;
do not broaden ordinary development loaders. Then wire their builder into the
entry script and repeat the all-1,212 synthetic end-to-end gate.

## 2026-08-29 — D-100: Add C4 without widening development scope

### Decision / experiment

Implement the C4 half of the concrete adapter boundary independently, and track
the direct-SQL identity bridge separately. Change type: general evaluation
integrity. Beads: `omni-benchmark-ei0.5.5.2` (C4) and
`omni-benchmark-ei0.5.5.1` (direct bridge).

### Hypothesis

If a sealed-only adapter consumes `SealedPreparedAttempt` and projects the
existing Omni capture result after receipt consumption, C4 can reuse proven
telemetry and result capture without making the dev-A probe loader accept test.
Evaluated-system terminal failures should remain immutable generations, while
benchmark-infrastructure failures must remain unstaged.

### Intervention

Added `SealedOmniConditionAdapter`. Construction requires the exact frozen C4
identity, canonical dispatch policy, safe workspace/capture root, and a probe
runner. Each call creates a unique private ignored sidecar store, invokes the
runner, derives the C4 record through the existing Omni attempt projection, and
overlays only the exact sealed attempt/cohort plus `partition=test`. Provenance,
cost reservation, budget-policy hash, versions, and semantic identity come from
Freeze B and the dispatch policy.

The adapter accepts the supported Omni terminal job failure as an evaluated-
system outcome. Any transport/poll/contract class owned by benchmark
infrastructure raises before staging. Wrong condition, forged prepared authority,
wrong adapter identity, unsafe root, invalid runner/result, or runner exception
also fail closed. The adapter source is included in the runtime-source digest.

The existing direct runtime identity is intentionally restricted to train,
dev-A, and dev-B. Rather than change that human-controlled scope surface or label
test traffic as dev-A, child bead `omni-benchmark-ei0.5.5.1` now tracks a
parallel sealed-only direct identity/preparer.

### Result

Six focused C4 adapter tests pass with 88.37% branch coverage. They cover
successful staging-compatible test projection, evaluated-system failure,
unstaged infrastructure failure, private sidecars, wrong-condition rejection
before runner construction, invalid roots/runners/results/authorities, and
runner exceptions. No live runner, provider, credential, real receipt, test
generation, protected outcome, or score was used.

The repository-wide gate passes 1,689 tests with five expected skips and 84.45%
branch coverage. Ruff, formatting, and diff checks pass.

### Interpretation

C4's production runner can now be added as a dependency-injection closure over
the already-proven Omni preflight/capture path. Direct SQL needs one explicit
sealed identity type; treating that as a first-class boundary is safer than
relaxing or lying about the development scope.

### Outcome

KEEP.

### Product implication

Partition scope belongs in the execution authority, not merely in the published
record. Separate production adapters can share capture mechanics without sharing
or broadening their authorization types.

### Next step

Build the sealed direct identity/preparer under `ei0.5.5.1`, then implement the
production C4 probe-runner closure and final adapter-factory builder.

## 2026-08-29 — D-101: Give sealed direct execution its own authority type

### Decision / experiment

Add a parallel C1-C3 sealed runtime binding and opaque capture authority instead
of broadening the development-only direct identity. Change type: general
evaluation integrity. Bead: `omni-benchmark-ei0.5.5.1`.

### Hypothesis

If the sealed direct lane binds the exact public test question, plan, Freeze B,
schedule, system/control commits, condition context, database, model, and budget
before reusing direct capture mechanics, it can preserve the ordinary loader's
negative test-scope contract while producing staging-compatible generations.

### Intervention

Added `SealedDirectRuntimeBinding`, whose question scope is exactly `test` and
whose sealed authority includes the plan, Freeze-B, schedule, control-commit,
and condition-binding hashes. Added an HMAC-backed
`SealedDirectPreparedCapture` that exact-compares those identities with live
model, database, and public-tool transports. A sealed subclass reuses the
existing direct tool loop but revalidates the sealed authority at every runtime
boundary and emits its own canonical receipt; no ordinary direct parser or
development loader accepts test.

Added `SealedDirectConditionAdapter` for dispatcher compatibility. It creates a
unique private capture store after adapter construction, invokes an injected
post-receipt dependency factory, preserves evaluated-system refusal/error
outcomes, rejects benchmark-infrastructure failures before staging, and projects
only an unscored `partition=test` generation record. The module is now included
in the sealed runtime-source digest.

### Result

Fourteen focused tests pass; the module reaches 82% branch coverage in the full
gate. They cover all C1-C3
identities, dispatcher-compatible execution, answered staging, refusal,
evaluated-system error, infrastructure quarantine, receipt/artifact binding,
runtime substitution, invalid construction, and the unchanged ordinary
test-scope rejection. The hardened focused-plus-adjacent regression gate passes
67 tests. The repository-wide gate passes 1,703 tests with five expected skips
and 84.43% branch coverage. No provider, credential, real receipt, real test
generation, protected outcome, or score was accessed.

### Interpretation

The direct lane no longer needs either of the two unsafe shortcuts: labeling
test traffic as dev-A or widening a human-controlled development loader. The
remaining production step is dependency construction from exact frozen Git
inputs after receipt consumption.

### Outcome

KEEP.

### Product implication

Reusable execution mechanics do not require reusable authorization types.
Keeping the authority partition-specific makes an invalid scope transition
unrepresentable while retaining the mature capture loop.

### Next step

Build the production direct dependency factory and C4 probe-runner closure, wire
all four factories into the dry-default entry point, and expand the runtime
source set to every transitive production dependency before Freeze B.

## 2026-08-29 — D-102: Recover production paths from the frozen input spec

### Decision / experiment

Make the future `config/freeze-b-input.json` the sole source of production
adapter paths rather than hard-code or infer them in the dispatcher. Change
type: general evaluation integrity. Bead: `omni-benchmark-ei0.5.5.3.1`.

### Hypothesis

If the adapter builder reloads the input specification and every referenced
file from Git at system commit `S`, then exact configuration paths can be
recovered after receipt consumption without trusting dirty working-tree files or
duplicating path declarations outside Freeze B.

### Intervention

Added `load_sealed_runtime_inputs`. It reads the input specification and all
listed frozen files as Git blobs, requires the spec's complete frozen-path set
and each blob digest to equal Freeze B, regenerates all four ordered condition
identities with the recorder's strict parser, and exact-compares database
snapshot, PostgreSQL, libpq, Freeze-A, and system-commit identity. It returns an
immutable path record for each condition plus the snapshot path. Its public
summary exposes hashes/counts only. Dirty substitutions are ignored. The loader
is included in the sealed runtime-source digest.

### Result

Four focused tests pass with 82.71% branch coverage. They cover exact four-lane
recovery, dirty substitution immunity, condition/frozen-blob/database/commit/path
substitution, strict lookup, and public summary shape. No environment credential,
provider, receipt, test output, protected outcome, or score was accessed.

### Interpretation

The production builder can now be driven by the same committed provenance input
that created Freeze B. The remaining closures may load the returned paths with
the existing condition-specific parsers, but cannot silently choose a different
runtime or semantic artifact.

### Outcome

KEEP.

### Product implication

Provenance manifests are more useful when they preserve the route back to exact
inputs, not only their final digests. A separately frozen path specification
provides that route without putting mutable filesystem state in authority.

### Next step

Construct the direct runtime dependencies and C4 probe runner from these exact
paths, then wire the complete post-consumption adapter builder.

## 2026-08-29 — D-103: Scope direct production resources to one sealed capture

### Decision / experiment

Construct direct transports only inside a context manager owned by one sealed
adapter invocation. Change type: general evaluation integrity. Bead:
`omni-benchmark-ei0.5.5.3.2`.

### Hypothesis

If adapter factories remain inert until dispatcher approval has been consumed,
and every attempt owns its lease selection, private database environment,
ephemeral runtime directories, and live transports for exactly the duration of
capture, then dry validation cannot touch credentials and cleanup is guaranteed
on success or failure.

### Intervention

Added `SealedDirectProductionConfig` and
`build_sealed_direct_adapter_factory`. Configuration stores exactly three
distinct absolute Claude lease paths (one per preregistered repetition), an
external private per-database PostgreSQL environment directory, a private
runtime parent, frozen system/input identity, and a confined capture root. It
does not stat external resources during construction.

After sealed adapter execution begins, the capture context validates only the
selected repetition lease, reads one exact mode-0600 database environment,
loads the committed direct runtime/public context/database identities, compares
runtime policy and pinned CLI identity with Freeze B/dispatch policy, creates
fresh mode-0700 HOME/TMP/work directories, constructs the pinned Claude and
attested read-only PostgreSQL transports, and mints the opaque sealed capture
authority. The directories are removed when capture exits. The database
environment loader is narrow and local to the sealed factory, avoiding a broad
baseline-runtime dependency. The factory source is included in the sealed
runtime digest.

Also corrected the sealed direct provenance comparison: Freeze B's committed
prompt and harness hashes bind the public context components. The separate
hardcoded Claude system prompt remains bound by model identity plus frozen
runtime source; the two prompt concepts are no longer conflated.

### Result

Four factory tests pass at 87.88% branch coverage, and the fourteen sealed
direct adapter tests remain green. Tests prove pre-attempt inertness,
repetition-to-lease selection, runtime cleanup, construction ordering, frozen
path/CLI/condition rejection, exact private database-file modes/schema, and
external-path confinement. No real lease/database environment was inspected,
no transport contacted a provider, and no receipt/test output/protected
outcome/score was accessed.

### Interpretation

C1-C3 now have a complete production construction path whose first external
read occurs inside the post-consumption attempt context. The remaining adapter
work is the equivalent C4 runner and top-level four-condition builder.

### Outcome

KEEP.

### Product implication

Resource lifetime is part of evaluation provenance. Binding identities without
also bounding when credentials and temporary state exist leaves a meaningful
gap; a capture-owned context closes it.

### Next step

Implement the C4 production probe-runner closure against frozen specs and
verified deployment targets, then wire all four factories into the entry point.

## 2026-08-29 — D-104: Keep C4 construction provider-inert until execution

### Decision / experiment

Represent verified post-E02 deployment evidence as an explicit all-database
gate and construct the Omni client only inside one sealed C4 adapter invocation.
Change type: general evaluation integrity. Bead:
`omni-benchmark-ei0.5.5.3.3`.

### Hypothesis

If C4's public committed specifications and verified deployment identities are
validated while building the adapter factory, but environment authentication,
CLI execution, and provider construction remain deferred to `execute`, then
the sealed dispatcher can prove exact provenance before consuming a live
attempt without making dry validation provider-active.

### Intervention

Added `SealedOmniDeploymentTarget`, `SealedOmniDeploymentGate`,
`SealedOmniProductionConfig`, and `build_sealed_omni_adapter_factory`. The
factory reloads the exact C4 condition, prompt, and managed instructions from
Git at the frozen system commit. It exact-compares their hashes, provider,
managed model, model configuration, pinned Omni CLI, semantic-model bundle,
and deployment coverage with Freeze B and the dispatch policy.

Each executed attempt selects one explicit branch/model/semantic-model target
by public database, overlays that immutable target and the frozen budget on the
existing Omni environment, rechecks the observed pinned CLI, renders the
unchanged committed prompt, authenticates, and captures through the existing
Omni job contract. No mutable environment value may substitute for a target
identity. The factory source is included in the sealed runtime digest.

### Result

Nine focused tests pass at 88.76% branch coverage, and the adjacent sealed Omni
adapter tests remain green. Tests prove pre-execution provider inertness,
post-execution construction order, exact target overlays, deployment coverage,
malformed evidence rejection, frozen path/spec/CLI/condition rejection, and
settings/observed-CLI failures before client construction. No real Omni
environment, credential, provider, receipt, test output, protected outcome, or
score was accessed.

### Interpretation

C4 now has a fail-closed production runner with the same post-consumption
resource boundary as C1-C3. One top-level closure remains: parse the reviewed
post-E02 evidence into this immutable gate and wire all four factories into the
sealed CLI without widening pre-consumption activity.

### Outcome

KEEP.

### Product implication

Deployment identity is part of the evaluated system. Carrying it as an
explicit verified gate makes dry validation safe and prevents mutable account
state from silently selecting a different semantic model at run time.

### Next step

Implement the top-level adapter-factory builder, including the strict
deployment-evidence loader, and bind it to the sealed entry point.

## 2026-08-29 — D-105: Cross the production boundary only after receipt consumption

### Decision / experiment

Move the complete C1-C4 factory builder inside dispatcher execution after the
one-time approval marker is written, and freeze a separately verified C4
deployment gate. Change type: general evaluation integrity. Bead:
`omni-benchmark-ei0.5.5.3.4`.

### Hypothesis

If dry preflight never constructs production configuration, receipt consumption
precedes all exact runtime/deployment loading, and the C4 target map is itself a
frozen evidence graph, then the same entry point can be safe for both operator
inspection and eventual sealed execution without permitting mutable provider
state to choose an evaluated system.

### Intervention

Added `SealedProductionAdapterConfig`,
`load_sealed_omni_deployment_gate`, and
`build_sealed_production_adapter_factories`. The deployment loader reads a
canonical gate and every referenced schema-v2 verified deployment record from
Git at S, requires every path/digest to be in Freeze B, rejects protected
fields, binds one deployment run/source commit plus the aggregate semantic
identity, and requires exact sorted coverage of all scheduled C4 databases.

The dry-default CLI now accepts the frozen input/gate paths and three lease,
private database-environment, and runtime-parent paths needed for explicit
execution. It only parses those paths before receipt consumption. The dispatcher
then consumes the receipt before invoking the builder, which constructs the
three direct factories and one Omni factory. Factory failure produces no
provider call or generation and requires a fresh receipt.

Expanded the runtime-source binding from the sealed surface modules to all 69
entry-point and statically imported local source files, with a closure test that
fails if a future local import is omitted. A security pass also made direct
execution reject repository-internal, symlinked, non-owner, or non-0700 Claude
lease and runtime-parent directories before transport construction. The
synthetic sealed-plan fixture now uses database names valid under the production
PostgreSQL identity grammar.

### Result

The real production builder and real C1-C4 adapters completed all 1,212
synthetic attempts, staged no scores, and finalized all twelve 101-record
cohorts; only the terminal provider/capture boundaries were synthetic. The
production-factory module passes six focused tests at 82.70% branch coverage.
The full repository gate passes 1,730 tests with five expected environment
skips at 84.45% branch coverage. Ruff, format, and diff checks pass. No real
receipt, provider, credential, protected outcome, gold, test annotation, or
sealed correctness value was accessed.

### Interpretation

The sealed no-score generation path is now production-wired without weakening
its dry mode or custody boundary. Remaining work is operational, not adapter
implementation: finish/freeze the public baseline and E02 candidate, create the
actual final deployment gate and Freeze B under their human controls, then use
the separately authorized sealed run.

### Outcome

KEEP.

### Product implication

A production command can be inspectable by default and still exact at execution
when its live dependency graph is a post-consumption function of frozen public
evidence rather than ambient account state.

### Next step

Close the adapter-wiring beads, update the shared frontier, and return to the
human-authorized public C4/final-candidate sequence without launching either
from this offline implementation lane.

## 2026-08-29 — D-106: Close the C4 completion-to-score handoff offline

### Pre-change hypothesis and boundary

The exact public C4 v4 dispatcher writes one immutable generation and run
manifest per attempt, but the completed direct-baseline scorer accepts only the
C1--C3 continuation freeze. A deterministic C4 freezer should be able to
reconcile the complete committed 129-attempt arm, bind its full private-file
inventory plus approval identities, and produce a canonical selection without
reading correctness. The dev-A scorer must then consume C4's hash-bound typed
governed-result sidecar rather than misclassifying the intentionally absent
`generated_sql` as `no_query`.

Bead `omni-benchmark-ei0.4.8`; change class: general evaluation integration.
Implementation is provider-inert and uses only synthetic fixtures and public
membership/schema metadata. It may not launch C4, inspect a v4 result, consume
an approval, access credentials or leases, or read dev-B/test/protected labels.

### Result

The new freezer derives the exact committed C4 schedule, requires 129 attempts
across ten databases and the separately bound schedule, execution-plan, and
deployment hashes, reconciles every generation/run manifest at its source
commit, rejects quarantined/incomplete/cross-run/unexpected/symlinked/scored
trees, hashes the complete allowed sidecar inventory, and writes one canonical
mode-0600 non-overwriting selection. Its CLI prints counts and hashes only.

The generalized scorer preserves the existing direct-selection default and
adds an explicit confined C4 selection. It verifies every C4 result path,
schema, generation binding, and SHA-256 before parsing the dev-A release. Typed
rows are decoded through the existing Omni result contract and compared against
a freshly executed gold query without fabricating SQL or re-executing the
evaluated system. Only the exact product terminal failure is mapped to the
closed candidate-execution category; benchmark-infrastructure generations are
rejected. Precomputed scoring refuses any case with preprocess or cleanup SQL
before database acquisition. An explicit artifact workspace keeps the frozen
C4 selection and outputs in the isolated C4 worktree while the train-only
release remains in its existing custody workspace; scoring verifies both git
roots and reads each artifact in place, so neither private release copying nor
an ad hoc C4 artifact transfer is required. Public aggregate verification finds 85 dev-A
questions in the 129-question C4 arm and zero nonempty preprocess or cleanup
sequences, so the exact arm satisfies that invariant.

Focused freeze/custody/scoring coverage passes 54 tests. The complete isolated
gate passes 1,757 tests with five expected environment/source skips and 84.17%
branch coverage; repository Ruff, formatting, and diff checks pass. Running the
exact v4 freeze command while v4 remains absent returned only
`C4 baseline schedule is incomplete`, exit status 1, and left the destination
absent. No provider, approval, credential, protected record, or live artifact
was accessed.

### Outcome

KEEP. After an authorized v4 dispatch completes, the agent can freeze it with:

```bash
cd /tmp/omni-benchmark-c4-postrun && uv run python scripts/freeze_c4_baseline.py --workspace /tmp/omni-benchmark-c4-prerequisites-integrated --system-commit ae08ec8a1d76111302af8af6d04ad73dc64ff8e6 --run-id public-c4-baseline-v4 --output-root experiments/autoresearch/raw/public-c4-baseline-v4 --destination experiments/autoresearch/state/public-c4-baseline-v4-freeze.json --expected-schedule-sha256 b58485722980f292180d3a3a8c956dc6bad37583e494dcc580ea49ac7338442d --expected-execution-plan-sha256 5fab1f6967fc9e877aa333eaccd2ca9760f42646c93ad627d99b6b7c6da3d221 --expected-deployment-sha256 d805eb6869201f28f928a5774263062302b29a5d8786fc3c1c120cb27f19df80
```

The exact 85-question dev-A intersection can then use the existing dual-scorer
CLI with the returned selection SHA-256 and expected official/sensitivity
denominators 85/85. This implementation does not authorize or launch v4, E02,
a dev-B checkpoint, Freeze B, or sealed evaluation.

## 2026-08-29 — D-107: Close the E02 full-dev-A execution handoff offline

### Pre-change hypothesis and boundary

The E02 relationship candidate is reproducible and locally deployment-ready,
but reproducibility alone is not an executable experiment. The production
deployment command currently snapshots only the frozen baseline bundle roots,
and the receipt-gated C4 scheduler currently selects only the 129-question
public baseline arm. A distinct provider-inert handoff should reproduce all 18
E02 deployment plans from exact Git objects, schedule exactly the committed 154
dev-A IDs under C4, require fresh human authority at each live boundary, and
freeze/score the resulting complete arm without copying the train-only release.

Bead `omni-benchmark-ei0.4.9`; change class: general evaluation integration.
RED tests precede each implementation slice. This work may use public committed
inputs and synthetic fixtures only. It may not create or consume a real
approval, contact Omni, access credentials or leases, inspect protected
records, launch C4/E02, or read a live experiment artifact.

### Result

The test-first implementation adds an exact committed dev-A C4 schedule and
reproduces the 18-database, 272-file, 91-relationship E02 candidate set from an
exact canonical Git commit. The reproduced candidate-set SHA-256 is
`c08ee8c10e4b2c26a142da5f36971dbb19488a827febf0514f5876e75b3a6f61`, matching
the previously frozen offline validation. Archive extraction is bounded and
rejects non-file members, traversal, oversized members, noncanonical commits,
and incomplete database coverage.

The new E02 preparation command is dry by default. It requires the exact
mode-0600 public C4 freeze and its expected SHA-256 before it will even print a
plan, binds that freeze into the plan identity, and requires a separate current
human receipt before deployment construction. Its 18 models and branches use
candidate-specific identities rather than mutating the public-baseline
resources. The subsequent generation mode schedules exactly 154 committed
dev-A IDs under C4, requires a second one-time receipt, binds the verified
deployment evidence to the exact E02 system commit, and retains the existing
wall-clock stop with C4 cost as telemetry rather than an operational abort.

The C4 freezer now has an explicit nondefault `e02-dev-a` schedule kind. It
requires exactly 154 attempts across 18 databases and emits a distinct frozen
selection kind that the existing dual scorer accepts through the already
separate artifact and gold-custody workspaces. The public 129-attempt C4 and all
sealed defaults are unchanged.

Focused E02, deployment, batch, freeze, scoring, and sealed regressions pass 148
tests. The full repository gate passes 1,775 tests with five expected
environment/source skips and 84.14% branch coverage. Ruff, formatting, and diff
checks pass.

### Outcome

KEEP. No live action occurred. Public C4 must complete and freeze first, after
which E02 deployment and E02 generation each require a new exact human receipt.
The exact full-154 scoreable denominators are intentionally not guessed from
the prior 140-question direct arm; a custody-safe aggregate conformance step or
equivalent human-controlled evidence remains necessary before final E02 score
publication. This implementation does not change that scoring definition.

## 2026-08-29 — D-108: Prepare aggregate-only full-dev-A gold conformance

### Pre-change hypothesis and boundary

The prior direct score receipt freezes gold eligibility for only 140 represented
dev-A questions, so its 122 official / 121 sensitivity denominators cannot be
assumed for E02's complete 154-question arm. The already human-approved frozen
eligibility rule can be applied in a distinct, explicit custody command before
candidate correctness execution, publishing only an immutable aggregate receipt
that the final scorer authenticates.

Bead `omni-benchmark-ei0.4.9.1`; change class: evaluation custody integration.
Implementation and tests may use synthetic fixtures only. This preparation may
not open the real release, acquire PostgreSQL, read a candidate artifact, run
E02, or expose a question identity, SQL string, row value, per-question status,
hidden annotation, or correctness result.

### Result

The new command requires explicit execution acknowledgement, the exact Freeze A
commit, the expected 154-record release SHA-256, both in-memory scorer DSNs, and
the pinned PostgreSQL version. It validates exact committed dev-A membership,
executes the same frozen sentinel conformance rule under both scorers, and writes
one canonical mode-0600 non-overwriting receipt in the confined state directory.
The receipt contains only input hashes, scorer identities, total scoreable and
unscorable counts, and aggregate totals for the already closed gold-failure
categories. It contains no IDs, SQL, result rows, or candidate evidence.

The complete E02 scorer can now authenticate that receipt against its own
Freeze-A, release, and dev-A-manifest bindings. It recomputes conformance and
compares the receipt-bound denominators before executing any candidate; a drift
or mismatch aborts before candidate scoring. Existing explicit-denominator
commands and direct, public-C4, and sealed defaults remain available and
unchanged.

Focused gold-conformance/E02/freeze/scoring/sealed coverage passes 155 tests.
The full repository gate passes 1,782 tests with five expected
environment/source skips and 84.06% branch coverage. Ruff, formatting, and diff
checks pass. No protected or live input was opened.

### Outcome

KEEP. The real aggregate sweep remains unexecuted and will be documented as a
separate custody action; preparing this command does not authorize E02
deployment or generation.

## 2026-08-29 — D-109: Close the sealed score-publication boundary

### Pre-change hypothesis and boundary

The final generation control plane can prove all 1,212 outputs complete, but the
repository has no production caller for the in-memory sealed batch scorer. If a
new custody entry point first authenticates Freeze B and all twelve immutable
cohorts, only then opens an exact 101-record test release, freezes scorer-specific
gold eligibility, and publishes private labels plus a separate identity-free
aggregate receipt, the held-out report can be completed without exposing sealed
correctness or weakening the generate-then-score gate.

This is a general evaluation-integrity intervention under
`omni-benchmark-ei0.6`. Development and tests use synthetic/public fixtures only.
No test gold, test annotation, dev-B outcome, live generation artifact,
credential, provider, or sealed correctness result may be opened or executed.
The previously authorized coverage-limited gold-conformance rule and the
preregistered endpoint definitions are inputs, not surfaces this change may
revise.

### Intervention

Added a dry-default final evaluator that authenticates the exact clean F/S
Freeze-B control checkout, the committed 1,212-attempt plan, and all twelve
private finalized cohorts before opening any release or constructing a database
provider. Added a separate explicit custody extractor that projects only the 101
frozen test records from the externally held source, verifies the expected source
hash before publication, normalizes the attachment's homogeneous integer
`external_knowledge` arrays to the existing string release contract, and refuses
overwrite or any noncanonical private destination.

Inside custody, the evaluator exact-loads the canonical 101-record release from
one already verified byte snapshot, freezes mode/question gold eligibility under
the human-approved coverage-limited rule, and executes each eligible candidate
once under both frozen scorers. It atomically publishes 24 private cohort score
artifacts, two identity-free aggregates, and one correctness-free receipt. The
aggregates implement the preregistered deterministic 10,000-replicate question-clustered
percentile intervals, primary and rung contrasts, repetition-one McNemar/Holm
sensitivity, per-run and pass^3 reliability, flips, outcome rates, and raw
terminal classes. Content-refusal versus insufficient-context subtype rates are
explicitly unavailable because that distinction is not retained in the frozen
generation contract; no subtype is inferred after the fact.

A security pass replaced ordinary final-directory rename with Linux
`renameat2(RENAME_NOREPLACE)`, preventing a raced empty destination from being
silently replaced. Paths are allowlisted and symlink-confined, all private files
are owner-only/single-link, credentials remain environment-only, operator output
contains hashes/counts only, and unexpected errors cross a sanitized no-traceback
boundary.

### Result

RED tests preceded each layer. The focused custody/scoring suite passes 83 tests;
the post-security affected suite passes 12 tests. The full repository gate passes
1,793 tests with five expected environment/source skips at 83.63% branch
coverage. Ruff, formatting, and diff checks pass. No test gold, test annotation,
dev-B outcome, live generation artifact, credential, provider, or sealed
correctness result was accessed.

### Outcome

KEEP. Production sealed scoring is now mechanically ready but remains unrun. It
does not authorize C4, Freeze B, a sealed dispatch, the held-out release, or
scoring; those actions remain behind their existing fresh human gates.

## 2026-08-29 — D-110: Prepare deterministic aggregate-only report rendering

### Pre-change hypothesis and boundary

The production scorer emits two identity-free aggregate artifacts, but the
standalone results report still requires manual numeric transcription. If one
dry-default command validates the complete official and sensitivity aggregate
envelopes, their shared custody bindings, exact frozen scorer identities, and
absence of protected or question-level fields before rendering a new immutable
Markdown fragment, then final reporting can be faster and less error-prone
without opening score artifacts or exposing per-question correctness.

Bead `omni-benchmark-zjp.1`; change class: evaluation reporting integration.
Tests and development use synthetic aggregate fixtures only. This work may not
open real sealed outputs, infer unavailable refusal subtypes, modify
`RESULTS.md`, contact a provider, access a database, or authorize any live or
custody action. The destination must be confined, owner-only, and
non-overwriting.

### Intervention

Added a fixed-field renderer for the two scorer-produced aggregate envelopes.
It authenticates the scorer-emitted SHA-256 of each mode-0600 source, requires
their Freeze-B, plan, release, and test-manifest bindings to agree, validates
the exact official and sensitivity scorer identities and complete aggregate
schemas, recomputes count/rate consistency, and rejects protected keys or
non-finite values recursively. Only preregistered aggregate fields enter the
Markdown template; arbitrary input strings are never interpolated.

The explicit command traverses private input paths with descriptor-relative
`O_NOFOLLOW` opens and inode/owner/mode/link/size checks. It publishes only to a
gitignored raw-run root through the hardened artifact store, producing a new
mode-0600 non-overwriting Markdown fragment. The fragment reports both scorers,
primary endpoints, condition summaries, paired contrasts, and the fixed
bootstrap method, while marking the two unobservable refusal subtypes as
unavailable. It does not modify `RESULTS.md`; narrative interpretation remains
a reviewed post-score step.

### Result

RED tests preceded the renderer, strict schema/count validation, ancestor-
symlink defense, aggregate-hash binding, explicit CLI, and sanitized error
boundary. The focused scorer/report integration gate passes 34 tests with
81.19% branch coverage for the new module. The full repository gate passes
1,816 tests with five expected environment/source skips and 83.58% branch
coverage. Repository-wide Ruff, formatting, CLI-help, and diff checks pass.
No real aggregate, score artifact, test label, dev-B outcome, database,
credential, provider, or live service was accessed.

### Outcome

KEEP. The final numeric transcription step is now deterministic and bound to
the exact sealed scoring handoff. This preparation does not authorize C4,
Freeze B, sealed generation, test release, scoring, or publication of the
result narrative; all existing human and custody gates remain in force.

## 2026-08-29 — D-111: Dispatch the exact authorized public C4 v4 baseline

### Pre-launch hypothesis and boundary

The bounded HTTP-429 retry added at exact system commit
`ae08ec8a1d76111302af8af6d04ad73dc64ff8e6` should allow the committed
129-attempt, ten-deployment public C4 arm to complete without changing its
semantic content, run identity, schedule, or execution plan. This run is needed
to freeze the governed development baseline before the separately authorized
E02 experiment.

Human decision `omni-benchmark-ei0.4.2.4` supplied the exact one-hour v4
receipt at 2026-08-29T12:05:28Z. Its file SHA-256 is
`04d7c29f2f1fe481f3f41c6a605c08e286292c004b1ae350d0fdf1c38cc2523f`.
Before launch, the receipt and byte-identical Beads response validate; the
system branch and commit match; the v4 output and consumption identities are
absent; and no competing C4 process exists. The authorized policy is concurrency
three, a 21,600-second wall bound that finishes started database-condition
blocks, a USD 7 per-attempt reservation, and a USD 560 telemetry ceiling.

This is one public-only dispatch. It may consume only that receipt and write
only the exact v4 run root. It may not access train gold, dev-B, test/sealed
data, correctness, or hidden annotations; touch credentials or Claude leases;
reuse a prior identity; rerun an attempt because of its answer; push; or mutate
the dirty main worktree beyond this contemporaneous log. Any infrastructure
failure remains governed by the preregistered rerun policy.

### Result and infrastructure adjudication

The exact receipt was consumed once. All three initially scheduled children
then exited before any evaluated answer because `OMNI_BASE_URL` was absent from
the inherited launch environment. Their sanitized failure sidecars share stderr
SHA-256
`db346d56108e1a2fcad01409cd9b8fe3d266bf3b7b3e1cfa5a35e6f85070f4ad`.
The v4 root contains exactly three mode-0600 failure records, zero generation
records, and zero correctness records; no process or staging directory remains.
No OAuth call, protected-label access, correctness inspection, or answer-based
decision occurred.

This is a mechanically demonstrated benchmark-infrastructure failure outside
the evaluated system. V4 is therefore incomplete and non-scoreable, but its
receipt and run identity remain spent and may not be reused. The three failure
file SHA-256 values are
`0f2fa826cac99a11b9a3b43a53c7ec68c5579b3c13a480f8b826d979ee65d4b0`,
`b419658c5207409dd55e1e011860069c289902f78bb6ec8d6252c2ab6fdb311d`,
and `6d036d424da3d11245f55d8a0302191002842496cfd877e5d34de699642965c8`.

### Preventive fix and outcome

TDD reproduced the sequencing defect: with a syntactically absent Omni
environment and a nominal receipt path, the live entry point reached approval
validation instead of failing environment preflight. Local commit
`e439b183a26a5d722a3317a7f89c650c8205ddb6` adds v4 to the closed quarantine
registry, binds the spent consumption marker and all three diagnostics, and
reuses the frozen `OmniCliSettings` validator before receipt validation or
consumption. The preflight checks the HTTPS origin and exactly one authentication
mode without opening or validating OAuth credentials and without making a
network request.

Focused gates pass 21 tests. The full repository gate passes 1,454 tests with
five expected skips and 84.34% branch coverage; Ruff, formatting, and diff checks
pass. Security review found no credential exposure, broader environment
inheritance, or new network behavior. Outcome: DISCARD v4 as score evidence;
KEEP its quarantine and the general pre-consumption preflight repair.

### Fresh no-launch v5 package

The provider-inert v5 dry run from exact commit `e439b18` resolves the same 129
public attempts and ten deployment targets with `live_execution=not_started`.
Run `public-c4-baseline-v5` binds schedule SHA-256
`2b8108874603fe6a372b1cc137d642623f31b985ff1d9d2a25e368e522793190`,
execution-plan SHA-256
`2d03cd2357dba1fb8c00aa4716286bb6d2501538df0ea0a775d8f0249ed8b3b0`,
and unchanged semantic-deployment SHA-256
`d805eb6869201f28f928a5774263062302b29a5d8786fc3c1c120cb27f19df80`.
Human decision `omni-benchmark-aez.7.1` is open. The mode-0600 exact helper has
SHA-256
`9a2502c0a81e48c556934d0419eca407aac76e1e4c3007aee7599badf96bfc3c`
and twice reports `ready_not_authorized_not_launched` after recomputing all
bindings and syntactically validating the recorded non-secret launch origin and
profile. No receipt, consumption marker, v5 output, Omni request, credential
action, or replacement dispatch exists.

## 2026-08-29 — D-112: Unify the C4 preflight repair with sealed readiness

### Integration hypothesis and boundary

The exact C4 v4 quarantine and pre-consumption environment preflight can be
replayed onto the complete E02, Freeze-B, sealed-dispatch, sealed-scoring, and
aggregate-report lineage without weakening either side. This is an offline
control-plane integration under Bead `omni-benchmark-ei0.7`; it may not create
or consume a receipt, contact a provider, inspect credentials or protected
labels, run scoring, mutate leases, or push.

### Result

Clean branch `codex/mvp-sealed-integrated` descends from sealed report commit
`301d45fdf808384708811220b436b904e48e57be`. Patch-equivalent commit `db7faae`
adds the exact v4 quarantine plus required Omni environment validation before
approval validation or consumption. The integration cherry-pick was conflict
free.

The first full gate correctly exposed five freezer-fixture failures: synthetic
success tests reused the now-real quarantined v4 run ID. Production behavior
was correct; the tests were coupled to a production identity. The fixture now
uses dedicated non-production ID `public-c4-baseline-freeze-test`, while the
explicit quarantine test retains real v3. This prevents future production
quarantines from changing unrelated freezer tests.

The focused cross-lineage gate passes 208 tests. After the fixture correction,
the C4 freezer/quarantine gate passes 24 tests and the full repository gate
passes 1,818 tests with five expected environment/source skips and 83.59%
branch coverage. Ruff, formatting, and diff checks pass. No live, credential,
receipt, gold, dev-B/test-label, correctness, lease, or push action occurred.

### Outcome

KEEP. One clean local lineage now contains the current report, E02 candidate,
C4 post-run path, Freeze B, sealed dispatch and scoring custody, aggregate
renderer, v4 quarantine, and the pre-consumption environment guard. The branch
does not authorize v5 or any sealed action; fresh human and custody gates remain
mandatory.

## 2026-08-29 — D-113: Prepare an exact fail-closed v5 runner

### Pre-change hypothesis and boundary

The v4 incident showed that a correct authorization helper is insufficient if
the later launch is reconstructed manually from ambient shell state. A separate
runner can eliminate that seam by recomputing every public/provider-inert v5
binding, requiring the canonical private receipt, supplying the exact recorded
non-secret Omni origin/profile through a minimal child environment, and invoking
only a fixed argv. Default mode must remain incapable of consumption or launch.
Bead `omni-benchmark-aez.8`; no provider, OAuth validation/mutation, protected
label, receipt, dispatcher, or push action is permitted during preparation.

### Result

Mode-0600 runner
`/home/ds/.omni-benchmark-approvals/launch_public_c4_baseline_v5.py` has SHA-256
`ef673e9c9ecbe219ff9aef52e496ba44b4a260b99db0723e058428c9a1e3f3cc`.
It requires the exact branch/commit, clean tracked state plus the three known
prior consumption markers, absent v5 output/consumption, no exact v5 process,
recomputed 129-attempt schedule/plan/deployment bindings, a mode-0600
single-link receipt authenticated by the exact Beads response, and syntactically
valid fixed profile settings. It accepts no token or binding argument. The child
environment drops any ambient `OMNI_API_TOKEN`, and execution uses a tuple argv
with no shell.

RED began with the absent module. The initial 21-test suite covered default
non-launch, missing/consumed/unsafe receipts, exact decision and binding checks,
process matching, sanitized failures, token exclusion, and exact subprocess
arguments at 82.16% branch-aware coverage. A final cross-directory rehearsal
then exposed that caller-selected `uv` could import main's older package before
the runner changed directory. A subprocess regression reproduced it, and the
runner now prepends the exact C4 worktree source path before any project import.
The final 22 tests pass at 82.96% branch-aware coverage; Ruff and formatting
pass. Provider-inert invocations from both main and the C4 worktree report
`waiting_for_human_receipt_not_launched`; receipt, consumption, and output remain
absent. Security review found no embedded credential, secret-bearing argument,
shell expansion, token forwarding, or sensitive error output.

### Outcome

KEEP. After the human creates and pastes the exact v5 receipt, the agent can use
one reviewed command surface instead of reconstructing launch state. The runner
does not expand human authority: `--execute` still fails without the fresh
authenticated receipt, and approval consumption remains inside the frozen
production gate before dispatcher construction.

## 2026-08-29 — D-114: Promote the immutable direct-baseline freeze into the final lineage

### Pre-integration hypothesis and boundary

The 112-preserved plus 518-continuation direct baseline was already complete,
content-addressed, and frozen before the train-only release, but its tested
freezer remained uncommitted in the dedicated isolated worktree. Promoting that
implementation and only its exact schedule/refusal prerequisites into the clean
MVP lineage should make the public-baseline evidence reproducible without
regenerating an attempt or importing deferred comparator experiments.

Beads `omni-benchmark-dih.5.4.2.4.4.2.2.5` and
`omni-benchmark-ei0.8`; generality: evaluation provenance. This step may inspect
public code, Git objects, aggregate counts, and hashes. It may not open run
answers or correctness, regenerate the frozen baseline, access protected labels,
contact a provider, inspect or mutate credentials or leases, consume a receipt,
launch C4, or push.

### Result

The stranded four-file implementation was reviewed and committed in its clean
worktree as `615fd4c912fa51b2e58b0dd358df34e30fd24864`. Fresh isolated gates
passed 17 focused tests at 81.37% branch-aware module coverage and 1,424 full
tests with five expected skips at 84.45%; Ruff, formatting, and diff checks
passed. The existing mode-0600 freeze artifact was not rewritten and remains
SHA-256 `04c75eb40c6a8bbb59af07358733b59a10d9b28787443d622fae5f31887bd725`.

The first final-lineage compatibility gate failed closed because the sealed
branch forked before commit `5be315e`, which supplies the committed exclusion
loader used to derive the exact 630-attempt schedule. Rather than merge the
unrelated C1-sensitivity side branch, the final lineage now carries the exact
historical exclusion/refusal patch in `b737f80` after freezer promotion
`e1d17ac`. Conflict resolution preserved both the later C4 schedule controls and
the earlier direct exclusion identity. Three historical test expectations were
updated to the later contract: evaluated-system refusals retain
`no_answer_insufficient_context`, set `failure_origin=evaluated_system`, and do
not populate `harness_failure`. The exact script entrypoint and its red/green
test were added in `cbc69ec`.

Clean branch `codex/mvp-sealed-integrated` now ends at
`cbc69ecced83f6c15abf384c9ce94b01d5f8e27f`. The final focused cross-lineage
gate passed 283 tests; the complete gate passed 1,843 tests with five expected
environment skips and 83.51% branch coverage. Repository-wide Ruff, formatting,
diff, CLI-help, and clean-status checks passed. Code/security review found no
credential, provider, shell-expansion, path-escape, overwrite, or protected-data
path in the freezer.

### Outcome

KEEP. The clean final MVP lineage now contains the immutable direct-baseline
freeze mechanism as well as the previously unified report, C4/E02 path, Freeze
B, sealed generation, scoring custody, and report renderer. A later independent
coverage audit opened `omni-benchmark-wk0`, which now blocks v5 until the human
fixes the pre-result dev-A frame. The provider-inert v5 runner still reports
`waiting_for_human_receipt_not_launched`; v5 receipt, output, and consumption
remain absent. No live, protected, credential, lease, or remote action occurred.

## 2026-08-29 — D-115: Preserve bounded public validator diagnostics before retry

### Pre-change hypothesis and boundary

The v6 public semantic deployment preserved stable issue counts for eight
databases, but discarded the product validator payloads needed to distinguish
general compiler defects from representability limits. If a read-only,
dry-default diagnostic command authenticates the committed v6 deployment
records and their exact bundle manifests before requesting validation, then
stores a bounded and recursively secret-rejecting copy in a new append-only
artifact, the remaining all-18 deployment work can be classified without
re-uploading models or using benchmark outcomes.

This is a general deployment-observability intervention under Bead
`omni-benchmark-dih.17.4`. Implementation and tests are provider-inert and use
synthetic validator responses. The command may not upload YAML, create or modify
models or branches, inspect or repair credentials, use questions, gold, hidden
annotations, dev-B/test outcomes, or correctness, and it may not launch C4.

### Intervention

Added a narrow validator-only product boundary and a dry-default command that
requires an explicit database list. Before constructing the client it loads each
exact v6 append-only failure record, requires the failed-validation schema and
positive prior issue count, verifies its source commit and manifest against a
Git-archived committed bundle plan, and atomically claims a new diagnostic run.
It never exposes upload, create-model, create-branch, readback, question, or
scoring operations.

Each response is recursively checked for protected and secret-bearing keys,
common credential-shaped values, JSON type safety, finite numbers, bounded
depth/node/string/issue/payload sizes, and then written mode 0600 with
`O_EXCL|O_NOFOLLOW`. Records bind the source record SHA-256, commit, manifest,
model/branch identity, old and observed issue counts, and a canonical issue
digest. Unsafe payloads and product failures produce content-free terminal
records; count drift is retained but cannot pass as a captured diagnostic.

### Offline result

All 18 committed bundle plans build with zero preflight failures. Their manifest
hashes exactly match the v6 records, and the semantic tree is byte-unchanged from
v6 source `7c669e5`. The compiler/regeneration/readback gate passes 175 tests at
85.08% scoped branch coverage. The full repository gate passes 1,859 tests with
five expected source/environment skips at 83.50% branch coverage; Ruff,
formatting, command-help, and diff checks pass. Security review found no
credential argument/output path, mutation method, protected-field path, or
high-severity issue. No provider, profile, credential, lease, question, gold,
hidden annotation, correctness result, or C4 action was accessed.

### Outcome

KEEP the diagnostic boundary. Its live execution remains a separate read-only
public deployment observation and has not occurred in this implementation
step. The v5 C4 runner remains blocked by `omni-benchmark-wk0` and untouched.

The first production-path invocation failed closed before client construction:
the immutable v6 records are deployment schema v1, while the initial loader
accepted only the current v2 writer schema. No diagnostic claim, output, profile
access, or provider request occurred. A red regression using a v1 source record
preceded widening the loader to the two explicit supported public deployment
schemas; all other identity and manifest checks remain unchanged.

### Live read-only result

The corrected command authenticated all eight v6 failures and issued exactly
one validator-only request per existing branch at a 1.25-second global minimum
interval. All eight issue counts reproduced exactly, 86/86 total, with no
drift: 13 `table_not_found`, 50 `column_not_found`, 17 `unparseable_sql`, four
`invalid_types_for_function`, and two `unexpected_validation_error`. The nine
mode-0600 append-only files under
`experiments/deployments/public-validator-diagnostics-v1/` have deterministic
aggregate SHA-256
`3d5dc0cffcc1c1fc754a51d3f80233bebb705501d1738f2f4f163a7ae2eef2da`.

The evidence separates five mechanisms. Mental-health and organ-transplant
report 13 missing tables, consistent with the operator-owned restore blocker
`omni-benchmark-2j9`; they are not compiler work. Polar and sports report 17
failures caused by emitted `DO NOT PARSE` markers. Solar and virtual-idol report
50 unresolved physical/semantic field bindings, with one additional solar
type error. Robot reports three string/numeric division errors. Planets reports
two product decimal-scale validation errors. These are public schema/model
diagnostics only; no question, gold, hidden annotation, correctness result,
model upload, branch/model creation, credential repair, lease mutation, or C4
action occurred.

The next compiler slice is therefore general and evidence-driven: remove
product-invalid parser markers without weakening local SQL admission, finish
explicit source bindings for fields that are not actual physical columns, and
make derived numeric expressions type-aware or explicitly unrepresentable.

## 2026-08-29 — D-116: Compile structured-leaf bindings from public schema paths

### Pre-change hypothesis and boundary

All 50 `column_not_found` diagnostics come from physical fields bound to public
`structured_leaf` records whose bundle specs omit authored SQL. The compiler
only synthesized SQL for whole physical columns, so Omni interpreted each
semantic name as a nonexistent base column. If the same general compiler derives
a PostgreSQL JSON traversal mechanically from the authenticated leaf path and
its owning column, those fields should become real source-bound dimensions
without database- or question-specific rules.

This is a mechanical public-schema compiler correction under Bead
`omni-benchmark-dih.17.3`. It uses only structured leaf `path` records already
in the committed public IR. It may not infer paths from validator strings,
change mappings, use questions/gold/hidden outcomes, or weaken SQL admission.

### Intervention and offline result

The compiler now emits a `${normalized_source_column}` JSON traversal for an
unauthored structured leaf. Intermediate object/array segments use `->`; the
terminal segment uses `->>`. Object keys are SQL-quoted, array indices are
non-negative integers, segment shapes are validated, and the synthesized scalar
must pass the same field-reference allowlist and PostgreSQL parser as authored
SQL. Authored structured expressions remain unchanged.

Exactly the affected 25 solar and 25 virtual-idol fields regenerated; no other
bundle spec contains an unauthored structured-leaf physical field. The focused
compiler/regeneration/deployment gate passes 163 tests at 85.47% branch
coverage; Ruff and diff checks pass after formatting. Live validation and
readback remain a separate append-only deployment step.

## 2026-08-29 — D-117: Retain the all-154 dev-A promotion frame

### Pre-result decision boundary

Before any C4 result existed, the human selected option B on
`omni-benchmark-wk0`: retain the preregistered requirement that a promotable
intervention be evaluable on all 154 dev-A questions. This is a human-controlled
scoring-frame decision, not an optimization chosen after observing an outcome.
No C4 receipt was consumed and no C4 dispatch, score, provider request, hidden
annotation, dev-B outcome, or test result was accessed to make it.

### Consequence

The prepared `public-c4-baseline-v5` package resolves ten deployment targets and
an 85-question scoring frame, so it cannot satisfy the retained rule and is not
launchable. `omni-benchmark-aez.7.1` remains blocked on the all-18 deployment
bead `omni-benchmark-dih.17`. The latter now explicitly depends on
operator-owned restore bug `omni-benchmark-39b`, because complete validation is
not possible while 71 public tables are absent from two mirrors.

No intervention preregistration file changed: option B preserves its existing
all-154 rule. The independent cybermarket recovery remains an append-only rerun
of the public direct baseline, and the incomplete two-database restore remains
outside this compiler lane. A fresh C4 package may be prepared only after all 18
isolated deployments validate with exact readback; the existing v5 helper and
approval files remain untouched.

### Outcome

KEEP. The development promotion frame and sealed all-database requirement are
aligned at the cost of waiting for the longest-lead compiler and restore work.
This decision supplies no launch authority.

## 2026-08-29 — D-118: Keep parser-control metadata out of emitted Omni SQL

### Pre-change hypothesis and boundary

The 17 `unparseable_sql` diagnostics on polar-equipment and sports-events are
caused by the compiler prefixing otherwise locally admitted public expressions
with `-- DO NOT PARSE`. The Omni validator treats that marker as an instruction
that the SQL is unparseable, so the compiler's attempted bypass creates the
failure it was intended to avoid. If `omni_parser_mode` remains reviewed source
metadata while the compiler emits only the already validated expression, the
bundles should remain deterministic and become parser-safe without weakening
local SQL admission.

This is a general public-schema compiler correction under Bead
`omni-benchmark-dih.17.5`. It applies mechanically to every marked field and may
not special-case a database, infer SQL from validator messages, relax reserved
directive rejection, use questions/gold/hidden outcomes, or contact Omni during
implementation.

### TDD evidence

The focused compiler test was changed first to require the admitted expression
without a directive. It failed against the old compiler because the emitted SQL
still began with `-- DO NOT PARSE`. After removing only the emission prefix, the
focused parser-mode and reserved-directive gate passes nine tests. The existing
canary regeneration test then failed at its historical expectation of 16
emitted directives, demonstrating that committed bundle outputs and the canary
contract must be regenerated together rather than patched per database.

### Intervention and offline result

The compiler no longer prefixes physical-field SQL with the reserved marker.
It still requires `omni_parser_mode` to be exactly `do_not_parse`, requires an
authored expression when that metadata is present, validates the expression
through the existing reference allowlist and PostgreSQL parser, and rejects any
attempt to place the reserved directive directly in authored SQL.

All 18 committed public bundles were regenerated from their authenticated
public specifications. Only marked view files and their bound manifests
changed; no question, database-specific rule, hidden field, or runtime outcome
entered generation. No emitted public bundle contains `-- DO NOT PARSE`. The
focused compiler/publication/deployment gate passes 141 tests at 86.67% scoped
branch coverage. Ruff, formatting, deterministic canary regeneration, and diff
checks pass. Live validation and exact readback remain a separate append-only
deployment step.

The integrated full-suite gate correctly exposed five C4-arm test failures:
the immutable v6 deployment records bind the pre-fix bundle manifests, while
the fixture had copied newly regenerated bundles into the same synthetic Git
commit. Production behavior was fail-closed, and this is further evidence that
the prepared v5 package is obsolete. Positive-path unit fixtures now derive
synthetic record bindings from the copied current public bundles, while a
separate regression requires the real historical v6 records to reject those
current bundles. This keeps tests independent of local Git history and shallow
clone depth. No v6 artifact, C4 arm, runner, approval file, or receipt was
changed.

The same regeneration changes the mechanically derived current E02 candidate
set digest from the historical value recorded for its earlier source commit to
`a4facbd0edcfd5e458e90e2abbabd12d42563bc3ac1da2c57fd516d30d3aa667`.
Current-commit tests now bind that derived value; the historical result and
research-log entries remain unchanged. No E02 deployment, receipt, run, or
promotion decision occurred.

### Outcome

KEEP. Parser-control intent remains explicit in reviewed source metadata while
the product receives only locally admitted SQL. The change removes the general
mechanism behind all 17 observed parser diagnostics without a per-database
exception.

## 2026-08-29 — D-119: Propagate numeric expectations through public formulas

### Pre-change hypothesis and boundary

The four observed `invalid_types_for_function` diagnostics are instances of a
general compiler gap: PostgreSQL JSON scalar extraction produces text even when
authenticated public leaf metadata declares a numeric type, and a physical text
column can participate in a reviewed numeric formula without an explicit safe
coercion. If the compiler propagates a numeric representation expectation only
through numeric expression positions, it can cast numeric leaves, safely coerce
text operands, and leave categorical predicates unchanged.

This is a public-schema compiler intervention under Bead
`omni-benchmark-dih.17.6`. Type evidence comes only from committed schema IR,
structured-leaf descriptions, physical SQL, mapping representations, and
derived formulas. The rule may not infer from a database name, validator path,
question, gold, hidden annotation, dev-B/test outcome, or runtime value. Text
coercion must fail safe to `NULL` for whitespace, categorical text, malformed
numbers, infinities, and other nonnumeric content rather than stripping
characters or raising a database cast error.

### TDD evidence

Red tests first reproduced two required cases: a `REAL` structured leaf whose
physical expression returns text remained uncast in arithmetic, and a declared
`TEXT` amount remained a string inside a numeric `NULLIF`. A control test kept a
text-valued `CASE` predicate unchanged. The first two tests failed against the
old compiler while the control passed.

### Intervention and offline result

A focused numeric-expression module now classifies public column declarations,
structured-leaf type prefixes, and explicit root casts. It propagates numeric
expectations through arithmetic, numeric functions, numeric `NULLIF` operands,
numeric `CASE` result branches, and comparisons against numeric literals. It
does not propagate those expectations into categorical predicates or through an
existing explicit cast.

Numeric structured leaves are cast to `DOUBLE PRECISION` only at numeric use
sites. Declared text at a numeric use site receives a strict, whitespace-tolerant
numeric grammar and a guarded cast; malformed values return `NULL`. The grammar
accepts signed integers, decimals, and scientific notation while rejecting
empty strings, `NaN`, infinity, currency, grouping separators, mixed tokens,
and categorical text. Field identifiers remain constrained to the compiler's
safe placeholder grammar and are normalized before type rewriting.

Regenerating all 18 public bundles changes only four database bundles. Robot
receives casts for its three reported averages plus the related temperature
range. Solar receives the reported safe text denominator cast and numeric casts
for structured fields whose earlier missing-column errors had masked their
types. Virtual-idol receives the same mechanical casts for newly source-bound
numeric leaves, and organ-transplant receives a safe numeric output for one
reviewed numeric representation backed by text. No other bundle changes.

The focused compiler, publication, committed-artifact, and deployment gate
passes 144 tests at 87.42% scoped branch coverage. Ruff, formatting,
deterministic regeneration, and diff checks pass. Review found no credential,
injection, or unsafe-cast path; its maintainability finding moved the recursive
transformer out of the already large bundle compiler and decomposed it into a
focused module. Live validation and readback remain a separate append-only
deployment step.

### Outcome

KEEP offline. The rule addresses the four observed type errors and latent
instances of the same public mechanism without database-specific branches. The
live product oracle remains pending; any next validator issue must be preserved
rather than tuned away.

## 2026-08-29 — D-120: Stabilize unsupported negative-scale decimal literals

### Pre-change hypothesis and boundary

The two planets validator diagnostics are produced by a general representation
boundary, not by either modeled concept: positive-exponent scientific literals
whose exponent exceeds the mantissa's fractional digits have a negative
PostgreSQL decimal scale. Omni's validator accepts decimal scales only from 0
through 19, so it rejects those formulas before evaluating them. Casting only
such literals to `DOUBLE PRECISION` should preserve the public formula while
giving Omni supported type metadata; ordinary decimals, scientific literals
with nonnegative scale, field references, and formula structure should remain
unchanged.

This intervention is scoped to public numeric-derived expressions under Bead
`omni-benchmark-dih.17.7`. It is driven only by authored public SQL and the
documented validator type boundary. It may not branch on database, field,
question, gold, annotation, dev-B/test outcome, or runtime value, and it may not
contact Omni until the offline compiler slice and all-18 regeneration pass.

### TDD evidence

A red integration test first requires `1.25e6`, whose decimal scale is -4, to
be explicitly represented as double precision. A paired control requires the
ordinary decimal `1.25` to remain byte-for-byte unchanged. The negative-scale
case fails against the existing compiler while the control passes.

### Intervention and offline result

The numeric-expression module now parses numeric-derived SQL and identifies
only non-string scientific literals whose positive exponent is greater than
the number of fractional mantissa digits. It wraps each such literal in an
explicit `DOUBLE PRECISION` cast. Negative exponents, ordinary decimals, and
scientific literals whose resulting decimal scale is zero or positive are
returned byte-for-byte unchanged. Existing placeholder admission and reserved
identifier checks remain in force.

All 18 public bundles were regenerated from their authenticated public inputs.
Only the planets bundle changed: the three public constants with scales -25,
-20, and -3 now carry explicit casts. The small negative-exponent gravitational
constant remains unchanged. This is a syntactic type-representation rule; it
does not inspect data values or contain database or field branches.

The focused compiler, publication, committed-artifact, and deployment gate
passes 148 tests at 87.73% scoped branch coverage. Ruff, formatting,
deterministic regeneration, and diff checks pass. Live planets validation and
exact readback remain the product oracle and must preserve any next blocker.

### Outcome

KEEP offline. The compiler now avoids emitting PostgreSQL decimal metadata that
the public Omni validator explicitly cannot represent, while leaving supported
numeric literals unchanged.

The two compiler regenerations mechanically change the current E02 candidate
set digest to
`0111ce62001d6bb6f796a3912830529b8fae263353e62dd06111768c3147c3b8`.
Current-commit tests bind that derived value. Historical deployment records,
candidate hashes, approval files, and run artifacts remain unchanged and retain
their fail-closed mismatch against the newly regenerated bundles.

## D-137: The two failing databases were never fully restored, and the omission mechanism hid it

> **Retracted by D-138.** The conclusion below is wrong: the skipped tables are
> an upstream defect that the inventory reproduces on purpose, not a provisioning
> defect in this repository. The measurements stand; the diagnosis does not. Do
> not act on the fix described here.

### Hypothesis

D-136 concluded that the benchmark's own gold SQL does not execute on
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
computed against the truncated state. D-134's classification work and 2j9's
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

## D-138: D-137 was wrong. The missing tables are an upstream defect, and the omission mechanism reproduces it correctly

> **Arithmetic corrected by D-139.** The upstream-loader diagnosis below
> stands, but 14 plus 13 describes the broader train/direct-capture population,
> not dev-A. The committed dev-A split contains nine plus nine affected
> questions: 18 total.

D-137 concluded that `mental_healths_large` and `organ_transplant_large` were
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

### What D-137 got wrong, and why

Three claims in D-137 are false and are retracted:

- "This is a provisioning defect in this repository, not an upstream benchmark
  defect." It is the reverse.
- "The data is present locally and fully recoverable." The bytes are in the
  archive, but the tables are not recoverable into a database that stays
  comparable to the scorer's.
- "Every downstream check passed because the verification fingerprints were
  computed after the truncated restore." The fingerprints match because they
  describe the correct database.

The error was method, not evidence. Every measurement in D-137 is reproducible and
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

## D-139: Correct D-138's dev-A arithmetic before changing the promotion frame

### Hypothesis

If D-138's 14 plus 13 count described dev-A, joining the committed
`dev_a_ids.txt` membership to the public `selected_database` field would return
those counts for `mental_healths_large` and `organ_transplant_large`.

### Result

It returns nine and nine: 18 dev-A questions total. The 14 and 13 counts are the
broader train/direct-capture population and were mislabeled as dev-A in D-138.
This agrees with the already frozen dev-A conformance result: exactly 18
questions, or 54 C1-C3 attempts, are officially unscorable with
`gold_statement_error`.

The upstream-loader diagnosis in D-138 still stands. The arithmetic correction
changes only the development-frame consequence: 154 scheduled dev-A questions
contain 136 answerable and 18 benchmark-invalid questions. Current direct
C1-C3 evidence has 122 official-scoreable questions because it also preserves
the separate nine-question cybermarket and five-question archeology pre-run
exclusions. The authorized cybermarket recovery can raise that direct
intersection to 131; archeology remains an explicit five-question exclusion.

### Outcome

`omni-benchmark-1u8` is corrected before human response. Option A preserves the
all-18-database and all-154-scheduled intent while preregistering the exact 18
scorer-conformance exclusions and using 136 as C4's answerable promotion
denominator. Option B keeps a literal all-154-scoreable rule, which makes the
optimization phase inconclusive in the official environment. No private record,
dev-B outcome, test label, database, attempt, or provider was accessed or
changed to make this correction.

## D-122: Freeze the 154-scheduled / 136-answerable dev-A frame

### Hypothesis and authorization

Human response A on `omni-benchmark-1u8` authorizes a fixed scorer-conformance
frame before any all-18 C4 result exists: schedule all 154 dev-A questions,
retain the 18 questions whose gold cannot run in the official environment as
explicitly unscorable, and evaluate promotion on all 136 answerable questions.
The exact 18 identities should be derivable from committed public split
membership and public database fields, without reading private record values.

### TDD and implementation

A new test first failed because no public-only derivation module or exclusion
artifact existed. The implementation joins `dev_a_ids.txt` to the public
eligible-question manifest, requires exactly 154 unique dev-A IDs, exact
manifest coverage, and nine affected IDs per database, then emits canonical
JSON. The committed exclusion artifact regenerates byte-for-byte and has
SHA-256 `0686255b77726ec5d5126ed53d42cf2af83e5746f34e49794381b06da805489a`.

`experiments/planned-dev-a-interventions-v1.json` is now present on the clean
MVP lineage at schema version 2. Every intervention retains all-154 scheduling,
binds the exclusion artifact, and requires complete coverage of the fixed 136
answerable questions. The stopping rule rejects any additional narrowing. Its
canonical SHA-256 is
`760cc8b7ded93168b12d402242531b9078f77b1d5f5dbe741cc8e77676293403`.

The reproducible all-18 loader-fidelity audit is committed at
`experiments/analysis/livesqlbench-loader-fidelity-v1.json`, SHA-256
`3966d135a5fddfde6215ebc568bb26145ee4baaa9427864d41216740665dbc0c`.
The separate upstream report remains a draft for human review and has not been
sent.

### Outcome

KEEP. The three focused derivation/canonicalization tests pass. No question-
specific runtime input, private label value, dev-B outcome, test label,
database/provider call, credential, rerun, C4 action, or sealed action entered
the change. Final repository gate: 1,884 passed, five expected environment-
dependent skips, 83.59% branch coverage; Ruff, formatting, and diff checks pass.

## D-123: Freeze the corrected all-18 baseline deployment request

### Hypothesis

The remaining `omni-benchmark-dih.17` live oracle can be authorized without
conflating the C4 baseline with the E02 intervention if one provider-inert
request binds the exact corrected baseline bundle set, one append-only run
identity, isolated resources, pacing, and explicit negative scope before any
Omni contact.

### Offline result

Loading semantic plans only from Git commit
`a684a3ec9c1c36aeaf8648be76d0127f6597d696` yields 18 valid baseline plans,
254 files, zero preflight failures, and bundle-set SHA-256
`2487b4ad6bb6c82a49cca76f3487c76a8311b688fe22da06b8c2f4436de83a8b`.
The separately regenerated E02 intervention has 272 files, 91 relationships,
and candidate SHA-256
`0111ce62001d6bb6f796a3912830529b8fae263353e62dd06111768c3147c3b8`;
all 18 per-database semantic deployment hashes differ. This proves the two
deployment identities must remain separate and the baseline must run first.

The frozen baseline-only request is
`experiments/public-baseline-v7-deployment-request.json`, SHA-256
`cf228cd8cdbc0e8f974850ff4f86b0f826d963cc7af2d002654953656a421c36`.
It specifies one append-only `public-baseline-v7-20260829` pass over all 18
existing isolated baseline branches with four workers and a globally paced
1.25-second minimum request interval. It prohibits C4, E02, questions, scoring,
protected labels, credential/lease operations, shared/main mutations, and
replacement runs.

### Outcome

WAITING on human decision `omni-benchmark-dih.17.8`. Preparation was entirely
provider-inert: no client was constructed, no run claim was created, and no
provider, credential, lease, question, label, score, or correctness surface was
accessed.

## D-124: Stop the authorized v7 preflight before guessing an Omni profile

### Hypothesis

The authorized v7 deployment can start only if the execution environment
already supplies the canonical profile label while the exact request, source
commit, bundle set, absent output, and single-owner process checks still pass.
A missing label must stop before the append-only claim because guessing could
waste the non-retryable run identity in the wrong tenant.

### Observation

Human response A on `omni-benchmark-dih.17.8` authorizes the exact request. The
pushed request rehashed to
`cf228cd8cdbc0e8f974850ff4f86b0f826d963cc7af2d002654953656a421c36`,
the source commit resolved exactly, no competing deployment process existed,
and the canonical v7 destination was absent. The shell did not export
`OMNI_PROFILE`, and neither the repository nor any `/tmp` worktree contained an
`.env`. A detached execution worktree was created at exact source commit
`a684a3ec9c1c36aeaf8648be76d0127f6597d696`; no deployment claim or output was
created.

### Outcome

PAUSE before provider contact. Human input `omni-benchmark-dih.17.9` requests
only the non-secret profile label used for prior isolated semantic deployments.
No credential/config store will be inspected, no profile will be guessed, and
the existing authorization remains unconsumed. No Omni client, question,
label, score, or correctness surface was accessed.

## D-125: Preserve the one-pass v7 live oracle and isolate three compiler mechanisms

### Hypothesis and authorization boundary

The exact all-18 corrected baseline request can provide a clean product oracle
without entering the evaluation surface if it is executed once under the
recorded A authorization, preserves every terminal result, and uses only public
semantic artifacts plus validation/readback. Failures should remain evidence
for general compiler work, never a reason for an unapproved retry.

### Result

The canonical non-secret profile label was recovered from the existing
`omni-benchmark-dih.7` record as `benchmark-infra`; no credential or config
store was inspected. The authorized v7 pass ran once. Its append-only claim and
18 records have aggregate SHA-256
`f0ef40203ce3ae044587bf2678d5f74da84c7ee548197fc020a3870b4eb1dbe1`:
13 databases validated with exact readback, five retained validator failures,
and zero record-write failures. It was not retried.

A separate read-only diagnostic pass captured the five failed validator
surfaces with aggregate SHA-256
`c9e347c374f112f945770a62af5a5e488b9b43ca1ec7ba8378de1ba1b87cbe6d`.
The residuals are general and public: two negative DECIMAL scales on planets;
nine unsupported structured-field operators plus one missing structured source
on polar; six identity self-references on sports; and 13 table-not-found issues
across the two official-loader-defective databases.

### Outcome

KEEP the immutable v7 evidence. Under the already-fixed 154-scheduled /
136-answerable frame, `mental_healths_large` and `organ_transplant_large` are
explicit per-database blockers rather than compiler targets. The answerable
deployment gate is therefore 16 databases: 13 are verified, and planets,
polar, and sports require only general compiler fixes before a newly authorized
validation pass. No question, gold value, hidden annotation, dev-B/test outcome,
correctness result, shared/main model, credential, OAuth profile, or lease was
accessed or changed.

## D-126: Compile the three v7 answerable failures as syntax classes

### Hypothesis

The remaining answerable failures do not require database-specific modeling.
Three syntax classes explain them: an authored physical SQL identity such as
`${field}` must collapse to the compiler's direct source-column binding instead
of a semantic self-reference; an authored structured-leaf extraction must be
rendered from its authenticated public path with Omni-supported chained `->` /
`->>` operators instead of PostgreSQL `#>>`; and a negative-exponent
scientific literal in a numeric derived field must be explicitly typed as
`DOUBLE PRECISION` so Omni does not infer an invalid DECIMAL scale.

### Test boundary

Add synthetic public-schema tests for those three classes before changing the
compiler. Preserve explicit semantic aliases, non-identity authored SQL,
ordinary decimals, and supported nonnegative-scale scientific literals. Then
regenerate every public bundle to expose the full mechanical blast radius. No
database name, question, label, gold value, or outcome may enter the rule.

### Outcome

KEEP OFFLINE. The four new regressions fail before implementation and pass
afterward. All 17 fan-out bundles regenerate deterministically; the compiler
changes seven bundle directories because the same structured-operator class
appears outside polar, while the target deltas remain exactly two planets
expressions, nine polar extractions, and six sports identities. The corrected
18-plan / 254-file baseline bundle-set SHA-256 is
`2f4038a06522d84074649cb1795c43fe97efeac5c3d2deb46767915c477d7220`.
The separately regenerated 18-plan / 272-file / 91-relationship E02 candidate
SHA-256 is
`b24302d6c8d8466e52b3f4483d3d4da7d7470d14e418ae767cd11fb80236297e`.

The repository-wide gate passes 1,887 tests with five expected
environment-dependent skips and 83.59% branch coverage; Ruff, formatting,
deterministic regeneration, and diff checks pass. The live v7 evidence remains
immutable. Product validation is still required under a new exact
authorization; no retry, C4, E02, question, scoring, correctness, credential,
OAuth, lease, or protected-data action occurred.

## D-127: Freeze the seven-bundle successor validation request

### Hypothesis

The next live product oracle should redeploy exactly the semantic-hash delta
from v7, not only the three previously failing databases and not all 18. That
keeps nine unchanged verified answerable deployments intact while ensuring the
four other bundles changed by the same general structured-operator rule are
also validated against their current bytes.

### Offline result

Comparing authenticated semantic deployment hashes from v7 source
`a684a3ec9c1c36aeaf8648be76d0127f6597d696` to corrected source
`536e7256581e0b2c290af23838bbd6fbe8e5110a` yields exactly seven changed
databases: cross-border, fake-account, labor-certification, planets,
polar-equipment, robot-fault, and sports-events. Their 88 files have selected
bundle-set SHA-256
`9b6d6e8357b54b6f18d89c1d854136929d77dbdcd06b9f2fcd236bfe0b8a492f`;
the full current 18-bundle set remains
`2f4038a06522d84074649cb1795c43fe97efeac5c3d2deb46767915c477d7220`.

The exact request is pushed at commit
`8b6ab7e4ee02115d237fe606b2fbf2ac75903f57` as
`experiments/public-baseline-v8-deployment-request.json`, SHA-256
`a5d9fba11d8b4502cffce97d082c1e865a0401be54b494d5049f5e4d4d766834`.
It binds an absent append-only destination, one run identity, isolated existing
baseline branches, bounded concurrency and pacing, and explicit negative
scope. The other eleven v7 records remain immutable.

### Outcome

WAITING on human A/B decision `omni-benchmark-dih.17.11`. Preparation was
provider-inert. No client, claim, output, question, score, correctness result,
credential, OAuth profile, lease, or protected data was accessed or changed.
The request authorizes no C4 or E02 action.

## D-128: Preserve v8 and move the answerable gate to two general compiler residuals

### Hypothesis and authorization boundary

The exact seven-bundle successor can test the D-126 mechanisms without
replacing v7 evidence if the recorded A response is consumed once, every
terminal result is retained, and no failed validation is retried. The expected
mechanical result is seven exact readbacks; any residual remains public
compiler/product evidence rather than a reason to inspect benchmark questions
or correctness.

### Result

Human decision `omni-benchmark-dih.17.11` was answered A and consumed exactly
once. Run `public-baseline-v8-20260829` retained one claim and seven terminal
records. SHA-256
`bb375d7e74353836a61597638814fac27bdbb9424510d1459eb2fd65e9639190`
is computed over canonical JSON for the filename-sorted array of each artifact
filename and byte SHA-256, including the claim. Request, source-commit,
database, file-count, manifest, pacing, and prior isolated model/branch/
connection identities all match exactly.

Five bundles validated with exact readback: cross-border, fake-account,
labor-certification, robot-fault, and sports-events. Planets retained two
validation issues and polar retained ten; record-write failures were zero. The
run was not retried. Combining immutable v7 records with their exact v8
successors gives 14/18 verified deployments, or 14/16 across the fixed
answerable gate after the two official-loader exclusions.

### Interpretation and next test boundary

Sports proves the general physical-identity collapse fixed all six circular
self-references. The two remaining classes falsify narrower D-126 assumptions:
wrapping an out-of-range scientific literal in `DOUBLE PRECISION` does not
prevent the product from inferring the literal's DECIMAL scale first, and a
structured leaf cannot rely on an unmaterialized `${base_json_field}` semantic
reference. Before any new live request, add synthetic regressions that require
scientific constants with out-of-range inferred scales to be constructed from
ordinary-scale literals, and require structured paths to begin from the
compiler-attested physical source identifier while retaining safe public path
escaping. The rules must remain database-independent and regenerate the full
fan-out deterministically.

### Outcome

KEEP v8 immutable and continue offline on `omni-benchmark-dih.17.5` and `.7`.
No C4, E02, question, score, correctness, gold/hidden/dev-B/test, credential,
OAuth, lease, or shared/main model action occurred. Any new product validation
requires a fresh exact human authorization.

## D-129: Remove unsafe literal metadata and semantic structured-base dependencies

### Hypothesis

The two remaining answerable validation classes arise before expression result
typing. An out-of-range scientific token can be assigned invalid DECIMAL
metadata before an enclosing cast is considered, while `${base_field}` requires
that a semantic base dimension exist even when the public schema proves the
physical JSONB source. Both can be removed mechanically: construct scientific
values from ordinary-scale literals and a typed power of ten, and construct
structured extraction directly from the compiler-attested physical column and
authenticated path.

### Test boundary

Add regressions before implementation for positive- and negative-exponent
construction, the actual planets-scale constants, mixed-case physical JSONB
sources, nested paths, array indices, and quote escaping. Preserve supported
ordinary/scientific literals and validate authored input before compiler-owned
structured regeneration. Regenerate all 18 public bundles and reject any
remaining scientific-literal or PostgreSQL JSON-operator syntax in emitted
views. No database-specific branch, benchmark question, gold, label, or outcome
may enter either rule.

### Offline result

The four initial regressions failed and pass after implementation. Unsafe
scientific tokens now compile as multiplication or division by
`POWER(CAST(10.0 AS DOUBLE PRECISION), n.0)`. Structured leaves compile as
`JSONB_EXTRACT_PATH_TEXT(raw_physical_column, ...)`, with physical identifier
quoting and path escaping derived only from authenticated public schema. The
18-plan / 254-file baseline regenerates with bundle-set SHA-256
`8a5c9aae0d29c2ef7b7c768767aeaedc41f4f18f0f090035dc142478d5dfae66`;
the separate 18-plan / 272-file / 91-relationship E02 candidate has SHA-256
`db811d6ec553d3b82e42ba3bbd9bafe7ca528a695836a33d6f1aff0b60c5b074`.
No emitted view retains `#>>`, chained `->` / `->>`, or a scientific-literal
token.

### Outcome

KEEP OFFLINE pending a fresh product validation authorization. Exact source
commit `aa1b82f39be705f1916823598fe65f7c47c8c57b` passes 1,891 tests with five
expected environment-dependent skips and 83.58% branch coverage; the 118-test
compiler/candidate gate, Ruff, formatting, and diff checks also pass. Because
the structured rule is general and changes authenticated bytes across all 18
bundles, the next live oracle must validate all 16 answerable deployments rather
than only planets and polar; the two fixed official-loader blockers remain
explicit. No live client, C4, E02, question, score, correctness, protected data,
credential, OAuth, or lease action occurred.

## D-130: Freeze the all-answerable v9 product-validation request

### Hypothesis

Because the D-129 structured-source representation changes authenticated
semantic bytes across every database, validating only the two prior failures
would leave fourteen answerable deployments bound to stale model content. One
successor pass over the complete fixed 16-database answerable set is the
smallest product oracle that can re-establish the C4 baseline prerequisite
without attempting to repair or fabricate the two official-loader blockers.

### Offline result

The exact provider-inert request is committed as
`experiments/public-baseline-v9-deployment-request.json` at
`04cf67a6b5140bcdc59f678f5d88d2e15e7fa0c1`, request SHA-256
`d519acde72f8386a814981cfa06994bc5e0b5e07b5a5e2f1be645d97978b88cc`.
It loads source commit `f1923ceac636481220c019ce9e8399c28c839f7a`
and binds 16 databases / 228 files / selected bundle-set SHA-256
`68fe84c5bc724bf345cfebf8b74bff2e70e8d64f52a5172bf84a8cac4941e6b5`;
the full 18-bundle set remains
`8a5c9aae0d29c2ef7b7c768767aeaedc41f4f18f0f090035dc142478d5dfae66`.
Mechanical verification reproduced every manifest and semantic deployment
digest and proved the append-only v9 destination absent. No product client or
credential surface was constructed or accessed.

### Outcome

WAITING on exact human A/B decision `omni-benchmark-dih.17.12`. A permits one
append-only deployment, validation, and exact-readback pass with every terminal
record preserved; B permits no claim or product contact. Neither choice grants
C4, E02, question, scoring/correctness, protected-data, credential/OAuth/lease,
shared/main model, or retry authority. The earlier standalone A predated this
request and was not consumed.

## D-131: Correct the active C4 denominator before dispatch

### Hypothesis

The human-approved dev-A frame is already fixed at 154 scheduled questions, 18
fixed scorer-conformance exclusions, and 136 answerable questions, but the
active public C4 schedule and freezer may still encode the obsolete
ten-database v5 arm. If so, launching it would produce a validly recorded run
against the wrong experimental denominator and leave no intervention promotable
under the approved frame.

### Test boundary

Before implementation, require the committed dev-A schedule to expose all 154
scheduled identities, execute exactly the 136 non-excluded identities across
16 databases, bind the committed scorer-conformance manifest, and reject a
substituted exclusion identity. Extend the failure-first boundary through
freezing and scoring before any provider action. Preserve the historical v5
artifacts for provenance, but remove them from the active C4 execution path.

### Current result

The first focused tests fail on the current implementation as expected:
`BaselineSchedule` has no scheduled-attempt frame, and a substituted exclusion
identity is accepted. The correction is tracked by
`omni-benchmark-ei0.4.10` and remains offline. No C4, E02, provider, question,
score, correctness, protected-data, credential, OAuth, or lease action occurred.

Separately, [mvp-status.md](mvp-status.md) now provides a high-level operator
rollup that distinguishes implemented infrastructure from obtained benchmark
evidence. Beads remains the task source of truth; the rollup is refreshed only
at material evidence, blocker, authorization, freeze, and sealed-run gates.

## 2026-08-29 — D-140: Retier live-action authorization and cut the optimization phase

> Numbered D-140, not D-131, deliberately. The ledger has forked: this file and
> the copy committed on `codex/mvp-current` share only 63 of their entry numbers
> and collide on seven (D-054, D-055, D-056, D-071, D-072, D-073, D-131) where
> the same number names a different decision in each lane. D-132 through D-139
> are left unallocated as reconciliation headroom. See the reconciliation note
> at the end of this entry.

### Observation that forced the decision

Stephanie's assessment: the process has been time-intensive out of proportion to
the project requirements. The ledger supports it. Five semantic deployment
identities (v1, v2, v7, v8, v9) and five C4 run identities (v1 through v5) were
spent before any governed accuracy existed. Zero of the ten produced a scored
result. The optimization phase sat behind that surface and was never reached, so
`experiments/experiments.csv` still holds exactly one row, the gold-free
PLUMBING-001 rehearsal, whose accuracy columns are empty by construction.

### Mechanism

The custody protocol was built to protect measurements and was applied to
infrastructure. A `public-baseline-vN` pass compiles public schema into semantic
bundles and deploys them to isolated branches; its own request file excludes
questions, gold, dev-B, test data, correctness, and shared models. Contamination
risk is zero. It was nonetheless gated one exact human A/B decision per pass,
with a single-use non-retryable identity. Because the Omni validator is the only
oracle for bundle validity, each defect class surfaced live, the general fix
changed bundle bytes, changed bytes invalidated the prior validation, and a new
authorization cycle followed. Three passes for one loop.

The same rule cost C4 identity v4 to an unset `OMNI_BASE_URL`: zero evaluated
answers, receipt spent. Identity v3 died on a pre-attempt HTTP 429.

The one real counterargument is that free redeployment lets a bundle be iterated
against validator feedback until it passes, quietly encoding database-specific
knowledge. Rationing deployments is a weak proxy for that. The actual guard is
that every fix must be a general compiler change with tests and no database
name, question, or label in the rule, which is enforced by reviewing the diff.
D-126 is the worked example: three syntax classes, four regressions, blast
radius across seven bundles, target deltas unchanged.

### Decisions

Stephanie approved three changes.

1. **Authorization is tiered by contamination risk, not liveness**
   (`omni-benchmark-xeg`). Tier 1, agent-autonomous: public semantic deployment,
   validation, and exact-readback passes, retryable under a new run ID, records
   still append-only and every terminal result still preserved. Tier 2, one exact
   human authorization per action: evaluated answers, dev-B checkpoints,
   protected data, shared/main model mutation. Credentials, OAuth, leases, and
   `git push` are unchanged. Written into `CLAUDE.md` and `AGENTS.md`.
2. **The offline validator and launch preflight gate.** Verified rather than
   assumed, per this repository's own prevention against treating a logged
   control as implemented. On the live lane `codex/mvp-current`, the bounded
   idempotent 429 observer retry is implemented with tests, and the C4
   environment preflight runs at line 388 of `baseline_batch_cli.py`, ahead of
   receipt validation at 413 and consumption at 418. Both controls are real and
   correctly ordered. An earlier check against `main` suggested otherwise and was
   wrong: `main` is deliberately stale and the commits were re-applied under
   different hashes. The remaining piece is the general readback normalization
   owned by `omni-benchmark-dih.17.13`, already claimed in another lane.
3. **The optimization phase is cut** (`omni-benchmark-ivg`). No dev-A-supervised
   intervention is promoted, no dev-B checkpoint is consumed, and the final
   candidate is the frozen mechanical baseline. Recorded as a post-Freeze-A
   deviation in `docs/protocol-diff.md` with its reason and with the argument
   that it cannot bias the primary contrast: the cut is decided on schedule cost,
   not observed accuracy, and it removes a system-improvement step from every
   condition equally, so it can only lower expected C4.

### Consequence

The executed system receives no question-level supervision and must not be
described as tuned or adapted. The remaining path is: resolve dih.17.13, finish
`omni-benchmark-ei0.4.10`, one C4 dispatch under tier 2, Freeze B with the
baseline as final candidate, the sealed run, then the report.

No question, gold value, hidden annotation, dev-B or test outcome, correctness
result, credential, OAuth profile, or lease was accessed or changed by this
entry. No provider contact occurred.

### Unreconciled state found while committing this entry

Three findings, recorded because they are not visible from either lane alone.

1. **The v7, v8, and v9 deployment records are committed on no branch.** All 44
   files exist only as untracked files in the dirty `main` worktree. They are
   the terminal output of authorized single-pass live oracles that may not be
   retried, so a `git clean` in that worktree would destroy irreplaceable
   evidence. Committed to `main` alongside this entry.
2. **The research ledger has forked.** `main`'s worktree copy holds 97 entries,
   the `codex/mvp-current` copy holds 96, they share 63 numbers, and seven
   numbers name different decisions in each. Any citation of D-054, D-055,
   D-056, D-071, D-072, D-073, or D-131 is currently ambiguous, and
   `docs/protocol-diff.md` and `RESULTS.md` cite D-numbers. Reconciliation is a
   human-controlled surface and is not attempted here.
3. **`main` is 79 commits behind `codex/mvp-current`** and is not the lane the
   working agent builds from, though it is the worktree that agent writes into.
   That combination is what produced findings 1 and 2.

No question, gold value, hidden annotation, dev-B or test outcome, correctness
result, credential, OAuth profile, or lease was accessed or changed. No provider
contact occurred.

### 2026-08-29 reconciliation addendum

The lane divergence described above is now resolved by the canonical numbering
map at the top of this file. All 142 decision entries from both lanes are
retained; the 140 whole-number decisions occupy D-001 through D-140 exactly,
and in-repository citations use the canonical numbers. The original observation
is preserved here as the reason the reconciliation was required.

## 2026-08-29 — D-141: Bind C4 execution to the fixed 154/136 frame

### Hypothesis

D-131 identified a live-path mismatch: the human-controlled frame schedules all
154 dev-A identities, fixes 18 official-loader failures as unscorable, and
executes 136 answerable identities across 16 databases, while the active C4
runner and freezer still selected the obsolete 129-attempt, ten-database arm.
Representing scheduled and executable identities separately at every boundary
should make substitution or partial coverage fail closed without executing an
excluded identity.

### Intervention

`BaselineSchedule` now binds the complete scheduled frame and the committed
scorer-conformance manifest in addition to its executable attempts. The C4
runner derives 154 scheduled attempts from committed dev-A membership, validates
the exact exclusion manifest without naming a database or question in code, and
executes only the resulting 136 attempts. The freezer preserves both ordered
identity sets and their counts. The dev-A scorer authenticates the scheduled
frame, the 18 fixed exclusions, and the conformance-manifest digest, then reports
scheduled, scoreable, and unscorable totals separately. Missing, substituted,
duplicated, or reordered identities are rejected.

The lane merge at `a4a9168` also retains main's C1 retrieval-sensitivity path and
the complete D-001 through D-140 ledger concordance. E02 remains unpromoted and
off the critical path; no deployment or evaluation authority was added.

### Result

The focused C4 frame and compatibility gate passes 75 tests. The complete suite
passes 1,917 tests with five expected environment-dependent skips. Branch
coverage is 83.53%, above the 80% gate; Ruff, formatting, and diff checks pass.
Diff review found no database name, benchmark instance, hidden label, or
question-specific rule in the implementation.

### Outcome

KEEP OFFLINE and close `omni-benchmark-ei0.4.10`. The obsolete v5 arm remains
historical and cannot enter the active C4 path. The next C4 prerequisite is the
general polar exact-readback correction under `omni-benchmark-dih.17.13`; C4
dispatch still requires one exact Tier 2 human authorization. No provider,
question, gold, hidden annotation, dev-B, test outcome, correctness, credential,
OAuth, lease, or push action occurred.

## 2026-08-29 — D-142: Distinguish readback convergence from semantic normalization

### Hypothesis

The immutable v9 record shows that polar validated with zero issues but its
cabin-environment view differed on the immediate exact readback. If this is an
eventually consistent extension snapshot rather than a compiler or product
canonicalization, the same isolated branch should later match the exact frozen
v9 semantic plan without any mutation. The general correction should then
observe readback convergence for a fixed bounded interval, never broaden the
authenticated equivalence relation.

### Observation and failure-first boundary

A Tier 1 read-only fetch of the existing isolated v9 polar extension layer used
the established non-secret `benchmark-infra` profile without inspecting or
changing any credential, OAuth, or lease state. Against source commit
`f1923ceac636481220c019ce9e8399c28c839f7a`, the same branch and manifest now
have zero semantic differences after the existing attested projection. This
refutes the structured-SQL-normalization hypothesis and identifies delayed
readback convergence as the external failure.

Before implementation, require a synthetic first readback mismatch followed by
an exact snapshot to verify successfully, and require a persistent mismatch to
fail closed after the fixed observation budget. The first focused test must fail
on the current single-read implementation.

### Current result

KEEP the bounded observer under `omni-benchmark-dih.17.13`. It performs at most
six exact observations over 30 seconds, preserves the first mismatch in a
terminal failure, and retries only a missing or semantically different expected
document. Unexpected files, malformed response shapes, duplicate keys, and
unsafe YAML still fail immediately. The authenticated semantic comparison is
unchanged. The focused deployment boundary passes 75 tests; the complete suite
passes 1,921 tests with five expected environment-dependent skips and 83.55%
branch coverage. Ruff, formatting, and diff checks pass.

No deployment, upload, validation, evaluated answer, question, gold, hidden
annotation, dev-B, test outcome, correctness, credential, OAuth, lease,
shared/main mutation, or push occurred.

## 2026-08-29 — D-143: Preserve v10 and reject the 30-second convergence budget

### Hypothesis

If six exact readback observations over 30 seconds cover the product's extension
convergence lag, the Tier 1 v10 polar pass should verify the existing isolated
branch without changing authenticated semantic equality. A terminal mismatch
must remain evidence and may not be overwritten or retried under the same run
identity.

### Result

REFUTED. At exact source commit
`42039fe565ea715d424c6bac0937c414f19797ac`, v10 validation returned zero issues
but both the pre-upload observation and the post-upload observation failed to
converge. The final record preserves 20 uploaded public extension files and the
six-observation terminal mismatch. Claim SHA-256 is
`2a717ee7423dc12eab354a8b6900e7d294608953ea1f77b4c623f1cefaf9653e`; record
SHA-256 is
`48795b9d26be2dc8480993d7a42d87064d7d1cf23cd2e6857ecfa7eeb1c64d23`.
There was no retry.

A separate Tier 1 read-only fetch immediately after the terminal record matched
the same committed plan with zero semantic differences. That retains the causal
finding—delayed readback convergence—but rejects 30 seconds as a sufficient
bound. The authenticated comparator remains unchanged. A successor may use a
new run ID only after a longer general bounded observer is implemented and
tested.

No evaluated answer, question, gold, hidden annotation, dev-B, test outcome,
correctness, credential, OAuth, lease, shared/main model, or C4 action occurred.

## 2026-08-29 — D-144: Extend exact readback observation to one minute

### Hypothesis

V10 refuted a 30-second convergence budget, then the same branch matched the
frozen plan on the immediately subsequent read-only fetch. Adding one final
30-second delay should cover that observed boundary while keeping the mechanism
fixed, bounded, and general. Authenticated semantic equality and all immediate
fail-closed cases remain unchanged.

### Failure-first boundary

Before implementation, update the persistent synthetic mismatch to require
seven observations over exactly 60 seconds. The current six-observation helper
must fail this test. A successor public validation may use a new Tier 1 run ID
only after the focused boundary, Ruff, formatting, and diff checks pass on an
exact commit.

### Current result

KEEP OFFLINE under `omni-benchmark-dih.17.13`. The fixed schedule now performs
seven observations over exactly 60 seconds. The focused deployment/readback
boundary passes 75 tests; Ruff, formatting, and diff checks pass. The only code
change is the additional final delay; retry classification and authenticated
semantic equality are unchanged. V10 remains immutable. No v11, evaluated
answer, question, gold, hidden annotation, dev-B, test outcome, correctness,
credential, OAuth, lease, shared/main model, or C4 action occurred.

## 2026-08-29 — D-145: Authenticate product-added view identity before projection

### Observation

The append-only Tier 1 v11 pass at source commit
`80ca78ad9e55d19973ed7e62cb5a1bc5551650e2` validated polar with zero issues
but failed exact readback after seven observations over 60 seconds. Claim
SHA-256 is
`b5022f939e7e433df325b8e89abd1c7fe3f20627c605885486edd75221507c72`;
record SHA-256 is
`5919e6a3760bc6515fe1b9856d5ae99d3b696c8814c5228ca82195d078dcca79`.
Five subsequent Tier 1 read-only observations were stably identical, so the
one-minute convergence hypothesis is refuted rather than merely underbudgeted.

Instrumenting the existing authenticated comparator identified the only
difference in `public/cabinenvironment.view`: Omni returned the top-level
`catalog`, `schema`, and `table_name` identity fields that the expected remote
projection omits. The public readback bytes were stable across the five
observations. No question, label, correctness, gold, hidden annotation, dev-B,
or test outcome was inspected.

### Hypothesis and failure-first boundary

An exact remote view identity is safe to project away only when all three
identity fields are present and byte-for-value equal to the compiler-attested
local view identity. A missing subset or any differing catalog, schema, or
physical table must continue to fail closed. After that authenticated
projection, every other semantic key remains subject to the existing exact
comparison.

Before implementation, require synthetic readback with the complete matching
identity triplet to pass, while a partial triplet and a wrong value for each
identity field still fail. The current comparator must fail the matching case.
The general rule may not contain a database name, benchmark question, or label.

### Result

KEEP. The failure-first matching case
failed on the prior comparator. The general implementation now requires the
complete identity triplet, compares each value with the authenticated local
view, and only then removes those three keys before the unchanged exact semantic
comparison. Partial and differing identities fail closed. The focused
deployment/readback boundary passes 54 tests; Ruff, formatting, and diff checks
pass.

The append-only Tier 1 v12 verification at exact source commit
`46a0c59d4927b4d16d55d4a9c4da7aea4fb82f9b` completed without a retry:
validation returned zero issues and all 20 public extension files passed exact
readback. No upload was needed because the isolated branch already contained
the authenticated files. Claim SHA-256 is
`f48fcf758756601b1507240774935aba70c0995d3239ffdf16cc51a0e4bf0e7e`;
verified-record SHA-256 is
`68a04df036230c1873dffa13a0f6c82c60555da3014f67519a707ea811cfd6b1`.
V9 through v11 remain immutable. The 16 answerable public deployments are now
validated with exact readback; the two fixed official-loader exclusions remain
explicit.

No evaluated answer, question, gold, hidden annotation, dev-B, test outcome,
correctness, credential, OAuth, lease, shared/main model, or C4 action occurred.

## 2026-08-29 — D-146: Use the thinnest defensible path to MVP results

### Decision

The evaluation apparatus has accumulated enough ceremony that it is delaying
the evaluation itself. For the submission-ready MVP, use one thin end-to-end
loop: make the smallest general fix needed for the current blocker, run focused
risk-proportionate checks, preserve one immutable live result when required, and
immediately advance to the next result-producing gate.

Repeated full-suite runs, duplicate status updates, worktree staging ceremony,
external-audit follow-ups, cleanup, and framework improvements are not MVP
prerequisites unless they directly protect validity or block the next result.
The irreducible controls remain unchanged: protected-data custody, frozen scorer
semantics, append-only evaluated evidence, exact run lineage, and one exact human
authorization for each evaluated or sealed action.

### Operational consequence

With public semantic validation complete, the direct path is now: bind and obtain
the fixed-frame C4 authorization; dispatch once; freeze and score; record Freeze
B; run the sealed evaluation through custody; finish `RESULTS.md`. The deferred
audit and worktree-hygiene queues must not interrupt this sequence unless they
surface a concrete blocker to one of those actions.

## 2026-08-29 — D-147: Bind C4 to one current 16-deployment evidence set

### Hypothesis

The approved C4 scheduler already emits 154 scheduled identities, 136 executable
dev-A attempts, and 18 fixed unscorable exclusions. Its real provider-inert dry
plan should therefore pass once the derived deployment gate references one
current immutable record set covering the same 16 answerable databases. No new
runtime mechanism or scoring decision is needed.

### Failure-first observation

At exact main commit `84908717b3df6687c628f972d1b81a978f994b2a`, the dry
plan failed before provider contact with `scheduled databases exceed the derived
deployment gate`. The committed arm still bound ten historical v6 deployments.
This is a stale evidence binding upstream of the already-correct scheduler, not
a reason to change the approved 154/136 frame.

### Result

KEEP. One append-only Tier 1 v13 pass
verified all 16 answerable databases with zero terminal failures and zero record
write failures. Its claim plus 16 records have canonical sorted-file aggregate
SHA-256
`5698a4d23e5c7b2d99dca1488e7ebb7b2591d62a87a683373bc0af1ab1cdc3c6`.
The existing arm now binds those exact records; its public full-train inventory
regenerates to 204 answerable identities while the unchanged evaluated scheduler
selects the approved 136 dev-A attempts. The 15-test focused arm/deployment gate
passes. At exact system commit
`aab9eb512aeb021be42b1549a7634708d0c09fb8`, the provider-inert v6 plan now
passes with 154 scheduled, 136 executable, 18 unscorable, and 16 deployment
targets. Schedule SHA-256 is
`fa4675408574a610d495ed0fd99b4542eddf9f6f77127af1ce42f6207c7ec7ba`;
execution-plan SHA-256 is
`a83b0042170227b1294f5a354ccb71c9d066bc069d8120724c6a252cd38662dd`;
deployment SHA-256 is
`6b65cf8e8d76d748f8438ecb62fcb379f302d0cb8bee68fe8864eba63cdb05c7`.
The exact no-launch human package is ready as `omni-benchmark-ei0.4.12`.
`RESULTS.md` now carries this verified 16-deployment state and identifies the
single-use C4 authorization as the next unresolved evidence gate; it adds no C4
or held-out estimate.

No C4 dispatch, evaluated answer, question, gold, hidden annotation, dev-B, test
outcome, correctness, credential, OAuth, or lease action occurred.

## 2026-08-29 — D-148: Replace repeated human prompts with standing authorization

### Decision

Stephanie granted all remaining human authorization for the MVP and directed
the project to stop requiring ceremonial human responses at each step. Agents
may therefore materialize and consume the existing action-specific control-plane
receipts without returning for another A/B prompt.

This removes prompt latency, not benchmark controls. Every evaluated or sealed
action remains bound to its exact system commit, run identity, schedule,
deployment or scorer inputs, output root, expiry, and single-use marker. Custody,
append-only evidence, quarantine, protected-data isolation, and the prohibition
on correctness-driven reruns remain unchanged. Credentials, OAuth, and leases
remain operator-owned.

### Immediate result

The exact C4 v6 receipt was created and validated from the already-bound
`omni-benchmark-ei0.4.12` package. It expires at `2026-08-30T00:00:11Z` and has
SHA-256
`16096b6e750ce2ac285f4b54b4b804e5dbede211912cb59541a3f8beb06b4e35`.
The helper then raised a reporting-only `expires_at` attribute error after
closing the decision; no consumption marker or output existed, so the valid
receipt is preserved rather than recreated.

## 2026-08-29 — D-149: Run the fixed-forward C4 dispatch from exact system HEAD

### Failure-first observation

The authorized v6 dispatcher consumed its receipt and staged three concurrent
children. Every child exited before provider contact with the same preflight
error: the bound system commit `aab9eb5` did not equal the newer main-worktree
HEAD. V6 produced no evaluated answers or correctness. Its three immutable
failure records and consumption marker are preserved, and no process remains.

### Hypothesis and result

The runner is sound; the launch context was wrong. A fresh run identity from a
detached worktree whose HEAD exactly equals the bound commit should pass the
same child preflight without changing evaluated code or retrying any observed
answer. KEEP for fixed-forward v7. Worktree `/tmp/omni-benchmark-c4-v7` is clean
at exact `aab9eb512aeb021be42b1549a7634708d0c09fb8`. Two provider-inert dry plans
stabilized after environment materialization at schedule SHA-256
`038558ca8eeed9a59d8efb32940749e7243768920475c8955d5830cb1336ad3a`
and execution-plan SHA-256
`a3fe6e79b8b66c35d8e644cefd9cd579d08acd56bc254e1765836951c73d5aad`.
Standing authorization created the exact v7 receipt under
`omni-benchmark-ei0.4.13`; its SHA-256 is
`c7c49d006f38be8510ef7e70a3288b0e52eb57379056b36b1d7311a728246a0b`.

V7 consumed that receipt but all three children exited before provider contact
because ignored source-tree bytecode differed across Python hash seeds. V7
produced no evaluated answers or correctness, and its immutable artifacts remain.
The fixed-forward hypothesis therefore adds no code change: start from another
fresh exact-commit worktree and set `PYTHONDONTWRITEBYTECODE=1` before its first
Python process. V8 has zero source-tree bytecode and two stable provider-inert
plans at schedule SHA-256
`27dfb0f6e5cc61f3ce4afea8db031aa1da8b9f174e257844846259fc8f3935a7`
and execution-plan SHA-256
`7c315004fd04dba16c4b002f96c815aba1c2d4d514638d2ba98e2ad1b8d4d302`.
Its exact receipt is recorded under `omni-benchmark-ei0.4.14`, SHA-256
`92757ebdbe10538ac3eb028008b838a8349eed0f9dfa3cb5b28673d4f174f2c7`.
The receipt was consumed exactly once and live dispatcher session `48207`
remained active past both earlier pre-provider failure points. Its first
observation had no terminal output files and zero source-tree bytecode; no
replacement may be launched while that handle is live.

## 2026-08-29 — D-150: Restore runtime semantic drift, then resume in place

### Observation and hypothesis

V8 terminated after preserving 59 complete immutable generations. One labor
attempt failed before question dispatch because authenticated semantic readback
returned a path set different from the exact public deployment plan; 77 attempts
remain pending and no process remains. This is semantic-branch drift caught by
the pre-answer gate, not an evaluated answer or a correctness result.

The smallest valid recovery is to redeploy only
`labor_certification_applications_large` from the same committed public bundle
under a fresh Tier 1 run ID, require zero validation issues and exact readback at
the same semantic digest, then resume the same v8 run identity. The immutable
repository reconciliation already proves 59 attempts complete and 77 pending,
so a continuation must skip all completed attempts and may retry only the one
pre-answer infrastructure failure plus the 76 unstarted attempts. No evaluated
code, bundle content, question, label, or scorer changes.

### Result

KEEP. Public-only v14 confirmed that the failed C4 target was the same branch
and model previously verified by v13. Its readback contained one obsolete
`apm.view` plus Omni's empty `model` and `relationships` extension stubs. The
runtime and deployment comparators already permit those two platform stubs;
the obsolete view was the sole blocker. It was deleted from the isolated
branch, and the fresh append-only v15 labor record then returned zero validation
issues and exact readback for the six committed semantic files at the unchanged
semantic digest.

The continuation preflight re-derived the unchanged schedule, execution plan,
and 16-target deployment binding, found exactly 59 reconciled immutable attempts
and 77 pending, and found no source-tree bytecode or competing dispatcher.
Standing authorization recorded `omni-benchmark-ei0.4.15.1`; its receipt
SHA-256 is
`69fb9678aeee9ceaacac28fbd224fd5a92c329de40616c897b5a8a840db9284c`.
The receipt was consumed once and the same v8 run/output identity resumed. The
generation count advanced beyond 59, confirming that completed attempts were
reconciled and new pending work began. No answer content or correctness was
inspected.

## 2026-08-29 — D-151: Restore polar runtime drift, then resume in place

### Observation and hypothesis

The v8 continuation advanced from 59 to 103 complete immutable generations.
While another in-flight attempt completed, one polar attempt stopped before
question dispatch when authenticated readback found changed
semantic content for polar's `operationmaintenance.view`. One new diagnostic
failure envelope was preserved; no answer content or correctness was inspected.

As with the resolved labor drift, the smallest valid recovery is a fresh
public-only polar deployment from the unchanged committed bundle, requiring zero
validation issues and exact readback on the same isolated branch/model. If that
passes, resume the same v8 identity only after reconciliation proves 103
complete attempts and 33 pending. No evaluated code, question, scorer, or
completed artifact changes.

### Result

KEEP. Public-only polar v16 returned zero validation issues and exact readback
on the same isolated branch/model. Reconciliation found 103 complete attempts
and 33 pending. Standing authorization bound and consumed one same-run
continuation receipt, SHA-256
`a0fe362c2855b1dabb819bf414bbcbfa00e49be861599f63fd6f1524d343f2d7`.
The continuation passed the repaired polar gate and advanced the immutable run.

## 2026-08-30 — D-152: Resume after pre-answer Omni rate limiting

### Observation and hypothesis

The second continuation preserved 117 complete generations, then one solar
attempt stopped before question dispatch because Omni returned HTTP 429 during
the authenticated semantic readback. The failure envelope contains no answer;
no correctness was inspected. Nineteen attempts remain pending.

This is a demonstrable provider-rate infrastructure failure, not semantic drift
or an evaluated result. Resume the same run after exact 117/19 reconciliation
with maximum concurrency reduced from three to two to lower request bursts. The
schedule, execution plan, semantic deployments, evaluated code, prompts, and
outputs remain unchanged; all 117 complete attempts must be skipped.

### Result

KEEP. Standing authorization bound the continuation to 117 reconciled and 19
pending attempts. Reducing infrastructure concurrency to two avoided another
request burst. The immutable run completed all 136 executable C4 generations:
91 answered and 45 retained explicit system/runtime error outcomes. The final
reconciliation is 136 complete and zero pending. No correctness was read during
capture.

## 2026-08-30 — D-153: Inventory preserved pre-answer diagnostics at freeze

### Observation and hypothesis

The completed C4 freezer reconciles all 136 attempts but rejects the artifact
tree because it contains the three immutable `.failed-*` directories preserved
by sanctioned pre-answer infrastructure continuations. Moving or deleting those
records would weaken provenance; treating them as attempts would be false.

Extend the freezer's general artifact inventory rule to accept only private
`.failed-<scheduled-instance>-r1-<nonce>` directories under that scheduled
database/condition, containing only a private `failure.json`. Hash those files
into the inventory while retaining the unchanged 136-attempt selection. Every
unrelated directory, unscheduled identity, extra file, or symlink must still
fail closed.

### Result

KEEP. The focused freezer tests pass, including acceptance of a private
scheduled-attempt diagnostic and rejection of an unscheduled diagnostic. The
completed v8 tree froze without moving or deleting evidence: 154 scheduled,
136 answerable, 18 fixed unscorable, 638 hash-inventoried files, selection
SHA-256
`256145c13cfae7142d92f108b4ee9dd93e658a44cafb683e5aec90170b8315cc`.

The aggregate-only full-dev-A conformance sweep then established 136 official
and 135 sensitivity scoreable questions. Its receipt SHA-256 is
`d9387e4b64c8d5160648b149374c0b9f9365438e350399d788cfd3db3d0fc6e5`.
No per-question identity, SQL, row value, or correctness left custody.

## 2026-08-30 — D-154: Resolve promoted C4 result paths without rewriting evidence

### Observation and hypothesis

C4 scoring failed closed before database acquisition because every one of the
91 answered generation records binds `answer.result.json` to its original
private `.staging-<attempt>-<nonce>` path. The dispatcher atomically promoted
that directory to the canonical attempt path after capture, so the file and its
recorded SHA-256 are present and correct while the immutable path string names
the pre-promotion location.

Accept only the exact sanctioned staging-path shape for the same
run/database/condition/instance/repetition and final filename. Continue reading
the promoted canonical artifact and require its bytes to match the immutable
recorded digest. Cross-attempt, cross-database, malformed nonce, traversal,
wrong filename, or hash mismatch must fail. This is provenance-preserving path
resolution, not artifact repair or scorer-semantic change.

### Result

KEEP. The scorer now accepts only the exact same-attempt private staging-path
shape while loading the canonical promoted file and verifying the immutable
recorded digest. Cross-attempt, cross-database, malformed-nonce, traversal,
wrong-filename, and hash-mismatch cases fail closed. The focused affected
surface passes 143 tests and Ruff; no generation or result artifact was
rewritten.

## 2026-08-30 — D-155: Recover only C4 infrastructure failures

### Observation and hypothesis

After the staging-path provenance correction, scoring still fails closed before
database acquisition because 45 of the 136 immutable C4 generations are labeled
benchmark-infrastructure outcomes: 34 unsupported semantic result types, ten
response-contract failures, and one adapter transport failure. Counting those
attempts as wrong would change the frozen system/infrastructure boundary; leaving
them in the selected set prevents a complete comparison.

Classify the 45 cases using only aggregate runtime metadata. If the failures are
general capture-adapter gaps, correct those mechanisms with failure-first tests
and run an append-only continuation containing exactly the demonstrably affected
attempts. The 91 answered attempts and all v8 evidence remain immutable and are
never regenerated. No question text, result rows, labels, correctness, credential,
OAuth, or lease state may be inspected. The recovered selection must preserve the
unchanged C4 system, schedule, deployments, and scorers while making every selected
attempt an evaluated-system outcome.

### Result

KEEP. Aggregate-only classification found that 32 failures exposed an `UNKNOWN`
planner type, one completed Omni job lacked a parseable generated query, and one
additional persistent plan rejection was an evaluated-system contract failure.
The remaining 11 attempts were recoverable by single-shot result execution of
their already-generated semantic queries. General adapter changes add Boolean
support, preserve empty strings for string fields, interpret empty non-string
cells as typed nulls, and bind every recovery entry to the original selection,
generation digest, deployment, branch, and model. The recovery never resubmitted
a benchmark question or model-reasoning request.

Append-only recovery v5 accounts for all 45 source failures as 11 recovered
typed results and 34 explicit evaluated-system failures. Its manifest SHA-256 is
`5d6ff474f30d3de6d703ad5c6c59373fe8093515eabb83473bdb352c4f30fd9f`.
Recovery v1-v4 remain immutable incomplete diagnostics and have no manifest, so
the scorer cannot consume them.

The unchanged official scorer then completed C4 dev-A scoring: 154 scheduled,
136 scoreable, 18 fixed unscorable, 9 correct, 93 wrong, and 34 refused or
system-error. The official score artifact SHA-256 is
`57d45346de0a98384207d350f163dfcf812e677cf3719b4a3008b5e0f3f222d8`;
the aggregate receipt SHA-256 is
`0296753e8fcbf826a99ed2f86088ecdfb61981db8dea47d93e7871cef2690a78`.
The frozen sensitivity scorer reports 9 correct, 93 wrong, 33 refused or
system-error over 135 scoreable attempts, with artifact SHA-256
`af333cc78bde8827dfd5f6b092b5c319492ba7554c9c18ed40710ca26d6d4251`.

## 2026-08-30 — D-156: Freeze the mechanical baseline despite low C4 accuracy

### Observation and hypothesis

The preregistered optimization phase was cut before C4 outcomes existed, making
the public mechanical baseline the final candidate. C4 subsequently scored 9 of
136 scoreable dev-A attempts correct. That low result is evidence about the
frozen governed system, not permission to tune, rerun question-level reasoning,
or select a different candidate after seeing correctness.

Record the actual Freeze B through the existing two-commit Git-object boundary:
an exact system commit containing the identity-only sealed schedule and complete
frozen input specification, followed by a direct child adding only the canonical
Freeze-B manifest. Use the human-controlled seed surface exactly once and expose
only hashes and counts. Then validate and plan all 1,212 sealed attempts without
provider contact or protected-data access before any production dispatch.

## 2026-08-30 — D-157: Close the sealed C4 deployment-coverage gap before Freeze B

### Observation and hypothesis

Freeze-B preparation exposed a mismatch hidden by the development-only frame.
The sealed schedule contains all 101 committed test identities under every
condition and the production C4 factory requires an exact deployment target for
every scheduled database. Every database occurs in the sealed split. The
current v13 C4 evidence covers only the 16 dev-A-answerable databases;
`mental_healths_large` and `organ_transplant_large` have explicit public-loader
blockers and no verified deployment target. The 18-question exclusion manifest
is scoped to C4 promotion and dev-A reporting, so it cannot silently change the
sealed 101-question estimand.

Before Freeze B, use only public official-loader inventory and committed
semantic artifacts to determine whether a general non-empty mechanical model
can be compiled, deployed, validated, and read back for each blocked database.
If not, stop at the human-controlled protocol surface rather than freezing an
impossible run, restoring benchmark-omitted tables, fabricating an empty model,
or inspecting sealed question content or outcomes.

### Result

Every selected mechanical view for the two databases depends on a physical
table omitted by the pinned official loader, so no honest non-empty baseline
deployment exists under the frozen compiler. Before any sealed generation,
label release, or outcome access, Stephanie selected option A in
`omni-benchmark-ei0.9.1.1`: execute all four conditions and three repetitions on
the matched 89-question subset from the 16 databases with verified deployments.
The 12 exclusions are a public-loader scope deviation, not model or gold
failures. No protected field or per-question outcome informed the decision.

## 2026-08-30 — D-158: Align the governed development result to the direct frame

### Observation and hypothesis

The full governed C4 result is 9/136, while the frozen direct C1-C3 report uses
the 122 questions that are scoreable in every direct condition. Comparing those
raw percentages could mistake a denominator difference for a system effect.

Compute one aggregate-only intersection from the immutable official score
artifacts. Require each included question to have a scored C1, C2, C3, and C4
record; emit only condition totals and the C1/C4 paired correctness table. Do
not expose question identities, SQL, rows, annotations, or per-question labels.

### Result

The matched intersection contains 122 questions. C1 has 9 correct, 80 wrong,
and 33 refused/error; C2 has 29, 91, and 2; C3 has 16, 74, and 32; C4 has 5,
83, and 34. C4 accuracy is therefore 5/122 (4.1%) on the aligned frame, versus
7.4% for C1, 23.8% for C2, and 13.1% for C3.

The paired C1/C4 table has 3 questions correct in both, 2 correct only in C4,
6 correct only in C1, and 111 correct in neither. The descriptive paired
difference is -4/122, or -3.3 percentage points. This confirms that C4's low
development accuracy is not caused by its broader scoreable denominator. It
remains exploratory development evidence and does not authorize tuning or a
question-level rerun.

## 2026-08-30 — D-159: Derive sealed completeness from the frozen frame

### Observation and hypothesis

The open pre-outcome frame decision may retain 101 sealed questions or use a
matched 89-question subset. The sealed custody stack currently repeats literal
101-question and 1,212-coordinate checks even though Freeze B already records
the question count and every downstream artifact binds the exact schedule.
Changing literals after the frame decision would create a broad, rushed patch;
pretending excluded questions failed would corrupt the estimand.

Generalize provider-inert completeness checks to derive cohort and total counts
from the exact frozen schedule and Freeze-B manifest, while retaining 101 and
1,212 as the byte-compatible defaults. First add failure-first tests for a
non-default internally consistent frame and inconsistent count bindings. This
plumbing must not choose A or B, alter split membership, weaken exact membership
or hash checks, fabricate generation records, access protected data, or contact
a provider.

Option A was then selected before implementation. The target exercised frame is
therefore 89 questions and 1,068 coordinates, but the mechanism remains general
and the existing 101-question default must continue to validate unchanged.

### Result

The sealed custody stack now derives question and coordinate counts from the
Freeze-B manifest and exact execution plan through scheduling, recording,
dispatch, cohort finalization, private release, dual scoring, approval, and
aggregate reporting. The original 101-question / 1,212-coordinate defaults and
schedule bytes remain unchanged. Synthetic end-to-end evidence exercises the
selected 89-question / 1,068-coordinate frame through immutable cohort loading,
private-release membership checks, both scorers, and identity-free publication.

The selected identity manifest is reproducibly generated from the committed
public eligible manifest, original frozen test IDs, and the human decision spec.
It contains 89 identities across the 16 verified databases and records the 12
excluded identities only as aggregate public database counts. The focused
provider-inert suite passed 250 tests with 80.00% branch coverage; Ruff, format,
and diff checks passed. No provider, protected label, sealed outcome, credential,
OAuth profile, or lease was accessed.

## 2026-08-30 — D-160: Keep the primary report aligned with the sealed frame

### Observation and hypothesis

After the matched-frame decision and plumbing landed, `RESULTS.md` still
described an unchanged 101-question sealed population and 1,212 pending
generations. Leaving those statements in the primary deliverable would make the
reported design contradict the committed protocol deviation before the sealed
run began.

Update only the report's design, pending-result, and limitation language to the
approved 89-question / 1,068-coordinate frame. Preserve the original
101-question split as provenance, state the narrower 16-database estimand, and
leave every held-out numeric result pending. Also mark the two refusal subtypes
as unavailable because the frozen generation contract cannot distinguish them.

### Result

The primary report now distinguishes the original 101-question split from the
executed matched 89-question frame, records the 12 public-loader exclusions as a
pre-outcome scope deviation, and uses 1,068 as the pending generation count. No
held-out value was added or inferred. The edit preserves the existing report
structure and direct wording; its headings, opening status, held-out table,
limitations, and closing reproducibility section were manually reread.

## 2026-08-30 — D-161: Freeze the sealed schedule from the human seed

### Observation and hypothesis

Stephanie approved the exact non-secret seed
`omni-livesqlbench-large-v1-sealed-mvp-v1` in
`omni-benchmark-ei0.9.1.3`. The 89-question identity manifest, selected final
candidate, two scorers, production adapters, and dynamic count gates are already
committed.

Generate the canonical 1,068-coordinate schedule from committed identities and
the approved seed, then record Freeze B only from exact Git objects. Provider-
inert planning must reproduce every schedule byte and bind the complete runtime,
deployment, model, budget, database-snapshot, and scorer inputs before any
sealed generation or label release.

### Result

The canonical schedule contains 1,068 coordinates over 89 questions, four
conditions, and three repetitions. Its file SHA-256 is
`97bf076437811bb54cda4ae923d69d751cd2dab6c3601cd1436d2a0f065332a1`
and its registered attempt-order SHA-256 is
`056a6c226ac3f7ea38750b26c89ba2e2eeb8aa9724438bedf93895150af87dec`.

System commit `d8d1a9335fe2107157f8ef0814f99e80ffd7ef1e` freezes 108 files,
including the exact runtime-source closure, dispatch policy, database snapshot,
condition inputs, C3 bundle-set attestation, and all 16 verified C4 deployment
records. Direct child `079e4ce8399b3c29545c60753e5e2da6e68ca582`
adds only the canonical Freeze-B manifest, whose SHA-256 is
`902fb1be70fd20fb193a8f302b25d5c68a7d6a37b78db6124d84868b92151a80`.
The Git-object control validator, schedule reproduction, 12-cohort plan, four
runtime-condition reload, and exact 16-target C4 deployment gate all pass. The
provider-inert plan SHA-256 is
`af9674b99bfc18ba39eef054bdb1dc0e2e0ee0cef8372e52f67040db45d1a884`.
No provider contact or protected-data access occurred.

## 2026-08-30 — D-162: Bind multi-database C3 to one frozen semantic-model set

### Observation and hypothesis

Freeze-B preflight exposed a general identity mismatch before any provider or
sealed action: C3 records one semantic-model digest, while the runtime loads a
different per-database bundle manifest. A single-database canary can satisfy
that contract, but a multi-database sealed run cannot.

Add one canonical public aggregate manifest that attests the path and digest of
every per-database C3 bundle manifest. The runtime should validate the selected
database manifest against that aggregate, retain the per-database digest in its
context identity, and compare Freeze B to the shared aggregate digest. This
keeps retrieval database-specific while making the frozen C3 identity exact and
general; any missing, duplicate, stale, or substituted manifest must fail before
model execution.

### Result

The public aggregate now attests all 18 database bundle manifests while each C3
attempt still loads and searches only its selected database bundle. The sealed
identity check binds the shared aggregate digest and retains the selected
manifest digest as a separate context component. A post-attestation manifest
mutation fails before model construction. The focused regression gate passed
217 tests; affected-module branch coverage is 84.32%, with Ruff and formatting
checks clean. No benchmark question, outcome, provider, credential, or protected
field was accessed.

## 2026-08-30 — D-163: Keep the result report synchronized with Freeze B

### Observation and hypothesis

Freeze B is complete, validated, and pushed, but the opening status in
`RESULTS.md` still said it was pending. That contradiction could make readers
mistake a completed reproducibility gate for unfinished apparatus.

Update only the current-status, held-out prerequisite, and reproducibility
language. Preserve every held-out result as pending and add the exact system,
control, and Freeze-B identities already recorded in D-161.

### Result

The report now states that Freeze B is complete and that sealed generation and
custody scoring remain. Its held-out section names only the remaining 1,068-run
and custody-release gates, and its reproducibility section records the exact
system commit, direct-child control commit, and Freeze-B SHA-256. No held-out
result, protected field, provider state, or credential was accessed or inferred.

## 2026-08-30 — D-164: Bind production dispatch to the selected sealed ID manifest

### Observation and hypothesis

After the operator rebuilt fresh Claude leases, exact pre-consumption planning
failed before receipt creation. Freeze B correctly records the matched-frame
`sealed_mvp_ids.txt`, but the production dispatch CLI exposed no selected-ID
argument and therefore called the planner with the original `test_ids.txt`
default. The explicit 89-ID planner path passed with the frozen plan SHA-256,
confirming a command-boundary omission rather than a schedule defect.

Require one explicit selected-ID path at the production dispatch boundary and
forward it to the existing exact planner. The frozen-file digest check must
remain authoritative, so an omitted, legacy, or substituted manifest fails
before approval validation or provider construction.

### Result

The CLI now requires `--test-ids` and forwards it to the plan loader. A
failure-first regression reproduced the missing option, then proved the exact
selected path is forwarded and omission is rejected. The focused CLI gate
passes six tests; the broader dispatch, plan, production-factory, runtime-input,
and Freeze-B boundary suite passes 130 tests in 102.78 seconds. Ruff and format
checks pass. No receipt, consumption marker, output root, provider request,
credential content, protected field, or sealed outcome was created or accessed.

## 2026-08-30 — D-165: Restore the proven system CA in sealed PostgreSQL setup

### Observation and hypothesis

The first exact sealed-final-v1 dispatch consumed its receipt, then stopped on
the first direct PostgreSQL privilege attestation before that worker reached an
evaluated query. Code comparison found one general difference from the proven
public direct loader: both private JSON schemas contain the same six PostgreSQL
fields, but the public loader adds
`PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt` before constructing the
attested transport, while the sealed duplicate did not. The transport requires
that field and otherwise sanitizes connection failures into the observed
attestation error.

Make the sealed loader add the same fixed system CA after validating the exact
mode-0600 six-field private file. Do not change the private schema, database
identity, privilege checks, credentials, query path, or any database-specific
rule.

### Result

A failure-first test reproduced the missing field. The sealed loader now returns
the six validated private values plus the same fixed system CA used by the
proven direct baseline. The focused factory, PostgreSQL transport, and baseline
loader gate passes 51 tests; the broader dispatch, plan, production-factory,
runtime-input, direct-factory, transport, and Freeze-B suite passes 170 tests in
105.96 seconds. Ruff and format checks pass.

The failed run is immutable: its correction-forward receipt was consumed once,
one concurrent generation staged before the error propagated, zero cohorts
finalized, and no dispatcher remains. No generation was rerun, no correctness
or protected field was read, and no credential or lease content was inspected.
A continuation must record a successor Freeze B, reconcile the one staged
envelope, and use a fresh exact receipt for the remaining attempts.

## 2026-08-30 — D-166: Bind C2 to its aggregate HKB manifest

### Observation and hypothesis

The fixed-system v2 dispatch passed PostgreSQL privilege attestation, confirming
D-165, then stopped before model execution because the constructed C2 runtime
did not match Freeze B. Public identity inspection isolated the mismatch:
Freeze B records the aggregate `semantic_models/public_ir/manifest.json`
digest, while the adapter compared it to the selected database's HKB payload
digest. `DirectContextIdentity` already retains both as `hkb_manifest` and
`hkb`; the sealed check selected the wrong component. This is the C2 analogue
of the aggregate-versus-selected C3 correction in D-162.

Compare C2 Freeze B only to `hkb_manifest`. Keep the selected `hkb` digest in
the runtime context identity so per-database payload substitution still fails
its own exact binding. Do not change retrieval, HKB content, prompt, model,
budget, database, or any database-specific rule.

### Result

A failure-first test now gives C2 distinct selected-payload and aggregate-
manifest digests; the old mapping fails and the corrected mapping passes. C1
continues to require no semantic digest, and C3 continues to bind its aggregate
semantic-model set. The focused adapter/public-context gate passes 33 tests;
the broader dispatch, planner, production, direct, PostgreSQL, and Freeze-B
boundary suite passes 203 tests in 107.79 seconds. Ruff and format checks pass.

V2 is immutable with three staged generations, zero finalized cohorts, and one
consumed receipt. No failing worker reached model execution, no correctness or
protected field was read, and no credential or lease content was inspected. A
new final system identity must exclude v2 and run the full fixed schedule under
a fresh exact receipt.

## 2026-08-30 — D-167: Preserve and reconcile a sealed C4 capture-contract stop

### Observation and hypothesis

The exact `sealed-final-v3` dispatcher staged 32 immutable attempts, then
stopped with zero finalized cohorts when one C4 capture returned the frozen
`response_contract_error` class. Shape-only trace inspection showed successful
job submission, polling to `COMPLETE`, result retrieval, and then the capture
contract failure. No question, response value, generated SQL, result row,
annotation, label, or correctness was opened.

The frozen harness classifies this error as benchmark infrastructure and leaves
the attempt unstaged. Therefore the registered correction-forward path is a
fresh exact receipt for the same system, control, run ID, and output root. Its
preflight must reconcile the 32 immutable envelopes and admit only the missing
coordinates. Do not restart completed attempts or change the frozen system.

### Result

V3 is preserved with 32 staged attempts, zero cohorts, one consumed receipt,
and no active dispatcher. A same-identity continuation is being prepared under
standing authorization. The immutable repository, not answer inspection,
determines the pending set.

## 2026-08-30 — D-168: Carry completed-job contract semantics into sealed C4

### Observation and hypothesis

A same-identity v3 continuation reconciled the first 32 attempts, preserved 16
more, and stopped on a different C4 `response_contract_error`. Repeated fresh
receipts would regenerate completed provider jobs and still stop the whole
dispatcher. Existing result-only C4 recovery already defines the relevant
general rule: when Omni completed result retrieval but produced no parseable
query, the outcome is an evaluated-system contract failure, not retryable model
generation.

Carry an internal `job_result_observed` bit from `OmniJobCapture` into
`OmniProbeResult`. In the sealed adapter, preserve only the exact conjunction of
an observed job result, `CONTRACT_ERROR`, `response_contract_error`, no generated
query, and no result artifact as an evaluated-system failure. Keep pre-result
contract errors, transport failures, and response errors with a generated query
unstaged for infrastructure recovery. This is the existing dev-A adjudication
rule applied consistently, not a question-specific or score-dependent change.

### Result

Failure-first tests distinguish completed/no-query jobs from true
infrastructure failures. The completed/no-query record retains
`response_contract_error`, has `failure_origin=evaluated_system`, and contains
no answer or generated query. Every other infrastructure path still raises
before staging. The focused adapter/capture gate passes 24 tests; the full
sealed, capture, and C4-recovery boundary gate passes 302 tests in 313.27
seconds. Ruff and format checks pass. V3 remains immutable with 48 staged
attempts, zero cohorts, two consumed receipts, and no dispatcher; it is excluded
from the successor full run.

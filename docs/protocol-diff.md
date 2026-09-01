# Freeze A amendment and execution status

> **Corrected 2026-08-31 (D-211).** This document describes the governed query
> path as a "raw-SQL rewrite path" taken on every attempt, with `join_via_map`
> empty as evidence that no query composed. That reading does not survive
> remeasurement. `rewriteSql` is Omni's documented default for any query carrying
> `userEditedSQL`, so it is true on all 661 parseable governed attempts and
> discriminates nothing; `join_via_map` is populated on topic readback, not on
> query submission, so its count of zero measured a field this pathway never
> sets. The authored SQL references the deployed model through `${view.field}`
> templating on 660 of 661 attempts, and most attempts also take the model's join
> scope through `join_paths_from_topic_name` (69.6% dev-A C4, 98.5% C5). What the
> model never supplied is the metric: an aggregate hand-written over a field
> reference appears on 34.1% of dev-A C4 and 38.1% of C5, which is Omni's
> documented signal for a topic with no measure. Corrected counts:
> [`governed-query-path-tally-v2.json`](../experiments/analysis/governed-query-path-tally-v2.json).
> The text below is left as the record of what was measured and published.

Status date: 2026-08-27. No private or sealed label has been accessed.

## Already compliant before the amendments

- Actual public population: 480 total, 332 Query, 148 Management, 18 databases;
  no use of absent `difficulty_tier`.
- Deterministic question-level 231/101 split with every database in both,
  database-first allocation, `high_level` balance, and public condition audits.
- Hard human custody, dev-A-only private release, aggregate-only dev-B guardian
  receipts, and no held-out hidden fields in development.
- Public-only pre-supervision baseline requirement.
- C1-C4 condition definitions, C4 production-fidelity priority, three one-shot
  repetitions, 1,212 generated outputs before scoring, no majority vote, and
  prespecified retry/infrastructure ownership.
- Question-generalization estimand and development-only LOODO positioning.

## Changed for Freeze A

- Added deterministic 154-question `dev-A` / 77-question `dev-B` split and
  transparent allocation diagnostics. Routine adaptation is dev-A-only; dev-B
  is an explicit, metered checkpoint gate.
- Distinguished Freeze A (pre-gold protocol) from Freeze B (pre-test system).
- Updated endpoints to C4 mean one-shot accuracy across three repetitions and
  paired C4-C1 as the primary product/comparative perspectives; rung contrasts
  are exploratory and C4-C3 is system-level without parity.
- Pinned an executable statistical plan: 95% question-clustered percentile
  bootstrap, 10,000 deterministic SHA-256 draws, exact nearest-rank convention,
  and repetition-one McNemar sensitivity with the primary contrast separate from
  the Holm-corrected exploratory rung family.
- Added the three-state attempt outcome: correct, wrong, or refused/errored.
- Added independent content and intervention provenance plus per-condition
  tuning-effort records.
- Preregistered official Soft EX and a corrected sensitivity scorer, sealed SQL-
  template overlap analysis, and separate blinded adjudication sensitivity.
- Verified from the public LiveSQLBench-Agent that normal HKB access is database-
  level discovery, not hidden question-specific knowledge IDs.
- Replaced scalar hill climbing with surface-typed, trace-driven experiments,
  dev-A regression control, branching lineage, non-weighted Pareto promotion,
  generality labels, and human control of protocol/custody/scoring surfaces.
- Added contemporaneous `research-log.md`, a living `failure-taxonomy.md`, and an
  evidence-only product-findings template.
- Added a fail-closed per-attempt cost/failure telemetry contract, private trace
  references, and `harness-disclosure.md`. Missing metrics require explicit
  unavailable/degraded provenance rather than zero defaults.
- Bound the production experiment ledger and dev-B checkpoint candidate identity
  to separate immutable generation and score artifacts. Joined correctness must
  agree with the generation terminal state; neither file can be silently edited
  or substituted after its hash is recorded.
- Bound every scaled generation to a condition-specific canonical `run.json`,
  including explicit semantic-model revision identity, and replaced the mixed
  telemetry smoke file with four independently manifested C1-C4 bundles. The C4
  adapter now emits a complete unscored attempt and private raw-JSON result
  sidecar or a terminal evaluated-system failure. CSV is retained only for
  response-contract integrity because it cannot preserve scoring value types.
- Pinned the exact Omni CLI version and executable SHA-256 in the C4 condition;
  the probe resolves and reuses that verified binary rather than trusting a
  same-version executable found earlier on PATH.
- Replaced raw per-question dev-B checkpoint artifacts in the development
  control plane with signed, hash-bound, replay-resistant aggregate guardian
  receipts. Receipt consumption is dual-recorded and must be committed before a
  later checkpoint, preventing local marker deletion from resetting the budget.
  The signing key remains outside agent scope.

## Unresolved after Freeze A infrastructure

These are execution work, not reasons to expand the protocol further:

- The human custodian's externally generated dev-B guardian public-key digest is
  now pinned; its private key remains outside agent scope.
- After the Freeze A protocol commit, add the non-self-referential
  `experiments/freeze-a.json` hash record in a second commit before releasing any
  hidden development label.

- Generate the actual public-only HKB-to-Omni baseline and immutable 231 outputs.
- Provision/fingerprint the benchmark databases and prove Omni/scorer snapshot
  parity.
- Implement semantic transformation provenance and measure HKB coverage,
  dependency preservation, representability, and discoverability.
- Produce the first full dev-A scored run, observed failure counts, regression
  seeds, and evidence-backed product findings.
- Run several explanatory successes and failures, then limited dev-B checkpoints.
- Establish competent C1-C3 baselines, run the production-fidelity C4 adapter
  against a live instance, identify C4 model/tier observability, and record
  tuning effort.
- Bind C3/C4 Freeze-B runs to a content-addressed semantic-model export or an
  immutable Omni revision; the contract smoke's mutable branch identity alone
  is not sufficient for final-run provenance.
- Freeze B, generate the scheduled 1,212 outputs, score them under the sealed
  boundary, and write the concise research/product narrative.

## Current optimization status

- **Available surfaces:** public split/custody/control-plane code and documented
  textual, structural, and human-controlled categories. No Omni semantic-model
  candidate has been generated yet.
- **Trace data captured:** none from Omni runs. The normalized schema now covers
  full observable cost/failure telemetry and fixed diagnostic stages. Synthetic
  C4 success/failure traces and complete attempt artifacts validate; a live
  four-condition public smoke gate must still pass before scaled execution.
- **Regression mechanism:** dev-A-only append-only capability cases with a
  preservation gate are being integrated; it has no cases until the baseline and
  first accepted fix.
- **Candidate selection:** branching lineage and non-dominated comparison are
  being integrated; there is no current winner or Pareto set because no system
  has run.
- **Current top failure classes:** unknown before baseline. The leading risk
  hypotheses are HKB dependency composition, semantic discoverability, and
  compilation/validation fidelity; they are not reported as observed failures.
- **Highest-information next experiment:** generate the mechanical public-only
  HKB-to-Omni model and baseline outputs, then use the first scored full dev-A run
  to locate each HKB-linked failure on the seven-step mechanism ladder. This
  distinguishes representation, retrieval, reasoning, compilation, and
  validation explanations before tuning any of them.

## Parallel execution model

About two thirds of the remaining engineering is parallelizable; the adaptive
hypothesis/change/evaluation chain is intentionally serial. With four agent slots,
use one integration owner plus three isolated lanes:

1. database provisioning, reset, and snapshot-parity canaries;
2. mechanical HKB intermediate representation and Omni model generation;
3. harness work—initially scoring/telemetry, then competent C1-C3 comparators and
   C4 production integration in disjoint configurations.

Independent agents may later analyze sanitized dev-A traces by database and
propose competing hypotheses, but only one registered intervention is integrated
into a candidate at a time. A dev-B guardian evaluates selected frozen candidates
and never proposes changes. The sealed test evaluator receives labels only after
Freeze B and releases no correctness until every output is generated. No agent
both develops and certifies the same artifact.

## Post-Freeze-A deviation, 2026-08-29: the optimization phase is cut

**What changed.** The supervised development phase in "Baseline and supervised
development" and the "Train-only autoresearch extension" are cut from the
executed study. No dev-A-supervised intervention is promoted, no dev-B
checkpoint is consumed, no experiment reaches a KEEP or REVERT decision, and the
final candidate carried into Freeze B is the frozen mechanical baseline.

**What the executed system is.** The mechanical public-only transformation plus
general compiler corrections driven by the Omni validator: structured-leaf
extraction operators, negative-scale numeric literals, physical identity
collapse, case normalization, and alias handling. Each has content provenance
`public schema` and intervention provenance `generic product improvement`. None
has content provenance `development gold` or intervention provenance `dev-A
failure`. The two provenance axes were preregistered precisely so this claim is
checkable rather than asserted.

**What dev-A was used for.** Diagnosis and reporting only: the C1-C3 accuracy
figures, the refusal and budget-exhaustion census, the registered budget
clustering test, the E01 audit. No dev-A outcome modified a runtime artifact.
The released dev-A gold remains offline diagnostic input as the information
tiers require.

**Reason.** The deployment and authorization surface consumed the schedule. Five
semantic deployment passes and five C4 run identities were spent before any
governed accuracy existed, because each live defect cost a full single-use
human-authorization cycle. The optimization phase sat behind that surface and
was never reached. This is recorded as a product finding, not hidden as a gap.

**Why it cannot bias the primary contrast.** The cut is decided on schedule
cost, not on observed accuracy, and it removes a system-improvement step from
every condition equally rather than selecting among outcomes. It can only lower
expected C4, which is the condition the study exists to test; it cannot
manufacture a favorable C4-C1 contrast. The alternative reading, that
optimization was abandoned because C3 underperformed C2 on the direct baseline,
is available to a reader and is answered by the contemporaneous ledger: the five
spent identities and their failure classes predate and explain the decision.

**What is still reported.** E01 as audited and inconclusive; E02 as a compiled,
hash-bound, never-evaluated candidate; both with their artifacts intact. The
sealed C1-C4 evaluation, dual scoring, endpoints, split, custody, and scorer
definitions are unchanged. Freeze B still occurs; it records the baseline as the
final candidate.

**Consequence for description.** The executed system receives no question-level
supervision. It must not be described as tuned, adapted, or dev-A-supervised.

## Post-Freeze-B deviation, 2026-08-30: restore a lean optimization demonstration

**What changed.** Stephanie clarified before any sealed correctness release that
the MVP must demonstrate whether optimization/tuning can improve Omni. The
2026-08-29 cut remains the historical explanation for why the mechanical
baseline was frozen and launched first, but it no longer defines the complete
MVP. That system is retained as an explicitly untuned baseline. A bounded
successor track adapts only on dev-A, may use only sparse aggregate dev-B
checkpoints, freezes one optimized candidate, and adds one optimized C4 held-out
arm on the already-selected matched frame.

**Contamination control.** `sealed-final-v6` generation may finish, but neither
its attempt contents nor any sealed correctness may enter development. The
optimized candidate must be frozen and its held-out outputs generated before
custody releases either arm's correctness. The sealed IDs, scorers, endpoints,
and no-retry policy remain fixed. No test outcome, dev-B per-question outcome,
question-specific rule, or database-name rule may drive a change.

**Interpretation.** The original C1-C4 run estimates the performance of the
untuned mechanical system. The added arm estimates the performance of one
explicitly dev-A-optimized Omni candidate under the same held-out membership.
This is a transparent post-Freeze-B protocol extension, not a replacement of
the baseline and not iterative hillclimbing on the test set. The report must
separate the preregistered baseline comparison from the later optimization
demonstration and disclose their different freeze times.

## Post-Freeze-A deviation, 2026-08-29: matched 89-question sealed frame

**What changed.** Before any sealed generation, test-label release, or test
outcome access, the executed sealed population was reduced from the committed
101-question/18-database split to the 89 questions assigned to the 16 databases
with verified governed C4 deployments. All four conditions and all three
repetitions use the same membership, producing 1,068 scheduled outputs.

**Why.** The pinned official LiveSQLBench loader omits every physical table used
by the mechanical semantic bundles for `mental_healths_large` and
`organ_transplant_large`. The 12 sealed questions assigned to those databases
therefore have no honest non-empty C4 deployment under the frozen compiler.
Restoring omitted tables would break official-loader comparability; deploying
empty models or counting the coordinates as system failures would misstate the
evaluated system. Waiting for a new compiler mechanism would put the MVP back on
an open-ended product path after the final candidate was selected.

**Decision and timing.** Stephanie selected option A in
`omni-benchmark-ei0.9.1.1` before Freeze B and before any sealed outcome existed.
The choice used only public split membership by database and public loader and
deployment evidence. It did not use question content, gold SQL, hidden
annotations, correctness, or dev-B information.

**Consequence for interpretation.** The primary and rung comparisons remain
paired because membership is identical across C1-C4. The estimand is narrower:
performance on the 16 officially loadable databases represented in the matched
frame, not all 18 databases in Large-v1. The report must disclose the 12
exclusions and may not classify them as model failures, gold failures, or
condition-specific missingness. The scorers, repetitions, retry policy, final
candidate, custody boundary, and endpoint definitions are unchanged.

## Post-Freeze-B deviation, 2026-08-30: C4 did not exercise semantic query compilation

**What changed.** Nothing in the executed system, the scorers, the split, the
custody boundary, or any recorded number. What changed is the description of what
the governed condition measures. The protocol's frozen-conditions table gives C4
the enforcement value "Enforced production harness", and `docs/methodology.md`
and `docs/harness-disclosure.md` carried the stronger reading that the production
harness enforces semantic compilation and that C4's queries are compiled through
Omni from declared model structure. Measurement on the frozen development
baseline falsifies that reading.

**What was measured.** All 135 governed semantic queries carry `rewriteSql:
true` and `aiGenerated: true` with hand-authored SQL in `userEditedSQL`, and
`join_via_map` is empty on all 135. No governed query declares a join path. The
executed structural aggregates come from that SQL, because `generated_sql` is
`null` on all 136 attempts by design. Method, evidence boundary, and per-class
counts are in `docs/c4-mechanism-measurements.md` §2 and
`docs/c4-query-path-disclosure.md`.

**Who chose the path, and whether an alternative existed.** Omni's production
agent chose it, on every attempt. The harness cannot select, request, or suppress
it: the submitted job body is exactly `modelId`, `progressWebhookEnabled`,
`prompt`, and `branchId`; the prompt is the bare `{question}`; and `rewriteSql`,
`userEditedSQL`, `join_via_map`, and `aiGenerated` appear nowhere under `src/`.
The conservative HKB compilation deferred 511 of 1,090 definitions (46.9%) as
cross-grain, so the deployed topics emit `"joins": {}` and publish no measures.
For the 62 of 133 parseable attempts spanning two or more distinct non-CTE
sources, rewrite was the only path the deployed model left open. This is a
rational agent response to the model it was given, not a scaffold defect and not
a rerun-eligible failure.

**Consequence for interpretation.** C4 minus C3 no longer differs on who composes
the query, nor on join and aggregation semantics: both arms are an agent
authoring SQL, and in neither arm does a semantic layer resolve a join path or
compile a measure. The study cannot claim it isolated semantic-layer query
composition. C4 minus C3 still differs on the agent, on field resolution at
rewrite time, on the execution contract, and on the accessible surface. The
semantic layer's measured contribution is a resolved field vocabulary: 109 of 135
attempts reference at least one compiled dimension and 39 reference at least one
HKB-backed derived dimension, while 0 attempts select exclusively compiled fields
and 97 select none. That input/output asymmetry left the planner typing output
columns of SQL it did not compose, which is the shape of the 31 `UNKNOWN`-type
terminal failures.

**Binding on the sealed arm.** The sealed C4 arm is hash-bound to the same
condition, prompt, instruction, and model-deployment artifacts
(`sealed_omni_factory.py:33-35`,
`config/sealed-omni-semantic-model-set-v1.json`), so it is expected to show the
same path. That is a prediction from committed configuration. No sealed record
has been read and none may be read before the arm completes.

**Disposition.** Disclose and reinterpret. Every published number stands; the
frame around the C4 query path is corrected in `RESULTS.md`,
`docs/harness-disclosure.md`, `docs/methodology.md`, and `docs/report-draft-v2.md`.
`EVALUATION_PROTOCOL.md` is a human-controlled frozen surface, so its C4
enforcement cell was not edited by an agent; the proposed amendment text was
put to the custodian in `docs/protocol-amendment-proposal-query-path.md`.
**Stephanie accepted that proposal on 2026-08-30, and both changes were applied
to `EVALUATION_PROTOCOL.md` verbatim**: the frozen-conditions cell at line 212
now qualifies enforcement and points at the measurement, and an addition after
the C4-C3 interpretation bullets records that the two arms do not differ on who
composes the query. Both original bullets survive unchanged. The protocol
carries no Freeze-B hash binding and is not a sealed runtime source, so the
amendment does not disturb the live sealed arm. Recorded as D-181.

**Effect on the named optimization contrast.** E02 declares FK-backed
relationships, which is the ingredient whose absence left rewrite as the only
cross-table path. E02 therefore becomes a direct test of this mechanism rather
than a correlational guess selected from relation counts. Whether E02 as built is
sufficient to move governed queries off the rewrite path is a separate open
measurement: its topics still declare no measures, so the agent may continue to
rewrite in order to aggregate. E05, which proposed declaring explicit output
types on compiled semantic fields, is recorded INCONCLUSIVE under its own
preregistered precondition. That precondition required at least 16 of the 31
class-A failures to select a compiled derived field; the measured ceiling is 6,
and 24 of 31 select no compiled bundle field of any kind.

## Post-Freeze-B deviation, 2026-08-30: score the untuned arm before completing E02

**What changed.** The untuned `sealed-final-v6` arm was scored after its complete
generation tree and the v10 split-provenance scoring control passed, but before
the E02 dev-A execution and optimized held-out arm described by the lean
optimization extension were complete. This reverses that extension's intended
ordering. It does not change the sealed population, generations, scorers,
endpoints, or any recorded answer.

**Consequence.** Aggregate held-out C1–C4 outcomes are now visible and cannot be
treated as development input. The project will not construct or select a new
optimized held-out candidate. E02 was selected and preregistered as a mechanism
contrast in D-180, and its general compiler change was committed before sealed
scoring. Only that pre-result candidate may be run on dev-A under its existing
identity. No implementation change, dev-B checkpoint, or promotion decision may
use the sealed aggregates. E02 is therefore reported as a pre-specified dev-A
contrast, not as evidence that a tuned candidate improves held-out accuracy.

**Why the primary result remains valid.** All 1,068 untuned generations were
immutable before release, both frozen scorers were published together, and no
wrong outcome was rerun. The sequencing deviation limits the optimization claim;
it does not bias the already-generated C1–C4 comparison. The report must state
this limitation directly rather than implying that the MVP completed the
original optimized-arm design.

### Correction-forward public validation after scoring

E02 deployment v4 subsequently exposed six public validator failures caused by
a general compiler omission: an absent relationship endpoint was materialized
only when normalization changed its spelling. The correction in commit
`f62d261e76e7fb9fc3bedd87e49983c111cc153a` publishes every absent endpoint as
an identity dimension and contains no database, question, label, or outcome
rule. Deployment v5 then verified and exactly read back all 16 public targets
with zero validation issues.

This is permitted only as public-schema compiler hygiene required to make the
already-preregistered E02 mechanism evaluable. It does not authorize a new
intervention, result-driven candidate selection, dev-B use, or a held-out
optimized arm. The sealed aggregates were not an input, and the immutable v4
failure remains part of the evidence.

## Post-Freeze-B deviation, 2026-08-31: result-type parity is closed and stated as a policy

**What the frozen text said.** Three statements in `docs/harness-disclosure.md`
described scorer/result-type parity as an open blocker: the C4 "Current
implementation state" cell ("scorer-type parity remains pending"), the
reference-implementation audit ("this is now an observed scale blocker, not only
a theoretical limitation"), and the capture verification gate ("scorer/result-type
parity remains a separate execution gate"). Its status line also still read that
no scaled baseline had been launched.

**What changed.** The typed result path landed on 2026-08-29 and closed the gate
by adopting a transport with authoritative field-type metadata, which is one of
the two remedies the frozen paragraph itself named. Omni's plan-only response is
the sole type authority; no type is inferred from string appearance. Parity with
the Psycopg-typed gold rows is structural, since both reach the same frozen
normalizers. Scaled generation subsequently ran to completion.

**Why this is a description correction, not a protocol change.** No measured
value, scorer version, artifact hash, or protocol surface is altered. Freeze A
history is not rewritten: the three statements are marked in place as superseded
and answered in a dated addendum at the end of the disclosure, the same treatment
given to the 2026-08-30 governed query-path correction.

**A disclosed cost, stated as policy.** `SUPPORTED_OMNI_RESULT_TYPES` is a closed
set of seven, and an unrecognized declared type fails closed as an
evaluated-system failure rather than being coerced. Of the 45 dev-A capture
failures, append-only recovery v5 recovered 11 as typed results and left 34
terminal; 31 of those 34 are attributed to an unknown planner result type. That
depresses C4 accuracy by construction, so it belongs in the disclosure as a
stated policy with its measured cost rather than as a pending gate.

**Scope note on the earlier query-path record.** The 2026-08-30 deviation above
reports 135 of 135 on the frozen development baseline, which remains correct in
its own frame. The measurement has since been extended to six governed arms:
661 of 661 parseable queries on the raw-SQL rewrite path with zero composed, of
which 261 are sealed C4 across three repetitions. See
`experiments/analysis/governed-query-path-tally-v1.json`.

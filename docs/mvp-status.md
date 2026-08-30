# MVP status and critical path

This is the high-level operator view of the Omni × LiveSQLBench evaluation.
It summarizes the durable Beads tracker and the research ledger; it does not
replace either one. Update it at every material evidence gate, blocker change,
human authorization, candidate freeze, or sealed-run transition.

Last reconciled: 2026-08-30T12:36:00-04:00 (America/New_York). Reconciliation happens at material evidence gates only, not on a daily cadence.

## Current position

The decisive governed dev-A baseline comparison has run and the mechanical
candidate is formally frozen as the **untuned baseline**. We have frozen
development evidence for direct C1-C3 and governed C4, plus a validated
89-question / 1,068-coordinate baseline Freeze B. The untuned held-out arm has
now completed generation, but its correctness remains sealed. We do **not** yet
have released sealed C1-C4 results or a frozen optimized Omni candidate.

Stephanie confirmed on 2026-08-30 that optimization/tuning is part of the MVP.
The 2026-08-29 cut remains in the historical record, but is superseded before
sealed correctness release. `omni-benchmark-ei0.11` owns the lean successor:
dev-A-only adaptation, at most sparse aggregate dev-B checkpoints, one optimized
candidate freeze, and one held-out optimized C4 arm. The active sealed run is
still the untuned baseline and cannot inform that work. Live-action
authorization is now tiered by contamination risk (`omni-benchmark-xeg`):
public semantic deployment and validation passes are agent-autonomous and
retryable under a new run ID. Standing human authorization now lets agents
materialize exact action receipts for evaluated, sealed, dev-B, protected-data,
and shared-model actions without another prompt; every binding remains exact.

The C4 control plane completed all 136 answerable attempts across 16 databases
while retaining the 18 fixed scorer-conformance exclusions. The immutable v8
selection is frozen and scored. Its official aggregate is 9 correct, 93 wrong,
34 refused/system-error, and 18 fixed unscorable out of 154 scheduled dev-A
identities. Eleven capture failures were recovered by replaying only their
already-generated semantic queries; 34 product-contract outcomes remain
explicit system failures. No question-level model reasoning was rerun.

V6 and v7 remain immutable pre-provider diagnostics with no evaluated answers.
Recovery v1-v4 remain immutable incomplete diagnostics and are excluded because
they have no recovery manifest. V8 plus recovery v5 is the sole scored C4
development result. Freeze-B preparation exposed a coverage mismatch: the
original sealed split contains all 18 databases, while the verified v13 C4
deployment set contains 16. Stephanie responded **A** to
`omni-benchmark-ei0.9.1.1` before any sealed outcome existed. The executed
sealed frame is now the matched 89-question subset on those 16 databases across
every condition and repetition, for 1,068 total coordinates. The 12 public-
loader-blocked questions are reported as a protocol deviation and scope
limitation, not as system or gold failures.

## Milestone map

| Stage | State | Evidence or remaining exit condition |
| --- | --- | --- |
| Evaluation design, public manifests, splits, and Freeze A | Complete | 332 eligible questions; 154 dev-A, 77 dev-B, and 101 sealed test identities; custody boundaries and two scorers are frozen. |
| Public C1-C3 direct baseline | Complete for the frozen baseline | Immutable generation and dev-A scoring exist. Official accuracy on the 122 scoreable-question intersection is C1 7.4%, C2 23.8%, C3 13.1%. The append-only nine-question cybermarket recovery, `omni-benchmark-dih.5.4.2.4.4.2.2.6`, is still outstanding and must not rewrite the frozen artifacts. |
| Train-only gold release | Complete | Exactly 154 dev-A records were released through custody; the complete source was removed from the host transfer area. Test gold and dev-B outcomes remain unavailable to development. |
| Public semantic compiler and deployment preparation | Complete | V13 validates and exactly reads back all 16 answerable databases in one current evidence set. The two official-loader exclusions remain explicit rather than fabricated. |
| C4 baseline | Complete and scored | V8 completed 136 executable attempts. Official aggregate: 9 correct, 93 wrong, 34 refused/system-error; 18 of 154 scheduled identities are fixed unscorable. Selection SHA-256 `256145c1…5cc`; recovery-manifest SHA-256 `5d6ff474…fd9f`; score-receipt SHA-256 `0296753e…0a78`. |
| Minimal dev-A experiment set | **E02 deployment 15/16; general polar fix prepared** | Aggregate-only failure analysis selected the preregistered relationship/grain intervention. Immutable deployment v2 exposed request-pressure failures; paced v3 exact-read back 15 targets and isolated ten broken camel/mixed-case relationship endpoint references on polar. A general stable-ID-driven alias fix is locally tested but not yet committed or redeployed. KEEP still requires all 16 deployments and the full 136-answerable dev-A comparison. |
| Untuned candidate and baseline Freeze B | **Complete** | Baseline system `8b0c739…`, direct-child control `94cc0d9…`, Freeze-B SHA-256 `e1c9f196…ae4730`; 108 frozen files and all 1,068 schedule coordinates reproduce from Git objects. |
| Untuned sealed C1-C4 evaluation | **Generation complete; correctness sealed** | V1-v5 remain immutable and excluded. V6 terminated with exactly 1,068 attempt envelopes, 12 generation manifests, and 12 run manifests; its dispatcher is absent. Receipt `e0a6ba14…f5c97a` was consumed once. No attempt content or correctness was opened, and the arm remains correctness-blind during optimization. |
| Optimized candidate and held-out arm | **Planned** | Adapt on dev-A only; optionally consume sparse aggregate dev-B checkpoints; freeze one candidate; generate one additional optimized C4 arm on the same preselected 89-question frame before any sealed correctness release. |
| Results/product report | Draft only | `RESULTS.md` already contains the design, direct baseline, failure analysis, and product findings. Replace every pending governed/sealed result after the immutable aggregates exist, then finish the concise submission-ready report. |

## What is already usable

- The frozen direct-SQL and governed C4 development results are real and can be
  discussed with their stated scopes and exclusions.
- The public HKB/compiler analysis and failure-mechanism evidence are real.
- The E01 no-op finding and the offline E02 candidate construction are real.
- The sealed dispatcher, scorer, and report handoff are tested infrastructure,
  not benchmark outcomes.

The clearest current interpretation is: searchable raw business knowledge (C2)
was strongest in the frozen direct baseline, while governed C4 produced 9
correct answers among 136 scoreable attempts and exposed 34 semantic-layer
contract failures. On the exact 122-question intersection shared by all four
conditions, C4 is 5/122 (4.1%), compared with C1 at 9/122 (7.4%), C2 at 29/122
(23.8%), and C3 at 16/122 (13.1%). The paired descriptive C4-C1 difference is
-3.3 percentage points. This alignment confirms the low C4 result is not a
denominator artifact; it remains exploratory development evidence rather than
the held-out comparison.

## Blocking and waiting

### Waiting on the operator now

Nothing. The lease rebuild completed just after the 07:00 credential refresh on
2026-08-30. The first sealed-final-v1 dispatch stopped on a general missing-CA
infrastructure bug after one generation staged and before any cohort finalized.
V2 then stopped on a general C2 aggregate-versus-selected HKB identity mismatch
before model execution, after three generations staged and before any cohort
finalized. The correction is frozen. Exact `sealed-final-v3` preflight passed
and its receipt was consumed once. The dispatcher then preserved 32 attempts
before a frozen capture-contract infrastructure stop; no dispatcher remains.
The same-identity continuation dry preflight reconciled exactly 32 and admitted
1,036; its receipt was consumed once and it preserved 16 more attempts before a
different completed-job contract stop. No dispatcher remains. The general
completed/no-query consistency fix is agent-owned and tested; no callback,
protected file, or additional authorization is needed.

### Agent-owned work now

- Execute the bounded dev-A optimization loop under `omni-benchmark-ei0.11`,
  beginning with the E02 relationship candidate. Commit the general relationship
  endpoint-alias fix, redeploy all 16 schedule-selected public models under a
  fresh exact run identity, run the 136-attempt dev-A comparison, freeze one
  optimized candidate, and generate its held-out C4 arm while all sealed
  correctness remains unavailable.
- Finish the aligned development comparison table and concise results/product
  report from immutable aggregates.
- Commit and publish reviewed work through `main` only. Worktree cleanup under
  `omni-benchmark-9v3` is not on the MVP critical path.

### Later exact gates

The agent may materialize exact optimization, checkpoint, freeze, and sealed-
action receipts under standing authorization when their bound inputs exist.

### Non-critical-path or deferred work

LODO, extensive template audits, optimizer-framework work, publication-grade
statistical extras, comparator polish, and protocol-paper expansion stay
deferred unless they directly block the MVP. The cybermarket append-only direct
baseline recovery is useful denominator repair and should be completed when its
isolated direct lane is safe, but it does not replace the C4 critical path.

## Definition of MVP complete

The MVP is complete only when all of the following are true:

1. The public C4 baseline is validated, immutably captured, frozen, and scored
   under the 154-scheduled/136-answerable frame.
2. A bounded dev-A optimization loop produces immutable KEEP/REVERT/
   INCONCLUSIVE evidence and freezes one optimized candidate; any dev-B use is
   aggregate-only and sparse.
3. The untuned and optimized candidates are frozen before their respective
   sealed execution, and no sealed correctness is released between them.
4. The twelve untuned C1-C4 cohorts and the optimized C4 arm finish; the two
   frozen scorers produce identity-safe aggregates through custody.
5. `RESULTS.md` reports the actual untuned, optimized, and sealed comparisons, product
   findings, limitations, and exact artifact lineage with no pending numeric
   placeholders.

## Sources of truth

- `bd show omni-benchmark-ei0` — durable MVP issue tree.
- `bd human list` — live operator decision queue.
- [research-log.md](research-log.md) — contemporaneous hypotheses and outcomes.
- [human-decisions.md](human-decisions.md) — exact current authorization scope.
- [../RESULTS.md](../RESULTS.md) — results-first report draft.
- `.dashboard/index.html` — local visual snapshot; ignored and regenerated at
  major gates.

This file must never contain private gold, per-question dev-B outcomes, hidden
test annotations, sealed correctness, credentials, or credential locations.

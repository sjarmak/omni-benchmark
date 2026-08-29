# MVP status and critical path

This is the high-level operator view of the Omni × LiveSQLBench evaluation.
It summarizes the durable Beads tracker and the research ledger; it does not
replace either one. Update it at every material evidence gate, blocker change,
human authorization, candidate freeze, or sealed-run transition.

Last reconciled: 2026-08-29T18:51:00-04:00 (America/New_York).

## Current position

The evaluation infrastructure is largely implemented, but the decisive
governed comparison has not run. We have shareable development evidence for the
direct C1-C3 conditions. We do **not** yet have C4 accuracy, a frozen final
candidate, or sealed C1-C4 results.

The optimization phase is cut (`omni-benchmark-ivg`, Stephanie 2026-08-29). No
dev-A-supervised intervention is promoted and no dev-B checkpoint is consumed;
the final candidate is the frozen mechanical baseline. The deviation and its
reasoning are recorded in [protocol-diff.md](protocol-diff.md). Live-action
authorization is now tiered by contamination risk (`omni-benchmark-xeg`):
public semantic deployment and validation passes are agent-autonomous and
retryable under a new run ID, while evaluated-answer, dev-B, protected-data, and
shared-model actions still need one exact human authorization each.

The corrected C4 control plane is complete: it schedules all 154 dev-A
identities, executes 136 answerable identities across 16 databases, and retains
the 18 fixed scorer-conformance exclusions explicitly through freeze and score
artifacts. The public deployment prerequisite is complete: v12 verified polar
with zero validation issues and exact readback, bringing the answerable frame to
16 of 16 databases. The immediate critical path is one exact human authorization
for the 136-attempt C4 dispatch, followed by freeze and scoring.

No C4 dispatch is currently authorized. The exact fixed-frame v6 package is
ready under `omni-benchmark-ei0.4.12`; the obsolete v5 package must not be used.

## Milestone map

| Stage | State | Evidence or remaining exit condition |
| --- | --- | --- |
| Evaluation design, public manifests, splits, and Freeze A | Complete | 332 eligible questions; 154 dev-A, 77 dev-B, and 101 sealed test identities; custody boundaries and two scorers are frozen. |
| Public C1-C3 direct baseline | Complete for the frozen baseline | Immutable generation and dev-A scoring exist. Official accuracy on the 122 scoreable-question intersection is C1 7.4%, C2 23.8%, C3 13.1%. The append-only nine-question cybermarket recovery, `omni-benchmark-dih.5.4.2.4.4.2.2.6`, is still outstanding and must not rewrite the frozen artifacts. |
| Train-only gold release | Complete | Exactly 154 dev-A records were released through custody; the complete source was removed from the host transfer area. Test gold and dev-B outcomes remain unavailable to development. |
| Public semantic compiler and deployment preparation | Complete | All 16 answerable databases validate with exact readback; polar v12 verified the authenticated identity projection. The two official-loader exclusions remain explicit rather than fabricated. |
| C4 baseline | Ready for authorization | The 154-scheduled/136-answerable control path and all answerable deployments are ready. Obtain one exact C4 authorization, dispatch 136 attempts, freeze the run, and score it while reporting all 154 scheduled identities and 18 fixed exclusions. |
| Minimal dev-A experiment set | **Cut from the MVP** | E01 audited as already present in the baseline, inconclusive. E02 compiled, hash-bound, never evaluated. Both are reported as-is with artifacts intact; neither enters the final system. Deviation recorded in `docs/protocol-diff.md`. |
| Final candidate and Freeze B | Tooling ready; candidate now determined | With the optimization phase cut, the final candidate is the frozen mechanical baseline. Record the freeze and control commit and bind the human-controlled sealed schedule seed. |
| Sealed C1-C4 evaluation | Tooling ready; not run | The 12-cohort generation, immutable manifests, dual scoring, and aggregate handoff are implemented and tested. They cannot run until Freeze B and the sealed custody gates are satisfied. |
| Results/product report | Draft only | `RESULTS.md` already contains the design, direct baseline, failure analysis, and product findings. Replace every pending governed/sealed result after the immutable aggregates exist, then finish the concise submission-ready report. |

## What is already usable

- The frozen direct-SQL development result is real and can be discussed with its
  stated scope and exclusions.
- The public HKB/compiler analysis and failure-mechanism evidence are real.
- The E01 no-op finding and the offline E02 candidate construction are real.
- The sealed dispatcher, scorer, and report handoff are tested infrastructure,
  not benchmark outcomes.

The clearest current interpretation is: searchable raw business knowledge (C2)
outperformed both raw schema (C1) and the searchable compiled model (C3) on the
frozen direct baseline, while the experiment that tests governed enforcement
(C4) remains pending.

## Blocking and waiting

### Waiting on the operator now

One action: choose A by running the exact two-line v6 authorization command in
`docs/human-decisions.md`, or choose B to hold. A creates a one-hour receipt but
does not launch; paste its JSON output back into chat. No credential, callback,
token, profile, or lease information is needed.

### Agent-owned work now

- Once the exact v6 receipt arrives, validate and dispatch C4 once, then freeze
  and score without adding another development loop.
- Commit and publish reviewed work through `main` only. Worktree cleanup under
  `omni-benchmark-9v3` is not on the MVP critical path.

### Later exact gates

These are not requests for action yet: a new C4 dispatch authorization after
the frame and deployment gates pass; the Freeze-B record and schedule seed; and
sealed generation/scoring custody authorization. E02 deployment authority is no
longer on the path.

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
2. The E01 audit and the unevaluated E02 candidate are reported as-is, with the
   cut optimization phase and its reasoning recorded in `docs/protocol-diff.md`.
3. The final candidate and Freeze B are recorded before sealed execution.
4. All twelve sealed C1-C4 cohorts finish and the two frozen scorers produce
   identity-safe aggregates through custody.
5. `RESULTS.md` reports the actual governed and sealed comparisons, product
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

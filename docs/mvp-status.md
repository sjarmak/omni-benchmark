# MVP status and critical path

This is the high-level operator view of the Omni × LiveSQLBench evaluation.
It summarizes the durable Beads tracker and the research ledger; it does not
replace either one. Update it at every material evidence gate, blocker change,
human authorization, candidate freeze, or sealed-run transition.

Last reconciled: 2026-08-29T15:30:00-04:00 (America/New_York).

## Current position

The evaluation infrastructure is largely implemented, but the decisive
governed comparison has not run. We have shareable development evidence for the
direct C1-C3 conditions. We do **not** yet have C4 accuracy, an evaluated E02
intervention, a frozen final candidate, or sealed C1-C4 results.

The immediate critical path has two parallel prerequisites:

1. Finish `omni-benchmark-ei0.4.10`, which corrects the active C4 control plane
   from the obsolete 129-attempt/10-database frame to the human-approved frame:
   154 dev-A questions scheduled, 136 answerable questions executed across 16
   databases, and 18 fixed scorer-conformance exclusions retained explicitly.
2. Receive decision **A** on `omni-benchmark-dih.17.12`, then perform exactly one
   append-only v9 deployment, validation, and exact-readback pass over the 16
   answerable public semantic bundles. Decision **B** holds without product
   contact. See [human-decisions.md](human-decisions.md) for the exact scope.

No C4 dispatch is currently authorized. The obsolete ten-database v5 package
must not be used.

## Milestone map

| Stage | State | Evidence or remaining exit condition |
| --- | --- | --- |
| Evaluation design, public manifests, splits, and Freeze A | Complete | 332 eligible questions; 154 dev-A, 77 dev-B, and 101 sealed test identities; custody boundaries and two scorers are frozen. |
| Public C1-C3 direct baseline | Complete for the frozen baseline | Immutable generation and dev-A scoring exist. Official accuracy on the 122 scoreable-question intersection is C1 7.4%, C2 23.8%, C3 13.1%. The append-only nine-question cybermarket recovery, `omni-benchmark-dih.5.4.2.4.4.2.2.6`, is still outstanding and must not rewrite the frozen artifacts. |
| Train-only gold release | Complete | Exactly 154 dev-A records were released through custody; the complete source was removed from the host transfer area. Test gold and dev-B outcomes remain unavailable to development. |
| Public semantic compiler and deployment preparation | In progress at the final validation gate | Fourteen of 16 answerable databases have immutable exact-readback evidence. General fixes for the remaining planets and polar mechanisms are fully tested; v9 must validate the current bytes for all 16 answerable bundles. |
| C4 baseline | Not run | First finish the corrected 154/136 frame and obtain 16-database v9 validation. Then prepare and obtain a fresh exact C4 authorization, dispatch 136 answerable attempts, freeze the run, and score it while reporting all 154 scheduled identities and 18 fixed exclusions. |
| Minimal dev-A experiment set | Offline candidate ready; accuracy not run | E01 was audited as already present in the baseline and is therefore inconclusive. E02's general relationship candidate is compiled and locally authenticated. After C4 freezes, deploy and evaluate E02 under separate authority; preserve the result even if it fails. |
| Final candidate and Freeze B | Tooling ready; decision not made | Select the final candidate only from the preregistered evidence, record the freeze and control commit, and bind the human-controlled sealed schedule seed. |
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

Only `omni-benchmark-dih.17.12` is in the human queue. Reply **A** or **B** in
chat. No command, credential, callback, token, profile, or lease information is
needed.

### Agent-owned work now

- Complete and fully test `omni-benchmark-ei0.4.10` without any provider or
  protected-data access.
- Keep the v9 execution worktree provider-inert until an A response is recorded.
- Preserve the dirty main worktree and make scoped commits from
  `codex/mvp-current` only.

### Later exact gates

These are not requests for action yet: a new C4 dispatch authorization after
the frame and deployment gates pass; separate E02 deployment/evaluation
authority; the final candidate/Freeze-B decision and schedule seed; and sealed
generation/scoring custody authorization.

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
2. The minimal dev-A trajectory contains the E01 audit, one immutable E02 result,
   and an evidence-based keep/revert decision.
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

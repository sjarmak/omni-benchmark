# MVP status and critical path

This is the high-level operator view of the Omni × LiveSQLBench evaluation.
It summarizes the durable Beads tracker and the research ledger; it does not
replace either one. Update it at every material evidence gate, blocker change,
human authorization, candidate freeze, or sealed-run transition.

Last reconciled: 2026-08-29T21:38:00-04:00 (America/New_York).

## Current position

The decisive governed dev-A comparison has now run. We have frozen development
evidence for direct C1-C3 and for governed C4. We do **not** yet have the formal
Freeze B record or sealed C1-C4 results.

The optimization phase is cut (`omni-benchmark-ivg`, Stephanie 2026-08-29). No
dev-A-supervised intervention is promoted and no dev-B checkpoint is consumed;
the final candidate is the frozen mechanical baseline. The deviation and its
reasoning are recorded in [protocol-diff.md](protocol-diff.md). Live-action
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
development result. Freeze-B preparation exposed one remaining coverage
prerequisite: the sealed schedule contains all 18 databases, while the verified
v13 C4 deployment set contains only the 16 dev-A-answerable databases. The
dev-A exclusion cannot be reused as a sealed-test exclusion. Human decision
`omni-benchmark-ei0.9.1.1` now selects either a matched 89-question sealed MVP or
retention of the all-101 frame with additional compiler/deployment work.

## Milestone map

| Stage | State | Evidence or remaining exit condition |
| --- | --- | --- |
| Evaluation design, public manifests, splits, and Freeze A | Complete | 332 eligible questions; 154 dev-A, 77 dev-B, and 101 sealed test identities; custody boundaries and two scorers are frozen. |
| Public C1-C3 direct baseline | Complete for the frozen baseline | Immutable generation and dev-A scoring exist. Official accuracy on the 122 scoreable-question intersection is C1 7.4%, C2 23.8%, C3 13.1%. The append-only nine-question cybermarket recovery, `omni-benchmark-dih.5.4.2.4.4.2.2.6`, is still outstanding and must not rewrite the frozen artifacts. |
| Train-only gold release | Complete | Exactly 154 dev-A records were released through custody; the complete source was removed from the host transfer area. Test gold and dev-B outcomes remain unavailable to development. |
| Public semantic compiler and deployment preparation | Complete | V13 validates and exactly reads back all 16 answerable databases in one current evidence set. The two official-loader exclusions remain explicit rather than fabricated. |
| C4 baseline | Complete and scored | V8 completed 136 executable attempts. Official aggregate: 9 correct, 93 wrong, 34 refused/system-error; 18 of 154 scheduled identities are fixed unscorable. Selection SHA-256 `256145c1…5cc`; recovery-manifest SHA-256 `5d6ff474…fd9f`; score-receipt SHA-256 `0296753e…0a78`. |
| Minimal dev-A experiment set | **Cut from the MVP** | E01 audited as already present in the baseline, inconclusive. E02 compiled, hash-bound, never evaluated. Both are reported as-is with artifacts intact; neither enters the final system. Deviation recorded in `docs/protocol-diff.md`. |
| Final candidate and Freeze B | Waiting on sealed-frame decision | The candidate is fixed. Choose matched 89-question execution across the 16 verified databases, or retain all 101 and wait for two new non-empty C4 deployments. Then bind the human-controlled schedule seed and record the freeze/control commits. |
| Sealed C1-C4 evaluation | Tooling ready; not run | The 12-cohort generation, immutable manifests, dual scoring, and aggregate handoff are implemented and tested. They cannot run until Freeze B and the sealed custody gates are satisfied. |
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
contract failures. C1-C3 percentages currently use a 122-question scoreable
intersection, so a headline C4-versus-C1-C3 delta should wait for the aligned
report table rather than comparing mismatched denominators.

## Blocking and waiting

### Waiting on the operator now

No further action authorization is needed. One substantive human-controlled
frame choice is open as `omni-benchmark-ei0.9.1.1`: reply **A** for the matched
89-question/16-database sealed MVP, or **B** to retain all 101 and resume
compiler/deployment work. After A, one safe, non-secret schedule-seed identifier
will be needed. No command, credential, callback, token, profile, lease, or
protected file is needed.

### Agent-owned work now

- After the human frame decision, record Freeze B for the already-determined
  mechanical baseline, then run the sealed C1-C4 evaluation and dual scoring
  through custody.
- Finish the aligned development comparison table and concise results/product
  report from immutable aggregates.
- Commit and publish reviewed work through `main` only. Worktree cleanup under
  `omni-benchmark-9v3` is not on the MVP critical path.

### Later exact gates

The agent may materialize the exact Freeze-B and sealed-action receipts under
standing authorization when their bound inputs exist. E02 deployment authority
is no longer on the path.

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

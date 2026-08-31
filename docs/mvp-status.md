# MVP status and critical path

This is the high-level operator view of the Omni × LiveSQLBench evaluation.
It summarizes the durable Beads tracker and the research ledger; it does not
replace either one. Update it at every material evidence gate, blocker change,
human authorization, candidate freeze, or sealed-run transition.

Last reconciled: 2026-08-30T21:14:51-04:00 (America/New_York). Reconciliation
happens at material evidence gates only, not on a daily cadence.

## Current position

The frozen **untuned baseline** has now completed the full matched held-out
comparison: 89 questions, four conditions, three repetitions, 1,068 immutable
attempts, and both frozen scorers. Only identity-free aggregates were opened.
Official mean accuracy is C1 10.1%, C2 22.1%, C3 8.6%, and C4 8.6%; corrected
sensitivity is 10.1%, 19.5%, 8.6%, and 9.7%. C2−C1 is the positive result
(+12.0 percentage points official; +9.4 sensitivity). C4 does not improve on
C1 (-1.5 and -0.4 points, with intervals spanning zero).

Optimization/tuning remains an MVP experiment, but its claim is narrower now.
The sealed baseline was scored before E02 dev-A execution completed. E02 was
selected and preregistered before those results. Its unchanged dev-A mechanism
contrast has now completed all 136 executable attempts and is frozen at
selection SHA-256 `7f173066…c86948`; 117 attempts answered and 19 ended in
capture infrastructure errors. Five transport failures captured no semantic
query and cannot be recovered without another model attempt. The preregistered
complete-136 rule therefore makes E02 INCONCLUSIVE; no complete promotion score
was published, and
it cannot be promoted. The sealed aggregates may not drive an intervention edit, dev-B
checkpoint, promotion decision, or optimized held-out arm. The project can
demonstrate a disciplined optimization attempt, but cannot claim held-out
improvement from it. A separate no-rerun diagnostic has now scored the 117
captured answers: official E02 is 11/117 versus matched C4 at 9/117 (+1.7
points), and sensitivity is 10/116 versus 9/116 (+0.9 points). Nineteen outcomes
remain unresolved, so this directional result does not change the formal
decision.

A later mechanism analysis, C5, has since completed on dev-A. It deploys Omni the
way its documentation prescribes (all-tables view surface, full FK join graph,
complete public HKB ported to `ai_context`) to test whether C4's result reflects
the governed path or the sparse model that could be compiled for it. It reflects
the sparse model: on the identical 136-attempt frame C5 scores 18/136 (13.2%)
against C4's 9/136 (6.6%), at roughly two-thirds the median token cost, while all
134 of its parseable queries still took the raw-SQL rewrite path and none
declared a join. C5 was registered on 2026-08-30 under D-197, after the sealed
aggregates were visible, so it is development-only by construction: it cannot
alter the frozen held-out numbers, cannot be promoted into a sealed successor,
and reports both frozen scorers on a single generation that was never rerun for a
wrong answer. Design:
[`c5-tuned-governed-condition.md`](c5-tuned-governed-condition.md).

Live-action authorization remains tiered by contamination risk
(`omni-benchmark-xeg`). Public semantic deployment and validation passes are
agent-autonomous and retryable under a new run ID. Standing human authorization
covers exact remaining MVP actions without another prompt; custody,
append-only evidence, and no-retry rules remain exact.

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
| Public C1-C3 direct baseline | Complete for the frozen baseline | Immutable generation and dev-A scoring exist. Official accuracy on the 122 scoreable-question intersection is C1 7.4%, C2 23.8%, C3 13.1%. The optional nine-question cybermarket denominator repair was cancelled unrun at the stop-after-E02 gate; the original exclusion and frozen artifacts remain unchanged. |
| Train-only gold release | Complete | Exactly 154 dev-A records were released through custody; the complete source was removed from the host transfer area. Test gold and dev-B outcomes remain unavailable to development. |
| Public semantic compiler and deployment preparation | Complete | V13 validates and exactly reads back all 16 answerable databases in one current evidence set. The two official-loader exclusions remain explicit rather than fabricated. |
| C4 baseline | Complete and scored | V8 completed 136 executable attempts. Official aggregate: 9 correct, 93 wrong, 34 refused/system-error; 18 of 154 scheduled identities are fixed unscorable. Selection SHA-256 `256145c1…5cc`; recovery-manifest SHA-256 `5d6ff474…fd9f`; score-receipt SHA-256 `0296753e…0a78`. |
| Minimal dev-A experiment set | **Complete; E02 INCONCLUSIVE** | Aggregate-only development analysis selected the preregistered relationship/grain intervention before sealed results were visible. Its sole immutable identity froze at selection `7f173066…c86948`. The no-rerun captured subset is 11/117 E02 versus 9/117 matched C4 under the official scorer, but 14 result-contract failures and five no-query transport failures leave the required 136-question promotion estimate incomplete. |
| Untuned candidate and baseline Freeze B | **Complete** | Baseline system `8b0c739…`, direct-child control `94cc0d9…`, Freeze-B SHA-256 `e1c9f196…ae4730`; 108 frozen files and all 1,068 schedule coordinates reproduce from Git objects. |
| Untuned sealed C1-C4 evaluation | **Complete and scored** | V1-v5 remain immutable and excluded. V6 has 1,068 attempts and 12 authenticated cohorts. Split-provenance scoring v10 completed once. Official aggregate `79bcfca3…8faff`; sensitivity `88dd6a71…b7eb26`; correctness-free receipt `534e28b9…b258f7`; aggregate report `884b660f…3a464`. No individual score artifact was opened. |
| Optimized candidate and held-out arm | **Cancelled; no promoted candidate** | E02 is INCONCLUSIVE on dev-A and cannot be promoted. Do not use sealed aggregates for intervention edits, checkpoints, promotion, or a new held-out arm. |
| Evidence preservation | **Complete** | Under closed P0 `omni-benchmark-vbt`, the public C4 baseline, sealed-final-v6, and terminal E02 roots have exact, independently verified main-workspace copies. E02 preservation covers 665 files / 5,586,131 bytes with manifest SHA-256 `d665578c…bc33a`. See the [evidence index](evidence-index.md). |
| Results/product report | **Held-out numbers integrated; final edit remains** | `RESULTS.md` now contains both frozen scorer matrices, paired contrasts, failure analysis, product findings, and the optimization-scope limitation. Finish the concise submission-ready edit and artifact-lineage check. |

## What is already usable

- The frozen direct-SQL and governed C4 development results are real and can be
  discussed with their stated scopes and exclusions.
- The public HKB/compiler analysis and failure-mechanism evidence are real.
- The E01 no-op finding and E02's completed, preserved, frozen dev-A generation
  are real. E02 is INCONCLUSIVE because five infrastructure failures prevent
  the preregistered complete-136 comparison. Its 117-answer matched diagnostic
  is usable as explicitly non-promotional product evidence.
- The sealed C1-C4 comparison is a real held-out outcome under both frozen
  scorers. Its aggregate-only report is shareable with the stated 89-question,
  16-database scope.

The clearest current interpretation is: searchable raw business knowledge (C2)
was strongest in the frozen direct baseline, while governed C4 produced 9
correct answers among 136 scoreable attempts and 34 refusal/system-error
outcomes. The evidence localizes those outcomes to the governed C4 path, but it
does not support assigning every one exclusively to Omni product behavior
rather than the integration contract or harness interpretation. On the exact
122-question intersection shared by all four conditions, C4 is 5/122 (4.1%),
compared with C1 at 9/122 (7.4%), C2 at 29/122 (23.8%), and C3 at 16/122
(13.1%). The paired descriptive C4-C1 difference is -3.3 percentage points.
This alignment confirms the low C4 result is not a denominator artifact. The
held-out comparison now strengthens the same product story: C2 is best, while
C4 does not improve on C1.

## Blocking and waiting

### Waiting on the operator now

One narrow operator action is now listed in `docs/human-decisions.md`:

1. Confirm that the transferred full source and its temporary external transfer
   directory were removed. Reply only with
   `remote cleanup status: file=0 directory=0`; retain the private 89-record
   projection.

No new model run, run authorization, callback, lease action, or protected-data
transfer is needed.

### Agent-owned work now

- Close the one remaining human custody confirmation while retaining the
  private 89-record projection used by the completed sealed scorer.
- Finalize the results packet, make the reviewed submission commit, and create
  the submission tag.

### Stop rule after E02, and the one authorized exception

E02 is preserved and recorded as INCONCLUSIVE. The stop rule stated after it
(D-191) was superseded on 2026-08-30 by operator directive D-197, which
authorized exactly one further development condition, C5, and nothing else. No
intervention edit, dev-B checkpoint, rerun, or held-out arm may be launched, and
C5 itself cannot be promoted into a sealed successor. C5's single generation and
scoring have since completed. Remaining work is custody closeout, artifact
verification, report correction without new empirical claims, and the final
submission commit and tag.

### Non-critical-path or deferred work

LODO, extensive template audits, optimizer-framework work, publication-grade
statistical extras, comparator polish, protocol-paper expansion, and the
cybermarket append-only recovery remain documented but were explicitly closed
or cancelled outside the MVP. They do not authorize another experiment before
or after submission.

## Definition of MVP complete

The MVP is complete only when all of the following are true:

1. The public C4 baseline is validated, immutably captured, frozen, and scored
   under the 154-scheduled/136-answerable frame.
2. The bounded pre-result E02 dev-A contrast produces immutable KEEP/REVERT/
   INCONCLUSIVE mechanism evidence without using held-out outcomes or dev-B, and
   the authorized C5 mechanism analysis produces its immutable dev-A evidence
   under both frozen scorers.
3. The twelve untuned C1-C4 cohorts and both frozen scorers produce
   identity-safe aggregates through custody.
4. `RESULTS.md` reports the actual development and sealed comparisons, product
   findings, the optimization-order limitation, and exact artifact lineage with
   no pending numeric placeholders.
5. The public C4 baseline, sealed-final-v6, and terminal E02 raw evidence are
   preserved and independently verified in stable main-workspace locations.
6. The full-source cleanup is confirmed and the concise report receives its
   final submission-ready edit.
7. The reviewed submission commit and tag exist, and no experiment lane remains
   authorized or running.

## Sources of truth

- `bd show omni-benchmark-ei0` — durable MVP issue tree.
- `bd human list` — live operator decision queue.
- [research-log.md](research-log.md) — contemporaneous hypotheses and outcomes.
- [human-decisions.md](human-decisions.md) — exact current authorization scope.
- [../RESULTS.md](../RESULTS.md) — results-first report draft.
- [evidence-index.md](evidence-index.md) — compact lineage, stable artifact
  locations, preservation verification, and custody posture.
- `.dashboard/index.html` — local visual snapshot; ignored and regenerated at
  major gates.

This file must never contain private gold, per-question dev-B outcomes, hidden
test annotations, sealed correctness, credentials, or credential locations.

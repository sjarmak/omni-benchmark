# Draft amendment: a development custody tier

**Status: proposal awaiting human approval. Not in force.** Custody rules are a
human-controlled surface (`CLAUDE.md`, "Split membership, custody rules, scoring
definitions, endpoints, and the protocol are human-controlled surfaces. Propose
changes; do not make them"). Nothing here changes until Stephanie approves it and
the change lands in `EVALUATION_PROTOCOL.md` under her authority.

## The problem this solves

`EVALUATION_PROTOCOL.md` defines one custody regime, built for the sealed test
set, and every development loop inherits it. That was the right default while the
sealed frame was the only thing being produced. It is the wrong default now.

The sealed-final-v6 run is the evidence. Five dispatches (v1 through v5) died
before a cohort was finalized, and each restart needed a fresh single-use
approval receipt authenticated by a closed Beads decision issue with a
one-minute `closed_at` window. None of those five failures had anything to do
with test-gold exposure. v1 stopped on a missing `PGSSLROOTCERT` in the sealed
loader (D-165). v2 stopped because the C2 adapter compared the Freeze B
aggregate manifest digest against the selected database's HKB payload digest
(D-166). v3 through v5 stopped on C4 governed-response contract failures
(D-167 through D-170). The receipt ceremony was paid five times and prevented
none of them, because it is not aimed at that class of failure.

Meanwhile the same regime made a routine scoring-side bugfix expensive. Fixing
`sealed_evaluation.py` moved HEAD, which broke the HEAD-equals-control check,
which meant release and scoring refused to run; the way out was three more Freeze
B records (v8, the rejected v9, and v10). That sequence is documented in
`docs/freeze-b-lineage.md` and `docs/sealed-finish-runbook.md`. It was the
correct resolution, and it should not be the price of a bugfix on a development
loop that touches no held-out data.

The proposal is to name the two regimes separately, so the sealed tier keeps
every protection it has and development stops paying for protections aimed at a
risk it does not carry.

## The principle

**Authorization scales with contamination risk, not with whether an action is
live.** That sentence is already in `CLAUDE.md` under "Live-action authorization
tiers"; this amendment applies it to the protocol itself rather than only to
agent authorization.

A control earns its place in the development tier if it protects against one of:
losing evidence, fabricating evidence, or contaminating a held-out partition.
Controls that exist only to make a single sealed measurement unrepeatable belong
in the sealed tier alone.

## Sealed tier: unchanged

No control is removed, weakened, or made conditional. Everything in
`EVALUATION_PROTOCOL.md` continues to govern the 101 sealed IDs, the 89-question
sealed MVP frame within them, and any future sealed measurement. This amendment
adds a tier; it does not modify the existing one.

Specifically unchanged: single-use approval receipts bound to a closed Beads
decision, the exact-HEAD clean-tree gate on release and scoring, Freeze B
recording with its two-commit boundary, the dev-B guardian signing path, and the
prohibition on any held-out result feeding a system change.

## Development tier: what carries over

These are the controls that protect evidence integrity, and they apply to every
development run without exception.

1. **Both frozen scorers, always co-reported.** Official-compatible Soft EX
   pinned to evaluator commit `e15cd221` and the corrected multiset sensitivity
   scorer. Neither may be reported alone, and neither may be selected after
   seeing results. This is the single most load-bearing anti-gaming rule in the
   project and it costs nothing to keep.
2. **The no-rerun rule.** A trial is never rerun because its answer was wrong. A
   rerun requires a demonstrable failure outside the evaluated system, documented
   before the replacement runs. Unchanged from the sealed tier.
3. **Append-only artifacts via `_write_exclusive`.** Mode 0600, `O_EXCL`, no
   overwrite. A botched record is fixed forward with a new record, never by
   deleting the file and retrying.
4. **Run-ID exclusivity and quarantine.** A run ID is claimed once. A run that
   fails is quarantined under its own ID and preserved, not reclaimed. Retries
   take a new ID.
5. **Recursive forbidden-field rejection.** Generation artifacts may not contain
   `sol_sql`, `gold_sql`, `test_cases`, `external_knowledge`, `test_correctness`,
   `gold_result`, or `expected_result` at any nesting depth. Correctness lives in
   a separate immutable score artifact.
6. **Deployment readback verification.** Every semantic deployment is verified by
   exact readback against what was written before any attempt runs against it.
   D-199 through D-202 are four separate deployment faults this caught.
7. **The runtime-commit guard.** `verify_system_commit`, including
   `_verify_ignored_runtime_files`. D-204 is the case where two launches failed
   on runtime bytecode; the guard was right both times.
8. **Contemporaneous logging.** Every meaningful change starts with a hypothesis
   and ends in `docs/research-log.md`, including the ones that failed.

## Development tier: what drops

Each of these is a sealed-tier control with a stated reason it does not transfer.

1. **The single-use approval-receipt round trip.** Materializing a receipt,
   closing a Beads decision issue within a one-minute window, and consuming the
   receipt exactly once. *Why it drops:* it authorizes spending a
   non-reproducible measurement. A dev-A run is reproducible by construction, so
   there is nothing single-use to protect. Replaced by: the run is logged before
   it starts and its cost ceiling is enforced by policy, as now.
2. **The exact-HEAD clean-tree scoring gate.** *Why it drops:* it exists so the
   scoring system that touched gold is identifiable to the byte. Development
   scoring reads dev-A labels that are already released to development, and the
   system commit is recorded in the run artifact regardless. Replaced by:
   recording the system commit and refusing to score from a dirty tree in the
   *runtime paths only*, which is what `verify_system_commit` already does.
3. **Freeze B ceremony for ordinary development iterations.** The two-commit
   boundary, the 108-digest manifest, and the direct-child validation. *Why it
   drops:* Freeze B answers "which exact system produced the held-out numbers."
   For a dev loop the answer is the recorded system commit. Replaced by: the
   per-series pin below.
4. **The guardian path for ordinary dev-A loops.** *Why it drops:* the guardian
   boundary protects dev-B aggregate correctness. It is not involved in dev-A at
   all, and invoking it for dev-A work would consume nothing but would blur the
   line that makes dev-B meaningful. Unchanged for dev-B, which keeps its
   metered 10-checkpoint budget and its Freeze-A-protected key pin.

## The drift rule: pin per series, bridge on upgrade

Approved in principle 2026-08-31; stated here for the amendment.

A **series** is a set of runs intended to be compared with each other. Each
series pins its benchmark version, its database snapshot identifiers, its scorer
commits, and its condition definitions at the series' first run, and every
subsequent run in that series uses those pins. A pin is recorded in the series
manifest, not inferred from whatever is checked out.

When an upstream benchmark version changes, a series does **not** silently move
to it. Instead:

1. The current series closes at its pinned version. Its published numbers stay
   attached to that pin and are never restated against the new one.
2. A **bridge round** runs the arms that matter on both the old and new pins,
   over the same question frame, and publishes both. The bridge round's purpose
   is to measure the version delta, not to produce a headline.
3. A new series opens at the new pin, citing the bridge round.

The failure this prevents is the one that looks like progress: a number improves
between rounds and nobody can separate the product change from the benchmark
change. A bridge round costs one extra measurement and makes the comparison
defensible; reconstructing the attribution afterward is not possible at all.

## What approval would mean concretely

If approved, `EVALUATION_PROTOCOL.md` gains a section that names the two tiers
and states which controls belong to each, and the development tooling stops
requiring receipt round trips and exact-HEAD gates for dev-A runs. The sealed
tooling is untouched. No existing published result changes, because no published
result was produced under the development tier.

If not approved, the status quo is workable; it is just slower per iteration, and
the slowness falls entirely on the loop that carries no contamination risk.

## Open questions for the human surface

1. Should the development tier permit scoring from a tree that is dirty outside
   `RUNTIME_PATHS`? The draft says yes, since the runtime guard already covers
   what executes. The conservative alternative is to require a clean tree
   everywhere, which reintroduces most of the cost the amendment removes.
2. Should a dev series' pin be allowed to change mid-series for a security fix in
   a dependency? The draft has no exception, which means a security fix forces a
   bridge round. That may be the right trade or may be too rigid.
3. Who authorizes opening a new series? The draft assumes the same human surface
   that controls the protocol, but this could reasonably be delegated.

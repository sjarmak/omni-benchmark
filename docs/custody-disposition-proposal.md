# Custody disposition proposal: untracked approval and state artifacts

Status: **PROPOSAL ONLY**, awaiting operator decision. Prepared for
`omni-benchmark-lcf`. No `.gitignore` edit and no `git add` has been run.
`git status --ignored` confirms both paths below are untracked and *not*
matched by any existing ignore pattern — they are simply new.

## 1. Inventory

### `experiments/approvals/c4-production/`

One file, 720 bytes, mode `0600`:

- `16096b6e750ce2ac285f4b54b4b804e5dbede211912cb59541a3f8beb06b4e35.consumed.json`

Content: a single consumed C4-production approval-token record — `kind:
"c4-production-approval-consumption"`, the binding condition, deployment/
execution-plan/schedule/system-commit hashes, the `decision_bead_id`
(`omni-benchmark-ei0.4.12`), a nonce, and a self-referential `receipt_sha256`.
No SQL, no question identity, no result data. This is the receipt that proves
a one-time-use approval token was spent, not the approval itself.

### `experiments/autoresearch/state/`

Three files, 372K total, mode `0600`:

| File | Size | Content |
|---|---|---|
| `public-direct-baseline-freeze-v1.json` | 299,518 B | 630 frozen trial/attempt selections (condition, database, instance ID, generation/run-manifest hashes) for the public direct-SQL baseline |
| `public-c4-baseline-v8-freeze.json` | 73,413 B | Output of `scripts/freeze_c4_baseline.py`: artifact/eligible-manifest hashes, attempt counts, and per-attempt entries (condition, database, instance ID, generation/run-manifest hashes) for the public C4 baseline, v8 |
| `dev-a-gold-conformance-v1.json` | 726 B | Output of `scripts/freeze_dev_a_gold_conformance.py`: input hashes, scorer identities, and aggregate scoreable/unscorable counts for both frozen scorers on dev-A |

All three are hash manifests and aggregate counts. None contain SQL text,
result rows, gold values, or candidate answers — verified by reading each
file in full. `dev-a-gold-conformance-v1.json` matches, byte-for-byte in
structure, the receipt shape `docs/research-log.md:8380-8398` describes as
containing "only input hashes, scorer identities, total scoreable and
unscorable counts... no IDs, SQL, result rows, or candidate evidence."

### Referenced by committed docs

- `experiments/autoresearch/state/public-direct-baseline-freeze-v1.json` is
  named and hash-checked explicitly at `docs/research-log.md:5677-5679`.
- The `experiments/autoresearch/state/public-c4-baseline-<version>-freeze.json`
  naming pattern is the documented, repeated destination of
  `scripts/freeze_c4_baseline.py` — earlier versions (`v4`, `v5`) are named by
  exact path in `docs/research-log.md:8294` and `docs/human-decisions.md:431`.
  `v8` is the current instance of that same custody flow, not a new one.
- The mechanism behind `dev-a-gold-conformance-v1.json` (the "coverage-limited
  gold-conformance rule," frozen by human decision `omni-benchmark-ei0.3.1")
  is documented at `docs/human-decisions.md:778-809` and
  `docs/research-log.md:8380-8423`, though the literal filename is not yet
  quoted anywhere.
- No committed doc currently names the consumed-approval-receipt filename or
  its hash directly; `omni-benchmark-ei0.4.12` (its `decision_bead_id`) is
  named at `docs/research-log.md:10147` and `:10174` as the exact package this
  receipt attests consumption of.

## 2. The sibling inconsistency

Three custody treatments already coexist for structurally similar artifacts,
and the two paths in this proposal don't fit any of them cleanly:

| Path | Git treatment | Rationale implied by existing pattern |
|---|---|---|
| `experiments/autoresearch/raw/`, `runs/`, `experiments/runs/` | Ignored | Per-attempt outputs / trace sidecars — large, regeneratable, can contain generated SQL |
| `experiments/quarantines/`, `experiments/freeze-b*.json` | **Committed** | Immutable incident/freeze records — small, hash-bearing, referenced as evidence |
| `experiments/approvals/c4-production/`, `experiments/autoresearch/state/` | **Untracked** (neither ignored nor added) | Undecided |

The two paths in this bead are structurally on the "committed" side of that
line — small, `0600`, append-only-by-construction (approvals are "consumed"
once; freeze files are versioned `-v1`, `-v2`, ... rather than overwritten),
and hash-bearing — but nothing has ever added them, and nothing ignores them
either. They are in limbo, not by policy but by omission: the freeze/approval
tooling was built and run before anyone decided which side of the ignore
line it belongs on. That is exactly the state `.gitignore`'s own comment on
`data/raw/` warns about ("reproducible... committed manifests are not
ignored") without extending the same explicit statement to these two paths.

## 3. Recommendation, per path

### `experiments/autoresearch/state/` — **track**

Rationale: this is the same category of artifact as `experiments/freeze-b*.json`
and `experiments/quarantines/*.json`, which are already committed — immutable,
hash-verified freeze/conformance receipts that downstream scoring code
authenticates against (`docs/research-log.md:8388-8391`: "The complete E02
scorer can now authenticate that receipt against its own Freeze-A, release,
and dev-A-manifest bindings"). One of the three files is already quoted by
exact path and hash in the committed research log; the other two are
instances of a naming pattern whose earlier versions are quoted the same way.
Leaving them untracked means the provenance trail the docs describe (freeze
artifact -> hash -> downstream authentication) has no corresponding
git history, so a `git blame`/`git log` reconstruction of "what was frozen,
when, and does the working tree still match it" is impossible for exactly the
artifacts most likely to be audited later. No file in this directory contains
gold, SQL, or candidate content.

Proposed command (run by the operator, not this agent):

```
git add experiments/autoresearch/state/public-direct-baseline-freeze-v1.json \
        experiments/autoresearch/state/public-c4-baseline-v8-freeze.json \
        experiments/autoresearch/state/dev-a-gold-conformance-v1.json
```

No `.gitignore` change is needed for this path — nothing currently ignores it.

### `experiments/approvals/c4-production/` — **track**

Rationale: this is a single consumed one-time-use approval receipt, the
approval-side counterpart to the freeze files above, and it is bound by hash
to a `decision_bead_id` that is already named in the committed research log.
Its entire purpose is to prove, after the fact, that a specific approval
token was spent exactly once for a specific deployment/execution-plan/
schedule binding (`CLAUDE.md`'s "custody, quarantine, and the no-retry rule"
language describes exactly this kind of record). An untracked receipt proves
nothing to a future auditor who only has the git history; it proves
everything to one who has both the commit and the file. No content in the
file is gold, SQL, or candidate-specific — it is exclusively hashes, an ID,
and a nonce.

Proposed command:

```
git add experiments/approvals/c4-production/16096b6e750ce2ac285f4b54b4b804e5dbede211912cb59541a3f8beb06b4e35.consumed.json
```

No `.gitignore` change is needed; nothing currently ignores this path either.

### Alternative considered and rejected: ignore both

An operator could instead treat both paths as ephemeral local state (parallel
to `experiments/autoresearch/raw/`) and add ignore patterns:

```
# NOT recommended — see rationale above
experiments/approvals/
experiments/autoresearch/state/
```

This would resolve the inconsistency the other direction and is internally
consistent with treating all of `experiments/autoresearch/` as regeneratable
working state. It is not recommended because these specific files are the
*output* of a freeze/approval step whose entire purpose is durable proof —
unlike `raw/`, they are small, already hash-referenced from committed prose,
and the tooling that produces them (`freeze_c4_baseline.py`,
`freeze_dev_a_gold_conformance.py`) treats them as non-overwriting artifacts,
not scratch state. Ignoring them would sever the provenance chain the rest of
the custody system is built to preserve.

### Partial alternative: track only the referenced file

A narrower option is to track only
`public-direct-baseline-freeze-v1.json` (explicitly quoted by path and hash
in `docs/research-log.md`) and leave the other two untracked pending an
explicit doc reference. Rejected as the primary recommendation because
`public-c4-baseline-v8-freeze.json` and the approval receipt are the same
*kind* of artifact under the same *documented* tooling pattern, just not yet
quoted by their current exact filename — deferring their custody decision
until each new version happens to get quoted in prose would mean the freeze
mechanism as a whole stays partially untracked indefinitely, since new
versions (`v9`, `v10`, ...) will keep landing before the log catches up.

## 4. Privacy check

Every file in both paths was read in full (not sampled) before writing this
proposal. None contain `sol_sql`, `gold_sql`, `test_cases`,
`external_knowledge`, `test_correctness`, `gold_result`, `expected_result`,
question text, or any other private/hidden content. All four files consist
exclusively of: SHA-256 hashes, condition/database/instance/attempt
identifiers, aggregate counts, scorer identity strings, timestamps embedded
in IDs, and one nonce. **No file in scope is a leak risk.**

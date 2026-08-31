# Sealed finish-line runbook (sealed-final-v6)

Operator reference for taking the untuned sealed generation arm from a stopped
or completed dispatcher through cohort finalization, test-label release, dual
scoring, and report rendering. Read this before touching `runs/sealed-final-v6`
again. V1 through v5 all died between generation and a scored result; this
document exists so v6 (or its successor) does not repeat the same five bugs.

Reference commit for everything below: control commit
`94cc0d9483c944d7dc13ed651c8fc2ef077f33ab`, system commit
`8b0c7393d564d9ecc2c2f84ba7446d610c1a0a6d`, Freeze B
`experiments/freeze-b-v7.json`. 89 questions x 4 conditions x 3 repetitions =
1068 scheduled attempts, 12 cohorts.

## 1. What actually happens after the last attempt

Cohort finalization is **not** a separate command. It is inlined in
`execute_sealed_dispatch` (`src/omni_benchmark/sealed_dispatch.py:533-605`).
When a dispatch invocation drives the pending-attempt count to zero
(`remaining == 0` at line 593), the same process calls `_finalize_all`
(line 702), which reconciles every staged envelope per condition/repetition,
computes `started_at`/`finished_at` from the twelve cohorts, and calls
`finalize_sealed_cohort` (`sealed_cohort_finalization.py:59`) once per cohort.
Finalization writes `generation.jsonl` + `run.json` atomically under
`<output_root>/cohorts/<condition>-r<repetition>/` (mode 0700 dirs, mode 0600
files, `os.rename` from a temp dir). If the dispatcher instead stops with
attempts still pending, it raises `SealedDispatchError` and no cohorts are
written — this is exactly what happened in v1 through v5.

So: **if the live v6 process (pid 3527456, started with
`--execute-sealed-generation`) reaches its last attempt without another
infrastructure stop, cohort finalization already happened inside that same
process and needs no further action.** Check for it with:

```
ls /home/ds/projects/omni-benchmark/runs/sealed-final-v6/cohorts
```

Twelve directories (`c1-r1` ... `c4-r3`), each holding `generation.jsonl` and
`run.json`, means generation and finalization are both done. Move to step 3.

## 2. Ordered command sequence (clean finish, no continuation)

Run every command from the repository root with `uv run python
sealed_tools/<script>.py`. All four steps below reload their inputs from
committed Git objects, not the working tree, so every one of them fails
closed if the frozen files do not match Freeze B.

**Step A — confirm the plan reproduces (read-only, no live effect):**

```
uv run python sealed_tools/plan_sealed_generation.py \
  --workspace /home/ds/projects/omni-benchmark \
  --control-commit 94cc0d9483c944d7dc13ed651c8fc2ef077f33ab \
  --system-commit 8b0c7393d564d9ecc2c2f84ba7446d610c1a0a6d \
  --freeze-b experiments/freeze-b-v7.json \
  --schedule data/final-schedule.jsonl \
  --public-manifest data/manifests/eligible_questions.jsonl \
  --test-ids data/manifests/sealed_mvp_ids.txt
```

Verifies: schedule, public manifest, and test-ID file all match the digests
Freeze B froze; the schedule reproduces byte-identically from the seed; prints
`plan_sha256` and the attempt/cohort counts. This is the same plan the
dispatcher used.

**Step B — release the sealed test labels into private custody:**

```
uv run python sealed_tools/release_sealed_test.py \
  --workspace /home/ds/projects/omni-benchmark \
  --source <external private gold JSONL, outside the workspace> \
  --destination data/private/test/labels.jsonl \
  --expected-source-sha256 <sha256 of that external source file> \
  --control-commit 94cc0d9483c944d7dc13ed651c8fc2ef077f33ab \
  --system-commit 8b0c7393d564d9ecc2c2f84ba7446d610c1a0a6d \
  --freeze-b experiments/freeze-b-v7.json \
  --schedule data/final-schedule.jsonl \
  --public-manifest data/manifests/eligible_questions.jsonl \
  --release-sealed-test
```

Without `--release-sealed-test` it refuses to run. Verifies the plan matches
Freeze B, derives the exact 89 test instance IDs from the plan (not from any
file an operator hands it), and copies only those 89 records out of the
external source into `data/private/test/labels.jsonl` with an atomic
link-then-verify publish that refuses to overwrite an existing destination.
Destination must be exactly `data/private/test/labels.jsonl`; anything else is
rejected before any file is touched.

**Step C — preflight scoring, then execute it:**

```
uv run python sealed_tools/score_sealed_evaluation.py \
  --workspace /home/ds/projects/omni-benchmark \
  --control-commit 94cc0d9483c944d7dc13ed651c8fc2ef077f33ab \
  --system-commit 8b0c7393d564d9ecc2c2f84ba7446d610c1a0a6d \
  --freeze-b experiments/freeze-b-v7.json \
  --schedule data/final-schedule.jsonl \
  --public-manifest data/manifests/eligible_questions.jsonl \
  --cohort-root runs/sealed-final-v6/cohorts
```

No `--execute-sealed-scoring` means this only authenticates all twelve
cohorts against the plan and Freeze B and prints
`"status":"validated_not_scored"`. It does not touch gold, does not connect to
PostgreSQL, and does not need `--release` or `--output-root`. Run this first
and confirm it succeeds before adding execute.

Then, to actually score:

```
uv run python sealed_tools/score_sealed_evaluation.py \
  --workspace /home/ds/projects/omni-benchmark \
  --control-commit 94cc0d9483c944d7dc13ed651c8fc2ef077f33ab \
  --system-commit 8b0c7393d564d9ecc2c2f84ba7446d610c1a0a6d \
  --freeze-b experiments/freeze-b-v7.json \
  --schedule data/final-schedule.jsonl \
  --public-manifest data/manifests/eligible_questions.jsonl \
  --cohort-root runs/sealed-final-v6/cohorts \
  --release data/private/test/labels.jsonl \
  --expected-release-sha256 <sha256 printed by step B's "output_sha256"> \
  --output-root runs/sealed-final-v6/score \
  --execute-sealed-scoring
```

This opens the released gold, requires `OMNI_BENCHMARK_SCORER_ADMIN_DSN` and
`OMNI_BENCHMARK_SCORER_EXECUTION_DSN` in the environment
(`dev_a_baseline_scoring_cli.py:30-31`), scores every
attempt under both frozen scorers on fresh isolated PostgreSQL copies, and
publishes 24 private per-cohort score files plus two aggregate files
(`official_soft_ex/aggregate.json`, `sensitivity/aggregate.json`) and one
`receipt.json` under `--output-root`, all via one atomic `renameat2` publish
that refuses to land on top of an existing destination.

**Step D — render the identity-free Markdown report (not HEAD-bound, safe any
time after step C):**

```
uv run python sealed_tools/render_sealed_report.py \
  --workspace /home/ds/projects/omni-benchmark \
  --official runs/sealed-final-v6/score/official_soft_ex/aggregate.json \
  --sensitivity runs/sealed-final-v6/score/sensitivity/aggregate.json \
  --expected-official-sha256 <sha256 from step C's receipt.json aggregates.official_soft_ex.sha256> \
  --expected-sensitivity-sha256 <sha256 from step C's receipt.json aggregates.sensitivity.sha256> \
  --destination runs/sealed-final-v6/report/held-out-results.md \
  --render-sealed-report
```

Reads the two aggregates by exact hash, cross-checks every internal count and
rate for consistency, rejects any protected field or non-finite number, and
writes the aggregate-only Markdown table used in `RESULTS.md`. This is the
only one of the four steps that does not call `load_freeze_b_control` — it has
no HEAD requirement.

## 3. HEAD constraint: which steps are bound, and when it lifts

`_current_exact_commit` (`freeze_b_record.py:225-233`) requires live HEAD to
equal the supplied `--control-commit` exactly. It is reached, directly or
transitively, from:

- `sealed_dispatch_cli.py:63` (`load_freeze_b_control`) — every dispatch or
  continuation invocation, dry or `--execute-sealed-generation`.
- `sealed_execution_plan.py:166` (`load_freeze_b_control` inside
  `load_sealed_execution_plan`) — plan loading, and everything that loads a
  plan first (dispatch, evaluation, test release).
- `sealed_evaluation_cli.py:67` (`load_freeze_b_control`), **plus** an
  independent, stricter check at line 58,
  `_require_exact_control_checkout`, called unconditionally before the
  `--execute-sealed-scoring` branch even runs. That check requires both
  `HEAD == control_commit` **and** `git status --porcelain
  --untracked-files=no` to be empty (`sealed_evaluation_cli.py:171-197`).
- `sealed_test_release.py:54` (`load_freeze_b_control`), plus the same
  `_require_exact_control_checkout` call at `sealed_test_release.py:104`
  (clean tree required).

So: **plan loading and dispatch/continuation need HEAD to equal `94cc0d9...`
and nothing else** — a dirty tracked tree does not block them.
**Test-label release and scoring need HEAD equal to `94cc0d9...` AND a fully
clean tracked tree.** `sealed_report.py` has no HEAD dependency at all; it is
the only finish-line step safe to run after HEAD moves.

**Right now**: HEAD is `94cc0d9...` (confirmed), but `git status --porcelain
--untracked-files=no` is **not** empty — `.beads/issues.jsonl`, `RESULTS.md`,
`docs/failure-taxonomy.md`, `docs/human-decisions.md`,
`docs/livesqlbench-upstream-loader-report-draft.md`, `docs/mvp-status.md`,
`docs/protocol-diff.md`, `docs/research-log.md`,
`experiments/analysis/wrong_answer_structure.py`,
`src/omni_benchmark/e02_experiment_cli.py`, `tests/test_e02_experiment_cli.py`,
and `tests/test_wrong_answer_structure.py` are all modified and tracked. This
means **step B and step C will fail their preflight today**, even though
generation/continuation would not be blocked by it. The untracked new files
(`experiments/approvals/`, `experiments/autoresearch/`,
`src/omni_benchmark/claude_lease_preflight.py`, etc.) do not count against the
check (`--untracked-files=no`), only tracked modifications do.

**Do not fix this by committing to main.** Committing any of those tracked
changes moves HEAD away from `94cc0d9...` and breaks every one of the four
steps above, including the ones currently unblocked. The only way to reach a
clean tree without moving HEAD is `git stash` the tracked changes immediately
before step B/C and restore the stash immediately after, or run steps B/C from
a separate worktree/clone checked out exactly at `94cc0d9...` with nothing
else changed.

**It becomes safe to commit to main only after step C has published its
`receipt.json`** (both aggregates immutable, hash-verified, on disk). Before
that, any commit blocks or corrupts the remaining finish-line steps. After
that, generation/continuation is moot (already done) and only report
rendering (HEAD-independent) remains, so HEAD can move freely.

## 4. Continuation procedure, if the live run stops again

Every prior sealed-final dispatch (v1-v5, plus v6's own earlier restarts)
stopped with a `SealedDispatchError` raised inside `_run_pending` before all
1068 attempts landed. `execute_sealed_dispatch` computes `pending` once at
the start of the call and drives that fixed batch through a single
`ThreadPoolExecutor`; it does not re-poll for newly freed capacity across
separate invocations. So a stop is final for that process: the remaining
coordinates need a **new** invocation of `dispatch_sealed_generation.py` with
`--execute-sealed-generation`, using the **same** `--run-id sealed-final-v6`
and `--output-root runs/sealed-final-v6` (same-identity continuation).

What a continuation needs:

1. **The exact same argument set the running dispatcher was launched with.**
   Confirmed from the live process (pid 3527456):

   ```
   --workspace /home/ds/projects/omni-benchmark
   --control-commit 94cc0d9483c944d7dc13ed651c8fc2ef077f33ab
   --system-commit 8b0c7393d564d9ecc2c2f84ba7446d610c1a0a6d
   --freeze-b experiments/freeze-b-v7.json
   --schedule data/final-schedule.jsonl
   --public-manifest data/manifests/eligible_questions.jsonl
   --test-ids data/manifests/sealed_mvp_ids.txt
   --policy config/sealed-dispatch-v1.json
   --output-root runs/sealed-final-v6
   --run-id sealed-final-v6
   --input-spec config/freeze-b-input.json
   --omni-deployment-gate config/sealed-omni-deployment-gate-v1.json
   --claude-config-dir /home/ds/.claude-leases/omni-a1
   --claude-config-dir /home/ds/.claude-leases/omni-a3
   --claude-config-dir /home/ds/.claude-leases/omni-a4
   --database-environments /home/ds/.local/state/omni-benchmark-neon-envs
   --runtime-parent /home/ds/.omni-benchmark-runtime/sealed-final-v6
   --execute-sealed-generation
   ```

   Only `--receipt` changes (below). Everything else must match exactly or
   `build_sealed_dispatch_binding` produces a different binding and the new
   receipt cannot authenticate against it.

2. **A fresh, single-use approval receipt.** The receipt already spent for
   this v6 launch is recorded at
   `runs/sealed-final-v6/approvals/e0a6ba14145d6fc0dbe61e4b364c951f9b618b466009b2b9935de284f2f5c97a.consumed.json`
   (`consume_sealed_production_approval`, `sealed_production_approval.py:155`,
   creates this file with `O_EXCL` — a second use of the same receipt content
   fails with "sealed human approval was already consumed"). A new invocation
   needs a new receipt JSON (`kind:
   sealed-production-human-approval`, fresh `nonce`, `approved_at`/
   `expires_at` window of at most one hour) whose `binding` matches
   `build_sealed_dispatch_binding` for this exact continuation (same
   `plan_sha256`, `policy_sha256`, `output_root`, `run_id`, `control_commit`,
   `system_commit`, `runtime_sources_sha256`, cost ceiling, concurrency, wall
   clock).
   `validate_sealed_production_approval` (`sealed_production_approval.py:71`)
   additionally requires that receipt to be authenticated by a **closed
   Beads decision issue**: `issue_type: decision`, `status: closed`,
   `close_reason: Responded`, label `human`, exactly one comment
   `"Response: " + <canonical receipt JSON>`, and `closed_at` within one
   minute of the receipt's `approved_at`.

   **Who produces it:** under the Tier 2 standing authorization already
   granted for this project (`omni-benchmark-ei0.4.x` pattern used for every
   v1-v5 continuation and D-165 through D-170), the agent may materialize and
   close the Beads decision and materialize/consume the matching receipt
   itself, without another human prompt, because the bound inputs (plan,
   Freeze B, policy, output root, run ID) already exist unchanged. This is
   exactly what happened for every prior same-identity continuation logged
   under D-167/D-168 in `docs/research-log.md`. It is still single-use and
   exact-bound: a receipt from one continuation attempt cannot be reused for
   a different one, and the rerun policy still forbids re-dispatching an
   attempt because its answer was wrong — only infrastructure stops justify a
   new receipt.

3. **Reconciliation, not restart.** On invocation, `preflight_sealed_dispatch`
   reconciles every one of the 1068 planned attempts against
   `SealedAttemptRepository` (`sealed_generation_staging.py:272`) before
   constructing any adapter. Only attempt IDs with no existing
   `attempts/<database>/<condition>/<instance_id>-r<repetition>/attempt.json`
   enter `pending`. The already-staged 860+ envelopes are read back, hash-
   verified against their binding, and left untouched — nothing is
   regenerated. This matches the current on-disk layout exactly:
   `runs/sealed-final-v6/attempts/<database>/<condition>/<instance_id>-r<repetition>/attempt.json`,
   confirmed live (860 staged files across 13 database directories as of this
   check).

4. **If it finishes this time**, cohort finalization runs automatically in
   the same process per step 1 above — no separate finalize command.

## 5. Known failure signatures, v1 through v5

All five died between generation and a scored cohort, before any correctness
was read. Look for these signatures first when triaging a new stop:

| Run | Stage | Signature | Root cause | Fix |
| --- | --- | --- | --- | --- |
| v1 | First PostgreSQL privilege attestation, before any evaluated query | Sealed loader fails PostgreSQL connection/attestation immediately after receipt consumption; one generation staged, zero cohorts | Sealed private-JSON loader omitted `PGSSLROOTCERT=/etc/ssl/certs/ca-certificates.crt` that the proven public direct loader sets | D-165: sealed loader now sets the same fixed system CA after validating the private file |
| v2 | Before model execution, C2 attempts only | Dispatch stops because the constructed C2 runtime context does not match Freeze B's C2 binding; three generations staged, zero cohorts | Adapter compared Freeze B's C2 digest (the aggregate `semantic_models/public_ir/manifest.json`) against the wrong component (the selected database's per-database HKB payload digest, not the aggregate manifest digest) | D-166: C2 binding check now compares only against `hkb_manifest` |
| v3 (first stop) | Mid-dispatch, C4 only | One C4 capture returns `response_contract_error`; job polled to `COMPLETE`, result retrieved, then capture-contract failure; 32 attempts staged, zero cohorts | Frozen harness classified a completed-job/no-parseable-query outcome as unstaged infrastructure failure instead of an evaluated-system terminal outcome | D-168: `job_result_observed` bit distinguishes completed/no-query from true infra failure; classified as `evaluated_system` |
| v3 (continuation) | Mid-dispatch, C4 only | A second, differently-shaped `response_contract_error` (completed job, no parseable query) after the D-168 fix landed; 48 attempts staged total across two receipts, zero cohorts | Same completed-job/no-query family as v3's first stop, different exact trace shape; V3 as a whole is retired and excluded from the successor run | D-168's fix already covers this class; V3 is not resumed — the next full attempt (v4) starts fresh with the fix baked in |
| v4 | Mid-dispatch, C4 only | 51 attempts staged, then stopped on `unsupported_semantic_result_type` | Omni returned a governed query and a terminal `ERROR` with a planner type (`UNKNOWN`) the frozen execution contract cannot score; a genuine product-contract gap, not a transient failure | D-169: same class of product-contract failure carried into sealed C4 as `evaluated_system`, no result artifact required |
| v5 | Mid-dispatch, C4 only | Job completes, produces a governed query, returns JSON rows, but strict capture binder rejects the rows against the AI Hub preview contract; 4 attempts staged, zero cohorts | Preview-row-count mismatch against the strict binder, even though usable typed rows were already returned by the same `run_query_json` call | D-170: on strict preview mismatch, replay the already-returned rows through the existing typed-result builder instead of failing closed; no second provider call |

General pattern across all five: the stop is always a **product/response
contract mismatch specific to C2 or C4**, never a scoring or correctness
issue, and every fix was a general classification/binding correction in the
frozen system, never a question-, database-, or label-specific patch. Watch
the dispatcher's stderr and the last-written `attempt.json` files under the
affected condition directory for the same shapes: a connection/attestation
error before any query (v1-shape), a binding mismatch before model execution
(v2-shape), or a `response_contract_error`/`unsupported_semantic_result_type`
class after job completion (v3/v4/v5-shape) in C4.

## 6. Pre-flight checklist before touching anything

- [ ] `git -C /home/ds/projects/omni-benchmark rev-parse HEAD` equals
      `94cc0d9483c944d7dc13ed651c8fc2ef077f33ab`. If not, stop — every
      finish-line step will refuse.
- [ ] For dispatch/continuation only: no other check needed beyond HEAD.
- [ ] For test-release or scoring: `git -C /home/ds/projects/omni-benchmark
      status --porcelain --untracked-files=no` is empty. If it is not
      (it currently is not), `git stash` the tracked changes first and
      restore them after — never commit to clear this, it moves HEAD.
- [ ] `ls runs/sealed-final-v6/cohorts` — if all twelve `c<N>-r<N>` directories
      exist, generation and finalization are already done; skip straight to
      step 2's Step B/C.
- [ ] If the dispatcher process is no longer running
      (`ps -p <pid>` empty) and cohorts are incomplete, this is a stop, not a
      pause — a continuation invocation is required (section 4).
- [ ] Before any continuation, confirm the exact argument set against the
      last live process's `/proc/<pid>/cmdline` (or the copy recorded in
      section 4) — do not reconstruct it from memory.
- [ ] Never rerun a trial because its answer was wrong. A continuation is
      only for the coordinates with no staged `attempt.json` at all.
- [ ] Never read, grep, or summarize `data/private/test/labels.jsonl` or any
      score artifact's per-attempt outcome outside the aggregate report.
- [ ] Do not commit to main until step C's `receipt.json` exists and both
      aggregate SHA-256s are recorded.

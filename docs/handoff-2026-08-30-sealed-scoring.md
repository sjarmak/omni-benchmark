# Handoff: sealed scoring blocked on freeze binding (2026-08-30)

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

Written at the end of a long session. Read this before touching the sealed lane.
Authoritative state is git and `bd`; this file explains what happened and why.

## Where things stand in one paragraph

The untuned sealed arm **finished generating**. All 1,068 attempts and all 12
cohorts exist and authenticate. No correctness has been opened: the gold has not
been released, no scorer has run, and nobody has seen a sealed outcome. Scoring
is blocked by a design deadlock between the frozen generation artifacts and a
scorer bug that had to be fixed. The agreed fix is to thread the generation
freeze through separately from the control freeze. That work is **not started**.

## Repository state

HEAD is `0429647c2cb655da30d7f12a7e2a6053fcd00589` on `main`, 5 commits past the
original control commit:

| Commit | What |
| --- | --- |
| `9a26f08` | codex: prepare exact E02 dev-A comparison |
| `168c9f1` | codex: record governed query-path analysis and MVP frontier (also committed this session's disclosure work and D-177..D-181) |
| `23a98bb` | codex: materialize E02 relationship endpoint aliases |
| `3389ae5` | **new system commit S'**: accept all evaluated-system C4 terminal classes in sealed scoring |
| `0429647` | **new control commit F'**: record Freeze B v8 |

Uncommitted and intentionally so: `docs/livesqlbench-upstream-loader-report-draft.md`
(codex's in-progress work, recovered from a stash) and `.beads/issues.jsonl`
(passive export, regenerates). Two stashes from 2026-08-29 predate this session
and were not created here; leave them alone.

Untracked but real: `docs/sealed-finish-runbook.md`,
`docs/custody-disposition-proposal.md`, `experiments/analysis/c4_mechanism_measurements.py`
and its test, `experiments/analysis/budget_clustering_test.py`,
`src/omni_benchmark/claude_lease_preflight.py` and its test.

## The blocker, precisely

Two gates guard sealed scoring and sealed test release, both via
`_require_exact_control_checkout` (`sealed_evaluation_cli.py:171`):

1. `git rev-parse HEAD` must equal the control commit.
2. `git status --porcelain --untracked-files=no` must be empty.

Two defects were found by running the preflight before releasing gold.

**Defect 1, worked around.** `load_sealed_execution_plan` defaults
`test_ids_path` to `TEST_IDS_PATH = "data/manifests/test_ids.txt"`
(`freeze_b_schedule.py:32`), the original **101**-question file, which Freeze B
never froze. The executed frame is the **89**-question `sealed_mvp_ids.txt`.
Neither `sealed_evaluation_cli.py` (scoring) nor `sealed_test_release.py` (gold
release) exposes a `--test-ids` flag or passes one; only `sealed_dispatch_cli.py`
does, which is why generation worked and both later steps fail. Worked around by
a driver that passes the correct frozen path; see below.

**Defect 2, fixed in `3389ae5`.** The C4 branch of `_generation_attempt`
(`sealed_evaluation.py:792-802`) accepted only `omni_job_terminal_failure`. The
run produced 32 `unsupported_semantic_result_type` and 4
`response_contract_error`, so 36 of 267 C4 attempts could not load and the batch
aborted. Cause: commit `34b7812` taught generation to emit these as distinct
classes; the validator was never taught them. Fixed via
`C4_EVALUATED_SYSTEM_FAILURE_CLASSES`; all three still map to
`CANDIDATE_EXECUTION_ERROR`. Comparison semantics unchanged. 98 tests pass across
the four sealed suites, ruff clean, and the tests prove the validator still
fails closed on an unknown class, a wrong `failure_origin`, and a non-errored
outcome.

**The deadlock.** Fixing the scorer requires a commit, which moves HEAD off the
control commit, so a new Freeze B (v8) was recorded to restore the binding. That
re-freeze is verified faithful: 108 frozen files with **no digest changed**, none
added or removed, schedule identical at `056a6c22...f87dec` with the same seed
and 89 questions, and both frozen scorer definitions byte-identical (Soft EX
still pinned to `e15cd221`). Only `system_commit`, `recorded_at`, and the
scorer's `source_commit` pointer differ. But every cohort `run.json` hard-records
`freeze_b_sha256: e1c9f196...` (**v7**), and `SealedRunManifest.from_dict`
validates it against the freeze passed in (now v8's `386bfebd...`), so all 12
cohorts are rejected with "sealed cohort run manifest is invalid"
(`sealed_evaluation.py:716`). The artifacts are cryptographically bound to the
freeze that produced them, and no re-freeze can change that.

## The agreed fix, not yet started

Stephanie decided: **thread the generation freeze through separately from the
control freeze.** They are two different concerns that the code currently
conflates into one `freeze_b` argument.

- Artifact validation (cohort run manifests, generation records) must validate
  against the **generation** freeze, v7 `e1c9f196...`, because that is the truth
  about how those artifacts were produced.
- The control gate binds the **current scoring** system, v8 `386bfebd...`.

Touch points: `load_sealed_output_batch` and `_load_cohort`
(`sealed_evaluation.py`), which currently receive a single `freeze_b`; and the
callers in `sealed_evaluation_cli.py`. Loading a v7 manifest currently requires
`load_freeze_b_control`, which enforces `HEAD == 94cc0d9`, so the generation
freeze needs a load path that does not re-assert the control gate. Keep every
existing integrity check; this is about passing the right freeze to the right
check, not relaxing either. Tests ship in the same commit.

While fixing this, also add `--test-ids` to `sealed_evaluation_cli.py` and
`sealed_test_release.py` so defect 1 stops needing a driver. That will require
another Freeze-B record, same as v8; the recipe is below.

## Recipe: how the v8 re-freeze was done

```
uv run python sealed_tools/record_freeze_b.py \
  --workspace /home/ds/projects/omni-benchmark \
  --system-commit <new system commit> \
  --input-spec config/freeze-b-input.json \
  --recorded-at <RFC3339 UTC, e.g. 2026-08-30T17:45:00Z> \
  --destination experiments/freeze-b-v9.json
```

`--recorded-at` must be UTC with `Z`; an offset like `-04:00` is rejected. Commit
the manifest **alone**: `_only_manifest_added` requires the control commit to add
exactly one file. Validate with `sealed_tools/validate_freeze_b_control.py`,
which takes `--manifest`, not `--freeze-b`. Then confirm against the previous
manifest that no frozen digest moved and the schedule sha256 is unchanged; if
either moves, stop.

Note `config/freeze-b-input.json` pins `schedule.ids_path` to
`data/manifests/sealed_mvp_ids.txt` with `question_count: 89`, so the recorder
is not affected by the bad `TEST_IDS_PATH` default.

## Verified run facts

Step A (`plan_sealed_generation.py`, read-only) passes at the original pair:
1,068 attempts, 12 cohorts of 89, 267 per condition, 356 per repetition, 16
databases, `plan_sha256`
`2d452a7377d05b93478052e649d087080d92745d39db0d540f08802eda14eeba`,
`schedule_sha256` `056a6c226ac3f7ea38750b26c89ba2e2eeb8aa9724438bedf93895150af87dec`,
`freeze_b_sha256` `e1c9f196...ae4730`.

Terminal outcome distribution, status fields only, no correctness:

| Condition | answered | notable non-answers |
| --- | ---: | --- |
| C1 | 179 | 38 insufficient-context, 33 budget, 13 rate limit |
| C2 | 198 | 31 budget, 16 insufficient-context, 15 rate limit |
| C3 | 169 | 55 insufficient-context, 22 budget, 16 rate limit |
| C4 | 229 | 32 unsupported result type, 4 response contract, 2 job terminal |

## Remaining sequence

1. Thread the generation freeze separately; add `--test-ids` to both CLIs; tests.
2. Record the next Freeze B over the corrected system; commit the manifest alone.
3. Preflight without `--execute-sealed-scoring`; expect `validated_not_scored`
   and all 1,068 attempts loading.
4. **Step B is human-only.** `release_sealed_test.py` needs the external private
   gold file from outside the workspace plus its SHA-256, and `--release-sealed-test`.
   Never agent-run.
5. Score, then render the report. Fill the 44 typed `SLOT_` tokens in
   `docs/report-draft-v2.md`; every slot names its source artifact and denominator.
6. Then the E02 named contrast, preregistered in D-180: the **primary readout is
   the query path** (`rewriteSql`, `join_via_map`, `join_paths_from_topic_name`),
   not accuracy. At most 15 non-correct attempts could plausibly convert and one
   correct attempt is at regression risk. Do not relax the KEEP/REVERT gate.

## Do not

- Do not rewrite cohort `run.json` or any generated artifact to satisfy a check.
- Do not change `dev_a_baseline_scoring.py:1129-1133`, which carries the same
  single-class pattern; that path produced published development numbers.
- Do not commit or move HEAD while a sealed step is mid-run.
- Do not touch the two 2026-08-29 stashes.
- Do not treat the mtime-based file monitor as agent attribution: a
  `git checkout` or `stash` rewrites every file differing between commits and
  looks identical to another agent editing.

## Session context worth keeping

The C4 query-path finding (D-178) reframed the study: Omni's agent authored SQL
through a rewrite path on every attempt because our conservative compilation left
the topics with no joins and no measures. Disclosed across `RESULTS.md`,
`docs/methodology.md`, `docs/harness-disclosure.md`, `docs/protocol-diff.md`, and
`README.md`; `EVALUATION_PROTOCOL.md` was amended after Stephanie accepted the
proposal (D-181). E05 is INCONCLUSIVE by its own preregistered precondition
(D-177, D-179) and parked on branch `feat/e05-typed-fields` in worktree
`/tmp/omni-benchmark-e05`. Ledger entries D-177 through D-181 carry the detail.

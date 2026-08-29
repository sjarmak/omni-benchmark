# omni-benchmark

Research evaluation of Omni's semantic layer on **LiveSQLBench Large-v1**. The
goal is evidence about *why* the system succeeds or fails, not a high score.
Read [README.md](README.md) first, then the doc that matches your task:

| Question | File |
| --- | --- |
| What is the preregistered design, custody, and freeze plan? | `EVALUATION_PROTOCOL.md` |
| What does the public benchmark actually contain, and what is unresolved? | `docs/benchmark-notes.md` |
| How does the optimization control plane work? | `docs/autoresearch.md` |
| What has been tried, and why? | `docs/research-log.md`, `experiments/` |
| Scorer semantics and the two frozen scorers | `docs/scoring.md` |
| Condition scaffolds and telemetry contract | `docs/harness-disclosure.md` |

Partitions: 332 eligible `Query` tasks, 231 development (154 `dev-A` adaptive,
77 `dev-B` metered), 101 sealed test. Conditions C1-C4 are defined in the README
table.

## Build and test

```bash
uv sync --dev
uv run pytest --cov=omni_benchmark --cov-branch   # branch coverage, fail_under=80
uv run ruff check . && uv run ruff format --check .
```

## Hard boundaries (do not relax for convenience)

- **Never** read, grep, index, or summarize hidden fields for the 101 test IDs.
  If test gold becomes visible, stop and document the contamination.
- Hidden dev-A annotations are **offline diagnostic input only**. They may shape
  how the system is built; they may never become question-specific runtime input.
  Dev-B per-question annotations remain guardian-only; development receives
  signed aggregate checkpoint receipts.
- Split membership, custody rules, scoring definitions, endpoints, and the
  protocol are human-controlled surfaces. Propose changes; do not make them.
- Never commit credentials, private gold, run artifacts, or sealed annotations.
- Never rerun a trial because its answer was wrong. Reruns require a demonstrable
  failure outside the evaluated system (see the protocol's rerun policy).

## Live-action authorization tiers

Authorization scales with contamination risk, not with whether an action is
"live". Recorded by Stephanie 2026-08-29 (`omni-benchmark-xeg`); this overrides
the global per-action external-approval rule for tier 1 only.

**Tier 1 - agent-autonomous.** Public semantic deployment, validation, and
exact-readback passes. Preconditions: public schema and public HKB only; no
questions, gold, hidden annotations, dev-B, test data, or correctness; isolated
`livesqlbench-*` branches only, never shared or main models. Retries are
permitted under a **new** run ID. Every terminal result is still preserved,
records stay append-only, and the run-ID claim stays exclusive. A compiler fix
between passes must still be general, tested, and free of any database name,
question, or label; that is enforced by reviewing the diff, not by rationing
passes.

**Tier 2 - one exact human authorization per action.** Anything that generates
evaluated answers (C1-C4 dispatch, E-series evaluation, sealed generation and
scoring), consumes a dev-B checkpoint, reads or releases protected data, or
mutates a shared/main Omni model. Single-use receipts, quarantine on failure,
and the no-retry rule are unchanged here.

Unchanged by this split: credentials, OAuth profiles, and leases remain
operator-owned; `git push` and other external artifacts still follow the global
per-action rule; the rerun policy still forbids rerunning a trial because its
answer was wrong.

## Gotchas

These cost time if you discover them by hitting them.

- **State artifacts refuse overwrite.** `_write_exclusive` writes mode `0600` via
  `O_EXCL` and raises `already exists; refusing overwrite`. Ledger, manifest, and
  checkpoint records are append-only. A botched record is fixed forward with a new
  record, never by deleting the file to retry.
- **The control plane reads git, not your working tree.** Autoresearch, custody,
  and probe commands verify `config/autoresearch.json` and `data/manifests/*`
  against the recorded Freeze A commit with `git show`. Uncommitted edits fail with
  "must be committed" or "must match the recorded commit". `--freeze-a-commit`
  needs the full 40-hex canonical hash; abbreviations are rejected.
- **The dev-B guardian digest is Freeze-A-protected.** Its private key remains
  outside agent scope. Never replace the committed digest during development.
- **dev-B is metered and single-use.** Hard maximum 10 checkpoints. Receipt and
  output hashes cannot be replayed, and each consumption marker must be committed
  before the next checkpoint is permitted.
- **Forbidden fields are rejected recursively.** Generation artifacts may not
  contain `sol_sql`, `gold_sql`, `test_cases`, `external_knowledge`,
  `test_correctness`, `gold_result`, or `expected_result` at any nesting depth.
  Correctness belongs in a separate immutable score artifact.
- **Broad gitignore patterns.** `*gold*.jsonl`, `*ground_truth*`, `*_gt*`,
  `data/raw/`, `data/private/`, `runs/`, `experiments/runs/`, and `.mcp.json` are
  ignored. A legitimately named new file can vanish silently; check `git status
  --ignored` if something you created will not stage.
- **Manifests are regenerated, never hand-edited.** Tests assert byte-identical
  regeneration from the pinned seeds and source hash. Fix inputs, rerun
  `scripts/prepare_benchmark.py` / `make_split.py` / `make_dev_split.py`.
- **Omni env contract.** Set exactly one of `OMNI_PROFILE` or `OMNI_API_TOKEN`.
  `OMNI_BASE_URL` must be an HTTPS origin with no embedded credentials. Values
  live in an untracked `.env`; `.env.example` is the only committed template.
- **Two frozen scorers, both reported.** Official Soft EX (pinned to evaluator
  commit `e15cd221`) reproduces lossy behavior on purpose. Do not "fix" it, and do
  not choose between scorers after seeing results.
- **Public Git remote boundary.** `origin` is
  `https://github.com/sjarmak/omni-benchmark`. Normal synchronization is allowed
  only under approved publish beads `omni-benchmark-dih.15` / `.16` and current
  per-action user authorization. Force-pushes, history rewrites, and every other
  remote are prohibited.
- Shell aliases may force `-i` on `cp`/`mv`/`rm` and hang the session. Use
  `cp -f`, `mv -f`, `rm -f`, `rm -rf`, and expand destructive paths literally.
- **OAuth profiles are leased, never repaired by benchmark agents.** Never
  refresh, rotate, copy back, or validate credentials while any Claude session
  or benchmark run may hold that identity; an auth failure pauses the lane for
  human-owned canonical login because refresh-token copies can revoke live
  sessions and turn benchmark attempts into infrastructure failures.
- Credential rotation is an operator-controlled recovery action, not routine
  benchmark maintenance. Establish exclusive ownership first, rotate once only
  if required, and keep the leased credential state stable until the run ends.

## Failure-mode preventions

- Never interpolate text containing backticks or `$()` into a shell command,
  including Beads fields; pass it through a file/stdin or literal-safe argument,
  or command substitution can execute embedded operator commands.
- Never treat a logged hypothesis or planned control as implemented; verify the
  exact run commit contains and tests it before calling it frozen, or a missing
  protection can invalidate the authorized trial.
- Never consume a live approval based only on dry-run success; validate the exact
  inherited provider environment first, or a missing `OMNI_BASE_URL` can spend
  the one-time receipt before any evaluated answer.
- Never let evaluation apparatus displace evaluation: use the smallest defensible
  check; defer all extra process unless it directly blocks MVP results.

## Working style

Every meaningful change starts with a hypothesis and ends in the ledger, including
the ones that failed. Log contemporaneously in `docs/research-log.md`; do not
reconstruct the story afterward. Classify each intervention's generality before
making it: question-specific changes are prohibited, benchmark-specific ones stay
out of the final system.

For the MVP, use one thin loop: focused checks, one immutable live attempt when
needed, then the next result-producing gate. Full-suite reruns, duplicate status,
worktree ceremony, and non-blocking reviews are optional; custody, frozen scorers,
append-only evidence, and exact evaluated/sealed authorization are not.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:1105d646 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

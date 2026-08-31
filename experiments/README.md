# Experiment artifacts

`experiments.csv` is a human-readable summary table retained from the initial
repository scaffold. It holds two rows and was never extended.

`config/autoresearch.json` configures an append-only JSONL ledger at
`experiments/autoresearch/ledger.jsonl`, written only by the validated lifecycle
tooling. **No run ever wrote to it and the file does not exist.** The optimization
phase was cut before the lifecycle tooling was exercised at scale (see the
2026-08-29 deviation in `docs/protocol-diff.md`), so the experiment history lives
instead in `docs/research-log.md`, which is contemporaneous and carries the
decision records, alongside the immutable per-run artifacts under
`experiments/autoresearch/raw/`, `experiments/deployments/`, and
`experiments/approvals/`.

**Decided 2026-08-31: keep the configured path, do not backfill.** Backfilling
would mean writing entries into an append-only ledger that no run produced, which
manufactures evidence rather than recording it; the absent file is the accurate
signal that the lifecycle tooling never ran at scale. Dropping the path is worse
than it looks: `config/autoresearch.json` is read out of the Freeze A commit with
`git show`, and the control plane compares the working tree against that commit,
so removing the field would fail every custody and probe command with a
must-match-the-recorded-commit error. `ledger_path` therefore stays as a declared
surface that the lifecycle code (`autoresearch_ledger.py`,
`autoresearch_lifecycle.py`) would write to if a future series exercises it. A
successor run that does use the lifecycle tooling gets a real ledger; this one
did not, and says so.

`PLUMBING-001` is a pre-label integration exercise. Its agreement labels mean
only that two repeated public dev-A result sets compare equal under the named
normalization policy; they are not LiveSQLBench correctness labels and must not
be included in accuracy calculations. The hash-bound raw evidence remains in
the ignored path named by the tracked receipt referenced from the row.

Checkpoint manifests and stop state live under `experiments/autoresearch/state/`
after real runs exist. They are intentionally absent at repository bootstrap:
creating empty or fabricated baseline/checkpoint records would weaken the audit
trail. The public-only baseline refers to all 231 development outputs. Adaptive
candidate checkpoints refer to complete 154-question `dev-A` runs and, only when
explicitly invoked, a separately metered 77-question `dev-B` run. Content hashes,
branch lineage, regression state, and Pareto membership make those references
immutable and auditable.

Large or secret-bearing raw execution artifacts must not be committed. Private
gold SQL, hidden knowledge annotations, hidden test cases, credentials, and raw
test results are prohibited in this tree. The sealed final evaluator writes only
its explicitly permitted output contract after the freeze.

`experiments/freeze-a.json` is created only in the metadata commit immediately
after the Freeze-A protocol commit. Its schema and two-commit ordering are fixed
in `EVALUATION_PROTOCOL.md`; no placeholder exists because a commit cannot
contain its own hash. No hidden development label may be released between those
two commits.

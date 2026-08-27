# Experiment artifacts

`experiments.csv` is a human-readable summary table retained from the initial
repository scaffold. The authoritative autoresearch history is the append-only
JSONL path configured in `config/autoresearch.json`; records are added only by
the validated lifecycle tooling.

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

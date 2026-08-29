# Omni on LiveSQLBench Large-v1

This repository evaluates whether Omni answers analytical questions more
accurately when LiveSQLBench business knowledge is represented and enforced
through Omni's semantic layer. The primary product result is governed Omni's
mean one-shot execution accuracy across three sealed repetitions; repetition-one
accuracy is reported separately. The primary comparison is governed Omni versus
a reasonably developed direct-SQL agent on the same held-out attempts.

Current status: Freeze A protocol frozen; its hash record is created in the
required follow-up commit. No private label or gold data belongs in this
repository or agent-accessible workspace.

For the current execution frontier, completed milestones, blockers, and the
remaining path to shareable results, see
[docs/mvp-status.md](docs/mvp-status.md). For the exact live human authorization
queue, see [docs/human-decisions.md](docs/human-decisions.md).

## Experimental design

The pinned public release contains 480 tasks. The reproducible preparation step
excludes 148 `Management` tasks and retains 332 `Query` tasks. A deterministic,
database-stratified split assigns 231 questions to supervised development and
101 to the sealed final evaluation. All 18 databases occur in both partitions.
The development set is split again into 154 adaptive optimization questions
(`dev-A`) and 77 metered checkpoint questions (`dev-B`).

The final evaluation freezes four conditions:

| Condition | Runtime representation | Query path |
| --- | --- | --- |
| C1 | Raw schema | Direct SQL |
| C2 | Searchable raw HKB | Direct SQL, optional reference |
| C3 | Searchable exported Omni model | Direct SQL, optional reference |
| C4 | Omni semantic model | Production-governed Omni |

C4 mean one-shot accuracy and the C4-C1 paired difference are the two primary
perspectives. All four conditions run three times on the held-out set, but there
is no majority vote. Rung-level C2-C1, C3-C2, and C4-C3 contrasts are exploratory.
See [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) and
[docs/methodology.md](docs/methodology.md) for the full preregistration. The
condition-specific scaffold and telemetry contract are disclosed in
[docs/harness-disclosure.md](docs/harness-disclosure.md).

## Setup

Requirements are Python 3.11 or newer, `uv`, and git.

```bash
uv sync --dev
uv run pytest --cov=omni_benchmark --cov-branch
uv run ruff check .
uv run ruff format --check .
```

Copy `.env.example` to an untracked `.env` only when connection details are
needed. Never place credentials in committed configuration.

## Reproduce the public manifest and split

Download the public `livesqlbench_large_v1_data.jsonl` from pinned dataset revision
`a418e108d5cbb4cf9b783a928eff5e924ad2460d` into the ignored `data/raw/`
directory. Verify its SHA-256 is
`f0e12218cb46f5b6e019908740a0b3303a1f8d1136c661545ad6dd1b4b5444f6`.

```bash
uv run python scripts/prepare_benchmark.py \
  --input data/raw/livesqlbench_large_v1_data.jsonl \
  --output-dir data/manifests \
  --source-commit a418e108d5cbb4cf9b783a928eff5e924ad2460d

uv run python scripts/make_split.py \
  --manifest-dir data/manifests \
  --seed omni-livesqlbench-large-v1-split-v1 \
  --train-size 231 \
  --test-size 101

uv run python scripts/make_dev_split.py \
  --manifest-dir data/manifests \
  --seed omni-livesqlbench-large-v1-development-split-v1 \
  --dev-a-size 154 \
  --dev-b-size 77
```

The tests verify byte-identical regeneration, exact counts, disjoint/exhaustive
membership, representation of all databases, and absence of protected fields.
`scripts/make_dev_split.py` deterministically derives the 154/77 internal split
from the committed 231 IDs and writes allocation diagnostics, including the
post-allocation `conditions.order` marginal.

## Reproduce the public HKB intermediate representation

Fetch and verify the 18 public HKB files, then regenerate the committed
provenance-preserving IR:

```bash
uv run python scripts/prepare_hkb.py fetch \
  --inventory config/public_hkb_sources.json \
  --destination-root data/raw/livesqlbench-large-v1/hkb

uv run python scripts/prepare_hkb.py build \
  --inventory config/public_hkb_sources.json \
  --source-root data/raw/livesqlbench-large-v1/hkb \
  --output-root semantic_models/public_ir
```

The generator validates all source hashes and the complete dependency DAG before
publishing output. It preserves every public definition and its dependency
provenance while leaving semantic representability explicitly unassessed. See
[`docs/hkb-semantic-baseline.md`](docs/hkb-semantic-baseline.md).

Fetch the independently pinned public DDL and column-meaning sources with:

```bash
uv run python scripts/prepare_schema_sources.py fetch \
  --inventory config/public_schema_sources.json \
  --destination-root data/raw/livesqlbench-large-v1/schema

uv run python scripts/prepare_schema_sources.py inspect \
  --inventory config/public_schema_sources.json \
  --source-root data/raw/livesqlbench-large-v1/schema

uv run python scripts/prepare_schema_sources.py build \
  --inventory config/public_schema_sources.json \
  --source-root data/raw/livesqlbench-large-v1/schema \
  --output-root semantic_models/public_schema_ir \
  --database archeology_scan_large \
  --companion-hkb-ir semantic_models/public_ir/archeology_scan_large.hkb.jsonl
```

The 36 source objects are verified against the same dataset revision before any
file is published. The canary compiler consumes DDL and column meanings only;
it does not consume the public sample rows embedded in the schema text. Its
committed row-free IR preserves tables, columns, structured leaves, and declared
keys while leaving HKB-to-schema interpretation to the next reviewed stage.
See [`docs/public-schema-sources.md`](docs/public-schema-sources.md).

## Gold custody

Keep the untouched private attachment outside this repository and outside any
agent-accessible workspace. Compute its SHA-256 without printing or parsing its
contents. Only after the pre-gold split commit exists may the human custodian run
the release tool to write exactly the 154 dev-A records into the ignored
`data/private/dev-a/` directory. Dev-B labels stay with the guardian:

```bash
uv run python sealed_tools/release_train.py \
  --source /path/outside/the/workspace/private-attachment.jsonl \
  --dev-a-ids data/manifests/dev_a_ids.txt \
  --destination data/private/dev-a/labels.jsonl \
  --freeze-a-commit "$FREEZE_A_COMMIT" \
  --workspace "$PWD"
```

The human custodian supplies the externally recorded full Freeze A hash. The
command verifies the canonical dev-A IDs and development-split metadata against
that commit, not the mutable current branch; rejects sources inside the
workspace; refuses overwrites; writes mode `0600`; and reports only counts and
hashes. It releases neither the 77 dev-B records nor the 101 held-out records.
The guardian scores dev-B checkpoints and returns signed aggregate receipts. The
final sealed evaluator is a separate post-freeze component and does not expose
test gold to development.

## Dev-A-only autoresearch

The optimization control plane is configured by
[`config/autoresearch.json`](config/autoresearch.json) and documented in
[`docs/autoresearch.md`](docs/autoresearch.md). It derives a `dev-A`-only public
optimization view, validates rich run artifacts, records hypotheses before
changes, gates `KEEP` on a full 154-question `dev-A` evaluation plus regression
evidence, meters `dev-B` checkpoints, preserves branching candidate lineage and
a small Pareto set, and terminates on an immutable stop record before held-out
scoring.

The loop is multi-objective rather than a scalar leaderboard: accuracy,
generality, regressions, cost/latency, complexity, and production relevance all
enter the explicit decision. Textual surfaces use systematic multi-candidate,
trace-guided search where useful; structural surfaces use targeted mechanism
experiments. Protocol/custody/scorer surfaces remain human-controlled. Hidden
train annotations are offline diagnostic inputs only and are prohibited from
runtime requests and ordinary run artifacts. The baseline first freezes exact
unscored public-only outputs; those same content-hashed outputs are scored only
after development labels are released. No baseline or experiment is
pre-populated.

The baseline manifest must be committed before supervised development and its
commit passed as `--baseline-commit` on later control-plane commands. Likewise,
each dev-B checkpoint's manifest and numbered consumption marker must be
committed before another checkpoint is permitted. These git commits are the
external rollback anchors for otherwise local append-only state.

Before any scaled run, verify the C4 production contract with one committed
public dev-A question. Configure `OMNI_BASE_URL`, `OMNI_MODEL_ID`,
`OMNI_BRANCH_ID`, and exactly one of `OMNI_PROFILE` or `OMNI_API_TOKEN` outside
git, then run:

```bash
uv run python scripts/omni_probe.py \
  --workspace "$PWD" \
  --config config/autoresearch.json \
  --freeze-a-commit "$FREEZE_A_COMMIT" \
  --system-commit "$SYSTEM_COMMIT" \
  --instance-id <committed-dev-A-id> \
  --output-root experiments/autoresearch/raw/c4-contract-probe \
  --run-id telemetry-smoke-v1 \
  --harness-config config/conditions/c4-production-v1.json \
  --prompt-spec config/prompts/c4-user-prompt-v1.txt \
  --instructions-spec config/instructions/c4-managed-instructions-v1.json \
  --budget-id c4-production-default \
  --execute-authenticated-smoke
```

The entry point verifies the config, split, and public manifest against the
recorded Freeze A commit, and requires the tracked system tree and run-spec
files to match `SYSTEM_COMMIT`, before authentication or submission. The output
root must be a new, previously nonexistent directory for every invocation. The
probe verifies the installed Omni CLI against the version and executable
SHA-256 pinned in the committed C4 condition, records the explicit semantic-model
branch separately from the managed LLM identity, and writes a
private raw-JSON result sidecar, reduced response-shape/trace artifacts, a
complete unscored `generation.jsonl`, and a generation-bound `run.json`. The
stdout receipt contains only paths, hashes, sizes, terminal state, and a hash of
the private Omni job ID. It never writes correctness or identity values.

The C1-C3 driver requires the exact read-only PostgreSQL coordinates in the
process environment (`PGHOST`, `PGDATABASE`, `PGUSER`, and `PGPASSWORD`) and a
private Claude Code OAuth directory. It forwards only the PostgreSQL allowlist
to the database transport, creates fresh empty `0700` home/temp/work directories
for the model invocation, and removes them afterward. Run this command once for
each direct condition, using the same public question, run ID, and repetition as
C4 and a new condition-specific output root each time:

```bash
uv run python scripts/direct_probe.py \
  --workspace "$PWD" \
  --system-commit "$SYSTEM_COMMIT" \
  --instance-id <committed-dev-A-id> \
  --condition <C1|C2|C3> \
  --output-root experiments/autoresearch/raw/<condition>-contract-probe \
  --run-id telemetry-smoke-v1 \
  --repetition 1 \
  --claude-config-dir "$CLAUDE_CONFIG_DIR" \
  --execute-authenticated-smoke
```

The shared committed direct-runtime policy pins the same provider, requested
model, effort, retry ceiling, turn limit, per-turn timeout, and per-turn cost
ceiling for C1-C3. Token ceilings remain explicitly unavailable because the
pinned Claude Code adapter exposes no supported token-limit setting; observed
provider tokens are captured as outcomes.

Once all four condition bundles exist, validate the cross-condition smoke gate
with four `--bundle CONDITION GENERATION RUN_MANIFEST MANIFEST_SHA256`
arguments:

```bash
uv run python scripts/autoresearch.py \
  --workspace "$PWD" \
  --config config/autoresearch.json \
  --freeze-a-commit "$FREEZE_A_COMMIT" \
  telemetry-smoke \
  --scope dev-a \
  --bundle C1 <c1-generation> <c1-run.json> <c1-manifest-sha256> \
  --bundle C2 <c2-generation> <c2-run.json> <c2-manifest-sha256> \
  --bundle C3 <c3-generation> <c3-run.json> <c3-manifest-sha256> \
  --bundle C4 <c4-generation> <c4-run.json> <c4-manifest-sha256>
```

## Repository map

```text
config/                 preregistration and optimization policy
data/manifests/         committed public manifest and split
docs/                   reconnaissance, methodology, findings, workflow
experiments/            append-only experiment metadata and checkpoints
scripts/                public preparation, split, and development tooling
sealed_tools/           human-custody boundary tools
src/omni_benchmark/     validated library implementation
tests/                  unit, integration, and workflow tests
```

Raw public downloads, private labels, secrets, and secret-bearing run artifacts
are gitignored. Product observations are appended to
[`docs/product-findings.md`](docs/product-findings.md); failed experiments remain
in the machine-readable autoresearch ledger and are never rewritten away.
The human-readable trajectory lives in
[`docs/research-log.md`](docs/research-log.md), while
[`docs/failure-taxonomy.md`](docs/failure-taxonomy.md) tracks the evolving
mechanism counts and top remaining failures at each checkpoint.

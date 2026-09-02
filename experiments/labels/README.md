# Failure-taxonomy label ledger

Each `<pass_id>.jsonl` file in this directory is an append-only ledger of
category judgments over immutable attempts. Git is the ledger; the telemetry
database's `attempt_label` table is a projection of these files and can be
rebuilt from them at any time. Plan of record: `docs/telemetry-db-plan.md`.
Category definitions: `docs/failure-taxonomy.md` (candidate taxonomy table).

## Rules

- **Append only.** A file gains lines; existing lines are never edited,
  reordered, or deleted. To retract or revise a judgment, append a new record
  with a later `created_at`; `attempt_label_latest` picks the newest record per
  (`attempt_id`, `generation_record_sha256`, `labeler`, `taxonomy_version`).
- **One pass per file.** The file stem is the `pass_id` (for example
  `c4-dev-a-human-v1.jsonl` gives `c4-dev-a-human-v1`). Stems match
  `[A-Za-z0-9][A-Za-z0-9._-]*`.
- **No private content.** A rationale may cite public attempt identifiers and
  aggregate observations. It must not quote gold SQL, hidden annotations,
  `external_knowledge` IDs, or any dev-B or test-partition correctness.
- **Dev-A only.** `scripts/label_attempt.py` reads `dev_a_ids.txt` and
  `test_ids.txt` from `--manifests-dir` (default `data/manifests`) before it
  writes, and refuses any attempt whose instance is outside dev-A. The loader
  re-checks every ledger line against the same files and refuses the whole
  load on a violation. A line whose (`attempt_id`,
  `generation_record_sha256`) matches no loaded attempt is set aside and
  counted as `label_attempt_not_loaded`; append a corrected line rather than
  editing the ledger.
- **Dev-A attempts only.** The label pipeline serves offline diagnosis of
  development attempts; sealed test attempts are never labeled per question.

## Record format

One JSON object per line, keys sorted, UTF-8, newline-terminated:

| Key | Value |
| --- | --- |
| `label_id` | sha256 over the JSON array `[pass_id, attempt_id, generation_record_sha256, labeler, taxonomy_version, created_at]`; derived on write and verified on read, so reloading a file is idempotent |
| `attempt_id` | attempt identifier from the generation record (`run:instance:condition:repetition`); the instance must be in dev-A |
| `generation_record_sha256` | 64 lowercase hex characters; pins the exact immutable record |
| `taxonomy_version` | `failure-taxonomy-v1` |
| `category` | one code from the table below |
| `labeler` | `human:<name>` or `model:<name>` |
| `rationale` | non-empty free text; public content only |
| `created_at` | ISO-8601 timestamp with an explicit UTC offset (`Z` or `+00:00`) |
| `pass_id` | equals the file stem |

Unknown keys, missing keys, a `label_id` or `pass_id` that disagrees with the
derived value, an unknown category, or a malformed labeler are rejected by
`omni_benchmark.telemetry_db.labels.parse_label_line`.

## Taxonomy `failure-taxonomy-v1`

Codes are the stable identifiers stored in `category`; titles are the row
names in `docs/failure-taxonomy.md`.

| Code | Title |
| --- | --- |
| `hkb_absent_or_mistransformed` | HKB absent/mistransformed |
| `hkb_dependency` | HKB dependency |
| `retrieval_discoverability` | Retrieval/discoverability |
| `retrieved_misinterpreted` | Retrieved but misinterpreted |
| `relationship_join` | Relationship/join |
| `metric_aggregation_grain` | Metric/aggregation/grain |
| `time_semantics` | Time semantics |
| `filter_value_alias` | Filter/value/alias |
| `semantic_compilation` | Semantic compilation |
| `validation_retry` | Validation/retry |
| `direct_reasoning` | Direct reasoning |
| `refusal_error` | Refusal/error |
| `scorer_data_ambiguity` | Scorer/data ambiguity |

Adding, renaming, or splitting a category is a new taxonomy version, defined
in `src/omni_benchmark/telemetry_db/taxonomy.py`; existing records keep their
`taxonomy_version` and remain valid.

## Commands

Append one human label (the record is printed as JSON):

```bash
uv run python scripts/label_attempt.py \
  --pass-id c4-dev-a-human-v1 \
  --attempt-id <attempt_id> \
  --generation-record-sha256 <64-hex> \
  --category relationship_join \
  --labeler human:stephanie \
  --rationale "Joined orders to customers on the wrong key; grain doubled."
```

Pin a timestamp instead of using the current time:

```bash
uv run python scripts/label_attempt.py ... --created-at 2026-09-01T12:00:00Z
```

Read every ledger in order (sorted file name, then line order):

```python
from pathlib import Path
from omni_benchmark.telemetry_db.labels import iter_label_records, label_rows

rows = label_rows(iter_label_records(Path("experiments/labels")))
```

Model-labeler passes write a whole `<pass_id>.jsonl` through the same
`append_label` function; they never rewrite a file. Build the cohort prompts,
label them, then ingest the whole pass in one shot:

```bash
uv run python scripts/build_label_prompts.py --out-dir <work>/prompts --batch-size 14
# a model assigns one category and rationale per attempt, writing
# <work>/labels/batch-NNN.json as [{attempt_id, generation_record_sha256,
# category, rationale}, ...]
uv run python scripts/ingest_label_pass.py \
  --input-dir <work>/labels \
  --manifest <work>/prompts/manifest.json \
  --pass-id dev-a-failures-model-v1 \
  --labeler model:claude-fable-5-1
```

`build_label_prompts.py` selects scored dev-A attempts by arm and outcome and
packages only the allowlisted public columns in
`omni_benchmark.telemetry_db.label_context`; repeated evidence fields are
de-duplicated and sampled at 40 values with the full count kept beside the
sample. `ingest_label_pass.py` refuses the whole pass unless every attempt in
the cohort manifest is labeled exactly once with a valid category, and it will
not touch a `<pass_id>.jsonl` that already exists.

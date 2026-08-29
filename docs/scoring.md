# Scoring policy

This project freezes two execution-result comparators before hidden development
labels are released. Both comparators consume already-executed rows. Neither
reads benchmark records, question IDs, SQL answers, or private annotations.

## Official-compatible Soft EX

Version `livesqlbench-soft-ex-e15cd221-v1` reproduces the Query-task comparison
path in the public LiveSQLBench evaluator at commit
`e15cd221267e06fabfaf6a3d4a69308280ce9a7c`.

Before execution, both candidate and gold SQL receive the public evaluator's
rewrites in this order:

1. remove block comments and newline-terminated line comments;
2. apply the pinned evaluator's regex-based attempt to remove standalone
   `DISTINCT` while retaining `DISTINCT ON`; this also unintentionally preserves
   some `DISTINCT` queries containing a later `JOIN ... ON`, which the local
   conformance fixture reproduces;
3. replace each `ROUND(expression, precision)` with its first argument,
   including nested calls.

This deliberately reproduces upstream behavior. It does not reinterpret whether
these rewrites are desirable SQL semantics. In particular, a line comment at end
of input without a newline is retained because that is what the pinned code does.

Executed rows are normalized as follows:

- top-level `date` and `datetime` values become `YYYY-MM-DD`;
- `Decimal` and `float` values are rounded recursively to two decimal places
  using decimal half-up rounding;
- top-level dictionaries and lists become JSON strings with sorted object keys.

When `conditions.order` is true, normalized sequences must be equal. Otherwise,
rows are compared as Python sets, so duplicate multiplicity is discarded. The
comparison fails when either result is empty, including when both are empty.

The official-compatible version is the benchmark-comparability score. Differences
between this pure comparator and the full official harness are listed below.

## Corrected sensitivity scorer

Version `omni-multiset-decimal-v1` leaves authored SQL unchanged and compares
results with stable typed values. It is a prespecified sensitivity analysis, not
a replacement for the official score.

- unordered results are compared as multisets, preserving duplicate rows;
- ordered results are compared as sequences;
- two empty results match, while only one empty result does not;
- null, boolean, numeric, string, date, mapping, and sequence values retain
  distinct canonical representations;
- dates and datetimes become `YYYY-MM-DD`;
- dictionary key order does not affect equality.

The public Large-v1 `conditions.decimal` values are
`{-1, 0, 1, 2, 3, 4, 5, 6, 8}`. The sensitivity policy gives them these frozen
meanings:

- `-1`: preserve the canonical numeric value without rounding;
- a nonnegative value: round `Decimal`, `float`, and integer values to that many
  decimal places using decimal half-up rounding.

Unknown values, booleans in place of integers, missing `decimal`, and non-boolean
`order` values fail validation. This makes a future public-data change explicit
instead of silently changing scoring.

## Frozen metadata

`scorer_metadata()` emits the scorer versions, official upstream commit, and
decimal-policy identifiers. Freeze manifests should store that object with the
scorer source commit. Any semantic change requires a new version string.

## Database execution integration

The pure scoring module intentionally stops at SQL rewriting and result
comparison. The integration layer is implemented in
`omni_benchmark.postgres_execution`, `omni_benchmark.postgres_isolation`,
`omni_benchmark.sealed_scoring`, and `omni_benchmark.sealed_batch`. It:

- executes rewritten candidate and gold SQL against separate clones of the same
  pristine PostgreSQL state for the official score;
- executes the unchanged authored SQL against equivalent isolated state for the
  sensitivity score;
- applies public `preprocess_sql` and `clean_up_sqls` in the correct lifecycle;
- preserves multiple-statement ordering and obtains rows with stable driver
  types;
- uses a distinct restricted role and read-only transactions for all candidate
  and gold SQL, while trusted setup/cleanup uses the clone-admin role;
- structurally admits only Query statements for generated candidate SQL and
  applies an evaluator-owned cancellation timer outside server SQL settings;
- rejects no-result statements without conflating them with a valid empty
  result; official overflow preserves the upstream prefix comparison with an
  explicit diagnostic, while sensitivity scoring rejects overflow;
- enforces the preregistered timeout and retry rules;
- distinguishes candidate-system failures from benchmark-infrastructure
  failures;
- records the three-state attempt outcome separately from result equality;
- keeps hidden test SQL and rows inside the sealed evaluator.

The public/synthetic suite covers each behavior, and an opt-in live conformance
test passed against a disposable PostgreSQL 18 template clone. See
`docs/sealed-execution.md` for the lifecycle, failure ownership, generate-then-
score gate, and the Freeze-B provenance contract. The final manifest is created
only after candidate selection and before any held-out generation.

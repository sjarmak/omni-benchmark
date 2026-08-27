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

## Database execution integration still required

The current module intentionally stops at pure SQL rewriting and result
comparison. The sealed evaluator still needs an integration layer that:

- executes rewritten candidate and gold SQL against the same isolated PostgreSQL
  state for the official score;
- executes the unchanged authored SQL against equivalent isolated state for the
  sensitivity score;
- applies public `preprocess_sql` and `clean_up_sqls` in the correct lifecycle;
- preserves multiple-statement ordering and obtains rows with stable driver
  types;
- enforces the preregistered timeout and retry rules;
- distinguishes candidate-system failures from benchmark-infrastructure
  failures;
- records the three-state attempt outcome separately from result equality;
- keeps hidden test SQL and rows inside the sealed evaluator.

Integration tests for those behaviors require provisioned benchmark databases.
They must be completed and frozen before Freeze B. The pure synthetic suite does
not claim database-execution equivalence by itself.

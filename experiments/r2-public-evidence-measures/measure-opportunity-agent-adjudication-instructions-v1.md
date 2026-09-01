# GPT-5.6 sol High instructions: R2 measure-opportunity adjudication

Use these instructions in a fresh ChatGPT conversation configured for model
`GPT-5.6 sol` with reasoning effort `High`. Attach only
`measure-opportunity-review-workbook-v1.csv`. Do not attach the accepted catalog,
repository, benchmark JSONL, run artifacts, or any other file.

The attached source workbook must have SHA-256
`5412b1b815df9cf0ca00b4fc673df2c8ca71ff1559cbb05bed0d4b6fa240d6ec`.
It contains 136 public dev-A questions and, for each question, the complete list
of already accepted measures from the same database. The catalog was frozen
before these questions were exposed to this review stage.

## Paste this task into ChatGPT

You are performing an outcome-blind semantic classification, not answering a
SQL benchmark and not reviewing whether the accepted measures are correct.

Your task is to review all 136 rows of the attached CSV and determine whether
one or more of the row's already accepted Omni measures could replace a metric
that the public question asks to compute. Return a completed CSV named
`measure-opportunity-review-workbook-v1-agent-adjudicated.csv`.

### Information boundary

Use only the contents of the attached workbook. You may use local data-analysis
or coding tools to parse, edit, and validate that CSV. Do not browse the web,
open the Hugging Face dataset page, download or parse LiveSQLBench JSONL, inspect
repository files, or use any other external source. Do not seek or use
`normal_query`, SQL, gold answers, expected results, correctness, generated
answers, hidden annotations, dev-B data, sealed-test data, or prior run outcomes.

The `question` cell in this workbook is an allowed public dev-A input. It is the
only question text you may inspect. The `eligible_measure_options_json` cell is
the complete allowed measure inventory for that row. Never invent a measure or
select a measure from another row merely because it looks relevant.

Do not answer any question, write SQL for it, estimate whether a system would
answer it correctly, or alter the accepted catalog. Classify only the semantic
opportunity visible in the row.

### Columns you may edit

Edit exactly these three columns:

- `decision`
- `measure_ids_json`
- `active_review_seconds`

Leave `active_review_seconds` blank on every row. Agent review time is
unavailable; blank means unavailable and must not be replaced by `0`.

Preserve every other cell exactly as supplied, including hashes, instance IDs,
database, question text, and the JSON string containing eligible options.
Preserve the exact header, column order, row order, and all 136 rows. Add no
columns and delete no rows.

### Allowed decisions

`decision` has exactly three allowed values:

- `mapped`: at least one eligible accepted measure is a clear semantic match
  for a metric the question asks to compute. `measure_ids_json` must contain all
  and only the clearly matching measure IDs and must not be empty.
- `none`: no eligible accepted measure is a clear semantic match for a metric
  the question asks to compute. `measure_ids_json` must be `[]`.
- `ambiguous`: the question appears to offer a measure-reuse opportunity, but
  the intended counted entity cannot be resolved defensibly from the question
  and option metadata, or two or more options remain genuinely plausible.
  `measure_ids_json` may contain the plausible measure IDs or may be `[]` when
  no specific option can be defended.

Do not create a reason code or a free-form rationale column. The downstream
contract consumes only the decision enum and selected measure IDs.

### Semantic mapping rule

Treat each eligible option as the count of distinct public identity values for
the entity described by its label, description, identity field, and view name.
Map an option when that distinct-entity count can supply an aggregate explicitly
or necessarily requested by the question. Filters, time windows, grouping, and
ranking do not prevent a match: a governed count measure may still be filtered
or grouped at query time.

Examples of the rule:

- "How many projects ...?" maps to the project count when that option exists.
- "Which sites have more than five artifacts?" maps to the artifact count,
  because the threshold requires counting artifacts; it does not map to the
  site count merely because sites are mentioned.
- "What percentage of projects are active?" maps to the project count because
  the same governed count can provide filtered and total project counts.
- "What is the average project budget?" does not map to a project count merely
  because projects are mentioned.
- A request for a sum, average, minimum, maximum, raw listing, attribute lookup,
  or descriptive breakdown is `none` unless the question also explicitly or
  necessarily requires one of the eligible distinct-entity counts.

Map the entity being counted, not every entity used as a filter, grouping key,
join path, subject, or descriptive dimension. A plural noun alone is not enough.
Do not infer a count opportunity solely because SQL could internally count rows
while solving another kind of metric. If the wording and option metadata do not
support one defensible match, use `ambiguous` rather than guessing.

When a question requests multiple distinct counts, include each clearly matching
measure. When one measure can be reused under multiple filters (for example, a
numerator and denominator over the same entity), list that measure ID once.

### JSON formatting

`measure_ids_json` must be a valid JSON array of strings on every row. IDs must
be copied exactly from that row's `eligible_measure_options_json`, sorted in
ascending lexicographic order, and unique. Use compact JSON, for example:

- `[]`
- `["r2m1m-abc..."]`
- `["r2m1m-abc...","r2m1m-def..."]`

### Required self-check before returning the file

Programmatically verify all of the following against the attached source CSV:

1. The output is UTF-8 CSV with the identical 11-column header.
2. It has exactly 136 data rows in the identical order, with every `instance_id`
   appearing exactly once.
3. Every non-editable cell is identical to the corresponding source cell.
4. Every decision is exactly `mapped`, `none`, or `ambiguous`.
5. Every `mapped` row has one or more selected IDs; every `none` row has `[]`.
6. Every selected ID occurs in that row's eligible option list, and selected IDs
   are sorted and unique.
7. Every `active_review_seconds` cell is blank.
8. No partial, extra, or explanatory rows or columns are present.

If any check fails, fix it before returning the file. If you cannot complete all
136 rows, report the failure and do not present a partial file as complete.

### Deliverables

Return:

1. the completed CSV file;
2. its SHA-256;
3. counts of `mapped`, `none`, and `ambiguous` rows; and
4. a concise provenance statement that names the product, model, and reasoning
   effort and explicitly confirms which inputs and tools were used; whether web
   browsing or any external file was accessed; whether any SQL, gold,
   correctness, hidden annotation, dev-B, sealed-test, or run-outcome data was
   accessed; and that active review seconds are unavailable rather than zero.

Do not claim that this is human review, independent domain validation, or a
measurement of manual review effort.

# Normalized provenance extract: ChatGPT measure adjudication

Status: observational provenance for a question-blind packet adjudication. This
is not a complete transcript and does not turn the workflow into a preregistered
agent comparison.

## Source and bounded window

- Shared record: <https://chatgpt.com/share/6a96c57e-01c0-83ea-aa79-5eda508be2f6>
- Page title: `Complete Spreadsheet Review`
- Retrieved for this extract: `2026-09-01T12:46:58Z`
- Adjudication window start: `2026-09-01T12:07:17.946000Z`
- Validator-compatible output: `2026-09-01T12:17:35.588452Z`
- Elapsed wall-clock envelope: `617.642452` seconds
- Product / model / effort: `ChatGPT` / `GPT-5.6 sol` / `High`

The operator's initial instruction was:

> fill out the open columns in the spreadsheet, and tell me if there is any
> additional context you need , it's based on this dataset:
> https://huggingface.co/datasets/birdsql/livesqlbench-large-v1

## Recovered adjudication

The agent loaded `measure-review-workbook-v1.csv`. For each row it parsed the
proposed `${view.field}` reference and the embedded `public_evidence_json`. It
accepted a row when all of these held:

1. `candidate_class` was `entity_count`;
2. embedded `identity_kind` was `primary_key`;
3. the SQL view equaled the workbook `view_name`; and
4. the SQL field equaled the suffix of `identity_field_stable_id` after
   lowercasing and removing non-alphanumeric characters.

The observed packet passed that rule for 812 of 812 rows. The first output used
the nonconforming reason `verified_primary_key_binding`. After the operator
supplied the frozen enum, one correction round produced 812 `accept` decisions
with reason `public_identity_and_binding_confirmed`. `binding_correction` and
`active_review_seconds` remained blank.

The bounded window contains two substantive user instruction messages, seven
assistant text messages, and 42 assistant tool-call messages. These are message
counts from the shared record, not independent task repetitions. Token usage,
cost, and human active time are unavailable.

## Information boundary and limitations

The agent reported that it did not download or parse the public benchmark
JSONL, inspect `query` or `normal_query`, iterate benchmark questions, or access
protected/gold information. It opened the Hugging Face landing page for context.
Its decisions used the workbook's embedded evidence and candidate metadata; it
did not independently load the underlying schema, column-meaning, or HKB files.

The proposed Omni YAML was produced by the deterministic benchmark generator,
not ChatGPT. This trace therefore measures packet adjudication, not measure
authoring and not Omni Modeling Agent performance. Raw shared-page HTML is not a
stable artifact: two immediate retrievals produced different byte hashes, so
the decision pipeline binds this normalized extract and the shared URL instead.

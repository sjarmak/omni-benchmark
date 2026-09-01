# Proposal: adopt the question-blind ChatGPT measure adjudication

**Status: exact amendment awaiting human approval. Not in force.** This proposal
does not authorize decision materialization, catalog freeze, question coverage,
deployment, or an evaluated attempt. The text between the markers is the exact
addition proposed for `EVALUATION_PROTOCOL.md`. Approval must name this file by
its final SHA-256 or Git blob.

This amendment is narrow. It changes only the catalog-review authorship and
burden contract in the already approved public-evidence measures extension. All
runtime arms, estimands, freeze order, custody boundaries, action receipts,
budgets, and stopping rules remain unchanged.

--- BEGIN EXACT PROPOSED AMENDMENT TEXT ---

## Amendment: question-blind agent adjudication of the measures packet

For `r2-public-evidence-measures-v1`, this amendment supersedes the requirement
that the sole human reviewer record a row-level decision and active review time
for every candidate. It also supersedes the corresponding claim that this series
measures manual human review burden. No other part of the development-only
extension is changed.

The measure candidates and proposed Omni YAML remain outputs of the deterministic
public-evidence generator. ChatGPT did not author, edit, or select the proposed
YAML. It adjudicated the already generated packet, and the repository operator
adopted that observed output at the artifact level without claiming to have
personally reviewed every row.

### Exact observed adjudication

The adopted adjudication is the existing, question-blind ChatGPT workflow whose
bounded provenance is
`experiments/r2-public-evidence-measures/agent-adjudication-provenance-v1.json`.
It records product `ChatGPT`, model `GPT-5.6 sol`, reasoning effort `High`, and
the public shared-record URL. Its input is the frozen blank workbook with
SHA-256
`0e756de6661060b1ebf14abb271be86f7121e4a28b9097d97d76cdf96522955e`;
its adopted output is
`measure-review-workbook-v1-validated.csv` with SHA-256
`94cabfcbcc997c99a6ef72f82b2781260203da965f73498c7133f8da8968ed9f`.
The output contains all 812 candidate IDs exactly once, changes no immutable
candidate cell, records 812 `accept` decisions with reason
`public_identity_and_binding_confirmed`, and leaves both
`active_review_seconds` and `binding_correction` blank on every row.

The adjudication read the workbook's embedded public evidence and candidate
metadata. It did not download or parse the public benchmark JSONL, inspect
`query` or `normal_query`, iterate benchmark questions, or use protected/gold
information, hidden annotations, dev-B, or sealed-test data. It opened the
public Hugging Face landing page for contextual verification. It did not
independently load or revalidate the underlying schema, column-meaning, or HKB
files, so its acceptance decisions are packet-level adjudication, not an
independent source audit.

The recovered mechanical rule accepts an `entity_count` candidate when the
proposed `${view.field}` reference names the workbook view, the embedded
`identity_kind` is `primary_key`, and the referenced field equals the suffix of
the embedded `identity_field_stable_id` after lowercasing and removing
non-alphanumeric characters. The first ChatGPT output used a reason outside the
frozen enum; one correction round replaced it with
`public_identity_and_binding_confirmed`. The adopted output must reproduce the
recovered rule exactly. This rule and the all-accept result describe the observed
workflow; they are not a general claim about review accuracy or domain authority.

### Provenance, validation, and freeze

Before the decisions can materialize, a new append-only approval record must
bind this exact amendment SHA-256 and Git blob plus the canonical provenance
artifact SHA-256. The agent-adjudication validator
must also authenticate the original approved protocol and approval record, the
catalog, blank workbook, adopted output workbook, normalized transcript extract,
and canonical provenance artifact by exact hashes. It rejects missing,
duplicate, or extra candidates; any immutable-cell change; a decision that does
not reproduce the recovered rule; a nonblank time or correction cell; altered
information-boundary metadata; noncanonical provenance; or a mismatched approval
chain.

The materialized decision artifact records `active_review_seconds: null`, not
zero, at both row and summary level and uses status `agent_adjudicated`. It
preserves every decision and reason, the recovered rule, the adjudicator
identity, the source and output hashes, the bounded transcript hash, and both
protocol approvals. The original human-review validator and its finite-time
requirement remain unchanged for any genuinely human-review artifact.

The decision artifact and accepted catalog freeze before any dev-A question or
question-coverage statistic is inspected. Only after that freeze may the
separate analysis-only question-to-measure opportunity map begin. If validation
or the approval chain fails, the adjudication is not partially accepted and the
series remains stopped.

### Narrow workflow-burden report

The adjudication workflow is observational and was not preregistered as an agent
comparison. Report only the facts recoverable from the shared record: an elapsed
wall-clock envelope of `617.642452` seconds, two substantive user instruction
messages, seven assistant text messages, 42 assistant tool-call messages, and
one correction round. Human active time, token usage, and monetary cost are
unavailable and must be reported as null, never zero. No comparison to manual
labor, time saved, or authoring efficiency is permitted.

This workflow does not evaluate Omni's Modeling Agent. That remains a separate,
future Sandbox-only authoring comparator using public inputs, with query-history
analysis prohibited. It cannot alter the adopted R2 catalog or contribute to
the primary semantic-replacement claim.

### Unchanged limits

The primary estimand remains verified semantic replacement caused by adding the
frozen measures to `R2-M1` relative to contemporaneous `R2-C5B`. Accuracy,
reliability, and cost remain secondary. The strongest supported claim remains
limited to governed reuse of this deterministically generated,
agent-adjudicated public-evidence catalog on the dev-A frame. The series cannot
establish domain correctness, independent review accuracy, manual modeling
burden, customer-wide value, held-out generalization, or Omni Modeling Agent
quality.

D-196, the requirement that approved protocol text be committed before live
control-plane use, full-source cleanup, credential ownership, action-specific
receipts, budget preflights, exact deployment readback, append-only evidence,
and the no-wrong-answer-rerun rule all remain in force. This amendment authorizes
no dev-B or sealed-test access and no live action by itself.

--- END EXACT PROPOSED AMENDMENT TEXT ---

## Bound evidence prepared before approval

- Adopted workbook SHA-256:
  `94cabfcbcc997c99a6ef72f82b2781260203da965f73498c7133f8da8968ed9f`
- Normalized transcript extract:
  `experiments/r2-public-evidence-measures/agent-adjudication-transcript-extract-v1.md`,
  SHA-256
  `09a10ff233e294e79fb867e20f64a17befdac10c2d0d69baf4f81a34033f85aa`
- Canonical provenance artifact:
  `experiments/r2-public-evidence-measures/agent-adjudication-provenance-v1.json`,
  SHA-256
  `c6e82efc4cb1f069cd5a257de4f7d1cc68e20cc8ee507e14c9c2a92e8bb7b1b0`
- Original exact protocol proposal SHA-256:
  `8495d6fb57c1e4060e34b97bd8ef9da79fd7fb78c268009aee8e5b1c072539c6`
- Original protocol approval-record SHA-256:
  `3cbd7f3483bb9ff248b3c6f3aea6b140c64c91b4c72b18236a1ecf6a91af6b73`

The decision artifact does not exist. Question coverage has not been inspected,
and no deployment or evaluated attempt has occurred.

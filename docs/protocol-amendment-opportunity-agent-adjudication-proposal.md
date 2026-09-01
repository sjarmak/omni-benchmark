# Proposal: agent-adjudicate the R2 measure-opportunity packet

**Status: exact amendment awaiting human approval. Not in force.** This proposal
does not authorize the adjudication run, decision materialization, opportunity-map
freeze, deployment, receipt creation or consumption, or an evaluated attempt.
The text between the markers is the exact addition proposed for
`EVALUATION_PROTOCOL.md`. Approval must name this file by its final SHA-256 or
Git blob.

This amendment is narrow. It replaces only the pending human authorship and
active-time requirements for the 136-row public dev-A opportunity-map pass. It
does not alter the already frozen accepted measure catalog, the mapping decision
semantics, the primary estimand, runtime inputs, arms, settings, scoring, custody,
budgets, receipts, or stopping and retry rules.

--- BEGIN EXACT PROPOSED AMENDMENT TEXT ---

## Amendment: outcome-blind agent adjudication of the measure-opportunity packet

For `r2-public-evidence-measures-v1`, this amendment supersedes the requirement
that the separate 136-row public dev-A question-to-measure opportunity pass be
performed as manual human review with finite row-level active review seconds. It
also supersedes the corresponding requirement to report human opportunity-map
review time. No other part of the development-only extension or the prior
question-blind catalog-adjudication amendment is changed.

The opportunity decisions are agent-adjudicated and may be adopted by the
repository operator at the artifact level. They must not be described as human
review, independent validation, domain-expert judgment, or evidence of manual
review burden. Human active time, agent active time, token use, and monetary cost
are unavailable unless directly evidenced; unavailable values are reported as
null, never zero.

### Exact prospective adjudication contract

The only adjudication input is
`experiments/r2-public-evidence-measures/measure-opportunity-review-workbook-v1.csv`,
SHA-256
`5412b1b815df9cf0ca00b4fc673df2c8ca71ff1559cbb05bed0d4b6fa240d6ec`.
It contains exactly 136 public dev-A `query` values and, for each question, the
complete same-database option list from the already frozen accepted catalog,
whose SHA-256 is
`2d2f9c15bc5f5271db924fa4377b41c26a0e61bcec221ed31d10b3365358039a`.
The adjudication is run in a fresh ChatGPT conversation using model `GPT-5.6
sol` at reasoning effort `High` under the exact instructions in
`experiments/r2-public-evidence-measures/measure-opportunity-agent-adjudication-instructions-v1.md`,
SHA-256
`0a7e8a114be05a6369d811bcf245836a5c86dead112601db0dba3efcb3169e67`.

The adjudicator may use local data-analysis tools to read, write, and validate
the workbook. It may use no other input: no web browsing, dataset landing page,
benchmark JSONL, repository file, accepted-catalog file, `normal_query`, SQL,
gold or expected result, correctness, generated answer, hidden annotation,
dev-B data, sealed-test data, or prior run outcome. The public `query` cells in
the workbook are allowed only for this analysis-only mapping pass. The pass
occurs after accepted-catalog freeze and before either arm, and its decisions
cannot alter the catalog, semantic bundles, prompts, job bodies, or runtime.

For every row the adjudicator records exactly one decision from `mapped`,
`none`, or `ambiguous` and a sorted, unique JSON array containing only measure
IDs present in that row's frozen eligible-option list. `mapped` requires at
least one selected measure; `none` requires an empty array; `ambiguous` may
retain zero or more plausible options. A measure is mapped only when its
distinct-entity count can supply an aggregate explicitly or necessarily
requested by the public question. Measures are not mapped merely because their
entities occur as filters, groups, joins, subjects, or descriptive dimensions.
The adjudicator leaves `active_review_seconds` blank on every row and changes no
other cell.

### Output adoption, validation, and freeze

The adjudication output has no authority merely because the model produced it.
Before materialization, a canonical provenance artifact must bind the product,
model, reasoning effort, exact instruction and input hashes, exact output hash,
available session evidence, and explicit information-boundary attestations. The
repository operator must then approve and adopt that exact output by SHA-256 in
a new append-only approval record. A replacement or corrected output requires a
new hash and a new adoption; approval is never inferred from a filename.

An agent-adjudication validator must authenticate this amendment and its
approval, the instruction file, the frozen accepted catalog, the deterministic
blank workbook, the observed output, the canonical provenance artifact, and the
output-adoption record by exact hashes. It rejects a missing, duplicate, extra,
or reordered row; any changed immutable cell; a decision outside the frozen
enum; a selected measure not present in that row's same-database options;
unsorted or duplicate IDs; `mapped` without an ID; `none` with an ID; a nonblank
active-time cell; noncanonical provenance; or a mismatched approval chain. The
existing finite-time human-review validator remains unchanged for genuinely
human opportunity reviews.

The materialized, question-text-free opportunity artifact records adjudication
status `agent_adjudicated` and `active_review_seconds: null` at row and summary
level. It binds the adjudicator, instructions, input, output, provenance, and
both approval stages. It preserves every decision and selected measure ID but
contains no question text or eligible-option payload. Only a fully validated
and adopted artifact may freeze the opportunity set; partial acceptance and
agent-side repair by the benchmark harness are prohibited.

### Reporting and unchanged inference limits

The primary opportunity set remains the rows decided `mapped`, frozen before
either evaluated arm. Report the complete 136-row distribution of `mapped`,
`none`, and `ambiguous`, selected-measure counts, and all available workflow
provenance. The opportunity map is an outcome-blind semantic classification by
one specified agent workflow, not an estimate of human agreement or domain
authority. Ambiguous rows remain outside the primary opportunity denominator
and are disclosed; no decision may be changed after outcomes are observed.

The primary estimand remains verified semantic replacement caused by adding the
frozen accepted measures to `R2-M1` relative to contemporaneous `R2-C5B`.
Accuracy, reliability, and cost remain secondary. The strongest supported claim
is limited to governed reuse of the deterministically generated,
agent-adjudicated catalog on the opportunity set classified by this separately
specified, outcome-blind agent workflow. The series cannot establish catalog
domain correctness, opportunity-map human agreement, manual modeling burden,
customer-wide value, held-out generalization, Omni Modeling Agent quality, or a
causal effect outside the paired conditions as deployed.

D-196, Git landing of all approved protocol text, full-source cleanup,
credential ownership, action-specific receipts, budget preflights, exact
deployment readback, append-only evidence, and the no-wrong-answer-rerun rule
all remain in force. This amendment authorizes no dev-B or sealed-test access
and no deployment or evaluated action by itself.

--- END EXACT PROPOSED AMENDMENT TEXT ---

## Bound pre-adjudication evidence

- Blank opportunity workbook SHA-256:
  `5412b1b815df9cf0ca00b4fc673df2c8ca71ff1559cbb05bed0d4b6fa240d6ec`
- Frozen accepted catalog SHA-256:
  `2d2f9c15bc5f5271db924fa4377b41c26a0e61bcec221ed31d10b3365358039a`
- Exact adjudication instructions SHA-256:
  `0a7e8a114be05a6369d811bcf245836a5c86dead112601db0dba3efcb3169e67`
- Exact adjudication instructions Git blob:
  `fd52dc212be0901f37e07943f992d40ec6cc8e3e`

No adjudicated opportunity workbook, opportunity-map provenance artifact,
output-adoption record, or materialized opportunity map exists yet. The prior
human-review task remains authoritative until this exact amendment is approved
and its approval record is materialized.

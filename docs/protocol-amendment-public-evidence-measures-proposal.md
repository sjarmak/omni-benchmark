# Proposal: public-evidence measures mechanism series

**Status: exact proposal awaiting human approval. Not in force.** Nothing in
this document authorizes a deployment, an evaluated attempt, a protocol change,
or access to dev-B or the sealed test partition. The text between the markers
below is the exact addition proposed for `EVALUATION_PROTOCOL.md`. Approval must
name this file and its Git blob or SHA-256 after the diff is final.

This proposal is the decision surface for Beads issue `omni-benchmark-w5x`. It
supersedes that issue's original `rewriteSql` / `join_via_map` outcome language,
which D-211 showed cannot discriminate semantic composition. It does not approve
the broader custody changes proposed in
`docs/protocol-amendment-dev-tier-draft.md`.

--- BEGIN EXACT PROPOSED PROTOCOL TEXT ---

## Development-only extension: public-evidence measures mechanism series

This post-result development series asks one narrow product question: when an
Omni model contains measures supported entirely by public evidence, does the
production agent reuse those governed definitions instead of rebuilding the
same metrics as inline aggregates? It also measures the human authoring burden
required to produce the eligible catalog.

The series is exploratory, dev-A-only, and named
`r2-public-evidence-measures-v1`. It does not change the frozen C1-C4 study,
restate any sealed result, or claim that LiveSQLBench supplies a
domain-authoritative customer model. It has no dev-B checkpoint, sealed-test
arm, or promotion path.

### Population, arms, and budget

The population is the same complete 136-question dev-A frame and the same 16
publicly deployable databases used by C5. The series contains exactly two new
arms with one immutable attempt per question:

| ID | Condition |
| --- | --- |
| `R2-C5B` | A contemporaneous C5 bridge: all public tables, qualifying public-FK joins, complete public HKB context, and no measures. |
| `R2-M1` | The identical condition plus only the accepted public-evidence measures frozen by the review process below. |

The evaluated-attempt budget is 136 per arm and 272 total. A dry plan must
project no more than USD 500 per arm and USD 1,000 total under the existing
budget policy; exceeding either projection returns the series to the human
surface rather than changing the ceiling. The attempt ceiling, not estimated
dollars, is the operational stop. Credit usage, tokens, and latency are
outcomes. A partially completed arm is not extended with replacement attempts
except under the existing exogenous-failure rerun policy.

The schedule is generated before either arm runs from the public IDs and seed
`omni-livesqlbench-large-v1-r2-measures-schedule-v1`. It is a deterministic,
database-block-interleaved schedule with arm order balanced across the 136
question pairs. Regeneration must be byte-identical. Each arm uses a fresh
isolated `livesqlbench-*` deployment identity and independent agent sessions.

The following complete current Balanced profile is materialized in every model,
not inherited from instance defaults:

```yaml
ai_settings:
  query_all_views_and_fields: enabled
  validate_analysis: disabled
  conversation_prune_length: max
  analyze_configuration:
    model: standard
    thinking: none
  build_configuration:
    model: smartest
    thinking: none
  simple_summarize_configuration:
    model: fastest
    thinking: none
```

This block is pinned from Omni's published Balanced profile as checked on
2026-08-31. Explicit materialization is required because Omni documents
different defaults for instances created on or before 2026-03-05 and
2026-04-23. Both arms also pin the benchmark revision, database snapshot,
136-question membership and schedule, public schema and HKB inputs, prompt,
harness and runtime commit, model and provider observations, condition bundles,
deployment readbacks, and both scorer versions. Historical C5 is context only;
it is not the control arm.

### Measure authority and complete candidate generation

Candidate generation reads only the committed public schema IR and public HKB.
It runs over every view in all 16 databases before any dev-A question or question
coverage statistic is read. Candidates are sorted deterministically and carry
stable IDs. Exactly two candidate classes are permitted:

1. An entity-count measure may be proposed only when public schema evidence
   declares one resolved single-column primary or unique key for the entity.
   The measure uses that key with `aggregate_type: count_distinct`; it is not a
   row count. Composite or inferred identity is ineligible.
2. An HKB-derived measure may be proposed only when public text explicitly
   states one supported aggregation over one named source role and that role,
   entity grain, and every relationship resolve from public evidence. For this
   first version, the frozen machine-explicit grammar is a single top-level
   `AVG`, `AVERAGE`, `SUM`, or `COUNT_DISTINCT` call, optionally preceded by a
   label and equals sign. The source binding must be exact, the mapping must be
   same-grain and compileable, and dependencies must be empty. Natural-language
   aggregation, row-level formulas, multi-input expressions, dependent
   measures, and cross-grain definitions are screened with their source IDs;
   they may enter a separately reviewed catalog version but are not completed
   by inference here.

Numeric type alone never licenses `sum`, `average`, or another aggregation.
Unstated formulas, guessed identities, unresolved fields, ambiguous
cardinalities, and unresolved cross-grain definitions are excluded or deferred.
The generator may bind public evidence to Omni syntax; it may not invent missing
semantics.

Each candidate packet contains the stable candidate and measure IDs, database
and view, candidate class, proposed Omni YAML, canonical aggregation signature,
dependency closure, grain and identity evidence, relationship evidence, source
paths and hashes with bounded public excerpts, compiler disposition, and a blank
review record. The packet set records its input-tree hashes, generator version,
ordered candidate IDs, and content hash. Regeneration from the same inputs must
be byte-identical.

### Human review and freeze order

The human operator who approved this design is the sole measure reviewer. The
review packet contains no dev outcome, correctness, question text, question
coverage, hidden annotation, or sealed information. For every candidate the
reviewer records `accept`, `reject`, or `defer`, one standardized reason, active
review seconds, and optionally a mechanical binding correction. Active review
seconds must be finite and nonnegative. The frozen reason policy is:

- `accept`: `public_identity_and_binding_confirmed` or
  `mechanical_binding_corrected`;
- `reject`: `binding_mismatch`, `duplicate_measure_name_conflict`,
  `identity_not_semantically_unique`, `not_an_entity`, or
  `public_evidence_insufficient`;
- `defer`: `needs_domain_authority`, `needs_grain_authority`, or
  `reviewer_uncertain`.

The deterministic workbook binds every immutable row to the source catalog's
file hash, internal hash, candidate ID, candidate payload hash, measure ID,
public evidence, proposed YAML, and aggregation signature. It contains every
candidate exactly once and begins with all reviewer cells blank. Completed
decisions cannot be materialized until an append-only approval record binds the
exact proposal SHA-256 and Git blob approved by the operator. Validation rejects
missing or duplicate candidates, immutable-cell edits, extra columns,
incomplete timing, and decision-incompatible reasons.

A correction may repair a field name, dependency binding, or equivalent syntax
only when the same public evidence still proves the unchanged semantic
definition. It must retain the frozen source stable ID and target view and is
recorded as `requires_public_evidence_validation`; the benchmark agent must
validate that binding against the public C5 inputs before catalog freeze. The
correction may not supply missing domain knowledge or change aggregation,
formula, entity identity, or grain. A correction that cannot pass that check, or
a semantically changed candidate, is rejected or deferred and may enter a later
catalog version, never the current one.

The complete candidate set is reviewed before acceptance counts or question
coverage are computed. The accepted catalog, all decisions, review burden, and
their hashes then freeze as `public-evidence-measure-catalog-v1`. Rejected and
deferred candidates remain in the decision artifact so selection is auditable.

Omni's Modeling Agent does not author, edit, or select this catalog. In
particular, its query-history workflow is prohibited because prior warehouse
query patterns could make treatment authoring depend on benchmark activity. A
separately preregistered authoring-workflow evaluation may later use the
Modeling Agent in Sandbox mode on the same public schema, public HKB, and C5
model only. Its proposed diff must be preserved and scored against this already
frozen human-reviewed catalog; it cannot alter `R2-M1` or support the causal
mechanism claim.

Only after that catalog freeze does the reviewer see the public dev-A questions.
In a separate pass, each of the 136 public IDs is mapped to zero or more already
accepted measure IDs, `none`, or `ambiguous`. The committed opportunity artifact
contains IDs and decisions, not copied question text. It records review time and
freezes before either arm. The map is analysis-only: it is prohibited from model
files, `ai_context`, prompts, job bodies, retrieval, or any other runtime input,
and it cannot change the accepted catalog.

If the accepted catalog is empty, or if the frozen opportunity map contains no
question mapped to an accepted measure, the series stops before deployment or
evaluated spend. That null result is reported as a limitation of what strict
public evidence can support.

### Primary mechanism estimand

The primary denominator is every scheduled question pair in the frozen
opportunity set, including refused, errored, or unparseable attempts. This is an
intention-to-treat mechanism estimate. Parseable-pair results are reported only
as a labeled sensitivity analysis.

Before execution, each accepted measure records a canonical inline-equivalent
signature: aggregation type or normalized formula plus its resolved source
field and dependency IDs. The classifier and its fixtures freeze with the
series. It reads generated semantic-query structure and authored SQL, but no
correctness or result value.

A treatment attempt uses an accepted measure only when its structured query or
`${view.measure}` token resolves to a measure ID mapped to that question. A
**verified semantic replacement** is a scheduled opportunity pair in which:

1. the bridge contains an inline aggregate matching the mapped measure's frozen
   equivalent signature;
2. the treatment references that accepted measure; and
3. the treatment does not recreate the same equivalent inline aggregate.

An unresolved parse, unmatched formula, refusal, or evaluated-system error is
not a verified replacement in the primary analysis and is separately counted.
No `rewriteSql` or `join_via_map` value participates in this classification.

The primary report gives the exact replacement numerator and opportunity
denominator, the rate, and a Wilson 95% interval. It also reports accepted-measure
utilization, inline-aggregate prevalence, and unresolved classifications on the
same opportunity set. Interpretation is fixed:

- one or more verified replacements means the mechanism was observed; the rate
  and interval, not a post-hoc threshold, describe practical magnitude;
- accepted-measure references without replacements mean measures were available
  but their contribution is additive or ambiguous;
- zero accepted-measure references mean measures were available but unused;
- a broken or incomplete evidence contract makes the mechanism result
  inconclusive and does not authorize a replacement run.

### Secondary outcomes and product decisions

The modeling-burden report gives candidates proposed, accepted, rejected, and
deferred; reason frequencies; corrections; active review minutes; accepted
catalog size; database coverage; and opportunity-question coverage. These
metrics inform whether Omni needs better authoring, grain declaration,
validation, or observability even if accuracy is flat.

Both frozen correctness scorers are always co-reported on all 136 attempts per
arm. Report exact accuracy, wrong-answer, refusal/error, and result-contract
counts; paired arm differences; tokens, latency, tool and database-query counts;
measured credit cost where the bracket is valid; total arm spend; and cost per
scheduled, answered, and correct attempt. Efficiency claims require comparable
output coverage. If coverage differs materially, cost is descriptive and is not
called a saving.

Paired accuracy and cost differences use 10,000 question-level paired-bootstrap
replicates, the existing `sha256_modulo_question_count_v1` algorithm, seed
`omni-livesqlbench-large-v1-r2-measures-analysis-v1`, and the existing
nearest-rank 95% interval. One repetition estimates variation across these
questions; it does not estimate generation-to-generation variance. No binary
significance decision is made.

The strongest supported claim is limited to governed reuse of the reviewed
public-evidence measures on this dev-A frame, together with the measured
authoring burden. Accuracy or cost changes are secondary system-level results.
The series cannot establish domain correctness of the catalog, customer-wide
value, held-out generalization, or a causal effect for any setting other than the
paired conditions as deployed.

### Custody, authorization, and stopping

The existing frozen scorers, no-wrong-answer-rerun rule, append-only exclusive
artifacts, exclusive run IDs and quarantine, recursive forbidden-field checks,
deployment validation and exact readback, runtime-commit guard, and
contemporaneous research log all remain mandatory. The question-to-measure map
is public analysis metadata, never runtime supervision. Hidden dev-A annotations
remain offline diagnostics and may not enter this series' catalog, map, model,
prompt, or classifier. Dev-B and the 101 sealed IDs remain untouched.

Human approval of this exact amendment opens only this named development series.
It does not waive action-specific receipts, credential ownership, source-cleanup
gates, budget preflights, or the rerun policy. D-196 continues to block live
action until the approved text has landed and every existing prerequisite is
green. Once those conditions hold, D-196 is superseded only for the exact
`R2-C5B` and `R2-M1` deployments and 272-attempt schedule described here.

--- END EXACT PROPOSED PROTOCOL TEXT ---

## Evidence used to prepare the proposal

- [Omni Balanced AI settings](https://docs.omni.co/guides/ai/tuning-cost-quality)
  provides the explicit profile and documents the instance-age defaults.
- [Omni measures](https://docs.omni.co/modeling/measures) recommends
  `aggregate_type` for standard measures so Omni can protect against join fanout.
- [Omni aggregate types](https://docs.omni.co/modeling/measures/parameters/aggregate-type)
  defines `count_distinct` and measure-on-measure formulas.
- [Omni Modeling Agent](https://docs.omni.co/ai/model-assistant) documents
  Sandbox review of proposed model diffs and a separate query-history workflow;
  those capabilities motivate the isolated future authoring comparator rather
  than treatment authoring in this series.
- D-211 and `experiments/analysis/governed-query-path-tally-v2.json` establish
  why measure references and inline aggregates replace the obsolete path fields.

## Exact approval requested later

After this proposal and its supporting implementation tests are final, the
operator will be asked one question: approve the exact marked text, identified
by its final hash, for insertion into `EVALUATION_PROTOCOL.md`? Until that answer
is recorded, the proposal remains non-operative and no live action is permitted.

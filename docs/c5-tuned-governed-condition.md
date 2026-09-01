# C5: docs-idiomatic tuned governed Omni

> **Corrected 2026-08-31 (D-211).** This document describes the governed query
> path as a "raw-SQL rewrite path" taken on every attempt, with `join_via_map`
> empty as evidence that no query composed. That reading does not survive
> remeasurement. `rewriteSql` is Omni's documented default for any query carrying
> `userEditedSQL`, so it is true on all 661 parseable governed attempts and
> discriminates nothing; `join_via_map` is populated on topic readback, not on
> query submission, so its count of zero measured a field this pathway never
> sets. The authored SQL references the deployed model through `${view.field}`
> templating on 660 of 661 attempts, and most attempts also take the model's join
> scope through `join_paths_from_topic_name` (69.6% dev-A C4, 98.5% C5). What the
> model never supplied is the metric: an aggregate hand-written over a field
> reference appears on 34.1% of dev-A C4 and 38.1% of C5, which is Omni's
> documented signal for a topic with no measure. Corrected counts:
> [`governed-query-path-tally-v2.json`](../experiments/analysis/governed-query-path-tally-v2.json).
> The text below is left as the record of what was measured and published.

Registered 2026-08-30 under operator directive (D-197). Epic
`omni-benchmark-7tq`. This is the entire design document; process that does
not defend the number is intentionally absent.

## Purpose

C4 measured Omni under a deployment shape its documentation never recommends:
join-free, measure-free topics, boilerplate `ai_context`, no tuning. C5
measures Omni deployed the way the product documentation prescribes, using
only public inputs. The question: how much of the knowledge value that C2
demonstrated (+12.0 points over C1 sealed, 23.8% vs 7.4% dev-A) does governed
Omni deliver when the semantic model actually carries that knowledge?

## Headline comparisons (dev-A, exploratory, both frozen scorers)

| Contrast | Question it answers |
| --- | --- |
| C5 vs C2 on the 122-question intersection | Same public knowledge: governed Omni vs direct SQL agent. This is the value-of-Omni number. |
| C5 vs frozen C4 on the 136-question frame | Effect of docs-idiomatic deployment vs mechanical baseline. |
| C5 vs E02 captured 117-subset | Incremental effect beyond joins alone. |
| C5 rewrite rate vs 131/131 | Mechanism readout: context delivery vs composition. |

The sealed 89-question frame stays closed. C5 postdates visible sealed
aggregates and is a dev-A condition; no held-out claim is made. Design
provenance is the mechanism measurements plus Omni's public documentation,
not any per-question outcome; no question content, gold, or hidden annotation
enters any C5 artifact, which keeps the contamination story checkable.

## Condition definition (phase 1)

Built by a new compiler entry point beside the baseline and E02 compilers.
Content provenance for every emitted object: public schema IR, public column
meanings, public HKB IR. Nothing else.

1. **Widened view surface.** Publish a view for every public table (47–63 per
   database), not the baseline's 6–11. Physical dimensions for every column
   with its public column meaning as description.
2. **Full join graphs.** Emit a join for every FK contract that passes the
   existing conservative cardinality rule (1,049 of 1,228 public FKs). The
   E02 endpoint filters relax automatically because both endpoints are now
   published. Joins remain `many_to_one`, declared on the FK-holding topic.
3. **Complete HKB port to `ai_context`** (never pruned by Omni's context
   assembly):
   - one exact field target → field-level `ai_context`;
   - table-scoped or cross-table definitions → topic-level `ai_context` on
     the owning topic, dependency chains inlined prerequisite-first;
   - database-global domain knowledge → model-level `ai_context`.
   Formulas are carried verbatim as text. The compiler enforces Omni's
   documented budget: warn at 150k characters of model context, fail above
   175k, per database.
4. **Field metadata through verified channels only.** HKB names that reference
   a field lead its field-level `ai_context` entry, and public value
   illustrations already arrive in the column description ("Example: ..."). No
   `synonyms` or `sample_values` YAML keys are emitted: those keys are not
   confirmed against the deployment API's exact-readback contract, and an
   unverified key risks failing the deployment rather than improving it.
5. **Generic query-pattern guidance at model level.** The structurally fragile
   shapes from the failure taxonomy (multi-hop join, windowed ranking,
   `DISTINCT` deduplication, grouped aggregation) are described once in
   model-level `ai_context` as guidance, instantiated from nothing but schema
   structure. No `sample_queries` key, for the same readback reason, and no
   question-derived content.
6. **No measures.** Phase 2 (measures with grain resolution, model-assisted
   authoring plus human review) is registered but built only if the phase 1
   readout warrants the spend.

## Execution (thin loop)

1. Compiler + tests (`omni-benchmark-7tq.1`).
2. Tier 1 deployment to isolated `livesqlbench-*` branches, one built-in
   validation + exact-readback pass per database (`7tq.2`).
3. **Operator gate:** lease + budget approval, then one 136-attempt dev-A
   generation under a new run ID (`7tq.3`). Append-only records; a wrong
   answer is never a rerun reason; path telemetry captured per attempt.
4. Both frozen scorers from the operator PG18 environment; aggregate-only
   committed comparison artifact (`7tq.4`).

## Implemented arm

The harness carries C5 as a third semantic candidate kind beside `baseline`
and `e02`, so every existing custody rule applies unchanged.

| Piece | Where |
| --- | --- |
| Compiler | `src/omni_benchmark/semantic_c5.py`, published through `publish_c5_bundle_artifacts` |
| Exact-Git candidate | `load_committed_c5_candidate` / `load_committed_c5_plan` in `e02_candidate.py` |
| Deployment | `scripts/prepare_c5_experiment.py` (dry by default), remote identity `livesqlbench-<database>-c5-tuned-<run revision>`, taken from the deployment run ID so a retry never lands on a populated branch |
| Generation | `--dry-run-c5-dev-a-experiment` / `--execute-live-c5-dev-a-experiment` in `baseline_batch_cli.py` |
| Unrepresentable columns | Widening injects a dimension for a column no identifier can name (`ESCAPE_VELOCITY_km/s`) and attests its direct physical binding, since Omni strips a bare column reference and resolves it itself; `_require_attested_physical_dimensions` fails such a bundle at compile time rather than at upload |
| Per-attempt readback | `_committed_semantic_plan(..., "c5")`, which verifies every deployed document including the model-level `ai_context` |

Two deliberate differences from the E02 arm. Readback for C5 excludes nothing:
the model file is part of the attested plan, because model-level `ai_context`
is a deployed artifact rather than an extension Omni added on its own. And a
C5 attempt compiles only its own database (about 5 seconds) rather than all
eighteen (about 56 seconds), which is byte-identical to the full compile and
tested as such.

One correctness fix travelled with the arm: the live deployed-semantics path
now validates the child Omni environment before a one-time approval receipt is
consumed. Previously only the derived-deployment (C4) path did, so an E02 or
C5 launch with a missing `OMNI_BASE_URL` could spend the receipt before any
evaluated answer.

## Kept and dropped

Kept, because they defend the number: public-only content provenance, both
frozen scorers reported without selection, single generation, append-only
evidence, isolated branches, frozen sealed artifacts untouched.

Dropped, per operator directive: freeze-manifest versioning beyond a commit
pin for the run, receipt machinery for dev-A generation beyond the one
operator approval, repeated readback evidence sets, per-decision document
sprawl. This document plus research-log entries is the paper trail.

## Operator decisions

- **G1 — confirmed 2026-08-30.** The definition above stands: all-tables view
  surface, phase 1 without measures.
- **G2 — approved 2026-08-30.** Budget approved for the one 136-attempt dev-A
  generation run.

Both gates were granted by Stephanie on 2026-08-30 with the instruction to run
the chain end to end autonomously. The no-rerun rule, append-only records, and
the closed sealed frame are unaffected by that approval.

## Outcome

Deployment `c5-dev-a-deployment-v8` verified all 16 target databases with exact
readback. Run `c5-dev-a-v4` completed 136 of 136 attempts on 2026-08-31, bound to
system commit `487c4dc4866622315d10066a3cc6552f9655435d`, with 110 answered and
26 errored and no record-write failures. All 26 non-answered attempts went
through the exact-readback recovery path and all 26 classified as
`evaluated_system_failure`, so none was set aside.

Both frozen scorers ran. On the identical 136-attempt frame C5 scores 18/136
(13.2%) official and 16/135 (11.9%) sensitivity, against the frozen C4
baseline's 9/136 (6.6%) and 9/135 (6.7%). On the 122-question five-condition
intersection C5 reaches 13/122 (10.7%) against C4's 5/122 (4.1%) and C2's 29/122
(23.8%). C5 is the first governed condition to clear the raw-schema floor C1.
Median total tokens fell from 583,188 to 396,884, tool calls from 7 to 3,
database queries from 2 to 1, and latency from 50,557 ms to 32,492 ms.

On the five-condition 122-question frame the same direction holds in aggregate:
C5 spent 1.42 hours of total attempt wall time against C4's 2.01 hours, median
31.9s against 50.6s, on median input tokens of 395,010 against 580,587. Dollar
cost cannot separate the two governed arms. Neither run has a measured
per-attempt figure, so both carry the same arm-level credit estimate of $0.684
per attempt; the comparison that survives is time and tokens. Per-arm sums,
medians, and quartiles for all five conditions:
[`../experiments/analysis/matched-122-cost-time-rollup-v1.json`](../experiments/analysis/matched-122-cost-time-rollup-v1.json).

The mechanism did not move: 134 of 134 parseable C5 queries carry `rewriteSql`
and none declares a join through the semantic model, matching every other
governed arm measured (661 of 661 across six arms). Publishing every table and
the full FK join graph produced no composed query, so the accuracy gain came
from the model serving as context rather than as a compiler.

Artifacts: freeze
[`../experiments/autoresearch/state/c5-dev-a-v4-freeze.json`](../experiments/autoresearch/state/c5-dev-a-v4-freeze.json),
accuracy
[`../experiments/analysis/c5-matched-122-comparison-v1.json`](../experiments/analysis/c5-matched-122-comparison-v1.json),
telemetry
[`../experiments/analysis/c5-telemetry-comparison-v1.json`](../experiments/analysis/c5-telemetry-comparison-v1.json),
query paths
[`../experiments/analysis/governed-query-path-tally-v1.json`](../experiments/analysis/governed-query-path-tally-v1.json).
Decisions D-202 through D-205 in [`research-log.md`](research-log.md); product
consequence in [PF-016](product-findings.md). Phase 2 is proposed under bead
`omni-benchmark-w5x` and needs its own authorization.

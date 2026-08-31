# C5: docs-idiomatic tuned governed Omni

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
| Deployment | `scripts/prepare_c5_experiment.py` (dry by default), remote identity `livesqlbench-<database>-c5-tuned-v1` |
| Generation | `--dry-run-c5-dev-a-experiment` / `--execute-live-c5-dev-a-experiment` in `baseline_batch_cli.py` |
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

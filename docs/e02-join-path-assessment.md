# E02 as a direct test of the C4 rewrite-path mechanism

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

Status: assessment. Companion to `docs/c4-query-path-disclosure.md` and
`docs/c4-mechanism-measurements.md`. It changes no protocol surface, no scorer,
and no frozen artifact, and it deploys nothing.

> **Superseded, 2026-08-31. This is a pre-run planning document and E02 has since
> run.** Read its forward-looking language as a record of what was decided in
> advance, not as open questions. What happened: E02's dev-A generation completed
> at 136 frozen attempts and is formally INCONCLUSIVE under the complete-136
> rule, with 117 answered, 14 unsupported-result-type captures, and 5 transport
> failures. Its captured subset moved +1.7 points official (11/117 against a
> matched C4 9/117) and +0.9 sensitivity. The central question this document
> poses, whether a declared join changes the path Omni's agent takes, was
> answered decisively in the negative, and C5 rather than E02 answered it. 134 of
> 134 parseable C5 attempts stayed on the rewrite path after a view was published
> for every table and a join for every qualifying foreign key. One arithmetic error
> below is left in place and corrected here: the text says "if the rewrite rate
> stays at 135 of 135", which is the dev-A C4 baseline denominator, not E02's.
> E02's own figure is 131 of 131 parseable.

Evidence boundary: the committed E02 compiler and deployment code at HEAD
`94cc0d9`, the committed public bundle specs, HKB IR, schema IR, and mapping IR,
the immutable v8 generation records, the frozen official score envelope, and the
hash-pinned recovery manifest. No gold SQL, result value, question text, hidden
annotation, dev-B record, or sealed outcome was read. Nothing under `runs/` was
opened. Every figure is an aggregate. No question identifier, SQL text, field
name, table name, or per-question label appears here.

---

## 1. Verdict

**E02 declares real join paths. It is the direct test of the mechanism, and it
is only a partial one.**

The candidate emits joins into the topic documents themselves, not into a side
channel. `compile_e02_relationship_bundle`
(`src/omni_benchmark/semantic_bundle.py:811-836`) loads each compiled topic,
replaces the baseline's `"joins": {}` with `{target_view: {}}` for every
FK-backed target, rewrites the topic's ai_context from "This topic intentionally
models no cross-table joins" to "This topic exposes only declared PK/unique-backed
many-to-one joins", and sets `validation.joins_generated` to `True` whenever any
relationship was emitted. It also writes a top-level `relationships` file of
`join_from_view` / `join_to_view` / `on_sql` entries in Omni's `${view.field}`
syntax.

Both surfaces reach Omni. `_deployment_file`
(`src/omni_benchmark/omni_semantic_deployment.py:287-305`) recognizes the
`relationships` name, parses it as a YAML sequence, validates every entry
against `_RELATIONSHIP_FIELDS`, and gives it a remote path. Topic documents
deploy by name with the joins map intact, and
`verify_semantic_deployment_readback` compares them field for field. Running
`experiments/analysis/e02_publication_validation.py --workspace .` builds 18
deployment plans over 272 files with 91 relationship contracts, candidate set
SHA-256 `db811d6ec553d3b82e42ba3bbd9bafe7ca528a695836a33d6f1aff0b60c5b074`.

So the answer to the first question is unambiguous. E02 is not a metadata-only
artifact that the bundle loader would discard. It converts the exact
`joins: {}` / `joins_generated: False` condition named in
`docs/c4-query-path-disclosure.md` §1.1 into declared join paths on the topics
the agent actually queries.

E02 is therefore no longer only a correlational bet on relationship counts. It
is the intervention that removes one of the two structural reasons the governed
arm could not compile a query. The other reason, the absence of measures,
E02 does not touch at all.

---

## 2. What the candidate actually emits

Measured by compiling both the baseline and the E02 candidate from the same
committed inputs and diffing the topic documents.

| Property | Baseline | E02 candidate |
| --- | ---: | ---: |
| Databases compiled | 18 | 18 |
| Topics with a non-empty `joins` map | 0 of 127 | 67 of 127 |
| Databases with `joins_generated: True` | 0 | 16 |
| Relationship contracts | 0 | 91 |
| Topics declaring a measure | 0 | 0 |
| Views declaring a measure | 0 | 0 |
| Databases whose `semantic_elements` changed | n/a | 0 |

The zero metric-disposition change is exact, not approximate: the candidate's
`semantic_elements` block is equal to the baseline's for all 18 databases. E02's
registered spec has two halves, a relationship half and a metric-reclassification
half ("Reclassify a deferred metric only when its public HKB supplies the
required aggregation"). As built, **only the relationship half does anything.**
No deferred metric was reclassified in any database. This matters for §4.

### 2.1 The FK funnel

`plan_relationship_contracts` over the 18 public schema IRs sees 1,228 declared
foreign keys. 1,049 pass the conservative contract (281 `exactly_one`, 768
`zero_or_one`, 0 multi-column) and 179 are deferred, every one of them for
`target_not_unique`.

Only 91 of those 1,049 survive into a bundle. Two filters do the cutting, both
in `compile_e02_relationship_bundle`. An edge is dropped unless both endpoint
tables are published views (`semantic_bundle.py:759-760`), and dropped again
unless both FK columns are published as physical dimensions bound one-to-one to
those columns (`_relationship_fields`, `semantic_bundle.py:839-859`). The
published surface is 6 to 11 views per database against 47 to 63 tables, so the
first filter alone removes the large majority.

The "16 databases" in the E02 inventory and the "16 databases" in the deployment
gate are two different sixteens. The inventory figure is how many of the 18
compiled databases carry at least one relationship. The deployment figure is the
schedule-derived set that `e02_experiment_cli` will deploy to, which is the 16
databases represented in the answerable dev-A frame. They coincide in size and
not in membership.

### 2.2 The slice that would actually be deployed

Restricting to the 16 databases the E02 CLI deploys to, which are the 16 the
v8 C4 baseline ran against:

| Quantity | Deployed slice |
| --- | ---: |
| Relationship contracts | 85 of 91 |
| Databases gaining at least one declared join | 14 of 16 |
| Topics gaining at least one declared join | 61 of 114 |
| Topics declaring a measure | 0 of 114 |

Two of the 16 deployed databases gain nothing: their published views hold no FK
pair that clears both filters.

Join out-degree across the 114 deployed topics: 53 declare no join, 39 declare
one, 20 declare two, 2 declare three. Every emitted join is `many_to_one`,
`always_left`, and `reversible: False`, and it is written only onto the topic
whose base view holds the foreign key. A topic on the referenced side gains no
path back. The joins map is one level deep, so a topic reaches its base view
plus its direct targets and no further.

---

## 3. Coverage against the 62 multi-relation attempts

The 62 are the parseable governed attempts that reference two or more distinct
non-CTE sources with an empty `join_via_map`
(`docs/c4-mechanism-measurements.md` §2.2). This analysis reproduces that set
exactly: 62 attempts, 2 correct, 41 wrong, 19 error.

Each attempt's non-CTE sources were resolved against the full compiled name
space of its database: topic name, view name, view file stem, and the physical
table of a published view. Of 173 distinct source references, 142 resolve to a
published view, 3 name a real public table that is not published as a view, and
28 name nothing in the public schema at all.

Each attempt was then classified against the E02 join graph for its database.

| Class | Attempts | Share of 62 |
| --- | ---: | ---: |
| Every source view covered by one topic's declared one-hop join set | **16** | 25.8% |
| All sources modeled and connected through declared relationships, but not within one topic's one-hop set | 18 | 29.0% |
| All sources modeled, no declared relationship links them | 7 | 11.3% |
| At least one source is not a published view | 21 | 33.9% |

Outcome split of the 16 with a declared path: 1 correct, 12 wrong, 3 error.
Three of the 31 class-A `UNKNOWN`-type failures fall in this bucket.

**Read this as the ceiling, not the estimate.** 16 of 62 is the fraction of
cross-table attempts for which a compiled path would have existed to take. It
does not say Omni's agent would have taken it, and nothing in the artifacts held
speaks to that. The residual uncertainty is the same one
`docs/c4-query-path-disclosure.md` §8 leaves open.

Three structural facts bound the number from below and above.

The 21 attempts whose sources include an unpublished table are out of reach for
any model-declaration change. There is no view, therefore no topic, therefore no
join. Widening the published surface is a different intervention with different
risk, and it is not E02.

The 18 connected-but-multi-hop attempts are the interesting margin. Their source
views are all modeled and all reachable from one another through declared E02
relationships, but no single topic's one-hop join set covers them. Omni topic
joins nest, so a compiler that emitted transitive paths rather than direct
targets could in principle reach some of these. E02 as built emits one level.
That is a bounded, general compiler change, and it would roughly double the
covered fraction if Omni honors nested paths.

The 7 no-declared-path attempts are cases where the conservative contract has
nothing to offer: no FK, an FK deferred for `target_not_unique`, or an FK column
that is not published as a dimension. Relaxing any of those relaxes the contract
that makes E02 defensible.

---

## 4. Sufficiency: necessary, not sufficient

E02 is necessary for the compiled path and not sufficient for it. The reason is
measures.

The deployed topics declare no measure, and the E02 candidate declares no
measure either. That is measured, not inferred: zero topic-level measures and
zero view-level measures across all 114 deployed topics under both compilers.
A query that aggregates cannot be composed from declared model objects when the
model declares no aggregate to compose.

The aggregation load on these queries is heavy. 85 of the 133 parseable governed
attempts contain an aggregate function. So do 46 of the 62 multi-relation
attempts. So do **11 of the 16** attempts for which E02 would supply a declared
join path.

That is the sufficiency answer in one line. For 11 of the 16 attempts where E02
finally makes cross-table access compilable, the agent still has a reason to
write SQL, because the aggregate it needs does not exist as a declared object.
E02 alone leaves 5 of 62 multi-relation attempts fully composable from declared
structure.

The evidence is not entirely against E02 acting alone. PF-004
(`docs/product-findings.md`) records that Omni, left to itself, inferred
many-to-one joins onto a topic whose `fields` list named only its base view, and
that an explicit `joins: {}` was required to suppress them. The shape E02 emits
is the shape the product produces natively, which is the strongest available
evidence that a base-view-only `fields` list does not neutralize a declared join.
It is product-behavior evidence from one canary, not a measurement of agent
path selection.

### 4.1 What a measures-declaring change would require

A measures intervention is larger than E02 and structurally different from it.

It needs a source of truth for which aggregation applies to which field. E02's
whole defensibility rests on foreign keys, which are declared, public, and
mechanical. There is no equivalent declared aggregation in the public schema. The
only candidate source is the public HKB, and that is precisely the half of E02's
registered spec that produced zero changes: the conservative contract found no
deferred metric whose public HKB supplied the required aggregation. Building the
measures change means either loosening that contract or reading aggregation
intent out of HKB definition text, which is a semantic judgment the compiler
must not make in code (ZFC) and which would need a model in the loop with its
own generality review.

It needs the grain contract that E02 declares but does not use. Once a topic
declares both a join and a measure, a `many_to_one` join to a fanned-out target
multiplies rows before aggregation. That is exactly the "repeated join-multiplication
regression" E02's own keep/revert rule names as an automatic revert. Measures on
top of joins is where that risk actually lands, and it needs the row-multiplication
audit the registration already specifies.

It needs a new deployment and a new readback contract. `_topic_document`
(`semantic_bundle.py:630-645`) emits no measures key at all, so this is a
compiler change plus a deployment-verification change, not a data change.

Sequenced against the MVP deadline, that is not a cheap addition to E02. It is a
second intervention.

---

## 5. Recommended intervention ordering

Given a small number of full 136-attempt evaluations before the MVP deadline.

### First: E02 as built, unchanged

It is compiled, hash-bound, deployment-gated, and tested. It is the only
available intervention that directly attacks the mechanism the disclosure
document established. It flips `joins_generated` on 14 of the 16 deployed
databases and gives 61 of 114 topics a declared path where the baseline gave
none.

The strongest argument for running it first is not its 16-of-62 coverage. It is
that the run answers a question no offline analysis can:
**does Omni's agent change path when a declared join exists?** Every downstream
decision depends on that answer, including whether a measures intervention is
worth building at all. The telemetry that answers it is already captured on
every attempt: `rewriteSql`, `join_via_map`, and `join_paths_from_topic_name`
come back on the semantic query, and the existing analyzer reads them. If the
rewrite rate stays at 135 of 135, the compiled-path hypothesis is dead and no
amount of measures work revives it. If it moves, the measures change becomes the
obvious next spend.

Accuracy expectation should be set low and stated in advance. At most 15
non-correct attempts sit in the declared-path bucket, 11 of them still need an
undeclared aggregate, and one currently-correct attempt sits in the same bucket
and can regress. The acceptance gate asks for at least two net additional correct
answers. E02 may well miss it. The path measurement is worth the slot regardless
of whether the accuracy gate passes, and the keep/revert rule should not be
relaxed to protect it.

### Second: conditional on the first result

If E02 measurably moves attempts off the rewrite path, spend the next slot on
**declared measures**, accepting that it is a compiler change with a grain risk
and a required row-multiplication audit. That is the intervention that closes
the remaining 11 of 16.

If E02 does not move the path at all, do not build measures. Spend the next slot
on E03 instead. E03 is bounded, textual, cheap, and it improves the vocabulary
surface that the disclosure document showed is the semantic layer's only
measured contribution in this deployment. A vocabulary improvement pays off
through the rewrite path, which is the path the agent demonstrably uses.

The nested-join variant of E02, which would address the 18 connected-but-multi-hop
attempts, sits below both. It is a small general compiler change, but it is worth
nothing until the path question is answered, and it competes for the same
evaluation slot.

### Not next: E05 typed fields

E05's precondition is measured and failed. The target was at least 16 of the 31
class-A failures selecting a compiled derived field; the ceiling is 6, and the
floor is 0 (`docs/c4-mechanism-measurements.md` §1.5). Widening it to all
compiled fields, derived and physical, reaches at most 7 of 31, because 24 of 31
select no compiled bundle field at all.

`docs/c4-reliability-intervention-family.md` already records E05 INCONCLUSIVE
under its own promotion rule. It should not consume an evaluation slot. The
narrower reporting fix inside it, recording the executed SQL instead of leaving
`generated_sql` null (`omni_attempt.py:166-173`), is a disclosure defect worth
fixing in the optimized arm and costs no evaluation slot at all.

### Also not next: widening the published view surface

The single largest coverage gap is the 21 of 62 attempts referencing tables that
are not published as views. That is a bigger lever than joins by count. It is
also a much larger change to the evaluated surface, it interacts with the
governance property that makes C4 a distinct condition, and it has no
conservative public contract behind it comparable to a foreign key. It should
not be attempted under deadline.

---

## 6. What this does not decide

Whether Omni's agent composes through a declared join when one exists. That is
the point of running E02 and it cannot be settled offline.

Whether Omni honors nested topic join paths, which is what the 18
connected-but-multi-hop attempts would need.

Whether a base-view-only topic `fields` list exposes the joined view's fields.
PF-004 shows the product's own default topic carries that shape with inferred
joins present, which is evidence and not proof.

Whether the sealed arm would behave the same way under E02. The sealed arm is
hash-bound to the untuned deployment and is unaffected by any of this.

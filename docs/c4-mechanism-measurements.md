# C4 mechanism measurements: E05 precondition and SQL path shape

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

Status: measurement. Bead `omni-benchmark-ei0.11.6`. This document runs the two
offline checks that `docs/c4-failure-attribution.md` §6.4 names as prerequisites
before any mechanism claim about the 34 governed-C4 terminal failures reaches
RESULTS.md. It changes no protocol surface, no scorer, and no frozen artifact.

Evidence boundary: the immutable v8 generation records, the frozen official
score envelope, the hash-pinned recovery manifest, the committed public semantic
bundles, and the committed public schema IR. No gold SQL, result value, question
text, hidden annotation, dev-B record, or sealed outcome was read. Every figure
below is an aggregate. No question identifier, SQL text, field name, or
per-question label appears here or in the analyzer's output.

Analyzer: `experiments/analysis/c4_mechanism_measurements.py`, tests in
`tests/test_c4_mechanism_measurements.py`.

```
uv run python experiments/analysis/c4_mechanism_measurements.py \
  --workspace . --c4-generation-root <public-c4-baseline-v8 output root>
```

Aggregate output SHA-256:
`56df0ab4d82e9d45ba3ef6296a473d9d6733b925835ec071ae6cd98f26d9053f`.

Custody bindings the analyzer verifies before emitting anything: official score
artifact SHA-256 `57d45346de0a98384207d350f163dfcf812e677cf3719b4a3008b5e0f3f222d8`
against its receipt, recovery manifest SHA-256
`5d6ff474f30d3de6d703ad5c6c59373fe8093515eabb83473bdb352c4f30fd9f`, and the
receipt's declared binding to that manifest. Each of the 136 attempts resolves
to exactly one generation record by the score envelope's `generation_sha256` and
`generation_record_sha256`, so the records are hash-bound to the frozen score
artifact independently of where the v8 output root is mounted.

---

## 0. Two corrections to the published taxonomy, found while measuring

**The class-A count is 31, not 32. Class C is 2, not 1.** The recovery manifest
at the pinned digest holds these reasons:

| Reason | Count | Disposition |
| --- | ---: | --- |
| `omni_unknown_result_type` | 31 | evaluated_system_failure |
| `omni_query_plan_rejected` | 2 | evaluated_system_failure |
| `omni_completed_job_contract_invalid` | 1 | evaluated_system_failure |
| `adapter_semantic_query_replay` | 11 | recovered_result |

`docs/c4-reliability-intervention-family.md` §2, the bead, and
`docs/c4-failure-attribution.md` all state 32 / 1 / 1. The terminal total of 34
is unchanged, and the substantive claim that one mechanism dominates the block
is unchanged. The specific number 32 is wrong wherever it labels class A.

**The "32 parseable governed queries" cross-check does not identify class A.**
`docs/c4-reliability-intervention-family.md` §2 says "exactly the 32 class-A
records carry a parseable governed query". Measured: 33 of the 34 terminal
failures carry a non-empty `userEditedSQL`, and 32 of those parse under sqlglot.
The parseable set spans class A (30 of 31 parse) and class C (2 of 2 parse). The
apparent 32-to-32 agreement is a coincidence of two different 32s.

---

## 1. Check 1: the E05 precondition

E05 declares explicit output types on compiled semantic fields. Its stated
precondition is that at least 16 of the class-A failures select a **derived**
(compiled, HKB-backed) field, because the type omission is not specific to
derived fields: `semantic_bundle.py:571-584` declares no type on physical
dimensions either.

### 1.1 What can and cannot be identified

The `UNKNOWN` decision is made over `semantic_query["fields"]`, the selected
field list, by `planned_query_data_types`
(`omni_result_adapter.py:156-171`, `434-481`). The recovery manifest records
only `plan_sha256`, not the plan body, and the captured traces are
metadata-only (`metadata_sha256`, no payload). **Which** field within an
attempt's selected set carried `UNKNOWN` is therefore not recoverable from any
artifact we hold.

What is recoverable is the full selected field set per attempt, and each
reference's provenance against the compiled bundles. That yields a bound: an
attempt can only be explained by a derived-field type gap if its selected set
contains a derived field at all.

### 1.2 Provenance of every selected field reference in class A

Each reference is classified against the compiled bundle for the view it names,
with the attempt's own CTE and alias names resolved from its `userEditedSQL`
first. 31 class-A attempts select 130 field references.

| Class of reference | Count | Share of 130 |
| --- | ---: | ---: |
| Compiled derived dimension (HKB-backed) | 8 | 6.2% |
| Compiled physical dimension (schema column in the bundle) | 15 | 11.5% |
| Query-local name (a CTE column or bare alias the attempt's own SQL defines) | 53 | 40.8% |
| Schema column of the view's table that the bundle does not declare | 23 | 17.7% |
| Name matching no bundle dimension and no schema column of that table | 20 | 15.4% |
| Omni built-in count | 8 | 6.2% |
| Reference to a view identifier no bundle publishes | 3 | 2.3% |

23 of 130 references (17.7%) are compiled bundle fields of any kind. 8 of 130
(6.2%) are compiled derived dimensions.

### 1.3 Class-A attempts by what their selected set could be typed from

| Composition of the selected set | Attempts | Share of 31 |
| --- | ---: | ---: |
| Contains at least one compiled derived dimension | 6 | 19.4% |
| Contains a compiled physical dimension and no derived one | 1 | 3.2% |
| Contains no compiled bundle field of any kind | 24 | 77.4% |
| Every field is a compiled derived dimension | 0 | 0.0% |

Every one of the 31 selects at least one field that is not a compiled bundle
field.

### 1.4 Control comparison

Derived-field selection across the whole frame, so the class-A rate can be read
against a base rate rather than in isolation:

| Outcome | Attempts | With at least one derived field | Rate |
| --- | ---: | ---: | ---: |
| Correct | 9 | 0 | 0.0% |
| Wrong answer | 93 | 6 | 6.5% |
| Terminal failure (all 34) | 34 | 7 | 20.6% |
| Class A only | 31 | 6 | 19.4% |

Derived-field selection is about three times as common in class A as among
wrong answers. The association points the same direction as the E05 hypothesis.
The absolute count does not reach the precondition under any reading.

### 1.5 Verdict on the E05 precondition

**Not met, and measured rather than unmeasurable.** The precondition asks for at
least 16 class-A failures on derived fields. The upper bound is 6 of 31, and
that bound is generous: it counts an attempt whenever a single derived field
appears anywhere in a selected set that also contains uncompiled references. The
lower bound is 0, because no class-A attempt selects derived fields exclusively
and no artifact identifies which field carried `UNKNOWN`. The true value lies in
[0, 6]. The precondition target of 16 is above the ceiling by a factor of 2.7.

Two consequences follow.

The bead's mechanism statement, "the mechanism is OUR compiler", is not
supported for the block it claims. At most 6 of 31 class-A attempts could be
caused by a missing type on a compiled derived field, and 24 of 31 select no
compiled field of any kind, so no declaration on any compiled field can reach
them.

The broader version of the harness reading, "declare a type on every emitted
field, derived and physical", also fails to cover the block. Adding derived and
physical together, 7 of 31 class-A attempts select any compiled field at all.
The remaining 24 select only query-local aliases, undeclared schema columns,
invented names, and the Omni count built-in. A compile-time declaration cannot
type a column that the compiler never emits.

---

## 2. Check 2: SQL path shape

### 2.1 Where the structural aggregate comes from

`omni_attempt.py:166-173` sets `generated_sql` to `None` for every C4 attempt.
Measured: **0 of 136** attempts carry a non-empty `generated_sql`. The entire C4
structural aggregate derives from the semantic query's `userEditedSQL`, as D-172
states.

| Outcome | Attempts | Carry a semantic query | Carry non-empty `userEditedSQL` | `userEditedSQL` parses |
| --- | ---: | ---: | ---: | ---: |
| Correct | 9 | 9 | 9 | 9 |
| Wrong answer | 93 | 93 | 93 | 92 |
| Refused or system-contract error | 34 | 33 | 33 | 32 |
| **Total** | **136** | **135** | **135** | **133** |

Class A alone: 31 of 31 carry `userEditedSQL`, 30 of 31 parse.

This corrects a figure in `docs/c4-failure-attribution.md` §4, which reads "133
of 136 governed attempts carried a non-empty `userEditedSQL`, including 32 of
the 34 errors". 135 of 136 carry one; 133 of them parse. The single attempt
without a semantic query is the class-B completed-job contract failure.

### 2.2 The multi-relation puzzle, resolved

The deployed topics emit `"joins": {}` and no measures, so a query compiled from
the declared model cannot traverse a join path. Two readings were open: the
agent used a raw-SQL escape path, or the planner resolved undeclared cross-table
access. The generated semantic queries settle it.

| Declared-structure flag | Attempts with a semantic query (135) |
| --- | ---: |
| `rewriteSql` true | 135 |
| `aiGenerated` true | 135 |
| `join_via_map` non-empty | **0** |
| `join_paths_from_topic_name` set | 94 |
| `table` names a CTE the attempt's own SQL defines | 17 |

**Every governed C4 query went through Omni's raw-SQL rewrite path.** All 135
carry `rewriteSql: true` together with hand-authored SQL text. Not one query
declares a join path in `join_via_map`. Every multi-relation query is
multi-relation because the agent wrote CTEs and explicit `JOIN` clauses over
`${topic}` sources in SQL text: 62 of the 133 parseable queries reference two or
more distinct non-CTE sources with an empty `join_via_map` (2 correct, 41 wrong,
19 error).

Reading 1 in `docs/c4-failure-attribution.md` §4 is the correct one. The planner
did not resolve undeclared cross-table access. C4's governed queries are
substantially the agent writing SQL with a semantic model available as context
and as a field-reference vocabulary.

### 2.3 What this means for the class-A mechanism

The fields the planner is asked to type are the output columns of hand-written
SQL, not a projection over declared model fields. That is why 53 of 130 class-A
selected references are names the attempt's own SQL invents, and why a further
46 are schema columns or names the bundle does not declare.

A compile-time output type on a compiled field could plausibly be **part** of
the class-A mechanism only for the 6 attempts whose selected set contains a
derived field, and only if the `UNKNOWN` landed on that field rather than on one
of the uncompiled references beside it. For the other 25 it cannot be the
mechanism, because there is no compiled field in the query for a declaration to
attach to.

The evidence supports a different mechanism statement for class A: the planner
reported `UNKNOWN` for output columns of agent-authored SQL that the semantic
model does not define, and the harness fails closed on `UNKNOWN`. That statement
is consistent with all 31, with PF-014 (the execution endpoint returned values
for a field the plan typed `UNKNOWN`), and with PF-006 (the product's own
generated `count` measure returned untyped). It attributes nothing to the
missing type declaration on compiled fields, because the failing queries mostly
do not select compiled fields.

This does not settle attribution between harness and product. It relocates the
disputed surface: from "our compiler under-declared its fields" to "the product
plans raw SQL it cannot type, and neither side specifies what a result contract
over rewritten SQL guarantees". §6.3 of the attribution document, that the
interface is under-specified, survives; §6.1's specific first bullet, that the
compiler held the type and dropped it, is true about the code and largely
irrelevant to these 31 attempts.

---

## 3. The relation_count confounder, quantified

`sql_features` counts `{table.sql(dialect="postgres") for table in
tree.find_all(exp.Table)}`, which includes CTE references, aliased self-joins,
and subquery sources. The corrected count removes names bound by a `WITH`
clause and collapses aliases to the base relation name, so it counts distinct
non-CTE data sources.

| Group | Parsed | Published mean | Corrected mean | Published multi-relation | Corrected multi-relation | With a CTE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Correct | 9 | 1.667 | 1.333 | 2/9 (22.2%) | 2/9 (22.2%) | 2/9 |
| Wrong answer | 92 | 2.620 | 1.826 | 50/92 (54.3%) | 41/92 (44.6%) | 40/92 |
| Refused or error | 32 | 2.875 | 2.000 | 20/32 (62.5%) | 19/32 (59.4%) | 16/32 |
| Class A only | 30 | 2.900 | 2.033 | 19/30 (63.3%) | 18/30 (60.0%) | 15/30 |

The published columns reproduce RESULTS.md §5 and `docs/failure-taxonomy.md`
exactly (1.667 / 2.620 / 2.875 and 2/9, 50/92, 20/32), which is the check that
this analyzer reads the same records the published aggregate read.

### 3.1 How much the separation changes

| Contrast | Published gap | Corrected gap | Reduction |
| --- | ---: | ---: | ---: |
| Wrong minus correct | 0.953 | 0.493 | 48.3% |
| Error minus correct | 1.208 | 0.667 | 44.8% |
| Class A minus correct | 1.233 | 0.700 | 43.2% |

**The direction survives and the magnitude roughly halves.** Wrong and failing
queries still use more distinct data sources than correct ones. Close to half of
the published separation was CTE and alias counting, and CTE use is itself
correlated with outcome (2 of 9 correct, 40 of 92 wrong, 16 of 32 error), so the
published metric partly measured query elaboration rather than cross-table
access.

Multi-relation prevalence moves less than the means. The correct group is
unchanged at 2 of 9. Wrong answers drop 9.7 points, from 54.3% to 44.6%. Errors
drop 3.1 points, from 62.5% to 59.4%.

### 3.2 What the published claims should now say

The join-presence figures in `docs/failure-taxonomy.md` (41/92 wrong, 18/32
error, 2/9 correct) carry the same confounder in principle: a join to a CTE the
query itself defines counts as a join. In practice they survive it. Of the 41
wrong-answer queries with a join, 33 also contain a CTE, but 39 join two or more
distinct non-CTE sources. All 18 error queries with a join do. The join figures
need no restatement.

RESULTS.md §5 and `docs/failure-taxonomy.md` state the relation figures as
descriptive associations, which they remain. The qualification they need is
narrower than a retraction: the published relation counts are an upper bound on
cross-table access, the corrected separation is roughly half the published one,
and the ordering across correct, wrong, and error is unchanged under both
measures. `docs/c4-failure-attribution.md` §7.3 uses the relation gap to argue
that converted class-A attempts would score below the ambient rate. That
argument still holds under the corrected numbers, with a smaller gap.

---

## 4. Verdicts

1. **E05's precondition is not met.** At most 6 of the 31 class-A failures can
   involve a compiled derived field, against a target of 16. 24 of 31 select no
   compiled bundle field at all. Measured, not estimated, and not blocked by
   missing artifacts.

2. **The class-A mechanism is not a missing type on a compiled derived field.**
   107 of 130 class-A selected field references are not compiled bundle fields:
   query-local aliases, undeclared schema columns, unmatched names, the Omni
   count built-in, and references to unpublished views. What the planner failed
   to type is predominantly the output of agent-authored SQL.

3. **All governed C4 development queries used the raw-SQL rewrite path.** 135 of
   135 semantic queries set `rewriteSql: true` with hand-authored SQL; 0 declare
   a join path. Multi-relation access is written by the agent, not resolved by
   the planner. The sealed arm was later measured the same way and matches at 261
   of 261 parseable across three repetitions; across all six governed arms the
   figure is 661 of 661.

4. **The relation-count separation is real and about half the published size.**
   Corrected means are 1.333 correct, 1.826 wrong, 2.000 error. Ordering
   unchanged; the correct-to-wrong gap falls from 0.953 to 0.493.

5. **Two published counts are wrong and should be corrected wherever they
   appear.** Class A is 31, class C is 2. `userEditedSQL` presence is 135 of
   136, of which 133 parse.

### What this does not decide

Which specific field carried `UNKNOWN` in any attempt. That is unrecoverable
from the artifacts we hold, and no offline analysis can produce it. The bounds
in §1.5 are the strongest statement the evidence supports.

Whether Omni accepts an explicit type declaration on a `sql`-derived dimension.
That is §6.4(3) of the attribution document, a Tier 1 public-only probe, and it
is still unrun. It is now a lower-value probe: even if Omni accepts and honors a
declared type, the declaration reaches at most 7 of 31 class-A attempts.

Whether a different intervention would convert class A. Nothing here proposes
one. The measurement narrows what an intervention would have to address: the
result contract over rewritten SQL, not the field documents the compiler emits.

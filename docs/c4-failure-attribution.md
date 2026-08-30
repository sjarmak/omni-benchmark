# C4 failure attribution: harness versus product

Status: analysis, not a decision. Bead `omni-benchmark-ei0.11.6`. This document
decides nothing about the protocol, the scorers, or the frozen system. It asks
one question: when RESULTS.md says governed C4 scored 9/136, how much of that
number is a statement about Omni's semantic layer and how much is a statement
about the compiler and capture path this repository wrote.

Evidence boundary: public aggregates, committed source, product findings, and
the decision ledger. No question identity, question text, SQL text, result row,
gold value, hidden annotation, dev-B record, or sealed outcome was read.

## Correction, 2026-08-30

`docs/c4-mechanism-measurements.md` measured the 34 terminal governed-C4
failures directly against the frozen recovery manifest at its pinned digest.
This document previously stated the class split as 32 class A, 1 class B, 1
class C. That is wrong. The measured split is 31 class A, 1 class B, 2 class C.
The terminal total of 34 is unchanged. Every occurrence of the old split below
is corrected, along with a `userEditedSQL` figure in §4 that conflated presence
with parseability. See `docs/c4-mechanism-measurements.md` for the measurement,
the analyzer, and the custody bindings.

---

## 1. The number under dispute

The frozen C4 dev-A baseline, official scorer, on the fixed 136 answerable
questions:

| Outcome | Count | Share of 136 |
| --- | ---: | ---: |
| Correct | 9 | 6.6% |
| Wrong | 93 | 68.4% |
| Refused or system-contract error | 34 | 25.0% |

The 34 are the contested block. They are not wrong answers. They are attempts
where the governed system produced work that the frozen execution contract could
not score, so no correctness comparison ever ran.

Bead `omni-benchmark-ei0.11.6` and `docs/c4-reliability-intervention-family.md`
attribute 31 of the 34 to a single mechanism: the query plan reported
`data_type: UNKNOWN` for a selected field, and the harness fails closed on
`UNKNOWN` rather than inferring a type from returned values. The remaining
three break down as one completed job with no parseable generated query and two
persistent plan rejections.

If that mechanism is caused by this repository's compiler, then a material part
of C4's reported result is a measurement artifact and reporting 6.6% without
attribution is indefensible. If it is caused by the product, the number stands
and the failure is itself a finding. Section 5 argues both readings. Sections 2
through 4 establish what is actually known first, because most of the
disagreement dissolves once the verified facts are separated from the inferred
ones.

---

## 2. What the source verifies

### 2.1 The compiler declares no output type on any field

`src/omni_benchmark/semantic_bundle.py:587-606`, `_derived_dimension`, emits
exactly four keys:

```python
return {
    "label": label,
    "description": _text(hkb.get("description"), "HKB description"),
    "sql": sql,
    "ai_context": f"Use this modeled field for {label}; ...",
}
```

There is no type key. The bead's mechanism claim is correct on this point.

The claim is also narrower than the truth. `_physical_dimension`
(`semantic_bundle.py:571-584`) emits `description`, optional `label`, optional
`sql`, and optional `ai_context`. It declares no type either. Grepping the whole
module for a type, format, or field-type key returns nothing. **No field of any
kind in any compiled bundle declares an output type.** The untyped surface is
100% of emitted fields, not the derived subset.

This matters for attribution in two directions. It strengthens the harness
reading, because the omission is total rather than incidental. It also weakens
the specific E05 mechanism, because an `UNKNOWN` on a selected field is equally
consistent with a physical field, and E05's precondition (at least 16 of the 31
selected a compiled derived field) has not been run.

### 2.2 The compiler computes the type and then discards it

`semantic_bundle.py:1142-1146`, immediately after the `_derived_dimension` call
that omits the type:

```python
field_kinds[name] = {
    "boolean_derived_dimension": "other",
    "categorical_derived_dimension": "text",
    "numeric_derived_dimension": "numeric",
}.get(str(mapping.get("representation")), "unknown")
```

The same function body derives a value kind for every derived field, uses it for
internal numeric coercion, and does not put it in the emitted document. The
physical path does the same at line 1111 via `physical_value_kind`
(`semantic_numeric.py:56-63`), which resolves `numeric`, `numeric_text`, or a
schema-declared kind, including recognising a root numeric cast in the emitted
SQL.

This is the single strongest fact for the harness reading. The information was
not unavailable, not expensive, and not uncertain. It was computed in the same
loop and dropped at serialization.

### 2.3 The harness fails closed on `UNKNOWN`, correctly

`omni_result_adapter.py:475-478` raises `OmniUnsupportedResultTypeError` when a
selected field's plan type is outside
`{BOOLEAN, DATE, JSON, NUMBER, STRING, TIMESTAMP, YESNO}`.
`c4_result_recovery.py:298-301` classifies `"UNKNOWN" in data_types` as
`omni_unknown_result_type`, an evaluated-system failure.

D-132 rejected value-based type inference deliberately, because inferring a type
from returned values silently changes comparison and aggregation semantics under
a result-set scorer. That decision is right and should not be revisited. It also
means no further adapter change can recover a class-A attempt. The harness is
already at the correct boundary; the disagreement is entirely about who should
have supplied the type.

### 2.4 The `UNKNOWN` determination comes from a replay plan, not the original attempt

`recover_c4_source` calls `client.plan_query(semantic_query)` fresh
(`c4_result_recovery.py:278`) and reads the type off that new plan. The final
class-A label is therefore a recovery-time property, not a capture-time one.

Concordance is good but not identity. D-155 records 34 capture-time
`Unsupported semantic result type` labels among the 45 original capture
failures, and the final classification produced 31 class A. D-155 also states
that the per-attempt mapping from capture label to final class is not derivable
from the published aggregates. D-150 and D-151 record runtime semantic drift (a
stale view) stopping 2 of 16 C4 targets during the same window, which
establishes that model state was not perfectly static across that period. The
possibility that some replay-time `UNKNOWN` values differ from generation-time
values is small but is not excluded by anything in the record.

---

## 3. What the records verify

- **PF-014 is the only field-level observation of the mechanism.** One canary,
  ETF, selected `yield_to_expense_ratio`; the plan reported `data_type: UNKNOWN`
  while the JSON endpoint returned values for that same field. Everything else
  about class A is an aggregate count. One observed instance plus a verified code
  path is a well-motivated hypothesis. It is not a measured cause.
- **Omni validated every bundle without raising the missing type.** The v13
  public-only pass validated and exactly read back all 16 answerable database
  bundles with zero terminal failures. PF-012 records that Omni canonicalizes
  the model on readback and returns no issue for these documents. The product
  accepted models it could not later type.
- **The product's type contract is inconsistent across its own surfaces
  independently of anything we authored.** PF-006: with `resultType: json` and
  `formatResults: false`, a planner-generated `count` measure returned as the
  strings `"680"` and `"17"` while boolean grouping values stayed typed. That is
  a numeric field the product itself created, not a field our compiler emitted.
- **The landed fixes are all harness-side and none of them are accuracy work.**
  D-121, D-132, D-155, D-168, D-169, and D-170 converted 11 of the original 45
  capture failures into scored results and made the remaining 34 classifiable.
  Every one of them is capture-path bookkeeping. Reporting any of them as an
  intervention on the evaluated system would overstate C4.

---

## 4. A structural fact that reframes the whole attribution

The C4 structural aggregate quoted in RESULTS.md §5 and in the failure taxonomy
(mean relations 1.667 correct, 2.620 wrong, 2.875 error; multi-relation in 2/9,
50/92, 20/32) is computed from one source. `omni_attempt.py:166-173` sets
`"generated_sql": None` for every C4 attempt, so
`experiments/analysis/wrong_answer_structure.py:160-175` falls through to
`generated_query["userEditedSQL"]`. D-172 states this explicitly: "Parse only
the semantic query's `userEditedSQL`".

So 135 of 136 governed attempts carried a non-empty `userEditedSQL` on the
semantic query, including 33 of the 34 errors. Of those 135, 133 parse under
sqlglot, including 32 of the 34 errors (30 of 31 class A, 2 of 2 class C; the
single class-B attempt carries no semantic query at all, so it contributes
neither presence nor a parse). The earlier "133 of 136 ... including 32 of the
34 errors" conflated presence with parseability; see
`docs/c4-mechanism-measurements.md` §2.1.

Set that against what the compiler deployed. `_topic_document`
(`semantic_bundle.py:630-645`) emits `"joins": {}` and the ai_context string
"This topic intentionally models no cross-table joins." The bundle emits
`dimensions` only; grepping for measures returns nothing. Every deployed topic
is a single join-free base view with no measures.

A query compiled from that model cannot reference two distinct tables through a
declared join path, because no join path exists. Yet 20 of 32 error queries and
50 of 92 wrong queries are multi-relation, and joins appear in 18/32 and 41/92.
Two readings, both consequential:

1. The Omni agent used the raw-SQL path and wrote joins the model does not
   declare. Under this reading, C4's governed queries are substantially the
   agent writing SQL with a semantic model available as context, and a
   compile-time field type on a modeled field is not obviously the thing that
   would have typed the output columns of hand-written SQL.
2. The planner resolved cross-table access the model does not declare. Under
   this reading the behavior is product-side and is a separate finding from the
   type gap.

One confounder must be stated. `sql_features` counts
`{table.sql(dialect="postgres") for table in tree.find_all(exp.Table)}`, which
includes CTE references, aliased self-joins, and subquery sources. So
`multi_relation` is an upper bound on genuine cross-table access, and the
relation-count evidence in RESULTS.md §5 and the failure taxonomy carries that
same upper-bound caveat.

**Implication for this analysis.** The bead's mechanism claim, "the compiler
emitted derived fields without a type, so the product could not infer the type,"
presumes the failing selected fields are compiled model fields. The structural
record is consistent with the failing queries carrying edited SQL, in which case
a compile-time type declaration on modeled fields addresses a different surface.
Nothing here refutes the E05 hypothesis. It does mean the hypothesis is less
established than either the bead or the intervention-family document currently
implies, and RESULTS.md must not state it as the cause of the 34.

---

## 5. Class-by-class attribution

| Class | n | Mechanism | Side, as best supported | Contestable? |
| --- | ---: | --- | --- | --- |
| A | 31 | Plan reports `UNKNOWN` for a selected field; harness fails closed | **Genuinely disputed.** See §6. | Yes, centrally |
| B | 1 | Job completed, no parseable generated query | Product. Omni reported a completed job whose contract carried no query. Nothing the harness declares changes that. | Weakly. The harness could in principle have accepted a completed job with no query as an empty answer, but that would score an absence as a result. |
| C | 2 | Persistent plan rejection | Product, after retry exclusion. `c4_result_recovery.py:279-288` reclassifies only after excluding 429, HTTP 5xx, timeout, and start failures, so transport noise is already removed. | Weakly. A rejection could reflect a malformed query the agent wrote. |
| D | 11 | Preview control rows, timestamp-free failure actions, plan summary dependency supersets, strict preview binding | **Harness, and already corrected.** These are not in the 34. They were recovered by replaying an already-generated query and are scored as answers. | No. This is settled and the record is explicit. |
| Scorer-conformance exclusions | 18 | Official Large-v1 loader skips tables whose archive filenames differ in capitalization | **Benchmark infrastructure**, neither harness nor product. Already excluded from the 136. | No |

Two things follow that the current reporting gets right and should keep.
Class D was corrected and its 11 attempts were returned to the scored frame, so
the 34 is a post-correction number, not a raw capture-failure count. The 18
loader exclusions are already outside the denominator.

One thing follows that the current reporting does not yet state. Classes B and C
are three attempts. Whatever is decided about class A, 91% of the disputed block
turns on a single question.

---

## 6. The interpretive question, argued both ways

**Question.** The compiler emitted a field without a declared output type and the
product could not infer one. Is that a harness defect or a product defect?

### 6.1 The harness-defect reading

- The compiler held the type and dropped it. `field_kinds` at
  `semantic_bundle.py:1142` computes `other`, `text`, or `numeric` from the
  recorded representation class for every derived field, in the same loop that
  emits the field document without it. `physical_value_kind` does the same for
  physical fields. This is not a case of the harness lacking information; it is a
  case of the harness not serializing information it already had.
- Omni exposes a supported result-type set. The adapter's own
  `SUPPORTED_OMNI_RESULT_TYPES` is `{BOOLEAN, DATE, JSON, NUMBER, STRING,
  TIMESTAMP, YESNO}`. A product that carries a closed type vocabulary in its plan
  API is a product that expects types to be expressible.
- Under-declaring a model and then reporting the product's inability to type it
  measures the modeling, not the semantic layer. A benchmark that publishes an
  under-specified model has partly measured its own authoring.
- The fix is on our side and is cheap. E05's `exact_reusable_change` derives the
  declaration from the representation class and public declared column types
  only, with no database name, question, or label. It is general, testable, and
  verifiable offline before any live attempt.

### 6.2 The product-defect reading

- The product accepted the model at publish and validation time and raised
  nothing. If a declared type is required for a governable result contract,
  validation is where a missing type should fail. All 16 answerable bundles
  passed product validation and exact readback with zero terminal failures, and
  PF-012 shows the product rewrote the model on import without flagging the
  omission. The failure then surfaced at answer time, on a live query, to an
  end user.
- Two surfaces of the same product disagree. PF-014 records the plan reporting
  `data_type: UNKNOWN` for `yield_to_expense_ratio` while the JSON execution
  endpoint returned values for that same field. The execution path resolved
  something the planning path could not. That inconsistency is internal to the
  product and no declaration by us created it. PF-014's own proposed product
  change says it directly: "Do not emit `UNKNOWN` for a field that the JSON
  execution endpoint can return."
- `UNKNOWN` is not an actionable error. It names a missing value, not a cause or
  a remedy. A typed error identifying the field and stating that its expression
  type could not be resolved would have been fixable by a model author in
  minutes. Instead the model author gets a successful publish, a clean
  validation, and an unanswerable question later.
- The product's own generated fields have the same problem. PF-006 records a
  planner-created `count` measure returning as a JSON string. That field was not
  authored by us. Whatever is true about our derived dimensions, the product's
  type fidelity is independently inconsistent.
- The warehouse knows the answer. The `sql` is Postgres and Omni executes it
  against Postgres, whose result-set metadata carries a type for every output
  column. Resolving the type of a derived expression against the engine that
  will run it is a describe call, not an open research problem. (This is an
  argument about a general capability of SQL engines. It is not a claim about
  Omni's internal implementation, which we have not inspected.)

### 6.3 The reading this analysis actually endorses

Both readings are correct about different objects, and the honest position is
that the interface between them is under-specified.

The type contract between a programmatic model author and a semantic layer is
not written down anywhere either side can point to. Our compiler declared no
type because nothing required one and validation confirmed nothing was missing.
The product required one only at query planning time and only for a subset of
fields, and reported its absence as a value rather than as a diagnosable error.
Neither side violated a stated contract, because there is no stated contract.

That is a real and reportable finding, and it is more useful to Omni's product
team than either accusation. It is also the reading that survives the gaps in
§2.4 and §4, which the single-cause readings do not.

### 6.4 What would settle it

None of these require live attempts, protected data, or a product change.

1. **Run the E05 precondition.** Count, on the immutable v8 generation records
   using field-kind metadata only, how many of the 31 selected a compiled derived
   field versus a physical field. If the derived share is small, the bead's
   mechanism is wrong and the harness reading loses most of its force.
2. **Count `userEditedSQL` divergence.** For the same 31, compare the semantic
   query's declared `fields` against the tables and output expressions in
   `userEditedSQL`, shape only. If the failing queries carry hand-written SQL,
   compile-time field typing is not the mechanism and §4 becomes the headline.
3. **Test whether Omni accepts a declared type at all.** Publish one field with
   an explicit type to an isolated `livesqlbench-*` branch and read it back.
   This is Tier 1: public schema, public HKB, no questions, no correctness. It
   is the only assumption in the harness reading that has never been checked. If
   Omni does not accept a type declaration on a `sql`-derived dimension, or
   accepts it and still plans `UNKNOWN`, the harness reading collapses entirely.

Until at least (1) and (3) are done, RESULTS.md should describe the mechanism as
a hypothesis with a named code path and a named untested assumption, and should
not attribute the 34 to either side.

---

## 7. Sensitivity numbers

All figures below are public aggregates from RESULTS.md §5 and D-155. Every one
is **descriptive**. None is a corrected estimate of what C4 would have scored.

### 7.1 The 136-question full answerable frame

| Denominator | Definition | C4 correct | Accuracy |
| --- | --- | ---: | ---: |
| 136 | All answerable dev-A questions. Official scorer. | 9 | **6.6%** |
| 102 | Attempts that produced a scoreable result (9 correct + 93 wrong). Excludes the 34 contract failures. | 9 | 8.8% |
| 135 | Sensitivity scorer, all answerable. | 9 | 6.7% |
| 102 | Sensitivity scorer, scoreable results only (135 minus 33 errors). | 9 | 8.8% |

The scoreable-result denominator is 102 under both frozen scorers and the
excluded figure is 8.8% under both. The exclusion analysis is scorer-invariant.

**6.6% is the headline. 8.8% is a conditional rate on a subset selected by an
outcome.** It answers "given that an attempt produced something scoreable, how
often was it right", which is not the study's question.

### 7.2 The 122-question four-condition intersection

Questions scoreable in all four conditions. This is the only frame where C4 and
the comparators share a denominator.

| Condition | Correct | Wrong | Refused/error | Accuracy on 122 | Non-answer rate | Accuracy excluding own non-answers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 raw schema | 9 | 80 | 33 | **7.4%** | 27.0% | 9/89 = 10.1% |
| C2 searchable raw HKB | 29 | 91 | 2 | **23.8%** | 1.6% | 29/120 = 24.2% |
| C3 searchable exported model | 16 | 74 | 32 | **13.1%** | 26.2% | 16/90 = 17.8% |
| C4 governed Omni | 5 | 83 | 34 | **4.1%** | 27.9% | 5/88 = 5.7% |

This table is the most important object in this document, for three reasons.

**C4's non-answer rate is not anomalous.** On the identical 122 questions, C4
fails to produce a scoreable answer 27.9% of the time, C1 27.0%, C3 26.2%. The
reader who demands that C4's 34 be excluded has to be shown that C1 and C3 carry
almost exactly the same burden. Excluding non-answers for C4 alone is the wrong
comparison, and it is the comparison a hostile reader will ask for.

**Excluding non-answers symmetrically does not change the ordering.** C4 goes
from last at 4.1% to last at 5.7%, against C2 at 24.2%. The attribution question
changes the size of C4's gap and does not touch its direction.

**The mechanisms behind the non-answer buckets are different and the comparison
is limited by that.** C4's are result-contract failures. C1's and C3's include
model-budget exhaustion and refusals, and RESULTS.md §6 records that the frozen
generation contract does not distinguish content refusal from insufficient
context, so the comparator bucket cannot be decomposed. Equal rates are evidence
against "the governed path uniquely fails to answer". They are not evidence that
the two paths are equally reliable.

One artifact of the intersection that a careful reader will find. Going from 136
to 122 removes 4 of C4's 9 correct answers, 10 of its 93 wrong answers, and none
of its 34 errors. That is why 6.6% on 136 becomes 4.1% on 122. The narrowing is
driven by the direct arm's coverage, not by C4.

### 7.3 Bounds on how much the 34 could matter

| Assumption | C4 on 136 | C4 on 122 |
| --- | ---: | ---: |
| Observed | 9/136 = 6.6% | 5/122 = 4.1% |
| All 34 convert and score at the frame's ambient rate | 12.0/136 = 8.8% | 6.9/122 = 5.7% |
| All 34 convert and every one is correct | 43/136 = 31.6% | 39/122 = 32.0% |

The ambient-rate row is the informative one. It closes 2.2 points on the 136
frame and 1.6 points of C4's 19.7-point gap to C2 on the 122 frame.

The all-correct row is a logical ceiling and nothing else. It assumes a 100%
correctness rate on the subset with the highest structural complexity in the
whole run, against an observed ambient rate of 8.8%. It is included only so that
a reader who computes it themselves finds it already stated and already
qualified.

There is a reason to think even the ambient row is optimistic. Error queries
average 2.875 relations against 2.620 for wrong answers and 1.667 for correct
ones, and 20 of 32 are multi-relation against 2 of 9 correct. If relation count
tracks difficulty, converted attempts would score below ambient, not at it.
`docs/c4-reliability-intervention-family.md` §5.1 says this and it should not be
dropped when the numbers are moved into RESULTS.md.

### 7.4 What none of these numbers are

- Not a corrected C4 accuracy. No corrected estimate exists, because no
  intervention has converted a single class-A attempt.
- Not held-out evidence. All of it is adaptively reused dev-A.
- Not a paired contrast, except the C1/C4 pairing already in RESULTS.md §5
  (3 correct in both, 2 C4 only, 6 C1 only, 111 in neither, difference -3.3
  points).
- Not a claim that the 34 would have been correct, wrong, or anything else.

---

## 8. Recommended report language for RESULTS.md

This section proposes text. It does not modify RESULTS.md, which is under
uncommitted change.

### 8.1 Executive summary, finding 2

Keep 9/136 (6.6%) as the stated result. Add the matched non-answer comparison in
the same breath, because it is the fact that prevents the 34 from being read as
unique governed-path fragility.

> Governed C4 separately scored 9/136 (6.6%) on its full answerable frame, with
> 34 attempts (25.0%) ending in a refused or system-contract outcome rather than
> a scoreable result. On the 122 questions scoreable in all four conditions, C4
> is 5/122 (4.1%) with a 27.9% non-answer rate, against 7.4% and 27.0% for C1,
> 23.8% and 1.6% for C2, and 13.1% and 26.2% for C3. C4's non-answer rate is
> comparable to C1's and C3's; its accuracy is the lowest of the four under every
> denominator we can construct. These are exploratory development results; the
> sealed comparison has not run.

### 8.2 Executive summary, finding 5

Replace the current mechanism sentence with one that names the code path, the
product surface, and the untested assumption.

> The governed semantic path exposed a distinct reliability surface. Thirty-four
> of 136 scoreable C4 attempts ended in a semantic-layer or system-contract
> failure rather than a scored result mismatch, of which 31 are a query plan
> reporting `UNKNOWN` for a selected field's type. Attribution between the
> evaluated system and this harness is unresolved. The compiled semantic bundles
> declare no output type on any field, although the compiler computes a value
> kind for each one, so the product had to infer the type of an expression it
> was never told about. The product also accepted and validated every bundle
> without reporting a missing type, and in the one field-level observation on
> record the JSON execution endpoint returned values for a field the plan typed
> as `UNKNOWN`. We have not yet tested whether declaring the type would change
> the outcome. Eleven additional capture gaps were separately traced to this
> harness, corrected, and returned to the scored frame by replaying only an
> already-generated semantic query; question-level model reasoning was never
> rerun.

### 8.3 New paragraph in §5, after the C4 paragraph

> Twenty-five percent of the C4 frame did not reach a scoreable result. On the
> 102 attempts that did, C4 is 9/102 (8.8%) under both frozen scorers. That
> figure is descriptive and conditional on an outcome; it is not a corrected
> accuracy, and it is not comparable to any condition's headline number. The
> symmetric version of the same exclusion, applied to every condition's own
> non-answers on the matched 122-question frame, gives C1 10.1%, C2 24.2%, C3
> 17.8%, and C4 5.7%. The ordering is unchanged. If all 34 contract failures had
> converted and scored at the frame's ambient rate, C4 would be 8.8% on 136 and
> 5.7% on 122, which closes 1.6 of the 19.7 points separating C4 from C2. The
> converted attempts carry more relations on average than either correct or
> wrong answers (2.875 against 1.667 and 2.620), so the ambient rate is more
> likely an upper bound than a central estimate for that subset.

### 8.4 New bullets in §8, Limitations

> - Thirty-four of 136 C4 attempts did not reach a scoreable result, and
>   attribution between the evaluated system and this harness is unresolved. The
>   compiled bundles declare no output type on any field, and the product
>   validated them without objection and later reported `UNKNOWN` for a selected
>   field's type at query planning time. Whether declaring the type at compile
>   time changes the outcome has not been tested. Both the accuracy and the
>   contract-failure rate reported for C4 carry this ambiguity.
> - The C4 structural aggregates (relation counts, join and aggregate presence)
>   are computed from the `userEditedSQL` carried on each governed semantic
>   query, because C4 records store no separate compiled SQL. The deployed
>   topics declare no joins and no measures, so multi-relation and aggregate
>   presence in those queries do not originate in the deployed model's declared
>   structure. The relation count also counts CTE references, aliased self-joins,
>   and subquery sources, so multi-relation prevalence is an upper bound on
>   cross-table access. These aggregates support the descriptive claims made for
>   them and no stronger claim about how the governed path composed its queries.
> - Accuracy on the governed frame is bounded above by 102/136 (75%) for any
>   modeling change, because a contract failure occurs downstream of the semantic
>   query an intervention would alter. This is a property of the measurement, not
>   of the system's answer quality.

### 8.5 §7, product recommendation 5

Sharpen it to the specific gap, and add the validation-time half, which is
currently missing and is the part a product team can act on soonest.

> 5. **Make semantic result contracts total, typed, and diagnosable at
>    authoring time.** Production planning and execution should expose a stable
>    representation for unknown, Boolean, temporal, and null values, and should
>    not report `UNKNOWN` for a field the JSON execution endpoint can return.
>    Where an output type cannot be resolved, model validation should say so at
>    publish time, naming the field and the reason, rather than accepting the
>    model and surfacing an untyped value on a later user query. Model import
>    should also document whether a programmatic author is expected to declare an
>    output type for a derived field, since neither validation nor readback
>    currently indicates that one is required.

### 8.6 What the reader should and should not conclude

Suggested as a short framed block wherever the 34 are first quantified.

> **What the 34 do and do not support.** They support: a quarter of governed
> attempts did not reach a scoreable result; 31 of them share one mechanism, an
> `UNKNOWN` selected-field type; the mechanism sits at a contract between a
> programmatically authored model and the product's query planner that neither
> side currently specifies. They do not support: that C4 would have scored higher
> (no conversion has been performed and no converted attempt has been scored);
> that Omni's semantic layer is defective (the compiled bundles declare no output
> type on any field, and the compiler computes one it does not emit); that this
> harness caused the failures (the product accepted and validated every bundle
> without reporting a missing type, returned values through its execution
> endpoint for a field its planner typed as `UNKNOWN`, and has never been tested
> against a bundle that declares a type); or that the 34 are unique to the
> governed path (C1 and C3 have 27.0% and 26.2% non-answer rates on the same 122
> questions, by different mechanisms).

---

## 9. Standing risks in the current framing

Three ways the present internal documents could produce an indefensible claim if
copied into RESULTS.md unchanged.

1. **`docs/c4-reliability-intervention-family.md` §2 labels all 34 as
   "Evaluated-system failure" in a Disposition column.** That is correct as a
   scoring disposition, meaning the attempt counts against the evaluated system
   rather than being reruns. Read as an attribution, it asserts the product-side
   conclusion this document argues is unresolved. If any of that table reaches
   RESULTS.md, the column needs renaming to something like "scoring
   disposition", with attribution stated separately.
2. **The bead states the mechanism as settled: "the mechanism is OUR
   compiler".** The verified chain is: the compiler emits no type (verified), it
   computes one it discards (verified), one field-level observation of `UNKNOWN`
   exists (PF-014), and the causal link is untested (E05's own precondition is
   unrun). Overstating our own culpability is also a defensibility failure,
   because it licenses an unfalsified implicit claim that Omni would have scored
   higher.
3. **§4's `userEditedSQL` finding is not yet reflected anywhere.** If the
   governed queries substantially carry SQL the model's declared structure
   cannot have produced, that affects the C4 condition's interpretation well
   beyond the 34, including whether E02's relationship intervention can express
   an effect. It should be checked with the shape-only count in §6.4(2) before
   RESULTS.md makes any further structural claim about C4.

## 10. Recommended sequence

1. Run the E05 precondition, §6.4(1). Offline, aggregate, no live attempt.
2. Run the `userEditedSQL` shape count, §6.4(2). Offline, aggregate.
3. Run the type-declaration acceptance probe, §6.4(3). Tier 1, public only.
4. Then, and only then, write the mechanism into RESULTS.md with whichever
   attribution the three results support. Until then use §8's language, which is
   accurate under every outcome of the three checks.

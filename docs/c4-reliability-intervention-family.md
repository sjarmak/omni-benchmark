# C4 contract-failure reliability as an intervention family (E05)

Status: specified, not registered and not executed. Bead
`omni-benchmark-ei0.11.6`. This document elevates contract-failure reliability
to a first-class intervention family alongside E01-E04 and fixes its taxonomy,
its landed-versus-remaining boundary, its intervention spec, and its
expected-value argument. It uses only released dev-A aggregates, public
compiler code, and the decision ledger. No question identity, SQL text, result
value, gold, hidden annotation, dev-B record, or sealed outcome is referenced.

`experiments/planned-dev-a-interventions-v1.json` is a committed registration
and is not modified here. E05 enters the loop under its own registration when
it is executed.

## Correction, 2026-08-30

`docs/c4-mechanism-measurements.md` measured the terminal governed-C4 failures
directly against the frozen recovery manifest at its pinned digest. The class
split reported below as 32 class A, 1 class B, 1 class C is wrong. The measured
split is 31 class A, 1 class B, 2 class C. The terminal total of 34 is
unchanged. Every count and table in this document that carries the old 32/1/1
split is corrected below; the E05 precondition result is also recorded, since
it has since been run. See `docs/c4-mechanism-measurements.md` for the
measurement, the analyzer, and the custody bindings.

## 1. Why this is a family and not a bug queue

The frozen C4 dev-A baseline scored 9 correct, 93 wrong, and 34 refused or
system-error over 136 answerable attempts. The 34 are not wrong answers. They
are attempts where the governed system produced work that the frozen execution
contract could not score. Two facts make them a family rather than incidental
noise.

They are large. The error class is 25.0% of the promotion frame and 3.8 times
the size of the entire correct set.

They are structurally distinct. In the identity-free structural aggregate, 32 of
34 error records contained parseable governed SQL, error queries averaged 2.88
relations against 2.62 for wrong answers and 1.67 for correct answers, and
multi-relation queries appeared in 20 of 32 parseable errors. The governed
system was not silent on these questions. It generated a query and then failed a
contract downstream of generation.

## 2. Taxonomy of the 34

Two classifications exist in the ledger and both are authoritative for what they
describe. D-155 recorded the capture-time labels of all 45 original capture
failures, then reclassified them with aggregate-only runtime metadata.

Capture-time labels, 45 failures across 136 attempts:

| Capture label | Count |
| --- | ---: |
| Unsupported semantic result type | 34 |
| Response-contract failure | 10 |
| Adapter transport failure | 1 |

Post-classification under append-only recovery v5, manifest SHA-256
`5d6ff474f30d3de6d703ad5c6c59373fe8093515eabb83473bdb352c4f30fd9f`:

| Mechanism class | Count | Disposition | Surface |
| --- | ---: | --- | --- |
| A. Result-type gap: planner reported `UNKNOWN` for a selected field | 31 | Evaluated-system failure | Evaluated system (semantic model and product plan API) |
| B. Capture and completed-job contract: job completed with no parseable generated query | 1 | Evaluated-system failure | Evaluated system |
| C. Planner or adapter exception: persistent plan rejection | 2 | Evaluated-system failure | Mixed; classified evaluated-system after retry exclusion |
| D. Result-only replay recovered | 11 | Scored as an answer | Harness capture and adapter |
| **Terminal evaluated-system failures** | **34** | | |

The per-attempt mapping from capture label to final class is not derivable from
the published aggregates. What is derivable is the final composition, and it
does not cross-check as cleanly against the independent structural diagnostic
as an earlier version of this document claimed. 33 of the 34 terminal failures
carry a non-empty `userEditedSQL`, and 32 of those parse. The parseable set
spans both class A (30 of 31 parse) and class C (2 of 2 parse); the single
class-B attempt carries no semantic query at all, so it has no `userEditedSQL`
to parse. The 32-parses figure is not the class-A count. It is a coincidence of
two different 32s; see `docs/c4-mechanism-measurements.md` §0.

Class D is the transport-and-capture tail. All 11 were converted to typed result
artifacts by replaying only the already-generated semantic query, with no
question resubmission and no model-reasoning rerun. That conversion is why the
terminal error count is 34 and not 45.

**Class A carries 91% of the remaining loss.** Any reliability intervention that
does not address `UNKNOWN` selected-field types is addressing 3 attempts.

## 3. What is already landed, and what remains

The distinction that governs this section: the harness capture path is not the
evaluated system, so fixing it is measurement bookkeeping and is not
promotion-eligible. The compiled semantic layer deployed to Omni is the
evaluated system, so changing it is an intervention and must pass the common
acceptance gate.

| Change | Class targeted | Commit or decision | Side | Effect |
| --- | --- | --- | --- | --- |
| Preview-control and action-envelope parsing | D | D-121, `9526505` | Harness | Preserved-response parse went 0/5 to 5/5 on the canary set |
| Selected-field versus dependency-field validation | A, D | D-132 | Harness | Made one canary's 240 rows captureable; separated a real `UNKNOWN` from a parser artifact |
| Boolean support, empty-string preservation, typed nulls in replay | D | D-155 | Harness | 11 of 45 capture failures recovered as typed results |
| Completed-job contract semantics preserved rather than dropped | B | D-168, `d18ce32` | Harness | Completed/no-query attempts stage as evaluated-system failures instead of stopping the dispatcher |
| Unsupported result types preserved as a distinct outcome | A | D-169, `34b7812` | Harness | `unsupported_semantic_result_type` is a classified outcome, not a generic contract error |
| Already-returned JSON rows bound after preview mismatch | D | D-170, `8b0c739` | Harness | Strict preview-binding failure falls back to rows the same call already returned, with one plan call and one JSON execution |

Every landed fix is on the harness side. Together they did two things: they
converted 11 attempts from unscoreable to scored, and they made the remaining 34
classifiable instead of undifferentiated. Neither of those is an accuracy
intervention on the evaluated system, and none of them should be reported as
one.

**What remains is entirely class A, and it is on the evaluated-system side.**
The harness is already correct to refuse it. `c4_result_recovery` fails closed on
`UNKNOWN` rather than inferring a type from returned values, because value-based
inference silently changes comparison and aggregation semantics; D-132 rejected
that path deliberately. No further adapter change can recover a class-A attempt
without breaking the type-faithful scorer boundary.

The candidate mechanism sits in the compiler. `semantic_bundle._derived_dimension`
emits compiled derived fields as `label`, `description`, `sql`, and `ai_context`
with no declared output type, leaving the product to infer the type of a derived
expression. It already knows more than it declares: the mapping carries a
`representation` that is exactly one of `boolean_derived_dimension`,
`categorical_derived_dimension`, or `numeric_derived_dimension`, and
`semantic_numeric` already classifies public declared column types into numeric
and text kinds. The supported result-type set is
`{BOOLEAN, DATE, JSON, NUMBER, STRING, TIMESTAMP, YESNO}`. PF-014 records the
observed shape of the failure: a selected derived field reported `data_type:
UNKNOWN` while the JSON endpoint returned values for it.

That is the E05 hypothesis. It is verifiable offline before any live attempt.

## 4. Intervention spec

Same shape as the E01-E04 entries. It is reproduced here as a candidate for
registration, not as a registration.

```json
{
  "id": "E05-reliability",
  "hypothesis": "Governed attempts fail the result-type contract because the compiler emits derived semantic fields without a declared output type, so the product must infer the type of a derived expression and can resolve it to UNKNOWN. Declaring the output type at compile time from information the compiler already holds should convert result-type failures into scoreable answers without changing which query the agent writes.",
  "observation": "Thirty-four of 136 answerable C4 dev-A attempts are terminal evaluated-system failures. Aggregate-only classification attributes 31 to an UNKNOWN planner result type, 1 to a completed job with no parseable query, and 2 to a persistent plan rejection. Thirty-two retain parseable governed SQL, so generation succeeded and the contract failed downstream. Compiled derived dimensions are emitted with label, description, sql, and ai_context and no declared output type, while the mapping already records a boolean, categorical, or numeric representation and the public schema already supplies declared column types.",
  "optimization_surface": "compile-time output-type declaration for semantic fields",
  "generality": "cross-database/general",
  "condition_scope": ["C4"],
  "exact_reusable_change": "Declare an explicit output type on every compiled semantic field, derived only from the recorded representation class and the public declared column types of its referenced fields, mapped into the supported result-type set. Boolean representations declare a boolean type, categorical representations declare a string type, numeric representations declare a number type only when every referenced public column resolves to a numeric declared type. When the representation and public schema do not jointly determine one supported type, defer the definition to searchable context instead of declaring a guess. Never infer a type from returned values, question text, gold, or an observed failure.",
  "candidate_generation": "one structural implementation; no wording search, no per-field tuning, no candidate ranking",
  "expected_effect": "Convert result-type contract failures into scoreable attempts at the frame's ambient answer quality, and leave query generation, retrieval, relationships, and context construction unchanged.",
  "prespecified_dev_a_evaluation": "Before any live attempt, run an offline aggregate precondition on the immutable v8 generation records: count how many of the 31 UNKNOWN-type failures selected a compiled derived field versus a physical field, using field-kind metadata only. If fewer than 16 selected a compiled derived field, the compiler mechanism does not carry the class and E05 is recorded INCONCLUSIVE without consuming a live attempt. If the precondition holds, schedule all 154 dev-A questions, apply the fixed 18 scorer-conformance exclusions, and evaluate on all 136 answerable questions, exactly as E02 does. Deploy only to the 16 databases derived from the committed answerable schedule.",
  "regression_check": "Run the entire frozen baseline-correct dev-A set. Report fixed and regressed IDs. Separately report the terminal failure vector: the count moving from refused_or_error to correct, to wrong, and the count moving in either direction out of correct. A move from wrong_answer to refused_or_error is a regression even when accuracy is flat.",
  "keep_revert_rule": "KEEP only if the common acceptance gate passes and the terminal evaluated-system failure count falls. Any declared type that is not determined by the representation class and public declared column types is an automatic REVERT. Any newly introduced type coercion that changes an existing correct answer is an automatic REVERT. A fall in error count with no net accuracy gain is recorded as a measurement improvement and does not by itself satisfy the accuracy gate."
}
```

### 4.1 Precondition outcome, 2026-08-30: INCONCLUSIVE

The `prespecified_dev_a_evaluation` precondition has been run against the
immutable v8 generation records, offline, no live attempt consumed. Measured in
`docs/c4-mechanism-measurements.md` §1: at most 6 of 31 class-A attempts contain
any compiled derived field in their selected field set, 0 select a compiled
derived field exclusively, and derived and physical compiled fields together
reach only 7 of 31. The precondition threshold is 16 of 31. 6 is below 16 by a
factor of 2.7.

Per the promotion rule stated in the precondition itself, E05 is recorded
**INCONCLUSIVE**. The compiler mechanism does not carry the class: 24 of 31
class-A attempts select no compiled bundle field of any kind, so no type
declaration on any compiled field, derived or physical, can reach them. E05 is
not recommended as the first optimization candidate on this evidence. The full
measurement, including the per-reference provenance breakdown and the bounds
argument, is in `docs/c4-mechanism-measurements.md` §1.

Generality constraint, stated once and binding on every rule in the change: no
database name, question identifier, question text, gold value, hidden
annotation, per-question label, or observed correctness may appear in or
condition any rule. The type declaration is a function of the representation
class and the public declared column types, and of nothing else. This is the
same constraint D-174 already enforced when it derived the E02 deployment set
from the committed schedule without naming a database in code.

The stopping rule that governs E01-E04 applies unchanged. E05 stops on two
consecutive failed gates, on any coverage failure that prevents complete
evaluation of the 136 answerable questions, or when the remaining change becomes
benchmark-specific.

## 5. Expected value

Two arguments. The second is the stronger one.

### 5.1 Direct accuracy

Of 136 answerable attempts, 102 reached a scored answer and 9 were correct, an
ambient rate of 8.82%. One answer is 0.74 percentage points. The common
acceptance gate requires two net additional correct answers, which is 1.47
points.

| Scenario | Attempts converted | Expected additional correct | Resulting accuracy |
| --- | ---: | ---: | ---: |
| Baseline | 0 | 0 | 9/136, 6.62% |
| Half of the error class converts at the ambient rate | 17 | 1.50 | 7.72% |
| The full class-A mechanism converts at the ambient rate | 31 | 2.74 | 8.63% |
| All 34 convert at the ambient rate | 34 | 3.00 | 8.82% |

Read the table carefully. Half-conversion at the ambient rate yields about 1.5
expected answers, which is under the two-answer gate. The claim that reliability
work beats a typical modeling delta holds at full conversion of class A, not at
half. Full conversion of class A is a 2.01-point gain and a 30% relative
improvement over a 6.62% baseline, which is larger than the gate any single
E01-E04 candidate has to clear.

There is a countervailing signal and it should not be hidden. Error queries
averaged 2.88 relations against 2.62 for wrong answers and 1.67 for correct
ones, and 20 of 32 parseable errors were multi-relation. If relation count
predicts difficulty, converted attempts will score below the ambient 8.82%, and
the direct gain shrinks. The direct argument alone is therefore real but not
decisive.

### 5.2 Measurement capacity, which is the real case

The 34 errors are not merely uncounted. They are attributed as non-correct and
they are insensitive to every modeling change. No E01-E04 intervention can
express an improvement on an attempt that fails the result-type contract before
scoring, because the contract failure happens downstream of the semantic query
the intervention changed.

That produces three compounding costs at a 9/136 baseline.

Every other intervention is measured on 102 informative attempts rather than
136. Restoring class A raises the informative denominator by 30%, which raises
the power of every subsequent gate on the same frame at no additional live cost.

Accuracy is capped at 102/136, or 75%, regardless of modeling quality. The
ceiling is not a modeling property and should not be paid for with modeling
work.

The two-answer gate is a coarse instrument against 34 opaque attempts. A
modeling change that fixes three class-A questions and breaks one elsewhere is
currently indistinguishable from one that fixes nothing, because the three fixes
are absorbed by the error class.

This makes E05 a multiplier on E01-E04 rather than a competitor for the same
budget, and it is the reason to sequence it early in the loop rather than to
rank it against a modeling candidate on projected accuracy alone. The
precondition in the spec keeps that sequencing cheap: it is an offline aggregate
count on records that already exist, and it can retire the hypothesis before any
live attempt is spent.

### 5.3 What E05 does not claim

It does not claim the converted attempts will be correct. It claims they will be
scoreable and therefore attributable.

It does not claim the landed harness fixes were interventions. They restored
capture fidelity and classification. Reporting them as accuracy work would
overstate the evaluated system.

It does not claim a product defect is fixed. PF-008, PF-010, PF-013, and PF-014
remain open product findings. E05 works around the `UNKNOWN` type gap from the
authoring side by declaring what the compiler already knows. The product-side
recommendation, an authoritative executable output type for every selected
semantic field, stands independently of whether E05 is promoted.

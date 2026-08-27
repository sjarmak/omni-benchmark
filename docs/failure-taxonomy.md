# Living failure taxonomy

Status: pre-baseline. No Omni benchmark run has been scored, so observed counts,
prevalence, representative failed questions, and affected databases are not yet
available. This file must not turn plausible risks into fabricated findings.
Update it at every baseline/checkpoint and preserve category splits/merges in the
research log.

## Current top three risk hypotheses—not observed failures

1. **HKB dependency composition.** All databases contain multi-hop HKB paths and
   the public HKB has 945 declared edges. A mechanical compiler may represent
   nodes but lose dependency meaning, grain, or composition.
2. **Semantic discoverability.** A definition may be correct in Omni but absent
   from the Topic/retrieval surface used by the agent, producing an apparent
   reasoning failure that is actually context selection.
3. **Compilation/validation fidelity.** Correct semantic intent may be altered
   during semantic compilation or rejected/changed by validation and retry
   behavior.

The highest-information next experiment is the public-only mechanical baseline
with trace capture sufficient to classify each HKB-linked dev-A failure into the
mechanism ladder below. That experiment can confirm, split, reorder, or reject
these hypotheses.

Every checkpoint also preserves the terminal failure vector. A move from
`wrong_answer` to `refused_or_error` is recorded separately from an accuracy
change so validation and safety behavior are not collapsed into one failure bin.

## HKB-linked mechanism ladder

For a failed development question whose offline annotation references HKB
knowledge, classify the earliest supported failure point:

1. required knowledge absent from the semantic model;
2. knowledge present but dependency graph wrong;
3. knowledge represented correctly but not retrieved;
4. knowledge retrieved but misinterpreted;
5. semantic representation correct but compilation failed;
6. compiled query correct but validation/harness changed the outcome;
7. model reasoning failed despite a correct, available representation.

Hidden `external_knowledge` IDs stay in offline diagnosis. This document records
aggregate classifications and non-private references, never hidden content.

## Candidate taxonomy

| Category | Definition | Count / prevalence | Representative examples | Affected databases | Suspected mechanism | Experiments attempted | Status | Product implication |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| HKB absent/mistransformed | Required public business definition is missing or semantically wrong in Omni | Not measured | Await baseline | Await baseline | Transformation coverage or interpretation | None | Unmeasured | Semantic-model authoring/automation |
| HKB dependency | Nodes exist but prerequisite edges, recursion, grain, or composition are wrong | Not measured | Await baseline | Await baseline | Dependency compiler | None | Unmeasured | Hierarchical metric composition |
| Retrieval/discoverability | Correct modeled object is not surfaced/selected | Not measured | Await baseline | Await baseline | Topic/context/retrieval behavior | None | Unmeasured | Agent discoverability and debugging |
| Retrieved but misinterpreted | Correct object is selected but agent uses it incorrectly | Not measured | Await baseline | Await baseline | Model reasoning or description ambiguity | None | Unmeasured | Description quality / reasoning support |
| Relationship/join | Wrong or missing join path, cardinality, or entity relationship | Not measured | Await baseline | Await baseline | Model relationship representation/planning | None | Unmeasured | Relationship authoring and guardrails |
| Metric/aggregation/grain | Wrong measure, aggregation, grouping, or grain | Not measured | Await baseline | Await baseline | Measure translation or reasoning | None | Unmeasured | Metric semantics and compiler checks |
| Time semantics | Wrong period, boundary, timezone, or comparison window | Not measured | Await baseline | Await baseline | Temporal modeling/planning | None | Unmeasured | First-class time semantics |
| Filter/value/alias | Wrong business filter, value interpretation, synonym, or alias | Not measured | Await baseline | Await baseline | HKB translation/retrieval/model reasoning | None | Unmeasured | Search and semantic authoring ergonomics |
| Semantic compilation | Intended semantic query is correct but compiled SQL is wrong/unsupported | Not measured | Await baseline | Await baseline | Omni compiler | None | Unmeasured | Compiler correctness/coverage |
| Validation/retry | A viable answer is rejected, corrupted, or not recovered | Not measured | Await baseline | Await baseline | Production validation/harness | None | Unmeasured | Validation observability and recovery |
| Direct reasoning | Required representation and tools are correct/available but reasoning fails | Not measured | Await baseline | Await baseline | Model planning/reasoning | None | Unmeasured | Agent workflow/model routing |
| Refusal/error | System returns no usable answer after its allowed retry policy | Not measured | Await baseline | Await baseline | Model/tool/harness/infrastructure ownership | None | Unmeasured | Reliability and safe failure behavior |
| Scorer/data ambiguity | System result may be reasonable but benchmark comparison or question is anomalous | Not measured | Await baseline | Await baseline | Benchmark/evaluator | None | Unmeasured | Evaluation limitation, not presumed product defect |

## Checkpoint update template

At each major checkpoint append:

- run/checkpoint ID and commit;
- total correct, wrong, and refused/errored;
- category counts and changed definitions;
- top three remaining sources of failure;
- fixed and newly exposed mechanisms;
- experiments linked to each category;
- product findings created or updated;
- highest-information next experiment.

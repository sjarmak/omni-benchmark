# What I tried, and what it changed

The full contemporaneous ledger is [`docs/research-log.md`](research-log.md),
about 200 numbered decisions written as the work happened. This page is the
research path through it: the hypotheses that were actually tested, what each
one did to the result, and the ones that produced nothing. Implementation and
custody decisions are omitted unless they changed a finding.

All optimization ran on development data. The 101 held-out questions were split
and committed before the gold labels were requested, and no held-out outcome was
used to select or edit an intervention.

## Trajectory

| # | Hypothesis | Change tested | Evaluated on | Result | Decision | What it taught |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | The public knowledge base can be compiled into an executable Omni semantic model | Conservative compiler that refuses to emit an object whose grain, identity, cardinality, or aggregation is not explicit | All 1,090 public HKB definitions, 18 databases | 193 compiled (17.7%), 193 kept as searchable context (17.7%), 511 deferred across an unresolved grain (46.9%), 193 unsupported (17.7%) | Ship the conservative compiler; carry the remainder as retrievable context | The knowledge base does not carry the contracts a semantic layer needs. Grain and relationship gaps, not vocabulary gaps, are what block compilation |
| 2 | Unbounded schema retrieval makes the direct comparator both unrunnable and an unfair control | Schema tool capped at 4 tables and 64 KiB per call | dev-A canary, then the full direct baseline | The 51-table single response disappeared; C1-C3 became runnable at $1.43 to $1.90 per attempt | Freeze the bound as a disclosed comparator scaffold | Retrieval payload is part of the agent contract. A scaffold choice can move a condition more than the condition's own treatment does |
| 3 | Searchable business knowledge improves a direct-SQL agent | C2 adds raw HKB search over C1; C3 substitutes the compiled model export | 122 official-scoreable dev-A questions per condition | C1 7.4%, C2 23.8%, C3 13.1% | Carry all three into the sealed comparison unchanged | Raw business knowledge helps substantially. Converting it into a bounded structured model gave back most of that gain |
| 4 | The governed Omni path benefits from the same knowledge, expressed as a model | C4 runs the deployed semantic model through Omni's production agent | 136 answerable dev-A questions | 9 correct (6.6%), 93 wrong, 34 refused or ended in a system-contract error | Freeze C4 untuned as the mechanical baseline | The governed path has a reliability surface of its own: a quarter of attempts never reached a scoreable answer |
| 5 | **C4 minus C3 isolates semantic query composition** | Read the query-path telemetry on every governed attempt instead of assuming the path | All 135 governed semantic queries on dev-A | 135 of 135 carry `rewriteSql: true` with agent-authored SQL. None declares a join path. The model resolved fields on 109 of 135 | **Refuted.** Amend the claim, disclose it, keep the data | Because the conservative compiler left topics with no joins and no measures, no composed path existed for cross-table access. C4 measured Omni-as-vocabulary, not Omni-as-compiler |
| 6 | E01: same-grain dependency composition is a missing ingredient | Audit the frozen baseline for dependency-bearing elements | Frozen baseline model, 18 databases | Already present: 48 dependency-bearing elements, 70 executable dependency edges, depth 3 | No contrast run | Audited no-op. The ingredient was never missing, so the experiment was cancelled rather than run for appearances |
| 7 | E02: declaring FK-backed relationships restores a composed join path | 91 relationships emitted across 16 databases from the 1,049 public FKs that pass a conservative cardinality rule | Fixed 136-question dev-A schedule | Generation complete and frozen: 117 answers, 19 capture-infrastructure failures, 5 of which lost the query itself in transport | **INCONCLUSIVE** under the preregistered complete-136 coverage rule. No promotion, no rerun | A preregistered coverage rule binds even when the direction is favorable. The no-rerun diagnostic on the 117 captured answers gives 11 official successes against 9 for matched C4, which is directional evidence and not a result |
| 8 | E03 (bounded descriptions), E04 (broad HKB context negative control) | Prespecified only | Not run | Not run | Out of MVP scope after the scoring-order deviation | Registered and left visible rather than quietly dropped |
| 9 | E05: declaring explicit output types fixes the 31 `UNKNOWN`-type result-contract failures | Preregistered precondition: at least 16 of those 31 attempts must select a compiled semantic field | Immutable generation records, offline | Ceiling is 6 of 31. 24 of 31 select no compiled bundle field at all, so no declaration on a compiled field can reach them | **INCONCLUSIVE** by its own stopping rule, before any live attempt | A stopping rule checked against existing records killed a plausible intervention for zero cost. The failures are upstream of anything the model declares |
| 10 | C5: Omni deployed the way its documentation prescribes carries the knowledge value C2 demonstrated | Widened view surface (every public table), full FK join graph, complete HKB ported into `ai_context` at field, topic, and model level | 136-question dev-A schedule | 18 correct (13.2%) against frozen C4's 9 (6.6%) on the identical frame; 13/122 against 5/122 on the five-condition intersection; median tokens 396,884 against 583,188; 134 of 134 parseable queries still carry `rewriteSql` and none declares a join | **Partly supported.** Report as a dev-A mechanism result; no promotion, no held-out claim | The knowledge value survives, the composition does not. Widening the model from 6-11 views to 47-63 with the full FK graph doubled accuracy and moved the rewrite rate by zero. The semantic layer worked as context, not as a compiler, which is what PF-016 records |

## What the trajectory shows and the numbers do not

**The hypothesis changed when the evidence changed.** Row 5 is a refutation of
this study's own central design assumption, found by measuring the query path
rather than assuming it. Everything after row 5 exists because of it: E02 and C5
both test the mechanism that measurement exposed. The alternative was to report
C4 minus C3 as a semantic-layer effect, which the telemetry does not support.

**Null and inconclusive results were preserved, not absorbed.** Rows 6, 8, and 9
cost live attempts that were never spent, and row 7 spent 136 attempts for a
formally inconclusive answer. All four remain in the ledger with their original
classifications. E02's INCONCLUSIVE verdict stands even though its directional
diagnostic favors the intervention, because the coverage rule was fixed in
advance and five attempts genuinely lost their query in transport.

## Ordering deviation, disclosed

The sealed C1-C4 comparison was scored before E02's dev-A generation finished,
which reverses the intended order. E02 had already been selected, preregistered,
and compiled before any sealed outcome existed, so the frozen comparison is
unaffected: every generation was complete before labels were released and both
scorers were published together. The consequence is narrower and permanent. No
optimized arm can now be promoted to the held-out set, because the sealed
aggregates are visible. The study therefore reports a valid untuned held-out
comparison plus a separate development optimization record, and claims no
held-out improvement from tuning. See
[`RESULTS.md`](../RESULTS.md) section 6, "Optimization-scope limitation".

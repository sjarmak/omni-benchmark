# C4 query path: what the governed arm actually executed

Status: disclosure finding. Companion to `docs/c4-mechanism-measurements.md` §2,
which first measured the flag distribution. This document establishes who chose
the rewrite path, whether an alternative existed, whether the sealed arm behaves
the same way, what survives of the C4 versus C3 contrast, and what disclosure
language the published documents now require. It changes no protocol surface, no
scorer, and no frozen artifact.

Evidence boundary: the immutable v8 generation records, the committed public
semantic bundles and schema IR, the committed condition/prompt/instruction
configs, `config/freeze-b-input.json`, the committed deployment records, and the
harness source at HEAD `94cc0d9`. No gold SQL, result value, question text,
hidden annotation, dev-B record, or sealed outcome was read. Nothing under
`runs/` was opened. Every figure is an aggregate. No question identifier, SQL
text, field name, table name, or per-question label appears here.

New measurements in this document come from two aggregate analyzers over the 135
semantic queries, reusing `build_field_index` and `build_view_columns` from
`experiments/analysis/c4_mechanism_measurements.py` so the compiled-field
provenance definition is identical to the one already published.

---

## 1. What `rewriteSql` is in this integration

`rewriteSql` is a field on Omni's own semantic-query object. It is set by Omni's
production agent, not by this benchmark.

**The harness never writes it.** A repository-wide search for `rewriteSql`,
`userEditedSQL`, `join_via_map`, and `aiGenerated` returns zero hits anywhere
under `src/`. The only occurrences are in analysis scripts that read those fields
back out of Omni's response and in documents describing them.

**The harness sends one thing: the question.** `config/prompts/c4-user-prompt-v1.txt`
is the single token `{question}`. `OmniCliClient.submit_job`
(`src/omni_benchmark/omni_cli.py:193-208`) posts a body of exactly four keys:
`modelId`, `progressWebhookEnabled: false`, `prompt`, and `branchId`. There is no
mode flag, no path selector, and no SQL hint. `config/instructions/c4-managed-instructions-v1.json`
records `"managed_agent_instructions": "not_exposed_by_omni"`, so the benchmark
neither supplies nor observes the agent's operative instructions.

**The harness passes Omni's query back verbatim.** `parse_omni_job_result`
(`src/omni_benchmark/omni_result_adapter.py:78-100`) lifts the `query` object off
the job's `generate_query` action. `omni_capture.py:221-229` then replays that
same object through `plan_query` and `run_query_json`. The only mutation is
`_query_with_model` (`omni_cli.py:401-407`), which sets `modelId` and raises if a
supplied `modelId` disagrees. Nothing in the harness rewrites, augments, or
strips the query.

**Answer to "who chose it": Omni's own agent chose it, on every attempt.** All
135 semantic queries carry `rewriteSql: true` and `aiGenerated: true`.

### 1.1 Was a non-rewrite path available and simply not taken?

For single-table questions, yes in principle. For anything requiring cross-table
access, no.

`_topic_document` (`src/omni_benchmark/semantic_bundle.py:630-645`) emits
`"joins": {}` on every topic, with the ai_context string "This topic
intentionally models no cross-table joins." The deployed baseline carries
`joins_generated: False` (asserted at `tests/test_semantic_bundle.py:296` and
`352`), and the bundles publish `dimensions` only, with no measures. A query
compiled from the declared model therefore cannot traverse a join path, because
the deployed model declares none, and cannot compile an aggregate from a declared
measure, because none exist.

This matters for how the finding is classified. The rewrite path was not a
discretionary detour around an equivalent compiled path. For the multi-relation
questions, which are 62 of 133 parseable attempts, it was the only path the
deployed model left open. The agent's behavior is a rational response to the
model it was given.

That does not fully explain the remaining 71 parseable single-source attempts,
which took the rewrite path as well. On the evidence held, Omni's agent defaults to raw-SQL
rewrite for this deployment regardless of whether the question needed it. Why it
does so is a product-internal decision the benchmark cannot observe.

---

## 2. Is this already disclosed? No, and one published claim is wrong

### 2.1 The inaccurate claim

`docs/harness-disclosure.md:32`, the "Compiler/query path" row of the condition
disclosure table, reads:

> | Compiler/query path | Agent emits SQL | Agent emits SQL | Agent emits SQL | Semantic query/objects compiled through Omni; generated SQL captured only if exposed |

The C4 cell is inaccurate in both halves.

"Semantic query/objects compiled through Omni" describes a compilation from
declared model structure. That did not happen. Zero of 135 queries declare a join
path, zero select exclusively compiled model fields, and 97 of 135 select no
compiled model field at all. The C4 cell should say what the C1-C3 cells say,
plus the qualifications in §5.

"Generated SQL captured only if exposed" implies the SQL may not have been
captured. It was captured, on all 135 attempts, in `userEditedSQL`. Separately,
`_query_fields` (`src/omni_benchmark/omni_attempt.py:166-173`) hard-codes
`"generated_sql": None` for every C4 attempt, so the field a reader would look in
is always empty while the SQL sits in an adjacent field. That is a disclosure
defect independent of the rewrite finding.

### 2.2 The strongest inaccurate claim

`docs/methodology.md:63`, the condition table's Enforcement column for C4:

> | C4 Governed Omni | Public schema and HKB | Omni semantic model | Production harness enforces semantic compilation/validation |

"Enforces semantic compilation" is the most specific and most directly falsified
claim in the project. No semantic compilation occurred on any of the 135
attempts. `docs/methodology.md:331-333` compounds it: "C4 remains the actual
production-default Omni system, including its production semantic compilation and
validation behavior."

`EVALUATION_PROTOCOL.md:212` carries the shorter form, "Enforced production
harness," in the same column position.

### 2.3 The framing claim, repeated in four places

`RESULTS.md:96-100` presents a table whose third column is headed **"Query path"**:

> | Condition | Information available at runtime | Query path |
> | C1 | Public schema | Direct SQL |
> | C2 | Public schema and searchable HKB | Direct SQL |
> | C3 | Public schema and searchable Omni model | Direct SQL |
> | C4 | Omni semantic model | Production-governed Omni |

Placing "Production-governed Omni" in a column of "Direct SQL" values asserts a
categorical difference in query path. The measured difference is not categorical.
C4's query path is also agent-authored SQL. What differs is the dialect it is
written in, the resolver that expands it, and the engine that runs it.

The identical row appears at `README.md:35` and `docs/report-draft-v2.md:33`.
Four documents carry the same unqualified framing.

### 2.4 A stale statement that says the check has not been run

`docs/report-draft-v2.md:363-369` states the open question and then says:

> If the governed queries substantially carry SQL that the deployed model's
> declared structure could not have produced, then the governed path is closer to
> an agent writing SQL with a semantic model available as context than to a
> planner composing declared objects, and that changes how much of C4's result is
> a statement about enforcement at all. The shape-only check that would resolve it
> is offline and has not been run.

The check has been run. The conditional's antecedent is satisfied. That sentence
must be replaced with the result, not merely updated.

`docs/c4-failure-attribution.md:559-564` flags the same gap: the finding "is not
yet reflected anywhere" and "should be checked with the shape-only count in
§6.4(2) before RESULTS.md makes any further structural claim about C4."

### 2.5 What is already on the record, and where

The underlying observation is not new to the project, but it has never reached a
published document.

`docs/c4-failure-attribution.md:180-196` states the puzzle and lists two
candidate readings, explicitly leaving it open: "Two readings, both
consequential: 1. The Omni agent used the raw-SQL path and wrote joins the model
does not declare... 2. The planner resolved cross-table access the model does not
declare."

`docs/c4-mechanism-measurements.md:198-209` settles it: "**Every governed C4
query went through Omni's raw-SQL rewrite path.** All 135 carry `rewriteSql:
true` together with hand-authored SQL text."

Both files are untracked working documents (`git status` shows them as `??`).
Neither `RESULTS.md`, `docs/harness-disclosure.md`, nor `EVALUATION_PROTOCOL.md`
carries any statement about `rewriteSql`, `userEditedSQL`, raw-SQL rewrite, or
agent-authored SQL in C4.

**Plain statement: the current published disclosure is not accurate.** The
finding is measured, it is material to what the headline number means, and it is
absent from every reader-facing surface.

### 2.6 Inventory of claims that are now inaccurate

| Location | Claim | Why it fails |
| --- | --- | --- |
| `docs/methodology.md:63` | "Production harness enforces semantic compilation/validation" | No compilation occurred on any of 135 attempts |
| `docs/methodology.md:331-333` | "production semantic compilation and validation behavior" | Same |
| `docs/harness-disclosure.md:32` | "Semantic query/objects compiled through Omni; generated SQL captured only if exposed" | Not compiled; SQL was captured, in `userEditedSQL` |
| `EVALUATION_PROTOCOL.md:212` | C4 enforcement "Enforced production harness" | Enforcement is over surface and name resolution, not composition |
| `RESULTS.md:100` | Query path "Production-governed Omni" against three "Direct SQL" rows | C4's query path is also agent-authored SQL |
| `README.md:35` | Same row | Same |
| `docs/report-draft-v2.md:33` | Same row | Same |
| `docs/report-draft-v2.md:368` | "The shape-only check that would resolve it is offline and has not been run" | It was run |
| `RESULTS.md:343-350` | C4 relation aggregates presented beside C1-C3 with no source note | Computed from `userEditedSQL` while `generated_sql` is `null` |
| `docs/c4-failure-attribution.md:170` | "133 of 136 governed attempts carried a non-empty `userEditedSQL`" | 135 carry one; 133 parse |
| `docs/research-log.md:10883` | "C4 could differ because it generates governed semantic queries" | Premise overturned, never revisited, no ledger entry for the measurement |

`docs/scoring.md`, `docs/benchmark-notes.md`, and `docs/protocol-diff.md` make no
C4 query-path claim and need no change.

---

## 3. The sealed arm behaves the same way

The sealed C4 arm is bound to the identical configuration by hash, not merely by
convention. Three independent bindings establish this without touching the live
run.

**Same three config files.** `src/omni_benchmark/sealed_omni_factory.py:33-35`
pins `_C4_CONDITION_PATH = config/conditions/c4-production-v1.json`,
`_C4_PROMPT_PATH = config/prompts/c4-user-prompt-v1.txt`, and
`_C4_INSTRUCTIONS_PATH = config/instructions/c4-managed-instructions-v1.json`.
Lines 307-313 raise `SealedOmniFactoryError("C4 frozen input path is
unsupported")` if a prepared attempt names anything else. The sealed prompt is
therefore the same bare `{question}`.

**Same deployed semantic model.** `config/freeze-b-input.json` gives C4
`"semantic_model_ref": "deployment:public-baseline-v13-20260829"`.
`config/sealed-omni-semantic-model-set-v1.json` carries
`"deployment_run_id": "public-baseline-v13-20260829"` with a per-database
`semantic_model_sha256`. Spot-checked against the committed deployment record for
one database, the hashes are identical. The sealed arm queries the same models,
with the same `joins: {}` topics and the same absence of measures, as the
development baseline.

**Same code path.** `sealed_omni_adapter.py` calls an `OmniProbeRunner` producing
the same `OmniProbeResult` type and hands it to the same `write_c4_attempt`
(`omni_attempt.py:49-62`), so `generated_sql` is `None` and `generated_query` is
Omni's verbatim object in the sealed arm too.

**Expectation: the sealed arm is producing `rewriteSql: true` with
agent-authored SQL at essentially the same rate.** Same agent, same prompt, same
model deployment, same absence of declared joins and measures. Nothing in the
configuration could push it toward a compiled path. This is a prediction from
committed configuration, not a measurement; the sealed records have not been and
must not be read until the arm completes.

---

## 4. What still separates C4 from C3, and what does not

C3 (`config/conditions/c3-direct-sql-v1.json`) is `"execution":
"direct_sql_harness"`, `"semantic_enforcement": "none"`, `"semantic_model_access":
"searchable"`, pointing at `semantic_models/public_baseline/manifest.json`. That
is the same compiled bundle set that was deployed to Omni for C4. C3's prompt is
also the bare `{question}`, byte-identical to C4's.

C3's tool surface is `("inspect_schema", "search_semantic_model", "execute_sql")`
(`src/omni_benchmark/direct_action_protocol.py:14`), and its answer action
carries raw SQL directly. So both arms have an agent that reads the same compiled
bundle and emits SQL. The bundle reaches C3 through a deterministic BM25 search
tool over the committed export, and reaches C4 through Omni's own unobservable
discovery over the deployed copy of the same artifact.

### Still different

1. **The agent.** C3 runs `claude-opus-5` under our own frozen scaffold with
   bounded retrieval. C4 runs Omni's managed, unobservable production agent with
   unobservable instructions, tools, and retries. This is the single largest
   uncontrolled difference between the arms, and it was already disclosed.
2. **Field resolution.** C4's SQL is written in Omni's `${view.field}` reference
   syntax and expanded by Omni against the deployed model. Where a token names a
   compiled derived dimension, Omni substitutes the HKB-backed definition at
   rewrite time. C3 must locate the equivalent definition in the searchable
   bundle and inline it by hand. The semantic layer does real work in C4 here.
   §5 quantifies how much.
3. **Execution engine and result contract.** C4 goes through Omni's plan and
   typed-result contract. That contract is where all 34 terminal failures
   originated. C3 executes against PostgreSQL directly and has no equivalent
   failure surface.
4. **Governance of the accessible surface.** C4's agent can only reach what the
   deployed views publish. C3 has `"schema_access": "inspect"` over the whole
   public schema.

### No longer different

1. **Who composes the query.** Both arms have an agent authoring SQL. The
   protocol's framing of C4 as a compiled-query condition against C1-C3 as
   direct-SQL conditions does not hold.
2. **Join and aggregation semantics.** In neither arm does a semantic layer
   resolve a join path or compile a measure. C4's joins are written into the SQL
   text by the agent, exactly as C3's are. `join_via_map` is empty on all 135.
3. **The comparability of the structural aggregate.** `RESULTS.md:343-346`
   reports C4 relation counts beside C1-C3 relation counts. Read as a comparison
   of compiled-versus-authored queries, that paragraph is misleading. Read as a
   comparison of agent-authored SQL in two dialects, it is more nearly
   apples-to-apples than the surrounding text claims. The numbers are fine; the
   frame around them is wrong.

### The hedge that was never written

C4 minus C3 is hedged in at least nine places: `docs/harness-disclosure.md:13-17`,
`EVALUATION_PROTOCOL.md:225-228`, `:258-262`, `:316-320`,
`docs/methodology.md:338-344`, `README.md:39`, `RESULTS.md:102-105`, `:498-500`,
and `docs/report-draft-v2.md:35-39`. Every one of those hedges is about **model
and scaffold parity**: C4 is a composite production system whose model routing is
unobservable, so the contrast is system-level rather than causal.

Not one of them hedges on the query path. The project has consistently disclosed
that it does not know which model C4 used, while asserting that it knows what C4
did with that model. The second assertion is the one that failed.

**The net effect on the research question.** C4 minus C3 was intended to isolate
the value of enforcing business knowledge through a semantic layer at query
composition time. It does not isolate that. What it now measures is the combined
effect of a different agent, a different SQL dialect with model-resolved field
references, a restricted accessible surface, and a different execution contract.
The semantic layer's contribution is real but narrower than claimed: it supplies
a resolved field vocabulary, not a compiled query.

---

## 5. Was the semantic model used at all? Yes, as a vocabulary, not as a compiler

This is measurable, and the answer is more favorable to the semantic layer than
§2 alone suggests. Two surfaces must be distinguished.

### 5.1 Input side: the `${...}` references inside the SQL

1,310 `${...}` tokens appear across the 135 SQL bodies. Classified against the
compiled bundles:

| Token class | Count | Share |
| --- | ---: | ---: |
| Undeclared schema column of a compiled view's table | 382 | 29.2% |
| Compiled physical dimension | 315 | 24.0% |
| Bare token, no view prefix, not attributable | 249 | 19.0% |
| View identifier the bundles do not publish | 157 | 12.0% |
| Name matching no dimension and no schema column | 125 | 9.5% |
| **Compiled derived dimension (HKB-backed)** | **82** | **6.3%** |

Per attempt, of 135:

| Property | Attempts | Share |
| --- | ---: | ---: |
| SQL body uses `${...}` reference syntax at all | 134 | 99.3% |
| SQL body names a compiled view identifier | 126 | 93.3% |
| `table` field names a compiled view | 104 | 77.0% |
| References at least one compiled dimension | 109 | 80.7% |
| **References at least one HKB-backed derived dimension** | **39** | **28.9%** |
| References no compiled dimension | 26 | 19.3% |
| SQL uses only raw physical table names, no Omni identifier | 1 | 0.7% |

The compiled counts are **lower bounds**. A token lands in a `compiled_*` bucket
only when it carries a view prefix that the bundles publish and a leaf the bundle
declares. The 249 bare tokens are unattributable without the containing view
context, and some are certainly compiled dimensions. The 157 unpublished-view
tokens are largely CTE-qualified names the attempt's own SQL defines; the
committed analyzer resolves those and this one does not.

**Reading.** This is not passthrough. The agent wrote in Omni's dialect over
Omni's compiled views on essentially every attempt, and Omni resolved those
references against the deployed model. The HKB business knowledge entered the
executed query, through derived-dimension expansion, on 39 of 135 attempts.

### 5.2 Output side: the selected field list

The `fields` list is what the planner is asked to type, and it is the output
columns of the hand-written SQL rather than a projection over model fields. 518
references across 135 attempts:

| Class | Count | Share |
| --- | ---: | ---: |
| Compiled physical dimension | 58 | 11.2% |
| Compiled derived dimension | 17 | 3.3% |
| Not a compiled bundle field | 443 | 85.5% |

Attempts selecting at least one compiled derived field: 13 of 135. At least one
compiled field of any kind: 38. No compiled field at all: 97. Selecting
exclusively compiled fields: **0**.

The asymmetry between §5.1 and §5.2 is the whole finding in one line. The model
is used heavily on the way in and barely at all on the way out. That is exactly
the shape a raw-SQL rewrite produces, and it is why the planner had output
columns it could not type.

### 5.3 Other structured query keys

`sorts` is non-empty on 101 attempts, `filters` on 71, `calculations` on 24.
Every other structural key (`pivots`, `fill_fields`, `row_totals`,
`custom_summary_types`, `dimensionIndex`, `join_via_map`) is empty on all 135.
While `rewriteSql` is set, the SQL text is authoritative and these fields cannot
be shown from the artifacts held to drive compilation rather than to echo a
parse of the SQL. They should not be cited as evidence of model-driven
composition.

---

## 6. Recommended disclosure language

### 6.1 `docs/harness-disclosure.md`, replace the C4 cell at line 32

Current C4 cell:

> Semantic query/objects compiled through Omni; generated SQL captured only if exposed

Replacement:

> Omni's production agent emits SQL through the product's raw-SQL rewrite path.
> All 135 development-baseline semantic queries carry `rewriteSql: true` with
> agent-authored SQL in `userEditedSQL`; none declares a join path. The SQL is
> written in Omni's `${view.field}` reference syntax over compiled views and
> resolved by Omni against the deployed model. `generated_sql` is recorded as
> `null` by design; the executed SQL is the semantic query's `userEditedSQL`.

### 6.2 `docs/harness-disclosure.md`, add after the paragraph ending at line 40

> **Governed query path, measured.** The C4 condition is labeled
> `"semantic_enforcement": "governed"`, and that label describes name resolution
> and accessible surface, not query compilation. The deployed topics emit
> `"joins": {}` and publish no measures, so the model declares no join path and
> no aggregate for a planner to compile. Every governed query in the frozen
> development baseline was composed as SQL by Omni's agent and rewritten by the
> product. The semantic layer's measured contribution is a resolved field
> vocabulary: 109 of 135 attempts reference at least one compiled dimension and
> 39 reference at least one HKB-backed derived dimension, but 0 select
> exclusively compiled model fields and 97 select none. The same configuration,
> prompt, and model deployment are hash-bound into the sealed arm
> (`sealed_omni_factory.py:33-35`, `config/sealed-omni-semantic-model-set-v1.json`),
> so the sealed arm is expected to show the same path. See
> `docs/c4-query-path-disclosure.md`.

### 6.3 `RESULTS.md`, replace the C4 row of the table at lines 96-100

> | C4 | Omni semantic model | Omni agent emits SQL through the product's rewrite path over model-resolved field references |

### 6.4 `RESULTS.md`, add immediately after that table

> **What "production-governed Omni" turned out to mean.** C4 was preregistered as
> the governed condition against three direct-SQL comparators. Measured on the
> frozen development baseline, the governed path is also an agent authoring SQL.
> All 135 semantic queries set `rewriteSql: true` with hand-authored SQL, and
> none declares a join path; the deployed model publishes no joins and no
> measures, so no compiled cross-table or aggregate path existed to take. The
> semantic layer still does work, as a field vocabulary Omni resolves at rewrite
> time, including HKB-backed derived definitions on 39 of 135 attempts. It does
> not compose the query. Read C4 minus C3 accordingly: it compares two
> agent-authored SQL conditions that differ in agent, dialect, accessible
> surface, and execution contract, not a compiled-query condition against a
> direct-SQL one. Full measurement in `docs/c4-query-path-disclosure.md`.

### 6.5 `RESULTS.md`, qualify the structural paragraph at lines 343-346

Insert before "The same identity-free analysis covered all 136 governed C4
outcomes":

> C4's structural figures are computed from the semantic query's `userEditedSQL`
> because `generated_sql` is `null` for every C4 attempt. That SQL is
> agent-authored in Omni's dialect, so these figures describe agent-written
> queries in both C4 and C1-C3 rather than a compiled path against authored
> ones.

### 6.6 `docs/methodology.md:63`, replace the C4 Enforcement cell

Current: `Production harness enforces semantic compilation/validation`

Replacement:

> Production harness governs the accessible surface and resolves model field
> references; measured on the development baseline it performs no query
> compilation

And at `docs/methodology.md:331-333`, replace "including its production semantic
compilation and validation behavior" with "including its production query-rewrite
and validation behavior".

### 6.7 `EVALUATION_PROTOCOL.md:212`, replace the C4 Enforcement cell

Current: `Enforced production harness`

Replacement:

> Enforced production harness (governs surface and field resolution; see
> `docs/c4-query-path-disclosure.md` for the measured query path)

The protocol's custody, freeze, split, scorer, and receipt surfaces are
unaffected. This is a single descriptive cell, and it is a human-controlled
surface: propose the change, do not make it.

### 6.8 `README.md:35` and `docs/report-draft-v2.md:33`

Apply the same replacement as §6.3, so all four condition tables agree.

### 6.9 `docs/report-draft-v2.md:363-369`, replace the stale conditional

Delete "The shape-only check that would resolve it is offline and has not been
run" and replace the whole conditional with the measured result:

> The check has since been run. All 135 governed semantic queries carry
> `rewriteSql: true` with agent-authored SQL and none declares a join path, so
> the governed path is an agent writing SQL with the semantic model available as
> a resolved field vocabulary rather than a planner composing declared objects.
> That narrows what C4's result says about enforcement. See
> `docs/c4-query-path-disclosure.md`.

### 6.10 `docs/research-log.md`, add a ledger entry

The measurement that produced `docs/c4-mechanism-measurements.md` has no log
entry. D-172 at `docs/research-log.md:10878-10914` states the premise this
finding overturns, "C4 could differ because it generates governed semantic
queries," and was never revisited. A contemporaneous entry should record the
measurement, the overturned premise, and the disclosure decision taken. The
research log has uncommitted changes; this is a recommendation, not an edit.

---

## 7. Options, ranked

The untuned sealed arm is nearly complete and is bound to the frozen
configuration by hash. No option can change it. Every fix applies only to the
optimized arm.

### Recommended: disclose and reinterpret, do not call it a defect

Adopt §6 verbatim. Restate C4 minus C3 as a system-level contrast between two
agent-authored SQL conditions. Keep every number as published; nothing measured
is wrong, only the frame around it.

**Why this ranks first.** The rewrite path was not a scaffold error. The harness
sends only the question, sets no mode flag, and cannot select a path. Omni's
agent chose it, and for the multi-relation majority it was the only available
choice given a model that declares no joins. Calling that a defect would
misattribute a product behavior, and a model-declaration change is an
intervention on the evaluated system that the protocol treats as benchmark-
specific tuning unless it is general.

**Cost.** Edits to two published documents plus this one. The headline C4 number
survives with a narrower claim attached. The framing loss is real: the study can
no longer say it isolated the value of semantic-layer query composition, only the
value of a governed vocabulary plus a different agent and execution contract.

### Second: declare joins in the optimized arm and run it as a named intervention

Emit real join declarations and measures in the deployed model for the optimized
arm, and report untuned-versus-optimized as a measured contrast on whether a
model that can compile cross-table access changes the path Omni's agent takes.

**Why second.** This is the scientifically most interesting move and directly
tests the study's actual research question. It is also the largest change, it
touches `semantic_bundle.py` (currently being edited in another worktree), it
must be general rather than database-specific to satisfy the protocol, and it
proves nothing about whether Omni's agent would use a declared join even when one
exists. It does not substitute for §6; the disclosure is required either way.

**Cost.** Compiler work, redeployment, a full optimized-arm run, and a generality
review of the diff. Schedule risk is the binding constraint.

### Third: a Tier 1 public-only probe on whether a declared join changes the path

On one public database, deploy a model with a declared join and submit a
public-schema-only multi-table prompt, observing whether the returned query
carries `join_via_map` or falls back to rewrite. Public schema and public HKB
only, no question, no gold, no correctness.

**Why third.** It answers the one question §7's second option assumes the answer
to, at a fraction of the cost, and it de-risks that option. It is a probe, not a
result, and it does not change any published number.

**Cost.** One isolated branch, one deployment, one prompt. Small.

### Not recommended: treat as a scaffold defect and patch the harness

There is no harness patch available. The benchmark cannot instruct the managed
agent (`"managed_agent_instructions": "not_exposed_by_omni"`), cannot pass a mode
flag through `ai job-submit`, and must not add prompt text steering the agent
away from a path, which would be a benchmark-specific intervention on the
evaluated system. The only lever is the deployed model, which is option two.

### Separately, and cheaply: fix the `generated_sql: null` reporting defect

`omni_attempt.py:171` records `generated_sql: None` while the executed SQL sits
in `generated_query.userEditedSQL`. A reader auditing C4 looks in the empty
field. This is a genuine harness defect, it is independent of the rewrite
finding, and it can be fixed in the optimized arm without touching the evaluated
system. It does not change any recorded value in the frozen baseline or the
sealed arm, which keep `null` as recorded.

---

## 8. What this does not decide

Whether Omni's agent would use a declared join path if one existed. Nothing in
the artifacts held speaks to it; §7's third option is the way to find out.

Whether the sealed arm's rate matches the development baseline's exactly. The
configuration binding makes the same behavior near-certain, but it is a
prediction until the sealed records are released.

Whether the `sorts`, `filters`, and `calculations` values on the semantic queries
are compilation inputs or echoes of a parse. Unmeasurable from the artifacts
held.

Which specific field carried `UNKNOWN` in any failing attempt. Already
established as unrecoverable in `docs/c4-mechanism-measurements.md` §1.5.

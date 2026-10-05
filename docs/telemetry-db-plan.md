# Benchmark telemetry database (plan)

Ratified 2026-09-01. Tracking epic: `omni-benchmark-6v9`.

## Purpose

Make the run evidence queryable through Omni itself, so tuning, telemetry
and observability gaps, failure classification, and improvement areas can be
asked as questions instead of one-off analysis scripts. The database is a
view over immutable artifacts plus versioned judgments; git stays the ledger.

## Decisions

| Fork | Decision | Why |
| --- | --- | --- |
| Custody scope | Dev-A full (telemetry, traces, both scorers, correctness). Sealed C1-C4 telemetry only, plus the published `aggregate.json` rates. No per-attempt sealed correctness. Dev-B never enters. Hidden gold fields never load for any partition. | A tuning tool that can see per-question test correctness is a test-set feedback loop. |
| Host | New Neon Postgres project (`omni-benchmark-telemetry`), new Omni connection, new Omni model. | Isolated from the 18 evaluated databases; same connector type Omni already uses. |
| Labels | Append-only `attempt_label` table fed from `experiments/labels/<pass>.jsonl` in git. Human labels via `scripts/label_attempt.py`, which appends one record per invocation; a model classifier that writes a whole pass file is designed but not yet built, so `attempt_label` is currently empty. | Category assignment is semantic judgment (ZFC), must be versioned, and must survive a rebuild. |
| Omni model | Hand-authored in the repo (`config/telemetry_db/omni_model/`), deployed through the omni CLI verbs `models create` / `create-branch` / `yaml-create` / `validate` / `merge-branch` by `scripts/deploy_telemetry_omni_model.py`, not through `omni_semantic_deploy_cli`. | Measure definitions must match `docs/scoring.md`; reviewable in git. Modeling Agent evaluation stays in `omni-benchmark-w5x.3`. |

## Schema (grain and keys)

- `run` (run_id, cohort_id, condition, arm, repetition, scope, partition, model_name, model_provider, model_version, system_commit, semantic_model_ref, semantic_model_sha256, question_count, manifest); `arm` is NULL on multi-condition runs
- `question` (instance_id, database, partition, category, high_level, question text and other public fields only)
- `deployment` (deployment_id, database, connection_id, branch_id, file_count, failure_stage)
- `attempt` fact, grain `attempt_id` + `generation_record_sha256`: every generation-record field (outcome, execution_status, failure_origin, terminal_failure_class, latency, tokens, cost and cost_source, tool counts, retry and validation counts, generated_sql, trace pointers)
- `score` (attempt_id, generation_record_sha256, scorer, scorer_version, outcome, status, failure_category, score_artifact_sha256); dev-A rows only, loader refuses any instance in `test_ids.txt`
- `trace_event` (attempt_id, seq, event_type, tool_name, status, failure_class, durations, token deltas)
- `action_evidence` (attempt_id, trace_seq, tool_name, retrieval_query, retrieved_public_ids, exploratory_sql)
- `sealed_aggregate` (run_id, scorer, condition, published rates from `aggregate.json`)
- `attempt_label` (label_id, attempt_id, generation_record_sha256, taxonomy_version, category, labeler, rationale, pass_id, created_at); view `attempt_label_latest`
- `load_run` (load_id, started_at, finished_at, source manifest sha256s, row counts, loader_version, system_commit)

Arm labels: run id is the loader input, `attempt.arm` is the analysis key. The
loader reads the committed run-to-arm mapping `config/telemetry_db/arms.json`,
keyed by the run id each generation record carries, and falls back to the
record's own condition for any unmapped run. Every downstream consumer groups by
`attempt.arm`: the analysis frames, the Omni model topics, and every
reconciliation query. C5 and E02 records carry `condition: C4` because their
scaffold is unchanged, so condition alone cannot separate them. `run.arm` is
NULL for the two multi-condition runs (`public-baseline-v1-direct-16db` and
`-continuation-1`, which mix C1, C2 and C3), which is why no query may group by
it. R2-C5B and R2-M1 loaded on 2026-09-02 from
`experiments/autoresearch/raw/r2-public-evidence-measures-v2` (runs
`r2-c5b-generation-v2` and `r2-m1-generation-v2`, 136 attempts each). Those two
arms are a separate paired study over 136 dev-A questions, a superset of both
matched frames (122 official, 121 sensitivity). The frozen R2 rollup in
`experiments/analysis/r2-paired-outcomes-v3.json` is over all 136; a query that
filters `dev_a_frame` puts R2 on the same questions as C1 through E02 and so
returns different counts than the freeze. Report which set a number is over.

## Loader

`scripts/load_telemetry_db.py`, idempotent upsert, reads
`experiments/autoresearch/raw/*`, `experiments/deployments/*`, and
`runs/preserved/sealed-final-v6` (telemetry and aggregates only). Join logic
follows `experiments/trace_viewer/collect.py` (generation index keyed by SHA,
not path). Forbidden fields are rejected recursively. Connection via
`OMNI_BENCHMARK_TELEMETRY_DSN` in the untracked `.env`.

## Verification gate

Per-condition dev-A accuracy per scorer and sealed telemetry rollups queried
from the database must agree exactly with the frozen JSON outputs under
`experiments/analysis/` and with `aggregate.json`. The reconciliation is
recorded in `docs/research-log.md` before the Omni model is trusted.

## Deployed model

Shared model `5a1dcadb-0cfa-4b0f-b660-48ce2e84bc41` (`omni-benchmark telemetry`)
on connection `a511399c-aa51-4f51-b00a-6845d767687b`. The YAML under
`config/telemetry_db/omni_model/` is the source of truth: one `.view` per table
or view in `telemetry` (`attempt`, `score`, `attempt_scored`, `run`, `question`,
`deployment`, `sealed_aggregate`, `attempt_label_latest`, `trace_event`,
`action_evidence`), a `relationships` file, a `model` file with `ai_context`, and
five topics (`attempt_scored`, `sealed_telemetry`, `sealed_aggregate`, `trace`,
`deployment`). `scripts/deploy_telemetry_omni_model.py --live` uploads every file
to a fresh branch with `models yaml-create` (mode `combined`), runs
`models validate`, and merges only when validation returns an empty list.
Deployed 2026-09-02 as branch `telemetry-model-v6`
(`07efa1ca-5c47-4fb0-936e-5f54adf2d608`); `models validate` returned `[]` and
the merge succeeded. Earlier branches `v1` and `v2` were deleted (topic field
errors and an HTTP 429 mid-upload); `v3` and `v4` merged and were superseded by
`v5` after the cost-per-correct measure moved onto the `attempt_scored` view,
and `v5` by `v6`.

`v6` removed the `sealed_aggregate` to `run` relationship. `sealed_aggregate`
carries `run_id = sealed-final-v6`, the preserved sealed evaluation root that
pools the three cohort runs per condition, while `telemetry.run` holds the
twelve cohort runs `sealed-c1-r1` through `sealed-c4-r3` (alongside the dev-A
and smoke runs). The join therefore matched zero rows:
`sealed_aggregate JOIN run ON run_id` returns 0 in SQL. The relationship, the
`neondb_telemetry__run.*` fields, and the run join in `sealed_aggregate.topic`
are gone, and the `run_id` dimension description now says what that value is.

`models yaml-create` with `mode: combined` merges the posted YAML into the file
already on the branch; it does not replace it. Dropping the `joins` block alone
left the previous `join_via_map` frozen on the topic and `models validate`
returned a `no_join_path_to_view` warning, so the topic now declares
`joins: {}` explicitly. That first `v6` branch was deleted and the name reused.

Measures follow `docs/scoring.md`: accuracy is `correct` over rows with
`status = 'scored'`, computed separately for `official_soft_ex` and
`sensitivity`, and both are always reported. `attempt_scored.flip_rate` is
scorer disagreement on attempts scored by both; the repetition flip rate lives
in `sealed_aggregate.correctness_flip_rate`. Cost per correct answer divides
the cost of official-scored attempts by the official correct count, the same
definition as the README cost table, and is NULL where Omni exposes no cost
(C4, C5, E02).

### Demo queries

Each query ran with `omni -p benchmark-infra -o json query run --body -`
against the merged model (`resultType: json`, `cache: SkipCache`). Filters use
the API shape `{"kind": "EQUALS", "type": "string", "values": [...],
"is_negative": false}`; a sort entry is `{"column_name": "<field>",
"sort_descending": false}` and a `field` key there fails with HTTP 400 "Unable
to parse data stream". `query run` ignores a `topic` key and does not apply a
topic's `default_filters`, so a query that stands for a topic must repeat that
topic's filter explicitly. Every figure below was cross-checked against SQL on
the loaded database.

1. Accuracy by arm and run for both scorers (dev-A). Table
   `neondb_telemetry__attempt`, fields `attempt.arm`, `attempt.run_id`,
   `attempt.attempts`, `score.official_scored_attempts`,
   `score.official_accuracy`, `score.sensitivity_scored_attempts`,
   `score.sensitivity_accuracy`, filter `attempt.partition = dev-a`.

   | Arm | Run | Attempts | Official scored | Official acc. | Sensitivity scored | Sensitivity acc. |
   | --- | --- | ---: | ---: | ---: | ---: | ---: |
   | C1 | public-baseline-v1-direct-16db | 46 | 25 | 0.040 | 25 | 0.040 |
   | C1 | public-baseline-v1-direct-16db-continuation-1 | 115 | 97 | 0.082 | 96 | 0.083 |
   | C2 | public-baseline-v1-direct-16db | 46 | 25 | 0.160 | 25 | 0.120 |
   | C2 | public-baseline-v1-direct-16db-continuation-1 | 115 | 97 | 0.258 | 96 | 0.260 |
   | C3 | public-baseline-v1-direct-16db | 45 | 24 | 0.083 | 24 | 0.083 |
   | C3 | public-baseline-v1-direct-16db-continuation-1 | 116 | 98 | 0.143 | 97 | 0.124 |
   | C4 | public-c4-baseline-v8 | 136 | 136 | 0.066 | 135 | 0.067 |
   | C5 | c5-dev-a-v4 | 136 | 136 | 0.132 | 135 | 0.119 |
   | E02 | e02-dev-a-v6 | 136 | 117 | 0.094 | 116 | 0.086 |

   Smoke and auth runs (`archeology-vertical-v1`, `public-baseline-v1*`) carry
   no score rows and report NULL accuracy. Every official figure equals the SQL
   ground truth (C1 0.040 / 0.082, C2 0.160 / 0.258, C3 0.083 / 0.143, C4 0.066,
   C5 0.132, E02 0.094).

2. Cost per correct answer by arm (dev-A). Table
   `neondb_telemetry__attempt_scored`, fields `arm`,
   `official_scored_cost_usd`, `official_correct_count`,
   `cost_per_official_correct`, filter `partition = dev-a`.

   | Arm | Official-scored cost (USD) | Official correct | USD per correct |
   | --- | ---: | ---: | ---: |
   | C1 | 161.85 | 9 | 17.98 |
   | C2 | 181.99 | 29 | 6.28 |
   | C3 | 195.07 | 16 | 12.19 |
   | C4 | 0 | 9 | NULL |
   | C5 | 0 | 18 | NULL |
   | E02 | 0 | 11 | NULL |

   C1 to C3 match the README cost table. The governed arms store
   `cost_unavailable_reason = omni_job_api_does_not_expose_cost`, so their
   per-attempt cost is NULL and the measure stays NULL rather than dividing
   zero. That is a gap in per-attempt attribution, not in cost: Omni bills AI
   usage in credits worth a dollar each, and the recorded account reading for
   2026-08 ($635.30 over 703 recorded Omni-routed attempts) loads into
   `neondb_telemetry__credit_period` with `basis = measured_account_period`.
   `neondb_telemetry__arm_cost` uses the recorded rounded proportional rate
   ($0.6839 per attempt), which divides account spend across all 929 AI
   conversations and assumes one conversation per attempt. The upper rate
   ($0.9037) divides all account spend across the 703 recorded attempts,
   charging the 226 unattributed conversations to the benchmark. Both are
   flagged `basis = proportional_estimate`. Governed-arm cost is therefore reportable at arm level as an
   estimate and unmeasured per attempt; the bracketing path that would measure
   it per attempt (`omni_credit_cost`, gated on `OMNI_COST_BRACKET_LEASE_DIR`)
   was not armed for these runs. Do not join `arm_cost` to attempts: it would
   multiply an arm-level estimate across attempt rows.

3. Terminal failure class distribution by arm (sealed test attempts). Table
   `neondb_telemetry__attempt`, fields `attempt.partition`, `attempt.arm`,
   `attempt.terminal_failure_class`, `attempt.attempts`, no filter; the test
   rows are:

   | Arm | Class | Attempts |
   | --- | --- | ---: |
   | C1 | NULL | 179 |
   | C1 | no_answer_insufficient_context | 38 |
   | C1 | model_budget_error | 33 |
   | C1 | model_rate_limit_error | 13 |
   | C1 | database_statement_error | 4 |
   | C2 | NULL | 198 |
   | C2 | model_budget_error | 31 |
   | C2 | no_answer_insufficient_context | 16 |
   | C2 | model_rate_limit_error | 15 |
   | C2 | database_statement_error, model_identity_mismatch, sql_not_admitted, turn_limit_exhausted | 3, 2, 1, 1 |
   | C3 | NULL | 169 |
   | C3 | no_answer_insufficient_context | 55 |
   | C3 | model_budget_error | 22 |
   | C3 | model_rate_limit_error | 16 |
   | C3 | database_statement_error, model_identity_mismatch, sql_not_admitted, turn_limit_exhausted | 2, 1, 1, 1 |
   | C4 | NULL | 229 |
   | C4 | unsupported_semantic_result_type | 32 |
   | C4 | response_contract_error | 4 |
   | C4 | omni_job_terminal_failure | 2 |

   Identical to `GROUP BY partition, arm, terminal_failure_class` in SQL.

4. Median latency by arm for sealed test attempts. Table
   `neondb_telemetry__attempt`, fields `attempt.arm`, `attempt.attempts`,
   `attempt.median_latency_ms`, `attempt.mean_latency_ms`, filter
   `attempt.partition = test`.

   | Arm | Attempts | Median latency (ms) | Mean latency (ms) |
   | --- | ---: | ---: | ---: |
   | C1 | 267 | 33,424.9 | 36,725.2 |
   | C2 | 267 | 43,976.5 | 46,608.9 |
   | C3 | 267 | 39,230.4 | 47,026.5 |
   | C4 | 267 | 51,094.5 | 69,958.6 |

   Medians equal the SQL `percentile_cont(0.5)` values.

5. Scorer flip rate by arm (dev-A). Table `neondb_telemetry__attempt_scored`,
   fields `arm`, `scored_by_both_count`, `correctness_flip_count`,
   `flip_rate`, filter `partition = dev-a`: C1 0 / 121 (0.000), C2 3 / 121
   (0.025), C3 2 / 121 (0.017), C4 2 / 135 (0.015), C5 4 / 135 (0.030),
   E02 3 / 116 (0.026).

6. Re-verification after the `v6` relationship removal, run against the merged
   `telemetry-model-v6`. Accuracy by arm for both scorers (dev-A). Table
   `neondb_telemetry__attempt`, fields `attempt.arm`, `attempt.attempts`,
   `score.official_scored_attempts`, `score.official_accuracy`,
   `score.sensitivity_scored_attempts`, `score.sensitivity_accuracy`, filter
   `attempt.partition = dev-a`.

   | Arm | Attempts | Official scored | Official acc. | Sensitivity scored | Sensitivity acc. |
   | --- | ---: | ---: | ---: | ---: | ---: |
   | C1 | 174 | 122 | 0.0737704918 | 121 | 0.0743801653 |
   | C2 | 168 | 122 | 0.2377049180 | 121 | 0.2314049587 |
   | C3 | 168 | 122 | 0.1311475410 | 121 | 0.1157024793 |
   | C4 | 137 | 136 | 0.0661764706 | 135 | 0.0666666667 |
   | C5 | 136 | 136 | 0.1323529412 | 135 | 0.1185185185 |
   | E02 | 136 | 117 | 0.0940170940 | 116 | 0.0862068966 |

   All 36 values equal the SQL rollup over `telemetry.attempt` left-joined to
   `telemetry.score` per scorer with `status = 'scored'`. The by-run split of
   query 1 is unchanged; this rollup pools the two multi-condition runs.

7. Re-verification after the `v6` relationship removal: the `sealed_telemetry`
   topic's median latency by arm. Table `neondb_telemetry__attempt`, fields
   `attempt.arm`, `attempt.attempts`, `attempt.median_latency_ms`,
   `attempt.mean_latency_ms`, with the topic's own `partition = test` filter
   restated.

   | Arm | Attempts | Median latency (ms) | Mean latency (ms) |
   | --- | ---: | ---: | ---: |
   | C1 | 267 | 33424.94929092936 | 36725.206265893976 |
   | C2 | 267 | 43976.515393005684 | 46608.89758977582 |
   | C3 | 267 | 39230.41807604022 | 47026.48509725883 |
   | C4 | 267 | 51094.4620158989 | 69958.55687876331 |

   Identical to `percentile_cont(0.5)` and `avg` over
   `telemetry.attempt WHERE partition = 'test'` to full precision. A third
   check on the now-joinless `sealed_aggregate` topic returned all eight
   published `mean_accuracy` and `pass_3_rate` rows, matching
   `telemetry.sealed_aggregate` exactly.

## Natural-language questions through Omni AI

The point of the database is that a question can be asked in words rather than
SQL. These four ran through `omni ai job-submit` against the shared model with
no topic hint, each completing in about 15 to 20 seconds. Every number was
checked against `psql` afterwards and matched.

1. "Which arm has the highest official_soft_ex accuracy on the dev-A partition,
   and what is its cost per correct answer?" (job `a64e14c7`). Answer: C2 at
   23.77 percent, 29 correct of the 122-question matched frame, 6.28 USD per
   correct answer. It volunteered the sensitivity figure (23.14 percent) beside
   the official one and marked C4, C5 and E02 as having no priced cost source.
   Both scorers and the cost figures reproduce
   `matched-122-cost-time-rollup-v1.json` exactly.

2. "On the sealed test partition, what is the distribution of
   terminal_failure_class by arm, and which failure classes are unique to the
   semantic-layer arm C4?" (job `000f9826`). Answer: C4's three classes are
   disjoint from the direct-SQL arms. C4 shows `unsupported_semantic_result_type`
   32, `response_contract_error` 4 and `omni_job_terminal_failure` 2, with no
   budget exhaustion, no rate-limit failures, no insufficient-context refusals
   and no database statement errors. C1, C2 and C3 carry exactly the
   complementary set. Verified by SQL: the two sets do not intersect.

3. "Where is telemetry missing or unreliable?" (job `8e3e6b34`). Answer: cost is
   absent for every C4, C5 and E02 attempt, with `cost_source = unavailable` and
   reason `omni_job_api_does_not_expose_cost`, so cost per correct answer cannot
   be computed for the governed arms at all. C1, C2 and C3 are fully priced on
   the sealed partition but only about 87 percent priced on dev-A. It also found
   that `retry_count`, `validation_attempt_count` and `model_version` are null
   for every governed attempt, and that the `generated_sql` and `generated_query`
   columns partition cleanly by arm family.

4. "For dev-A, compare median latency, tool_call_count and database_query_count
   between attempts that scored correct and those that did not, per arm." (job
   `b6456b25`). Answer: correct attempts are faster in every arm under both
   scorers, typically 40 to 50 percent lower median latency, and use the same or
   fewer tool calls. The gap is widest in C4 (4 tool calls versus 7) and E02
   (4 versus 6) and absent in C5. Database query counts barely differ.

### What the queries surfaced that the artifacts did not

Two observations came out of asking rather than out of any frozen artifact.

- 54 official and 60 sensitivity score rows carry a null outcome, all confined
  to C1, C2 and C3 (18 per arm per scorer). Their median latency is 74 to 88
  seconds against roughly 36 to 52 seconds for scored-and-wrong attempts, and 50
  of the 54 carry a terminal failure class. A scored row with no verdict is not
  the same as a wrong answer, and the accuracy denominator currently drops them
  silently.
- Effort and correctness move in opposite directions. Failure looks like long,
  tool-heavy flailing rather than under-exploration, which is the opposite of
  what a retry or turn-limit increase would help with.

Neither observation changes a frozen result. Both are candidates for the next
round of telemetry work: a distinct outcome value for scored-but-no-verdict, and
a cost source for the governed arms.

## Out of scope

Dev-B, sealed per-attempt correctness, gold or hidden annotations, rule-based
category assignment in the loader, and any write path from Omni back to the
database.

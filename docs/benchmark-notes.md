# LiveSQLBench Large-v1 benchmark reconnaissance

Status: Phase 1, public information only. Inspected 2026-08-27.

No private attachment, gold SQL, hidden knowledge annotation, or hidden test
case was accessed to produce this document. "Observed" below means reproduced
from the pinned public files or public evaluator code. "Official claim" means
the maintainers state it but this project has not independently established it.
"Unresolved" identifies work that must not be filled in by assumption.

## Pinned public sources

| Source | Revision | Local verification |
| --- | --- | --- |
| [LiveSQLBench Large-v1 dataset](https://huggingface.co/datasets/birdsql/livesqlbench-large-v1/tree/a418e108d5cbb4cf9b783a928eff5e924ad2460d) | `a418e108d5cbb4cf9b783a928eff5e924ad2460d` | `livesqlbench_large_v1_data.jsonl` SHA-256 `f0e12218cb46f5b6e019908740a0b3303a1f8d1136c661545ad6dd1b4b5444f6` |
| [Official LiveSQLBench repository](https://github.com/bird-bench/livesqlbench/tree/e15cd221267e06fabfaf6a3d4a69308280ce9a7c) | `e15cd221267e06fabfaf6a3d4a69308280ce9a7c` | Evaluator, database build, and agent behavior were read at this revision |

The dataset card calls the benchmark continuously evolving. Every experiment
must therefore store both the revision and content hashes; the name
"Large-v1" alone does not identify immutable bytes. The card claims the release
is contamination-free, but this project cannot independently establish model
training provenance and will treat that as an official claim, not a result.

## Release structure and eligibility

The public repository contains one task JSONL and one directory per database.
Each database directory contains:

- `*_schema.txt`: PostgreSQL `CREATE TABLE` statements interleaved with three
  sample rows per table;
- `*_column_meaning_base.json`: a map from
  `database|table|column` to a description;
- `*_kb.jsonl`: structured hierarchical knowledge-base entries.

The public JSONL has 480 records and 480 unique `instance_id` values. Filtering
solely on the public `category` field yields exactly **332 `Query` records** and
**148 `Management` records**. `Query` is the benchmark's SELECT-only/BI class;
`Management` covers database-management and CRUD tasks. The latter 148 records
are excluded. This is the observed eligible population, even though the prompt's
rough expectation was approximately 320.

| Database | All | Eligible `Query` | Excluded `Management` |
| --- | ---: | ---: | ---: |
| `archeology_scan_large` | 13 | 10 | 3 |
| `cross_border_large` | 29 | 20 | 9 |
| `cybermarket_pattern_large` | 29 | 20 | 9 |
| `disaster_relief_large` | 15 | 12 | 3 |
| `exchange_traded_funds_large` | 28 | 19 | 9 |
| `fake_account_large` | 29 | 24 | 5 |
| `labor_certification_applications_large` | 29 | 19 | 10 |
| `mental_healths_large` | 26 | 20 | 6 |
| `museum_artifact_large` | 30 | 20 | 10 |
| `organ_transplant_large` | 32 | 19 | 13 |
| `planets_data_large` | 29 | 19 | 10 |
| `polar_equipment_large` | 30 | 20 | 10 |
| `residential_data_large` | 29 | 21 | 8 |
| `reverse_logistics_large` | 28 | 20 | 8 |
| `robot_fault_prediction_large` | 17 | 10 | 7 |
| `solar_panel_large` | 30 | 20 | 10 |
| `sports_events_large` | 29 | 20 | 9 |
| `virtual_idol_large` | 28 | 19 | 9 |
| **Total** | **480** | **332** | **148** |

The [dataset card](https://huggingface.co/datasets/birdsql/livesqlbench-large-v1/blob/a418e108d5cbb4cf9b783a928eff5e924ad2460d/README.md)
describes the task fields. The actual public JSONL contains:

- usable public fields: `instance_id`, `selected_database`, `query`,
  `normal_query`, `category`, `high_level`, `conditions`, `preprocess_sql`, and
  `clean_up_sqls`;
- protected-field placeholders: `sol_sql`, `external_knowledge`, and
  `test_cases` exist as empty arrays in all 480 public records;
- no `difficulty_tier` field, although the card documents one.

The card says `query` is the natural phrasing used for evaluation and
`normal_query` is a concise reference phrasing. The experiment must use `query`
for all four conditions unless a separately logged training-only intervention
tests something else.

### Public metadata available for splitting

Database is the most important stratum. Of the 332 eligible questions, 181 have
`high_level: true` and 151 have `high_level: false`. `conditions` contains three
scoring-related fields:

| Field | Eligible distribution |
| --- | --- |
| `order` | 194 true, 138 false |
| `distinct` | 17 true, 315 false |
| `decimal` | -1: 158; 0: 8; 1: 6; 2: 110; 3: 24; 4: 22; 5: 1; 6: 2; 8: 1 |

The committed split is database-first and balances `high_level` second. The
rarity of some joint `conditions` cells makes full cross-stratification unstable;
their train/test balance should be audited and reported rather than used to
construct tiny, question-determining strata. Difficulty cannot be used for
splitting or preregistered subgroup analysis because it is not public at the
pinned revision.

Two naming inconsistencies require adapters, not assumptions: the public record
uses `clean_up_sqls`, while the card documents `clean_up_sql`, and the pinned
evaluator reads `clean_up_sql`. The release also uses empty protected-field
arrays rather than literally excluding the fields as the card says. All 332
eligible Query records have empty `preprocess_sql` and `clean_up_sqls` arrays at
the pinned public revision, so the cleanup mismatch does not change the current
eligible public inputs; the adapter should still handle the contract explicitly.

## Database scale and schema metadata

The [official setup documentation](https://github.com/bird-bench/livesqlbench/blob/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/README.md#evaluation-environment-setup)
reports 18 PostgreSQL databases, 971 tables, 17,749 columns, about 2,056.48 rows
per table on average, and 746.33 MB total. Counting `CREATE TABLE` statements in
the pinned public schema files independently reproduces 971 tables.

The column-meaning maps contain exactly 17,749 keys: 17,537 plain-string values
and 212 structured values for JSON/JSONB columns. A structured value contains a
column-level description plus `fields_meaning`, a map describing nested JSON
properties. This is important semantic input; flattening only relational column
names would discard definitions for nested fields used by JSON operations.

The schema text is not clean DDL. It includes representative data values and
retains original quoting, mixed casing, types, keys, and relationships. A
preparation step must parse DDL separately from examples while preserving both
as different provenance-bearing inputs.

## Hierarchical knowledge base

Each HKB JSONL record has six fields:

| Field | Observed meaning |
| --- | --- |
| `id` | Integer identifier unique within one database, not globally |
| `knowledge` | Human-readable business concept name |
| `description` | Short intent/interpretation |
| `definition` | Natural-language rule, formula, mapping, or example |
| `type` | `calculation_knowledge`, `domain_knowledge`, or `value_illustration` |
| `children_knowledge` | Despite the name, IDs that the current node depends on; `-1` is documented as no dependency |

Observed graph statistics across all 18 databases are:

| Property | Count |
| --- | ---: |
| HKB entries | 1,090 |
| `calculation_knowledge` | 430 |
| `domain_knowledge` | 462 |
| `value_illustration` | 198 |
| Entries using documented no-dependency sentinel `-1` | 509 |
| Entries using undocumented empty list `[]` | 21 |
| Entries with one or more direct dependencies | 560 |
| Direct dependency edges | 945 |
| Maximum direct dependencies on one entry | 5 |
| Edges whose target itself has dependencies | 344 |
| Databases containing multi-hop dependencies | 18 of 18 |
| Maximum dependency-chain length | 6 edges |
| Duplicate IDs within a database | 0 |
| Dangling references / self-edges / detected cycles | 0 / 0 / 0 |

These figures normalize both `-1` and `[]` as zero outgoing dependency edges;
every list member produces an edge from the current entry to a prerequisite.
Maximum chain length and cycle checks use depth-first traversal within each
database. The 21 empty arrays are a format inconsistency, not evidence of a
different semantic category.

The dependency graph is the strongest direct connection to a semantic layer.
An HKB entry cannot safely become an isolated blob of prompt text: 344 edges
lead to another derived entry, and every database requires multi-hop resolution.
The transformation should retain a stable source key such as
`<database>:hkb:<id>`, dependency edges, original type, source text, and the
compiled Omni objects that implement it.

Candidate transformation classes to validate in Phase 4 are:

1. mechanically bind schema keys and column meanings to views/fields, including
   nested JSON fields;
2. topologically resolve HKB dependencies and translate supported calculations,
   filters, joins, aliases, and reusable dimensions/measures;
3. attach explanatory business context where a rule cannot be expressed as a
   governed semantic object without changing meaning;
4. record every interpretation and exception explicitly rather than silently
   weakening a rule or adding question-specific behavior.

These are hypotheses, not yet claims about which Omni construct can represent
every HKB type. The public release provides no formal grammar mapping HKB text to
SQL, and the type labels alone do not prove aggregation grain, join path, time
semantics, or expression support. Those require structural validation and train-
only experiments.

The general dataset card says two HKB formats exist, structured JSON and an
unstructured document. This Large-v1 snapshot contains only `*_kb.jsonl` files
and explicitly calls the release "HKB-JSON." It also advertises business-rule
drift/versioned definitions, but the observed records have no version or validity
field beyond the six fields above. Whether drift cases are encoded only in text,
are deferred to a later release, or appear in protected data is unresolved and
must not be inferred from gold.

## Official evaluation behavior

The official runner expects each scored record to contain `selected_database`,
`preprocess_sql`, `sol_sql`, and `pred_sqls`. It creates per-database PostgreSQL
template clones for worker isolation, applies preprocessing, evaluates one
record, performs cleanup, then restores the ephemeral database. See the pinned
[evaluation runner](https://github.com/bird-bench/livesqlbench/blob/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/evaluation/src/evaluation.py#L181-L425)
and [database utilities](https://github.com/bird-bench/livesqlbench/blob/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/evaluation/src/db_utils.py#L25-L338).

For `category == "Query"`, the runner discards any customized test-case list
and installs one default Soft EX result-equivalence test. Management tasks use
custom hidden test cases, but they are outside this experiment. At the pinned
revision the Query path does the following to both predicted and gold SQL:

1. remove block and line comments;
2. remove standalone `DISTINCT` while attempting to preserve `DISTINCT ON`;
3. remove `ROUND(...)` calls and retain only the first argument;
4. execute prediction and gold with a 60-second PostgreSQL statement timeout;
5. fetch at most the first 10,000 rows;
6. normalize `date` and `datetime` values to `YYYY-MM-DD`, recursively round
   floats/decimals to two places, and serialize lists/dicts with sorted keys;
7. require both normalized results to be non-empty;
8. compare lists exactly when `conditions.order` is true, otherwise compare
   Python sets of rows.

Execution errors and timeouts fail the question. Ordered comparison preserves
row multiplicity; unordered set comparison discards both order and duplicate
multiplicity. Two empty result sets fail rather than match. Date-time
normalization discards time-of-day. The default path hard-codes two decimal
places and does not consult `conditions.decimal`; it rewrites `DISTINCT`
regardless of `conditions.distinct`. Those observations come from the pinned
[Soft EX implementation](https://github.com/bird-bench/livesqlbench/blob/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/evaluation/src/test_utils.py#L118-L284)
and [default test case](https://github.com/bird-bench/livesqlbench/blob/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/evaluation/src/test_utils.py#L375-L424),
not from the higher-level README description.

The scorer executes the prediction once to detect errors and again inside the
default comparison. For a list of SQL statements, `execute_queries` retains only
the last statement's result. These details are benign for a single pure SELECT
but must be preserved or explicitly tested in any sealed wrapper. We should run
an oracle conformance suite against the pinned official evaluator before relying
on a reimplementation.

## Existing public harnesses

The repository has two relevant starting points:

- the batch evaluator described above, which is the scoring authority;
- [LiveSQLBench-Agent](https://github.com/bird-bench/livesqlbench/tree/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/LiveSQLBench-Agent),
  a Google ADK system-agent/DB-environment/orchestrator stack with eight tools,
  a 30-step budget, one final SQL submission, SELECT-only exploration, and
  per-task database copies.

The agent is useful as a comparator/harness skeleton: it exposes schema, column
meaning, HKB discovery, SQL execution, and submission as separate operations.
It is not an Omni semantic-layer condition and is not Large-v1-ready without
work at this revision: its documented configuration accepts only `lite` or
`full`. Its knowledge endpoint also omits `type` and `children_knowledge` from
the fields shown to the agent, so using it unchanged would erase precisely the
dependency structure this study is meant to evaluate. See the pinned
[agent configuration](https://github.com/bird-bench/livesqlbench/blob/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/LiveSQLBench-Agent/shared/config.py#L20-L65)
and [knowledge service](https://github.com/bird-bench/livesqlbench/blob/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/LiveSQLBench-Agent/db_environment/server.py#L25-L74).

The current public LiveSQLBench-Agent is also evidence for the intended HKB
access boundary. Its tool interface lets the agent list all database-level
knowledge names, fetch a named definition, or fetch every definition; its public
instruction tells the agent to discover knowledge when domain terms require it.
No tool receives the hidden per-question `external_knowledge` IDs as a runtime
oracle. This study follows that database-level discovery model for C2-C4. The
private IDs remain offline diagnostic metadata. If a leaderboard submission path
later proves to use different access, that difference will be documented and any
official-protocol comparator reported separately rather than changing the main
experiment.

## Database provisioning options

The official from-scratch path downloads the Large-v1 dumps, builds a
PostgreSQL 18 image, imports 18 `*_template` databases, and clones real databases
from them. The evaluator then makes worker-specific clones and resets each after
use. This is the lowest-risk scoring reference because it matches the published
build and reset model. The current prebuilt `docker-compose.yml` does not declare
a Large-v1 database service; Large-v1 is present in
`docker-compose.build.yml`, so a from-source build is the verified official path.
The [Large-v1 Dockerfile](https://github.com/bird-bench/livesqlbench/blob/e15cd221267e06fabfaf6a3d4a69308280ce9a7c/evaluation/env/Dockerfile.postgresql_large_v1)
defaults to PostgreSQL 18 because newer dumps may require it.

Three practical topologies remain under consideration:

| Option | Advantages | Risks / unresolved checks |
| --- | --- | --- |
| Official local PostgreSQL 18 container | Closest scorer parity; all 18 DBs on one host; fast template cloning/reset; low cost | Omni must be able to reach it, or generation and scoring use different copies |
| One managed PostgreSQL server with 18 databases | Stable network endpoint for Omni; matches the evaluator's one-host/many-database assumption | Service must support dump restore, required extensions, PG compatibility, template cloning or another reset strategy |
| One Neon project per database, as proposed in the initial topology | Strong DB isolation and independent reset/branch operations | 18 hosts conflict with the stock evaluator's single-host configuration; restore/version/extension compatibility, automation, quotas, and cross-copy identity require validation |

The initial recommendation is to keep the official local PostgreSQL 18 snapshot
as the scoring authority even if Omni must query a managed mirror. Before any
benchmark run, compare schema fingerprints and deterministic data canaries across
the generation and scoring copies. The three-way parity pattern in
`~/gas-city-observability` is directly reusable: a warehouse result, the same SQL
through Omni, and the governed Topic result test connection parity separately
from semantic parity. Its `0 = pass`, `1 = observed disagreement`, `2 = could not
run` contract should also be retained so missing access never masquerades as a
failed or passed benchmark question.

## Unresolved pre-baseline checks

These are Phase 2/3 checks, not permission to inspect private data:

- confirm the downloadable dump hash, exact PostgreSQL build, extensions,
  database names, and row-count/schema fingerprints;
- verify whether the official checker accepts the Large-v1 container built from
  the pinned dump without import warnings;
- choose the Omni-reachable topology and prove byte/row parity with the scoring
  snapshot;
- determine which Omni APIs/UI flows expose generated governed query artifacts,
  tool trajectories, model tier/identifier, tokens, cost, and latency;
- determine whether C4 produces SQL that can be submitted to the official scorer
  or whether a sealed, conformance-tested result-set adapter is required;
- test the official evaluator's behavior for empty results, duplicate rows,
  `DISTINCT ON`, nested `ROUND`, more than 10,000 rows, timestamps, JSON values,
  and all observed `conditions` values;
- resolve cleanup field naming without reading hidden SQL;
- confirm semantic-model export/search can expose identical public information to
  C3 while C4 retains production enforcement;
- record the dataset-card license inconsistency: front matter says CC-BY-4.0,
  while the footer says CC-BY-SA-4.0, before redistributing public artifacts.

## Threats visible before any run

- **Primary scope:** because all databases occur in train and test, the headline
  estimates unseen-question performance inside modeled databases, not cold-start
  performance on an unseen database.
- **Supervision:** final models may use dev-A failures and gold offline plus
  aggregate dev-B checkpoint feedback; the final system is supervised, not
  zero-shot, but per-question dev-B labels remain unavailable.
- **Public exposure:** the benchmark is public as of this experiment. The
  maintainers' contamination-control claim cannot rule out post-release model
  exposure.
- **Small subgroups:** 101 held-out questions give approximately one percentage
  point per question, but per-database and rare-condition cells will be small.
- **Evaluator semantics:** Soft EX deliberately equates some different SQL and
  rejects some extensionally equal cases. Accuracy is accuracy under the pinned
  scorer, not proof of fully equivalent SQL semantics.
- **Environment parity:** generation and scoring against non-identical database
  snapshots can create false gains or failures.
- **Composite C4:** production Omni may use multiple opaque model tiers and a
  validation stage, confounding a causal C4-C3 interpretation when exact model
  parity is unavailable.
- **Version drift:** Omni, model providers, and the evolving benchmark can change
  during a 1,212-trial evaluation. Pinned artifacts, timestamps, deterministic
  interleaving, and the sealed generate-then-score boundary mitigate but do not
  eliminate this threat.

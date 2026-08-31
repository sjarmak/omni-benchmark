# What the LiveSQLBench evaluation says about the product

*For Omni's product team. Independent evaluation, public inputs only, no
question-level tuning. Numbers here match [`RESULTS.md`](../RESULTS.md); the
per-finding evidence is in
[`docs/product-findings.md`](product-findings.md).*

## Bottom line

Business knowledge is worth a lot to an analytical agent, and our deployed
semantic model did not deliver it.

Giving an agent a search tool over the benchmark's business definitions raised
accuracy from 10.1% to 22.1%. Compiling those same definitions into an Omni
semantic model and asking the governed product the same questions gave 8.6%, at
3.9 times the token cost. The gap is not subtle.

We checked the governed condition's own query objects and found that all 135 captured queries carried
`rewriteSql: true` with hand-written SQL, and that none of them declared a join
path. The product's agent never composed a query through the semantic layer, because
our compiler had deferred so much of the knowledge base that the model we
deployed published no joins and no measures. For any question needing two tables
or a sum, raw SQL was the only path left.

That makes this a finding about the authoring and import path more than about the
planner. Below is what a model author cannot currently do, in the order we would
fix it. A second arm, C5, is in deployment now and tests the same product with a
model that carries the joins and the knowledge; its results section at the end of
this brief is empty on purpose, and marks where those numbers will land.

## What we ran, in one paragraph

LiveSQLBench Large-v1: 18 PostgreSQL databases, 971 tables, 17,749 columns, and a
knowledge base of 1,090 business definitions with 945 dependency edges between
them. We built four conditions that differ by exactly one thing each. C1 is an
agent with the raw schema writing SQL. C2 adds a search tool over the raw
business definitions. C3 swaps that search tool's payload for our compiled
semantic model. C4 is the governed Omni product. All four ran three times over
the same 89 held-out questions on 16 databases, 1,068 generations in total, all
completed before anything was scored. Two scorers were frozen before any answer
key existed and both are reported. No question-level tuning ever entered the
system.

## The three results a product decision should rest on

**1. Knowledge access is where the accuracy is.** C2 minus C1 is +12.0 points
under the official scorer (95% interval 5.6 to 18.7), with 37 questions flipping
to correct and 5 flipping away. That comparison holds the model, the scaffold,
and the retrieval budget fixed. The only change is that the agent can search the
definitions. The corrected scorer puts the same contrast at +9.4 points, so the
two disagree on size and not on direction.

**2. Our compiled model gave that gain back.** C3 minus C2 is −13.5 points. C4
minus C1 is −1.5 points with an interval spanning zero, so we cannot separate a
small governed loss from a small governed gain. Cost is not ambiguous. The governed
condition used 3.9 times C1's median tokens, 1.5 times its latency, and 2.3 times
its tool calls. The extra volume is almost entirely input, a median of 580.0k
tokens against 145.8k.

**3. The two systems fail differently, and the difference is a product
property.** The governed condition refuses or errors on 14.2% of scoreable
attempts against 33.7% and 38.2% for the direct baselines, so it answers far more
often. It is also wrong more often when it does answer: 77.2% of its attempts are
incorrect against 56.2% for the raw-schema baseline. A system that declines is
inconvenient. A system that returns a plausible wrong number with no marker on it
is worse than inconvenient, and at equal accuracy these are not the same product.

## Why the model had nothing to compile

We ran every one of the 1,090 public definitions through a compiler built to
refuse to guess. Each definition got exactly one disposition:

| Disposition | Definitions | Share |
| --- | ---: | ---: |
| Compiled into an executable object | 193 | 17.7% |
| Kept as searchable context only | 193 | 17.7% |
| Deferred because it crosses an unresolved grain | 511 | 46.9% |
| Unsupported inputs | 193 | 17.7% |

The three reasons recorded most often for deferral were unknown cardinality,
unspecified aggregation, and missing cross-grain identity. Those are contracts
the import path has no way to express today, so a definition that depends on any
of them cannot become an executable object without the compiler inventing
something.

The refusal to invent was deliberate and we would keep it. A compiler that
guesses a join path to raise its coverage number ships a model that looks
governed and quietly returns wrong answers, which is a worse product failure than
a low coverage number. The problem is that the low coverage number was invisible.
Nothing in the deployment path told us the model we were about to publish had no
joins and no measures. We found out from a query-path audit after the held-out
run was already scored.

The semantic layer was not inert. On 109 of 135 attempts the product resolved at
least one of our compiled field definitions, and on 39 it expanded a
knowledge-base-backed derived definition into the executed SQL. It worked as a
vocabulary rather than a query builder, because we had not given it the structure
to build with.

## What to build, in order

The first item blocks measurement of everything else. The second is what would
give a planner something to compile. The rest are independent of both and cheaper
than either, so they can run in parallel.

### 1. A total typed result contract for rewritten SQL

**What a user hits.** A governed job runs, produces a query, and the result comes
back in a shape the caller cannot consume. From outside, this is indistinguishable
from the query having failed.

**Evidence.** Thirty-one of the 34 governed non-answers in our development
baseline shared an `UNKNOWN` selected-field type. Later, our relationship
experiment preserved 14 generated semantic queries that we could not capture at
all because their result types were unsupported. Those 14 are the direct cause of
that experiment being recorded as inconclusive.

**What to change.** When the agent authors the SQL, nothing currently specifies
what the planner guarantees about the type of an output column the model never
declared. Give unknown, boolean, temporal, and null values a stable
representation, separate selected fields from dependency fields in the plan
summary, and surface an unsupported output type as a visible job outcome rather
than an exception at the adapter. Right now an unsupported type consumes a
governed attempt and leaves no way to tell whether the governed query itself
succeeded.

### 2. Complete machine-readable results

**What a user hits.** A preview comes back where a result was expected, with
presentation-control records mixed into the data rows.

**Evidence.** All five of our strict concurrency-canary captures failed on this
before we wrote narrow adapter corrections.

**What to change.** Return the complete result or a stable paginated or
content-addressed handle to it, and keep preview metadata out of the data rows. A
truncated preview is a display artifact, and accepting one as an analytical
result is how a downstream system silently computes on partial data.

### 3. Grain and relationship authoring, with a predeployment coverage report

**What a user hits.** They import their business definitions, the import
succeeds, and the resulting model cannot answer questions that need a join or an
aggregate. Nothing in the flow told them that would happen.

**Evidence.** 511 of 1,090 definitions deferred across an unresolved grain. The
public schemas of these 16 databases hold 1,049 foreign keys that pass a
conservative cardinality contract, and the bounded model we could build from them
exposed 91 relationships. That gap was not visible anywhere until the query-path
audit.

**What to change.** Two things. Make grain, identity, cardinality, and
aggregation first-class contracts an author can state, so a definition that
depends on one of them has somewhere to put it. Then add a dry-run coverage
report that lists, before deployment, which definitions compiled, which are
carried as context only, which were deferred, and why, along with which
relationships were accepted, deferred, or are unreachable. That turns a silent
coverage problem into a decision the author gets to make.

Sequence this after the result contract. We tried the relationship half on its
own, and the result-capture gap is what made it unscoreable.

The C5 arm described below is the direct test of this item. It publishes 1,049
foreign keys as joins and the complete knowledge base as context, so its
query-path readout will show whether relationship coverage alone moves a governed
agent off the rewrite path, or whether the grain and aggregation contracts have
to arrive with it.

### 4. Deployment identity and diagnostics

**What a user hits.** A schema refresh fails and the error does not say what to
fix.

**Evidence.** A selected-database mismatch broke all 17 of our non-canary
connections, and it became actionable only after we diagnosed it externally.
Model publishing separately exposed a gap between logical and physical model
identity, and a readback path that canonicalizes SQL so an author cannot verify
byte-for-byte what was deployed.

The C5 deployment added two more, both reproducible. Views whose table names
carry CamelCase are renamed on creation, which failed 21 views on the first pass.
And on the database with the largest view surface, the product regenerated our
entire view layer from the physical schema after our upload landed: reading the
branch back showed 58 of 118 documents differing, every view and no topic, with
the views carrying schema-generated content instead of ours. Uploading a second
time did not fix it. Two passes hit the same failure on the same database, so
this is deterministic, not a race. From an author's side it looks like a
successful publish that silently is not what they wrote.

**What to change.** Validate database access at save time, return a structured
refresh failure that names the mismatch, and expose stable logical and physical
model identities with a canonical export contract.

### 5. Run provenance and outcome telemetry

**What a user hits.** A run finishes and they cannot tell which model revision
produced it, what it cost, or why it declined.

**Evidence.** Completed AI jobs already expose useful provider token buckets,
timings, tool and query activity, and phase events, which is why three of our
four conditions have full telemetry. Raw AI jobs expose no dollar cost, no
immutable model revision, and no structured refusal reason. Cost coverage in our
run is 267 of 267 attempts for the direct conditions and 0 of 267 for the
governed one, which is why the governed refusal rate is reported as unavailable
rather than estimated.

**What to change.** Echo the immutable model and branch revision on every job,
along with retries and validation attempts. Expose raw-job cost where the
provider reports it. Add a typed refusal outcome that separates a content
refusal, an explicit statement that the schema is insufficient, an exhausted
budget, and an infrastructure failure. Those four imply four different product
responses and currently arrive as one terminal state.

### 6. Bounded, query-directed retrieval

**What a user hits.** The agent spends its budget reading schema and never gets
to the query.

**Evidence.** The very first direct-SQL attempt in this study pulled all 51
tables of a database into context and exhausted its budget before writing a line
of SQL. The tool call was semantically valid, and it ended the run. The same
slice exposed a second problem: a safety filter rejected canonical foreign-key
values as suspected secrets.

**What to change.** Make schema and semantic search query-directed and bounded,
put per-call context volume in telemetry so the budget burn is visible, and give
public provenance identifiers a type so a safety filter can tell a foreign key
from a credential.

## What we got wrong on our side

Two of these are ours, not yours, and they change how the C4 result should be
read.

**We applied the no-guess rule to relationships, where it did not belong.** The
compiler refuses to invent semantics, and for a definition that depends on an
unresolved grain, an unspecified aggregation, or a missing cross-grain identity
that refusal is correct and we would keep it. A foreign key is not in that
category. It is a declared contract in the public schema, so publishing it as a
join invents nothing and costs nothing in provenance. We applied one rule to both
cases and shipped a model with 91 relationships where the same public inputs
supported 1,049. C5 uses no input the mechanical baseline did not have; it just
stops treating a stated contract as a guess. Nothing prevented that in the
original build.

**We did not read your documentation against our deployment until after the
held-out run was scored.** The documented operating model is topics carrying
joins and measures, the knowledge corpus attached whole as `ai_context`, sample
queries as few-shot structure, and an eval-gated tuning loop. Our baseline
deployed join-free, measure-free topics with boilerplate `ai_context` and no
tuning loop, which inverts all four. That comparison needed no result to exist
and would have flagged the arm as non-idiomatic before we froze it.

Both of these are why we describe C4 as underspecified rather than as a fair test
of the governed path. We preregistered "governed" as a property of the endpoint,
and it is a property of the deployed model. That distinction is also the sharpest
product finding in this brief, because the product never surfaced which of the
two we had.

## What we are not claiming

- Nothing here is a verdict on Omni's planner. No governed query in this study
  was composed by the semantic layer, so semantic query composition went
  unmeasured.
- Nor is it a verdict on Omni deployed the way you would deploy it. Our model
  came from a compiler that refuses to guess, using public inputs only, and it
  published no joins and no measures.
- The frame covers 89 of 101 held-out questions on 16 of 18 databases, because
  the benchmark's own loader cannot populate the other two.
- The relationship experiment is inconclusive by our own rule, not a negative
  result. Its captured subset shows 11 correct of 117 against 9 of 117 for the
  matched governed baseline, and 19 unresolved captures leave the full-frame
  number anywhere between 8.1% and 22.1%.

## What C5 found

C5 is a governed condition built the way Omni's documentation prescribes rather
than the way our conservative compiler produced: a view for every table instead
of six to eleven, a join for every foreign key that passes the same cardinality
contract, the entire knowledge base carried into model, topic, and field
`ai_context`, and query-pattern guidance derived from schema structure alone. No
measures in this phase, because measures need grain resolution and that is a
second phase. Same public inputs, same custody rules, same two scorers,
development partition only.

It ran on a matched frame of 122 questions across 14 databases, built so that C1
through C5 are scored on identical questions, plus the full 136-attempt frame
against the frozen C4 baseline. Eight deployment passes are preserved; the last
verified all 16 databases with exact readback.

### Does the governed rung recover the knowledge benefit?

Partly. On the identical 136-attempt frame, C5 scores 18 of 136 (13.2%) against
C4's 9 of 136 (6.6%). On the 122-question intersection:

| Condition | Official | Sensitivity |
| --- | --- | --- |
| C1 raw schema | 9 / 122 (7.4%) | 9 / 121 (7.4%) |
| C2 raw HKB, direct SQL | 29 / 122 (23.8%) | 28 / 121 (23.1%) |
| C3 exported model, direct SQL | 16 / 122 (13.1%) | 14 / 121 (11.6%) |
| C4 mechanical governed | 5 / 122 (4.1%) | 6 / 121 (5.0%) |
| C5 docs-idiomatic governed | 13 / 122 (10.7%) | 12 / 121 (9.9%) |

C5 is the first governed condition to clear the raw-schema floor; C4 sat below
it. About 45% of the distance from C4 to C2 closes. It is also cheaper: median
total tokens fall from 583,188 to 396,884, median tool calls from 7 to 3, median
database queries from 2 to 1, and median latency from 50.6 to 32.5 seconds. A
governed deployment built to your own documentation is both more accurate and
less expensive than the sparse one, by a wide margin.

### Do declared joins change the query path?

They did not change it on a single query.

C5 published a view for every table and a join for every qualifying foreign key,
and 134 of 134 parseable C5 attempts still carried `rewriteSql` with
agent-authored SQL. Zero declared a join through the semantic model. Across all
six governed arms we have measured, including three sealed C4 repetitions and
E02, the count is 661 of 661 on the rewrite path and zero composed. The audit
artifact is `experiments/analysis/governed-query-path-tally-v1.json`, regenerable
from `governed_query_path_tally.py`.

That result is the reason PF-016 exists and sits at the top of the ledger. The
accuracy gain is real and it came from the semantic model serving as better
context for hand-written SQL, not from composition. A customer in the same
position sees the same thing we saw: better answers, governed branding, and no
signal anywhere that the semantic layer was bypassed on every single query.

### What to build next

Relationship coverage is not the binding constraint, which the full join graph
settles. That moves phase 2 measures up: publish measures, resolve grain, and
check whether a declared join path ever appears. If the rewrite rate stays at
100% with measures present, the fallback is unconditional and item 2 (make
composition observable and enforceable) becomes the highest-value fix in the
list. If it drops, the 46.9% grain-deferral rate is the constraint and items 1
and 3 carry the weight.

# We gave an AI agent a semantic layer. The prose version won.

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

*An independent evaluation of Omni on LiveSQLBench Large-v1. Full method and
artifacts: [`RESULTS.md`](../RESULTS.md) and the protocol paper source at
[`manuscript/main.tex`](../manuscript/main.tex), which
[`manuscript/build.sh`](../manuscript/build.sh) renders.*

A semantic layer is a bet. You write your business definitions once, in governed
objects a query engine compiles, instead of letting a language model reinvent
them every time someone asks a question. The bet is that this makes the answers
more accurate.

We tested that bet. Making business definitions available to the agent helped a
lot, worth 12 percentage points of accuracy. Compiling those same definitions
into a governed semantic model and routing queries through the product gave back
the entire gain, and cost about four times as many tokens to do it.

The run records show something the score cannot. The governed system never used
the semantic layer to build a query. We inspected 661 governed queries across six
separate deployments, and every one carried a hand-written SQL rewrite while none
declared a join through the model.

Our first explanation was that the model we deployed did not contain enough
structure for it to do anything else. So we built one that did. C5 deploys the
same public knowledge the way the product's documentation says to deploy it, with
a view for every table and a join for every qualifying foreign key, roughly six
times the model. Accuracy went up. The rewrite rate stayed at 100%.

So the fallback is not a coverage problem, or at least not only one. Whether the
agent has a compiled path available and whether it takes that path are two
different things, and this post ends on the second.

## Why this is hard to measure

When people compare "agent with a semantic layer" against "agent without one",
they change three things at the same time.

1. **Access.** Does the agent have the business knowledge at all? Nobody can
   answer a question about "active high-value accounts" from column names. If the
   definition is missing, no architecture rescues it.
2. **Representation.** Is that knowledge a paragraph of English the model reads,
   or a structured object with declared grain, dependencies, and join paths?
3. **Enforcement.** Can the agent ignore the model and write whatever SQL it
   wants, or must it compile its intent through the governed layer?

A single before-and-after comparison moves all three at once, so it cannot tell
you which one did the work. That matters commercially, because the three cost
wildly different amounts to adopt. Writing definitions down is cheap. Modeling
them properly is expensive. Enforcing the model changes how your whole analytics
stack works.

So we built a four-rung ladder, where each rung changes exactly one thing.

- **C1.** The agent gets the raw database schema and writes SQL.
- **C2.** Same agent, same tooling, plus a search tool over the benchmark's raw
  business-knowledge base. Only *access* changed.
- **C3.** Same agent again, but the search tool now returns the compiled semantic
  model instead of the raw knowledge. Only *representation* changed.
- **C4.** Omni's production system, asked the question directly.

## The benchmark, and why we picked it

LiveSQLBench Large-v1 ships 18 PostgreSQL databases with 971 tables and 17,749
columns. What makes it unusual is that it also ships the thing a semantic layer
is supposed to hold: a hierarchical knowledge base of 1,090 business definitions,
connected by 945 declared dependency edges. Definitions build on other
definitions. Every database needs multi-hop resolution, and the longest chain is
six edges deep.

That structure is the whole reason we chose it. On a benchmark where every
definition stands alone, a prose blob and a dependency-aware model would look
identical. Here they can come apart.

We split the 332 eligible questions into 231 for development and 101 sealed. Then
we split development again, so that most tuning happened on one part and a
metered checkpoint partition stayed behind a signing boundary with a hard limit
of ten uses. We never used it. The final system got no question-level supervision
at all.

One thing went wrong before we ran anything, and it is worth naming because it
shapes every number below. The benchmark's official Linux loader silently skips
34 tables in one database and 37 in another, because the capitalization in those
archive filenames does not match what the loader asks for. The benchmark's own
reference SQL cannot run there. Twelve of our 101 sealed questions live on those
two databases. We cut them before generating a single sealed answer, before any
label was released, and before we could see any outcome. That leaves 89 held-out
questions on 16 databases, and it means our result describes those 16 databases
rather than the full benchmark.

## The rules we set before we looked

All 1,068 generations (89 questions, 4 conditions, 3 repetitions) finished before
anything was scored. No held-out outcome could reach a prompt, a retrieval
setting, or a retry policy, because none of them existed yet when the prompts
were frozen.

We froze two scorers before any answer key was released. One reproduces the
official evaluator exactly, including behavior we think is lossy, because that is
the number that compares to other work on this benchmark. The other fixes those
issues and is reported as a sensitivity check. We report both, everywhere,
because picking the flattering one after seeing results is how benchmark
reporting goes bad.

Every attempt records its own telemetry, and anything we could not observe is
recorded as null with a stated reason. It is never recorded as zero. That
distinction shows up in the results. We have dollar costs for three conditions
and not for the fourth, and we say so rather than printing a zero.

## The numbers

Mean one-shot execution accuracy across three repetitions, on 89 held-out
questions:

| Condition | What it has | Official scorer | Corrected scorer |
| --- | --- | ---: | ---: |
| C1 | Raw schema, writes own SQL | 10.1% | 10.1% |
| C2 | Raw schema + searchable business knowledge | **22.1%** | **19.5%** |
| C3 | Raw schema + searchable semantic model | 8.6% | 8.6% |
| C4 | Governed Omni | 8.6% | 9.7% |

And the paired differences under the official scorer, with 95% intervals from a
question-clustered bootstrap over 10,000 replicates:

| Contrast | Difference | 95% interval | Questions gained | Questions lost |
| --- | ---: | ---: | ---: | ---: |
| C2 − C1 | +12.0 | 5.6 to 18.7 | 37 | 5 |
| C3 − C2 | −13.5 | −20.6 to −7.1 | 4 | 40 |
| C4 − C1 | −1.5 | −7.1 to 4.1 | 10 | 14 |
| C4 − C3 | 0.0 | −4.9 to 4.9 | 10 | 10 |

Read the first row first. C2 minus C1 is the cleanest comparison in the study:
same model, same scaffold, same retrieval budget, same 89 questions. The only
difference is that C2 can search the business definitions. That is worth 12
points, and 37 questions flipped to correct against 5 that flipped away. The
corrected scorer puts the same contrast at +9.4 points (3.4 to 15.7), so the two
disagree on size and not on direction.

Then the gain evaporates. Taking the same knowledge, compiling it into our
semantic model, and exposing it through the same search interface cost 13.5
points. The governed product did not recover it. Its paired difference against the
plain raw-schema baseline is −1.5 points, with an interval wide enough that we
cannot distinguish a small loss from a small gain.

Cost is not wide at all. The governed condition used 3.9 times C1's median tokens,
1.5 times its latency, and 2.3 times its tool calls, and got no accuracy for it.
Almost all of the extra volume is input tokens, a median of 580.0k against 145.8k
for the direct baseline.

## The reliability result the accuracy column hides

The governed condition refused or errored on 14.2% of its scoreable attempts. The
direct baselines refused or errored on 33.7% and 38.2%. So the governed system
answers far more often. It also gets a much larger share of those answers wrong:
77.2% wrong, against 56.2% for the raw-schema baseline.

For an analyst, those are different failure modes with different consequences. A
system that declines is annoying and safe. A system that confidently returns a
wrong number is dangerous, because there is no marker on the output telling you
it is wrong. At equal accuracy, the two are not interchangeable products.

## The part we did not expect

Partway through, we ran a check on the governed condition's own query objects to
confirm that it was doing what "governed" implies: compiling queries from the
semantic model.

It was not. All 135 captured governed queries from the development baseline carry
`rewriteSql: true` with hand-written SQL in `userEditedSQL`. Zero of them declare
a join path. The field Omni would populate with a compiled query is null on every
attempt.

We checked whether our own setup had forced that path, and it had not. The test
scaffold posts three things to the product: a model identifier, the question
text, and a branch identifier. It exposes no mode flag, and a repository-wide
search confirms that no code of ours ever writes `rewriteSql`. The product chose
the rewrite path itself.

Then we found the reason, and it was our model rather than the product's agent.

## Why there was nothing to compile

Before touching any answer key, we transformed the public schema, column
meanings, and knowledge base into semantic artifacts. Every definition got
exactly one disposition, under a rule that refuses to guess:

| Disposition | Definitions | Share |
| --- | ---: | ---: |
| Compiled into an executable object | 193 | 17.7% |
| Kept as searchable context only | 193 | 17.7% |
| Deferred because it crosses an unresolved grain | 511 | 46.9% |
| Unsupported inputs | 193 | 17.7% |

Fewer than one definition in five became something a query engine can execute.
Almost half were deferred because they cross a grain that the public inputs never
pin down. The three most common recorded reasons were unknown cardinality,
unspecified aggregation, and missing cross-grain identity.

Those two findings connect through a step that accuracy alone would never have
surfaced. Because the compiler deferred all of those definitions, the deployed
model published no joins and no measures. So when
a question needed to touch two tables, or needed a sum, there was no compiled path
for the planner to take. Writing raw SQL was the only route left. The semantic
layer still did real work as a vocabulary. On 109 of 135 attempts the product
resolved at least one of our compiled field definitions, and on 39 it expanded a
knowledge-base-backed derived definition into the executed query. It resolved
names without building the query.

That has a consequence for the study, and the paper states it in the body rather
than a footnote. C4 minus C3 does not measure enforcement. It compares two
conditions that both had an agent writing SQL, differing in which agent, which
dialect, which surface, and which execution contract. No amount of model-parity
work would fix that, because in neither arm did a semantic layer resolve a join.

That refusal to guess was deliberate, and we would make it again. A compiler that
invents a join path to raise its coverage number produces a model that looks
governed and silently returns wrong answers. The negative result reads narrowly,
though. A conservatively compiled model, built from these public inputs and
deployed with no joins and no measures, did not reproduce the benefit that the
same knowledge gave as searchable prose.

## What we tried, and what happened to it

We preregistered four intervention families before running any of them, in an
append-only ledger where a hypothesis has to be written down before the code
changes and a failed experiment cannot be edited out afterward.

The interesting one was E02: declare relationships backed by foreign keys, which
is precisely the ingredient whose absence forced the rewrite path. Of 1,228 public
foreign keys, 1,049 passed the conservative cardinality contract, and the model
gained 91 relationships across 16 databases.

E02 then failed its own coverage rule. Its single 136-question run captured no
scoreable outcome on 19 of them: 14 saved queries that our capture path rejected
because the result types were unsupported, and 5 genuine transport failures that
saved nothing at all. Our rules require complete coverage before we score it, and
they forbid rerunning a question because we did not like what came back. So E02 is
recorded as inconclusive.

We did what we could without a rerun. Scoring the 117 answers we did capture gives
E02 11 correct against the frozen baseline's 9 on the identical questions, +1.7
points, from four gains and two regressions. Depending on how the 19 missing
outcomes resolve, the full-frame number lands anywhere between 8.1% and 22.1%.
That is not evidence that relationships help; it is a reason to run the
experiment properly once the result-capture contract is fixed.

We also have a process failure to report. We scored the held-out arm before E02's
development run finished, which reverses the order we had specified. The frozen
four-condition comparison is untouched, because every held-out generation was
complete before scoring and both scorers ran together. The cost falls entirely on
optimization. Now that we have seen held-out aggregates, they cannot drive any
further change, so this study reports no tuned result at all.

## What we think this means

Three claims we will stand behind:

- Giving an analytical agent searchable business definitions produced a large,
  reproducible accuracy gain on this benchmark. That is the strongest effect we
  measured, and it is the one comparison where everything else is held fixed.
- The governed product, deployed from a conservative public-only model, did not
  beat a plain SQL-writing agent, and cost roughly four times as much per attempt.
- The two systems fail differently. The governed one declines less and is wrong
  more.

Three claims we will not make:

- Nothing here measures semantic-layer query composition, because no governed
  query was composed by the semantic layer.
- The result is not a general verdict on Omni. We deployed a model built by a
  compiler that refuses to guess, so it published no joins and no measures. A
  model built the way the product's documentation prescribes is a different
  system.
- The frame covers 89 of 101 held-out questions on 16 of 18 databases, so it is
  not a full-benchmark number.

## The arm that tests our own explanation: C5

The four-condition study leaves one question open by construction. We measured a
governed deployment whose model had almost no structure in it, so on that
evidence alone we could not tell whether the governed rung fails as a design or
failed here as a deployment. C5 is the arm that separates those, and we ran it.

C5 is built by a second compiler from the same public inputs, deployed the way
Omni's own documentation prescribes rather than the way a refuse-to-guess
compiler produces. Six things change:

- A view for every public table, 47 to 63 per database, against the mechanical
  baseline's 6 to 11.
- A join for every foreign key that passes the same conservative cardinality
  contract, 1,049 of 1,228. The endpoint filters that bounded E02 relax on their
  own, because both ends of each key now have a published view.
- The whole knowledge base carried into model, topic, and field context instead
  of pruned, with dependency chains inlined prerequisite-first and formulas
  carried verbatim, inside the product's documented context budget.
- Field metadata only through channels the deployment API's readback contract
  confirms, so an unverified key cannot fail the deployment.
- Generic query-pattern guidance at model level for the fragile query shapes in
  our failure taxonomy, written from schema structure and from no question
  content.
- Still no measures. Measures need grain resolution, and that is a second phase
  we build only if this one earns it.

Everything that defends the number stays: public inputs only, both frozen
scorers, one generation, append-only records, no rerun because an answer was
wrong. The held-out frame is closed and stays closed, so C5 cannot make a
held-out claim no matter what it shows. It runs on the development partition,
against a matched frame of 122 questions across 14 databases where every
condition can be scored on identical questions.

### Getting it deployed has been its own finding

Eight passes, all preserved rather than tidied away, because each failure is a
property of writing a semantic model to this product. The first four are where
the product findings came from.

The first pass failed on 21 views whose CamelCase table names the product renames
on creation. The second reached 8 of 16 databases and then the process that owned
it exited, leaving half an arm deployed; the fix ties the remote identity to the
run's revision so a retry can never land on a populated branch. The third
verified 15 of 16 databases with exact readback and failed on the largest view
surface in the set, `planets_data_large`. When we read that branch back, 58 of
its 118 documents differed from what we uploaded: every view, no topic, and the
views carried Omni's own schema-generated content rather than ours. The product
had regenerated the view layer from the physical schema after our upload landed.

We changed the deployment to upload a second time when a branch does not
converge. The fourth pass carried that fix and hit the same failure on the same
database, so this is deterministic rather than a timing race. It took eight
passes in total. The final one verified all 16 databases with exact readback,
and the two launch failures that followed it turned out to be the harness
rejecting its own stale Python bytecode rather than anything about Omni.

### What C5 showed

One generation, 136 attempts, all terminal, scored under both frozen scorers.

On the identical 136-attempt frame, C5 scores 18 of 136 (13.2%) against the
frozen C4 baseline's 9 of 136 (6.6%); the sensitivity scorer gives 16 of 135
against 9 of 135. On the 122-question intersection where all five conditions
have a scoreable answer:

| Condition | Official | Sensitivity |
| --- | --- | --- |
| C1 raw schema | 9 / 122 (7.4%) | 9 / 121 (7.4%) |
| C2 raw HKB | 29 / 122 (23.8%) | 28 / 121 (23.1%) |
| C3 exported model | 16 / 122 (13.1%) | 14 / 121 (11.6%) |
| C4 mechanical governed | 5 / 122 (4.1%) | 6 / 121 (5.0%) |
| C5 docs-idiomatic governed | 13 / 122 (10.7%) | 12 / 121 (9.9%) |

C5 is the first governed condition to clear the raw-schema floor. C4 was below
it. C5 is also cheaper than C4 on every axis we measure: median total tokens
fall from 583,188 to 396,884, median tool calls from 7 to 3, median database
queries from 2 to 1, and median latency from 50.6 to 32.5 seconds.

The mechanism did not move at all. Across six governed arms, including this one,
661 of 661 parseable attempts carried `rewriteSql` and not one declared a join
through the semantic model. The C5 arm is 134 of 134. Publishing every table and
the full foreign-key join graph did not produce a single composed query.

We said a null result would not let us choose between the two readings. We
didn't have to choose: the query-path data decided it. C5's accuracy gain is
real and it is not composition. The semantic model made the agent's hand-written
SQL better by being better context, which is worth something and is not the
product premise. About a third of the C4-to-C2 gap closed: 8 of the 24 correct
answers separating them under the official scorer, 6 of 22 under the sensitivity
scorer. Two-thirds of it survives a model built to the product's own documented
shape, so compilation coverage does not explain the remainder either, even though
the pipeline captured only 193 of 1,090 definitions.

Phase two is the experiment that separates the last question: add measures,
resolve grain, and check whether a declared join path ever appears. If the
rewrite rate stays at 100% with measures published, the fallback is
unconditional.

Everything above is reproducible from the repository. The manifests, the split
seeds, both scorers, the experiment ledger, the contemporaneous research log
including the entries where things broke, and the aggregate artifacts with their
hashes are all public. Private answer keys and hidden annotations are not, and
never entered the development workspace.

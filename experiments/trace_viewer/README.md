# Matched dev-A condition explorer

One self-contained page over the 122 dev-A questions every condition was scored
on, so C1-C5 can be read per question rather than per aggregate.

```bash
python3 experiments/trace_viewer/build.py            # -> experiments/trace_viewer/index.html
python3 experiments/trace_viewer/build.py --body-only   # no <html> wrapper, for a hosted publish
```

The rows are inlined at build time; the page opens from disk with no server and
no network access. Rebuild it after any new scorer run.

## What the join is

No single artifact holds this frame. Correctness comes from three score runs,
one per arm group, and is read as written, never recomputed:

| Arm | Score artifact | Generation records |
| --- | --- | --- |
| C1, C2, C3 | `public-direct-baseline-dev-a-scores-v1` | `public-baseline-v1-direct-16db`, `…-continuation-1` |
| C4 | `c4-matched-122-scores-v1` | `public-c4-baseline-v8` |
| C5 | `c5-matched-122-scores-v1` | `c5-dev-a-v4` |

C5's records carry `condition: "C4"` and sit in a `c4/` directory, because the
condition scaffold is unchanged and only the semantic model differs; the run id
is the only discriminator. A score record names its generation by content hash
rather than by path, and a recovery pass can leave the same attempt id in more
than one directory, so the hash is what the join keys on.

`tests/test_trace_viewer.py` asserts the resulting per-condition counts equal
`experiments/analysis/c5-matched-122-comparison-v1.json` exactly. If that test
fails, the page is wrong, not the aggregate.

## What a detail panel shows

Per arm: the ordered trajectory from `attempt.trace.jsonl` (one line per model
turn, tool dispatch, or Omni job transition, with its duration, tokens, and
failure class), what the arm asked for from `attempt.action-evidence.json`
(retrieval queries, how many objects came back, and any exploratory SQL), the
query it finally submitted, and the rows that came back.

The trace records what an attempt did, not what it said: model turns carry token
counts and a metadata hash in place of prompt and completion text. The step
timeline is therefore the finest-grained view of an attempt this repository
holds. Action evidence exists only for the direct arms; a governed attempt hands
the question to Omni and has no retrieval step of its own.

## The per-arm rollup

Above the table, a rollup gives each arm's total and median spend, total wall
time, median latency, median input and output tokens, and correct count. It
recomputes under whatever filter is active, so a contrast chip narrows the
resource picture with the rows.

Total wall time is the sum of per-attempt latency over the frame. It measures
work done, not elapsed clock: attempts ran concurrently. A governed arm's dollar
column is daggered because it is an estimate, not a measurement, for the reason
below.

The same figures over the unfiltered frame are generated as a committed artifact
by `experiments/analysis/matched_122_cost_time_rollup.py` into
`matched-122-cost-time-rollup-v1.json`, which adds Tukey quartiles per arm. Quote
that artifact in reports rather than reading numbers off this page; RESULTS.md
section 5 explains how each column was measured.

## Two columns that are not what they look like

**Cost** is not comparable across arm groups. C1-C3 run through a provider that
bills and reports per attempt. Omni's job API exposes no cost, and
`omni_credit_cost.capture_with_cost`, which brackets Omni's AI credit counter
around each attempt, landed after every run in this frame, so no C4 or C5
attempt here carries a measured figure. The page falls back to the arm-level
estimate in `experiments/analysis/omni-credit-spend-breakdown-2026-08.json`:
the account's credit total for the billing period divided across the
Omni-routed attempts on disk. It is derived from a cumulative counter with no
per-job attribution, is the same number on every governed row, and is marked
`(arm estimate)` for that reason. Compare tokens and wall time across arms;
compare cost only within an arm group.

**Query** is a different artifact per arm group. C1-C3 submit SQL, held in
`generated_sql`. C4 and C5 submit an Omni query object, held in
`generated_query`; the page pretty-prints it. An empty query is not a missing
field, it is the failure, and the arm's `terminal_failure_class` names it.

## Contrast labels

The label on each row names why it is worth opening. `only_C2` is a question
only the direct agent with public knowledge got; `C5_recovers_C4` is one the
docs-idiomatic deployment got and the mechanical baseline did not;
`C5_loses_C4` is the reverse. `all_wrong_with_errors` separates the questions
where an arm produced a wrong answer from those where an arm never answered.

Scope: dev-A, exploratory, official frozen scorer in the cells with the
sensitivity scorer shown in the detail panel where the two disagree. No sealed
result, gold SQL, or hidden annotation is read or displayed.

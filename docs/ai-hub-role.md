# Omni AI Hub in the C4 workflow

AI Hub is a product-native diagnostic and rapid-iteration surface for governed
Omni (`C4`). It is not the benchmark judge. LiveSQLBench execution correctness,
custody, partitions, experiment decisions, regression accounting, and sealed
evaluation remain owned by the external benchmark infrastructure.

An AI Hub pass cannot promote a candidate by itself. A promising change must
still pass the external `dev-A` execution evaluation and regression checks; only
selected checkpoints consult `dev-B` under the existing guardian boundary.

## Preferred C4 loop

1. External `dev-A` results identify a recurring failure class.
2. Inspect representative governed-agent sessions in AI Hub.
3. Locate the suspected mechanism: semantic content, discoverability, retrieval,
   reasoning, compilation, validation, or another product behavior.
4. Record a hypothesis before changing the system.
5. Apply the smallest reusable change on an isolated branch.
6. When useful, compare the branch through a small AI Hub prompt set.
7. Run the external `dev-A` evaluation for promising candidates.
8. Keep, revert, or archive using external correctness plus regressions, safety,
   cost, latency, reliability, complexity, and generality.

AI Hub prompt sets are development aids, not mirrors of all 154 `dev-A`
questions. Each set records its failure-class purpose, prompt membership,
selection time, selection provenance, model ID, branch ID, run ID, and whether
prompts were chosen before or after inspecting failures. Expectations are judge
inputs only and may not become evaluated-agent runtime hints.

## First live canary inspection

Once the public-only canary model and database connection exist, one
representative C4 run will inventory what AI Hub exposes against the external
trace contract:

- conversation, job, model/tier, and branch identity;
- semantic objects/context available, selected, or retrieved;
- generated semantic query or SQL;
- compiler and validation behavior;
- retries, tool calls, database queries, tokens, cost, and timing;
- terminal agent error versus accuracy-judge failure;
- judge verdict, confidence, rationale, and conversation linkage.

Unavailable fields remain `null` in external telemetry and are named explicitly;
they are never inferred from reduced UI events. Product-native AI time is not
mislabeled as end-to-end wall-clock latency.

## Product-learning matrix

For each meaningful C4 failure class, record in
[`product-findings.md`](product-findings.md):

1. whether AI Hub makes the failure visible;
2. whether a user can identify why it failed;
3. whether relevant semantic context and tool behavior are exposed;
4. whether existing AI Hub/modeling workflows can correct it;
5. whether remediation requires external transformation or product engineering;
6. whether AI Hub Evals detect the change;
7. whether external execution correctness agrees.

Judge/execution disagreement is preserved, not reconciled away. It is evidence
about the product evaluation workflow—for example, a judge pass with a wrong
result set, a correct execution result with a judge failure, or a product
validator converting a likely wrong answer into an explicit refusal.

Structural surfaces outside AI Hub remain in scope: HKB dependency
transformation, semantic-object generation, grain, relationships, retrieval
architecture, compilation, validation, and harness behavior.

Current status: no authenticated AI Hub run or eval has been launched. Live
inspection waits for the canary connection and isolated public-only C4 branch.

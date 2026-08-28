# Dev-A-only autoresearch workflow

Status: control plane implemented before private dev-A labels are released.

This workflow extends, and does not replace, the preregistered
[evaluation protocol](../EVALUATION_PROTOCOL.md). The public-only baseline spans
the 231-question development partition. Adaptive work then uses 154 `dev-A`
questions; the 77 `dev-B` questions are a metered internal generalization gate.
The 101-question held-out partition remains outside development tooling and is
scored only after Freeze B.

## Existing-artifact audit

| Requirement | Existing artifact | Status before this integration |
| --- | --- | --- |
| Public eligible population | `data/manifests/eligible_questions.jsonl` plus provenance metadata | Satisfied |
| Deterministic 231/101 partition | `train_ids.txt`, `test_ids.txt`, split metadata, and regeneration tests | Satisfied |
| Deterministic 154/77 internal partition | `dev_a_ids.txt`, `dev_b_ids.txt`, allocation diagnostics, and regeneration tests | Added by this integration |
| Hidden-label custody | `sealed_tools/release_train.py` and `omni_benchmark.custody` | Satisfied for dev-A-only release and aggregate dev-B receipts; final evaluator remains future sealed work |
| Information tiers and runtime prohibition | `EVALUATION_PROTOCOL.md` and `config/preregistration.json` | Satisfied as protocol; this integration adds run-artifact enforcement |
| Four-condition matrix and three repetitions | Protocol and preregistration | Satisfied as design; condition harnesses remain to be implemented |
| Experiment summary ledger | `experiments/experiments.csv` | Partial: header existed, but no lifecycle, completeness, or append-only validation |
| Immutable public-only baseline | Protocol | Added as an unscored, content-hashed generation artifact |
| Proposal-before-change experiment lifecycle | None | Missing |
| Full-train acceptance gate | None | Missing |
| Stable checkpoints and stopping state | None | Missing |
| Train-only public development view | Full audit manifest contained both partitions | Missing |
| Question-specific-fix guard | Protocol only | Missing mechanical check |

The `omni_benchmark.autoresearch` control plane and
`config/autoresearch.json` address the operational gaps. They do not fabricate a
baseline or experiment: those records are created only after real runs exist.

## State and data boundaries

The committed eligible manifest remains the audit source for all 332 public
questions. Routine optimization receives a derived public view containing only
the 154 `dev-A` IDs. It never receives a `dev-B` or held-out outcome. A separate
guardian evaluates exact `dev-B` outputs and releases only a hash-bound aggregate
receipt. The guardian signs the exact receipt bytes with a private key held
outside agent scope. The checkpoint capability verifies the detached signature
against a separately recorded public-key SHA-256, rejects replayed receipt or
output hashes, and irreversibly increments the counter; ordinary proposal/
evaluation commands cannot accept `dev-B` IDs or per-question outcomes.

Training generation artifacts may contain generated SQL or a governed query,
latency, token/cost observations, non-secret tool failures, and
semantic-object identifiers used by the evaluated system. They may not contain
gold SQL, test cases, hidden `external_knowledge` IDs, expected results, or test
scores. Correctness is added in a separate immutable score artifact. The
validator rejects protected keys recursively, so nesting a hidden
field does not bypass the boundary.

The committed Freeze A configuration makes the score path and its expected
SHA-256 mandatory for every scored decision and checkpoint. The control plane
stores both component hashes plus a combined candidate hash, so a dev-B guardian
receipt cannot be rebound to a different generation or score artifact.

Offline diagnostic tooling may separately read the dev-A-only private release
under the custody contract. It may turn privileged annotations into aggregate
diagnostic conclusions such as `knowledge_present_but_inaccessible`; it must not
copy hidden IDs or content into runtime requests or ordinary run artifacts.

## Optimization cycle

Each iteration is a state transition, not an unstructured agent session:

1. **Observe.** Read the current complete `dev-A` run, rich traces, regression
   suite, and train-derived failure taxonomy. Recompute prevalence after
   accepted changes.
2. **Propose.** Append an experiment proposal before changing the system. State
   the affected class, mechanism, predicted direction, regression risk,
   subsystem, parent state, and why the intervention is reusable.
3. **Modify.** Change one mechanism with the smallest system-level patch that
   tests the hypothesis.
4. **Evaluate locally.** When useful, run the proposal's prespecified training
   slice. The slice is declared before results and is never selected from
   favorable outcomes.
5. **Evaluate globally.** A candidate can be `KEEP` only after an exact
   154-question `dev-A` run plus regression evidence. Compare question-level
   transitions, not just aggregate
   accuracy.
6. **Decide.** Append exactly one `KEEP`, `REVERT`, `INCONCLUSIVE`,
   `INVESTIGATE`, or `ARCHIVE` decision,
   including fixed/regressed questions, accuracy, cost, latency, failure-class,
   complexity, and production-relevance evidence.
7. **Checkpoint or continue.** Preserve content hashes, configuration, git
   revision, results, taxonomy, regression suite, Pareto set, and ledger head at
   stable states. Only selected candidates use a counted `dev-B` checkpoint.

The ordered objective is execution accuracy, reusable generality, low
regression rate, reasonable latency/cost, low complexity, and production
relevance. It is deliberately not collapsed into a weighted reward. A scalar
increase cannot authorize `KEEP` by itself.

For C4, AI Hub may accelerate the observe and local-evaluation steps through
product-native session inspection and small failure-class prompt sets. It cannot
authorize `KEEP`: external execution correctness remains authoritative, and a
promising AI Hub branch comparison must still pass the full `dev-A` and existing
regression gates. Prompt-set membership and selection provenance are recorded.
See [`ai-hub-role.md`](ai-hub-role.md).

## Optimization surfaces and search methods

The optimized artifact is the complete relevant system: HKB transformation,
semantic model and descriptions, retrieval, instructions, planning, compilation,
validation/retry, and harness code. Every proposal declares one surface:

- **Textual:** prompts, instructions, tool/semantic-object descriptions, aliases,
  and textual HKB representations. Generate several plausible candidates when
  the surface matters, compare them on the same prespecified slice, use traces
  and failure feedback, and retain strong alternatives. This borrows
  GEPA/MIPRO-style search principles without requiring a framework dependency.
- **Structural:** dependency resolution, model generation, relationship
  inference, context/retrieval algorithms, planning, compilation, validation,
  and fallback behavior. Use a mechanism-level hypothesis, the smallest code or
  system change, targeted tests, and full `dev-A` regression evaluation.
- **Human/research-controlled:** protocol, membership, custody, endpoints,
  scorer choice, legitimate-supervision rules, and scientific acceptability.
  Agents may identify a concern, but cannot autonomously change these surfaces or
  use observed scores to justify a change.

The escalation order is concrete mechanism, smallest reusable intervention,
targeted effect, global regression check, then architecture only after repeated
local approaches plateau. If one surface repeatedly produces no signal, switch
the search method or inspect another mechanism rather than generating indefinite
variants.

## Rich traces and regression control

Aggregate accuracy is insufficient input to the research agent. The normalized
attempt and private trace contract is specified in `harness-disclosure.md`. A
diagnostic trace may contain the public question, generation/scored outcomes,
actual-result hash,
failure category, public HKB nodes implicated by offline analysis, semantic
objects available and retrieved, generated query, compiler/validation/execution
behavior, and earlier experiments touching the mechanism. Hidden train gold and
`external_knowledge` IDs may be read by the offline diagnostic boundary but are
never copied into runtime context or the ordinary trace artifact.

When an accepted intervention fixes a reusable capability, add representative
`dev-A` IDs to the append-only regression suite with capability, rationale, and
source experiment. Promotion checks target effect, prior capability preservation,
global `dev-A` outcomes, generality, and cost/complexity. A recurring failure
tradeoff is accepted only when explicitly valuable and documented.

## Branching candidates and Pareto promotion

Experiments may descend from any preserved candidate, not only the most recent
accuracy leader. Parent lineage therefore forms an auditable branch graph.
Periodically evaluate the strongest branches on the same full `dev-A` run and
promote only a small number to `dev-B`.

Maintain a small non-dominated set across execution accuracy, wrong-answer rate,
refusal/error rate, regressions, cost, latency, stability, semantic-model
complexity, special-case count, and generality. No arbitrary weighted score
collapses these dimensions. Equal-accuracy candidates may both survive when one
is safer or cheaper. Each kept intervention declares scope:
`cross_database_general`, `database_family`, or
`database_specific_legitimate`. `question_specific` changes are prohibited;
`benchmark_specific` candidates may be archived as exploratory evidence but are
not promoted into the final system.

## Intervention selection and failure ownership

Prioritization uses the qualitative relationship
`prevalence x plausible fixability x generality`. A model or reviewer supplies
the semantic judgment and its evidence; application code only validates the
record structure and enforces custody policy. This preserves the repository's
zero-framework-cognition boundary instead of embedding keyword heuristics for
failure meaning.

The initial taxonomy is revised from training evidence. It should distinguish
HKB transformation and dependency failures, metrics, dimensions, aliases,
joins, time, filters, aggregation, Topic routing, retrieval, compilation,
validation, direct reasoning, formatting, and infrastructure where the evidence
supports those categories. For HKB-linked failures, offline diagnosis should
separate:

1. knowledge absent from the semantic model;
2. knowledge present but inaccessible;
3. knowledge retrieved but misinterpreted;
4. semantic representation correct but compilation failed;
5. compiled query correct but later validation or harness behavior failed;
6. model reasoning failed despite a correct, available representation.

Ownership is recorded as a hypothesis—model, semantic model, harness, Omni
product, environment, evaluator, or benchmark—and changes only with evidence.

## Anti-reward-hacking gates

The control plane rejects committed benchmark instance IDs in an intervention
description or patch. Code review remains responsible for broader semantic
forms of memorization that a deterministic guard cannot prove, including
near-verbatim question matching, answer templates, hidden-annotation-driven
retrieval, and database rules whose only rationale is one benchmark item.

Training-derived example queries are a named experimental family. Their
proposal records generation method, provenance, reusable pattern, and count.
They contain no question IDs or verbatim question-to-gold pairs, and material
use requires a with/without ablation before freeze.

## Checkpoints and stopping

`baseline`, numbered checkpoints, and `final-candidate` are immutable manifests.
The baseline points to the one-time public-only 231-question unscored output.
Adaptive checkpoints point to complete `dev-A` runs and a guardian-issued
signed `dev-B` aggregate receipt bound to the candidate output hash; they record
git/config/result/model, taxonomy, regression, Pareto, ledger hashes, and the
monotonic `dev-B` evaluation count. Per-question dev-B outcomes do not enter the
ordinary workspace. Existing files are never overwritten. A checkpoint creates
both a manifest and a numbered receipt-consumption marker. Commit that pair
before requesting another dev-B evaluation: the control plane cross-checks the
two histories and their committed bytes, so marker deletion, manifest deletion,
receipt replay, and local counter reset fail closed.

After four consecutive non-`KEEP` experiments, the loop must explicitly review
whether continued work is justified; this is a review trigger, not an automatic
acceptance or termination rule. Stopping requires an immutable reason record.
Once stopped, the development control plane rejects proposals, decisions,
regression additions, and checkpoints. Selecting
`final-candidate` triggers Freeze B: freeze C1–C4 together, commit the system,
record the freeze hash, terminate optimization, generate all
sealed outputs, and only then score them. Test results never reopen this loop.

## Reused and rejected autoresearch patterns

The workflow adopts useful conventions observed in the public
[`autoresearch-livesql-farm`](https://github.com/vivek100/autoresearch-livesql-farm)
implementation: versioned manifests, raw immutable run artifacts, explicit
parent lineage, validation before promotion, and recoverable append-only state.
It intentionally does not adopt benchmark-label-bearing run artifacts, silent
exception defaults, heuristic semantic root-cause classifiers, unconstrained
random experiment IDs, or acceptance based on a favorable subset. Those
patterns conflict with this evaluation's custody, auditability, and
generalization goals.

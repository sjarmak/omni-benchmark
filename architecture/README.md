# Architecture diagram (LikeC4)

Architecture-as-code model of `omni-benchmark`, rendered with
[LikeC4](https://likec4.dev). The model is the source of truth across
[`spec.c4`](spec.c4) (element kinds, tags, deployment node kinds),
[`model.c4`](model.c4) (the system), and [`views.c4`](views.c4) (structure,
walkthrough, and lens views), with the deployment model in
[`deployment.c4`](deployment.c4). The narrative companions are
[`README.md`](../README.md), [`docs/methodology.md`](../docs/methodology.md),
and the preregistration in
[`EVALUATION_PROTOCOL.md`](../EVALUATION_PROTOCOL.md).

The conceptual experiment is small: one public question set, five runtime
conditions, one sealed scoring boundary. Most of what this model shows exists
for a different reason. The benchmark ships hidden gold answers, so generation
and scoring have to be provably separated; agent runs are repeated, so
provenance has to be immutable enough that a retry cannot quietly rewrite the
evidence. Those two constraints are why there is a custody container at all, and
the model is laid out so a reviewer can see exactly where they bite.

Every element `link`s to its source (`src/…`, `config/…`, `docs/…`), so any box
in the explorer is one click from the code.

## Evidence state is tagged, not guessed

This is an evaluation repo, so the useful question about any box is not "is it
shipped" but **"can it still move without invalidating a result"**. Tags answer
that (legend in `spec.c4`):

| Tag | Meaning | Render |
|---|---|---|
| `#frozen` | preregistered or hash-pinned; changing it is a protocol deviation | blue |
| `#built` | implemented and exercised; free to change | default |
| `#evolving` | active work, contract still moving | amber |
| `#dormant` | ran to completion but produced no usable claim | **dashed, dimmed** |
| `#human` | human-controlled gate; agents may propose, never decide | indigo |
| `#custody` | sits on the hidden-data boundary; a leak here voids the result | **red** |

The frozen spine is the pinned release, the manifests and split, the condition
specs, the two scorers, and the Freeze A/B records. `#evolving` is C5 alone.
`#dormant` is E02, which completed but is formally inconclusive. `#custody` is
the six-element contamination surface plus the sealed boundary.

## Views

**Structure** — the static map:

| View | Scope |
|---|---|
| `index` | system landscape — the harness between the pinned benchmark, the two agent runtimes under comparison, and the shared PostgreSQL substrate |
| `benchmarkSystem` | the system decomposed into containers: prepare → compile → define conditions → generate → seal, with custody wrapping all of it |
| `conditionLadder` | the ablation itself — C1 → C5, each rung adding exactly one thing, with sealed results attached |
| `prepContainer` | pinned release to reproducible partitions |
| `compilerContainer` | public HKB to a deployed Omni model, and where 46.9% of it was deferred |
| `runtimeContainer` | how one attempt happens — two agent paths, one execution substrate |
| `custodyContainer` | what makes the evidence tamper-evident |
| `controlContainer` | what an agent may optimize against, and when |
| `sealedContainer` | the one-way boundary |
| `deployment` | where each piece runs, and which boundaries are trust boundaries |

**Walkthrough flows** (dynamic / numbered-step views):

| View | Flow |
|---|---|
| `splitFlow` | pinned release → eligibility → deterministic split → Freeze A, all before any condition exists |
| `directFlow` | one direct-SQL attempt (C1–C3): condition spec → pinned agent → bounded retrieval → read-only SQL → captured artifact |
| `governedFlow` | one governed Omni attempt (C4/C5), including the trace capture that reinterpreted the C4 result |
| `sealedFlow` | receipt → sealed generation → scoring inside the boundary → identity-free aggregates out |

**Lenses:**

| View | Scope |
|---|---|
| `custodyLens` | everything that touches hidden data, with the rest dimmed — the boxes any challenge to a result would be about |
| `openWork` | what is still moving: C5 in amber, the dormant E02 arm dashed |

### Running the walkthrough

For a review, present in this order: `index` → `benchmarkSystem` (orient on
structure) → `conditionLadder` (what was actually compared) → `splitFlow` →
`directFlow` → `governedFlow` → `sealedFlow` (what actually happens) →
`custodyLens` (why the result is defensible) → `openWork` (what is left). In
`npx likec4 start`, the dynamic views animate step by step.

## Viewing and regenerating

```bash
# Interactive, hot-reloading explorer (recommended)
npx likec4 start architecture

# Validate the model — the source of truth for correctness
npx likec4 validate architecture

# Re-export the static PNGs (needs a one-time browser download:
#   npx playwright install chromium-headless-shell)
npx likec4 export png architecture -o architecture/exports

# Check that every `link` still resolves to real code (drift guard)
node architecture/check-links.mjs

# Regenerate the three figures embedded in the repo README
npx likec4 export jpg architecture --flat \
  -f benchmarkSystem -f conditionLadder -f sealedFlow \
  -o architecture/figures
```

Two output directories, on purpose. `architecture/figures/` holds the three
JPEGs the repo README embeds; they are committed so the README renders without
depending on a published site, and they are regenerated with the command above
whenever the model changes. `architecture/exports/` is the full sixteen-view PNG
set and is gitignored; it, and the interactive explorer, are produced locally by
the commands above. A GitHub Pages workflow that publishes the explorer on any
push touching `architecture/**` is written but not enabled on this repository,
so the committed JPEGs are what the README renders from.

## Keeping the model honest

A diagram that drifts is worse than no diagram, so two things guard it:

- **`check-links.mjs`** fails loudly when an element points at a file that was
  moved, renamed, or deleted. That is how a model silently goes stale.
- **Numbers in descriptions are quoted from committed results**, not
  approximated: the sealed accuracies (C1 10.1%, C2 22.1%, C3 8.6%, C4 8.6%)
  come from [`RESULTS.md`](../RESULTS.md), and the 17.7% / 46.9% compilation
  figures from [`docs/hkb-semantic-baseline.md`](../docs/hkb-semantic-baseline.md).
  When a result changes, the model changes with it.

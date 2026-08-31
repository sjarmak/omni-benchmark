# arXiv submission notes

Upload the LaTeX source archive (`main.tex`, `abstract.tex`, `sections/`,
`materials.tex`, `references.tex`), not a compiled PDF. The bibliography is a
manual `thebibliography` block, so no `.bib` or `.bbl` is needed.

This paper now reports the executed four-condition held-out result. It was the
protocol half of the study until 2026-08-31; the reorganization around the
findings is described below.

The committed `main.pdf` was built on 2026-08-31 before the C5 section was
filled in, so it is behind `sections/c5.tex` and the four sections that
cross-reference it. No LaTeX toolchain is installed in this workspace and no
workflow builds the paper, so the rebuild is a manual step tracked by bead
`omni-benchmark-cze`. The source tree, not the PDF, is what gets uploaded.

## Where this sits in the deliverable set

1. **This paper.** The full record: design, custody, development trajectory, the
   held-out result, the query-path measurement, product implications, and
   limitations.
2. **[`RESULTS.md`](../RESULTS.md).** The repository's primary results report,
   with the complete artifact hashes and links into the evidence index. The paper
   and `RESULTS.md` must agree on every number; `RESULTS.md` is the source.
3. **The repository.** Manifests, experiment ledger, research log, trace
   aggregates, model-generation tooling, and scorer implementation.
4. **[`docs/blog-draft.md`](../docs/blog-draft.md)** and
   **[`docs/product-team-brief.md`](../docs/product-team-brief.md).**
   Plain-language versions for a general technical audience and for Omni's
   product team.

## Structure

The section order is introduction, related work, benchmark reconnaissance,
design and custody, conditions and telemetry, scorers, analysis plan, development
record, held-out results, the registered C5 successor condition, product
implications, limitations, standing of the record, materials. The old status
section was replaced rather than left in front of the results, and the
control-plane machinery was compressed to what a reader needs in order to trust
the result.

Section 10 is the C5 arm, and it now reports a result. The condition definition,
the prespecified comparison table, and the preserved deployment history are
followed by `tab:c5accuracy` (five conditions on the matched 122-question frame
under both frozen scorers) and `tab:c5mechanism` (query-path readout), plus
findings, mechanism, and interpretation paragraphs. Three cells still carry the
`\pending` macro: the compiled-dimension, derived-definition, and no-compiled-
field rows of `tab:c5mechanism`, because the analyzer that produces them
(`experiments/analysis/c4_mechanism_measurements.py`) is pinned to the frozen C4
score and recovery roots and has not been generalized to C5. The table caption
says so. `grep -rn 'pending' sections/` finds them.

## Paste-ready metadata

**Title**

    Does an Enforced Semantic Layer Improve Analytical Question Answering?
    A Preregistered Four-Condition Evaluation on LiveSQLBench Large-v1

**Authors**

    Stephanie Jarmak

**Abstract** (plain text, no LaTeX)

    A semantic layer rests on the premise that writing business definitions
    once, and compiling every query through them, makes analytical question
    answering more accurate than letting a competent agent write SQL against
    a raw schema. Evaluations of that premise typically change three things
    at once: whether the business knowledge is available at all, how it is
    represented, and whether its use is enforced. Changing them together
    makes attribution difficult. We report a preregistered four-condition
    evaluation of the Omni semantic layer on LiveSQLBench Large-v1, a
    benchmark whose 18 PostgreSQL databases (971 tables, 17,749 columns)
    ship a hierarchical knowledge base of 1,090 business definitions
    connected by 945 declared dependency edges, with multi-hop resolution
    required in every database. From the pinned public release we derived
    332 eligible Query tasks and split them deterministically into 231
    development and 101 sealed test questions. Before any sealed generation,
    label release, or outcome access, the held-out frame was narrowed to the
    89 questions on the 16 databases the official Linux loader can populate,
    and all four conditions were run three times over that identical
    membership, producing 1,068 generations that were all completed before
    any output was scored. Under the official-compatible Soft EX scorer,
    mean one-shot execution accuracy was 10.1% for raw-schema direct SQL,
    22.1% for direct SQL with a searchable raw knowledge base, 8.6% for
    direct SQL with a searchable exported semantic model, and 8.6% for the
    production-governed semantic-layer product; a corrected multiset
    comparator gave 10.1%, 19.5%, 8.6%, and 9.7%. The knowledge contrast is
    the one that moves: searchable business knowledge is worth +12.0 points
    over the raw-schema baseline (95% interval 5.6 to 18.7), while the
    governed system is -1.5 points against it (95% interval -7.1 to 4.1) at
    3.9 times the median token volume. Mechanism evidence explains the shape
    of that result rather than resolving it in the product's favor. Only
    17.7% of the 1,090 public definitions compiled into executable objects
    and 46.9% were deferred across an unresolved grain, so the deployed
    model published no joins and no measures; every governed development
    query then took the product's raw-SQL rewrite path, which means the
    executed comparison contrasts two agent-authored SQL conditions and does
    not isolate semantic query composition. We report both frozen scorers
    without post-result selection, an append-only development record in
    which one preregistered relationship-path experiment resolved
    inconclusive under its own coverage rule, a per-attempt telemetry
    contract in which unobservable quantities are null with a declared
    reason rather than zero, and the custody boundary that kept hidden gold
    out of the development workspace throughout.

**Comments**

    Preregistered evaluation; 1,068 held-out generations under two frozen
    scorers. 13 tables, 39 references.

**Categories**

    Primary:    cs.DB
    Cross-list: cs.AI, cs.CL, cs.SE

## Before submitting

- Compile with `./build.sh` (pinned TeX Live container, three passes).
- Confirm every number in the paper matches `RESULTS.md`.
- Confirm no per-question correctness, question identity, gold SQL, hidden
  annotation, or credential appears in the source archive.
- Confirm the C5 arm's numbers match `RESULTS.md` and that the three remaining
  `\pending` cells in `tab:c5mechanism` are still explained by the caption. If
  the compiled-bundle analyzer has since been generalized to C5, fill them.
  `grep -rn 'pending\|placeholder' sections/` finds every destination.
- Report-number, journal-ref, and DOI fields stay empty until a venue exists.

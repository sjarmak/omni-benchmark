# arXiv submission notes

Upload the LaTeX source archive (`main.tex`, `abstract.tex`, `sections/`,
`materials.tex`, `references.tex`), not a compiled PDF. The bibliography is a
manual `thebibliography` block, so no `.bib` or `.bbl` is needed.

This is the protocol half of the study. It reports no accuracy and no findings.

## Where this sits in the deliverable set

This paper is the methodological record, not the primary deliverable. The
artifact set is:

1. **Results report (6 to 10 pages).** The primary deliverable once runs exist:
   why the question, the design in roughly one page, the baseline, what failed,
   the experiment trajectory, the held-out result, the C1 through C4
   interpretation, product findings, and limitations.
2. **This protocol paper.** Supporting material and preregistration, linked or
   appended.
3. **The repository.** Manifests, experiment ledger, research log, trace
   aggregates, model-generation tooling, and scorer implementation.

When real runs exist, the results narrative takes precedence over this paper's
section structure. Do not append a Results section to this document and call it
the report. Reorganize around the findings, carry over the parts that earn their
place (the HKB reconnaissance, the failure mechanism ladder, the telemetry
design, the estimand and condition definitions), and compress the custody and
control-plane machinery to what a reader needs in order to trust the result.
Replace the status section rather than leaving it in front of the results.

## Paste-ready metadata

**Title**

    Does an Enforced Semantic Layer Improve Analytical Question Answering?
    A Preregistered Four-Condition Protocol on LiveSQLBench Large-v1

**Authors**

    Stephanie Jarmak

**Abstract** (plain text, no LaTeX)

    A semantic layer rests on the premise that writing business definitions
    once, and compiling every query through them, makes analytical question
    answering more accurate than letting a competent agent write SQL against
    a raw schema. Evaluations of that premise typically change three things
    at once: whether the business knowledge is available at all, how it is
    represented, and whether its use is enforced. Changing them together
    makes attribution difficult. This paper is the protocol half of such a
    test. It preregisters a four-condition evaluation of the Omni semantic
    layer on LiveSQLBench Large-v1, a benchmark whose 18 PostgreSQL
    databases (971 tables, 17,749 columns) ship with a hierarchical
    knowledge base of 1,090 business definitions connected by 945 declared
    dependency edges, with multi-hop resolution required in every database.
    From the pinned public release we derive 332 eligible Query tasks and
    split them deterministically into 231 development and 101 sealed test
    questions, then split development again into 154 development questions
    and 77 metered checkpoint questions with a hard maximum of ten checkpoint
    evaluations. The executed final candidate receives no question-level
    supervision and consumes no checkpoint. Four conditions are frozen together and run
    three times over the sealed questions, producing 1,212 generations that
    are all completed before any output is scored: raw schema with direct
    SQL, direct SQL with a searchable raw knowledge base, direct SQL with a
    searchable exported semantic model, and the production-governed
    semantic-layer product. The primary endpoints are the governed system's
    mean one-shot execution accuracy across three repetitions and its paired
    difference against the direct-SQL baseline, both with question-clustered
    uncertainty and no majority vote. We specify the custody boundary that
    keeps hidden gold out of the development workspace, the append-only
    control plane that can govern supervised development on the development
    partition, two independently versioned scorers (an official-compatible
    Soft EX that reproduces known lossy normalization, and a corrected
    multiset comparator reported as a prespecified sensitivity analysis),
    and a per-attempt telemetry contract in which unobservable quantities
    are recorded as null with a declared reason rather than as zero. We
    report no accuracy results. No sealed generation has been produced, no
    output has been scored, and the capture verification gate that precedes
    any scaled run has not yet been passed. What this paper contributes is
    the frozen design, the reconnaissance that motivated it, and an explicit
    account of the confounds that a semantic-layer comparison inherits from
    its harness.

**Comments**

    Preregistered protocol; reports design and reconnaissance only, no results.
    2 tables, 39 references.

**Categories**

    Primary:    cs.DB
    Cross-list: cs.AI, cs.CL, cs.SE

## Before submitting

- Compile with pdflatex twice (table of contents and cross-references).
- Confirm no result, accuracy, or finding language has entered any section.
- Confirm no private gold, hidden annotation, or credential appears in the
  source archive.
- Report-number, journal-ref, and DOI fields stay empty until a venue exists.

# Proposed amendment to EVALUATION_PROTOCOL.md: the C4 query path

> **ACCEPTED 2026-08-30 by Stephanie.** Both changes below were applied to
> `EVALUATION_PROTOCOL.md` exactly as written: the frozen-conditions table cell
> at line 212, and the addition after the C4-C3 interpretation bullets. Both
> original bullets survive verbatim; the amendment adds and qualifies, it does
> not rewrite. The protocol carried no Freeze-B hash binding (none of the 108
> frozen files is a markdown document) and is absent from the sealed runtime
> source paths, so the amendment does not disturb the live sealed arm. Recorded
> in [research-log.md](research-log.md) as D-181. This file is retained as the
> decision record.

Status: proposal awaiting human decision. Nothing in `EVALUATION_PROTOCOL.md` has
been edited. Prepared 2026-08-30 under the CLAUDE.md rule that split membership,
custody rules, scoring definitions, endpoints, and the protocol are
human-controlled surfaces: propose changes, do not make them.

Decision requested from Stephanie: accept, reject, or amend the replacement text
in §2 and §3. Rejecting is a coherent option, and §5 says what happens then.

Evidence: `docs/c4-query-path-disclosure.md`,
`docs/c4-mechanism-measurements.md` §2, `docs/c4-failure-attribution.md`. No gold
SQL, result value, question text, hidden annotation, dev-B record, or sealed
outcome was read to produce any of it.

---

## 1. The finding, stated once

Omni's production agent took the product's raw-SQL rewrite path on every C4
attempt. All 135 governed semantic queries in the frozen development baseline
carry `rewriteSql: true` and `aiGenerated: true` with hand-authored SQL in
`userEditedSQL`, and `join_via_map` is empty on all 135. No governed query
declares a join path.

The benchmark could not have selected that path. The submitted job body is
exactly `modelId`, `progressWebhookEnabled`, `prompt`, and `branchId`; the prompt
is the single token `{question}`; the product exposes no mode flag; and
`rewriteSql`, `userEditedSQL`, `join_via_map`, and `aiGenerated` appear nowhere
under `src/`. The agent's operative instructions are recorded as
`"managed_agent_instructions": "not_exposed_by_omni"`.

For cross-table questions there was also no other path available. The
conservative HKB compilation deferred 511 of 1,090 definitions (46.9%) as
cross-grain, so the deployed topics emit `"joins": {}` and publish no measures. A
query compiled from the declared model can neither traverse a join path nor
compile an aggregate from a declared measure.

The consequence for the protocol is that C4's enforcement value describes the
accessible surface and field-reference resolution, not query composition.

---

## 2. Proposed change 1: the frozen-conditions table

### Exact current text, `EVALUATION_PROTOCOL.md:212`

```
| C4 Governed Omni | Public schema and HKB | Omni semantic model | Enforced production harness |
```

### Exact proposed replacement

```
| C4 Governed Omni | Public schema and HKB | Omni semantic model | Enforced production harness (governs surface and field resolution; see `docs/c4-query-path-disclosure.md` for the measured query path) |
```

The knowledge and representation cells are unchanged and remain accurate. Only
the enforcement cell changes, and it changes from a claim about what the harness
enforces to a claim about what was measured, with a pointer to the measurement.

---

## 3. Proposed change 2: the C4-C3 interpretation bullets

The table cell alone leaves a second claim standing. The interpretation bullets
say that model parity is what stands between C4-C3 and an architectural contrast.
The measurement shows that parity is not sufficient, because the two arms no
longer differ on who composes the query.

### Exact current text, `EVALUATION_PROTOCOL.md:225-228`

```
- with model parity, C4-C3 is an approximate architectural contrast, subject to
  remaining system differences;
- without model parity, C4-C3 is only a production-system comparison and must not
  be called the causal effect of enforcement.
```

### Exact proposed replacement

```
- with model parity, C4-C3 is an approximate architectural contrast, subject to
  remaining system differences;
- without model parity, C4-C3 is only a production-system comparison and must not
  be called the causal effect of enforcement.

Measured on the frozen development baseline, C4's governed queries were composed
as SQL by the production agent through the product's rewrite path over a model
declaring no joins and no measures. C4-C3 therefore does not separate a compiled
query path from a direct-SQL one, and model parity does not restore that
separation. It separates two agent-authored SQL conditions differing in agent,
SQL dialect, accessible surface, and execution contract. See
`docs/c4-query-path-disclosure.md`.
```

This is an addition, not a rewrite: both existing bullets survive verbatim.

---

## 4. Why a frozen protocol should be amended rather than left with a deviation note

The deviation record exists. `docs/protocol-diff.md` carries a dated entry for
this finding, and `docs/harness-disclosure.md`, `docs/methodology.md`,
`RESULTS.md`, and `docs/report-draft-v2.md` all now state the measured query path.
The question is whether the protocol itself should also change. Four arguments
say yes.

**The falsified text is descriptive, not operative.** Freezing protects the
surfaces that could bias a result if they moved after outcomes were seen: split
membership, custody rules, scorer definitions, endpoints, the retry policy, the
statistical plan. The enforcement column of the conditions table drives none of
them. Amending it cannot change which questions are scored, how they are scored,
or which contrast is primary. This is the class of change where a freeze
protects nothing and costs accuracy.

**The claim is falsified rather than merely narrowed.** A deviation note is the
right instrument when the protocol's claim remains true and the execution
departed from it. Here the protocol's own description of the condition is wrong
about the mechanism the study exists to test. A reader who consults the frozen
protocol as the authoritative statement of the design will take away a claim the
evidence contradicts, and will find the correction only by also reading four
other documents.

**The protocol is the document a skeptical external reader reaches first.** It is
the preregistration. Leaving the strongest form of the falsified claim in the
preregistration, with the correction distributed across the report and the
disclosure surfaces, inverts the normal reliability ordering, where the
preregistration constrains the report rather than the report correcting the
preregistration.

**The amendment is auditable and directional.** It weakens a claim in the
project's own disfavor after the development outcomes were seen and before any
sealed outcome exists. There is no reading under which this edit improves the
study's apparent result. The Freeze A commit remains the historical record; this
is a prospective addendum in the same form as the AI Hub diagnostic boundary
already noted in `docs/harness-disclosure.md`.

The argument against is real and should be weighed. A frozen surface that is
edited once is easier to edit again, and the value of a preregistration comes
from its resistance to revision. That is why this proposal is narrow: two
descriptive passages, no operative surface, an addition rather than a
replacement in §3, and human sign-off rather than an agent edit.

---

## 5. If the amendment is rejected

No further action is required and nothing is left inconsistent by accident. The
protocol keeps its current text, `docs/protocol-diff.md` carries the dated
deviation, and every reader-facing document states the measured path. The cost of
rejection is that the preregistration's condition table remains the one surface
where the falsified claim stands unqualified, and readers who stop there will
carry it away.

A middle option exists: accept §2, which removes the strongest form of the claim
in a single cell, and reject §3, leaving the interpretation bullets to the
deviation record.

---

## 6. What this proposal does not touch

Split membership, custody rules, the dev-B guardian boundary, scorer definitions
and their pinned evaluator commits, endpoint definitions, the retry and rerun
policy, the statistical plan, the sealed frame, and the freeze commits. Nothing
here changes a recorded number, an artifact hash, or an authorization surface.
The sealed arm is hash-bound to the same C4 configuration and is unaffected
either way.

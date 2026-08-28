# Omni product findings

This append-only ledger records product observations from the evaluation. It
starts before model construction so regressions and dead ends are preserved in
the order encountered.

Each finding must include:

- finding ID and observation time;
- observed behavior and a minimal non-private example;
- expected and actual behavior;
- frequency, severity, and benchmark/workflow impact;
- suggested product change;
- evidence that the suggestion improves outcomes, if tested;
- experiment and git provenance.

Private SQL, hidden knowledge annotations, test-case bodies, credentials, and
customer data must not appear in this file.

## Current status

No Omni benchmark run has been completed, so there are no evidence-backed
product findings yet. Public benchmark structure and scorer quirks are research
inputs, not Omni product behavior. The first findings should come from the
public-only baseline and its rich traces. Condition-specific telemetry opacity
is a candidate observability finding, but it will not be entered as evidence
until the four public smoke attempts establish what Omni actually exposes.

## Entry template

### PF-XXX: Short finding title

- **Observed behavior:**
- **Minimal non-private reproduction:**
- **Expected behavior:**
- **Actual behavior:**
- **Why it matters to customers:**
- **Systematic evidence / frequency:**
- **Benchmark impact:**
- **Severity:**
- **Proposed product change:**
- **Was the change tested?:**
- **Measured effect:**
- **Experiment / commit provenance:**
- **Visible in AI Hub?:**
- **AI Hub exposes relevant context/behavior?:**
- **Fixable through current AI Hub/modeling workflow?:**
- **AI Hub Eval outcome:**
- **External execution outcome:**
- **Evaluator agreement/disagreement:**

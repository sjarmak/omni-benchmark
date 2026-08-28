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

## PF-001: Schema-refresh failures lack actionable diagnostics in the CLI/API

- **Observed behavior:** A newly created schema model reached terminal `FAILED`
  on two refresh attempts, while the job-status surface returned no failure
  reason.
- **Minimal non-private reproduction:** Create a schema model for an isolated
  read-only PostgreSQL benchmark connection; run one hard refresh and one
  public-schema soft refresh; poll the returned job IDs.
- **Expected behavior:** Terminal failure identifies whether the cause is
  authentication, network reachability, database permission, SQL/introspection,
  or an internal service error, with a safe remediation hint.
- **Actual behavior:** Both jobs exposed only type `refresh_schema` and status
  `FAILED`; subsequent shared-model creation could not use the schema model.
- **Why it matters to customers:** Operators cannot distinguish a product issue
  from an incorrectly configured least-privilege connection without leaving the
  normal modeling workflow or contacting support.
- **Systematic evidence / frequency:** 2/2 attempts on one isolated canary
  connection. This is an initial workflow finding, not yet evidence of broad
  prevalence.
- **Benchmark impact:** Blocks live C4 model upload and delays baseline execution;
  it does not affect any reported accuracy result.
- **Severity:** Medium workflow/observability issue pending root-cause isolation.
- **Proposed product change:** Return a sanitized structured error code, failing
  stage, and remediation guidance from the refresh job-status endpoint; link the
  same details from the model/AI Hub workflow.
- **Was the change tested?:** No product change is available to test.
- **Measured effect:** Not applicable; setup remains blocked on connectivity
  diagnosis.
- **Experiment / commit provenance:** Research decision D-027; public semantic
  bundle commit `4622f0f`; live setup bead `omni-benchmark-dih.12`.
- **Visible in AI Hub?:** Unknown; no usable live C4 model exists yet.
- **AI Hub exposes relevant context/behavior?:** Unknown.
- **Fixable through current AI Hub/modeling workflow?:** Unknown; likely outside
  AI Hub if the failure is connection- or refresh-layer related.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** Not run.
- **Evaluator agreement/disagreement:** Not applicable.

## Current status

No Omni benchmark question run has been completed. PF-001 is evidence about the
model-setup workflow, not agent correctness. Public benchmark structure and
scorer quirks remain research inputs rather than Omni product behavior. Findings
about answer generation should come from the public-only baseline and its rich
traces.

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

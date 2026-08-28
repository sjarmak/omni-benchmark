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

One public dev-A question has completed the unscored four-condition capture
gate. C1-C3 answered and executed; C4 ended in a typed result-contract error
because its exposed result was truncated. No correctness label or scored
baseline has been accessed, so these canaries establish observability and
execution mechanics rather than accuracy.

## PF-001 follow-up: Refresh failure was a selected-database permission mismatch

- **Observed behavior:** Read-only diagnosis established that the stored Omni
  connection selected PostgreSQL database `neondb`, while the benchmark reader
  was intentionally granted `CONNECT` only to `archeology_scan_large`.
- **Minimal non-private reproduction:** Configure a valid PostgreSQL host, role,
  and password but select a database for which the role lacks `CONNECT`; create
  or refresh the schema model and inspect the terminal job response.
- **Expected behavior:** Connection validation or schema refresh identifies the
  selected-database `CONNECT` denial and names the configuration field to fix.
- **Actual behavior:** Connection creation succeeded. Both refresh jobs exposed
  only `FAILED`; schema access returned 404 and raw query access returned 403.
  The underlying PostgreSQL denial was not exposed by the product surfaces used.
- **Why it matters to customers:** A nearly correct least-privilege connection
  is a common setup error. Without the selected-database error, an operator can
  spend substantial time investigating schema grants, network policy, model
  syntax, or service health instead of correcting one connection field.
- **Systematic evidence / frequency:** The wrong selected database was confirmed
  on the archeology canary. The same connection-creation pattern was used for
  the remaining benchmark databases, but those connections have not yet been
  audited for this mismatch; prevalence therefore remains unconfirmed.
- **Benchmark impact:** C4 upload/readback and live canary execution remain
  blocked until an explicitly approved connection correction and refresh.
- **Severity:** High setup-workflow impact; no effect on any accuracy result.
- **Proposed product change:** Validate database reachability and `CONNECT` at
  connection save time. Also propagate a sanitized PostgreSQL error category,
  failing database name, and remediation hint through refresh job status and the
  modeling/AI Hub UI.
- **Was the change tested?:** No product change was available. A read-only
  counterfactual check succeeded against `archeology_scan_large` with the same
  host and role.
- **Measured effect:** The correct target exposed PostgreSQL 18 in read-only
  mode with public-schema usage and exactly 51 base tables / 959 columns; the
  stored target denied database access. No Omni connection was mutated.
- **Experiment / commit provenance:** Bead `omni-benchmark-dih.14`; uncommitted
  read-only diagnosis on 2026-08-28; no benchmark-question or correctness run.
- **Visible in AI Hub?:** Not yet; schema generation never completed.
- **AI Hub exposes relevant context/behavior?:** No evidence that the database
  permission cause is visible before a usable model exists.
- **Fixable through current AI Hub/modeling workflow?:** No; the selected
  database belongs to connection configuration.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** Direct read-only database verification
  succeeded on the intended database; benchmark scoring was not run.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-001 validation: Correcting the selected database resolved the refresh

- **Observed behavior:** After changing only the connection's selected database
  from `neondb` to `archeology_scan_large`, the same least-privilege role and
  endpoint completed a public-only schema refresh.
- **Minimal non-private reproduction:** Keep host, port, role, grants, and
  connection ID fixed; correct the selected database; run one soft refresh
  restricted to `public`; read back schemas and views.
- **Expected behavior:** The corrected connection refreshes the one authorized
  public schema and exposes the same table population as the verified mirror.
- **Actual behavior:** Refresh job
  `8039ab6a-5a8d-4f80-9ae7-fddae67d4b7d` completed. Readback returned only
  `archeology_scan_large.public` and 51 views, matching the mirror's 51 public
  tables.
- **Why it matters to customers:** This counterfactual isolates the selected
  database as the cause. Actionable connection validation would have turned an
  opaque multi-hour setup investigation into a single-field correction.
- **Systematic evidence / frequency:** Confirmed on the archeology canary only;
  the other 17 connections were deliberately not changed.
- **Benchmark impact:** Clears the first C4 schema-model blocker. It does not
  contribute any benchmark accuracy result.
- **Severity:** High setup-workflow impact, now remediated for the canary.
- **Proposed product change:** Validate database `CONNECT` during connection
  save and return a sanitized failing-database error from refresh jobs.
- **Was the change tested?:** The configuration correction was tested; the
  proposed product diagnostics were not.
- **Measured effect:** Refresh changed from 2/2 opaque failures to one completed
  controlled refresh with 51/51 expected views.
- **Experiment / commit provenance:** Beads
  `omni-benchmark-dih.14` and `omni-benchmark-dih.14.1`; external action on
  2026-08-28; local documentation commit pending.
- **Visible in AI Hub?:** AI Hub inspection awaits the isolated semantic-model
  canary.
- **AI Hub exposes relevant context/behavior?:** Not applicable before a usable
  semantic model exists.
- **Fixable through current AI Hub/modeling workflow?:** No; the fix is in
  connection configuration.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** Schema refresh and model readback passed;
  benchmark question execution was not run.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-001 scale-out: The same selected-database error affected all 17 remaining connections

- **Observed behavior:** The first immutable 18-database deployment fan-out
  reached exact readback only for the corrected archeology canary. Read-only API
  inspection then showed that every other LiveSQLBench connection still selected
  `neondb` rather than its named benchmark database.
- **Minimal non-private reproduction:** List the safe `name`, `id`, `database`,
  and `includeSchemas` fields for the 18 isolated connections. Compare the
  corrected canary with the other records, then create and refresh an isolated
  schema model on one representative connection.
- **Expected behavior:** A connection created after successful read-only mirror
  verification selects the verified database, or connection validation rejects
  a target the role cannot access.
- **Actual behavior:** 17/17 non-canary records selected `neondb` with
  `includeSchemas=[public]`; the corrected canary selected
  `archeology_scan_large`. The representative schema-model refresh ended only
  `FAILED`, and a shared model could not be created.
- **Why it matters to customers:** A repeated single-field setup error can block
  an entire multi-connection rollout while appearing to be a schema, grant, or
  service problem.
- **Systematic evidence / frequency:** 17/17 non-canary benchmark connections;
  the earlier canary correction provides the positive counterfactual.
- **Benchmark impact:** Eleven otherwise authenticated bundles failed before a
  model ID. Six additional bundles were stopped by an independent local mapping
  preflight and therefore did not yet exercise their connections.
- **Severity:** High setup and rollout reliability impact; no accuracy result.
- **Proposed product change:** Validate selected-database access when saving a
  connection, expose the failing database in sanitized refresh status, and add a
  bulk connection health check before multi-model rollout.
- **Was the change tested?:** The archeology counterfactual was tested and fixed;
  the 17 scale-out records were inspected but deliberately not mutated in this
  deployment experiment.
- **Measured effect:** One corrected connection refreshed and supported exact
  14-file readback; 17 uncorrected connection records retained the same erroneous
  selected database.
- **Experiment / commit provenance:** D-047; Beads
  `omni-benchmark-dih.17` and `.17.1`; deployment source
  `5edb423d8eaa911cf8da467716ead287998acc30`.
- **Visible in AI Hub?:** No; schema-model setup failed before AI Hub could be a
  useful diagnostic surface.
- **AI Hub exposes relevant context/behavior?:** No evidence that it exposes this
  connection-layer cause.
- **Fixable through current AI Hub/modeling workflow?:** No; this is connection
  configuration and schema-refresh observability.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** No question was run or scored.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-002: Model upload can silently create a near-duplicate schema view

- **Observed behavior:** Uploading an extension with the flat artifact name
  `archeology_scan_large.public__pointcloud.view` succeeded, but created the new
  logical view `archeology_scan_large.public__pointcloud` instead of extending
  the schema-model view `archeology_scan_large_public__pointcloud`.
- **Minimal non-private reproduction:** On an isolated branch, upload a view
  extension whose filename encodes `catalog.schema__table.view` rather than the
  schema-model path `catalog.schema/table.view`; compare fully resolved view
  names and run model validation.
- **Expected behavior:** The upload surface either maps the obvious schema-view
  artifact to the existing view or warns that the file creates a near-duplicate
  logical view with the same catalog, schema, and table.
- **Actual behavior:** The API reported success. The distinction became visible
  only through fully resolved model readback; validation discussed SQL parsing,
  not the duplicate target identity.
- **Why it matters to customers:** A modeler can believe they governed an
  existing schema view while topics and queries continue to use a different
  unmodified view. This is especially difficult to spot in generated models.
- **Systematic evidence / frequency:** 7/7 uploaded canary view files used the
  wrong logical path before the deployment rule was corrected. This measures one
  compiler's repeated mistake, not general customer prevalence.
- **Benchmark impact:** The first semantic bundle could not be accepted as the
  public-only C4 baseline. No benchmark question was run against it.
- **Severity:** High model-correctness risk in automated upload workflows.
- **Proposed product change:** Warn when a new view file resolves to the same
  catalog/schema/table as an existing schema view but has a different logical
  name, and expose the resolved logical target in the upload response.
- **Was the change tested?:** The external product was not changed. Mapping the
  artifact to `archeology_scan_large.public/pointcloud.view` extended the
  intended base view and removed this class of validation ambiguity.
- **Measured effect:** The corrected pointcloud path resolved to
  `archeology_scan_large_public__pointcloud`; the seven duplicate files were
  removed from the isolated branch.
- **Experiment / commit provenance:** Research decision D-033; bead
  `omni-benchmark-dih.12`; public bundle source commit `4622f0f`; isolated branch
  canary on 2026-08-28.
- **Visible in AI Hub?:** Pending the authorized diagnostic inspection.
- **AI Hub exposes relevant context/behavior?:** Pending.
- **Fixable through current AI Hub/modeling workflow?:** Yes, by editing model
  filenames/paths; discoverability of the cause remains the product issue.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** Product-native validation/readback only; no
  benchmark scoring.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-003: Valid PostgreSQL JSON expressions require an opaque parser escape

- **Observed behavior:** Omni validation rejected valid PostgreSQL `->>` JSON
  extraction in modeled dimensions as `unparseable_sql`.
- **Minimal non-private reproduction:** Define a dimension as
  `CAST(${cloud_metrics} ->> 'Scan_Resol_Mm' AS DOUBLE PRECISION)` on a
  PostgreSQL JSON/structured column and validate the branch.
- **Expected behavior:** The dialect-aware model parser accepts SQL that the
  configured PostgreSQL database accepts, or identifies the unsupported
  construct and proposes the documented compatibility marker.
- **Actual behavior:** Validation rejected the extractor and every field that
  depended on it. Adding `-- DO NOT PARSE` only to the extractor made the entire
  pointcloud extension validate while leaving derived formulas parser-checked.
- **Why it matters to customers:** A valid, reusable semantic definition either
  appears broken or must opt out of parser validation, reducing compiler
  observability for exactly the semi-structured fields where validation is
  valuable.
- **Systematic evidence / frequency:** The initial branch reported 29 cascading
  expression errors across four executable view extensions. The narrow
  pointcloud test covered five JSON leaves and six dependent fields; after the
  parser marker, none of those eleven fields produced a validation issue.
- **Benchmark impact:** Blocks mechanical HKB-to-Omni compilation until the
  compiler records an explicit dialect-bypass decision. It has not affected an
  accuracy result.
- **Severity:** Medium modeling/compilation issue with a documented workaround.
- **Proposed product change:** Add PostgreSQL JSON operator support to the model
  SQL parser, or make the validator return a structured `dialect_parse_gap`
  suggestion that preserves validation of downstream expressions.
- **Was the change tested?:** The narrow compiler workaround was tested on the
  isolated pointcloud extension; a full regenerated-bundle validation is next.
- **Measured effect:** Pointcloud validation changed from eleven direct/cascaded
  errors to zero without disabling parsing for derived formulas.
- **Experiment / commit provenance:** Research decision D-033; bead
  `omni-benchmark-dih.12`; isolated branch canary on 2026-08-28; corrected local
  compiler commit pending.
- **Visible in AI Hub?:** Pending the authorized diagnostic inspection.
- **AI Hub exposes relevant context/behavior?:** Pending.
- **Fixable through current AI Hub/modeling workflow?:** Yes through YAML model
  editing, but the workaround weakens parser coverage for the marked field.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** Product-native validation only; no benchmark
  correctness judgment.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-004: Topic readback adds joins unless no-join intent is explicit

- **Observed behavior:** A topic with one base-view field selector but no
  `joins` property gained two inferred many-to-one joins on readback.
- **Minimal non-private reproduction:** Create a topic on the pointcloud schema
  view with `fields: [archeology_scan_large_public__pointcloud.*]`, omit
  `joins`, upload it, and read the extension YAML back.
- **Expected behavior:** A generated topic that selects only one view either
  remains single-view or clearly reports that model-default joins will be added.
- **Actual behavior:** Omni inserted joins to `personnel` and `projects` while
  model validation remained clean. Setting `joins: {}` suppressed both.
- **Why it matters to customers:** Implicit joins expand the semantic and AI
  search surface beyond the modeler's reviewed intent and can introduce
  unreviewed relationship/cardinality behavior.
- **Systematic evidence / frequency:** 1/1 topic inspected before the fix had
  inferred joins; 7/7 topics passed exact no-join readback after the compiler
  emitted an empty map.
- **Benchmark impact:** The public-only baseline would otherwise have contained
  relationship semantics not approved by the HKB transformation methodology.
- **Severity:** High semantic-governance risk for generated topics.
- **Proposed product change:** Expose inferred joins in the upload response and
  provide an explicit freeze-defaults/no-inferred-joins creation mode.
- **Was the change tested?:** Yes. The compiler now emits `joins: {}` for every
  deliberate single-view topic.
- **Measured effect:** Pointcloud topic readback changed from two inferred joins
  to zero; all 14 bundle artifacts then matched semantic readback and validation
  remained clean.
- **Experiment / commit provenance:** Research decisions D-034/D-035; commit
  `dc05b6b7ea61d256d54e4077a97884297ffa57a4`; bead
  `omni-benchmark-dih.12`.
- **Visible in AI Hub?:** The resulting agent query is visible, but the
  pre-fix implicit topic configuration was not surfaced in the inspected job.
- **AI Hub exposes relevant context/behavior?:** It exposes the selected topic
  and query fields, not why the topic contains a join.
- **Fixable through current AI Hub/modeling workflow?:** Yes through topic YAML;
  automated diagnosis remains weak.
- **AI Hub Eval outcome:** No judge run; one diagnostic job after the fix used
  only the intended base-view fields.
- **External execution outcome:** Governed query succeeded after the fix; no
  benchmark score was computed.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-005: CLI request schema and live query cache enums disagree

- **Observed behavior:** `omni query run --schema` advertised `disabled`,
  `normal`, `refresh`, and `refresh_all`; the live endpoint rejected `disabled`
  and required `Standard`, `SkipRequery`, `SkipCache`, or
  `SkipCacheAndRebuildExtracts`.
- **Minimal non-private reproduction:** Build a query body from the CLI's schema
  with `cache: disabled` and submit it to the same authenticated instance.
- **Expected behavior:** A request that validates against the installed CLI's
  generated schema is accepted by the endpoint, or version skew is identified
  before submission.
- **Actual behavior:** The endpoint returned HTTP 400 before query execution.
  Replacing the value with `SkipCache` succeeded.
- **Why it matters to customers:** Schema-driven integrations can fail at
  runtime even when they follow the product's own machine-readable contract.
- **Systematic evidence / frequency:** 1/1 canary request using the advertised
  value failed; 1/1 corrected request succeeded.
- **Benchmark impact:** No accuracy effect, but it would create false harness
  failures at scale if not caught by the canary.
- **Severity:** Medium API/CLI integration issue.
- **Proposed product change:** Generate CLI request schemas from the live API
  contract or enforce compatible version negotiation and contract tests.
- **Was the change tested?:** The integration workaround was tested; the
  product contract was not changed.
- **Measured effect:** Request outcome changed from pre-execution HTTP 400 to a
  successful two-row governed result.
- **Experiment / commit provenance:** D-035; Omni CLI 1.1.2; isolated archeology
  branch canary on 2026-08-28.
- **Visible in AI Hub?:** No; this occurred in the semantic-query API client.
- **AI Hub exposes relevant context/behavior?:** No.
- **Fixable through current AI Hub/modeling workflow?:** No.
- **AI Hub Eval outcome:** Not applicable.
- **External execution outcome:** The corrected request executed; no benchmark
  correctness judgment was made.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-006: Unformatted JSON results still stringify numeric measures

- **Observed behavior:** A semantic query with `resultType: json` and
  `formatResults: false` returned the count measure as strings (`"680"` and
  `"17"`) while preserving the boolean grouping field as booleans.
- **Minimal non-private reproduction:** Query
  `is_premium_quality_scan` and `count` through `pointcloud_semantics` with raw
  JSON output and formatting disabled.
- **Expected behavior:** Unformatted JSON preserves database/semantic primitive
  types, particularly numeric measures used for execution-result comparison.
- **Actual behavior:** Boolean values remained typed; the count became a string.
- **Why it matters to customers:** Downstream API clients and execution scorers
  cannot assume JSON primitive types reflect semantic field types, creating
  subtle equality and aggregation bugs.
- **Systematic evidence / frequency:** One query and one numeric measure so far;
  prevalence across numeric/date types remains to be measured before scale.
- **Benchmark impact:** The current C4 result adapter must not claim typed-number
  preservation or launch scaled scoring until predicted/gold normalization is
  demonstrably aligned.
- **Severity:** High for strict machine-to-machine result comparison; lower for
  human-facing presentation.
- **Proposed product change:** Preserve semantic types in unformatted JSON or
  return an explicit field-type schema alongside values and document coercion.
- **Was the change tested?:** No product fix exists. The finding is now a gate
  for C4 scorer-parity validation.
- **Measured effect:** Two numeric count cells were strings; two boolean cells
  were booleans.
- **Experiment / commit provenance:** D-035; isolated archeology semantic query
  on 2026-08-28.
- **Visible in AI Hub?:** AI Hub stores the executed query result as CSV, which
  does not resolve primitive-type preservation.
- **AI Hub exposes relevant context/behavior?:** It exposes field metadata and
  the generated query, but its CSV result is not a typed oracle.
- **Fixable through current AI Hub/modeling workflow?:** No.
- **AI Hub Eval outcome:** No judge run.
- **External execution outcome:** Query execution succeeded; no benchmark score
  was computed.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-007: AI Hub exposes rich run telemetry but not an immutable branch revision

- **Observed behavior:** The inspected AI job exposed model/provider token
  buckets, tool and query counts, tool errors, LLM/query/total durations, actions,
  generated semantic query, result status, row count, and truncation. The result
  did not echo an immutable branch/model-content revision; its query carried the
  shared model ID even though submission targeted an isolated branch.
- **Minimal non-private reproduction:** Submit a branch-scoped public prompt,
  retrieve the completed job result, and inspect `metrics`, `actions`, and the
  generated query identity.
- **Expected behavior:** A diagnostic run binds its trace to exact semantic
  model revision and branch alongside provider/model and execution metrics.
- **Actual behavior:** Bedrock `claude-opus-5`, token buckets, one tool call, one
  query, and detailed durations were visible. Cost, retry count, validation
  attempts, and immutable semantic revision were not.
- **Why it matters to customers:** AI Hub is genuinely useful for diagnosing
  performance and cost behavior, but branch comparisons and reproducible evals
  still require external request provenance.
- **Systematic evidence / frequency:** One branch-scoped diagnostic job.
- **Benchmark impact:** C4 telemetry coverage is better than the synthetic
  contract assumed, but the harness must retain submitted branch/revision identity
  and mark unobserved fields unavailable.
- **Severity:** Medium observability/reproducibility gap with strong existing
  diagnostic value.
- **Proposed product change:** Echo branch ID plus immutable semantic revision,
  model-stage routing, retries, validation attempts, and cost in the job result.
- **Was the change tested?:** No product change. The observed metrics will be
  integrated into the external trace contract.
- **Measured effect:** One job reported 7,233 ms total, 6,302 ms LLM, 352 ms
  query, one tool call, one query, zero tool errors, and provider/model token
  buckets; cost/retry/validation remained unavailable.
- **Experiment / commit provenance:** D-035; AI Hub job
  `49955018-a245-4fb6-ba81-668181c49e77`; response SHA-256
  `960cfbeba89022944bba2fcbd569a8948b521d4bc8c388d8fc1b92ab066b781d`.
- **Visible in AI Hub?:** Yes; this is a native AI Hub observation.
- **AI Hub exposes relevant context/behavior?:** Yes for selected topic, query,
  actions, token buckets, tool/query counts, and timings.
- **Fixable through current AI Hub/modeling workflow?:** The model can be
  improved there; missing run identity/telemetry requires product support.
- **AI Hub Eval outcome:** No judge run; diagnostic only.
- **External execution outcome:** The independently issued semantic query used
  the same fields and returned the same grouping shape; no correctness score.
- **Evaluator agreement/disagreement:** No correctness evaluator was invoked.

## PF-008: Governed AI jobs do not expose a structured refusal outcome

- **Observed behavior:** The pinned Omni AI job contract exposes terminal states
  `COMPLETE`, `FAILED`, and `CANCELLED`, but no distinct refusal state or typed
  refusal reason.
- **Minimal non-private reproduction:** Inspect the embedded job schema in the
  pinned Omni CLI and compare its terminal-state enum with a completed job that
  has no scoreable query action.
- **Expected behavior:** A governed agent run exposes `REFUSED` separately from
  product failure, cancellation, transport error, and result-contract failure.
- **Actual behavior:** External telemetry can classify the latter failures as
  errors, but cannot identify a genuine refusal without interpreting response
  prose. This benchmark deliberately does not use that heuristic.
- **Why it matters to customers:** Refusal and failure have different product and
  safety implications. Combining them makes it harder to tell whether governance
  safely declined a request or the system malfunctioned.
- **Systematic evidence / frequency:** Contract-level limitation in pinned CLI
  1.1.2; one completed-no-scoreable-result C4 attempt observed so far.
- **Benchmark impact:** C1-C3 can report separate refusal/error rates. C4 error
  rate is observable, while its refusal rate must be labeled unavailable until a
  structured signal exists.
- **Severity:** Medium observability and evaluation gap.
- **Proposed product change:** Add a stable typed terminal/action outcome for
  refusal plus a machine-readable reason category, independent of narrative text.
- **Was the change tested?:** The external harness was tested to preserve separate
  raw and summary buckets and to avoid treating unsupported states or prose as a
  refusal.
- **Measured effect:** No accuracy effect measured; the change prevents two
  operationally different non-answer classes from being silently conflated.
- **Experiment / commit provenance:** D-037; Bead
  `omni-benchmark-dih.5.4.4`; commit pending.
- **Visible in AI Hub?:** Narrative behavior may be visible, but the inspected
  machine-readable job contract lacks a stable refusal outcome.
- **AI Hub exposes relevant context/behavior?:** Partially; actions and terminal
  state are visible, but refusal is not structurally distinguishable.
- **Fixable through current AI Hub/modeling workflow?:** No; this requires product
  telemetry/API support.
- **AI Hub Eval outcome:** No judge run.
- **External execution outcome:** One C4 attempt was classified as a contract
  error due to truncation; no correctness score was computed.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-009: Missing grain contracts dominate public-only HKB translation

- **Observed behavior:** Across the 17 non-canary public HKBs, the conservative
  compiler materialized 179 of 1,036 definitions and retained 183 as context;
  491 were deferred cross-grain and 183 were unsupported.
- **Minimal non-private reproduction:** Run the committed public schema, mapping,
  and bundle publishers for any database under
  `semantic_models/public_baseline/`, then inspect mapping disposition and loss
  counts in its manifest.
- **Expected behavior:** A reusable HKB-to-semantic-model workflow compiles
  definitions whose grain and inputs are explicit, while explaining which
  additional contracts are required for unsafe definitions.
- **Actual behavior:** Row-local scalar definitions frequently compiled. The
  leading loss codes were `cardinality_unknown` (398),
  `aggregation_unspecified` (314), and `cross_grain_no_identity` (308).
- **Why it matters to customers:** Business definitions often span entities and
  grains. Without explicit contracts, automated modeling must either preserve
  them only as prose or guess joins and aggregations that governance is supposed
  to control.
- **Systematic evidence / frequency:** 1,036 definitions across 17/17 non-canary
  databases; the earlier archeology canary showed the same qualitative pattern.
- **Benchmark impact:** Only 17.3% of these definitions entered the executable
  public baseline. This is transformation coverage evidence; no answer accuracy
  or failure prevalence is claimed before scored runs.
- **Severity:** High semantic-model automation and authoring constraint.
- **Proposed product change:** Add explicit metric grain, entity identity,
  relationship/cardinality, and aggregation contracts, and expose a compiler
  dry run that identifies the missing contract for each unmaterialized
  definition.
- **Was the change tested?:** The conservative no-guess transformation and its
  explanations were tested; the proposed product capability was not.
- **Measured effect:** 179 compiled, 183 context-only, 491 deferred cross-grain,
  and 183 unsupported. All artifacts regenerate byte-for-byte.
- **Experiment / commit provenance:** D-043; Bead `omni-benchmark-786`; commits
  `d3f84f6ea5d15b247e3d1ffba739cd220289e72a` and
  `dcdd1a08a3d45a4a14978fe39f66542938fa5f32`.
- **Visible in AI Hub?:** Not yet tested across the fan-out; the evidence comes
  from the external transformation/compiler artifacts.
- **AI Hub exposes relevant context/behavior?:** To be measured after isolated
  bundles are deployed.
- **Fixable through current AI Hub/modeling workflow?:** Individual definitions
  may be modeled manually; reusable cross-grain compilation requires semantic
  model or compiler support outside prompt evaluation alone.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** Not run; this precedes the preserved public-only
  question baseline.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-010: Truncated governed results are observable but not execution-scorable

- **Observed behavior:** The governed C4 canary completed its product workflow
  and exposed model, token, tool, query, and latency telemetry, but marked its
  CSV result as truncated. The external adapter correctly rejected that result
  as `response_contract_error` rather than treating an incomplete table as an
  answer.
- **Minimal non-private reproduction:** Ask the isolated archeology benchmark
  branch the public `archeology_scan_3` question, retrieve the completed AI job,
  and inspect the result truncation flag before adapting rows for execution
  comparison.
- **Expected behavior:** A machine client can obtain the complete governed
  result set, or a stable handle for fetching it, even when the AI Hub preview
  is truncated.
- **Actual behavior:** The job retained one governed query and detailed trace
  telemetry, but the exposed result was incomplete and therefore unscoreable by
  either frozen execution scorer.
- **Why it matters to customers:** API clients, downstream automations, and
  external evaluators need complete results. A plausible partial table is more
  dangerous than an explicit error because it can silently produce incorrect
  analytical conclusions.
- **Systematic evidence / frequency:** One of one full C4 benchmark canaries;
  prevalence must be measured during public baseline generation.
- **Benchmark impact:** C4 capture verification passes, but execution scoring is
  blocked until the harness obtains the full governed result without changing
  the evaluated query path.
- **Severity:** High for execution-based evaluation and machine-to-machine use.
- **Proposed product change:** Return a content-addressed full-result handle or
  paginated result API from the AI job, with truncation applying only to the UI
  preview. Bind the handle to the exact semantic query/model revision.
- **Was the change tested?:** The external adapter's fail-closed behavior was
  tested. No product-side full-result capability has yet been verified.
- **Measured effect:** The attempt preserved 248,786 tokens, three tool calls,
  one governed database query, and 29.3 seconds of latency while correctly
  remaining an error rather than a confidently wrong partial answer.
- **Experiment / commit provenance:** D-037 and D-045 closeout; C4 system commit
  `dd8e7b1`; generation SHA-256
  `86814a6b5264cacc49d0ade910416b6521e4ab26f561819bfaa3701346914494`.
- **Visible in AI Hub?:** Yes; the job exposes the truncation flag and trace.
- **AI Hub exposes relevant context/behavior?:** It exposes the query and
  truncated result status, but not a complete scorer-ready result.
- **Fixable through current AI Hub/modeling workflow?:** No; this is a result
  delivery/API capability rather than semantic authoring.
- **AI Hub Eval outcome:** No judge run; external execution is authoritative.
- **External execution outcome:** Not scored because the result contract was
  incomplete.
- **Evaluator agreement/disagreement:** No disagreement was manufactured; the
  external evaluator refused to judge an incomplete result.

## PF-011: Physical table identity and semantic extension identity diverge

- **Observed behavior:** Six public-only bundles failed the exact deployment
  preflight even though their manifests were internally hashed. Five contained
  mixed-case physical PostgreSQL table names behind normalized lowercase Omni
  extension filenames; one used unqualified extension filenames.
- **Minimal non-private reproduction:** Build the committed deployment plan for
  `cross_border_large`, `cybermarket_pattern_large`,
  `labor_certification_applications_large`, `museum_artifact_large`,
  `polar_equipment_large`, or `residential_data_large` and compare each `.view`
  filename with its `catalog`, `schema`, and `table_name` identity.
- **Expected behavior:** Mechanical tooling can address the correct logical Omni
  view while independently preserving the exact case-sensitive physical table
  identity used for SQL compilation.
- **Actual behavior:** The canary-derived adapter treated normalized extension
  path identity and physical table identity as identical. It rejected 27
  mixed-case mismatches across five databases and six unqualified filenames in
  the sixth database.
- **Why it matters to customers:** Warehouses with quoted or mixed-case objects
  are common. Conflating physical and logical identity makes automated model
  publishing brittle and encourages unsafe name guessing.
- **Systematic evidence / frequency:** 6/18 mechanical bundles; 33 affected view
  artifacts split into two coherent classes.
- **Benchmark impact:** These bundles were correctly stopped before product
  mutation, but cannot enter C4 baseline generation until the general mapping
  rule is fixed and read back exactly.
- **Severity:** High for semantic-model automation; no measured accuracy effect.
- **Proposed product change:** Expose a stable schema-view identifier separately
  from physical catalog/schema/table identity in model export/import APIs, and
  validate extension targets against that identifier.
- **Was the change tested?:** The fail-closed preflight was tested. The corrected
  general mapping and live readback are tracked but not yet completed.
- **Measured effect:** One lowercase canary verified; six additional databases
  produced explicit blockers instead of near-duplicate or misbound model views.
- **Experiment / commit provenance:** D-047; Beads
  `omni-benchmark-dih.17` and `.17.2`; deployment source
  `5edb423d8eaa911cf8da467716ead287998acc30`.
- **Visible in AI Hub?:** No; the issue occurs before a valid branch exists.
- **AI Hub exposes relevant context/behavior?:** Not at this stage.
- **Fixable through current AI Hub/modeling workflow?:** Individual views could
  be repaired manually, but the reusable identity mapping belongs in model
  tooling or import/export contracts.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** No question was run or scored.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-001 scale-out validation: Exact database selection restored all 17 schema models

- **Observed behavior:** Changing only the selected database on each affected
  benchmark connection converted the representative opaque refresh failure into
  completed public-schema refreshes across the full 17-connection scale-out.
- **Minimal non-private reproduction:** Preserve each verified endpoint, role,
  credential, and `includeSchemas=[public]`; change `database` from `neondb` to
  the parity-verified named database; refresh and read back schemas/views.
- **Expected behavior:** Every corrected connection exposes exactly its one
  authorized public schema with the same table/view count as the scorer mirror.
- **Actual behavior:** All 17 refresh jobs completed. Each schema readback
  contained only `<database>.public`, and all 17 view counts exactly matched the
  committed parity inventory. The API returned HTTP 429 when more than five
  refresh jobs were started together; bounded later batches completed.
- **Why it matters to customers:** This closes the causal loop: valid mirrors
  and least-privilege grants were not the problem. A save-time connection check
  and actionable refresh error would have prevented a rollout-wide outage.
- **Systematic evidence / frequency:** 17/17 affected connections, following the
  independently corrected archeology canary (18/18 total usable schema models).
- **Benchmark impact:** Clears the connection prerequisite for isolated C4
  semantic deployment; no question was run or scored.
- **Severity:** High setup and rollout reliability impact, externally remediated.
- **Proposed product change:** Validate the selected database during connection
  save; return a sanitized failing stage/database from refresh status; document
  or signal the refresh concurrency/rate limit with retry guidance.
- **Was the change tested?:** The configuration correction was tested at full
  benchmark scale. The proposed product-side validation/diagnostics were not.
- **Measured effect:** Schema refresh changed from a representative `FAILED`
  with no reason to 17/17 `COMPLETED`, with exact public view-count parity.
- **Experiment / commit provenance:** D-049; Bead
  `omni-benchmark-dih.17.1`; secret-free receipt
  `experiments/deployments/connection-corrections-v1.json`.
- **Visible in AI Hub?:** The repaired models can now reach AI-facing workflows;
  the original connection failure cause was not visible there.
- **AI Hub exposes relevant context/behavior?:** Not for the pre-model connection
  cause observed here.
- **Fixable through current AI Hub/modeling workflow?:** No; selected database
  and schema refresh are connection/model infrastructure surfaces.
- **AI Hub Eval outcome:** Not run.
- **External execution outcome:** Schema and view readback passed; no benchmark
  correctness result was produced.
- **Evaluator agreement/disagreement:** Not applicable.

## PF-012: Model readback canonicalizes redundant physical-column SQL

- **Observed behavior:** After the compiler emitted exact public-column SQL for
  direct physical dimensions, Omni accepted and validated the models but
  omitted those redundant `sql` properties from extension readback.
- **Minimal non-private reproduction:** On the isolated cross-border branch,
  upload `proc_comp` with the exact identity binding `sql: '"procComp"'`.
  Validation returns no issues; extension readback retains the field metadata
  but omits `sql`.
- **Expected behavior:** Programmatic publishing has either byte-stable readback
  or a documented semantic canonicalization contract that distinguishes benign
  product normalization from changed model meaning.
- **Actual behavior:** Strict semantic readback rejected three validator-clean
  databases until the external verifier used compiler-attested public-schema
  identity provenance to recognize only this omission.
- **Why it matters to customers:** CI/CD and model-generation tools need to know
  whether a readback difference is harmless normalization, semantic drift, or a
  lost definition. Accepting arbitrary missing SQL would be unsafe.
- **Systematic evidence / frequency:** 3/18 databases in the exact-column v5
  run: cross-border, cybermarket, and labor certification. No authored,
  structured-leaf, or derived SQL difference was accepted.
- **Benchmark impact:** The narrow equivalence rule increased exact verified C4
  deployment coverage from 7/18 to 10/18 without changing the residual
  validator issue vector or any benchmark question behavior.
- **Severity:** Medium for model automation and provenance; high if strict
  readback is used as a deployment gate without a product canonical form.
- **Proposed product change:** Expose a content-addressed semantic revision or
  documented canonical model export. Include field provenance that distinguishes
  inferred physical identity from authored SQL and derived definitions.
- **Was the change tested?:** Yes. The external adapter accepts only an omitted
  SQL property attested by exact view, field, source-column stable ID, and
  identity SQL in the authenticated bundle manifest. Adversarial tests preserve
  rejection of derived and unattested alias SQL changes.
- **Measured effect:** Three databases moved from zero-validator readback failure
  to exact verified deployment; full tests reported 1,387 passed and five
  environment-gated skips.
- **Experiment / commit provenance:** D-052; runs
  `public-baseline-v5-20260828` and `public-baseline-v6-20260828`; source commit
  `7c669e521bba215101684d89e9ef78aabef5b855`.
- **Visible in AI Hub?:** The final model is usable by AI Hub, but the reason for
  the readback rewrite is not surfaced as a diagnostic event.
- **AI Hub exposes relevant context/behavior?:** It exposes the resulting model,
  not the import-time canonicalization provenance.
- **Fixable through current AI Hub/modeling workflow?:** No; this is an
  import/export and model-identity contract.
- **AI Hub Eval outcome:** Not run; no question was required to reproduce it.

## PF-013: Governed job previews mix data rows with presentation-control records

- **Observed behavior:** Three of five public C4 concurrency canaries returned a
  truncated CSV preview containing one-column `FIRST`, `SAMPLED ... FROM
  MIDDLE`, and `LAST` section labels between ordinary multi-column rows. Four of
  five also recorded timestamp-free `failure` actions before a later successful
  governed query.
- **Minimal non-private reproduction:** Run the five committed public C4 canary
  questions against the isolated verified branches and retrieve their completed
  AI job results. The behavior reproduced across archeology, cybermarket, and
  ETF truncated previews and across four databases' recovered failure histories.
- **Expected behavior:** Machine-facing results separate preview-control metadata
  from CSV data, and action records expose a stable common envelope or an
  explicit per-type schema.
- **Actual behavior:** Presentation labels are serialized as ragged CSV rows and
  product-native failure records omit the timestamp present on every other
  observed action type.
- **Why it matters to customers:** API consumers can misclassify a successfully
  completed governed query as a harness failure or accidentally ingest preview
  labels as business data.
- **Systematic evidence / frequency:** Truncation labels affected 3/5 canaries;
  timestamp-free failure actions affected 4/5. Together they caused 5/5 external
  capture failures before the adapter correction.
- **Benchmark impact:** The initial authenticated concurrency canary produced
  five `response_contract_error` outcomes despite 63 tool calls and 17 database
  queries. The narrow adapter correction parses all five preserved responses.
  A fresh five-question canary then captured three complete results and exposed
  two separate plan-schema differences rather than the original preview/action
  variants.
- **Severity:** High for machine-to-machine analytics and external evaluation.
- **Proposed product change:** Return preview section boundaries as structured
  metadata outside the CSV payload and give every action a stable timestamped
  envelope, including failure actions.
- **Was the change tested?:** Yes on the external adapter with RED/GREEN tests
  and all five preserved public responses; no product-side change was available.
- **Measured effect:** Preserved-response parse success changed from 0/5 to 5/5.
- **Experiment / commit provenance:** D-054; source commit `9526505`; runs
  `public-c4-concurrency-canary-v3-20260828-1425` and
  `public-c4-concurrency-canary-v4-20260828-1434`.
- **Visible in AI Hub?:** Partially. AI Hub exposes action history and truncated
  results, but the schema mismatch is clearest in the machine API response.
- **AI Hub exposes relevant context/behavior?:** It exposes the recovered query
  sequence, but not why a strict external parser rejected the response.
- **Fixable through current AI Hub/modeling workflow?:** No; this is an API
  response-contract issue rather than semantic-model authoring.
- **AI Hub Eval outcome:** Not run; external execution remains authoritative.
- **External execution outcome:** Three of five fresh attempts produced complete
  typed result artifacts; two reached governed JSON execution before failing a
  different plan-metadata contract.
- **Evaluator agreement/disagreement:** External capture distinguished the API
  representation issue from governed query completion; no correctness score was
  consulted.
- **External execution outcome:** Product validation and exact semantic readback
  passed for the ten-database frozen subset; question scoring remains separate.
- **Evaluator agreement/disagreement:** The product validator accepted all three
  models while the original external exact-readback gate rejected them. The
  attested canonicalizer reconciled the representations without treating the
  validator as the correctness authority.

## PF-014: Query-plan summaries conflate output and dependency field metadata

- **Observed behavior:** Two of five fresh C4 canary plans described more fields
  in `summary.fields` than the governed query selected. After treating the
  summary as a dependency superset, one result became type-faithfully captureable;
  the other selected field still reported `data_type: UNKNOWN`.
- **Minimal non-private reproduction:** Run the committed disaster-relief and ETF
  public canary questions. Compare the submitted query fields,
  `plan.query.model_job.fields`, `summary.fields`, and returned JSON columns.
- **Expected behavior:** The API identifies the selected output schema separately
  from helper/dependency metadata and supplies an authoritative executable type
  for every selected field.
- **Actual behavior:** Disaster selected three fields while the summary also
  described `damage_report`; ETF selected four while the summary also described
  `platform_tier`. ETF's selected `yield_to_expense_ratio` then reported
  `UNKNOWN`, although the JSON endpoint returned string values.
- **Why it matters to customers:** Machine clients need a type-faithful output
  contract. Treating every summary field as output rejects valid queries, while
  guessing an `UNKNOWN` type risks silently changing comparison and aggregation
  semantics.
- **Systematic evidence / frequency:** Extra helper metadata affected 2/5 fresh
  canary attempts. One of those two (1/5 overall) also had an unsupported selected
  result type.
- **Benchmark impact:** The narrow selected-field validation makes all 240
  disaster rows captureable. ETF is now classified as an explicit
  `unsupported_semantic_result_type` evaluated-system failure rather than a
  generic harness contract error; no correctness result was inspected.
- **Severity:** High for external execution scoring and governed-query API
  interoperability; medium for interactive users who consume rendered results.
- **Proposed product change:** Return explicit `selected_fields` and
  `dependency_fields` sections with canonical names, output order, and executable
  data types. Do not emit `UNKNOWN` for a field that the JSON execution endpoint
  can return.
- **Was the change tested?:** Yes. RED/GREEN tests require exact equality between
  submitted and planned selected fields, selected-field uniqueness and coverage,
  and exact output-column cardinality. Unknown types remain fail-closed.
- **Measured effect:** Preserved disaster replay changed from contract failure to
  a 240-row typed result. Preserved ETF replay changed from an undifferentiated
  contract error to a distinct unsupported-type outcome.
- **Experiment / commit provenance:** D-055; run
  `public-c4-concurrency-canary-v4-20260828-1434`; source commit pending review.
- **Visible in AI Hub?:** Partially. The governed query and result are visible,
  but the selected-versus-helper distinction and machine type-binding failure
  require API trace inspection.
- **AI Hub exposes relevant context/behavior?:** It exposes the semantic query and
  result presentation, but not a clear authoritative output-schema contract.
- **Fixable through current AI Hub/modeling workflow?:** The `UNKNOWN` type may
  originate in semantic modeling, but the ambiguous response contract itself is
  an API/compiler surface outside AI Hub evaluation.
- **AI Hub Eval outcome:** Not run; external execution capture remains the
  authority for this finding.
- **External execution outcome:** Preserved public response replay succeeded for
  disaster and produced the explicit unsupported-type classification for ETF.
- **Evaluator agreement/disagreement:** No evaluator correctness outcome was
  consulted; this finding concerns the product-to-harness result contract.

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

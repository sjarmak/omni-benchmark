# Human decision queue

This page is the concise operator view of work waiting on human authority.
Beads is the durable source of truth; this checked-in page explains the request
and its consequence in plain language. Run `bd human list` for the live queue.

Last updated: 2026-08-29T18:51:00-04:00 (America/New_York). Benchmark agents have
authorized access only to the extracted 154-record dev-A release. No agent has
accessed the complete gold package, dev-B annotations, test annotations, or
sealed-test results.

## Standing policy change — 2026-08-29

Live-action authorization is now tiered by contamination risk rather than by
whether an action touches a provider (`omni-benchmark-xeg`).

- **No decision needed from you:** public semantic deployment, validation, and
  exact-readback passes. Public schema only, isolated `livesqlbench-*` branches,
  no questions, gold, hidden annotations, dev-B, test data, or correctness.
  Retries run under a new run ID. Records stay append-only and every terminal
  result is preserved. Compiler generality is enforced by diff review.
- **Still one exact decision from you, per action:** anything producing evaluated
  answers (C1-C4 dispatch, sealed generation and scoring), consuming a dev-B
  checkpoint, reading or releasing protected data, or mutating a shared/main Omni
  model. Credentials, OAuth profiles, and leases remain operator-owned.

The optimization phase is also cut (`omni-benchmark-ivg`). E02 deployment
authority is no longer on the path and will not be requested. The deviation is
recorded in [protocol-diff.md](protocol-diff.md).

The corrected C4 control-plane frame is complete and fully tested: all 154
dev-A identities remain scheduled, exactly 136 answerable identities execute,
and the 18 fixed exclusions remain explicit. The public deployment prerequisite
is also complete: polar v12 validates with exact readback, so all 16 answerable
databases are ready. The next human action will be one exact C4 dispatch
authorization; its bound package is being prepared now.

The agent-autonomous v12 polar verification is complete and needs no response
from you. It returned zero validation issues and exact readback for all 20
public extension files. The general fix authenticates all three returned view
identity values before projecting them away; every other semantic difference
remains exact. No C4 action has launched.

## Waiting on you now — exact C4 v6 dispatch authorization

Reply **B** to hold. To choose **A**, run this exact two-line command on the
benchmark host:

```bash
cd /home/ds/projects/omni-benchmark
uv run python /home/ds/.omni-benchmark-approvals/authorize-public-c4-baseline-v6.py --authorize
```

The helper is mode `0600`, SHA-256
`7ab7b3b8a5ef55c21e31c6ad20b9a4fe25bb158e4237878d78c2fc4e44443e7b`,
and currently reports `ready_not_authorized_not_launched`. It creates a
one-hour receipt and records your response; it does **not** consume the receipt
or launch C4. After it prints JSON, paste that one JSON line here so the agent
can immediately validate and run the exact dispatch before expiry.

The package is `omni-benchmark-ei0.4.12`: system commit
`aab9eb512aeb021be42b1549a7634708d0c09fb8`, run
`public-c4-baseline-v6`, 154 scheduled / 136 executable / 18 fixed unscorable,
16 verified deployment targets, schedule SHA-256
`fa4675408574a610d495ed0fd99b4542eddf9f6f77127af1ce42f6207c7ec7ba`,
execution-plan SHA-256
`a83b0042170227b1294f5a354ccb71c9d066bc069d8120724c6a252cd38662dd`,
and deployment SHA-256
`6b65cf8e8d76d748f8438ecb62fcb379f302d0cb8bee68fe8864eba63cdb05c7`.
Concurrency is three; the wall bound is six hours; projected spend is
USD 98.948908, with a USD 7 per-attempt ceiling and USD 952 telemetry ceiling.

This authorizes one C4 generation dispatch only. It does not authorize a rerun,
scoring, Freeze B, sealed work, protected-data access, credentials/OAuth/leases,
or shared-model mutation.

## Most recent authorized action completed

### Exact 16-answerable v9 validation pass — `omni-benchmark-dih.17.12`

Your response **A** to `omni-benchmark-dih.17.12` was consumed exactly once. No
further operator action, command, profile, credential, callback URL, token,
config file, or lease path is needed now.

- **A** authorizes exactly one append-only deployment, product validation, and
  exact-readback pass for the 16 answerable corrected public-baseline bundles.
- **B** holds the request and permits no product contact or run claim.

The pushed request is
`experiments/public-baseline-v9-deployment-request.json` at exact request commit
`04cf67a6b5140bcdc59f678f5d88d2e15e7fa0c1`, request SHA-256
`d519acde72f8386a814981cfa06994bc5e0b5e07b5a5e2f1be645d97978b88cc`.
It binds source commit `f1923ceac636481220c019ce9e8399c28c839f7a`,
16 databases / 228 files, selected bundle-set SHA-256
`68fe84c5bc724bf345cfebf8b74bff2e70e8d64f52a5172bf84a8cac4941e6b5`,
full-18 bundle-set SHA-256
`8a5c9aae0d29c2ef7b7c768767aeaedc41f4f18f0f090035dc142478d5dfae66`,
run `public-baseline-v9-20260829`, absent output root
`experiments/deployments/public-baseline-v9`, four workers, and 1.25-second
global pacing. `mental_healths_large` and `organ_transplant_large` remain the
two fixed official-loader blockers and are explicitly excluded.

The one append-only pass completed without a retry. Fifteen databases validated
with exact readback. `polar_equipment_large` reached zero validator issues but
failed exact readback because `public/cabinenvironment.view` returned different
semantic content. All 16 terminal records plus the claim were preserved with
zero record-write failures; their canonical aggregate SHA-256 is
`2c906e48088793bc91107dc69aa647c48ca0f966dc3c03720a7912f74d4b3a77`.
The remaining general round-trip blocker is `omni-benchmark-dih.17.13`.

The completed authorization covered no C4 or E02 question dispatch, benchmark
question access, scoring/correctness, gold/hidden/dev-B/test access,
credential/OAuth/lease operation, shared/main model mutation, retry, or
deployment outside the exact 16-database set. That one-pass restriction is now
superseded by the Tier 1 policy above: a successor public-only validation pass
uses a new run ID and needs no human decision.

## Previous authorized action completed

### Exact seven-bundle v8 validation pass — `omni-benchmark-dih.17.11`

Your response **A** was recorded and consumed exactly once for the frozen v8
request. The append-only pass completed without a retry: cross-border,
fake-account, labor-certification, robot-fault, and sports-events validated with
exact readback; planets retained two validator issues; polar retained ten; and
record writes had zero failures. Its claim plus seven terminal records have
aggregate SHA-256
`bb375d7e74353836a61597638814fac27bdbb9424510d1459eb2fd65e9639190`.

Combined immutable v7 and v8 evidence leaves 14 of 18 total deployments
verified, or 14 of the 16 answerable databases under the fixed 154-scheduled /
136-answerable frame. Sports is resolved. General offline corrections for the
prior planets and polar blockers are fully gated at exact source commit
`aa1b82f39be705f1916823598fe65f7c47c8c57b` (1,891 passed, five expected
skips, 83.58% branch coverage). V9 subsequently resolved planets and reduced
polar to the distinct exact-readback blocker described above.

The completed authorization covered no retry, C4, E02, question dispatch,
scoring/correctness, protected labels, credentials/OAuth/leases, shared/main
models, or further live diagnostics. Any subsequent product contact requires a
new exact request.

## Decision completed — schedule 154, score 136 answerable dev-A questions

Your response **A** to `omni-benchmark-1u8` is recorded. All 154 dev-A
questions remain scheduled across all 18 databases; the exact 18 questions
assigned to `mental_healths_large` and `organ_transplant_large` are fixed
scorer-conformance exclusions, and C4 promotion uses all 136 answerable
questions. Scheduled, scoreable, and unscorable counts remain separate.

The response authorizes only the offline exclusion/frame update and an upstream
report draft. It does not authorize C4, database mutation, reruns, credentials,
OAuth/leases, dev-B, test release, sealed generation, or sealed scoring. The
refuted 71-table recovery remains prohibited.

## Decision completed — retain all 154 dev-A questions

Your response **B** to `omni-benchmark-wk0` is recorded and the decision bead is
closed. The preregistered promotion frame remains all 154 dev-A questions. The
prepared ten-database/85-question `public-c4-baseline-v5` package cannot satisfy
that frame and must not be authorized, rehearsed, or launched.

C4 remains blocked until `omni-benchmark-dih.17` records all 18 isolated
semantic deployments validated with exact readback. The proposed database
recovery in `omni-benchmark-39b` is withdrawn: it would break official
LiveSQLBench comparability. No inventory change, re-provisioning, or affected
C1-C3 rerun is authorized or needed.

The clean integration branch is pushed as `codex/mvp-sealed-integrated` at
`74915f3fec98468c8ac6951750a2e81fe585fb6e`. Its copy of this document records
the same decision. The two remaining offline numeric compiler blockers are now
implemented and the full repository gate passes 1,869 tests with five expected
skips and 83.56% branch coverage. Their remaining prerequisite is one
append-only all-18 deployment, validation, and exact-readback pass; the refuted
database recovery is no longer on that path. No live action is requested from
you yet.
Do not use any older v5 helper, receipt, launch command, or post-run command
shown in the historical record below.

## Historical record — superseded by decision B

### Coverage choice (completed) — `omni-benchmark-wk0`

Do **not** run the v5 authorization helper yet. No receipt or command is needed
for this decision. Reply with `A` or `B` in this chat:

- **A — fixed ten-database development frame.** Amend the intervention plan,
  before any C4 result exists, so promotion requires every dev-A question in
  the ten already deployed databases (85 questions). This matches the
  submission-ready-MVP priority and permits an earlier development signal, but
  it does not reduce the separate requirement for all 18 C4 deployments before
  the sealed run.
- **B — retain all 154 dev-A questions.** Keep the original full-dev-A rule and
  hold v5 until all 18 databases deploy. This preserves the stronger original
  frame but waits on compiler defects `omni-benchmark-dih.17.2` and
  `omni-benchmark-dih.17.3`.

This choice is required because the committed intervention plan makes C4 the
promotion condition for E01-E03, declares an intervention INCONCLUSIVE when it
cannot cover all 154 dev-A questions, and stops when full coverage is
unavailable. The prepared v5 arm covers ten databases and only 85 dev-A
questions. Choosing the frame after seeing a C4 result would be post-hoc, so v5
is blocked until you decide. The count uses only committed public split
membership and public database fields; no gold, hidden annotations, dev-B, or
test outcomes were read.

### Obsolete — exact public C4 baseline v5 dispatch — `omni-benchmark-aez.7.1`

Do not run the previously recorded v5 helper. Decision B permanently makes this
ten-target package insufficient for the retained promotion frame. Authorizing
it could spend a one-hour, single-dispatch receipt and up to USD 560 on an arm
that cannot satisfy the current promotion rule.

The mode-0600 runner remains
`/home/ds/.omni-benchmark-approvals/launch_public_c4_baseline_v5.py`, SHA-256
`ef673e9c9ecbe219ff9aef52e496ba44b4a260b99db0723e058428c9a1e3f3cc`.
Its provider-inert check reports
`waiting_for_human_receipt_not_launched`; receipt, output, and consumption
remain absent. Decision B keeps v5 obsolete; a different all-18 package can be
prepared only after the deployment and restore blockers are complete.
V4 is already spent and must not be retried. Its exact receipt was consumed,
then all three initial children exited before any answer because the launch
environment omitted `OMNI_BASE_URL`. V4 contains three private failure
sidecars, zero generation records, and zero correctness records. Local commit
`e439b183a26a5d722a3317a7f89c650c8205ddb6` quarantines it and adds a regression
that checks the required Omni environment before any future approval is
consumed. The full gate passes 1,454 tests with five expected skips and 84.34%
branch coverage. No OAuth validation, refresh, or credential mutation occurred.

### Historical v5 post-run plan — do not run

The following command documented the superseded v5 plan and must not be run. It
is retained only as historical provenance:

```bash
cd /tmp/omni-benchmark-c4-postrun && uv run python scripts/freeze_c4_baseline.py --workspace /tmp/omni-benchmark-c4-prerequisites-integrated --system-commit e439b183a26a5d722a3317a7f89c650c8205ddb6 --run-id public-c4-baseline-v5 --output-root experiments/autoresearch/raw/public-c4-baseline-v5 --destination experiments/autoresearch/state/public-c4-baseline-v5-freeze.json --expected-schedule-sha256 2b8108874603fe6a372b1cc137d642623f31b985ff1d9d2a25e368e522793190 --expected-execution-plan-sha256 2d03cd2357dba1fb8c00aa4716286bb6d2501538df0ea0a775d8f0249ed8b3b0 --expected-deployment-sha256 d805eb6869201f28f928a5774263062302b29a5d8786fc3c1c120cb27f19df80
```

The freezer requires the exact complete committed schedule and immutable
generation/run/result inventory, rejects extras and quarantined or scored
artifacts, and returns only counts plus the selection SHA-256. It neither
contacts Omni nor opens the train-only release. The agent will then substitute
that returned digest for `<selection-sha256-from-freeze-output>` and run:

```bash
cd /tmp/omni-benchmark-c4-postrun && uv run python scripts/score_dev_a_baseline.py --workspace /home/ds/projects/omni-benchmark --artifact-workspace /tmp/omni-benchmark-c4-prerequisites-integrated --freeze-a-commit 7d39ee107338da1ce10e2553a4290e64bfc2f892 --selection experiments/autoresearch/state/public-c4-baseline-v5-freeze.json --expected-selection-sha256 <selection-sha256-from-freeze-output> --expected-release-sha256 34794127f6f34f5214eedf652b86d870fb2c4e8f67d364bbd8d333897acf2c3d --expected-official-scoreable-questions 85 --expected-sensitivity-scoreable-questions 85 --output-root experiments/autoresearch/raw/public-c4-baseline-v5-dev-a-scores-v1
```

This keeps public C4 artifacts in their isolated worktree and the authorized
154-record dev-A release in its existing main custody workspace; neither is
copied. The scorer validates every C4 candidate before acquiring a database,
then reports both frozen scorers over the exact 85-question C4/dev-A
intersection. No further human response is needed for this post-run handoff.

### No response required — one clean final MVP lineage is ready

Clean local branch `codex/mvp-sealed-integrated` now ends at commit
`cbc69ecced83f6c15abf384c9ce94b01d5f8e27f`. It contains the current report,
the immutable 112+518 direct-baseline selection freezer and its exact committed
exclusion/refusal semantics, the integrated E02 candidate and execution gates,
the C4 freezer/scorer, Freeze-B controls, sealed generation and scoring custody,
aggregate report rendering, the v4 quarantine, and the pre-consumption Omni
environment guard. The full repository gate passes 1,843 tests with five
expected skips and 83.51% branch coverage; Ruff, formatting, and diff checks
pass. The direct-baseline freeze remains the already-created mode-0600 artifact
with SHA-256
`04c75eb40c6a8bbb59af07358733b59a10d9b28787443d622fae5f31887bd725`;
it was not regenerated.

This consolidation is offline readiness only. It does not authorize v5, E02,
Freeze B, sealed generation, test release, or scoring. No human action is
currently requested.

### No response required — E01 was already in the frozen baseline

The public-only audit under `omni-benchmark-ei0.4.3` found that E01's exact
same-grain dependency-composition mechanism predates the intervention plan and
is already active in the frozen baseline. All 254 bundle files regenerate
exactly across 18 databases; the baseline has 48 dependency-bearing compiled
elements and 70 executable same-grain dependency edges. E01 is therefore
recorded as `INCONCLUSIVE — ALREADY BASELINE`, not rerun or redefined. This is
an experiment-integrity issue, not a new human blocker. The later optimization
cut means work does not proceed to E02. No protected data or live system was
accessed.

### Superseded record — E02 was locally deployment-ready

The bounded E02 candidate is frozen in local commits `185dd25`, `fcb9715`, and
`f87eae4`. It derives only public PK/unique-backed many-to-one relationships,
keeps nullable-FK optionality explicit, and leaves all HKB metric dispositions
unchanged. It emits 91 relationships across 16 databases and 67 direct source
topics; 179 non-unique targets remain deferred. All 18 candidate bundles
publish and authenticate locally over 272 hash-bound files. The aggregate
candidate-set SHA-256 is
`16ee2a02f994d3f90234e24366fe6ddefd041b3b0d2a7e63c001b4803a0fe6da`.

No Omni request, credential action, deployment, or evaluation run occurred.
The previously planned deployment and full-dev-A experiment were cut by
`omni-benchmark-ivg`; there is no E02 action or authorization to perform.

### Superseded record — the full E02 execution path was prepared offline

Clean local branch `codex/e02-run-readiness` now contains the exact no-launch
E02 handoff. Commits `e206f3aee57514e805d8978453bd1e18bec32269` and
`dc6b49639a8038c93eabaa41308d3ce77f825828` reproduce the public 18-database
candidate from Git, require the completed public C4 freeze before planning, use
isolated E02 model/branch identities,
and requires one fresh receipt for deployment plus a second fresh receipt for
the exact 154-question C4 generation run. It also adds the distinct complete
E02 freezer/scorer path and an explicit aggregate-only 154-question gold-
conformance receipt while preserving the public C4 and sealed defaults.
The candidate-set SHA-256 is
`c08ee8c10e4b2c26a142da5f36971dbb19488a827febf0514f5876e75b3a6f61`.
The full repository gate passes 1,775 tests with five expected skips and 84.14%
branch coverage. No provider, credential, receipt, gold record, protected
label, or live artifact was accessed.

Do not authorize or run E02. The optimization phase is closed, so the prepared
path remains historical offline evidence and no authorization package will be
requested.

One later custody action is recorded rather than guessed: the prior 122 official
/ 121 sensitivity scoreable denominators describe the 140-question represented
direct arm, not automatically the complete 154-question E02 arm. Commit
`dc6b49639a8038c93eabaa41308d3ce77f825828` prepares an explicit command that applies the already frozen rule to
all 154 dev-A questions and publishes only a canonical private aggregate
receipt: hashes, scorer identities, counts, and closed failure-category totals;
it cannot publish IDs, SQL, rows, per-question status, or correctness. The E02
scorer authenticates that receipt and verifies its denominators before any
candidate execution. The real aggregate sweep has not run, and agents must not
inspect question-level gold or infer the missing 14 outcomes. No action is
requested from you now; its exact custody command will be added here before it
is executed.

### No response required tonight — sealed scoring is Freeze-B-bound

The offline final-evaluation gate is complete on local branch
`codex/sealed-readiness`. Commit
`a1df3c8b56ec90c0b6aad53b057b748084555a1f` requires one canonical Freeze B,
all twelve C1-C4/repetition run manifests, the exact ordered 1,212-attempt
schedule, and generation/run/record hashes to agree before the evaluator reads
gold or acquires a database. Commit
`5e5ea33776f7b9b67b5914cea5600d12b70b7080` adds the one-time recorder that
derives every final hash from exact Git objects. Commit
`43ad5500d6532c4d7223cf4e65be85f0f0e5f95d` adds the deterministic schedule
generator and makes the recorder reproduce the schedule byte-for-byte from the
committed test-ID manifest and human seed. It does not read question content or
labels, choose a seed, or print identities. Commit
`f513eb09929f40763912a7a67a86b63e1ad3899b` adds the post-freeze control gate:
the commit containing the Freeze-B record must be a direct non-merge child of
the frozen system and add only that one canonical file. This resolves the
manifest's Git self-reference without permitting a post-freeze system change.
Commits `a06f3040de23a3c3bd2046a12827cac9a9e40dd9`,
`2848cae5ba73b93e5507965e01151e5ae9e88205`, and
`1d17d412f99381be4d44ab54513cfacbd5b17267` add the remaining offline
generation path: exact no-execution planning from F/S and frozen public Git
objects, opaque plan-bound prepared attempts with atomic private reconciliation,
and schedule-ordered 101-attempt cohort finalization into twelve bound run
manifests. These layers do not dispatch, contact providers, score, or read gold.
Commits `000b4aa6d0156da6431168114bd5e235c309e2e4` and
`c1006dc0c8f6d6fba898609109065963cd1c8a1e` add the distinct sealed-production
receipt and synthetic-tested no-score dispatcher. Read-only preflight validates
the exact plan, policy, runtime-source set, public question hashes, staged state,
and human receipt before any write. Execution consumes once before constructing
an adapter, reserves the complete pending cost, enforces the wall/concurrency
limits and one in-flight attempt per database, resumes only under a fresh
receipt, and finalizes the twelve cohorts when all 1,212 attempts exist. The
synthetic end-to-end run completed all 1,212 fake attempts and 12 cohorts; no
real receipt was created or consumed and no provider was contacted. Concrete
C1-C3/C4 adapters and the dry-default production CLI remain unfinished, so this
is not production-launch-ready and creates no new human request.
Commit `02f96bec0154cb26143615077e5162050dd06591` now adds the dry-default
production command, canonical policy loading from the exact Freeze-B-recorded
Git object at `S`, and exact public-question loading from the frozen manifest.
Dry mode performs the full receipt-authenticated preflight but does not consume.
The explicit execute flag still fails closed before consumption because the
production dependency builder is not yet wired. Commits
`6ebfe12f2a6b7a8ad64bcf5e478b845d990fa331` and
`cbf6e5f256fd0dbcc684f5d1facbe1d15f964f13` now add the sealed C4 projection
adapter and a distinct test-only C1-C3 runtime/capture authority. The ordinary
development loaders remain unchanged and reject test; evaluated-system failures
can stage while benchmark-infrastructure failures cannot. Remaining offline
work is the exact frozen direct dependency factory, C4 probe-runner closure,
entry-point factory wiring, and final transitive runtime-source set. This
narrows the remaining work but does not create a production authorization
request.
Subsequent isolated commits `86c7cbf030df15a722e0946dc421cfad5f0cdc04`,
`a054d0b8fad9939ceb361e37dfe899741250de39`,
`63cf2799de0b3a36cccd4e9c39272c079b6bc95b`, and
`51d79918d469978aa1438736ec7a558fc5ba265c` complete that offline work. The
final entry point remains dry by default; explicit execution consumes a fresh
sealed receipt before loading exact runtime/deployment inputs or constructing
C1-C4 adapters. A strict frozen all-database C4 deployment gate and the full
69-file local runtime import closure are bound. The real production adapters
completed all 1,212 synthetic attempts and twelve cohorts. The current full
gate passes 1,730 tests with five expected skips and 84.45% branch coverage.
Bead `omni-benchmark-ei0.5` and all implementation children are closed.
No real receipt, provider, credential, test generation, protected outcome, or
score was accessed. This creates no new response request.
The combined branch also contains the current report and integrated E02
candidate; its earlier pre-factory checkpoint passed 1,703 tests with five
expected skips and 84.43% branch coverage.
No hidden data, live service, credentials, approval receipt, actual schedule
seed, final manifest, or test generation was accessed.

This does **not** create the actual Freeze B. After C4, the E02 experiment, and
final-candidate selection, a later exact human package must supply or approve
the schedule seed and actual final hashes before any sealed generation. Nothing
is needed from you for that tonight. The only current response request remains
the C4 v5 authorization above when you are awake and available.

### Standing local MVP authority — recorded 2026-08-29

The human authorized agents to proceed autonomously with routine, scoped local
implementation decisions and relevant local commits when they advance the
submission-ready MVP. Agents should prefer making progress, keep Beads and the
research log contemporaneous, and place genuine issues or required decisions
on this page instead of stopping on incidental process questions.

This standing authority does **not** relax the benchmark's custody or
human-controlled surfaces. It does not authorize a push; credential or lease
work; access to dev-B/test/protected labels or sealed correctness; changes to
splits, custody, scoring, endpoints, or protocol; receipt reuse; or a production
C4/sealed dispatch. Those actions retain their existing exact fresh-human gates.

No response is required for legacy authorization bead `omni-benchmark-1yu`.
The exact C4 and sealed production paths now enforce current one-time human
receipts before constructing live dispatchers. A 2026-08-29 audit found that
older direct-baseline and direct-canary CLI entry points do not yet share that
enforcement, so they remain prohibited and the broader bead stays open. That
deferred comparator hardening does not weaken or block the exact C4 v5 and
sealed gates used by the MVP.

### Exact public C4 baseline v3 dispatch — `omni-benchmark-ei0.4.2.3`

The human created the exact canonical receipt, SHA-256
`6f139bea9803a20d337bdb1ba1ee1325236c4b3953d181d75d5ed63b48136416`.
The gate consumed it before dispatcher construction. The sole authorized v3
run has stopped and no process remains. Do not run the authorization helper
again or start another dispatcher. The exact run bound:

- system commit `f1efd00ae49824b6eb13e6655157f83a022004f3`;
- run ID `public-c4-baseline-v3` and output root
  `experiments/autoresearch/raw/public-c4-baseline-v3`;
- schedule SHA-256
  `d9f9ea201e77f9e57e9a7859a983571ed35d45d2802b815cb48b2e2f5ec063b3`;
- execution-plan SHA-256
  `a875a10f5e0597aed2a14187418cee008144d7f4c950f44bf7c9fb3a098b7876`;
- semantic deployment SHA-256
  `d805eb6869201f28f928a5774263062302b29a5d8786fc3c1c120cb27f19df80`.

The planned one-run policy is concurrency three, a 21,600-second wall bound
that finishes started database-condition blocks, a USD 7 per-attempt
reservation, a USD 560 C4 telemetry ceiling, and observed C4 cost basis USD
0.7275655. The public-only dry run resolved 129 attempts and ten deployment
targets and reported `live_execution=not_started`.

The recovered profile crossed authentication. The scheduler completed 18
immutable generations, then stopped fail-closed when one new pre-attempt
`whoami` request returned Omni HTTP 429. It finished already-started blocks and
left one sanitized failure diagnostic, zero staging directories, and no active
process. No correctness was inspected and no credential validation canary was
run. V3 is incomplete and non-scoreable; it will be quarantined under
`omni-benchmark-aez.5`. A prospective idempotent-observer retry repair is tracked
under `omni-benchmark-aez.6`. Scoped local implementation commits are covered
by the standing MVP authority above, but no replacement authority or v4 run is
currently authorized.

## Completed v2 quarantine decision

### Scoped local quarantine commit and v3 package — `omni-benchmark-aez.4.1`

The human selected **A**. Local commit
`f1efd00ae49824b6eb13e6655157f83a022004f3` contains only the v2 quarantine
manifest, fail-closed registry entry, and two related test files. The raw v2
run and approval artifacts remain untracked. The previously completed full
suite passes 1,439 tests with five skips and 84.33% branch coverage; Ruff,
formatting, and diff checks pass. Nothing was pushed, and no Omni request,
credential validation, receipt consumption, or C4 dispatch occurred.

## Completed human-owned profile recovery

### Canonical Omni login — `omni-benchmark-ei0.4.2.2`

The human completed the canonical interactive login for the existing
`benchmark-infra` profile and reported success. No agent validation request was
made. This repairs the profile only; it did not authorize v2 reuse or v3.

## Completed C4 authorization and failed infrastructure start

### Exact public C4 baseline v2 dispatch — `omni-benchmark-ei0.4.2.1`

The human created and authenticated the exact receipt with SHA-256
`d9869dfc57a4c8fc1ef536644228fd6f858b841d18af5ccd3262bfbdd42e0ed2`.
The control plane consumed it before dispatcher construction. The exact run was
commit `da84b4ae2305cba0f6b31a87f1545b2fdff8d29c`, run ID
`public-c4-baseline-v2`, output root
`experiments/autoresearch/raw/public-c4-baseline-v2`, schedule SHA-256
`3dc74f45730079a5da635388a955b5a3c87059decc9cd57989a90c715bc0c12d`,
execution-plan SHA-256
`c7df1706cedc53256754b15942b357855c2e9163978641b2d0c45dac6c4bd59b`, and
semantic deployment SHA-256
`d805eb6869201f28f928a5774263062302b29a5d8786fc3c1c120cb27f19df80`.

At concurrency three, the first three child processes all exited with identical
sanitized Omni HTTP 403 diagnostics before an evaluated answer. The batch failed
closed immediately. There are zero generation artifacts, zero correctness
results, and no active process. The receipt is spent and the v2 output root is
append-only diagnostic evidence; neither may be reused or overwritten.

## Completed repository-control decision

### Local C4-prerequisite commits and clean integration — `omni-benchmark-ei0.4.1`

At 2026-08-28T22:59-04:00 the human selected **A**: authorize exactly two
scoped local commits and a fresh clean integration worktree, with no push and no
C4 dispatch.

Both C4 prerequisite implementations are complete and full-suite green in
their isolated worktrees. No C4 run occurred. The semantic-content/cost lane
passes 1,429 tests with five skips; the human-approval lane passes 1,430 tests
with five skips. The latter also has a regression and fail-closed repair for a
symlinked approval-directory parent.

Repository policy requires explicit human permission before agents create git
commits. The recommended next step is limited to making one reviewed **local**
commit in each isolated worktree and combining them in a new clean integration
worktree. Integration must apply the semantic-content/cost lane first and make
the approval receipt's deployment identity bind its `semantic_model_sha256`,
then run the combined full test and formatting gates.

This decision does **not** authorize a push, any mutation of the dirty main
worktree, lease or credential work, gold/dev-B/test access, a C4 canary, or a C4
production run. C4 remains stopped and quarantined; production would require a
separate fresh human authorization after integration.

The semantic-content/cost lane is local commit `d6337c1`; the human-approval
gate follows as local commit `da84b4a` on clean branch
`codex/c4-prerequisites-integrated`. The shared CLI resolution preserves the
new budget policy and hashes `branch_id`, `model_id`, and
`semantic_model_sha256` into the approval deployment identity. A focused
integration regression went RED before the helper existed and then passed;
combined focused suites pass 49/49. Repository-wide gates pass 1,438 tests with
five explicit skips and 84.33% branch coverage; Ruff, formatting, and diff
checks pass. Both prerequisite beads are closed.

Nothing was pushed, the dirty main worktree was not mutated by integration, and
no C4, Omni, credential, lease, gold, dev-B, or test-label action occurred. C4
remains stopped and quarantined. The completed decision is not production-run
authority; a separate fresh human authorization is still mandatory.

## Completed scoring decision

### Finite-Decimal contract repair — `omni-benchmark-ei0.3.2`

At 2026-08-28T22:24-04:00 the human selected **A**: authorize a general
operand-sized local decimal context for finite values as conformance to the
already-frozen half-up rounding contract, retain scorer identities, require
regression and full-suite gates, and authorize one clean dev-A restart.

The repair has no question-specific branch and applies equally to both frozen
scorers and later sealed evaluation. It changes only the arithmetic context
needed to complete the documented operation; the rounding rule and scorer
identities remain unchanged. Genuinely invalid decimal signals still become the
closed benchmark-infrastructure class `scorer_policy_error`, and unexpected
internal failures remain sanitized at the command boundary. The focused
scorer/custody suite passes 55/55. No private value or question identity was
inspected. Full gates subsequently passed, and the single authorized restart
completed with exact 122 official / 121 sensitivity question coverage and
published only the permitted immutable aggregate/score artifacts.

### Coverage-limited treatment of unscorable gold — `omni-benchmark-ei0.3.1`

At 2026-08-28T21:59-04:00 the human selected **A**, with this binding response:

> Freeze the coverage-limited gold-conformance rule exactly as documented in
> this file; retain and report all unscorable counts, use denominators 122
> official and 121 sensitivity on dev-A, and apply the same sealed
> evaluator-only rule to test.

The exact frozen-baseline/dev-A intersection is 420 attempts over 140 of the
154 released dev-A questions. The scorer validates all inputs before database
execution and publishes nothing unless the complete paired batch succeeds.

The first invocation stopped safely because the local restricted scorer role
had not been granted SELECT outside the original one-database canary. It
published no scores. The repository's hardened read-only ACL policy was applied
across all 18 public databases and verified: 938/938 public relations are now
readable, the role remains read-only and non-privileged, and the original gold
canary passes. That demonstrable infrastructure fault is resolved.

The corrected restart exposed a separate deterministic benchmark-input limit:

- All 9 represented `mental_healths_large` questions and all 9 represented
  `organ_transplant_large` questions fail their gold phase under both frozen
  scorers with `gold_statement_error` / PostgreSQL `42P01` (undefined table).
  The exact pinned public restore omits the referenced relations.
- One `polar_equipment_large` gold result exceeds the sensitivity scorer's
  frozen 10,000-row cap (`gold_result_overflow`). It remains scoreable under the
  official-compatible scorer.
- Therefore official-compatible coverage is 122/140 represented questions,
  or 366/420 attempts. Sensitivity coverage is 121/140 questions, or 363/420
  attempts.

The evaluator must now run a complete gold-conformance sweep before any
candidate correctness execution. A mode/question pair is unscorable only for
the closed deterministic gold-phase classes `gold_query_missing`,
`gold_timeout`, `gold_statement_error`, `gold_no_result`, or
`gold_result_overflow`. Database, preprocess, cleanup, candidate, and scorer
policy failures still abort publication. Eligibility is frozen before candidate
execution; candidates are never executed for unscorable mode/question pairs.

Every one of the 420 scheduled dev-A attempts remains in each score artifact.
Scoreable records carry correctness; unscorable records carry only status and
the closed gold failure category. Receipts report scheduled, scoreable, and
unscorable attempts and questions separately. Publication must fail unless the
observed scoreable-question counts are exactly 122 official and 121
sensitivity. The sealed evaluator must apply the identical rule internally and
must not reveal test identities, per-question outcomes, or correctness results
to development. This decision authorizes dev-A scoring and subsequent
MVP-focused experiments; it does not authorize dev-B access, sealed evaluation,
or any C4 production run.

## Completed custody action

### Train-only dev-A release — `omni-benchmark-ei0.1`

The public-only direct baseline prerequisite is complete. It is frozen at
630/630 trials, and its mode-0600 selection manifest has SHA-256
`04c75eb40c6a8bbb59af07358733b59a10d9b28787443d622fae5f31887bd725`.
The first train-only release attempt failed safely before publication. The
completed values-free probe inspected exactly 154 dev-A records from the same
480-record source: 152 have integer `external_knowledge` arrays and 2 have empty
arrays. The source SHA-256 is
`be6433ea0687c37e2b6a901acbe000667d073da8dec2f08e79686995d2f8d5b1`.
Both temporary transfers were removed successfully, and
`data/private/dev-a/labels.jsonl` remains absent.

The smallest format adapter was implemented and tested: homogeneous integer
IDs are converted losslessly to decimal strings, already-string arrays remain
valid, and mixed arrays, booleans, floats, objects, and source-hash mismatches
fail closed before publication. The human train-only release completed with
exit status 0: source 480, released 154, ignored 326, output SHA-256
`34794127f6f34f5214eedf652b86d870fb2c4e8f67d364bbd8d333897acf2c3d`.
Cleanup completed with `file=0`, `directory=0`. Agent verification confirmed a
regular mode-0600 file, 154 lines, the reported output hash, and exact committed
dev-A membership. **Do not rerun the release command.** The remaining text in
this section is the historical operator procedure used for the completed action.

#### What file to use

Use the private JSONL attachment from the LiveSQLBench gold email. This is the
full private source package supplied separately from the repository. It is not
a file created by this project. Do not open it in an editor, preview it, print
it, convert it, or paste it into a chat.

The release tool reads the complete source under human custody, verifies the
probed source hash, and publishes only the 154 committed dev-A records. It does
not inspect or publish hidden fields from the other 326 records. Its terminal
output contains only counts and hashes; controlled failures print one sanitized
line without a traceback, path, or hidden value.

#### What “pause agents” means

“Pause” means that no Codex, Claude, or other agent is executing commands on the
Linux benchmark host while the full private file is temporarily present there.
Wait for the current chat turn to finish, stop any separate agent sessions, and
stop any background agent command that can inspect the host. Ordinary human
Terminal and SSH sessions may remain open. You do not need to stop PostgreSQL,
Omni, the operating system, or your MacBook.

This Codex workspace cannot read your MacBook filesystem. A gold file that
remains only on the MacBook is outside this workspace. If a separate local agent
on the MacBook has filesystem access, stop that agent too.

#### Before transfer or release

1. Let all current agent commands finish, then pause or stop every agent session
   that can access this host. Do not perform the release while an agent turn or
   background agent command is running.
2. Keep the email and its attachment under human custody. A download on a
   separate MacBook is acceptable because the Linux benchmark agents cannot
   access it. Do not upload it to this chat, the repository, a shared cloud
   folder, or an agent-accessible workspace.
3. Do not tell an agent the attachment's filename or path. The command below
   reads the path privately so the literal path is not stored in shell history.

#### If the file is on a MacBook and the repository is on the Linux host

Keep the MacBook copy as the human-custodied source. After all agents on the
Linux host are paused, open a normal Terminal on the MacBook and run the
following. Start a clean Bash shell first because current macOS Terminal shells
often default to Zsh, whose `read` flags differ. The first prompt accepts the SSH
hostname or an existing SSH alias. The second prompt accepts the gold file's
absolute Mac path without echoing it or storing the literal path in shell
history.

```bash
bash --noprofile --norc

read -r -p 'Benchmark SSH host or alias: ' OMNI_BENCHMARK_HOST
OMNI_REMOTE_GOLD_DIR=$(ssh "$OMNI_BENCHMARK_HOST" \
  'umask 077; mktemp -d /var/tmp/omni-gold-human.XXXXXXXX')

read -r -s -p 'Absolute path to the gold JSONL on this Mac: ' OMNI_MAC_GOLD_SOURCE
printf '\n'
scp "$OMNI_MAC_GOLD_SOURCE" \
  "$OMNI_BENCHMARK_HOST:$OMNI_REMOTE_GOLD_DIR/source.jsonl"
transfer_status=$?
unset OMNI_MAC_GOLD_SOURCE
printf 'transfer exit status: %s\n' "$transfer_status"
printf 'remote temporary directory: %s\n' "$OMNI_REMOTE_GOLD_DIR"
```

Continue only if `transfer exit status: 0` appears. Do not paste the printed
temporary directory into a chat. In the same Mac Terminal, connect to the host:

```bash
ssh "$OMNI_BENCHMARK_HOST"
```

At the remote shell, privately enter the temporary directory printed by the Mac
command, validate that it is the dedicated custody directory, and set the source
path:

```bash
bash --noprofile --norc

read -r -s -p 'Remote temporary gold directory: ' OMNI_GOLD_TRANSFER_DIR
printf '\n'

case "$OMNI_GOLD_TRANSFER_DIR" in
  /var/tmp/omni-gold-human.*) ;;
  *) printf 'Unexpected temporary-directory prefix; stopping.\n'; exit 2 ;;
esac

OMNI_GOLD_SOURCE="$OMNI_GOLD_TRANSFER_DIR/source.jsonl"
test -f "$OMNI_GOLD_SOURCE" || { printf 'Transferred source is absent; stopping.\n'; exit 2; }
chmod 600 "$OMNI_GOLD_SOURCE"
```

If the existing Mac-to-host transfer command is unsuitable because the normal
`work` alias uses Mosh instead of SSH, a human may use a remote file browser:

1. In a human-controlled Linux terminal, run these three commands one at a time:

   ```bash
   umask 077
   OMNI_GOLD_TRANSFER_DIR=$(mktemp -d /var/tmp/omni-gold-human.XXXXXXXX)
   printf 'remote temporary directory: %s\n' "$OMNI_GOLD_TRANSFER_DIR"
   ```

   `mktemp` chooses the `X` characters; do not choose them manually or type
   `XXXXXXXX` as the resulting directory name.
2. In the remote file browser, drag the MacBook gold JSONL into exactly the
   printed directory and name the remote copy `source.jsonl`. Do not put it in
   the repository.
3. Back in the same Linux terminal, run these commands one at a time:

   ```bash
   OMNI_GOLD_SOURCE="$OMNI_GOLD_TRANSFER_DIR/source.jsonl"
   test -f "$OMNI_GOLD_SOURCE"; printf 'source present status: %s\n' "$?"
   chmod 600 "$OMNI_GOLD_SOURCE"
   ```

Continue only if `source present status: 0` appears.

#### Exact release command

Use a separate human-controlled terminal. The command itself must be run from
the project directory; only the private source file stays outside the project.

```bash
cd /home/ds/projects/omni-benchmark

# If the file was transferred from the MacBook using the preceding steps,
# OMNI_GOLD_SOURCE is already set. Otherwise, enter its external path now:
if [ -z "${OMNI_GOLD_SOURCE:-}" ]; then
  read -r -s -p 'Absolute path to the private gold JSONL: ' OMNI_GOLD_SOURCE
  printf '\n'
fi

uv run python sealed_tools/release_train.py --source "$OMNI_GOLD_SOURCE" --dev-a-ids data/manifests/dev_a_ids.txt --destination data/private/dev-a/labels.jsonl --expected-source-sha256 be6433ea0687c37e2b6a901acbe000667d073da8dec2f08e79686995d2f8d5b1 --freeze-a-commit 7d39ee107338da1ce10e2553a4290e64bfc2f892 --workspace /home/ds/projects/omni-benchmark
release_status=$?
printf 'release exit status: %s\n' "$release_status"
```

The tool should exit with status `0` and print one JSON object containing only
`counts`, `output_sha256`, and `source_sha256`. The required counts are exactly
`{"ignored": 326, "released": 154, "source": 480}`, and the reported source
SHA-256 must equal the probed value above.

If the command fails or reports any other count or source hash, stop. Do not
retry or inspect/edit the source. Report only the nonzero status and sanitized
error that contains no private filename, path, or content.

#### After the release attempt

1. Whether the release succeeded or failed, remove only the temporary remote
   source before resuming any agent. If the Mac transfer steps above were used,
   run the following in the same remote shell. The validated directory contains
   only the transferred source; the MacBook copy remains intact.

   ```bash
   rm -f -- "$OMNI_GOLD_SOURCE"; file_cleanup_status=$?
   rmdir -- "$OMNI_GOLD_TRANSFER_DIR"; directory_cleanup_status=$?
   printf 'remote cleanup status: file=%s directory=%s\n' "$file_cleanup_status" "$directory_cleanup_status"
   unset OMNI_GOLD_SOURCE OMNI_GOLD_TRANSFER_DIR
   ```

   If either cleanup command fails, do not resume an agent until the temporary
   remote source has been removed. If a removable volume was used instead,
   unmount it. Keep the canonical copy in the human-controlled email, MacBook,
   or vault according to the custody policy.
2. If the release succeeded, return to the benchmark chat and paste only the
   one-line JSON count/hash summary plus `release exit status: 0`. Do not attach
   the file or paste its path, records, SQL, knowledge IDs, test cases, or other
   contents. If it failed, report only the nonzero exit status and a sanitized
   error that contains no private path or content.
3. Do not run `bd human respond` yourself. After checking the count/hash-only
   summary and destination metadata, the benchmark agent will record the response.

After a successful release, the extracted dev-A-only destination is authorized
offline development input. The complete source, dev-B records, and test records
remain outside agent scope.

- The C4 production lane remains stopped and requires a new, explicit human
  authorization after its prerequisites are integrated. A passing canary will
  remain a precondition, not authorization.

## Approved actions in progress

- The Omni `benchmark-infra` browser OAuth flow was completed at approximately
  14:25 EDT. Server-side `whoami` succeeds, and the five-way C4 capture canary
  was relaunched. No gold or hidden-label access was involved.

## Recently completed

- The immutable Claude comparator lease handoff completed on 2026-08-28. Three
  private lease directories passed nine sequential invocations without byte
  mutation and replaced every `~/.claude-homes` path for benchmark launches.
  The first frozen-transport canary failed before any Claude invocation because
  parent-generated Python bytecode was nondeterministic across child hash seeds;
  this was a benchmark-infrastructure preflight failure, not an OAuth failure.
  The retry completed 12/12 with zero infrastructure failures. The continuation
  runtime-path defect is now fixed and reviewed. Because a full continuation
  would straddle the automatic 19:00 EDT credential refresh at measured
  throughput, launch is staged for the fresh post-refresh window. No operator
  action is currently requested.

- Before the full direct baseline fan-out, refusal handling was locked on
  2026-08-28: preserve `refused` separately from wrong answers and errors;
  never selectively rerun it; report per-condition/per-database refusal rates,
  all-attempt execution success, and answered-only accuracy. Three sealed
  repetitions remain planned. The 14:00 EDT C4 coverage decision and $2,000
  total cost ceiling are also recorded in Beads.

- `omni-benchmark-dih.17.1` was authorized and completed on 2026-08-28. Safe
  readback proved the 17 non-canary connections selected `neondb` while the
  parity-verified mirrors and direct comparators targeted exact named
  databases. Only each benchmark connection's database field was corrected;
  all 17 public-only schema refreshes completed, and readback table/view counts
  exactly matched the committed parity inventory. No Gas City connection,
  credential, Neon content/grant, or shared/main Omni model was changed.

- `omni-benchmark-dih.5.4.2.5.3` was dismissed at
  `2026-08-28T10:51:34-04:00`. The user identified the existing isolated
  `claude-1`, `claude-3`, `claude-4`, and `claude-5` OAuth harnesses, so no
  interactive reauthentication is required. The capacity picker selected
  account 3 for the next public-only C1-C3 canary; credentials remain outside
  the repository and run artifacts.
- `omni-benchmark-dih.5.4.2.4.4.1.1` was completed at
  `2026-08-28T08:57:28-04:00`. The credential-free bindings for all 18 direct
  databases and their fail-closed inventory loader were tested and committed in
  `459d3ce`. No endpoint, URL, password, token, or connection mutation entered
  the repository.
- `omni-benchmark-dih.15` was completed at
  `2026-08-28T08:47:33-04:00`. The public Git remote is configured and the
  explicitly authorized, reviewed history was pushed to `main`; Beads/Dolt
  state was pushed separately to `refs/dolt/data`. Git history and Beads data
  share a repository but not a ref. No ignored, private, or dirty-worktree
  artifact was published.
- `omni-benchmark-dih.14.1` was approved and verified on 2026-08-28. The
  archeology connection now selects `archeology_scan_large`; one public-only
  refresh completed and readback returned one public schema with 51 views. No
  other connection was changed.
- `omni-benchmark-dih.12.1` was approved and verified on 2026-08-28. One
  isolated archeology model/branch received the committed public-only bundle;
  validation returned zero issues, 14/14 artifacts passed semantic readback,
  one governed semantic query succeeded, and one unscored AI Hub diagnostic
  completed. No shared/main model was merged or changed, and no hidden label,
  gold data, or benchmark correctness result was accessed.

## No action requested yet

- Production sealed score custody is now prepared offline on clean branch
  `codex/sealed-scoring-production` at commit `7342476`. It validates all twelve
  cohorts before opening any private release, extracts exactly the 101 frozen
  test records only after Freeze B, applies the already approved
  coverage-limited dual-scorer rule, and emits identity-free aggregate reports.
  It must be integrated into the final system commit before Freeze B. **Do not
  transfer the gold attachment, release test labels, run either new explicit
  execution flag, or read aggregate sealed results yet.** Exact values and
  commands will be filled in only after C4, final-candidate freeze, and the later
  sealed authorization. One reporting limitation is now explicit: the frozen
  generation record does not retain the direct agent's content-refusal versus
  insufficient-context subtype, so those two held-out cells will be reported as
  unavailable rather than guessed; the combined refusal/error rate and raw
  terminal classes remain available. No response is requested now.
- No dev-B checkpoint or sealed-test custody action is requested yet. Their
  private records remain guardian-only until their later protocol gates.
- Do not change Neon grants or database contents. All 18 public mirrors already
  passed exact scorer parity and read-only-role verification.
- The resumed long-running goal changes orchestration state only; it does not
  broaden service permissions or evaluation custody.

## How decisions are handled

1. The request is filed as a Beads `decision` with the `human` label.
2. The exact action and scope appear on this page before execution.
3. A response is recorded with `bd human respond <bead-id>` (or dismissed with
   `bd human dismiss <bead-id>`).
4. In the same authorization-consumption step, this page is updated so the
   operator view never continues to show the answered request as pending.
5. The implementation bead remains open until the approved action is executed
   and verified; answering a decision is not treated as completing the work.
6. The outcome is preserved in Beads and the research log when it affects the
   experiment.

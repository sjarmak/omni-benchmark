# Human decision queue

This page is the concise operator view of work waiting on human authority.
Beads is the durable source of truth; this checked-in page explains the request
and its consequence in plain language. Run `bd human list` for the live queue.

Last updated: 2026-08-28T14:36:00-04:00 (America/New_York). No gold package,
hidden annotation, or sealed-test result has been accessed.

## Waiting for a response

- **Refresh the three Claude comparator identities**
  (`omni-benchmark-ddy`, P0). The credential rotation at 14:20 EDT invalidated
  the server-side OAuth sessions used by `claude-3`, `claude-4`, and
  `claude-5`. Their later local expiry timestamps do not prove validity: a
  provider request returns `OAuth session expired and could not be refreshed`.
  Account 5 was refreshed and independently passed the exact immutable
  transport at 14:36 EDT. Reauthenticate **account 3 and account 4** through
  the existing credential workflow, without pasting credentials into chat,
  then notify the benchmark operator. Account 1 is optional and is not needed
  for the current three-profile run. The direct baseline remains stopped. Its 112 valid
  pre-rotation attempts are preserved; 95 attempts from
  `2026-08-28T18:20:46Z` through `18:26:20Z` are recorded as authorized
  benchmark-infrastructure reruns and will not enter outcome metrics.

## Approved actions in progress

- The Omni `benchmark-infra` browser OAuth flow was completed at approximately
  14:25 EDT. Server-side `whoami` succeeds, and the five-way C4 capture canary
  was relaunched. No gold or hidden-label access was involved.

## Recently completed

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

- Keep the gold email unopened and undownloaded. The package remains outside
  agent scope until the public-only baseline is preserved and the train-only
  guardian release is ready.
- Do not change Neon grants or database contents. All 18 public mirrors already
  passed exact scorer parity and read-only-role verification.
- The resumed long-running goal changes orchestration state only; it does not
  broaden service permissions or evaluation custody.

## How decisions are handled

1. The request is filed as a Beads `decision` with the `human` label.
2. The exact action and scope appear on this page before execution.
3. A response is recorded with `bd human respond <bead-id>` (or dismissed with
   `bd human dismiss <bead-id>`).
4. The implementation bead remains open until the approved action is executed
   and verified; answering a decision is not treated as completing the work.
5. Closed decisions are removed from “Waiting for a response” at the next doc
   update, with the outcome preserved in Beads and the research log when it
   affects the experiment.

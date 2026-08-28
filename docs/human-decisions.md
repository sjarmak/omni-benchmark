# Human decision queue

This page is the concise operator view of work waiting on human authority.
Beads is the durable source of truth; this checked-in page explains the request
and its consequence in plain language. Run `bd human list` for the live queue.

Last updated: 2026-08-28T14:51:42-04:00 (America/New_York). No gold package,
hidden annotation, or sealed-test result has been accessed.

## Waiting for a response

- **Establish exclusive ownership of Claude comparator identities**
  (`omni-benchmark-ddy`, P0). No further rotation, refresh, credential copy, or
  validation canary is authorized while a Claude session or benchmark process
  may hold the same identity. OAuth refresh state is mutable: independent
  copies and background sessions can revoke one another, which is what turned
  the live baseline into infrastructure failures after 14:20 EDT. The required
  recovery is a single human-owned canonical login per identity after competing
  sessions are stopped, followed by a benchmark credential lease that no other
  process mutates for the duration of the run. Do not paste credentials into
  chat. The direct baseline remains stopped. Its 112 valid
  pre-rotation attempts are preserved; 95 attempts from
  `2026-08-28T18:20:46Z` through `18:26:20Z` are recorded as authorized
  benchmark-infrastructure reruns and will not enter outcome metrics.

  **Requested operator action:** dedicate accounts 1, 3, and 4 exclusively to
  the benchmark until the direct continuation finishes. In each account's own
  canonical `claude-N` environment, make sure no Claude session is still
  running, perform one interactive `/login`, then exit without starting or
  resuming other work. Do not run `ds-cred`, copy credential files, start Remote
  Control, or open another Claude session under those identities afterward.
  Notify the benchmark operator only when all three logins are complete.
  Account 5 is intentionally excluded from this recovery because it currently
  owns a live background Omni benchmark session; stopping that session is not
  required if account 5 remains outside the comparator pool.

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

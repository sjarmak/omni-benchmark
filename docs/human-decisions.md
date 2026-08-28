# Human decision queue

This page is the concise operator view of work waiting on human authority.
Beads is the durable source of truth; this checked-in page explains the request
and its consequence in plain language. Run `bd human list` for the live queue.

Last updated: 2026-08-28T08:47:33-04:00 (America/New_York). No gold package,
hidden annotation, or sealed-test result has been accessed.

## Waiting for a response

No decisions are currently waiting on the user. `bd human list` returned an
empty queue at the timestamp above.

## Approved actions in progress

| Bead | Approved scope | Boundary retained | Close the implementation work when |
| --- | --- | --- | --- |
| `omni-benchmark-dih.5.4.2.4.4.1.1` | Read the exact public Neon connection coordinates and generate credential-free SHA-256 target bindings for all 18 direct C1–C3 databases. | Persist only database name, physical database name, and digest—never host, endpoint, URL, password, or token. No connection mutation. | The inventory-bound sidecar and fail-closed loader are tested and committed. |

## Recently completed

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

# Freeze B lineage

Freeze B is the record that binds the sealed evaluation to an exact system. Ten
of them were recorded between 2026-08-30 02:58Z and 18:57Z. Two are load-bearing
for the published sealed result: **v7** froze the system that generated the 1,068
attempts, and **v10** froze the control the scorers ran under. The other eight
are superseded or rejected, and they are kept because a freeze series that only
shows its winners is not auditable.

This page exists so an outside reader can ask the question that matters about any
frozen benchmark result: *could a result have been seen before the system was
frozen?* The answer here is bounded by artifacts, and one joint in that chain is
weaker than the others. Both are stated below.

## The ten records

Every record is a single-line canonical JSON file under `experiments/`. The
Freeze B SHA-256 is the digest of the file itself, so any row can be rechecked
with `sha256sum`. All ten bind the same Freeze A commit
`7d39ee107338da1ce10e2553a4290e64bfc2f892` and the same 108 frozen input files.

| v | File | Recorded (UTC) | System commit | Why it was recorded | Frozen inputs vs. previous |
| --- | --- | --- | --- | --- | --- |
| 1 | `freeze-b.json` | 02:58:53 | `d8d1a93` freeze sealed system inputs | First freeze of the sealed system. | baseline, 108 files |
| 2 | `freeze-b-v2.json` | 11:15:01 | `c8a784f` bind sealed dispatch to selected ids | Dispatch used the wrong ID manifest. | 1 changed: `sealed_dispatch_cli.py` |
| 3 | `freeze-b-v3.json` | 11:24:51 | `d104fe4` restore sealed postgres system CA | Direct-SQL transport lost its CA bundle. | 1 changed: `sealed_direct_factory.py` |
| 4 | `freeze-b-v4.json` | 11:36:30 | `717d853` bind sealed C2 aggregate identity | C2 aggregate identity was not bound. | 1 changed: `sealed_direct_adapter.py` |
| 5 | `freeze-b-v5.json` | 12:03:01 | `d18ce32` preserve completed Omni contract failures | Contract failures were being dropped instead of recorded. | 2 changed: `omni_capture.py`, `sealed_omni_adapter.py` |
| 6 | `freeze-b-v6.json` | 12:21:53 | `34b7812` preserve unsupported Omni result types | Unsupported result types needed a distinct terminal class. | 1 changed: `sealed_omni_adapter.py` |
| 7 | `freeze-b-v7.json` | 12:33:07 | `8b0c739` reuse returned Omni typed rows | **Generation freeze.** Typed rows Omni already returned were being discarded. | 1 changed: `omni_capture.py` |
| 8 | `freeze-b-v8.json` | 17:49:07 | `3389ae5` accept all evaluated-system C4 terminal classes in sealed scoring | Re-established the HEAD-equals-control binding after a scoring-validator fix. | **none: identical to v7** |
| 9 | `freeze-b-v9.json` | 18:52:30 | `dd07c5b` separate sealed generation and scoring freezes | **Rejected.** Changed a frozen control-module digest. | 1 changed: `freeze_b_control.py` |
| 10 | `freeze-b-v10.json` | 18:57:18 | `0a5aee4` keep archived freeze loading outside frozen control | **Scoring freeze.** Redid v9's fix without touching a frozen input. | reverts v9; identical to v8 |

Full digests:

```
902fb1be70fd20fb193a8f302b25d5c68a7d6a37b78db6124d84868b92151a80  experiments/freeze-b.json
7fd65b9a619d07fdf76e6f04cf608f8be09b7a9a8af9b71d9757aa1106c699d5  experiments/freeze-b-v2.json
08d741ec4fba303ccc9ee2f2d08d598cef0159d45d582f70259469c4000b5e36  experiments/freeze-b-v3.json
e8c299a27983356c6b3ed9fda547c7bbc23f67fc481168d3129298876a490d8b  experiments/freeze-b-v4.json
581a8c1022c36dd65cef3a9bb4e49f6a68bf784a51cf21d2359a9b0d729d57c2  experiments/freeze-b-v5.json
29cc21fcbeea62d0d35c0199c95b559addacd4f1b4700cc197c4f703cd3fc1e8  experiments/freeze-b-v6.json
e1c9f1967422822c848c18a17ba759d4e4fbc7f21aa0fe3ae1045b9236ae4730  experiments/freeze-b-v7.json
386bfebd04a1fd25af13e720da265ea8a2fae5f86a07ee1ca600ebdb05366162  experiments/freeze-b-v8.json
c2705b2c791fd9a3b05ef7138e1533982ca66e806ebd1adefd4f0b1e79287aef  experiments/freeze-b-v9.json
ff10083bf70d82bd483d12e98751d9bf7f5d4236c42fac3ba921405d87953a05  experiments/freeze-b-v10.json
```

The published sealed receipt names two of these, and they are different values on
purpose: `generation_freeze_b_sha256` is v7 (`e1c9f196…`) and `freeze_b_sha256`
is v10 (`ff10083b…`). Before v9 a single field served both roles, which is the
defect v9 and v10 were recorded to fix.

## What each freeze changed

Recompute the frozen-input diff between any two records:

```bash
uv run python -c "
import json
a = json.load(open('experiments/freeze-b-v8.json'))['frozen_files']
b = json.load(open('experiments/freeze-b-v10.json'))['frozen_files']
print(sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p)) or 'identical')
"
```

Three facts fall out of that diff and each one matters to a reader deciding how
much the freeze series is worth.

**v7, v8, and v10 are byte-identical across all 108 frozen inputs.** The three
records differ only in `system_commit`, `recorded_at`, and the scorer source
pointer. So the system that produced the answers and the system that scored them
are the same frozen system, and the two later records are re-bindings rather than
changes.

**v9 is the only record that changed a frozen digest, and it was rejected for
exactly that.** It modified `freeze_b_control.py`, which is itself one of the 108
frozen inputs, so the module that enforces the freeze would have been changed by
the act of recording the freeze. v10 achieves the same separation of generation
and scoring provenance by moving archived-freeze loading outside the frozen
control module, leaving all 108 digests at their v8 values.

**The 108 frozen inputs cover the generation system, not the scoring system.**
`sealed_evaluation.py`, `sealed_evaluation_cli.py`, and `sealed_results.py` are
absent from the frozen set; 68 of the 108 entries are `src/` modules and those
three are not among them. The scoring side is bound by `system_commit` and by the
HEAD-equals-control check in `_require_exact_control_checkout`, which is a real
binding but a different one: commit identity plus a clean tree, rather than a
per-file digest. A reader auditing the scorers should verify the commit, not look
for their digests in `frozen_files`.

## Ordering: what the artifacts establish

The question is whether any correctness value could have influenced any freeze.
The timeline, in UTC, with the evidence for each row:

| Time | Event | Evidence |
| --- | --- | --- |
| 02:58:53 | Freeze B v1 | record `recorded_at`, commit `079e4ce` |
| 12:33:07 | Freeze B v7, the generation freeze | record `recorded_at`, commit `94cc0d9` |
| 12:34:27 | Human approval of the `sealed-final-v6` dispatch, bound to v7 | approval response in bead `omni-benchmark-ei0.10.14` |
| 12:35:27 | Approval consumed | `runs/preserved/sealed-final-v6/approvals/e0a6ba14….consumed.json` mtime |
| 12:35:51 | First attempt written | earliest `attempts/**/attempt.json` mtime |
| 16:33:21 | Last attempt written | latest `attempts/**/attempt.json` mtime |
| 17:49:07 | Freeze B v8 | record `recorded_at`, commit `0429647` |
| 18:07 | Attestation: generation complete, "gold has not been released, no scorer has run, nobody has seen a sealed outcome" | bead comment on `omni-benchmark-ei0.10` |
| 18:52:30 | Freeze B v9, rejected | record `recorded_at`, commit `2bf2380` |
| 18:57:18 | Freeze B v10, the scoring freeze | record `recorded_at`, commit `fe4660d` |
| 19:00 | Attestation: v10 preflight passes, status `validated_not_scored`, "no correctness or private label opened" | bead comment on `omni-benchmark-ei0.10.15` |
| 19:15 – 19:27 | Operator releases the sealed gold | bracketed, not directly timestamped (see below) |
| 19:27:25 | All 26 per-arm score files and both aggregates written | `score/**` mtimes, within one second of each other |
| 19:27:38 | Aggregate report written | `report/held-out-results.md` mtime |
| 19:32 | Results published | bead comment on `omni-benchmark-ei0.10` |

Every freeze precedes the first scorer output by at least 30 minutes, and the
26 score files were all written inside a single second, which is consistent with
one scoring pass and inconsistent with an iterative one.

## The claim, stated at the strength the evidence supports

The defensible claim is **not** "nobody looked at a result before freezing." It
is narrower and it is checkable:

> No gold was released and no scorer ran until after the last freeze, so no
> correctness value existed that could have influenced any freeze.

That distinction is load-bearing, because one freeze in the series **was**
informed by sealed run data. The commit v8 froze over, `3389ae5`, says so in its
own body:

> Run sealed-final-v6 produced 32 and 4 of those respectively, so 36 of 267 C4
> attempts could not be loaded and the batch load aborted.

Those are terminal-failure counts read off the sealed run. They are not
correctness: an attempt that could not be loaded has no score either way, and the
fix admitted the two missing terminal classes without changing how any admitted
answer compares to gold. The commit body makes the same argument and the diff
supports it, since v8 changed none of the 108 frozen inputs. But a reader should
see the sequence rather than take the conclusion: sealed non-correctness
telemetry was observed at 13:49, and a freeze was recorded on top of it at 17:49.

## The weak joint

`runs/preserved/sealed-final-v6/score/receipt.json` carries the lineage digests,
the attempt and cohort counts, and the score-artifact list. It does **not**
carry a `scored_at` field. Neither does it record when the gold was released.

So the "gold released after the last freeze" step rests on two things that are
weaker than a signed artifact: file mtimes in the preserved run tree, and bead
comment timestamps written by the operator. Both are consistent, and the mtimes
are corroborated independently by the approval-consumption record and the attempt
files. Neither is tamper-evident the way the freeze digests are.

Adding `scored_at` and a gold-release timestamp to the score receipt would close
this, and it is tracked rather than fixed in place: the receipt is a
Freeze-B-bound artifact under append-only custody, so changing its schema after
results were published would itself be the kind of post-hoc edit this page exists
to rule out. The change belongs to the next run series, under the pin-per-series
drift rule.

## Rechecking this page

```bash
sha256sum experiments/freeze-b.json experiments/freeze-b-v[0-9]*.json
git log --format='%H %ad %s' --date=iso-local -- experiments/freeze-b-v8.json
git show 3389ae5 --stat
TZ=UTC find runs/preserved/sealed-final-v6/score -type f \
  -printf '%TY-%Tm-%TdT%TH:%TM:%TSZ  %p\n' | sort
```

The last command needs the preserved run tree, which is ignored local custody and
is not part of a clone.

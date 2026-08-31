"""Preregistered test: is budget exhaustion a property of the question?

Registered 2026-08-28 22:00Z at 220 of 518 captures, BEFORE observing the
remaining attempts. The pattern was found post-hoc in the first 216; this fixes
the statistic and the threshold so the rest of the run is a confirmatory sample.

Hypothesis. model_budget_error clusters by question rather than by condition:
some questions are expensive to answer under any direct scaffold.

Statistic. Over questions run in all three conditions, count questions failing in
at least two. Compare against a permutation null that holds the total failure
count fixed and redistributes it uniformly over attempt slots, which preserves
the marginal failure rate and the per-question attempt counts.

Decision rule, fixed in advance. Confirmed at one-sided p < 0.01 on the holdout
sample alone (captures not in the registered prefix). Reported as not confirmed
otherwise. No other statistic substituted after seeing the result.
"""

from __future__ import annotations

import collections
import json
import os
import random
import sys

REGISTERED_PREFIX = 220
TRIALS = 200_000
ALPHA = 0.01
FAILURE = "model_budget_error"


def load(root: str) -> list[tuple[str, str, bool, str]]:
    """Return (question, condition, failed, finished_at) per capture."""
    rows = []
    for dirpath, _, files in os.walk(root):
        if "capture.receipt.json" not in files:
            continue
        summary = json.load(open(os.path.join(dirpath, "capture.receipt.json"))).get(
            "capture_summary", {}
        )
        parts = os.path.relpath(dirpath, root).split(os.sep)
        condition = next((p for p in parts if p in ("c1", "c2", "c3", "c4")), "?")
        rows.append(
            (
                parts[-1].rsplit("-r", 1)[0],
                condition,
                summary.get("failure_class") == FAILURE,
                summary.get("finished_at") or "",
            )
        )
    return sorted(rows, key=lambda r: r[3])


def multi_condition_count(
    rows: list[tuple[str, str, bool, str]],
) -> tuple[int, int, int]:
    """Questions failing in >=2 conditions, among those run in all three."""
    seen: dict[str, dict[str, bool]] = collections.defaultdict(dict)
    for question, condition, failed, _ in rows:
        seen[question][condition] = failed
    full = {q: d for q, d in seen.items() if len(d) >= 3}
    multi = sum(1 for d in full.values() if sum(d.values()) >= 2)
    return multi, len(full), sum(sum(d.values()) for d in full.values())


def permutation_p(rows: list[tuple[str, str, bool, str]], observed: int) -> float:
    seen: dict[str, dict[str, bool]] = collections.defaultdict(dict)
    for question, condition, failed, _ in rows:
        seen[question][condition] = failed
    full = {q: d for q, d in seen.items() if len(d) >= 3}
    slots = [(q, c) for q, d in full.items() for c in d]
    failures = sum(sum(d.values()) for d in full.values())
    if failures == 0:
        return 1.0
    random.seed(0)
    at_least = 0
    for _ in range(TRIALS):
        hit = collections.Counter(q for q, _ in random.sample(slots, failures))
        if sum(1 for v in hit.values() if v >= 2) >= observed:
            at_least += 1
    return at_least / TRIALS


def main() -> int:
    rows = load(sys.argv[1])
    holdout = rows[REGISTERED_PREFIX:]
    if len(holdout) < 100:
        print(f"holdout too small: {len(holdout)} captures; rerun after completion")
        return 2
    multi, questions, failures = multi_condition_count(holdout)
    p = permutation_p(holdout, multi)
    print(f"holdout captures       {len(holdout)}")
    print(f"questions in all 3     {questions}")
    print(f"budget errors          {failures}")
    print(f"questions failing >=2  {multi}")
    print(f"permutation p          {p:.4f}")
    print(
        f"verdict                {'CONFIRMED' if p < ALPHA else 'NOT CONFIRMED'} at alpha={ALPHA}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

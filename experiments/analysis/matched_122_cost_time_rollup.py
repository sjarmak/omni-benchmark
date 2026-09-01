#!/usr/bin/env python3
"""Cost and wall time for all five arms on the matched dev-A 122-question frame.

The existing rollups each cover part of the picture. `sealed_telemetry_summary`
describes the sealed C1-C4 cohorts, `dev_a_telemetry_summary --compare` describes
C4 against C5 on dev-A, and the credit artifacts describe governed spend at the
account level. None of them puts all five arms on one frame with both resource
axes, which is what a report needs.

This reads the same three committed score artifacts the condition explorer reads,
joins them to their generation records by content hash, and aggregates the
resource fields the generation records already carry. Correctness is read, never
recomputed. No gold, no sealed partition, and no hidden annotation is touched.

Cost is not comparable across the direct and governed arms, and the output says so
per arm rather than in prose only. C1-C3 carry a provider-billed `cost_usd` per
attempt. Omni's job endpoint exposes no price field, and the credit-bracketing
pass landed after every run in this frame, so C4 and C5 carry no measured cost;
they are reported as an arm-level estimate derived from the billing-period credit
total, identical on every attempt, with `cost_measured` false.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments/analysis"))
sys.path.insert(0, str(ROOT / "experiments/trace_viewer"))

import collect  # noqa: E402
from sealed_telemetry_summary import canonical_bytes, tukey_distribution  # noqa: E402

ARMS = ("C1", "C2", "C3", "C4", "C5")
DISTRIBUTIONS = (
    "latency_ms",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cost_usd",
)


def _values(rows: list[dict], arm: str, field: str) -> list[float]:
    out = []
    for row in rows:
        value = row["arms"][arm].get(field)
        if value is not None:
            out.append(value)
    return out


def arm_summary(rows: list[dict], arm: str, credit: dict) -> dict:
    attempts = len(rows)
    cost = _values(rows, arm, "cost_usd")
    latency = _values(rows, arm, "latency_ms")
    measured = bool(cost)

    if measured:
        spend = {
            "cost_measured": True,
            "cost_source": "provider_reported_per_attempt",
            "coverage": len(cost),
            "total_usd": round(sum(cost), 6),
            "median_usd": round(statistics.median(cost), 6),
        }
    else:
        per = credit["per_attempt_usd"]
        spend = {
            "cost_measured": False,
            "cost_source": "arm_level_credit_estimate",
            "coverage": 0,
            "total_usd": round(per * attempts, 6),
            "median_usd": per,
            "upper_bound_total_usd": round(credit["upper_bound_usd"] * attempts, 6),
            "estimate_note": (
                "billing-period credit total divided across the Omni-routed attempts "
                "on disk; identical on every attempt, no per-job attribution"
            ),
        }

    correct = sum(1 for row in rows if row["arms"][arm]["outcome"] == "correct")
    per_correct = None
    if correct:
        per_correct = round(spend["total_usd"] / correct, 6)

    return {
        "attempts": attempts,
        "official_correct": correct,
        "spend": spend,
        "cost_per_correct_answer_usd": per_correct,
        "wall_time": {
            "coverage": len(latency),
            "total_hours": round(sum(latency) / 3_600_000, 6),
            "median_ms": round(statistics.median(latency), 6) if latency else None,
        },
        "distributions": {
            field: tukey_distribution(_values(rows, arm, field), total=attempts)
            for field in DISTRIBUTIONS
        },
    }


def build() -> dict:
    rows = collect.build()
    credit = collect.governed_cost_estimate()
    payload = {
        "artifact_kind": "matched_frame_cost_time_rollup",
        "frame": {
            "name": "matched dev-A 122",
            "question_count": len(rows),
            "scorer": "official",
            "score_artifacts": sorted({run for run, _ in collect.CONDITIONS.values()}),
        },
        "governed_cost_estimate": credit,
        "quartile_method": "tukey_median_of_halves_excluding_odd_median",
        "arms": {arm: arm_summary(rows, arm, credit) for arm in ARMS},
        "caveats": [
            "cost is not comparable across the direct and governed arms: C1-C3 bill "
            "through the Claude Code OAuth surface, C4 and C5 through Omni AI credits",
            "governed cost is an arm-level estimate, not a measurement; it cannot "
            "separate a cheap attempt from an expensive one",
            "wall time and token counts are measured for all five arms",
        ],
        "aggregate_hash_basis": "canonical JSON without aggregate_payload_sha256",
    }
    import hashlib

    payload["aggregate_payload_sha256"] = hashlib.sha256(
        canonical_bytes(payload)
    ).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write canonical JSON here")
    args = parser.parse_args()

    payload = build()
    data = canonical_bytes(payload)
    if args.out:
        if args.out.exists():
            raise SystemExit(f"{args.out} already exists; refusing overwrite")
        args.out.write_bytes(data)
        print(f"wrote {args.out} ({len(data)} bytes)")
    else:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Aggregate-only workload telemetry for a dev-A generation run.

`sealed_telemetry_summary.py` reads the frozen twelve-cohort sealed layout and
assumes four conditions over three repetitions. A dev-A experiment run is a
different shape: one condition, one repetition, and a raw per-database tree. This
reads that tree and produces the same class of aggregate, so a dev-A condition
can be put beside the frozen C4 arm on workload terms.

`compare` intersects two runs on their shared attempt coordinates so the medians
describe the same questions in both arms. Coordinates are used to match and are
never emitted: the output carries counts, coverage, and distributions only. No
gold, no per-question correctness, and no hidden annotation is read.

Cost is reported, not derived. Omni's job endpoint returns `metrics` with
`durationMs`, `llmMs`, `queryCount`, `queryDurationMs`, `tokenBuckets`,
`toolBreakdown`, `toolCallCount`, and `toolErrorCount`, and no price field, so a
governed attempt's `cost_usd` is null with `cost_source` recording why.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sealed_telemetry_summary import (  # noqa: E402
    SummaryError,
    canonical_bytes,
    tukey_distribution,
)

OUTCOMES = ("answered", "errored", "refused")
DISTRIBUTIONS = (
    ("latency_ms", "latency_ms"),
    ("total_tokens", "token_usage.total_tokens"),
    ("input_tokens", "token_usage.input_tokens"),
    ("output_tokens", "token_usage.output_tokens"),
    ("tool_call_count", "tool_call_count"),
    ("database_query_count", "database_query_count"),
)


def _field(record: dict[str, Any], field: str) -> Any:
    if field.startswith("token_usage."):
        usage = record.get("token_usage")
        return usage.get(field.split(".", 1)[1]) if isinstance(usage, dict) else None
    return record.get(field)


def _values(records: Iterable[dict[str, Any]], field: str) -> list[int | float]:
    return [
        value
        for value in (_field(record, field) for record in records)
        if value is not None
    ]


def _coordinate(record: dict[str, Any], location: str) -> tuple[str, int]:
    instance = record.get("instance_id")
    repetition = record.get("repetition")
    if not isinstance(instance, str) or not instance:
        raise SummaryError(f"{location}: instance_id must be a non-empty string")
    if isinstance(repetition, bool) or not isinstance(repetition, int):
        raise SummaryError(f"{location}: repetition must be an integer")
    return instance, repetition


def read_run(run_root: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Read one record per attempt directory, keyed by attempt coordinate."""

    paths = sorted(run_root.glob("*/*/*/generation.jsonl"))
    if not paths:
        raise SummaryError(f"{run_root}: no generation records found")
    records: dict[tuple[str, int], dict[str, Any]] = {}
    for path in paths:
        location = str(path.relative_to(run_root))
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) != 1:
            raise SummaryError(f"{location}: expected exactly one record")
        raw = json.loads(lines[0])
        if not isinstance(raw, dict):
            raise SummaryError(f"{location}: record must be an object")
        coordinate = _coordinate(raw, location)
        if coordinate in records:
            raise SummaryError(f"{location}: duplicate attempt coordinate")
        records[coordinate] = raw
    return records


def _cost(records: Sequence[dict[str, Any]]) -> dict[str, object]:
    observed = [
        record["cost_usd"] for record in records if record.get("cost_usd") is not None
    ]
    sources = sorted({str(record.get("cost_source")) for record in records})
    reasons = sorted(
        {
            str(record["cost_unavailable_reason"])
            for record in records
            if record.get("cost_unavailable_reason") is not None
        }
    )
    if not observed:
        return {
            "status": "unavailable",
            "observed": 0,
            "missing": len(records),
            "cost_source": sources,
            "unavailable_reason": reasons,
        }
    return {
        "status": "fully_observed" if len(observed) == len(records) else "partial",
        "observed": len(observed),
        "missing": len(records) - len(observed),
        "cost_source": sources,
        "total": round(float(sum(observed)), 6),
        "mean": round(float(sum(observed)) / len(observed), 6),
    }


def _models(records: Sequence[dict[str, Any]]) -> list[dict[str, object]]:
    """Name the models an arm actually ran on, with how many attempts used each."""

    counts: dict[tuple[str, str], int] = {}
    for record in records:
        model = record.get("model")
        if isinstance(model, dict):
            key = (str(model.get("name")), str(model.get("provider")))
        else:
            key = (str(model), "unknown")
        counts[key] = counts.get(key, 0) + 1
    return [
        {"name": name, "provider": provider, "attempt_count": count}
        for (name, provider), count in sorted(counts.items())
    ]


def summarize(records: Sequence[dict[str, Any]]) -> dict[str, object]:
    """Return aggregate-only workload telemetry for one arm."""

    total = len(records)
    if total == 0:
        raise SummaryError("cannot summarize an empty arm")
    outcomes = {
        outcome: sum(
            1 for record in records if record.get("generation_outcome") == outcome
        )
        for outcome in OUTCOMES
    }
    unrecognized = total - sum(outcomes.values())
    if unrecognized:
        raise SummaryError("arm contains an unsupported generation_outcome")
    answered = [
        record for record in records if record.get("generation_outcome") == "answered"
    ]
    return {
        "attempt_count": total,
        "outcomes": outcomes,
        "models": _models(records),
        "token_source": sorted({str(record.get("token_source")) for record in records}),
        "cost": _cost(records),
        "all_attempts": {
            name: tukey_distribution(_values(records, field), total=total)
            for name, field in DISTRIBUTIONS
        },
        "answered_attempts": {
            name: tukey_distribution(_values(answered, field), total=len(answered))
            for name, field in DISTRIBUTIONS
        },
    }


def _sealed(payload: dict[str, object]) -> dict[str, object]:
    payload["aggregate_hash_basis"] = "canonical JSON without aggregate_payload_sha256"
    payload["aggregate_payload_sha256"] = hashlib.sha256(
        canonical_bytes(payload)
    ).hexdigest()
    return payload


def summarize_run(run_root: Path) -> dict[str, object]:
    records = read_run(run_root)
    return _sealed(
        {
            "artifact_kind": "dev_a_telemetry_summary",
            "schema_version": 1,
            "quartile_method": "tukey_median_of_halves_excluding_odd_median",
            "run_root": run_root.as_posix(),
            "arm": summarize(list(records.values())),
        }
    )


def compare_runs(named_roots: Sequence[tuple[str, Path]]) -> dict[str, object]:
    if len(named_roots) < 2:
        raise SummaryError("comparison needs at least two runs")
    loaded = {label: read_run(root) for label, root in named_roots}
    shared: set[tuple[str, int]] | None = None
    for records in loaded.values():
        shared = set(records) if shared is None else shared & set(records)
    assert shared is not None
    if not shared:
        raise SummaryError("runs share no attempt coordinate")
    order = sorted(shared)
    return _sealed(
        {
            "artifact_kind": "dev_a_telemetry_comparison",
            "schema_version": 1,
            "quartile_method": "tukey_median_of_halves_excluding_odd_median",
            "matched_attempt_count": len(order),
            "runs": {
                label: {
                    "run_root": root.as_posix(),
                    "attempt_count": len(loaded[label]),
                    "matched": summarize(
                        [loaded[label][coordinate] for coordinate in order]
                    ),
                }
                for label, root in named_roots
            },
        }
    )


def _named_root(value: str) -> tuple[str, Path]:
    label, separator, root = value.partition("=")
    if not separator or not label:
        raise argparse.ArgumentTypeError("expected label=path")
    return label, Path(root)


def _emit(payload: dict[str, object], destination: Path | None) -> None:
    content = canonical_bytes(payload)
    if destination is None:
        sys.stdout.buffer.write(content)
        return
    with destination.open("xb") as handle:
        handle.write(content)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    one = commands.add_parser("summarize")
    one.add_argument("run_root", type=Path)
    one.add_argument("--output", type=Path)

    many = commands.add_parser("compare")
    many.add_argument("--run", type=_named_root, action="append", required=True)
    many.add_argument("--output", type=Path)

    arguments = parser.parse_args(argv)
    if arguments.command == "summarize":
        _emit(summarize_run(arguments.run_root), arguments.output)
    else:
        _emit(compare_runs(arguments.run), arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

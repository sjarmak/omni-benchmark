#!/usr/bin/env python3
"""Produce a deterministic, aggregate-only sealed telemetry summary."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable, Sequence


CONDITIONS = ("C1", "C2", "C3", "C4")
REPETITIONS = (1, 2, 3)
OUTCOMES = ("answered", "errored", "refused")
WHITELISTED_FIELDS = (
    "condition",
    "repetition",
    "generation_outcome",
    "model",
    "failure_origin",
    "terminal_failure_class",
    "latency_ms",
    "token_source",
    "token_usage",
    "cost_source",
    "cost_usd",
    "tool_call_count",
    "database_query_count",
    "telemetry_unavailable",
)


class SummaryError(ValueError):
    """Raised when cohort shape or whitelisted telemetry is invalid."""


def canonical_bytes(value: object) -> bytes:
    """Return newline-terminated canonical JSON bytes."""

    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _rounded(value: int | float) -> float:
    return round(float(value), 6)


def _median(values: Sequence[int | float]) -> float:
    return _rounded(statistics.median(values))


def tukey_distribution(
    values: Iterable[int | float], *, total: int | None = None
) -> dict[str, object]:
    """Summarize values with Tukey's median-of-halves quartiles.

    For an odd sample, the overall median is excluded from both halves.
    """

    ordered = sorted(values)
    observed = len(ordered)
    denominator = observed if total is None else total
    if denominator < observed:
        raise SummaryError("distribution total cannot be smaller than observations")
    if not ordered:
        return {
            "observed": 0,
            "missing": denominator,
            "median": None,
            "tukey_iqr": None,
        }

    median = _median(ordered)
    if observed == 1:
        q1 = q3 = median
    else:
        midpoint = observed // 2
        lower = ordered[:midpoint]
        upper = ordered[(observed + 1) // 2 :]
        q1 = _median(lower)
        q3 = _median(upper)
    return {
        "observed": observed,
        "missing": denominator - observed,
        "median": median,
        "tukey_iqr": {"q1": q1, "q3": q3},
    }


def _median_coverage(values: Iterable[int | float], *, total: int) -> dict[str, object]:
    observed_values = list(values)
    return {
        "observed": len(observed_values),
        "missing": total - len(observed_values),
        "median": _median(observed_values) if observed_values else None,
    }


def _cost_summary(values: Sequence[int | float], *, total: int) -> dict[str, object]:
    observed = len(values)
    base: dict[str, object] = {"observed": observed, "missing": total - observed}
    if observed == 0:
        return {**base, "status": "unavailable"}
    if observed != total:
        return {**base, "status": "partially_observed"}
    cost_total = sum(values)
    return {
        **base,
        "status": "fully_observed",
        "mean": _rounded(cost_total / total),
        "total": _rounded(cost_total),
    }


def _nonnegative_number(value: object, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SummaryError(f"{label} must be numeric")
    if not math.isfinite(value) or value < 0:
        raise SummaryError(f"{label} must be finite and non-negative")
    return value


def _optional_number(value: object, label: str) -> int | float | None:
    if value is None:
        return None
    return _nonnegative_number(value, label)


def _optional_count(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SummaryError(f"{label} must be a non-negative integer or null")
    return value


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SummaryError(f"{label} must be a non-empty string")
    return value


def _model_identity(value: object, location: str) -> dict[str, str | None]:
    """Project the three model-identity fields, refusing any other shape.

    A null identity is a real observation for an attempt whose token buckets
    named no model, so it is preserved rather than dropped. Version is null on
    every sealed attempt; keeping it distinguishes "no version reported" from
    "no identity reported" in the published counts.
    """

    if value is None:
        return {"name": None, "provider": None, "version": None}
    if not isinstance(value, dict):
        raise SummaryError(f"{location}.model must be an object or null")
    identity: dict[str, str | None] = {}
    for key in ("name", "provider", "version"):
        field = value.get(key)
        if field is not None and (not isinstance(field, str) or not field):
            raise SummaryError(f"{location}.model.{key} must be a string or null")
        identity[key] = field
    return identity


def _identity_counts(records: Sequence[dict[str, Any]]) -> list[dict[str, object]]:
    """Count attempts per distinct model identity, in a stable sorted order."""

    counts: Counter[tuple[str, str, str]] = Counter(
        (
            record["model"]["name"] or "unreported",
            record["model"]["provider"] or "unreported",
            record["model"]["version"] or "unreported",
        )
        for record in records
    )
    return [
        {
            "name": name,
            "provider": provider,
            "version": version,
            "attempt_count": count,
        }
        for (name, provider, version), count in sorted(counts.items())
    ]


def _validate_record(
    record: dict[str, Any], *, condition: str, repetition: int, location: str
) -> dict[str, Any]:
    projected = {field: record.get(field) for field in WHITELISTED_FIELDS}
    projected["model"] = _model_identity(projected["model"], location)
    if projected["condition"] != condition:
        raise SummaryError(f"{location}: condition does not match cohort")
    if projected["repetition"] != repetition:
        raise SummaryError(f"{location}: repetition does not match cohort")

    outcome = projected["generation_outcome"]
    if outcome not in OUTCOMES:
        raise SummaryError(f"{location}: unsupported generation_outcome")
    if condition == "C4" and outcome == "refused":
        raise SummaryError(f"{location}: C4 has no structured refusal state")
    if outcome != "answered":
        _nonempty_string(projected["failure_origin"], f"{location}.failure_origin")
        _nonempty_string(
            projected["terminal_failure_class"],
            f"{location}.terminal_failure_class",
        )

    projected["latency_ms"] = _optional_number(
        projected["latency_ms"], f"{location}.latency_ms"
    )
    projected["tool_call_count"] = _optional_count(
        projected["tool_call_count"], f"{location}.tool_call_count"
    )
    projected["database_query_count"] = _optional_count(
        projected["database_query_count"], f"{location}.database_query_count"
    )

    token_source = _nonempty_string(
        projected["token_source"], f"{location}.token_source"
    )
    token_usage = projected["token_usage"]
    if token_usage is None:
        if token_source != "unavailable":
            raise SummaryError(f"{location}: null token_usage must be unavailable")
    elif isinstance(token_usage, dict):
        normalized_tokens = {
            key: _nonnegative_number(
                token_usage.get(key), f"{location}.token_usage.{key}"
            )
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
        if (
            normalized_tokens["input_tokens"] + normalized_tokens["output_tokens"]
            != normalized_tokens["total_tokens"]
        ):
            raise SummaryError(f"{location}: token usage does not reconcile")
        if token_source == "unavailable":
            raise SummaryError(
                f"{location}: observed token_usage cannot be unavailable"
            )
        projected["token_usage"] = normalized_tokens
    else:
        raise SummaryError(f"{location}: token_usage must be an object or null")

    cost_source = _nonempty_string(projected["cost_source"], f"{location}.cost_source")
    projected["cost_usd"] = _optional_number(
        projected["cost_usd"], f"{location}.cost_usd"
    )
    if projected["cost_usd"] is None and cost_source != "unavailable":
        raise SummaryError(f"{location}: null cost_usd must be unavailable")
    if projected["cost_usd"] is not None and cost_source == "unavailable":
        raise SummaryError(f"{location}: observed cost_usd cannot be unavailable")
    if condition == "C4" and (
        projected["cost_usd"] is not None or cost_source != "unavailable"
    ):
        raise SummaryError(f"{location}: C4 cost must remain unavailable")

    unavailable = projected["telemetry_unavailable"]
    if not isinstance(unavailable, list) or any(
        not isinstance(item, str) or not item for item in unavailable
    ):
        raise SummaryError(f"{location}: telemetry_unavailable must be a string list")
    if len(set(unavailable)) != len(unavailable):
        raise SummaryError(f"{location}: telemetry_unavailable contains duplicates")
    return projected


def _read_cohort(
    path: Path, *, condition: str, repetition: int, expected: int
) -> tuple[list[dict[str, Any]], dict[str, object]]:
    cohort = f"{condition.lower()}-r{repetition}"
    if not path.is_file():
        raise SummaryError(f"{cohort}: expected generation.jsonl is missing")
    content = path.read_bytes()
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise SummaryError(f"{cohort}: generation.jsonl is not UTF-8") from error
    if len(lines) != expected:
        raise SummaryError(f"{cohort}: expected {expected} records, found {len(lines)}")

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise SummaryError(
                f"{cohort}: invalid JSON on line {line_number}"
            ) from error
        if not isinstance(raw, dict):
            raise SummaryError(f"{cohort}: line {line_number} must be an object")
        records.append(
            _validate_record(
                raw,
                condition=condition,
                repetition=repetition,
                location=f"{cohort}:{line_number}",
            )
        )

    relative_path = f"cohorts/{cohort}/generation.jsonl"
    source = {
        "byte_count": len(content),
        "cohort": cohort,
        "path": relative_path,
        "record_count": len(records),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    return records, source


def _values(records: Iterable[dict[str, Any]], field: str) -> list[int | float]:
    values: list[int | float] = []
    for record in records:
        if field.startswith("token_usage."):
            token_usage = record["token_usage"]
            value = token_usage.get(field.split(".", 1)[1]) if token_usage else None
        else:
            value = record[field]
        if value is not None:
            values.append(value)
    return values


def _counter(records: Iterable[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                value for record in records if (value := record[field]) is not None
            ).items()
        )
    )


def _outcome_resource_medians(
    records: Sequence[dict[str, Any]], outcome: str
) -> dict[str, object]:
    selected = [record for record in records if record["generation_outcome"] == outcome]
    fields = {
        "latency_ms": "latency_ms",
        "total_tokens": "token_usage.total_tokens",
        "tool_call_count": "tool_call_count",
        "database_query_count": "database_query_count",
        "cost_usd": "cost_usd",
    }
    medians: dict[str, object] = {"attempt_count": len(selected), "coverage": {}}
    for output_name, field in fields.items():
        observed = _values(selected, field)
        medians[output_name] = _median(observed) if observed else None
        medians["coverage"][output_name] = {
            "observed": len(observed),
            "missing": len(selected) - len(observed),
        }
    return medians


def _condition_summary(
    records: Sequence[dict[str, Any]], condition: str
) -> dict[str, object]:
    total = len(records)
    outcome_counts = Counter(record["generation_outcome"] for record in records)
    declared_unavailable = Counter(
        item for record in records for item in record["telemetry_unavailable"]
    )
    telemetry = {
        "latency_ms": tukey_distribution(_values(records, "latency_ms"), total=total),
        "token_usage": {
            name: tukey_distribution(
                _values(records, f"token_usage.{name}"), total=total
            )
            for name in ("input_tokens", "output_tokens", "total_tokens")
        },
        "tool_call_count": _median_coverage(
            _values(records, "tool_call_count"), total=total
        ),
        "database_query_count": _median_coverage(
            _values(records, "database_query_count"), total=total
        ),
        "cost_usd": _cost_summary(_values(records, "cost_usd"), total=total),
    }
    return {
        "attempt_count": total,
        "repetitions": dict(
            sorted(Counter(str(record["repetition"]) for record in records).items())
        ),
        "outcomes": {
            outcome: (
                None
                if condition == "C4" and outcome == "refused"
                else outcome_counts[outcome]
            )
            for outcome in OUTCOMES
        },
        "refusal": {
            "status": "unavailable" if condition == "C4" else "observed",
            "count": None if condition == "C4" else outcome_counts["refused"],
        },
        "model_identities": _identity_counts(records),
        "failure_origins": _counter(records, "failure_origin"),
        "failure_classes": _counter(records, "terminal_failure_class"),
        "sources": {
            "token_source": _counter(records, "token_source"),
            "cost_source": _counter(records, "cost_source"),
        },
        "declared_unavailable": dict(sorted(declared_unavailable.items())),
        "telemetry": telemetry,
        "outcome_resource_medians": {
            outcome: _outcome_resource_medians(records, outcome)
            for outcome in ("answered", "errored")
        },
    }


def summarize_run(
    run_root: Path, *, expected_per_cohort: int = 89
) -> dict[str, object]:
    """Read only the twelve generation cohort files and return safe aggregates."""

    if expected_per_cohort <= 0:
        raise SummaryError("expected_per_cohort must be positive")
    records_by_condition: dict[str, list[dict[str, Any]]] = {
        condition: [] for condition in CONDITIONS
    }
    source_files: list[dict[str, object]] = []
    for condition in CONDITIONS:
        for repetition in REPETITIONS:
            path = (
                run_root
                / "cohorts"
                / f"{condition.lower()}-r{repetition}"
                / "generation.jsonl"
            )
            records, source = _read_cohort(
                path,
                condition=condition,
                repetition=repetition,
                expected=expected_per_cohort,
            )
            records_by_condition[condition].extend(records)
            source_files.append(source)

    source_files.sort(key=lambda source: str(source["path"]))
    expected_per_condition = expected_per_cohort * len(REPETITIONS)
    conditions = {
        condition: _condition_summary(records_by_condition[condition], condition)
        for condition in CONDITIONS
    }
    if any(
        value["attempt_count"] != expected_per_condition
        for value in conditions.values()
    ):
        raise SummaryError("condition attempt count invariant failed")

    summary: dict[str, object] = {
        "artifact_kind": "sealed_telemetry_summary",
        "schema_version": 1,
        "quartile_method": "tukey_median_of_halves_excluding_odd_median",
        "expected": {
            "cohort_count": len(CONDITIONS) * len(REPETITIONS),
            "attempts_per_cohort": expected_per_cohort,
            "attempts_per_condition": expected_per_condition,
        },
        "conditions": conditions,
        "provenance": {
            "input_kind": "generation_records_only",
            "whitelisted_fields": list(WHITELISTED_FIELDS),
            "source_files": source_files,
            "source_set_hash_basis": "canonical source_files JSON",
            "source_set_sha256": hashlib.sha256(
                canonical_bytes(source_files)
            ).hexdigest(),
        },
        "aggregate_hash_basis": "canonical JSON without aggregate_payload_sha256",
    }
    summary["aggregate_payload_sha256"] = hashlib.sha256(
        canonical_bytes(summary)
    ).hexdigest()
    return summary


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--expected-per-cohort", type=int, default=89)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    summary = summarize_run(
        arguments.run_root, expected_per_cohort=arguments.expected_per_cohort
    )
    payload = canonical_bytes(summary)
    if arguments.output is None:
        sys.stdout.buffer.write(payload)
    else:
        with arguments.output.open("xb") as handle:
            handle.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

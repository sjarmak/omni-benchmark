#!/usr/bin/env python3
"""Put C5 on the same dev-A questions as every other condition.

The direct conditions were frozen over 18 databases and the governed conditions
over the 16 with verified deployments, and the direct freeze is itself missing
14 dev-A questions, so no two of these arms were scored on the same question set.
`derive` narrows a frozen selection to the intersection of the governed
execution frame and the direct freeze, which lets one scorer run per selection
produce C1, C2, C3, C4, and C5 aggregates over identical questions. `report`
merges the resulting receipts into one aggregate comparison.

Every input here is public: split membership, attempt identities, and generation
outcomes. No gold, no per-question correctness, and no hidden annotation is read,
written, or inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from omni_benchmark.baseline_batch import (
    c4_dev_a_experiment_schedule,
    load_committed_baseline_schedule,
)

STATE_ROOT = Path("experiments/autoresearch/state")
SCORERS = ("official", "sensitivity")
DIRECT_KIND = "public-direct-baseline-freeze"
GOVERNED_KINDS = frozenset(
    {
        "public-c4-baseline-freeze",
        "e02-dev-a-c4-freeze",
        "c5-dev-a-c4-freeze",
    }
)


class MatchedFrameError(ValueError):
    """Raised when the matched frame cannot be built from public inputs."""


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MatchedFrameError(f"{path.name} is not a JSON object")
    return value


def governed_instance_ids(workspace: Path, system_commit: str, run_id: str) -> set[str]:
    """Read the committed C4/C5 dev-A frame as public question identities."""
    full = load_committed_baseline_schedule(workspace, system_commit, run_id=run_id)
    schedule = c4_dev_a_experiment_schedule(workspace, system_commit, full)
    return {attempt.instance_id for attempt in schedule.attempts}


def matched_instance_ids(
    workspace: Path,
    system_commit: str,
    run_id: str,
    direct_selection: Mapping[str, Any],
) -> set[str]:
    """Intersect the governed execution frame with the direct freeze."""
    if direct_selection.get("kind") != DIRECT_KIND:
        raise MatchedFrameError("frame source is not the direct baseline freeze")
    direct = {
        entry["instance_id"]
        for entry in direct_selection.get("entries", [])
        if isinstance(entry, Mapping)
    }
    governed = governed_instance_ids(workspace, system_commit, run_id)
    matched = governed & direct
    if not matched:
        raise MatchedFrameError("governed and direct frames do not intersect")
    return matched


def _restrict_direct(
    selection: Mapping[str, Any], instance_ids: set[str]
) -> dict[str, Any]:
    kept = [
        entry for entry in selection["entries"] if entry["instance_id"] in instance_ids
    ]
    dispositions = Counter(entry["disposition"] for entry in kept)
    derived = dict(selection)
    derived["entries"] = kept
    derived["counts"] = {
        "continuation": dispositions["continuation"],
        "preserved": dispositions["preserved"],
        "total": len(kept),
    }
    return derived


def _generation_outcomes(
    workspace: Path, selection: Mapping[str, Any], entries: list[Mapping[str, Any]]
) -> Counter[str]:
    """Count answered, errored, and refused from hash-verified generation records."""
    output_root = selection.get("output_root")
    if not isinstance(output_root, str):
        raise MatchedFrameError("governed selection output root is invalid")
    outcomes: Counter[str] = Counter()
    for entry in entries:
        path = (
            workspace
            / output_root
            / entry["database"]
            / "c4"
            / f"{entry['instance_id']}-r{entry['repetition']}"
            / "generation.jsonl"
        )
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["generation_sha256"]:
            raise MatchedFrameError(
                "generation artifact does not match its frozen hash"
            )
        lines = content.splitlines()
        if len(lines) != 1:
            raise MatchedFrameError("generation artifact must hold one record")
        record = json.loads(lines[0])
        if record.get("attempt_id") != entry["attempt_id"]:
            raise MatchedFrameError("generation artifact identity does not match")
        outcome = record.get("generation_outcome")
        if outcome not in ("answered", "errored", "refused"):
            raise MatchedFrameError("generation outcome is not recognised")
        outcomes[outcome] += 1
    return outcomes


def _restrict_governed(
    workspace: Path, selection: Mapping[str, Any], instance_ids: set[str]
) -> dict[str, Any]:
    kept = [
        entry for entry in selection["entries"] if entry["instance_id"] in instance_ids
    ]
    scheduled = selection["scheduled_entries"]
    outcomes = _generation_outcomes(workspace, selection, kept)
    derived = dict(selection)
    derived["entries"] = kept
    derived["counts"] = {
        "answerable_attempts": len(kept),
        "answered": outcomes["answered"],
        "attempts": len(kept),
        "databases": len({entry["database"] for entry in kept}),
        "errored": outcomes["errored"],
        "refused": outcomes["refused"],
        "scheduled_attempts": len(scheduled),
        "scheduled_databases": len({entry["database"] for entry in scheduled}),
        "unscorable_attempts": len(scheduled) - len(kept),
    }
    return derived


def _write_exclusive(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def _derive(arguments: argparse.Namespace) -> int:
    workspace = arguments.workspace.resolve(strict=True)
    destination = workspace / arguments.destination
    if destination.parent != workspace / STATE_ROOT:
        raise MatchedFrameError("destination must be an autoresearch state artifact")
    direct = _read_json(workspace / arguments.frame_source)
    instance_ids = matched_instance_ids(
        workspace, arguments.system_commit, arguments.run_id, direct
    )
    if arguments.expected_questions != len(instance_ids):
        raise MatchedFrameError(
            f"matched frame holds {len(instance_ids)} questions, "
            f"not {arguments.expected_questions}"
        )
    source = _read_json(workspace / arguments.source)
    kind = source.get("kind")
    if kind == DIRECT_KIND:
        derived = _restrict_direct(source, instance_ids)
        attempts = len(derived["entries"])
    elif kind in GOVERNED_KINDS:
        derived = _restrict_governed(workspace, source, instance_ids)
        attempts = derived["counts"]["attempts"]
        if attempts != len(instance_ids):
            raise MatchedFrameError("governed selection does not cover the frame once")
    else:
        raise MatchedFrameError("source selection kind is not supported")
    content = canonical_bytes(derived)
    _write_exclusive(destination, content)
    print(
        json.dumps(
            {
                "attempts": attempts,
                "destination": arguments.destination.as_posix(),
                "kind": kind,
                "questions": len(instance_ids),
                "selection_sha256": hashlib.sha256(content).hexdigest(),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _condition_rates(receipt: Mapping[str, Any], scorer: str) -> dict[str, Any]:
    block = receipt.get(scorer)
    if not isinstance(block, Mapping):
        raise MatchedFrameError(f"receipt has no {scorer} block")
    by_condition = block.get("by_condition")
    if not isinstance(by_condition, Mapping):
        raise MatchedFrameError(f"{scorer} block has no per-condition counts")
    result: dict[str, Any] = {}
    for condition, counts in sorted(by_condition.items()):
        scoreable = counts["scoreable_attempts"]
        if not isinstance(scoreable, int) or scoreable <= 0:
            raise MatchedFrameError("scoreable attempts are invalid")
        result[condition] = {
            "accuracy_percent": round(100.0 * counts["correct"] / scoreable, 1),
            "correct": counts["correct"],
            "refused_or_error": counts["refused_or_error"],
            "scoreable_attempts": scoreable,
            "wrong_answer": counts["wrong_answer"],
        }
    return result


def _labelled_receipt(value: str) -> tuple[str | None, Path]:
    """Parse ``--receipt PATH`` or ``--receipt ARM=PATH``.

    C5 executes under the C4 condition scaffold, so two governed receipts carry
    the same condition key and would collide on merge. An explicit arm label
    renames the single condition a receipt reports.
    """

    label, separator, path = value.partition("=")
    if not separator:
        return None, Path(value)
    if not label.strip() or not path.strip():
        raise argparse.ArgumentTypeError("arm label and receipt path are required")
    return label, Path(path)


def _report(arguments: argparse.Namespace) -> int:
    workspace = arguments.workspace.resolve(strict=True)
    labels = [label for label, _ in arguments.receipt]
    receipts = [_read_json(workspace / path) for _, path in arguments.receipt]
    release = {receipt.get("release_sha256") for receipt in receipts}
    if len(release) != 1:
        raise MatchedFrameError("receipts do not share one gold release")
    comparison: dict[str, Any] = {
        "kind": arguments.kind,
        "release_sha256": release.pop(),
        "schema_version": 1,
        "selection_sha256": sorted(receipt["selection_sha256"] for receipt in receipts),
    }
    for scorer in SCORERS:
        merged: dict[str, Any] = {}
        for label, receipt in zip(labels, receipts):
            rates_by_condition = _condition_rates(receipt, scorer)
            if label is not None and len(rates_by_condition) != 1:
                raise MatchedFrameError("an arm label needs a single-condition receipt")
            for condition, rates in rates_by_condition.items():
                arm = label if label is not None else condition
                if arm in merged:
                    raise MatchedFrameError(f"{arm} appears in two receipts")
                merged[arm] = rates
        comparison[scorer] = merged
    content = canonical_bytes(comparison)
    if arguments.destination is not None:
        _write_exclusive(workspace / arguments.destination, content)
    print(content.decode().rstrip("\n"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    derive = subparsers.add_parser("derive")
    derive.add_argument("--workspace", type=Path, required=True)
    derive.add_argument("--system-commit", required=True)
    derive.add_argument("--run-id", required=True)
    derive.add_argument("--frame-source", type=Path, required=True)
    derive.add_argument("--source", type=Path, required=True)
    derive.add_argument("--destination", type=Path, required=True)
    derive.add_argument("--expected-questions", type=int, required=True)
    derive.set_defaults(handler=_derive)

    report = subparsers.add_parser("report")
    report.add_argument("--workspace", type=Path, required=True)
    report.add_argument(
        "--receipt", type=_labelled_receipt, action="append", required=True
    )
    report.add_argument("--kind", default="c5-matched-dev-a-comparison")
    report.add_argument("--destination", type=Path)
    report.set_defaults(handler=_report)

    arguments = parser.parse_args(argv)
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())

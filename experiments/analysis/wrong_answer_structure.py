"""Aggregate SQL-shape diagnostics for the frozen dev-A baseline.

This reads only immutable score envelopes and their hash-bound candidate
generation records. It never reads gold SQL, result values, or hidden
annotations, and it emits no question IDs or SQL text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
FEATURES = (
    "aggregate",
    "distinct",
    "grouped",
    "join",
    "multi_relation",
    "nested",
    "where",
    "window",
)


def sql_features(sql: str) -> dict[str, bool | int]:
    """Return value-free structural features for one PostgreSQL query."""
    tree = sqlglot.parse_one(sql, read="postgres")
    relations = {table.sql(dialect="postgres") for table in tree.find_all(exp.Table)}
    return {
        "aggregate": any(tree.find_all(exp.AggFunc)),
        "distinct": any(
            select.args.get("distinct") is not None
            for select in tree.find_all(exp.Select)
        ),
        "grouped": any(tree.find_all(exp.Group)),
        "join": any(tree.find_all(exp.Join)),
        "multi_relation": len(relations) >= 2,
        "nested": any(tree.find_all(exp.Subquery)),
        "relation_count": len(relations),
        "where": any(tree.find_all(exp.Where)),
        "window": any(tree.find_all(exp.Window)),
    }


def _bounded_bytes(path: Path) -> bytes:
    metadata = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > MAX_ARTIFACT_BYTES
    ):
        raise ValueError(f"unsafe or oversized artifact: {path}")
    content = path.read_bytes()
    if len(content) != metadata.st_size:
        raise ValueError(f"artifact changed while reading: {path}")
    return content


def _json(path: Path) -> Any:
    return json.loads(_bounded_bytes(path))


def _generation_index(roots: list[Path]) -> dict[str, list[Path]]:
    indexed: dict[str, list[Path]] = defaultdict(list)
    for root in roots:
        for path in root.rglob("generation.jsonl"):
            content = _bounded_bytes(path)
            indexed[hashlib.sha256(content).hexdigest()].append(path)
    return dict(indexed)


def _record_for_attempt(
    paths: list[Path], attempt_id: str, record_sha256: str
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in paths:
        for line in _bounded_bytes(path).splitlines(keepends=True):
            if hashlib.sha256(line).hexdigest() != record_sha256:
                continue
            record = json.loads(line)
            if isinstance(record, dict) and record.get("attempt_id") == attempt_id:
                matches.append(record)
    if len(matches) != 1:
        raise ValueError("score attempt does not resolve to one generation record")
    return matches[0]


def _attempt_identity(attempt_id: str) -> tuple[str, str]:
    parts = attempt_id.rsplit(":", 3)
    if len(parts) != 4 or parts[2] not in {"C1", "C2", "C3"}:
        raise ValueError("invalid direct attempt identity")
    return parts[1], parts[2]


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["condition"], row["outcome"])].append(row)
    summary: dict[str, Any] = {}
    for (condition, outcome), values in sorted(grouped.items()):
        key = f"{condition}:{outcome}"
        parsed = [value for value in values if value["features"] is not None]
        summary[key] = {
            "count": len(values),
            "feature_counts": {
                feature: sum(bool(value["features"][feature]) for value in parsed)
                for feature in FEATURES
            },
            "mean_relation_count": (
                None
                if not parsed
                else round(
                    sum(value["features"]["relation_count"] for value in parsed)
                    / len(parsed),
                    3,
                )
            ),
            "parsed_sql_count": len(parsed),
        }
    return summary


def _wrong_rates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for condition in ("C1", "C2", "C3"):
        values = [
            row
            for row in rows
            if row["condition"] == condition and row["features"] is not None
        ]
        condition_result: dict[str, Any] = {}
        for feature in FEATURES:
            present = [row for row in values if row["features"][feature]]
            absent = [row for row in values if not row["features"][feature]]
            condition_result[feature] = {
                "absent": [
                    sum(row["outcome"] == "wrong_answer" for row in absent),
                    len(absent),
                ],
                "present": [
                    sum(row["outcome"] == "wrong_answer" for row in present),
                    len(present),
                ],
            }
        result[condition] = condition_result
    return result


def _paired_patterns(score_attempts: list[dict[str, Any]]) -> dict[str, int]:
    paired: dict[str, dict[str, str]] = defaultdict(dict)
    for attempt in score_attempts:
        if attempt.get("status") != "scored":
            continue
        question, condition = _attempt_identity(attempt["attempt_id"])
        paired[question][condition] = attempt["outcome"]
    patterns = Counter(
        ",".join(
            f"{condition}={outcomes[condition]}" for condition in ("C1", "C2", "C3")
        )
        for outcomes in paired.values()
        if set(outcomes) == {"C1", "C2", "C3"}
    )
    return dict(sorted(patterns.items(), key=lambda item: (-item[1], item[0])))


def analyze(workspace: Path) -> dict[str, Any]:
    score_root = (
        workspace
        / "experiments/autoresearch/raw/public-direct-baseline-dev-a-scores-v1"
    )
    receipt = _json(score_root / "receipt.json")
    score_path = workspace / receipt["artifacts"]["official"]["path"]
    score_content = _bounded_bytes(score_path)
    if (
        hashlib.sha256(score_content).hexdigest()
        != receipt["artifacts"]["official"]["sha256"]
    ):
        raise ValueError("official score artifact hash changed")
    score = json.loads(score_content)
    freeze = _json(
        workspace
        / "experiments/autoresearch/state/public-direct-baseline-freeze-v1.json"
    )
    raw_root = workspace / "experiments/autoresearch/raw"
    index = _generation_index(
        [raw_root / freeze["original_run_id"], raw_root / freeze["continuation_run_id"]]
    )
    rows: list[dict[str, Any]] = []
    for attempt in score["attempts"]:
        if attempt.get("status") != "scored" or attempt.get("outcome") not in {
            "correct",
            "wrong_answer",
        }:
            continue
        paths = index.get(attempt["generation_sha256"], [])
        record = _record_for_attempt(
            paths, attempt["attempt_id"], attempt["generation_record_sha256"]
        )
        _, condition = _attempt_identity(attempt["attempt_id"])
        sql = record.get("generated_sql")
        features = None
        if isinstance(sql, str) and sql:
            try:
                features = sql_features(sql)
            except sqlglot.errors.SqlglotError:
                features = None
        rows.append(
            {
                "condition": condition,
                "features": features,
                "outcome": attempt["outcome"],
            }
        )
    return {
        "artifact_sha256": receipt["artifacts"]["official"]["sha256"],
        "paired_patterns": _paired_patterns(score["attempts"]),
        "row_count": len(rows),
        "schema_version": 1,
        "sql_shape_summary": _summarize(rows),
        "wrong_rates_by_feature": _wrong_rates(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(analyze(arguments.workspace.resolve(strict=True)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

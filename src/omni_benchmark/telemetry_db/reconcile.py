"""Reconcile the loaded telemetry database against the frozen analysis artifacts.

The verification gate in ``docs/telemetry-db-plan.md`` requires that every
aggregate queried from the database agree with the frozen JSON outputs under
``experiments/analysis`` and with the sealed ``aggregate.json`` files before
the Omni model is trusted. ``reconcile`` projects each frozen artifact onto the
subset of values the database can reproduce, recomputes that subset from
database rows (``reconcile_observed``), and compares the two trees path by
path. Counts and strings must agree exactly; every rate, cost, and median is
published at six decimals, so those compare within an absolute 1e-6.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omni_benchmark.telemetry_db import reconcile_observed as observed
from omni_benchmark.telemetry_db.sealed_readers import SEALED_RUN_ID

FLOAT_TOLERANCE = 1e-6
ANALYSIS_DIR = Path("experiments/analysis")
SEALED_SCORE_DIR = Path("runs/preserved") / SEALED_RUN_ID / "score"
ARTIFACT_PATHS: Mapping[str, Path] = {
    "c5_matched_122": ANALYSIS_DIR / "c5-matched-122-comparison-v1.json",
    "matched_122_rollup": ANALYSIS_DIR / "matched-122-cost-time-rollup-v1.json",
    "sealed_telemetry_summary": ANALYSIS_DIR / "sealed-telemetry-summary-v2.json",
    "sealed_correctness_matrix": ANALYSIS_DIR / "sealed-correctness-matrix-v1.json",
    "c5_telemetry_comparison": ANALYSIS_DIR / "c5-telemetry-comparison-v1.json",
    "governed_query_path_tally": ANALYSIS_DIR / "governed-query-path-tally-v2.json",
}
SEALED_SCORERS: tuple[str, ...] = ("official_soft_ex", "sensitivity")
#: governed-query-path-tally arm label -> ``telemetry.run.run_id`` it was read
#: from. The tally artifact records only labels; these roots are the ones
#: passed on its command line (research log, 2026-08-30 schema-2 correction).
TALLY_ARM_RUNS: Mapping[str, str] = {
    "dev-a-c4": "public-c4-baseline-v8",
    "dev-a-c5": "c5-dev-a-v4",
    "dev-a-e02": "e02-dev-a-v6",
    "sealed-c4": "sealed-c4-r1",
    "sealed-c4-r2": "sealed-c4-r2",
    "sealed-c4-r3": "sealed-c4-r3",
}
GROUPS: tuple[str, ...] = (
    "dev_a_frame",
    "matched_122_rollup",
    "sealed_telemetry",
    "sealed_aggregate",
    "correctness_matrix",
    "c5_telemetry_comparison",
    "query_path_tally",
)
MATCH = "match"


class ReconcileError(ValueError):
    """Raised when an artifact or the database cannot be reconciled."""


@dataclass(frozen=True)
class Check:
    """One scalar comparison between a frozen artifact and the database."""

    group: str
    path: str
    expected: object
    observed: object
    tolerance: str
    status: str


@dataclass(frozen=True)
class FrozenArtifacts:
    """The frozen JSON documents a reconciliation compares against."""

    documents: Mapping[str, Mapping[str, Any]]
    sources: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def require(self, name: str) -> Mapping[str, Any]:
        document = self.documents.get(name)
        if document is None:
            raise ReconcileError(f"frozen artifact {name!r} was not loaded")
        return document


@dataclass(frozen=True)
class Reconciliation:
    """Every check run plus the provenance the report records."""

    checks: tuple[Check, ...]
    load_runs: tuple[Mapping[str, object], ...]
    sources: Mapping[str, Mapping[str, object]]

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(check for check in self.checks if check.status != MATCH)

    def summary(self) -> dict[str, object]:
        by_status: dict[str, int] = {}
        for check in self.checks:
            by_status[check.status] = by_status.get(check.status, 0) + 1
        return {
            "checks": len(self.checks),
            "matches": by_status.get(MATCH, 0),
            "failures": len(self.failures),
            "by_status": dict(sorted(by_status.items())),
        }


# --- frozen artifacts ----------------------------------------------------------


def _read_json(path: Path) -> tuple[Mapping[str, Any], dict[str, object]]:
    if not path.is_file():
        raise ReconcileError(f"frozen artifact missing: {path}")
    content = path.read_bytes()
    try:
        document = json.loads(content)
    except ValueError as error:
        raise ReconcileError(f"{path}: invalid JSON: {error}") from error
    if not isinstance(document, dict):
        raise ReconcileError(f"{path}: top level must be an object")
    return document, {"sha256": hashlib.sha256(content).hexdigest()}


def load_frozen_artifacts(repo_root: Path) -> FrozenArtifacts:
    """Read every frozen artifact the reconciliation compares against."""
    documents: dict[str, Mapping[str, Any]] = {}
    sources: dict[str, dict[str, object]] = {}
    paths = dict(ARTIFACT_PATHS)
    for scorer in SEALED_SCORERS:
        paths[f"sealed_aggregate/{scorer}"] = (
            SEALED_SCORE_DIR / scorer / "aggregate.json"
        )
    for name, relative in paths.items():
        documents[name], digest = _read_json(repo_root / relative)
        sources[name] = {"path": relative.as_posix(), **digest}
    return FrozenArtifacts(documents=documents, sources=sources)


# --- comparison ------------------------------------------------------------------


def flatten(value: object, prefix: str = "") -> dict[str, object]:
    """Map every leaf of a nested JSON value to its dotted path.

    Empty containers are leaves, so an artifact that publishes ``{}`` is
    still checked against what the database produced.
    """
    if isinstance(value, Mapping) and value:
        leaves: dict[str, object] = {}
        for key, item in value.items():
            leaves.update(flatten(item, f"{prefix}.{key}" if prefix else str(key)))
        return leaves
    if isinstance(value, (list, tuple)) and value:
        leaves = {}
        for index, item in enumerate(value):
            leaves.update(flatten(item, f"{prefix}[{index}]"))
        return leaves
    return {prefix: value}


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compare_scalar(expected: object, observed: object) -> tuple[str, bool]:
    """Return the tolerance applied and whether the values agree under it."""
    if isinstance(expected, float):
        return (
            f"abs<={FLOAT_TOLERANCE:g}",
            _is_number(observed) and abs(observed - expected) <= FLOAT_TOLERANCE,
        )
    if _is_number(expected):
        return "exact", _is_number(observed) and observed == expected
    return "exact", type(observed) is type(expected) and observed == expected


def build_checks(group: str, expected: object, observed_tree: object) -> list[Check]:
    """Compare two trees leaf by leaf; observed-only leaves are failures too."""
    expected_leaves = flatten(expected)
    observed_leaves = flatten(observed_tree)
    checks: list[Check] = []
    for path in sorted(set(expected_leaves) | set(observed_leaves)):
        if path not in observed_leaves:
            checks.append(
                Check(group, path, expected_leaves[path], None, "exact", "missing")
            )
            continue
        if path not in expected_leaves:
            checks.append(
                Check(group, path, None, observed_leaves[path], "exact", "unexpected")
            )
            continue
        tolerance, agrees = compare_scalar(expected_leaves[path], observed_leaves[path])
        status = MATCH if agrees else "mismatch"
        checks.append(
            Check(
                group,
                path,
                expected_leaves[path],
                observed_leaves[path],
                tolerance,
                status,
            )
        )
    return checks


# --- expected projections --------------------------------------------------------


def _expected_frame(document: Mapping[str, Any]) -> dict[str, Any]:
    fields = (*observed.SCORE_OUTCOMES, "scoreable_attempts", "accuracy_percent")
    return {
        scorer: {
            arm: {name: document[scorer][arm][name] for name in fields}
            for arm in observed.FRAME_ARMS
        }
        for scorer in observed.SCORERS
    }


def _expected_rollup_arm(arm: Mapping[str, Any]) -> dict[str, Any]:
    spend = {"coverage": arm["spend"]["coverage"]}
    projected = {
        "attempts": arm["attempts"],
        "official_correct": arm["official_correct"],
        "wall_time": arm["wall_time"],
        "distributions": arm["distributions"],
        "spend": spend,
    }
    if arm["spend"]["cost_measured"]:
        spend["total_usd"] = arm["spend"]["total_usd"]
        spend["median_usd"] = arm["spend"]["median_usd"]
        projected["cost_per_correct_answer_usd"] = arm["cost_per_correct_answer_usd"]
    return projected


def _expected_rollup(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "question_count": document["frame"]["question_count"],
        "arms": {
            arm: _expected_rollup_arm(document["arms"][arm])
            for arm in observed.FRAME_ARMS
        },
    }


def _expected_sealed_aggregate(artifacts: FrozenArtifacts) -> dict[str, Any]:
    expected: dict[str, Any] = {}
    for scorer in SEALED_SCORERS:
        conditions = artifacts.require(f"sealed_aggregate/{scorer}")["report"][
            "conditions"
        ]
        expected[scorer] = {
            condition: {
                **{name: block[name] for name in observed.SEALED_AGGREGATE_FIELDS},
                "generation_outcomes": block["generation_outcomes"],
                "terminal_failure_classes": block["terminal_failure_classes"],
            }
            for condition, block in conditions.items()
        }
    return expected


def _expected_matrix(document: Mapping[str, Any]) -> dict[str, Any]:
    arm_summary = document["arm_summary"]
    return {
        "arm_summary": {
            scorer: {
                condition: block["pooled"] for condition, block in per_scorer.items()
            }
            for scorer, per_scorer in arm_summary.items()
            if scorer != "terminal_failure_classes"
        },
        "terminal_failure_classes": arm_summary["terminal_failure_classes"],
    }


def _expected_comparison(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "matched_attempt_count": document["matched_attempt_count"],
        "runs": {
            label: {"attempt_count": run["attempt_count"], "matched": run["matched"]}
            for label, run in document["runs"].items()
        },
    }


# --- observed trees -----------------------------------------------------------------


def _observed_sealed_aggregate(conn: Any) -> dict[str, Any]:
    tallies = observed.sealed_outcome_tallies(conn)
    result: dict[str, Any] = {}
    for scorer, conditions in observed.sealed_aggregates(conn, SEALED_RUN_ID).items():
        result[scorer] = {}
        for condition, fields in conditions.items():
            tally = tallies.get(condition)
            if tally is None:
                raise ReconcileError(f"no sealed attempts loaded for {condition}")
            result[scorer][condition] = {
                **fields,
                "generation_outcomes": tally["generation_outcomes"],
                "terminal_failure_classes": tally["terminal_failure_classes"],
            }
    return result


def _observed_matrix(conn: Any) -> dict[str, Any]:
    tallies = observed.sealed_outcome_tallies(conn)
    return {
        "arm_summary": observed.pooled_matrix_summary(conn, SEALED_RUN_ID),
        "terminal_failure_classes": {
            condition: tally["failure_classes_including_none"]
            for condition, tally in tallies.items()
        },
    }


def _comparison_runs(document: Mapping[str, Any]) -> dict[str, str]:
    return {
        label: Path(run["run_root"]).name for label, run in document["runs"].items()
    }


def _observed_tally(conn: Any, document: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label in document["arms"]:
        run_id = TALLY_ARM_RUNS.get(label)
        if run_id is None:
            raise ReconcileError(f"no run mapped for tally arm {label!r}")
        result[label] = observed.query_path_tally(conn, run_id)
    return result


def group_checks(group: str, conn: Any, artifacts: FrozenArtifacts) -> list[Check]:
    """Run one reconciliation group against the database."""
    if group == "dev_a_frame":
        expected = _expected_frame(artifacts.require("c5_matched_122"))
        return build_checks(group, expected, observed.dev_a_frame_counts(conn))
    if group == "matched_122_rollup":
        expected = _expected_rollup(artifacts.require("matched_122_rollup"))
        return build_checks(group, expected, observed.matched_frame_rollup(conn))
    if group == "sealed_telemetry":
        conditions = artifacts.require("sealed_telemetry_summary")["conditions"]
        summaries = observed.sealed_condition_summaries(conn, tuple(conditions))
        return build_checks(group, conditions, summaries)
    if group == "sealed_aggregate":
        expected = _expected_sealed_aggregate(artifacts)
        return build_checks(group, expected, _observed_sealed_aggregate(conn))
    if group == "correctness_matrix":
        expected = _expected_matrix(artifacts.require("sealed_correctness_matrix"))
        return build_checks(group, expected, _observed_matrix(conn))
    if group == "c5_telemetry_comparison":
        document = artifacts.require("c5_telemetry_comparison")
        comparison = observed.run_comparison(conn, _comparison_runs(document))
        return build_checks(group, _expected_comparison(document), comparison)
    if group == "query_path_tally":
        document = artifacts.require("governed_query_path_tally")
        return build_checks(group, document["arms"], _observed_tally(conn, document))
    raise ReconcileError(f"unknown reconciliation group {group!r}")


def reconcile(
    conn: Any, artifacts: FrozenArtifacts, groups: Sequence[str] = GROUPS
) -> Reconciliation:
    """Run every requested group and collect the checks with load provenance."""
    checks: list[Check] = []
    for group in groups:
        checks.extend(group_checks(group, conn, artifacts))
    return Reconciliation(
        checks=tuple(checks),
        load_runs=tuple(observed.load_runs(conn)),
        sources=dict(artifacts.sources),
    )


# --- presentation --------------------------------------------------------------------


def _cell(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def render_table(checks: Sequence[Check]) -> str:
    """Plain-text table: check, expected, observed, status."""
    rows = [("check", "expected", "observed", "status")]
    rows.extend(
        (f"{c.group}:{c.path}", _cell(c.expected), _cell(c.observed), c.status)
        for c in checks
    )
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = [
        "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in rows
    ]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(lines)


def to_report(reconciliation: Reconciliation) -> dict[str, object]:
    """JSON-ready report; carries no connection details."""
    return {
        "artifact_kind": "telemetry_db_reconciliation",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "float_tolerance": FLOAT_TOLERANCE,
        "load_runs": list(reconciliation.load_runs),
        "frozen_sources": dict(sorted(reconciliation.sources.items())),
        "summary": reconciliation.summary(),
        "checks": [
            {
                "group": c.group,
                "check": c.path,
                "expected": c.expected,
                "observed": c.observed,
                "tolerance": c.tolerance,
                "status": c.status,
            }
            for c in reconciliation.checks
        ],
    }


def write_report(path: Path, reconciliation: Reconciliation) -> None:
    """Write the report once; an existing file is never overwritten."""
    content = json.dumps(to_report(reconciliation), indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as error:
        raise ReconcileError(f"{path} already exists; refusing overwrite") from error

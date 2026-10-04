"""Aggregate-only secondary analysis for the paired R2 measures study."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .autoresearch_metrics import median_iqr
from .measure_catalog_review import MeasureReviewError, write_review_artifact
from .measure_review_catalog import canonical_catalog_bytes
from .protected_fields import ProtectedFieldError, reject_protected_fields
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION
from .scoring import OFFICIAL_SOFT_EX_VERSION, SENSITIVITY_SCORER_VERSION


class R2PairedOutcomeError(ValueError):
    """Raised when the R2 paired outcome report is not defensible."""


EXPECTED_SCHEDULE_SHA256 = (
    "8498c35e062dd893d1f20eda503bb65c95603b94c5fdd5fa2a87a8c7ccc27bda"
)
EXPECTED_PAIR_COUNT = 136
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = "omni-livesqlbench-large-v1-r2-measures-analysis-v1"
ANALYSIS_VERSION = "r2_paired_outcome_analysis_v3"

_REPORT_KIND = "r2-public-evidence-paired-outcome-report"
_SCHEDULE_KIND = "r2-public-evidence-measures-paired-schedule"
_SCHEDULE_VERSION = "r2-public-evidence-measures-paired-schedule-v1"
_SCORE_SCHEMA_VERSIONS = frozenset({"score-artifact-v1", "r2-score-artifact-v2"})
_OUTCOMES = ("correct", "refused_or_error", "wrong_answer")
_GENERATION_OUTCOMES = ("answered", "errored", "refused")
_SCORED_FIELDS = frozenset(
    {
        "correctness",
        "official_correct",
        "outcome",
        "score",
        "sensitivity_correct",
    }
)
_RESULT_CONTRACT_FAILURES = frozenset(
    {
        "response_contract_error",
        "result_contract_error",
        "unsupported_semantic_result_type",
    }
)
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_FAILURE = re.compile(r"[a-z][a-z0-9._-]{0,79}")
_SOURCE_PATHS = {
    "paired_schedule": (
        "experiments/r2-public-evidence-measures/r2-paired-execution-schedule-v1.json"
    )
}


@dataclass(frozen=True)
class _Generation:
    attempt_id: str
    condition: str
    cost_usd: float | None
    database_query_count: int | None
    generation_outcome: str
    instance_id: str
    latency_ms: float
    record_sha256: str
    terminal_failure_class: str | None
    token_count: int | None
    tool_call_count: int | None
    validation_attempt_count: int | None


@dataclass(frozen=True)
class _Score:
    failure_category: str | None
    outcome: str | None
    status: str


def build_r2_paired_outcome_report(
    schedule_bytes: bytes,
    control_generation_bytes: bytes,
    treatment_generation_bytes: bytes,
    control_official_score_bytes: bytes,
    control_sensitivity_score_bytes: bytes,
    treatment_official_score_bytes: bytes,
    treatment_sensitivity_score_bytes: bytes,
    *,
    expected_pair_count: int = EXPECTED_PAIR_COUNT,
    expected_schedule_sha256: str = EXPECTED_SCHEDULE_SHA256,
) -> dict[str, Any]:
    """Build the preregistered aggregate secondary-outcome report."""
    _positive_int(expected_pair_count, "expected pair count")
    _digest(expected_schedule_sha256, "expected schedule hash")
    if _sha256(schedule_bytes) != expected_schedule_sha256:
        raise R2PairedOutcomeError("schedule hash does not match the freeze")
    schedule = _schedule(schedule_bytes, expected_pair_count)
    control = _generation_records(
        control_generation_bytes,
        CONTROL_CONDITION,
        schedule,
        expected_pair_count,
    )
    treatment = _generation_records(
        treatment_generation_bytes,
        TREATMENT_CONDITION,
        schedule,
        expected_pair_count,
    )
    scores = {
        "official_soft_ex": {
            CONTROL_CONDITION: _score_artifact(
                control_official_score_bytes,
                control_generation_bytes,
                control,
                "official_soft_ex",
                OFFICIAL_SOFT_EX_VERSION,
            ),
            TREATMENT_CONDITION: _score_artifact(
                treatment_official_score_bytes,
                treatment_generation_bytes,
                treatment,
                "official_soft_ex",
                OFFICIAL_SOFT_EX_VERSION,
            ),
        },
        "sensitivity": {
            CONTROL_CONDITION: _score_artifact(
                control_sensitivity_score_bytes,
                control_generation_bytes,
                control,
                "sensitivity",
                SENSITIVITY_SCORER_VERSION,
            ),
            TREATMENT_CONDITION: _score_artifact(
                treatment_sensitivity_score_bytes,
                treatment_generation_bytes,
                treatment,
                "sensitivity",
                SENSITIVITY_SCORER_VERSION,
            ),
        },
    }
    generations = {
        CONTROL_CONDITION: control,
        TREATMENT_CONDITION: treatment,
    }
    telemetry = {
        condition: _generation_report(records)
        for condition, records in generations.items()
    }
    pair_order = tuple(
        _text(item.get("instance_id"), "pair instance") for item in schedule["pairs"]
    )
    scorer_reports = {
        identity: _scorer_report(
            arm_scores,
            generations,
            telemetry,
            pair_order,
            version=(
                OFFICIAL_SOFT_EX_VERSION
                if identity == "official_soft_ex"
                else SENSITIVITY_SCORER_VERSION
            ),
        )
        for identity, arm_scores in scores.items()
    }
    score_inputs = {
        "official_soft_ex": {
            CONTROL_CONDITION: control_official_score_bytes,
            TREATMENT_CONDITION: treatment_official_score_bytes,
        },
        "sensitivity": {
            CONTROL_CONDITION: control_sensitivity_score_bytes,
            TREATMENT_CONDITION: treatment_sensitivity_score_bytes,
        },
    }
    report: dict[str, Any] = {
        "analysis_version": ANALYSIS_VERSION,
        "bootstrap": {
            "ci_level": 0.95,
            "interval": "percentile_nearest_rank",
            "replicates": BOOTSTRAP_REPLICATES,
            "sampler": "sha256_modulo_question_count_v1",
            "seed": BOOTSTRAP_SEED,
        },
        "generation": telemetry,
        "information_boundary": {
            "emits_attempt_level_outcomes": False,
            "emits_question_level_outcomes": False,
            "hidden_annotations_used": False,
            "question_text_used": False,
            "result_values_used": False,
            "sealed_test_used": False,
        },
        "kind": _REPORT_KIND,
        "paired_cost": _paired_cost(control, treatment, pair_order),
        "paired_reliability": _paired_reliability(control, treatment, pair_order),
        "pair_count": expected_pair_count,
        "schema_version": 1,
        "scorers": scorer_reports,
        "source": {
            "generations": {
                CONTROL_CONDITION: {
                    "record_count": len(control),
                    "sha256": _sha256(control_generation_bytes),
                },
                TREATMENT_CONDITION: {
                    "record_count": len(treatment),
                    "sha256": _sha256(treatment_generation_bytes),
                },
            },
            "paired_schedule": {
                "path": _SOURCE_PATHS["paired_schedule"],
                "sha256": _sha256(schedule_bytes),
            },
            "score_artifacts": {
                identity: {
                    condition: {
                        "generation_sha256": _sha256(
                            control_generation_bytes
                            if condition == CONTROL_CONDITION
                            else treatment_generation_bytes
                        ),
                        "sha256": _sha256(content),
                    }
                    for condition, content in selected.items()
                }
                for identity, selected in score_inputs.items()
            },
        },
    }
    report["manifest"] = {"artifact_sha256": _sha256(canonical_catalog_bytes(report))}
    _reject_protected(report, "paired outcome report")
    return report


def validate_r2_paired_outcome_report(
    content: bytes,
    schedule_bytes: bytes,
    control_generation_bytes: bytes,
    treatment_generation_bytes: bytes,
    control_official_score_bytes: bytes,
    control_sensitivity_score_bytes: bytes,
    treatment_official_score_bytes: bytes,
    treatment_sensitivity_score_bytes: bytes,
    *,
    expected_pair_count: int = EXPECTED_PAIR_COUNT,
    expected_schedule_sha256: str = EXPECTED_SCHEDULE_SHA256,
) -> dict[str, Any]:
    """Regenerate and compare the complete aggregate report."""
    observed = _json_object(content, "paired outcome report")
    expected = build_r2_paired_outcome_report(
        schedule_bytes,
        control_generation_bytes,
        treatment_generation_bytes,
        control_official_score_bytes,
        control_sensitivity_score_bytes,
        treatment_official_score_bytes,
        treatment_sensitivity_score_bytes,
        expected_pair_count=expected_pair_count,
        expected_schedule_sha256=expected_schedule_sha256,
    )
    if canonical_catalog_bytes(observed) != canonical_catalog_bytes(expected):
        raise R2PairedOutcomeError(
            "paired outcome report does not reproduce from the frozen evidence"
        )
    if content != canonical_catalog_bytes(observed):
        raise R2PairedOutcomeError("paired outcome report is not canonical JSON")
    return expected


def write_r2_paired_outcome_report(
    destination: Path, report: Mapping[str, object]
) -> None:
    """Publish a canonical aggregate report append-only at mode 0600."""
    if not isinstance(report, Mapping):
        raise R2PairedOutcomeError("paired outcome report must be an object")
    try:
        write_review_artifact(destination, canonical_catalog_bytes(report))
    except (MeasureReviewError, TypeError, ValueError) as error:
        raise R2PairedOutcomeError(str(error)) from error


def _schedule(content: bytes, expected_pair_count: int) -> dict[str, Any]:
    value = _json_object(content, "paired schedule")
    _reject_protected(value, "paired schedule")
    if content != canonical_catalog_bytes(value):
        raise R2PairedOutcomeError("paired schedule is not canonical JSON")
    if (
        value.get("kind") != _SCHEDULE_KIND
        or value.get("schedule_version") != _SCHEDULE_VERSION
        or value.get("schema_version") != 1
    ):
        raise R2PairedOutcomeError("paired schedule identity is invalid")
    _validate_internal_hash(value, "paired schedule")
    pairs = value.get("pairs")
    attempts = value.get("attempts")
    if (
        not isinstance(pairs, list)
        or len(pairs) != expected_pair_count
        or not isinstance(attempts, list)
        or len(attempts) != expected_pair_count * 2
    ):
        raise R2PairedOutcomeError("paired schedule count is invalid")
    pair_ids: set[str] = set()
    instance_ids: set[str] = set()
    for pair in pairs:
        selected = _mapping(pair, "paired schedule pair")
        pair_id = _text(selected.get("pair_id"), "pair identity")
        instance_id = _text(selected.get("instance_id"), "pair instance")
        if pair_id in pair_ids or instance_id in instance_ids:
            raise R2PairedOutcomeError("paired schedule contains duplicate identity")
        pair_ids.add(pair_id)
        instance_ids.add(instance_id)
    attempt_ids: set[str] = set()
    counts: Counter[str] = Counter()
    for attempt in attempts:
        selected = _mapping(attempt, "paired schedule attempt")
        attempt_id = _text(selected.get("attempt_id"), "attempt identity")
        condition = selected.get("condition")
        if attempt_id in attempt_ids:
            raise R2PairedOutcomeError("paired schedule contains duplicate attempt")
        if condition not in {CONTROL_CONDITION, TREATMENT_CONDITION}:
            raise R2PairedOutcomeError("paired schedule condition is invalid")
        if selected.get("instance_id") not in instance_ids:
            raise R2PairedOutcomeError("paired schedule attempt instance is invalid")
        if selected.get("repetition") != 1:
            raise R2PairedOutcomeError("paired schedule repetition is invalid")
        attempt_ids.add(attempt_id)
        counts[str(condition)] += 1
    if counts != Counter(
        {
            CONTROL_CONDITION: expected_pair_count,
            TREATMENT_CONDITION: expected_pair_count,
        }
    ):
        raise R2PairedOutcomeError("paired schedule arm counts are invalid")
    return value


def _generation_records(
    content: bytes,
    condition: str,
    schedule: Mapping[str, Any],
    expected_pair_count: int,
) -> tuple[_Generation, ...]:
    records = _jsonl_objects(content, f"{condition} generation")
    expected = [item for item in schedule["attempts"] if item["condition"] == condition]
    if len(records) != expected_pair_count:
        raise R2PairedOutcomeError(
            f"{condition} generation is not a complete scheduled arm"
        )
    result: list[_Generation] = []
    seen: set[str] = set()
    run_ids: set[str] = set()
    raw_lines = content.splitlines(keepends=True)
    for record, raw, scheduled in zip(records, raw_lines, expected, strict=True):
        _reject_protected(record, f"{condition} generation")
        scored = _find_key(record, _SCORED_FIELDS)
        if scored is not None:
            raise R2PairedOutcomeError(
                f"{condition} generation contains scored field {scored}"
            )
        attempt_id = _text(record.get("attempt_id"), "generation attempt identity")
        if attempt_id in seen:
            raise R2PairedOutcomeError(
                f"{condition} generation contains a duplicate attempt"
            )
        seen.add(attempt_id)
        if (
            attempt_id != scheduled["attempt_id"]
            or record.get("instance_id") != scheduled["instance_id"]
            or record.get("condition") != condition
        ):
            raise R2PairedOutcomeError(
                f"{condition} generation attempt identity is invalid"
            )
        if record.get("partition") != "dev-a" or record.get("repetition") != 1:
            raise R2PairedOutcomeError(f"{condition} generation scope is invalid")
        run_ids.add(_text(record.get("run_id"), "generation run ID"))
        generation_outcome = record.get("generation_outcome")
        if generation_outcome not in _GENERATION_OUTCOMES:
            raise R2PairedOutcomeError(f"{condition} generation outcome is invalid")
        failure = record.get("terminal_failure_class")
        if (generation_outcome == "answered") != (failure is None):
            raise R2PairedOutcomeError(
                f"{condition} generation outcome and failure are inconsistent"
            )
        if failure is not None:
            failure = _failure(failure, "terminal failure class")
        cost = _optional_number(record.get("cost_usd"), "cost_usd")
        unavailable = record.get("cost_unavailable_reason")
        if cost is None:
            _text(unavailable, "cost_unavailable_reason")
        elif unavailable is not None:
            raise R2PairedOutcomeError(
                "cost_unavailable_reason must be null when cost is observed"
            )
        result.append(
            _Generation(
                attempt_id=attempt_id,
                condition=condition,
                cost_usd=cost,
                database_query_count=_optional_count(
                    record.get("database_query_count"), "database_query_count"
                ),
                generation_outcome=str(generation_outcome),
                instance_id=_text(record.get("instance_id"), "generation instance"),
                latency_ms=_required_number(record.get("latency_ms"), "latency_ms"),
                record_sha256=_sha256(raw),
                terminal_failure_class=failure,
                token_count=_token_count(record.get("token_usage")),
                tool_call_count=_optional_count(
                    record.get("tool_call_count"), "tool_call_count"
                ),
                validation_attempt_count=_optional_count(
                    record.get("validation_attempt_count"),
                    "validation_attempt_count",
                ),
            )
        )
    if len(run_ids) != 1:
        raise R2PairedOutcomeError(f"{condition} generation must have one run ID")
    return tuple(result)


def _score_artifact(
    content: bytes,
    generation_bytes: bytes,
    generation: Sequence[_Generation],
    expected_identity: str,
    expected_version: str,
) -> dict[str, _Score]:
    value = _json_object(content, "score artifact")
    _reject_protected(value, "score artifact")
    if content != canonical_catalog_bytes(value):
        raise R2PairedOutcomeError("score artifact is not canonical JSON")
    if set(value) != {"attempts", "generation", "schema_version", "scorer"}:
        raise R2PairedOutcomeError("score artifact shape is invalid")
    schema_version = value.get("schema_version")
    if schema_version not in _SCORE_SCHEMA_VERSIONS:
        raise R2PairedOutcomeError("score artifact version is invalid")
    binding = _mapping(value.get("generation"), "score generation binding")
    if set(binding) != {"path", "sha256"}:
        raise R2PairedOutcomeError("score artifact generation binding is invalid")
    _text(binding.get("path"), "score generation path")
    if binding.get("sha256") != _sha256(generation_bytes):
        raise R2PairedOutcomeError("score artifact generation hash is invalid")
    scorer = _mapping(value.get("scorer"), "score artifact scorer")
    if set(scorer) != {"identity", "version"} or (
        scorer.get("identity"),
        scorer.get("version"),
    ) != (expected_identity, expected_version):
        raise R2PairedOutcomeError("score artifact frozen scorer is invalid")
    attempts = value.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != len(generation):
        raise R2PairedOutcomeError("score artifact is not a complete scheduled arm")
    observed_ids = [
        item.get("attempt_id") if isinstance(item, Mapping) else None
        for item in attempts
    ]
    if len(observed_ids) != len(set(observed_ids)):
        raise R2PairedOutcomeError("score artifact contains a duplicate score attempt")
    result: dict[str, _Score] = {}
    for raw, record in zip(attempts, generation, strict=True):
        attempt = _mapping(raw, "score attempt")
        fields = set(attempt)
        allowed = {
            "attempt_id",
            "failure_category",
            "generation_record_sha256",
            "outcome",
        }
        required = {"attempt_id", "generation_record_sha256", "outcome"}
        if schema_version == "r2-score-artifact-v2":
            allowed.add("status")
            required = {"attempt_id", "generation_record_sha256", "status"}
        if fields - allowed or required - fields:
            raise R2PairedOutcomeError("score artifact attempt shape is invalid")
        if attempt.get("attempt_id") != record.attempt_id:
            raise R2PairedOutcomeError("score artifact attempt identity is invalid")
        if attempt.get("generation_record_sha256") != record.record_sha256:
            raise R2PairedOutcomeError(
                "score artifact generation record hash is invalid"
            )
        status = attempt.get("status", "scored")
        outcome = attempt.get("outcome")
        if status not in {"scored", "unscorable"}:
            raise R2PairedOutcomeError("score artifact status is invalid")
        if (status == "scored" and outcome not in _OUTCOMES) or (
            status == "unscorable" and outcome is not None
        ):
            raise R2PairedOutcomeError("score artifact outcome is invalid")
        category = attempt.get("failure_category")
        if category is not None:
            category = _failure(category, "score failure category")
        if status == "unscorable" and category is None:
            raise R2PairedOutcomeError(
                "unscorable score artifact attempt requires a failure category"
            )
        result[record.instance_id] = _Score(
            failure_category=category,
            outcome=None if outcome is None else str(outcome),
            status=str(status),
        )
    return result


def _generation_report(records: Sequence[_Generation]) -> dict[str, Any]:
    outcomes = Counter(record.generation_outcome for record in records)
    failures = Counter(
        record.terminal_failure_class
        for record in records
        if record.terminal_failure_class is not None
    )
    costs = [record.cost_usd for record in records]
    total_cost = _optional_sum(costs)
    answered = outcomes["answered"]
    median_latency, iqr_latency = median_iqr([record.latency_ms for record in records])
    return {
        "generation_outcomes": {name: outcomes[name] for name in _GENERATION_OUTCOMES},
        "result_contract_failure_count": sum(
            failures[name] for name in _RESULT_CONTRACT_FAILURES
        ),
        "scheduled_attempts": len(records),
        "telemetry": {
            "cost_observed_attempts": sum(cost is not None for cost in costs),
            "cost_per_answered_attempt": (
                None if total_cost is None or answered == 0 else total_cost / answered
            ),
            "cost_per_scheduled_attempt": (
                None if total_cost is None else total_cost / len(records)
            ),
            "cost_unavailable_count": sum(cost is None for cost in costs),
            "database_query_count": _optional_sum(
                [record.database_query_count for record in records]
            ),
            "iqr_latency_ms": iqr_latency,
            "median_latency_ms": median_latency,
            "token_count": _optional_sum([record.token_count for record in records]),
            "tool_call_count": _optional_sum(
                [record.tool_call_count for record in records]
            ),
            "total_cost_usd": total_cost,
            "validation_attempt_count": _optional_sum(
                [record.validation_attempt_count for record in records]
            ),
        },
        "terminal_failure_classes": dict(sorted(failures.items())),
    }


def _scorer_report(
    scores: Mapping[str, Mapping[str, _Score]],
    generations: Mapping[str, Sequence[_Generation]],
    generation_reports: Mapping[str, Mapping[str, Any]],
    pair_order: Sequence[str],
    *,
    version: str,
) -> dict[str, Any]:
    arms: dict[str, dict[str, Any]] = {}
    for condition in (CONTROL_CONDITION, TREATMENT_CONDITION):
        selected = scores[condition]
        outcomes = Counter(
            score.outcome for score in selected.values() if score.status == "scored"
        )
        categories = Counter(
            score.failure_category
            for score in selected.values()
            if score.failure_category is not None
        )
        correct = outcomes["correct"]
        unscorable = sum(score.status == "unscorable" for score in selected.values())
        scoreable = len(selected) - unscorable
        if scoreable < 1:
            raise R2PairedOutcomeError("scorer has no scoreable attempts")
        total_cost = generation_reports[condition]["telemetry"]["total_cost_usd"]
        arms[condition] = {
            "accuracy": correct / scoreable,
            "cost_per_correct_attempt": (
                None if total_cost is None or correct == 0 else total_cost / correct
            ),
            "failure_categories": dict(sorted(categories.items())),
            "outcomes": {name: outcomes[name] for name in _OUTCOMES},
            "scheduled_attempts": len(generations[condition]),
            "scoreable_attempts": scoreable,
            "unscorable_attempts": unscorable,
        }
    control = scores[CONTROL_CONDITION]
    treatment = scores[TREATMENT_CONDITION]
    control_unscorable = {
        item for item in pair_order if control[item].status == "unscorable"
    }
    treatment_unscorable = {
        item for item in pair_order if treatment[item].status == "unscorable"
    }
    if control_unscorable != treatment_unscorable:
        raise R2PairedOutcomeError("scorer unscorable frame differs between arms")
    scoreable_pairs = [item for item in pair_order if item not in control_unscorable]
    differences = [
        int(treatment[item].outcome == "correct")
        - int(control[item].outcome == "correct")
        for item in scoreable_pairs
    ]
    interval = _bootstrap_interval(differences)
    interval.update(
        {
            "discordant_gains": sum(value == 1 for value in differences),
            "discordant_losses": sum(value == -1 for value in differences),
            "pair_count": len(scoreable_pairs),
        }
    )
    return {
        "arms": arms,
        "paired_accuracy": interval,
        "version": version,
    }


def _paired_cost(
    control: Sequence[_Generation],
    treatment: Sequence[_Generation],
    pair_order: Sequence[str],
) -> dict[str, Any]:
    control_cost = {record.instance_id: record.cost_usd for record in control}
    treatment_cost = {record.instance_id: record.cost_usd for record in treatment}
    complete = [
        item
        for item in pair_order
        if control_cost[item] is not None and treatment_cost[item] is not None
    ]
    if len(complete) != len(pair_order):
        return {
            "complete_pair_count": len(complete),
            "estimate": None,
            "lower": None,
            "pair_count": len(pair_order),
            "status": "unavailable_incomplete_cost",
            "upper": None,
        }
    differences = [
        float(treatment_cost[item]) - float(control_cost[item]) for item in pair_order
    ]
    report = _bootstrap_interval(differences)
    return {
        "complete_pair_count": len(pair_order),
        **report,
        "pair_count": len(pair_order),
        "status": "complete",
    }


def _paired_reliability(
    control: Sequence[_Generation],
    treatment: Sequence[_Generation],
    pair_order: Sequence[str],
) -> dict[str, Any]:
    by_condition = {
        CONTROL_CONDITION: {record.instance_id: record for record in control},
        TREATMENT_CONDITION: {record.instance_id: record for record in treatment},
    }

    def contrast(predicate) -> tuple[dict[str, float], list[int]]:
        differences = [
            int(predicate(by_condition[TREATMENT_CONDITION][item]))
            - int(predicate(by_condition[CONTROL_CONDITION][item]))
            for item in pair_order
        ]
        return _bootstrap_interval(differences), differences

    answered, answered_differences = contrast(
        lambda record: record.generation_outcome == "answered"
    )
    contract, contract_differences = contrast(
        lambda record: record.terminal_failure_class in _RESULT_CONTRACT_FAILURES
    )
    return {
        "answered_rate": {
            **answered,
            "discordant_gains": sum(value == 1 for value in answered_differences),
            "discordant_losses": sum(value == -1 for value in answered_differences),
            "pair_count": len(pair_order),
        },
        "result_contract_failure_rate": {
            **contract,
            "discordant_decreases": sum(value == -1 for value in contract_differences),
            "discordant_increases": sum(value == 1 for value in contract_differences),
            "pair_count": len(pair_order),
        },
    }


def _bootstrap_interval(values: Sequence[float | int]) -> dict[str, float]:
    if not values:
        raise R2PairedOutcomeError("paired endpoint has no observations")
    count = len(values)
    estimates = []
    for replicate in range(BOOTSTRAP_REPLICATES):
        total = 0.0
        for draw in range(count):
            index = (
                int.from_bytes(
                    hashlib.sha256(
                        f"{BOOTSTRAP_SEED}\0{replicate}\0{draw}".encode()
                    ).digest(),
                    "big",
                )
                % count
            )
            total += values[index]
        estimates.append(total / count)
    estimates.sort()
    return {
        "estimate": sum(values) / count,
        "lower": estimates[max(0, math.ceil(0.025 * BOOTSTRAP_REPLICATES) - 1)],
        "upper": estimates[max(0, math.ceil(0.975 * BOOTSTRAP_REPLICATES) - 1)],
    }


def _validate_internal_hash(value: Mapping[str, Any], label: str) -> None:
    manifest = _mapping(value.get("manifest"), f"{label} manifest")
    observed = manifest.get("artifact_sha256")
    _digest(observed, f"{label} artifact hash")
    unsigned = copy.deepcopy(dict(value))
    unsigned_manifest = _mapping(unsigned.get("manifest"), f"{label} manifest")
    del unsigned_manifest["artifact_sha256"]
    if observed != _sha256(canonical_catalog_bytes(unsigned)):
        raise R2PairedOutcomeError(f"{label} internal hash is invalid")


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    if not isinstance(content, bytes) or not content:
        raise R2PairedOutcomeError(f"{label} size is invalid")
    try:
        value = json.loads(content.decode(), object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise R2PairedOutcomeError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise R2PairedOutcomeError(f"{label} must be an object")
    return value


def _jsonl_objects(content: bytes, label: str) -> list[dict[str, Any]]:
    if not isinstance(content, bytes) or not content:
        raise R2PairedOutcomeError(f"{label} size is invalid")
    lines = content.splitlines(keepends=True)
    if not lines or any(not line.endswith(b"\n") for line in lines):
        raise R2PairedOutcomeError(f"{label} must be newline terminated")
    result = []
    for line_number, raw in enumerate(lines, start=1):
        try:
            value = json.loads(raw, object_pairs_hook=_strict_object)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise R2PairedOutcomeError(
                f"{label} line {line_number} is not valid JSON"
            ) from error
        if not isinstance(value, dict):
            raise R2PairedOutcomeError(f"{label} record must be an object")
        if canonical_catalog_bytes(value) != raw:
            raise R2PairedOutcomeError(f"{label} records must be canonical JSON")
        result.append(value)
    return result


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise R2PairedOutcomeError(f"duplicate JSON field {key}")
        result[key] = value
    return result


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise R2PairedOutcomeError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise R2PairedOutcomeError(f"{label} is invalid")
    return value


def _failure(value: object, label: str) -> str:
    if not isinstance(value, str) or _SAFE_FAILURE.fullmatch(value) is None:
        raise R2PairedOutcomeError(f"{label} is invalid")
    return value


def _required_number(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise R2PairedOutcomeError(f"{label} must be a nonnegative finite number")
    return float(value)


def _optional_number(value: object, label: str) -> float | None:
    return None if value is None else _required_number(value, label)


def _optional_count(value: object, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise R2PairedOutcomeError(f"{label} must be a nonnegative integer or null")
    return value


def _token_count(value: object) -> int | None:
    if value is None:
        return None
    selected = _mapping(value, "token_usage")
    if set(selected) != {"input_tokens", "output_tokens", "total_tokens"}:
        raise R2PairedOutcomeError("token_usage is invalid")
    counts = {name: _optional_count(count, name) for name, count in selected.items()}
    if any(count is None for count in counts.values()):
        raise R2PairedOutcomeError("token_usage counts must be observed")
    if counts["input_tokens"] + counts["output_tokens"] != counts["total_tokens"]:
        raise R2PairedOutcomeError("token_usage total is inconsistent")
    return counts["total_tokens"]


def _optional_sum(values: Sequence[int | float | None]) -> int | float | None:
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _find_key(value: object, forbidden: frozenset[str]) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).casefold() in forbidden:
                return str(key)
            found = _find_key(nested, forbidden)
            if found is not None:
                return found
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for nested in value:
            found = _find_key(nested, forbidden)
            if found is not None:
                return found
    return None


def _reject_protected(value: object, label: str) -> None:
    try:
        reject_protected_fields(value)
    except ProtectedFieldError as error:
        raise R2PairedOutcomeError(f"{label} contains a protected field") from error


def _positive_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise R2PairedOutcomeError(f"{label} is invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise R2PairedOutcomeError(f"{label} is invalid")
    return value


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

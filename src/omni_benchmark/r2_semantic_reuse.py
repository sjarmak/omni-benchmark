"""Classify governed measure reuse for the paired R2 mechanism study."""

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

from .measure_catalog_review import MeasureReviewError, write_review_artifact
from .measure_opportunity_map import MeasureOpportunityMapError, _accepted_catalog
from .measure_review_catalog import canonical_catalog_bytes
from .protected_fields import ProtectedFieldError, reject_protected_fields
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION


class R2SemanticReuseError(ValueError):
    """Raised when the R2 semantic-reuse result is not defensible."""


EXPECTED_ACCEPTED_CATALOG_SHA256 = (
    "2d2f9c15bc5f5271db924fa4377b41c26a0e61bcec221ed31d10b3365358039a"
)
EXPECTED_SCHEDULE_SHA256 = (
    "8498c35e062dd893d1f20eda503bb65c95603b94c5fdd5fa2a87a8c7ccc27bda"
)
EXPECTED_PAIR_COUNT = 136
CLASSIFIER_VERSION = "r2_semantic_reuse_classifier_v1"

_REPORT_KIND = "r2-public-evidence-semantic-reuse-report"
_REPORT_VERSION = "r2-public-evidence-semantic-reuse-report-v1"
_MAX_ARTIFACT_BYTES = 64_000_000
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUALIFIED_NAME = re.compile(
    r"^(?P<view>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<field>[A-Za-z_][A-Za-z0-9_]*)$"
)
_SEMANTIC_TOKEN = re.compile(
    r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*\."
    r"[A-Za-z_][A-Za-z0-9_]*)\}"
)
_DOLLAR_QUOTE = re.compile(r"\$[A-Za-z_0-9]*\$")
_CLASSIFICATIONS = (
    "measure_reference_with_inline_recreation",
    "measure_reference_without_bridge_inline",
    "no_measure_reference",
    "unresolved_both",
    "unresolved_control",
    "unresolved_treatment",
    "verified_replacement",
)
_SCORED_FIELDS = frozenset(
    {
        "correctness",
        "official_correct",
        "outcome",
        "score",
        "sensitivity_correct",
    }
)
_SOURCE_PATHS = {
    "accepted_catalog": (
        "experiments/r2-public-evidence-measures/"
        "public-evidence-measure-catalog-v1.json"
    ),
    "opportunity_map": (
        "experiments/r2-public-evidence-measures/measure-opportunity-map-v1.json"
    ),
    "paired_schedule": (
        "experiments/r2-public-evidence-measures/r2-paired-execution-schedule-v1.json"
    ),
}


@dataclass(frozen=True)
class _Measure:
    aggregate_type: str
    database: str
    measure_id: str
    measure_reference: str
    source_reference: str


@dataclass(frozen=True)
class _QuerySurface:
    inline_references: frozenset[str]
    measure_references: frozenset[str]
    parseable: bool


def build_r2_semantic_reuse_report(
    accepted_catalog_bytes: bytes,
    opportunity_map_bytes: bytes,
    schedule_bytes: bytes,
    control_generation_bytes: bytes,
    treatment_generation_bytes: bytes,
    *,
    expected_pair_count: int = EXPECTED_PAIR_COUNT,
    expected_catalog_sha256: str = EXPECTED_ACCEPTED_CATALOG_SHA256,
    expected_schedule_sha256: str = EXPECTED_SCHEDULE_SHA256,
) -> dict[str, Any]:
    """Build an aggregate-only intention-to-treat semantic-reuse report."""
    _positive_int(expected_pair_count, "expected pair count")
    _digest(expected_catalog_sha256, "expected accepted catalog hash")
    _digest(expected_schedule_sha256, "expected paired schedule hash")
    if _sha256(accepted_catalog_bytes) != expected_catalog_sha256:
        raise R2SemanticReuseError("accepted catalog hash does not match the freeze")
    if _sha256(schedule_bytes) != expected_schedule_sha256:
        raise R2SemanticReuseError("paired schedule hash does not match the freeze")

    measures = _measures(accepted_catalog_bytes)
    schedule = _schedule(schedule_bytes, expected_pair_count)
    mapped = _mapped_opportunities(
        opportunity_map_bytes,
        accepted_catalog_bytes,
        measures,
        schedule,
        expected_pair_count,
    )
    control_records = _generation_records(
        control_generation_bytes,
        CONTROL_CONDITION,
        schedule,
        measures,
        expected_pair_count,
    )
    treatment_records = _generation_records(
        treatment_generation_bytes,
        TREATMENT_CONDITION,
        schedule,
        measures,
        expected_pair_count,
    )

    classifications: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    bridge_inline_count = 0
    treatment_inline_count = 0
    treatment_reference_count = 0
    parseable_count = 0
    verified_count = 0
    unresolved_count = 0
    for instance_id, measure_ids in mapped.items():
        control = control_records[instance_id]
        treatment = treatment_records[instance_id]
        mapped_ids = frozenset(measure_ids)
        control_inline = control.inline_references.intersection(mapped_ids)
        treatment_inline = treatment.inline_references.intersection(mapped_ids)
        treatment_references = treatment.measure_references.intersection(mapped_ids)
        bridge_inline_count += bool(control_inline)
        treatment_inline_count += bool(treatment_inline)
        treatment_reference_count += bool(treatment_references)
        classification = _classification(
            control,
            treatment,
            control_inline,
            treatment_inline,
            treatment_references,
        )
        counts[classification] += 1
        is_parseable = control.parseable and treatment.parseable
        parseable_count += is_parseable
        is_verified = classification == "verified_replacement"
        verified_count += is_verified
        unresolved_count += classification.startswith("unresolved_")
        classifications.append(
            {
                "classification": classification,
                "control_inline_measure_ids": sorted(control_inline),
                "instance_id": instance_id,
                "treatment_inline_measure_ids": sorted(treatment_inline),
                "treatment_reference_measure_ids": sorted(treatment_references),
            }
        )

    opportunity_count = len(mapped)
    report: dict[str, Any] = {
        "classifier_version": CLASSIFIER_VERSION,
        "information_boundary": {
            "correctness_used": False,
            "hidden_annotations_used": False,
            "question_text_used": False,
            "result_values_used": False,
            "sealed_test_used": False,
        },
        "kind": _REPORT_KIND,
        "policy": {
            "classifier": "deterministic_exact_structure_and_lexical_match",
            "denominator": "all_mapped_scheduled_pairs",
            "interval": "wilson_95_two_sided",
            "parseable_pairs": "labeled_sensitivity_only",
            "unresolved_primary_value": "not_verified_replacement",
        },
        "report_version": _REPORT_VERSION,
        "schema_version": 1,
        "source": {
            "accepted_catalog": {
                "path": _SOURCE_PATHS["accepted_catalog"],
                "sha256": _sha256(accepted_catalog_bytes),
            },
            "control_generation": {
                "condition": CONTROL_CONDITION,
                "record_count": len(control_records),
                "sha256": _sha256(control_generation_bytes),
            },
            "opportunity_map": {
                "path": _SOURCE_PATHS["opportunity_map"],
                "sha256": _sha256(opportunity_map_bytes),
            },
            "paired_schedule": {
                "path": _SOURCE_PATHS["paired_schedule"],
                "sha256": _sha256(schedule_bytes),
            },
            "treatment_generation": {
                "condition": TREATMENT_CONDITION,
                "record_count": len(treatment_records),
                "sha256": _sha256(treatment_generation_bytes),
            },
        },
        "summary": {
            "bridge_inline_equivalent_count": bridge_inline_count,
            "classification_counts": {name: counts[name] for name in _CLASSIFICATIONS},
            "opportunity_pair_count": opportunity_count,
            "parseable_sensitivity": {
                "denominator": parseable_count,
                "rate": verified_count / parseable_count if parseable_count else None,
                "verified_replacement_count": verified_count,
                "wilson_95": _wilson_interval(verified_count, parseable_count),
            },
            "scheduled_pair_count": expected_pair_count,
            "treatment_inline_equivalent_count": treatment_inline_count,
            "treatment_measure_reference_count": treatment_reference_count,
            "unresolved_pair_count": unresolved_count,
            "verified_replacement_count": verified_count,
            "verified_replacement_rate": verified_count / opportunity_count,
            "verified_replacement_wilson_95": _wilson_interval(
                verified_count, opportunity_count
            ),
        },
    }
    report["manifest"] = {
        "classification_sha256": _sha256(canonical_catalog_bytes(classifications))
    }
    report["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(report))
    _reject_protected(report, "semantic-reuse report")
    return report


def validate_r2_semantic_reuse_report(
    content: bytes,
    accepted_catalog_bytes: bytes,
    opportunity_map_bytes: bytes,
    schedule_bytes: bytes,
    control_generation_bytes: bytes,
    treatment_generation_bytes: bytes,
    *,
    expected_pair_count: int = EXPECTED_PAIR_COUNT,
    expected_catalog_sha256: str = EXPECTED_ACCEPTED_CATALOG_SHA256,
    expected_schedule_sha256: str = EXPECTED_SCHEDULE_SHA256,
) -> dict[str, Any]:
    """Regenerate and compare the complete aggregate report."""
    observed = _json_object(content, "semantic-reuse report")
    expected = build_r2_semantic_reuse_report(
        accepted_catalog_bytes,
        opportunity_map_bytes,
        schedule_bytes,
        control_generation_bytes,
        treatment_generation_bytes,
        expected_pair_count=expected_pair_count,
        expected_catalog_sha256=expected_catalog_sha256,
        expected_schedule_sha256=expected_schedule_sha256,
    )
    if canonical_catalog_bytes(observed) != canonical_catalog_bytes(expected):
        raise R2SemanticReuseError(
            "semantic-reuse report does not reproduce from the frozen evidence"
        )
    if content != canonical_catalog_bytes(observed):
        raise R2SemanticReuseError("semantic-reuse report is not canonical JSON")
    return expected


def write_r2_semantic_reuse_report(
    destination: Path, report: Mapping[str, object]
) -> None:
    """Publish a canonical aggregate report append-only at mode 0600."""
    if not isinstance(report, Mapping):
        raise R2SemanticReuseError("semantic-reuse report must be an object")
    try:
        write_review_artifact(destination, canonical_catalog_bytes(report))
    except (MeasureReviewError, TypeError, ValueError) as error:
        raise R2SemanticReuseError(str(error)) from error


def _measures(content: bytes) -> dict[str, _Measure]:
    try:
        catalog = _accepted_catalog(content)
    except MeasureOpportunityMapError as error:
        raise R2SemanticReuseError(str(error)) from error
    result: dict[str, _Measure] = {}
    references: set[str] = set()
    for raw in catalog["accepted_candidates"]:
        candidate = _mapping(raw, "accepted measure candidate")
        measure_id = _text(candidate.get("measure_id"), "measure ID")
        database = _text(candidate.get("database"), "measure database")
        view = _mapping(candidate.get("view"), "measure view")
        view_name = _safe_name(view.get("view_name"), "measure view name")
        measure = _mapping(candidate.get("measure"), "measure")
        measure_name = _safe_name(measure.get("name"), "measure name")
        definition = _mapping(measure.get("definition"), "measure definition")
        signature = _mapping(
            candidate.get("inline_equivalent_signature"),
            "inline-equivalent signature",
        )
        aggregate_type = _aggregate_type(signature.get("aggregate_type"))
        if definition.get("aggregate_type") != aggregate_type:
            raise R2SemanticReuseError(
                "measure definition and inline signature aggregate types differ"
            )
        stable_ids = signature.get("source_field_stable_ids")
        if (
            not isinstance(stable_ids, list)
            or len(stable_ids) != 1
            or not isinstance(stable_ids[0], str)
            or not stable_ids[0]
        ):
            raise R2SemanticReuseError(
                "inline-equivalent signature must have one source field"
            )
        source_match = _SEMANTIC_TOKEN.fullmatch(
            _text(definition.get("sql"), "measure source SQL")
        )
        if (
            source_match is None
            or source_match.group("name").partition(".")[0] != view_name
        ):
            raise R2SemanticReuseError("measure source binding is invalid")
        measure_reference = f"{view_name}.{measure_name}"
        if measure_reference in references:
            raise R2SemanticReuseError("measure reference is duplicated")
        references.add(measure_reference)
        result[measure_id] = _Measure(
            aggregate_type=aggregate_type,
            database=database,
            measure_id=measure_id,
            measure_reference=measure_reference,
            source_reference=source_match.group("name"),
        )
    if not result:
        raise R2SemanticReuseError("accepted catalog has no measures")
    return result


def _schedule(content: bytes, expected_pair_count: int) -> dict[str, Any]:
    value = _json_object(content, "paired schedule")
    _reject_protected(value, "paired schedule")
    if content != canonical_catalog_bytes(value):
        raise R2SemanticReuseError("paired schedule is not canonical JSON")
    if (
        value.get("kind") != "r2-public-evidence-measures-paired-schedule"
        or value.get("schema_version") != 1
    ):
        raise R2SemanticReuseError("paired schedule identity is invalid")
    _validate_internal_hash(value, "paired schedule")
    pairs = value.get("pairs")
    attempts = value.get("attempts")
    if (
        not isinstance(pairs, list)
        or len(pairs) != expected_pair_count
        or not isinstance(attempts, list)
        or len(attempts) != expected_pair_count * 2
    ):
        raise R2SemanticReuseError("paired schedule count is invalid")
    pair_ids: list[str] = []
    instance_ids: list[str] = []
    pair_database: dict[str, str] = {}
    for raw in pairs:
        pair = _mapping(raw, "paired schedule pair")
        pair_id = _text(pair.get("pair_id"), "pair identity")
        instance_id = _text(pair.get("instance_id"), "scheduled instance")
        database = _text(pair.get("database"), "scheduled database")
        pair_ids.append(pair_id)
        instance_ids.append(instance_id)
        pair_database[instance_id] = database
    if len(pair_ids) != len(set(pair_ids)) or len(instance_ids) != len(
        set(instance_ids)
    ):
        raise R2SemanticReuseError("paired schedule contains duplicate identity")
    observed_attempt_ids: list[str] = []
    counts: Counter[str] = Counter()
    for raw in attempts:
        attempt = _mapping(raw, "paired schedule attempt")
        attempt_id = _text(attempt.get("attempt_id"), "attempt identity")
        condition = attempt.get("condition")
        if condition not in {CONTROL_CONDITION, TREATMENT_CONDITION}:
            raise R2SemanticReuseError("paired schedule condition is invalid")
        if attempt.get("instance_id") not in pair_database:
            raise R2SemanticReuseError("paired schedule attempt instance is invalid")
        observed_attempt_ids.append(attempt_id)
        counts[condition] += 1
    if len(observed_attempt_ids) != len(set(observed_attempt_ids)):
        raise R2SemanticReuseError("paired schedule contains duplicate attempt")
    if counts != Counter(
        {
            CONTROL_CONDITION: expected_pair_count,
            TREATMENT_CONDITION: expected_pair_count,
        }
    ):
        raise R2SemanticReuseError("paired schedule arm counts are invalid")
    value["_pair_database"] = pair_database
    return value


def _mapped_opportunities(
    content: bytes,
    catalog_bytes: bytes,
    measures: Mapping[str, _Measure],
    schedule: Mapping[str, Any],
    expected_pair_count: int,
) -> dict[str, tuple[str, ...]]:
    value = _json_object(content, "opportunity map")
    _reject_protected(value, "opportunity map")
    if content != canonical_catalog_bytes(value):
        raise R2SemanticReuseError("opportunity map is not canonical JSON")
    if (
        value.get("kind") != "public-evidence-measure-opportunity-map"
        or value.get("map_version") != "r2-public-evidence-measure-opportunity-map-v1"
        or value.get("schema_version") != 1
    ):
        raise R2SemanticReuseError("opportunity map identity is invalid")
    _validate_internal_hash(value, "opportunity map")
    source = _mapping(value.get("source"), "opportunity map source")
    if source.get("accepted_catalog_sha256") != _sha256(catalog_bytes):
        raise R2SemanticReuseError("opportunity map catalog hash is invalid")
    adjudication = value.get("adjudication")
    agent_adjudicated = adjudication == {
        "adjudicator": {
            "interface": "Codex",
            "model_family": "GPT-5",
            "product": "ChatGPT Work",
            "reasoning_effort": None,
            "reasoning_effort_status": "runtime_managed_not_exposed",
        },
        "status": "agent_adjudicated",
    }
    if adjudication is not None and not agent_adjudicated:
        raise R2SemanticReuseError("opportunity map adjudication is invalid")
    decisions = value.get("decisions")
    if not isinstance(decisions, list) or len(decisions) != expected_pair_count:
        raise R2SemanticReuseError("opportunity map count is invalid")
    pair_database = schedule["_pair_database"]
    ids: list[str] = []
    mapped: dict[str, tuple[str, ...]] = {}
    mapped_assignments = 0
    review_seconds: list[float] = []
    decision_counts: Counter[str] = Counter()
    for raw in decisions:
        decision = _mapping(raw, "opportunity decision")
        instance_id = _text(decision.get("instance_id"), "opportunity instance")
        ids.append(instance_id)
        if instance_id not in pair_database:
            raise R2SemanticReuseError(
                "opportunity instance is outside the paired schedule"
            )
        database = _text(decision.get("database"), "question database")
        if database != pair_database[instance_id]:
            raise R2SemanticReuseError("opportunity question database is invalid")
        disposition = decision.get("decision")
        if disposition not in {"ambiguous", "mapped", "none"}:
            raise R2SemanticReuseError("opportunity decision is invalid")
        measure_ids = decision.get("measure_ids")
        if (
            not isinstance(measure_ids, list)
            or any(not isinstance(item, str) or not item for item in measure_ids)
            or measure_ids != sorted(measure_ids)
            or len(measure_ids) != len(set(measure_ids))
        ):
            raise R2SemanticReuseError("opportunity measure IDs are invalid")
        unknown = set(measure_ids).difference(measures)
        if unknown:
            raise R2SemanticReuseError("opportunity map contains an unknown measure")
        if any(measures[item].database != database for item in measure_ids):
            raise R2SemanticReuseError(
                "mapped measure does not belong to the question database"
            )
        if disposition == "mapped" and not measure_ids:
            raise R2SemanticReuseError("mapped opportunity has no measure")
        if disposition == "none" and measure_ids:
            raise R2SemanticReuseError("none opportunity contains a measure")
        seconds = decision.get("active_review_seconds")
        if agent_adjudicated:
            valid_seconds = seconds is None
        else:
            valid_seconds = (
                not isinstance(seconds, bool)
                and isinstance(seconds, (int, float))
                and math.isfinite(seconds)
                and seconds >= 0
            )
        if not valid_seconds:
            raise R2SemanticReuseError("opportunity review seconds are invalid")
        if not agent_adjudicated:
            assert isinstance(seconds, (int, float))
            review_seconds.append(float(seconds))
        decision_counts[disposition] += 1
        if disposition == "mapped":
            mapped[instance_id] = tuple(measure_ids)
            mapped_assignments += len(measure_ids)
    if (
        ids != sorted(ids)
        or len(ids) != len(set(ids))
        or set(ids) != set(pair_database)
    ):
        raise R2SemanticReuseError(
            "opportunity map must contain every scheduled identity sorted"
        )
    manifest = _mapping(value.get("manifest"), "opportunity map manifest")
    if manifest.get("ordered_instance_ids") != ids:
        raise R2SemanticReuseError("opportunity map manifest membership is invalid")
    summary = _mapping(value.get("summary"), "opportunity map summary")
    if (
        summary.get("eligible_question_count") != expected_pair_count
        or summary.get("mapped_question_count") != decision_counts["mapped"]
        or summary.get("none_question_count") != decision_counts["none"]
        or summary.get("ambiguous_question_count") != decision_counts["ambiguous"]
        or summary.get("opportunity_question_count") != decision_counts["mapped"]
        or summary.get("mapped_measure_assignments") != mapped_assignments
        or summary.get("active_review_seconds")
        != (None if agent_adjudicated else math.fsum(review_seconds))
    ):
        raise R2SemanticReuseError("opportunity map summary is invalid")
    if not mapped:
        raise R2SemanticReuseError("opportunity map has no mapped opportunity")
    return mapped


def _generation_records(
    content: bytes,
    condition: str,
    schedule: Mapping[str, Any],
    measures: Mapping[str, _Measure],
    expected_pair_count: int,
) -> dict[str, _QuerySurface]:
    records = _jsonl_objects(content, f"{condition} generation")
    attempt_ids = [record.get("attempt_id") for record in records]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise R2SemanticReuseError(
            f"{condition} generation contains a duplicate attempt"
        )
    expected = [item for item in schedule["attempts"] if item["condition"] == condition]
    if len(records) != expected_pair_count:
        raise R2SemanticReuseError(
            f"{condition} generation is not a complete scheduled arm"
        )
    result: dict[str, _QuerySurface] = {}
    run_ids: set[str] = set()
    for record, scheduled in zip(records, expected, strict=True):
        _reject_protected(record, f"{condition} generation")
        scored = _find_key(record, _SCORED_FIELDS)
        if scored is not None:
            raise R2SemanticReuseError(
                f"{condition} generation contains scored field {scored}"
            )
        if record.get("condition") != condition:
            raise R2SemanticReuseError(f"{condition} generation condition is invalid")
        if record.get("attempt_id") != scheduled["attempt_id"]:
            raise R2SemanticReuseError(
                f"{condition} generation attempt identity is invalid"
            )
        if record.get("instance_id") != scheduled["instance_id"]:
            raise R2SemanticReuseError(
                f"{condition} generation instance identity is invalid"
            )
        if record.get("partition") != "dev-a":
            raise R2SemanticReuseError(f"{condition} generation must be dev-a")
        if record.get("repetition") != 1:
            raise R2SemanticReuseError(f"{condition} generation repetition is invalid")
        run_ids.add(_text(record.get("run_id"), "generation run ID"))
        generation_state = record.get("generation_outcome")
        if generation_state not in {"answered", "errored", "refused"}:
            raise R2SemanticReuseError(f"{condition} generation state is invalid")
        result[scheduled["instance_id"]] = _query_surface(
            record.get("generated_query"), generation_state == "answered", measures
        )
    if len(run_ids) != 1:
        raise R2SemanticReuseError(f"{condition} generation must have one run ID")
    return result


def _query_surface(
    raw_query: object, answered: bool, measures: Mapping[str, _Measure]
) -> _QuerySurface:
    if not answered:
        return _unresolved_surface()
    if isinstance(raw_query, str):
        try:
            query = json.loads(raw_query, object_pairs_hook=_strict_object)
        except (UnicodeError, json.JSONDecodeError, R2SemanticReuseError):
            return _unresolved_surface()
    elif isinstance(raw_query, Mapping):
        query = dict(raw_query)
    else:
        return _unresolved_surface()
    if not isinstance(query, Mapping) or query.get("parsed") is not True:
        return _unresolved_surface()
    sql = query.get("userEditedSQL", "")
    if not isinstance(sql, str):
        return _unresolved_surface()
    lexical_sql = _lexical_sql(sql)
    if lexical_sql is None:
        return _unresolved_surface()
    try:
        structured_references = _structured_references(query)
        aggregate_nodes = tuple(_aggregate_nodes(query.get("calculations", [])))
    except R2SemanticReuseError:
        return _unresolved_surface()
    token_references = set(_SEMANTIC_TOKEN.findall(lexical_sql))
    all_references = structured_references.union(token_references)
    return _QuerySurface(
        inline_references=frozenset(
            _inline_measure_ids(lexical_sql, aggregate_nodes, measures)
        ),
        measure_references=frozenset(
            measure_id
            for measure_id, measure in measures.items()
            if measure.measure_reference in all_references
        ),
        parseable=True,
    )


def _classification(
    control: _QuerySurface,
    treatment: _QuerySurface,
    control_inline: frozenset[str],
    treatment_inline: frozenset[str],
    treatment_references: frozenset[str],
) -> str:
    if not control.parseable and not treatment.parseable:
        return "unresolved_both"
    if not control.parseable:
        return "unresolved_control"
    if not treatment.parseable:
        return "unresolved_treatment"
    if control_inline.intersection(treatment_references).difference(treatment_inline):
        return "verified_replacement"
    if treatment_references.intersection(treatment_inline):
        return "measure_reference_with_inline_recreation"
    if treatment_references:
        return "measure_reference_without_bridge_inline"
    return "no_measure_reference"


def _inline_measure_ids(
    sql: str,
    aggregate_nodes: Sequence[Mapping[str, Any]],
    measures: Mapping[str, _Measure],
) -> set[str]:
    result: set[str] = set()
    for measure_id, measure in measures.items():
        if _sql_has_inline(sql, measure) or any(
            _aggregate_matches(node, measure) for node in aggregate_nodes
        ):
            result.add(measure_id)
    return result


def _sql_has_inline(sql: str, measure: _Measure) -> bool:
    token = re.escape(f"${{{measure.source_reference}}}")
    if measure.aggregate_type == "count_distinct":
        function = r"COUNT\s*\(\s*DISTINCT\s+" + token + r"\s*\)"
    elif measure.aggregate_type == "average":
        function = r"(?:AVG|AVERAGE)\s*\(\s*" + token + r"\s*\)"
    else:
        function = r"SUM\s*\(\s*" + token + r"\s*\)"
    return re.search(r"(?i)(?<![A-Za-z0-9_])" + function, sql) is not None


def _aggregate_matches(node: Mapping[str, Any], measure: _Measure) -> bool:
    operator = node.get("operator")
    if not isinstance(operator, str):
        return False
    normalized = operator.rsplit(".", 1)[-1].casefold()
    distinct = node.get("distinct")
    if measure.aggregate_type == "count_distinct":
        operator_matches = normalized == "count_distinct" or (
            normalized == "count" and distinct is True
        )
    elif measure.aggregate_type == "average":
        operator_matches = normalized in {"avg", "average"} and distinct is not True
    else:
        operator_matches = normalized == "sum" and distinct is not True
    operands = node.get("operands")
    return bool(
        operator_matches
        and isinstance(operands, list)
        and len(operands) == 1
        and isinstance(operands[0], Mapping)
        and operands[0].get("field_name") == measure.source_reference
    )


def _aggregate_nodes(value: object) -> Sequence[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            aggregate = item.get("aggregate")
            if aggregate is not None:
                if not isinstance(aggregate, Mapping):
                    raise R2SemanticReuseError("structured aggregate is invalid")
                result.append(aggregate)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for nested in item:
                visit(nested)

    visit(value)
    return result


def _structured_references(query: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for key in ("fields", "pivots"):
        values = query.get(key, [])
        if not isinstance(values, list) or any(
            not isinstance(item, str) for item in values
        ):
            raise R2SemanticReuseError(f"structured query {key} is invalid")
        result.update(item for item in values if _QUALIFIED_NAME.fullmatch(item))
    sorts = query.get("sorts", [])
    if not isinstance(sorts, list) or any(
        not isinstance(item, Mapping) for item in sorts
    ):
        raise R2SemanticReuseError("structured query sorts are invalid")
    for item in sorts:
        name = item.get("column_name")
        if isinstance(name, str) and _QUALIFIED_NAME.fullmatch(name):
            result.add(name)
    filters = query.get("filters", {})
    if not isinstance(filters, Mapping):
        raise R2SemanticReuseError("structured query filters are invalid")
    for outer, value in filters.items():
        if not isinstance(outer, str):
            raise R2SemanticReuseError("structured query filter key is invalid")
        if _QUALIFIED_NAME.fullmatch(outer):
            result.add(outer)
        elif _SAFE_NAME.fullmatch(outer) and isinstance(value, Mapping):
            result.update(
                f"{outer}.{inner}"
                for inner in value
                if isinstance(inner, str) and _SAFE_NAME.fullmatch(inner)
            )
    calculations = query.get("calculations", [])
    if not isinstance(calculations, list) or any(
        not isinstance(item, Mapping) for item in calculations
    ):
        raise R2SemanticReuseError("structured query calculations are invalid")

    def visit(item: object) -> None:
        if isinstance(item, Mapping):
            field_name = item.get("field_name")
            if isinstance(field_name, str) and _QUALIFIED_NAME.fullmatch(field_name):
                result.add(field_name)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for nested in item:
                visit(nested)

    visit(calculations)
    return result


def _lexical_sql(sql: str) -> str | None:
    output = list(sql)
    index = 0
    length = len(sql)
    while index < length:
        if sql.startswith("--", index):
            end = sql.find("\n", index + 2)
            if end == -1:
                end = length
            _blank(output, index, end)
            index = end
            continue
        if sql.startswith("/*", index):
            depth = 1
            cursor = index + 2
            while cursor < length and depth:
                if sql.startswith("/*", cursor):
                    depth += 1
                    cursor += 2
                elif sql.startswith("*/", cursor):
                    depth -= 1
                    cursor += 2
                else:
                    cursor += 1
            if depth:
                return None
            _blank(output, index, cursor)
            index = cursor
            continue
        if sql[index] == "'":
            cursor = index + 1
            while cursor < length:
                if sql[cursor] == "\\" and cursor + 1 < length:
                    cursor += 2
                    continue
                if sql[cursor] == "'":
                    if cursor + 1 < length and sql[cursor + 1] == "'":
                        cursor += 2
                        continue
                    cursor += 1
                    break
                cursor += 1
            else:
                return None
            _blank(output, index, cursor)
            index = cursor
            continue
        if sql[index] == "$" and not sql.startswith("${", index):
            match = _DOLLAR_QUOTE.match(sql, index)
            if match is not None:
                delimiter = match.group(0)
                end = sql.find(delimiter, match.end())
                if end == -1:
                    return None
                cursor = end + len(delimiter)
                _blank(output, index, cursor)
                index = cursor
                continue
        index += 1
    return "".join(output)


def _blank(output: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if output[index] != "\n":
            output[index] = " "


def _unresolved_surface() -> _QuerySurface:
    return _QuerySurface(frozenset(), frozenset(), False)


def _wilson_interval(numerator: int, denominator: int) -> dict[str, float] | None:
    if denominator == 0:
        return None
    z = 1.959963984540054
    proportion = numerator / denominator
    z_squared = z * z
    denominator_term = 1 + z_squared / denominator
    center = (proportion + z_squared / (2 * denominator)) / denominator_term
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / denominator
            + z_squared / (4 * denominator * denominator)
        )
        / denominator_term
    )
    return {
        "lower": round(max(0.0, center - margin), 12),
        "upper": round(min(1.0, center + margin), 12),
    }


def _validate_internal_hash(value: dict[str, Any], label: str) -> None:
    manifest = _mapping(value.get("manifest"), f"{label} manifest")
    stored = manifest.get("artifact_sha256")
    source = copy.deepcopy(value)
    source["manifest"].pop("artifact_sha256", None)
    if stored != _sha256(canonical_catalog_bytes(source)):
        raise R2SemanticReuseError(f"{label} hash is invalid")


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    if (
        not isinstance(content, bytes)
        or not content
        or len(content) > _MAX_ARTIFACT_BYTES
    ):
        raise R2SemanticReuseError(f"{label} size is invalid")
    try:
        value = json.loads(content, object_pairs_hook=_strict_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise R2SemanticReuseError(f"{label} must be valid JSON") from error
    if not isinstance(value, dict):
        raise R2SemanticReuseError(f"{label} must be an object")
    return value


def _jsonl_objects(content: bytes, label: str) -> list[dict[str, Any]]:
    if (
        not isinstance(content, bytes)
        or not content
        or len(content) > _MAX_ARTIFACT_BYTES
    ):
        raise R2SemanticReuseError(f"{label} size is invalid")
    lines = content.splitlines(keepends=True)
    if not lines or any(not line.endswith(b"\n") for line in lines):
        raise R2SemanticReuseError(f"{label} must be newline-terminated")
    result: list[dict[str, Any]] = []
    for line_number, raw in enumerate(lines, start=1):
        try:
            value = json.loads(raw, object_pairs_hook=_strict_object)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise R2SemanticReuseError(
                f"{label} line {line_number} is not valid JSON"
            ) from error
        if not isinstance(value, dict):
            raise R2SemanticReuseError(f"{label} record must be an object")
        if canonical_catalog_bytes(value) != raw:
            raise R2SemanticReuseError(f"{label} records must be canonical JSON")
        result.append(value)
    return result


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise R2SemanticReuseError(f"duplicate JSON field {key}")
        result[key] = value
    return result


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
        raise R2SemanticReuseError(f"{label} contains a protected field") from error


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise R2SemanticReuseError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise R2SemanticReuseError(f"{label} is invalid")
    return value


def _safe_name(value: object, label: str) -> str:
    text = _text(value, label)
    if _SAFE_NAME.fullmatch(text) is None:
        raise R2SemanticReuseError(f"{label} is invalid")
    return text


def _aggregate_type(value: object) -> str:
    if value not in {"average", "count_distinct", "sum"}:
        raise R2SemanticReuseError("inline-equivalent aggregate type is invalid")
    return str(value)


def _positive_int(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise R2SemanticReuseError(f"{label} is invalid")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise R2SemanticReuseError(f"{label} is invalid")
    return value


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()

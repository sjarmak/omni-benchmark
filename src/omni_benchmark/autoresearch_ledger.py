"""Append-only experiment proposals, decisions, and regression state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .autoresearch_analysis import (
    dominates,
    guard_intervention_text,
    outcome_for,
    pareto_frontier,
    run_deltas,
)

from .autoresearch_config import (
    DECISIONS,
    EXPERIMENT_TEXT_FIELDS,
    GENERALITY_SCOPES,
    OPTIMIZATION_SURFACES,
    TUNING_ACTORS,
    AutoresearchConfig,
    AutoresearchError,
    _find_forbidden,
    _require_commit,
    _require_string,
    _utc_timestamp,
)
from .autoresearch_lifecycle import (
    LedgerCheck as LedgerCheck,
    _append_event,
    _read_chained_events,
    _require_active,
    _require_baseline,
    create_baseline as create_baseline,
    create_checkpoint as create_checkpoint,
    stop_optimization as stop_optimization,
)
from .autoresearch_runs import (
    ValidatedRun,
    _number,
    validate_run,
)


def add_regression_case(
    config: AutoresearchConfig,
    *,
    instance_id: str,
    capability: str,
    rationale: str,
    source_experiment: str,
) -> dict[str, Any]:
    """Append one dev-A representative to the immutable regression suite."""
    _require_active(config)
    if instance_id not in config.dev_a_id_set:
        raise AutoresearchError("regression suite IDs must belong to dev-A")
    capability = _require_string(capability, "capability")
    rationale = _require_string(rationale, "rationale")
    source_experiment = _require_string(source_experiment, "source_experiment")
    proposals = _read_chained_events(config, config.ledger_path)
    proposal = next(
        (
            event
            for event in proposals
            if event.get("event") == "proposal"
            and event.get("experiment_id") == source_experiment
        ),
        None,
    )
    if proposal is None:
        raise AutoresearchError("source_experiment must name an existing proposal")
    condition = proposal["condition"]

    def check(events: Sequence[dict[str, Any]]) -> None:
        if any(
            event.get("instance_id") == instance_id
            and event.get("condition") == condition
            for event in events
        ):
            raise AutoresearchError("regression suite case already exists")

    payload = {
        "capability": capability,
        "condition": condition,
        "created_at": _utc_timestamp(),
        "event": "regression-case",
        "instance_id": instance_id,
        "rationale": rationale,
        "schema_version": 1,
        "source_experiment": source_experiment,
    }
    return _append_event(config, payload, check, path=config.regression_suite_path)


def _regression_evidence(
    config: AutoresearchConfig,
    before: ValidatedRun,
    after: ValidatedRun,
    *,
    condition: str,
) -> list[dict[str, object]]:
    cases = [
        case
        for case in _read_chained_events(config, config.regression_suite_path)
        if case.get("condition") == condition
    ]
    evidence: list[dict[str, object]] = []
    for case in cases:
        instance_id = case["instance_id"]
        evidence.append(
            {
                "after_outcome": outcome_for(after, instance_id),
                "before_outcome": outcome_for(before, instance_id),
                "capability": case["capability"],
                "instance_id": instance_id,
                "preserved": instance_id in after.correct_ids,
                "source_experiment": case["source_experiment"],
            }
        )
    return evidence


def read_pareto_frontier(config: AutoresearchConfig) -> tuple[dict[str, Any], ...]:
    """Return non-dominated kept branches without scalarizing objectives."""
    return tuple(pareto_frontier(_read_chained_events(config, config.ledger_path)))


def _valid_parent(parent: str, events: Sequence[dict[str, Any]]) -> bool:
    if parent == "baseline":
        return True
    return any(
        event.get("event") == "proposal" and event.get("experiment_id") == parent
        for event in events
    )


def propose_experiment(
    config: AutoresearchConfig,
    *,
    experiment_id: str,
    parent: str,
    hypothesis: str,
    intervention: str,
    affected_class: str,
    mechanism: str,
    predicted_direction: str,
    regression_risk: str,
    subsystem: str,
    generality_rationale: str,
    condition: str,
    content_provenance: str,
    intervention_provenance: str,
    tuning_actor: str,
    tuning_effort: str,
    optimization_surface: str,
    candidate_generation_method: str,
    generality_scope: str,
    candidate_variants: Sequence[Mapping[str, Any]] = (),
    evaluation_subset: Sequence[str] = (),
) -> dict[str, Any]:
    """Append a prespecified experiment proposal before any decision exists."""
    _require_active(config)
    _require_baseline(config)
    values = {
        "hypothesis": hypothesis,
        "intervention": intervention,
        "affected_class": affected_class,
        "mechanism": mechanism,
        "predicted_direction": predicted_direction,
        "regression_risk": regression_risk,
        "subsystem": subsystem,
        "generality_rationale": generality_rationale,
    }
    experiment_id = _require_string(experiment_id, "experiment_id")
    parent = _require_string(parent, "parent")
    for field in EXPERIMENT_TEXT_FIELDS:
        values[field] = _require_string(values[field], field)
    guard_intervention_text(intervention, config.train_ids)
    if condition not in {"C1", "C2", "C3", "C4"}:
        raise AutoresearchError("condition must be C1, C2, C3, or C4")
    content_provenance = _require_string(content_provenance, "content_provenance")
    intervention_provenance = _require_string(
        intervention_provenance, "intervention_provenance"
    )
    if tuning_actor not in TUNING_ACTORS:
        raise AutoresearchError("tuning_actor is not recognized")
    tuning_effort = _require_string(tuning_effort, "tuning_effort")
    if optimization_surface not in OPTIMIZATION_SURFACES:
        raise AutoresearchError("optimization_surface is not recognized")
    if (
        optimization_surface == "human_research_controlled"
        and tuning_actor == "autonomous_agent"
    ):
        raise AutoresearchError(
            "human-research-controlled surfaces require human participation"
        )
    candidate_generation_method = _require_string(
        candidate_generation_method, "candidate_generation_method"
    )
    if generality_scope not in GENERALITY_SCOPES:
        raise AutoresearchError("generality_scope is not recognized")
    if generality_scope == "question_specific":
        raise AutoresearchError("question_specific interventions are forbidden")
    variants = tuple(candidate_variants)
    if any(not isinstance(variant, Mapping) for variant in variants):
        raise AutoresearchError("candidate_variants must contain objects")
    if _find_forbidden(list(variants), config.forbidden_fields) is not None:
        raise AutoresearchError("candidate_variants contain a forbidden field")
    guard_intervention_text(json.dumps(variants, sort_keys=True), config.train_ids)
    subset = tuple(evaluation_subset)
    if any(
        not isinstance(value, str) or value not in config.dev_a_id_set
        for value in subset
    ):
        raise AutoresearchError("evaluation_subset must contain only dev-A IDs")
    if len(set(subset)) != len(subset):
        raise AutoresearchError("evaluation_subset contains duplicate IDs")

    def check(events: Sequence[dict[str, Any]]) -> None:
        if any(event.get("experiment_id") == experiment_id for event in events):
            raise AutoresearchError("experiment ID already exists")
        if not _valid_parent(parent, events):
            raise AutoresearchError("parent must be baseline or an existing candidate")

    payload = {
        "affected_class": affected_class,
        "created_at": _utc_timestamp(),
        "candidate_generation_method": candidate_generation_method,
        "candidate_variants": list(variants),
        "condition": condition,
        "content_provenance": content_provenance,
        "evaluation_subset": list(subset),
        "event": "proposal",
        "experiment_id": experiment_id,
        "generality_rationale": generality_rationale,
        "generality_scope": generality_scope,
        "hypothesis": hypothesis,
        "intervention": intervention,
        "intervention_provenance": intervention_provenance,
        "mechanism": mechanism,
        "parent": parent,
        "optimization_surface": optimization_surface,
        "predicted_direction": predicted_direction,
        "regression_risk": regression_risk,
        "schema_version": 1,
        "subsystem": subsystem,
        "tuning_actor": tuning_actor,
        "tuning_effort": tuning_effort,
    }
    return _append_event(config, payload, check)


def decide_experiment(
    config: AutoresearchConfig,
    *,
    experiment_id: str,
    decision: str,
    before_run_path: Path,
    after_run_path: Path,
    before_score_path: Path | None = None,
    before_score_sha256: str | None = None,
    before_run_manifest_path: Path | None = None,
    before_run_manifest_sha256: str | None = None,
    after_score_path: Path | None = None,
    after_score_sha256: str | None = None,
    after_run_manifest_path: Path | None = None,
    after_run_manifest_sha256: str | None = None,
    git_commit: str,
    rationale: str,
    complexity_impact: str,
    production_relevance: str,
    complexity_score: float,
    special_case_count: int,
    stability_rate: float,
    unexpected_observations: str,
    follow_up_hypotheses: Sequence[str],
) -> dict[str, Any]:
    """Record a human/model decision using mechanically computed full-train deltas."""
    _require_active(config)
    if decision not in DECISIONS:
        raise AutoresearchError("decision is not allowed by the experiment protocol")
    experiment_id = _require_string(experiment_id, "experiment_id")
    rationale = _require_string(rationale, "rationale")
    complexity_impact = _require_string(complexity_impact, "complexity_impact")
    production_relevance = _require_string(production_relevance, "production_relevance")
    complexity = _number(complexity_score, "complexity_score")
    if (
        isinstance(special_case_count, bool)
        or not isinstance(special_case_count, int)
        or special_case_count < 0
    ):
        raise AutoresearchError("special_case_count must be a non-negative integer")
    stability = _number(stability_rate, "stability_rate")
    if stability is None or stability > 1:
        raise AutoresearchError("stability_rate must be between zero and one")
    unexpected_observations = _require_string(
        unexpected_observations, "unexpected_observations"
    )
    hypotheses = tuple(follow_up_hypotheses)
    if any(not isinstance(value, str) or not value for value in hypotheses):
        raise AutoresearchError("follow_up_hypotheses must contain non-empty strings")
    before = validate_run(
        config,
        before_run_path,
        score_path=before_score_path,
        expected_score_sha256=before_score_sha256,
        manifest_path=before_run_manifest_path,
        expected_manifest_sha256=before_run_manifest_sha256,
    )
    after = validate_run(
        config,
        after_run_path,
        score_path=after_score_path,
        expected_score_sha256=after_score_sha256,
        manifest_path=after_run_manifest_path,
        expected_manifest_sha256=after_run_manifest_sha256,
    )
    commit = _require_commit(git_commit)
    parent: str | None = None
    proposal: dict[str, Any] | None = None
    existing_events = _read_chained_events(config, config.ledger_path)
    preview = next(
        (
            event
            for event in existing_events
            if event.get("event") == "proposal"
            and event.get("experiment_id") == experiment_id
        ),
        None,
    )
    if preview is None:
        raise AutoresearchError("proposal must be recorded first")
    if (
        before.condition != preview["condition"]
        or after.condition != preview["condition"]
    ):
        raise AutoresearchError("run condition must match the experiment proposal")
    if before.repetition != after.repetition:
        raise AutoresearchError("before and after runs must use the same repetition")
    evidence = _regression_evidence(
        config, before, after, condition=preview["condition"]
    )
    deltas = run_deltas(before, after)

    def check(events: Sequence[dict[str, Any]]) -> None:
        nonlocal parent, proposal
        proposals = [
            event
            for event in events
            if event.get("event") == "proposal"
            and event.get("experiment_id") == experiment_id
        ]
        if not proposals:
            raise AutoresearchError("proposal must be recorded first")
        if any(
            event.get("event") == "decision"
            and event.get("experiment_id") == experiment_id
            for event in events
        ):
            raise AutoresearchError("experiment already has a decision")
        proposal = proposals[0]
        parent = proposal["parent"]
        if decision == "KEEP" and not evidence:
            raise AutoresearchError("KEEP requires a non-empty regression suite")
        if decision == "KEEP" and not all(item["preserved"] for item in evidence):
            raise AutoresearchError("KEEP requires regression suite preservation")
        if decision == "KEEP" and proposal["generality_scope"] == "benchmark_specific":
            raise AutoresearchError("benchmark_specific candidates cannot be kept")
        vector = {
            "accuracy": after.accuracy,
            "complexity": complexity,
            "cost": after.total_cost_usd,
            "error_rate": after.error_rate,
            "generality": GENERALITY_SCOPES[proposal["generality_scope"]],
            "latency": after.mean_latency_ms,
            "refusal_rate": after.refusal_rate,
            "refused_or_error_rate": after.refused_or_error_rate,
            "regression_count": len(deltas["regressed_questions"]),
            "special_case_count": special_case_count,
            "stability": stability,
            "wrong_answer_rate": after.wrong_answer_rate,
        }
        if decision == "KEEP" and any(
            dominates(event["candidate_vector"], vector)
            for event in pareto_frontier(events)
            if event.get("condition") == proposal["condition"]
        ):
            raise AutoresearchError("dominated candidate cannot be kept; use ARCHIVE")
        payload.update(
            {
                "candidate_vector": vector,
                "condition": proposal["condition"],
                "content_provenance": proposal["content_provenance"],
                "generality_scope": proposal["generality_scope"],
                "intervention_provenance": proposal["intervention_provenance"],
                "parent": parent,
                "pareto": {
                    "dimensions": {
                        "maximize": ["accuracy", "stability", "generality"],
                        "minimize": [
                            "wrong_answer_rate",
                            "refused_or_error_rate",
                            "regression_count",
                            "cost",
                            "latency",
                            "complexity",
                            "special_case_count",
                        ],
                    },
                    "status": "non_dominated" if decision == "KEEP" else "not_kept",
                },
                "tuning_actor": proposal["tuning_actor"],
                "tuning_effort": proposal["tuning_effort"],
            }
        )

    payload = {
        "after_run": after.as_manifest(config.workspace),
        "before_run": before.as_manifest(config.workspace),
        "complexity_impact": complexity_impact,
        "created_at": _utc_timestamp(),
        "decision": decision,
        "event": "decision",
        "experiment_id": experiment_id,
        "follow_up_hypotheses": list(hypotheses),
        "git_commit": commit,
        "metrics": deltas,
        "production_relevance": production_relevance,
        "rationale": rationale,
        "regression_suite_evidence": evidence,
        "schema_version": 1,
        "unexpected_observations": unexpected_observations,
    }

    def check_with_parent(events: Sequence[dict[str, Any]]) -> None:
        check(events)

    return _append_event(config, payload, check_with_parent)

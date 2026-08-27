"""Command-line interface for train-only autoresearch artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .autoresearch_config import (
    GENERALITY_SCOPES,
    OPTIMIZATION_SURFACES,
    TUNING_ACTORS,
    AutoresearchConfig,
    _display_path,
    create_public_dev_a_view,
    load_config,
)
from .autoresearch_ledger import (
    DECISIONS,
    add_regression_case,
    create_baseline,
    create_checkpoint,
    decide_experiment,
    propose_experiment,
    stop_optimization,
)
from .autoresearch_smoke import TelemetrySmokeBundle, validate_telemetry_smoke


def _add_telemetry_smoke_parser(subparsers: argparse._SubParsersAction) -> None:
    telemetry_smoke = subparsers.add_parser("telemetry-smoke")
    telemetry_smoke.add_argument("--scope", choices=("train", "dev-a"), default="train")
    telemetry_smoke.add_argument(
        "--bundle",
        action="append",
        nargs=4,
        required=True,
        metavar=("CONDITION", "GENERATION", "RUN_MANIFEST", "MANIFEST_SHA256"),
    )


def _add_baseline_parser(subparsers: argparse._SubParsersAction) -> None:
    baseline = subparsers.add_parser("baseline")
    baseline.add_argument("--run", type=Path, required=True)
    baseline.add_argument("--run-manifest", type=Path)
    baseline.add_argument("--run-manifest-sha256")
    baseline.add_argument("--git-commit", required=True)


def _add_propose_parser(subparsers: argparse._SubParsersAction) -> None:
    propose = subparsers.add_parser("propose")
    propose.add_argument("--experiment-id", required=True)
    propose.add_argument("--parent", required=True)
    for option in (
        "hypothesis",
        "intervention",
        "affected-class",
        "mechanism",
        "predicted-direction",
        "regression-risk",
        "subsystem",
        "generality-rationale",
    ):
        propose.add_argument(f"--{option}", required=True)
    propose.add_argument("--evaluation-id", action="append", default=[])
    propose.add_argument("--condition", choices=("C1", "C2", "C3", "C4"), required=True)
    propose.add_argument("--content-provenance", required=True)
    propose.add_argument("--intervention-provenance", required=True)
    propose.add_argument("--tuning-actor", choices=sorted(TUNING_ACTORS), required=True)
    propose.add_argument("--tuning-effort", required=True)
    propose.add_argument(
        "--optimization-surface", choices=sorted(OPTIMIZATION_SURFACES), required=True
    )
    propose.add_argument("--candidate-generation-method", required=True)
    propose.add_argument(
        "--generality-scope", choices=sorted(GENERALITY_SCOPES), required=True
    )


def _add_regression_parser(subparsers: argparse._SubParsersAction) -> None:
    regression = subparsers.add_parser("regression-add")
    regression.add_argument("--instance-id", required=True)
    regression.add_argument("--capability", required=True)
    regression.add_argument("--rationale", required=True)
    regression.add_argument("--source-experiment", required=True)


def _add_decide_parser(subparsers: argparse._SubParsersAction) -> None:
    decide = subparsers.add_parser("decide")
    decide.add_argument("--experiment-id", required=True)
    decide.add_argument("--decision", choices=sorted(DECISIONS), required=True)
    decide.add_argument("--before-run", type=Path, required=True)
    decide.add_argument("--before-score", type=Path)
    decide.add_argument("--before-score-sha256")
    decide.add_argument("--before-run-manifest", type=Path)
    decide.add_argument("--before-run-manifest-sha256")
    decide.add_argument("--after-run", type=Path, required=True)
    decide.add_argument("--after-score", type=Path)
    decide.add_argument("--after-score-sha256")
    decide.add_argument("--after-run-manifest", type=Path)
    decide.add_argument("--after-run-manifest-sha256")
    decide.add_argument("--git-commit", required=True)
    decide.add_argument("--rationale", required=True)
    decide.add_argument("--complexity-impact", required=True)
    decide.add_argument("--production-relevance", required=True)
    decide.add_argument("--complexity-score", type=float, required=True)
    decide.add_argument("--special-case-count", type=int, required=True)
    decide.add_argument("--stability-rate", type=float, required=True)
    decide.add_argument("--unexpected-observations", required=True)
    decide.add_argument("--follow-up-hypothesis", action="append", default=[])


def _add_checkpoint_parser(subparsers: argparse._SubParsersAction) -> None:
    checkpoint = subparsers.add_parser("checkpoint")
    checkpoint.add_argument("--name", required=True)
    checkpoint.add_argument("--run", type=Path, required=True)
    checkpoint.add_argument("--score", type=Path)
    checkpoint.add_argument("--score-sha256")
    checkpoint.add_argument("--run-manifest", type=Path)
    checkpoint.add_argument("--run-manifest-sha256")
    checkpoint.add_argument("--dev-b-receipt", type=Path, required=True)
    checkpoint.add_argument("--dev-b-signature", type=Path, required=True)
    checkpoint.add_argument("--guardian-public-key", type=Path, required=True)
    checkpoint.add_argument("--taxonomy", type=Path, required=True)
    checkpoint.add_argument("--git-commit", required=True)


def _add_stop_parser(subparsers: argparse._SubParsersAction) -> None:
    stop = subparsers.add_parser("stop")
    stop.add_argument("--reason", required=True)
    stop.add_argument("--rationale", required=True)
    stop.add_argument("--git-commit", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--freeze-a-commit", required=True)
    parser.add_argument("--baseline-commit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("public-dev-a")
    _add_telemetry_smoke_parser(subparsers)
    _add_baseline_parser(subparsers)
    _add_propose_parser(subparsers)
    _add_regression_parser(subparsers)
    _add_decide_parser(subparsers)
    _add_checkpoint_parser(subparsers)
    _add_stop_parser(subparsers)
    return parser


def _path_output(config: AutoresearchConfig, path: Path, status: str) -> dict[str, str]:
    return {"path": _display_path(path, config.workspace), "status": status}


def _handle_public_dev_a(
    config: AutoresearchConfig, arguments: argparse.Namespace
) -> dict[str, object]:
    del arguments
    return _path_output(config, create_public_dev_a_view(config), "created")


def _handle_telemetry_smoke(
    config: AutoresearchConfig, arguments: argparse.Namespace
) -> dict[str, object]:
    bundles = [
        TelemetrySmokeBundle(
            condition=condition,
            generation_path=Path(generation_path),
            run_manifest_path=Path(run_manifest_path),
            expected_run_manifest_sha256=manifest_sha256,
        )
        for condition, generation_path, run_manifest_path, manifest_sha256 in (
            arguments.bundle
        )
    ]
    return {
        **validate_telemetry_smoke(config, bundles, scope=arguments.scope),
        "status": "validated",
    }


def _handle_baseline(
    config: AutoresearchConfig, arguments: argparse.Namespace
) -> dict[str, object]:
    path = create_baseline(
        config,
        run_path=arguments.run,
        run_manifest_path=arguments.run_manifest,
        run_manifest_sha256=arguments.run_manifest_sha256,
        git_commit=arguments.git_commit,
    )
    return _path_output(config, path, "created")


def _handle_propose(
    config: AutoresearchConfig, arguments: argparse.Namespace
) -> dict[str, object]:
    event = propose_experiment(
        config,
        experiment_id=arguments.experiment_id,
        parent=arguments.parent,
        hypothesis=arguments.hypothesis,
        intervention=arguments.intervention,
        affected_class=arguments.affected_class,
        mechanism=arguments.mechanism,
        predicted_direction=arguments.predicted_direction,
        regression_risk=arguments.regression_risk,
        subsystem=arguments.subsystem,
        generality_rationale=arguments.generality_rationale,
        condition=arguments.condition,
        content_provenance=arguments.content_provenance,
        intervention_provenance=arguments.intervention_provenance,
        tuning_actor=arguments.tuning_actor,
        tuning_effort=arguments.tuning_effort,
        optimization_surface=arguments.optimization_surface,
        candidate_generation_method=arguments.candidate_generation_method,
        generality_scope=arguments.generality_scope,
        evaluation_subset=arguments.evaluation_id,
    )
    return {"event_sha256": event["event_sha256"], "status": "proposed"}


def _handle_regression_add(
    config: AutoresearchConfig, arguments: argparse.Namespace
) -> dict[str, object]:
    event = add_regression_case(
        config,
        instance_id=arguments.instance_id,
        capability=arguments.capability,
        rationale=arguments.rationale,
        source_experiment=arguments.source_experiment,
    )
    return {"event_sha256": event["event_sha256"], "status": "added"}


def _handle_decide(
    config: AutoresearchConfig, arguments: argparse.Namespace
) -> dict[str, object]:
    event = decide_experiment(
        config,
        experiment_id=arguments.experiment_id,
        decision=arguments.decision,
        before_run_path=arguments.before_run,
        before_score_path=arguments.before_score,
        before_score_sha256=arguments.before_score_sha256,
        before_run_manifest_path=arguments.before_run_manifest,
        before_run_manifest_sha256=arguments.before_run_manifest_sha256,
        after_run_path=arguments.after_run,
        after_score_path=arguments.after_score,
        after_score_sha256=arguments.after_score_sha256,
        after_run_manifest_path=arguments.after_run_manifest,
        after_run_manifest_sha256=arguments.after_run_manifest_sha256,
        git_commit=arguments.git_commit,
        rationale=arguments.rationale,
        complexity_impact=arguments.complexity_impact,
        production_relevance=arguments.production_relevance,
        complexity_score=arguments.complexity_score,
        special_case_count=arguments.special_case_count,
        stability_rate=arguments.stability_rate,
        unexpected_observations=arguments.unexpected_observations,
        follow_up_hypotheses=arguments.follow_up_hypothesis,
    )
    return {"event_sha256": event["event_sha256"], "status": arguments.decision}


def _handle_checkpoint(
    config: AutoresearchConfig, arguments: argparse.Namespace
) -> dict[str, object]:
    path = create_checkpoint(
        config,
        name=arguments.name,
        run_path=arguments.run,
        score_path=arguments.score,
        score_sha256=arguments.score_sha256,
        run_manifest_path=arguments.run_manifest,
        run_manifest_sha256=arguments.run_manifest_sha256,
        dev_b_receipt_path=arguments.dev_b_receipt,
        dev_b_signature_path=arguments.dev_b_signature,
        guardian_public_key_path=arguments.guardian_public_key,
        taxonomy_path=arguments.taxonomy,
        git_commit=arguments.git_commit,
    )
    return _path_output(config, path, "created")


def _handle_stop(
    config: AutoresearchConfig, arguments: argparse.Namespace
) -> dict[str, object]:
    path = stop_optimization(
        config,
        reason=arguments.reason,
        rationale=arguments.rationale,
        git_commit=arguments.git_commit,
    )
    return _path_output(config, path, "stopped")


_COMMAND_HANDLERS = {
    "public-dev-a": _handle_public_dev_a,
    "telemetry-smoke": _handle_telemetry_smoke,
    "baseline": _handle_baseline,
    "propose": _handle_propose,
    "regression-add": _handle_regression_add,
    "decide": _handle_decide,
    "checkpoint": _handle_checkpoint,
    "stop": _handle_stop,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run the train-only autoresearch artifact lifecycle CLI."""
    arguments = _parser().parse_args(argv)
    config = load_config(
        arguments.config,
        workspace=arguments.workspace,
        freeze_a_commit=arguments.freeze_a_commit,
        baseline_commit=arguments.baseline_commit,
    )
    output = _COMMAND_HANDLERS[arguments.command](config, arguments)
    print(json.dumps(output, sort_keys=True))
    return 0

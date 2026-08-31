#!/usr/bin/env python3
"""Create an aggregate-only E02 diagnostic without regenerating answers."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence


SCORERS = ("official_soft_ex", "sensitivity")
FAILURE_CLASSES = (
    "adapter_transport_error",
    "unsupported_semantic_result_type",
)
OUTCOMES = ("correct", "wrong_answer", "refused_or_error", "unscorable")


class DiagnosticError(ValueError):
    """Raised when diagnostic inputs are incomplete or do not match."""


def canonical_bytes(value: object) -> bytes:
    """Return canonical, newline-terminated JSON bytes."""

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


def _identity_from_attempt_id(attempt_id: object) -> str:
    if not isinstance(attempt_id, str) or attempt_id.count(":") < 3:
        raise DiagnosticError("attempt identity is invalid")
    _, identity = attempt_id.split(":", 1)
    instance_id, condition, repetition = identity.rsplit(":", 2)
    if not instance_id or condition != "C4" or repetition != "1":
        raise DiagnosticError("attempt identity is invalid")
    return identity


def _entry_identity(entry: Mapping[str, object]) -> str:
    expected = (
        f"{entry.get('instance_id')}:{entry.get('condition')}:{entry.get('repetition')}"
    )
    actual = _identity_from_attempt_id(entry.get("attempt_id"))
    if actual != expected:
        raise DiagnosticError("selection attempt identity does not reconcile")
    return actual


def derive_answered_selection(
    source_selection: Mapping[str, Any],
    generations: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return an answered-only diagnostic selection and private classification."""

    entries = source_selection.get("entries")
    scheduled = source_selection.get("scheduled_entries")
    counts = source_selection.get("counts")
    if not isinstance(entries, list) or not isinstance(scheduled, list):
        raise DiagnosticError("selection entries are invalid")
    if not isinstance(counts, Mapping) or len(entries) == 0:
        raise DiagnosticError("selection counts are invalid")
    if set(generations) != {entry.get("attempt_id") for entry in entries}:
        raise DiagnosticError("generation records do not match the frozen selection")

    answered: list[dict[str, Any]] = []
    strata: dict[str, Counter[str]] = {
        name: Counter(count=0, saved_query=0) for name in FAILURE_CLASSES
    }
    identity_strata: dict[str, str] = {}
    for raw_entry in entries:
        if not isinstance(raw_entry, Mapping):
            raise DiagnosticError("selection entry is invalid")
        entry = dict(raw_entry)
        attempt_id = entry.get("attempt_id")
        record = generations.get(attempt_id)
        if not isinstance(record, Mapping):
            raise DiagnosticError("generation record is invalid")
        outcome = record.get("generation_outcome")
        if outcome == "answered":
            if record.get("failure_origin") not in (None, ""):
                raise DiagnosticError("answered record has a failure origin")
            answered.append(entry)
            continue
        if (
            outcome != "errored"
            or record.get("failure_origin") != "benchmark_infrastructure"
        ):
            raise DiagnosticError(
                "diagnostic accepts only infrastructure capture failures"
            )
        failure_class = record.get("terminal_failure_class")
        if failure_class not in FAILURE_CLASSES:
            raise DiagnosticError("diagnostic failure class is not preregistered")
        strata[failure_class]["count"] += 1
        if record.get("generated_query") is not None:
            strata[failure_class]["saved_query"] += 1
        identity_strata[_entry_identity(entry)] = failure_class

    derived = copy.deepcopy(dict(source_selection))
    derived["entries"] = answered
    new_counts = dict(counts)
    new_counts.update(
        {
            "answerable_attempts": len(answered),
            "attempts": len(answered),
            "answered": len(answered),
            "databases": len({entry["database"] for entry in answered}),
            "errored": 0,
            "refused": 0,
            "scheduled_attempts": len(scheduled),
            "scheduled_databases": len({entry["database"] for entry in scheduled}),
            "unscorable_attempts": len(scheduled) - len(answered),
        }
    )
    # Synthetic unit fixtures use the same semantics with legacy count labels.
    for old in ("answerable_questions", "scheduled_questions", "unscorable_questions"):
        new_counts.pop(old, None)
    derived["counts"] = new_counts
    public_strata = {
        name: {
            "count": strata[name]["count"],
            "saved_query": strata[name]["saved_query"],
        }
        for name in FAILURE_CLASSES
    }
    return derived, {
        "answered": len(answered),
        "failure_strata": public_strata,
        "frozen_attempts": len(entries),
        "scheduled_attempts": len(scheduled),
        "_failure_strata_by_identity": identity_strata,
    }


def _score_outcomes(score: Mapping[str, Any]) -> dict[str, str]:
    attempts = score.get("attempts")
    if not isinstance(attempts, list):
        raise DiagnosticError("score attempts are invalid")
    result: dict[str, str] = {}
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise DiagnosticError("score attempt is invalid")
        identity = _identity_from_attempt_id(attempt.get("attempt_id"))
        outcome = attempt.get("outcome")
        normalized = "unscorable" if outcome is None else outcome
        if normalized not in OUTCOMES or identity in result:
            raise DiagnosticError("score outcome or identity is invalid")
        result[identity] = normalized
    return result


def _accuracy(correct: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(correct / denominator, 6)


def summarize_diagnostic(
    *,
    source_selection: Mapping[str, Any],
    diagnostic_selection: Mapping[str, Any],
    classification: Mapping[str, Any],
    e02_scores: Mapping[str, Mapping[str, Any]],
    baseline_scores: Mapping[str, Mapping[str, Any]],
    full_scoreable_denominators: Mapping[str, int],
    provenance: Mapping[str, str],
) -> dict[str, Any]:
    """Build a matched, aggregate-only comparison and missingness bounds."""

    source_entries = source_selection.get("entries")
    diagnostic_entries = diagnostic_selection.get("entries")
    if not isinstance(source_entries, list) or not isinstance(diagnostic_entries, list):
        raise DiagnosticError("selection entries are invalid")
    source_ids = {_entry_identity(entry) for entry in source_entries}
    diagnostic_ids = {_entry_identity(entry) for entry in diagnostic_entries}
    if not diagnostic_ids < source_ids:
        raise DiagnosticError("diagnostic selection must be a strict subset")
    identity_strata = classification.get("_failure_strata_by_identity")
    if (
        not isinstance(identity_strata, Mapping)
        or set(identity_strata) != source_ids - diagnostic_ids
    ):
        raise DiagnosticError("failure strata do not match missing identities")

    scorer_reports: dict[str, Any] = {}
    for scorer in SCORERS:
        if scorer not in e02_scores or scorer not in baseline_scores:
            raise DiagnosticError("both frozen scorers are required")
        e02 = _score_outcomes(e02_scores[scorer])
        baseline = _score_outcomes(baseline_scores[scorer])
        if set(e02) != diagnostic_ids:
            raise DiagnosticError(
                f"{scorer} E02 identities do not match diagnostic selection"
            )
        if set(baseline) != source_ids:
            raise DiagnosticError(
                f"{scorer} baseline identities do not match source selection"
            )
        if {key for key, value in e02.items() if value == "unscorable"} != {
            key for key in diagnostic_ids if baseline[key] == "unscorable"
        }:
            raise DiagnosticError("matched scorer eligibility does not reconcile")

        transition: dict[str, Counter[str]] = defaultdict(Counter)
        for identity in sorted(diagnostic_ids):
            transition[baseline[identity]][e02[identity]] += 1
        missingness: dict[str, Counter[str]] = {
            name: Counter() for name in FAILURE_CLASSES
        }
        for identity, failure_class in identity_strata.items():
            missingness[failure_class][baseline[identity]] += 1

        scoreable_ids = {key for key, value in e02.items() if value != "unscorable"}
        denominator = full_scoreable_denominators.get(scorer)
        if type(denominator) is not int or denominator < len(scoreable_ids):
            raise DiagnosticError("full-frame denominator is invalid")
        e02_correct = sum(e02[key] == "correct" for key in scoreable_ids)
        baseline_correct = sum(baseline[key] == "correct" for key in scoreable_ids)
        unresolved = denominator - len(scoreable_ids)
        transport_scoreable = sum(
            failure_class == "adapter_transport_error"
            and baseline[identity] != "unscorable"
            for identity, failure_class in identity_strata.items()
        )
        scorer_reports[scorer] = {
            "captured_subset": {
                "attempts": len(diagnostic_ids),
                "baseline_accuracy": _accuracy(baseline_correct, len(scoreable_ids)),
                "baseline_correct": baseline_correct,
                "e02_accuracy": _accuracy(e02_correct, len(scoreable_ids)),
                "e02_correct": e02_correct,
                "paired_difference": round(
                    (e02_correct - baseline_correct) / len(scoreable_ids), 6
                )
                if scoreable_ids
                else None,
                "scoreable_attempts": len(scoreable_ids),
                "unscorable_attempts": len(diagnostic_ids) - len(scoreable_ids),
            },
            "full_frame_bounds": {
                "denominator": denominator,
                "known_correct": e02_correct,
                "logical_lower_accuracy": _accuracy(e02_correct, denominator),
                "logical_upper_accuracy": _accuracy(
                    e02_correct + unresolved, denominator
                ),
                "transport_only_upper_accuracy": _accuracy(
                    e02_correct + transport_scoreable, denominator
                ),
                "unresolved_scoreable_attempts": unresolved,
            },
            "missingness_baseline_outcomes": {
                name: dict(sorted(missingness[name].items()))
                for name in FAILURE_CLASSES
            },
            "transition_counts": {
                before: dict(sorted(after.items()))
                for before, after in sorted(transition.items())
            },
        }

    public_classification = {
        key: value for key, value in classification.items() if not key.startswith("_")
    }
    payload: dict[str, Any] = {
        "analysis_scope": "offline dev-A diagnostic on captured E02 answers only",
        "classification": public_classification,
        "formal_status": "INCONCLUSIVE",
        "interpretation_limit": (
            "Not a promotion estimate: 19 infrastructure losses remain unresolved, "
            "and no answer was regenerated."
        ),
        "provenance": dict(sorted(provenance.items())),
        "schema_version": 1,
        "scorers": scorer_reports,
    }
    payload["aggregate_payload_sha256"] = hashlib.sha256(
        canonical_bytes(payload)
    ).hexdigest()
    return payload


def _read_json(
    path: Path, expected_sha256: str | None = None
) -> tuple[dict[str, Any], str]:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise DiagnosticError(f"{path.name} does not match its expected SHA-256")
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DiagnosticError(f"{path.name} is not valid JSON") from error
    if not isinstance(value, dict):
        raise DiagnosticError(f"{path.name} must contain an object")
    return value, digest


def _write_exclusive(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content)


def _generation_records(
    root: Path, selection: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    output_root = selection.get("output_root")
    if not isinstance(output_root, str):
        raise DiagnosticError("selection output root is invalid")
    for entry in selection.get("entries", []):
        path = (
            root
            / output_root
            / entry["database"]
            / "c4"
            / f"{entry['instance_id']}-r{entry['repetition']}"
            / "generation.jsonl"
        )
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["generation_sha256"]:
            raise DiagnosticError("generation artifact does not match frozen SHA-256")
        lines = content.splitlines()
        if len(lines) != 1:
            raise DiagnosticError("generation artifact must contain one record")
        record = json.loads(lines[0])
        if record.get("attempt_id") != entry["attempt_id"]:
            raise DiagnosticError(
                "generation artifact identity does not match selection"
            )
        records[entry["attempt_id"]] = record
    return records


def _derive(arguments: argparse.Namespace) -> dict[str, Any]:
    selection, source_sha = _read_json(
        arguments.selection, arguments.expected_selection_sha256
    )
    records = _generation_records(arguments.artifact_workspace, selection)
    derived, classification = derive_answered_selection(selection, records)
    content = canonical_bytes(derived)
    _write_exclusive(arguments.destination, content, 0o600)
    return {
        "answered": classification["answered"],
        "derived_selection_sha256": hashlib.sha256(content).hexdigest(),
        "failure_strata": classification["failure_strata"],
        "source_selection_sha256": source_sha,
    }


def _report(arguments: argparse.Namespace) -> dict[str, Any]:
    source, source_sha = _read_json(
        arguments.source_selection, arguments.expected_source_sha256
    )
    diagnostic, diagnostic_sha = _read_json(
        arguments.diagnostic_selection, arguments.expected_diagnostic_sha256
    )
    records = _generation_records(arguments.artifact_workspace, source)
    expected_diagnostic, classification = derive_answered_selection(source, records)
    if diagnostic != expected_diagnostic:
        raise DiagnosticError(
            "diagnostic selection is not the deterministic projection"
        )

    score_inputs: dict[str, dict[str, dict[str, Any]]] = {"e02": {}, "baseline": {}}
    provenance = {
        "source_selection_sha256": source_sha,
        "diagnostic_selection_sha256": diagnostic_sha,
    }
    for arm, scorer, path in (
        ("e02", "official_soft_ex", arguments.e02_official),
        ("e02", "sensitivity", arguments.e02_sensitivity),
        ("baseline", "official_soft_ex", arguments.baseline_official),
        ("baseline", "sensitivity", arguments.baseline_sensitivity),
    ):
        value, digest = _read_json(path)
        scorer_metadata = value.get("scorer")
        if (
            not isinstance(scorer_metadata, Mapping)
            or scorer_metadata.get("identity") != scorer
        ):
            raise DiagnosticError("score artifact has the wrong frozen scorer identity")
        expected_selection = (
            diagnostic_sha
            if arm == "e02"
            else arguments.expected_baseline_selection_sha256
        )
        if value.get("selection_sha256") != expected_selection:
            raise DiagnosticError("score artifact has the wrong selection binding")
        score_inputs[arm][scorer] = value
        provenance[f"{arm}_{scorer}_sha256"] = digest
    baseline_selection_hashes = {
        score_inputs["baseline"][scorer].get("selection_sha256") for scorer in SCORERS
    }
    if len(baseline_selection_hashes) != 1 or None in baseline_selection_hashes:
        raise DiagnosticError("baseline score selection bindings do not reconcile")
    provenance["baseline_selection_sha256"] = baseline_selection_hashes.pop()
    conformance, conformance_sha = _read_json(arguments.conformance)
    provenance["dev_a_conformance_sha256"] = conformance_sha
    releases = {
        score_inputs[arm][scorer].get("release_sha256")
        for arm in ("e02", "baseline")
        for scorer in SCORERS
    }
    releases.add(conformance.get("release_sha256"))
    if len(releases) != 1 or None in releases:
        raise DiagnosticError("score and conformance release bindings do not reconcile")
    provenance["dev_a_release_sha256"] = releases.pop()
    dev_a_ids = {
        score_inputs[arm][scorer].get("dev_a_ids_sha256")
        for arm in ("e02", "baseline")
        for scorer in SCORERS
    }
    dev_a_ids.add(conformance.get("dev_a_ids_sha256"))
    if len(dev_a_ids) != 1 or None in dev_a_ids:
        raise DiagnosticError("score and conformance ID bindings do not reconcile")
    provenance["dev_a_ids_sha256"] = dev_a_ids.pop()
    denominators = {
        "official_soft_ex": conformance["official"]["scoreable_questions"],
        "sensitivity": conformance["sensitivity"]["scoreable_questions"],
    }
    for scorer, conformance_key in (
        ("official_soft_ex", "official"),
        ("sensitivity", "sensitivity"),
    ):
        frozen = conformance[conformance_key]
        for arm in ("e02", "baseline"):
            metadata = score_inputs[arm][scorer]["scorer"]
            if metadata.get("identity") != frozen.get(
                "scorer_identity"
            ) or metadata.get("version") != frozen.get("scorer_version"):
                raise DiagnosticError(
                    "score artifact does not match conformance scorer"
                )
    report = summarize_diagnostic(
        source_selection=source,
        diagnostic_selection=diagnostic,
        classification=classification,
        e02_scores=score_inputs["e02"],
        baseline_scores=score_inputs["baseline"],
        full_scoreable_denominators=denominators,
        provenance=provenance,
    )
    content = canonical_bytes(report)
    _write_exclusive(arguments.output, content, 0o644)
    return {
        "aggregate_report_sha256": hashlib.sha256(content).hexdigest(),
        "formal_status": report["formal_status"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    derive = commands.add_parser("derive")
    derive.add_argument("--artifact-workspace", type=Path, required=True)
    derive.add_argument("--selection", type=Path, required=True)
    derive.add_argument("--expected-selection-sha256", required=True)
    derive.add_argument("--destination", type=Path, required=True)
    report = commands.add_parser("report")
    report.add_argument("--artifact-workspace", type=Path, required=True)
    report.add_argument("--source-selection", type=Path, required=True)
    report.add_argument("--expected-source-sha256", required=True)
    report.add_argument("--diagnostic-selection", type=Path, required=True)
    report.add_argument("--expected-diagnostic-sha256", required=True)
    report.add_argument("--e02-official", type=Path, required=True)
    report.add_argument("--e02-sensitivity", type=Path, required=True)
    report.add_argument("--baseline-official", type=Path, required=True)
    report.add_argument("--baseline-sensitivity", type=Path, required=True)
    report.add_argument("--expected-baseline-selection-sha256", required=True)
    report.add_argument("--conformance", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = (
            _derive(arguments) if arguments.command == "derive" else _report(arguments)
        )
    except (
        DiagnosticError,
        OSError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ) as error:
        raise SystemExit(f"E02 diagnostic failed: {error}") from error
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

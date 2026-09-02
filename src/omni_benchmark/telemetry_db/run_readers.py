"""Reader for the dev-A raw run tree: generation records, traces, and scores.

The raw tree also holds dev-B attempts from the mixed public-baseline runs.
Those never enter the database: every record is gated on the dev-A split and
anything outside it is set aside with a counted reason. Score artifacts are
gated the same way, and a score entry naming an instance outside dev-A is a
custody violation rather than a drop. The sealed run has its own reader in
:mod:`sealed_readers`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .arms import ArmMapping
from .custody import SplitIds, assert_dev_a_instance
from .generation_rows import (
    GenerationRecord,
    ReaderError,
    action_evidence_rows,
    attempt_row,
    instance_of_attempt_id,
    parse_timestamp,
    read_generation_records,
    trace_event_rows,
)
from .rows import Row
from .sources import (
    BatchBuilder,
    ReleasedQuestion,
    SourceBatch,
    collapse,
    load_json_object,
    relative_to,
)

GENERATION_FILENAME = "generation.jsonl"
TRACE_FILENAME = "attempt.trace.jsonl"
ACTION_EVIDENCE_FILENAME = "attempt.action-evidence.json"
RUN_MANIFEST_FILENAME = "run.json"
FAILURE_FILENAME = "failure.json"
SCORE_DIR_GLOB = "*-scores-v*"
SCORE_FILE_GLOB = "*.score.json"
_RUN_JSON_FIELDS = (
    "scope",
    "git_commit",
    "system_commit",
    "semantic_model_ref",
    "semantic_model_sha256",
    "model",
    "provider",
    "model_config_id",
    "budget_id",
    "harness_config_sha256",
    "prompt_sha256",
    "instructions_sha256",
)


@dataclass(frozen=True)
class _Entry:
    generation: GenerationRecord
    question: ReleasedQuestion
    run_json: Mapping[str, Any] | None
    run_dir: str


def emit_generation(
    builder: BatchBuilder,
    generation: GenerationRecord,
    *,
    arm: str,
    question: ReleasedQuestion,
    trace_path: Path,
) -> None:
    """Attempt, trace, and action-evidence rows for one released generation.

    ``artifact_dir`` is the directory holding the trace, which is the attempt
    directory for dev-A and the capture directory for the sealed run. Action
    evidence is optional: Omni arms never write it, so its absence is not a
    drop.
    """
    artifact_dir = relative_to(trace_path.parent, builder.repo_root)
    builder.add(
        attempt_row(
            generation,
            arm=arm,
            database=question.database,
            partition=question.partition,
            artifact_dir=artifact_dir,
        )
    )
    if generation.record.get("trace_captured") is not True:
        builder.drop("trace_not_captured")
    elif not trace_path.is_file():
        raise ReaderError(
            f"{generation.context}: trace_captured but {trace_path} is absent"
        )
    else:
        builder.add(*trace_event_rows(trace_path, generation))
    action_path = trace_path.with_name(ACTION_EVIDENCE_FILENAME)
    if action_path.is_file():
        builder.add(*action_evidence_rows(action_path, generation))


def read_dev_a(
    raw_dir: Path,
    *,
    repo_root: Path,
    arms: ArmMapping,
    split: SplitIds,
    questions: Mapping[str, ReleasedQuestion],
) -> SourceBatch:
    """Every dev-A run directory, its traces, and both scorers' score artifacts."""
    builder = BatchBuilder("dev-a", repo_root)
    generations: dict[str, GenerationRecord] = {}
    by_run: dict[str, list[_Entry]] = defaultdict(list)
    for run_dir in sorted(raw_dir.iterdir()):
        if not run_dir.is_dir() or run_dir.name.startswith("."):
            builder.drop("raw_entry_not_a_run_directory")
        elif run_dir.match(SCORE_DIR_GLOB):
            continue
        else:
            _read_run_dir(builder, run_dir, arms, split, questions, generations, by_run)
    for run_id, entries in sorted(by_run.items()):
        builder.add(_dev_a_run_row(run_id, entries, arms))
    builder.note(
        "arms",
        {
            run_id: {
                "arms": sorted(
                    {arms.arm_for(run_id, e.generation.condition) for e in entries}
                ),
                "canonical": arms.canonical(run_id),
                "mapped": arms.mapped(run_id),
                "attempts": len(entries),
                "directories": sorted({entry.run_dir for entry in entries}),
            }
            for run_id, entries in sorted(by_run.items())
        },
    )
    _read_score_artifacts(builder, raw_dir, generations, split)
    return builder.freeze()


def _read_run_dir(
    builder: BatchBuilder,
    run_dir: Path,
    arms: ArmMapping,
    split: SplitIds,
    questions: Mapping[str, ReleasedQuestion],
    generations: dict[str, GenerationRecord],
    by_run: dict[str, list[_Entry]],
) -> None:
    generation_paths = sorted(run_dir.rglob(GENERATION_FILENAME))
    if not generation_paths:
        builder.drop("run_directory_without_generation_records")
    for failure in run_dir.rglob(FAILURE_FILENAME):
        if not failure.with_name(GENERATION_FILENAME).is_file():
            builder.drop("failure_only_attempt_directory")
    for path in generation_paths:
        run_json_path = path.with_name(RUN_MANIFEST_FILENAME)
        run_json = load_json_object(run_json_path) if run_json_path.is_file() else None
        if run_json is None:
            builder.drop("attempt_directory_without_run_json")
        for generation in read_generation_records(path):
            if generation.sha256 in generations:
                builder.drop("duplicate_generation_record")
                continue
            if generation.instance_id not in split.dev_a:
                builder.drop("attempt_instance_not_dev_a")
                continue
            question = questions.get(generation.instance_id)
            if question is None:
                builder.drop("attempt_instance_absent_from_question_release")
                continue
            generations[generation.sha256] = generation
            emit_generation(
                builder,
                generation,
                arm=arms.arm_for(generation.run_id, generation.condition),
                question=question,
                trace_path=path.with_name(TRACE_FILENAME),
            )
            by_run[generation.run_id].append(
                _Entry(generation, question, run_json, run_dir.name)
            )


def collapse_fields(
    candidates: Mapping[str, list[Any]],
) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    """Collapse each field's values; the second mapping lists the ambiguous ones."""
    values: dict[str, Any] = {}
    ambiguous: dict[str, list[Any]] = {}
    for name, candidate_values in candidates.items():
        values[name], distinct = collapse(candidate_values)
        if distinct:
            ambiguous[name] = list(distinct)
    return values, ambiguous


def time_span(
    records: list[Mapping[str, Any]], context: str
) -> tuple[datetime | None, datetime | None]:
    """Earliest start and latest finish across records; None when none carry one."""
    starts = [parse_timestamp(r.get("started_at"), context) for r in records]
    finishes = [parse_timestamp(r.get("finished_at"), context) for r in records]
    known_starts = [value for value in starts if value is not None]
    known_finishes = [value for value in finishes if value is not None]
    return (
        min(known_starts) if known_starts else None,
        max(known_finishes) if known_finishes else None,
    )


def _dev_a_run_row(run_id: str, entries: list[_Entry], arms: ArmMapping) -> Row:
    records = [entry.generation.record for entry in entries]
    manifests = [entry.run_json for entry in entries if entry.run_json is not None]
    run_json, ambiguous_json = collapse_fields(
        {name: [m.get(name) for m in manifests] for name in _RUN_JSON_FIELDS}
    )
    models = [r.get("model") or {} for r in records]
    fields, ambiguous = collapse_fields(
        {
            "condition": [r["condition"] for r in records],
            "arm": [arms.arm_for(run_id, r["condition"]) for r in records],
            "repetition": [r["repetition"] for r in records],
            "partition": [entry.question.partition for entry in entries],
            "model_name": [m.get("name") for m in models],
            "model_provider": [m.get("provider") for m in models],
            "model_version": [m.get("version") for m in models],
        }
    )
    started_at, finished_at = time_span(records, f"run {run_id}")
    return Row(
        "run",
        {
            "run_id": run_id,
            **fields,
            "scope": run_json["scope"],
            "system_commit": run_json["git_commit"],
            "semantic_model_ref": run_json["semantic_model_ref"],
            "semantic_model_sha256": run_json["semantic_model_sha256"],
            "started_at": started_at,
            "finished_at": finished_at,
            "question_count": len({r["instance_id"] for r in records}),
            "manifest": {
                "source": "dev-a",
                "source_dirs": sorted({entry.run_dir for entry in entries}),
                "attempt_count": len(entries),
                "attempts_without_run_json": len(entries) - len(manifests),
                "arm": {
                    "canonical": arms.canonical(run_id),
                    "mapped": arms.mapped(run_id),
                },
                "run_json": run_json,
                "ambiguous_fields": dict(
                    sorted({**ambiguous, **ambiguous_json}.items())
                ),
            },
        },
    )


def _read_score_artifacts(
    builder: BatchBuilder,
    raw_dir: Path,
    generations: Mapping[str, GenerationRecord],
    split: SplitIds,
) -> None:
    seen: dict[tuple[str, str, str], Row] = {}
    for score_dir in sorted(raw_dir.glob(SCORE_DIR_GLOB)):
        if not score_dir.is_dir():
            continue
        for path in sorted(score_dir.glob(SCORE_FILE_GLOB)):
            artifact_sha256 = builder.manifest(path)
            for row in _score_rows(path, artifact_sha256, generations, split):
                key = (
                    row.values["attempt_id"],
                    row.values["generation_record_sha256"],
                    row.values["scorer"],
                )
                previous = seen.get(key)
                if previous is None:
                    seen[key] = row
                    builder.add(row)
                elif _same_verdict(previous, row):
                    builder.drop("duplicate_identical_score_entry")
                else:
                    raise ReaderError(
                        f"{path}: score for {key} conflicts with an earlier artifact"
                    )


_VERDICT_COLUMNS = ("scorer_version", "outcome", "status", "failure_category")


def _same_verdict(first: Row, second: Row) -> bool:
    return all(first.values[c] == second.values[c] for c in _VERDICT_COLUMNS)


def _score_rows(
    path: Path,
    artifact_sha256: str,
    generations: Mapping[str, GenerationRecord],
    split: SplitIds,
) -> tuple[Row, ...]:
    scorer, attempts = _score_artifact(path)
    return tuple(
        _score_row(
            entry,
            f"{path}: attempts[{index}]",
            scorer=scorer,
            artifact_sha256=artifact_sha256,
            generations=generations,
            split=split,
        )
        for index, entry in enumerate(attempts)
    )


def _score_artifact(path: Path) -> tuple[Mapping[str, Any], list[Any]]:
    artifact = load_json_object(path)
    scorer = artifact.get("scorer")
    if not isinstance(scorer, dict) or not isinstance(scorer.get("identity"), str):
        raise ReaderError(f"{path}: scorer.identity must be text")
    attempts = artifact.get("attempts")
    if not isinstance(attempts, list):
        raise ReaderError(f"{path}: attempts must be a list")
    return scorer, attempts


def _score_row(
    entry: Any,
    context: str,
    *,
    scorer: Mapping[str, Any],
    artifact_sha256: str,
    generations: Mapping[str, GenerationRecord],
    split: SplitIds,
) -> Row:
    if not isinstance(entry, dict):
        raise ReaderError(f"{context}: expected an object")
    attempt_id = entry.get("attempt_id")
    sha256 = entry.get("generation_record_sha256")
    if not isinstance(attempt_id, str) or not isinstance(sha256, str):
        raise ReaderError(
            f"{context}: attempt_id and generation_record_sha256 must be text"
        )
    assert_dev_a_instance(instance_of_attempt_id(attempt_id, context), split, context)
    generation = generations.get(sha256)
    if generation is None:
        raise ReaderError(f"{context}: no generation record with sha256 {sha256}")
    if generation.attempt_id != attempt_id:
        raise ReaderError(f"{context}: attempt_id does not match the generation record")
    return Row(
        "score",
        {
            "attempt_id": attempt_id,
            "generation_record_sha256": sha256,
            "scorer": scorer["identity"],
            "scorer_version": scorer.get("version"),
            "outcome": entry.get("outcome"),
            "status": entry.get("status"),
            "failure_category": entry.get("failure_category"),
            "score_artifact_sha256": artifact_sha256,
        },
    )

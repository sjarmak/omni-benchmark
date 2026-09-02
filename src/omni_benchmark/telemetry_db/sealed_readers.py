"""Reader for the preserved sealed run: telemetry and published aggregates only.

The sealed reader has no per-attempt score path at all. It reads cohort
manifests, generation records, captures, and ``score/*/aggregate.json``; the
per-cohort score artifacts next to the aggregates are never opened.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .generation_rows import (
    GenerationRecord,
    ReaderError,
    as_decimal,
    as_integer,
    parse_timestamp,
    read_generation_records,
)
from .rows import Row
from .run_readers import GENERATION_FILENAME, RUN_MANIFEST_FILENAME, emit_generation
from .sources import (
    BatchBuilder,
    ReleasedQuestion,
    SourceBatch,
    collapse,
    load_json_object,
    relative_to,
)

#: The one preserved sealed run every sealed reader, loader default, and
#: reconciliation refers to. Declared once so the three cannot drift apart.
SEALED_RUN_ID = "sealed-final-v6"
SEALED_MANIFEST_KIND = "sealed-run-manifest"
SEALED_AGGREGATE_KIND = "sealed-aggregate-result"
CAPTURES_DIRNAME = "captures"
AGGREGATE_COUNT_COLUMNS = (
    "correct",
    "wrong_answer",
    "refused_or_error",
    "scoreable_attempts",
)
AGGREGATE_RATE_COLUMNS = (
    "mean_accuracy",
    "pass_3_rate",
    "wrong_rate",
    "refused_or_error_rate",
    "error_rate",
    "correctness_flip_rate",
)


def read_sealed(
    sealed_dir: Path,
    *,
    repo_root: Path,
    questions: Mapping[str, ReleasedQuestion],
) -> SourceBatch:
    """Sealed cohorts, captures, and aggregate reports; never per-attempt scores."""
    builder = BatchBuilder("sealed", repo_root)
    cohorts_dir = sealed_dir / "cohorts"
    if not cohorts_dir.is_dir():
        raise ReaderError(f"{cohorts_dir}: sealed cohorts directory is absent")
    for cohort_dir in sorted(cohorts_dir.iterdir()):
        if not cohort_dir.is_dir():
            builder.drop("cohorts_entry_not_a_directory")
            continue
        _read_cohort(builder, cohort_dir, sealed_dir, questions)
    _read_aggregates(builder, sealed_dir / "score", sealed_dir.name)
    return builder.freeze()


def _read_cohort(
    builder: BatchBuilder,
    cohort_dir: Path,
    sealed_dir: Path,
    questions: Mapping[str, ReleasedQuestion],
) -> None:
    manifest_path = cohort_dir / RUN_MANIFEST_FILENAME
    builder.manifest(manifest_path)
    manifest = load_json_object(manifest_path)
    if manifest.get("kind") != SEALED_MANIFEST_KIND:
        raise ReaderError(f"{manifest_path}: kind is not {SEALED_MANIFEST_KIND!r}")
    records = read_generation_records(cohort_dir / GENERATION_FILENAME)
    if not records:
        raise ReaderError(f"{cohort_dir}: cohort has no generation records")
    partitions: list[str] = []
    for generation in records:
        question = questions.get(generation.instance_id)
        if question is None:
            builder.drop("attempt_instance_absent_from_question_release")
            continue
        partitions.append(question.partition)
        emit_generation(
            builder,
            generation,
            arm=generation.condition,
            question=question,
            trace_path=_sealed_trace_path(generation, sealed_dir),
        )
    run_id = _check_cohort(cohort_dir, manifest, records)
    builder.add(
        _sealed_run_row(cohort_dir, manifest, run_id, records, partitions, builder)
    )


def _sealed_trace_path(generation: GenerationRecord, sealed_dir: Path) -> Path:
    trace_path = generation.record.get("trace_path")
    if not isinstance(trace_path, str):
        raise ReaderError(f"{generation.context}: trace_path must be text")
    marker = f"{CAPTURES_DIRNAME}/"
    if marker not in trace_path:
        raise ReaderError(f"{generation.context}: trace_path lacks a {marker} segment")
    suffix = trace_path.split(marker, 1)[1]
    return sealed_dir / CAPTURES_DIRNAME / suffix


def _check_cohort(
    cohort_dir: Path, manifest: Mapping[str, Any], records: tuple[GenerationRecord, ...]
) -> str:
    """The cohort's single run_id, after the manifest and records agree."""
    context = str(cohort_dir / RUN_MANIFEST_FILENAME)
    run_id, distinct = collapse([g.run_id for g in records])
    if distinct:
        raise ReaderError(
            f"{cohort_dir}: records carry several run_ids {list(distinct)}"
        )
    for key in ("condition", "repetition"):
        value, distinct = collapse([g.record[key] for g in records])
        if distinct or value != manifest.get(key):
            raise ReaderError(f"{context}: {key} disagrees with the cohort records")
    if manifest.get("question_count") != len({g.instance_id for g in records}):
        raise ReaderError(
            f"{context}: question_count disagrees with the cohort records"
        )
    return run_id


def _sealed_run_row(
    cohort_dir: Path,
    manifest: Mapping[str, Any],
    run_id: str,
    records: tuple[GenerationRecord, ...],
    partitions: list[str],
    builder: BatchBuilder,
) -> Row:
    context = str(cohort_dir / RUN_MANIFEST_FILENAME)
    partition, _ = collapse(partitions)
    model_version, _ = collapse(
        [(g.record.get("model") or {}).get("version") for g in records]
    )
    return Row(
        "run",
        {
            "run_id": run_id,
            "cohort_id": cohort_dir.name,
            "condition": manifest["condition"],
            "arm": manifest["condition"],
            "repetition": manifest["repetition"],
            "scope": manifest.get("scope"),
            "partition": partition,
            "model_name": manifest.get("model"),
            "model_provider": manifest.get("provider"),
            "model_version": model_version,
            "system_commit": manifest.get("system_commit"),
            "semantic_model_ref": manifest.get("semantic_model_ref"),
            "semantic_model_sha256": manifest.get("semantic_model_sha256"),
            "started_at": parse_timestamp(manifest.get("started_at"), context),
            "finished_at": parse_timestamp(manifest.get("finished_at"), context),
            "question_count": manifest["question_count"],
            "manifest": {
                "source": "sealed",
                "cohort_dir": relative_to(cohort_dir, builder.repo_root),
                "run_json": dict(manifest),
            },
        },
    )


def _read_aggregates(builder: BatchBuilder, score_dir: Path, run_id: str) -> None:
    if not score_dir.is_dir():
        raise ReaderError(f"{score_dir}: sealed score directory is absent")
    for scorer_dir in sorted(score_dir.iterdir()):
        if not scorer_dir.is_dir():
            builder.drop("score_entry_not_a_scorer_directory")
            continue
        path = scorer_dir / "aggregate.json"
        builder.manifest(path)
        aggregate = load_json_object(path)
        if aggregate.get("kind") != SEALED_AGGREGATE_KIND:
            raise ReaderError(f"{path}: kind is not {SEALED_AGGREGATE_KIND!r}")
        report = aggregate.get("report")
        conditions = report.get("conditions") if isinstance(report, dict) else None
        if not isinstance(conditions, dict) or not conditions:
            raise ReaderError(f"{path}: report.conditions must be a non-empty object")
        for condition, block in sorted(conditions.items()):
            builder.add(
                _aggregate_row(run_id, scorer_dir.name, condition, block, report, path)
            )


def _aggregate_row(
    run_id: str,
    scorer: str,
    condition: str,
    block: Any,
    report: Mapping[str, Any],
    path: Path,
) -> Row:
    context = f"{path}: report.conditions[{condition!r}]"
    if not isinstance(block, dict):
        raise ReaderError(f"{context}: expected an object")
    missing = [
        c for c in AGGREGATE_COUNT_COLUMNS + AGGREGATE_RATE_COLUMNS if c not in block
    ]
    if missing:
        raise ReaderError(f"{context}: missing {missing}")
    values: dict[str, Any] = {
        "run_id": run_id,
        "scorer": scorer,
        "condition": condition,
        "report": dict(report),
    }
    for column in AGGREGATE_COUNT_COLUMNS:
        values[column] = as_integer(block[column], f"{context}: {column}")
    for column in AGGREGATE_RATE_COLUMNS:
        values[column] = as_decimal(block[column], f"{context}: {column}")
    return Row("sealed_aggregate", values)

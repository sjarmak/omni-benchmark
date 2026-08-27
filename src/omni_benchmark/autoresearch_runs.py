"""Strict run-artifact validation for train, dev-A, and dev-B."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .autoresearch_config import (
    OUTCOMES,
    REQUIRED_RUN_FIELDS,
    AutoresearchConfig,
    AutoresearchError,
    _find_forbidden,
    _read_confined_private_jsonl,
    _public_records_by_id,
    _sha256_bytes,
)
from .autoresearch_artifacts import (
    MAX_RESULT_ARTIFACT_BYTES as MAX_RESULT_ARTIFACT_BYTES,
    MAX_RUN_ARTIFACT_BYTES,
    RESULT_ARTIFACT_FIELDS as RESULT_ARTIFACT_FIELDS,
    TRACE_EVENT_FIELDS as TRACE_EVENT_FIELDS,
    TRACE_FAILURE_TERMINAL_STATES as TRACE_FAILURE_TERMINAL_STATES,
    TRACE_ROOTS as TRACE_ROOTS,
    TRACE_SCHEMA_VERSION as _TRACE_SCHEMA_VERSION,
    TRACE_SUCCESS_TERMINAL_STATES as TRACE_SUCCESS_TERMINAL_STATES,
    _count,
    _has_opaque_result_binding,
    _number,
    _resolve_raw_run_path,
    _validate_diagnostic_trace,
    _validate_safe_record_content,
    _validate_timestamp,
    _validate_trace_reference,
    _verify_result_artifact,
    _verify_trace_artifact,
)
from .content_policy import ContentPolicy
from .autoresearch_metrics import (
    ValidatedBaselineOutputs,
    ValidatedGenerationOutputs,
    ValidatedRun,
    median_iqr,
)
from .autoresearch_provenance import validate_manifest_binding
from .score_artifacts import (
    AttemptScore,
    ScoreArtifactError,
    validate_score_artifact,
)

if TYPE_CHECKING:
    from .autoresearch_smoke import (
        validate_telemetry_smoke as validate_telemetry_smoke,
    )

BASELINE_REQUIRED_FIELDS = REQUIRED_RUN_FIELDS - {"outcome"}
TRACE_SCHEMA_VERSION = _TRACE_SCHEMA_VERSION
ALLOWED_RUN_FIELDS = REQUIRED_RUN_FIELDS | {
    "actual_result_hash",
    "actual_result_status",
    "compiler_failure_class",
    "compiler_status",
    "execution_failure_class",
    "execution_status",
    "failure_category",
    "generated_query",
    "generated_sql",
    "prior_experiment_ids",
    "prior_experiments",
    "public_hkb_nodes",
    "question",
    "query_unavailable_reason",
    "result_artifact_path",
    "result_artifact_schema_version",
    "result_artifact_sha256",
    "semantic_objects_available",
    "semantic_objects_retrieved",
    "validation_failure_class",
    "validation_status",
}


def __getattr__(name: str) -> Any:
    """Resolve the legacy smoke-validator export without an import cycle."""
    if name == "validate_telemetry_smoke":
        from .autoresearch_smoke import validate_telemetry_smoke

        return validate_telemetry_smoke
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _validate_model(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"provider", "name", "version"}:
        raise AutoresearchError("model must contain provider, name, and version")
    if any(
        item is not None and (not isinstance(item, str) or not item)
        for item in value.values()
    ):
        raise AutoresearchError("model fields must be non-empty strings or null")


def _validate_token_usage(value: Any) -> None:
    if value is None:
        return
    expected = {"input_tokens", "output_tokens", "total_tokens"}
    if not isinstance(value, dict) or set(value) != expected:
        raise AutoresearchError("token_usage must contain exact token count fields")
    try:
        counts = {key: _count(item, key, nullable=False) for key, item in value.items()}
    except AutoresearchError as error:
        raise AutoresearchError(
            "token_usage must contain a complete non-negative token count triple"
        ) from error
    if counts["total_tokens"] != counts["input_tokens"] + counts["output_tokens"]:  # type: ignore[operator]
        raise AutoresearchError(
            "total_tokens must equal input_tokens plus output_tokens"
        )


def _validate_telemetry(record: Mapping[str, Any]) -> None:
    for field in ("attempt_id", "run_id"):
        value = record[field]
        if not isinstance(value, str) or not value:
            raise AutoresearchError(f"{field} must be a non-empty string")
    started = _validate_timestamp(record["started_at"], "started_at")
    finished = _validate_timestamp(record["finished_at"], "finished_at")
    if finished < started:
        raise AutoresearchError("finished_at must not precede started_at")
    if record["condition"] not in {"C1", "C2", "C3", "C4"}:
        raise AutoresearchError("condition must be C1, C2, C3, or C4")
    repetition = record["repetition"]
    if (
        isinstance(repetition, bool)
        or not isinstance(repetition, int)
        or repetition < 1
    ):
        raise AutoresearchError("repetition must be a positive integer")
    _validate_model(record["model"])
    _validate_token_usage(record["token_usage"])
    observed_latency = _number(record["latency_ms"], "latency_ms")
    timestamp_latency = (finished - started).total_seconds() * 1000
    if abs(observed_latency - timestamp_latency) > 1:  # type: ignore[operator]
        raise AutoresearchError(
            "latency_ms must match started_at and finished_at timestamps"
        )
    for field in (
        "tool_call_count",
        "database_query_count",
        "retry_count",
        "validation_attempt_count",
    ):
        _count(record[field], field)
    failure_class = record["terminal_failure_class"]
    if failure_class is not None and (
        not isinstance(failure_class, str) or not failure_class
    ):
        raise AutoresearchError("terminal_failure_class must be a string or null")
    _validate_capture_telemetry(record)


def _validate_capture_telemetry(record: Mapping[str, Any]) -> None:
    generation_outcome = record["generation_outcome"]
    if generation_outcome not in {"answered", "refused", "errored"}:
        raise AutoresearchError(
            "generation_outcome must be answered, refused, or errored"
        )
    scored_outcome = record.get("outcome")
    if (
        scored_outcome in {"correct", "wrong_answer"}
        and generation_outcome != "answered"
    ):
        raise AutoresearchError(
            "answered scored outcomes require generation_outcome answered"
        )
    if scored_outcome == "refused_or_error" and generation_outcome == "answered":
        raise AutoresearchError(
            "refused_or_error requires generation_outcome refused or errored"
        )
    failure_origin = record["failure_origin"]
    if failure_origin not in {None, "evaluated_system"}:
        raise AutoresearchError("failure_origin must be evaluated_system or null")
    failure_class = record["terminal_failure_class"]
    if generation_outcome == "answered" and any(
        value is not None
        for value in (failure_origin, failure_class, record["harness_failure"])
    ):
        raise AutoresearchError(
            "answered attempts cannot declare a terminal evaluated-system failure"
        )
    if generation_outcome in {"refused", "errored"} and (
        failure_origin != "evaluated_system" or failure_class is None
    ):
        raise AutoresearchError(
            "refused or errored attempts require failure_origin and a terminal failure class"
        )
    for source_field, value_field in (
        ("token_source", "token_usage"),
        ("cost_source", "cost_usd"),
    ):
        source = record[source_field]
        if source not in {"provider_reported", "derived", "unavailable"}:
            raise AutoresearchError(
                f"{source_field} must be provider_reported, derived, or unavailable"
            )
        if (record[value_field] is None) != (source == "unavailable"):
            raise AutoresearchError(
                f"{source_field} must disclose whether {value_field} is available"
            )
    _validate_unavailable_counts(record)
    _validate_tool_breakdown(record)
    _validate_trace_reference(record)


def _validate_unavailable_counts(record: Mapping[str, Any]) -> None:
    supported_fields = {
        "tool_call_count",
        "database_query_count",
        "retry_count",
        "validation_attempt_count",
        "model_provider",
        "model_name",
        "model_version",
    }
    unavailable = record["telemetry_unavailable"]
    if (
        not isinstance(unavailable, list)
        or len(set(unavailable)) != len(unavailable)
        or any(field not in supported_fields for field in unavailable)
    ):
        raise AutoresearchError(
            "telemetry_unavailable must contain unique supported telemetry fields"
        )
    null_fields = {
        field
        for field in supported_fields
        if (
            record[field] is None
            if field in record
            else record["model"][field.removeprefix("model_")] is None
        )
    }
    if set(unavailable) != null_fields:
        raise AutoresearchError(
            "telemetry_unavailable must exactly identify unavailable counts"
        )


def _validate_tool_breakdown(record: Mapping[str, Any]) -> None:
    breakdown = record["tool_calls_by_name"]
    if not isinstance(breakdown, list):
        raise AutoresearchError("tool_calls_by_name must be an array")
    names: set[str] = set()
    total = 0
    for item in breakdown:
        if not isinstance(item, dict) or set(item) != {"name", "count"}:
            raise AutoresearchError(
                "tool_calls_by_name entries must contain name and count"
            )
        name = item["name"]
        count = item["count"]
        if not isinstance(name, str) or not name or name in names:
            raise AutoresearchError("tool_calls_by_name names must be unique strings")
        try:
            validated_count = _count(count, "tool_calls_by_name count", nullable=False)
        except AutoresearchError as error:
            raise AutoresearchError(
                "tool_calls_by_name counts must be non-negative integers"
            ) from error
        names.add(name)
        total += validated_count  # type: ignore[operator]
    observed_total = record["tool_call_count"]
    if observed_total is None and breakdown:
        raise AutoresearchError(
            "tool_calls_by_name must be empty when tool_call_count is unavailable"
        )
    if observed_total is not None and total != observed_total:
        raise AutoresearchError("tool_calls_by_name must sum to tool_call_count")


def _validate_run_record(
    record: dict[str, Any],
    config: AutoresearchConfig,
    expected_partition: str,
    *,
    scored: bool,
    public_questions: Mapping[str, str],
) -> tuple[str, str | None, float, float | None, str | None]:
    forbidden = _find_forbidden(record, config.forbidden_fields)
    if forbidden is not None:
        raise AutoresearchError("run artifact contains a forbidden field")
    required_fields = REQUIRED_RUN_FIELDS if scored else BASELINE_REQUIRED_FIELDS
    missing = required_fields - record.keys()
    if missing:
        raise AutoresearchError("run artifact record is missing required fields")
    if record.keys() - ALLOWED_RUN_FIELDS:
        raise AutoresearchError("run artifact record contains an unsupported field")
    instance_id = record["instance_id"]
    if not isinstance(instance_id, str) or not instance_id:
        raise AutoresearchError("instance_id must be a non-empty string")
    if record["partition"] != expected_partition:
        raise AutoresearchError(f"partition must be {expected_partition}")
    question = record.get("question")
    if question is not None and question != public_questions.get(instance_id):
        raise AutoresearchError(
            "run question must exactly match the committed public question"
        )
    if not scored and "outcome" in record:
        raise AutoresearchError(
            "public-only baseline outputs must not contain outcomes"
        )
    outcome = record.get("outcome")
    if scored and outcome not in OUTCOMES:
        raise AutoresearchError(
            "outcome must be correct, wrong_answer, or refused_or_error"
        )
    queries = [record.get("generated_query"), record.get("generated_sql")]
    if any(
        query is not None and (not isinstance(query, str) or not query)
        for query in queries
    ):
        raise AutoresearchError(
            "generated_query and generated_sql must be non-empty strings or null"
        )
    content_policy = ContentPolicy.from_environment(os.environ)
    if any(
        query is not None and not content_policy.query_is_safe(query)
        for query in queries
    ):
        raise AutoresearchError("generated query contains an exact live credential")
    if record["generation_outcome"] == "answered" and not any(queries):
        if not _has_opaque_result_binding(record):
            raise AutoresearchError(
                "answered attempts require a query, SQL, or bound opaque result"
            )
    latency_ms = _number(record["latency_ms"], "latency_ms")
    cost_usd = _number(record["cost_usd"], "cost_usd", nullable=True)
    _validate_telemetry(record)
    harness_failure = record["harness_failure"]
    if harness_failure is not None and not isinstance(harness_failure, str):
        raise AutoresearchError("harness_failure must be a string or null")
    semantic_objects = record["semantic_objects"]
    if not isinstance(semantic_objects, list) or any(
        not isinstance(value, str) or not value for value in semantic_objects
    ):
        raise AutoresearchError(
            "semantic_objects must be an array of non-empty strings"
        )
    category = record.get("failure_category")
    if category is not None and (not isinstance(category, str) or not category):
        raise AutoresearchError("failure_category must be a non-empty string or null")
    _validate_diagnostic_trace(record)
    _validate_safe_record_content(record, content_policy)
    _verify_result_artifact(config, record, content_policy)
    _verify_trace_artifact(config, record, content_policy)
    return instance_id, outcome, float(latency_ms), cost_usd, category


def _public_question_texts(config: AutoresearchConfig) -> dict[str, str]:
    return {
        instance_id: record["query"]
        for instance_id, record in _public_records_by_id(config).items()
    }


def _scope_definition(
    config: AutoresearchConfig, scope: str
) -> tuple[str, int, frozenset[str]]:
    definitions = {
        "train": ("train", config.expected_train_count, config.train_id_set),
        "dev-a": ("dev-a", config.expected_dev_a_count, config.dev_a_id_set),
        "dev-b": ("dev-b", config.expected_dev_b_count, config.dev_b_id_set),
    }
    try:
        return definitions[scope]
    except KeyError as error:
        raise AutoresearchError("run scope must be train, dev-a, or dev-b") from error


def _validate_run_identity(
    records: list[dict[str, Any]], description: str
) -> tuple[str, str, int]:
    attempt_ids = [record["attempt_id"] for record in records]
    if len(set(attempt_ids)) != len(attempt_ids):
        raise AutoresearchError(f"{description} contains a duplicate attempt_id")
    conditions = {record["condition"] for record in records}
    run_ids = {record["run_id"] for record in records}
    repetitions = {record["repetition"] for record in records}
    if len(conditions) != 1 or len(run_ids) != 1 or len(repetitions) != 1:
        raise AutoresearchError(
            f"{description} must have one condition, run_id, and repetition"
        )
    return next(iter(conditions)), next(iter(run_ids)), next(iter(repetitions))


def _validate_run_for_scope(
    config: AutoresearchConfig,
    path: Path,
    *,
    scope: str = "dev-a",
    manifest_path: Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> ValidatedRun:
    """Validate an exact, once-each run for the explicitly selected partition."""
    run_path = _resolve_raw_run_path(config, Path(path), "run artifact")
    records, sha256 = _read_confined_private_jsonl(
        config.workspace,
        run_path,
        "run artifact",
        maximum_bytes=MAX_RUN_ARTIFACT_BYTES,
    )
    return _summarize_run_records(
        config,
        run_path=run_path,
        generation_sha256=sha256,
        records=records,
        scope=scope,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def _summarize_run_records(
    config: AutoresearchConfig,
    *,
    run_path: Path,
    generation_sha256: str,
    records: list[dict[str, Any]],
    scope: str,
    scores_by_attempt: Mapping[str, AttemptScore] | None = None,
    score_path: Path | None = None,
    score_sha256: str | None = None,
    manifest_path: Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> ValidatedRun:
    """Join validated generation telemetry with optional immutable score labels."""
    expected_partition, expected_count, permitted_ids = _scope_definition(config, scope)
    if len(records) != expected_count:
        raise AutoresearchError(
            f"run artifact must contain exactly {expected_count} records"
        )
    seen: set[str] = set()
    correct_ids: set[str] = set()
    wrong_ids: set[str] = set()
    refusal_ids: set[str] = set()
    latencies: list[float] = []
    costs: list[float | None] = []
    total_tokens: list[int | None] = []
    tool_calls: list[int | None] = []
    database_queries: list[int | None] = []
    category_counts: dict[str, int] = {}
    terminal_failure_counts: dict[str, int] = {}
    public_questions = _public_question_texts(config)
    for record in records:
        instance_id, outcome, latency, cost, category = _validate_run_record(
            record,
            config,
            expected_partition,
            scored=scores_by_attempt is None,
            public_questions=public_questions,
        )
        if scores_by_attempt is not None:
            attempt_id = record["attempt_id"]
            try:
                score = scores_by_attempt[attempt_id]
            except KeyError as error:
                raise AutoresearchError(
                    "score artifact is missing a generation attempt"
                ) from error
            outcome = score.outcome
            category = score.failure_category
            _validate_capture_telemetry({**record, "outcome": outcome})
        if instance_id in seen:
            raise AutoresearchError("run artifact contains a duplicate instance_id")
        if instance_id not in permitted_ids:
            raise AutoresearchError(
                f"run artifact contains an ID outside the {scope} partition"
            )
        seen.add(instance_id)
        if outcome == "correct":
            correct_ids.add(instance_id)
        elif outcome == "wrong_answer":
            wrong_ids.add(instance_id)
        else:
            refusal_ids.add(instance_id)
        latencies.append(latency)
        costs.append(cost)
        usage = record["token_usage"]
        total_tokens.append(None if usage is None else usage["total_tokens"])
        tool_calls.append(record["tool_call_count"])
        database_queries.append(record["database_query_count"])
        if category is not None:
            category_counts[category] = category_counts.get(category, 0) + 1
        terminal_failure = record["terminal_failure_class"]
        if terminal_failure is not None:
            terminal_failure_counts[terminal_failure] = (
                terminal_failure_counts.get(terminal_failure, 0) + 1
            )
    if seen != permitted_ids:
        raise AutoresearchError(
            f"run artifact does not exactly match the {scope} partition"
        )
    condition, run_id, repetition = _validate_run_identity(records, "run artifact")
    manifest = validate_manifest_binding(
        workspace=config.workspace,
        records=records,
        generation_sha256=generation_sha256,
        condition=condition,
        scope=scope,
        repetition=repetition,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        required=config.run_manifest_required,
    )
    total_cost = None if any(cost is None for cost in costs) else sum(costs)  # type: ignore[arg-type]
    aggregate_tokens = (
        None if any(value is None for value in total_tokens) else sum(total_tokens)  # type: ignore[arg-type]
    )
    median_tokens: float | None = None
    iqr_tokens: float | None = None
    if aggregate_tokens is not None:
        median_tokens, iqr_tokens = median_iqr(total_tokens)  # type: ignore[arg-type]
    aggregate_tool_calls = (
        None if any(value is None for value in tool_calls) else sum(tool_calls)  # type: ignore[arg-type]
    )
    aggregate_database_queries = (
        None
        if any(value is None for value in database_queries)
        else sum(database_queries)  # type: ignore[arg-type]
    )
    median_latency, iqr_latency = median_iqr(latencies)
    combined_sha256 = generation_sha256
    if score_sha256 is not None:
        combined_sha256 = _sha256_bytes(f"{generation_sha256}:{score_sha256}".encode())
    if manifest is not None:
        combined_sha256 = _sha256_bytes(f"{combined_sha256}:{manifest.sha256}".encode())
    return ValidatedRun(
        path=run_path,
        sha256=combined_sha256,
        generation_sha256=generation_sha256,
        score_path=score_path,
        score_sha256=score_sha256,
        question_count=len(records),
        scope=scope,
        condition=condition,
        run_id=run_id,
        repetition=repetition,
        correct_ids=frozenset(correct_ids),
        wrong_answer_ids=frozenset(wrong_ids),
        refused_or_error_ids=frozenset(refusal_ids),
        mean_latency_ms=sum(latencies) / len(latencies),
        median_latency_ms=median_latency,
        iqr_latency_ms=iqr_latency,
        total_cost_usd=total_cost,
        total_tokens=aggregate_tokens,
        median_tokens=median_tokens,
        iqr_tokens=iqr_tokens,
        total_tool_calls=aggregate_tool_calls,
        total_database_queries=aggregate_database_queries,
        failure_categories=tuple(sorted(category_counts.items())),
        terminal_failure_classes=tuple(sorted(terminal_failure_counts.items())),
        run_manifest_path=None if manifest is None else manifest.path,
        run_manifest_sha256=None if manifest is None else manifest.sha256,
    )


def validate_run(
    config: AutoresearchConfig,
    path: Path,
    *,
    scope: str = "dev-a",
    score_path: Path | None = None,
    expected_score_sha256: str | None = None,
    manifest_path: Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> ValidatedRun:
    """Validate scored dev-A output; dev-B is available only via checkpoints."""
    if scope == "dev-b":
        raise AutoresearchError("dev-B runs require checkpoint evaluation")
    if score_path is not None or expected_score_sha256 is not None:
        if score_path is None or expected_score_sha256 is None:
            raise AutoresearchError(
                "score artifact path and hash must be supplied together"
            )
        return validate_scored_generation(
            config,
            path,
            score_path=score_path,
            expected_score_sha256=expected_score_sha256,
            scope=scope,
            manifest_path=manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    if config.score_artifact_required:
        raise AutoresearchError(
            "immutable score artifact path and hash are required by the protocol"
        )
    return _validate_run_for_scope(
        config,
        path,
        scope=scope,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def validate_scored_generation(
    config: AutoresearchConfig,
    generation_path: Path,
    *,
    score_path: Path,
    expected_score_sha256: str,
    scope: str = "dev-a",
    manifest_path: Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> ValidatedRun:
    """Join immutable labels to an unmodified dev-A generation artifact in memory."""
    generation = validate_generation_outputs(
        config,
        generation_path,
        scope=scope,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    try:
        scores = validate_score_artifact(
            config.workspace,
            generation=generation,
            score_path=score_path,
            expected_score_sha256=expected_score_sha256,
        )
    except ScoreArtifactError as error:
        raise AutoresearchError(str(error)) from error
    records, generation_sha256 = _read_confined_private_jsonl(
        config.workspace,
        generation.path,
        "generation artifact",
        maximum_bytes=MAX_RUN_ARTIFACT_BYTES,
    )
    if (
        generation_sha256
        not in {
            generation.sha256,
            scores.generation_sha256,
        }
        or generation.sha256 != scores.generation_sha256
    ):
        raise AutoresearchError(
            "generation artifact changed after score binding validation"
        )
    return _summarize_run_records(
        config,
        run_path=generation.path,
        generation_sha256=generation_sha256,
        records=records,
        scope=scope,
        scores_by_attempt={score.attempt_id: score for score in scores.attempts},
        score_path=scores.path,
        score_sha256=scores.sha256,
        manifest_path=generation.run_manifest_path,
        expected_manifest_sha256=generation.run_manifest_sha256,
    )


def validate_baseline_outputs(
    config: AutoresearchConfig,
    path: Path,
    *,
    manifest_path: Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> ValidatedBaselineOutputs:
    """Validate exact unscored 231-question outputs before label release."""
    generation = _validate_generation_for_scope(
        config,
        path,
        scope="train",
        description="baseline output artifact",
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    return ValidatedBaselineOutputs(
        path=generation.path,
        sha256=generation.sha256,
        question_count=generation.question_count,
        run_manifest_path=generation.run_manifest_path,
        run_manifest_sha256=generation.run_manifest_sha256,
    )


def validate_generation_outputs(
    config: AutoresearchConfig,
    path: Path,
    *,
    scope: str,
    manifest_path: Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> ValidatedGenerationOutputs:
    """Validate immutable unscored generation for train or routine dev-A."""
    if scope == "dev-b":
        raise AutoresearchError("dev-B generation requires the checkpoint guardian")
    if scope not in {"train", "dev-a"}:
        raise AutoresearchError("generation scope must be train or dev-a")
    return _validate_generation_for_scope(
        config,
        path,
        scope=scope,
        description="generation artifact",
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def _validate_generation_for_scope(
    config: AutoresearchConfig,
    path: Path,
    *,
    scope: str,
    description: str,
    manifest_path: Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> ValidatedGenerationOutputs:
    run_path = _resolve_raw_run_path(config, Path(path), description)
    records, sha256 = _read_confined_private_jsonl(
        config.workspace,
        run_path,
        description,
        maximum_bytes=MAX_RUN_ARTIFACT_BYTES,
    )
    expected_partition, expected_count, permitted_ids = _scope_definition(config, scope)
    if len(records) != expected_count:
        raise AutoresearchError(
            f"generation artifact must contain exactly {expected_count} records"
        )
    seen: set[str] = set()
    public_questions = _public_question_texts(config)
    for record in records:
        instance_id, _, _, _, _ = _validate_run_record(
            record,
            config,
            expected_partition,
            scored=False,
            public_questions=public_questions,
        )
        if instance_id in seen:
            raise AutoresearchError(
                "baseline output artifact contains a duplicate instance_id"
            )
        if instance_id not in permitted_ids:
            raise AutoresearchError(
                f"generation artifact contains an ID outside the {scope} partition"
            )
        seen.add(instance_id)
    if seen != permitted_ids:
        raise AutoresearchError(
            f"generation artifact does not exactly match the {scope} partition"
        )
    condition, run_id, repetition = _validate_run_identity(records, description)
    manifest = validate_manifest_binding(
        workspace=config.workspace,
        records=records,
        generation_sha256=sha256,
        condition=condition,
        scope=scope,
        repetition=repetition,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected_manifest_sha256,
        required=config.run_manifest_required,
    )
    return ValidatedGenerationOutputs(
        path=run_path,
        sha256=sha256,
        question_count=len(records),
        scope=scope,
        condition=condition,
        run_id=run_id,
        repetition=repetition,
        run_manifest_path=None if manifest is None else manifest.path,
        run_manifest_sha256=None if manifest is None else manifest.sha256,
    )

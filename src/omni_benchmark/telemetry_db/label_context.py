"""Public dev-A evidence packaged for a model-driven failure-labeling pass.

The labeler judges *why* an attempt failed. That judgment is semantic, so it is
delegated to a model; this module only assembles the evidence and enforces the
custody boundary around it. Every column below is public benchmark telemetry or
system output. Hidden annotations, sealed splits, and reference answers never
enter this path.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .custody import SplitIds, assert_dev_a_instance, reject_forbidden_fields
from .taxonomy import TAXONOMY_VERSION, taxonomy_for


class LabelContextError(ValueError):
    """Raised when a cohort selects nothing it could label."""


DEFAULT_SCORER = "official_soft_ex"

#: Attempt columns a labeler may see. Explicit rather than ``SELECT *`` so a new
#: column cannot silently widen what leaves the database.
ATTEMPT_COLUMNS: tuple[str, ...] = (
    "attempt_id",
    "generation_record_sha256",
    "instance_id",
    "database",
    "condition",
    "arm",
    "repetition",
    "generation_outcome",
    "execution_status",
    "failure_origin",
    "terminal_failure_class",
    "harness_failure",
    "generated_sql",
    "generated_query",
    "query_unavailable_reason",
    "tool_call_count",
    "tool_calls_by_name",
    "database_query_count",
    "retry_count",
    "validation_attempt_count",
    "actual_result_status",
    "latency_ms",
)


@dataclass(frozen=True)
class Cohort:
    """Which dev-A attempts a labeling pass covers."""

    arms: tuple[str, ...]
    outcomes: tuple[str, ...]
    terminal_failure_classes: tuple[str, ...] = ()
    scorer: str = DEFAULT_SCORER
    limit: int | None = None

    def __post_init__(self) -> None:
        if not self.arms:
            raise LabelContextError("a cohort must name at least one arm")
        if not self.outcomes:
            raise LabelContextError("a cohort must name at least one outcome")
        if self.limit is not None and self.limit < 1:
            raise LabelContextError(f"limit must be positive, got {self.limit}")


_SELECT = """
SELECT {columns},
       question.question AS question,
       question.category AS question_category,
       question.high_level AS question_high_level,
       score.outcome AS official_outcome,
       score.status AS score_status,
       score.failure_category AS score_failure_category
FROM telemetry.attempt AS attempt
JOIN telemetry.score AS score
    ON score.attempt_id = attempt.attempt_id
    AND score.generation_record_sha256 = attempt.generation_record_sha256
    AND score.scorer = %(scorer)s
LEFT JOIN telemetry.question AS question
    ON question.instance_id = attempt.instance_id
WHERE attempt.partition = 'dev-a'
    AND attempt.arm = ANY(%(arms)s)
    AND score.outcome = ANY(%(outcomes)s)
    AND (%(classes)s::text[] IS NULL
        OR attempt.terminal_failure_class = ANY(%(classes)s::text[]))
ORDER BY attempt.attempt_id, attempt.generation_record_sha256
"""

_TRACE_SQL = """
SELECT seq, tool_name, status, failure_class
FROM telemetry.trace_event
WHERE attempt_id = %(attempt_id)s
    AND generation_record_sha256 = %(sha)s
    AND (status = 'error' OR failure_class IS NOT NULL)
ORDER BY seq
"""

_EVIDENCE_SQL = """
SELECT trace_seq, tool_name, retrieval_query, retrieved_public_ids, exploratory_sql
FROM telemetry.action_evidence
WHERE attempt_id = %(attempt_id)s AND generation_record_sha256 = %(sha)s
ORDER BY trace_seq
"""


#: How many distinct values of a repeated evidence field reach a prompt. A large
#: retrieval trace is summarised rather than pasted; the paired ``*_count`` key
#: keeps the truncation visible to the labeler instead of silent.
SAMPLE_LIMIT = 40


def _add_bounded(row: dict[str, Any], name: str, values: Iterable[Any]) -> None:
    """Attach a de-duplicated, bounded sample of ``values`` and its full count."""
    distinct: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            distinct.append(value)
    row[f"{name}_count"] = len(distinct)
    row[f"{name}_sample"] = distinct[:SAMPLE_LIMIT]


def context_rows(
    conn: psycopg.Connection[Any], cohort: Cohort, split: SplitIds
) -> list[dict[str, Any]]:
    """Return one public-evidence row per attempt in the cohort."""
    columns = ", ".join(f"attempt.{name} AS {name}" for name in ATTEMPT_COLUMNS)
    sql = _SELECT.format(columns=columns)
    if cohort.limit is not None:
        sql += f"\nLIMIT {int(cohort.limit)}"
    parameters = {
        "scorer": cohort.scorer,
        "arms": list(cohort.arms),
        "outcomes": list(cohort.outcomes),
        "classes": list(cohort.terminal_failure_classes) or None,
    }
    with conn.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(sql, parameters).fetchall()
        for row in rows:
            context = f"label context for attempt {row['attempt_id']}"
            assert_dev_a_instance(row["instance_id"], split, context)
            keys = {
                "attempt_id": row["attempt_id"],
                "sha": row["generation_record_sha256"],
            }
            with conn.cursor(row_factory=dict_row) as inner:
                row["failing_trace_events"] = inner.execute(_TRACE_SQL, keys).fetchall()
                evidence = inner.execute(_EVIDENCE_SQL, keys).fetchall()
            _add_bounded(
                row,
                "retrieval_query",
                (
                    item["retrieval_query"]
                    for item in evidence
                    if item["retrieval_query"] is not None
                ),
            )
            _add_bounded(
                row,
                "retrieved_public_id",
                (
                    identifier
                    for item in evidence
                    for identifier in (item["retrieved_public_ids"] or [])
                ),
            )
            _add_bounded(
                row,
                "exploratory_sql",
                (
                    item["exploratory_sql"]
                    for item in evidence
                    if item["exploratory_sql"] is not None
                ),
            )
            reject_forbidden_fields(row, context)
    return rows


_PROMPT_HEADER = f"""\
Assign exactly one {TAXONOMY_VERSION} category to each benchmark attempt below, \
and explain each choice from that attempt's evidence. Every attempt shown failed \
to produce the expected answer; your job is to say why, at the level of the \
system's own behaviour. Judge only from what is shown, attempt by attempt: two \
attempts in one batch may fail for different reasons. Where the evidence does not \
distinguish between categories, choose the one the evidence best supports and say \
in the rationale what would have settled it.

Categories:
"""


def _taxonomy_block() -> str:
    codes = taxonomy_for(TAXONOMY_VERSION)
    return "\n".join(f"- {code}: {title}" for code, title in codes.items())


_EVIDENCE_KEYS: tuple[str, ...] = ATTEMPT_COLUMNS + (
    "question",
    "question_category",
    "question_high_level",
    "official_outcome",
    "score_status",
    "score_failure_category",
    "failing_trace_events",
    "retrieval_query_count",
    "retrieval_query_sample",
    "retrieved_public_id_count",
    "retrieved_public_id_sample",
    "exploratory_sql_count",
    "exploratory_sql_sample",
)


def _evidence_of(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key] for key in _EVIDENCE_KEYS if row.get(key) not in (None, [], {})
    }


def render_batch_prompt(rows: Sequence[dict[str, Any]]) -> str:
    """Render one labeling prompt covering a batch of context rows."""
    if not rows:
        raise LabelContextError("cannot render a prompt for an empty batch")
    evidence = [_evidence_of(row) for row in rows]
    return (
        _PROMPT_HEADER
        + _taxonomy_block()
        + f"\n\nAttempt evidence ({len(rows)} attempts):\n"
        + json.dumps(evidence, indent=2, default=str, sort_keys=True)
    )


def render_prompt(row: dict[str, Any]) -> str:
    """Render one labeling prompt from a single context row."""
    return render_batch_prompt([row])


def cohort_summary(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Count the cohort by arm, for a log line before a labeling fan-out."""
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["arm"]] = counts.get(row["arm"], 0) + 1
    return counts


__all__ = [
    "ATTEMPT_COLUMNS",
    "SAMPLE_LIMIT",
    "Cohort",
    "LabelContextError",
    "cohort_summary",
    "context_rows",
    "render_batch_prompt",
    "render_prompt",
]

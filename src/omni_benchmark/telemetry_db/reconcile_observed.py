"""Observed aggregates queried from the telemetry database.

Each public function returns a tree shaped like the frozen artifact it is
reconciled against, so ``reconcile.py`` can flatten both sides and compare
path by path. Every query reads public telemetry columns only: arm, outcome,
resource counters, query-shape flags, and the correctness verdicts already
published in ``telemetry.score`` and ``telemetry.sealed_aggregate``. No hidden
field is selected.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from psycopg.rows import dict_row

from omni_benchmark.telemetry_db.reconcile_stats import (
    as_number,
    cost_summary,
    median,
    median_coverage,
    percent,
    rounded,
    tukey_distribution,
)

#: Frozen-artifact scorer label -> ``telemetry.score.scorer`` value.
SCORERS: Mapping[str, str] = {
    "official": "official_soft_ex",
    "sensitivity": "sensitivity",
}
FRAME_ARMS: tuple[str, ...] = ("C1", "C2", "C3", "C4", "C5")
SEALED_CONDITIONS: tuple[str, ...] = ("C1", "C2", "C3", "C4")
GENERATION_OUTCOMES: tuple[str, ...] = ("answered", "errored", "refused")
SCORE_OUTCOMES: tuple[str, ...] = ("correct", "wrong_answer", "refused_or_error")
TOKEN_FIELDS: tuple[str, ...] = ("input_tokens", "output_tokens", "total_tokens")
ROLLUP_FIELDS: tuple[str, ...] = ("latency_ms", *TOKEN_FIELDS, "cost_usd")
COMPARISON_FIELDS: tuple[str, ...] = (
    "latency_ms",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "tool_call_count",
    "database_query_count",
)
QUERY_PATH_SHAPES: tuple[str, ...] = (
    "user_edited_sql",
    "topic_scoped",
    "user_edited_sql_and_topic_scoped",
    "semantic_token_present",
    "qualified_token_present",
    "inline_aggregate_over_token",
    "bare_table_from",
)
SEALED_AGGREGATE_FIELDS: tuple[str, ...] = (
    "correct",
    "wrong_answer",
    "refused_or_error",
    "mean_accuracy",
    "pass_3_rate",
    "wrong_rate",
    "refused_or_error_rate",
    "error_rate",
    "correctness_flip_rate",
    "scoreable_attempts",
)


class ObservedError(ValueError):
    """Raised when database rows cannot form the aggregate being reconciled."""


FRAME_ROWS_SQL = """
WITH scored AS (
    SELECT a.arm, a.instance_id, s.outcome, a.latency_ms, a.input_tokens,
           a.output_tokens, a.total_tokens, a.cost_usd
    FROM telemetry.attempt AS a
    JOIN telemetry.score AS s
      ON s.attempt_id = a.attempt_id
     AND s.generation_record_sha256 = a.generation_record_sha256
    WHERE a.partition = 'dev-a'
      AND a.arm = ANY(%(arms)s)
      AND s.scorer = %(scorer)s
), frame AS (
    SELECT instance_id
    FROM scored
    WHERE outcome IS NOT NULL
    GROUP BY instance_id
    HAVING count(DISTINCT arm) = %(arm_count)s
)
SELECT scored.*
FROM scored
JOIN frame USING (instance_id)
ORDER BY arm, instance_id
"""

SEALED_ROWS_SQL = """
SELECT condition, repetition, generation_outcome, model_name, model_provider,
       generation_record -> 'model' ->> 'version' AS model_version,
       failure_origin, terminal_failure_class, token_source, cost_source,
       telemetry_unavailable, latency_ms, input_tokens, output_tokens,
       total_tokens, tool_call_count, database_query_count, cost_usd
FROM telemetry.attempt
WHERE partition = 'test'
ORDER BY condition, attempt_id
"""

SEALED_AGGREGATE_SQL = """
SELECT scorer, condition, correct, wrong_answer, refused_or_error,
       mean_accuracy, pass_3_rate, wrong_rate, refused_or_error_rate, error_rate,
       correctness_flip_rate, scoreable_attempts
FROM telemetry.sealed_aggregate
WHERE run_id = %(run_id)s
ORDER BY scorer, condition
"""

RUN_ROWS_SQL = """
SELECT run_id, instance_id, repetition, generation_outcome, model_name,
       model_provider, token_source, cost_source, cost_unavailable_reason,
       cost_usd, latency_ms, input_tokens, output_tokens, total_tokens,
       tool_call_count, database_query_count
FROM telemetry.attempt
WHERE run_id = ANY(%(run_ids)s)
ORDER BY run_id, instance_id, repetition
"""

# Mirrors experiments/analysis/governed_query_path_tally.py: ``\m`` is the
# Postgres ARE spelling of Python's ``\b`` before a word character, and
# ``pg_input_is_valid`` leaves a '{'-prefixed but malformed value unparsed so it
# counts as no_semantic_query, the way the tally's JSONDecodeError branch does.
QUERY_PATH_SQL = r"""
WITH parsed AS (
    SELECT attempt_id,
           CASE WHEN generated_query ~ '^\s*\{'
                 AND pg_input_is_valid(generated_query, 'jsonb')
                THEN generated_query::jsonb END AS query
    FROM telemetry.attempt
    WHERE run_id = %(run_id)s
), shaped AS (
    SELECT attempt_id, query IS NOT NULL AS parseable,
           CASE WHEN jsonb_typeof(query -> 'userEditedSQL') = 'string'
                THEN query ->> 'userEditedSQL' ELSE '' END AS sql,
           CASE jsonb_typeof(query -> 'join_paths_from_topic_name')
                WHEN 'string'
                    THEN btrim(query ->> 'join_paths_from_topic_name') <> ''
                WHEN 'boolean'
                    THEN (query ->> 'join_paths_from_topic_name')::boolean
                WHEN 'number'
                    THEN (query ->> 'join_paths_from_topic_name')::numeric <> 0
                WHEN 'array'
                    THEN jsonb_array_length(query -> 'join_paths_from_topic_name') > 0
                WHEN 'object'
                    THEN query -> 'join_paths_from_topic_name' <> '{}'::jsonb
                ELSE false END AS topic_scoped
    FROM parsed
), measured AS (
    SELECT parseable, topic_scoped, btrim(sql) <> '' AS has_sql,
           (SELECT count(*) FROM regexp_matches(
                sql, '\$\{[A-Za-z_][A-Za-z0-9_.]*\}', 'g')) AS token_count,
           (SELECT count(*) FROM regexp_matches(
                sql, '\$\{[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_.]*\}', 'g'))
               AS qualified_count,
           sql ~* '\m(SUM|COUNT|AVG|MIN|MAX|MEDIAN|STDDEV|VARIANCE)\s*\(\s*(DISTINCT\s+)?\$\{'
               AS inline_aggregate,
           sql ~* '\mFROM\s+(?!\$\{)["`\[A-Za-z_]' AS bare_table_from
    FROM shaped
)
SELECT count(*) AS attempts,
       count(*) FILTER (WHERE NOT parseable) AS no_semantic_query,
       count(*) FILTER (WHERE parseable AND has_sql) AS user_edited_sql,
       count(*) FILTER (WHERE parseable AND topic_scoped) AS topic_scoped,
       count(*) FILTER (WHERE parseable AND has_sql AND topic_scoped)
           AS user_edited_sql_and_topic_scoped,
       count(*) FILTER (WHERE parseable AND token_count > 0)
           AS semantic_token_present,
       count(*) FILTER (WHERE parseable AND qualified_count > 0)
           AS qualified_token_present,
       count(*) FILTER (WHERE parseable AND has_sql AND inline_aggregate)
           AS inline_aggregate_over_token,
       count(*) FILTER (WHERE parseable AND has_sql AND bare_table_from)
           AS bare_table_from,
       coalesce(sum(token_count) FILTER (WHERE parseable), 0)
           AS semantic_token_total
FROM measured
"""

LOAD_RUNS_SQL = """
SELECT load_id, started_at, finished_at, loader_version, system_commit, row_counts
FROM telemetry.load_run
ORDER BY finished_at, load_id
"""


def fetch(conn: Any, query: str, params: Mapping[str, Any] | None = None) -> list[dict]:
    """Run one query and return every row as a dict."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def _column(rows: Iterable[Mapping[str, Any]], field: str) -> list[int | float]:
    return [as_number(row[field]) for row in rows if row[field] is not None]


def _counts(values: Iterable[object]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _group(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(dict(row))
    return grouped


# --- matched dev-A frame -----------------------------------------------------


def frame_rows(conn: Any, scorer: str, arms: Sequence[str] = FRAME_ARMS) -> list[dict]:
    """Scored dev-A attempts on the frame of questions scoreable in every arm."""
    if scorer not in SCORERS:
        raise ObservedError(f"unknown scorer label {scorer!r}")
    params = {"arms": list(arms), "scorer": SCORERS[scorer], "arm_count": len(arms)}
    return fetch(conn, FRAME_ROWS_SQL, params)


def dev_a_frame_counts(
    conn: Any, arms: Sequence[str] = FRAME_ARMS
) -> dict[str, dict[str, dict[str, object]]]:
    """Per-scorer, per-arm verdict counts on the matched frame."""
    result: dict[str, dict[str, dict[str, object]]] = {}
    for scorer in SCORERS:
        grouped = _group(frame_rows(conn, scorer, arms), "arm")
        result[scorer] = {}
        for arm in arms:
            outcomes = Counter(row["outcome"] for row in grouped.get(arm, []))
            scoreable = sum(outcomes.values())
            result[scorer][arm] = {
                **{outcome: outcomes[outcome] for outcome in SCORE_OUTCOMES},
                "scoreable_attempts": scoreable,
                "accuracy_percent": percent(outcomes["correct"], scoreable),
            }
    return result


def _arm_rollup(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    attempts = len(rows)
    cost = _column(rows, "cost_usd")
    latency = _column(rows, "latency_ms")
    correct = sum(1 for row in rows if row["outcome"] == "correct")
    spend: dict[str, object] = {"coverage": len(cost)}
    if cost:
        spend["total_usd"] = rounded(sum(cost))
        spend["median_usd"] = median(cost)
    summary: dict[str, object] = {
        "attempts": attempts,
        "official_correct": correct,
        "spend": spend,
        "wall_time": {
            "coverage": len(latency),
            "total_hours": rounded(sum(latency) / 3_600_000),
            "median_ms": median(latency) if latency else None,
        },
        "distributions": {
            field: tukey_distribution(_column(rows, field), total=attempts)
            for field in ROLLUP_FIELDS
        },
    }
    if cost:
        summary["cost_per_correct_answer_usd"] = (
            rounded(spend["total_usd"] / correct) if correct else None
        )
    return summary


def matched_frame_rollup(
    conn: Any, arms: Sequence[str] = FRAME_ARMS
) -> dict[str, object]:
    """Cost, wall time, and resource distributions per arm on the official frame."""
    rows = frame_rows(conn, "official", arms)
    grouped = _group(rows, "arm")
    return {
        "question_count": len({row["instance_id"] for row in rows}),
        "arms": {arm: _arm_rollup(grouped.get(arm, [])) for arm in arms},
    }


# --- sealed test attempts ----------------------------------------------------


def _identity_counts(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, object]]:
    counts = Counter(
        (
            row["model_name"] or "unreported",
            row["model_provider"] or "unreported",
            row["model_version"] or "unreported",
        )
        for row in rows
    )
    return [
        {"name": name, "provider": provider, "version": version, "attempt_count": n}
        for (name, provider, version), n in sorted(counts.items())
    ]


def _outcome_medians(rows: Sequence[Mapping[str, Any]], outcome: str) -> dict:
    selected = [row for row in rows if row["generation_outcome"] == outcome]
    fields = (
        "latency_ms",
        "total_tokens",
        "tool_call_count",
        "database_query_count",
        "cost_usd",
    )
    medians: dict[str, object] = {"attempt_count": len(selected), "coverage": {}}
    for field in fields:
        observed = _column(selected, field)
        medians[field] = median(observed) if observed else None
        medians["coverage"][field] = {
            "observed": len(observed),
            "missing": len(selected) - len(observed),
        }
    return medians


def _declared_unavailable(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    items: list[str] = []
    for row in rows:
        declared = row["telemetry_unavailable"]
        if not isinstance(declared, list):
            raise ObservedError("sealed attempt telemetry_unavailable is not a list")
        items.extend(declared)
    return _counts(items)


def _sealed_telemetry(rows: Sequence[Mapping[str, Any]], total: int) -> dict:
    return {
        "latency_ms": tukey_distribution(_column(rows, "latency_ms"), total=total),
        "token_usage": {
            field: tukey_distribution(_column(rows, field), total=total)
            for field in TOKEN_FIELDS
        },
        "tool_call_count": median_coverage(
            _column(rows, "tool_call_count"), total=total
        ),
        "database_query_count": median_coverage(
            _column(rows, "database_query_count"), total=total
        ),
        "cost_usd": cost_summary(_column(rows, "cost_usd"), total=total),
    }


def _sealed_condition(rows: Sequence[Mapping[str, Any]], condition: str) -> dict:
    """Mirror ``sealed_telemetry_summary._condition_summary`` from rows.

    The frozen summary publishes C4 refusals as null because the governed
    path has no structured refusal state. A zero count reproduces that null;
    a non-zero count is reported so it surfaces as a mismatch.
    """
    total = len(rows)
    outcomes = Counter(row["generation_outcome"] for row in rows)
    refusal_unobservable = condition == "C4" and outcomes["refused"] == 0
    return {
        "attempt_count": total,
        "repetitions": _counts(str(row["repetition"]) for row in rows),
        "outcomes": {
            outcome: (
                None
                if refusal_unobservable and outcome == "refused"
                else outcomes[outcome]
            )
            for outcome in GENERATION_OUTCOMES
        },
        "refusal": {
            "status": "unavailable" if refusal_unobservable else "observed",
            "count": None if refusal_unobservable else outcomes["refused"],
        },
        "model_identities": _identity_counts(rows),
        "failure_origins": _counts(
            row["failure_origin"] for row in rows if row["failure_origin"] is not None
        ),
        "failure_classes": _counts(
            row["terminal_failure_class"]
            for row in rows
            if row["terminal_failure_class"] is not None
        ),
        "sources": {
            "token_source": _counts(row["token_source"] for row in rows),
            "cost_source": _counts(row["cost_source"] for row in rows),
        },
        "declared_unavailable": _declared_unavailable(rows),
        "telemetry": _sealed_telemetry(rows, total),
        "outcome_resource_medians": {
            outcome: _outcome_medians(rows, outcome)
            for outcome in ("answered", "errored")
        },
    }


def sealed_condition_summaries(
    conn: Any, conditions: Sequence[str] = SEALED_CONDITIONS
) -> dict[str, dict]:
    """Per-condition sealed telemetry rollups from test-partition attempts."""
    grouped = _group(fetch(conn, SEALED_ROWS_SQL), "condition")
    return {
        condition: _sealed_condition(grouped.get(condition, []), condition)
        for condition in conditions
    }


def sealed_outcome_tallies(
    conn: Any, conditions: Sequence[str] = SEALED_CONDITIONS
) -> dict[str, dict[str, dict[str, int]]]:
    """Generation outcomes and terminal failure classes per sealed condition.

    ``terminal_failure_classes`` omits attempts with no failure, as
    ``aggregate.json`` does; ``failure_classes_including_none`` counts them as
    ``"none"``, the convention the sealed correctness matrix publishes.
    """
    grouped = _group(fetch(conn, SEALED_ROWS_SQL), "condition")
    tallies: dict[str, dict[str, dict[str, int]]] = {}
    for condition in conditions:
        rows = grouped.get(condition, [])
        classes = [row["terminal_failure_class"] for row in rows]
        tallies[condition] = {
            "generation_outcomes": _counts(row["generation_outcome"] for row in rows),
            "terminal_failure_classes": _counts(c for c in classes if c is not None),
            "failure_classes_including_none": _counts(c or "none" for c in classes),
        }
    return tallies


def sealed_aggregates(
    conn: Any, run_id: str
) -> dict[str, dict[str, dict[str, object]]]:
    """Published sealed rates for one run, keyed by scorer then condition."""
    result: dict[str, dict[str, dict[str, object]]] = {}
    for row in fetch(conn, SEALED_AGGREGATE_SQL, {"run_id": run_id}):
        result.setdefault(row["scorer"], {})[row["condition"]] = {
            field: (None if row[field] is None else as_number(row[field]))
            for field in SEALED_AGGREGATE_FIELDS
        }
    return result


def pooled_matrix_summary(
    conn: Any, run_id: str
) -> dict[str, dict[str, dict[str, object]]]:
    """The correctness matrix's pooled per-arm summary, from sealed_aggregate."""
    summary: dict[str, dict[str, dict[str, object]]] = {}
    for scorer, conditions in sealed_aggregates(conn, run_id).items():
        summary[scorer] = {}
        for condition, fields in conditions.items():
            correct = int(fields["correct"])
            n = int(fields["scoreable_attempts"])
            summary[scorer][condition] = {
                "correct": correct,
                "n": n,
                "percent": percent(correct, n),
                "refused_or_error": int(fields["refused_or_error"]),
                "wrong_answer": int(fields["wrong_answer"]),
            }
    return summary


# --- dev-A run comparison ----------------------------------------------------


def _run_cost(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    observed = _column(rows, "cost_usd")
    sources = sorted({str(row["cost_source"]) for row in rows})
    reasons = sorted(
        {
            str(row["cost_unavailable_reason"])
            for row in rows
            if row["cost_unavailable_reason"] is not None
        }
    )
    if not observed:
        return {
            "status": "unavailable",
            "observed": 0,
            "missing": len(rows),
            "cost_source": sources,
            "unavailable_reason": reasons,
        }
    return {
        "status": "fully_observed" if len(observed) == len(rows) else "partial",
        "observed": len(observed),
        "missing": len(rows) - len(observed),
        "cost_source": sources,
        "total": rounded(sum(observed)),
        "mean": rounded(sum(observed) / len(observed)),
    }


def _run_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Mirror ``dev_a_telemetry_summary.summarize`` for one set of attempts."""
    if not rows:
        raise ObservedError("cannot summarize an empty arm")
    outcomes = Counter(row["generation_outcome"] for row in rows)
    unrecognized = len(rows) - sum(outcomes[o] for o in GENERATION_OUTCOMES)
    if unrecognized:
        raise ObservedError("arm contains an unsupported generation_outcome")
    models = Counter(
        (
            str(row["model_name"]),
            "unknown" if row["model_provider"] is None else str(row["model_provider"]),
        )
        for row in rows
    )
    answered = [row for row in rows if row["generation_outcome"] == "answered"]
    return {
        "attempt_count": len(rows),
        "outcomes": {outcome: outcomes[outcome] for outcome in GENERATION_OUTCOMES},
        "models": [
            {"name": name, "provider": provider, "attempt_count": count}
            for (name, provider), count in sorted(models.items())
        ],
        "token_source": sorted({str(row["token_source"]) for row in rows}),
        "cost": _run_cost(rows),
        "all_attempts": {
            field: tukey_distribution(_column(rows, field), total=len(rows))
            for field in COMPARISON_FIELDS
        },
        "answered_attempts": {
            field: tukey_distribution(_column(answered, field), total=len(answered))
            for field in COMPARISON_FIELDS
        },
    }


def _keyed_by_coordinate(rows: Iterable[Mapping[str, Any]]) -> dict[tuple, dict]:
    keyed: dict[tuple, dict] = {}
    for row in rows:
        coordinate = (row["instance_id"], row["repetition"])
        if coordinate in keyed:
            raise ObservedError(f"{row['run_id']}: duplicate coordinate {coordinate}")
        keyed[coordinate] = dict(row)
    return keyed


def run_comparison(conn: Any, runs: Mapping[str, str]) -> dict[str, object]:
    """Compare runs on their shared (instance, repetition) coordinates."""
    if len(runs) < 2:
        raise ObservedError("comparison needs at least two runs")
    grouped = _group(
        fetch(conn, RUN_ROWS_SQL, {"run_ids": list(runs.values())}), "run_id"
    )
    missing = [run_id for run_id in runs.values() if run_id not in grouped]
    if missing:
        raise ObservedError(f"no attempts loaded for runs {missing}")
    keyed = {
        label: _keyed_by_coordinate(grouped[run_id]) for label, run_id in runs.items()
    }
    shared = set.intersection(*(set(records) for records in keyed.values()))
    if not shared:
        raise ObservedError("runs share no attempt coordinate")
    order = sorted(shared)
    return {
        "matched_attempt_count": len(order),
        "runs": {
            label: {
                "attempt_count": len(records),
                "matched": _run_summary([records[c] for c in order]),
            }
            for label, records in keyed.items()
        },
    }


# --- governed query-path tally ------------------------------------------------


def query_path_tally(conn: Any, run_id: str) -> dict[str, object]:
    """Mirror ``governed_query_path_tally.summarize_arm`` for one run."""
    rows = fetch(conn, QUERY_PATH_SQL, {"run_id": run_id})
    counts = {key: int(value) for key, value in rows[0].items()}
    if counts["attempts"] == 0:
        raise ObservedError(f"no attempts loaded for run {run_id!r}")
    parseable = counts["attempts"] - counts["no_semantic_query"]
    return {
        **counts,
        "parseable_attempts": parseable,
        "shares_of_parseable_percent": {
            shape: percent(counts[shape], parseable) for shape in QUERY_PATH_SHAPES
        },
    }


# --- load provenance -------------------------------------------------------------


def load_runs(conn: Any) -> list[dict[str, object]]:
    """Every recorded load, oldest first, for the reconciliation report."""
    return [
        {
            "load_id": row["load_id"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "finished_at": (
                row["finished_at"].isoformat() if row["finished_at"] else None
            ),
            "loader_version": row["loader_version"],
            "system_commit": row["system_commit"],
            "row_counts": row["row_counts"],
        }
        for row in fetch(conn, LOAD_RUNS_SQL)
    ]

#!/usr/bin/env python3
"""Assemble the matched dev-A 122-question frame as one row per question.

Every condition was scored by a separate scorer run over its own freeze, so the
per-question picture only exists once the three score artifacts are joined back
onto the generation records that produced them. That join is what this module
does; nothing here recomputes an outcome.

Inputs are public: the dev-A question release, the frozen generation records,
and the committed score artifacts. No gold SQL, no test partition, no hidden
annotation is read.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "experiments/autoresearch/raw"
QUESTIONS = ROOT / "data/manifests/eligible_questions.jsonl"
CREDIT_BREAKDOWN = (
    ROOT / "experiments/analysis/omni-credit-spend-breakdown-2026-08.json"
)

# Each condition names the score artifact that released it and the run
# directories its generation records live under. C5 is the c5-dev-a-v4
# deployment, which the harness still labels condition C4 because the condition
# scaffold is unchanged; only the semantic model differs.
CONDITIONS = {
    "C1": ("public-direct-baseline-dev-a-scores-v1", "C1"),
    "C2": ("public-direct-baseline-dev-a-scores-v1", "C2"),
    "C3": ("public-direct-baseline-dev-a-scores-v1", "C3"),
    "C4": ("c4-matched-122-scores-v1", "C4"),
    "C5": ("c5-matched-122-scores-v1", "C4"),
}
GENERATION_RUNS = (
    "public-baseline-v1-direct-16db",
    "public-baseline-v1-direct-16db-continuation-1",
    "public-c4-baseline-v8",
    "c5-dev-a-v4",
)
SCORERS = ("official", "sensitivity")


def load_questions():
    out = {}
    with QUESTIONS.open(encoding="utf-8") as fh:
        for line in fh:
            q = json.loads(line)
            out[q["instance_id"]] = q
    return out


def index_generations():
    """Map generation sha256 to its record, over every frozen run directory.

    Scores carry the record hash rather than a path, and the same attempt id can
    appear in more than one run directory after a recovery pass, so the hash is
    the only key that identifies exactly the record that was scored.
    """
    by_sha = {}
    for run in GENERATION_RUNS:
        for path in (RAW / run).rglob("generation.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                record["_dir"] = str(path.parent.relative_to(ROOT))
                by_sha[_sha_of(path.parent)] = record
    return by_sha


def _sha_of(directory: Path) -> str:
    import hashlib

    return hashlib.sha256((directory / "generation.jsonl").read_bytes()).hexdigest()


def load_outcomes():
    """condition -> scorer -> instance_id -> {outcome, failure_category, sha}."""
    cache = {}
    outcomes = defaultdict(lambda: defaultdict(dict))
    for condition, (artifact, label) in CONDITIONS.items():
        for scorer in SCORERS:
            key = (artifact, scorer)
            if key not in cache:
                cache[key] = json.loads(
                    (RAW / artifact / f"{scorer}.score.json").read_text(
                        encoding="utf-8"
                    )
                )
            for attempt in cache[key]["attempts"]:
                _run, instance, cond, _rep = attempt["attempt_id"].split(":")
                if cond != label:
                    continue
                outcomes[condition][scorer][instance] = attempt
    return outcomes


def run_metadata(directory: str):
    path = ROOT / directory / "run.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def trace_steps(directory: str):
    """The ordered event list, which is the attempt's trajectory.

    The trace records what the attempt did, not what it said: model turns carry
    token counts and a metadata hash rather than prompt or completion text, so a
    step timeline is the finest-grained view of an attempt this repository holds.
    """
    path = ROOT / directory / "attempt.trace.jsonl"
    if not path.exists():
        return []
    steps = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        steps.append(
            {
                "seq": event.get("seq"),
                "event_type": event.get("event_type"),
                "tool_name": event.get("tool_name"),
                "status": event.get("status"),
                "failure_class": event.get("failure_class"),
                "duration_ms": event.get("duration_ms"),
                "elapsed_ms": event.get("elapsed_ms"),
                "input_tokens": event.get("input_tokens"),
                "output_tokens": event.get("output_tokens"),
            }
        )
    return sorted(steps, key=lambda s: s["seq"] if s["seq"] is not None else 0)


def trace_actions(directory: str, max_ids: int = 6):
    """What the direct arms actually asked for: retrieval queries and probe SQL.

    Only the direct conditions write this; a governed attempt hands the question
    to Omni and has no retrieval step of its own to record.
    """
    path = ROOT / directory / "attempt.action-evidence.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    actions = []
    for record in payload.get("records", []):
        retrieved = record.get("retrieved_public_ids") or []
        actions.append(
            {
                "trace_seq": record.get("trace_seq"),
                "tool_name": record.get("tool_name"),
                "retrieval_query": record.get("retrieval_query"),
                "exploratory_sql": record.get("exploratory_sql"),
                "retrieved": retrieved[:max_ids],
                "retrieved_count": len(retrieved),
            }
        )
    return actions


def result_preview(directory: str, max_rows: int = 8):
    path = ROOT / directory / "answer.result.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])

    def cell(value):
        if isinstance(value, dict):
            return str(value.get("value", ""))
        return "" if value is None else str(value)

    return {
        "columns": payload.get("columns", []),
        "rows": [[cell(v) for v in row] for row in rows[:max_rows]],
        "row_count": len(rows),
        "truncated": bool(payload.get("truncated")) or len(rows) > max_rows,
    }


def _query_text(record):
    """The artifact the condition actually submitted: SQL, or an Omni query."""
    if record.get("generated_sql"):
        return record["generated_sql"], "sql"
    raw = record.get("generated_query")
    if not raw:
        return None, None
    try:
        return json.dumps(json.loads(raw), indent=2, sort_keys=True), "omni_query"
    except (TypeError, ValueError):
        return str(raw), "omni_query"


def governed_cost_estimate():
    """The account-level credit figure that stands in for a per-attempt cost.

    `omni_credit_cost.capture_with_cost` brackets the credit counter around each
    governed attempt, but it postdates every run in this frame, so these attempts
    carry the job API's silence. The August credit total divided across the
    Omni-routed attempts recorded on disk is the only spend figure that covers
    them, and it is derived from a counter with no per-job attribution, so the
    page labels it as an estimate over the arm rather than a cost of a row.
    """
    if not CREDIT_BREAKDOWN.exists():
        return None
    breakdown = json.loads(CREDIT_BREAKDOWN.read_text(encoding="utf-8"))
    return {
        "per_attempt_usd": breakdown["proportional_estimate_usd_per_omni_attempt"],
        "upper_bound_usd": breakdown["upper_bound_usd_per_omni_attempt"],
        "credits_used_usd": breakdown["credits_used_usd"],
        "attempts": breakdown["omni_routed_attempts_recorded"],
        "period": breakdown["period"],
        "caveats": breakdown["caveats"],
        "source": str(CREDIT_BREAKDOWN.relative_to(ROOT)),
    }


def build():
    questions = load_questions()
    generations = index_generations()
    outcomes = load_outcomes()

    # The matched frame is the set of questions every condition scored.
    frame = set.intersection(*(set(outcomes[c]["official"]) for c in CONDITIONS))

    rows = []
    for instance in sorted(frame):
        question = questions.get(instance, {})
        arms = {}
        for condition in CONDITIONS:
            attempt = outcomes[condition]["official"][instance]
            record = generations.get(attempt["generation_sha256"])
            if record is None:
                raise SystemExit(
                    f"no generation record for {condition} {instance}; "
                    "the score artifact and the frozen runs disagree"
                )
            directory = record["_dir"]
            query, query_kind = _query_text(record)
            usage = record.get("token_usage") or {}
            model = record.get("model") or {}
            sensitivity = outcomes[condition]["sensitivity"].get(instance, {})
            arms[condition] = {
                "attempt_id": attempt["attempt_id"],
                "outcome": attempt["outcome"],
                "sensitivity_outcome": sensitivity.get("outcome"),
                "failure_category": attempt.get("failure_category"),
                "generation_outcome": record.get("generation_outcome"),
                "execution_status": record.get("execution_status"),
                "terminal_failure_class": record.get("terminal_failure_class"),
                "failure_origin": record.get("failure_origin"),
                "query": query,
                "query_kind": query_kind,
                "query_unavailable_reason": record.get("query_unavailable_reason"),
                "cost_usd": record.get("cost_usd"),
                "cost_source": record.get("cost_source"),
                "cost_unavailable_reason": record.get("cost_unavailable_reason"),
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "token_source": record.get("token_source"),
                "latency_ms": record.get("latency_ms"),
                "tool_calls": record.get("tool_calls_by_name") or [],
                "tool_call_count": record.get("tool_call_count"),
                "database_query_count": record.get("database_query_count"),
                "retry_count": record.get("retry_count"),
                "model": model.get("name") or run_metadata(directory).get("model"),
                "provider": model.get("provider"),
                "semantic_model": run_metadata(directory).get("semantic_model_ref"),
                "artifact_dir": directory,
                "steps": trace_steps(directory),
                "actions": trace_actions(directory),
                "result": result_preview(directory),
            }
        rows.append(
            {
                "instance_id": instance,
                "database": question.get("selected_database", ""),
                "question": question.get("query", ""),
                "normal_query": question.get("normal_query", ""),
                "category": question.get("category", ""),
                "high_level": question.get("high_level", ""),
                "conditions_spec": _spec(question.get("conditions")),
                "arms": arms,
                "pattern": classify(arms),
            }
        )
    return rows


def _spec(value):
    """The release stores answer conditions as a dict on some rows, a repr on others."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def classify(arms):
    """Name what makes a question worth opening.

    Correctness alone is a thin read on five arms, so the label distinguishes
    the contrasts that carry an argument: an arm that stands alone, an arm that
    recovers what a related arm lost, and the questions no arm reached.
    """
    correct = {c for c, a in arms.items() if a["outcome"] == "correct"}
    errored = {c for c, a in arms.items() if a["outcome"] == "refused_or_error"}
    if not correct:
        return "all_wrong" if not errored else "all_wrong_with_errors"
    if len(correct) == 5:
        return "all_correct"
    if correct == {"C2"}:
        return "only_C2"
    if correct == {"C5"}:
        return "only_C5"
    if len(correct) == 1:
        return f"only_{next(iter(correct))}"
    if "C5" in correct and "C4" not in correct:
        return "C5_recovers_C4"
    if "C4" in correct and "C5" not in correct:
        return "C5_loses_C4"
    return "split"


if __name__ == "__main__":
    data = build()
    print(json.dumps(data[:1], indent=1)[:2000])
    from collections import Counter

    print(len(data), Counter(r["pattern"] for r in data))

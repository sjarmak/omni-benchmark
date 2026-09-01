#!/usr/bin/env python3
"""Tally which query path every governed attempt actually took.

The governed conditions were adopted to test semantic composition. Schema 1 of
this analyzer answered that question with two fields that cannot answer it, and
its output was published; see the research log correction. ``rewriteSql`` is
Omni's documented default handling for any query carrying ``userEditedSQL``, so
it is true on every governed attempt we recorded and discriminates nothing.
``join_via_map`` is populated when a topic definition is *read back*, not when a
query is submitted, so it is empty on every governed attempt we recorded and its
count of zero measured the absence of a field this pathway never sets.

Schema 2 counts the shapes that actually vary:

* ``user_edited_sql`` - the attempt carried agent-authored SQL;
* ``topic_scoped`` - the attempt named a topic via ``join_paths_from_topic_name``,
  so the model supplied the join scope;
* ``semantic_tokens`` - ``${...}`` references in that SQL, and whether any is
  qualified (``${view.field}``). Qualified tokens resolve through the deployed
  model, so field-level definitions still apply to them;
* ``inline_aggregate_over_token`` - an aggregate function wrapping a ``${...}``
  token rather than a model measure, which is Omni's documented signal that the
  topic lacked the measure the metric needed;
* ``bare_table_from`` - a ``FROM`` naming a table rather than a ``${...}`` token,
  the one shape here that genuinely reaches outside the model.

These shapes co-occur, so they are counted independently rather than bucketed
into one winner-take-all classification.

Every input is public run metadata: the query shape flags on generation records
and the structure of the SQL string, never its literals. No question text, gold
SQL, result value, correctness label, or hidden annotation is read, and no SQL
text is emitted. The output is aggregate counts per arm, so it is safe to commit
alongside sealed arms whose per-question records are not public.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

#: A ``${...}`` reference into the deployed semantic model.
SEMANTIC_TOKEN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.]*)\}")

#: An aggregate applied directly to a model reference instead of a measure.
AGGREGATE_OVER_TOKEN = re.compile(
    r"\b(?:SUM|COUNT|AVG|MIN|MAX|MEDIAN|STDDEV|VARIANCE)\s*\(\s*(?:DISTINCT\s+)?\$\{",
    re.IGNORECASE,
)

#: A ``FROM`` clause naming a table rather than a model reference.
BARE_TABLE_FROM = re.compile(r"\bFROM\s+(?!\$\{)[\"`\[A-Za-z_]", re.IGNORECASE)

#: Shape counters reported per arm, in report order.
SHAPES = (
    "user_edited_sql",
    "topic_scoped",
    "user_edited_sql_and_topic_scoped",
    "semantic_token_present",
    "qualified_token_present",
    "inline_aggregate_over_token",
    "bare_table_from",
)


class QueryPathTallyError(ValueError):
    """Raised when an arm cannot be tallied from public run metadata."""


def _semantic_query(record: dict[str, Any]) -> dict[str, Any] | None:
    raw = record.get("generated_query")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _authored_sql(query: dict[str, Any]) -> str:
    value = query.get("userEditedSQL")
    return value if isinstance(value, str) else ""


def _is_topic_scoped(query: dict[str, Any]) -> bool:
    """Report whether the query named a topic for the model to scope joins."""
    value = query.get("join_paths_from_topic_name")
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def classify_query(query: dict[str, Any]) -> dict[str, Any]:
    """Measure the co-occurring path shapes of one governed semantic query."""

    sql = _authored_sql(query)
    has_sql = bool(sql.strip())
    topic_scoped = _is_topic_scoped(query)
    tokens = SEMANTIC_TOKEN.findall(sql) if has_sql else []
    return {
        "user_edited_sql": has_sql,
        "topic_scoped": topic_scoped,
        "user_edited_sql_and_topic_scoped": has_sql and topic_scoped,
        "semantic_token_present": bool(tokens),
        "qualified_token_present": any("." in token for token in tokens),
        "inline_aggregate_over_token": bool(
            has_sql and AGGREGATE_OVER_TOKEN.search(sql)
        ),
        "bare_table_from": bool(has_sql and BARE_TABLE_FROM.search(sql)),
        "semantic_token_count": len(tokens),
    }


def tally_arm(root: Path) -> dict[str, int]:
    """Count query-path shapes across every generation record under ``root``."""

    counts = dict.fromkeys(("attempts", "no_semantic_query", "semantic_token_total"), 0)
    counts.update(dict.fromkeys(SHAPES, 0))
    for path in sorted(root.rglob("generation.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            counts["attempts"] += 1
            query = _semantic_query(json.loads(line))
            if query is None:
                counts["no_semantic_query"] += 1
                continue
            shapes = classify_query(query)
            counts["semantic_token_total"] += shapes["semantic_token_count"]
            for shape in SHAPES:
                counts[shape] += int(shapes[shape])
    if counts["attempts"] == 0:
        raise QueryPathTallyError(f"no generation records under {root}")
    return counts


def _share(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 1) if denominator else None


def summarize_arm(counts: dict[str, int]) -> dict[str, Any]:
    """Add the parseable denominator and the shares reported alongside it."""

    parseable = counts["attempts"] - counts["no_semantic_query"]
    return {
        **counts,
        "parseable_attempts": parseable,
        "shares_of_parseable_percent": {
            shape: _share(counts[shape], parseable) for shape in SHAPES
        },
    }


def _named_root(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition("=")
    if not separator or not name.strip() or not path.strip():
        raise argparse.ArgumentTypeError("expected ARM=PATH")
    return name, Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--arm", type=_named_root, action="append", required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)

    workspace = arguments.workspace.resolve(strict=True)
    arms = {
        name: summarize_arm(tally_arm(workspace / root)) for name, root in arguments.arm
    }

    report = {
        "artifact_kind": "governed_query_path_tally",
        "arms": arms,
        "reads": "public query-shape flags and SQL structure on generation records only",
        "schema_version": SCHEMA_VERSION,
        "supersedes": "governed-query-path-tally-v1.json",
    }
    content = (
        json.dumps(report, allow_nan=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    if arguments.output is not None:
        destination = workspace / arguments.output
        if destination.exists():
            raise QueryPathTallyError(
                f"{destination} already exists; refusing overwrite"
            )
        destination.write_text(content, encoding="utf-8")
    print(content.rstrip("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Tally which query path every governed attempt actually took.

The governed conditions were adopted to test semantic composition. This
analyzer answers whether composition happened, by reading the semantic query
each governed attempt returned and counting three mutually exclusive shapes:

* ``rewrite`` - the attempt carried ``rewriteSql``, so Omni executed SQL the
  agent wrote rather than composing against the deployed model;
* ``composed`` - the attempt declared a model join path via ``join_via_map``
  and did not rewrite;
* ``no_semantic_query`` - the attempt returned nothing parseable.

Every input is public run metadata: the query shape flags on generation
records. No question text, gold SQL, result value, correctness label, or hidden
annotation is read. The output is aggregate counts per arm, so it is safe to
commit alongside sealed arms whose per-question records are not public.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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


def tally_arm(root: Path) -> dict[str, int]:
    """Count query-path shapes across every generation record under ``root``."""

    counts = {"attempts": 0, "rewrite": 0, "composed": 0, "no_semantic_query": 0}
    for path in sorted(root.rglob("generation.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            counts["attempts"] += 1
            query = _semantic_query(record)
            if query is None:
                counts["no_semantic_query"] += 1
            elif query.get("rewriteSql"):
                counts["rewrite"] += 1
            elif query.get("join_via_map"):
                counts["composed"] += 1
            else:
                counts["no_semantic_query"] += 1
    if counts["attempts"] == 0:
        raise QueryPathTallyError(f"no generation records under {root}")
    return counts


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
    arms: dict[str, Any] = {}
    for name, root in arguments.arm:
        counts = tally_arm(workspace / root)
        parseable = counts["attempts"] - counts["no_semantic_query"]
        arms[name] = {
            **counts,
            "parseable_attempts": parseable,
            "rewrite_share_of_parseable_percent": (
                round(100.0 * counts["rewrite"] / parseable, 1) if parseable else None
            ),
        }

    report = {
        "artifact_kind": "governed_query_path_tally",
        "arms": arms,
        "reads": "public query-shape flags on generation records only",
        "schema_version": 1,
    }
    content = (
        json.dumps(report, allow_nan=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    if arguments.output is not None:
        (workspace / arguments.output).write_text(content, encoding="utf-8")
    print(content.rstrip("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

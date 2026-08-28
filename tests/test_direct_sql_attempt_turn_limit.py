from __future__ import annotations

import json
from pathlib import Path

from omni_benchmark.direct_sql_attempt import write_direct_attempt
from tests.direct_attempt_fixtures import attempt_spec, capture_probe


COMMIT = "e" * 40


def test_turn_limit_after_tool_dispatch_captures_and_publishes_failure(
    tmp_path: Path,
) -> None:
    workspace, store, binding, probe = capture_probe(
        tmp_path,
        actions=[
            {
                "type": "tool",
                "name": "inspect_schema",
                "arguments": {"query": "public schema"},
            },
        ],
        instance_id="public-exhausted",
        maximum_turns=1,
        run_id="run-exhausted",
        system_commit=COMMIT,
    )

    artifacts = write_direct_attempt(
        workspace=workspace,
        store=store,
        spec=attempt_spec(binding),
        probe=probe,
    )

    generation = json.loads(artifacts.generation.path.read_text())
    assert generation["generation_outcome"] == "errored"
    assert generation["terminal_failure_class"] == "turn_limit_exhausted"

from __future__ import annotations

import pytest

from omni_benchmark.direct_action_protocol import (
    DirectActionProtocolError,
    DirectToolAction,
    direct_tool_specs,
    parse_direct_action,
)


def test_schema_tool_requires_query_for_every_direct_condition() -> None:
    for condition in ("C1", "C2", "C3"):
        schema_tool = next(
            tool
            for tool in direct_tool_specs(condition)
            if tool["name"] == "inspect_schema"
        )

        assert schema_tool["input_schema"] == {
            "additionalProperties": False,
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "type": "object",
        }


def test_schema_action_preserves_exact_nonempty_query() -> None:
    action = parse_direct_action(
        {
            "type": "tool",
            "name": "inspect_schema",
            "arguments": {"query": "weather conditions"},
        }
    )

    assert action == DirectToolAction("inspect_schema", {"query": "weather conditions"})


@pytest.mark.parametrize(
    "arguments",
    [{}, {"query": ""}, {"query": "weather", "extra": "forbidden"}],
)
def test_schema_action_rejects_missing_empty_or_extra_arguments(
    arguments: dict[str, str],
) -> None:
    with pytest.raises(DirectActionProtocolError):
        parse_direct_action(
            {"type": "tool", "name": "inspect_schema", "arguments": arguments}
        )

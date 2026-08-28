from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_benchmark.claude_direct_transport import ClaudeDirectTransportError
from tests.test_claude_direct_transport import (
    _messages,
    _success_stream,
    _tool_specs,
    _transport,
)


@pytest.mark.parametrize(
    "envelope",
    [
        None,
        {},
        {
            "action": {"sql": "SELECT COUNT(*) FROM site", "type": "answer"},
            "unexpected": True,
        },
        {"action": {"action": {"sql": "SELECT COUNT(*) FROM site", "type": "answer"}}},
    ],
)
def test_structured_action_requires_exact_provider_envelope(
    tmp_path: Path, envelope: object
) -> None:
    events = [json.loads(line) for line in _success_stream().splitlines()]
    events[-1]["structured_output"] = envelope
    transport, _ = _transport(
        tmp_path,
        "\n".join(json.dumps(event) for event in events),
    )

    with pytest.raises(ClaudeDirectTransportError) as exc:
        transport.next_turn(_messages(), _tool_specs())

    assert exc.value.category == "protocol"

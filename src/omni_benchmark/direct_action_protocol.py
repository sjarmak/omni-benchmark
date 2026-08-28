"""Strict action and tool schemas for direct-SQL comparator turns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .direct_capture_contract import DirectCondition

DIRECT_TOOL_NAMES = {
    "C1": ("inspect_schema", "execute_sql"),
    "C2": ("inspect_schema", "search_hkb", "execute_sql"),
    "C3": ("inspect_schema", "search_semantic_model", "execute_sql"),
}
_REFUSAL_REASONS = frozenset({"cannot_answer_safely", "insufficient_information"})


class DirectActionProtocolError(ValueError):
    """Raised when a model action violates the direct-comparator protocol."""


@dataclass(frozen=True)
class DirectToolAction:
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True)
class DirectAnswerAction:
    sql: str


@dataclass(frozen=True)
class DirectRefusalAction:
    reason: str


def direct_tool_specs(condition: DirectCondition) -> tuple[Mapping[str, Any], ...]:
    """Return the exact model-facing tool schema authorized for a condition."""
    definitions = {
        "inspect_schema": ("Inspect the public database schema.", {}),
        "search_hkb": (
            "Search the public database-level business knowledge base.",
            {"query": {"type": "string"}},
        ),
        "search_semantic_model": (
            "Search the public Omni semantic-model representation.",
            {"query": {"type": "string"}},
        ),
        "execute_sql": (
            "Execute admitted Query-only SQL using a read-only transaction.",
            {"sql": {"type": "string"}},
        ),
    }
    return tuple(
        {
            "description": definitions[name][0],
            "input_schema": {
                "additionalProperties": False,
                "properties": definitions[name][1],
                "required": list(definitions[name][1]),
                "type": "object",
            },
            "name": name,
        }
        for name in DIRECT_TOOL_NAMES[condition]
    )


def parse_direct_action(
    action: Mapping[str, Any],
) -> DirectToolAction | DirectAnswerAction | DirectRefusalAction:
    """Parse one strict structured model action."""
    action_type = action.get("type")
    if action_type == "tool":
        if set(action) != {"type", "name", "arguments"}:
            raise DirectActionProtocolError("tool action must use the exact schema")
        return _parse_tool_action(action)
    if action_type == "answer":
        if set(action) != {"type", "sql"} or not _nonempty(action.get("sql")):
            raise DirectActionProtocolError(
                "answer action must contain only non-empty SQL"
            )
        return DirectAnswerAction(action["sql"])
    if action_type == "refuse":
        if (
            set(action) != {"type", "reason"}
            or action.get("reason") not in _REFUSAL_REASONS
        ):
            raise DirectActionProtocolError("refusal action must use an allowed reason")
        return DirectRefusalAction(action["reason"])
    raise DirectActionProtocolError("model action type is invalid")


def _parse_tool_action(action: Mapping[str, Any]) -> DirectToolAction:
    name = action.get("name")
    arguments = action.get("arguments")
    if not isinstance(name, str) or not isinstance(arguments, Mapping):
        raise DirectActionProtocolError("tool action name and arguments are invalid")
    expected = {
        "inspect_schema": set(),
        "search_hkb": {"query"},
        "search_semantic_model": {"query"},
        "execute_sql": {"sql"},
    }
    if name not in expected or set(arguments) != expected[name]:
        raise DirectActionProtocolError("tool arguments do not match the strict schema")
    if any(not _nonempty(value) for value in arguments.values()):
        raise DirectActionProtocolError("tool string arguments must be non-empty")
    return DirectToolAction(name, dict(arguments))


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())

from typing import Any

MAXIMUM_JSON_NESTING = 64


def validate_json_nesting(value: Any, depth: int = 0) -> None:
    if not isinstance(value, (dict, list)):
        return
    if depth >= MAXIMUM_JSON_NESTING:
        raise RecursionError("JSON nesting exceeds the inventory limit")
    children = value.values() if isinstance(value, dict) else value
    for child in children:
        validate_json_nesting(child, depth + 1)

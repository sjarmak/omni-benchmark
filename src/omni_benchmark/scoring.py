"""Frozen, pure result comparators for LiveSQLBench Query tasks."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable


OFFICIAL_EVALUATOR_COMMIT = "e15cd221267e06fabfaf6a3d4a69308280ce9a7c"
OFFICIAL_SOFT_EX_VERSION = "livesqlbench-soft-ex-e15cd221-v1"
SENSITIVITY_SCORER_VERSION = "omni-multiset-decimal-v1"
DEFAULT_DECIMAL_PLACES = 2
PUBLIC_DECIMAL_VALUES = frozenset({-1, 0, 1, 2, 3, 4, 5, 6, 8})


class ScoringPolicyError(ValueError):
    """Raised when scorer inputs violate the frozen scoring policy."""


def scorer_metadata() -> dict[str, dict[str, str | None]]:
    """Return independently serializable scorer-version metadata."""

    return {
        "official_soft_ex": {
            "decimal_policy": "fixed_2_half_up",
            "version": OFFICIAL_SOFT_EX_VERSION,
            "upstream_commit": OFFICIAL_EVALUATOR_COMMIT,
        },
        "sensitivity": {
            "decimal_policy": "minus_one_exact_nonnegative_half_up",
            "version": SENSITIVITY_SCORER_VERSION,
            "upstream_commit": None,
        },
    }


def _quantize_number(value: Decimal | float | int, decimal_places: int) -> Decimal:
    quantizer = Decimal(1).scaleb(-decimal_places)
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    return decimal_value.quantize(quantizer, rounding=ROUND_HALF_UP)


def _official_recursive(value: Any, decimal_places: int) -> Any:
    if isinstance(value, Decimal):
        return float(_quantize_number(value, decimal_places))
    if isinstance(value, float):
        return float(_quantize_number(value, decimal_places))
    if isinstance(value, (list, tuple)):
        return type(value)(_official_recursive(item, decimal_places) for item in value)
    if isinstance(value, dict):
        return {
            key: _official_recursive(item, decimal_places)
            for key, item in value.items()
        }
    return value


def _official_item(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    normalized = _official_recursive(value, DEFAULT_DECIMAL_PLACES)
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, sort_keys=True)
    return normalized


def _normalize_rows(
    results: Sequence[Sequence[Any]], normalizer: Callable[[Any], Any]
) -> list[tuple[Any, ...]]:
    return [tuple(normalizer(value) for value in row) for row in results]


def _official_order(conditions: Mapping[str, Any] | None) -> bool:
    if conditions is None:
        return False
    order = conditions.get("order", False)
    if not isinstance(order, bool):
        raise ScoringPolicyError("conditions.order must be a boolean")
    return order


def official_soft_ex_equal(
    predicted: Sequence[Sequence[Any]],
    gold: Sequence[Sequence[Any]],
    *,
    conditions: Mapping[str, Any] | None = None,
) -> bool:
    """Compare executed rows using the pinned official Soft EX behavior."""

    predicted_rows = _normalize_rows(predicted, _official_item)
    gold_rows = _normalize_rows(gold, _official_item)
    if not predicted_rows or not gold_rows:
        return False
    if _official_order(conditions):
        return predicted_rows == gold_rows
    return set(predicted_rows) == set(gold_rows)


def _sensitivity_policy(
    conditions: Mapping[str, Any] | None,
) -> tuple[int | None, bool]:
    if not isinstance(conditions, Mapping):
        raise ScoringPolicyError("conditions must be a mapping")
    if "decimal" not in conditions:
        raise ScoringPolicyError("conditions.decimal is required")
    decimal = conditions["decimal"]
    if not isinstance(decimal, int) or isinstance(decimal, bool):
        raise ScoringPolicyError("conditions.decimal must be an integer")
    if decimal not in PUBLIC_DECIMAL_VALUES:
        allowed = ", ".join(str(value) for value in sorted(PUBLIC_DECIMAL_VALUES))
        raise ScoringPolicyError(f"conditions.decimal must be one of: {allowed}")
    order = conditions.get("order")
    if not isinstance(order, bool):
        raise ScoringPolicyError("conditions.order must be a boolean")
    decimal_places = None if decimal == -1 else decimal
    return decimal_places, order


def _stable_key(value: tuple[Any, ...]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_exact_number(value: Decimal | float | int) -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    normalized = Decimal(0) if decimal_value == 0 else decimal_value.normalize()
    return format(normalized, "f")


def _sensitivity_item(value: Any, decimal_places: int | None) -> tuple[Any, ...]:
    if value is None:
        return ("null",)
    if isinstance(value, (date, datetime)):
        return ("date", value.strftime("%Y-%m-%d"))
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (Decimal, float, int)):
        if decimal_places is None:
            return ("number", _canonical_exact_number(value))
        return ("number", format(_quantize_number(value, decimal_places), "f"))
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, Mapping):
        pairs = (
            (
                _sensitivity_item(key, decimal_places),
                _sensitivity_item(item, decimal_places),
            )
            for key, item in value.items()
        )
        return (
            "mapping",
            tuple(sorted(pairs, key=lambda pair: _stable_key(pair[0]))),
        )
    if isinstance(value, (list, tuple)):
        return (
            "sequence",
            tuple(_sensitivity_item(item, decimal_places) for item in value),
        )
    return (f"python:{type(value).__module__}.{type(value).__qualname__}", repr(value))


def sensitivity_equal(
    predicted: Sequence[Sequence[Any]],
    gold: Sequence[Sequence[Any]],
    *,
    conditions: Mapping[str, Any] | None,
) -> bool:
    """Compare executed rows with multiplicity and public decimal metadata."""

    decimal_places, ordered = _sensitivity_policy(conditions)

    def normalizer(value: Any) -> tuple[Any, ...]:
        return _sensitivity_item(value, decimal_places)

    predicted_rows = _normalize_rows(predicted, normalizer)
    gold_rows = _normalize_rows(gold, normalizer)
    if ordered:
        return predicted_rows == gold_rows
    return Counter(predicted_rows) == Counter(gold_rows)


def _remove_comments_official(sql: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    no_line = re.sub(r"--.*?(\r\n|\r|\n)", r"\1", no_block)
    no_blank = re.sub(r"\n\s*\n+", "\n", no_line)
    return no_blank.strip()


def _remove_distinct_official(sql: str) -> str:
    cleaned = re.sub(r"\bDISTINCT\b(?![^()]*\bON\b)", "", sql, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _matching_parenthesis(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _first_argument_end(text: str, start: int) -> int:
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            if depth == 0:
                return index
            depth -= 1
        elif text[index] == "," and depth == 0:
            return index
    return len(text)


def _remove_round_official(sql: str) -> str:
    result = sql
    pattern = re.compile(r"ROUND\s*\(", re.IGNORECASE)
    while match := pattern.search(result):
        open_parenthesis = match.end() - 1
        close_parenthesis = _matching_parenthesis(result, open_parenthesis)
        if close_parenthesis == -1:
            break
        argument_end = _first_argument_end(result, open_parenthesis + 1)
        first_argument = result[open_parenthesis + 1 : argument_end].strip()
        result = (
            result[: match.start()] + first_argument + result[close_parenthesis + 1 :]
        )
    return result


def rewrite_sql_official(sql: str) -> str:
    """Apply the official Query-task rewrites before database execution."""

    return _remove_round_official(
        _remove_distinct_official(_remove_comments_official(sql))
    )


def rewrite_sql_sensitivity(sql: str) -> str:
    """Preserve the authored SQL for the corrected sensitivity analysis."""

    return sql

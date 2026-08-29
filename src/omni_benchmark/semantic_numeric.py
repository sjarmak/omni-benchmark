"""Apply public-schema numeric types to modeled scalar expressions."""

from __future__ import annotations

import re
from typing import Any, Mapping

import sqlglot
from sqlglot import expressions as exp


class NumericExpressionError(ValueError):
    """Raised when a numeric expression cannot be transformed safely."""


_FIELD_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_FIELD_SENTINEL = "__omni_modeled_field_reference__"
_FIELD_SENTINEL_CALL = re.compile(
    rf"{_FIELD_SENTINEL}\('([A-Za-z_][A-Za-z0-9_]*)'\)", re.IGNORECASE
)
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NUMERIC_TEXT_PATTERN = r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
_NUMERIC_TYPE = re.compile(
    r"^(?:BIGINT|BIGSERIAL|DECIMAL|DOUBLE PRECISION|FLOAT|INTEGER|MONEY|"
    r"NUMERIC|REAL|SERIAL|SMALLINT|SMALLSERIAL)(?:\b|\()"
)
_TEXT_TYPE = re.compile(r"^(?:CHAR|CHARACTER|CHARACTER VARYING|TEXT|VARCHAR)(?:\b|\()")
_SCIENTIFIC_LITERAL = re.compile(
    r"^(?:[0-9]+(?:\.([0-9]*))?|\.([0-9]+))[eE]([+-]?)([0-9]+)$"
)
_ARITHMETIC = (exp.Add, exp.Div, exp.Mod, exp.Mul, exp.Pow, exp.Sub)
_COMPARISONS = (exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.NEQ)


def schema_value_kind(source: Mapping[str, Any]) -> str:
    """Classify a public column or structured-leaf declaration."""
    if source.get("record_kind") == "column":
        declared = source.get("declared_type_sql")
        if not isinstance(declared, str):
            return "unknown"
        type_text = declared.strip().upper()
    elif source.get("record_kind") == "structured_leaf":
        description = source.get("description")
        if not isinstance(description, str):
            return "unknown"
        type_text = description.split(".", maxsplit=1)[0].strip().upper()
    else:
        return "unknown"
    if _NUMERIC_TYPE.match(type_text):
        return "numeric"
    if _TEXT_TYPE.match(type_text):
        return "text"
    return "other"


def physical_value_kind(source: Mapping[str, Any], sql: str | None) -> str:
    """Classify the value exposed by one compiled physical dimension."""
    if sql is not None and _root_numeric_cast(sql):
        return "numeric"
    kind = schema_value_kind(source)
    if source.get("record_kind") == "structured_leaf" and kind == "numeric":
        return "numeric_text"
    return kind


def _root_numeric_cast(sql: str) -> bool:
    parseable = _replace_references(sql)
    try:
        statement = sqlglot.parse_one(f"SELECT {parseable}", read="postgres")
    except sqlglot.errors.ParseError:
        return False
    if not isinstance(statement, exp.Select) or len(statement.expressions) != 1:
        return False
    expression = statement.expressions[0]
    while isinstance(expression, exp.Paren):
        expression = expression.this
    if not isinstance(expression, exp.Cast):
        return False
    target = expression.args.get("to")
    return isinstance(target, exp.DataType) and bool(
        _NUMERIC_TYPE.match(target.sql(dialect="postgres").strip().upper())
    )


def _replace_references(sql: str) -> str:
    return _FIELD_REFERENCE.sub(
        lambda match: f"{_FIELD_SENTINEL}('{match.group(1)}')", sql
    )


def _parse_scalar(sql: str) -> exp.Expression:
    try:
        statement = sqlglot.parse_one(
            f"SELECT {_replace_references(sql)}", read="postgres"
        )
    except sqlglot.errors.ParseError as error:
        raise NumericExpressionError(
            "field SQL is not valid PostgreSQL syntax"
        ) from error
    if not isinstance(statement, exp.Select) or len(statement.expressions) != 1:
        raise NumericExpressionError("field SQL must be one modeled scalar expression")
    return statement.expressions[0]


def _render_scalar(node: exp.Expression) -> str:
    restored = _FIELD_SENTINEL_CALL.sub(
        lambda match: f"${{{match.group(1)}}}", node.sql(dialect="postgres")
    )
    if _FIELD_SENTINEL in restored.lower():
        raise NumericExpressionError(
            "numeric expression transformation left a reserved identifier"
        )
    return restored


def _sentinel_field(node: exp.Expression) -> str | None:
    if not isinstance(node, exp.Anonymous) or node.name.lower() != _FIELD_SENTINEL:
        return None
    if len(node.expressions) != 1 or not isinstance(node.expressions[0], exp.Literal):
        return None
    literal = node.expressions[0]
    if not literal.is_string or not _SAFE_NAME.fullmatch(str(literal.this)):
        return None
    return str(literal.this)


def _double_type() -> exp.DataType:
    return exp.DataType.build("DOUBLE PRECISION", dialect="postgres")


def _safe_numeric_text(node: exp.Expression) -> exp.Expression:
    return exp.Case(
        ifs=[
            exp.If(
                this=exp.RegexpLike(
                    this=exp.Trim(this=node.copy()),
                    expression=exp.Literal.string(_NUMERIC_TEXT_PATTERN),
                ),
                true=exp.Cast(this=exp.Trim(this=node.copy()), to=_double_type()),
            )
        ],
        default=exp.Null(),
    )


def _numeric_literal(node: exp.Expression | None) -> bool:
    if isinstance(node, exp.Literal):
        return not node.is_string
    if isinstance(node, exp.Neg):
        return _numeric_literal(node.this)
    return False


def _has_negative_decimal_scale(node: exp.Expression) -> bool:
    if not isinstance(node, exp.Literal) or node.is_string:
        return False
    match = _SCIENTIFIC_LITERAL.fullmatch(str(node.this))
    if match is None:
        return False
    fractional_digits = match.group(1) or match.group(2) or ""
    exponent_sign = match.group(3)
    exponent = int(match.group(4))
    return exponent_sign == "-" or exponent > len(fractional_digits)


def _expectations(
    node: exp.Expression, expected_numeric: bool
) -> tuple[set[str], set[str]]:
    if isinstance(node, _ARITHMETIC):
        return {"this", "expression"}, set()
    if isinstance(node, (exp.Ln, exp.Neg, exp.Sqrt)):
        return {"this"}, set()
    if isinstance(node, exp.Nullif) and expected_numeric:
        return {"this", "expression"}, set()
    if isinstance(node, (exp.Coalesce, exp.Greatest, exp.Least)):
        return set(), {"this", "expressions"} if expected_numeric else set()
    if isinstance(node, exp.Case):
        return set(), {"default"}
    if isinstance(node, _COMPARISONS) and (
        _numeric_literal(node.this) or _numeric_literal(node.expression)
    ):
        return {"this", "expression"}, set()
    return set(), set()


def _rewrite_case_if(
    node: exp.If,
    field_kinds: Mapping[str, str],
    expected_numeric: bool,
) -> tuple[exp.If, bool]:
    rewritten = node.copy()
    condition, condition_changed = _coerce_node(
        node.this, field_kinds, expected_numeric=False
    )
    result, result_changed = _coerce_node(
        node.args["true"], field_kinds, expected_numeric=expected_numeric
    )
    rewritten.set("this", condition)
    rewritten.set("true", result)
    return rewritten, condition_changed or result_changed


def _rewrite_list(
    parent: exp.Expression,
    values: list[Any],
    field_kinds: Mapping[str, str],
    expected_numeric: bool,
) -> tuple[list[Any], bool]:
    rewritten: list[Any] = []
    changed = False
    for child in values:
        if not isinstance(child, exp.Expression):
            rewritten.append(child)
        elif isinstance(parent, exp.Case) and isinstance(child, exp.If):
            value, child_changed = _rewrite_case_if(
                child, field_kinds, expected_numeric
            )
            rewritten.append(value)
            changed = changed or child_changed
        else:
            value, child_changed = _coerce_node(
                child, field_kinds, expected_numeric=expected_numeric
            )
            rewritten.append(value)
            changed = changed or child_changed
    return rewritten, changed


def _coerce_children(
    node: exp.Expression,
    field_kinds: Mapping[str, str],
    expected_numeric: bool,
) -> tuple[exp.Expression, bool]:
    numeric_keys, inherited_keys = _expectations(node, expected_numeric)
    copied = node.copy()
    changed = False
    for key, value in node.args.items():
        child_expected = key in numeric_keys or (
            expected_numeric and key in inherited_keys
        )
        if isinstance(value, exp.Expression):
            rewritten, child_changed = _coerce_node(
                value, field_kinds, expected_numeric=child_expected
            )
            copied.set(key, rewritten)
        elif isinstance(value, list):
            rewritten, child_changed = _rewrite_list(
                node, value, field_kinds, child_expected
            )
            copied.set(key, rewritten)
        else:
            continue
        changed = changed or child_changed
    return copied, changed


def _coerce_node(
    node: exp.Expression,
    field_kinds: Mapping[str, str],
    *,
    expected_numeric: bool,
) -> tuple[exp.Expression, bool]:
    field = _sentinel_field(node)
    if field is not None and expected_numeric:
        kind = field_kinds.get(field, "unknown")
        if kind == "numeric_text":
            return exp.Cast(this=node.copy(), to=_double_type()), True
        if kind == "text":
            return _safe_numeric_text(node), True
    if field is not None or isinstance(node, exp.Cast):
        return node.copy(), False
    return _coerce_children(node, field_kinds, expected_numeric)


def coerce_numeric_references(sql: str, field_kinds: Mapping[str, str]) -> str:
    """Cast only field references used in numeric expression positions."""
    expression = _parse_scalar(sql)
    rewritten, changed = _coerce_node(expression, field_kinds, expected_numeric=True)
    if not changed:
        return sql
    return _render_scalar(rewritten)


def stabilize_negative_scale_decimals(sql: str) -> str:
    """Cast scientific literals that destabilize Omni decimal-scale inference."""
    rewritten = _parse_scalar(sql).copy()
    targets = [node for node in rewritten.walk() if _has_negative_decimal_scale(node)]
    for node in targets:
        node.replace(exp.Cast(this=node.copy(), to=_double_type()))
    if not targets:
        return sql
    return _render_scalar(rewritten)

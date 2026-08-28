from __future__ import annotations

import json
import re

from .claude_direct_contract import ClaudeFailureCategory

_AUTH_PATTERN = re.compile(
    r"(?i)(authentication\s+(?:failed|error)|invalid\s+(?:auth|oauth)|"
    r"oauth\s+(?:session|token)\s+(?:expired|invalid)|api\s*key\s+(?:invalid|missing)|"
    r"unauthorized|(?:http\s+|status\s*=?\s*)(?:401|403)\b)"
)
_RATE_LIMIT_PATTERN = re.compile(r"(?i)(?:http\s+|status\s*=?\s*)429\b")
_QUOTA_PATTERN = re.compile(
    r"(?i)(monthly\s+usage\s+limit|rate\s+limit\s+(?:exceeded|reached)|"
    r"quota\s+(?:exceeded|exhausted)|usage\s+limit\s+reached|"
    r"hit\s+your\s+session\s+limit)"
)


def classify_claude_failure(stdout: str, stderr: str) -> ClaudeFailureCategory:
    literal = "\n".join((*_literal_lines(stdout), stderr))
    if _AUTH_PATTERN.search(literal):
        return "auth"
    if _RATE_LIMIT_PATTERN.search(literal):
        return "rate_limit"
    if _QUOTA_PATTERN.search(literal):
        return "quota"
    return "infrastructure"


def _literal_lines(raw: str) -> tuple[str, ...]:
    literal: list[str] = []
    for line in raw.splitlines():
        try:
            value = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            literal.append(line)
            continue
        if not isinstance(value, dict):
            literal.append(line)
    return tuple(literal)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")

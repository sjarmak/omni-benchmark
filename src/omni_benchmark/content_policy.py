"""Shared secret redaction and bounded diagnostic-content policy."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

MAX_DETAIL_CHARS = 2000
MAX_IDENTIFIER_CHARS = 512
TRUNCATION_NOTE = "... [truncated]"
REDACTED = "[REDACTED]"

SENSITIVE_KEY_NAMES = frozenset(
    {
        "api_key",
        "access_key",
        "all_proxy",
        "auth",
        "authorization",
        "cookie",
        "cookies",
        "connection_string",
        "connection_uri",
        "credential",
        "credentials",
        "database_url",
        "dsn",
        "http_proxy",
        "https_proxy",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session",
        "set_cookie",
        "storage_state",
        "token",
        "webhook_signing_secret",
    }
)
SENSITIVE_KEY_SUFFIXES = (
    "password",
    "passwd",
    "_access_key",
    "_api_key",
    "_cookie",
    "_credential",
    "_database_url",
    "_dsn",
    "_password",
    "_private_key",
    "_connection_string",
    "_connection_uri",
    "_secret",
    "_storage_state",
    "_token",
)
SENSITIVE_URI_KEY_NAMES = frozenset(
    {
        "all_proxy",
        "connection_string",
        "connection_uri",
        "database_url",
        "dsn",
        "http_proxy",
        "https_proxy",
    }
)
SENSITIVE_URI_KEY_SUFFIXES = (
    "_connection_string",
    "_connection_uri",
    "_database_url",
    "_dsn",
)
PERSISTED_VALUE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{12,}"), REDACTED),
    (re.compile(r"sk-proj-[A-Za-z0-9_-]{12,}"), REDACTED),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"), f"Bearer {REDACTED}"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
)
SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    *PERSISTED_VALUE_PATTERNS,
    (
        re.compile(
            r"(?i)\b([A-Za-z0-9_.-]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD))"
            r'(["\']?\s*[=:]\s*["\']?)[^\s"\',;}]+'
        ),
        rf"\1\2{REDACTED}",
    ),
)


@dataclass(frozen=True)
class ContentPolicy:
    """Immutable policy constructed from the current credential environment."""

    exact_secret_values: tuple[str, ...] = field(repr=False)

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> ContentPolicy:
        values: set[str] = set()
        for key, value in environment.items():
            if not value or not _is_sensitive_key(key):
                continue
            values.add(value)
            if _is_sensitive_uri_key(key):
                values.update(_uri_userinfo_components(value))
        return cls(tuple(sorted(values, key=lambda value: (-len(value), value))))

    def redact(self, value: str) -> str:
        """Destroy exact live credentials and common credential shapes."""
        redacted = value
        for secret in self.exact_secret_values:
            redacted = redacted.replace(secret, REDACTED)
        for pattern, replacement in SECRET_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    def redact_persisted_value(self, value: str) -> str:
        """Redact credential values without treating SQL column names as secrets."""
        redacted = value
        for secret in self.exact_secret_values:
            redacted = redacted.replace(secret, REDACTED)
        for pattern, replacement in PERSISTED_VALUE_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    def safe_detail(self, value: object) -> str:
        """Redact before applying the persisted diagnostic-size ceiling."""
        redacted = self.redact(str(value))
        if len(redacted) <= MAX_DETAIL_CHARS:
            return redacted
        return redacted[: MAX_DETAIL_CHARS - len(TRUNCATION_NOTE)] + TRUNCATION_NOTE

    def diagnostic_is_safe(self, value: str) -> bool:
        """Return true only when a diagnostic is already redacted and bounded."""
        return self.safe_detail(value) == value

    def identifier_is_safe(self, value: str) -> bool:
        """Validate short persisted provider/model/tool identifiers."""
        return len(value) <= MAX_IDENTIFIER_CHARS and self.redact(value) == value

    def query_is_safe(self, value: str) -> bool:
        """Reject executable text containing credential material; never rewrite it."""
        return self.redact_persisted_value(value) == value

    def bytes_are_safe(self, value: bytes) -> bool:
        """Reject raw text bytes containing credential material."""
        try:
            decoded = value.decode("utf-8")
        except UnicodeError:
            return False
        return self.redact_persisted_value(decoded) == decoded

    def sanitize_json(self, value: Any) -> Any:
        """Recursively redact sensitive keys and string values."""
        if isinstance(value, dict):
            return {
                key: (
                    REDACTED
                    if _is_sensitive_key(str(key))
                    else self.sanitize_json(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.sanitize_json(item) for item in value]
        if isinstance(value, str):
            return self.redact_persisted_value(value)
        return value

    def field_name_is_sensitive(self, value: str) -> bool:
        """Return whether a provider field name identifies credential material."""
        return _is_sensitive_key(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in SENSITIVE_KEY_NAMES or normalized.endswith(
        SENSITIVE_KEY_SUFFIXES
    )


def _is_sensitive_uri_key(key: str) -> bool:
    normalized = _normalize_key(key)
    return normalized in SENSITIVE_URI_KEY_NAMES or normalized.endswith(
        SENSITIVE_URI_KEY_SUFFIXES
    )


def _normalize_key(key: str) -> str:
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return normalized.lower().replace("-", "_")


def _uri_userinfo_components(value: str) -> set[str]:
    try:
        parsed = urlsplit(value)
        components = (parsed.username, parsed.password)
    except ValueError:
        return set()
    return {
        component
        for original in components
        if original
        for component in (original, unquote(original))
        if component
    }

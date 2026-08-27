from __future__ import annotations

import pytest

from omni_benchmark.content_policy import ContentPolicy, MAX_DETAIL_CHARS


def test_safe_detail_redacts_before_bounding_and_is_idempotent() -> None:
    policy = ContentPolicy.from_environment(
        {"UNRELATED_SERVICE_TOKEN": "live-secret-value"}
    )
    value = "x" * MAX_DETAIL_CHARS + " Bearer abc.def.ghi live-secret-value"

    sanitized = policy.safe_detail(value)

    assert len(sanitized) <= MAX_DETAIL_CHARS
    assert "abc.def.ghi" not in sanitized
    assert "live-secret-value" not in sanitized
    assert policy.safe_detail(sanitized) == sanitized


def test_policy_repr_never_exposes_captured_secret_values() -> None:
    policy = ContentPolicy.from_environment(
        {"UNRELATED_SERVICE_TOKEN": "live-secret-value"}
    )

    assert "live-secret-value" not in repr(policy)


def test_database_connection_environment_values_are_credentials() -> None:
    connection = "postgresql://benchmark:live-password@db.example/analytics"
    policy = ContentPolicy.from_environment({"DATABASE_URL": connection})

    assert connection not in policy.safe_detail(f"provider failed: {connection}")
    assert policy.bytes_are_safe(connection.encode()) is False


@pytest.mark.parametrize(
    "key",
    ["TOKEN", "CREDENTIAL", "CREDENTIALS", "ACCESS_KEY", "AUTH"],
)
def test_bare_credential_environment_names_are_sensitive(key: str) -> None:
    policy = ContentPolicy.from_environment({key: "live-credential-canary"})

    assert "live-credential-canary" not in policy.safe_detail(
        "provider echoed live-credential-canary"
    )


def test_proxy_environment_values_are_sensitive() -> None:
    proxy = "http://benchmark:live-password@proxy.example:8080"
    policy = ContentPolicy.from_environment({"HTTPS_PROXY": proxy})

    assert proxy not in policy.safe_detail(f"proxy failed: {proxy}")
    assert policy.bytes_are_safe(proxy.encode()) is False


@pytest.mark.parametrize("key", ["HTTPS_PROXY", "DATABASE_URL", "DSN"])
def test_connection_uri_userinfo_components_are_sensitive(key: str) -> None:
    connection_uri = (
        "postgresql://benchmark-user:live%2Fpassword@database.example/benchmark"
    )
    policy = ContentPolicy.from_environment({key: connection_uri})

    detail = policy.safe_detail(
        "authentication failed for benchmark-user using live/password or "
        "live%2Fpassword"
    )

    assert "benchmark-user" not in detail
    assert "live/password" not in detail
    assert "live%2Fpassword" not in detail
    assert policy.bytes_are_safe(connection_uri.encode()) is False


def test_json_projection_redacts_sensitive_keys_and_exact_values() -> None:
    policy = ContentPolicy.from_environment({"OMNI_API_TOKEN": "live-token-value"})

    sanitized = policy.sanitize_json(
        {
            "authorization": "Bearer provider-token",
            "nested": {"cookie": "session-cookie", "message": "live-token-value"},
            "token_usage": {"input_tokens": 10, "output_tokens": 5},
        }
    )

    assert sanitized == {
        "authorization": "[REDACTED]",
        "nested": {"cookie": "[REDACTED]", "message": "[REDACTED]"},
        "token_usage": {"input_tokens": 10, "output_tokens": 5},
    }


def test_json_projection_recognizes_api_key_spelling_variants() -> None:
    policy = ContentPolicy.from_environment({"API_KEY": "live-api-key"})

    sanitized = policy.sanitize_json(
        {"API_KEY": "first", "nested": {"apiKey": "second"}}
    )

    assert sanitized == {
        "API_KEY": "[REDACTED]",
        "nested": {"apiKey": "[REDACTED]"},
    }


@pytest.mark.parametrize(
    "key",
    ["token", "credential", "credentials", "access_key", "auth"],
)
def test_json_projection_redacts_bare_credential_keys(key: str) -> None:
    policy = ContentPolicy.from_environment({})

    assert policy.sanitize_json({key: "opaque-value"}) == {key: "[REDACTED]"}


def test_query_check_rejects_exact_live_secret_without_rewriting_sql() -> None:
    policy = ContentPolicy.from_environment({"OMNI_API_TOKEN": "live-token-value"})

    assert policy.query_is_safe("SELECT 1") is True
    assert policy.query_is_safe("SELECT 'live-token-value'") is False

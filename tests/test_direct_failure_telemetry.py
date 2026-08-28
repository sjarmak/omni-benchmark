from __future__ import annotations

import math

import pytest

from omni_benchmark.claude_direct_contract import (
    ClaudeDirectTransportError,
    ClaudeUsage,
)
from omni_benchmark.direct_capture_contract import (
    DirectModelFailure,
    DirectModelUsage,
)


def test_model_failure_preserves_partial_and_terminal_observations() -> None:
    partial = DirectModelUsage(input_tokens=17, output_tokens=3)
    terminal = DirectModelUsage(input_tokens=19, output_tokens=5)

    failure = DirectModelFailure(
        "rate_limit",
        "provider rate limit",
        partial_usage=partial,
        retry_count=2,
        terminal_cost_usd=0.125,
        terminal_usage=terminal,
    )

    assert failure.category == "rate_limit"
    assert failure.partial_usage == partial
    assert failure.terminal_usage == terminal
    assert failure.retry_count == 2
    assert failure.terminal_cost_usd == pytest.approx(0.125)
    assert failure.accounted_usage == terminal
    assert failure.token_source == "provider_reported"
    assert failure.token_observation == "terminal"
    assert failure.cost_source == "provider_reported"
    assert failure.retryable is False


def test_model_failure_uses_partial_usage_when_terminal_usage_is_unavailable() -> None:
    partial = DirectModelUsage(input_tokens=11, output_tokens=2)

    failure = DirectModelFailure(
        "timeout",
        "provider timeout",
        partial_usage=partial,
        retry_count=None,
    )

    assert failure.accounted_usage == partial
    assert failure.token_source == "provider_reported"
    assert failure.token_observation == "partial"
    assert failure.cost_source == "unavailable"
    assert failure.retryable is True


def test_model_failure_preserves_explicit_zero_telemetry() -> None:
    zero = DirectModelUsage(input_tokens=0, output_tokens=0)

    failure = DirectModelFailure(
        "auth",
        "provider authentication failed",
        partial_usage=zero,
        retry_count=0,
        terminal_cost_usd=0.0,
        terminal_usage=zero,
    )

    assert failure.accounted_usage == zero
    assert failure.retry_count == 0
    assert failure.terminal_cost_usd == 0.0
    assert failure.token_source == "provider_reported"
    assert failure.token_observation == "terminal"
    assert failure.cost_source == "provider_reported"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_tokens", -1),
        ("input_tokens", True),
        ("output_tokens", -1),
        ("output_tokens", 1.5),
    ],
)
def test_model_usage_rejects_invalid_counts(field: str, value: object) -> None:
    values: dict[str, object] = {"input_tokens": 1, "output_tokens": 1}
    values[field] = value

    with pytest.raises(ValueError, match=field):
        DirectModelUsage(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [-1, True, 1.5])
def test_model_failure_rejects_invalid_retry_counts(value: object) -> None:
    with pytest.raises(ValueError, match="retry_count"):
        DirectModelFailure(
            "timeout",
            "provider timeout",
            retry_count=value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf, True])
def test_model_failure_rejects_invalid_cost(value: object) -> None:
    with pytest.raises(ValueError, match="terminal_cost_usd"):
        DirectModelFailure(
            "budget",
            "provider budget exhausted",
            terminal_cost_usd=value,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("category", ["unknown", None, ["timeout"]])
def test_model_failure_rejects_unknown_category_and_non_typed_usage(
    category: object,
) -> None:
    with pytest.raises(ValueError, match="category"):
        DirectModelFailure(category, "provider failed")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="partial_usage"):
        DirectModelFailure(
            "protocol",
            "provider protocol failed",
            partial_usage={"input_tokens": 1, "output_tokens": 1},  # type: ignore[arg-type]
        )


def test_claude_failure_implements_provider_neutral_failure_contract() -> None:
    partial = ClaudeUsage(
        input_tokens=13,
        output_tokens=4,
        message_count=2,
        models=("claude-sonnet-4-6",),
    )
    terminal = ClaudeUsage(
        input_tokens=15,
        output_tokens=5,
        message_count=1,
        models=("claude-sonnet-4-6",),
    )

    failure = ClaudeDirectTransportError(
        "budget",
        "Claude exhausted its fixed budget",
        partial_usage=partial,
        retry_count=1,
        terminal_cost_usd=0.25,
        terminal_usage=terminal,
    )

    assert isinstance(failure, DirectModelFailure)
    assert failure.partial_usage is partial
    assert failure.terminal_usage is terminal
    assert failure.accounted_usage is terminal
    assert failure.token_source == "provider_reported"
    assert failure.token_observation == "terminal"

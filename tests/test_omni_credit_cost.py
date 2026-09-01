"""Bracketed credit-usage cost measurement for governed Omni attempts."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from omni_benchmark.autoresearch_capture_policy import _validate_sources
from omni_benchmark.baseline_batch import (
    AttemptObservation,
    BaselineAttempt,
    BaselineBatchError,
    BatchBudget,
    _hard_budget_cost,
)
from omni_benchmark.autoresearch_config import AutoresearchError
from omni_benchmark.omni_credit_cost import (
    COST_SOURCE_CREDIT_USAGE_DELTA,
    COST_UNAVAILABLE_JOB_API,
    COST_UNAVAILABLE_NONMONOTONIC,
    COST_UNAVAILABLE_PERIOD_ROLLOVER,
    COST_UNAVAILABLE_READ_FAILED,
    LEASE_DIRECTORY_VARIABLE,
    AttemptCost,
    CreditUsageReading,
    OmniCreditCostError,
    capture_with_cost,
    credit_usage_user_id,
    read_credit_usage,
    resolve_attempt_cost,
    unavailable_cost,
)

USER_ID = "595a871e-e5a9-46b7-a208-f8920da67263"
OTHER_USER_ID = "21798e02-8b2e-4d88-9f4b-55c5538ff4ef"
PERIOD_START_MS = 1785542400000
PERIOD_END_MS = 1788220800000

_C4_BUDGET = BatchBudget(
    cost_ceiling_usd=10.0,
    attempt_cost_ceiling_usd=1.0,
    unobservable_cost_reservation_conditions=frozenset({"C4"}),
)


def usage_response(
    credits: float,
    *,
    user_id: str = USER_ID,
    period_start_ms: int = PERIOD_START_MS,
    period_end_ms: int = PERIOD_END_MS,
) -> dict[str, Any]:
    return {
        "periodEnd": period_end_ms,
        "periodStart": period_start_ms,
        "users": [{"creditsUsed": credits, "userId": user_id}],
    }


def reading(
    credits: float, *, period_start_ms: int = PERIOD_START_MS
) -> CreditUsageReading:
    return CreditUsageReading(
        user_id=USER_ID,
        credits_used=credits,
        period_start_ms=period_start_ms,
        period_end_ms=PERIOD_END_MS,
    )


@dataclass
class FakeProbe:
    """The single probe attribute the bracket is allowed to set."""

    cost: AttemptCost | None = None


class FakeClient:
    """A credit-usage transport that answers from a scripted queue."""

    def __init__(self, responses: Sequence[Any]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, ...]] = []

    def whoami(self) -> dict[str, Any]:
        return {"user": {"id": OTHER_USER_ID, "membershipId": USER_ID}}

    def credit_usage(self, user_ids: Sequence[str]) -> dict[str, Any]:
        self.requests.append(tuple(user_ids))
        if not self._responses:
            raise AssertionError("credit usage was read more times than scripted")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def enabled_environment(lease_directory: Path) -> dict[str, str]:
    return {LEASE_DIRECTORY_VARIABLE: str(lease_directory)}


def test_user_id_comes_from_the_whoami_membership_identity() -> None:
    whoami = {"user": {"id": OTHER_USER_ID, "membershipId": USER_ID}}
    assert credit_usage_user_id(whoami) == USER_ID


@pytest.mark.parametrize(
    "whoami",
    [
        {},
        {"user": {}},
        {"user": {"id": OTHER_USER_ID}},
        {"user": {"membershipId": ""}},
        {"user": {"membershipId": "not-a-uuid"}},
        {"user": {"membershipId": USER_ID.upper()}},
        {"user": [USER_ID]},
        {"user": {"membershipId": 1}},
    ],
)
def test_user_id_rejects_an_identity_it_cannot_name(whoami: Any) -> None:
    with pytest.raises(OmniCreditCostError):
        credit_usage_user_id(whoami)


def test_reading_binds_the_period_and_the_requested_identity() -> None:
    client = FakeClient([usage_response(635.297481375)])
    observed = read_credit_usage(client, USER_ID)
    assert client.requests == [(USER_ID,)]
    assert observed == reading(635.297481375)


@pytest.mark.parametrize(
    "response",
    [
        {"periodStart": PERIOD_START_MS, "periodEnd": PERIOD_END_MS, "users": []},
        {
            "periodStart": PERIOD_START_MS,
            "periodEnd": PERIOD_END_MS,
            "users": [
                {"creditsUsed": 1.0, "userId": USER_ID},
                {"creditsUsed": 2.0, "userId": OTHER_USER_ID},
            ],
        },
        usage_response(1.0, user_id=OTHER_USER_ID),
        usage_response(-1.0),
        usage_response(float("nan")),
        usage_response(float("inf")),
        usage_response(True),
        {
            "periodEnd": PERIOD_END_MS,
            "users": [{"creditsUsed": 1.0, "userId": USER_ID}],
        },
        usage_response(1.0, period_start_ms=PERIOD_END_MS),
        {
            "periodStart": "1785542400000",
            "periodEnd": PERIOD_END_MS,
            "users": [{"creditsUsed": 1.0, "userId": USER_ID}],
        },
        [usage_response(1.0)],
    ],
)
def test_reading_rejects_a_response_it_cannot_attribute(response: Any) -> None:
    with pytest.raises(OmniCreditCostError):
        read_credit_usage(FakeClient([response]), USER_ID)


def test_reading_reports_a_transport_failure_as_a_cost_error() -> None:
    client = FakeClient([RuntimeError("Omni CLI request failed")])
    with pytest.raises(OmniCreditCostError):
        read_credit_usage(client, USER_ID)


def test_reading_requires_a_client_that_exposes_credit_usage() -> None:
    class WithoutCreditUsage:
        def whoami(self) -> dict[str, Any]:
            return {}

    with pytest.raises(OmniCreditCostError):
        read_credit_usage(WithoutCreditUsage(), USER_ID)


def test_delta_across_one_period_is_the_measured_cost() -> None:
    cost = resolve_attempt_cost(reading(635.0), reading(635.68390625))
    assert cost == AttemptCost(
        cost_usd=pytest.approx(0.68390625),
        cost_source=COST_SOURCE_CREDIT_USAGE_DELTA,
        cost_unavailable_reason=None,
    )


def test_a_zero_delta_is_measured_rather_than_unavailable() -> None:
    cost = resolve_attempt_cost(reading(635.0), reading(635.0))
    assert cost.cost_usd == 0.0
    assert cost.cost_source == COST_SOURCE_CREDIT_USAGE_DELTA


def test_a_bracket_spanning_the_period_rollover_records_no_number() -> None:
    cost = resolve_attempt_cost(
        reading(635.0), reading(0.5, period_start_ms=PERIOD_END_MS)
    )
    assert cost == unavailable_cost(COST_UNAVAILABLE_PERIOD_ROLLOVER)
    assert cost.cost_usd is None


def test_a_counter_that_moved_backwards_records_no_number() -> None:
    cost = resolve_attempt_cost(reading(635.0), reading(634.0))
    assert cost == unavailable_cost(COST_UNAVAILABLE_NONMONOTONIC)


def test_every_unavailable_reason_is_separable_from_the_job_api_case() -> None:
    reasons = {
        COST_UNAVAILABLE_JOB_API,
        COST_UNAVAILABLE_READ_FAILED,
        COST_UNAVAILABLE_PERIOD_ROLLOVER,
        COST_UNAVAILABLE_NONMONOTONIC,
    }
    assert len(reasons) == 4
    for reason in reasons:
        cost = unavailable_cost(reason)
        assert cost.cost_usd is None
        assert cost.cost_source == "unavailable"
        assert cost.cost_unavailable_reason == reason


def test_an_unconfigured_bracket_leaves_the_attempt_record_untouched() -> None:
    client = FakeClient([])
    probe = capture_with_cost(
        client=client, environment={}, capture=lambda: FakeProbe()
    )
    assert probe.cost is None
    assert client.requests == []


def test_a_configured_bracket_measures_one_attempt(tmp_path: Path) -> None:
    client = FakeClient([usage_response(635.0), usage_response(635.5)])
    probe = capture_with_cost(
        client=client,
        environment=enabled_environment(tmp_path),
        capture=lambda: FakeProbe(),
    )
    assert probe.cost == AttemptCost(
        cost_usd=pytest.approx(0.5),
        cost_source=COST_SOURCE_CREDIT_USAGE_DELTA,
        cost_unavailable_reason=None,
    )
    assert client.requests == [(USER_ID,), (USER_ID,)]


def test_the_pre_read_happens_before_the_job_is_submitted(tmp_path: Path) -> None:
    order: list[str] = []

    class OrderedClient(FakeClient):
        def credit_usage(self, user_ids: Sequence[str]) -> dict[str, Any]:
            order.append("credit-usage")
            return super().credit_usage(user_ids)

    def capture() -> FakeProbe:
        order.append("capture")
        return FakeProbe()

    client = OrderedClient([usage_response(1.0), usage_response(2.0)])
    capture_with_cost(
        client=client,
        environment=enabled_environment(tmp_path),
        capture=capture,
    )
    assert order == ["credit-usage", "capture", "credit-usage"]


def test_a_failed_pre_read_refuses_the_launch(tmp_path: Path) -> None:
    captured = False

    def capture() -> FakeProbe:
        nonlocal captured
        captured = True
        return FakeProbe()

    client = FakeClient([RuntimeError("Omni CLI request failed")])
    with pytest.raises(OmniCreditCostError):
        capture_with_cost(
            client=client,
            environment=enabled_environment(tmp_path),
            capture=capture,
        )
    assert not captured


def test_a_failed_post_read_keeps_the_attempt_and_names_the_failure(
    tmp_path: Path,
) -> None:
    client = FakeClient([usage_response(1.0), RuntimeError("read failed")])
    probe = capture_with_cost(
        client=client,
        environment=enabled_environment(tmp_path),
        capture=lambda: FakeProbe(),
    )
    assert probe.cost == unavailable_cost(COST_UNAVAILABLE_READ_FAILED)


def test_a_second_attempt_on_one_identity_cannot_run_concurrently(
    tmp_path: Path,
) -> None:
    environment = enabled_environment(tmp_path)
    outer = FakeClient([usage_response(1.0), usage_response(2.0)])
    inner = FakeClient([usage_response(1.0), usage_response(2.0)])

    def nested() -> FakeProbe:
        with pytest.raises(OmniCreditCostError):
            capture_with_cost(
                client=inner,
                environment=environment,
                capture=lambda: FakeProbe(),
            )
        return FakeProbe()

    capture_with_cost(client=outer, environment=environment, capture=nested)
    assert inner.requests == []


def test_the_lease_is_released_for_the_next_serial_attempt(tmp_path: Path) -> None:
    environment = enabled_environment(tmp_path)
    for _ in range(2):
        client = FakeClient([usage_response(1.0), usage_response(2.0)])
        probe = capture_with_cost(
            client=client,
            environment=environment,
            capture=lambda: FakeProbe(),
        )
        assert probe.cost is not None
        assert probe.cost.cost_source == COST_SOURCE_CREDIT_USAGE_DELTA


def test_a_failing_capture_still_releases_the_lease(tmp_path: Path) -> None:
    environment = enabled_environment(tmp_path)

    def failing() -> FakeProbe:
        raise RuntimeError("capture failed")

    with pytest.raises(RuntimeError, match="capture failed"):
        capture_with_cost(
            client=FakeClient([usage_response(1.0)]),
            environment=environment,
            capture=failing,
        )
    probe = capture_with_cost(
        client=FakeClient([usage_response(1.0), usage_response(2.0)]),
        environment=environment,
        capture=lambda: FakeProbe(),
    )
    assert probe.cost is not None


def test_the_lease_file_is_private_to_its_owner(tmp_path: Path) -> None:
    capture_with_cost(
        client=FakeClient([usage_response(1.0), usage_response(2.0)]),
        environment=enabled_environment(tmp_path),
        capture=lambda: FakeProbe(),
    )
    leases = sorted(tmp_path.iterdir())
    assert len(leases) == 1
    assert leases[0].stat().st_mode & 0o777 == 0o600
    assert USER_ID not in leases[0].name


@pytest.mark.parametrize("value", ["", "   ", "relative/path"])
def test_a_lease_directory_that_is_not_an_absolute_path_is_refused(
    value: str,
) -> None:
    with pytest.raises(OmniCreditCostError):
        capture_with_cost(
            client=FakeClient([]),
            environment={LEASE_DIRECTORY_VARIABLE: value},
            capture=lambda: FakeProbe(),
        )


def test_a_missing_lease_directory_is_refused_rather_than_created(
    tmp_path: Path,
) -> None:
    absent = tmp_path / "absent"
    with pytest.raises(OmniCreditCostError):
        capture_with_cost(
            client=FakeClient([]),
            environment={LEASE_DIRECTORY_VARIABLE: str(absent)},
            capture=lambda: FakeProbe(),
        )
    assert not absent.exists()


def test_a_symlinked_lease_directory_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(OmniCreditCostError):
        capture_with_cost(
            client=FakeClient([]),
            environment={LEASE_DIRECTORY_VARIABLE: str(link)},
            capture=lambda: FakeProbe(),
        )


def test_the_captured_august_evidence_parses_as_one_reading() -> None:
    evidence = json.loads(
        Path("experiments/analysis/omni-credit-usage-2026-08.json").read_text()
    )
    observed = read_credit_usage(
        FakeClient([evidence["raw_response"]]),
        evidence["raw_response"]["users"][0]["userId"],
    )
    assert observed.credits_used == 635.297481375
    assert observed.period_start_ms < observed.period_end_ms


def test_the_capture_vocabulary_admits_a_credit_delta_only_for_cost() -> None:
    """Widening the source vocabulary must not let tokens claim a credit delta."""
    measured = {
        "cost_source": COST_SOURCE_CREDIT_USAGE_DELTA,
        "cost_usd": 0.5,
        "token_source": "provider_reported",
        "token_usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }

    _validate_sources(measured)

    with pytest.raises(AutoresearchError, match="token_source must be"):
        _validate_sources({**measured, "token_source": COST_SOURCE_CREDIT_USAGE_DELTA})
    with pytest.raises(AutoresearchError, match="cost_source must disclose"):
        _validate_sources({**measured, "cost_usd": None})


def _c4_observation(
    *, cost_usd: float | None, reason: str | None
) -> AttemptObservation:
    return AttemptObservation(
        attempt=BaselineAttempt(
            condition="C4",
            database="synthetic_db",
            instance_id="q-001",
            repetition=1,
            run_id="run-1",
        ),
        cost_usd=cost_usd,
        database_query_count=1,
        generation_outcome="answered",
        latency_ms=1_000.0,
        retry_count=None,
        terminal_failure_class=None,
        token_count=None,
        tool_call_count=None,
        validation_attempt_count=None,
        cost_reservation_usd=_C4_BUDGET.attempt_cost_ceiling_usd,
        budget_policy_sha256=_C4_BUDGET.sha256,
        cost_unavailable_reason=reason,
    )


@pytest.mark.parametrize(
    "reason",
    [
        COST_UNAVAILABLE_JOB_API,
        COST_UNAVAILABLE_NONMONOTONIC,
        COST_UNAVAILABLE_PERIOD_ROLLOVER,
        COST_UNAVAILABLE_READ_FAILED,
    ],
)
def test_budget_accounting_accepts_every_named_cost_unavailable_reason(
    reason: str,
) -> None:
    """A bracket that could not measure must not fail the batch's cost accounting."""
    cost = _hard_budget_cost(_c4_observation(cost_usd=None, reason=reason), _C4_BUDGET)

    assert cost == _C4_BUDGET.attempt_cost_ceiling_usd


def test_budget_accounting_still_rejects_an_unexplained_null_cost() -> None:
    with pytest.raises(BaselineBatchError, match="unavailable cost reason"):
        _hard_budget_cost(
            _c4_observation(cost_usd=None, reason="invented_reason"), _C4_BUDGET
        )


def test_budget_accounting_charges_a_measured_c4_delta() -> None:
    cost = _hard_budget_cost(_c4_observation(cost_usd=0.25, reason=None), _C4_BUDGET)

    assert cost == 0.25


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (reading(1.0), None),
        (None, reading(1.0)),
        (
            reading(1.0),
            CreditUsageReading(
                user_id=OTHER_USER_ID,
                credits_used=2.0,
                period_start_ms=PERIOD_START_MS,
                period_end_ms=PERIOD_END_MS,
            ),
        ),
    ],
)
def test_a_delta_refuses_readings_it_cannot_pair(before: object, after: object) -> None:
    with pytest.raises(OmniCreditCostError):
        resolve_attempt_cost(before, after)  # type: ignore[arg-type]


def test_a_bracket_refuses_a_client_whose_identity_is_unusable(
    tmp_path: Path,
) -> None:
    class NoIdentity:
        def credit_usage(self, user_ids: Sequence[str]) -> dict[str, Any]:
            raise AssertionError("credit usage must not be read without an identity")

    class FailingIdentity(NoIdentity):
        def whoami(self) -> dict[str, Any]:
            raise RuntimeError("identity unavailable")

    class MalformedIdentity(NoIdentity):
        def whoami(self) -> list[str]:
            return [USER_ID]

    for client in (NoIdentity(), FailingIdentity(), MalformedIdentity()):
        with pytest.raises(OmniCreditCostError):
            capture_with_cost(
                client=client,
                environment=enabled_environment(tmp_path),
                capture=lambda: FakeProbe(),
            )

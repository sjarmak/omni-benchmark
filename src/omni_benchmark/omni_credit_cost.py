"""Measure one governed attempt's dollar cost from bracketed AI credit usage.

The Omni job API exposes no cost: neither ``ai job-status`` nor ``ai job-result``
carries one, so every governed attempt has recorded ``cost_usd`` as unavailable.
The credit endpoint does expose spend, but only as one cumulative figure per user
per billing period, so a single attempt's cost is a difference between two reads
rather than a reported value.

That difference is only meaningful under conditions the counter cannot express,
so each one is enforced here rather than assumed:

- Sole consumer and serialization. Any other use of the identity inside the
  bracket lands in the same counter, so the bracket holds an exclusive advisory
  lease on the membership id for its whole duration and refuses to start without
  it. The lease covers other harness processes; traffic from outside the harness
  on the same identity remains undetectable and would inflate a delta.
- Period boundary. A bracket spanning the monthly rollover would see the counter
  reset and compute a negative delta, so a pair of reads reporting different
  period bounds records no number instead of a wrong one.
- Read failure. A post-read that fails records a reason of its own so it never
  reads as the pre-existing "the job API exposes no cost" case.

Bracketing is opt-in. With no lease directory configured the attempt record is
byte-for-byte what it was before this module existed.
"""

from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import math
import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

LEASE_DIRECTORY_VARIABLE = "OMNI_COST_BRACKET_LEASE_DIR"

COST_SOURCE_UNAVAILABLE = "unavailable"
COST_SOURCE_CREDIT_USAGE_DELTA = "credit_usage_delta"

COST_UNAVAILABLE_JOB_API = "omni_job_api_does_not_expose_cost"
COST_UNAVAILABLE_READ_FAILED = "credit_usage_read_failed"
COST_UNAVAILABLE_PERIOD_ROLLOVER = "credit_usage_period_rollover"
COST_UNAVAILABLE_NONMONOTONIC = "credit_usage_nonmonotonic"

MEMBERSHIP_ID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)

Probe = TypeVar("Probe")


class OmniCreditCostError(RuntimeError):
    """Raised when an attempt's cost cannot be measured under stated conditions."""


@dataclass(frozen=True)
class AttemptCost:
    """One attempt's cost and the provenance of that number or its absence."""

    cost_usd: float | None
    cost_source: str
    cost_unavailable_reason: str | None


@dataclass(frozen=True)
class CreditUsageReading:
    """One cumulative credit counter bound to the period it was read in."""

    user_id: str
    credits_used: float
    period_start_ms: int
    period_end_ms: int


def unavailable_cost(reason: str) -> AttemptCost:
    """Name why an attempt carries no measured cost without inventing one."""
    if not isinstance(reason, str) or not reason:
        raise OmniCreditCostError("cost unavailable reason must be a non-empty string")
    return AttemptCost(
        cost_usd=None,
        cost_source=COST_SOURCE_UNAVAILABLE,
        cost_unavailable_reason=reason,
    )


def credit_usage_user_id(whoami: Mapping[str, Any]) -> str:
    """Read the membership id the credit endpoint bills, from the live identity."""
    user = whoami.get("user") if isinstance(whoami, Mapping) else None
    membership = user.get("membershipId") if isinstance(user, Mapping) else None
    if (
        not isinstance(membership, str)
        or MEMBERSHIP_ID_PATTERN.fullmatch(membership) is None
    ):
        raise OmniCreditCostError("Omni identity exposes no usable membership id")
    return membership


def read_credit_usage(client: Any, user_id: str) -> CreditUsageReading:
    """Read one identity's cumulative period usage, or refuse to interpret it."""
    identity = _validated_user_id(user_id)
    reader = getattr(client, "credit_usage", None)
    if not callable(reader):
        raise OmniCreditCostError("Omni client does not expose credit usage")
    try:
        response = reader([identity])
    except Exception as error:
        raise OmniCreditCostError("Omni credit usage could not be read") from error
    return _reading(response, identity)


def resolve_attempt_cost(
    before: CreditUsageReading, after: CreditUsageReading
) -> AttemptCost:
    """Difference two readings, or say which condition made the delta meaningless."""
    if type(before) is not CreditUsageReading or type(after) is not CreditUsageReading:
        raise OmniCreditCostError("credit usage readings are invalid")
    if before.user_id != after.user_id:
        raise OmniCreditCostError("credit usage readings name different identities")
    if (
        before.period_start_ms != after.period_start_ms
        or before.period_end_ms != after.period_end_ms
    ):
        return unavailable_cost(COST_UNAVAILABLE_PERIOD_ROLLOVER)
    delta = after.credits_used - before.credits_used
    if delta < 0:
        return unavailable_cost(COST_UNAVAILABLE_NONMONOTONIC)
    return AttemptCost(
        cost_usd=float(delta),
        cost_source=COST_SOURCE_CREDIT_USAGE_DELTA,
        cost_unavailable_reason=None,
    )


def capture_with_cost(
    *,
    client: Any,
    environment: Mapping[str, str],
    capture: Callable[[], Probe],
) -> Probe:
    """Run one capture inside a credit bracket when the operator configured one."""
    directory = _lease_directory(environment)
    if directory is None:
        return capture()
    user_id = credit_usage_user_id(_whoami(client))
    with _identity_lease(directory, user_id):
        before = read_credit_usage(client, user_id)
        probe = capture()
        return dataclasses.replace(probe, cost=_measured_cost(client, user_id, before))


def _measured_cost(
    client: Any, user_id: str, before: CreditUsageReading
) -> AttemptCost:
    try:
        after = read_credit_usage(client, user_id)
    except OmniCreditCostError:
        return unavailable_cost(COST_UNAVAILABLE_READ_FAILED)
    return resolve_attempt_cost(before, after)


def _whoami(client: Any) -> Mapping[str, Any]:
    reader = getattr(client, "whoami", None)
    if not callable(reader):
        raise OmniCreditCostError("Omni client does not expose an identity")
    try:
        response = reader()
    except Exception as error:
        raise OmniCreditCostError("Omni identity could not be read") from error
    if not isinstance(response, Mapping):
        raise OmniCreditCostError("Omni identity response is malformed")
    return response


@contextmanager
def _identity_lease(directory: Path, user_id: str) -> Iterator[None]:
    """Hold one exclusive advisory lease on a membership id, or refuse to run."""
    path = directory / f"omni-credit-{hashlib.sha256(user_id.encode()).hexdigest()}"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise OmniCreditCostError(
                "another run holds the Omni identity; a bracketed cost cannot be "
                "attributed to one attempt"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _lease_directory(environment: Mapping[str, str]) -> Path | None:
    value = environment.get(LEASE_DIRECTORY_VARIABLE)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise OmniCreditCostError(f"{LEASE_DIRECTORY_VARIABLE} must name a directory")
    directory = Path(value.strip())
    if (
        not directory.is_absolute()
        or directory.is_symlink()
        or not directory.is_dir()
        or directory.absolute() != directory.resolve()
    ):
        raise OmniCreditCostError(
            f"{LEASE_DIRECTORY_VARIABLE} must be an existing absolute directory "
            "that is not a symbolic link"
        )
    return directory


def _validated_user_id(value: object) -> str:
    if not isinstance(value, str) or MEMBERSHIP_ID_PATTERN.fullmatch(value) is None:
        raise OmniCreditCostError("credit usage identity must be a membership id")
    return value


def _reading(response: object, user_id: str) -> CreditUsageReading:
    if not isinstance(response, Mapping):
        raise OmniCreditCostError("Omni credit usage response must be an object")
    start = _period_bound(response.get("periodStart"), "periodStart")
    end = _period_bound(response.get("periodEnd"), "periodEnd")
    if start >= end:
        raise OmniCreditCostError("Omni credit usage period bounds are not ordered")
    users = response.get("users")
    if not isinstance(users, Sequence) or isinstance(users, (str, bytes)):
        raise OmniCreditCostError("Omni credit usage must list users")
    if len(users) != 1:
        raise OmniCreditCostError("Omni credit usage must name exactly one user")
    user = users[0]
    if not isinstance(user, Mapping) or user.get("userId") != user_id:
        raise OmniCreditCostError("Omni credit usage names a different identity")
    return CreditUsageReading(
        user_id=user_id,
        credits_used=_credits(user.get("creditsUsed")),
        period_start_ms=start,
        period_end_ms=end,
    )


def _period_bound(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OmniCreditCostError(
            f"Omni credit usage {name} must be epoch milliseconds"
        )
    return value


def _credits(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise OmniCreditCostError(
            "Omni credit usage must report a non-negative finite credit total"
        )
    return float(value)

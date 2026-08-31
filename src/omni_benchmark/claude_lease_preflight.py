"""Refuse to launch when a leased OAuth identity can change mid-attempt.

The direct transport pins its config directory and asserts the pinned identity is
unchanged for the whole invocation. Two clocks can break that assertion after a
launch has already been judged healthy: the access token can expire, and an
external owner of the same identity can rotate it. Both are knowable before any
attempt starts, so both belong in a launch gate rather than in a failure
classification afterwards.

Slot-to-source correspondence is deliberately not checked here. Which filesystem
holds the authoritative copy of an identity is a deployment fact, not a property
of the evaluated system, and encoding it would couple the harness to one machine.
That check belongs to the operator tooling that builds the leases.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

_CREDENTIAL_NAME = ".credentials.json"
_OAUTH_KEY = "claudeAiOauth"
_EXPIRY_KEY = "expiresAt"


class ClaudeLeasePreflightError(ValueError):
    """Raised when a leased identity cannot be guaranteed stable for an attempt."""


def _slot_identity(config_directory: Path) -> str:
    """Name a slot without publishing its path."""
    return hashlib.sha256(str(config_directory).encode()).hexdigest()


def _expiry_seconds(config_directory: Path) -> float:
    """Read one slot's access-token expiry as epoch seconds."""
    path = config_directory / _CREDENTIAL_NAME
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ClaudeLeasePreflightError(
            f"slot {_slot_identity(config_directory)} has no readable credential"
        ) from error
    if not isinstance(payload, dict):
        raise ClaudeLeasePreflightError(
            f"slot {_slot_identity(config_directory)} has no readable credential"
        )
    oauth = payload.get(_OAUTH_KEY, payload)
    expiry = oauth.get(_EXPIRY_KEY) if isinstance(oauth, dict) else None
    if not isinstance(expiry, (int, float)) or isinstance(expiry, bool) or expiry <= 0:
        raise ClaudeLeasePreflightError(
            f"slot {_slot_identity(config_directory)} has no usable token expiry; "
            "the profile is logged out or was force-expired"
        )
    return float(expiry) / 1000.0


def lease_window_report(
    config_directories: tuple[Path, ...],
    *,
    attempt_seconds: float,
    identity_stable_until: float | None = None,
    now: float | None = None,
) -> dict[str, object]:
    """Describe per-slot headroom without exposing paths or token material."""
    moment = time.time() if now is None else now
    slots = [
        {
            "slot_sha256": _slot_identity(directory),
            "headroom_seconds": _expiry_seconds(directory) - moment,
            "satisfies_attempt": _expiry_seconds(directory) - moment > attempt_seconds,
        }
        for directory in config_directories
    ]
    boundary = None if identity_stable_until is None else identity_stable_until - moment
    return {
        "attempt_seconds": attempt_seconds,
        "rotation_boundary_seconds": boundary,
        "slots": slots,
    }


def verify_lease_window(
    config_directories: tuple[Path, ...],
    *,
    attempt_seconds: float,
    identity_stable_until: float | None = None,
    now: float | None = None,
) -> None:
    """Raise unless every leased slot outlives the longest attempt it may serve."""
    if not config_directories:
        raise ClaudeLeasePreflightError("at least one Claude OAuth slot is required")
    if attempt_seconds <= 0:
        raise ClaudeLeasePreflightError("attempt duration must be positive")
    moment = time.time() if now is None else now

    failures: list[str] = []
    for directory in config_directories:
        headroom = _expiry_seconds(directory) - moment
        if headroom <= attempt_seconds:
            failures.append(
                f"slot {_slot_identity(directory)} expires in {headroom:.0f}s, "
                f"inside the {attempt_seconds:.0f}s attempt ceiling"
            )
    if failures:
        raise ClaudeLeasePreflightError("; ".join(failures))

    if identity_stable_until is not None:
        boundary = identity_stable_until - moment
        if boundary <= attempt_seconds:
            raise ClaudeLeasePreflightError(
                f"a scheduled rotation lands in {boundary:.0f}s, inside the "
                f"{attempt_seconds:.0f}s attempt ceiling; every leased identity can "
                "change mid-attempt"
            )

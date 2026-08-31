from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from omni_benchmark.claude_lease_preflight import (
    ClaudeLeasePreflightError,
    lease_window_report,
    verify_lease_window,
)

NOW = 1_700_000_000.0
HOUR = 3600.0


def _slot(root: Path, name: str, *, expires_at_seconds: float | None) -> Path:
    directory = root / name
    directory.mkdir(mode=0o700)
    payload: dict[str, object] = {
        "claudeAiOauth": {"accessToken": "a", "refreshToken": "r"}
    }
    if expires_at_seconds is not None:
        payload["claudeAiOauth"]["expiresAt"] = int(expires_at_seconds * 1000)  # type: ignore[index]
    (directory / ".credentials.json").write_text(json.dumps(payload))
    (directory / ".credentials.json").chmod(0o600)
    return directory


def test_accepts_slots_with_headroom_beyond_the_attempt(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=NOW + 4 * HOUR)
    verify_lease_window((slot,), attempt_seconds=HOUR, now=NOW)


def test_rejects_slot_whose_token_expires_inside_the_attempt(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=NOW + 0.5 * HOUR)
    with pytest.raises(ClaudeLeasePreflightError) as error:
        verify_lease_window((slot,), attempt_seconds=HOUR, now=NOW)
    assert "expires" in str(error.value)


def test_rejects_already_expired_slot(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=NOW - HOUR)
    with pytest.raises(ClaudeLeasePreflightError):
        verify_lease_window((slot,), attempt_seconds=HOUR, now=NOW)


def test_rejects_slot_without_a_usable_expiry(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=None)
    with pytest.raises(ClaudeLeasePreflightError) as error:
        verify_lease_window((slot,), attempt_seconds=HOUR, now=NOW)
    assert "expiry" in str(error.value)


def test_rejects_slot_with_zero_expiry_from_a_logged_out_home(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=0)
    with pytest.raises(ClaudeLeasePreflightError):
        verify_lease_window((slot,), attempt_seconds=HOUR, now=NOW)


def test_rejects_unreadable_credentials(tmp_path: Path) -> None:
    directory = tmp_path / "a"
    directory.mkdir(mode=0o700)
    with pytest.raises(ClaudeLeasePreflightError) as error:
        verify_lease_window((directory,), attempt_seconds=HOUR, now=NOW)
    assert "credential" in str(error.value)


def test_rejects_rotation_boundary_inside_the_attempt(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=NOW + 8 * HOUR)
    with pytest.raises(ClaudeLeasePreflightError) as error:
        verify_lease_window(
            (slot,),
            attempt_seconds=2 * HOUR,
            identity_stable_until=NOW + HOUR,
            now=NOW,
        )
    assert "rotat" in str(error.value)


def test_accepts_rotation_boundary_beyond_the_attempt(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=NOW + 8 * HOUR)
    verify_lease_window(
        (slot,),
        attempt_seconds=HOUR,
        identity_stable_until=NOW + 6 * HOUR,
        now=NOW,
    )


def test_boundary_is_checked_even_when_every_token_has_headroom(tmp_path: Path) -> None:
    slots = (
        _slot(tmp_path, "a", expires_at_seconds=NOW + 8 * HOUR),
        _slot(tmp_path, "b", expires_at_seconds=NOW + 8 * HOUR),
    )
    with pytest.raises(ClaudeLeasePreflightError):
        verify_lease_window(
            slots, attempt_seconds=2 * HOUR, identity_stable_until=NOW + HOUR, now=NOW
        )


def test_reports_every_failing_slot_not_only_the_first(tmp_path: Path) -> None:
    slots = (
        _slot(tmp_path, "a", expires_at_seconds=NOW + 0.5 * HOUR),
        _slot(tmp_path, "b", expires_at_seconds=NOW + 8 * HOUR),
        _slot(tmp_path, "c", expires_at_seconds=NOW - HOUR),
    )
    with pytest.raises(ClaudeLeasePreflightError) as error:
        verify_lease_window(slots, attempt_seconds=HOUR, now=NOW)
    message = str(error.value)
    assert message.count("slot ") >= 2


def test_message_never_leaks_the_slot_path_or_token(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "secret-profile-name", expires_at_seconds=NOW - HOUR)
    with pytest.raises(ClaudeLeasePreflightError) as error:
        verify_lease_window((slot,), attempt_seconds=HOUR, now=NOW)
    message = str(error.value)
    assert "secret-profile-name" not in message
    assert str(slot) not in message


def test_requires_at_least_one_slot() -> None:
    with pytest.raises(ClaudeLeasePreflightError):
        verify_lease_window((), attempt_seconds=HOUR, now=NOW)


def test_rejects_non_positive_attempt_duration(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=NOW + 8 * HOUR)
    with pytest.raises(ClaudeLeasePreflightError):
        verify_lease_window((slot,), attempt_seconds=0.0, now=NOW)


def test_report_exposes_headroom_without_secrets(tmp_path: Path) -> None:
    slot = _slot(tmp_path, "a", expires_at_seconds=NOW + 2 * HOUR)
    report = lease_window_report((slot,), attempt_seconds=HOUR, now=NOW)
    entry = report["slots"][0]
    assert entry["headroom_seconds"] == pytest.approx(2 * HOUR)
    assert entry["satisfies_attempt"] is True
    assert "path" not in entry
    assert len(entry["slot_sha256"]) == 64


def test_live_launch_is_refused_when_a_slot_expires_inside_an_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate must sit in the launch path, not only in the helper."""
    import omni_benchmark.baseline_batch_cli as cli

    slot = _slot(tmp_path, "a", expires_at_seconds=time.time() + 0.25 * HOUR)
    captured: dict[str, object] = {}

    def _fail(*_args: object, **kwargs: object) -> None:
        captured["reached_execution"] = True

    monkeypatch.setattr(cli, "_execute_live", _fail)
    arguments = argparse.Namespace(
        execute_live_baseline=True,
        execute_live_direct_baseline=False,
        execute_live_direct_concurrency_canary=False,
        subprocess_timeout_seconds=HOUR,
        identity_stable_until=None,
    )
    plan = SimpleNamespace(claude_config_directories=(slot,))
    with pytest.raises(cli.BaselineBatchError) as error:
        cli._verify_lease_window(arguments, plan)
    assert "lease preflight failed" in str(error.value)
    assert "reached_execution" not in captured


def test_launch_gate_rejects_a_naive_stable_until(tmp_path: Path) -> None:
    import omni_benchmark.baseline_batch_cli as cli

    with pytest.raises(cli.BaselineBatchError) as error:
        cli._identity_stable_until("2026-08-28T23:00:00")
    assert "UTC offset" in str(error.value)


def test_launch_gate_rejects_unparseable_stable_until() -> None:
    import omni_benchmark.baseline_batch_cli as cli

    with pytest.raises(cli.BaselineBatchError):
        cli._identity_stable_until("19:00 tonight")


def test_launch_gate_accepts_an_absent_stable_until() -> None:
    import omni_benchmark.baseline_batch_cli as cli

    assert cli._identity_stable_until(None) is None


def test_launch_gate_parses_an_offset_aware_stable_until() -> None:
    import omni_benchmark.baseline_batch_cli as cli

    assert cli._identity_stable_until("2026-08-28T23:00:00+00:00") == pytest.approx(
        1787958000.0
    )


def test_dispatch_timeout_default_bounds_a_stuck_attempt_without_failing_slow_ones() -> (
    None
):
    """Both live entrypoints bound a child at 900s.

    The slowest attempt observed on the 16-database continuation was 156s, so 900s
    keeps a wide margin for slower databases while capping what one wedged attempt
    can hold a slot for. It also halves the headroom the lease preflight demands,
    since the attempt bound is what verify_lease_window compares tokens against.
    """
    import argparse

    from omni_benchmark import baseline_batch_cli, baseline_continuation_cli

    batch = baseline_batch_cli._parser()
    assert batch.get_default("subprocess_timeout_seconds") == 900.0

    # The continuation CLI defines its execution flags on subparsers, so read the
    # default from the function that installs them rather than the root parser.
    continuation = argparse.ArgumentParser()
    baseline_continuation_cli._execution_arguments(continuation)
    assert continuation.get_default("subprocess_timeout_seconds") == 900.0

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
from hypothesis import given, strategies as st

from omni_benchmark.telemetry_db.credit_readers import read_credits
from omni_benchmark.telemetry_db.generation_rows import ReaderError

PERIOD = "2026-08-01T00:00:00Z / 2026-09-01T00:00:00Z"


def _usage(**overrides: Any) -> dict[str, Any]:
    return {
        "api_endpoint": "https://example.omniapp.co",
        "captured_at_utc": "2026-08-31T19:00:27Z",
        "cli_command": "omni ai credit-usage-users-read",
        "credit_unit_usd": 1.0,
        "period_start_utc": "2026-08-01T00:00:00+00:00",
        "period_end_utc": "2026-09-01T00:00:00+00:00",
        "note": "captured before the rollover",
        "raw_response": {"users": [{"creditsUsed": 100.5}, {"creditsUsed": 9.5}]},
        **overrides,
    }


def _breakdown(**overrides: Any) -> dict[str, Any]:
    return {
        "period": PERIOD,
        "credits_used_usd": 110.0,
        "omni_routed_attempts_recorded": 50,
        "account_ai_conversations_in_period": 80,
        "unattributed_conversations": 30,
        "proportional_estimate_usd_per_omni_attempt": 2.2,
        "upper_bound_usd_per_omni_attempt": 3.0,
        "arms": [
            {"arm": "C5 dev-A (c5-dev-a-v4)", "omni_attempts": 30, "note": "tuned"},
            {"arm": "aborted pilots", "omni_attempts": 20, "note": "no records"},
        ],
        **overrides,
    }


def _scopes() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scopes": {
            "C5 dev-A (c5-dev-a-v4)": {"arm": "C5", "partition": "dev-a"},
            "aborted pilots": {"arm": None, "partition": None},
        },
    }


def _write(root: Path, usage: Any, breakdown: Any, scopes: Any) -> tuple[Path, Path]:
    analysis = root / "experiments" / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / "omni-credit-usage-2026-08.json").write_text(
        json.dumps(usage), encoding="utf-8"
    )
    if breakdown is not None:
        (analysis / "omni-credit-spend-breakdown-2026-08.json").write_text(
            json.dumps(breakdown), encoding="utf-8"
        )
    scopes_path = root / "credit_scopes.json"
    scopes_path.write_text(json.dumps(scopes), encoding="utf-8")
    return analysis, scopes_path


def _read(root: Path, **overrides: Any):
    usage = overrides.get("usage", _usage())
    breakdown = overrides.get("breakdown", _breakdown())
    scopes = overrides.get("scopes", _scopes())
    analysis, scopes_path = _write(root, usage, breakdown, scopes)
    return read_credits(analysis, repo_root=root, scopes_path=scopes_path)


def test_read_credits_records_the_measured_period_and_the_derived_arm_split(
    tmp_path: Path,
) -> None:
    batch = _read(tmp_path)
    (period,) = batch.rows["credit_period"]
    assert period.values["period_start"] == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert period.values["period_end"] == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert period.values["credits_used_usd"] == Decimal("110.0")
    assert period.values["basis"] == "measured_account_period"
    assert period.values["omni_routed_attempts_recorded"] == 50
    assert period.values["unattributed_conversations"] == 30
    costs = {row.values["scope"]: row.values for row in batch.rows["arm_cost"]}
    assert set(costs) == {"C5 dev-A (c5-dev-a-v4)", "aborted pilots"}
    tuned = costs["C5 dev-A (c5-dev-a-v4)"]
    assert (tuned["arm"], tuned["partition"]) == ("C5", "dev-a")
    assert tuned["basis"] == "proportional_estimate"
    assert tuned["omni_attempts"] == 30
    assert tuned["cost_usd"] == Decimal("66.0")
    assert tuned["cost_usd_upper"] == Decimal("90.0")
    pilots = costs["aborted pilots"]
    assert (pilots["arm"], pilots["partition"]) == (None, None)


def test_read_credits_hashes_both_artifacts_and_the_scope_mapping(
    tmp_path: Path,
) -> None:
    batch = _read(tmp_path)
    assert sorted(batch.manifests) == [
        "credit_scopes.json",
        "experiments/analysis/omni-credit-spend-breakdown-2026-08.json",
        "experiments/analysis/omni-credit-usage-2026-08.json",
    ]


def test_read_credits_without_a_breakdown_keeps_the_measured_period(
    tmp_path: Path,
) -> None:
    batch = _read(tmp_path, breakdown=None)
    assert len(batch.rows["credit_period"]) == 1
    assert batch.count("arm_cost") == 0
    assert batch.dropped["credit_period_without_spend_breakdown"] == 1


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("credits_used_usd", 12.0, "disagrees with the measured"),
        ("period", "2026-07-01T00:00:00Z / 2026-08-01T00:00:00Z", "period"),
        ("proportional_estimate_usd_per_omni_attempt", "cheap", "must be a number"),
        ("arms", [{"omni_attempts": 3}], "arm must be a non-empty string"),
        ("arms", [{"arm": "C5 dev-A (c5-dev-a-v4)"}], "omni_attempts"),
    ],
)
def test_read_credits_rejects_a_breakdown_that_does_not_fit(
    tmp_path: Path, field: str, value: Any, match: str
) -> None:
    with pytest.raises(ReaderError, match=match):
        _read(tmp_path, breakdown=_breakdown(**{field: value}))


def test_read_credits_rejects_an_unmapped_scope(tmp_path: Path) -> None:
    scopes = _scopes()
    del scopes["scopes"]["aborted pilots"]
    with pytest.raises(ReaderError, match="names no scope"):
        _read(tmp_path, scopes=scopes)


def test_read_credits_rejects_usage_that_is_not_a_credit_reading(
    tmp_path: Path,
) -> None:
    with pytest.raises(ReaderError, match="creditsUsed"):
        _read(tmp_path, usage=_usage(raw_response={"users": [{"creditsUsed": "x"}]}))
    with pytest.raises(ReaderError, match="credit_unit_usd"):
        _read(tmp_path, usage=_usage(credit_unit_usd=0))


def test_read_credits_over_an_empty_directory_reads_nothing(tmp_path: Path) -> None:
    analysis = tmp_path / "experiments" / "analysis"
    analysis.mkdir(parents=True)
    scopes_path = tmp_path / "credit_scopes.json"
    scopes_path.write_text(json.dumps(_scopes()), encoding="utf-8")
    batch = read_credits(analysis, repo_root=tmp_path, scopes_path=scopes_path)
    assert batch.count("credit_period") == 0
    assert batch.manifests == {
        "credit_scopes.json": batch.manifests["credit_scopes.json"]
    }


@given(
    counts=st.lists(st.integers(min_value=1, max_value=1000), min_size=1, max_size=8),
    cents=st.integers(min_value=1, max_value=100000),
)
def test_credit_allocation_conserves_period_spend(
    counts: list[int], cents: int
) -> None:
    rate = Decimal(cents) / 100
    total = sum(counts)
    measured = rate * total
    scopes = {
        str(index): {"arm": None, "partition": None} for index in range(len(counts))
    }
    usage = _usage(raw_response={"users": [{"creditsUsed": str(measured)}]})
    breakdown = _breakdown(
        credits_used_usd=str(measured),
        omni_routed_attempts_recorded=total,
        proportional_estimate_usd_per_omni_attempt=str(rate),
        upper_bound_usd_per_omni_attempt=str(rate * 2),
        arms=[
            {"arm": str(index), "omni_attempts": count}
            for index, count in enumerate(counts)
        ],
    )
    with TemporaryDirectory() as directory:
        batch = _read(
            Path(directory), usage=usage, breakdown=breakdown, scopes={"scopes": scopes}
        )
    assert sum(row.values["cost_usd"] for row in batch.rows["arm_cost"]) == measured
    assert (
        sum(row.values["cost_usd_upper"] for row in batch.rows["arm_cost"])
        == measured * 2
    )
    assert batch.rows["credit_period"][0].values["credits_used_usd"] == measured


def test_read_credits_rejects_a_breakdown_without_its_usage_capture(
    tmp_path: Path,
) -> None:
    analysis, scopes_path = _write(tmp_path, _usage(), _breakdown(), _scopes())
    (analysis / "omni-credit-usage-2026-08.json").unlink()
    with pytest.raises(ReaderError, match="has no matching credit usage"):
        read_credits(analysis, repo_root=tmp_path, scopes_path=scopes_path)

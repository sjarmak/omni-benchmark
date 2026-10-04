from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .generation_rows import ReaderError, as_integer, parse_timestamp
from .rows import Row
from .sources import BatchBuilder, SourceBatch, load_json_object

USAGE_PREFIX = "omni-credit-usage-"
BREAKDOWN_PREFIX = "omni-credit-spend-breakdown-"
MEASURED_BASIS = "measured_account_period"
ESTIMATE_BASIS = "proportional_estimate"
NO_BREAKDOWN = "credit_period_without_spend_breakdown"

__all__ = ["read_credits"]


def read_credits(
    analysis_dir: Path, *, repo_root: Path, scopes_path: Path
) -> SourceBatch:
    builder = BatchBuilder("credits", repo_root)
    builder.manifest(scopes_path)
    scopes = _read_scopes(scopes_path)
    for breakdown_path in sorted(analysis_dir.glob(f"{BREAKDOWN_PREFIX}*.json")):
        suffix = breakdown_path.name[len(BREAKDOWN_PREFIX) : -len(".json")]
        usage_path = analysis_dir / f"{USAGE_PREFIX}{suffix}.json"
        if not usage_path.is_file():
            raise ReaderError(f"{breakdown_path.name} has no matching credit usage")
    for usage_path in sorted(analysis_dir.glob(f"{USAGE_PREFIX}*.json")):
        suffix = usage_path.name[len(USAGE_PREFIX) : -len(".json")]
        _read_period(usage_path, suffix, builder=builder, scopes=scopes)
    return builder.freeze()


def _read_period(
    usage_path: Path,
    suffix: str,
    *,
    builder: BatchBuilder,
    scopes: Mapping[str, Mapping[str, str | None]],
) -> None:
    digest = builder.manifest(usage_path)
    usage = load_json_object(usage_path)
    context = f"credit usage {usage_path.name}"
    period_start = _required_timestamp(usage.get("period_start_utc"), context)
    period_end = _required_timestamp(usage.get("period_end_utc"), context)
    unit = _decimal(usage.get("credit_unit_usd"), f"{context}: credit_unit_usd")
    if unit <= 0:
        raise ReaderError(f"{context}: credit_unit_usd must be positive")
    measured = _credits_used(usage, context) * unit
    breakdown_path = usage_path.parent / f"{BREAKDOWN_PREFIX}{suffix}.json"
    if not breakdown_path.exists():
        builder.add(
            Row(
                "credit_period",
                {
                    "period_start": period_start,
                    "period_end": period_end,
                    "credits_used_usd": measured,
                    "credit_unit_usd": unit,
                    "basis": MEASURED_BASIS,
                    "captured_at": parse_timestamp(
                        usage.get("captured_at_utc"), context
                    ),
                    "source_artifact": usage_path.name,
                    "source_artifact_sha256": digest,
                    "note": _text(usage.get("note")),
                },
            )
        )
        builder.drop(NO_BREAKDOWN)
        return
    breakdown_digest = builder.manifest(breakdown_path)
    breakdown = load_json_object(breakdown_path)
    breakdown_context = f"credit spend breakdown {breakdown_path.name}"
    _check_period(breakdown, period_start, period_end, breakdown_context)
    stated = _decimal(
        breakdown.get("credits_used_usd"), f"{breakdown_context}: credits_used_usd"
    )
    if stated != measured:
        raise ReaderError(
            f"{breakdown_context}: credits_used_usd {stated} disagrees with the "
            f"measured {measured} in {usage_path.name}"
        )
    builder.add(
        Row(
            "credit_period",
            {
                "period_start": period_start,
                "period_end": period_end,
                "credits_used_usd": measured,
                "credit_unit_usd": unit,
                "basis": MEASURED_BASIS,
                "omni_routed_attempts_recorded": as_integer(
                    breakdown.get("omni_routed_attempts_recorded"), breakdown_context
                ),
                "ai_conversations": as_integer(
                    breakdown.get("account_ai_conversations_in_period"),
                    breakdown_context,
                ),
                "unattributed_conversations": as_integer(
                    breakdown.get("unattributed_conversations"), breakdown_context
                ),
                "captured_at": parse_timestamp(usage.get("captured_at_utc"), context),
                "source_artifact": usage_path.name,
                "source_artifact_sha256": digest,
                "note": _text(usage.get("note")),
            },
        )
    )
    per_attempt = _decimal(
        breakdown.get("proportional_estimate_usd_per_omni_attempt"),
        f"{breakdown_context}: proportional_estimate_usd_per_omni_attempt",
    )
    upper = _decimal(
        breakdown.get("upper_bound_usd_per_omni_attempt"),
        f"{breakdown_context}: upper_bound_usd_per_omni_attempt",
    )
    for entry in _entries(breakdown, breakdown_context):
        builder.add(
            _arm_cost_row(
                entry,
                period_start=period_start,
                per_attempt=per_attempt,
                upper=upper,
                scopes=scopes,
                artifact=breakdown_path.name,
                digest=breakdown_digest,
                context=breakdown_context,
            )
        )


def _arm_cost_row(
    entry: Mapping[str, Any],
    *,
    period_start: Any,
    per_attempt: Decimal,
    upper: Decimal,
    scopes: Mapping[str, Mapping[str, str | None]],
    artifact: str,
    digest: str,
    context: str,
) -> Row:
    scope = entry.get("arm")
    if not isinstance(scope, str) or not scope.strip():
        raise ReaderError(f"{context}: arm must be a non-empty string")
    mapped = scopes.get(scope)
    if mapped is None:
        raise ReaderError(f"{context}: {scope!r} names no scope in the scope mapping")
    attempts = as_integer(entry.get("omni_attempts"), f"{context}: {scope}")
    if attempts is None:
        raise ReaderError(f"{context}: {scope!r} has no omni_attempts")
    count = Decimal(attempts)
    return Row(
        "arm_cost",
        {
            "period_start": period_start,
            "scope": scope,
            "arm": mapped["arm"],
            "partition": mapped["partition"],
            "basis": ESTIMATE_BASIS,
            "omni_attempts": attempts,
            "usd_per_attempt": per_attempt,
            "usd_per_attempt_upper": upper,
            "cost_usd": per_attempt * count,
            "cost_usd_upper": upper * count,
            "source_artifact": artifact,
            "source_artifact_sha256": digest,
            "note": _text(entry.get("note")),
        },
    )


def _read_scopes(path: Path) -> dict[str, Mapping[str, str | None]]:
    document = load_json_object(path)
    scopes = document.get("scopes")
    if not isinstance(scopes, dict):
        raise ReaderError(f"{path}: scopes must be a JSON object")
    mapping: dict[str, Mapping[str, str | None]] = {}
    for scope, value in scopes.items():
        if not isinstance(value, dict) or set(value) - {"arm", "partition"}:
            raise ReaderError(f"{path}: scope {scope!r} must name arm and partition")
        mapping[scope] = {
            "arm": _text(value.get("arm")),
            "partition": _text(value.get("partition")),
        }
    return mapping


def _entries(
    breakdown: Mapping[str, Any], context: str
) -> tuple[Mapping[str, Any], ...]:
    arms = breakdown.get("arms")
    if not isinstance(arms, list):
        raise ReaderError(f"{context}: arms must be a JSON array")
    for entry in arms:
        if not isinstance(entry, dict):
            raise ReaderError(f"{context}: every arms entry must be a JSON object")
    return tuple(arms)


def _check_period(
    breakdown: Mapping[str, Any], start: Any, end: Any, context: str
) -> None:
    period = breakdown.get("period")
    if not isinstance(period, str) or "/" not in period:
        raise ReaderError(f"{context}: period must read '<start> / <end>'")
    stated_start, _, stated_end = period.partition("/")
    if (
        parse_timestamp(stated_start.strip(), context) != start
        or parse_timestamp(stated_end.strip(), context) != end
    ):
        raise ReaderError(f"{context}: period {period!r} is not the measured period")


def _credits_used(usage: Mapping[str, Any], context: str) -> Decimal:
    response = usage.get("raw_response")
    users = response.get("users") if isinstance(response, dict) else None
    if not isinstance(users, list) or not users:
        raise ReaderError(f"{context}: raw_response.users must be a non-empty array")
    total = Decimal(0)
    for index, user in enumerate(users):
        if not isinstance(user, dict):
            raise ReaderError(f"{context}: user {index} must be a JSON object")
        total += _decimal(
            user.get("creditsUsed"), f"{context}: user {index} creditsUsed"
        )
    return total


def _decimal(value: Any, context: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ReaderError(f"{context} must be a number")
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise ReaderError(f"{context} must be a number") from error


def _required_timestamp(value: Any, context: str) -> Any:
    parsed = parse_timestamp(value, context)
    if parsed is None:
        raise ReaderError(f"{context}: the billing period must be recorded")
    return parsed


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReaderError(f"expected text, got {type(value).__name__}")
    return value

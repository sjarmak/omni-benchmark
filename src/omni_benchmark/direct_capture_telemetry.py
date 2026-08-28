"""Small immutable telemetry values and clocks used by direct capture."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class DirectProbeTelemetry:
    token_usage: dict[str, int] | None
    cost_usd: float | None
    retry_count: int | None
    semantic_objects: tuple[str, ...]
    tool_calls_by_name: tuple[tuple[str, int], ...]
    tool_call_count: int
    failure_origin: str | None
    finished_at: str

    @property
    def token_source(self) -> str:
        return "provider_reported" if self.token_usage is not None else "unavailable"

    @property
    def cost_source(self) -> str:
        return "provider_reported" if self.cost_usd is not None else "unavailable"


def failure_origin(failure: str | None) -> str | None:
    if failure is None:
        return None
    if failure in {"database_identity_mismatch", "database_infrastructure_error"}:
        return "benchmark_infrastructure"
    return "evaluated_system"


def timestamp_after(started_at: str, elapsed_ms: float) -> str:
    parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    return (
        (parsed + timedelta(milliseconds=elapsed_ms))
        .astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )

"""Aggregate arithmetic shared by the frozen analysis artifacts.

Every function here mirrors, digit for digit, the arithmetic used by the
scripts under ``experiments/analysis`` that produced the frozen JSON outputs.
The reconciliation recomputes those aggregates from database rows and must
round the same way the originals did, or a correct database would appear to
disagree with a correct artifact.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from decimal import Decimal

Number = int | float


class ReconcileStatsError(ValueError):
    """Raised when a distribution is asked for an impossible coverage."""


def as_number(value: object) -> Number:
    """Coerce a database numeric to the float the frozen scripts summed."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ReconcileStatsError(f"expected a number, got {type(value).__name__}")
    if isinstance(value, Decimal):
        return float(value)
    return value


def rounded(value: Number) -> float:
    """Six-decimal rounding, the precision every frozen artifact publishes."""
    return round(float(value), 6)


def median(values: Sequence[Number]) -> float:
    """Rounded ``statistics.median``; the caller guarantees a non-empty input."""
    if not values:
        raise ReconcileStatsError("median of an empty sequence")
    return rounded(statistics.median(values))


def tukey_distribution(
    values: Iterable[Number], *, total: int | None = None
) -> dict[str, object]:
    """Tukey median-of-halves quartiles, odd-sample median excluded from both."""
    ordered = sorted(values)
    observed = len(ordered)
    denominator = observed if total is None else total
    if denominator < observed:
        raise ReconcileStatsError("distribution total is smaller than observations")
    if not ordered:
        return {
            "observed": 0,
            "missing": denominator,
            "median": None,
            "tukey_iqr": None,
        }
    centre = median(ordered)
    if observed == 1:
        q1 = q3 = centre
    else:
        midpoint = observed // 2
        q1 = median(ordered[:midpoint])
        q3 = median(ordered[(observed + 1) // 2 :])
    return {
        "observed": observed,
        "missing": denominator - observed,
        "median": centre,
        "tukey_iqr": {"q1": q1, "q3": q3},
    }


def median_coverage(values: Iterable[Number], *, total: int) -> dict[str, object]:
    """Median plus observed/missing coverage against ``total`` attempts."""
    observed = list(values)
    if total < len(observed):
        raise ReconcileStatsError("coverage total is smaller than observations")
    return {
        "observed": len(observed),
        "missing": total - len(observed),
        "median": median(observed) if observed else None,
    }


def cost_summary(values: Sequence[Number], *, total: int) -> dict[str, object]:
    """The sealed summary's cost block: status, coverage, and totals."""
    observed = len(values)
    if total < observed:
        raise ReconcileStatsError("cost total is smaller than observations")
    base: dict[str, object] = {"observed": observed, "missing": total - observed}
    if observed == 0:
        return {**base, "status": "unavailable"}
    if observed != total:
        return {**base, "status": "partially_observed"}
    cost_total = sum(values)
    return {
        **base,
        "status": "fully_observed",
        "mean": rounded(cost_total / total),
        "total": rounded(cost_total),
    }


def percent(numerator: int, denominator: int) -> float | None:
    """One-decimal percentage, ``None`` for an empty denominator."""
    return round(100.0 * numerator / denominator, 1) if denominator else None

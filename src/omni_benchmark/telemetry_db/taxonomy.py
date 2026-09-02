"""Stable category codes for the failure taxonomy in docs/failure-taxonomy.md."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType


class TaxonomyError(ValueError):
    """Raised when a taxonomy version or category is not defined."""


TAXONOMY_VERSION = "failure-taxonomy-v1"

TAXONOMY_V1: Mapping[str, str] = MappingProxyType(
    {
        "hkb_absent_or_mistransformed": "HKB absent/mistransformed",
        "hkb_dependency": "HKB dependency",
        "retrieval_discoverability": "Retrieval/discoverability",
        "retrieved_misinterpreted": "Retrieved but misinterpreted",
        "relationship_join": "Relationship/join",
        "metric_aggregation_grain": "Metric/aggregation/grain",
        "time_semantics": "Time semantics",
        "filter_value_alias": "Filter/value/alias",
        "semantic_compilation": "Semantic compilation",
        "validation_retry": "Validation/retry",
        "direct_reasoning": "Direct reasoning",
        "refusal_error": "Refusal/error",
        "scorer_data_ambiguity": "Scorer/data ambiguity",
    }
)

TAXONOMIES: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {TAXONOMY_VERSION: TAXONOMY_V1}
)


def taxonomy_for(version: str) -> Mapping[str, str]:
    """Return the code -> title mapping for one taxonomy version."""
    try:
        return TAXONOMIES[version]
    except KeyError:
        known = ", ".join(sorted(TAXONOMIES))
        raise TaxonomyError(
            f"unknown taxonomy_version {version!r}; known versions: {known}"
        ) from None


def validate_category(version: str, category: str) -> str:
    """Return ``category`` if it is a code of ``version``; raise otherwise."""
    codes = taxonomy_for(version)
    if category not in codes:
        raise TaxonomyError(
            f"unknown category {category!r} for {version}; "
            f"known codes: {', '.join(codes)}"
        )
    return category

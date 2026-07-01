"""Overall confidence calculation for canonical profiles."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from src.confidence.sources import (
    DEFAULT_SOURCE_WEIGHT,
    SOURCE_CONFIDENCE,
    get_source_weight,
)
from src.models.canonical import CanonicalProfile, Location
from src.models.provenance import ProvenanceEntry

SCORABLE_FIELDS: tuple[str, ...] = (
    "full_name",
    "emails",
    "phones",
    "location",
    "links",
    "headline",
    "years_experience",
    "skills",
    "experience",
    "education",
)


def _location_is_populated(location: Location | None) -> bool:
    """Return True when a location contains at least one populated field."""
    if location is None:
        return False
    return any(
        (
            location.raw and location.raw.strip(),
            location.city and location.city.strip(),
            location.state and location.state.strip(),
            location.country and location.country.strip(),
        )
    )


def _is_non_empty_string(value: str | None) -> bool:
    return value is not None and bool(value.strip())


_FIELD_POPULATED_CHECKS: dict[str, Callable[[CanonicalProfile], bool]] = {
    "full_name": lambda profile: _is_non_empty_string(profile.full_name),
    "emails": lambda profile: bool(profile.emails),
    "phones": lambda profile: bool(profile.phones),
    "location": lambda profile: _location_is_populated(profile.location),
    "links": lambda profile: bool(profile.links),
    "headline": lambda profile: _is_non_empty_string(profile.headline),
    "years_experience": lambda profile: profile.years_experience is not None,
    "skills": lambda profile: bool(profile.skills),
    "experience": lambda profile: bool(profile.experience),
    "education": lambda profile: bool(profile.education),
}


def _iter_populated_fields(profile: CanonicalProfile) -> Iterator[str]:
    """Yield canonical field names that contain data and should be scored."""
    for field_name in SCORABLE_FIELDS:
        is_populated = _FIELD_POPULATED_CHECKS.get(field_name)
        if is_populated is not None and is_populated(profile):
            yield field_name


def _field_confidence(
    provenance: list[ProvenanceEntry],
    field_name: str,
    source_weights: dict[str, float],
) -> float:
    """Return the highest source weight associated with a populated field."""
    matching_sources = [
        entry.source
        for entry in provenance
        if entry.field == field_name
    ]
    if not matching_sources:
        return DEFAULT_SOURCE_WEIGHT

    return max(
        get_source_weight(source, source_weights)
        for source in matching_sources
    )


def _calculate_overall_confidence(
    profile: CanonicalProfile,
    source_weights: dict[str, float],
) -> float:
    """Compute the average field confidence rounded to two decimal places."""
    field_scores = [
        _field_confidence(profile.provenance, field_name, source_weights)
        for field_name in _iter_populated_fields(profile)
    ]

    if not field_scores:
        return 0.0

    average = sum(field_scores) / len(field_scores)
    return round(average, 2)


class ConfidenceEngine:
    """Calculate ``overall_confidence`` for a canonical profile.

    Confidence is derived from provenance-backed source weights. Field values
    are never modified; a new profile instance is returned with the score set.
    """

    def __init__(self, source_weights: dict[str, float] | None = None) -> None:
        self._source_weights = dict(
            source_weights if source_weights is not None else SOURCE_CONFIDENCE
        )

    def calculate(self, profile: CanonicalProfile) -> CanonicalProfile:
        """Return a copy of ``profile`` with ``overall_confidence`` populated.

        Never raises due to missing optional data.
        """
        overall_confidence = _calculate_overall_confidence(
            profile,
            self._source_weights,
        )
        return profile.model_copy(update={"overall_confidence": overall_confidence})

"""Reusable field-level merge helpers for combining canonical profiles.

Each function is stateless and independent of orchestration logic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import TypeVar

from src.models.canonical import (
    EducationEntry,
    ExperienceEntry,
    LinkEntry,
    Location,
)
from src.models.provenance import ProvenanceEntry, ProvenanceMethod
from src.normalizers.email import normalize_email
from src.normalizers.phone import normalize_phone
from src.normalizers.skill import normalize_skill
from src.normalizers.url import normalize_url

T = TypeVar("T")


def infer_profile_priority(
    provenance: Sequence[ProvenanceEntry],
    source_priority: Sequence[str],
) -> int:
    """Return the priority rank for a profile based on its provenance sources.

    Lower rank means higher priority. Sources not in ``source_priority`` rank
    last among unknown sources in stable order.
    """
    sources = {entry.source for entry in provenance}
    for rank, source_id in enumerate(source_priority):
        if source_id in sources:
            return rank
    return len(source_priority)


def merge_candidate_id(values: Iterable[str | None]) -> str:
    """Return the first non-empty candidate identifier in input order."""
    for value in values:
        if value is not None and value.strip():
            return value
    return ""


def merge_scalar_by_priority(
    values: Sequence[tuple[T | None, int]],
) -> T | None:
    """Select the first non-empty scalar from the highest-priority source.

    Values are sorted by ascending priority rank (lower rank wins). ``None``
    and blank strings are skipped. Numeric zero is treated as a valid value.
    """
    for value, _ in sorted(values, key=lambda item: item[1]):
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def merge_string_lists(
    lists: Sequence[Sequence[str]],
    normalize_fn: Callable[[str | None], str | None],
) -> list[str]:
    """Merge string lists with normalization, invalid-value removal, and dedup.

    Iterates lists in order, then items within each list. Preserves first-seen
    insertion order after normalization.
    """
    seen: set[str] = set()
    merged: list[str] = []

    for items in lists:
        for item in items:
            normalized = normalize_fn(item)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)

    return merged


def merge_emails(lists: Sequence[Sequence[str]]) -> list[str]:
    """Merge email lists using ``normalize_email``."""
    return merge_string_lists(lists, normalize_email)


def merge_phones(lists: Sequence[Sequence[str]]) -> list[str]:
    """Merge phone lists using ``normalize_phone``."""
    return merge_string_lists(lists, normalize_phone)


def merge_skills(lists: Sequence[Sequence[str]]) -> list[str]:
    """Merge skill lists with alias canonicalization and deduplication."""
    seen: set[str] = set()
    merged: list[str] = []

    for skills in lists:
        for skill in skills:
            normalized = normalize_skill(skill)
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            merged.append(normalized)

    return merged


def location_has_value(location: Location | None) -> bool:
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


def merge_location(
    values: Sequence[tuple[Location | None, int]],
) -> Location | None:
    """Select the first populated location from the highest-priority source."""
    for location, _ in sorted(values, key=lambda item: item[1]):
        if location_has_value(location):
            return location
    return None


def merge_links(lists: Sequence[Sequence[LinkEntry]]) -> list[LinkEntry]:
    """Merge link lists, deduplicating by normalized URL while preserving order."""
    seen_urls: set[str] = set()
    merged: list[LinkEntry] = []

    for links in lists:
        for link in links:
            normalized_url = normalize_url(link.url)
            if normalized_url is None or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            merged.append(
                LinkEntry(url=normalized_url, label=link.label)
            )

    return merged


def _experience_key(entry: ExperienceEntry) -> tuple[str | None, ...]:
    """Build a uniqueness key for an experience record."""
    return (
        entry.company,
        entry.title,
        entry.start_date,
        entry.end_date,
    )


def merge_experience(lists: Sequence[Sequence[ExperienceEntry]]) -> list[ExperienceEntry]:
    """Merge experience lists, keeping unique entries by company/title/dates."""
    seen: set[tuple[str | None, ...]] = set()
    merged: list[ExperienceEntry] = []

    for experiences in lists:
        for entry in experiences:
            key = _experience_key(entry)
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)

    return merged


def _education_key(entry: EducationEntry) -> tuple[str | None, ...]:
    """Build a uniqueness key for an education record."""
    return (
        entry.institution,
        entry.degree,
        entry.field_of_study,
        entry.start_date,
        entry.end_date,
    )


def merge_education(lists: Sequence[Sequence[EducationEntry]]) -> list[EducationEntry]:
    """Merge education lists, keeping unique entries by institution/degree/dates."""
    seen: set[tuple[str | None, ...]] = set()
    merged: list[EducationEntry] = []

    for educations in lists:
        for entry in educations:
            key = _education_key(entry)
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)

    return merged


def merge_provenance(
    provenance_lists: Sequence[Sequence[ProvenanceEntry]],
) -> list[ProvenanceEntry]:
    """Combine provenance records without losing or duplicating entries."""
    seen: set[tuple[str, str, ProvenanceMethod]] = set()
    merged: list[ProvenanceEntry] = []

    for provenance in provenance_lists:
        for entry in provenance:
            key = (entry.field, entry.source, entry.method)
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)

    return merged

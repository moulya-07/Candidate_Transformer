"""Merge engine orchestration."""

from __future__ import annotations

from src.merge import policies
from src.models.canonical import CanonicalProfile

DEFAULT_SOURCE_PRIORITY: list[str] = ["recruiter_csv", "github"]


class MergeEngine:
    """Combine multiple canonical profiles into a single merged profile.

    Field-level rules are delegated to reusable helpers in ``policies``.
    Source priority is configurable so additional data sources can be added
    without changing merge logic.
    """

    def __init__(self, source_priority: list[str] | None = None) -> None:
        self._source_priority = list(
            source_priority if source_priority is not None else DEFAULT_SOURCE_PRIORITY
        )

    def merge_profiles(self, profiles: list[CanonicalProfile]) -> CanonicalProfile:
        """Merge profiles into one canonical profile using configured policies.

        Returns an empty profile when ``profiles`` is empty. Never raises due to
        missing optional fields on input profiles.
        """
        if not profiles:
            return CanonicalProfile(candidate_id="")

        ranked_profiles = [
            (
                profile,
                policies.infer_profile_priority(
                    profile.provenance,
                    self._source_priority,
                ),
            )
            for profile in profiles
        ]

        return CanonicalProfile(
            candidate_id=policies.merge_candidate_id(
                profile.candidate_id for profile in profiles
            ),
            full_name=policies.merge_scalar_by_priority(
                [(profile.full_name, rank) for profile, rank in ranked_profiles]
            ),
            emails=policies.merge_emails(profile.emails for profile in profiles),
            phones=policies.merge_phones(profile.phones for profile in profiles),
            location=policies.merge_location(
                [
                    (profile.location, rank)
                    for profile, rank in ranked_profiles
                ]
            ),
            links=policies.merge_links(profile.links for profile in profiles),
            headline=policies.merge_scalar_by_priority(
                [(profile.headline, rank) for profile, rank in ranked_profiles]
            ),
            years_experience=policies.merge_scalar_by_priority(
                [
                    (profile.years_experience, rank)
                    for profile, rank in ranked_profiles
                ]
            ),
            skills=policies.merge_skills(profile.skills for profile in profiles),
            experience=policies.merge_experience(
                profile.experience for profile in profiles
            ),
            education=policies.merge_education(
                profile.education for profile in profiles
            ),
            provenance=policies.merge_provenance(
                profile.provenance for profile in profiles
            ),
            overall_confidence=None,
        )

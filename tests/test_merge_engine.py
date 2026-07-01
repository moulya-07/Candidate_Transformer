"""Unit tests for the merge engine and field-level merge policies."""

from __future__ import annotations

import uuid

import pytest

from src.merge.engine import MergeEngine
from src.models.canonical import (
    CanonicalProfile,
    EducationEntry,
    ExperienceEntry,
    LinkEntry,
    Location,
)
from src.models.provenance import ProvenanceEntry, ProvenanceMethod


def _provenance(source: str, *fields: str) -> list[ProvenanceEntry]:
    return [
        ProvenanceEntry(
            field=field,
            source=source,
            method=ProvenanceMethod.DIRECT,
        )
        for field in fields
    ]


def _csv_profile(**overrides: object) -> CanonicalProfile:
    defaults: dict[str, object] = {
        "candidate_id": str(uuid.uuid4()),
        "full_name": "Jane Recruiter",
        "emails": ["jane@example.com"],
        "phones": ["+14155552671"],
        "location": Location(raw="San Francisco, CA"),
        "links": [],
        "headline": "Engineer at Acme Corp",
        "years_experience": 5.0,
        "skills": ["Python", "py"],
        "experience": [
            ExperienceEntry(
                company="Acme Corp",
                title="Engineer",
                start_date="2020-01",
                end_date=None,
            )
        ],
        "education": [
            EducationEntry(
                institution="State University",
                degree="BS",
                field_of_study="Computer Science",
                start_date="2014-09",
                end_date="2018-05",
            )
        ],
        "provenance": _provenance(
            "recruiter_csv",
            "full_name",
            "emails",
            "phones",
            "headline",
            "location",
        ),
        "overall_confidence": 0.9,
    }
    defaults.update(overrides)
    return CanonicalProfile(**defaults)  # type: ignore[arg-type]


def _github_profile(**overrides: object) -> CanonicalProfile:
    defaults: dict[str, object] = {
        "candidate_id": str(uuid.uuid4()),
        "full_name": "Jane GitHub",
        "emails": ["JANE@EXAMPLE.COM", "jane.github@example.com"],
        "phones": [],
        "location": Location(raw="Berlin, Germany"),
        "links": [
            LinkEntry(url="https://github.com/janedoe", label="github"),
            LinkEntry(url="https://janedoe.dev/", label="blog"),
        ],
        "headline": "Open-source contributor",
        "years_experience": 7.0,
        "skills": ["JavaScript", "js", "Docker"],
        "experience": [
            ExperienceEntry(
                company="Open Source",
                title="Maintainer",
                start_date="2019-06",
                end_date="2023-12",
            )
        ],
        "education": [
            EducationEntry(
                institution="Online Academy",
                degree="Certificate",
                field_of_study="Web Development",
                start_date="2018-01",
                end_date="2018-12",
            )
        ],
        "provenance": _provenance(
            "github",
            "full_name",
            "emails",
            "location",
            "headline",
            "links",
            "skills",
        ),
        "overall_confidence": 0.75,
    }
    defaults.update(overrides)
    return CanonicalProfile(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def engine() -> MergeEngine:
    return MergeEngine()


class TestSingleProfile:
    def test_single_profile_passthrough_with_normalization(
        self, engine: MergeEngine
    ) -> None:
        profile = _csv_profile(
            emails=["  Jane@Example.COM  "],
            phones=["+1 415 555 2671"],
            skills=["py", "Python", "docker"],
        )

        merged = engine.merge_profiles([profile])

        assert merged.candidate_id == profile.candidate_id
        assert merged.full_name == "Jane Recruiter"
        assert merged.emails == ["jane@example.com"]
        assert merged.phones == ["+14155552671"]
        assert merged.skills == ["Python", "Docker"]
        assert len(merged.experience) == 1
        assert len(merged.education) == 1
        assert merged.overall_confidence is None


class TestCsvGitHubMerge:
    def test_csv_and_github_merge(self, engine: MergeEngine) -> None:
        csv_profile = _csv_profile()
        github_profile = _github_profile()

        merged = engine.merge_profiles([csv_profile, github_profile])

        assert merged.candidate_id == csv_profile.candidate_id
        assert merged.full_name == "Jane Recruiter"
        assert merged.headline == "Engineer at Acme Corp"
        assert merged.location is not None
        assert merged.location.raw == "San Francisco, CA"
        assert merged.years_experience == 5.0
        assert merged.emails == [
            "jane@example.com",
            "jane.github@example.com",
        ]
        assert merged.phones == ["+14155552671"]
        assert merged.skills == ["Python", "JavaScript", "Docker"]
        assert len(merged.links) == 2
        assert len(merged.experience) == 2
        assert len(merged.education) == 2
        assert merged.overall_confidence is None

        provenance_sources = {entry.source for entry in merged.provenance}
        assert provenance_sources == {"recruiter_csv", "github"}


class TestDuplicateEmails:
    def test_duplicate_emails_deduplicated(self, engine: MergeEngine) -> None:
        first = _csv_profile(emails=["jane@example.com"])
        second = _github_profile(emails=["JANE@EXAMPLE.COM", "other@example.com"])

        merged = engine.merge_profiles([first, second])

        assert merged.emails == ["jane@example.com", "other@example.com"]


class TestDuplicatePhones:
    def test_duplicate_phones_deduplicated(self, engine: MergeEngine) -> None:
        first = _csv_profile(phones=["+14155552671"])
        second = _csv_profile(
            candidate_id="second-id",
            phones=["+1 415 555 2671"],
            provenance=_provenance("recruiter_csv", "phones"),
        )

        merged = engine.merge_profiles([first, second])

        assert merged.phones == ["+14155552671"]


class TestDuplicateSkills:
    def test_duplicate_skills_deduplicated_and_canonicalized(
        self, engine: MergeEngine
    ) -> None:
        first = _csv_profile(skills=["py", "Python"])
        second = _github_profile(skills=["javascript", "js"])

        merged = engine.merge_profiles([first, second])

        assert merged.skills == ["Python", "JavaScript"]


class TestDuplicateLinks:
    def test_duplicate_links_deduplicated_by_url(self, engine: MergeEngine) -> None:
        first = _github_profile(
            links=[LinkEntry(url="https://github.com/janedoe", label="github")]
        )
        second = _github_profile(
            candidate_id="second-id",
            links=[
                LinkEntry(url="http://github.com/janedoe/", label="github"),
                LinkEntry(url="https://portfolio.example.com", label="portfolio"),
            ],
            provenance=_provenance("github", "links"),
        )

        merged = engine.merge_profiles([first, second])

        assert len(merged.links) == 2
        assert merged.links[0].url == "https://github.com/janedoe"
        assert merged.links[1].url == "https://portfolio.example.com"


class TestConflictingScalars:
    def test_conflicting_names_prefers_csv(self, engine: MergeEngine) -> None:
        merged = engine.merge_profiles([_github_profile(), _csv_profile()])
        assert merged.full_name == "Jane Recruiter"

    def test_conflicting_headlines_prefers_csv(self, engine: MergeEngine) -> None:
        merged = engine.merge_profiles([_github_profile(), _csv_profile()])
        assert merged.headline == "Engineer at Acme Corp"

    def test_conflicting_locations_prefers_csv(self, engine: MergeEngine) -> None:
        merged = engine.merge_profiles([_github_profile(), _csv_profile()])
        assert merged.location is not None
        assert merged.location.raw == "San Francisco, CA"


class TestExperienceMerge:
    def test_unique_experience_entries_merged(self, engine: MergeEngine) -> None:
        shared = ExperienceEntry(
            company="Shared Co",
            title="Developer",
            start_date="2021-01",
            end_date="2022-01",
        )
        csv_profile = _csv_profile(experience=[shared])
        github_profile = _github_profile(
            experience=[
                shared,
                ExperienceEntry(
                    company="Other Co",
                    title="Lead",
                    start_date="2023-01",
                    end_date=None,
                ),
            ]
        )

        merged = engine.merge_profiles([csv_profile, github_profile])

        assert len(merged.experience) == 2
        assert merged.experience[0].company == "Shared Co"
        assert merged.experience[1].company == "Other Co"


class TestEducationMerge:
    def test_unique_education_entries_merged(self, engine: MergeEngine) -> None:
        shared = EducationEntry(
            institution="Shared University",
            degree="MS",
            field_of_study="AI",
            start_date="2019-09",
            end_date="2021-05",
        )
        csv_profile = _csv_profile(education=[shared])
        github_profile = _github_profile(
            education=[
                shared,
                EducationEntry(
                    institution="Bootcamp",
                    degree="Certificate",
                    field_of_study="Cloud",
                    start_date="2022-01",
                    end_date="2022-06",
                ),
            ]
        )

        merged = engine.merge_profiles([csv_profile, github_profile])

        assert len(merged.education) == 2
        assert merged.education[0].institution == "Shared University"
        assert merged.education[1].institution == "Bootcamp"


class TestProvenanceMerge:
    def test_provenance_merged_without_duplicates(self, engine: MergeEngine) -> None:
        csv_profile = _csv_profile()
        duplicate_csv = _csv_profile(
            candidate_id="duplicate-id",
            provenance=_provenance("recruiter_csv", "full_name", "emails"),
        )
        github_profile = _github_profile()

        merged = engine.merge_profiles([csv_profile, duplicate_csv, github_profile])

        keys = {
            (entry.field, entry.source, entry.method)
            for entry in merged.provenance
        }
        assert len(keys) == len(merged.provenance)
        assert ("full_name", "recruiter_csv", ProvenanceMethod.DIRECT) in keys
        assert ("skills", "github", ProvenanceMethod.DIRECT) in keys


class TestEmptyAndMissingFields:
    def test_empty_profile_list(self, engine: MergeEngine) -> None:
        merged = engine.merge_profiles([])

        assert merged.candidate_id == ""
        assert merged.full_name is None
        assert merged.emails == []
        assert merged.phones == []
        assert merged.skills == []
        assert merged.links == []
        assert merged.experience == []
        assert merged.education == []
        assert merged.provenance == []
        assert merged.overall_confidence is None

    def test_missing_optional_fields(self, engine: MergeEngine) -> None:
        sparse = CanonicalProfile(
            candidate_id="sparse-id",
            provenance=[],
        )
        enriched = _github_profile()

        merged = engine.merge_profiles([sparse, enriched])

        assert merged.candidate_id == "sparse-id"
        assert merged.full_name == "Jane GitHub"
        assert merged.emails == ["jane@example.com", "jane.github@example.com"]
        assert merged.phones == []
        assert merged.location is not None
        assert merged.headline == "Open-source contributor"


class TestInvalidValuesFiltered:
    def test_invalid_emails_and_phones_removed(self, engine: MergeEngine) -> None:
        profile = _csv_profile(
            emails=["not-an-email", "valid@example.com"],
            phones=["invalid-phone", "+14155552671"],
        )

        merged = engine.merge_profiles([profile])

        assert merged.emails == ["valid@example.com"]
        assert merged.phones == ["+14155552671"]


class TestConfigurableSourcePriority:
    def test_custom_priority_order(self) -> None:
        custom_engine = MergeEngine(source_priority=["github", "recruiter_csv"])
        merged = custom_engine.merge_profiles([_csv_profile(), _github_profile()])

        assert merged.full_name == "Jane GitHub"
        assert merged.headline == "Open-source contributor"
        assert merged.years_experience == 7.0

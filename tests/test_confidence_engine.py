"""Unit tests for the confidence engine."""

from __future__ import annotations

import uuid

import pytest

from src.confidence.engine import ConfidenceEngine
from src.models.canonical import (
    CanonicalProfile,
    EducationEntry,
    ExperienceEntry,
    LinkEntry,
    Location,
)
from src.models.provenance import ProvenanceEntry, ProvenanceMethod


def _provenance(
    source: str,
    *fields: str,
    method: ProvenanceMethod = ProvenanceMethod.DIRECT,
) -> list[ProvenanceEntry]:
    return [
        ProvenanceEntry(field=field, source=source, method=method)
        for field in fields
    ]


@pytest.fixture
def engine() -> ConfidenceEngine:
    return ConfidenceEngine()


class TestRecruiterOnlyProfile:
    def test_all_recruiter_fields_score_one(self, engine: ConfidenceEngine) -> None:
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane Doe",
            emails=["jane@example.com"],
            phones=["+14155552671"],
            location=Location(raw="San Francisco"),
            headline="Engineer",
            years_experience=5.0,
            skills=["Python"],
            experience=[
                ExperienceEntry(
                    company="Acme",
                    title="Engineer",
                    start_date="2020-01",
                )
            ],
            education=[
                EducationEntry(
                    institution="State U",
                    degree="BS",
                    field_of_study="CS",
                )
            ],
            provenance=_provenance(
                "recruiter_csv",
                "full_name",
                "emails",
                "phones",
                "location",
                "headline",
                "years_experience",
                "skills",
                "experience",
                "education",
            ),
        )

        result = engine.calculate(profile)

        assert result.overall_confidence == 1.0
        assert result.full_name == profile.full_name
        assert result.emails == profile.emails
        assert result.provenance == profile.provenance


class TestGitHubOnlyProfile:
    def test_all_github_fields_score_point_eight(
        self, engine: ConfidenceEngine
    ) -> None:
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane GitHub",
            emails=["jane@example.com"],
            links=[LinkEntry(url="https://github.com/jane", label="github")],
            headline="Contributor",
            skills=["JavaScript"],
            provenance=_provenance(
                "github",
                "full_name",
                "emails",
                "links",
                "headline",
                "skills",
            ),
        )

        result = engine.calculate(profile)

        assert result.overall_confidence == 0.8


class TestMixedSources:
    def test_mixed_source_average(self, engine: ConfidenceEngine) -> None:
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane Doe",
            emails=["jane@example.com"],
            skills=["Python"],
            provenance=[
                *_provenance("recruiter_csv", "full_name", "emails"),
                *_provenance("github", "skills"),
            ],
        )

        result = engine.calculate(profile)

        # (1.0 + 1.0 + 0.8) / 3 = 0.933... -> 0.93
        assert result.overall_confidence == 0.93

    def test_highest_source_wins_for_field(self, engine: ConfidenceEngine) -> None:
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane Doe",
            provenance=[
                ProvenanceEntry(
                    field="full_name",
                    source="github",
                    method=ProvenanceMethod.DIRECT,
                ),
                ProvenanceEntry(
                    field="full_name",
                    source="recruiter_csv",
                    method=ProvenanceMethod.MERGED,
                ),
            ],
        )

        result = engine.calculate(profile)

        assert result.overall_confidence == 1.0


class TestUnknownSource:
    def test_unknown_source_uses_default_weight(
        self, engine: ConfidenceEngine
    ) -> None:
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane Doe",
            provenance=_provenance("unknown_future_source", "full_name"),
        )

        result = engine.calculate(profile)

        assert result.overall_confidence == 0.5


class TestEmptyProfile:
    def test_empty_profile_scores_zero(self, engine: ConfidenceEngine) -> None:
        profile = CanonicalProfile(candidate_id="")

        result = engine.calculate(profile)

        assert result.overall_confidence == 0.0


class TestMissingProvenance:
    def test_populated_field_without_provenance_uses_default(
        self, engine: ConfidenceEngine
    ) -> None:
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane Doe",
            emails=["jane@example.com"],
            provenance=[],
        )

        result = engine.calculate(profile)

        # (0.5 + 0.5) / 2 = 0.5
        assert result.overall_confidence == 0.5


class TestRoundedValues:
    def test_result_rounded_to_two_decimals(self, engine: ConfidenceEngine) -> None:
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane Doe",
            skills=["Python"],
            provenance=[
                *_provenance("recruiter_csv", "full_name"),
                *_provenance("github", "skills"),
            ],
        )

        result = engine.calculate(profile)

        # (1.0 + 0.8) / 2 = 0.9
        assert result.overall_confidence == 0.9


class TestManyPopulatedFields:
    def test_all_populated_fields_contribute(self, engine: ConfidenceEngine) -> None:
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane Doe",
            emails=["jane@example.com"],
            phones=["+14155552671"],
            location=Location(raw="NYC"),
            links=[LinkEntry(url="https://example.com", label="site")],
            headline="Engineer",
            years_experience=3.0,
            skills=["Python", "Docker"],
            experience=[ExperienceEntry(company="Acme", title="Dev")],
            education=[EducationEntry(institution="State U", degree="BS")],
            provenance=_provenance(
                "github",
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
            ),
        )

        result = engine.calculate(profile)

        assert result.overall_confidence == 0.8
        assert profile.overall_confidence is None
        assert result.full_name == profile.full_name
        assert result.skills == profile.skills


class TestCustomWeights:
    def test_custom_source_weights(self) -> None:
        custom_engine = ConfidenceEngine(
            source_weights={"recruiter_csv": 0.75, "github": 0.25}
        )
        profile = CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name="Jane Doe",
            skills=["Python"],
            provenance=[
                *_provenance("recruiter_csv", "full_name"),
                *_provenance("github", "skills"),
            ],
        )

        result = custom_engine.calculate(profile)

        assert result.overall_confidence == 0.5

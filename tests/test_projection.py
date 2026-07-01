"""Unit tests for the projection layer."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.models.canonical import (
    CanonicalProfile,
    EducationEntry,
    ExperienceEntry,
    LinkEntry,
    Location,
)
from src.models.provenance import ProvenanceEntry, ProvenanceMethod
from src.projection.config import OutputConfig, load_config
from src.projection.projector import (
    InvalidFieldPathError,
    MissingFieldError,
    Projector,
    parse_field_path,
    resolve_field_path,
)


@pytest.fixture
def projector() -> Projector:
    return Projector()


@pytest.fixture
def sample_profile() -> CanonicalProfile:
    return CanonicalProfile(
        candidate_id=str(uuid.uuid4()),
        full_name="Jane Doe",
        emails=["jane@example.com", "jane.doe@work.com"],
        phones=["+14155552671"],
        location=Location(raw="San Francisco", city="San Francisco", country="USA"),
        links=[
            LinkEntry(url="https://github.com/janedoe", label="github"),
            LinkEntry(url="https://janedoe.dev", label="blog"),
        ],
        headline="Software Engineer",
        years_experience=6.0,
        skills=["py", "JavaScript", "docker"],
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                title="Engineer",
                start_date="2020-01",
                end_date=None,
            )
        ],
        education=[
            EducationEntry(
                institution="State University",
                degree="BS",
                field_of_study="Computer Science",
                start_date="2014-09",
                end_date="2018-05",
            )
        ],
        provenance=[
            ProvenanceEntry(
                field="full_name",
                source="recruiter_csv",
                method=ProvenanceMethod.DIRECT,
            )
        ],
        overall_confidence=0.93,
    )


def _config(**overrides: object) -> OutputConfig:
    defaults: dict[str, object] = {
        "fields": [{"path": "full_name"}],
        "include_confidence": False,
        "include_provenance": False,
        "on_missing": "null",
    }
    defaults.update(overrides)
    return OutputConfig.model_validate(defaults)


class TestSimpleProjection:
    def test_projects_selected_fields(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[
                {"path": "full_name"},
                {"path": "headline"},
                {"path": "years_experience"},
            ]
        )

        result = projector.project(sample_profile, config)

        assert result == {
            "full_name": "Jane Doe",
            "headline": "Software Engineer",
            "years_experience": 6.0,
        }
        assert sample_profile.full_name == "Jane Doe"


class TestRenamedFields:
    def test_renamed_output_path(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[
                {"path": "primary_email", "from": "emails[0]"},
                {"path": "display_name", "from": "full_name"},
            ]
        )

        result = projector.project(sample_profile, config)

        assert result["primary_email"] == "jane@example.com"
        assert result["display_name"] == "Jane Doe"


class TestNestedFields:
    def test_nested_source_lookup(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[
                {"path": "city", "from": "location.city"},
                {"path": "country", "from": "location.country"},
            ]
        )

        result = projector.project(sample_profile, config)

        assert result["city"] == "San Francisco"
        assert result["country"] == "USA"

    def test_nested_output_path(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[{"path": "location.city", "from": "location.city"}]
        )

        result = projector.project(sample_profile, config)

        assert result == {"location": {"city": "San Francisco"}}


class TestListExtraction:
    def test_projects_list_field(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(fields=[{"path": "emails"}])

        result = projector.project(sample_profile, config)

        assert result["emails"] == ["jane@example.com", "jane.doe@work.com"]


class TestArrayIndex:
    def test_array_index_extraction(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[
                {"path": "first_company", "from": "experience[0].company"},
                {"path": "github_url", "from": "links[0].url", "normalize": "url"},
            ]
        )

        result = projector.project(sample_profile, config)

        assert result["first_company"] == "Acme Corp"
        assert result["github_url"] == "https://github.com/janedoe"


class TestArrayExpansion:
    def test_skills_array_expansion(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[
                {
                    "path": "skills",
                    "from": "skills[].name",
                    "normalize": "canonical",
                }
            ]
        )

        result = projector.project(sample_profile, config)

        assert result["skills"] == ["Python", "JavaScript", "Docker"]


class TestMissingNull:
    def test_missing_value_becomes_null(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[{"path": "secondary_email", "from": "emails[5]"}],
            on_missing="null",
        )

        result = projector.project(sample_profile, config)

        assert result == {"secondary_email": None}


class TestMissingOmit:
    def test_missing_value_is_omitted(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[
                {"path": "full_name"},
                {"path": "secondary_email", "from": "emails[5]"},
            ],
            on_missing="omit",
        )

        result = projector.project(sample_profile, config)

        assert result == {"full_name": "Jane Doe"}
        assert "secondary_email" not in result


class TestMissingError:
    def test_missing_value_raises(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(
            fields=[{"path": "secondary_email", "from": "emails[5]"}],
            on_missing="error",
        )

        with pytest.raises(MissingFieldError, match="emails\\[5\\]"):
            projector.project(sample_profile, config)


class TestConfidence:
    def test_confidence_included_when_enabled(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(fields=[{"path": "full_name"}], include_confidence=True)

        result = projector.project(sample_profile, config)

        assert result["overall_confidence"] == 0.93

    def test_confidence_excluded_by_default(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(fields=[{"path": "full_name"}])

        result = projector.project(sample_profile, config)

        assert "overall_confidence" not in result


class TestProvenance:
    def test_provenance_included_when_enabled(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(fields=[{"path": "full_name"}], include_provenance=True)

        result = projector.project(sample_profile, config)

        assert result["provenance"] == [
            {
                "field": "full_name",
                "source": "recruiter_csv",
                "method": "direct",
            }
        ]

    def test_provenance_excluded_by_default(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = _config(fields=[{"path": "full_name"}])

        result = projector.project(sample_profile, config)

        assert "provenance" not in result


class TestInvalidConfig:
    def test_invalid_on_missing(self) -> None:
        with pytest.raises(ValidationError):
            OutputConfig.model_validate(
                {
                    "fields": [{"path": "full_name"}],
                    "on_missing": "skip",
                }
            )

    def test_invalid_normalizer(self) -> None:
        with pytest.raises(ValidationError):
            OutputConfig.model_validate(
                {
                    "fields": [
                        {"path": "phone", "from": "phones[0]", "normalize": "E1645"}
                    ]
                }
            )

    def test_empty_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            OutputConfig.model_validate({"fields": []})

    def test_load_config_from_dict(self) -> None:
        config = load_config(
            {
                "fields": [{"path": "full_name"}],
                "include_confidence": True,
                "include_provenance": False,
                "on_missing": "null",
            }
        )

        assert config.include_confidence is True
        assert config.fields[0].source_path == "full_name"


class TestInvalidFieldPath:
    def test_invalid_path_syntax(self) -> None:
        with pytest.raises(InvalidFieldPathError):
            parse_field_path("")

        with pytest.raises(InvalidFieldPathError):
            parse_field_path("emails[abc]")

    def test_missing_nested_field(
        self, sample_profile: CanonicalProfile
    ) -> None:
        profile = sample_profile.model_copy(update={"location": None})

        with pytest.raises(MissingFieldError):
            resolve_field_path(profile, "location.city")


class TestNormalization:
    def test_phone_normalization(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        profile = sample_profile.model_copy(update={"phones": ["+1 415 555 2671"]})
        config = _config(
            fields=[
                {"path": "phone", "from": "phones[0]", "normalize": "E164"}
            ]
        )

        result = projector.project(profile, config)

        assert result["phone"] == "+14155552671"

    def test_email_normalization(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        profile = sample_profile.model_copy(
            update={"emails": ["  Jane@Example.COM  "]}
        )
        config = _config(
            fields=[
                {"path": "primary_email", "from": "emails[0]", "normalize": "email"}
            ]
        )

        result = projector.project(profile, config)

        assert result["primary_email"] == "jane@example.com"


class TestAssignmentExampleConfig:
    def test_example_runtime_config(
        self, projector: Projector, sample_profile: CanonicalProfile
    ) -> None:
        config = load_config(
            {
                "fields": [
                    {"path": "full_name"},
                    {"path": "primary_email", "from": "emails[0]"},
                    {
                        "path": "phone",
                        "from": "phones[0]",
                        "normalize": "E164",
                    },
                    {
                        "path": "skills",
                        "from": "skills[].name",
                        "normalize": "canonical",
                    },
                ],
                "include_confidence": True,
                "include_provenance": True,
                "on_missing": "null",
            }
        )

        result = projector.project(sample_profile, config)

        assert result["full_name"] == "Jane Doe"
        assert result["primary_email"] == "jane@example.com"
        assert result["phone"] == "+14155552671"
        assert result["skills"] == ["Python", "JavaScript", "Docker"]
        assert result["overall_confidence"] == 0.93
        assert len(result["provenance"]) == 1

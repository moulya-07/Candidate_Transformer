"""Canonical candidate profile — internal source of truth for the pipeline.

This model is independent of output configuration. The projection layer
transforms CanonicalProfile into configurable JSON without modifying it.
"""

from pydantic import BaseModel, Field

from .provenance import ProvenanceEntry


class Location(BaseModel):
    """Normalized location representation."""

    raw: str | None = Field(
        default=None,
        description="Original location string when structured parts are unknown.",
    )
    city: str | None = None
    state: str | None = None
    country: str | None = None


class LinkEntry(BaseModel):
    """A normalized external link associated with the candidate."""

    url: str
    label: str | None = Field(
        default=None,
        description="Link type or label (e.g. 'github', 'portfolio').",
    )


class ExperienceEntry(BaseModel):
    """A single employment record."""

    company: str | None = None
    title: str | None = None
    start_date: str | None = Field(
        default=None,
        description="Normalized start date in YYYY-MM format.",
    )
    end_date: str | None = Field(
        default=None,
        description="Normalized end date in YYYY-MM format, or null if current.",
    )
    description: str | None = None


class EducationEntry(BaseModel):
    """A single education record."""

    institution: str | None = None
    degree: str | None = None
    field_of_study: str | None = None
    start_date: str | None = Field(
        default=None,
        description="Normalized start date in YYYY-MM format.",
    )
    end_date: str | None = Field(
        default=None,
        description="Normalized end date in YYYY-MM format.",
    )


class CanonicalProfile(BaseModel):
    """Unified candidate profile produced by the transformation pipeline.

    Fields are populated by parsers, normalized, merged, and enriched with
    provenance and confidence. This model must never depend on output config.
    """

    candidate_id: str = Field(
        ...,
        description="Stable identifier for the candidate across sources.",
    )
    full_name: str | None = None
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(
        default_factory=list,
        description="Phone numbers normalized to E.164.",
    )
    location: Location | None = None
    links: list[LinkEntry] = Field(default_factory=list)
    headline: str | None = None
    years_experience: float | None = None
    skills: list[str] = Field(
        default_factory=list,
        description="Canonical skill names after normalization.",
    )
    experience: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(
        default_factory=list,
        description="Per-field provenance records for merged values.",
    )
    overall_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Aggregate confidence score for the merged profile.",
    )

    model_config = {"extra": "forbid"}

"""Provenance tracking models.

Every populated field in the canonical profile should have a corresponding
ProvenanceEntry describing where the value came from and how it was derived.
"""

from enum import Enum

from pydantic import BaseModel, Field


class ProvenanceMethod(str, Enum):
    """How a field value was obtained or transformed."""

    DIRECT = "direct"
    EXTRACTED = "extracted"
    NORMALIZED = "normalized"
    MERGED = "merged"
    INFERRED = "inferred"


class ProvenanceEntry(BaseModel):
    """Tracks the origin of a single canonical field value."""

    field: str = Field(
        ...,
        description="Canonical field name (e.g. 'full_name', 'skills').",
    )
    source: str = Field(
        ...,
        description="Source identifier (e.g. 'recruiter_csv', 'github').",
    )
    method: ProvenanceMethod = Field(
        ...,
        description="Transformation method applied to derive the value.",
    )

    model_config = {"frozen": True}

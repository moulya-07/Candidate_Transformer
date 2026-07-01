"""Canonical domain models for the candidate transformation pipeline."""

from .canonical import (
    CanonicalProfile,
    EducationEntry,
    ExperienceEntry,
    LinkEntry,
    Location,
)
from .provenance import ProvenanceEntry, ProvenanceMethod

__all__ = [
    "CanonicalProfile",
    "EducationEntry",
    "ExperienceEntry",
    "LinkEntry",
    "Location",
    "ProvenanceEntry",
    "ProvenanceMethod",
]

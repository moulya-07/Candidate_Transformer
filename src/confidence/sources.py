"""Configurable per-source confidence weights for the confidence engine."""

from __future__ import annotations

DEFAULT_SOURCE_WEIGHT: float = 0.50

SOURCE_CONFIDENCE: dict[str, float] = {
    "recruiter_csv": 1.00,
    "github": 0.80,
    "linkedin": 0.90,
    "ats": 0.95,
    "resume": 0.85,
    "recruiter_notes": 0.60,
}


def get_source_weight(
    source: str,
    weights: dict[str, float] | None = None,
) -> float:
    """Return the confidence weight for a provenance source identifier.

    Unknown sources receive ``DEFAULT_SOURCE_WEIGHT``. Never raises.
    """
    mapping = weights if weights is not None else SOURCE_CONFIDENCE
    return mapping.get(source, DEFAULT_SOURCE_WEIGHT)

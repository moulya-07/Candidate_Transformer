"""Name normalization."""

import re


def normalize_name(name: str | None) -> str | None:
    """Normalize a person's name.

    Trims whitespace and collapses internal spaces while preserving
    capitalization. Returns None for empty or missing input. Never raises.
    """
    if name is None:
        return None

    value = name.strip()
    if not value:
        return None

    return re.sub(r"\s+", " ", value)

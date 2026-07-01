"""Email normalization."""

import re

_EMAIL_PATTERN = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")


def normalize_email(email: str | None) -> str | None:
    """Normalize and validate an email address.

    Trims whitespace, lowercases, and validates basic format.
    Returns None for invalid, empty, or missing input. Never raises.
    """
    if email is None:
        return None

    value = email.strip().lower()
    if not value:
        return None

    if not _EMAIL_PATTERN.fullmatch(value):
        return None

    return value

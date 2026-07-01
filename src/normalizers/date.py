"""Date normalization to YYYY-MM."""

from datetime import datetime

from dateutil import parser as date_parser


def normalize_date(date_str: str | None) -> str | None:
    """Normalize a date string to YYYY-MM format.

    Supports common month/year and year/month formats. Returns None for
    invalid, empty, or missing input. Never raises.
    """
    if date_str is None:
        return None

    value = date_str.strip()
    if not value:
        return None

    try:
        parsed = date_parser.parse(value, default=datetime(1900, 1, 1))
        return parsed.strftime("%Y-%m")
    except (ValueError, TypeError, OverflowError):
        return None
    except Exception:
        return None

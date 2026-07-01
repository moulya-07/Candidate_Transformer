"""Phone number normalization to E.164."""

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat


def normalize_phone(phone: str | None) -> str | None:
    """Normalize a phone number to E.164 format.

    Returns None for invalid, empty, or missing input. Never raises.
    """
    if phone is None:
        return None

    value = phone.strip()
    if not value:
        return None

    try:
        parsed = phonenumbers.parse(value, None)
        if not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    except NumberParseException:
        return None
    except Exception:
        return None

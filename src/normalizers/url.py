"""URL normalization."""

from urllib.parse import urlparse, urlunparse


def _is_valid_netloc(netloc: str) -> bool:
    """Return True when the URL host looks usable."""
    if not netloc or " " in netloc:
        return False

    host = netloc.rsplit("@", maxsplit=1)[-1].split(":", maxsplit=1)[0]
    if host == "localhost":
        return True

    if "." not in host:
        return False

    return all(part for part in host.split("."))


def normalize_url(url: str | None) -> str | None:
    """Normalize a URL for consistent storage and comparison.

    Trims whitespace, ensures an https:// prefix, and removes trailing
    slashes from the path. Returns None for invalid, empty, or missing input.
    Never raises.
    """
    if url is None:
        return None

    value = url.strip()
    if not value:
        return None

    try:
        if value.startswith("http://"):
            value = f"https://{value[len('http://'):]}"
        elif not value.startswith("https://"):
            value = f"https://{value}"

        parsed = urlparse(value)
        if not _is_valid_netloc(parsed.netloc):
            return None

        path = parsed.path.rstrip("/")
        normalized = urlunparse(
            (
                "https",
                parsed.netloc,
                path,
                parsed.params,
                parsed.query,
                parsed.fragment,
            )
        )
        return normalized
    except Exception:
        return None

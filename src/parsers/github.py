"""GitHub profile source parser."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

import requests
from requests import Response, Session

from src.models.canonical import CanonicalProfile, LinkEntry, Location
from src.models.provenance import ProvenanceEntry, ProvenanceMethod
from src.parsers.base import SourceParser

logger = logging.getLogger(__name__)

SOURCE_ID = "github"
API_BASE_URL = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 10.0

GITHUB_LINK_LABEL = "github"
BLOG_LINK_LABEL = "blog"


def _is_blank(value: Any) -> bool:
    """Return True when a value is missing or empty."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _as_str(value: Any) -> str | None:
    """Convert a value to a trimmed string when present."""
    if _is_blank(value):
        return None
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _append_provenance(
    provenance: list[ProvenanceEntry],
    field: str,
    method: ProvenanceMethod = ProvenanceMethod.DIRECT,
) -> None:
    """Record provenance for a populated canonical field."""
    provenance.append(
        ProvenanceEntry(
            field=field,
            source=SOURCE_ID,
            method=method,
        )
    )


def _extract_languages(repositories: list[dict[str, Any]]) -> list[str]:
    """Collect unique repository languages in first-seen order."""
    languages: list[str] = []
    seen: set[str] = set()

    for repository in repositories:
        language = _as_str(repository.get("language"))
        if language is None or language in seen:
            continue
        seen.add(language)
        languages.append(language)

    return languages


def _profile_to_canonical(
    profile_data: dict[str, Any],
    repositories: list[dict[str, Any]],
) -> CanonicalProfile | None:
    """Map GitHub profile and repository data to a canonical profile."""
    login = _as_str(profile_data.get("login"))
    if login is None:
        logger.warning("GitHub profile is missing a login; skipping profile.")
        return None

    full_name = _as_str(profile_data.get("name")) or login
    email = _as_str(profile_data.get("email"))
    location_raw = _as_str(profile_data.get("location"))
    bio = _as_str(profile_data.get("bio"))
    html_url = _as_str(profile_data.get("html_url"))
    blog = _as_str(profile_data.get("blog"))

    emails = [email] if email else []
    location = Location(raw=location_raw) if location_raw else None

    links: list[LinkEntry] = []
    if html_url:
        links.append(LinkEntry(url=html_url, label=GITHUB_LINK_LABEL))
    if blog:
        links.append(LinkEntry(url=blog, label=BLOG_LINK_LABEL))

    skills = _extract_languages(repositories)

    provenance: list[ProvenanceEntry] = []
    if full_name:
        _append_provenance(provenance, "full_name")
    if emails:
        _append_provenance(provenance, "emails")
    if location:
        _append_provenance(provenance, "location")
    if bio:
        _append_provenance(provenance, "headline")
    if links:
        _append_provenance(provenance, "links")
    if skills:
        _append_provenance(provenance, "skills", method=ProvenanceMethod.EXTRACTED)

    try:
        return CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name=full_name,
            emails=emails,
            phones=[],
            location=location,
            links=links,
            headline=bio,
            skills=skills,
            experience=[],
            education=[],
            provenance=provenance,
            overall_confidence=None,
        )
    except Exception as exc:
        logger.warning("Failed to build canonical profile from GitHub data: %s", exc)
        return None


def _parse_json_payload(payload: Any) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Extract profile and repository payloads from loaded JSON."""
    if not isinstance(payload, dict):
        logger.warning("GitHub JSON payload must be an object.")
        return None, []

    if isinstance(payload.get("profile"), dict):
        profile_data = payload["profile"]
        repositories = payload.get("repos", [])
    else:
        profile_data = {key: value for key, value in payload.items() if key != "repos"}
        repositories = payload.get("repos", [])

    if not isinstance(repositories, list):
        logger.warning("GitHub JSON repositories payload must be a list.")
        repositories = []

    return profile_data, repositories


def _load_json_file(path: Path) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Load GitHub profile data from a local JSON file."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Unable to read GitHub JSON file %s: %s", path, exc)
        return None, []

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.warning("Malformed GitHub JSON file %s: %s", path, exc)
        return None, []

    return _parse_json_payload(payload)


def _handle_api_error(response: Response, username: str, resource: str) -> None:
    """Log warnings for unsuccessful GitHub API responses."""
    if response.status_code == 404:
        logger.warning("GitHub %s not found for username '%s'.", resource, username)
        return

    if response.status_code in {403, 429}:
        logger.warning(
            "GitHub API rate limit or forbidden response for '%s' (%s): %s",
            username,
            resource,
            response.status_code,
        )
        return

    logger.warning(
        "Unexpected GitHub API response for '%s' (%s): %s",
        username,
        resource,
        response.status_code,
    )


def _fetch_json(
    session: Session,
    url: str,
    username: str,
    resource: str,
    timeout: float,
) -> Any | None:
    """Perform a GET request and return parsed JSON when successful."""
    try:
        response = session.get(
            url,
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json"},
        )
    except requests.Timeout:
        logger.warning("GitHub API timeout while fetching %s for '%s'.", resource, username)
        return None
    except requests.RequestException as exc:
        logger.warning(
            "GitHub API network failure while fetching %s for '%s': %s",
            resource,
            username,
            exc,
        )
        return None

    if response.status_code != 200:
        _handle_api_error(response, username, resource)
        return None

    try:
        return response.json()
    except ValueError as exc:
        logger.warning("Invalid JSON returned for GitHub %s ('%s'): %s", resource, username, exc)
        return None


def _fetch_profile(
    session: Session,
    username: str,
    timeout: float,
) -> dict[str, Any] | None:
    """Fetch a GitHub user profile from the REST API."""
    url = f"{API_BASE_URL}/users/{username}"
    payload = _fetch_json(session, url, username, "profile", timeout)
    if isinstance(payload, dict):
        return payload
    return None


def _fetch_repositories(
    session: Session,
    username: str,
    timeout: float,
) -> list[dict[str, Any]]:
    """Fetch public repositories for a GitHub user."""
    url = f"{API_BASE_URL}/users/{username}/repos"
    payload = _fetch_json(session, url, username, "repositories", timeout)

    if payload is None:
        return []

    if not isinstance(payload, list):
        logger.warning("Unexpected GitHub repositories payload for '%s'.", username)
        return []

    repositories = [repo for repo in payload if isinstance(repo, dict)]
    if not repositories:
        logger.warning("No repositories found for GitHub user '%s'.", username)

    return repositories


def _fetch_from_api(
    session: Session,
    username: str,
    timeout: float,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Fetch GitHub profile and repository data from the REST API."""
    cleaned_username = username.strip()
    if not cleaned_username:
        logger.warning("GitHub username is empty.")
        return None, []

    profile_data = _fetch_profile(session, cleaned_username, timeout)
    if profile_data is None:
        return None, []

    repositories = _fetch_repositories(session, cleaned_username, timeout)
    return profile_data, repositories


class GitHubProfileParser(SourceParser):
    """Parse GitHub profile data into a canonical candidate profile."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: Session | None = None,
    ) -> None:
        self._timeout = timeout
        self._session = session or requests.Session()

    @property
    def source_id(self) -> str:
        return SOURCE_ID

    def parse(self, source: str | Path) -> list[CanonicalProfile]:
        path = Path(source)

        if path.exists() and path.is_file():
            profile_data, repositories = _load_json_file(path)
        else:
            profile_data, repositories = _fetch_from_api(
                self._session,
                str(source),
                self._timeout,
            )

        if profile_data is None:
            return []

        profile = _profile_to_canonical(profile_data, repositories)
        if profile is None:
            return []

        return [profile]

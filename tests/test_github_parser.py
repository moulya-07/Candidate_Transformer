"""Unit tests for the GitHub profile parser."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.models.provenance import ProvenanceMethod
from src.parsers.github import GitHubProfileParser


@pytest.fixture
def parser() -> GitHubProfileParser:
    return GitHubProfileParser(session=requests.Session())


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload = {
        "login": "octocat",
        "name": "The Octocat",
        "email": "octocat@github.com",
        "bio": "GitHub mascot",
        "blog": "https://octocat.blog",
        "html_url": "https://github.com/octocat",
        "location": "San Francisco",
        "company": "GitHub",
    }
    payload.update(overrides)
    return payload


def _repo(language: str | None) -> dict[str, str | None]:
    return {"language": language}


def _mock_response(
    status_code: int,
    json_data: object | None = None,
    *,
    raise_json_error: bool = False,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if raise_json_error:
        response.json.side_effect = ValueError("invalid json")
    else:
        response.json.return_value = json_data
    return response


def test_parse_valid_api_response(parser: GitHubProfileParser) -> None:
    profile = _profile_payload()
    repos = [_repo("Python"), _repo("JavaScript"), _repo("Python")]

    with patch.object(
        parser._session,
        "get",
        side_effect=[
            _mock_response(200, profile),
            _mock_response(200, repos),
        ],
    ) as mock_get:
        profiles = parser.parse("octocat")

    assert len(profiles) == 1
    result = profiles[0]
    assert result.full_name == "The Octocat"
    assert result.emails == ["octocat@github.com"]
    assert result.phones == []
    assert result.location is not None
    assert result.location.raw == "San Francisco"
    assert result.headline == "GitHub mascot"
    assert result.skills == ["Python", "JavaScript"]
    assert result.experience == []
    assert result.education == []
    assert result.overall_confidence is None
    assert [link.url for link in result.links] == [
        "https://github.com/octocat",
        "https://octocat.blog",
    ]

    provenance_by_field = {entry.field: entry for entry in result.provenance}
    assert provenance_by_field["full_name"].method == ProvenanceMethod.DIRECT
    assert provenance_by_field["skills"].method == ProvenanceMethod.EXTRACTED
    assert all(entry.source == "github" for entry in result.provenance)

    assert mock_get.call_count == 2


def test_parse_valid_json_file(parser: GitHubProfileParser, tmp_path: Path) -> None:
    json_path = tmp_path / "github_profile.json"
    json_path.write_text(
        json.dumps(
            {
                "profile": _profile_payload(name=None),
                "repos": [_repo("Go"), _repo("Rust")],
            }
        ),
        encoding="utf-8",
    )

    profiles = parser.parse(json_path)

    assert len(profiles) == 1
    result = profiles[0]
    assert result.full_name == "octocat"
    assert result.skills == ["Go", "Rust"]


def test_parse_missing_email(parser: GitHubProfileParser) -> None:
    profile = _profile_payload(email=None)

    with patch.object(
        parser._session,
        "get",
        side_effect=[
            _mock_response(200, profile),
            _mock_response(200, []),
        ],
    ):
        profiles = parser.parse("octocat")

    assert len(profiles) == 1
    assert profiles[0].emails == []
    assert "emails" not in {entry.field for entry in profiles[0].provenance}


def test_parse_missing_bio(parser: GitHubProfileParser) -> None:
    profile = _profile_payload(bio="")

    with patch.object(
        parser._session,
        "get",
        side_effect=[
            _mock_response(200, profile),
            _mock_response(200, []),
        ],
    ):
        profiles = parser.parse("octocat")

    assert len(profiles) == 1
    assert profiles[0].headline is None
    assert "headline" not in {entry.field for entry in profiles[0].provenance}


def test_parse_no_repositories(parser: GitHubProfileParser) -> None:
    profile = _profile_payload()

    with patch.object(
        parser._session,
        "get",
        side_effect=[
            _mock_response(200, profile),
            _mock_response(200, []),
        ],
    ):
        profiles = parser.parse("octocat")

    assert len(profiles) == 1
    assert profiles[0].skills == []
    assert "skills" not in {entry.field for entry in profiles[0].provenance}


def test_parse_404_response(parser: GitHubProfileParser) -> None:
    with patch.object(
        parser._session,
        "get",
        return_value=_mock_response(404, {"message": "Not Found"}),
    ):
        profiles = parser.parse("missing-user")

    assert profiles == []


def test_parse_malformed_json_file(parser: GitHubProfileParser, tmp_path: Path) -> None:
    json_path = tmp_path / "broken.json"
    json_path.write_text("{not valid json", encoding="utf-8")

    profiles = parser.parse(json_path)

    assert profiles == []


def test_parse_api_timeout(parser: GitHubProfileParser) -> None:
    with patch.object(
        parser._session,
        "get",
        side_effect=requests.Timeout("timed out"),
    ):
        profiles = parser.parse("octocat")

    assert profiles == []


def test_parse_duplicate_repository_languages(parser: GitHubProfileParser) -> None:
    profile = _profile_payload()
    repos = [_repo("Python"), _repo("Ruby"), _repo("Python"), _repo("Ruby")]

    with patch.object(
        parser._session,
        "get",
        side_effect=[
            _mock_response(200, profile),
            _mock_response(200, repos),
        ],
    ):
        profiles = parser.parse("octocat")

    assert profiles[0].skills == ["Python", "Ruby"]


def test_parse_invalid_api_json(parser: GitHubProfileParser) -> None:
    with patch.object(
        parser._session,
        "get",
        return_value=_mock_response(200, None, raise_json_error=True),
    ):
        profiles = parser.parse("octocat")

    assert profiles == []


def test_parse_rate_limited_response(parser: GitHubProfileParser) -> None:
    with patch.object(
        parser._session,
        "get",
        return_value=_mock_response(403, {"message": "rate limit exceeded"}),
    ):
        profiles = parser.parse("octocat")

    assert profiles == []

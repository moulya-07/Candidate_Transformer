"""Unit tests for field normalizers."""

from __future__ import annotations

import pytest

from src.normalizers.date import normalize_date
from src.normalizers.email import normalize_email
from src.normalizers.name import normalize_name
from src.normalizers.phone import normalize_phone
from src.normalizers.skill import normalize_skill, normalize_skill_list
from src.normalizers.url import normalize_url


class TestNormalizePhone:
    def test_valid_us_number(self) -> None:
        assert normalize_phone("+1 415 555 2671") == "+14155552671"

    def test_valid_international_number(self) -> None:
        assert normalize_phone("+44 20 7946 0958") == "+442079460958"

    def test_invalid_number(self) -> None:
        assert normalize_phone("not-a-phone") is None

    def test_none_input(self) -> None:
        assert normalize_phone(None) is None

    def test_empty_string(self) -> None:
        assert normalize_phone("") is None

    def test_whitespace_only(self) -> None:
        assert normalize_phone("   ") is None


class TestNormalizeEmail:
    def test_valid_email(self) -> None:
        assert normalize_email("  Jane@Example.COM  ") == "jane@example.com"

    def test_invalid_email(self) -> None:
        assert normalize_email("not-an-email") is None
        assert normalize_email("@missing-local.com") is None
        assert normalize_email("missing-domain@") is None

    def test_none_input(self) -> None:
        assert normalize_email(None) is None

    def test_empty_string(self) -> None:
        assert normalize_email("") is None

    def test_whitespace_only(self) -> None:
        assert normalize_email("   ") is None


class TestNormalizeName:
    def test_trims_and_collapses_spaces(self) -> None:
        assert normalize_name("  John   Doe  ") == "John Doe"

    def test_preserves_capitalization(self) -> None:
        assert normalize_name("McDonald") == "McDonald"
        assert normalize_name("de la Cruz") == "de la Cruz"

    def test_none_input(self) -> None:
        assert normalize_name(None) is None

    def test_empty_string(self) -> None:
        assert normalize_name("") is None

    def test_whitespace_only(self) -> None:
        assert normalize_name("   ") is None


class TestNormalizeSkill:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("py", "Python"),
            ("PYTHON3", "Python"),
            ("js", "JavaScript"),
            ("nodejs", "Node.js"),
            ("reactjs", "React"),
            ("docker", "Docker"),
        ],
    )
    def test_known_aliases(self, raw: str, expected: str) -> None:
        assert normalize_skill(raw) == expected

    def test_unknown_skill_is_cleaned(self) -> None:
        assert normalize_skill("  Kubernetes  ") == "Kubernetes"

    def test_none_input(self) -> None:
        assert normalize_skill(None) == ""

    def test_empty_string(self) -> None:
        assert normalize_skill("") == ""

    def test_skill_list_deduplicates(self) -> None:
        assert normalize_skill_list(["py", "Python", "js", "javascript", ""]) == [
            "Python",
            "JavaScript",
        ]

    def test_skill_list_preserves_first_canonical_order(self) -> None:
        assert normalize_skill_list(["docker", "DOCKER", "React", "reactjs"]) == [
            "Docker",
            "React",
        ]


class TestNormalizeDate:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Jan 2024", "2024-01"),
            ("January 2024", "2024-01"),
            ("2024/01", "2024-01"),
            ("2024-01", "2024-01"),
            ("01-2024", "2024-01"),
        ],
    )
    def test_valid_formats(self, raw: str, expected: str) -> None:
        assert normalize_date(raw) == expected

    def test_invalid_date(self) -> None:
        assert normalize_date("not-a-date") is None

    def test_none_input(self) -> None:
        assert normalize_date(None) is None

    def test_empty_string(self) -> None:
        assert normalize_date("") is None

    def test_whitespace_only(self) -> None:
        assert normalize_date("   ") is None


class TestNormalizeUrl:
    def test_adds_https_prefix(self) -> None:
        assert normalize_url("example.com") == "https://example.com"

    def test_removes_trailing_slash(self) -> None:
        assert normalize_url("https://example.com/") == "https://example.com"
        assert normalize_url("https://example.com/api/") == "https://example.com/api"

    def test_upgrades_http_to_https(self) -> None:
        assert normalize_url("http://example.com/path/") == "https://example.com/path"

    def test_trims_whitespace(self) -> None:
        assert normalize_url("  https://example.com  ") == "https://example.com"

    def test_invalid_url(self) -> None:
        assert normalize_url("not a url") is None
        assert normalize_url("://missing-scheme") is None

    def test_none_input(self) -> None:
        assert normalize_url(None) is None

    def test_empty_string(self) -> None:
        assert normalize_url("") is None

    def test_whitespace_only(self) -> None:
        assert normalize_url("   ") is None

    def test_preserves_query_string(self) -> None:
        assert (
            normalize_url("https://example.com/search?q=test")
            == "https://example.com/search?q=test"
        )

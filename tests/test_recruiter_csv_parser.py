"""Unit tests for the recruiter CSV parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.provenance import ProvenanceMethod
from src.parsers.recruiter_csv import RecruiterCsvParser


@pytest.fixture
def parser() -> RecruiterCsvParser:
    return RecruiterCsvParser()


def _write_csv(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_valid_csv(parser: RecruiterCsvParser, tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "candidates.csv",
        "name,email,phone,current_company,title,location\n"
        "Jane Doe,jane@example.com,+1 555 0100,Acme Corp,Engineer,San Francisco\n"
        "John Smith,john@example.com,,Beta LLC,Manager,New York\n",
    )

    profiles = parser.parse(csv_path)

    assert len(profiles) == 2
    assert parser.source_id == "recruiter_csv"

    first = profiles[0]
    assert first.candidate_id
    assert first.full_name == "Jane Doe"
    assert first.emails == ["jane@example.com"]
    assert first.phones == ["+1 555 0100"]
    assert first.headline == "Engineer at Acme Corp"
    assert first.location is not None
    assert first.location.raw == "San Francisco"
    assert first.links == []
    assert first.skills == []
    assert first.experience == []
    assert first.education == []
    assert first.overall_confidence is None

    provenance_fields = {entry.field for entry in first.provenance}
    assert provenance_fields == {
        "full_name",
        "emails",
        "phones",
        "headline",
        "location",
    }
    assert all(entry.source == "recruiter_csv" for entry in first.provenance)
    assert all(entry.method == ProvenanceMethod.DIRECT for entry in first.provenance)

    second = profiles[1]
    assert second.full_name == "John Smith"
    assert second.phones == []
    assert second.headline == "Manager at Beta LLC"


def test_parse_missing_optional_columns(
    parser: RecruiterCsvParser,
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(
        tmp_path / "partial.csv",
        "name,email\n"
        "Alice Example,alice@example.com\n",
    )

    profiles = parser.parse(csv_path)

    assert len(profiles) == 1
    profile = profiles[0]
    assert profile.full_name == "Alice Example"
    assert profile.emails == ["alice@example.com"]
    assert profile.phones == []
    assert profile.headline is None
    assert profile.location is None
    assert {entry.field for entry in profile.provenance} == {"full_name", "emails"}


def test_parse_ignores_unknown_columns(
    parser: RecruiterCsvParser,
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(
        tmp_path / "extra_columns.csv",
        "name,email,internal_id,notes\n"
        "Bob Example,bob@example.com,123,ignore me\n",
    )

    profiles = parser.parse(csv_path)

    assert len(profiles) == 1
    assert profiles[0].full_name == "Bob Example"
    assert profiles[0].emails == ["bob@example.com"]


def test_parse_empty_csv(parser: RecruiterCsvParser, tmp_path: Path) -> None:
    csv_path = _write_csv(tmp_path / "empty.csv", "")

    profiles = parser.parse(csv_path)

    assert profiles == []


def test_parse_csv_with_headers_only(
    parser: RecruiterCsvParser,
    tmp_path: Path,
) -> None:
    csv_path = _write_csv(
        tmp_path / "headers_only.csv",
        "name,email,phone,current_company,title,location\n",
    )

    profiles = parser.parse(csv_path)

    assert profiles == []


def test_parse_malformed_csv(parser: RecruiterCsvParser, tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "malformed.csv",
        'name,email\n'
        '"unclosed quote,value\n'
        "Valid Name,valid@example.com\n",
    )

    profiles = parser.parse(csv_path)

    assert profiles == []


def test_parse_missing_csv(parser: RecruiterCsvParser, tmp_path: Path) -> None:
    missing_path = tmp_path / "does_not_exist.csv"

    profiles = parser.parse(missing_path)

    assert profiles == []


def test_parse_skips_blank_row(parser: RecruiterCsvParser, tmp_path: Path) -> None:
    csv_path = _write_csv(
        tmp_path / "blank_row.csv",
        "name,email,phone\n"
        "Valid User,valid@example.com,123\n"
        ",,\n"
        "Another User,another@example.com,456\n",
    )

    profiles = parser.parse(csv_path)

    assert len(profiles) == 2
    assert profiles[0].full_name == "Valid User"
    assert profiles[1].full_name == "Another User"


def test_parse_invalid_encoding_fallback(
    parser: RecruiterCsvParser,
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "latin1.csv"
    csv_path.write_bytes(
        b"name,email\n"
        b"Caf\xe9 User,cafe@example.com\n"
    )

    profiles = parser.parse(csv_path)

    assert len(profiles) == 1
    assert profiles[0].full_name == "Café User"
    assert profiles[0].emails == ["cafe@example.com"]

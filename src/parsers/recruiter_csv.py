"""Recruiter CSV source parser."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from pandas import Series

from src.models.canonical import CanonicalProfile, Location
from src.models.provenance import ProvenanceEntry, ProvenanceMethod
from src.parsers.base import SourceParser

logger = logging.getLogger(__name__)

SOURCE_ID = "recruiter_csv"

COLUMN_NAME = "name"
COLUMN_EMAIL = "email"
COLUMN_PHONE = "phone"
COLUMN_CURRENT_COMPANY = "current_company"
COLUMN_TITLE = "title"
COLUMN_LOCATION = "location"

KNOWN_COLUMNS = frozenset(
    {
        COLUMN_NAME,
        COLUMN_EMAIL,
        COLUMN_PHONE,
        COLUMN_CURRENT_COMPANY,
        COLUMN_TITLE,
        COLUMN_LOCATION,
    }
)


def _is_blank(value: Any) -> bool:
    """Return True when a CSV cell is missing or empty."""
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _cell_to_str(value: Any) -> str:
    """Convert a CSV cell to a trimmed string."""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _get_cell(row: Series, column: str) -> str | None:
    """Read a known column from a row, returning None when absent or blank."""
    if column not in row.index:
        return None
    value = row[column]
    if _is_blank(value):
        return None
    return _cell_to_str(value)


def _build_headline(row: Series) -> str | None:
    """Derive headline from title and current_company without normalization."""
    title = _get_cell(row, COLUMN_TITLE)
    company = _get_cell(row, COLUMN_CURRENT_COMPANY)

    if title and company:
        return f"{title} at {company}"
    if title:
        return title
    if company:
        return company
    return None


def _append_provenance(
    provenance: list[ProvenanceEntry],
    field: str,
) -> None:
    """Record direct extraction provenance for a populated field."""
    provenance.append(
        ProvenanceEntry(
            field=field,
            source=SOURCE_ID,
            method=ProvenanceMethod.DIRECT,
        )
    )


def _row_has_extractable_data(row: Series) -> bool:
    """Return True when at least one mapped CSV field contains a value."""
    return any(
        _get_cell(row, column) is not None
        for column in KNOWN_COLUMNS
    )


def _row_to_profile(row: Series, row_number: int) -> CanonicalProfile | None:
    """Map a single CSV row to a canonical profile."""
    if not _row_has_extractable_data(row):
        logger.warning(
            "Skipping CSV row %d: no extractable candidate values found.",
            row_number,
        )
        return None

    full_name = _get_cell(row, COLUMN_NAME)
    email = _get_cell(row, COLUMN_EMAIL)
    phone = _get_cell(row, COLUMN_PHONE)
    location_raw = _get_cell(row, COLUMN_LOCATION)
    headline = _build_headline(row)

    emails = [email] if email else []
    phones = [phone] if phone else []
    location = Location(raw=location_raw) if location_raw else None

    provenance: list[ProvenanceEntry] = []
    if full_name:
        _append_provenance(provenance, "full_name")
    if emails:
        _append_provenance(provenance, "emails")
    if phones:
        _append_provenance(provenance, "phones")
    if headline:
        _append_provenance(provenance, "headline")
    if location:
        _append_provenance(provenance, "location")

    try:
        return CanonicalProfile(
            candidate_id=str(uuid.uuid4()),
            full_name=full_name,
            emails=emails,
            phones=phones,
            location=location,
            links=[],
            headline=headline,
            skills=[],
            experience=[],
            education=[],
            provenance=provenance,
            overall_confidence=None,
        )
    except Exception as exc:
        logger.warning(
            "Skipping CSV row %d: failed to build canonical profile (%s).",
            row_number,
            exc,
        )
        return None


def _read_csv(path: Path) -> pd.DataFrame | None:
    """Read CSV file into a DataFrame, logging warnings on failure."""
    if not path.exists():
        logger.warning("CSV file not found: %s", path)
        return None

    if not path.is_file():
        logger.warning("CSV path is not a file: %s", path)
        return None

    encodings = ("utf-8", "latin-1")
    last_error: Exception | None = None

    for index, encoding in enumerate(encodings):
        try:
            frame = pd.read_csv(path, encoding=encoding)
            if index > 0:
                logger.warning(
                    "CSV file %s read using fallback encoding %s.",
                    path,
                    encoding,
                )
            return frame
        except UnicodeDecodeError as exc:
            last_error = exc
            logger.warning(
                "Invalid encoding for CSV file %s using %s: %s",
                path,
                encoding,
                exc,
            )
        except pd.errors.EmptyDataError:
            logger.warning("CSV file is empty: %s", path)
            return pd.DataFrame()
        except pd.errors.ParserError as exc:
            logger.warning("Malformed CSV file %s: %s", path, exc)
            return None

    logger.warning(
        "Unable to decode CSV file %s after trying %s: %s",
        path,
        ", ".join(encodings),
        last_error,
    )
    return None


class RecruiterCsvParser(SourceParser):
    """Parse recruiter CSV rows into canonical candidate profiles."""

    @property
    def source_id(self) -> str:
        return SOURCE_ID

    def parse(self, source: str | Path) -> list[CanonicalProfile]:
        path = Path(source)
        frame = _read_csv(path)

        if frame is None:
            return []

        if frame.empty:
            logger.warning("CSV file contains no data rows: %s", path)
            return []

        profiles: list[CanonicalProfile] = []
        for index, row in frame.iterrows():
            row_number = int(index) + 2  # account for header row and 0-based index
            profile = _row_to_profile(row, row_number)
            if profile is not None:
                profiles.append(profile)

        return profiles

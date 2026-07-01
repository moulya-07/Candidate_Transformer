"""Base parser interface for all data sources."""

from abc import ABC, abstractmethod
from pathlib import Path

from src.models.canonical import CanonicalProfile


class SourceParser(ABC):
    """Abstract parser that converts a raw source into canonical profiles."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Stable identifier for this data source (e.g. 'recruiter_csv')."""

    @abstractmethod
    def parse(self, source: str | Path) -> list[CanonicalProfile]:
        """Parse input and return one canonical profile per logical record."""

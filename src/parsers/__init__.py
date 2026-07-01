"""Source parsers — convert raw inputs into partial canonical profiles."""

from src.parsers.base import SourceParser
from src.parsers.github import GitHubProfileParser
from src.parsers.recruiter_csv import RecruiterCsvParser

__all__ = [
    "GitHubProfileParser",
    "RecruiterCsvParser",
    "SourceParser",
]

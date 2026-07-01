"""Output projection configuration models and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_NORMALIZERS: frozenset[str] = frozenset(
    {
        "E164",
        "canonical",
        "email",
        "url",
        "name",
        "date",
    }
)

MissingValuePolicy = Literal["null", "omit", "error"]


class FieldMapping(BaseModel):
    """Maps a canonical source path to an output field path."""

    path: str = Field(..., min_length=1, description="Output field path.")
    source: str | None = Field(
        default=None,
        alias="from",
        description="Canonical source path; defaults to ``path`` when omitted.",
    )
    normalize: str | None = Field(
        default=None,
        description="Optional normalizer to apply to the extracted value.",
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("path", "source")
    @classmethod
    def _validate_path_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Field path must not be blank.")
        return value

    @field_validator("normalize")
    @classmethod
    def _validate_normalizer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in ALLOWED_NORMALIZERS:
            allowed = ", ".join(sorted(ALLOWED_NORMALIZERS))
            raise ValueError(
                f"Unsupported normalize value '{value}'. Allowed values: {allowed}."
            )
        return value

    @property
    def source_path(self) -> str:
        """Return the canonical path to read from."""
        return self.source if self.source is not None else self.path


class OutputConfig(BaseModel):
    """Runtime configuration for projecting a canonical profile to output JSON."""

    fields: list[FieldMapping] = Field(
        ...,
        min_length=1,
        description="Ordered list of output field mappings.",
    )
    include_confidence: bool = False
    include_provenance: bool = False
    on_missing: MissingValuePolicy = "null"

    model_config = ConfigDict(extra="forbid")

    @field_validator("on_missing")
    @classmethod
    def _validate_on_missing(cls, value: str) -> str:
        if value not in ("null", "omit", "error"):
            raise ValueError(
                "on_missing must be one of: 'null', 'omit', 'error'."
            )
        return value


def load_config(source: dict[str, Any] | str | Path) -> OutputConfig:
    """Load and validate projection configuration from a dict, JSON string, or file."""
    if isinstance(source, Path):
        data = json.loads(source.read_text(encoding="utf-8"))
    elif isinstance(source, str):
        data = json.loads(source)
    else:
        data = source
    return OutputConfig.model_validate(data)

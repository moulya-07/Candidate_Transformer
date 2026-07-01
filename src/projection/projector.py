"""Canonical-to-output projector."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel

from src.models.canonical import CanonicalProfile
from src.normalizers.date import normalize_date
from src.normalizers.email import normalize_email
from src.normalizers.name import normalize_name
from src.normalizers.phone import normalize_phone
from src.normalizers.skill import normalize_skill
from src.normalizers.url import normalize_url
from src.projection.config import FieldMapping, MissingValuePolicy, OutputConfig

NORMALIZER_REGISTRY: dict[str, Callable[[Any], Any]] = {
    "E164": normalize_phone,
    "canonical": normalize_skill,
    "email": normalize_email,
    "url": normalize_url,
    "name": normalize_name,
    "date": normalize_date,
}


class ProjectionError(Exception):
    """Base error for projection failures."""


class MissingFieldError(ProjectionError):
    """Raised when a required field path cannot be resolved."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Missing field '{path}': {reason}")


class InvalidFieldPathError(ProjectionError):
    """Raised when a field path cannot be parsed."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid field path '{path}': {reason}")


class _AttrSegment:
    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


class _IndexSegment:
    __slots__ = ("index",)

    def __init__(self, index: int) -> None:
        self.index = index


class _ExpandSegment:
    __slots__ = ()


_MISSING = object()


def parse_field_path(path: str) -> list[_AttrSegment | _IndexSegment | _ExpandSegment]:
    """Parse a dotted field path into reusable traversal segments."""
    if not path or not path.strip():
        raise InvalidFieldPathError(path, "path must not be empty")

    segments: list[_AttrSegment | _IndexSegment | _ExpandSegment] = []
    for part in path.strip().split("."):
        if not part:
            raise InvalidFieldPathError(path, "path contains an empty segment")

        if part.endswith("[]"):
            attribute = part[:-2]
            if not attribute:
                raise InvalidFieldPathError(path, "array expansion requires a field name")
            segments.append(_AttrSegment(attribute))
            segments.append(_ExpandSegment())
            continue

        if "[" in part:
            if not part.endswith("]"):
                raise InvalidFieldPathError(path, f"malformed index segment '{part}'")

            attribute, index_part = part.split("[", maxsplit=1)
            index_text = index_part[:-1]
            if not attribute or not index_text.isdigit():
                raise InvalidFieldPathError(path, f"malformed index segment '{part}'")

            segments.append(_AttrSegment(attribute))
            segments.append(_IndexSegment(int(index_text)))
            continue

        segments.append(_AttrSegment(part))

    return segments


def _get_attribute(value: Any, name: str) -> Any:
    """Read an attribute or mapping key from a traversal value."""
    if value is None:
        return _MISSING

    if isinstance(value, str) and name == "name":
        return value

    if isinstance(value, BaseModel):
        if not hasattr(value, name):
            return _MISSING
        return getattr(value, name)

    if isinstance(value, dict):
        if name not in value:
            return _MISSING
        return value[name]

    if hasattr(value, name):
        return getattr(value, name)

    return _MISSING


def resolve_field_path(profile: CanonicalProfile, path: str) -> Any:
    """Resolve a field path against a canonical profile.

    Returns the resolved value. Raises ``MissingFieldError`` when the path
    cannot be resolved and ``InvalidFieldPathError`` when the path is malformed.
    """
    segments = parse_field_path(path)
    result = _resolve_segments(profile, segments, 0, path)
    if result is _MISSING:
        raise MissingFieldError(path, "value is unavailable")
    return result


def _resolve_segments(
    value: Any,
    segments: list[_AttrSegment | _IndexSegment | _ExpandSegment],
    index: int,
    original_path: str,
) -> Any:
    if index >= len(segments):
        return value

    segment = segments[index]

    if isinstance(segment, _AttrSegment):
        next_value = _get_attribute(value, segment.name)
        if next_value is _MISSING:
            return _MISSING
        return _resolve_segments(next_value, segments, index + 1, original_path)

    if isinstance(segment, _IndexSegment):
        if not isinstance(value, list):
            return _MISSING
        if segment.index < 0 or segment.index >= len(value):
            return _MISSING
        return _resolve_segments(value[segment.index], segments, index + 1, original_path)

    if not isinstance(value, list):
        return _MISSING

    if index + 1 >= len(segments):
        return value

    expanded: list[Any] = []
    for item in value:
        resolved_item = _resolve_segments(item, segments, index + 1, original_path)
        if resolved_item is not _MISSING:
            expanded.append(resolved_item)
    return expanded


def _apply_normalizer(value: Any, normalizer_name: str | None) -> Any:
    """Apply a configured normalizer to a scalar or list value."""
    if normalizer_name is None:
        return value

    normalizer = NORMALIZER_REGISTRY[normalizer_name]
    if isinstance(value, list):
        return [normalizer(item) for item in value]
    return normalizer(value)


def _to_json_value(value: Any) -> Any:
    """Convert resolved values into JSON-compatible Python objects."""
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_json_value(item) for key, item in value.items()}
    return value


def _set_nested_output(output: dict[str, Any], path: str, value: Any) -> None:
    """Assign a value to a potentially dotted output path."""
    parts = path.split(".")
    current = output
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


class Projector:
    """Project canonical profiles into runtime-configurable output dictionaries."""

    def project(self, profile: CanonicalProfile, config: OutputConfig) -> dict[str, Any]:
        """Transform ``profile`` into output JSON according to ``config``.

        The input profile is never modified. Returns a plain dictionary suitable
        for JSON serialization.
        """
        output: dict[str, Any] = {}

        for field_mapping in config.fields:
            self._project_field(profile, field_mapping, config.on_missing, output)

        if config.include_confidence:
            output["overall_confidence"] = profile.overall_confidence

        if config.include_provenance:
            output["provenance"] = [
                entry.model_dump(mode="json") for entry in profile.provenance
            ]

        return output

    def _project_field(
        self,
        profile: CanonicalProfile,
        field_mapping: FieldMapping,
        on_missing: MissingValuePolicy,
        output: dict[str, Any],
    ) -> None:
        source_path = field_mapping.source_path

        try:
            value = resolve_field_path(profile, source_path)
        except MissingFieldError as exc:
            self._apply_missing_policy(
                output_path=field_mapping.path,
                source_path=source_path,
                policy=on_missing,
                reason=exc.reason,
                output=output,
            )
            return
        except InvalidFieldPathError:
            if on_missing == "error":
                raise
            if on_missing == "omit":
                return
            _set_nested_output(output, field_mapping.path, None)
            return

        value = _apply_normalizer(value, field_mapping.normalize)
        _set_nested_output(output, field_mapping.path, _to_json_value(value))

    def _apply_missing_policy(
        self,
        output_path: str,
        source_path: str,
        policy: MissingValuePolicy,
        reason: str,
        output: dict[str, Any],
    ) -> None:
        if policy == "error":
            raise MissingFieldError(source_path, reason)
        if policy == "omit":
            return
        _set_nested_output(output, output_path, None)

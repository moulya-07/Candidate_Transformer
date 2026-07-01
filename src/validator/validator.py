"""Output validation wrapper."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError as PydanticValidationError

from src.normalizers.date import normalize_date
from src.normalizers.email import normalize_email
from src.normalizers.name import normalize_name
from src.normalizers.phone import normalize_phone
from src.normalizers.skill import normalize_skill
from src.normalizers.url import normalize_url
from src.projection.config import OutputConfig
from src.validator.output_schema import (
    ValidationConfig,
    ValidationFieldSpec,
    build_output_model,
    collect_field_specs,
)

NormalizerFn = Callable[[Any], Any]

_NORMALIZER_REGISTRY: dict[str, NormalizerFn] = {
    "E164": normalize_phone,
    "canonical": normalize_skill,
    "email": normalize_email,
    "url": normalize_url,
    "name": normalize_name,
    "date": normalize_date,
}


class OutputValidationError(Exception):
    """Raised when projected output fails schema validation."""

    def __init__(
        self,
        message: str,
        *,
        field: str,
        expected_type: str,
        actual_value: Any,
    ) -> None:
        self.field = field
        self.expected_type = expected_type
        self.actual_value = actual_value
        super().__init__(message)


class MissingRequiredFieldError(OutputValidationError):
    """Raised when a required output field is absent."""


class WrongTypeError(OutputValidationError):
    """Raised when a field value does not match the expected type."""


class InvalidNormalizationError(OutputValidationError):
    """Raised when a normalized field value is not in canonical form."""


class InvalidNestedStructureError(OutputValidationError):
    """Raised when nested object or array structure is invalid."""


class ConfigValidationError(OutputValidationError):
    """Raised when validation configuration is unknown or invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            field="<config>",
            expected_type="valid validation configuration",
            actual_value=None,
        )


class OutputValidator:
    """Validate projected output dictionaries against runtime schema configuration."""

    def validate(
        self,
        output_dict: dict[str, Any],
        config: ValidationConfig | OutputConfig | dict[str, Any],
    ) -> dict[str, Any]:
        """Validate ``output_dict`` and return it unchanged when valid."""
        validation_config = _coerce_config(config)
        model_type = _build_model(validation_config)

        try:
            model_type.model_validate(output_dict)
        except PydanticValidationError as exc:
            raise _translate_validation_error(exc) from exc

        _validate_normalization(output_dict, collect_field_specs(validation_config))
        return output_dict


def _coerce_config(
    config: ValidationConfig | OutputConfig | dict[str, Any],
) -> ValidationConfig:
    if isinstance(config, ValidationConfig):
        return config

    if isinstance(config, OutputConfig):
        return _validation_config_from_output_config(config)

    try:
        return ValidationConfig.model_validate(config)
    except PydanticValidationError as exc:
        raise ConfigValidationError(_format_config_error(exc)) from exc
    except ValueError as exc:
        raise ConfigValidationError(str(exc)) from exc


def _validation_config_from_output_config(config: OutputConfig) -> ValidationConfig:
    """Adapt projection configuration when explicit validation rules are embedded."""
    fields: list[ValidationFieldSpec] = []

    for mapping in config.fields:
        raw_field = mapping.model_dump(by_alias=True)
        if "type" not in raw_field:
            raise ConfigValidationError(
                "OutputConfig field mappings must include 'type' for validation. "
                f"Missing on path '{mapping.path}'."
            )
        fields.append(ValidationFieldSpec.model_validate(raw_field))

    return ValidationConfig(
        fields=fields,
        include_confidence=config.include_confidence,
        include_provenance=config.include_provenance,
    )


def _build_model(config: ValidationConfig) -> type[BaseModel]:
    try:
        return build_output_model(config)
    except ValueError as exc:
        raise ConfigValidationError(str(exc)) from exc


def _translate_validation_error(exc: PydanticValidationError) -> OutputValidationError:
    errors = exc.errors(include_url=False)
    if not errors:
        return InvalidNestedStructureError(
            "Output validation failed.",
            field="<root>",
            expected_type="valid output",
            actual_value=None,
        )

    first = errors[0]
    field_path = _format_field_path(first.get("loc", ()))
    error_type = first.get("type", "")
    message = first.get("msg", "Validation failed.")
    input_value = first.get("input")
    expected = _expected_type_from_error(first)

    if error_type == "missing":
        return MissingRequiredFieldError(
            f"Missing required field '{field_path}'.",
            field=field_path,
            expected_type=expected,
            actual_value=None,
        )

    if error_type in {"extra_forbidden", "list_type", "dict_type", "model_type"}:
        return InvalidNestedStructureError(
            f"Invalid nested structure at '{field_path}': {message}",
            field=field_path,
            expected_type=expected,
            actual_value=input_value,
        )

    return WrongTypeError(
        f"Wrong type for field '{field_path}': expected {expected}, got {type(input_value).__name__}.",
        field=field_path,
        expected_type=expected,
        actual_value=input_value,
    )


def _format_field_path(location: tuple[Any, ...]) -> str:
    parts: list[str] = []
    for item in location:
        if item == "value":
            continue
        if isinstance(item, int):
            parts[-1] = f"{parts[-1]}[{item}]"
        else:
            parts.append(str(item))
    return ".".join(parts) if parts else "<root>"


def _expected_type_from_error(error: dict[str, Any]) -> str:
    ctx = error.get("ctx") or {}
    if "expected" in ctx:
        return str(ctx["expected"])
    if error.get("type") == "missing":
        return "present value"
    return str(error.get("type", "valid value"))


def _format_config_error(exc: PydanticValidationError) -> str:
    messages = [
        f"{'.'.join(str(part) for part in err.get('loc', ()))}: {err.get('msg')}"
        for err in exc.errors(include_url=False)
    ]
    return "Invalid validation configuration: " + "; ".join(messages)


def _validate_normalization(
    output_dict: dict[str, Any],
    field_specs: list[ValidationFieldSpec],
) -> None:
    for spec in field_specs:
        if spec.normalize is None:
            continue

        normalizer = _NORMALIZER_REGISTRY.get(spec.normalize)
        if normalizer is None:
            raise ConfigValidationError(
                f"Unknown normalizer '{spec.normalize}' for field '{spec.path}'."
            )

        value = _get_value_at_path(output_dict, spec.path)
        if value is None:
            continue

        _assert_normalized_value(spec.path, value, normalizer, spec)


def _assert_normalized_value(
    path: str,
    value: Any,
    normalizer: NormalizerFn,
    spec: ValidationFieldSpec,
) -> None:
    if spec.type == "array" and isinstance(value, list):
        for index, item in enumerate(value):
            _assert_scalar_normalized(f"{path}[{index}]", item, normalizer)
        return

    _assert_scalar_normalized(path, value, normalizer)


def _assert_scalar_normalized(path: str, value: Any, normalizer: NormalizerFn) -> None:
    if not isinstance(value, str):
        raise InvalidNormalizationError(
            f"Invalid normalization result for field '{path}': expected normalized string.",
            field=path,
            expected_type="normalized string",
            actual_value=value,
        )

    normalized = normalizer(value)
    if normalized != value:
        raise InvalidNormalizationError(
            f"Invalid normalization result for field '{path}': "
            f"value '{value}' is not in normalized form (expected '{normalized}').",
            field=path,
            expected_type="normalized value",
            actual_value=value,
        )


def _get_value_at_path(data: dict[str, Any], path: str) -> Any:
    segments = path.replace("[]", "").split(".")
    current: Any = data

    for segment in segments:
        if not segment:
            continue
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]

    if isinstance(current, list) and len(segments) == 1:
        return current

    return current

"""Unit tests for the output validator."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.validator.output_schema import ValidationConfig, build_output_model
from src.validator.validator import (
    ConfigValidationError,
    InvalidNestedStructureError,
    InvalidNormalizationError,
    MissingRequiredFieldError,
    OutputValidationError,
    OutputValidator,
    WrongTypeError,
)


@pytest.fixture
def validator() -> OutputValidator:
    return OutputValidator()


def _config(**overrides: object) -> ValidationConfig:
    defaults: dict[str, object] = {
        "fields": [{"path": "full_name", "type": "string", "required": True}],
        "include_confidence": False,
        "include_provenance": False,
        "allow_extra": False,
    }
    defaults.update(overrides)
    return ValidationConfig.model_validate(defaults)


class TestValidOutput:
    def test_valid_simple_output(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {"path": "full_name", "type": "string", "required": True},
                {"path": "years_experience", "type": "number", "required": True},
                {"path": "active", "type": "boolean", "required": False},
            ]
        )
        output = {
            "full_name": "Jane Doe",
            "years_experience": 6,
            "active": True,
        }

        result = validator.validate(output, config)

        assert result is output
        assert result == output

    def test_valid_nested_output(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {"path": "location.city", "type": "string", "required": True},
                {"path": "location.country", "type": "string", "required": True},
            ]
        )
        output = {"location": {"city": "San Francisco", "country": "USA"}}

        assert validator.validate(output, config) == output

    def test_valid_array_output(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {
                    "path": "emails",
                    "type": "array",
                    "item_type": "string",
                    "required": True,
                }
            ]
        )
        output = {"emails": ["jane@example.com", "jane.doe@work.com"]}

        assert validator.validate(output, config) == output

    def test_valid_with_confidence_and_provenance(
        self, validator: OutputValidator
    ) -> None:
        config = _config(
            fields=[{"path": "full_name", "type": "string", "required": True}],
            include_confidence=True,
            include_provenance=True,
        )
        output = {
            "full_name": "Jane Doe",
            "overall_confidence": 0.93,
            "provenance": [
                {
                    "field": "full_name",
                    "source": "recruiter_csv",
                    "method": "direct",
                }
            ],
        }

        assert validator.validate(output, config) == output

    def test_valid_normalized_email(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {
                    "path": "primary_email",
                    "type": "string",
                    "required": True,
                    "normalize": "email",
                }
            ]
        )
        output = {"primary_email": "jane@example.com"}

        assert validator.validate(output, config) == output


class TestMissingRequiredField:
    def test_missing_top_level_field(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[{"path": "full_name", "type": "string", "required": True}]
        )

        with pytest.raises(MissingRequiredFieldError) as exc_info:
            validator.validate({}, config)

        error = exc_info.value
        assert error.field == "full_name"
        assert error.actual_value is None
        assert "required" in str(error).lower()

    def test_missing_nested_field(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {"path": "location.city", "type": "string", "required": True},
            ]
        )

        with pytest.raises(MissingRequiredFieldError) as exc_info:
            validator.validate({"location": {}}, config)

        assert exc_info.value.field == "location.city"


class TestWrongPrimitiveType:
    def test_wrong_string_type(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[{"path": "full_name", "type": "string", "required": True}]
        )

        with pytest.raises(WrongTypeError) as exc_info:
            validator.validate({"full_name": 123}, config)

        error = exc_info.value
        assert error.field == "full_name"
        assert error.expected_type
        assert error.actual_value == 123

    def test_wrong_number_type(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[{"path": "years_experience", "type": "number", "required": True}]
        )

        with pytest.raises(WrongTypeError) as exc_info:
            validator.validate({"years_experience": "six"}, config)

        assert exc_info.value.field == "years_experience"
        assert exc_info.value.actual_value == "six"

    def test_wrong_boolean_type(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[{"path": "active", "type": "boolean", "required": True}]
        )

        with pytest.raises(WrongTypeError) as exc_info:
            validator.validate({"active": "yes"}, config)

        assert exc_info.value.field == "active"


class TestWrongArrayType:
    def test_array_expected_but_scalar_provided(
        self, validator: OutputValidator
    ) -> None:
        config = _config(
            fields=[
                {
                    "path": "emails",
                    "type": "array",
                    "item_type": "string",
                    "required": True,
                }
            ]
        )

        with pytest.raises(InvalidNestedStructureError) as exc_info:
            validator.validate({"emails": "jane@example.com"}, config)

        assert exc_info.value.field == "emails"

    def test_array_with_wrong_item_type(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {
                    "path": "scores",
                    "type": "array",
                    "item_type": "number",
                    "required": True,
                }
            ]
        )

        with pytest.raises(WrongTypeError) as exc_info:
            validator.validate({"scores": [1, "two", 3]}, config)

        assert "scores" in exc_info.value.field


class TestWrongNestedObject:
    def test_nested_object_expected_scalar(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {"path": "location.city", "type": "string", "required": True},
            ]
        )

        with pytest.raises(InvalidNestedStructureError) as exc_info:
            validator.validate({"location": "San Francisco"}, config)

        assert exc_info.value.field == "location"

    def test_nested_object_wrong_child_type(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {"path": "location.city", "type": "string", "required": True},
                {"path": "location.zip", "type": "number", "required": True},
            ]
        )

        with pytest.raises(WrongTypeError) as exc_info:
            validator.validate({"location": {"city": "SF", "zip": "94107"}}, config)

        assert exc_info.value.field == "location.zip"


class TestNullHandling:
    def test_null_allowed_for_optional_field(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {"path": "headline", "type": "string", "required": False},
            ]
        )

        assert validator.validate({"headline": None}, config) == {"headline": None}
        assert validator.validate({}, config) == {}

    def test_null_not_allowed_for_required_field(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[{"path": "full_name", "type": "string", "required": True}]
        )

        with pytest.raises(WrongTypeError) as exc_info:
            validator.validate({"full_name": None}, config)

        assert exc_info.value.field == "full_name"
        assert exc_info.value.actual_value is None

    def test_null_only_field(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[{"path": "placeholder", "type": "null", "required": False}]
        )

        assert validator.validate({"placeholder": None}, config) == {"placeholder": None}

        with pytest.raises(WrongTypeError):
            validator.validate({"placeholder": "value"}, config)


class TestExtraFieldHandling:
    def test_extra_fields_forbidden_by_default(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[{"path": "full_name", "type": "string", "required": True}]
        )

        with pytest.raises(OutputValidationError) as exc_info:
            validator.validate(
                {"full_name": "Jane Doe", "unexpected": "value"},
                config,
            )

        assert "unexpected" in exc_info.value.field or "extra" in str(exc_info.value).lower()

    def test_extra_fields_allowed_when_configured(
        self, validator: OutputValidator
    ) -> None:
        config = _config(
            fields=[{"path": "full_name", "type": "string", "required": True}],
            allow_extra=True,
        )
        output = {"full_name": "Jane Doe", "legacy_id": str(uuid.uuid4())}

        assert validator.validate(output, config) is output


class TestInvalidConfiguration:
    def test_unknown_field_type(self) -> None:
        with pytest.raises(PydanticValidationError):
            ValidationConfig.model_validate(
                {
                    "fields": [
                        {"path": "full_name", "type": "text", "required": True},
                    ]
                }
            )

    def test_unknown_normalizer(self) -> None:
        with pytest.raises(PydanticValidationError):
            ValidationConfig.model_validate(
                {
                    "fields": [
                        {
                            "path": "full_name",
                            "type": "string",
                            "required": True,
                            "normalize": "uppercase",
                        }
                    ]
                }
            )

    def test_duplicate_paths_rejected(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {"path": "full_name", "type": "string", "required": True},
                {"path": "full_name", "type": "string", "required": False},
            ]
        )

        with pytest.raises(ConfigValidationError):
            validator.validate({"full_name": "Jane Doe"}, config)

    def test_invalid_nested_path_index_not_supported(self) -> None:
        with pytest.raises(ValueError, match="indexed paths"):
            build_output_model(
                ValidationConfig.model_validate(
                    {
                        "fields": [
                            {
                                "path": "emails[0]",
                                "type": "string",
                                "required": True,
                            }
                        ]
                    }
                )
            )

    def test_invalid_normalization_result(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[
                {
                    "path": "primary_email",
                    "type": "string",
                    "required": True,
                    "normalize": "email",
                }
            ]
        )

        with pytest.raises(InvalidNormalizationError) as exc_info:
            validator.validate({"primary_email": "not-an-email"}, config)

        error = exc_info.value
        assert error.field == "primary_email"
        assert error.actual_value == "not-an-email"


class TestImmutability:
    def test_validator_does_not_mutate_output(self, validator: OutputValidator) -> None:
        config = _config(
            fields=[{"path": "full_name", "type": "string", "required": True}]
        )
        output = {"full_name": "Jane Doe"}
        snapshot = dict(output)

        result = validator.validate(output, config)

        assert result is output
        assert output == snapshot

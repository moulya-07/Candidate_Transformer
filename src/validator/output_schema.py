"""Dynamic output schema definition for projected JSON validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from src.projection.config import ALLOWED_NORMALIZERS

FieldType = Literal["string", "number", "boolean", "array", "object", "null"]

FIELD_TYPES: frozenset[str] = frozenset(get_args(FieldType))

_PYTHON_TYPE_MAP: dict[FieldType, type[Any]] = {
    "string": str,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


class ValidationFieldSpec(BaseModel):
    """Single output field validation rule aligned with projection field mappings."""

    path: str = Field(..., min_length=1, description="Output field path.")
    type: FieldType = Field(..., description="Expected JSON type for the field value.")
    required: bool = Field(default=True, description="Whether the field must be present.")
    normalize: str | None = Field(
        default=None,
        description="Optional normalizer whose output must match the projected value.",
    )
    item_type: FieldType | None = Field(
        default=None,
        description="Element type when ``type`` is ``array``; defaults to ``string``.",
    )

    model_config = ConfigDict(extra="forbid")

    @field_validator("path")
    @classmethod
    def _validate_path_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Field path must not be blank.")
        return value

    @field_validator("type")
    @classmethod
    def _validate_type(cls, value: str) -> str:
        if value not in FIELD_TYPES:
            allowed = ", ".join(sorted(FIELD_TYPES))
            raise ValueError(f"Unsupported type '{value}'. Allowed values: {allowed}.")
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

    @field_validator("item_type")
    @classmethod
    def _validate_item_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value not in FIELD_TYPES:
            allowed = ", ".join(sorted(FIELD_TYPES))
            raise ValueError(f"Unsupported item_type '{value}'. Allowed values: {allowed}.")
        return value


class ValidationConfig(BaseModel):
    """Runtime validation configuration mirroring projection output shape."""

    fields: list[ValidationFieldSpec] = Field(
        ...,
        min_length=1,
        description="Ordered list of output field validation rules.",
    )
    include_confidence: bool = False
    include_provenance: bool = False
    allow_extra: bool = False

    model_config = ConfigDict(extra="forbid")


@dataclass
class _SchemaNode:
    """Tree node used while assembling a nested output schema."""

    leaf_spec: ValidationFieldSpec | None = None
    children: dict[str, _SchemaNode] = field(default_factory=dict)
    array_item: _SchemaNode | None = None

    @property
    def is_leaf(self) -> bool:
        return self.leaf_spec is not None and not self.children and self.array_item is None


def _parse_path_segments(path: str) -> list[str | None]:
    """Parse a dotted output path into attribute names and array-expansion markers."""
    if not path or not path.strip():
        raise ValueError("Field path must not be empty.")

    segments: list[str | None] = []
    for part in path.strip().split("."):
        if not part:
            raise ValueError(f"Invalid field path '{path}': path contains an empty segment.")

        if part.endswith("[]"):
            attribute = part[:-2]
            if not attribute:
                raise ValueError(
                    f"Invalid field path '{path}': array expansion requires a field name."
                )
            segments.append(attribute)
            segments.append(None)
            continue

        if "[" in part:
            raise ValueError(
                f"Invalid field path '{path}': indexed paths are not supported for validation."
            )

        segments.append(part)

    return segments


def _insert_field(root: _SchemaNode, spec: ValidationFieldSpec) -> None:
    """Insert a field specification into the schema tree."""
    segments = _parse_path_segments(spec.path)
    node = root

    index = 0
    while index < len(segments):
        segment = segments[index]
        is_last = index == len(segments) - 1

        if segment is None:
            if node.array_item is None:
                node.array_item = _SchemaNode()
            node = node.array_item
            index += 1
            continue

        if is_last:
            if segment in node.children and not node.children[segment].is_leaf:
                raise ValueError(
                    f"Conflicting validation paths for '{spec.path}': "
                    "nested structure already defined."
                )
            if segment in node.children and node.children[segment].leaf_spec is not None:
                raise ValueError(
                    f"Duplicate validation path '{spec.path}' in configuration."
                )
            node.children[segment] = _SchemaNode(leaf_spec=spec)
            return

        if segment not in node.children:
            node.children[segment] = _SchemaNode()
        node = node.children[segment]
        index += 1


def _annotation_for_type(
    field_type: FieldType,
    *,
    required: bool,
    item_type: FieldType | None = None,
    nested_model: type[BaseModel] | None = None,
) -> tuple[Any, Any]:
    """Return a Pydantic field annotation and default for a schema type."""
    if field_type == "array":
        element_type = item_type or "string"
        if element_type == "object" and nested_model is not None:
            inner: Any = nested_model
        else:
            inner = _PYTHON_TYPE_MAP[element_type]
        annotation: Any = list[inner]  # type: ignore[valid-type]
    elif field_type == "object" and nested_model is not None:
        annotation = nested_model
    else:
        annotation = _PYTHON_TYPE_MAP[field_type]

    if not required:
        annotation = annotation | None
        return annotation, None

    return annotation, ...


def _build_model_from_node(name: str, node: _SchemaNode) -> type[BaseModel]:
    """Recursively build a Pydantic model from a schema tree node."""
    if node.array_item is not None and node.children:
        raise ValueError(
            f"Invalid schema node '{name}': cannot combine array items with object children."
        )

    if node.is_leaf:
        spec = node.leaf_spec
        assert spec is not None
        nested_model = None
        if spec.type == "object" and node.children:
            nested_model = _build_model_from_node(f"{name}_object", node)
        annotation, default = _annotation_for_type(
            spec.type,
            required=spec.required,
            item_type=spec.item_type,
            nested_model=nested_model,
        )
        return create_model(
            name,
            __config__=ConfigDict(extra="forbid", strict=True),
            value=(annotation, default),
        )

    field_definitions: dict[str, Any] = {}

    for child_name, child_node in node.children.items():
        if child_node.array_item is not None:
            item_node = child_node.array_item
            if item_node.is_leaf and item_node.leaf_spec is not None:
                item_spec = item_node.leaf_spec
                annotation, default = _annotation_for_type(
                    "array",
                    required=item_spec.required,
                    item_type=item_spec.item_type or item_spec.type,
                )
            else:
                item_model = _build_model_from_node(f"{name}_{child_name}_item", item_node)
                parent_required = _node_required(child_node, item_node)
                annotation, default = _annotation_for_type(
                    "array",
                    required=parent_required,
                    item_type="object",
                    nested_model=item_model,
                )
            field_definitions[child_name] = (annotation, default)
            continue

        if child_node.is_leaf:
            spec = child_node.leaf_spec
            assert spec is not None
            nested_model = None
            if spec.type == "object" and child_node.children:
                nested_model = _build_model_from_node(f"{name}_{child_name}", child_node)
            annotation, default = _annotation_for_type(
                spec.type,
                required=spec.required,
                item_type=spec.item_type,
                nested_model=nested_model,
            )
        else:
            nested_model = _build_model_from_node(f"{name}_{child_name}", child_node)
            annotation, default = _annotation_for_type(
                "object",
                required=_object_node_required(child_node),
                nested_model=nested_model,
            )

        field_definitions[child_name] = (annotation, default)

    extra_policy = "forbid"
    return create_model(
        name,
        __config__=ConfigDict(extra=extra_policy, strict=True),
        **field_definitions,
    )


def _node_required(parent: _SchemaNode, item_node: _SchemaNode) -> bool:
    if item_node.is_leaf and item_node.leaf_spec is not None:
        return item_node.leaf_spec.required
    return any(
        child.leaf_spec.required
        for child in _iter_leaf_specs(item_node)
        if child.leaf_spec is not None
    )


def _object_node_required(node: _SchemaNode) -> bool:
    specs = [child.leaf_spec for child in _iter_leaf_specs(node) if child.leaf_spec]
    if not specs:
        return False
    return any(spec.required for spec in specs)


def _iter_leaf_specs(node: _SchemaNode) -> list[_SchemaNode]:
    nodes: list[_SchemaNode] = []
    if node.is_leaf:
        nodes.append(node)
    for child in node.children.values():
        nodes.extend(_iter_leaf_specs(child))
    if node.array_item is not None:
        nodes.extend(_iter_leaf_specs(node.array_item))
    return nodes


def build_output_model(config: ValidationConfig) -> type[BaseModel]:
    """Build a strict Pydantic model that validates projected output shape."""
    root = _SchemaNode()
    seen_paths: set[str] = set()

    for field_spec in config.fields:
        if field_spec.path in seen_paths:
            raise ValueError(f"Duplicate validation path '{field_spec.path}' in configuration.")
        seen_paths.add(field_spec.path)
        _insert_field(root, field_spec)

    model_fields: dict[str, Any] = {}

    for child_name, child_node in root.children.items():
        if child_node.is_leaf:
            spec = child_node.leaf_spec
            assert spec is not None
            nested_model = None
            if spec.type == "object" and child_node.children:
                nested_model = _build_model_from_node(f"Output_{child_name}", child_node)
            annotation, default = _annotation_for_type(
                spec.type,
                required=spec.required,
                item_type=spec.item_type,
                nested_model=nested_model,
            )
        elif child_node.array_item is not None:
            item_node = child_node.array_item
            if item_node.is_leaf and item_node.leaf_spec is not None:
                item_spec = item_node.leaf_spec
                annotation, default = _annotation_for_type(
                    "array",
                    required=item_spec.required,
                    item_type=item_spec.item_type or item_spec.type,
                )
            else:
                item_model = _build_model_from_node(f"Output_{child_name}_item", item_node)
                annotation, default = _annotation_for_type(
                    "array",
                    required=_node_required(child_node, item_node),
                    item_type="object",
                    nested_model=item_model,
                )
        else:
            nested_model = _build_model_from_node(f"Output_{child_name}", child_node)
            annotation, default = _annotation_for_type(
                "object",
                required=_object_node_required(child_node),
                nested_model=nested_model,
            )

        model_fields[child_name] = (annotation, default)

    if config.include_confidence:
        model_fields["overall_confidence"] = (float | None, None)

    if config.include_provenance:
        model_fields["provenance"] = (list[dict[str, Any]] | None, None)

    extra_policy: Literal["forbid", "ignore"] = "ignore" if config.allow_extra else "forbid"
    return create_model(
        "ProjectedOutput",
        __config__=ConfigDict(extra=extra_policy, strict=True),
        **model_fields,
    )


def collect_field_specs(config: ValidationConfig) -> list[ValidationFieldSpec]:
    """Return field specs in configuration order for post-schema normalization checks."""
    return list(config.fields)

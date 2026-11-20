"""JSON Schema generation and validation for output records."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator

from ..models.output import FullOutputDocument, StrictOutputDocument


def full_schema() -> dict[str, Any]:
    return FullOutputDocument.model_json_schema(mode="serialization")


def strict_schema() -> dict[str, Any]:
    return StrictOutputDocument.model_json_schema(mode="serialization")


def validate_full(data: Any) -> None:
    Draft202012Validator(full_schema()).validate(data)


def validate_strict(data: Any) -> None:
    Draft202012Validator(strict_schema()).validate(data)

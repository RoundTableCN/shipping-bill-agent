"""Shared scalar types: money, currency, ISO date."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Annotated, Any

from pydantic import BeforeValidator, StringConstraints, WithJsonSchema

# ISO 4217 minor units. Default is 2 for currencies not listed here.
CURRENCY_PRECISION: dict[str, int] = {
    "JPY": 0,
    "KRW": 0,
    "KWD": 3,
    "BHD": 3,
    "OMR": 3,
    "JOD": 3,
}


def to_decimal(value: Any) -> Decimal:
    """Convert a value to Decimal without going through binary float.

    Floats are converted via ``str(value)`` so that 0.1 becomes Decimal("0.1")
    rather than the binary expansion. Empty strings are rejected; use None for
    "not extracted".
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid money value")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            raise ValueError("empty string is not a valid money value; use None")

        negative = False
        if text.startswith("(") and text.endswith(")"):
            negative = True
            text = text[1:-1].strip()
        if text.endswith("-"):
            negative = True
            text = text[:-1].strip()

        text = re.sub(
            r"(?i)^(?:USD|CNY|EUR|HKD|JPY|GBP|AUD|CAD|SGD|US\$|\$|￥|¥|€|£)\s*",
            "",
            text,
        )
        text = re.sub(
            r"(?i)\s*(?:USD|CNY|EUR|HKD|JPY|GBP|AUD|CAD|SGD)$",
            "",
            text,
        )
        if not text:
            raise ValueError("empty string is not a valid money value; use None")
        try:
            result = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"invalid decimal: {value!r}") from exc
        return -result if negative else result
    raise TypeError(f"unsupported money type: {type(value).__name__}")


Money = Annotated[
    Decimal,
    BeforeValidator(to_decimal),
    WithJsonSchema({"type": "number"}, mode="validation"),
    WithJsonSchema({"type": "number"}, mode="serialization"),
]

Currency = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z]{3}$"),
]

ISODate = Annotated[
    str,
    StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$"),
]


def quantize_money(value: Decimal | None, currency: str | None) -> Decimal | None:
    """Quantize an amount to the currency's ISO 4217 minor unit."""
    if value is None:
        return None
    precision = CURRENCY_PRECISION.get((currency or "").upper(), 2)
    quantum = Decimal(1).scaleb(-precision)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)

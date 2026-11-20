"""JSON serialization for output records.

Two modes:

- ``full``   : every audit field, used internally and for review.
- ``strict`` : only the keys in the exam's standard output format. The rest
               of the audit trail is written to a sibling ``audit.json``.

Money is serialized with ``simplejson(use_decimal=True)`` so that it is emitted
as a JSON number (not a string) without a binary-float round trip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Literal

import simplejson

from ..models.output import (
    FullOutputDocument,
    OutputRecord,
    StrictOutputDocument,
    StrictOutputRecord,
)
from ..models.types import quantize_money

OutputMode = Literal["full", "strict"]

REQUIRED_STRICT_KEYS = (
    "operation",
    "document_info",
    "transaction_party",
    "charge_details",
    "financial_attributes",
    "audit_trail",
)


def _quantize_charge(charge: dict, currency: str | None) -> None:
    if charge.get("amount") is not None:
        charge["amount"] = quantize_money(charge["amount"], currency)


def _quantize_breakdown(breakdown: dict | None, currency: str | None) -> None:
    if not breakdown:
        return
    for key in ("quantity", "unit_price", "rate"):
        if breakdown.get(key) is not None:
            breakdown[key] = quantize_money(breakdown[key], currency)


def _quantize_totals(totals: dict | None, currency: str | None) -> None:
    if not totals:
        return
    for key in ("subtotal", "tax", "total"):
        if totals.get(key) is not None:
            totals[key] = quantize_money(totals[key], currency)


def _quantize_money_value(value: dict | None, currency: str | None) -> None:
    if value and value.get("normalized") is not None:
        value["normalized"] = quantize_money(value["normalized"], currency)


def _quantize_charge_values(values: dict | None, currency: str | None) -> None:
    if not values:
        return
    for key in ("quantity", "rate", "amount"):
        _quantize_money_value(values.get(key), currency)
    _quantize_money_value(
        values.get("settlement_amount"),
        values.get("settlement_currency") or currency,
    )
    # ROE is an exchange rate, not a monetary amount; keep its precision.


def to_full_dict(record: OutputRecord) -> dict:
    """Full audit dictionary with currency-aware amount quantization."""
    data = record.model_dump(mode="python")
    currency = data["charge_details"].get("currency")

    _quantize_charge(data["charge_details"], currency)

    audit = data.get("audit_trail") or {}
    if audit.get("candidate_amount") is not None:
        audit["candidate_amount"] = quantize_money(audit["candidate_amount"], currency)
    _quantize_breakdown(audit.get("charge_breakdown"), currency)
    _quantize_totals(audit.get("document_totals"), currency)
    _quantize_charge_values(audit.get("charge_values"), currency)

    # Validate and normalize the full record shape.
    validated = OutputRecord.model_validate(data)
    return validated.model_dump(mode="python")


def to_strict_dict(record: OutputRecord) -> dict:
    """Exam-compliant dictionary: required keys only, audit = ai_reasoning."""
    full = to_full_dict(record)
    return {
        "operation": full["operation"],
        "document_info": full["document_info"],
        "transaction_party": full["transaction_party"],
        "charge_details": full["charge_details"],
        "financial_attributes": full["financial_attributes"],
        "audit_trail": {"ai_reasoning": full["audit_trail"]["ai_reasoning"]},
    }


def dumps(records: Iterable[OutputRecord], mode: OutputMode = "full") -> str:
    """Serialize records to a JSON array string."""
    records = list(records)
    if mode == "full":
        payload = [to_full_dict(r) for r in records]
        validated = FullOutputDocument.model_validate(payload)
        data = [r.model_dump(mode="python") for r in validated.root]
    elif mode == "strict":
        payload = [to_strict_dict(r) for r in records]
        validated = StrictOutputDocument.model_validate(payload)
        data = [r.model_dump(mode="python") for r in validated.root]
    else:
        raise ValueError(f"unknown output mode: {mode!r}")

    return simplejson.dumps(
        data,
        use_decimal=True,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


def write_output(
    records: Iterable[OutputRecord],
    out_path: str | Path,
    mode: OutputMode = "full",
    audit_path: str | Path | None = None,
) -> dict[str, Path]:
    """Write the main output. In strict mode also write the full audit trail."""
    records = list(records)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dumps(records, mode) + "\n", encoding="utf-8")

    written: dict[str, Path] = {"output": out}

    if mode == "strict":
        audit = Path(audit_path) if audit_path else out.with_name("audit.json")
        audit.parent.mkdir(parents=True, exist_ok=True)
        audit_payload = [to_full_dict(r)["audit_trail"] for r in records]
        audit.write_text(
            simplejson.dumps(
                audit_payload,
                use_decimal=True,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        written["audit"] = audit

    return written

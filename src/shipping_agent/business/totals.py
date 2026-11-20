"""Extract subtotal / tax / total from a normalized document."""

from __future__ import annotations

import re
from decimal import Decimal

from pydantic import Field

from ..io.text_normalize import parse_amount
from ..models.base import StrictModel
from ..models.bundle import DocumentBundle
from ..models.output import DocumentTotals

SUBTOTAL_LABELS = ("SUBTOTAL", "SUB TOTAL", "小计")
TAX_LABELS = ("TAX AMOUNT", "TAX", "税额", "税费")
TOTAL_LABELS = (
    "GRAND TOTAL BALANCE DUE TO",
    "GRAND TOTAL",
    "TOTAL CHARGES TO BE PAID",
    "TOTAL AMOUNT",
    "BALANCE DUE",
    "TOTAL",
    "合计",
    "总计",
)

_AMOUNT_RE = re.compile(
    r"(?i)(?:USD|CNY|EUR|HKD|JPY|GBP|AUD|CAD|SGD|US\$|\$|￥|¥|€|£)?\s*"
    r"([\d,]+(?:\.\d{1,4})?)"
)


class TotalsResult(StrictModel):
    totals: DocumentTotals = Field(default_factory=DocumentTotals)
    warnings: list[str] = Field(default_factory=list)


def _label_amounts(
    text: str,
    labels: tuple[str, ...],
    *,
    exclude: tuple[str, ...] = (),
) -> list[Decimal]:
    values: list[Decimal] = []
    lines = text.splitlines()

    for index, line in enumerate(lines):
        upper = line.upper()
        if any(token.upper() in upper for token in exclude):
            continue
        for label in sorted(labels, key=len, reverse=True):
            match = re.search(rf"(?i)\b{re.escape(label)}\b", line)
            if not match:
                continue

            amount_match = _AMOUNT_RE.search(line[match.end():])
            if amount_match is None:
                # PDF text extraction often puts the label and the value on
                # separate lines (e.g. "SUBTOTAL:" then "220.00").
                for next_line in lines[index + 1:]:
                    if not next_line.strip():
                        continue
                    amount_match = _AMOUNT_RE.search(next_line)
                    break

            if amount_match:
                amount = parse_amount(amount_match.group(1))
                if amount is not None:
                    values.append(amount)
            break
    return values


def _pick(values: list[Decimal], field: str, warnings: list[str]) -> Decimal | None:
    if not values:
        return None
    unique = list(dict.fromkeys(values))
    if len(unique) == 1:
        return unique[0]
    warnings.append(
        f"W_MULTIPLE_{field.upper()}_VALUES: " + ", ".join(str(v) for v in unique)
    )
    return None


def extract_document_totals(bundle: DocumentBundle) -> TotalsResult:
    text = bundle.norm_text or bundle.raw_text
    warnings: list[str] = []

    subtotal = _pick(
        _label_amounts(text, SUBTOTAL_LABELS),
        "subtotal",
        warnings,
    )
    tax = _pick(
        _label_amounts(text, TAX_LABELS),
        "tax",
        warnings,
    )
    total = _pick(
        _label_amounts(text, TOTAL_LABELS, exclude=("SUBTOTAL", "SUB TOTAL")),
        "total",
        warnings,
    )

    # Excel uses 合计 per currency; multiple distinct totals cannot be one field.
    if total is None and "MULTIPLE_TOTAL_VALUES" in " ".join(warnings):
        warnings.append("W_MULTI_CURRENCY_TOTAL: total left as null")

    return TotalsResult(
        totals=DocumentTotals(subtotal=subtotal, tax=tax, total=total),
        warnings=warnings,
    )

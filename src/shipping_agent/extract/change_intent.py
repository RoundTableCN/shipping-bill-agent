"""Extract explicit change intent with evidence. Never infer changes."""

from __future__ import annotations

import re

from ..models.bundle import DocumentBundle
from .models import FieldChange

_CHANGE_HINT = re.compile(
    r"(?i)(REVISED|CHANGED|CORRECTED|UPDATED|更正|改为|调整为|修正)"
)

_EN_PATTERN = re.compile(
    r"(?i)(?P<charge>[A-Z][A-Z0-9 /&'\-]{2,80}?)\s+(?:AMOUNT\s+)?"
    r"(?:REVISED|CHANGED|CORRECTED|UPDATED)\s+FROM\s+"
    r"(?P<old>(?:USD|CNY|EUR|HKD|JPY|GBP)?\s*[\d,]+\.\d{2})\s+TO\s+"
    r"(?P<new>(?:USD|CNY|EUR|HKD|JPY|GBP)?\s*[\d,]+\.\d{2})"
)

_ZH_PATTERN = re.compile(
    r"(?P<charge>[一-鿿A-Z0-9 /&'\-]{2,40}?)(?:金额)?"
    r"(?:改为|更正为|调整为|修正为)\s*"
    r"(?P<new>(?:USD|CNY|EUR|HKD|JPY|GBP)?\s*[\d,]+\.?\d{0,2})"
)


def _clean_charge(value: str) -> str | None:
    value = re.sub(r"(?i)^(CORRECTION|AMENDMENT|NOTE)\s*[:：]?\s*", "", value.strip())
    value = re.sub(r"(?i)\s+AMOUNT\s*$", "", value)
    value = value.strip(" :-—,.;")
    return value or None


def extract_change_intent(
    bundle: DocumentBundle,
    existing_bill: dict | None = None,
) -> list[FieldChange]:
    changes: list[FieldChange] = []
    seen: set[tuple] = set()

    for line in (bundle.norm_text or bundle.raw_text).splitlines():
        text = line.strip()
        if not text or not _CHANGE_HINT.search(text):
            continue

        match = _EN_PATTERN.search(text)
        if match:
            charge = _clean_charge(match.group("charge"))
            key = ("amount", charge, match.group("old"), match.group("new"))
            if key not in seen:
                seen.add(key)
                changes.append(
                    FieldChange(
                        field="amount",
                        charge_item=charge,
                        old_value=match.group("old").strip(),
                        new_value=match.group("new").strip(),
                        evidence_quote=text,
                        confidence=0.95,
                    )
                )
            continue

        match = _ZH_PATTERN.search(text)
        if match:
            charge = _clean_charge(match.group("charge"))
            key = ("amount", charge, None, match.group("new"))
            if key not in seen:
                seen.add(key)
                changes.append(
                    FieldChange(
                        field="amount",
                        charge_item=charge,
                        old_value=None,
                        new_value=match.group("new").strip(),
                        evidence_quote=text,
                        confidence=0.85,
                    )
                )

    return changes

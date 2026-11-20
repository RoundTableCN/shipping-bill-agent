"""Text, amount, currency, date and filename normalization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "RMB": "CNY",
    "CNY": "CNY",
    "EUR": "EUR",
    "HKD": "HKD",
    "JPY": "JPY",
    "GBP": "GBP",
    "AUD": "AUD",
    "CAD": "CAD",
    "SGD": "SGD",
    "￥": "CNY",
    "¥": "CNY",
    "€": "EUR",
    "£": "GBP",
}

ISO_CODES = {
    "USD", "CNY", "EUR", "HKD", "JPY", "GBP", "AUD", "CAD", "SGD",
    "KRW", "TWD", "THB", "MYR", "IDR", "PHP", "VND", "INR",
    "AED", "SAR", "CHF", "NZD", "KWD", "BHD", "OMR", "JOD",
}

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\xa0", " ").replace("​", "").replace("﻿", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_id_for(data: bytes) -> str:
    return sha256_bytes(data)[:12]


def safe_filename(name: str, fallback: str = "attachment") -> str:
    name = unicodedata.normalize("NFKC", name or "")
    name = name.replace("\x00", "").replace("\xa0", " ")
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = name.strip().strip(".") or fallback
    if len(name) > 120:
        stem, suffix = Path(name).stem[:100], Path(name).suffix[:20]
        name = f"{stem}{suffix}"
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        name = f"_{name}"
    return name


def parse_amount(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    text = unicodedata.normalize("NFKC", str(raw)).strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    if text.endswith("-"):
        negative = True
        text = text[:-1]
    text = text.replace(",", "").replace(" ", "")
    text = re.sub(r"^[^\d+\-.]*", "", text)
    text = re.sub(r"[^\d.\-]*$", "", text)
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_currency(raw: str | None) -> tuple[str | None, bool]:
    """Return (ISO code or None, inferred_from_symbol)."""
    if raw is None:
        return None, False
    text = unicodedata.normalize("NFKC", str(raw)).strip().upper()
    if not text:
        return None, False
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if text == symbol.upper():
            inferred = symbol in {"$", "US$", "￥", "¥", "€", "£"}
            return code, inferred
    if re.fullmatch(r"[A-Z]{3}", text) and text in ISO_CODES:
        return text, False
    # "$50" / "USD 50" style: pull the first known symbol/code.
    m = re.search(r"(US\$|USD|RMB|CNY|EUR|HKD|JPY|GBP|AUD|CAD|SGD|[$￥¥€£])", text)
    if m:
        symbol = m.group(1)
        code = _CURRENCY_SYMBOLS.get(symbol, "USD" if symbol == "$" else None)
        return code, symbol in {"$", "US$", "￥", "¥", "€", "£"}
    return None, False


def _iso(year: int, month: int, day: int) -> str | None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    from datetime import date

    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_date_info(raw: str | None) -> tuple[str | None, str, list[str]]:
    """Parse a date and report whether the month/day order is ambiguous.

    Returns ``(iso_or_none, status, candidates)`` where status is
    ``CONFIRMED``, ``AMBIGUOUS`` or ``UNKNOWN``.  For an ambiguous value such
    as ``10/03/2025`` the normalized date is ``None`` and both possible ISO
    dates are returned as candidates.
    """
    if not raw:
        return None, "UNKNOWN", []
    text = unicodedata.normalize("NFKC", str(raw)).strip()
    year_first = (
        re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", text)
    )
    if year_first:
        year, month, day = (int(value) for value in year_first.groups())
        iso = _iso(year, month, day)
        return (iso, "CONFIRMED", [iso]) if iso else (None, "UNKNOWN", [])

    day_month = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", text)
    if not day_month:
        return None, "UNKNOWN", []
    first, second, year = (int(value) for value in day_month.groups())
    month_first = _iso(year, first, second)
    day_first = _iso(year, second, first)

    if first > 12 and second <= 12:
        return (day_first, "CONFIRMED", [day_first]) if day_first else (None, "UNKNOWN", [])
    if second > 12 and first <= 12:
        return (month_first, "CONFIRMED", [month_first]) if month_first else (None, "UNKNOWN", [])
    if month_first is None and day_first is None:
        return None, "UNKNOWN", []
    if first == second and month_first is not None:
        return month_first, "CONFIRMED", [month_first]
    candidates = [value for value in (month_first, day_first) if value]
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) == 1:
        return candidates[0], "CONFIRMED", candidates
    return None, "AMBIGUOUS", candidates


def parse_date(raw: str | None) -> str | None:
    """Backward-compatible helper: return a normalized date only if unambiguous."""
    iso, _status, _candidates = parse_date_info(raw)
    return iso


def is_probable_total_line(text: str) -> bool:
    return bool(
        re.search(
            r"(?i)\b(SUBTOTAL|TOTAL|GRAND\s+TOTAL|BALANCE|TAX|PAID|AMOUNT\s+DUE)\b|合计|小计|总计|税额",
            text or "",
        )
    )


def is_legal_boilerplate(text: str) -> bool:
    text = text or ""
    if len(text) > 220 and re.search(r"(?i)\b(shall|liability|clause|merchant|tariff)\b", text):
        return True
    return bool(re.search(r"(?i)(all\s+claims|governing\s+law|court|hereby)", text))

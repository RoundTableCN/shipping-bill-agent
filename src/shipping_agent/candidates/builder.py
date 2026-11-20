"""Deterministic charge-candidate generation from DocumentBundle."""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal

from ..io.text_normalize import (
    is_legal_boilerplate,
    is_probable_total_line,
    normalize_text,
    parse_amount,
    parse_currency,
)
from ..models.bundle import DocumentBundle, SourceRef, TableBlock, TextBlock
from ..models.candidate import RawChargeLine
from .columns import map_columns, table_rows

_CURRENCY_RE = re.compile(r"(?i)\bCURRENCY\s*[:：]?\s*([A-Z]{3})\b")
_TERM_RE = re.compile(r"(?i)\bTERMS?\s*[:：]?\s*(PP|CC|COD)\b")

_PATTERNS = (
    re.compile(
        r"^(?P<name>[A-Z][A-Z0-9 /&'\-.,()]{2,60}?)\s+"
        r"(?P<cur>USD|CNY|EUR|HKD|JPY|GBP)\s+"
        r"(?P<amt>[\d,]+\.\d{2,4})"
    ),
    re.compile(
        r"^(?P<name>[A-Z][A-Z0-9 /&'\-.,()]{2,60}?)\s+"
        r"(?P<amt>[\d,]+\.\d{2,4})\s*"
        r"(?P<cur>USD|CNY|EUR|HKD|JPY|GBP)?$"
    ),
    re.compile(
        r"(?P<name>H/C|HANDLING(?:\s+FEE)?|THC|DOC(?:UMENTATION)?(?:\s+FEE)?|"
        r"D/O|CUSTOMS|TRUCKING|STORAGE|DETENTION|DEMURRAGE)"
        r"\s*[:：]?\s*(?P<sym>USD|US\$|\$)?\s*(?P<amt>[\d,]+\.?\d{0,2})"
    ),
)


def _hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def _doc_currency(bundle: DocumentBundle) -> str | None:
    match = _CURRENCY_RE.search(bundle.norm_text or bundle.raw_text)
    return match.group(1).upper() if match else None


def _doc_payment_term(bundle: DocumentBundle) -> str | None:
    match = _TERM_RE.search(bundle.norm_text or bundle.raw_text)
    return match.group(1).upper() if match else None


def _pick(texts: list[str], mapping: dict[str, int], field: str) -> str | None:
    index = mapping.get(field)
    if index is None or index >= len(texts):
        return None
    value = texts[index].strip()
    return value or None


def _find_currency(texts: list[str]) -> tuple[str | None, bool]:
    for text in texts:
        code, inferred = parse_currency(text)
        if code:
            return code, inferred
    return None, False


def _find_amount(texts: list[str]) -> tuple[str | None, Decimal | None]:
    for text in reversed(texts):
        value = parse_amount(text)
        if value is not None:
            return text, value
    return None, None


def _find_payment_term(texts: list[str]) -> str | None:
    for text in texts:
        match = re.search(r"(?i)\b(PP|CC|COD)\b", text)
        if match:
            return match.group(1).upper()
    return None


def _find_prepaid_collect(texts: list[str]) -> str | None:
    """Read P/C only from an explicit P/C label or PREPAID/COLLECT word.

    A bare ``C`` in a BASE or other column must not become P/C; table column
    mapping handles a real P/C header, this fallback is for text lines.
    """
    for text in texts:
        match = re.search(r"(?i)\bP/?C\s*[:：]?\s*([PC])\b", text)
        if match:
            return match.group(1).upper()
        match = re.search(r"(?i)\b(PREPAID|COLLECT)\b", text)
        if match:
            return match.group(1).upper()
    return None


def _find_charge_code(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b([A-Z]{2,6}\d{1,4})\b", value.upper())
    return match.group(1) if match else None


def _charge_name_without_code(value: str | None, code: str | None) -> str | None:
    if not value:
        return None
    name = re.sub(r"(?i)^\s*WAYBILL\s+", "", value).strip()
    if code:
        name = re.sub(rf"(?i)\b{re.escape(code)}\b", "", name).strip(" :-")
    return re.sub(r"\s+", " ", name).strip() or None


def _party_code(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{2,8}", value):
        return None
    if value in {"PAYER", "PAYEE", "CODE", "NONE", "NULL"}:
        return None
    return value


def _find_party_codes(value: str) -> tuple[str | None, str | None]:
    match = re.search(
        r"(?i)\b([A-Z]{2,8})\s+PAY\s+([A-Z]{2,8})\b", value
    )
    if not match:
        return None, None
    return _party_code(match.group(1)), _party_code(match.group(2))


def _find_payment_due(value: str) -> str | None:
    match = re.search(
        r"(?i)\b(PAY\s+IMMEDIATELY|PAYMENT\s+DUE\s+IMMEDIATELY|"
        r"DUE\s+IMMEDIATELY|PAY\s+ON\s+DEMAND)\b",
        value,
    )
    return re.sub(r"\s+", " ", match.group(1)).upper() if match else None


def _find_charge(texts: list[str]) -> str | None:
    """Pick the most descriptive cell when the table has no charge-name column."""
    best: str | None = None
    best_score = 0
    for text in texts:
        value = text.strip()
        if not value or value in {"-", "—"}:
            continue
        if parse_amount(value) is not None:
            continue
        code, _ = parse_currency(value)
        if code:
            continue
        if re.fullmatch(r"[A-Z]{1,4}", value):
            continue
        if re.fullmatch(r"[A-Z]{2,5}\d{2,}", value):
            continue
        tokens = re.findall(r"[A-Za-z]{2,}", value)
        score = len(tokens) + (2 if " " in value else 0)
        if score > best_score:
            best, best_score = value, score
    return best


def _row_bbox(row: list) -> list[float] | None:
    boxes = [cell.bbox for cell in row if cell is not None and cell.bbox]
    if not boxes:
        return None
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _bbox_overlap(a: list[float] | None, b: list[float] | None) -> bool:
    if not a or not b:
        return False
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return False
    overlap = (x1 - x0) * (y1 - y0)
    block_area = max((a[2] - a[0]) * (a[3] - a[1]), 1.0)
    return overlap / block_area > 0.5


def _flags_for(amount: Decimal, rate_raw: str | None, qty_raw: str | None, inferred: bool) -> list[str]:
    flags = ["AMOUNT_PARSED"]
    if inferred:
        flags.append("CURRENCY_INFERRED")
    rate = parse_amount(rate_raw)
    qty = parse_amount(qty_raw)
    if rate is not None and qty is not None and abs(rate * qty - amount) <= Decimal("0.01"):
        flags.append("RATE_QTY_MATCH")
    return flags


def _candidate_from_table_row(
    bundle: DocumentBundle,
    table: TableBlock,
    row_index: int,
    texts: list[str],
    mapping: dict[str, int],
    candidate_no: int,
) -> RawChargeLine | None:
    joined = " ".join(text for text in texts if text).strip()
    if not joined or is_probable_total_line(joined):
        return None

    charge_raw = _pick(texts, mapping, "charge_item") or _find_charge(texts)
    amount_raw = _pick(texts, mapping, "amount")
    amount = parse_amount(amount_raw)
    if amount is None:
        amount_raw, amount = _find_amount(texts)
    if not charge_raw or amount is None:
        return None

    currency_raw = _pick(texts, mapping, "currency")
    currency_text_raw = currency_raw
    currency, inferred = parse_currency(currency_raw)
    found_currency: str | None = None
    if not currency:
        found_currency, found_inferred = _find_currency(texts)
        currency = found_currency
        inferred = found_inferred
    if not currency:
        currency = _doc_currency(bundle)
        inferred = False
    if inferred:
        currency_source = "INFERRED_FROM_DOLLAR_SYMBOL"
    elif currency_raw or found_currency:
        currency_source = "DOCUMENT_TEXT"
    elif currency:
        currency_source = "DOCUMENT_DEFAULT"
    else:
        currency_source = "MISSING"

    qty_raw = _pick(texts, mapping, "qty")
    rate_raw = _pick(texts, mapping, "rate")
    payment_term = (
        _pick(texts, mapping, "payment_term")
        or _find_payment_term(texts)
        or _doc_payment_term(bundle)
    )
    prepaid_collect_raw = (
        _pick(texts, mapping, "prepaid_collect")
        or _find_prepaid_collect(texts)
    )
    payout_payer, payout_payee = _find_party_codes(joined)
    payer_code_raw = _party_code(_pick(texts, mapping, "payer_code")) or payout_payer
    payee_code_raw = _party_code(_pick(texts, mapping, "payee_code")) or payout_payee
    payment_due_instruction = _find_payment_due(joined)
    charge_code_raw = _pick(texts, mapping, "charge_code") or _find_charge_code(
        charge_raw
    )
    charge_name_raw = _charge_name_without_code(charge_raw, charge_code_raw)
    charge_type_raw = _pick(texts, mapping, "charge_type")
    base_raw = _pick(texts, mapping, "base")
    roe_raw = _pick(texts, mapping, "roe")
    settlement_amount_raw = _pick(texts, mapping, "settlement_amount")
    settlement_currency_raw = _pick(texts, mapping, "settlement_currency")

    source_position_id = _hash(bundle.source.file_id, "table", table.table_id, row_index)
    content_fingerprint = _hash(normalize_text(joined), str(amount), currency or "")
    row = table_rows(table)[row_index]
    bbox = _row_bbox(row) or table.bbox

    return RawChargeLine(
        line_id=source_position_id,
        source_position_id=source_position_id,
        content_fingerprint=content_fingerprint,
        candidate_id=f"c{candidate_no:03d}",
        charge_raw=charge_raw,
        charge_name_raw=charge_name_raw,
        charge_code_raw=charge_code_raw,
        qty_raw=qty_raw,
        rate_raw=rate_raw,
        amount_raw=amount_raw,
        currency_raw=currency,
        currency_text_raw=currency_text_raw,
        currency_source=currency_source,
        payment_term_raw=payment_term,
        payment_due_instruction=payment_due_instruction,
        prepaid_collect_raw=prepaid_collect_raw,
        payer_code_raw=payer_code_raw,
        payee_code_raw=payee_code_raw,
        party_mapping_status=(
            "PENDING_CONFIRMATION"
            if payer_code_raw or payee_code_raw
            else None
        ),
        charge_type_raw=charge_type_raw,
        base_raw=base_raw,
        roe_raw=roe_raw,
        settlement_amount_raw=settlement_amount_raw,
        settlement_currency_raw=settlement_currency_raw,
        source_kind="table_row",
        evidence=SourceRef(
            file_id=bundle.source.file_id,
            file_name=bundle.source.file_name,
            media_type=bundle.media_type,
            page=table.page,
            block_id=table.table_id,
            bbox=bbox,
            quote=joined,
        ),
        deterministic_flags=["TABLE_ROW"] + _flags_for(amount, rate_raw, qty_raw, inferred),
    )


def _parse_text_line(line: str) -> dict[str, object] | None:
    line = normalize_text(line).strip()
    if not line or len(line) > 180 or is_probable_total_line(line) or is_legal_boilerplate(line):
        return None

    for pattern in _PATTERNS:
        match = pattern.search(line)
        if not match:
            continue
        groups = match.groupdict()
        amount = parse_amount(groups.get("amt"))
        if amount is None:
            continue
        name = (groups.get("name") or "").strip(" :-")
        if not name:
            continue
        currency_raw = groups.get("cur") or groups.get("sym")
        currency, inferred = parse_currency(currency_raw)
        return {
            "name": name,
            "amount": amount,
            "amount_raw": groups.get("amt"),
            "currency": currency,
            "currency_text_raw": currency_raw,
            "inferred": inferred,
        }
    return None


def _candidate_from_text_block(
    bundle: DocumentBundle,
    block: TextBlock,
    candidate_no: int,
) -> RawChargeLine | None:
    parsed = _parse_text_line(block.text)
    if parsed is None:
        return None

    currency = parsed["currency"] or _doc_currency(bundle)
    source_kind = "email_body" if bundle.media_type == "message/rfc822" else "text_line"
    charge_name_raw = str(parsed["name"])
    charge_code_raw = _find_charge_code(charge_name_raw)
    payer_code_raw, payee_code_raw = _find_party_codes(block.text)
    payment_due_instruction = _find_payment_due(block.text)
    prepaid_collect_raw = _find_prepaid_collect([block.text])
    source_position_id = _hash(bundle.source.file_id, "text", block.block_id, block.order)
    content_fingerprint = _hash(normalize_text(block.text), str(parsed["amount"]), currency or "")
    if parsed["inferred"]:
        currency_source = "INFERRED_FROM_DOLLAR_SYMBOL"
    elif parsed["currency"]:
        currency_source = "DOCUMENT_TEXT"
    elif currency:
        currency_source = "DOCUMENT_DEFAULT"
    else:
        currency_source = "MISSING"

    return RawChargeLine(
        line_id=source_position_id,
        source_position_id=source_position_id,
        content_fingerprint=content_fingerprint,
        candidate_id=f"c{candidate_no:03d}",
        charge_raw=str(parsed["name"]),
        charge_name_raw=charge_name_raw,
        charge_code_raw=charge_code_raw,
        amount_raw=str(parsed["amount_raw"]),
        currency_raw=currency,
        currency_text_raw=str(parsed["currency_text_raw"]) if parsed.get("currency_text_raw") else None,
        currency_source=currency_source,
        payment_term_raw=_doc_payment_term(bundle),
        payment_due_instruction=payment_due_instruction,
        prepaid_collect_raw=prepaid_collect_raw,
        payer_code_raw=payer_code_raw,
        payee_code_raw=payee_code_raw,
        party_mapping_status=(
            "PENDING_CONFIRMATION"
            if payer_code_raw or payee_code_raw
            else None
        ),
        source_kind=source_kind,
        evidence=SourceRef(
            file_id=bundle.source.file_id,
            file_name=bundle.source.file_name,
            media_type=bundle.media_type,
            page=block.page,
            block_id=block.block_id,
            bbox=block.bbox,
            quote=block.text,
        ),
        deterministic_flags=[source_kind.upper()] + _flags_for(
            parsed["amount"], None, None, bool(parsed["inferred"])
        ),
    )


def build_candidates(bundle: DocumentBundle) -> list[RawChargeLine]:
    candidates: list[RawChargeLine] = []
    table_boxes: list[list[float] | None] = []

    for table in bundle.tables:
        rows = table_rows(table)
        if len(rows) < 2:
            continue
        header = [cell.text if cell else "" for cell in rows[0]]
        mapping = map_columns(header)
        table_boxes.append(table.bbox)
        for row_index in range(1, len(rows)):
            texts = [
                cell.text if cell is not None else "" for cell in rows[row_index]
            ]
            candidate = _candidate_from_table_row(
                bundle, table, row_index, texts, mapping, len(candidates) + 1
            )
            if candidate is not None:
                candidates.append(candidate)

    for block in bundle.blocks:
        if block.kind not in ("line", "paragraph", "ocr_line"):
            continue
        if any(_bbox_overlap(block.bbox, box) for box in table_boxes):
            continue
        candidate = _candidate_from_text_block(bundle, block, len(candidates) + 1)
        if candidate is not None:
            candidates.append(candidate)

    return candidates


def collect_candidates(bundle: DocumentBundle) -> list[RawChargeLine]:
    """Candidates for the bundle plus billing child attachments."""
    candidates = build_candidates(bundle)
    for attachment in bundle.attachments:
        if attachment.role == "billing" and attachment.child is not None:
            candidates.extend(collect_candidates(attachment.child))
    return candidates

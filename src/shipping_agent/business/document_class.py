"""Rule-based document classification (offline baseline for the LLM)."""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

from ..extract.models import DocumentClassification
from ..io.text_normalize import parse_date, parse_date_info
from ..models.bundle import DocumentBundle
from ..models.output import BusinessInstruction, DateCandidate

_COMPANY_SUFFIX = re.compile(
    r"(?i)\b(LIMITED|LTD\.?|LLC|INC\.?|CO\.|COMPANY|CORP\.?|CORPORATION|GMBH|AG|TECH)\b|公司"
)

_REFERENCE_PATTERNS = (
    re.compile(r"(?i)PRE-ALERT\s+([A-Z0-9]{6,})"),
    re.compile(
        r"(?i)(?:INVOICE|D/C|DEBIT\s+NOTE|CREDIT\s+NOTE|STATEMENT)\s*"
        r"(?:NO\.?|NUMBER|#)\s*[:：]?\s*([A-Z0-9][A-Z0-9\-/]{3,})"
    ),
    re.compile(
        r"(?i)(?:D/C|DEBIT\s+NOTE|CREDIT\s+NOTE|INVOICE|STATEMENT|BILL\s+OF\s+LADING|B/L)"
        r"\s*(?:NO\.?|NUMBER|#)?\s*[:：]?\s*([A-Z0-9][A-Z0-9\-/]{3,})"
    ),
    re.compile(
        r"(?i)(?:MBL|HBL|MASTER\s+B/L|HOUSE\s+B/L)\s*(?:NO\.?)?\s*[:：]?\s*"
        r"([A-Z0-9][A-Z0-9\-/]{3,})"
    ),
    # Carrier B/L numbers often look like SCAC + booking prefix + digits.
    re.compile(r"\b([A-Z]{4}[A-Z]{2,4}\d{7,})\b"),
    # Generic container / reference fallback (e.g. MSCU1234564).
    re.compile(r"\b([A-Z]{4,8}\d{7,})\b"),
)

_REF_BLACKLIST = {
    "BILL", "TYPE", "NO", "NUMBER", "DATE", "WAYBILL", "SCAC",
    "CUR", "AMOUNT", "TOTAL", "STATEMENT", "INVOICE", "NOTE", "D/C", "B/L",
}

_BL_PATTERNS = (
    re.compile(
        r"(?i)(?:MASTER\s+B/L|HOUSE\s+B/L|MBL|HBL|B/L)"
        r"\s*(?:NO\.?|NUMBER|#)?\s*[:：]?\s*([A-Z0-9][A-Z0-9\-/]{5,})"
    ),
    re.compile(r"\b([A-Z]{4}[A-Z]{2,4}\d{7,})\b"),
)
_BL_SPACED_PATTERN = re.compile(
    r"(?i)(?:MASTER\s+B/L|HOUSE\s+B/L|MBL|HBL|B/L)"
    r"\s*(?:NO\.?|NUMBER|#)?\s*[:：]?\s*([A-Z]{4}\s+[A-Z0-9][A-Z0-9\-/]{4,})"
)
_BOOKING_PATTERN = re.compile(
    r"(?i)(?:BOOKING\s*(?:NO\.?|NUMBER)?)\s*[:：]?\s*([A-Z0-9][A-Z0-9\-/]{5,})"
)
_CONTAINER_PATTERN = re.compile(r"\b([A-Z]{4}\d{7})\b")
_CONTAINER_LABELED_PATTERN = re.compile(
    r"(?i)(?:CNTR|CONTAINER|CONTAINER\s+NO|箱号|箱號|SEAL)"
    r"\s*(?:NO\.?|NUMBER|#)?\s*[:：]?\s*([A-Z]{4}\d{7})"
)
_SEAL_PATTERN = re.compile(
    r"(?i)(?:SEAL|封条|封條)[ \t]*(?:NO\.?|NUMBER|#)?[ \t]*[:：]?[ \t]*"
    r"([A-Z0-9]{4,16})\b"
)
_DOCUMENT_NUMBER_PATTERNS = (
    re.compile(
        r"(?i)\b(?:DEBIT\s+INVOICE|INVOICE|D/C|DEBIT\s+NOTE|CREDIT\s+NOTE|"
        r"STATEMENT|DOCUMENT)\s*(?:NO\.?|NUMBER|#)\s*[:：]?\s*"
        r"([A-Z0-9][A-Z0-9_\-/]{3,})"
    ),
    re.compile(
        r"(?i)\b(?:DEBIT\s+INVOICE|INVOICE|D/C|DEBIT\s+NOTE|CREDIT\s+NOTE|"
        r"STATEMENT|DOCUMENT)\s*[:：]\s*"
        r"([A-Z0-9][A-Z0-9_\-/]{3,})"
    ),
)
_MBL_PATTERN = re.compile(
    r"(?i)\b(?:MASTER\s+B/L|MASTER\s+BILL\s+OF\s+LADING|MBL)"
    r"\s*(?:NO\.?|NUMBER|#)?\s*[:：]?\s*([A-Z0-9][A-Z0-9\-/]{5,})"
)
_HBL_PATTERN = re.compile(
    r"(?i)\b(?:HOUSE\s+B/L|HOUSE\s+BILL\s+OF\s+LADING|HBL)"
    r"\s*(?:NO\.?|NUMBER|#)?\s*[:：]?\s*([A-Z0-9][A-Z0-9\-/]{5,})"
)
_WAYBILL_PATTERN = re.compile(
    r"(?i)\b(?:WAYBILL|WAY\s+BILL)\s*(?:NO\.?|NUMBER|#)?\s*[:：]?\s*"
    r"([A-Z0-9][A-Z0-9\-/]{5,})"
)
_OUR_FILE_PATTERN = re.compile(
    r"(?i)\b(?:OUR\s+FILE|AGENT\s+FILE|FILE)\s*(?:NO\.?|NUMBER|#)?\s*[:：]?\s*"
    r"([A-Z0-9][A-Z0-9\-/]{3,})"
)
_PAYMENT_TERM_RE = re.compile(
    r"(?i)\b(?:PAYMENT\s+TERMS?|TERMS?)\s*[:：]?\s*(PP|CC|COD)\b"
)
_PAYMENT_DUE_RE = re.compile(
    r"(?i)\b(PAY\s+IMMEDIATELY|PAYMENT\s+DUE\s+IMMEDIATELY|"
    r"DUE\s+IMMEDIATELY|PAY\s+ON\s+DEMAND)\b"
)
_PAYMENT_RECEIVED_RE = re.compile(
    r"(?i)\bPAYMENT\s+RECEIVED\s*[:：]?\s*(YES|NO)\b"
)


def _container_check_digit(value: str) -> bool:
    """ISO 6346 check digit for the seven digits after the owner code."""
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    values = {
        **{letter: index + 10 for index, letter in enumerate(letters)},
        "A": 10, "B": 12, "C": 13, "D": 14, "E": 15, "F": 16, "G": 17,
        "H": 18, "I": 19, "J": 20, "K": 21, "L": 23, "M": 24, "N": 25,
        "O": 26, "P": 27, "Q": 28, "R": 29, "S": 30, "T": 31, "U": 32,
        "V": 34, "W": 35, "X": 36, "Y": 37, "Z": 38,
    }
    if len(value) != 11 or not re.fullmatch(r"[A-Z]{4}\d{7}", value):
        return False
    total = 0
    for index, char in enumerate(value[:10]):
        number = int(char) if char.isdigit() else values[char]
        total += number * (2 ** index)
    check = total % 11
    if check == 10:
        check = 0
    return int(value[-1]) == check


def is_valid_container_no(value: str | None) -> bool:
    if not value:
        return False
    value = value.upper()
    if not re.fullmatch(r"[A-Z]{4}\d{7}", value):
        return False
    # ISO 6346 equipment category is U, J or Z.  This rejects invoice
    # numbers such as INV-DEMO-001 while accepting MSCU1234564.
    if value[3] not in {"U", "J", "Z"}:
        return False
    return _container_check_digit(value)


def _extract_containers(
    text: str, subject: str = ""
) -> tuple[list[str], dict[str, str]]:
    values: list[str] = []
    sources: dict[str, str] = {}
    for source_name, source in (("email_subject", subject), ("document_text", text)):
        if not source:
            continue
        matches = list(_CONTAINER_LABELED_PATTERN.finditer(source)) or list(
            _CONTAINER_PATTERN.finditer(source)
        )
        for match in matches:
            value = _clean(match.group(1))
            if value and is_valid_container_no(value):
                value = value.upper()
                if value not in sources:
                    values.append(value)
                    sources[value] = source_name
    return values, sources


def _extract_seals(text: str) -> list[str]:
    values = [match.group(1).upper() for match in _SEAL_PATTERN.finditer(text)]
    return list(dict.fromkeys(value for value in values if value))


def _extract_document_numbers(text: str) -> tuple[str | None, str | None]:
    document_number: str | None = None
    invoice_number: str | None = None
    for pattern in _DOCUMENT_NUMBER_PATTERNS:
        for match in pattern.finditer(text):
            value = _clean(match.group(1))
            if not value or value.upper() in _REF_BLACKLIST:
                continue
            normalized = value.lstrip("_")
            label = match.group(0).upper()
            if "INVOICE" in label:
                invoice_number = invoice_number or normalized
                document_number = document_number or normalized
            else:
                document_number = document_number or normalized
    return document_number, invoice_number


def _first_labeled(pattern: re.Pattern[str], text: str) -> str | None:
    for match in pattern.finditer(text):
        value = _clean(match.group(1))
        if value and value.upper() not in _REF_BLACKLIST and re.search(r"\d", value):
            return value
    return None


def _same_name(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    na = re.sub(r"[^A-Z0-9]+", " ", a.upper()).strip()
    nb = re.sub(r"[^A-Z0-9]+", " ", b.upper()).strip()
    return bool(na and nb and (na == nb or na in nb or nb in na))


def _extract_bl(text: str, subject: str) -> str | None:
    for source in (text, subject):
        for pattern in _BL_PATTERNS:
            for match in pattern.finditer(source):
                value = _clean(match.group(1))
                if value and value.upper() not in _REF_BLACKLIST and re.search(r"\d", value):
                    return value
    return None


def _extract_bl_pair(text: str, subject: str) -> tuple[str | None, str | None]:
    """Return (raw B/L, normalized B/L), preserving spaces in the raw form."""
    normalized = _extract_bl(text, subject)
    if not normalized:
        return None, None
    for source in (text, subject):
        for match in _BL_SPACED_PATTERN.finditer(source):
            raw = _clean(match.group(1))
            if raw and re.sub(r"\s+", "", raw).upper() == normalized.upper():
                return raw, normalized
    # Some PDF rows have the spaced B/L in a reconstructed row without a
    # nearby "B/L" label; compare the de-spaced value to the selected B/L.
    for source in (text, subject):
        for match in re.finditer(r"\b([A-Z]{4}\s+[A-Z]{2,4}\d{7,})\b", source):
            raw = _clean(match.group(1))
            if raw and re.sub(r"\s+", "", raw).upper() == normalized.upper():
                return raw, normalized
    return normalized, normalized


def _extract_booking(text: str) -> str | None:
    match = _BOOKING_PATTERN.search(text)
    if match:
        value = _clean(match.group(1))
        if value and re.search(r"\d", value):
            return value
    return None


_LABELED_DATE_PATTERNS = (
    re.compile(
        r"(?i)(?:INVOICE\s+DATE|D/C\s+DATE|STATEMENT\s+DATE|RELEASE\s+DATE|DATE)"
        r"\s*[:：]?\s*(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})"
    ),
)
_GENERIC_DATE_PATTERNS = (
    re.compile(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})"),
    re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b"),
)
_RAW_DATE_RE = re.compile(
    r"(?i)\bDOCUMENT\s+DATE\s+RAW\s*[:：]?\s*"
    r"(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})"
)
_DUE_DATE_RE = re.compile(
    r"(?i)\bDUE\s+DATE\s*[:：]?\s*"
    r"(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})"
)


_PARTY_REJECT = re.compile(
    r"(?i)\b(shall|merchant|tariff|clause|liability|do not include|governing law|court)\b"
)


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" :：-—,.;")
    return value or None


def _party_value(value: str | None) -> str | None:
    value = _clean(value)
    if not value:
        return None
    if len(value) > 160 or _PARTY_REJECT.search(value):
        return None
    # Long legal sentences are rejected, but long registered company names
    # (e.g. "... AS AGENTS FOR ... LTD") are legitimate parties.
    if len(value) > 80 and not _COMPANY_SUFFIX.search(value):
        return None
    # A bare long code such as "PAYER-DEMO-01" is not a party name.  Codes are
    # preserved separately as payer_code_raw/payee_code_raw.
    if (
        " " not in value
        and not _COMPANY_SUFFIX.search(value)
        and not re.search(r"[一-鿿]", value)
        and len(value) > 5
    ):
        return None
    return value


def _label_value(text: str, labels: tuple[str, ...]) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        for label in labels:
            match = re.search(rf"(?i)\b{re.escape(label)}\b\s*[:：]?\s*(.*)$", line)
            if not match:
                continue
            value = _party_value(match.group(1))
            if value:
                return value
            if index + 1 < len(lines):
                next_line = lines[index + 1]
                # Never take the next label as the value of this label.
                if re.match(r"(?i)^[A-Z][A-Z /_-]{2,}\s*[:：]", next_line):
                    continue
                return _party_value(next_line)
    return None


def _find_letterhead(bundle: DocumentBundle) -> str | None:
    for block in bundle.blocks:
        text = _clean(block.text)
        if not text or len(text) < 5:
            continue
        text = re.sub(r"(?i)^(issuer|seller|from)\s*[:：]\s*", "", text)
        upper = text.upper()
        if upper in {
            "DEBIT NOTE", "CREDIT NOTE", "INVOICE", "COMMERCIAL INVOICE",
            "GENERAL NOTICE", "ARRIVAL NOTICE", "PRE-ALERT", "STATEMENT",
        }:
            continue
        if _COMPANY_SUFFIX.search(text):
            return text
    return None


def _extract_reference(text: str, subject: str) -> str | None:
    for source in (subject, text):
        for pattern in _REFERENCE_PATTERNS:
            match = pattern.search(source)
            if match:
                value = _clean(match.group(1))
                if (
                    value
                    and value.upper() not in _REF_BLACKLIST
                    and re.search(r"\d", value)
                ):
                    return value
    return None


_DATE_LABEL_RE = re.compile(
    r"(?i)\b(INVOICE\s+DATE|D/C\s+DATE|STATEMENT\s+DATE|RELEASE\s+DATE|"
    r"DUE\s+DATE|POD\s+ETA|ETA|ETD|ATD|DATE)\b\s*[:：]?\s*"
    r"(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})"
)


def _collect_date_candidates(
    text: str, meta: dict, primary: str | None
) -> list[DateCandidate]:
    candidates: list[DateCandidate] = []
    seen: set[tuple[str | None, str, str]] = set()

    raw_header = meta.get("date")
    if raw_header:
        try:
            iso = parsedate_to_datetime(str(raw_header)).date().isoformat()
            status = "CONFIRMED"
            possible = [iso]
        except (TypeError, ValueError):
            iso, status, possible = parse_date_info(str(raw_header))
        candidates.append(
            DateCandidate(
                label="EMAIL DATE",
                raw=str(raw_header),
                iso=iso,
                source="EMAIL_HEADER",
                status=status,
                candidates=possible,
            )
        )
        if iso:
            seen.add((iso, str(raw_header), "EMAIL_HEADER"))

    raw_match = _RAW_DATE_RE.search(text)
    if raw_match:
        raw = raw_match.group(1)
        iso, status, possible = parse_date_info(raw)
        candidates.append(
            DateCandidate(
                label="DOCUMENT DATE RAW",
                raw=raw,
                iso=iso,
                source="LABELED",
                status=status,
                candidates=possible,
            )
        )
        if iso:
            seen.add((iso, raw, "LABELED"))

    for match in _DATE_LABEL_RE.finditer(text):
        raw = match.group(2)
        iso, status, possible = parse_date_info(raw)
        key = (iso, raw, "LABELED")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            DateCandidate(
                label=match.group(1).upper(),
                raw=raw,
                iso=iso,
                source="LABELED",
                status=status,
                candidates=possible,
            )
        )

    for pattern in _GENERIC_DATE_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1)
            if any(item.raw == raw for item in candidates):
                continue
            iso, status, possible = parse_date_info(raw)
            if not possible:
                continue
            if iso and any(item.iso == iso for item in candidates):
                continue
            key = (iso, raw, "GENERIC")
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                DateCandidate(
                    raw=raw,
                    iso=iso,
                    source="GENERIC",
                    status=status,
                    candidates=possible,
                )
            )

    for candidate in candidates:
        candidate.selected = bool(primary and candidate.iso == primary)
    return candidates


def _extract_payment_status(
    text: str,
) -> tuple[str, bool | None, str]:
    """Return (status, payment_received, scope); never decides AR/AP."""
    match = _PAYMENT_RECEIVED_RE.search(text)
    if not match:
        return "UNKNOWN", None, "UNKNOWN"
    received = match.group(1).upper() == "YES"
    # Only claim a scope when the party/amount range is close to the
    # PAYMENT RECEIVED marker; "customer" elsewhere in a tariff notice must
    # not turn into a IMPORTER AP/AR conclusion.
    start = max(0, match.start() - 120)
    end = min(len(text), match.end() + 120)
    context = text[start:end].upper()
    if re.search(r"\b(CUSTOMER|BILL\s+TO|RECEIVABLE|客户|应收)\b", context):
        scope = "CUSTOMER_RECEIVABLE"
    elif re.search(r"\b(VENDOR|SUPPLIER|PAYABLE|供应商|应付)\b", context):
        scope = "VENDOR_PAYABLE"
    else:
        scope = "UNKNOWN"
    return ("PAID" if received else "UNPAID"), received, scope


def _extract_date_info(
    text: str, meta: dict
) -> tuple[str | None, str | None, str]:
    """Return (primary ISO, raw value, status); ambiguous dates stay null."""
    raw_header = meta.get("date")
    if raw_header:
        try:
            iso = parsedate_to_datetime(str(raw_header)).date().isoformat()
            return iso, str(raw_header), "CONFIRMED"
        except (TypeError, ValueError):
            iso, status, _ = parse_date_info(str(raw_header))
            return iso, str(raw_header), status

    raw_match = _RAW_DATE_RE.search(text)
    if raw_match:
        raw = raw_match.group(1)
        iso, status, _ = parse_date_info(raw)
        return iso, raw, status

    labeled: list[tuple[str, str, str]] = []
    for pattern in _LABELED_DATE_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1)
            iso, status, _ = parse_date_info(raw)
            if iso:
                labeled.append((iso, raw, status))
    if labeled:
        iso, raw, status = min(labeled, key=lambda item: item[0])
        return iso, raw, "CONFIRMED"

    # If only ambiguous dates exist, return the first raw value but no ISO.
    for pattern in _LABELED_DATE_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1)
            _iso, status, candidates = parse_date_info(raw)
            if status == "AMBIGUOUS" and candidates:
                return None, raw, "AMBIGUOUS"

    generic: list[tuple[str, str]] = []
    for pattern in _GENERIC_DATE_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1)
            iso, _status, _ = parse_date_info(raw)
            if iso:
                generic.append((iso, raw))
    if generic:
        iso, raw = min(generic, key=lambda item: item[0])
        return iso, raw, "CONFIRMED"
    return None, None, "UNKNOWN"


def _extract_date(text: str, meta: dict) -> str | None:
    return _extract_date_info(text, meta)[0]


def _extract_payment_due_instruction(text: str) -> str | None:
    match = _PAYMENT_DUE_RE.search(text)
    return re.sub(r"\s+", " ", match.group(1)).strip().upper() if match else None


def _extract_document_payment_term(text: str) -> str | None:
    match = _PAYMENT_TERM_RE.search(text)
    return match.group(1).upper() if match else None


def _extract_release_type(text: str) -> str:
    upper = text.upper()
    if "TELEX RELEASE" in upper or "TELEX-RELEASE" in upper:
        return "TELEX_RELEASE"
    if "ORIGINAL B/L" in upper or "ORIGINAL BILL OF LADING" in upper:
        return "ORIGINAL_BILL_OF_LADING"
    if "SEA WAYBILL" in upper or "SEAWAYBILL" in upper:
        return "SEA_WAYBILL"
    return "UNKNOWN"


def _extract_release_status(text: str) -> str:
    upper = text.upper()
    if re.search(r"\bHOLD\b", upper):
        return "HOLD"
    if re.search(r"\bRELEASED\b", upper):
        return "RELEASED"
    return "UNKNOWN"


def _extract_shipment_status(text: str) -> str:
    upper = text.upper()
    if re.search(r"\bHOLD\b", upper):
        return "HOLD"
    if "ARRIVED" in upper:
        return "ARRIVED"
    if "IN TRANSIT" in upper or "IN-TRANSIT" in upper:
        return "IN_TRANSIT"
    return "UNKNOWN"


def _extract_business_instructions(
    text: str, subject: str
) -> list[BusinessInstruction]:
    instructions: list[BusinessInstruction] = []
    for source_name, source in (("email_subject", subject), ("email_body", text)):
        if not source:
            continue
        for line in source.splitlines():
            upper = line.upper()
            if re.search(r"\bHOLD\b", upper):
                instructions.append(
                    BusinessInstruction(
                        kind="HOLD",
                        raw=line.strip(),
                        source=source_name,
                        status="ACTIVE",
                    )
                )
            if "TELEX RELEASE" in upper or "TELEX-RELEASE" in upper:
                instructions.append(
                    BusinessInstruction(
                        kind="TELEX_RELEASE",
                        raw=line.strip(),
                        source=source_name,
                        status="REQUESTED",
                    )
                )
    unique: list[BusinessInstruction] = []
    seen: set[tuple[str, str]] = set()
    for item in instructions:
        key = (item.kind, item.raw)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def _detect_type(search: str) -> tuple[str | None, str, str]:
    """Return (document_type, document_class, matched_signal)."""
    upper = search.upper()
    if "GENERAL NOTICE" in upper:
        return "General Notice", "notice", "GENERAL NOTICE"
    if "DEBIT NOTE" in upper or re.search(r"\bD/C\s*NO", upper):
        return "Debit Note", "billing", "DEBIT NOTE"
    if "CREDIT NOTE" in upper:
        return "Credit Note", "billing", "CREDIT NOTE"
    if "DEBIT INVOICE" in upper:
        return "Invoice", "billing", "DEBIT INVOICE"
    if re.search(
        r"(?im)^\s*(?:DOCUMENT\s+TYPE|TYPE)\s*[:：]\s*(?:COMMERCIAL\s+)?INVOICE\b",
        search,
    ):
        return "Invoice", "billing", "INVOICE"
    if "COMMERCIAL INVOICE" in upper or "INVOICE NO" in upper or "INVOICE DATE" in upper:
        return "Invoice", "billing", "INVOICE"
    if "ARRIVAL NOTICE" in upper:
        return "Arrival Notice", "notice", "ARRIVAL NOTICE"
    if "PRE-ALERT" in upper or "PRE ALERT" in upper:
        return "PRE-ALERT", "notice", "PRE-ALERT"
    if "STATEMENT" in upper:
        if "BALANCE DUE" in upper or "AMOUNT DUE" in upper:
            return "Statement", "billing", "STATEMENT + BALANCE DUE"
        return "Statement", "notice", "STATEMENT"
    if "BILL OF LADING" in upper or re.search(r"\bB/L\s*NO", upper) or "WAYBILL" in upper:
        return "Bill of Lading", "reference", "BILL OF LADING"
    return None, "unknown", "no document-type keyword"


def classify_document_rules(bundle: DocumentBundle) -> DocumentClassification:
    text = bundle.norm_text or bundle.raw_text
    subject = str(bundle.meta.get("subject") or "")
    search = f"{subject}\n{text}"
    upper = search.upper()

    # Coordinate-reconstructed rows are more reliable than get_text() ordering
    # for label/value pairs such as PAYMENT RECEIVED and spaced B/L numbers.
    evidence_text = "\n".join(block.text for block in bundle.blocks)
    pair_text = f"{text}\n{evidence_text}"

    document_type, document_class, signal = _detect_type(search)
    document_number, invoice_number = _extract_document_numbers(pair_text)
    reference_no = _extract_reference(text, subject)
    document_date, document_date_raw, document_date_status = _extract_date_info(
        pair_text or text, bundle.meta
    )
    mbl_no = _first_labeled(_MBL_PATTERN, pair_text) or _first_labeled(
        _MBL_PATTERN, subject
    )
    hbl_no = _first_labeled(_HBL_PATTERN, pair_text) or _first_labeled(
        _HBL_PATTERN, subject
    )
    waybill_no = _first_labeled(_WAYBILL_PATTERN, pair_text)
    bl_no = mbl_no or hbl_no or waybill_no or _extract_bl(text, subject)
    bl_no_raw, _bl_normalized = _extract_bl_pair(pair_text, subject)
    booking_no = _extract_booking(text)
    container_nos, container_sources = _extract_containers(text, subject)
    seal_nos = _extract_seals(text)
    date_candidates = _collect_date_candidates(pair_text, bundle.meta, document_date)
    payment_status, payment_received, payment_status_scope = _extract_payment_status(
        evidence_text or text
    )
    document_payment_term_raw = _extract_document_payment_term(search)
    document_payment_term_normalized = document_payment_term_raw
    payment_due_instruction = _extract_payment_due_instruction(search)
    due_date_match = _DUE_DATE_RE.search(pair_text or text)
    payment_due_date = (
        parse_date(due_date_match.group(1)) if due_date_match else None
    )
    release_type = _extract_release_type(search)
    release_status = _extract_release_status(search)
    shipment_operation_status = _extract_shipment_status(search)
    business_instructions = _extract_business_instructions(text, subject)

    # A B/L number is not a document number.  Only use reference_no when it
    # comes from an explicit document/email reference label.
    if document_number:
        reference_no = document_number
    elif reference_no and bl_no and reference_no.upper() == bl_no.upper():
        reference_no = None

    reference_no_raw = reference_no
    if reference_no and bl_no and reference_no.upper() == bl_no.upper() and bl_no_raw:
        reference_no_raw = bl_no_raw

    letterhead = _find_letterhead(bundle)
    issuer_candidates: list[str] = []
    if letterhead:
        issuer_candidates.append(letterhead)

    issuer = _label_value(text, ("ISSUER", "SELLER"))
    recipient = _label_value(text, ("BILL TO / PAYER", "BILL TO", "RECIPIENT"))
    payer = _label_value(text, ("BILL TO / PAYER", "PAYER"))
    payee = _label_value(
        text,
        ("BENEFICIARY", "REMIT TO / BENEFICIARY", "REMIT TO", "BALANCE DUE TO", "PAYABLE TO"),
    )
    beneficiary = _label_value(text, ("BENEFICIARY",)) or payee

    if not issuer and letterhead and payee and _same_name(letterhead, payee):
        issuer = letterhead
    if issuer and issuer not in issuer_candidates:
        issuer_candidates.insert(0, issuer)

    # Notices do not establish a payment obligation; keep money-flow fields empty.
    if document_class != "billing":
        payer = payee = beneficiary = None

    # PRE-ALERT emails often only expose parties in the subject line.
    subject_match = re.search(
        r"(?i)(.+?)\s+PRE-ALERT\s+[A-Z0-9]{6,}\s+(.+?)\s+\d+X\d+", subject
    )
    if subject_match:
        issuer_candidates.append(_clean(subject_match.group(1)))
        recipient = recipient or _clean(subject_match.group(2))
    subject_recipient = re.search(r"(?i)PRE-ALERT\s+[A-Z0-9]{6,}\s+(.+?)\s+\d+X\d+", subject)
    if subject_recipient:
        recipient = recipient or _clean(subject_recipient.group(1))

    recipient_candidates = [recipient] if recipient else []
    issuer_candidates = [value for value in dict.fromkeys(issuer_candidates) if value]

    evidence: list[str] = [f"matched {signal}"]
    void = bool(
        re.search(r"(?i)\b(VOID|VOIDED)\b|STATUS\s*[:：]?\s*CANCELLED|作废", search)
    )
    informational = any(
        token in upper for token in ("FOR REFERENCE ONLY", "NOT A BILL", "THIS IS NOT AN INVOICE")
    )
    tentative = any(
        token in upper for token in ("PROFORMA", "DRAFT", "ESTIMATE", "报价")
    ) or document_class == "notice"

    if void:
        billing_status = "void"
        evidence.append("matched VOID/CANCELLED")
    elif informational:
        billing_status = "informational"
        evidence.append("matched reference-only marker")
    elif document_class == "billing" and not tentative:
        billing_status = "confirmed"
        evidence.append("formal billing document, no PROFORMA/DRAFT/VOID")
    elif tentative:
        billing_status = "tentative"
        evidence.append("notice/tentative document")
    elif document_class == "reference":
        billing_status = "informational"
        evidence.append("reference document")
    else:
        billing_status = "unknown"
        evidence.append("insufficient status evidence")

    if reference_no:
        evidence.append(f"reference_no={reference_no}")
    if document_date:
        evidence.append(f"document_date={document_date}")

    confidence = 0.25 if document_class == "unknown" else 0.55
    if document_type:
        confidence += 0.15
    if reference_no:
        confidence += 0.10
    if document_date:
        confidence += 0.05
    if letterhead or recipient or payer or payee:
        confidence += 0.10
    confidence = min(round(confidence, 2), 0.95)

    reasoning = [
        f"document_type={document_type or 'unknown'} (signal: {signal})",
        f"document_class={document_class}",
        f"billing_status={billing_status}",
    ]
    if reference_no:
        reasoning.append(f"reference_no={reference_no}")
    if document_date:
        reasoning.append(f"document_date={document_date}")
    if letterhead and not issuer:
        reasoning.append(
            f"issuer candidate={letterhead!r}; identity is not confirmed"
        )
    if not issuer and not letterhead:
        reasoning.append("issuer is not explicit on the document")

    return DocumentClassification(
        document_type=document_type,
        document_class=document_class,
        billing_status=billing_status,
        billing_status_evidence=evidence,
        reference_no=reference_no,
        reference_no_raw=reference_no_raw,
        document_number=document_number,
        invoice_number=invoice_number,
        document_date=document_date,
        document_date_raw=document_date_raw,
        document_date_status=document_date_status,
        date_candidates=date_candidates,
        bl_no=bl_no,
        bl_no_raw=bl_no_raw,
        mbl_no=mbl_no,
        hbl_no=hbl_no,
        waybill_no=waybill_no,
        booking_no=booking_no,
        container_nos=container_nos,
        container_sources=container_sources,
        seal_nos=seal_nos,
        payment_status=payment_status,
        payment_received=payment_received,
        payment_status_scope=payment_status_scope,
        document_payment_term_raw=document_payment_term_raw,
        document_payment_term_normalized=document_payment_term_normalized,
        payment_due_instruction=payment_due_instruction,
        payment_due_date=payment_due_date,
        release_type=release_type,
        release_status=release_status,
        shipment_operation_status=shipment_operation_status,
        business_instructions=business_instructions,
        issuer=issuer,
        recipient=recipient,
        letterhead_party=letterhead,
        issuer_candidates=issuer_candidates,
        recipient_candidates=recipient_candidates,
        payer=payer,
        payee=payee,
        beneficiary=beneficiary,
        confidence=confidence,
        reasoning=reasoning,
    )

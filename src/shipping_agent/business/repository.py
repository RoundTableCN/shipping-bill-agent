"""Existing bill adapter and in-memory indexes."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..io.text_normalize import parse_currency, parse_date
from ..models.base import StrictModel
from ..models.output import PostingType
from ..models.types import Currency, ISODate, Money, to_decimal


class ExistingCharge(StrictModel):
    line_id: str
    charge_item: str
    charge_item_raw: str | None = None
    amount: Money
    currency: Currency
    payment_term: str | None = None


class ExistingBill(StrictModel):
    bill_id: str
    reference_no: str | None = None
    bl_no: str | None = None
    booking_no: str | None = None
    container_nos: list[str] = []
    document_date: ISODate | None = None
    parties: dict[str, str | None] = {}
    payer: str | None = None
    payee: str | None = None
    beneficiary: str | None = None
    currency: Currency | None = None
    charges: list[ExistingCharge] = []
    total: Money | None = None
    posting_type: PostingType | None = None
    raw: dict[str, Any] = {}
    warnings: list[str] = []


def _first(raw: dict, *keys: str, default=None):
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return default


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,;/\s]+", value) if item.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def _normalize_currency(value) -> str | None:
    code, _ = parse_currency(str(value) if value is not None else None)
    return code


def _parse_bill(raw: dict, index: int) -> ExistingBill:
    warnings: list[str] = []
    bill_id = str(
        _first(raw, "bill_id", "id", "reference_no", "ref_no", default=f"bill-{index}")
    )
    reference_no = _first(raw, "reference_no", "ref_no", "invoice_no", "dn_no", "document_no")
    bl_no = _first(raw, "bl_no", "b_l_no", "mbl_no", "house_bl_no")
    booking_no = _first(raw, "booking_no", "booking")
    containers = _as_list(_first(raw, "container_nos", "containers", "container_no"))

    parties = dict(raw.get("parties") or {})
    payer = _first(raw, "payer", default=parties.get("payer"))
    payee = _first(raw, "payee", default=parties.get("payee"))
    beneficiary = _first(raw, "beneficiary", default=payee)

    currency = _normalize_currency(_first(raw, "currency"))
    total_raw = _first(raw, "total", "total_amount")
    total = to_decimal(total_raw) if total_raw is not None else None

    charges: list[ExistingCharge] = []
    for line_index, item in enumerate(raw.get("charges") or [], start=1):
        if not isinstance(item, dict):
            continue
        name = _first(item, "charge_item", "charge_name", "description", "item")
        amount_raw = _first(item, "amount", "debit", "value")
        line_currency = _normalize_currency(_first(item, "currency", "cur", default=currency))
        if not name or amount_raw is None or not line_currency:
            warnings.append(f"skipped charge line {line_index}: missing name/amount/currency")
            continue
        try:
            amount = to_decimal(amount_raw)
        except (TypeError, ValueError):
            warnings.append(f"skipped charge line {line_index}: invalid amount")
            continue
        line_id = str(_first(item, "line_id", "id", default=f"{bill_id}-L{line_index}"))
        charges.append(
            ExistingCharge(
                line_id=line_id,
                charge_item=str(name),
                charge_item_raw=str(name),
                amount=amount,
                currency=line_currency,
                payment_term=_first(item, "payment_term", "terms", "pc"),
            )
        )

    return ExistingBill(
        bill_id=bill_id,
        reference_no=str(reference_no) if reference_no else None,
        bl_no=str(bl_no) if bl_no else None,
        booking_no=str(booking_no) if booking_no else None,
        container_nos=containers,
        document_date=parse_date(_first(raw, "document_date", "date", "invoice_date")),
        parties=parties,
        payer=str(payer) if payer else None,
        payee=str(payee) if payee else None,
        beneficiary=str(beneficiary) if beneficiary else None,
        currency=currency,
        charges=charges,
        total=total,
        posting_type=_first(raw, "posting_type"),
        raw=raw,
        warnings=warnings,
    )


class BillRepository:
    def __init__(self, bills: list[ExistingBill]):
        self.bills = bills
        self.by_reference: dict[str, list[ExistingBill]] = defaultdict(list)
        self.by_bl: dict[str, list[ExistingBill]] = defaultdict(list)
        self.by_booking: dict[str, list[ExistingBill]] = defaultdict(list)
        self.container_index: dict[str, list[ExistingBill]] = defaultdict(list)

        for bill in bills:
            if bill.reference_no:
                self.by_reference[bill.reference_no.upper()].append(bill)
            if bill.bl_no:
                self.by_bl[bill.bl_no.upper()].append(bill)
            if bill.booking_no:
                self.by_booking[bill.booking_no.upper()].append(bill)
            for container in bill.container_nos:
                self.container_index[container.upper()].append(bill)

    @classmethod
    def from_file(cls, path: str | Path) -> "BillRepository":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            raw_bills = data.get("bills", [])
        elif isinstance(data, list):
            raw_bills = data
        else:
            raw_bills = []
        return cls([_parse_bill(raw, index) for index, raw in enumerate(raw_bills, start=1)])

    def by_reference_no(self, reference_no: str | None) -> list[ExistingBill]:
        if not reference_no:
            return []
        return list(self.by_reference.get(reference_no.upper(), []))

    def by_bl_no(self, bl_no: str | None) -> list[ExistingBill]:
        if not bl_no:
            return []
        return list(self.by_bl.get(bl_no.upper(), []))

    def by_booking_no(self, booking_no: str | None) -> list[ExistingBill]:
        if not booking_no:
            return []
        return list(self.by_booking.get(booking_no.upper(), []))

    def by_container(self, container_no: str | None) -> list[ExistingBill]:
        if not container_no:
            return []
        return list(self.container_index.get(container_no.upper(), []))

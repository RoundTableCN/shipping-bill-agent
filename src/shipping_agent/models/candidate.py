"""Deterministic charge candidates passed to the LLM."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import StrictModel
from .bundle import SourceRef
from .output import CurrencySource

SourceKind = Literal["table_row", "text_line", "email_body", "ocr_row"]
PositionKind = Literal["table_row", "text_block", "email_body"]


class SourcePosition(StrictModel):
    """Stable source location for a charge line.

    - table row:   file_id + page + table_id + row_index
    - text block:  file_id + page + block_id + line_index
    - email body:  file_id + "email_body" + char_start + char_end
    """

    kind: PositionKind
    file_id: str
    page: int | None = None
    table_id: str | None = None
    row_index: int | None = None
    block_id: str | None = None
    line_index: int | None = None
    char_start: int | None = None
    char_end: int | None = None


class RawChargeLine(StrictModel):
    line_id: str
    source_position_id: str
    content_fingerprint: str
    candidate_id: str
    charge_raw: str | None = None
    charge_name_raw: str | None = None
    charge_code_raw: str | None = None
    qty_raw: str | None = None
    rate_raw: str | None = None
    amount_raw: str | None = None
    currency_raw: str | None = None
    currency_text_raw: str | None = None
    currency_source: CurrencySource | None = None
    payment_term_raw: str | None = None
    payment_due_instruction: str | None = None
    prepaid_collect_raw: str | None = None
    payer_code_raw: str | None = None
    payee_code_raw: str | None = None
    party_mapping_status: str | None = None
    charge_type_raw: str | None = None
    base_raw: str | None = None
    roe_raw: str | None = None
    settlement_amount_raw: str | None = None
    settlement_currency_raw: str | None = None
    subtotal_raw: str | None = None
    tax_raw: str | None = None
    total_raw: str | None = None
    source_kind: SourceKind
    evidence: SourceRef
    deterministic_flags: list[str] = Field(default_factory=list)

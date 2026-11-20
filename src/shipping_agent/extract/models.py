"""Structured extraction results (rules and LLM share these models)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..models.base import StrictModel
from ..models.output import (
    BillingStatus,
    BusinessInstruction,
    CurrencySource,
    DateCandidate,
    DateStatus,
    DocumentClass,
    MappingStatus,
    PaymentStatus,
    PaymentStatusScope,
    PrepaidCollectStatus,
    ReleaseStatus,
    ReleaseType,
    ShipmentOperationStatus,
)
from ..models.types import Currency, ISODate, Money


class DocumentClassification(StrictModel):
    document_type: str | None = None
    document_class: DocumentClass = "unknown"
    billing_status: BillingStatus = "unknown"
    billing_status_evidence: list[str] = Field(default_factory=list)

    reference_no: str | None = None
    reference_no_raw: str | None = None
    document_number: str | None = None
    invoice_number: str | None = None
    document_date: ISODate | None = None
    document_date_raw: str | None = None
    document_date_status: DateStatus = "UNKNOWN"
    date_candidates: list[DateCandidate] = Field(default_factory=list)
    bl_no: str | None = None
    bl_no_raw: str | None = None
    mbl_no: str | None = None
    hbl_no: str | None = None
    waybill_no: str | None = None
    booking_no: str | None = None
    container_nos: list[str] = Field(default_factory=list)
    container_sources: dict[str, str] = Field(default_factory=dict)
    seal_nos: list[str] = Field(default_factory=list)
    payment_status: PaymentStatus = "UNKNOWN"
    payment_received: bool | None = None
    payment_status_scope: PaymentStatusScope = "UNKNOWN"
    document_payment_term_raw: str | None = None
    document_payment_term_normalized: str | None = None
    payment_due_instruction: str | None = None
    payment_due_date: ISODate | None = None
    release_type: ReleaseType = "UNKNOWN"
    release_status: ReleaseStatus = "UNKNOWN"
    shipment_operation_status: ShipmentOperationStatus = "UNKNOWN"
    business_instructions: list[BusinessInstruction] = Field(default_factory=list)

    issuer: str | None = None
    recipient: str | None = None
    letterhead_party: str | None = None
    issuer_candidates: list[str] = Field(default_factory=list)
    recipient_candidates: list[str] = Field(default_factory=list)
    payer: str | None = None
    payee: str | None = None
    beneficiary: str | None = None
    payer_code_raw: str | None = None
    payee_code_raw: str | None = None
    party_mapping_status: str | None = None

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: list[str] = Field(default_factory=list)


class ExtractedCharge(StrictModel):
    candidate_id: str
    charge_raw: str | None = None
    charge_name_raw: str | None = None
    charge_code_raw: str | None = None
    charge_item: str | None = None
    candidate_standard_charge_name: str | None = None
    amount: Money | None = None
    currency: Currency | None = None
    currency_source: CurrencySource | None = None
    payment_term: str | None = None
    payment_due_instruction: str | None = None
    payment_due_date: ISODate | None = None
    prepaid_collect_raw: str | None = None
    prepaid_collect_normalized: str | None = None
    prepaid_collect_status: PrepaidCollectStatus | None = None
    quantity: Money | None = None
    unit_price: Money | None = None
    base_raw: str | None = None
    roe_raw: str | None = None
    payer_code_raw: str | None = None
    payee_code_raw: str | None = None
    party_mapping_status: str | None = None
    mapping_status: MappingStatus = "UNMATCHED"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_quote: str | None = None
    reasoning: list[str] = Field(default_factory=list)


class FieldChange(StrictModel):
    field: str
    charge_item: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    evidence_quote: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ChargeExtractionList(StrictModel):
    charges: list[ExtractedCharge] = Field(default_factory=list)


class ChangeIntentList(StrictModel):
    changes: list[FieldChange] = Field(default_factory=list)


class ExtractionResult(StrictModel):
    classification: DocumentClassification
    charges: list[ExtractedCharge] = Field(default_factory=list)
    change_intent: list[FieldChange] = Field(default_factory=list)
    source: Literal["rules", "llm", "rules_fallback"] = "rules"
    warnings: list[str] = Field(default_factory=list)

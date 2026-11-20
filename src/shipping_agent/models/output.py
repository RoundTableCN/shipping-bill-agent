"""Strict output models matching the exam's standard output format.

The four business objects (document_info, transaction_party, charge_details,
financial_attributes) allow only the keys defined by the exam. All audit
extensions live in ``audit_trail``. ``StrictOutputRecord`` is the exact
"strict mode" shape; ``OutputRecord`` is the internal/full shape.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, RootModel

from .base import StrictModel
from .types import Currency, ISODate, Money

Operation = Literal["CREATE", "UPDATE", "NO_CHANGE", "PENDING_REVIEW"]
PostingType = Literal["AR", "AP"]
DocumentClass = Literal["billing", "notice", "reference", "unknown"]
BillingStatus = Literal["confirmed", "tentative", "informational", "void", "unknown"]
PartyStatus = Literal["confirmed", "candidate", "unknown"]
ChargeDirection = Literal["to_us", "by_us", "ambiguous"]
DecisionStatus = Literal["AUTO", "REVIEW", "REJECT"]
AccountingStatus = Literal["CONFIRMED", "PENDING_CONFIRMATION"]
MappingStatus = Literal[
    "MATCHED", "CANDIDATE", "UNMATCHED", "PENDING_CONFIRMATION"
]
CurrencySource = Literal[
    "DOCUMENT_TEXT",
    "INFERRED_FROM_DOLLAR_SYMBOL",
    "DOCUMENT_DEFAULT",
    "MISSING",
    "LLM",
]
OperationStatus = Literal["PROVISIONAL", "CONFIRMED", "REJECTED"]
PaymentStatus = Literal["PAID", "UNPAID", "UNKNOWN"]
PaymentStatusScope = Literal[
    "CUSTOMER_RECEIVABLE", "VENDOR_PAYABLE", "UNKNOWN"
]
DateSource = Literal["EMAIL_HEADER", "LABELED", "GENERIC"]
DateStatus = Literal["CONFIRMED", "AMBIGUOUS", "UNKNOWN"]
PrepaidCollectStatus = Literal["CONFIRMED", "PENDING_CONFIRMATION", "UNKNOWN"]
ReleaseType = Literal[
    "TELEX_RELEASE", "ORIGINAL_BILL_OF_LADING", "SEA_WAYBILL", "UNKNOWN"
]
ReleaseStatus = Literal["HOLD", "RELEASED", "UNKNOWN"]
ShipmentOperationStatus = Literal["HOLD", "IN_TRANSIT", "ARRIVED", "UNKNOWN"]
InstructionKind = Literal["HOLD", "TELEX_RELEASE", "RELEASE", "OTHER"]
OcrMode = Literal["api", "degraded_local", "mock", "vision", "not_applicable"]


class DocumentInfo(StrictModel):
    document_type: str | None = None
    reference_no: str | None = None
    document_date: ISODate | None = None


class TransactionParty(StrictModel):
    issuer: str | None = None
    recipient: str | None = None


class ChargeDetails(StrictModel):
    charge_item: str | None = None
    amount: Money | None = None
    currency: Currency | None = None
    payment_term: str | None = None


class FinancialAttributes(StrictModel):
    accounting_entity: str | None = None
    posting_type: PostingType | None = None


class ChargeBreakdown(StrictModel):
    quantity: Money | None = None
    unit_price: Money | None = None
    rate: Money | None = None


class DocumentTotals(StrictModel):
    subtotal: Money | None = None
    tax: Money | None = None
    total: Money | None = None


class RawNormalized(StrictModel):
    raw: str | None = None
    normalized: str | None = None


class MoneyValue(StrictModel):
    raw: str | None = None
    normalized: Money | None = None


class DateCandidate(StrictModel):
    label: str | None = None
    raw: str | None = None
    iso: ISODate | None = None
    source: DateSource
    selected: bool = False
    status: DateStatus = "UNKNOWN"
    candidates: list[ISODate] = Field(default_factory=list)


class BusinessInstruction(StrictModel):
    kind: InstructionKind
    raw: str
    source: str | None = None
    status: str | None = None


class DocumentIdentityAudit(StrictModel):
    document_number: RawNormalized | None = None
    invoice_number: RawNormalized | None = None
    reference_no: RawNormalized | None = None
    bl_no: RawNormalized | None = None
    mbl_no: RawNormalized | None = None
    hbl_no: RawNormalized | None = None
    waybill_no: RawNormalized | None = None
    booking_no: RawNormalized | None = None
    container_nos: list[str] = Field(default_factory=list)
    container_sources: dict[str, str] = Field(default_factory=dict)
    seal_nos: list[str] = Field(default_factory=list)
    date_candidates: list[DateCandidate] = Field(default_factory=list)
    document_date_raw: str | None = None
    document_date_status: DateStatus | None = None


class ChargeValuesAudit(StrictModel):
    charge_code_raw: str | None = None
    charge_name_raw: str | None = None
    original_charge_name: str | None = None
    standard_charge_name: str | None = None
    candidate_standard_charge_name: str | None = None
    mapping_status: MappingStatus | None = None
    quantity: MoneyValue | None = None
    rate: MoneyValue | None = None
    amount: MoneyValue | None = None
    roe: MoneyValue | None = None
    base: str | None = None
    base_review_required: bool = False
    settlement_amount: MoneyValue | None = None
    settlement_currency: Currency | None = None
    currency: RawNormalized | None = None
    currency_source: CurrencySource | None = None
    payment_term: RawNormalized | None = None
    payment_due_instruction: str | None = None
    payment_due_date: ISODate | None = None
    prepaid_collect_raw: str | None = None
    prepaid_collect_normalized: str | None = None
    prepaid_collect_status: PrepaidCollectStatus | None = None
    payer_code_raw: str | None = None
    payee_code_raw: str | None = None
    party_mapping_status: str | None = None
    charge_type: str | None = None


class StatusAudit(StrictModel):
    operation_status: OperationStatus | None = None
    candidate_posting_type: PostingType | None = None
    accounting_direction: ChargeDirection | None = None
    candidate_direction: ChargeDirection | None = None
    accounting_status: AccountingStatus | None = None
    payment_status: PaymentStatus | None = None
    payment_received: bool | None = None
    payment_status_scope: PaymentStatusScope | None = None
    release_type: ReleaseType | None = None
    release_status: ReleaseStatus | None = None
    shipment_operation_status: ShipmentOperationStatus | None = None
    business_instructions: list[BusinessInstruction] = Field(default_factory=list)


class ValidationReport(StrictModel):
    passed: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SourceTrace(StrictModel):
    file: str
    file_id: str
    page: int | None = None
    bbox: list[float] | None = None
    quote: str | None = None
    field_path: str | None = None


class MatchCandidate(StrictModel):
    bill_id: str
    line_id: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    reason: str | None = None


class MatchAttempt(StrictModel):
    rule: str
    matched: bool = False
    candidate_count: int = Field(default=0, ge=0)
    note: str | None = None


class AuditTrail(StrictModel):
    """Full audit trail. Every field is explicit; no ``extra='allow'``."""

    ai_reasoning: list[str]

    document_class: DocumentClass | None = None
    billing_status: BillingStatus | None = None
    billing_status_evidence: list[str] | None = None

    original_charge_item: str | None = None
    line_id: str | None = None
    source_position_id: str | None = None
    content_fingerprint: str | None = None
    historical_line_id: str | None = None

    charge_breakdown: ChargeBreakdown | None = None
    candidate_amount: Money | None = None
    document_totals: DocumentTotals | None = None

    letterhead_party: str | None = None
    issuer_candidate: list[str] | None = None
    issuer_status: PartyStatus | None = None
    recipient_candidate: list[str] | None = None
    recipient_status: PartyStatus | None = None

    payer: str | None = None
    payee: str | None = None
    beneficiary: str | None = None
    charge_direction: ChargeDirection | None = None
    candidate_posting_type: PostingType | None = None
    accounting_direction: ChargeDirection | None = None
    candidate_direction: ChargeDirection | None = None
    accounting_status: AccountingStatus | None = None
    collection_right: bool | None = None
    payment_obligation: bool | None = None

    document_identity: DocumentIdentityAudit | None = None
    charge_values: ChargeValuesAudit | None = None
    status: StatusAudit | None = None
    source: SourceTrace | None = None
    raw_text_excerpt: str | None = None

    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    document_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    arap_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    decision_status: DecisionStatus | None = None

    validation: ValidationReport | None = None
    matched_bill_id: str | None = None
    match_rule: str | None = None
    match_candidates: list[MatchCandidate] | None = None
    strict_attempts: list[MatchAttempt] | None = None
    enhanced_attempts: list[MatchAttempt] | None = None

    changes: list[str] | None = None
    inherited_fields: list[str] | None = None
    amount_changed: bool | None = None
    document_operation_summary: dict[str, int] | None = None
    history_checked: bool | None = None
    ocr_mode: OcrMode | None = None


class OutputRecord(StrictModel):
    operation: Operation
    document_info: DocumentInfo
    transaction_party: TransactionParty
    charge_details: ChargeDetails
    financial_attributes: FinancialAttributes
    audit_trail: AuditTrail


class FullOutputDocument(RootModel[list[OutputRecord]]):
    """The full output is a JSON array of records."""


class StrictAuditTrail(StrictModel):
    """Strict mode keeps only the key required by the exam example."""

    ai_reasoning: list[str]


class StrictOutputRecord(StrictModel):
    operation: Operation
    document_info: DocumentInfo
    transaction_party: TransactionParty
    charge_details: ChargeDetails
    financial_attributes: FinancialAttributes
    audit_trail: StrictAuditTrail


class StrictOutputDocument(RootModel[list[StrictOutputRecord]]):
    """Strict output matches the exam's standard output format exactly."""

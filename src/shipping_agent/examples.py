"""Reusable example records for tests and demos."""

from decimal import Decimal

from .models.output import (
    AuditTrail,
    ChargeBreakdown,
    ChargeDetails,
    DocumentInfo,
    DocumentTotals,
    FinancialAttributes,
    MatchAttempt,
    OutputRecord,
    SourceTrace,
    TransactionParty,
    ValidationReport,
)


def sample_prealert_record() -> OutputRecord:
    """The EML PRE-ALERT case: extract the fee but do not post it."""
    return OutputRecord(
        operation="PENDING_REVIEW",
        document_info=DocumentInfo(
            document_type="PRE-ALERT",
            reference_no="PREALERT-DEMO-001",
            document_date="2026-10-20",
        ),
        transaction_party=TransactionParty(issuer=None, recipient=None),
        charge_details=ChargeDetails(
            charge_item="Handling Charge",
            amount=Decimal("50.00"),
            currency="USD",
            payment_term=None,
        ),
        financial_attributes=FinancialAttributes(
            accounting_entity="Importer Beta (Shanghai)",
            posting_type=None,
        ),
        audit_trail=AuditTrail(
            ai_reasoning=[
                "费用出现在 PRE-ALERT 邮件正文，不是正式账单",
                "签发方/接收方仅为主题行推断，未写入正式字段",
                "付款方/收款方/付款方式未确认，AR/AP 待复核",
            ],
            document_class="notice",
            billing_status="tentative",
            billing_status_evidence=["PRE-ALERT in subject", "no invoice number"],
            original_charge_item="H/C",
            line_id="eml-body-line-12",
            source_position_id="eml-body-line-12",
            content_fingerprint="sha256:demo",
            charge_breakdown=ChargeBreakdown(),
            candidate_amount=Decimal("50.00"),
            document_totals=DocumentTotals(),
            issuer_candidate=["示例物流科技"],
            issuer_status="candidate",
            recipient_candidate=["EXAMPLE CONSIGNEE LLC"],
            recipient_status="candidate",
            charge_direction="ambiguous",
            source=SourceTrace(
                file="sample.eml",
                file_id="a1b2c3d4e5f6",
                quote="SHA pay TAR：H/C $50",
            ),
            raw_text_excerpt="Carrier Free H/C\nSHA pay TAR：H/C $50",
            confidence=0.55,
            extraction_confidence=0.72,
            document_confidence=0.95,
            arap_confidence=0.0,
            decision_status="REVIEW",
            validation=ValidationReport(
                passed=False,
                errors=["E_DOC_NOT_BILLING", "E_ARAP_UNDETERMINED"],
                warnings=["W_DATE_INCONSISTENT", "W_CURRENCY_INFERRED"],
            ),
            match_candidates=[],
            strict_attempts=[MatchAttempt(rule="STRICT_L1", matched=False)],
            enhanced_attempts=[MatchAttempt(rule="ENHANCED_E4", matched=False)],
            changes=[],
            inherited_fields=[],
            amount_changed=False,
            document_operation_summary={
                "CREATE": 0,
                "UPDATE": 0,
                "NO_CHANGE": 0,
                "PENDING_REVIEW": 1,
            },
            ocr_mode="not_applicable",
        ),
    )

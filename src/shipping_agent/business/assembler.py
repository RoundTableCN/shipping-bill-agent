"""Assemble final OutputRecord objects from extraction + rules."""

from __future__ import annotations

from collections import Counter

from ..extract.models import DocumentClassification, ExtractionResult
from ..io.text_normalize import parse_amount, parse_currency
from ..models.candidate import RawChargeLine
from ..models.output import (
    AuditTrail,
    ChargeBreakdown,
    ChargeDetails,
    ChargeValuesAudit,
    DocumentIdentityAudit,
    DocumentInfo,
    DocumentTotals,
    FinancialAttributes,
    MoneyValue,
    OutputRecord,
    RawNormalized,
    SourceTrace,
    StatusAudit,
    TransactionParty,
    ValidationReport,
)
from .ar_ap import ArapResult
from .decision import DecisionResult
from .matcher import MatchResult


def _confidence(classification: DocumentClassification, charge, arap: ArapResult) -> float:
    values = [classification.confidence, charge.confidence]
    if arap.posting_type is not None or arap.candidate_posting_type is not None:
        values.append(arap.confidence)
    return round(min(values), 2)


_STANDARD_BASES = {"C", "P", "PP", "CC", "F", "W", "M"}


def _document_identity(classification: DocumentClassification) -> DocumentIdentityAudit:
    return DocumentIdentityAudit(
        document_number=RawNormalized(
            normalized=classification.document_number
        ),
        invoice_number=RawNormalized(
            normalized=classification.invoice_number
        ),
        reference_no=RawNormalized(
            raw=classification.reference_no_raw or classification.reference_no,
            normalized=classification.reference_no,
        ),
        bl_no=RawNormalized(
            raw=classification.bl_no_raw or classification.bl_no,
            normalized=classification.bl_no,
        ),
        mbl_no=RawNormalized(normalized=classification.mbl_no),
        hbl_no=RawNormalized(normalized=classification.hbl_no),
        waybill_no=RawNormalized(normalized=classification.waybill_no),
        booking_no=RawNormalized(normalized=classification.booking_no),
        container_nos=classification.container_nos,
        container_sources=classification.container_sources,
        seal_nos=classification.seal_nos,
        date_candidates=classification.date_candidates,
        document_date_raw=classification.document_date_raw,
        document_date_status=classification.document_date_status,
    )


def _money_value(raw: str | None, normalized=None) -> MoneyValue:
    return MoneyValue(
        raw=raw,
        normalized=normalized if normalized is not None else parse_amount(raw),
    )


def _charge_values(
    charge,
    candidate: RawChargeLine | None,
) -> ChargeValuesAudit:
    base = candidate.base_raw if candidate else None
    settlement_currency, _ = parse_currency(
        candidate.settlement_currency_raw if candidate else None
    )
    return ChargeValuesAudit(
        charge_code_raw=charge.charge_code_raw,
        charge_name_raw=charge.charge_name_raw or charge.charge_raw,
        original_charge_name=charge.charge_raw,
        standard_charge_name=(
            charge.charge_item if charge.mapping_status == "MATCHED" else None
        ),
        candidate_standard_charge_name=charge.candidate_standard_charge_name,
        mapping_status=charge.mapping_status,
        quantity=_money_value(
            candidate.qty_raw if candidate else None, charge.quantity
        ),
        rate=_money_value(
            candidate.rate_raw if candidate else None, charge.unit_price
        ),
        amount=_money_value(
            candidate.amount_raw if candidate else None, charge.amount
        ),
        roe=_money_value(candidate.roe_raw if candidate else charge.roe_raw),
        base=charge.base_raw or base,
        base_review_required=bool(
            (charge.base_raw or base)
            and (charge.base_raw or base).strip().upper() not in _STANDARD_BASES
        ),
        settlement_amount=_money_value(
            candidate.settlement_amount_raw if candidate else None
        ),
        settlement_currency=settlement_currency,
        currency=RawNormalized(
            raw=(
                candidate.currency_text_raw
                if candidate and candidate.currency_text_raw
                else (candidate.currency_raw if candidate else None)
            ),
            normalized=charge.currency,
        ),
        currency_source=(
            candidate.currency_source
            if candidate and candidate.currency_source
            else charge.currency_source
        ),
        payment_term=RawNormalized(
            raw=candidate.payment_term_raw if candidate else None,
            normalized=charge.payment_term,
        ),
        payment_due_instruction=charge.payment_due_instruction,
        payment_due_date=charge.payment_due_date,
        prepaid_collect_raw=charge.prepaid_collect_raw,
        prepaid_collect_normalized=charge.prepaid_collect_normalized,
        prepaid_collect_status=charge.prepaid_collect_status,
        payer_code_raw=charge.payer_code_raw,
        payee_code_raw=charge.payee_code_raw,
        party_mapping_status=charge.party_mapping_status,
        charge_type=candidate.charge_type_raw if candidate else None,
    )


def _operation_status(decision: DecisionResult) -> str:
    if decision.decision_status == "REJECT":
        return "REJECTED"
    if decision.operation in {"UPDATE", "NO_CHANGE"}:
        return "CONFIRMED"
    return "PROVISIONAL"


def assemble_records(
    classification: DocumentClassification,
    extraction: ExtractionResult,
    matches: list[MatchResult],
    arap_results: list[ArapResult],
    decisions: list[DecisionResult],
    candidates: list[RawChargeLine],
    *,
    ocr_mode: str = "not_applicable",
    extra_warnings: list[str] | None = None,
    document_totals: DocumentTotals | None = None,
    validation: ValidationReport | None = None,
    validation_by_id: dict[str, ValidationReport] | None = None,
    history_checked: bool = True,
) -> list[OutputRecord]:
    candidate_by_id = {candidate.candidate_id: candidate for candidate in candidates}
    match_by_id = {result.candidate_id: result for result in matches}
    # ARAP results are positional; map by index to charges.
    arap_by_index = {
        charge.candidate_id: arap
        for charge, arap in zip(extraction.charges, arap_results)
    }
    decision_by_index = {
        charge.candidate_id: decision
        for charge, decision in zip(extraction.charges, decisions)
    }

    summary = Counter(decision.operation for decision in decisions)
    document_operation_summary = {
        "CREATE": summary.get("CREATE", 0),
        "UPDATE": summary.get("UPDATE", 0),
        "NO_CHANGE": summary.get("NO_CHANGE", 0),
        "PENDING_REVIEW": summary.get("PENDING_REVIEW", 0),
    }

    records: list[OutputRecord] = []
    for record_index, charge in enumerate(extraction.charges):
        candidate = candidate_by_id.get(charge.candidate_id)
        match = match_by_id.get(charge.candidate_id)
        arap = arap_by_index.get(charge.candidate_id)
        decision = decision_by_index.get(charge.candidate_id)
        if arap is None or decision is None:
            continue

        reasoning: list[str] = []
        reasoning.extend(classification.reasoning)
        reasoning.extend(charge.reasoning)
        if match:
            reasoning.extend(match.notes)
        reasoning.extend(decision.reasons)
        reasoning.extend(arap.reasoning)
        reasoning = list(dict.fromkeys(item for item in reasoning if item))

        source = None
        line_id = None
        source_position_id = None
        content_fingerprint = None
        raw_excerpt = None
        if candidate is not None:
            line_id = candidate.line_id
            source_position_id = candidate.source_position_id
            content_fingerprint = candidate.content_fingerprint
            raw_excerpt = candidate.evidence.quote
            source = SourceTrace(
                file=candidate.evidence.file_name,
                file_id=candidate.evidence.file_id,
                page=candidate.evidence.page,
                bbox=candidate.evidence.bbox,
                quote=candidate.evidence.quote,
            )

        warnings = list(decision.validation_warnings)
        warnings.extend(extraction.warnings)
        warnings.extend(extra_warnings or [])
        record_validation = (
            validation_by_id.get(charge.candidate_id)
            if validation_by_id is not None
            else validation
        )
        if record_validation is not None:
            warnings.extend(record_validation.warnings)
        warnings = list(dict.fromkeys(warnings))
        errors = list(decision.validation_errors)
        if record_validation is not None:
            errors.extend(record_validation.errors)
        errors = list(dict.fromkeys(errors))

        attempts = match.attempts if match else []
        strict_attempts = [item for item in attempts if item.rule.startswith("STRICT")]
        enhanced_attempts = [item for item in attempts if item.rule.startswith("ENHANCED")]

        audit = AuditTrail(
            ai_reasoning=reasoning,
            document_class=classification.document_class,
            billing_status=classification.billing_status,
            billing_status_evidence=classification.billing_status_evidence,
            original_charge_item=charge.charge_raw,
            line_id=line_id,
            source_position_id=source_position_id,
            content_fingerprint=content_fingerprint,
            historical_line_id=match.line.line_id if match and match.line else None,
            charge_breakdown=ChargeBreakdown(
                quantity=charge.quantity,
                unit_price=charge.unit_price,
                rate=charge.unit_price,
            ),
            candidate_amount=charge.amount,
            document_totals=(
                (document_totals or DocumentTotals())
                if record_index == 0
                else None
            ),
            letterhead_party=classification.letterhead_party,
            issuer_candidate=classification.issuer_candidates,
            issuer_status="candidate" if classification.issuer_candidates else None,
            recipient_candidate=classification.recipient_candidates,
            recipient_status="candidate" if classification.recipient_candidates else None,
            payer=classification.payer,
            payee=classification.payee,
            beneficiary=classification.beneficiary,
            charge_direction=arap.charge_direction,
            candidate_posting_type=arap.candidate_posting_type,
            accounting_direction=arap.accounting_direction,
            candidate_direction=arap.candidate_direction,
            accounting_status=arap.accounting_status,
            collection_right=arap.collection_right,
            payment_obligation=arap.payment_obligation,
            document_identity=_document_identity(classification),
            charge_values=_charge_values(charge, candidate),
            status=StatusAudit(
                operation_status=_operation_status(decision),
                candidate_posting_type=arap.candidate_posting_type,
                accounting_direction=arap.accounting_direction,
                candidate_direction=arap.candidate_direction,
                accounting_status=arap.accounting_status,
                payment_status=classification.payment_status,
                payment_received=classification.payment_received,
                payment_status_scope=classification.payment_status_scope,
                release_type=classification.release_type,
                release_status=classification.release_status,
                shipment_operation_status=classification.shipment_operation_status,
                business_instructions=classification.business_instructions,
            ),
            source=source,
            raw_text_excerpt=raw_excerpt,
            confidence=_confidence(classification, charge, arap),
            extraction_confidence=charge.confidence,
            document_confidence=classification.confidence,
            arap_confidence=arap.confidence,
            decision_status=decision.decision_status,
            validation=ValidationReport(
                passed=not errors,
                errors=errors,
                warnings=warnings,
            ),
            matched_bill_id=match.bill.bill_id if match and match.bill else None,
            match_rule=match.rule if match else None,
            match_candidates=match.candidates if match else None,
            strict_attempts=strict_attempts or None,
            enhanced_attempts=enhanced_attempts or None,
            changes=decision.changes,
            inherited_fields=decision.inherited_fields,
            amount_changed=decision.amount_changed,
            document_operation_summary=(
                document_operation_summary if record_index == 0 else None
            ),
            history_checked=history_checked,
            ocr_mode=ocr_mode,
        )

        records.append(
            OutputRecord(
                operation=decision.operation,
                document_info=DocumentInfo(
                    document_type=classification.document_type,
                    reference_no=classification.reference_no,
                    document_date=classification.document_date,
                ),
                transaction_party=TransactionParty(
                    issuer=classification.issuer,
                    recipient=classification.recipient,
                ),
                charge_details=ChargeDetails(
                    charge_item=decision.final_charge_item,
                    amount=decision.final_amount,
                    currency=decision.final_currency,
                    payment_term=decision.final_payment_term,
                ),
                financial_attributes=FinancialAttributes(
                    accounting_entity=arap.accounting_entity,
                    posting_type=arap.posting_type,
                ),
                audit_trail=audit,
            )
        )

    return records

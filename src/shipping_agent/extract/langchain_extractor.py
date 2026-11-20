"""LangChain structured-extraction implementation."""

from __future__ import annotations

import json

from ..business.charge_mapper import default_mapper
from ..business.document_class import classify_document_rules
from ..models.bundle import DocumentBundle
from ..models.candidate import RawChargeLine
from .evidence import evidence_in_text
from .rules import RuleBasedExtractor
from .models import (
    ChangeIntentList,
    ChargeExtractionList,
    DocumentClassification,
    ExtractedCharge,
    ExtractionResult,
    FieldChange,
)
from .prompts import change_prompt, charge_prompt, classification_prompt


_GROUNDED_FIELDS = (
    "reference_no",
    "reference_no_raw",
    "document_number",
    "invoice_number",
    "bl_no",
    "bl_no_raw",
    "mbl_no",
    "hbl_no",
    "waybill_no",
    "booking_no",
    "container_nos",
    "container_sources",
    "seal_nos",
    "document_date",
    "document_date_raw",
    "document_date_status",
    "date_candidates",
    "payment_status",
    "payment_received",
    "payment_status_scope",
    "document_payment_term_raw",
    "document_payment_term_normalized",
    "payment_due_instruction",
    "payment_due_date",
    "release_type",
    "release_status",
    "shipment_operation_status",
    "business_instructions",
    "payer_code_raw",
    "payee_code_raw",
    "party_mapping_status",
)


def _plausible_party(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip()
    if len(text) <= 2:
        return False
    if text.upper() in {"LI", "TO", "FROM", "CC", "BCC", "SUBJECT"}:
        return False
    return True


def _reconcile_classification(llm, rule):
    """Keep LLM semantic output, but ground identity/date/status in rules.

    LLMs are useful for document interpretation, but they must not invent
    reference numbers, copy a B/L into reference_no, turn an ambiguous date
    into a confirmed one, or use an email header fragment as a party.
    """
    if llm.reasoning is None:
        llm.reasoning = []
    old_reference = llm.reference_no
    old_date = llm.document_date
    llm.document_type = rule.document_type or llm.document_type
    if rule.document_class != "unknown":
        llm.document_class = rule.document_class
    if rule.billing_status != "unknown":
        llm.billing_status = rule.billing_status
    if rule.billing_status_evidence:
        llm.billing_status_evidence = list(rule.billing_status_evidence)

    for field in _GROUNDED_FIELDS:
        setattr(llm, field, getattr(rule, field))

    llm.letterhead_party = rule.letterhead_party
    llm.issuer_candidates = list(rule.issuer_candidates)
    llm.recipient_candidates = list(rule.recipient_candidates)
    llm.issuer = rule.issuer or (llm.issuer if _plausible_party(llm.issuer) else None)
    llm.recipient = rule.recipient or (
        llm.recipient if _plausible_party(llm.recipient) else None
    )
    # Money-flow roles are deterministic; do not let the LLM promote a code
    # or an email header into payer/payee/beneficiary.
    llm.payer = rule.payer
    llm.payee = rule.payee
    llm.beneficiary = rule.beneficiary

    if old_reference != llm.reference_no:
        llm.reasoning.append(
            f"rule reconciliation: reference_no {old_reference!r} -> "
            f"{llm.reference_no!r}"
        )
    if old_date != llm.document_date:
        llm.reasoning.append(
            f"rule reconciliation: document_date {old_date!r} -> "
            f"{llm.document_date!r} ({llm.document_date_status})"
        )
    llm.reasoning.append(
        "deterministic identity/date/payment fields override LLM output; "
        "LLM notes above are advisory"
    )
    return llm


class LangChainExtractor:
    def __init__(self, model, method: str = "function_calling"):
        self.model = model
        self.method = method
        self.classification_chain = classification_prompt() | model.with_structured_output(
            DocumentClassification, method=method
        )
        self.charge_chain = charge_prompt() | model.with_structured_output(
            ChargeExtractionList, method=method
        )
        self.change_chain = change_prompt() | model.with_structured_output(
            ChangeIntentList, method=method
        )

    def extract(
        self,
        bundle: DocumentBundle,
        candidates: list[RawChargeLine],
        existing_bill: dict | None = None,
    ) -> ExtractionResult:
        text = (bundle.norm_text or bundle.raw_text)[:12000]
        hint = str(bundle.meta.get("subject") or bundle.media_type or "")
        warnings: list[str] = []

        classification = self.classification_chain.invoke({"hint": hint, "text": text})
        if classification.document_type:
            canonical = {
                "COMMERCIAL INVOICE": "Invoice",
                "DEBIT INVOICE": "Invoice",
                "INVOICE": "Invoice",
                "DEBIT NOTE": "Debit Note",
                "CREDIT NOTE": "Credit Note",
                "GENERAL NOTICE": "General Notice",
                "PRE-ALERT": "PRE-ALERT",
            }.get(classification.document_type.strip().upper())
            if canonical:
                classification.document_type = canonical
        classification = _reconcile_classification(
            classification, classify_document_rules(bundle)
        )

        candidates_payload = [
            candidate.model_dump(mode="json") for candidate in candidates
        ]
        charge_list = self.charge_chain.invoke(
            {
                "document_type": classification.document_type or "unknown",
                "candidates": json.dumps(candidates_payload, ensure_ascii=False),
                "text": text[:6000],
            }
        )

        valid_ids = {candidate.candidate_id for candidate in candidates}
        mapper = default_mapper()
        # Use the deterministic extractor as the baseline for charge values.
        # The LLM may interpret names, but it must not invent quantity, rate,
        # amount, currency, P/C, payer/payee codes, or payment instructions.
        rule_result = RuleBasedExtractor(mapper).extract(
            bundle, candidates, existing_bill
        )
        llm_by_id: dict[str, ExtractedCharge] = {}
        for charge in charge_list.charges:
            if charge.candidate_id not in valid_ids:
                warnings.append(f"LLM_UNKNOWN_CANDIDATE: {charge.candidate_id}")
                continue
            if charge.evidence_quote and not evidence_in_text(
                charge.evidence_quote, bundle
            ):
                warnings.append(f"EVIDENCE_NOT_FOUND: {charge.candidate_id}")
                charge.confidence = max(0.0, charge.confidence - 0.2)
            llm_by_id[charge.candidate_id] = charge

        charges: list[ExtractedCharge] = []
        for base in rule_result.charges:
            llm_charge = llm_by_id.get(base.candidate_id)
            if llm_charge is None:
                charges.append(base)
                continue
            # Only use the LLM name when the deterministic mapper had no match
            # and the LLM name maps to a confirmed standard name.
            if base.mapping_status == "UNMATCHED":
                raw_name = (
                    llm_charge.charge_name_raw
                    or llm_charge.charge_raw
                    or llm_charge.charge_item
                )
                standard, status = mapper.standardize_with_status(raw_name)
                if status == "MATCHED":
                    base.charge_item = standard
                    base.candidate_standard_charge_name = standard
                    base.mapping_status = status
            if llm_charge.evidence_quote and not base.evidence_quote:
                base.evidence_quote = llm_charge.evidence_quote
            if llm_charge.reasoning:
                base.reasoning.extend(
                    f"LLM: {item}" for item in llm_charge.reasoning
                )
            base.reasoning.append(
                "LLM charge numeric/column fields were ignored; deterministic "
                "candidate values were used"
            )
            charges.append(base)

        warnings.extend(rule_result.warnings)
        if not charge_list.charges:
            warnings.append("LLM_NO_CHARGES: model returned no charge candidates")

        changes: list[FieldChange] = []
        if existing_bill is not None:
            change_list = self.change_chain.invoke(
                {
                    "existing_bill": json.dumps(
                        existing_bill, ensure_ascii=False, default=str
                    ),
                    "text": text,
                }
            )
            for change in change_list.changes:
                if change.evidence_quote and not evidence_in_text(
                    change.evidence_quote, bundle
                ):
                    warnings.append("EVIDENCE_NOT_FOUND: change_intent")
                    continue
                changes.append(change)

        if not charges:
            warnings.append("LLM_NO_CHARGES: model returned no charge candidates")

        return ExtractionResult(
            classification=classification,
            charges=charges,
            change_intent=changes,
            source="llm",
            warnings=list(dict.fromkeys(warnings)),
        )

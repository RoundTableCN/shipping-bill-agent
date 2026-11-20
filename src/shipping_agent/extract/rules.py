"""Deterministic extraction baseline. Always works offline."""

from __future__ import annotations

import re

from ..business.charge_mapper import ChargeMapper, default_mapper
from ..business.document_class import classify_document_rules
from ..io.text_normalize import parse_amount, parse_currency
from ..models.bundle import DocumentBundle
from ..models.candidate import RawChargeLine
from .change_intent import extract_change_intent
from .evidence import evidence_in_text
from .models import ExtractedCharge, ExtractionResult

_CURRENCY_RE = re.compile(r"(?i)\bCURRENCY\s*[:：]?\s*([A-Z]{3})\b")
_TERM_RE = re.compile(r"(?i)\bTERMS?\s*[:：]?\s*(PP|CC|COD)\b")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 2)))


def normalize_payment_term(value: str | None) -> str | None:
    """Only explicit PP/CC/COD is a payment term.

    A single ``P``/``C`` belongs to a P/C (prepaid/collect) column and must
    never be silently expanded to PP/CC.
    """
    if not value:
        return None
    upper = value.strip().upper()
    if upper in {"PP", "PREPAID", "预付"}:
        return "PP"
    if upper in {"CC", "COLLECT", "到付"}:
        return "CC"
    if upper == "COD":
        return "COD"
    return None


def normalize_prepaid_collect(
    value: str | None,
) -> tuple[str | None, str]:
    """Return (normalized, status) for a P/C cell.

    A bare ``C`` is left unnormalized because the source does not tell us
    whether it means Collect or a charge code; ``CC`` is explicit.
    """
    if not value:
        return None, "UNKNOWN"
    upper = re.sub(r"\s+", "", value.upper())
    if upper in {"P", "PP", "PREPAID"}:
        return "PREPAID", "CONFIRMED"
    if upper in {"CC", "COLLECT"}:
        return "COLLECT", "CONFIRMED"
    if upper == "C":
        return None, "PENDING_CONFIRMATION"
    return None, "PENDING_CONFIRMATION"


class RuleBasedExtractor:
    def __init__(self, mapper: ChargeMapper | None = None):
        self.mapper = mapper or default_mapper()

    @staticmethod
    def _doc_currency(bundle: DocumentBundle) -> str | None:
        match = _CURRENCY_RE.search(bundle.norm_text or bundle.raw_text)
        if not match:
            return None
        code, _ = parse_currency(match.group(1))
        return code

    @staticmethod
    def _doc_payment_term(bundle: DocumentBundle) -> str | None:
        match = _TERM_RE.search(bundle.norm_text or bundle.raw_text)
        return match.group(1).upper() if match else None

    def extract(
        self,
        bundle: DocumentBundle,
        candidates: list[RawChargeLine],
        existing_bill: dict | None = None,
    ) -> ExtractionResult:
        classification = classify_document_rules(bundle)
        doc_currency = self._doc_currency(bundle)
        doc_term = (
            classification.document_payment_term_normalized
            or self._doc_payment_term(bundle)
        )
        doc_instruction = classification.payment_due_instruction
        warnings: list[str] = []

        if classification.document_class == "unknown":
            warnings.append("W_DOCUMENT_UNKNOWN: no document-type keyword matched")
        if classification.billing_status != "confirmed":
            warnings.append(
                f"W_DOCUMENT_NOT_CONFIRMED: billing_status={classification.billing_status}"
            )

        charges: list[ExtractedCharge] = []
        for candidate in candidates:
            standard, mapping_status = self.mapper.standardize_with_status(
                candidate.charge_raw
            )
            mapped = mapping_status == "MATCHED"
            candidate_standard = (
                standard if mapping_status != "UNMATCHED" else None
            )
            raw_name = candidate.charge_name_raw or candidate.charge_raw
            final_name = standard if mapped and standard else raw_name
            amount = parse_amount(candidate.amount_raw)
            currency = candidate.currency_raw or doc_currency
            if candidate.currency_source:
                currency_source = candidate.currency_source
            elif "CURRENCY_INFERRED" in candidate.deterministic_flags:
                currency_source = "INFERRED_FROM_DOLLAR_SYMBOL"
            elif candidate.currency_raw:
                currency_source = "DOCUMENT_TEXT"
            elif currency:
                currency_source = "DOCUMENT_DEFAULT"
            else:
                currency_source = "MISSING"
            payment_term = normalize_payment_term(
                candidate.payment_term_raw or doc_term
            )
            payment_due_instruction = (
                candidate.payment_due_instruction or doc_instruction
            )
            prepaid_normalized, prepaid_status = normalize_prepaid_collect(
                candidate.prepaid_collect_raw
            )
            quantity = parse_amount(candidate.qty_raw)
            unit_price = parse_amount(candidate.rate_raw)

            confidence = 0.9
            reasoning: list[str] = []
            if mapped:
                reasoning.append(f"standardized {candidate.charge_raw!r} -> {standard!r}")
            elif candidate_standard:
                confidence -= 0.1
                reasoning.append(
                    f"candidate mapping {candidate.charge_raw!r} -> "
                    f"{candidate_standard!r} ({mapping_status})"
                )
                warnings.append(
                    f"W_CHARGE_MAPPING_UNCONFIRMED: {candidate.charge_raw!r} "
                    f"-> {candidate_standard!r} ({mapping_status})"
                )
            else:
                confidence -= 0.15
                warnings.append(f"W_UNKNOWN_CHARGE: {candidate.charge_raw!r}")

            if amount is None:
                confidence -= 0.4
                warnings.append(f"E_AMOUNT_INVALID: {candidate.candidate_id}")
            else:
                reasoning.append(f"amount parsed from {candidate.amount_raw!r} -> {amount}")

            if currency:
                reasoning.append(f"currency={currency}")
            else:
                confidence -= 0.1
                warnings.append(f"W_CURRENCY_MISSING: {candidate.candidate_id}")

            if "CURRENCY_INFERRED" in candidate.deterministic_flags:
                confidence -= 0.1
                warnings.append(f"W_CURRENCY_INFERRED: {candidate.candidate_id}")

            evidence_ok = evidence_in_text(candidate.evidence.quote, bundle)
            if not evidence_ok:
                confidence -= 0.2
                warnings.append(f"EVIDENCE_NOT_FOUND: {candidate.candidate_id}")
            else:
                reasoning.append("evidence found in source text")

            charges.append(
                ExtractedCharge(
                    candidate_id=candidate.candidate_id,
                    charge_raw=candidate.charge_raw,
                    charge_name_raw=raw_name,
                    charge_code_raw=candidate.charge_code_raw,
                    charge_item=final_name,
                    candidate_standard_charge_name=candidate_standard,
                    amount=amount,
                    currency=currency,
                    currency_source=currency_source,
                    payment_term=payment_term,
                    payment_due_instruction=payment_due_instruction,
                    payment_due_date=classification.payment_due_date,
                    prepaid_collect_raw=candidate.prepaid_collect_raw,
                    prepaid_collect_normalized=prepaid_normalized,
                    prepaid_collect_status=prepaid_status,
                    quantity=quantity,
                    unit_price=unit_price,
                    base_raw=candidate.base_raw,
                    roe_raw=candidate.roe_raw,
                    payer_code_raw=candidate.payer_code_raw,
                    payee_code_raw=candidate.payee_code_raw,
                    party_mapping_status=(
                        candidate.party_mapping_status
                        or classification.party_mapping_status
                    ),
                    mapping_status=mapping_status,
                    confidence=_clamp(confidence),
                    evidence_quote=candidate.evidence.quote,
                    reasoning=reasoning,
                )
            )

        changes = extract_change_intent(bundle, existing_bill)

        # Preserve order while de-duplicating warnings.
        warnings = list(dict.fromkeys(warnings))

        return ExtractionResult(
            classification=classification,
            charges=charges,
            change_intent=changes,
            source="rules",
            warnings=warnings,
        )

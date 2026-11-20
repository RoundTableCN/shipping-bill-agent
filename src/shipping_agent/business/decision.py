"""Operation decision and final charge values."""

from __future__ import annotations

from pydantic import Field

from ..extract.models import DocumentClassification, ExtractedCharge, FieldChange
from ..io.text_normalize import parse_currency
from ..models.base import StrictModel
from ..models.output import (
    DecisionStatus,
    Operation,
    ValidationReport,
)
from ..models.types import Currency, Money, to_decimal
from .ar_ap import ArapResult
from .charge_mapper import normalize_charge
from .matcher import MatchResult


class DecisionConfig(StrictModel):
    extraction_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    document_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    arap_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    require_confirmed_arap: bool = True


class DecisionResult(StrictModel):
    operation: Operation
    decision_status: DecisionStatus
    reasons: list[str] = Field(default_factory=list)
    amount_changed: bool = False
    changes: list[str] = Field(default_factory=list)
    inherited_fields: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)

    final_charge_item: str | None = None
    final_amount: Money | None = None
    final_currency: Currency | None = None
    final_payment_term: str | None = None


def _name_compatible(a: str | None, b: str | None) -> bool:
    ka, kb = normalize_charge(a or ""), normalize_charge(b or "")
    if not ka or not kb:
        return False
    return ka == kb or ka in kb or kb in ka


def _term(value: str | None) -> str | None:
    if not value:
        return None
    upper = value.strip().upper()
    if upper in {"P", "PP", "PREPAID", "预付"}:
        return "PP"
    if upper in {"C", "CC", "COLLECT", "到付"}:
        return "CC"
    return upper


def _arap_confirmed(arap: ArapResult, config: DecisionConfig) -> bool:
    if arap.posting_type is None:
        return False
    if config.require_confirmed_arap and arap.accounting_status != "CONFIRMED":
        return False
    return arap.confidence >= config.arap_threshold


def _change_for(
    charge: ExtractedCharge, field: str, changes: list[FieldChange]
) -> FieldChange | None:
    for change in changes:
        if change.field != field:
            continue
        if not change.charge_item:
            continue
        if _name_compatible(
            change.charge_item, charge.charge_item or charge.charge_raw
        ):
            return change
    return None


def _apply_changes(
    charge: ExtractedCharge,
    existing_item: str | None,
    existing_amount,
    existing_currency: str | None,
    existing_term: str | None,
    changes: list[FieldChange],
) -> tuple[dict, set[str], list[str], list[str]]:
    final = {
        "charge_item": existing_item,
        "amount": existing_amount,
        "currency": existing_currency,
        "payment_term": existing_term,
    }
    changed: set[str] = set()
    errors: list[str] = []
    warnings: list[str] = []

    for field in ("charge_item", "amount", "currency", "payment_term"):
        change = _change_for(charge, field, changes)
        if change is None:
            continue

        if field == "amount":
            try:
                new_amount = to_decimal(change.new_value)
            except (TypeError, ValueError):
                errors.append(f"E_CHANGE_INVALID_AMOUNT: {change.new_value!r}")
                continue
            final["amount"] = new_amount
            if existing_amount is None or new_amount != existing_amount:
                changed.add("amount")
            new_currency, _ = parse_currency(change.new_value)
            if new_currency and new_currency != existing_currency:
                final["currency"] = new_currency
                changed.add("currency")
            if change.old_value:
                try:
                    old_amount = to_decimal(change.old_value)
                except (TypeError, ValueError):
                    old_amount = None
                if old_amount is not None and existing_amount is not None and old_amount != existing_amount:
                    warnings.append(
                        f"W_CHANGE_OLD_MISMATCH: change says {change.old_value!r}, "
                        f"existing is {existing_amount}"
                    )
        elif field == "currency":
            new_currency, _ = parse_currency(change.new_value)
            if not new_currency:
                errors.append(f"E_CHANGE_INVALID_CURRENCY: {change.new_value!r}")
            elif new_currency != existing_currency:
                final["currency"] = new_currency
                changed.add("currency")
        elif field == "charge_item":
            if change.new_value and normalize_charge(change.new_value) != normalize_charge(
                existing_item or ""
            ):
                final["charge_item"] = change.new_value
                changed.add("charge_item")
        elif field == "payment_term":
            new_term = _term(change.new_value)
            if not new_term:
                errors.append(f"E_CHANGE_INVALID_TERM: {change.new_value!r}")
            elif new_term != _term(existing_term):
                final["payment_term"] = new_term
                changed.add("payment_term")

    return final, changed, errors, warnings


def _final_from_charge(charge: ExtractedCharge) -> dict:
    return {
        "final_charge_item": charge.charge_item,
        "final_amount": charge.amount,
        "final_currency": charge.currency,
        "final_payment_term": charge.payment_term,
    }


def decide(
    classification: DocumentClassification,
    charge: ExtractedCharge,
    match: MatchResult,
    arap: ArapResult,
    changes: list[FieldChange],
    config: DecisionConfig | None = None,
    validation: ValidationReport | None = None,
    history_checked: bool = True,
) -> DecisionResult:
    config = config or DecisionConfig()
    base_errors = list(validation.errors) if validation else []
    base_warnings = list(validation.warnings) if validation else []

    def result(
        operation: Operation,
        status: DecisionStatus,
        *,
        reasons: list[str],
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
        **final,
    ) -> DecisionResult:
        merged_errors = list(dict.fromkeys([*base_errors, *(errors or [])]))
        merged_warnings = list(dict.fromkeys([*base_warnings, *(warnings or [])]))
        values = {**_final_from_charge(charge), **final}
        return DecisionResult(
            operation=operation,
            decision_status=status,
            reasons=reasons,
            validation_errors=merged_errors,
            validation_warnings=merged_warnings,
            **values,
        )

    if classification.billing_status == "void":
        return result(
            "PENDING_REVIEW",
            "REJECT",
            reasons=["document is VOID/CANCELLED"],
            errors=["E_DOC_VOID"],
        )

    if classification.document_type == "Statement":
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=[
                "Statement summarizes existing bills; CREATE/UPDATE not allowed"
            ],
            errors=["E_DOC_STATEMENT_NOT_POSTABLE"],
        )

    if classification.document_class != "billing" or classification.billing_status != "confirmed":
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=[
                f"document_class={classification.document_class}",
                f"billing_status={classification.billing_status}",
                "not a confirmed billing document",
            ],
            errors=["E_DOC_NOT_BILLING"],
        )

    if base_errors:
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=["data validation failed"],
        )

    if classification.confidence < config.document_threshold:
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=["document confidence below threshold"],
            errors=["W_LOW_DOCUMENT_CONFIDENCE"],
        )
    if charge.confidence < config.extraction_threshold:
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=["extraction confidence below threshold"],
            errors=["W_LOW_EXTRACTION_CONFIDENCE"],
        )

    if match.ambiguous:
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=["multiple historical matches"],
            errors=["W_MULTIPLE_MATCHES"],
        )

    if not match.matched:
        if not history_checked:
            return result(
                "PENDING_REVIEW",
                "REVIEW",
                reasons=[
                    "no historical bill data was provided",
                    "CREATE/UPDATE cannot be confirmed without a history check",
                ],
                warnings=["W_HISTORY_NOT_CHECKED: no existing bill data"],
            )
        if not _arap_confirmed(arap, config):
            return result(
                "PENDING_REVIEW",
                "REVIEW",
                reasons=[
                    "no historical bill and AR/AP cannot be confirmed",
                    f"candidate_posting_type={arap.candidate_posting_type}",
                    f"accounting_status={arap.accounting_status}",
                    *arap.reasoning,
                ],
                errors=["E_ARAP_UNDETERMINED"],
            )
        return result(
            "CREATE",
            "AUTO",
            reasons=["no historical bill matched; formal billing document"],
        )

    existing = match.line
    if existing is None:
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=["match result missing historical line"],
            errors=["E_MATCH_INCONSISTENT"],
        )

    final, changed, change_errors, change_warnings = _apply_changes(
        charge,
        existing.charge_item,
        existing.amount,
        existing.currency,
        existing.payment_term,
        changes,
    )
    warnings = list(change_warnings)

    amount_changed = bool(
        charge.amount is not None and existing.amount != charge.amount
    )

    diffs: list[str] = []
    if charge.amount is not None and existing.amount != charge.amount:
        diffs.append("amount")
    if charge.currency and existing.currency != charge.currency:
        diffs.append("currency")
    if charge.charge_item and not _name_compatible(
        charge.charge_item, existing.charge_item
    ):
        diffs.append("charge_item")
    if charge.payment_term and _term(charge.payment_term) != _term(existing.payment_term):
        diffs.append("payment_term")

    missing_evidence = [field for field in diffs if field not in changed]
    if missing_evidence:
        change_errors.append(
            "W_CHANGED_WITHOUT_EVIDENCE: " + ", ".join(sorted(missing_evidence))
        )

    if change_errors:
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=["change application failed or lacks evidence"],
            errors=change_errors,
            warnings=warnings,
            amount_changed=amount_changed,
            changes=sorted(changed),
            final_charge_item=final["charge_item"],
            final_amount=final["amount"],
            final_currency=final["currency"],
            final_payment_term=final["payment_term"],
        )

    if not _arap_confirmed(arap, config):
        return result(
            "PENDING_REVIEW",
            "REVIEW",
            reasons=[
                "AR/AP not confirmed",
                f"candidate_posting_type={arap.candidate_posting_type}",
                f"accounting_status={arap.accounting_status}",
                *arap.reasoning,
            ],
            errors=["E_ARAP_UNDETERMINED"],
            warnings=warnings,
            amount_changed=amount_changed,
            changes=sorted(changed),
            final_charge_item=final["charge_item"],
            final_amount=final["amount"],
            final_currency=final["currency"],
            final_payment_term=final["payment_term"],
        )

    all_fields = {"charge_item", "amount", "currency", "payment_term"}
    if changed:
        return result(
            "UPDATE",
            "AUTO",
            reasons=["matched historical bill; explicit change evidence applied"],
            warnings=warnings,
            amount_changed=amount_changed,
            changes=sorted(changed),
            inherited_fields=sorted(all_fields - changed),
            final_charge_item=final["charge_item"],
            final_amount=final["amount"],
            final_currency=final["currency"],
            final_payment_term=final["payment_term"],
        )

    return result(
        "NO_CHANGE",
        "AUTO",
        reasons=["matched historical bill and values are identical"],
        warnings=warnings,
        amount_changed=False,
        changes=[],
        inherited_fields=sorted(all_fields),
        final_charge_item=existing.charge_item,
        final_amount=existing.amount,
        final_currency=existing.currency,
        final_payment_term=existing.payment_term,
    )

"""Deterministic validation rules for extracted charges and totals."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal

from pydantic import Field

from ..extract.models import DocumentClassification, ExtractedCharge
from ..io.text_normalize import ISO_CODES
from ..models.base import StrictModel
from ..models.candidate import RawChargeLine
from ..models.output import DocumentTotals, ValidationReport
from ..models.types import Money

OCR_CONFUSION_PATTERN = re.compile(
    r"(?i)(?:\d[oisb]|[oisb]\d|[.,][oisb]{1,2}(?=\D|$))"
)


class ValidationIssue(StrictModel):
    code: str
    severity: Literal["error", "warning", "info"] = "warning"
    message: str
    field: str | None = None
    candidate_id: str | None = None


class ValidationConfig(StrictModel):
    amount_tolerance: Money = Decimal("0.01")
    relative_tolerance: float = Field(default=0.001, ge=0.0)


class ValidationResult(StrictModel):
    issues: list[ValidationIssue] = Field(default_factory=list)
    report: ValidationReport = Field(default_factory=ValidationReport)


def _within_tolerance(a: Decimal, b: Decimal, config: ValidationConfig) -> bool:
    diff = abs(a - b)
    if diff <= config.amount_tolerance:
        return True
    scale = max(abs(a), abs(b))
    return diff <= scale * Decimal(str(config.relative_tolerance))


def has_ocr_confusion(text: str | None) -> bool:
    """Detect O/0, I/1, S/5, B/8 confusion in a numeric field."""
    if not text:
        return False
    return bool(OCR_CONFUSION_PATTERN.search(text))


def validate_classification(
    classification: DocumentClassification,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not classification.reference_no:
        issues.append(
            ValidationIssue(
                code="W_MISSING_REFERENCE",
                severity="warning",
                message="document reference number is missing",
                field="reference_no",
            )
        )
    if not classification.document_date:
        issues.append(
            ValidationIssue(
                code="W_MISSING_DATE",
                severity="warning",
                message="document date is missing",
                field="document_date",
            )
        )
    if classification.document_date_status == "AMBIGUOUS":
        issues.append(
            ValidationIssue(
                code="E_DATE_AMBIGUOUS",
                severity="error",
                message="date has multiple plausible month/day interpretations",
                field="document_date",
            )
        )
    if (
        classification.reference_no
        and classification.bl_no
        and classification.reference_no.upper() == classification.bl_no.upper()
    ):
        issues.append(
            ValidationIssue(
                code="E_NUMBER_REUSED",
                severity="error",
                message=(
                    "the same value is used as both a document reference and "
                    "a B/L number"
                ),
                field="reference_no",
            )
        )
    identity_values = {
        value.upper()
        for value in (
            classification.reference_no,
            classification.document_number,
            classification.invoice_number,
        )
        if value
    }
    for container in classification.container_nos:
        if container.upper() in identity_values:
            issues.append(
                ValidationIssue(
                    code="E_INVOICE_AS_CONTAINER",
                    severity="error",
                    message=(
                        f"{container!r} is also an invoice/document number; "
                        "container classification requires label/check-digit evidence"
                    ),
                    field="container_nos",
                )
            )
    if (
        classification.payment_received is not None
        and classification.payment_status_scope == "UNKNOWN"
    ):
        issues.append(
            ValidationIssue(
                code="W_PAYMENT_SCOPE_UNKNOWN",
                severity="warning",
                message=(
                    "PAYMENT RECEIVED was found but the affected receivable/"
                    "payable party is not explicit"
                ),
                field="payment_received",
            )
        )
    return issues


def validate_charge(
    charge: ExtractedCharge,
    candidate: RawChargeLine | None = None,
    config: ValidationConfig | None = None,
) -> list[ValidationIssue]:
    config = config or ValidationConfig()
    issues: list[ValidationIssue] = []
    prefix = {"candidate_id": charge.candidate_id}

    if not charge.charge_item:
        issues.append(
            ValidationIssue(
                code="E_CHARGE_ITEM_MISSING",
                severity="error",
                message="charge item is missing",
                field="charge_item",
                **prefix,
            )
        )

    if charge.amount is None:
        issues.append(
            ValidationIssue(
                code="E_AMOUNT_MISSING",
                severity="error",
                message="amount is missing or unparsable",
                field="amount",
                **prefix,
            )
        )
    elif not charge.amount.is_finite():
        issues.append(
            ValidationIssue(
                code="E_AMOUNT_INVALID",
                severity="error",
                message="amount is not finite",
                field="amount",
                **prefix,
            )
        )
    else:
        if charge.amount == 0:
            issues.append(
                ValidationIssue(
                    code="W_AMOUNT_ZERO",
                    severity="warning",
                    message="amount is zero",
                    field="amount",
                    **prefix,
                )
            )
        if charge.amount < 0:
            issues.append(
                ValidationIssue(
                    code="W_NEGATIVE_AMOUNT",
                    severity="warning",
                    message="amount is negative; confirm this is a credit/adjustment",
                    field="amount",
                    **prefix,
                )
            )

    if charge.currency is None:
        issues.append(
            ValidationIssue(
                code="W_CURRENCY_MISSING",
                severity="warning",
                message="currency is missing",
                field="currency",
                **prefix,
            )
        )
    elif charge.currency not in ISO_CODES:
        issues.append(
            ValidationIssue(
                code="E_CURRENCY_INVALID",
                severity="error",
                message=f"currency {charge.currency!r} is not an ISO 4217 code",
                field="currency",
                **prefix,
            )
        )

    if charge.mapping_status in {"CANDIDATE", "PENDING_CONFIRMATION"}:
        issues.append(
            ValidationIssue(
                code="E_MAPPING_NOT_CONFIRMED",
                severity="error",
                message=(
                    f"charge mapping is {charge.mapping_status}; a candidate "
                    "standard name is not a confirmed ledger item"
                ),
                field="charge_item",
                **prefix,
            )
        )
    if charge.payment_term and charge.payment_term.upper() not in {"PP", "CC", "COD"}:
        issues.append(
            ValidationIssue(
                code="W_PAYMENT_TERM_UNKNOWN",
                severity="warning",
                message=f"payment term {charge.payment_term!r} is not PP/CC/COD",
                field="payment_term",
                **prefix,
            )
        )

    if (
        charge.amount is not None
        and charge.quantity is not None
        and charge.unit_price is not None
        and charge.quantity.is_finite()
        and charge.unit_price.is_finite()
    ):
        expected = charge.quantity * charge.unit_price
        if not _within_tolerance(expected, charge.amount, config):
            issues.append(
                ValidationIssue(
                    code="E_RATE_QTY_MISMATCH",
                    severity="error",
                    message=(
                        f"quantity {charge.quantity} * unit price {charge.unit_price} "
                        f"= {expected} does not match amount {charge.amount}"
                    ),
                    field="amount",
                    **prefix,
                )
            )

    if candidate is not None:
        for field, raw in (
            ("amount", candidate.amount_raw),
            ("rate", candidate.rate_raw),
            ("qty", candidate.qty_raw),
        ):
            if has_ocr_confusion(raw):
                issues.append(
                    ValidationIssue(
                        code="E_OCR_CONFUSION",
                        severity="error",
                        message=f"possible OCR confusion in {field}: {raw!r}",
                        field=field,
                        **prefix,
                    )
                )

    if not charge.evidence_quote:
        issues.append(
            ValidationIssue(
                code="W_EVIDENCE_MISSING",
                severity="warning",
                message="no evidence quote attached",
                field="evidence_quote",
                **prefix,
            )
        )

    return issues


def validate_totals(
    charges: list[ExtractedCharge],
    totals: DocumentTotals | None,
    config: ValidationConfig | None = None,
) -> list[ValidationIssue]:
    config = config or ValidationConfig()
    if totals is None:
        return []
    issues: list[ValidationIssue] = []

    if totals.subtotal is not None and totals.tax is not None and totals.total is not None:
        expected = totals.subtotal + totals.tax
        if not _within_tolerance(expected, totals.total, config):
            issues.append(
                ValidationIssue(
                    code="E_TAX_MISMATCH",
                    severity="error",
                    message=(
                        f"subtotal {totals.subtotal} + tax {totals.tax} "
                        f"= {expected} does not match total {totals.total}"
                    ),
                    field="document_totals",
                )
            )

    if totals.total is not None and charges:
        currencies = {
            charge.currency for charge in charges if charge.currency is not None
        }
        if len(currencies) > 1:
            issues.append(
                ValidationIssue(
                    code="W_MULTI_CURRENCY_TOTAL",
                    severity="warning",
                    message=(
                        "document has multiple currencies; total reconciliation skipped"
                    ),
                    field="document_totals",
                )
            )
        else:
            amount_sum = sum(
                (charge.amount for charge in charges if charge.amount is not None),
                Decimal("0"),
            )
            if not _within_tolerance(amount_sum, totals.total, config):
                issues.append(
                    ValidationIssue(
                        code="E_SUM_MISMATCH",
                        severity="error",
                        message=(
                            f"charge sum {amount_sum} does not match total {totals.total}"
                        ),
                        field="document_totals",
                    )
                )

    return issues


def validate_all(
    classification: DocumentClassification,
    charges: list[ExtractedCharge],
    candidates: list[RawChargeLine] | None = None,
    totals: DocumentTotals | None = None,
    config: ValidationConfig | None = None,
) -> ValidationResult:
    config = config or ValidationConfig()
    candidate_by_id = {
        candidate.candidate_id: candidate for candidate in (candidates or [])
    }

    issues: list[ValidationIssue] = []
    issues.extend(validate_classification(classification))
    for charge in charges:
        issues.extend(
            validate_charge(
                charge,
                candidate_by_id.get(charge.candidate_id),
                config,
            )
        )
    issues.extend(validate_totals(charges, totals, config))

    errors = [
        f"{issue.code}: {issue.message}"
        for issue in issues
        if issue.severity == "error"
    ]
    warnings = [
        f"{issue.code}: {issue.message}"
        for issue in issues
        if issue.severity == "warning"
    ]
    return ValidationResult(
        issues=issues,
        report=ValidationReport(
            passed=not errors,
            errors=errors,
            warnings=warnings,
        ),
    )

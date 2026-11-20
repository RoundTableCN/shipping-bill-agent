from decimal import Decimal

from shipping_agent.extract.models import DocumentClassification, ExtractedCharge
from shipping_agent.models.bundle import SourceRef
from shipping_agent.models.candidate import RawChargeLine
from shipping_agent.models.output import DocumentTotals
from shipping_agent.validate.rules import (
    has_ocr_confusion,
    validate_all,
    validate_charge,
    validate_totals,
)


def _charge(**overrides) -> ExtractedCharge:
    data = {
        "candidate_id": "c1",
        "charge_item": "Handling Charge",
        "amount": Decimal("65.00"),
        "currency": "USD",
        "payment_term": "PP",
        "quantity": Decimal("1"),
        "unit_price": Decimal("65.00"),
        "confidence": 0.9,
        "evidence_quote": "HANDLING CHARGE 65.00",
    }
    data.update(overrides)
    return ExtractedCharge(**data)


def _candidate(**overrides) -> RawChargeLine:
    data = {
        "line_id": "l1",
        "source_position_id": "p1",
        "content_fingerprint": "fp1",
        "candidate_id": "c1",
        "charge_raw": "HANDLING CHARGE",
        "amount_raw": "65.00",
        "currency_raw": "USD",
        "source_kind": "table_row",
        "evidence": SourceRef(
            file_id="f1", file_name="bill.pdf", media_type="application/pdf"
        ),
    }
    data.update(overrides)
    return RawChargeLine(**data)


def _codes(issues):
    return [issue.code for issue in issues]


def test_valid_charge_has_no_errors():
    issues = validate_charge(_charge(), _candidate())
    assert [issue for issue in issues if issue.severity == "error"] == []


def test_missing_amount():
    issues = validate_charge(_charge(amount=None), _candidate(amount_raw=None))
    assert "E_AMOUNT_MISSING" in _codes(issues)


def test_non_iso_currency():
    issues = validate_charge(_charge(currency="ABC"), _candidate(currency_raw="ABC"))
    assert "E_CURRENCY_INVALID" in _codes(issues)


def test_rate_qty_mismatch():
    issues = validate_charge(
        _charge(quantity=Decimal("2"), unit_price=Decimal("65.00"), amount=Decimal("100.00")),
        _candidate(),
    )
    assert "E_RATE_QTY_MISMATCH" in _codes(issues)


def test_ocr_confusion_in_amount():
    issues = validate_charge(_charge(), _candidate(amount_raw="65.OO"))
    assert "E_OCR_CONFUSION" in _codes(issues)


def test_payment_term_warning():
    issues = validate_charge(_charge(payment_term="XX"), _candidate())
    assert "W_PAYMENT_TERM_UNKNOWN" in _codes(issues)


def test_zero_and_negative_warnings():
    assert "W_AMOUNT_ZERO" in _codes(validate_charge(_charge(amount=Decimal("0")), _candidate()))
    assert "W_NEGATIVE_AMOUNT" in _codes(
        validate_charge(_charge(amount=Decimal("-10.00")), _candidate())
    )


def test_totals_match():
    issues = validate_totals(
        [_charge(amount=Decimal("65.00")), _charge(amount=Decimal("35.00"))],
        DocumentTotals(subtotal=Decimal("100.00"), tax=Decimal("0"), total=Decimal("100.00")),
    )
    assert "E_SUM_MISMATCH" not in _codes(issues)
    assert "E_TAX_MISMATCH" not in _codes(issues)


def test_sum_mismatch():
    issues = validate_totals(
        [_charge(amount=Decimal("65.00"))],
        DocumentTotals(total=Decimal("100.00")),
    )
    assert "E_SUM_MISMATCH" in _codes(issues)


def test_tax_mismatch():
    issues = validate_totals(
        [_charge(amount=Decimal("100.00"))],
        DocumentTotals(subtotal=Decimal("100.00"), tax=Decimal("5.00"), total=Decimal("110.00")),
    )
    assert "E_TAX_MISMATCH" in _codes(issues)


def test_multi_currency_total_skipped():
    issues = validate_totals(
        [
            _charge(amount=Decimal("65.00"), currency="USD"),
            _charge(amount=Decimal("80.00"), currency="CNY"),
        ],
        DocumentTotals(total=Decimal("145.00")),
    )
    assert "W_MULTI_CURRENCY_TOTAL" in _codes(issues)


def test_classification_warnings_and_all_passed():
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
    )
    result = validate_all(classification, [_charge()], [_candidate()])
    assert "W_MISSING_REFERENCE" in _codes(result.issues)
    assert "W_MISSING_DATE" in _codes(result.issues)
    assert result.report.passed is True


def test_all_fails_when_error_present():
    classification = DocumentClassification(
        document_class="billing",
        billing_status="confirmed",
        reference_no="INV-1",
        document_date="2026-10-25",
    )
    result = validate_all(classification, [_charge(amount=None)], [_candidate(amount_raw=None)])
    assert result.report.passed is False
    assert "E_AMOUNT_MISSING" in _codes(result.issues)


def test_ocr_confusion_helper():
    assert has_ocr_confusion("65.OO")
    assert has_ocr_confusion("1O0.00")
    assert has_ocr_confusion("B5")
    assert not has_ocr_confusion("USD 65.00")
    assert not has_ocr_confusion("1,310.40")

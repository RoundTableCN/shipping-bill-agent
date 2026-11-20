from decimal import Decimal
from pathlib import Path

import fitz

from shipping_agent.business.ar_ap import ArapResult
from shipping_agent.business.decision import DecisionConfig, decide
from shipping_agent.business.matcher import MatchResult, Matcher
from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.business.repository import BillRepository, ExistingBill, ExistingCharge
from shipping_agent.business.document_class import classify_document_rules
from shipping_agent.candidates import build_candidates
from shipping_agent.extract.models import DocumentClassification, ExtractedCharge
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.models.bundle import DocumentBundle, SourceRef, TextBlock
from shipping_agent.validate.rules import validate_charge


def _text_bundle(lines: list[str]) -> DocumentBundle:
    blocks = [
        TextBlock(block_id=f"L{i}", kind="line", text=line, order=i)
        for i, line in enumerate(lines)
    ]
    text = "\n".join(lines)
    return DocumentBundle(
        bundle_id="test",
        source=SourceRef(file_id="abc123", file_name="test.txt", media_type="text/plain"),
        media_type="text/plain",
        raw_text=text,
        norm_text=text,
        blocks=blocks,
    )


def _classification(**overrides) -> DocumentClassification:
    data = {
        "document_class": "billing",
        "billing_status": "confirmed",
        "confidence": 0.95,
    }
    data.update(overrides)
    return DocumentClassification(**data)


def _charge(**overrides) -> ExtractedCharge:
    data = {
        "candidate_id": "c1",
        "charge_item": "Handling Charge",
        "amount": Decimal("80.00"),
        "currency": "USD",
        "payment_term": "PP",
        "confidence": 0.9,
        "evidence_quote": "HANDLING CHARGE 80.00",
    }
    data.update(overrides)
    return ExtractedCharge(**data)


def test_proforma_invoice_is_tentative_and_pending(tmp_path: Path):
    bundle = _text_bundle(
        [
            "PROFORMA INVOICE",
            "INVOICE NO.: PRO-001",
            "INVOICE DATE: 2026-10-25",
            "HANDLING CHARGE USD 65.00",
            "TOTAL USD 65.00",
        ]
    )
    classification = classify_document_rules(bundle)
    assert classification.document_type == "Invoice"
    assert classification.billing_status == "tentative"

    result = process_bundle(
        bundle,
        build_candidates(bundle),
        PipelineConfig(existing_bills=None),
    )
    assert result.records[0].operation == "PENDING_REVIEW"
    assert "E_DOC_NOT_BILLING" in result.records[0].audit_trail.validation.errors


def test_amount_change_without_evidence_goes_to_review():
    existing = ExistingBill(
        bill_id="B1",
        reference_no="REF-X",
        charges=[
            ExistingCharge(
                line_id="L1",
                charge_item="Handling Charge",
                amount=Decimal("65.00"),
                currency="USD",
            )
        ],
    )
    match = MatchResult(
        candidate_id="c1",
        matched=True,
        bill=existing,
        line=existing.charges[0],
        rule="STRICT_L1",
    )
    result = decide(
        _classification(reference_no="REF-X"),
        _charge(amount=Decimal("80.00")),
        match,
        ArapResult(posting_type="AP", accounting_status="CONFIRMED", confidence=0.9),
        [],
        DecisionConfig(),
    )

    assert result.operation == "PENDING_REVIEW"
    assert result.decision_status == "REVIEW"
    assert any(
        "W_CHANGED_WITHOUT_EVIDENCE" in error
        for error in result.validation_errors
    )


def test_missing_payment_term_has_no_unknown_warning():
    issues = validate_charge(_charge(payment_term=None))
    codes = [issue.code for issue in issues]
    assert "W_PAYMENT_TERM_UNKNOWN" not in codes


def test_single_part_eml(tmp_path: Path):
    eml = (
        "From: a@example.com\r\n"
        "To: b@example.com\r\n"
        "Subject: Simple bill\r\n"
        "Date: Thu, 01 Oct 2026 10:00:00 +0800\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "HANDLING CHARGE USD 65.00\r\n"
        "TOTAL USD 65.00\r\n"
    ).encode("utf-8")
    path = tmp_path / "simple.eml"
    path.write_bytes(eml)

    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="mock")
    bundle = parse_file(path, ctx)
    candidates = build_candidates(bundle)

    assert bundle.media_type == "message/rfc822"
    assert bundle.meta["subject"] == "Simple bill"
    assert len(candidates) == 1
    assert candidates[0].charge_raw == "HANDLING CHARGE"
    assert candidates[0].amount_raw == "65.00"


def test_multi_page_pdf(tmp_path: Path):
    path = tmp_path / "two_pages.pdf"
    doc = fitz.open()
    for page_no in (1, 2):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50), "COMMERCIAL INVOICE", fontsize=18)
        page.insert_text((50, 80), "INVOICE NO.: MULTI-001", fontsize=10)
        page.insert_text((50, 100), "INVOICE DATE: 2026-10-25", fontsize=10)
        page.insert_text((50, 120), "CURRENCY: USD", fontsize=10)
        headers = ["DESCRIPTION", "UNIT", "RATE", "QTY", "P/C", "AMOUNT"]
        xs = [50, 300, 350, 410, 460, 520]
        for x, header in zip(xs, headers):
            page.insert_text((x, 160), header, fontsize=8)
        values = [f"PAGE{page_no} CHARGE", "-", "65.00", "1.00", "P", "65.00"]
        for x, value in zip(xs, values):
            page.insert_text((x, 180), value, fontsize=8)
    doc.save(path)
    doc.close()

    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    candidates = build_candidates(bundle)

    assert len(bundle.tables) == 2
    assert len(candidates) == 2
    assert {candidate.charge_raw for candidate in candidates} == {
        "PAGE1 CHARGE",
        "PAGE2 CHARGE",
    }


def test_same_reference_different_issuer_is_ambiguous():
    def bill(bill_id: str, issuer: str) -> ExistingBill:
        return ExistingBill(
            bill_id=bill_id,
            reference_no="REF-X",
            parties={"issuer": issuer},
            charges=[
                ExistingCharge(
                    line_id=f"{bill_id}-L1",
                    charge_item="Handling Charge",
                    amount=Decimal("65.00"),
                    currency="USD",
                )
            ],
        )

    repo = BillRepository(
        [bill("B1", "ISSUER ONE"), bill("B2", "ISSUER TWO")]
    )
    matcher = Matcher(repo, mode="strict")
    classification = _classification(reference_no="REF-X")
    charge = _charge(amount=Decimal("65.00"))

    result = matcher.match(classification, [charge])[0]

    assert result.matched is False
    assert result.ambiguous is True
    assert len(result.candidates) == 2

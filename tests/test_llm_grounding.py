"""LLM classification must be grounded by deterministic document rules."""

from __future__ import annotations

from pathlib import Path

from shipping_agent.business.document_class import classify_document_rules
from shipping_agent.extract.langchain_extractor import _reconcile_classification
from shipping_agent.extract.models import DocumentClassification
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.models.bundle import DocumentBundle, SourceRef


def _bundle(text: str) -> DocumentBundle:
    return DocumentBundle(
        bundle_id="llm-grounding",
        source=SourceRef(
            file_id="llm-grounding",
            file_name="grounding.txt",
            media_type="text/plain",
        ),
        media_type="text/plain",
        raw_text=text,
        norm_text=text,
    )


def _llm(**overrides) -> DocumentClassification:
    payload = {
        "document_type": "INVOICE",
        "document_class": "billing",
        "billing_status": "confirmed",
        "confidence": 0.9,
    }
    payload.update(overrides)
    return DocumentClassification(**payload)


def test_llm_reference_and_recipient_are_grounded(
    fixtures_dir: Path, tmp_path: Path
):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "sample_prealert.eml", ctx)
    rule = classify_document_rules(bundle)
    llm = _llm(
        document_type="PRE-ALERT",
        document_class="notice",
        billing_status="tentative",
        reference_no="LI",
        recipient="LI",
        payer="LI",
        payment_due_instruction="DUE DATE 10-24-2026",
    )

    result = _reconcile_classification(llm, rule)

    assert result.reference_no == rule.reference_no == "PREALERT-DEMO-001"
    assert result.recipient == rule.recipient == "EXAMPLE CONSIGNEE LLC"
    assert result.payer is None
    assert result.payment_due_instruction is None


def test_llm_bl_is_not_reused_as_reference(
    samples_dir: Path, tmp_path: Path
):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(samples_dir / "sample_general_notice.pdf", ctx)
    rule = classify_document_rules(bundle)
    llm = _llm(reference_no="BL-DEMO-001", bl_no="BL-DEMO-001")

    result = _reconcile_classification(llm, rule)

    assert result.reference_no is None
    assert result.bl_no == "BL-DEMO-001"


def test_llm_ambiguous_date_is_not_confirmed(tmp_path: Path):
    text = (
        "INVOICE NO: INV-DEMO-001\n"
        "INVOICE DATE: 10/03/2025\n"
        "TOTAL USD 26.90\n"
    )
    rule = classify_document_rules(_bundle(text))
    llm = _llm(document_date="2025-10-03", document_date_status="CONFIRMED")

    result = _reconcile_classification(llm, rule)

    assert result.document_date is None
    assert result.document_date_raw == "10/03/2025"
    assert result.document_date_status == "AMBIGUOUS"


def test_llm_due_date_is_not_payment_instruction(
    samples_dir: Path, tmp_path: Path
):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(samples_dir / "sample_debit_note.pdf", ctx)
    rule = classify_document_rules(bundle)
    llm = _llm(
        document_type="DEBIT NOTE",
        payment_due_instruction="DUE DATE 10-24-2026",
        payment_due_date="2026-10-24",
    )

    result = _reconcile_classification(llm, rule)

    assert result.payment_due_instruction is None
    assert result.payment_due_date == "2026-10-24"

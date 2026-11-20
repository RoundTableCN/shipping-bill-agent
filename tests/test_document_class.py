from pathlib import Path

from shipping_agent.business.document_class import classify_document_rules
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.models.bundle import DocumentBundle, SourceRef


def _classify(path: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    return classify_document_rules(bundle)


def test_prealert_email(fixtures_dir: Path, tmp_path: Path):
    result = _classify(fixtures_dir / "sample_prealert.eml", tmp_path)

    assert result.document_type == "PRE-ALERT"
    assert result.document_class == "notice"
    assert result.billing_status == "tentative"
    assert result.reference_no == "PREALERT-DEMO-001"
    assert result.document_date == "2026-10-20"
    assert "示例物流科技" in result.issuer_candidates
    assert "EXAMPLE CONSIGNEE LLC" in result.recipient_candidates
    assert result.payer is None
    assert result.payee is None
    assert result.confidence >= 0.8


def test_general_notice(samples_dir: Path, tmp_path: Path):
    result = _classify(samples_dir / "sample_general_notice.pdf", tmp_path)

    assert result.document_type == "General Notice"
    assert result.document_class == "notice"
    assert result.billing_status == "tentative"
    assert result.reference_no is None
    assert result.bl_no == "BL-DEMO-001"
    assert result.bl_no_raw == "BL-DEMO-001"
    assert result.document_date == "2026-10-19"
    assert result.payer is None
    assert result.payee is None
    assert result.beneficiary is None


def test_debit_note(samples_dir: Path, tmp_path: Path):
    result = _classify(samples_dir / "sample_debit_note.pdf", tmp_path)

    assert result.document_type == "Debit Note"
    assert result.document_class == "billing"
    assert result.billing_status == "confirmed"
    assert result.reference_no == "DN-DEMO-002"
    assert result.document_date == "2026-10-24"
    assert result.payee == "CARRIER ALPHA LIMITED (LAX)"
    assert result.beneficiary == "CARRIER ALPHA LIMITED"


def test_invoice_fixture(fixtures_dir: Path, tmp_path: Path):
    result = _classify(fixtures_dir / "formal_invoice.pdf", tmp_path)

    assert result.document_type == "Invoice"
    assert result.document_class == "billing"
    assert result.billing_status == "confirmed"
    assert result.reference_no == "INV-FIXTURE-001"
    assert result.document_date == "2026-10-25"
    assert result.payer == "IMPORTER BETA (SHANGHAI)"
    assert result.payee == "CARRIER ALPHA LIMITED"


def test_statement_docx(fixtures_dir: Path, tmp_path: Path):
    result = _classify(fixtures_dir / "statement.docx", tmp_path)

    assert result.document_type == "Statement"
    assert result.document_class == "billing"
    assert result.billing_status == "confirmed"
    assert result.reference_no == "STMT-FIXTURE-002"
    assert result.document_date == "2026-10-26"


def test_statement_excel(fixtures_dir: Path, tmp_path: Path):
    result = _classify(fixtures_dir / "charges.xlsx", tmp_path)

    assert result.document_type == "Statement"
    assert result.document_class == "notice"
    assert result.billing_status == "tentative"
    assert result.reference_no == "STMT-FIXTURE-001"


def test_debit_invoice_is_billing():
    bundle = DocumentBundle(
        bundle_id="text-debit-invoice",
        source=SourceRef(
            file_id="text-debit-invoice",
            file_name="vision.txt",
            media_type="text/plain",
        ),
        media_type="text/plain",
        raw_text=(
            "DOCUMENT TYPE: Debit Invoice\n"
            "REFERENCE NO: INV-DEMO-001\n"
            "DOCUMENT DATE: 2025-10-03\n"
            "TOTAL: 26.90\n"
        ),
    )

    result = classify_document_rules(bundle)

    assert result.document_type == "Invoice"
    assert result.document_class == "billing"
    assert result.billing_status == "confirmed"

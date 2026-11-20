from decimal import Decimal
from pathlib import Path

from shipping_agent.business.totals import extract_document_totals
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file


def _totals(path: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    return extract_document_totals(bundle)


def test_invoice_totals(fixtures_dir: Path, tmp_path: Path):
    result = _totals(fixtures_dir / "formal_invoice.pdf", tmp_path)
    assert result.totals.subtotal == Decimal("220.00")
    assert result.totals.tax == Decimal("0.00")
    assert result.totals.total == Decimal("220.00")


def test_revised_invoice_totals(fixtures_dir: Path, tmp_path: Path):
    result = _totals(fixtures_dir / "formal_invoice_revised.pdf", tmp_path)
    assert result.totals.total == Decimal("235.00")


def test_debit_note_total(samples_dir: Path, tmp_path: Path):
    result = _totals(samples_dir / "sample_debit_note.pdf", tmp_path)
    assert result.totals.total == Decimal("1410.40")


def test_general_notice_total(samples_dir: Path, tmp_path: Path):
    result = _totals(samples_dir / "sample_general_notice.pdf", tmp_path)
    assert result.totals.total == Decimal("245.0000")


def test_word_statement_totals(fixtures_dir: Path, tmp_path: Path):
    result = _totals(fixtures_dir / "statement.docx", tmp_path)
    assert result.totals.subtotal == Decimal("220.00")
    assert result.totals.tax == Decimal("0.00")
    assert result.totals.total == Decimal("220.00")


def test_email_has_no_totals(fixtures_dir: Path, tmp_path: Path):
    result = _totals(fixtures_dir / "sample_prealert.eml", tmp_path)
    assert result.totals.subtotal is None
    assert result.totals.tax is None
    assert result.totals.total is None


def test_excel_multi_currency_skips_total(fixtures_dir: Path, tmp_path: Path):
    result = _totals(fixtures_dir / "charges.xlsx", tmp_path)
    assert result.totals.total is None
    assert any("MULTIPLE_TOTAL_VALUES" in warning for warning in result.warnings)
    assert any("W_MULTI_CURRENCY_TOTAL" in warning for warning in result.warnings)

from pathlib import Path

from shipping_agent.extract.evidence import evidence_in_text
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file


def test_eml_evidence(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "sample_prealert.eml", ctx)

    assert evidence_in_text("SHA pay TAR：H/C $50", bundle)
    assert not evidence_in_text("this quote does not exist", bundle)


def test_pdf_table_row_evidence(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "formal_invoice.pdf", ctx)

    assert evidence_in_text("HANDLING CHARGE - 65.00 1.00 P 65.00", bundle)
    assert evidence_in_text("INV-FIXTURE-001", bundle)
    assert not evidence_in_text("HANDLING CHARGE - 99.00", bundle)

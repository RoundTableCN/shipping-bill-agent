from decimal import Decimal
from pathlib import Path

from shipping_agent.candidates import build_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.io.text_normalize import parse_amount


def _ctx(tmp_path: Path) -> ParseContext:
    return ParseContext(run_dir=tmp_path / "run", ocr_mode="local")


def test_formal_invoice_table(fixtures_dir: Path, tmp_path: Path):
    bundle = parse_file(fixtures_dir / "formal_invoice.pdf", _ctx(tmp_path))

    assert "INV-FIXTURE-001" in bundle.raw_text
    assert len(bundle.tables) == 1
    table = bundle.tables[0]
    header = [cell.text for cell in table.cells if cell.row == 0]
    assert header[:6] == ["DESCRIPTION", "UNIT", "RATE", "QTY", "P/C", "AMOUNT"]

    candidates = build_candidates(bundle)
    assert len(candidates) == 3
    assert [c.charge_raw for c in candidates] == [
        "HANDLING CHARGE",
        "DOCUMENTATION FEE",
        "TRUCKING FEE",
    ]
    assert [parse_amount(c.amount_raw) for c in candidates] == [
        Decimal("65.00"),
        Decimal("35.00"),
        Decimal("120.00"),
    ]
    assert all(c.currency_raw == "USD" for c in candidates)


def test_revised_invoice_has_correction_evidence(fixtures_dir: Path, tmp_path: Path):
    bundle = parse_file(fixtures_dir / "formal_invoice_revised.pdf", _ctx(tmp_path))
    assert "REVISION: R1" in bundle.raw_text
    assert "CORRECTION:" in bundle.raw_text
    assert "USD 65.00 TO USD 80.00" in bundle.raw_text


def test_create_invoice_has_distinct_shipment(fixtures_dir: Path, tmp_path: Path):
    bundle = parse_file(fixtures_dir / "formal_invoice_create.pdf", _ctx(tmp_path))
    assert "INV-FIXTURE-003" in bundle.raw_text
    assert "MAEU999888777" in bundle.raw_text
    assert "MAEU275752922" not in bundle.raw_text


def test_debit_note_sample(samples_dir: Path, tmp_path: Path):
    bundle = parse_file(samples_dir / "sample_debit_note.pdf", _ctx(tmp_path))
    assert "DN-DEMO-002" in bundle.raw_text
    assert len(bundle.tables) == 1

    candidates = build_candidates(bundle)
    assert len(candidates) == 3
    assert [parse_amount(c.amount_raw) for c in candidates] == [
        Decimal("65.00"),
        Decimal("1310.40"),
        Decimal("35.00"),
    ]
    assert [c.charge_raw for c in candidates] == [
        "HANDLING CHARGE",
        "4 ADD'L DETENTION FREE TIME CHARGE",
        "HANDLING CHARGE",
    ]


def test_general_notice_sample_and_label_pairs(samples_dir: Path, tmp_path: Path):
    bundle = parse_file(samples_dir / "sample_general_notice.pdf", _ctx(tmp_path))
    text = bundle.norm_text

    assert "GENERAL NOTICE" in text
    assert "PAYMENT RECEIVED" in text and "NO" in text
    assert "OBL RECEIVED" in text and "YES" in text
    assert "BL-DEMO-001" in text
    assert "245.0000" in text

    candidates = build_candidates(bundle)
    assert len(candidates) == 1
    assert parse_amount(candidates[0].amount_raw) == Decimal("245.0000")
    assert candidates[0].currency_raw == "USD"

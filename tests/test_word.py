from decimal import Decimal
from pathlib import Path

from shipping_agent.candidates import build_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.io.text_normalize import parse_amount


def test_statement_docx(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "statement.docx", ctx)

    assert "STMT-FIXTURE-002" in bundle.raw_text
    assert "BALANCE DUE: USD 220.00" in bundle.raw_text
    assert len(bundle.tables) == 1

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

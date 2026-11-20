from decimal import Decimal
from pathlib import Path

from shipping_agent.candidates import build_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.io.text_normalize import parse_amount


def test_excel_header_and_rows(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "charges.xlsx", ctx)

    assert len(bundle.tables) == 1
    sheets = {sheet["name"]: sheet for sheet in bundle.meta["sheets"]}
    assert sheets["应付明细"]["header_row"] == 4
    assert sheets["应付明细"]["data_rows"] == 5
    assert len(bundle.meta["total_rows"]) == 2

    candidates = build_candidates(bundle)
    assert len(candidates) == 5
    assert [c.charge_raw for c in candidates] == [
        "海运费",
        "操作费",
        "文件费",
        "拖车费",
        "报关费",
    ]
    assert [parse_amount(c.amount_raw) for c in candidates] == [
        Decimal("1200.00"),
        Decimal("65.00"),
        Decimal("35.00"),
        Decimal("120.00"),
        Decimal("80.00"),
    ]
    assert [c.currency_raw for c in candidates] == ["USD", "USD", "USD", "USD", "CNY"]
    assert all(c.payment_term_raw == "PP" for c in candidates)


def test_excel_no_header_sheet_warns(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "charges.xlsx", ctx)

    codes = [warning.code for warning in bundle.warnings]
    assert "EXCEL_HEADER_NOT_FOUND" in codes

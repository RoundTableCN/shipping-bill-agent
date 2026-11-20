"""Legacy .doc fallback: OLE piece-table text and pipe table rows."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from shipping_agent.io import word_parser
from shipping_agent.io.context import ParseContext, ParseError
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.io.legacy_doc import extract_legacy_doc_text
from shipping_agent.io.word_parser import _legacy_tables_from_lines


def _office_template() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft Office"
        / "root"
        / "Office16"
        / "2052"
        / "PROTTPLN.DOC",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft Office"
        / "root"
        / "Office16"
        / "1033"
        / "PROTTPLN.DOC",
    ]
    return next((path for path in candidates if path.exists()), None)


def test_pipe_lines_become_table():
    tables = _legacy_tables_from_lines(
        [
            "DESCRIPTION | QTY | RATE | AMOUNT",
            "HANDLING CHARGE | 1 | 65.00 | 65.00",
            "TOTAL | | | 65.00",
        ]
    )

    assert len(tables) == 1
    by_position = {(cell.row, cell.col): cell.text for cell in tables[0].cells}
    assert by_position[(0, 0)] == "DESCRIPTION"
    assert by_position[(1, 0)] == "HANDLING CHARGE"
    assert by_position[(1, 3)] == "65.00"
    assert by_position[(2, 0)] == "TOTAL"
    assert by_position[(2, 3)] == "65.00"


def test_legacy_doc_text_fallback(monkeypatch, tmp_path: Path):
    template = _office_template()
    if template is None:
        pytest.skip("no Office .doc template available for a real OLE fixture")

    text = extract_legacy_doc_text(template)
    assert text.strip()

    def unavailable(path, work_dir):
        raise ParseError("LEGACY_DOC_UNSUPPORTED", "no converter")

    monkeypatch.setattr(word_parser, "_convert_doc_to_docx", unavailable)
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(template, ctx)

    assert bundle.media_type == "application/msword"
    assert bundle.raw_text.strip()
    assert "LEGACY_DOC_TEXT_FALLBACK" in {warning.code for warning in bundle.warnings}

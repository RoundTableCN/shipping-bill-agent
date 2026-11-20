"""Verify that generated fixtures are readable and contain expected invariants."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz
from docx import Document
from openpyxl import load_workbook

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "data" / "fixtures"


def pdf_text(name: str) -> str:
    doc = fitz.open(FIX / name)
    text = "\n".join(page.get_text("text") for page in doc)
    doc.close()
    return text


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} FAILED {detail}")
    print(f"PASS  {name}  {detail}")


def main() -> None:
    # PDFs
    text = pdf_text("formal_invoice.pdf")
    check("formal_invoice ref", "INV-FIXTURE-001" in text)
    check("formal_invoice charges", all(x in text for x in ("HANDLING CHARGE", "65.00", "DOCUMENTATION FEE", "TRUCKING FEE")))
    check("formal_invoice total", "220.00" in text)

    text = pdf_text("formal_invoice_revised.pdf")
    check("revised marker", "REVISED" in text and "REVISION: R1" in text)
    check("revised amount", "80.00" in text)
    check("revised correction evidence", "CORRECTION:" in text and "USD 65.00 TO USD 80.00" in text)

    text = pdf_text("formal_invoice_create.pdf")
    check("create ref", "INV-FIXTURE-003" in text)
    check("create total", "290.00" in text)
    check("create distinct shipment", "MAEU999888777" in text and "MAEU275752922" not in text)

    # Excel
    wb = load_workbook(FIX / "charges.xlsx", data_only=True)
    ws = wb["应付明细"]
    check("excel title", ws["A1"].value == "SHIPPING CHARGES DETAIL")
    check("excel header row 4", ws.cell(row=4, column=2).value == "费用名称")
    check("excel detail rows", ws.cell(row=5, column=2).value == "海运费" and ws.cell(row=9, column=2).value == "报关费")
    check("excel usd total", ws.cell(row=10, column=7).value == 1420)
    check("excel cny total", ws.cell(row=11, column=7).value == 80)

    # Word
    doc = Document(FIX / "statement.docx")
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    check("word statement no", any("STMT-FIXTURE-002" in p for p in paragraphs))
    check("word balance due", any("BALANCE DUE: USD 220.00" in p for p in paragraphs))
    check("word table rows", len(doc.tables) == 1 and len(doc.tables[0].rows) == 4)

    # JSON
    data = json.loads((FIX / "existing_bills.json").read_text(encoding="utf-8"))
    check("json bills", len(data["bills"]) == 2)
    check("json bill 001", data["bills"][0]["reference_no"] == "INV-FIXTURE-001" and len(data["bills"][0]["charges"]) == 3)
    check("json duplicate pair", [c["amount"] for c in data["bills"][1]["charges"]] == [35.0, 35.0])

    print("\nAll fixture checks passed.")


if __name__ == "__main__":
    main()

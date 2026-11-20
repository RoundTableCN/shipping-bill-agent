"""Generate synthetic fixtures for the shipping bill agent.

Outputs (all under data/fixtures/):
  - formal_invoice.pdf           NO_CHANGE against BILL-FIX-001
  - formal_invoice_revised.pdf   UPDATE (Handling 65 -> 80, explicit correction)
  - formal_invoice_create.pdf    CREATE (no existing match)
  - charges.xlsx                 Excel fee table, multi-currency
  - statement.docx               Word statement with BALANCE DUE
  - existing_bills.json          historical bills for matching tests
  - README.md                    fixture description and expected outcomes

These are synthetic documents, not real business records.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import fitz  # PyMuPDF
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

ISSUER = "CARRIER ALPHA LIMITED"
ISSUER_ADDR = "100 EXAMPLE ROAD, SUITE 1, ANYTOWN, CA 90000"
ACCOUNTING_ENTITY = "IMPORTER BETA (SHANGHAI)"
REMIT_TO = "CARRIER ALPHA LIMITED"
BL_NO = "MAEU888777666"
HBL_NO = "CGT260888888"
BOOKING_NO = "CGTSE260888888"
VESSEL = "FIXTURE STAR 001E"
CONTAINERS = "FIXU1234567, FIXU7654321"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _text(page: fitz.Page, x: float, y: float, text: str, size: float = 9,
          bold: bool = False, color=(0, 0, 0)) -> None:
    page.insert_text(
        (x, y), text, fontsize=size, fontname="hebo" if bold else "helv",
        color=color,
    )


def _line(page: fitz.Page, x0: float, y: float, x1: float) -> None:
    page.draw_line((x0, y), (x1, y), color=(0.6, 0.6, 0.6), width=0.6)


def make_invoice_pdf(
    path: Path,
    *,
    title: str,
    invoice_no: str,
    revision: str | None,
    charges: list[tuple[str, str, str, str, str, str]],
    subtotal: str,
    tax: str,
    total: str,
    remark: str | None = None,
    bl_no: str = BL_NO,
    hbl_no: str = HBL_NO,
    booking_no: str = BOOKING_NO,
    vessel: str = VESSEL,
    containers: str = CONTAINERS,
) -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4

    # Header
    _text(page, 50, 55, title, size=18, bold=True)
    _text(page, 50, 80, ISSUER, size=10, bold=True)
    _text(page, 50, 94, ISSUER_ADDR, size=8)
    _text(page, 50, 106, "TEL: 555-010-0199   EMAIL: BILLING@EXAMPLE.INVALID", size=8)

    # Invoice meta
    y = 140
    _text(page, 50, y, f"INVOICE NO.: {invoice_no}", size=10, bold=True)
    if revision:
        _text(page, 260, y, f"REVISION: {revision}", size=10, bold=True)
    _text(page, 50, y + 18, "INVOICE DATE: 2026-10-25", size=9)
    _text(page, 260, y + 18, "DUE DATE: 2026-11-24", size=9)
    _text(page, 50, y + 36, "CURRENCY: USD", size=9)
    _text(page, 260, y + 36, "TERMS: PP", size=9)

    # Parties
    y = 205
    _text(page, 50, y, "BILL TO / PAYER:", size=9, bold=True)
    _text(page, 50, y + 14, ACCOUNTING_ENTITY, size=9)
    _text(page, 300, y, "REMIT TO / BENEFICIARY:", size=9, bold=True)
    _text(page, 300, y + 14, REMIT_TO, size=9)

    # Shipment
    y = 250
    _text(page, 50, y, f"MASTER B/L NO.: {bl_no}", size=9)
    _text(page, 260, y, f"HOUSE B/L NO.: {hbl_no}", size=9)
    _text(page, 50, y + 16, f"BOOKING NO.: {booking_no}", size=9)
    _text(page, 260, y + 16, f"VESSEL/VOYAGE: {vessel}", size=9)
    _text(page, 50, y + 32, f"CONTAINER NOS.: {containers}", size=9)

    # Charge table
    header_y = 320
    cols = [50, 300, 350, 410, 460, 520]
    headers = ["DESCRIPTION", "UNIT", "RATE", "QTY", "P/C", "AMOUNT"]
    _text(page, 50, header_y, "CHARGE DETAILS", size=10, bold=True)
    _line(page, 50, header_y + 6, 560)
    for x, h in zip(cols, headers):
        _text(page, x, header_y + 20, h, size=8, bold=True)
    _line(page, 50, header_y + 26, 560)

    y = header_y + 42
    for desc, unit, rate, qty, pc, amount in charges:
        _text(page, cols[0], y, desc, size=8)
        _text(page, cols[1], y, unit, size=8)
        _text(page, cols[2], y, rate, size=8)
        _text(page, cols[3], y, qty, size=8)
        _text(page, cols[4], y, pc, size=8)
        _text(page, cols[5], y, amount, size=8)
        y += 18

    _line(page, 50, y - 4, 560)

    # Totals
    ty = y + 16
    for label, value, bold in (("SUBTOTAL:", subtotal, False),
                               ("TAX:", tax, False),
                               ("TOTAL:", total, True)):
        _text(page, 380, ty, label, size=9, bold=bold)
        _text(page, 500, ty, value, size=9, bold=bold)
        ty += 16

    # Remark
    if remark:
        _text(page, 50, ty + 20, "REMARK:", size=9, bold=True)
        # simple wrapping for the fixture
        words = remark.split()
        line, lines = "", []
        for w in words:
            if len(line) + len(w) + 1 > 95:
                lines.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        if line:
            lines.append(line)
        for i, text in enumerate(lines):
            _text(page, 50, ty + 34 + i * 12, text, size=8)

    _text(page, 50, 800, "This is a formal invoice. Payment is due by the date shown above.",
          size=8, color=(0.3, 0.3, 0.3))

    doc.save(path)
    doc.close()
    print(f"wrote {path}")


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

def make_excel(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "应付明细"

    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="D9E2F3")

    ws.merge_cells("A1:I1")
    c = ws["A1"]
    c.value = "SHIPPING CHARGES DETAIL"
    c.font = Font(size=14, bold=True)
    c.alignment = Alignment(horizontal="center")
    c.fill = head_fill

    ws["A2"] = "Statement No."
    ws["B2"] = "STMT-FIXTURE-001"
    ws["D2"] = "Statement Date"
    ws["E2"] = "2026-10-26"
    ws["G2"] = "Currency"
    ws["H2"] = "USD / CNY"

    # Intentionally leave row 3 blank to exercise header-row detection.
    headers = ["序号", "费用名称", "单位", "数量", "单价", "币种", "金额", "付款方式", "备注"]
    header_row = 4
    for col, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=h)
        cell.font = Font(bold=True)
        cell.fill = head_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    rows = [
        (1, "海运费", "1x40HQ", 1, 1200.00, "USD", 1200.00, "PP", "Ocean Freight"),
        (2, "操作费", "-", 1, 65.00, "USD", 65.00, "PP", "Handling Charge"),
        (3, "文件费", "-", 1, 35.00, "USD", 35.00, "PP", "Documentation Fee"),
        (4, "拖车费", "-", 1, 120.00, "USD", 120.00, "PP", "Trucking Charge"),
        (5, "报关费", "-", 1, 80.00, "CNY", 80.00, "PP", "Customs Clearance Fee"),
    ]
    r = header_row + 1
    for row in rows:
        for col, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=col, value=value)
            cell.border = border
            cell.alignment = Alignment(vertical="center")
        r += 1

    # Totals per currency
    ws.cell(row=r, column=2, value="合计 USD").font = Font(bold=True)
    ws.cell(row=r, column=7, value=1420.00).font = Font(bold=True)
    ws.cell(row=r + 1, column=2, value="合计 CNY").font = Font(bold=True)
    ws.cell(row=r + 1, column=7, value=80.00).font = Font(bold=True)

    widths = [6, 16, 12, 8, 12, 8, 14, 10, 24]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    ws2 = wb.create_sheet("说明")
    ws2["A1"] = "说明"
    ws2["A1"].font = Font(bold=True)
    ws2["A2"] = "本文件为测试 fixture，用于验证 Excel 表头识别、多币种、合计行对账。"
    ws2["A3"] = "第 3 行故意留空；表头在第 4 行；合计行按币种分组。"
    ws2.column_dimensions["A"].width = 80

    wb.save(path)
    print(f"wrote {path}")


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------

def make_docx(path: Path) -> None:
    doc = Document()

    # Basic page setup
    section = doc.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("SHIPPING CHARGES STATEMENT")
    run.bold = True
    run.font.size = Pt(16)

    meta = [
        ("Statement No.", "STMT-FIXTURE-002"),
        ("Statement Date", "2026-10-26"),
        ("Period", "2026-10-01 to 2026-10-31"),
        ("Issuer", ISSUER),
        ("Bill To", ACCOUNTING_ENTITY),
        ("Currency", "USD"),
    ]
    for label, value in meta:
        p = doc.add_paragraph()
        p.add_run(f"{label}: ").bold = True
        p.add_run(value)

    doc.add_paragraph("")
    table = doc.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = ["DESCRIPTION", "UNIT", "RATE", "QTY", "P/C", "AMOUNT"]
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        cell.text = h
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True

    rows = [
        ("HANDLING CHARGE", "-", "65.00", "1.00", "P", "65.00"),
        ("DOCUMENTATION FEE", "-", "35.00", "1.00", "P", "35.00"),
        ("TRUCKING FEE", "-", "120.00", "1.00", "P", "120.00"),
    ]
    for row in rows:
        cells = table.add_row().cells
        for i, value in enumerate(row):
            cells[i].text = value

    doc.add_paragraph("")
    for label, value in (("SUBTOTAL", "USD 220.00"),
                         ("TAX", "USD 0.00"),
                         ("BALANCE DUE", "USD 220.00"),
                         ("PAYMENT DUE DATE", "2026-11-24")):
        p = doc.add_paragraph()
        p.add_run(f"{label}: ").bold = True
        p.add_run(value)

    note = doc.add_paragraph()
    note.add_run("Note: ").bold = True
    note.add_run("This statement consolidates the charges for the period and shows the balance due. "
                 "It is issued by the beneficiary named above.")

    doc.save(path)
    print(f"wrote {path}")


# ---------------------------------------------------------------------------
# Existing bills JSON
# ---------------------------------------------------------------------------

def make_existing_bills(path: Path) -> None:
    data = {
        "format_version": "1.0",
        "generated_at": "2026-11-05",
        "bills": [
            {
                "bill_id": "BILL-FIX-001",
                "reference_no": "INV-FIXTURE-001",
                "bl_no": BL_NO,
                "booking_no": BOOKING_NO,
                "container_nos": ["FIXU1234567", "FIXU7654321"],
                "document_date": "2026-10-25",
                "parties": {
                    "issuer": ISSUER,
                    "recipient": ACCOUNTING_ENTITY,
                },
                "payer": ACCOUNTING_ENTITY,
                "payee": REMIT_TO,
                "beneficiary": REMIT_TO,
                "posting_type": "AP",
                "currency": "USD",
                "charges": [
                    {
                        "line_id": "BILL-FIX-001-L1",
                        "charge_item": "Handling Charge",
                        "amount": 65.00,
                        "currency": "USD",
                        "payment_term": "PP",
                    },
                    {
                        "line_id": "BILL-FIX-001-L2",
                        "charge_item": "Documentation Fee",
                        "amount": 35.00,
                        "currency": "USD",
                        "payment_term": "PP",
                    },
                    {
                        "line_id": "BILL-FIX-001-L3",
                        "charge_item": "Trucking Charge",
                        "amount": 120.00,
                        "currency": "USD",
                        "payment_term": "PP",
                    },
                ],
                "total": 220.00,
                "raw": {
                    "source": "fixture",
                    "note": "Matches formal_invoice.pdf exactly (NO_CHANGE).",
                },
            },
            {
                "bill_id": "BILL-FIX-002",
                "reference_no": "DC-FIXTURE-002",
                "bl_no": "FIXUBL0000002",
                "booking_no": "FIXUBK0000002",
                "container_nos": ["FIXU0000002"],
                "document_date": "2026-10-20",
                "parties": {
                    "issuer": ISSUER,
                    "recipient": ACCOUNTING_ENTITY,
                },
                "payer": ACCOUNTING_ENTITY,
                "payee": REMIT_TO,
                "beneficiary": REMIT_TO,
                "posting_type": "AP",
                "currency": "USD",
                "charges": [
                    {
                        "line_id": "BILL-FIX-002-L1",
                        "charge_item": "Handling Charge",
                        "amount": 35.00,
                        "currency": "USD",
                        "payment_term": "PP",
                    },
                    {
                        "line_id": "BILL-FIX-002-L2",
                        "charge_item": "Handling Charge",
                        "amount": 35.00,
                        "currency": "USD",
                        "payment_term": "PP",
                    },
                ],
                "total": 70.00,
                "raw": {
                    "source": "fixture",
                    "note": "Two identical lines, used for one-to-one matching tests.",
                },
            },
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

def make_readme(path: Path) -> None:
    text = """# Fixtures（合成测试数据）

这些文件是为验证系统能力而**人工合成**的测试数据，不是真实业务单据。

## 文件与预期

| 文件 | 单据编号 | 用途 | 预期 operation |
|---|---|---|---|
| `formal_invoice.pdf` | INV-FIXTURE-001 | 与 `BILL-FIX-001` 完全一致 | `NO_CHANGE` |
| `formal_invoice_revised.pdf` | INV-FIXTURE-001 (R1) | Handling 65 → 80，并带明确更正说明 | `UPDATE` |
| `formal_invoice_create.pdf` | INV-FIXTURE-003 | 无历史匹配 | `CREATE` |
| `charges.xlsx` | STMT-FIXTURE-001 | Excel 表头/多币种/合计行 | `CREATE`（或按 statement 状态复核） |
| `statement.docx` | STMT-FIXTURE-002 | Word 正文 + 表格 + BALANCE DUE | `CREATE`（statement/confirmed） |
| `existing_bills.json` | — | 历史账单，供匹配/去重/AR-AP | 参考数据 |

## 关键字段

- Issuer：CARRIER ALPHA LIMITED
- Accounting entity / Payer：IMPORTER BETA (SHANGHAI)
- Payee / Beneficiary：CARRIER ALPHA LIMITED
- Master B/L：MAEU888777666
- House B/L：CGT260888888
- Booking：CGTSE260888888
- Containers：FIXU1234567, FIXU7654321
- `formal_invoice_create.pdf` 使用独立标识：MAEU999888777 / CGT260999999 / CGTSE260999999 / TGHU1234567

## 覆盖场景

1. **CREATE**：`formal_invoice_create.pdf`（INV-FIXTURE-003）
   - 使用独立的 B/L / booking / container：`MAEU999888777` / `CGTSE260999999` / `TGHU1234567`
   - 避免被 strict L2/L3/L4 误匹配到 `BILL-FIX-001`
2. **NO_CHANGE**：`formal_invoice.pdf` 对 `BILL-FIX-001`
3. **UPDATE**：`formal_invoice_revised.pdf` 对 `BILL-FIX-001`
   - 更正证据：`CORRECTION: HANDLING CHARGE AMOUNT REVISED FROM USD 65.00 TO USD 80.00`
4. **一对一匹配**：`BILL-FIX-002` 有两条同额同名 Handling 35
5. **Excel**：表头在第 4 行（第 3 行故意留空）、多币种、按币种合计
6. **Word**：正文 + 表格 + `BALANCE DUE`，用于 `billing_status=confirmed` 判定
7. **AR/AP**：Bill To/Payer 与 Payee/Beneficiary 明确，便于验证资金流判断

## 注意

- PDF 为**文字型**（非扫描件）。离线模式可用本地文本解析；真实 OCR 测试需把文件托管到公网 URL 后调用 OCR API。
- `formal_invoice_revised.pdf` 与 `formal_invoice.pdf` 使用同一 `reference_no`，靠 `REVISION` 和更正说明区分版本。
- `existing_bills.json` 的金额为 JSON number；适配层应转换为 `Decimal`。
"""
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path}")


def main() -> None:
    make_invoice_pdf(
        OUT / "formal_invoice.pdf",
        title="COMMERCIAL INVOICE",
        invoice_no="INV-FIXTURE-001",
        revision=None,
        charges=[
            ("HANDLING CHARGE", "-", "65.00", "1.00", "P", "65.00"),
            ("DOCUMENTATION FEE", "-", "35.00", "1.00", "P", "35.00"),
            ("TRUCKING FEE", "-", "120.00", "1.00", "P", "120.00"),
        ],
        subtotal="220.00",
        tax="0.00",
        total="220.00",
    )

    make_invoice_pdf(
        OUT / "formal_invoice_revised.pdf",
        title="COMMERCIAL INVOICE (REVISED)",
        invoice_no="INV-FIXTURE-001",
        revision="R1",
        charges=[
            ("HANDLING CHARGE", "-", "80.00", "1.00", "P", "80.00"),
            ("DOCUMENTATION FEE", "-", "35.00", "1.00", "P", "35.00"),
            ("TRUCKING FEE", "-", "120.00", "1.00", "P", "120.00"),
        ],
        subtotal="235.00",
        tax="0.00",
        total="235.00",
        remark=("CORRECTION: HANDLING CHARGE AMOUNT REVISED FROM USD 65.00 TO USD 80.00. "
                "ALL OTHER CHARGES UNCHANGED."),
    )

    make_invoice_pdf(
        OUT / "formal_invoice_create.pdf",
        title="COMMERCIAL INVOICE",
        invoice_no="INV-FIXTURE-003",
        revision=None,
        charges=[
            ("HANDLING CHARGE", "-", "100.00", "1.00", "P", "100.00"),
            ("DOCUMENTATION FEE", "-", "40.00", "1.00", "P", "40.00"),
            ("TRUCKING FEE", "-", "150.00", "1.00", "P", "150.00"),
        ],
        subtotal="290.00",
        tax="0.00",
        total="290.00",
        bl_no="MAEU999888777",
        hbl_no="CGT260999999",
        booking_no="CGTSE260999999",
        vessel="MSC FIXTURE 001E",
        containers="TGHU1234567",
    )

    make_excel(OUT / "charges.xlsx")
    make_docx(OUT / "statement.docx")
    make_existing_bills(OUT / "existing_bills.json")
    make_readme(OUT / "README.md")


if __name__ == "__main__":
    main()

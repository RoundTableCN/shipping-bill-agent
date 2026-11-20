"""Table header mapping shared by candidate generation."""

from __future__ import annotations

from ..models.bundle import TableBlock, TableCell

COLUMN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "charge_item": ("费用名称", "费用", "项目", "DESCRIPTION", "CHARGE", "ITEM", "PARTICULARS"),
    "charge_code": ("费用代码", "CHARGE CODE"),
    "charge_type": ("TYPE", "类型"),
    "base": ("BASE", "计费方式"),
    "qty": ("数量", "QTY", "QUANTITY"),
    "rate": ("单价", "RATE", "UNIT PRICE"),
    "roe": ("R.O.E", "ROE", "EXCHANGE RATE", "汇率"),
    "settlement_amount": ("SETTLEMENT AMOUNT", "结算金额", "结算额"),
    "settlement_currency": ("SETTLEMENT CURRENCY", "结算币种"),
    "amount": ("金额", "AMOUNT", "DEBIT", "合计金额"),
    "currency": ("币种", "CURRENCY", "CUR"),
    "payment_term": ("付款方式", "PAYMENT TERM", "PAYMENT TERMS", "TERM"),
    "prepaid_collect": ("P/C", "PC", "PREPAID/COLLECT", "PREPAID COLLECT", "预付/到付"),
    "payer_code": ("PAYER CODE", "付款方代码"),
    "payee_code": ("PAYEE CODE", "收款方代码"),
    "unit": ("单位", "UNIT"),
    "remark": ("备注", "REMARK", "MEMO"),
}

HEADER_HINTS = {kw for values in COLUMN_KEYWORDS.values() for kw in values}


def map_columns(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, text in enumerate(header):
        upper = (text or "").upper().strip()
        if not upper:
            continue
        for field, keywords in COLUMN_KEYWORDS.items():
            if field in mapping:
                continue
            if any(keyword.upper() in upper for keyword in keywords):
                mapping[field] = index
    return mapping


def table_rows(table: TableBlock) -> list[list[TableCell | None]]:
    if not table.cells:
        return []
    max_row = max(cell.row for cell in table.cells)
    max_col = max(cell.col for cell in table.cells)
    grid: list[list[TableCell | None]] = [
        [None for _ in range(max_col + 1)] for _ in range(max_row + 1)
    ]
    for cell in table.cells:
        grid[cell.row][cell.col] = cell
    return grid


def header_text(table: TableBlock) -> list[str]:
    rows = table_rows(table)
    if not rows:
        return []
    return [cell.text if cell else "" for cell in rows[0]]

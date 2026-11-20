"""Excel parsing: sheets, header detection, charge rows."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from ..models.bundle import DocumentBundle, SourceRef, TableBlock, TableCell, TextBlock, Warning
from .context import ParseContext, ParseError
from .detect import MediaType, detect_media_type_bytes
from .text_normalize import file_id_for, is_probable_total_line, normalize_text

COLUMN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "charge_item": ("费用名称", "费用", "项目", "DESCRIPTION", "CHARGE", "ITEM", "PARTICULARS"),
    "qty": ("数量", "QTY", "QUANTITY"),
    "rate": ("单价", "RATE", "UNIT PRICE"),
    "amount": ("金额", "AMOUNT", "DEBIT", "合计金额"),
    "currency": ("币种", "CURRENCY", "CUR"),
    "payment_term": ("付款方式", "P/C", "PAYMENT", "TERM"),
    "unit": ("单位", "UNIT"),
    "remark": ("备注", "REMARK", "MEMO"),
}

HEADER_HINTS = {kw for values in COLUMN_KEYWORDS.values() for kw in values}


def _cell_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value).strip()


def _xlsx_sheets(path: Path) -> list[tuple[str, list[list[str]]]]:
    workbook = load_workbook(path, data_only=True, read_only=True)
    sheets: list[tuple[str, list[list[str]]]] = []
    try:
        for sheet in workbook.worksheets:
            rows = [[_cell_to_text(cell) for cell in row] for row in sheet.iter_rows(values_only=True)]
            sheets.append((sheet.title, rows))
    finally:
        workbook.close()
    return sheets


def _xls_sheets(path: Path) -> list[tuple[str, list[list[str]]]]:
    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - dependency error
        raise ParseError("XLS_READER_MISSING", "install xlrd to read .xls files") from exc
    workbook = xlrd.open_workbook(path, on_demand=True)
    sheets: list[tuple[str, list[list[str]]]] = []
    try:
        for sheet in workbook.sheets():
            rows = [
                [_cell_to_text(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
                for r in range(sheet.nrows)
            ]
            sheets.append((sheet.name, rows))
    finally:
        workbook.release_resources()
    return sheets


def _header_score(row: list[str]) -> int:
    text = " ".join(row).upper()
    return sum(1 for hint in HEADER_HINTS if hint.upper() in text)


def _detect_header(rows: list[list[str]], max_scan: int = 15) -> int | None:
    best_index: int | None = None
    best_score = 1
    for index, row in enumerate(rows[:max_scan]):
        score = _header_score(row)
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _map_columns(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, text in enumerate(header):
        upper = text.upper().strip()
        if not upper:
            continue
        for field, keywords in COLUMN_KEYWORDS.items():
            if field in mapping:
                continue
            if any(keyword.upper() in upper for keyword in keywords):
                mapping[field] = index
    return mapping


def parse_excel(
    path: str | Path,
    ctx: ParseContext,
    *,
    data: bytes | None = None,
    file_name: str | None = None,
) -> DocumentBundle:
    path = Path(path)
    data = data if data is not None else path.read_bytes()
    file_id = file_id_for(data)
    file_name = file_name or path.name
    media_type = detect_media_type_bytes(data, file_name)

    sheets = _xls_sheets(path) if media_type is MediaType.XLS else _xlsx_sheets(path)

    tables: list[TableBlock] = []
    blocks: list[TextBlock] = []
    raw_lines: list[str] = []
    sheet_meta: list[dict[str, Any]] = []
    total_rows: list[dict[str, Any]] = []
    warnings: list[Warning] = []

    for sheet_index, (sheet_name, rows) in enumerate(sheets):
        raw_lines.append(f"### {sheet_name}")
        for row in rows:
            raw_lines.append("\t".join(row))

        header_row = _detect_header(rows)
        if header_row is None:
            warnings.append(
                Warning(
                    code="EXCEL_HEADER_NOT_FOUND",
                    message=f"sheet {sheet_name!r}: no header row detected",
                    severity="warning",
                )
            )
            continue

        header = rows[header_row]
        columns = _map_columns(header)
        data_rows = rows[header_row + 1:]
        table_no = sheet_index + 1
        table_id = f"sheet{sheet_index}-t1"

        cells: list[TableCell] = []
        for col, value in enumerate(header):
            if value:
                cells.append(TableCell(row=0, col=col, text=value))

        kept_rows = 0
        for r, row in enumerate(data_rows, start=1):
            if not any(cell.strip() for cell in row):
                continue
            joined = " | ".join(cell for cell in row if cell)
            if is_probable_total_line(joined):
                total_rows.append({"sheet": sheet_name, "row": header_row + r, "text": joined})
                continue
            kept_rows += 1
            for c, value in enumerate(row):
                if value:
                    cells.append(TableCell(row=r, col=c, text=value))

        if kept_rows:
            tables.append(
                TableBlock(
                    table_id=table_id,
                    page=None,
                    cells=cells,
                    header_row_count=1,
                )
            )
            blocks.append(
                TextBlock(
                    block_id=f"{table_id}-header",
                    page=None,
                    kind="line",
                    text=" | ".join(header),
                    order=len(blocks),
                )
            )

        sheet_meta.append(
            {
                "name": sheet_name,
                "header_row": header_row + 1,
                "columns": columns,
                "data_rows": kept_rows,
            }
        )

    raw_text = "\n".join(raw_lines)

    return DocumentBundle(
        bundle_id=f"xls-{file_id}",
        source=SourceRef(
            file_id=file_id,
            file_name=file_name,
            media_type=media_type.value,
        ),
        media_type=media_type.value,
        meta={
            "sheets": sheet_meta,
            "total_rows": total_rows,
        },
        raw_text=raw_text,
        norm_text=normalize_text(raw_text),
        blocks=blocks,
        tables=tables,
        ocr_mode="not_applicable",
        parse_quality=1.0,
        warnings=warnings,
    )

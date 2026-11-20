"""Plain text, HTML and CSV parsing."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from ..models.bundle import DocumentBundle, SourceRef, TableBlock, TableCell, TextBlock
from .context import ParseContext
from .detect import MediaType, detect_media_type_bytes
from .text_normalize import file_id_for, normalize_text


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        rows: list[str] = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if cells:
                rows.append(" | ".join(cells))
        table.replace_with("\n".join(rows))
    return soup.get_text("\n")


def parse_text(
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

    raw = _decode(data)
    if media_type is MediaType.HTML:
        raw = _html_to_text(raw)

    blocks: list[TextBlock] = []
    for n, line in enumerate(raw.splitlines()):
        text = line.strip()
        if text:
            blocks.append(
                TextBlock(
                    block_id=f"text-L{n}",
                    page=None,
                    kind="line",
                    text=text,
                    order=n,
                )
            )

    tables: list[TableBlock] = []
    if media_type is MediaType.CSV:
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        rows = list(csv.reader(io.StringIO(raw), delimiter=delimiter))
        if len(rows) >= 2 and any(any(cell.strip() for cell in row) for row in rows):
            cells: list[TableCell] = []
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    if value.strip():
                        cells.append(TableCell(row=r, col=c, text=value.strip()))
            tables.append(
                TableBlock(
                    table_id="csv-t1",
                    cells=cells,
                    header_row_count=1,
                )
            )

    return DocumentBundle(
        bundle_id=f"text-{file_id}",
        source=SourceRef(file_id=file_id, file_name=file_name, media_type=media_type.value),
        media_type=media_type.value,
        meta={"lines": len(blocks), "media_type": media_type.value},
        raw_text=raw,
        norm_text=normalize_text(raw),
        blocks=blocks,
        tables=tables,
        ocr_mode="not_applicable",
        parse_quality=1.0,
        warnings=[],
    )

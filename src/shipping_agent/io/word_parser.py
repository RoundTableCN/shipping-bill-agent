"""Word parsing: paragraphs and tables in body order."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..models.bundle import DocumentBundle, SourceRef, TableBlock, TableCell, TextBlock, Warning
from .context import ParseContext, ParseError
from .detect import MediaType, detect_media_type_bytes
from .text_normalize import file_id_for, normalize_text


def _iter_block_items(document):
    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield Table(child, document)


def _ps_quote(value: str) -> str:
    """Quote a path for a PowerShell single-quoted string."""
    return "'" + value.replace("'", "''") + "'"


def _convert_doc_with_word_com(path: Path, work_dir: Path) -> Path:
    """Windows fallback: use installed Microsoft Word via COM automation."""
    if os.name != "nt":
        raise ParseError(
            "LEGACY_DOC_UNSUPPORTED",
            "LibreOffice (soffice) or Microsoft Word is required to convert .doc files",
        )
    converted = work_dir / f"{path.stem}.docx"
    script = (
        "$ErrorActionPreference='Stop';"
        "$word=New-Object -ComObject Word.Application;"
        "$word.Visible=$false;"
        "$word.DisplayAlerts=0;"
        "try {"
        f"$doc=$word.Documents.Open({_ps_quote(str(path))},$false,$true);"
        "try {"
        f"$doc.SaveAs2({_ps_quote(str(converted))},16);"
        "} finally {"
        "$doc.Close(0);"
        "}"
        "} finally {"
        "$word.Quit();"
        "}"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not converted.exists():
        raise ParseError(
            "LEGACY_DOC_CONVERT_FAILED",
            (
                result.stderr
                or result.stdout
                or "Microsoft Word COM conversion failed"
            ).strip(),
        )
    return converted


def _convert_doc_to_docx(path: Path, work_dir: Path) -> Path:
    import shutil

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        result = subprocess.run(
            [soffice, "--headless", "--convert-to", "docx", "--outdir", str(work_dir), str(path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        converted = work_dir / f"{path.stem}.docx"
        if result.returncode != 0 or not converted.exists():
            raise ParseError(
                "LEGACY_DOC_CONVERT_FAILED",
                (result.stderr or result.stdout or "conversion failed").strip(),
            )
        return converted

    # Word COM is opt-in: on some machines Word opens a first-run dialog and
    # blocks non-interactive conversion.  The pure-Python fallback is safer.
    if os.name == "nt" and os.getenv("DOC_WORD_COM", "0") == "1":
        return _convert_doc_with_word_com(path, work_dir)

    raise ParseError(
        "LEGACY_DOC_UNSUPPORTED",
        "LibreOffice (soffice) is not installed; using the built-in .doc text parser",
    )


def _legacy_tables_from_lines(lines: list[str]) -> list[TableBlock]:
    """Turn pipe-delimited legacy-doc table lines into TableBlocks."""
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.count("|") >= 2:
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    tables: list[TableBlock] = []
    for group in groups:
        rows: list[list[str]] = []
        for line in group:
            parts = [part.strip() for part in line.split("|")]
            while parts and not parts[-1]:
                parts.pop()
            if len(parts) >= 2:
                rows.append(parts)
        if len(rows) < 2:
            continue
        cells: list[TableCell] = []
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                cells.append(TableCell(row=row_index, col=col_index, text=value))
        tables.append(
            TableBlock(
                table_id=f"doc-t{len(tables) + 1}",
                page=None,
                cells=cells,
                header_row_count=1,
            )
        )
    return tables


def _parse_legacy_doc(
    path: Path,
    ctx: ParseContext,
    data: bytes,
    file_name: str,
) -> DocumentBundle:
    from .legacy_doc import LegacyDocError, extract_legacy_doc_text

    try:
        text = extract_legacy_doc_text(path)
    except LegacyDocError as exc:
        raise ParseError("LEGACY_DOC_PARSE_FAILED", str(exc)) from exc

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blocks = [
        TextBlock(
            block_id=f"doc-p{index}",
            page=None,
            kind="paragraph",
            text=line,
            order=index,
        )
        for index, line in enumerate(lines)
    ]
    tables = _legacy_tables_from_lines(lines)
    raw_text = "\n".join(lines)
    return DocumentBundle(
        bundle_id=f"doc-{file_id_for(data)}",
        source=SourceRef(
            file_id=file_id_for(data),
            file_name=file_name,
            media_type="application/msword",
        ),
        media_type="application/msword",
        meta={
            "legacy_doc": True,
            "paragraphs": len(blocks),
            "tables": len(tables),
        },
        raw_text=raw_text,
        norm_text=normalize_text(raw_text),
        blocks=blocks,
        tables=tables,
        ocr_mode="not_applicable",
        parse_quality=0.7,
        warnings=[
            Warning(
                code="LEGACY_DOC_TEXT_FALLBACK",
                message=(
                    "LibreOffice is unavailable; extracted text from the "
                    "Word 97 binary piece table"
                ),
                severity="info",
            )
        ],
    )


def parse_word(
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

    warnings: list[Warning] = []
    blocks: list[TextBlock] = []
    tables: list[TableBlock] = []
    raw_lines: list[str] = []
    order = 0

    tmp_dir: tempfile.TemporaryDirectory | None = None
    try:
        source_path = path
        if media_type is MediaType.DOC:
            try:
                tmp_dir = tempfile.TemporaryDirectory()
                source_path = _convert_doc_to_docx(path, Path(tmp_dir.name))
            except ParseError as exc:
                if exc.code in {
                    "LEGACY_DOC_UNSUPPORTED",
                    "LEGACY_DOC_CONVERT_FAILED",
                }:
                    return _parse_legacy_doc(path, ctx, data, file_name)
                raise
            warnings.append(
                Warning(
                    code="LEGACY_DOC_CONVERTED",
                    message="converted .doc to .docx via LibreOffice or Microsoft Word",
                    severity="info",
                )
            )

        document = Document(source_path)
        for item in _iter_block_items(document):
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if text:
                    blocks.append(
                        TextBlock(
                            block_id=f"p-{order}",
                            page=None,
                            kind="paragraph",
                            text=text,
                            order=order,
                        )
                    )
                    raw_lines.append(text)
                    order += 1
            elif isinstance(item, Table):
                cells: list[TableCell] = []
                for row_index, row in enumerate(item.rows):
                    for col_index, cell in enumerate(row.cells):
                        text = cell.text.strip()
                        if text:
                            cells.append(TableCell(row=row_index, col=col_index, text=text))
                if cells:
                    table_id = f"tbl-{len(tables) + 1}"
                    tables.append(
                        TableBlock(
                            table_id=table_id,
                            page=None,
                            cells=cells,
                            header_row_count=1,
                        )
                    )
                    for row in item.rows:
                        raw_lines.append(" | ".join(c.text.strip() for c in row.cells))
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()

    raw_text = "\n".join(raw_lines)

    return DocumentBundle(
        bundle_id=f"doc-{file_id}",
        source=SourceRef(
            file_id=file_id,
            file_name=file_name,
            media_type=media_type.value,
        ),
        media_type=media_type.value,
        meta={
            "paragraphs": sum(1 for block in blocks if block.kind == "paragraph"),
            "tables": len(tables),
        },
        raw_text=raw_text,
        norm_text=normalize_text(raw_text),
        blocks=blocks,
        tables=tables,
        ocr_mode="not_applicable",
        parse_quality=1.0,
        warnings=warnings,
    )

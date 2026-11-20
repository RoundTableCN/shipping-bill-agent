"""PDF parsing: text blocks, coordinate row reconstruction, table detection."""

from __future__ import annotations

import os
import re
from pathlib import Path

import fitz

from ..models.bundle import DocumentBundle, SourceRef, TableBlock, TableCell, TextBlock, Warning
from .context import ParseContext, ParseError
from .text_normalize import (
    file_id_for,
    is_legal_boilerplate,
    is_probable_total_line,
    normalize_text,
)

HEADER_TOKENS = {
    "DESCRIPTION", "CHARGE", "CHARGES", "UNIT", "RATE", "QTY", "QUANTITY",
    "P/C", "PC", "AMOUNT", "CUR", "CURRENCY", "DEBIT", "CREDIT", "ITEM",
    "TOTAL", "费用", "金额", "币种", "数量", "单价", "合计",
}


def _cluster_rows(words: list[tuple], tolerance: float = 3.0) -> list[tuple[float, list[tuple]]]:
    buckets: dict[float, list[tuple]] = {}
    for word in words:
        key = round(word[1] / tolerance) * tolerance
        buckets.setdefault(key, []).append(word)
    return [(y, sorted(ws, key=lambda w: w[0])) for y, ws in sorted(buckets.items())]


def _row_text(words: list[tuple]) -> str:
    return " ".join(str(w[4]) for w in sorted(words, key=lambda w: w[0])).strip()


def _bbox(words: list[tuple]) -> list[float] | None:
    if not words:
        return None
    return [
        min(w[0] for w in words),
        min(w[1] for w in words),
        max(w[2] for w in words),
        max(w[3] for w in words),
    ]


def _normalize_token(word: str) -> str:
    token = word.upper().strip()
    return re.sub(r"[^A-Z0-9/]", "", token)


def _header_score(words: list[tuple]) -> int:
    tokens = {_normalize_token(str(w[4])) for w in words}
    return sum(1 for token in tokens if token in HEADER_TOKENS)


def _is_header_row(words: list[tuple]) -> bool:
    if len(words) < 3 or len(words) > 12:
        return False
    text = _row_text(words)
    if len(text) > 140 or is_probable_total_line(text) or is_legal_boilerplate(text):
        return False
    return _header_score(words) >= 2


def _assign_columns(words: list[tuple], columns: list[tuple[float, float]]) -> list[str]:
    cells = [""] * len(columns)
    for word in sorted(words, key=lambda w: w[0]):
        center = (word[0] + word[2]) / 2
        index = 0
        for i, (x0, _x1) in enumerate(columns):
            if center >= x0 - 5:
                index = i
        cells[index] = f"{cells[index]} {word[4]}".strip()
    return cells


def _detect_tables(
    rows: list[tuple[float, list[tuple]]],
    page_index: int,
    page_width: float,
) -> list[TableBlock]:
    tables: list[TableBlock] = []
    i = 0
    table_no = 0
    while i < len(rows):
        _y, words = rows[i]
        if not _is_header_row(words):
            i += 1
            continue

        header_words = sorted(words, key=lambda w: w[0])
        columns: list[tuple[float, float]] = []
        for idx, word in enumerate(header_words):
            x0 = word[0]
            x1 = header_words[idx + 1][0] if idx + 1 < len(header_words) else page_width
            columns.append((x0, max(x1, x0 + 1)))

        data_rows: list[list[tuple]] = []
        j = i + 1
        while j < len(rows):
            y2, row_words = rows[j]
            row_text = _row_text(row_words)
            if _is_header_row(row_words):
                break
            if is_probable_total_line(row_text):
                break
            if is_legal_boilerplate(row_text) or len(row_words) > 20:
                break
            if y2 - rows[j - 1][0] > 28:
                break
            if len(row_words) >= 2:
                data_rows.append(row_words)
            j += 1

        if not data_rows:
            i += 1
            continue

        cells: list[TableCell] = []
        for col, word in enumerate(header_words):
            cells.append(
                TableCell(
                    row=0,
                    col=col,
                    text=str(word[4]),
                    bbox=[word[0], word[1], word[2], word[3]],
                )
            )
        for r, row_words in enumerate(data_rows, start=1):
            values = _assign_columns(row_words, columns)
            for c, value in enumerate(values):
                if not value:
                    continue
                cells.append(
                    TableCell(
                        row=r,
                        col=c,
                        text=value,
                        bbox=_bbox(row_words),
                    )
                )

        table_no += 1
        tables.append(
            TableBlock(
                table_id=f"p{page_index}-t{table_no}",
                page=page_index,
                bbox=_bbox(header_words + [w for row in data_rows for w in row]),
                cells=cells,
                header_row_count=1,
            )
        )
        i = j

    return tables


def _parse_page_words(page: fitz.Page, page_index: int, order_start: int) -> tuple[list[TextBlock], list[TableBlock], int]:
    words = page.get_text("words")
    rows = _cluster_rows(words)
    blocks: list[TextBlock] = []
    order = order_start
    for row_no, (y, row_words) in enumerate(rows):
        text = _row_text(row_words)
        if not text:
            continue
        blocks.append(
            TextBlock(
                block_id=f"p{page_index}-r{row_no}",
                page=page_index,
                kind="line",
                text=text,
                bbox=_bbox(row_words),
                order=order,
            )
        )
        order += 1

    tables = _detect_tables(rows, page_index, page.rect.width)
    return blocks, tables, order


def _ocr_page(
    page: fitz.Page,
    page_index: int,
    ctx: ParseContext,
    file_id: str,
    order_start: int,
) -> tuple[str, list[TextBlock], list[TableBlock], bool, list[Warning], int]:
    if ctx.ocr_client is None:
        return "", [], [], False, [
            Warning(code="OCR_CLIENT_REQUIRED", message="no OCR client configured")
        ], order_start
    if ctx.hosting is None:
        return "", [], [], False, [
            Warning(
                code="OCR_URL_REQUIRED",
                message="OCR_FILE_BASE_URL is not configured; page not uploaded",
            )
        ], order_start

    ocr_dir = ctx.run_dir / "ocr_pages"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    image_path = ocr_dir / f"{file_id}-p{page_index}.png"
    pix = page.get_pixmap(dpi=200)
    pix.save(str(image_path))

    file_url = ctx.hosting.url_for(image_path)
    if not file_url:
        return "", [], [], False, [
            Warning(
                code="OCR_URL_REQUIRED",
                message="hosting adapter returned no public URL",
            )
        ], order_start

    try:
        result = ctx.ocr_client.extract(image_path, file_url)
    except Exception as exc:  # noqa: BLE001 - OCR failure must not kill the PDF
        return "", [], [], False, [
            Warning(code="OCR_FAILED", message=str(exc))
        ], order_start

    blocks: list[TextBlock] = []
    order = order_start
    for n, line in enumerate(result.text.splitlines()):
        text = line.strip()
        if not text:
            continue
        blocks.append(
            TextBlock(
                block_id=f"p{page_index}-ocr{n}",
                page=page_index,
                kind="ocr_line",
                text=text,
                order=order,
            )
        )
        order += 1

    tables: list[TableBlock] = []
    for t_index, rows in enumerate(result.tables, start=1):
        cells: list[TableCell] = []
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if value:
                    cells.append(TableCell(row=r, col=c, text=str(value)))
        if cells:
            tables.append(
                TableBlock(
                    table_id=f"p{page_index}-ocr{t_index}",
                    page=page_index,
                    cells=cells,
                    header_row_count=1 if len(rows) >= 2 else 0,
                )
            )

    warnings: list[Warning] = []
    if not result.text and not result.tables:
        warnings.append(
            Warning(
                code="OCR_EMPTY",
                message=f"OCR returned nothing for page {page_index}",
            )
        )
    return result.text, blocks, tables, result.mode == "api", warnings, order


def parse_pdf(
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

    try:
        doc = fitz.open(path)
    except Exception as exc:  # noqa: BLE001 - PyMuPDF raises several types
        raise ParseError("PDF_OPEN_FAILED", str(exc)) from exc

    if doc.needs_pass:
        doc.close()
        raise ParseError("PDF_ENCRYPTED", "PDF requires a password")

    page_count = doc.page_count
    raw_parts: list[str] = []
    all_blocks: list[TextBlock] = []
    all_tables: list[TableBlock] = []
    scanned_pages: list[int] = []
    ocr_attempts: list[int] = []
    ocr_pages: list[int] = []
    ocr_failures: list[int] = []
    warnings: list[Warning] = []
    order = 0
    # A URL input is already public: try the OCR API against the original PDF
    # URL before anything else.  This avoids needing OCR_FILE_BASE_URL for the
    # common "paste a public link" workflow.
    url_ocr_attempted = False
    if ctx.source_url and ctx.ocr_mode == "api" and ctx.ocr_client is not None:
        url_ocr_attempted = True
        try:
            url_result = ctx.ocr_client.extract(path, ctx.source_url)
        except Exception as exc:  # noqa: BLE001 - fall through to local/vision
            warnings.append(
                Warning(
                    code="OCR_FAILED",
                    message=f"URL OCR failed: {type(exc).__name__}: {exc}",
                )
            )
        else:
            if url_result.text or url_result.tables:
                from .image_parser import _bundle_from_ocr

                bundle = _bundle_from_ocr(
                    file_id=file_id,
                    file_name=file_name,
                    media_type="application/pdf",
                    result=url_result,
                )
                bundle.bundle_id = f"pdf-{file_id}"
                bundle.meta["page_count"] = page_count
                bundle.meta["ocr_source_url"] = ctx.source_url
                bundle.meta["ocr_input"] = "url"
                doc.close()
                return bundle
            warnings.append(
                Warning(
                    code="OCR_EMPTY",
                    message="URL OCR returned no text or tables",
                )
            )

    # OCR is the primary reader for PDFs in api mode.  If OCR returns nothing
    # (notably for text-layer PDFs), fall back to the local text layer.
    ocr_first = ctx.ocr_mode == "api" and os.getenv("OCR_PDF_FIRST", "1") != "0"

    try:
        for page_index in range(page_count):
            page = doc[page_index]
            local_text = page.get_text("text")
            has_local_text = len(local_text.strip()) >= 80
            if not has_local_text:
                scanned_pages.append(page_index)

            ocr_text = ""
            ocr_blocks: list[TextBlock] = []
            ocr_tables: list[TableBlock] = []
            ocr_used = False

            should_try_ocr = ctx.ocr_mode == "api" and (
                ocr_first or not has_local_text
            )
            # When a public URL was supplied but no OCR_FILE_BASE_URL exists,
            # the whole-document URL OCR was already attempted above; page
            # images cannot be uploaded, so do not repeat a known failure.
            if ctx.source_url and ctx.hosting is None:
                should_try_ocr = False
            if should_try_ocr:
                ocr_attempts.append(page_index)
                (
                    ocr_text,
                    ocr_blocks,
                    ocr_tables,
                    _used,
                    ocr_warnings,
                    order,
                ) = _ocr_page(page, page_index, ctx, file_id, order)
                warnings.extend(ocr_warnings)
                if ocr_text or ocr_tables:
                    ocr_pages.append(page_index)
                    ocr_used = True
                else:
                    ocr_failures.append(page_index)

            if ocr_used:
                page_text = ocr_text
                all_blocks.extend(ocr_blocks)
                all_tables.extend(ocr_tables)
            else:
                page_text = local_text
                blocks, tables, order = _parse_page_words(page, page_index, order)
                all_blocks.extend(blocks)
                all_tables.extend(tables)

            raw_parts.append(page_text)
    finally:
        doc.close()

    raw_text = "\n".join(raw_parts)
    if scanned_pages and ctx.ocr_mode != "api":
        warnings.append(
            Warning(
                code="OCR_REQUIRED",
                message=f"Pages with little/no text layer: {scanned_pages}",
                severity="warning",
            )
        )
        ctx.warn("OCR_REQUIRED", f"scanned pages: {scanned_pages}")
    if ocr_failures:
        ctx.warn("OCR_FAILED", f"OCR failed for pages: {ocr_failures}")

    # Last line of defence for scanned PDFs: render the PDF and ask the
    # configured vision model, exactly like the image path.
    if not raw_text.strip() and not all_tables:
        from .image_parser import _bundle_from_vision, _vision_fallback_enabled

        if _vision_fallback_enabled(ctx):
            try:
                from ..vision_extractor import VisionExtractor

                vision = VisionExtractor().extract(path)
                if not vision.error and (
                    vision.data.charges
                    or vision.data.reference_no
                    or vision.data.total is not None
                ):
                    vision_bundle = _bundle_from_vision(
                        file_id=file_id,
                        file_name=file_name,
                        media_type="application/pdf",
                        data=vision.data,
                        model=vision.model,
                        elapsed=vision.elapsed,
                    )
                    vision_bundle.bundle_id = f"pdf-{file_id}"
                    vision_bundle.meta["page_count"] = page_count
                    vision_bundle.meta["ocr_source_url"] = ctx.source_url
                    vision_bundle.warnings.extend(warnings)
                    return vision_bundle
                warnings.append(
                    Warning(
                        code="VISION_FALLBACK_FAILED",
                        message=(
                            vision.error
                            or "vision returned no usable PDF fields"
                        ),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep local empty bundle
                warnings.append(
                    Warning(
                        code="VISION_FALLBACK_FAILED",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )

    if ocr_pages:
        ocr_mode = "api"
    elif ctx.ocr_mode == "api":
        ocr_mode = "degraded_local"
    elif ctx.ocr_mode == "local":
        ocr_mode = "degraded_local"
    else:
        ocr_mode = "mock"

    return DocumentBundle(
        bundle_id=f"pdf-{file_id}",
        source=SourceRef(
            file_id=file_id,
            file_name=file_name,
            media_type="application/pdf",
        ),
        media_type="application/pdf",
        meta={
            "page_count": page_count,
            "scanned_pages": scanned_pages,
            "ocr_attempts": ocr_attempts,
            "ocr_pages": ocr_pages,
            "ocr_failures": ocr_failures,
            "url_ocr_attempted": url_ocr_attempted,
            "ocr_source_url": ctx.source_url,
        },
        raw_text=raw_text,
        norm_text=normalize_text(raw_text),
        blocks=all_blocks,
        tables=all_tables,
        ocr_mode=ocr_mode,
        parse_quality=0.9 if ocr_pages else (0.6 if scanned_pages else 1.0),
        warnings=warnings,
    )

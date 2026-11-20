"""Image parsing via OCR (mock by default until the API is probed)."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import fitz
from PIL import Image

from ..models.bundle import DocumentBundle, SourceRef, TableBlock, TableCell, TextBlock, Warning
from .context import ParseContext, ParseError
from .detect import detect_media_type_bytes
from .ocr_client import MockOcrClient, OcrResult
from .text_normalize import file_id_for, normalize_text


def _vision_fallback_enabled(ctx: ParseContext) -> bool:
    """The final image recognizer is the configured vision-capable LLM.

    It is on by default but skips silently when no usable API is configured.
    Set VISION_FALLBACK=0, or ParseContext.vision_fallback=False, to disable.
    """
    if ctx.vision_fallback is not None:
        return ctx.vision_fallback
    if os.getenv("VISION_FALLBACK", "1") == "0":
        return False
    try:
        from ..vision_extractor import VisionConfig

        return VisionConfig.from_env().enabled
    except Exception:
        return False


def _bundle_from_ocr(
    *,
    file_id: str,
    file_name: str,
    media_type: str,
    result: OcrResult,
) -> DocumentBundle:
    blocks: list[TextBlock] = []
    for n, line in enumerate(result.text.splitlines()):
        text = line.strip()
        if text:
            blocks.append(
                TextBlock(
                    block_id=f"ocr-L{n}",
                    page=None,
                    kind="ocr_line",
                    text=text,
                    order=n,
                )
            )

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
                    table_id=f"ocr-t{t_index}",
                    page=None,
                    cells=cells,
                    header_row_count=1 if len(rows) >= 2 else 0,
                )
            )

    warnings: list[Warning] = []
    if not result.text and not result.tables:
        warnings.append(
            Warning(
                code="OCR_EMPTY",
                message="OCR returned no text or tables",
                severity="warning",
            )
        )

    return DocumentBundle(
        bundle_id=f"img-{file_id}",
        source=SourceRef(file_id=file_id, file_name=file_name, media_type=media_type),
        media_type=media_type,
        meta={"ocr_mode": result.mode},
        raw_text=result.text,
        norm_text=normalize_text(result.text),
        blocks=blocks,
        tables=tables,
        ocr_raw=result.raw,
        ocr_mode="api" if result.mode == "api" else "mock",
        parse_quality=1.0 if (result.text or result.tables) else 0.0,
        warnings=warnings,
    )


def _vision_quantity(charge) -> object:
    """Drop a quantity that is actually an ROE value.

    Vision models sometimes put ROE (e.g. 1.0) into QTY.  Only discard it
    when QTY == ROE and QTY*Rate does not reconcile with Amount.
    """
    quantity = charge.quantity
    rate = charge.unit_price
    amount = charge.amount
    roe = charge.roe
    if (
        quantity is None
        or roe is None
        or rate is None
        or amount is None
        or quantity != roe
    ):
        return quantity
    try:
        if abs(quantity * rate - amount) > Decimal("0.01"):
            return None
    except Exception:  # noqa: BLE001 - keep the model value if types differ
        return quantity
    return quantity


def _bundle_from_vision(
    *,
    file_id: str,
    file_name: str,
    media_type: str,
    data,
    model: str,
    elapsed: float,
) -> DocumentBundle:
    """Convert a vision extraction into the same bundle shape as OCR."""
    fields = [
        ("DOCUMENT TYPE", data.document_type),
        ("DOCUMENT NO", data.document_number),
        ("INVOICE NO", data.invoice_number),
        ("REFERENCE NO", data.reference_no),
        ("DOCUMENT DATE", data.document_date),
        ("DOCUMENT DATE RAW", data.document_date_raw),
        ("ISSUER", data.issuer),
        ("RECIPIENT", data.recipient),
        ("PAYER", data.payer),
        ("PAYEE", data.payee),
        ("BENEFICIARY", data.beneficiary),
        ("MBL NO", data.mbl_no),
        ("HBL NO", data.hbl_no),
        ("B/L NO", data.bl_no),
        ("WAYBILL NO", data.waybill_no),
        ("BOOKING NO", data.booking_no),
        ("CONTAINER NO", ", ".join(data.container_nos)),
        ("SEAL NO", ", ".join(data.seal_nos)),
        ("VESSEL", data.vessel),
        ("VOYAGE", data.voyage),
        ("POL", data.pol),
        ("POD", data.pod),
        ("PAYMENT TERM", data.payment_term),
        ("PAYMENT DUE INSTRUCTION", data.payment_due_instruction),
        ("PAYMENT RECEIVED", data.payment_received),
        ("RELEASE TYPE", data.release_type),
        ("RELEASE STATUS", data.release_status),
        ("SHIPMENT STATUS", data.shipment_operation_status),
        ("CURRENCY", data.currency),
        ("SUBTOTAL", data.subtotal),
        ("TAX", data.tax),
        ("TOTAL", data.total),
    ]
    lines = [f"{label}: {value}" for label, value in fields if value is not None]
    blocks: list[TextBlock] = []
    for n, line in enumerate(lines):
        blocks.append(
            TextBlock(
                block_id=f"vision-L{n}",
                page=None,
                kind="ocr_line",
                text=line,
                order=n,
            )
        )

    headers = [
        "DESCRIPTION",
        "CODE",
        "QTY",
        "BASE",
        "RATE",
        "ROE",
        "AMOUNT",
        "CURRENCY",
        "P/C",
        "PAYMENT TERM",
        "PAYER CODE",
        "PAYEE CODE",
    ]
    cells: list[TableCell] = [
        TableCell(row=0, col=col, text=header)
        for col, header in enumerate(headers)
    ]
    for row, charge in enumerate(data.charges, start=1):
        values = [
            charge.name,
            charge.code,
            _vision_quantity(charge),
            charge.base,
            charge.unit_price,
            charge.roe,
            charge.amount,
            charge.currency,
            charge.prepaid_collect,
            charge.payment_term,
            charge.payer_code,
            charge.payee_code,
        ]
        for col, value in enumerate(values):
            if value is not None:
                cells.append(TableCell(row=row, col=col, text=str(value)))

    tables: list[TableBlock] = []
    if data.charges:
        tables.append(
            TableBlock(
                table_id="vision-t1",
                page=None,
                cells=cells,
                header_row_count=1,
            )
        )

    raw_text = "\n".join(lines)
    return DocumentBundle(
        bundle_id=f"img-{file_id}",
        source=SourceRef(file_id=file_id, file_name=file_name, media_type=media_type),
        media_type=media_type,
        meta={
            "ocr_mode": "vision",
            "vision_model": model,
            "vision_elapsed": elapsed,
            "vision_fallback": True,
        },
        raw_text=raw_text,
        norm_text=normalize_text(raw_text),
        blocks=blocks,
        tables=tables,
        ocr_raw={"vision": data.model_dump(mode="json")},
        ocr_mode="vision",
        parse_quality=0.5,
        warnings=[
            Warning(
                code="VISION_FALLBACK",
                message=(
                    "OCR returned no text; used the vision model as fallback. "
                    "Result requires manual review."
                ),
                severity="warning",
            )
        ],
    )


def _image_to_pdf(path: Path, ctx: ParseContext, file_id: str) -> Path:
    """The OCR task accepts PDFs but times out on direct PNGs; wrap the image."""
    ocr_dir = ctx.run_dir / "ocr_pages"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = ocr_dir / f"{file_id}.pdf"
    doc = fitz.open()
    try:
        with Image.open(path) as image:
            width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError("image has invalid dimensions")
        page = doc.new_page(width=width, height=height)
        page.insert_image(page.rect, filename=str(path))
        doc.save(str(pdf_path))
    except Exception as exc:  # noqa: BLE001 - conversion failure must be explicit
        raise ParseError("IMAGE_TO_PDF_FAILED", str(exc)) from exc
    finally:
        doc.close()
    return pdf_path


def parse_image(
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
    media_type = detect_media_type_bytes(data, file_name).value

    client = ctx.ocr_client
    if client is None:
        if ctx.ocr_mode == "api":
            raise ParseError(
                "OCR_CLIENT_REQUIRED",
                "api mode requires an OCR client",
            )
        client = MockOcrClient()

    ocr_input = path
    file_url = None
    if ctx.ocr_mode == "api" and ctx.source_url:
        # The URL input is already public; let the OCR server fetch it
        # directly.  No local re-hosting or PNG-to-PDF conversion is needed.
        file_url = ctx.source_url
    elif ctx.ocr_mode == "api" and ctx.hosting is not None:
        if os.getenv("OCR_IMAGE_AS_PDF", "1") != "0":
            ocr_input = _image_to_pdf(path, ctx, file_id)
        file_url = ctx.hosting.url_for(ocr_input)

    ocr_failed_warning: Warning | None = None
    if ctx.ocr_mode == "api" and not file_url:
        if _vision_fallback_enabled(ctx):
            # No public OCR URL: skip OCR and let the configured vision model
            # try the original image.
            result = OcrResult(text="", tables=[], raw={}, mode="api")
        else:
            raise ParseError(
                "OCR_URL_REQUIRED",
                "api mode requires OCR_FILE_BASE_URL (or a tunnel) so the OCR "
                "server can download the image; alternatively configure a "
                "vision-capable model (VISION_* or the first-run API) as the "
                "final fallback",
            )
    else:
        try:
            result = client.extract(ocr_input, file_url)
        except Exception as exc:  # noqa: BLE001 - OCR must not skip the fallbacks
            result = OcrResult(text="", tables=[], raw={}, mode="api")
            ocr_failed_warning = Warning(
                code="OCR_FAILED",
                message=f"{type(exc).__name__}: {exc}",
                severity="warning",
            )
    bundle = _bundle_from_ocr(
        file_id=file_id,
        file_name=file_name,
        media_type=media_type,
        result=result,
    )
    if ocr_failed_warning is not None:
        bundle.warnings.append(ocr_failed_warning)
    bundle.meta["ocr_input"] = "pdf" if ocr_input != path else "image"
    bundle.meta["ocr_file_type"] = result.file_type
    bundle.meta["url_ocr_attempted"] = bool(ctx.source_url)
    bundle.meta["ocr_source_url"] = ctx.source_url
    if not result.text and not result.tables:
        if not any(warning.code == "OCR_EMPTY" for warning in bundle.warnings):
            bundle.warnings.append(
                Warning(
                    code="OCR_EMPTY",
                    message="OCR returned no text or tables for this image",
                    severity="warning",
                )
            )
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
                        media_type=media_type,
                        data=vision.data,
                        model=vision.model,
                        elapsed=vision.elapsed,
                    )
                    vision_bundle.meta["ocr_input"] = (
                        "pdf" if ocr_input != path else "image"
                    )
                    vision_bundle.meta["ocr_file_type"] = result.file_type
                    vision_bundle.meta["url_ocr_attempted"] = bool(ctx.source_url)
                    vision_bundle.meta["ocr_source_url"] = ctx.source_url
                    vision_bundle.warnings.extend(bundle.warnings)
                    return vision_bundle
                bundle.warnings.append(
                    Warning(
                        code="VISION_FALLBACK_FAILED",
                        message=vision.error or "vision returned no usable fields",
                        severity="warning",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - fallback must not hide OCR result
                bundle.warnings.append(
                    Warning(
                        code="VISION_FALLBACK_FAILED",
                        message=f"{type(exc).__name__}: {exc}",
                        severity="warning",
                    )
                )
        elif os.getenv("VISION_FALLBACK", "1") != "0":
            bundle.warnings.append(
                Warning(
                    code="VISION_FALLBACK_UNAVAILABLE",
                    message=(
                        "image OCR returned nothing and no vision-capable API "
                        "is configured; set VISION_BASE_URL/VISION_MODEL/"
                        "VISION_API_KEY (or ANTHROPIC_*), or choose an "
                        "image-capable model in the first-run API settings"
                    ),
                    severity="warning",
                )
            )
    return bundle

"""EML parsing: headers, body, recursive attachments."""

from __future__ import annotations

import email
from email import policy
from pathlib import Path

from ..models.bundle import Attachment, DocumentBundle, SourceRef, TextBlock, Warning
from .context import ParseContext, ParseError
from .detect import MediaType, detect_media_type_bytes
from .text_normalize import file_id_for, normalize_text, safe_filename, sha256_bytes

BILLING_KEYWORDS = ("invoice", "debit", "credit", "statement", "bill", "dn", "cn", "账单", "对账单", "发票")
REFERENCE_KEYWORDS = ("b/l", "bill of lading", "提单", "packing", "booking", "manifest", "waybill")
IMAGE_TYPES = {MediaType.PNG, MediaType.JPEG, MediaType.TIFF, MediaType.GIF, MediaType.BMP, MediaType.WEBP}


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


def _looks_billing(child: DocumentBundle | None) -> bool:
    if child is None:
        return False
    upper = child.raw_text.upper()
    if "INVOICE" in upper or "DEBIT NOTE" in upper or "CREDIT NOTE" in upper:
        return True
    for table in child.tables:
        header = " ".join(
            cell.text.upper() for cell in table.cells if cell.row < table.header_row_count
        )
        if "CHARGE" in header and ("AMOUNT" in header or "DESCRIPTION" in header):
            return True
    return False


def _role_for(filename: str, inline: bool, media_type: MediaType, child: DocumentBundle | None) -> str:
    if inline or media_type in IMAGE_TYPES:
        return "media"
    lower = filename.lower()
    if any(k in lower for k in BILLING_KEYWORDS):
        return "billing"
    if any(k in lower for k in REFERENCE_KEYWORDS):
        return "reference"
    if _looks_billing(child):
        return "billing"
    if child is not None:
        return "reference"
    return "unknown"


def parse_eml(
    path: str | Path,
    ctx: ParseContext,
    *,
    data: bytes | None = None,
    file_name: str | None = None,
    depth: int = 0,
) -> DocumentBundle:
    path = Path(path)
    data = data if data is not None else path.read_bytes()
    file_id = file_id_for(data)
    file_name = file_name or path.name

    msg = email.message_from_bytes(data, policy=policy.default)

    meta = {
        "subject": str(msg.get("subject") or ""),
        "from": str(msg.get("from") or ""),
        "to": str(msg.get("to") or ""),
        "cc": str(msg.get("cc") or ""),
        "date": str(msg.get("date") or ""),
        "message_id": str(msg.get("message-id") or ""),
    }

    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[Attachment] = []
    warnings: list[Warning] = []
    att_index = 0

    def walk(part: email.message.Message, parent_type: str) -> None:
        nonlocal att_index

        if part.is_multipart():
            for sub in part.iter_parts():
                walk(sub, part.get_content_type())
            return

        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if not filename:
            if part.get_content_type() == "text/plain":
                try:
                    plain_parts.append(part.get_content())
                except Exception:  # noqa: BLE001
                    pass
            elif part.get_content_type() == "text/html":
                try:
                    html_parts.append(part.get_content())
                except Exception:  # noqa: BLE001
                    pass
            return

        payload = part.get_payload(decode=True) or b""
        media_type = detect_media_type_bytes(payload, filename)
        inline = disposition == "inline" or (
            disposition is None and parent_type == "multipart/related"
        )

        if ctx.attachment_count >= ctx.max_attachments:
            warnings.append(
                Warning(
                    code="ATTACHMENT_LIMIT",
                    message=f"attachment limit {ctx.max_attachments} reached",
                    severity="warning",
                )
            )
            return
        ctx.attachment_count += 1

        att_index += 1
        safe_name = f"{att_index:02d}_{safe_filename(filename)}"
        saved_path = ctx.attachment_dir() / safe_name
        saved_path.write_bytes(payload)
        digest = sha256_bytes(payload)

        child: DocumentBundle | None = None
        if not inline and media_type not in IMAGE_TYPES and depth < ctx.max_depth:
            from .dispatcher import parse_bytes

            try:
                child = parse_bytes(payload, filename, ctx, depth=depth + 1)
            except ParseError as exc:
                warnings.append(
                    Warning(
                        code=exc.code,
                        message=f"{filename}: {exc.message}",
                        severity="warning",
                    )
                )

        role = _role_for(filename, inline, media_type, child)
        attachments.append(
            Attachment(
                file_name=filename,
                media_type=media_type.value,
                size=len(payload),
                sha256=digest,
                inline=inline,
                content_id=part.get("content-id"),
                child=child,
                role=role,
            )
        )

    walk(msg, msg.get_content_type())

    raw_body = "\n".join(p for p in plain_parts if p).strip()
    body_source = "text/plain"
    if not raw_body and html_parts:
        raw_body = _html_to_text("\n".join(html_parts)).strip()
        body_source = "text/html"

    blocks: list[TextBlock] = []
    for n, line in enumerate(raw_body.splitlines()):
        text = line.strip()
        if not text:
            continue
        blocks.append(
            TextBlock(
                block_id=f"body-L{n}",
                page=None,
                kind="line",
                text=text,
                order=n,
            )
        )

    meta["body_source"] = body_source
    meta["attachment_count"] = len(attachments)

    return DocumentBundle(
        bundle_id=f"eml-{file_id}",
        source=SourceRef(
            file_id=file_id,
            file_name=file_name,
            media_type="message/rfc822",
        ),
        media_type="message/rfc822",
        meta=meta,
        raw_text=raw_body,
        norm_text=normalize_text(raw_body),
        blocks=blocks,
        attachments=attachments,
        ocr_mode="not_applicable",
        parse_quality=1.0,
        warnings=warnings,
    )

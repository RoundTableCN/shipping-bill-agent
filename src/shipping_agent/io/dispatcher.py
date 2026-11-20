"""Dispatch bytes/files to the right parser."""

from __future__ import annotations

from pathlib import Path

from ..models.bundle import DocumentBundle
from .context import ParseContext, ParseError
from .detect import MediaType, detect_media_type_bytes
from .text_normalize import safe_filename, sha256_bytes

IMAGE_TYPES = {
    MediaType.PNG,
    MediaType.JPEG,
    MediaType.TIFF,
    MediaType.GIF,
    MediaType.BMP,
    MediaType.WEBP,
}


def parse_file(
    path: str | Path,
    ctx: ParseContext,
    *,
    media_type: MediaType | None = None,
    depth: int = 0,
    data: bytes | None = None,
    file_name: str | None = None,
) -> DocumentBundle:
    path = Path(path)
    if depth > ctx.max_depth:
        raise ParseError("MAX_DEPTH", f"attachment recursion depth exceeded ({ctx.max_depth})")

    data = data if data is not None else path.read_bytes()
    if len(data) > ctx.max_bytes:
        raise ParseError("FILE_TOO_LARGE", f"{len(data)} bytes exceeds limit {ctx.max_bytes}")

    name = file_name or path.name
    media = media_type or detect_media_type_bytes(data, name)

    if media is MediaType.PDF:
        from .pdf_parser import parse_pdf

        return parse_pdf(path, ctx, data=data, file_name=name)
    if media is MediaType.EML:
        from .eml_parser import parse_eml

        return parse_eml(path, ctx, data=data, file_name=name, depth=depth)
    if media in (MediaType.XLSX, MediaType.XLS):
        from .excel_parser import parse_excel

        return parse_excel(path, ctx, data=data, file_name=name)
    if media in (MediaType.DOCX, MediaType.DOC):
        from .word_parser import parse_word

        return parse_word(path, ctx, data=data, file_name=name)
    if media in IMAGE_TYPES:
        from .image_parser import parse_image

        return parse_image(path, ctx, data=data, file_name=name)
    if media in (MediaType.HTML, MediaType.CSV, MediaType.TEXT):
        from .text_parser import parse_text

        return parse_text(path, ctx, data=data, file_name=name)

    raise ParseError("UNSUPPORTED_FORMAT", f"{name!r} -> {media.value}")


def parse_bytes(data: bytes, name: str, ctx: ParseContext, *, depth: int = 0) -> DocumentBundle:
    """Parse an in-memory attachment. The bytes are written to a run-scoped temp file."""
    media = detect_media_type_bytes(data, name)
    tmp_dir = ctx.run_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(data)
    tmp_path = tmp_dir / f"{digest[:12]}_{safe_filename(name)}"
    if not tmp_path.exists():
        tmp_path.write_bytes(data)
    return parse_file(tmp_path, ctx, media_type=media, depth=depth, data=data, file_name=name)


parse_path = parse_file

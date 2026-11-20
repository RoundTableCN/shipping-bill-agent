"""Format detection by magic bytes, with extension as a fallback."""

from __future__ import annotations

import io
import re
import zipfile
from enum import Enum
from pathlib import Path


class MediaType(str, Enum):
    PDF = "application/pdf"
    PNG = "image/png"
    JPEG = "image/jpeg"
    TIFF = "image/tiff"
    GIF = "image/gif"
    BMP = "image/bmp"
    WEBP = "image/webp"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    XLS = "application/vnd.ms-excel"
    DOC = "application/msword"
    EML = "message/rfc822"
    HTML = "text/html"
    CSV = "text/csv"
    TEXT = "text/plain"
    UNKNOWN = "application/octet-stream"


ZIP = b"PK\x03\x04"
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", MediaType.PNG),
    (b"\xff\xd8\xff", MediaType.JPEG),
    (b"II*\x00", MediaType.TIFF),
    (b"MM\x00*", MediaType.TIFF),
    (b"GIF87a", MediaType.GIF),
    (b"GIF89a", MediaType.GIF),
    (b"BM", MediaType.BMP),
)

EXTENSION_MAP = {
    ".pdf": MediaType.PDF,
    ".png": MediaType.PNG,
    ".jpg": MediaType.JPEG,
    ".jpeg": MediaType.JPEG,
    ".tif": MediaType.TIFF,
    ".tiff": MediaType.TIFF,
    ".gif": MediaType.GIF,
    ".bmp": MediaType.BMP,
    ".webp": MediaType.WEBP,
    ".xlsx": MediaType.XLSX,
    ".xlsm": MediaType.XLSX,
    ".docx": MediaType.DOCX,
    ".xls": MediaType.XLS,
    ".doc": MediaType.DOC,
    ".eml": MediaType.EML,
    ".html": MediaType.HTML,
    ".htm": MediaType.HTML,
    ".csv": MediaType.CSV,
    ".tsv": MediaType.CSV,
    ".txt": MediaType.TEXT,
}


def _zip_kind(data: bytes) -> MediaType:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        return MediaType.UNKNOWN
    if any(name.startswith("word/") for name in names):
        return MediaType.DOCX
    if any(name.startswith("xl/") for name in names):
        return MediaType.XLSX
    return MediaType.UNKNOWN


def _ole_kind(data: bytes) -> MediaType:
    if "WordDocument".encode("utf-16le") in data or b"WordDocument" in data:
        return MediaType.DOC
    if "Workbook".encode("utf-16le") in data or b"Workbook" in data:
        return MediaType.XLS
    if "Book".encode("utf-16le") in data or b"Book" in data:
        return MediaType.XLS
    return MediaType.UNKNOWN


def _looks_like_eml(data: bytes, name: str) -> bool:
    head = data[:8192].decode("latin-1", errors="ignore")
    headers = re.findall(
        r"(?im)^(From|To|Cc|Subject|Date|Message-ID|MIME-Version|Content-Type):",
        head,
    )
    if name.lower().endswith(".eml"):
        return True
    return len(set(h.lower() for h in headers)) >= 2 and (
        "MIME-Version" in head or "Message-ID" in head or "Content-Type" in head
    )


def _looks_like_text(data: bytes) -> bool:
    for encoding in ("utf-8", "gb18030"):
        try:
            text = data[:4096].decode(encoding)
        except UnicodeDecodeError:
            continue
        if not text:
            continue
        printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
        if printable / max(len(text), 1) > 0.85:
            return True
    return False


def detect_media_type_bytes(data: bytes, name: str = "") -> MediaType:
    name = name or ""
    lower = name.lower()

    if data.startswith(b"%PDF-"):
        return MediaType.PDF
    for magic, media_type in IMAGE_MAGIC:
        if data.startswith(magic):
            return media_type
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return MediaType.WEBP
    if data.startswith(ZIP):
        kind = _zip_kind(data)
        return kind if kind is not MediaType.UNKNOWN else MediaType.UNKNOWN
    if data.startswith(OLE):
        kind = _ole_kind(data)
        return kind if kind is not MediaType.UNKNOWN else MediaType.UNKNOWN
    if _looks_like_eml(data, name):
        return MediaType.EML

    head = data[:2048].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return MediaType.HTML

    suffix = Path(lower).suffix
    if suffix in EXTENSION_MAP:
        return EXTENSION_MAP[suffix]

    if suffix in (".csv", ".tsv"):
        return MediaType.CSV
    if _looks_like_text(data):
        return MediaType.TEXT
    return MediaType.UNKNOWN


def detect_media_type(path: str | Path, name: str | None = None) -> MediaType:
    path = Path(path)
    data = path.read_bytes()
    return detect_media_type_bytes(data, name or path.name)

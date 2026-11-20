"""Normalized document representation produced by all parsers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .base import StrictModel

TextKind = Literal[
    "title",
    "paragraph",
    "line",
    "table_cell",
    "header",
    "footer",
    "ocr_line",
    "signature",
]
AttachmentRole = Literal["billing", "reference", "media", "unknown"]
OcrMode = Literal["api", "degraded_local", "mock", "vision", "not_applicable"]


class Warning(StrictModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"


class SourceRef(StrictModel):
    file_id: str
    file_name: str
    media_type: str
    page: int | None = None
    block_id: str | None = None
    bbox: list[float] | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str | None = None


class TextBlock(StrictModel):
    block_id: str
    page: int | None = None
    kind: TextKind
    text: str
    bbox: list[float] | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    order: int = 0


class TableCell(StrictModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    col_span: int = Field(default=1, ge=1)
    text: str
    bbox: list[float] | None = None
    is_numeric: bool = False
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class TableBlock(StrictModel):
    table_id: str
    page: int | None = None
    bbox: list[float] | None = None
    cells: list[TableCell] = Field(default_factory=list)
    header_row_count: int = Field(default=1, ge=0)
    caption: str | None = None


class Attachment(StrictModel):
    file_name: str
    media_type: str
    size: int = Field(ge=0)
    sha256: str
    inline: bool = False
    content_id: str | None = None
    child: DocumentBundle | None = None
    role: AttachmentRole = "unknown"


class DocumentBundle(StrictModel):
    bundle_id: str
    source: SourceRef
    media_type: str
    meta: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""
    norm_text: str = ""
    blocks: list[TextBlock] = Field(default_factory=list)
    tables: list[TableBlock] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    ocr_raw: dict[str, Any] | None = None
    ocr_mode: OcrMode = "not_applicable"
    parse_quality: float = Field(default=1.0, ge=0.0, le=1.0)
    warnings: list[Warning] = Field(default_factory=list)


Attachment.model_rebuild()
DocumentBundle.model_rebuild()

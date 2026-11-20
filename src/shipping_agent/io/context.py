"""Parser context and errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

OcrModeSetting = Literal["mock", "local", "api"]


class ParseError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass
class ParseContext:
    run_dir: Path
    ocr_mode: OcrModeSetting = "mock"
    ocr_client: Any | None = None
    hosting: Any | None = None
    # Original public URL when the document was supplied via URL; the OCR API
    # can fetch it directly instead of requiring OCR_FILE_BASE_URL hosting.
    source_url: str | None = None
    # None = follow VISION_FALLBACK/env; False = deterministic offline mode.
    vision_fallback: bool | None = None
    max_depth: int = 5
    max_attachments: int = 50
    max_bytes: int = 200 * 1024 * 1024
    attachment_count: int = 0
    warnings: list[dict[str, str]] = field(default_factory=list)

    def attachment_dir(self) -> Path:
        path = self.run_dir / "attachments"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def warn(self, code: str, message: str, severity: str = "warning") -> None:
        self.warnings.append({"code": code, "message": message, "severity": severity})

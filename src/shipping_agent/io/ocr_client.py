"""OCR client.

The real response schema is not documented. Until ``scripts/ocr_probe.py``
has been run, only known paths are read and the raw response is preserved.
The default client is a mock so the offline pipeline works.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import requests

from .context import ParseError


@dataclass
class OcrResult:
    text: str = ""
    tables: list[list[list[str]]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    mode: str = "mock"
    pages: list[dict[str, Any]] = field(default_factory=list)
    structured: list[dict[str, Any]] = field(default_factory=list)
    file_type: str | None = None

    @classmethod
    def from_raw(cls, raw: Any, mode: str = "mock") -> "OcrResult":
        """Normalize a real/manual business-schema response."""
        if not isinstance(raw, dict):
            return cls(raw={"raw": raw}, mode=mode)
        items = _business_items(raw)
        return cls(
            text=_known_text(raw),
            tables=_known_tables(raw),
            raw=raw,
            mode=mode,
            structured=items,
            file_type=(
                str(items[0].get("fileType"))
                if items and items[0].get("fileType")
                else None
            ),
        )


class OcrClient(Protocol):
    def extract(self, path: Path, file_url: str | None = None) -> OcrResult:
        ...


class MockOcrClient:
    """Returns preconfigured results keyed by file sha256, or empty text."""

    def __init__(self, results: dict[str, OcrResult] | None = None):
        self.results = results or {}

    def extract(self, path: Path, file_url: str | None = None) -> OcrResult:
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        result = self.results.get(digest)
        if result is not None:
            return result
        return OcrResult(text="", raw={"mock": True}, mode="mock")


def _dig(data: Any, path: tuple[str, ...]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


_TEXT_PATHS = (
    ("data", "text"),
    ("data", "result", "text"),
    ("result", "text"),
    ("text",),
    ("data", "content"),
)
_TABLE_PATHS = (
    ("data", "tables"),
    ("data", "result", "tables"),
    ("result", "tables"),
    ("tables",),
)


_FIELD_LABELS = {
    "fileType": "FILE TYPE",
    "invoiceNumber": "INVOICE NO",
    "invoiceDate": "INVOICE DATE",
    "mblNumber": "MBL NO",
    "issuer": "ISSUER",
    "shipper": "SHIPPER",
    "consignee": "CONSIGNEE",
    "billTo": "BILL TO",
    "payer": "PAYER",
    "beneficiary": "BENEFICIARY",
    "currency": "CURRENCY",
    "totalAmount": "TOTAL",
    "itNumber": "IT NO",
    "pickupLocation": "PICKUP",
    "customsClearance": "CUSTOMS",
    "remark": "REMARK",
}


def _business_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    data = raw.get("data")
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _text_from_items(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        for key, label in _FIELD_LABELS.items():
            value = item.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _tables_from_items(items: list[dict[str, Any]]) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for item in items:
        charges = item.get("chargeList")
        if not isinstance(charges, list) or not charges:
            continue
        if not all(isinstance(charge, dict) for charge in charges):
            continue
        headers = list(
            dict.fromkeys(key for charge in charges for key in charge.keys())
        )
        if not headers:
            continue
        rows = [headers]
        for charge in charges:
            rows.append(
                ["" if charge.get(header) is None else str(charge.get(header)) for header in headers]
            )
        tables.append(rows)
    return tables


def _known_text(raw: dict[str, Any]) -> str:
    """Only read confirmed/known paths; never recursively collect strings."""
    for path in _TEXT_PATHS:
        value = _dig(raw, path)
        if isinstance(value, str):
            return value
    return _text_from_items(_business_items(raw))


def _known_tables(raw: dict[str, Any]) -> list[list[list[str]]]:
    for path in _TABLE_PATHS:
        value = _dig(raw, path)
        if isinstance(value, list):
            tables: list[list[list[str]]] = []
            for table in value:
                if isinstance(table, list):
                    tables.append(
                        [
                            ["" if cell is None else str(cell) for cell in row]
                            if isinstance(row, list)
                            else [str(row)]
                            for row in table
                        ]
                    )
            return tables
    return _tables_from_items(_business_items(raw))


class HttpOcrClient:
    """Minimal HTTP client. Capabilities are unknown until the probe is run."""

    def __init__(
        self,
        endpoint: str,
        *,
        task: str = "orderChange",
        task_type: str = "",
        timeout: tuple[int, int] = (10, 300),
        session: requests.Session | None = None,
        attempts: int = 3,
    ):
        self.endpoint = endpoint
        self.task = task
        self.task_type = task_type
        self.timeout = timeout
        self.session = session or requests.Session()
        self.attempts = max(1, attempts)

    def extract(self, path: Path, file_url: str | None = None) -> OcrResult:
        if not file_url:
            raise ParseError(
                "OCR_URL_REQUIRED",
                "OCR API requires a public URL; configure OCR_FILE_BASE_URL or use mock mode",
            )
        payload = {
            "file": file_url,
            "task": self.task,
            "callBack": "",
            "taskType": self.task_type,
        }
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                response = self.session.post(
                    self.endpoint, json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                try:
                    raw = response.json()
                except ValueError as exc:
                    raise ParseError(
                        "OCR_BAD_JSON", "OCR response is not valid JSON"
                    ) from exc
                return OcrResult.from_raw(raw, mode="api")
            except ParseError:
                raise
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    time.sleep(2 ** attempt)
                    continue
                raise ParseError("OCR_UNAVAILABLE", str(exc)) from exc

        raise ParseError("OCR_UNAVAILABLE", str(last_error))

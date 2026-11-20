"""Vision-model extractor for comparison with the OCR API.

Uses the configured Anthropic-compatible endpoint (the current environment
points it at DeepSeek, which supports image blocks).
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import fitz
import requests
from PIL import Image
from pydantic import Field

from .env import load_project_env
from .models.base import StrictModel
from .models.types import Currency, ISODate, Money

PROMPT = """你是航运账单识别器。请只输出一个 JSON 对象，不要 markdown，不要解释。
字段：
document_type, document_number, invoice_number, reference_no,
document_date(YYYY-MM-DD), document_date_raw(原文值), issuer, recipient,
payer, payee, beneficiary, currency(ISO 4217),
mbl_no, hbl_no, bl_no, waybill_no, booking_no, container_nos, seal_nos,
vessel, voyage, pol, pod, payment_term(PP/CC/COD),
payment_due_instruction(如 PAY IMMEDIATELY), payment_received(YES/NO/null),
release_type, release_status, shipment_operation_status,
charges: [{name, code, quantity, unit_price, amount, currency, payment_term,
           prepaid_collect, base, roe, payer_code, payee_code}],
subtotal, tax, total, confidence(0-1), notes:[]
无法确定填 null，不得虚构。金额用数字。日期保留原文和原始格式；如果
月/日顺序无法确认，document_date 填 null，并在 notes 中说明。
P/C、Rate、Amount、ROE 必须按列区分，不能把 Rate 当 Amount。
单据/费用/币种/编号必须来自图片。"""


class VisionCharge(StrictModel):
    name: str | None = None
    code: str | None = None
    quantity: Money | None = None
    unit_price: Money | None = None
    amount: Money | None = None
    currency: Currency | None = None
    payment_term: str | None = None
    prepaid_collect: str | None = None
    base: str | None = None
    roe: Money | None = None
    payer_code: str | None = None
    payee_code: str | None = None


class VisionExtraction(StrictModel):
    document_type: str | None = None
    document_number: str | None = None
    invoice_number: str | None = None
    reference_no: str | None = None
    document_date: ISODate | None = None
    document_date_raw: str | None = None
    issuer: str | None = None
    recipient: str | None = None
    payer: str | None = None
    payee: str | None = None
    beneficiary: str | None = None
    currency: Currency | None = None
    mbl_no: str | None = None
    hbl_no: str | None = None
    bl_no: str | None = None
    waybill_no: str | None = None
    booking_no: str | None = None
    container_nos: list[str] = Field(default_factory=list)
    seal_nos: list[str] = Field(default_factory=list)
    vessel: str | None = None
    voyage: str | None = None
    pol: str | None = None
    pod: str | None = None
    payment_term: str | None = None
    payment_due_instruction: str | None = None
    payment_received: str | None = None
    release_type: str | None = None
    release_status: str | None = None
    shipment_operation_status: str | None = None
    charges: list[VisionCharge] = Field(default_factory=list)
    subtotal: Money | None = None
    tax: Money | None = None
    total: Money | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: list[str] = Field(default_factory=list)


@dataclass
class VisionResult:
    data: VisionExtraction
    raw: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    elapsed: float = 0.0
    error: str | None = None


VisionProtocol = Literal["anthropic", "openai"]


def _first_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _infer_protocol(base_url: str) -> VisionProtocol:
    """Pick the wire format from the endpoint unless explicitly configured."""
    base = (base_url or "").lower()
    if "/anthropic" in base:
        return "anthropic"
    if (
        base.endswith("/v1")
        or base.endswith("/chat/completions")
        or "openai.com" in base
        or "deepseek.com/v1" in base
    ):
        return "openai"
    return "anthropic"


@dataclass
class VisionConfig:
    base_url: str
    model: str
    api_key: str
    timeout: int = 180
    protocol: VisionProtocol = "anthropic"

    @classmethod
    def from_env(cls) -> "VisionConfig":
        """Resolve the final image recognizer.

        Priority:
        1. Explicit ``VISION_*`` settings (including ``VISION_PROTOCOL``).
        2. The platform's Anthropic-compatible ``ANTHROPIC_*`` environment.
        3. The API saved by the first-run UI (Anthropic or OpenAI-compatible).
        4. The historical defaults, disabled because the key is empty.
        """
        load_project_env()

        explicit_base = _first_env("VISION_BASE_URL")
        explicit_model = _first_env("VISION_MODEL")
        explicit_key = _first_env("VISION_API_KEY")
        explicit_protocol = _first_env("VISION_PROTOCOL").lower()

        if explicit_base or explicit_model or explicit_key:
            base = (
                explicit_base
                or _first_env("ANTHROPIC_BASE_URL")
                or "https://api.deepseek.com/anthropic"
            )
            model = (
                explicit_model
                or _first_env("ANTHROPIC_MODEL")
                or "deepseek-flash"
            )
            key = explicit_key or _first_env(
                "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"
            )
            protocol: VisionProtocol = (
                explicit_protocol
                if explicit_protocol in {"anthropic", "openai"}
                else _infer_protocol(base)
            )
            return cls(
                base_url=base.rstrip("/"),
                model=model,
                api_key=key,
                protocol=protocol,
            )

        # The hosting platform exposes an image-capable DeepSeek model through
        # its Anthropic-compatible endpoint.
        platform_base = _first_env("ANTHROPIC_BASE_URL")
        platform_model = _first_env("ANTHROPIC_MODEL")
        platform_key = _first_env("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
        if platform_key:
            return cls(
                base_url=(
                    platform_base or "https://api.deepseek.com/anthropic"
                ).rstrip("/"),
                model=platform_model or "deepseek-flash",
                api_key=platform_key,
                protocol="anthropic",
            )

        # Reuse the first-run config.  OpenAI-compatible providers (including
        # DeepSeek) are attempted too; if the selected model is text-only the
        # extractor returns an actionable error instead of crashing the UI.
        try:
            from .ai_config import load_ai_config

            ai = load_ai_config()
        except Exception:
            ai = None
        if ai is not None and ai.enabled:
            if ai.provider == "anthropic":
                return cls(
                    base_url=(ai.base_url or "https://api.anthropic.com").rstrip("/"),
                    model=ai.model or "claude-sonnet-5-5",
                    api_key=ai.api_key,
                    protocol="anthropic",
                )
            if ai.provider in {"openai", "deepseek"}:
                default_base = (
                    "https://api.openai.com/v1"
                    if ai.provider == "openai"
                    else "https://api.deepseek.com"
                )
                default_model = (
                    "gpt-4o-mini" if ai.provider == "openai" else "deepseek-flash"
                )
                return cls(
                    base_url=(ai.base_url or default_base).rstrip("/"),
                    model=ai.model or default_model,
                    api_key=ai.api_key,
                    protocol="openai",
                )

        base = platform_base or "https://api.deepseek.com/anthropic"
        return cls(
            base_url=base.rstrip("/"),
            model=platform_model or "deepseek-flash",
            api_key="",
            protocol=explicit_protocol
            if explicit_protocol in {"anthropic", "openai"}
            else _infer_protocol(base),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def endpoint(self) -> str:
        base = self.base_url.rstrip("/")
        if self.protocol == "openai":
            if base.endswith("/chat/completions"):
                return base
            return base + "/chat/completions"
        if base.endswith("/v1/messages"):
            return base
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"


def _image_b64(path: Path) -> tuple[str, str]:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=85)
    return "image/jpeg", base64.b64encode(buffer.getvalue()).decode()


def _pdf_images(path: Path, max_pages: int = 3, dpi: int = 120) -> list[tuple[str, str]]:
    images: list[tuple[str, str]] = []
    doc = fitz.open(path)
    try:
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
            images.append(("image/jpeg", base64.b64encode(buffer.getvalue()).decode()))
    finally:
        doc.close()
    return images


def document_images(path: Path, max_pages: int = 3) -> list[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf_images(path, max_pages=max_pages)
    return [_image_b64(path)]


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _extract_text(raw: dict[str, Any]) -> str:
    """Read text from either Anthropic or OpenAI-compatible responses."""
    content = raw.get("content")
    if content is not None:
        return _content_text(content).strip()

    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                text = _content_text(message.get("content"))
                if text.strip():
                    return text.strip()
            text = _content_text(first.get("text"))
            if text.strip():
                return text.strip()

    output_text = raw.get("output_text")
    return output_text.strip() if isinstance(output_text, str) else ""


def _parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start:end + 1])
                return value if isinstance(value, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


class VisionExtractor:
    def __init__(self, config: VisionConfig | None = None):
        self.config = config or VisionConfig.from_env()

    def extract(self, path: str | Path, *, max_pages: int = 3) -> VisionResult:
        path = Path(path)
        if not self.config.enabled:
            return VisionResult(
                data=VisionExtraction(),
                model=self.config.model,
                error="vision model is not configured",
            )

        images = document_images(path, max_pages=max_pages)
        instruction = PROMPT + "\n\n请识别这些图片中的账单信息。"

        if self.config.protocol == "openai":
            content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
            for media_type, data in images:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{data}",
                        },
                    }
                )
            payload = {
                "model": self.config.model,
                "max_tokens": 16000,
                "temperature": 0,
                "messages": [{"role": "user", "content": content}],
            }
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "content-type": "application/json",
            }
        else:
            content = [{"type": "text", "text": instruction}]
            for media_type, data in images:
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    }
                )
            payload = {
                "model": self.config.model,
                "max_tokens": 16000,
                "temperature": 0,
                "messages": [{"role": "user", "content": content}],
            }
            headers = {
                "Authorization": f"Bearer {self.config.api_key}",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }

        started = time.time()
        response = None
        try:
            response = requests.post(
                self.config.endpoint(),
                headers=headers,
                json=payload,
                timeout=self.config.timeout,
            )
            response.raise_for_status()
            raw = response.json()
        except Exception as exc:  # noqa: BLE001
            detail = ""
            if response is not None:
                try:
                    detail = f" | {response.text[:500]}"
                except Exception:
                    detail = ""
            return VisionResult(
                data=VisionExtraction(),
                model=self.config.model,
                elapsed=time.time() - started,
                error=f"{type(exc).__name__}: {exc}{detail}",
            )

        text = _extract_text(raw)
        parsed = _parse_json(text)
        if not parsed:
            return VisionResult(
                data=VisionExtraction(),
                raw=raw,
                model=self.config.model,
                elapsed=time.time() - started,
                error=(
                    "no JSON in response; "
                    f"stop_reason={raw.get('stop_reason')}, "
                    f"text_len={len(text)}"
                ),
            )
        for list_key in ("container_nos", "seal_nos", "charges", "notes"):
            if parsed.get(list_key) is None:
                parsed[list_key] = []
        try:
            data = VisionExtraction.model_validate(parsed)
        except Exception as exc:  # noqa: BLE001
            return VisionResult(
                data=VisionExtraction(),
                raw=raw,
                model=self.config.model,
                elapsed=time.time() - started,
                error=f"schema: {exc}",
            )

        return VisionResult(
            data=data,
            raw=raw,
            model=self.config.model,
            elapsed=time.time() - started,
        )

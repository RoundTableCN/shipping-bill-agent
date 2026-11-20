"""Build OCR client and hosting adapter from environment configuration."""

from __future__ import annotations

import os

from ..env import load_project_env
from .file_hosting import LocalHttpHosting
from .ocr_client import HttpOcrClient, MockOcrClient

DEFAULT_ENDPOINT = "https://gateway.pltplt.com/ai/process"


def build_ocr_client(ocr_mode: str):
    load_project_env()
    if ocr_mode == "mock":
        return MockOcrClient()
    if ocr_mode == "local":
        return None
    if ocr_mode == "api":
        return HttpOcrClient(
            os.getenv("OCR_ENDPOINT", DEFAULT_ENDPOINT),
            task=os.getenv("OCR_TASK", "orderChange"),
            task_type=os.getenv("OCR_TASK_TYPE", ""),
        )
    raise ValueError(f"unknown OCR mode: {ocr_mode!r}")


def build_url_ocr_client():
    """OCR client for public URL input: one attempt, 60s by default.

    URL inputs should not wait for three long OCR retries before local/vision
    fallback.  Configure with ``URL_OCR_TIMEOUT`` if a different deadline is
    required.
    """
    load_project_env()
    try:
        read_timeout = max(1, int(os.getenv("URL_OCR_TIMEOUT", "60")))
    except ValueError:
        read_timeout = 60
    return HttpOcrClient(
        os.getenv("OCR_ENDPOINT", DEFAULT_ENDPOINT),
        task=os.getenv("OCR_TASK", "orderChange"),
        task_type=os.getenv("OCR_TASK_TYPE", ""),
        timeout=(min(10, read_timeout), read_timeout),
        attempts=1,
    )


def build_hosting(ocr_mode: str = "api"):
    load_project_env()
    if ocr_mode != "api":
        return None
    base_url = os.getenv("OCR_FILE_BASE_URL", "").strip()
    if not base_url:
        return None
    serve_dir = os.getenv("OCR_SERVE_DIR", "out/ocr_serve")
    return LocalHttpHosting(base_url, serve_dir)


def ocr_setup_warning(ocr_mode: str) -> str | None:
    if ocr_mode != "api":
        return None
    missing = []
    if not os.getenv("OCR_FILE_BASE_URL"):
        missing.append("OCR_FILE_BASE_URL")
    if missing:
        return (
            "OCR api mode is missing " + ", ".join(missing)
            + "; scanned pages/images will not be uploaded to the OCR server."
        )
    return None

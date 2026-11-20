"""Public-URL input regression tests (local HTTP server, no internet)."""

from __future__ import annotations

import json
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import fitz
import pytest
from PIL import Image

import shipping_agent.vision_extractor as vision_module
from shipping_agent.build_cli import main as build_main
from shipping_agent.io.context import ParseContext, ParseError
from shipping_agent.io.image_parser import parse_image
from shipping_agent.io.ocr_client import OcrResult
from shipping_agent.io.ocr_factory import build_url_ocr_client
from shipping_agent.io.pdf_parser import parse_pdf
from shipping_agent.io.url_fetcher import download_url, is_url, split_urls
from shipping_agent.ui_service import analyze_url
from shipping_agent.vision_extractor import VisionCharge, VisionExtraction, VisionResult

ROOT = Path(__file__).resolve().parents[1]
HAS_SAMPLE_IMAGE = (ROOT / "data" / "samples" / "sample_carrier_invoice.png").exists()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: ANN001
        return


@pytest.fixture
def http_server(tmp_path: Path):
    serve_dir = tmp_path / "serve"
    serve_dir.mkdir()
    shutil.copy2(
        ROOT / "data" / "fixtures" / "formal_invoice.pdf",
        serve_dir / "formal_invoice.pdf",
    )
    Image.new("RGB", (32, 20), "white").save(serve_dir / "sample.png")

    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(serve_dir), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", serve_dir
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_is_url_accepts_http_and_rejects_local_paths():
    assert is_url("https://example.com/a.pdf")
    assert is_url("http://example.com/a.pdf")
    assert not is_url("data/fixtures/formal_invoice.pdf")
    assert not is_url("file:///tmp/a.pdf")


def test_split_urls_supports_multiple_lines():
    urls = split_urls(
        "https://example.com/a.pdf\n\n"
        "  https://example.com/b.png  \n"
        "# comment\n"
        "https://example.com/a.pdf\n"
    )
    assert urls == [
        "https://example.com/a.pdf",
        "https://example.com/b.png",
    ]

    with pytest.raises(ParseError) as invalid:
        split_urls("https://example.com/a.pdf\nfile:///tmp/b.pdf")
    assert invalid.value.code == "URL_INVALID"


def test_url_ocr_client_has_60s_single_attempt():
    client = build_url_ocr_client()
    assert client.timeout == (10, 60)
    assert client.attempts == 1


def test_download_url_saves_file(http_server, tmp_path: Path):
    base, serve_dir = http_server

    path = download_url(f"{base}/formal_invoice.pdf", tmp_path / "downloads")

    assert path.name == "formal_invoice.pdf"
    assert path.read_bytes() == (serve_dir / "formal_invoice.pdf").read_bytes()


def test_download_url_errors(http_server, tmp_path: Path):
    base, _ = http_server

    with pytest.raises(ParseError) as invalid:
        download_url("file:///tmp/a.pdf", tmp_path / "downloads")
    assert invalid.value.code == "URL_INVALID"

    with pytest.raises(ParseError) as missing:
        download_url(f"{base}/missing.pdf", tmp_path / "downloads")
    assert missing.value.code == "URL_DOWNLOAD_FAILED"

    with pytest.raises(ParseError) as large:
        download_url(
            f"{base}/formal_invoice.pdf",
            tmp_path / "downloads",
            max_bytes=10,
        )
    assert large.value.code == "URL_TOO_LARGE"


def test_analyze_url_runs_the_normal_pipeline(http_server, monkeypatch):
    base, _ = http_server
    monkeypatch.setattr(
        "shipping_agent.ui_service.build_url_ocr_client",
        lambda: RecordingOcr(),
    )

    analysis = analyze_url(
        f"{base}/formal_invoice.pdf",
        existing_bills=ROOT / "data" / "fixtures" / "existing_bills.json",
        accounting_entity="IMPORTER BETA (SHANGHAI)",
        ocr_mode="local",
    )

    assert len(analysis.pipeline.records) == 3
    assert all(
        record.operation == "NO_CHANGE" for record in analysis.pipeline.records
    )


def test_build_cli_accepts_url(http_server, tmp_path: Path, monkeypatch):
    base, _ = http_server
    out = tmp_path / "out"
    monkeypatch.setattr(
        "shipping_agent.build_cli.build_url_ocr_client",
        lambda: RecordingOcr(),
    )

    code = build_main(
        [
            "--url",
            f"{base}/formal_invoice.pdf",
            "--out",
            str(out),
            "--existing-bills",
            str(ROOT / "data" / "fixtures" / "existing_bills.json"),
            "--accounting-entity",
            "IMPORTER BETA (SHANGHAI)",
            "--ocr-mode",
            "local",
            "--output-mode",
            "full",
            "--quiet",
        ]
    )

    assert code == 0
    data = json.loads((out / "formal_invoice.json").read_text(encoding="utf-8"))
    assert len(data) == 3
    assert all(record["operation"] == "NO_CHANGE" for record in data)


class RecordingOcr:
    def __init__(self, result: OcrResult | None = None, error: Exception | None = None):
        self.result = result or OcrResult(text="", tables=[], raw={}, mode="api")
        self.error = error
        self.calls: list[tuple[Path, str | None]] = []

    def extract(self, path: Path, file_url: str | None = None) -> OcrResult:
        self.calls.append((Path(path), file_url))
        if self.error is not None:
            raise self.error
        return self.result


class FakeVision:
    def extract(self, path: Path, *, max_pages: int = 3) -> VisionResult:
        return VisionResult(
            data=VisionExtraction(
                document_type="Invoice",
                reference_no="URL-VISION-1",
                currency="USD",
                charges=[VisionCharge(name="WHARFAGE", amount="21.90", currency="USD")],
                total="21.90",
            ),
            model="fake-vision",
        )


@pytest.mark.skipif(not HAS_SAMPLE_IMAGE, reason="sample image omitted")
def test_url_image_uses_ocr_api_url_first(tmp_path: Path):
    image = ROOT / "data" / "samples" / "sample_carrier_invoice.png"
    client = RecordingOcr(
        OcrResult(
            text="INVOICE NO: URL-OCR-1\nTOTAL: 21.90 USD",
            tables=[],
            raw={},
            mode="api",
        )
    )
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=None,
        source_url="https://public.example/invoice.png",
    )

    bundle = parse_image(image, ctx)

    assert client.calls[0][1] == "https://public.example/invoice.png"
    assert bundle.ocr_mode == "api"
    assert "URL-OCR-1" in bundle.raw_text


def test_url_pdf_uses_ocr_api_url_first(tmp_path: Path):
    pdf = ROOT / "data" / "fixtures" / "formal_invoice.pdf"
    client = RecordingOcr(
        OcrResult(
            text="INVOICE NO: URL-PDF-1\nTOTAL: 65.00 USD",
            tables=[],
            raw={},
            mode="api",
        )
    )
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=None,
        source_url="https://public.example/invoice.pdf",
    )

    bundle = parse_pdf(pdf, ctx)

    assert client.calls[0][1] == "https://public.example/invoice.pdf"
    assert bundle.ocr_mode == "api"
    assert "URL-PDF-1" in bundle.raw_text


def test_url_pdf_falls_back_to_local_when_ocr_empty(tmp_path: Path):
    pdf = ROOT / "data" / "fixtures" / "formal_invoice.pdf"
    client = RecordingOcr(OcrResult(text="", tables=[], raw={}, mode="api"))
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=None,
        source_url="https://public.example/invoice.pdf",
    )

    bundle = parse_pdf(pdf, ctx)

    assert bundle.meta["url_ocr_attempted"] is True
    assert any(w.code == "OCR_EMPTY" for w in bundle.warnings)
    assert not any(w.code == "OCR_URL_REQUIRED" for w in bundle.warnings)
    assert "INVOICE" in bundle.raw_text.upper()


@pytest.mark.skipif(not HAS_SAMPLE_IMAGE, reason="sample image omitted")
def test_url_scanned_pdf_falls_back_to_vision(monkeypatch, tmp_path: Path):
    image = ROOT / "data" / "samples" / "sample_carrier_invoice.png"
    scanned = tmp_path / "scanned.pdf"
    doc = fitz.open()
    with Image.open(image) as source:
        width, height = source.size
    page = doc.new_page(width=width, height=height)
    page.insert_image(page.rect, filename=str(image))
    doc.save(str(scanned))
    doc.close()

    monkeypatch.setenv("VISION_FALLBACK", "1")
    monkeypatch.setenv("VISION_BASE_URL", "https://vision.example/anthropic")
    monkeypatch.setenv("VISION_MODEL", "fake-vision")
    monkeypatch.setenv("VISION_API_KEY", "test-key")
    monkeypatch.setattr(vision_module, "VisionExtractor", lambda: FakeVision())
    client = RecordingOcr(OcrResult(text="", tables=[], raw={}, mode="api"))
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=None,
        source_url="https://public.example/scanned.pdf",
    )

    bundle = parse_pdf(scanned, ctx)

    assert bundle.ocr_mode == "vision"
    assert bundle.meta["vision_fallback"] is True
    assert "URL-VISION-1" in bundle.raw_text


@pytest.mark.skipif(not HAS_SAMPLE_IMAGE, reason="sample image omitted")
def test_url_image_falls_back_to_vision_when_ocr_fails(
    monkeypatch, tmp_path: Path
):
    image = ROOT / "data" / "samples" / "sample_carrier_invoice.png"
    monkeypatch.setenv("VISION_FALLBACK", "1")
    monkeypatch.setenv("VISION_BASE_URL", "https://vision.example/anthropic")
    monkeypatch.setenv("VISION_MODEL", "fake-vision")
    monkeypatch.setenv("VISION_API_KEY", "test-key")
    monkeypatch.setattr(vision_module, "VisionExtractor", lambda: FakeVision())
    client = RecordingOcr(error=RuntimeError("OCR gateway unavailable"))
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=None,
        source_url="https://public.example/invoice.png",
    )

    bundle = parse_image(image, ctx)

    assert bundle.ocr_mode == "vision"
    assert bundle.meta["vision_fallback"] is True
    assert any(w.code == "OCR_FAILED" for w in bundle.warnings)
    assert any(w.code == "VISION_FALLBACK" for w in bundle.warnings)

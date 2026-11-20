from pathlib import Path

import fitz
import pytest

from shipping_agent.candidates import build_candidates
from shipping_agent.io.context import ParseContext, ParseError
from shipping_agent.io.file_hosting import LocalHttpHosting
from shipping_agent.io.image_parser import parse_image
from shipping_agent.io.ocr_client import HttpOcrClient, OcrResult
from shipping_agent.io.ocr_factory import build_hosting, build_ocr_client
from shipping_agent.io.pdf_parser import parse_pdf


class FakeHosting:
    def url_for(self, path: Path) -> str:
        return f"https://public.example/{Path(path).name}"


class FakeClient:
    def __init__(self, result: OcrResult):
        self.result = result
        self.calls: list[tuple[Path, str | None]] = []

    def extract(self, path: Path, file_url: str | None = None) -> OcrResult:
        self.calls.append((Path(path), file_url))
        return self.result


def test_image_api_wiring(samples_dir: Path, tmp_path: Path):
    text = "WHARFAGE ADMINISTRATION FEE USD 5.00\nWHARFAGE USD 21.90"
    client = FakeClient(
        OcrResult(text=text, raw={"data": {"text": text}}, mode="api")
    )
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=FakeHosting(),
    )

    bundle = parse_image(samples_dir / "sample_carrier_invoice.png", ctx)

    assert bundle.ocr_mode == "api"
    assert "WHARFAGE" in bundle.raw_text
    assert bundle.meta["ocr_input"] == "pdf"
    assert client.calls[0][0].suffix == ".pdf"
    assert client.calls[0][1].startswith("https://")
    assert client.calls[0][1].endswith(".pdf")
    assert len(build_candidates(bundle)) == 2


def test_image_api_requires_public_url(
    monkeypatch, samples_dir: Path, tmp_path: Path
):
    monkeypatch.setenv("VISION_FALLBACK", "0")
    client = FakeClient(OcrResult(text="x", mode="api"))
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=None,
    )

    with pytest.raises(ParseError) as exc:
        parse_image(samples_dir / "sample_carrier_invoice.png", ctx)
    assert exc.value.code == "OCR_URL_REQUIRED"


def test_scanned_pdf_uses_ocr(tmp_path: Path):
    pdf_path = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(pdf_path)
    doc.close()

    text = "HANDLING CHARGE USD 65.00"
    client = FakeClient(
        OcrResult(text=text, raw={"data": {"text": text}}, mode="api")
    )
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=FakeHosting(),
    )

    bundle = parse_pdf(pdf_path, ctx)

    assert bundle.ocr_mode == "api"
    assert "HANDLING CHARGE" in bundle.raw_text
    assert bundle.meta["ocr_pages"] == [0]
    assert len(build_candidates(bundle)) == 1
    assert client.calls[0][1].startswith("https://")


def test_text_pdf_ocr_first_falls_back_to_local(samples_dir: Path, tmp_path: Path):
    client = FakeClient(OcrResult(text="", mode="api"))
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=FakeHosting(),
    )

    bundle = parse_pdf(samples_dir / "sample_general_notice.pdf", ctx)

    assert client.calls, "OCR should be attempted first in api mode"
    assert bundle.ocr_mode == "degraded_local"
    assert bundle.meta["ocr_attempts"]
    assert bundle.meta["ocr_pages"] == []
    assert "GENERAL NOTICE" in bundle.raw_text
    assert len(build_candidates(bundle)) == 1


def test_text_pdf_ocr_first_uses_ocr_when_it_returns_text(
    samples_dir: Path, tmp_path: Path
):
    client = FakeClient(
        OcrResult(text="OCR HANDLING CHARGE USD 1.00", raw={}, mode="api")
    )
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=client,
        hosting=FakeHosting(),
    )

    bundle = parse_pdf(samples_dir / "sample_general_notice.pdf", ctx)

    assert bundle.ocr_mode == "api"
    assert "OCR HANDLING CHARGE" in bundle.raw_text
    assert "GENERAL NOTICE" not in bundle.raw_text
    assert bundle.meta["ocr_pages"] == list(range(bundle.meta["page_count"]))


def test_ocr_factory_and_local_hosting(monkeypatch, samples_dir: Path, tmp_path: Path):
    serve_dir = tmp_path / "serve"
    monkeypatch.setenv("OCR_FILE_BASE_URL", "https://public.example")
    monkeypatch.setenv("OCR_SERVE_DIR", str(serve_dir))
    monkeypatch.setenv("OCR_ENDPOINT", "https://example.invalid/ocr")

    client = build_ocr_client("api")
    hosting = build_hosting("api")

    assert isinstance(client, HttpOcrClient)
    assert isinstance(hosting, LocalHttpHosting)

    url = hosting.url_for(samples_dir / "sample_carrier_invoice.png")
    assert url.startswith("https://public.example/")
    assert url.endswith(".png")
    assert any(serve_dir.iterdir())

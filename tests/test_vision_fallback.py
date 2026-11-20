"""Image OCR empty -> optional vision-model fallback."""

from __future__ import annotations

from pathlib import Path

import shipping_agent.vision_extractor as vision_module
from shipping_agent.ai_config import AIConfig, save_ai_config
from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.candidates import build_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.image_parser import parse_image
from shipping_agent.io.ocr_client import OcrResult
from shipping_agent.vision_extractor import VisionCharge, VisionExtraction, VisionResult


class FakeHosting:
    def url_for(self, path: Path) -> str:
        return f"https://public.example/{Path(path).name}"


class FakeClient:
    def extract(self, path: Path, file_url: str | None = None) -> OcrResult:
        return OcrResult(text="", tables=[], raw={}, mode="api")


class FakeVision:
    def extract(self, path: Path, *, max_pages: int = 3) -> VisionResult:
        return VisionResult(
            data=VisionExtraction(
                document_type="Invoice",
                reference_no="INV-DEMO-001",
                document_date="2025-10-03",
                issuer="CARRIER",
                recipient="EXAMPLE FORWARDING INC.",
                currency="USD",
                charges=[
                    VisionCharge(
                        name="WHARFAGE ADMINISTRATION FEE",
                        amount="5.00",
                        currency="USD",
                    ),
                    VisionCharge(
                        name="WHARFAGE",
                        amount="21.90",
                        currency="USD",
                    ),
                ],
                total="26.90",
            ),
            model="fake-vision",
        )


def _enable_fake_vision(monkeypatch) -> None:
    monkeypatch.setenv("VISION_FALLBACK", "1")
    monkeypatch.setenv("VISION_BASE_URL", "https://vision.example/anthropic")
    monkeypatch.setenv("VISION_MODEL", "fake-vision")
    monkeypatch.setenv("VISION_API_KEY", "test-key")
    monkeypatch.setattr(vision_module, "VisionExtractor", lambda: FakeVision())


def test_image_vision_fallback_without_ocr_url(
    monkeypatch, samples_dir: Path, tmp_path: Path
):
    _enable_fake_vision(monkeypatch)
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=FakeClient(),
        hosting=None,
    )

    bundle = parse_image(samples_dir / "sample_carrier_invoice.png", ctx)

    assert bundle.ocr_mode == "vision"
    assert len(build_candidates(bundle)) == 2


def test_image_vision_fallback(monkeypatch, samples_dir: Path, tmp_path: Path):
    _enable_fake_vision(monkeypatch)
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=FakeClient(),
        hosting=FakeHosting(),
    )

    bundle = parse_image(samples_dir / "sample_carrier_invoice.png", ctx)

    assert bundle.ocr_mode == "vision"
    assert bundle.meta["vision_fallback"] is True
    assert "REFERENCE NO: INV-DEMO-001" in bundle.raw_text
    assert any(w.code == "VISION_FALLBACK" for w in bundle.warnings)
    candidates = build_candidates(bundle)
    assert len(candidates) == 2
    assert [c.amount_raw for c in candidates] == ["5.00", "21.90"]

    result = process_bundle(bundle, candidates, PipelineConfig())
    assert result.records
    assert all(record.operation == "PENDING_REVIEW" for record in result.records)
    assert any(
        "E_VISION_FALLBACK_REVIEW" in error
        for record in result.records
        for error in (record.audit_trail.validation.errors if record.audit_trail.validation else [])
    )


def test_image_vision_fallback_after_mock_or_local(
    monkeypatch, samples_dir: Path, tmp_path: Path
):
    _enable_fake_vision(monkeypatch)
    for mode in ("mock", "local"):
        ctx = ParseContext(
            run_dir=tmp_path / mode,
            ocr_mode=mode,
            ocr_client=FakeClient(),
            hosting=None,
        )
        bundle = parse_image(samples_dir / "sample_carrier_invoice.png", ctx)
        assert bundle.ocr_mode == "vision", mode
        assert len(build_candidates(bundle)) == 2, mode


def test_saved_api_without_ocr_url_uses_vision_fallback(
    monkeypatch, samples_dir: Path, tmp_path: Path
):
    """The saved first-run API should avoid the OCR_URL_REQUIRED crash."""
    for name in (
        "VISION_BASE_URL",
        "VISION_MODEL",
        "VISION_API_KEY",
        "VISION_PROTOCOL",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "LLM_API_KEY",
        "LLM_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AI_CONFIG_PATH", str(tmp_path / "ai_config.json"))
    save_ai_config(
        AIConfig(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            api_key="test-key",
            source="custom",
        )
    )
    monkeypatch.setattr(vision_module, "VisionExtractor", lambda: FakeVision())
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=FakeClient(),
        hosting=None,
    )

    bundle = parse_image(samples_dir / "sample_carrier_invoice.png", ctx)

    assert bundle.ocr_mode == "vision"
    assert len(build_candidates(bundle)) == 2

from pathlib import Path

import pytest

from shipping_agent.candidates import build_candidates
from shipping_agent.io.context import ParseContext, ParseError
from shipping_agent.io.image_parser import parse_image
from shipping_agent.io.ocr_client import HttpOcrClient, MockOcrClient, OcrResult
from shipping_agent.io.text_normalize import sha256_bytes


def test_mock_ocr_image_candidates(samples_dir: Path, tmp_path: Path):
    path = samples_dir / "sample_carrier_invoice.png"
    digest = sha256_bytes(path.read_bytes())
    text = (
        "WHARFAGE ADMINISTRATION FEE USD 5.00\n"
        "WHARFAGE USD 21.90\n"
        "TOTAL USD 26.90"
    )
    result = OcrResult(text=text, raw={"data": {"text": text}}, mode="mock")
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="mock",
        ocr_client=MockOcrClient({digest: result}),
    )

    bundle = parse_image(path, ctx, file_name=path.name)
    assert bundle.ocr_mode == "mock"
    assert "WHARFAGE" in bundle.raw_text

    candidates = build_candidates(bundle)
    assert len(candidates) == 2
    assert [c.charge_raw for c in candidates] == [
        "WHARFAGE ADMINISTRATION FEE",
        "WHARFAGE",
    ]
    assert [c.currency_raw for c in candidates] == ["USD", "USD"]


def test_http_ocr_requires_public_url(samples_dir: Path):
    client = HttpOcrClient("https://example.invalid/ocr")
    with pytest.raises(ParseError) as exc:
        client.extract(samples_dir / "sample_carrier_invoice.png", file_url=None)
    assert exc.value.code == "OCR_URL_REQUIRED"


def test_http_ocr_reads_known_text_path(samples_dir: Path):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": 200, "message": "success", "data": {"text": "INVOICE INV-DEMO-001"}}

    class FakeSession:
        def post(self, url, json, timeout):
            assert json["file"] == "https://public.example/x.png"
            assert json["task"] == "orderChange"
            return FakeResponse()

    client = HttpOcrClient("https://example.invalid/ocr", session=FakeSession())
    result = client.extract(
        samples_dir / "sample_carrier_invoice.png",
        file_url="https://public.example/x.png",
    )
    assert result.mode == "api"
    assert result.text == "INVOICE INV-DEMO-001"
    assert result.raw["code"] == 200


def test_http_ocr_business_schema(samples_dir: Path):
    raw = {
        "success": True,
        "message": "文档处理成功",
        "error_code": None,
        "task_id": None,
        "data": {
            "orderType": "None",
            "pages_split": [[0, 3]],
            "list": [
                {
                    "fileType": "DEBIT-NOTE",
                    "mblNumber": "MAEU888777666",
                    "shipper": "SHENZHEN XUELANG",
                    "consignee": "EXAMPLE CONSIGNEE LLC",
                    "invoiceNumber": "DN-DEMO-002",
                    "chargeList": [
                        {
                            "chargeName": "Handling Charge",
                            "amount": "65.00",
                            "currency": "USD",
                            "paymentTerm": "PP",
                        }
                    ],
                    "ctrList": [],
                    "page_index": [0, 3],
                }
            ],
        },
    }

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return raw

    class FakeSession:
        def post(self, url, json, timeout):
            return FakeResponse()

    client = HttpOcrClient("https://example.invalid/ocr", session=FakeSession())
    result = client.extract(
        samples_dir / "sample_carrier_invoice.png",
        file_url="https://public.example/x.png",
    )

    assert result.mode == "api"
    assert result.file_type == "DEBIT-NOTE"
    assert len(result.structured) == 1
    assert "FILE TYPE: DEBIT-NOTE" in result.text
    assert "MBL NO: MAEU888777666" in result.text
    assert result.tables[0][0] == [
        "chargeName",
        "amount",
        "currency",
        "paymentTerm",
    ]
    assert result.tables[0][1] == ["Handling Charge", "65.00", "USD", "PP"]


def test_business_charge_table_feeds_candidates(samples_dir: Path, tmp_path: Path):
    from shipping_agent.candidates import build_candidates
    from shipping_agent.io.context import ParseContext
    from shipping_agent.io.image_parser import parse_image

    class FakeClient:
        def extract(self, path, file_url=None):
            return OcrResult(
                text="FILE TYPE: DEBIT-NOTE",
                tables=[
                    [
                        ["chargeName", "amount", "currency", "paymentTerm"],
                        ["Handling Charge", "65.00", "USD", "PP"],
                    ]
                ],
                mode="api",
                structured=[{"fileType": "DEBIT-NOTE"}],
                file_type="DEBIT-NOTE",
            )

    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="api",
        ocr_client=FakeClient(),
        hosting=type("H", (), {"url_for": lambda self, path: "https://x/y.png"})(),
    )
    bundle = parse_image(samples_dir / "sample_carrier_invoice.png", ctx)
    candidates = build_candidates(bundle)

    assert len(candidates) == 1
    assert candidates[0].charge_raw == "Handling Charge"
    assert candidates[0].amount_raw == "65.00"
    assert candidates[0].currency_raw == "USD"

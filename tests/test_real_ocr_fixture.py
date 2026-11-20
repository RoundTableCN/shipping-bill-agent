import json
from decimal import Decimal
from pathlib import Path

from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.candidates import build_candidates, collect_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.io.ocr_client import MockOcrClient, OcrResult
from shipping_agent.io.text_normalize import sha256_bytes


def test_real_ocr_response_parses_and_feeds_candidates(
    fixtures_dir: Path, samples_dir: Path, tmp_path: Path
):
    raw = json.loads((fixtures_dir / "ocr_real_CARRIER.json").read_text(encoding="utf-8"))
    ocr = OcrResult.from_raw(raw, mode="mock")

    assert ocr.file_type == "PAI-CARRIER-NOTICE"
    assert "INVOICE NO: INV-DEMO-001" in ocr.text
    assert "MBL NO: CGTSE260888888" in ocr.text
    assert len(ocr.tables) == 1
    assert ocr.tables[0][0] == ["chargeItem", "amount", "chargeCtr"]
    assert ocr.tables[0][1] == ["WHARFAGE ADMINISTRATION FEE", "5.00", ""]

    image = samples_dir / "sample_carrier_invoice.png"
    client = MockOcrClient({sha256_bytes(image.read_bytes()): ocr})
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="mock",
        ocr_client=client,
    )

    bundle = parse_file(image, ctx)
    assert bundle.meta["ocr_file_type"] == "PAI-CARRIER-NOTICE"
    candidates = collect_candidates(bundle)
    assert len(candidates) == 2
    assert [candidate.charge_raw for candidate in candidates] == [
        "WHARFAGE ADMINISTRATION FEE",
        "WHARFAGE",
    ]
    assert [candidate.amount_raw for candidate in candidates] == ["5.00", "21.90"]
    assert [candidate.currency_raw for candidate in candidates] == [None, None]

    result = process_bundle(
        bundle,
        candidates,
        PipelineConfig(accounting_entity="EXAMPLE FORWARDING INC."),
    )
    assert [record.operation for record in result.records] == [
        "PENDING_REVIEW",
        "PENDING_REVIEW",
    ]
    assert [record.charge_details.amount for record in result.records] == [
        Decimal("5.00"),
        Decimal("21.90"),
    ]
    assert all(
        any("W_CURRENCY_MISSING" in warning for warning in record.audit_trail.validation.warnings)
        for record in result.records
    )

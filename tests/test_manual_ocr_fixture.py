import json
from decimal import Decimal
from pathlib import Path

from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.candidates import collect_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.io.ocr_client import MockOcrClient, OcrResult
from shipping_agent.io.text_normalize import sha256_bytes


def test_manual_ocr_fixture_runs_downstream(
    fixtures_dir: Path, samples_dir: Path, tmp_path: Path
):
    raw = json.loads((fixtures_dir / "ocr_mock_CARRIER.json").read_text(encoding="utf-8"))
    ocr = OcrResult.from_raw(raw, mode="mock")
    assert ocr.file_type == "INVOICE"
    assert "INVOICE NO: INV-DEMO-001" in ocr.text
    assert len(ocr.tables) == 1

    image = samples_dir / "sample_carrier_invoice.png"
    client = MockOcrClient({sha256_bytes(image.read_bytes()): ocr})
    ctx = ParseContext(
        run_dir=tmp_path / "run",
        ocr_mode="mock",
        ocr_client=client,
    )

    bundle = parse_file(image, ctx)
    candidates = collect_candidates(bundle)
    assert len(candidates) == 2

    result = process_bundle(
        bundle,
        candidates,
        PipelineConfig(
            existing_bills=str(fixtures_dir / "existing_bills.json"),
            accounting_entity="EXAMPLE FORWARDING INC.",
        ),
    )

    assert [record.operation for record in result.records] == ["CREATE", "CREATE"]
    assert [record.charge_details.charge_item for record in result.records] == [
        "Wharfage Administration Fee",
        "Wharfage",
    ]
    assert [record.charge_details.amount for record in result.records] == [
        Decimal("5.00"),
        Decimal("21.90"),
    ]
    assert all(
        record.financial_attributes.posting_type == "AP"
        for record in result.records
    )
    assert all(
        record.audit_trail.validation.passed for record in result.records
    )

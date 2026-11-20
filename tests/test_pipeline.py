import json
from pathlib import Path

from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.candidates import collect_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.output.serializer import REQUIRED_STRICT_KEYS, write_output


def _process(path: Path, fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    return process_bundle(
        bundle,
        candidates,
        PipelineConfig(existing_bills=str(fixtures_dir / "existing_bills.json")),
    )


def test_strict_output_from_pipeline(fixtures_dir: Path, tmp_path: Path):
    result = _process(
        fixtures_dir / "formal_invoice_create.pdf", fixtures_dir, tmp_path
    )
    out = tmp_path / "out.json"
    audit = tmp_path / "audit.json"

    write_output(result.records, out, mode="strict", audit_path=audit)
    data = json.loads(out.read_text(encoding="utf-8"))

    assert set(data[0].keys()) == set(REQUIRED_STRICT_KEYS)
    assert set(data[0]["audit_trail"].keys()) == {"ai_reasoning"}
    assert data[0]["operation"] == "CREATE"
    assert data[0]["charge_details"]["amount"] == 100.0
    assert audit.exists()


def test_document_operation_summary(fixtures_dir: Path, tmp_path: Path):
    result = _process(
        fixtures_dir / "formal_invoice_revised.pdf", fixtures_dir, tmp_path
    )
    summary = result.records[0].audit_trail.document_operation_summary

    assert summary == {
        "CREATE": 0,
        "UPDATE": 1,
        "NO_CHANGE": 2,
        "PENDING_REVIEW": 0,
    }


def test_evidenced_update_preserves_other_fields(fixtures_dir: Path, tmp_path: Path):
    result = _process(
        fixtures_dir / "formal_invoice_revised.pdf", fixtures_dir, tmp_path
    )
    update = result.records[0]

    assert update.charge_details.charge_item == "Handling Charge"
    assert update.charge_details.currency == "USD"
    assert update.charge_details.payment_term == "PP"
    assert update.audit_trail.historical_line_id == "BILL-FIX-001-L1"
    assert update.audit_trail.match_rule == "STRICT_L1"

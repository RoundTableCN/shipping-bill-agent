import json
from pathlib import Path

import pytest

from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.candidates import collect_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.output.serializer import dumps

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "data" / "golden" / "expected"
EXISTING_BILLS = ROOT / "data" / "fixtures" / "existing_bills.json"

CASES = {
    "sample_prealert": ROOT / "data" / "fixtures" / "sample_prealert.eml",
    "sample_general_notice": ROOT / "data" / "samples" / "sample_general_notice.pdf",
    "sample_debit_note": ROOT / "data" / "samples" / "sample_debit_note.pdf",
    "sample_carrier_invoice": ROOT / "data" / "samples" / "sample_carrier_invoice.png",
    "formal_invoice": ROOT / "data" / "fixtures" / "formal_invoice.pdf",
    "formal_invoice_revised": ROOT / "data" / "fixtures" / "formal_invoice_revised.pdf",
    "formal_invoice_create": ROOT / "data" / "fixtures" / "formal_invoice_create.pdf",
    "statement": ROOT / "data" / "fixtures" / "statement.docx",
    "charges": ROOT / "data" / "fixtures" / "charges.xlsx",
}

STRICT_KEYS = {
    "operation",
    "document_info",
    "transaction_party",
    "charge_details",
    "financial_attributes",
    "audit_trail",
}


def _run(path: Path, tmp_path: Path) -> str:
    ctx = ParseContext(
        run_dir=tmp_path / "run", ocr_mode="mock", vision_fallback=False
    )
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    config = PipelineConfig(existing_bills=str(EXISTING_BILLS))
    result = process_bundle(bundle, candidates, config)
    return dumps(result.records, mode="full")


def _project(records: list[dict]) -> list[dict]:
    projected = []
    for record in records:
        audit = record["audit_trail"]
        projected.append(
            {
                "operation": record["operation"],
                "document_info": record["document_info"],
                "transaction_party": record["transaction_party"],
                "charge_details": record["charge_details"],
                "financial_attributes": record["financial_attributes"],
                "document_class": audit["document_class"],
                "billing_status": audit["billing_status"],
                "decision_status": audit["decision_status"],
                "matched_bill_id": audit["matched_bill_id"],
                "match_rule": audit["match_rule"],
                "changes": audit["changes"],
                "inherited_fields": audit["inherited_fields"],
                "amount_changed": audit["amount_changed"],
                "validation_passed": audit["validation"]["passed"],
                "validation_errors": audit["validation"]["errors"],
                "validation_warnings": audit["validation"]["warnings"],
            }
        )
    return projected


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_snapshot(name: str, tmp_path: Path):
    actual = json.loads(_run(CASES[name], tmp_path))
    expected = json.loads((EXPECTED / f"{name}.json").read_text(encoding="utf-8"))

    assert _project(actual) == _project(expected)


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_strict_shape(name: str, tmp_path: Path):
    ctx = ParseContext(
        run_dir=tmp_path / "run", ocr_mode="mock", vision_fallback=False
    )
    bundle = parse_file(CASES[name], ctx)
    candidates = collect_candidates(bundle)
    config = PipelineConfig(existing_bills=str(EXISTING_BILLS))
    result = process_bundle(bundle, candidates, config)

    data = json.loads(dumps(result.records, mode="strict"))
    for record in data:
        assert set(record.keys()) == STRICT_KEYS
        assert set(record["audit_trail"].keys()) == {"ai_reasoning"}

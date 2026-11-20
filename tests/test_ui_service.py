import json
from pathlib import Path

from shipping_agent.ui_service import (
    analyze_bytes,
    analyze_path,
    audit_payload,
    extraction_payload,
    records_payload,
    summary_rows,
)


def test_analyze_path_create_invoice(fixtures_dir: Path):
    analysis = analyze_path(
        fixtures_dir / "formal_invoice_create.pdf",
        existing_bills=fixtures_dir / "existing_bills.json",
        accounting_entity="IMPORTER BETA (SHANGHAI)",
        ocr_mode="local",
    )

    rows = summary_rows(analysis)
    assert len(rows) == 3
    assert all(row["operation"] == "CREATE" for row in rows)
    assert rows[0]["posting_type"] == "AP"

    full = json.loads(records_payload(analysis, "full"))
    strict = json.loads(records_payload(analysis, "strict"))
    audit = json.loads(audit_payload(analysis))
    assert len(full) == 3
    assert set(strict[0].keys()) == {
        "operation",
        "document_info",
        "transaction_party",
        "charge_details",
        "financial_attributes",
        "audit_trail",
    }
    assert set(strict[0]["audit_trail"].keys()) == {"ai_reasoning"}
    assert len(audit) == 3


def test_analyze_bytes_prealert(fixtures_dir: Path):
    data = (fixtures_dir / "sample_prealert.eml").read_bytes()
    analysis = analyze_bytes(
        data,
        "sample.eml",
        existing_bills=None,
        accounting_entity="IMPORTER BETA (SHANGHAI)",
        ocr_mode="mock",
    )

    rows = summary_rows(analysis)
    assert len(rows) == 1
    assert rows[0]["operation"] == "PENDING_REVIEW"
    assert rows[0]["charge_item"] == "H/C"

    details = extraction_payload(analysis)
    assert details["classification"]["document_type"] == "PRE-ALERT"
    assert details["charges"][0]["amount"] == 50.0

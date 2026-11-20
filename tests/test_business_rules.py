"""Regression tests for the four-sample business rules."""

from decimal import Decimal
from pathlib import Path

from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.candidates import collect_candidates
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file

ROOT = Path(__file__).resolve().parents[1]


def _process(path: Path, tmp_path: Path, *, entity: str | None = None):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    return process_bundle(
        bundle,
        candidates,
        PipelineConfig(
            existing_bills=str(ROOT / "data" / "fixtures" / "existing_bills.json"),
            accounting_entity=entity,
        ),
    )


def test_general_notice_preserves_raw_bl_and_payment_status(tmp_path: Path):
    result = _process(
        ROOT / "data" / "samples" / "sample_general_notice.pdf", tmp_path
    )
    record = result.records[0]
    audit = record.audit_trail

    assert record.operation == "PENDING_REVIEW"
    assert record.financial_attributes.posting_type is None
    assert audit.document_identity is not None
    assert audit.document_identity.bl_no.raw == "BL-DEMO-001"
    assert audit.document_identity.bl_no.normalized == "BL-DEMO-001"
    assert audit.status.payment_status == "UNPAID"
    assert audit.charge_values.mapping_status == "CANDIDATE"


def test_debit_note_keeps_same_name_rows_separate(tmp_path: Path):
    result = _process(
        ROOT / "data" / "samples" / "sample_debit_note.pdf", tmp_path
    )

    assert len(result.records) == 3
    assert [record.charge_details.amount for record in result.records] == [
        Decimal("65.00"),
        Decimal("1310.40"),
        Decimal("35.00"),
    ]
    handling = [
        record for record in result.records
        if record.charge_details.charge_item == "Handling Charge"
    ]
    assert len(handling) == 2
    assert len({record.audit_trail.line_id for record in handling}) == 2
    assert result.records[0].financial_attributes.posting_type is None
    assert result.records[1].audit_trail.charge_values.mapping_status == (
        "PENDING_CONFIRMATION"
    )


def test_prealert_currency_is_inferred_not_defaulted(tmp_path: Path):
    result = _process(ROOT / "data" / "fixtures" / "sample_prealert.eml", tmp_path)
    record = result.records[0]
    values = record.audit_trail.charge_values

    assert record.operation == "PENDING_REVIEW"
    assert record.financial_attributes.posting_type is None
    assert values.currency.raw == "$"
    assert values.currency.normalized == "USD"
    assert values.currency_source == "INFERRED_FROM_DOLLAR_SYMBOL"


def test_statement_is_candidate_ap_not_confirmed(tmp_path: Path):
    result = _process(ROOT / "data" / "fixtures" / "statement.docx", tmp_path)
    record = result.records[0]

    assert record.operation == "PENDING_REVIEW"
    assert record.financial_attributes.posting_type is None
    assert record.audit_trail.status.candidate_posting_type == "AP"
    assert record.audit_trail.status.accounting_status == "PENDING_CONFIRMATION"
    assert "E_DOC_STATEMENT_NOT_POSTABLE" in record.audit_trail.validation.errors

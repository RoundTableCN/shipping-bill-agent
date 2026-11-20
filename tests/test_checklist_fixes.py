"""Regression tests for the issue-fix checklist P0-P2."""

from __future__ import annotations

from pathlib import Path

from shipping_agent.business.document_class import (
    classify_document_rules,
    is_valid_container_no,
)
from shipping_agent.business.pipeline import PipelineConfig, process_bundle
from shipping_agent.candidates import collect_candidates
from shipping_agent.extract.rules import RuleBasedExtractor
from shipping_agent.io.context import ParseContext
from shipping_agent.io.dispatcher import parse_file
from shipping_agent.io.image_parser import _vision_quantity
from shipping_agent.io.text_normalize import parse_date_info
from shipping_agent.models.bundle import (
    DocumentBundle,
    SourceRef,
    TableBlock,
    TableCell,
    TextBlock,
)
from shipping_agent.vision_extractor import VisionCharge


def _bundle(text: str) -> DocumentBundle:
    lines = text.splitlines()
    return DocumentBundle(
        bundle_id="checklist-text",
        source=SourceRef(
            file_id="checklist-text",
            file_name="checklist.txt",
            media_type="text/plain",
        ),
        media_type="text/plain",
        raw_text=text,
        norm_text=text,
        blocks=[
            TextBlock(
                block_id=f"L{index}",
                kind="line",
                text=line,
                order=index,
            )
            for index, line in enumerate(lines)
            if line.strip()
        ],
    )


def _process(path: Path, fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(path, ctx)
    candidates = collect_candidates(bundle)
    return process_bundle(
        bundle,
        candidates,
        PipelineConfig(
            existing_bills=str(fixtures_dir / "existing_bills.json"),
            accounting_entity="IMPORTER BETA (SHANGHAI)",
        ),
    )


def test_pc_is_not_document_payment_term(samples_dir: Path, fixtures_dir: Path, tmp_path: Path):
    result = _process(samples_dir / "sample_debit_note.pdf", fixtures_dir, tmp_path)

    assert [record.charge_details.payment_term for record in result.records] == [
        "COD",
        "COD",
        "COD",
    ]
    for record in result.records:
        values = record.audit_trail.charge_values
        assert values.prepaid_collect_raw == "C"
        assert values.prepaid_collect_normalized is None
        assert values.prepaid_collect_status == "PENDING_CONFIRMATION"


def test_invoice_number_not_container_and_date_ambiguity():
    text = (
        "INVOICE NO: INV-DEMO-001\n"
        "INVOICE DATE: 10/03/2025\n"
        "CONTAINER NO: FIXU7654321\n"
        "BOOKING NO: CGTSE260888888\n"
        "B/L NO: CGTSE260888888\n"
        "PAYMENT DUE INSTRUCTION: PAY IMMEDIATELY\n"
        "WHARFAGE USD 21.90\n"
        "TOTAL USD 21.90\n"
    )
    classification = classify_document_rules(_bundle(text))

    assert classification.reference_no == "INV-DEMO-001"
    assert classification.invoice_number == "INV-DEMO-001"
    assert classification.container_nos == ["FIXU7654321"]
    assert classification.booking_no == "CGTSE260888888"
    assert classification.bl_no == "CGTSE260888888"
    assert classification.document_date is None
    assert classification.document_date_raw == "10/03/2025"
    assert classification.document_date_status == "AMBIGUOUS"
    assert classification.payment_due_instruction == "PAY IMMEDIATELY"

    iso, status, candidates = parse_date_info("10/03/2025")
    assert iso is None
    assert status == "AMBIGUOUS"
    assert candidates == ["2025-10-03", "2025-03-10"]


def test_vision_roe_is_not_quantity():
    bad = VisionCharge(
        name="WHARFAGE",
        quantity="1.0",
        unit_price="2.85",
        roe="1.0",
        amount="21.90",
    )
    good = VisionCharge(
        name="WHARFAGE",
        quantity="2.0",
        unit_price="2.85",
        roe="1.0",
        amount="5.70",
    )

    assert _vision_quantity(bad) is None
    assert str(_vision_quantity(good)) == "2.0"


def test_base_c_is_not_prepaid_collect():
    header = [
        "DESCRIPTION", "QTY", "BASE", "RATE", "ROE", "AMOUNT", "CURRENCY", "P/C",
    ]
    row = ["WHARFAGE", "", "C", "2.85", "1.0", "21.9", "USD", ""]
    cells = [
        TableCell(row=0, col=index, text=text)
        for index, text in enumerate(header)
    ] + [
        TableCell(row=1, col=index, text=text)
        for index, text in enumerate(row)
        if text
    ]
    bundle = DocumentBundle(
        bundle_id="table-base",
        source=SourceRef(
            file_id="table-base",
            file_name="table.png",
            media_type="image/png",
        ),
        media_type="image/png",
        tables=[
            TableBlock(
                table_id="t1",
                cells=cells,
                header_row_count=1,
            )
        ],
    )

    candidates = collect_candidates(bundle)

    assert len(candidates) == 1
    assert candidates[0].base_raw == "C"
    assert candidates[0].qty_raw is None
    assert candidates[0].prepaid_collect_raw is None
    assert candidates[0].amount_raw == "21.9"


def test_container_check_digit_rejects_invoice_numbers():
    assert is_valid_container_no("MSCU1234564")
    assert is_valid_container_no("TGHU1234567")
    assert is_valid_container_no("FIXU7654321")
    assert not is_valid_container_no("INV-DEMO-001")


def test_prealert_subject_container_codes_and_hold(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "sample_prealert.eml", ctx)
    classification = classify_document_rules(bundle)

    assert classification.container_nos == ["TGHU1234567"]
    assert classification.container_sources["TGHU1234567"] == "email_subject"
    assert classification.release_type == "TELEX_RELEASE"
    assert classification.release_status == "HOLD"
    assert classification.shipment_operation_status == "HOLD"
    assert any(item.kind == "HOLD" for item in classification.business_instructions)

    result = RuleBasedExtractor().extract(bundle, collect_candidates(bundle))
    charge = result.charges[0]
    assert charge.payer_code_raw == "SHA"
    assert charge.payee_code_raw == "TAR"
    assert charge.party_mapping_status == "PENDING_CONFIRMATION"
    assert charge.charge_item == "H/C"
    assert charge.candidate_standard_charge_name == "Handling Charge"
    assert charge.mapping_status == "CANDIDATE"


def test_oca17_and_unconfirmed_mapping_not_final(samples_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(samples_dir / "sample_general_notice.pdf", ctx)
    result = RuleBasedExtractor().extract(bundle, collect_candidates(bundle))
    charge = result.charges[0]

    assert charge.charge_code_raw == "OCA17"
    assert charge.charge_name_raw == "On Carriage Additional - US Em"
    assert charge.charge_item == "On Carriage Additional - US Em"
    assert charge.candidate_standard_charge_name == "On Carriage Additional"
    assert charge.mapping_status == "CANDIDATE"


def test_bl_is_not_reused_as_document_reference(samples_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(samples_dir / "sample_general_notice.pdf", ctx)
    result = classify_document_rules(bundle)

    assert result.reference_no is None
    assert result.bl_no == "BL-DEMO-001"
    assert result.bl_no_raw == "BL-DEMO-001"


def test_payment_received_has_party_scope(samples_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(samples_dir / "sample_general_notice.pdf", ctx)
    result = classify_document_rules(bundle)

    assert result.payment_received is False
    assert result.payment_status == "UNPAID"
    assert result.payment_status_scope in {
        "CUSTOMER_RECEIVABLE",
        "UNKNOWN",
    }


def test_document_summary_is_not_repeated_per_charge(
    samples_dir: Path, fixtures_dir: Path, tmp_path: Path
):
    result = _process(samples_dir / "sample_debit_note.pdf", fixtures_dir, tmp_path)

    assert result.records[0].audit_trail.document_operation_summary == {
        "CREATE": 0,
        "UPDATE": 0,
        "NO_CHANGE": 0,
        "PENDING_REVIEW": 3,
    }
    assert all(
        record.audit_trail.document_operation_summary is None
        for record in result.records[1:]
    )
    assert all(
        record.audit_trail.document_totals is None
        for record in result.records[1:]
    )


def test_no_history_requires_review(fixtures_dir: Path, tmp_path: Path):
    ctx = ParseContext(run_dir=tmp_path / "run", ocr_mode="local")
    bundle = parse_file(fixtures_dir / "formal_invoice.pdf", ctx)
    result = process_bundle(
        bundle,
        collect_candidates(bundle),
        PipelineConfig(
            existing_bills=None,
            accounting_entity="IMPORTER BETA (SHANGHAI)",
        ),
    )

    assert result.records
    assert all(record.operation == "PENDING_REVIEW" for record in result.records)
    assert all(record.audit_trail.history_checked is False for record in result.records)
    assert any(
        "W_HISTORY_NOT_CHECKED" in error
        for record in result.records
        for error in record.audit_trail.validation.warnings
    )


def test_pay_immediately_is_instruction_not_payment_term():
    text = (
        "INVOICE NO: INV-DEMO-001\n"
        "INVOICE DATE: 2025-10-04\n"
        "PAY IMMEDIATELY\n"
        "WHARFAGE USD 21.90\n"
        "TOTAL USD 21.90\n"
    )
    bundle = _bundle(text)
    result = RuleBasedExtractor().extract(bundle, collect_candidates(bundle))

    assert result.classification.payment_due_instruction == "PAY IMMEDIATELY"
    assert result.charges[0].payment_term is None
    assert result.charges[0].payment_due_instruction == "PAY IMMEDIATELY"


def test_mapping_error_is_charge_specific(samples_dir: Path, fixtures_dir: Path, tmp_path: Path):
    result = _process(samples_dir / "sample_debit_note.pdf", fixtures_dir, tmp_path)

    assert all(
        not any(
            error.startswith("E_MAPPING_NOT_CONFIRMED")
            for error in record.audit_trail.validation.errors
        )
        for record in (result.records[0], result.records[2])
    )
    assert any(
        error.startswith("E_MAPPING_NOT_CONFIRMED")
        for error in result.records[1].audit_trail.validation.errors
    )
